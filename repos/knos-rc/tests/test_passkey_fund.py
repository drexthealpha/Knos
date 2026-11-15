"""knos-passkey's Fund (1.1) inside LiteSVM, beside the test build of knos_pay: a funder with only a passkey funds a
work order. The wallet (the program's account `Open` creates) holds test USDC; a relayer pays every fee and the rent
of the order; the passkey's assertion, verified by LiteSVM's own secp256r1 precompile, is the only authority.

The authenticator is the stand-in of tests/test_passkey_chain.py (`Passkey`). The last test runs web/passkey_fund.js
in node against a stand-in for navigator.credentials and for the RPC, and sends what it returns to the chain here.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

pytest.importorskip("solders.litesvm")

from cryptography.hazmat.primitives import serialization  # noqa: E402
from solders.instruction import AccountMeta, Instruction  # noqa: E402
from solders.keypair import Keypair  # noqa: E402
from solders.pubkey import Pubkey  # noqa: E402

from _order import DAY, REPO, TERMS, TH, USDC, OrderChain, issue  # noqa: E402
from _pay2 import WF_REPO, WF_SHA  # noqa: E402
from test_passkey_chain import BUILD, ORIGIN, RP_ID, Passkey  # noqa: E402

from knos.settle.v2 import passkey as pk  # noqa: E402
from knos.settle.v2 import passkey_fund as pf  # noqa: E402
from knos.settle.v2 import pay  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SRC = (ROOT / "programs-v2" / "knos_passkey" / "src" / "lib.rs").read_text(encoding="utf-8")
E = {name: int(code) for name, code in re.findall(r"pub const (E_\w+): u32 = (\d+);", SRC)}


class World(OrderChain):
    """The chain of tests/_order.py with knos_passkey beside knos_pay: a passkey whose wallet is open and holds
    1,000.00 test USDC and no SOL beyond its own rent, and a relayer (the chain's payer) who holds no token of it."""
    def __init__(self):
        super().__init__()
        self.svm.add_program_from_file(pk.PASSKEY_ID, str(BUILD))
        self.p = Passkey(11)
        assert self.send([pk.open_ix(self.payer.pubkey(), self.p.key)]), self.err
        self.source = self.token_account(self.p.wallet, self.usdc)
        self.mint_to(self.usdc, self.source, 1_000 * USDC)
        self.rent = (self.svm.minimum_balance_for_rent_exemption(pf.ORDER_LEN), self.svm.minimum_balance_for_rent_exemption(165))

    def slot(self) -> int:
        return int(self.svm.get_clock().slot)

    def nonce(self, p: Passkey | None = None) -> int:
        w = pk.read_wallet(self.data((p or self.p).wallet))
        return w.nonce if w else 0

    def data_of(self, n: int, amount: int = 20 * USDC, terms: bytes = TERMS, p: Passkey | None = None, **kw) -> bytes:
        """The instruction data of the FundOrderWallet the wallet is to sign: knos_pay's own client builds it."""
        w = (p or self.p).wallet
        return bytes(pay.fund_order_wallet_ix(w, pay.ata(w, self.usdc), self.usdc, REPO, n, amount, WF_REPO, WF_SHA, terms, **kw).data)

    def ixs(self, data: bytes, *, expiry: int | None = None, nonce: int | None = None, signed: dict | None = None, signer: Passkey | None = None,
            assertion=None, mint: Pubkey | None = None, rent: bool = True, **kw) -> list[Instruction]:
        """[the rent of the order and its token account, the precompile, Fund]. signed: what the passkey signs instead
        (mint, data, expiry_slot, nonce), when it differs from what the instruction says."""
        mint = mint or self.usdc
        expiry = self.slot() + 150 if expiry is None else expiry
        nonce = self.nonce() + 1 if nonce is None else nonce
        what = dict(mint=mint, data=data, expiry_slot=expiry, nonce=nonce) | (signed or {})
        auth, cdj, sig = assertion or (signer or self.p).get(pf.fund_challenge(**what))
        order = pf.order_of(self.p.wallet, data)
        ov = pay.ov_pda(order)
        pre = pf.rent_ixs(self.payer.pubkey(), order, ov, *self.rent, self.lamports(order), self.lamports(ov)) if rent else []
        return [*pre, *pf.fund_ixs(self.p.key, mint, data, expiry, nonce, auth, cdj, sig, **kw)]

    def refused(self, ixs) -> int | str:
        """The custom error code of a transaction that must not go through, and nothing may have moved."""
        before = (self.balance(self.source), self.nonce(), self.lamports(self.p.wallet))
        assert not self.send(ixs), "the transaction went through"
        assert (self.balance(self.source), self.nonce(), self.lamports(self.p.wallet)) == before
        m = re.search(r"Custom\((\d+)\)", self.err or "")
        return int(m.group(1)) if m else self.err


@pytest.fixture()
def w() -> World:
    return World()


def test_a_passkey_funds_an_order_and_the_same_assertion_cannot_fund_again(w: World):
    n, relay, wallet_sol = issue(), w.lamports(w.payer.pubkey()), w.lamports(w.p.wallet)
    data = w.data_of(n)
    ixs = w.ixs(data)
    assert w.send(ixs), w.err
    order = pf.order_of(w.p.wallet, data)
    o = w.order(order)
    # the order is the one the passkey signed for, the wallet is its funder, and it refunds to the wallet and nowhere else
    assert (o.amount, o.repo_id, o.issue, o.terms, o.source, o.refund_to, o.mint) == (20 * USDC, REPO, n, TH, w.p.wallet, w.p.wallet, w.usdc)
    # the fee is knos_pay's: read from the order it wrote, never computed by the passkey program or by this test
    assert o.fee > 0 and w.held(order) == 20 * USDC + o.fee and w.balance(w.source) == 1_000 * USDC - 20 * USDC - o.fee
    assert w.said("knosp:") == [f"knosp:funded wallet={w.p.wallet} order={order} mint={w.usdc} amount={20 * USDC} fee={o.fee} nonce=1"]
    assert w.nonce() == 1
    # the funder spent no SOL: the relayer paid the fee and the rent of both accounts
    assert w.lamports(w.p.wallet) == wallet_sol and relay - w.lamports(w.payer.pubkey()) >= sum(w.rent)
    assert w.size <= 1232, w.size                                       # one transaction a cluster takes
    # the same assertion again: with the same bytes, as the next nonce, and for a second order of the same issue
    assert w.refused(ixs[-2:]) == E["E_NONCE"]
    verify, fund = ixs[-2:]
    again = Instruction(fund.program_id, bytes(fund.data)[:9] + (2).to_bytes(8, "little") + bytes(fund.data)[17:], fund.accounts)
    assert w.refused([verify, again]) == E["E_CHALLENGE"]
    # a new assertion funds the next order of the same issue (seq 1), as nonce 2
    assert w.send(w.ixs(w.data_of(n, seq=1))), w.err
    assert w.nonce() == 2 and w.balance(w.source) == 1_000 * USDC - 2 * (20 * USDC + o.fee)
    # and after the deadline anyone sends the money of an order nobody delivered back to the wallet's token account
    w.warp(14 * DAY + 1)
    assert w.send([pay.refund_order_ix(w.payer.pubkey(), order, o)]), w.err
    assert w.balance(w.source) == 1_000 * USDC - (20 * USDC + o.fee) and w.order(order) is None


def test_an_assertion_for_other_terms_another_amount_or_another_order_is_refused(w: World):
    n = issue()
    signed = w.data_of(n)
    expiry = w.slot() + 150
    assertion = w.p.get(pf.fund_challenge(w.usdc, signed, expiry, 1))
    other_terms = pay.terms_json({"accept": "", "checks": [{"app": 15368, "name": "anything"}], "mode": "merge", "v": 2})
    other_mint = w.new_mint()
    w.mint_to(other_mint, w.token_account(w.p.wallet, other_mint), 1_000 * USDC)
    sent = {"amount": w.data_of(n, 200 * USDC), "terms": w.data_of(n, terms=other_terms), "issue": w.data_of(n + 1), "seq": w.data_of(n, seq=1),
            "work time": w.data_of(n, work_s=DAY), "options": w.data_of(n, options=pay.opts(flags=pay.F_NEUTRAL)),
            "workflow commit": signed[:118] + b"b" * 40 + signed[158:]}
    for name, data in sent.items():
        assert data != signed and w.refused(w.ixs(data, expiry=expiry, assertion=assertion)) == E["E_CHALLENGE"], name
    assert w.refused(w.ixs(signed, expiry=expiry, assertion=assertion, mint=other_mint)) == E["E_CHALLENGE"]      # the same terms, paid in another mint
    assert w.refused(w.ixs(signed, expiry=expiry + 1, assertion=assertion)) == E["E_CHALLENGE"]                   # a later expiry than was signed
    # a withdrawal's assertion funds nothing, and a funding's withdraws nothing
    to = w.token_account(Keypair().pubkey(), w.usdc)
    assert w.refused(w.ixs(signed, expiry=expiry, assertion=w.p.get(pk.challenge(w.p.wallet, w.usdc, to, 20 * USDC, 1)))) == E["E_CHALLENGE"]
    assert w.refused(pk.withdraw_ixs(w.p.key, w.usdc, to, 20 * USDC, 1, *assertion)) == E["E_CHALLENGE"]
    # a relay cannot repair the client data: the signature is over its hash
    auth, cdj, sig = assertion
    forged = cdj.replace(pk.b64url(pf.fund_challenge(w.usdc, signed, expiry, 1)).encode(), pk.b64url(pf.fund_challenge(w.usdc, sent["amount"], expiry, 1)).encode())
    message = auth + hashlib.sha256(cdj).digest()
    assert w.refused([pk.secp256r1_ix(w.p.key, sig, message), pf.fund_ix(w.p.key, w.usdc, sent["amount"], expiry, 1, forged)]) == E["E_MESSAGE"]
    assert w.order(pf.order_of(w.p.wallet, sent["amount"])) is None
    assert w.send(w.ixs(signed, expiry=expiry, assertion=assertion)), w.err                                       # untouched, it funds what it says
    assert w.order(pf.order_of(w.p.wallet, signed)).amount == 20 * USDC


def test_after_the_expiry_slot_it_is_refused(w: World):
    data, expiry = w.data_of(issue()), w.slot() + 40
    assertion = w.p.get(pf.fund_challenge(w.usdc, data, expiry, 1))
    w.svm.warp_to_slot(expiry + 1)
    assert w.refused(w.ixs(data, expiry=expiry, assertion=assertion)) == E["E_EXPIRED"]
    assert w.refused(w.ixs(data, expiry=0)) == E["E_EXPIRED"]
    w.svm.warp_to_slot(expiry)                                           # the last slot it is good in
    assert w.send(w.ixs(data, expiry=expiry, assertion=assertion)), w.err
    assert w.nonce() == 1


def test_a_wrong_passkey_is_refused(w: World):
    other, data, expiry = Passkey(12), w.data_of(issue()), w.slot() + 150
    assert w.send([pk.open_ix(w.payer.pubkey(), other.key)]), w.err
    # the other passkey signs exactly this funding; the precompile verifies it (it is a good signature of that key)
    auth, cdj, sig = other.get(pf.fund_challenge(w.usdc, data, expiry, 1))
    message = auth + hashlib.sha256(cdj).digest()
    fund = pf.fund_ix(w.p.key, w.usdc, data, expiry, 1, cdj)
    assert w.refused([pk.secp256r1_ix(other.key, sig, message), fund]) == E["E_SIGNER"]
    # the same signature under this wallet's key does not verify at all: the precompile stops the transaction
    assert w.refused([pk.secp256r1_ix(w.p.key, sig, message), fund]) == 2 and "(1, Tagged(InstructionErrorCustom(2))" in w.err   # instruction 1: the precompile
    # the other passkey's own funding, pointed at this wallet's money
    theirs = w.data_of(issue(), p=other)
    auth, cdj, sig = other.get(pf.fund_challenge(w.usdc, theirs, expiry, 1))
    mixed = pf.fund_ixs(other.key, w.usdc, theirs, expiry, 1, auth, cdj, sig, from_token=w.source)
    assert w.refused(mixed) == E["E_FROM"]
    # no assertion at all
    assert w.refused([fund]) == E["E_PRECOMPILE"]


def test_the_wallet_signs_for_fund_order_wallet_of_knos_pay_and_nothing_else(w: World):
    data, expiry = w.data_of(issue()), w.slot() + 150
    order = pf.order_of(w.p.wallet, data)

    def fund(inner: bytes, swap: dict[int, Pubkey] | None = None) -> list[Instruction]:
        auth, cdj, sig = w.p.get(pf.fund_challenge(w.usdc, inner, expiry, 1))
        body = expiry.to_bytes(8, "little") + (1).to_bytes(8, "little") + len(cdj).to_bytes(2, "little") + cdj + inner
        acc = list(pf.fund_ix(w.p.key, w.usdc, data, expiry, 1, cdj).accounts)
        for at, key in (swap or {}).items():
            acc[at] = AccountMeta(key, False, acc[at].is_writable)
        return [pk.secp256r1_ix(w.p.key, sig, auth + hashlib.sha256(cdj).digest()), Instruction(pk.PASSKEY_ID, b"\x02" + body, acc)]

    # another instruction of knos_pay (TopUp is 23), signed for by the passkey itself; a FundOrderWallet cut short
    assert w.refused(fund(bytes([23]) + data[1:])) == E["E_FUND"]
    assert w.refused(fund(data[:157])) == E["E_FUND"]
    # another program in knos_pay's place, the passkey having signed these very bytes
    assert w.refused(fund(data, {9: pay.TOKEN})) == E["E_FUND"]
    assert w.refused(fund(data, {10: w.payer.pubkey()})) == E["E_ACCOUNTS"]          # an account someone filled, not the instructions sysvar
    # without the relayer's rent the wallet would have to pay it, and the system program takes nothing from a wallet
    assert isinstance(w.refused(w.ixs(data, rent=False)), str) and w.order(order) is None
    assert f"pub const KNOS_PAY: Pubkey = pubkey!(\"{pay.PAY_ID}\");" in SRC and "pub const FUND_ORDER_WALLET: u8 = 15;" in SRC
    assert set(pk.ERRORS) | set(pf.ERRORS) == set(E.values()) and not set(pk.ERRORS) & set(pf.ERRORS)
    assert w.send(w.ixs(data, expiry=expiry)), w.err


# -- the intent: what the browser returns is what a relayer sends -------------------------------------------------------
def test_an_intent_is_read_back_as_it_was_written(w: World):
    data, expiry = w.data_of(issue()), w.slot() + 150
    auth, cdj, sig = w.p.get(pf.fund_challenge(w.usdc, data, expiry, 1))
    i = pf.Intent(w.p.key, w.usdc, pay.TOKEN, data, expiry, 1, auth, cdj, pk.raw_signature(sig))
    line = pf.intent_comment(i)
    assert re.fullmatch(r"/knos passkey-fund [A-Za-z0-9_-]+", line)
    assert pf.read_intent(line) == pf.read_intent(pf.intent(i)) == pf.read_intent(f"please\n{line}\n") == i
    assert (i.wallet, i.order, i.amount) == (w.p.wallet, pf.order_of(w.p.wallet, data), 20 * USDC)
    for change in ({"amount": 1}, {"order": str(w.p.wallet)}, {"wallet": str(w.usdc)}, {"v": 2}, {"pay": str(pk.PASSKEY_ID)}, {"tokenProgram": str(w.usdc)}):
        with pytest.raises(ValueError):
            pf.read_intent(pf.intent(i) | change)
    with pytest.raises(ValueError):
        pf.read_intent("/knos passkey-fund abc")


RUN = """
import { createPrivateKey, sign } from "node:crypto";
import { readFileSync } from "node:fs";
import { passkeyFundIntent, intentComment } from "./passkey_fund.js";
const given = JSON.parse(readFileSync(process.argv[2], "utf8"));
const key = createPrivateKey(given.pem), b64url = (b) => Buffer.from(b).toString("base64url");
const asked = [];
globalThis.fetch = async (url, init) => {                       // the RPC: the wallet's account, as the chain holds it
  const call = JSON.parse(init.body);
  asked.push([call.method, call.params[0]]);
  return { ok: true, json: async () => ({ result: { value: { owner: given.ids.knos_passkey, lamports: 1, data: [given.account, "base64"] } } }) };
};
const credentials = { get: async ({ publicKey }) => {            // an authenticator: signs authenticatorData || sha256(clientDataJSON)
  const clientDataJSON = Buffer.from(JSON.stringify({ type: "webauthn.get", challenge: b64url(publicKey.challenge), origin: given.origin, crossOrigin: false }));
  const authenticatorData = Buffer.from(given.authenticatorData, "hex");
  const hash = await crypto.subtle.digest("SHA-256", clientDataJSON);
  return { response: { authenticatorData, clientDataJSON, signature: sign("sha256", Buffer.concat([authenticatorData, Buffer.from(hash)]), key) } };
} };
const intent = await passkeyFundIntent({ terms: given.terms, amount: given.amount, expirySlot: given.expirySlot, wallet: { key: given.key, credentialId: null } },
  { rpc: "http://rpc.invalid", ids: given.ids, rpId: given.rpId, credentials });
console.log(JSON.stringify({ intent, comment: intentComment(intent), asked }));
"""


def test_what_the_browser_helper_returns_funds_the_order_on_chain(w: World, tmp_path: Path):
    node = shutil.which("node")
    if not node:
        pytest.skip("needs node")
    # the site as scripts/build_site.sh lays it out: settle.js and passkey.js beside the page's own files
    for src, name in (("web/passkey_fund.js", "passkey_fund.js"), ("sdk/settle/index.js", "settle.js"), ("sdk/settle/passkey.js", "passkey.js")):
        shutil.copy(ROOT / src, tmp_path / name)
    assert 'cp -r web/. "$out/"' in (ROOT / "scripts" / "build_site.sh").read_text(encoding="utf-8")
    (tmp_path / "run.mjs").write_text(RUN, encoding="utf-8")
    assert w.send(w.ixs(w.data_of(issue()))), w.err                      # the wallet's nonce is 1 already: the helper must read it
    n, terms = issue(), {"accept": "", "checks": [{"app": 15368, "name": "test"}], "mode": "merge", "v": 2}
    assert pay.terms_json(terms) == TERMS
    expiry = w.slot() + 150
    pem = w.p.sk.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
    given = {"pem": pem, "ids": json.loads((ROOT / "programs-v2" / "program_ids.json").read_text()), "origin": ORIGIN, "rpId": RP_ID,
             "account": base64.b64encode(w.data(w.p.wallet)).decode(), "authenticatorData": (hashlib.sha256(RP_ID.encode()).digest() + bytes([5, 0, 0, 0, 9])).hex(),
             "terms": {"repoId": REPO, "issue": n, "wfRepo": WF_REPO, "wfSha": WF_SHA, "terms": terms, "mint": str(w.usdc)},
             "amount": 35 * USDC, "expirySlot": expiry, "key": w.p.key.hex()}
    (tmp_path / "given.json").write_text(json.dumps(given), encoding="utf-8")
    r = subprocess.run([node, "run.mjs", "given.json"], cwd=tmp_path, capture_output=True, text=True, timeout=120, check=False)
    assert r.returncode == 0, r.stdout + r.stderr
    out = json.loads(r.stdout)
    assert out["asked"] == [["getAccountInfo", str(w.p.wallet)]]
    assert re.fullmatch(r"/knos passkey-fund [A-Za-z0-9_-]+", out["comment"])
    i = pf.read_intent(out["comment"])                                   # a relayer reads the line, and needs nothing else
    assert i == pf.read_intent(out["intent"])
    data = w.data_of(n, 35 * USDC)
    assert (i.key, i.mint, i.data, i.expiry_slot, i.nonce, i.order, i.amount) == (w.p.key, w.usdc, data, expiry, 2, pf.order_of(w.p.wallet, data), 35 * USDC)
    assert i.client_data_json == json.dumps({"type": "webauthn.get", "challenge": pk.b64url(pf.fund_challenge(w.usdc, data, expiry, 2)), "origin": ORIGIN,
                                             "crossOrigin": False}, separators=(",", ":")).encode()
    ov = pay.ov_pda(i.order)
    assert w.send([*pf.rent_ixs(w.payer.pubkey(), i.order, ov, *w.rent), *i.ixs()]), w.err
    o = w.order(i.order)
    assert (o.amount, o.source, o.terms) == (35 * USDC, w.p.wallet, TH) and w.held(i.order) == 35 * USDC + o.fee and w.nonce() == 2
    assert w.refused(i.ixs()) == E["E_NONCE"]
