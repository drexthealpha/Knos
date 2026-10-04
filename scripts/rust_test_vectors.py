#!/usr/bin/env python3
"""Writes programs-v2/testdata/*.json: what the Rust handler tests (programs-v2/handlers/tests/knos_*.rs) replay.

Each file is one scenario, driven here through the Python test harnesses (tests/_oidc2.py, _order.py, _meter.py,
test_passkey_chain.py) with every call that reaches LiteSVM written down in order: the programs loaded, the airdrops,
the accounts and the clock set by hand, and every transaction as the signed bytes a relay would send, with what the
program answered (accepted, or the instruction and custom error that refused it). `check` steps hold the token
balances, lamports and account data read here at that point. The Rust tests send the same bytes to the same test
binaries in the litesvm crate and assert the same answers and the same state, and their own literal numbers besides.

Deterministic: wallets come from a counter, tokens are signed by the seed-derived RSA key the `testkeys` builds trust
(tests/_settle.py) and the passkey signs with RFC 6979 nonces, so two runs write the same bytes.

    python scripts/rust_test_vectors.py            # write the files
    python scripts/rust_test_vectors.py --check    # fail if a committed file differs from what this would write

Run it again after any change to a program's accounts, instruction data or errors (it needs the test binaries in
tests/fixtures: bash scripts/build_programs_v2.sh all).
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests")]
OUT = ROOT / "programs-v2" / "testdata"

from solders.keypair import Keypair as _Keypair  # noqa: E402
from solders.litesvm import LiteSVM as _LiteSVM  # noqa: E402
from solders.pubkey import Pubkey  # noqa: E402

import _meter  # noqa: E402
import _oidc2  # noqa: E402
import _order  # noqa: E402
import _pay2  # noqa: E402
import _settle  # noqa: E402
import test_passkey_chain as _pk  # noqa: E402

from knos.settle.v2 import meter, oidc, pay  # noqa: E402
from knos.settle.v2 import passkey as pk  # noqa: E402

USDC, DAY = 1_000_000, 86_400
NOW: "Recorder | None" = None         # the scenario being written


def _hex(key) -> str:
    return bytes(key).hex()


class Recorder:
    """One scenario's steps. `names` are the addresses the Rust test reads by name."""
    def __init__(self, name: str):
        self.name, self.steps, self.names, self.programs, self.n, self.next_label = name, [], {}, [], 0, None

    def keypair(self) -> _Keypair:
        self.n += 1
        return _Keypair.from_seed(hashlib.sha256(f"knos rust vectors {self.name} {self.n}".encode()).digest())

    def label(self, label: str) -> None:
        """Names the next transaction: the Rust test runs up to it and asserts on what it left."""
        self.next_label = label

    def check(self, svm, label: str, tokens=(), data=(), lamports=()) -> None:
        """What the named token accounts hold, what the named accounts contain and weigh, as read here, now."""
        def acc(name):
            a = svm.get_account(self.names_key(name))
            return a if a is not None and a.lamports > 0 else None
        got = {n: acc(n) for n in {*tokens, *data, *lamports}}
        self.steps.append({"op": "check", "label": label,
                           "tokens": {n: int.from_bytes(bytes(got[n].data)[64:72], "little") if got[n] else 0 for n in tokens},
                           "data": {n: bytes(got[n].data).hex() if got[n] else None for n in data},
                           "lamports": {n: got[n].lamports if got[n] else 0 for n in lamports}})

    def name_it(self, **names) -> None:
        self.names.update({k: _hex(v) for k, v in names.items()})

    def names_key(self, name: str) -> Pubkey:
        return Pubkey.from_bytes(bytes.fromhex(self.names[name]))

    def doc(self) -> str:
        return json.dumps({"scenario": self.name, "programs": self.programs, "names": self.names, "steps": self.steps}, indent=1, sort_keys=True) + "\n"


class Svm:
    """LiteSVM, with every call that changes the chain written to the scenario's steps."""
    def __init__(self):
        self._svm, self._rec = _LiteSVM(), NOW

    def __getattr__(self, name):
        return getattr(self._svm, name)

    def add_program_from_file(self, program_id, path):
        self._rec.programs.append({"id": _hex(program_id), "file": Path(path).name})
        return self._svm.add_program_from_file(program_id, path)

    def airdrop(self, to, lamports):
        self._rec.steps.append({"op": "airdrop", "to": _hex(to), "lamports": lamports})
        return self._svm.airdrop(to, lamports)

    def set_account(self, address, account):
        self._rec.steps.append({"op": "account", "at": _hex(address), "lamports": account.lamports, "data": bytes(account.data).hex(),
                                "owner": _hex(account.owner), "executable": bool(account.executable)})
        return self._svm.set_account(address, account)

    def set_clock(self, clock):
        self._rec.steps.append({"op": "clock", "slot": clock.slot, "epoch": clock.epoch, "epoch_start": clock.epoch_start_timestamp,
                                "leader_epoch": clock.leader_schedule_epoch, "unix": clock.unix_timestamp})
        return self._svm.set_clock(clock)

    def expire_blockhash(self):
        self._rec.steps.append({"op": "expire"})
        return self._svm.expire_blockhash()

    def with_sigverify(self, on):
        raise NotImplementedError("the vectors hold signed transactions only")

    def send_transaction(self, tx):
        r = self._svm.send_transaction(tx)
        ok = "Failed" not in type(r).__name__
        step = {"op": "tx", "tx": bytes(tx).hex(), "ok": ok}
        if not ok:
            err = str(r.err() if callable(getattr(r, "err", None)) else r.err)
            m = re.search(r"\((\d+), Tagged\(InstructionErrorCustom\((\d+)\)\)", err) or re.search(r"\((\d+),.*?Custom\((\d+)\)", err)
            assert m, f"{self._rec.name}: a refusal without a custom error: {err}"
            step.update(ix=int(m.group(1)), code=int(m.group(2)))
        if self._rec.next_label:
            step["label"], self._rec.next_label = self._rec.next_label, None
        self._rec.steps.append(step)
        return r


class _Keys:
    """Stands in for solders' Keypair in the harnesses: Keypair() is the scenario's next wallet, not a random one."""
    def __call__(self):
        return NOW.keypair()

    def __getattr__(self, name):
        return getattr(_Keypair, name)


for module in (_settle, _oidc2, _pay2, _order, _meter, _pk):
    if hasattr(module, "LiteSVM"):
        module.LiteSVM = Svm
    if hasattr(module, "Keypair"):
        module.Keypair = _Keys()


def scenario(name: str) -> Recorder:
    global NOW
    NOW = Recorder(name)
    return NOW


# == knos_oidc ===========================================================================================================
def oidc_verify() -> Recorder:
    """A genesis key is registered; a token GitHub signed is written and verified in two transactions; the same token
    with one bit of its signature flipped is refused by the second."""
    r = scenario("oidc_verify")
    c = _oidc2.Chain2()
    n = _settle.modulus(_settle.signing_key())
    r.label("register_key")
    assert c.send([oidc.register_key_ix(c.payer.pubkey(), oidc.GITHUB, n)]), c.err
    r.label("key_params")
    assert c.send([oidc.key_params_ix(c.payer.pubkey(), oidc.GITHUB, n)]), c.err
    r.name_it(key=oidc.key_pda(oidc.GITHUB, n))
    r.check(c.svm, "key", data=["key"])

    def run(jwt: str, tag: str) -> bool:
        tid = c.write(jwt)
        r.name_it(**{tag: oidc.token_pda(c.payer.pubkey(), tid)})
        r.check(c.svm, f"{tag}_written", data=[tag])
        plan = oidc.step_plan(n.bit_length())
        assert len(plan) == 2
        for i, sq in enumerate(plan, 1):
            r.label(f"{tag}_step{i}")
            if not c.send([oidc.step_ix(c.payer.pubkey(), tid, oidc.key_pda(oidc.GITHUB, n), sq)]):
                r.check(c.svm, f"{tag}_refused", data=[tag])
                return False
        r.check(c.svm, f"{tag}_verified", data=[tag])
        return True

    claims = _settle.github_claims(aud="knos:rust-handler-test", iat=c.now(), nbf=c.now() - 600, exp=c.now() + 300, jti="rust1")
    good = _settle.sign_jwt(_settle.signing_key(), claims)
    assert run(good, "token") and oidc.read_token(c.data(r.names_key("token"))).verified
    head, body, sig = _settle.sign_jwt(_settle.signing_key(), dict(claims, jti="rust2")).split(".")
    raw = bytearray(base64.urlsafe_b64decode(sig + "=" * (-len(sig) % 4)))
    raw[100] ^= 1
    assert not run(f"{head}.{body}.{_settle.b64(bytes(raw))}", "forged")
    return r


# == knos_pay ============================================================================================================
def _order_chain(r: Recorder) -> "_order.OrderChain":
    c = _order.OrderChain()
    r.name_it(fee=c.fee, funder_tok=c.funder_tok, balance_tok=pay.baltok_pda(c.bal), relayer_tok=c.tip)
    return c


def pay_order() -> Recorder:
    """A wallet funds an order (FundOrderWallet), a proof pays it (PayOrder), and the same token sent again is refused."""
    r = scenario("pay_order")
    c = _order_chain(r)
    wallet, dest = c.wallet(c.usdc)
    payees = [(_order.AUTHOR, 10_000, wallet.pubkey())]
    ix = c.fund_wallet_ix(2001, 100 * USDC)
    order = ix.accounts[1].pubkey
    r.name_it(order=order, order_tok=pay.ov_pda(order), dest=dest)
    r.check(c.svm, "start", tokens=["funder_tok", "fee", "dest"])
    r.label("fund_order_wallet")
    assert c.send([ix], c.funder), c.err
    r.check(c.svm, "funded", tokens=["funder_tok", "order_tok", "fee", "dest"], data=["order"])
    c.warp(5)
    proof = c.pay_token(order, payees)
    o = c.order(order)
    pay_ix = c.marked(c.pay_ix(order, proof, payees))
    r.name_it(used=pay_ix.accounts[13].pubkey)
    r.label("pay_order")
    assert c.send([pay_ix]), c.err
    r.check(c.svm, "paid", tokens=["funder_tok", "order_tok", "fee", "dest", "relayer_tok"], data=["order", "used"])
    r.label("pay_order_again")
    assert not c.send([c.pay_ix(order, proof, payees, o)]), "the same token paid twice"
    r.check(c.svm, "refused", tokens=["funder_tok", "order_tok", "fee", "dest", "relayer_tok"], data=["order"])
    return r


def double_pay() -> Recorder:
    """Two fund tokens for one issue (FundOrderBalance): the first order is paid, the second funds the same address
    anew, the first order's pay token is refused there by its marker, and the order goes back at its deadline."""
    r = scenario("double_pay")
    c = _order_chain(r)
    wallet, dest = c.wallet(c.usdc)
    payees = [(_order.AUTHOR, 10_000, wallet.pubkey())]
    first, second = c.fund_token(2002, 100 * USDC), c.fund_token(2002, 100 * USDC)
    ix = c.fund_balance_ix(first, 2002)
    order = ix.accounts[7].pubkey
    r.name_it(order=order, order_tok=pay.ov_pda(order), dest=dest)
    r.check(c.svm, "start", tokens=["balance_tok", "fee", "dest"])
    r.label("fund_order_balance")
    assert c.send([ix]), c.err
    r.check(c.svm, "funded", tokens=["balance_tok", "order_tok"], data=["order"])
    c.warp(5)
    proof = c.pay_token(order, payees)
    r.label("pay_order")
    assert c.send([c.pay_ix(order, proof, payees)]), c.err
    r.check(c.svm, "paid", tokens=["balance_tok", "order_tok", "fee", "dest"], data=["order"])
    again = c.fund_balance_ix(second, 2002)
    assert again.accounts[7].pubkey == order
    r.label("fund_same_address")
    assert c.send([again]), c.err
    o = c.order(order)
    r.check(c.svm, "funded_again", tokens=["balance_tok", "order_tok", "fee", "dest"], data=["order"])
    r.label("pay_with_old_token")
    assert not c.send([c.pay_ix(order, proof, payees, o)]), "one pay token paid two orders"
    r.check(c.svm, "refused", tokens=["balance_tok", "order_tok", "fee", "dest"], data=["order"])
    refund = pay.refund_order_ix(c.payer.pubkey(), order, o)
    r.label("refund_early")
    assert not c.send([refund])
    c.warp(o.deadline - c.now() + 1)
    r.label("refund_order")
    assert c.send([refund]), c.err
    r.check(c.svm, "refunded", tokens=["balance_tok", "order_tok", "fee", "dest"], data=["order"])
    return r


def order_fees() -> Recorder:
    """A wallet funds five orders, one at each edge of the fee tiers; the funder cancels the first, twice."""
    r = scenario("order_fees")
    c = _order_chain(r)
    r.check(c.svm, "start", tokens=["funder_tok"])
    for i, units in enumerate((100, 1_000, 1_001, 50_000, 50_001)):
        ix = c.fund_wallet_ix(2100 + i, units * USDC)
        order = ix.accounts[1].pubkey
        r.name_it(**{f"order_{units}": order, f"order_tok_{units}": pay.ov_pda(order)})
        r.label(f"fund_{units}")
        assert c.send([ix], c.funder), c.err
        assert c.order(order).fee == pay.order_fee(units * USDC)
        r.check(c.svm, f"funded_{units}", tokens=["funder_tok", f"order_tok_{units}"], data=[f"order_{units}"])
    order = r.names_key("order_100")
    stranger = c.fund()
    r.label("cancel_by_stranger")
    assert not c.send([pay.cancel_ix(stranger.pubkey(), order)], signers=[stranger])
    r.label("cancel")
    assert c.send([pay.cancel_ix(c.funder.pubkey(), order)], signers=[c.funder]), c.err
    o = c.order(order)
    assert o.cancel_at == c.now() and o.deadline == c.now() + pay.NOTICE
    r.check(c.svm, "cancelled", tokens=["funder_tok", "order_tok_100"], data=["order_100"])
    r.label("cancel_again")
    assert not c.send([pay.cancel_ix(c.funder.pubkey(), order)], signers=[c.funder])
    return r


# == knos_meter ==========================================================================================================
def meter_count() -> Recorder:
    """Credits are opened and filled; one evaluation is recorded (Record); a batch of 5,000 is (RecordBatch); a second
    token for the same seq is refused; the seller's claim of the batch is counted (ClaimBatch); the wallet takes the
    rest of its credits back (WithdrawCredits)."""
    r = scenario("meter_count")
    c = _meter.Meter()
    mint = c.new_mint()
    r.label("open_credits")
    wallet, credits = c.open(mint, _meter.BUYER, 0)
    wallet_tok = meter.ata(wallet.pubkey(), mint, c.token_program(mint))
    c.mint_to(mint, wallet_tok, 1000 * USDC)
    r.label("deposit")
    assert c.send([meter.deposit_ix(wallet_tok, wallet.pubkey(), credits, mint, 1000 * USDC, 6, c.token_program(mint))], wallet), c.err
    fee = c.token_account(meter.FEE_OWNER, mint)
    c.set_used(_meter.BUYER, meter.FREE_PER_MONTH)         # past the month's free evaluations: each one costs 0.05
    month = meter.yyyymm(c.now())
    r.name_it(credits=credits, credits_tok=meter.crtok_pda(credits), fee=fee, wallet_tok=wallet_tok, plan=meter.plan_pda(_meter.BUYER),
              month=meter.month_pda(_meter.BUYER, _meter.SELLER, month), ledger=_meter.ledger_pda(_meter.BUYER, _meter.SELLER, month),
              claims=_meter.ledger_pda(_meter.BUYER, _meter.SELLER, month, True))
    r.check(c.svm, "opened", tokens=["credits_tok", "fee", "wallet_tok"], data=["credits", "plan"])
    aud = c.aud("0" * 40, verdict=1, rate=2 * USDC)
    token = c.token(aud)
    r.label("record")
    assert c.send([meter.record_ix(c.payer.pubkey(), token, c.key_of(token), credits, c.credits(credits), aud, c.now())]), c.err
    r.check(c.svm, "recorded", tokens=["credits_tok", "fee"], data=["credits", "plan", "month"])
    root = _meter.merkle_root(sorted(hashlib.sha256(bytes([i])).digest() for i in range(8)))
    batch = c.batch_aud(seq=0, count=5000, accepted=4321, value=8_642 * USDC, root=root)
    token = c.token(batch)
    r.label("record_batch")
    assert c.send([_meter.record_batch_ix(c.payer.pubkey(), token, c.key_of(token), credits, c.credits(credits), batch)]), c.err
    r.check(c.svm, "batched", tokens=["credits_tok", "fee"], data=["credits", "plan", "ledger"])
    token = c.token(batch, jti="again")                     # GitHub signs the same batch once more: a new token, the old seq
    r.label("record_batch_same_seq")
    assert not c.send([_meter.record_batch_ix(c.payer.pubkey(), token, c.key_of(token), credits, c.credits(credits), batch)])
    r.check(c.svm, "refused", tokens=["credits_tok", "fee"], data=["credits", "plan", "ledger"])
    claim = c.batch_aud(seq=0, count=5000, accepted=4321, value=8_642 * USDC, root=root, kind="claim")
    token = c.gh(claim, repository_owner_id=_meter.SELLER)
    r.label("claim_batch")
    assert c.send([_meter.claim_batch_ix(c.payer.pubkey(), token, c.key_of(token), claim)]), c.err
    r.check(c.svm, "claimed", data=["claims"])
    left = c.held(credits)
    r.label("withdraw_credits")
    assert c.send([meter.withdraw_credits_ix(wallet.pubkey(), credits, mint, left, wallet_tok, c.token_program(mint))], wallet), c.err
    r.check(c.svm, "withdrawn", tokens=["credits_tok", "fee", "wallet_tok"], data=["credits"])
    return r


# == knos_passkey ========================================================================================================
class Passkey(_pk.Passkey):
    """The stand-in authenticator, signing with RFC 6979 nonces: the same assertion in every run. The low s unless
    high_s is True (the base class's `high_s` forces one of the two valid s values; None means the low one here)."""
    def sign(self, message: bytes, high_s: bool | None = None) -> bytes:
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import ec, utils
        r_, s = utils.decode_dss_signature(self.sk.sign(message, ec.ECDSA(hashes.SHA256(), deterministic_signing=True)))
        return utils.encode_dss_signature(r_, pk.N - s if (s > pk.N // 2) != bool(high_s) else s)


def passkey_wallet() -> Recorder:
    """A passkey's wallet is paid 100.00 and opened (Open); a withdrawal whose assertion another passkey signed is
    refused, by the precompile when it is checked against the wallet's key and by the program when it is checked against
    the signer's own; the same withdrawal signed by the wallet's passkey goes through (Withdraw); its assertion again is refused."""
    r = scenario("passkey_wallet")
    c = _pk.Chain()
    mint, p, other = c.mint(), Passkey(7), Passkey(8)
    source = c.pay(p.wallet, mint, 100_000_000)
    r.label("open")
    assert c.send([pk.open_ix(c.payer.pubkey(), p.key)]), c.err
    owner = NOW.keypair().pubkey()
    to = pay.ata(owner, mint, pay.TOKEN)
    assert c.send([pay.create_ata_ix(c.payer.pubkey(), owner, mint, pay.TOKEN)]), c.err
    r.name_it(wallet=p.wallet, source=source, to=to)
    r.check(c.svm, "opened", tokens=["source", "to"], data=["wallet"])
    challenge = pk.challenge(wallet=p.wallet, mint=mint, to=to, amount=5_000_000, nonce=1)
    auth, cdj, sig = other.get(challenge)
    r.label("withdraw_wrong_signature")
    assert not c.send(pk.withdraw_ixs(p.key, mint, to, 5_000_000, 1, auth, cdj, sig, pay.TOKEN))
    r.check(c.svm, "refused", tokens=["source", "to"], data=["wallet"])
    # the precompile is given the other passkey's key too, so it passes: the program itself must refuse the wallet
    forged = pk.withdraw_ixs(other.key, mint, to, 5_000_000, 1, auth, cdj, sig, pay.TOKEN)
    r.label("withdraw_another_passkey")
    assert not c.send([forged[0], *pk.withdraw_ixs(p.key, mint, to, 5_000_000, 1, auth, cdj, sig, pay.TOKEN)[1:]])
    r.check(c.svm, "refused_by_program", tokens=["source", "to"], data=["wallet"])
    auth, cdj, sig = p.get(challenge)
    ixs = pk.withdraw_ixs(p.key, mint, to, 5_000_000, 1, auth, cdj, sig, pay.TOKEN)
    r.label("withdraw")
    assert c.send(ixs), c.err
    r.check(c.svm, "withdrawn", tokens=["source", "to"], data=["wallet"])
    r.label("withdraw_replayed")
    assert not c.send(ixs)
    r.check(c.svm, "replay_refused", tokens=["source", "to"], data=["wallet"])
    return r


SCENARIOS = (oidc_verify, pay_order, double_pay, order_fees, meter_count, passkey_wallet)


def main(argv: list[str]) -> int:
    check, stale = "--check" in argv, []
    OUT.mkdir(exist_ok=True)
    for make in SCENARIOS:
        r = make()
        path, doc = OUT / f"{r.name}.json", r.doc()
        if check:
            if not path.is_file() or path.read_text(encoding="utf-8") != doc:
                stale.append(path.name)
        else:
            path.write_text(doc, encoding="utf-8")
        txs = [s for s in r.steps if s["op"] == "tx"]
        print(f"{path.relative_to(ROOT)}: {len(txs)} transactions, {sum(not s['ok'] for s in txs)} refused, {len(doc):,} bytes")
    if stale:
        print("stale (run scripts/rust_test_vectors.py and commit): " + " ".join(stale), file=sys.stderr)
    return 1 if stale else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
