"""The rounds 0.3.25 adds to scripts/exercise_rounds/ for the capabilities deployed at the public program ids with no
exercising transaction recorded: tip (fund_by_comment, pay_on_merge), meter-single, passkey-payee, gate (upgrade_gate),
guardian (key_guardian) and pause; and why hold_and_bind has none. Each runs against a fake cluster here (accounts,
logs and histories held in memory; no network, no node): what it sends, what it reads back and what it records.
meter-single also runs on the simulator. Nothing here is evidence of the public program ids."""
from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
from solders.keypair import Keypair
from solders.pubkey import Pubkey

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
NOW = 1_760_000_000
OWNER = 142920951           # the maintainer's account (scripts/own_github_ids.json)
NINE = ("verify_gitlab", "key_guardian", "fund_by_comment", "pay_on_merge", "hold_and_bind", "pause", "meter_single", "passkey_payee_wallet", "upgrade_gate")


@pytest.fixture(scope="module")
def ex():
    spec = importlib.util.spec_from_file_location("knos_exercise_deployed_rounds", ROOT / "scripts" / "exercise_public.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    said: list[str] = []
    mod.register_places()
    names = mod.load_rounds(say=said.append)
    assert said == [] and {"tip", "meter-single", "passkey-payee", "gate", "guardian", "pause"} <= set(names)
    return mod


def sig(n: int) -> str:
    return str(Keypair.from_seed(bytes([n]) * 32).sign_message(b"knos fake transaction"))


def jwt(claims: dict) -> str:
    b = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()  # noqa: E731
    return f"{b({'alg': 'RS256', 'kid': 'k'})}.{b(claims)}.c2ln"


class Ledger:
    def __init__(self):
        self.accounts: dict[str, bytes] = {}
        self.said: dict[str, list[str]] = {}
        self.hist: dict[str, list[str]] = {}

    def wrote(self, signature: str, program: Pubkey, lines: list[str], *touched) -> None:
        self.said[signature] = [f"Program {program} invoke [1]", *[f"Program log: {x}" for x in lines], f"Program {program} success"]
        for a in touched:
            self.hist.setdefault(str(a), []).insert(0, signature)

    def account(self, address):
        return self.accounts.get(str(address))

    def history(self, address, most=500):
        yield from self.hist.get(str(address), [])[:most]

    def logs(self, signature):
        return self.said.get(signature, [])

    def now(self):
        return NOW


def token_account(amount: int) -> bytes:
    return bytes(64) + amount.to_bytes(8, "little") + bytes(93)


def fake_world(ex, tmp_path: Path):
    class Fake(ex.World):
        mode = "public"

        def __init__(self):
            self.ledger, self.url, self.keys, self.cfg = Ledger(), "https://fake.invalid", tmp_path, {}
            self.relayer, self.funder = Keypair.from_seed(bytes([7]) * 32), Keypair.from_seed(bytes([8]) * 32)
            self.mint = ex.pay.USDC_DEVNET
            self.funder_token = ex.pay.ata(self.funder.pubkey(), self.mint)
            self.repository, self.rows, self.answers, self.sent, self.on_send, self.on_refused = "drexthealpha/knos-e2e", [], {}, [], None, None

        def pin(self):
            return "drexthealpha/Knos", "a" * 40, 1

        def submit(self, tok, payer=None):
            return self.answers.get(tok.jwt, {"ok": False, "why": "carried before"})

        def find(self, kind, pick, forge, taken):
            return next((t for t in self.rows if t.kind == kind and t.jwt not in taken and pick(t)), None)

        def landed(self, signature):
            named = {a for a, sigs in self.ledger.hist.items() if signature in sigs}
            return {"ok": True, "accounts": sorted(named | {ex.oidc.IDS[p] for p in ex.PROGRAMS})} if signature in self.ledger.said else None

        def send(self, ixs, payer=None, signers=None):
            self.sent.append(list(ixs))
            return self.on_send(list(ixs))

        def refused(self, ixs, payer=None):
            self.sent.append(list(ixs))
            return self.on_refused(list(ixs))

    return Fake()


def programs(ex):
    return {n: {"id": ex.oidc.IDS[n], "is": "next" if n in ("knos_oidc", "knos_pay") else "new"} for n in ex.PROGRAMS}


def one(ex, w, name: str) -> tuple[dict, list[str], int]:
    said: list[str] = []
    ev = ex.new_evidence(w, programs(ex))
    codes = ex.run_registered(w, ev, said.append, None, name)
    return ev, said, codes[name]


def test_the_pause_round_runs_only_when_named(ex):
    """The pause stops new funding at the public knos_pay for everyone while it runs, so it is the one round that runs
    only by name: `run`, `run --resume` and `run --phase after` pass it by (scripts/exercise_rounds/pause.py)."""
    assert [n for n, x in ex.EXT.items() if x.alone] == ["pause"]
    said: list[str] = []
    assert ex.main(["list"], said.append) == 0
    assert any(line.startswith("round pause (phase any; needs knos_pay, public; simulated: no; runs only by name: run --only pause): ") for line in said)


def test_the_nine_deployed_capabilities_each_have_a_round_or_a_reason(ex):
    caps = {c["id"]: c for c in json.loads((ROOT / "docs" / "capabilities.json").read_text(encoding="utf-8"))["capabilities"]}
    # 0.3.25's rounds at the public ids exercised five of them; the others stay deployed, and nothing else is deployed alone
    assert {i for i, c in caps.items() if c["stage"] == "deployed"} <= set(NINE) and all(caps[c]["stage"] in ("deployed", "exercised") for c in NINE)
    plan = ex.exercisable()         # what is still below `exercised`, and the round that would run it
    rounds = {"verify_gitlab": "gitlab", "key_guardian": "guardian", "fund_by_comment": "tip", "pay_on_merge": "tip", "pause": "pause",
              "meter_single": "meter-single", "passkey_payee_wallet": "passkey-payee", "upgrade_gate": "gate"}
    for c, name in rounds.items():  # each has its round, whether or not that round has exercised it yet
        assert c in ex.EXT[name].caps and plan.get(c, name) == name and (c in plan) == (caps[c]["stage"] != "exercised"), c
    assert plan["hold_and_bind"].startswith("none: cannot: a job is held only for a payee whose GitHub account has no wallet bound")
    for c in NINE:          # each one's note says what its round does, or why there is none
        assert caps[c].get("note"), c


# ---- tip ---------------------------------------------------------------------------------------------------------
def _tip_tokens(ex, w):
    th = hashlib.sha256(b"terms").digest()
    balance = ex.pay.balance_pda(OWNER, w.funder.pubkey(), w.mint)
    fund = ex.Tok(jwt({"aud": ex.pay.fund_audience(17, 1_000_000, 0, th, balance), "repository_id": "111", "iat": NOW}))
    paid = ex.Tok(jwt({"aud": ex.pay.pay_audience(111, 17, OWNER, "b" * 40, th, 0, None), "repository_id": "111", "iat": NOW}))
    w.rows = [fund, paid]
    # the repository's run carried the fund token first: the round finds the transaction by the token's marker
    w.ledger.wrote(sig(1), ex.pay.PAY_ID, [f"knos2:funded repo=111 issue=17 amount=1000000 mode=0 by={OWNER} source={balance} faucet=0"],
                   ex.pay.used_pda(fund.jwt))
    return fund, paid, balance


def test_a_tip_funds_a_job_from_the_owners_balance_and_the_merge_pays_its_author(ex, tmp_path):
    w = fake_world(ex, tmp_path)
    _fund, paid, balance = _tip_tokens(ex, w)
    to = Keypair.from_seed(bytes([3]) * 32).pubkey()
    w.answers[paid.jwt] = {"ok": True, "sigs": [sig(2)]}
    w.ledger.wrote(sig(2), ex.pay.PAY_ID, [f"knos2:paid repo=111 issue=17 payee={OWNER} amount=950000 fee=50000 to={to}"])
    ev, said, code = one(ex, w, "tip")
    assert code == 0, said
    assert ev["exercises"]["fund_by_comment"]["signature"] == sig(1) and ev["exercises"]["pay_on_merge"]["signature"] == sig(2)
    assert str(balance) in ev["exercises"]["fund_by_comment"]["asserted"][0] and str(to) in ev["exercises"]["pay_on_merge"]["asserted"][0]
    assert [t["signature"] for t in ev["rounds"]["tip"]["transactions"]] == [sig(1), sig(2)]


def test_a_tip_held_for_a_payee_with_no_wallet_says_so_and_one_with_no_token_says_what_to_start(ex, tmp_path):
    w = fake_world(ex, tmp_path)
    _fund, paid, _balance = _tip_tokens(ex, w)
    w.ledger.wrote(sig(4), ex.pay.PAY_ID, [f"knos2:held repo=111 issue=17 payee={OWNER} until={NOW + 86_400}"], ex.pay.used_pda(paid.jwt))
    ev, _said, code = one(ex, w, "tip")
    assert code == 3 and ev["exercises"]["pay_on_merge"]["status"].startswith("cannot: the job was held for payee")
    empty = fake_world(ex, tmp_path)
    ev, said, code = one(ex, empty, "tip")
    assert code == 3 and ev["exercises"]["fund_by_comment"]["status"] == "needs run: knos.yml (/knos tip)"
    assert any("comment `/knos tip 1`" in line for line in said)


# ---- passkey-payee ------------------------------------------------------------------------------------------------
def test_a_passkey_wallet_is_paid_before_it_exists_and_one_transaction_signed_by_the_passkey_opens_it_and_withdraws(ex, tmp_path):
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec, utils
    from knos.settle.v2 import passkey as pk
    w = fake_world(ex, tmp_path)
    state = {}

    def on_send(ixs):
        if not state:           # the payment: an associated token account and a transfer to it
            held = ixs[0].accounts[1].pubkey
            assert ixs[1].accounts[2].pubkey == held and int.from_bytes(ixs[1].data[1:9], "little") == 100_000
            w.ledger.accounts[str(held)] = token_account(100_000)
            state["held"] = held
            return sig(5)
        opened, pre, withdraw = ixs
        key = bytes(opened.data[1:34])
        assert opened.accounts[1].pubkey == withdraw.accounts[0].pubkey == pk.wallet(key) and withdraw.accounts[1].pubkey == state["held"]
        d = bytes(pre.data)
        o = [int.from_bytes(d[2 + 2 * i:4 + 2 * i], "little") for i in range(7)]
        r, s = int.from_bytes(d[o[0]:o[0] + 32], "big"), int.from_bytes(d[o[0] + 32:o[0] + 64], "big")
        public = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), d[o[2]:o[2] + 33])
        public.verify(utils.encode_dss_signature(r, s), d[o[4]:o[4] + o[5]], ec.ECDSA(hashes.SHA256()))     # what the precompile checks
        amount, nonce = int.from_bytes(withdraw.data[1:9], "little"), int.from_bytes(withdraw.data[9:17], "little")
        cdj = json.loads(bytes(withdraw.data[17:]))
        assert (amount, nonce) == (100_000, 1) and cdj["challenge"] == pk.b64url(pk.challenge(pk.wallet(key), w.mint, w.funder_token, amount, nonce))
        w.ledger.accounts[str(pk.wallet(key))] = bytes([1, 0]) + key + bytes(5) + nonce.to_bytes(8, "little")
        w.ledger.accounts[str(state["held"])] = token_account(0)
        return sig(6)

    w.on_send = on_send
    ev, said, code = one(ex, w, "passkey-payee")
    assert code == 0, said
    e = ev["exercises"]["passkey_payee_wallet"]
    assert e["signature"] == sig(6) and e["program"] == "knos_passkey" and "software" in e["asserted"][-1]
    again: list[str] = []
    assert ex.run_registered(w, ev, again.append, None, "passkey-payee") == {"passkey-payee": 0}      # done: nothing is sent again
    assert "[passkey-payee] done before: nothing is sent again" in again and len(w.sent) == 2
    _ev, said, code = one(ex, w, "passkey-payee")          # a fresh record, and the wallet open already: refused, not worked around
    assert code == 1 and "is open already" in _ev["exercises"]["passkey_payee_wallet"]["status"] and len(w.sent) == 2


# ---- gate -----------------------------------------------------------------------------------------------------------
def test_upgrade_gates_record_of_the_live_build_is_read_with_the_transaction_that_wrote_it(ex, tmp_path):
    seen = json.loads((ROOT / "docs" / "provenance.json").read_text(encoding="utf-8"))["programs"]["knos_oidc"]
    w = fake_world(ex, tmp_path)
    program, h = Pubkey.from_string(seen["address"]), bytes.fromhex(seen["on_chain_hash"])
    at = ex.gate.record_pda(program, h)
    w.ledger.accounts[str(at)] = (bytes([1]) + bytes(7) + (37523515307).to_bytes(8, "little") + NOW.to_bytes(8, "little") + (5).to_bytes(8, "little")
                                  + bytes(program) + h + seen["on_chain_commit"].encode())
    w.ledger.wrote(sig(7), ex.gate.GATE_ID, ["gate: recorded"], at, ex.gate.GATE_ID)
    w.ledger.hist[str(at)].insert(0, sig(8))            # a later transaction that only read it
    w.ledger.said[sig(8)] = []
    ev = ex.new_evidence(w, {**programs(ex), "knos_oidc": {"is": "next", "hash": seen["on_chain_hash"]}})
    codes = ex.run_registered(w, ev, lambda _l: None, None, "gate")
    assert codes == {"gate": 0}
    e = ev["exercises"]["upgrade_gate"]
    assert e["signature"] == sig(7) and e["program"] == "upgrade_gate" and seen["on_chain_commit"] in e["asserted"][0]
    # a build the public id does not run now is not counted
    w2 = fake_world(ex, tmp_path)
    w2.ledger.accounts.update(w.ledger.accounts)
    ev = ex.new_evidence(w2, {**programs(ex), "knos_oidc": {"is": "next", "hash": "00" * 32}})
    ex.run_registered(w2, ev, lambda _l: None, None, "gate")
    assert ev["exercises"]["upgrade_gate"]["status"].startswith("cannot: upgrade_gate holds no record")


# ---- guardian and pause ------------------------------------------------------------------------------------------
def _common():
    """scripts/exercise_rounds/_guardian.py as the rounds load it (guardian.common): loaded here when no earlier test
    of this file has run a round, so each test stands alone (a shard may hold any one of them)."""
    name = "knos_exercise_guardian_common"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / "exercise_rounds" / "_guardian.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return sys.modules[name]


def key_account(issuer: int, flags: int) -> bytes:
    d = bytearray(40 + 8 * 64)
    d[0], d[1], d[2], d[24] = 1, issuer, 64, flags
    return bytes(d)


def test_the_guardian_approves_only_a_key_that_waits_for_it_and_otherwise_says_why_it_cannot(ex, tmp_path, monkeypatch):
    from knos.settle import oidc as first
    n = (1 << 2047) + 12345
    g = ex.EXT["guardian"].fn.__globals__
    monkeypatch.setitem(g, "PUBLISHED", lambda issuer: [n] if issuer == 0 else [])
    w = fake_world(ex, tmp_path)
    ev, _said, code = one(ex, w, "guardian")
    assert code == 3 and ev["exercises"]["key_guardian"]["status"].startswith("skipped: ") and "governance" in ev["exercises"]["key_guardian"]["status"]
    (tmp_path / "governance").mkdir()
    at = ex.oidc.key_pda(0, n)
    w.ledger.accounts[str(at)] = key_account(0, ex.oidc.APPROVED | ex.oidc.GENESIS)
    ev, _said, code = one(ex, w, "guardian")
    assert code == 3 and ev["exercises"]["key_guardian"]["status"].startswith("cannot: no signing key waits for the guardian")
    w.ledger.accounts[str(at)] = key_account(0, 0)          # registered by the rotate run, ready, not approved
    calls = []

    def runner(argv):
        calls.append(argv[2:6])
        w.ledger.accounts[str(at)] = key_account(0, ex.oidc.APPROVED)
        w.ledger.wrote(sig(9), ex.oidc.OIDC_ID, [], at)
        return subprocess.CompletedProcess(argv, 0, "approved\n", "")

    monkeypatch.setattr(_common(), "RUNNER", runner)
    ev, said, code = one(ex, w, "guardian")
    assert code == 0, said
    assert calls == [["guardian", "approve", "0", first.key_hash(n).hex()]] and ev["exercises"]["key_guardian"]["signature"] == sig(9)


def test_the_guardian_pauses_new_funding_a_funding_is_refused_and_the_pause_is_lifted(ex, tmp_path, monkeypatch):
    w = fake_world(ex, tmp_path)
    (tmp_path / "governance").mkdir()
    pause = ex.pay.pause_pda()
    asked = []

    def runner(argv):
        seconds = int(argv[4])
        asked.append(seconds)
        w.ledger.accounts[str(pause)] = ((NOW + seconds) if seconds else 0).to_bytes(8, "little", signed=True)
        w.ledger.wrote(sig(10 + len(asked)), ex.pay.PAY_ID, [f"knos2:paused until={(NOW + seconds) if seconds else 0}"], pause)
        return subprocess.CompletedProcess(argv, 0, "", "")

    def refused(ixs):
        assert ixs[0].program_id == ex.pay.PAY_ID and ixs[0].accounts[-1].pubkey == pause      # FundOrderWallet names the pause account
        return sig(20), 96

    w.on_refused = refused
    monkeypatch.setattr(_common(), "RUNNER", runner)
    ev, said, code = one(ex, w, "pause")
    assert code == 0, said
    assert asked == [120, 0]
    e = ev["exercises"]["pause"]
    assert e["signature"] == sig(11) and e["refusals"] == [{"signature": sig(20), "error": 96, "means": "new funding is paused"}]
    assert [t["signature"] for t in ev["rounds"]["pause"]["transactions"]] == [sig(11), sig(20), sig(12)]


def test_a_funding_refused_with_another_error_fails_the_pause_round(ex, tmp_path, monkeypatch):
    w = fake_world(ex, tmp_path)
    (tmp_path / "governance").mkdir()
    pause = ex.pay.pause_pda()

    def runner(argv):
        w.ledger.accounts[str(pause)] = (NOW + 120).to_bytes(8, "little", signed=True)
        w.ledger.wrote(sig(30), ex.pay.PAY_ID, [], pause)
        return subprocess.CompletedProcess(argv, 0, "", "")

    w.on_refused = lambda ixs: (sig(31), 87)
    monkeypatch.setattr(_common(), "RUNNER", runner)
    ev, _said, code = one(ex, w, "pause")
    assert code == 1 and "not 96" in ev["exercises"]["pause"]["status"]


# ---- meter-single, on the simulator ------------------------------------------------------------------------------
def test_one_evaluation_is_counted_once_and_its_retry_is_free_on_the_simulator(ex):
    pytest.importorskip("solders.litesvm")
    w, said = ex.Simulated(), []
    try:
        ev = ex.new_evidence(w, ex.simulated_programs())
        codes = ex.run_registered(w, ev, said.append, None, "meter-single")
    finally:
        w.close()
    assert codes == {"meter-single": 0}, said
    st = ev["rounds"]["meter-single"]
    assert st["counted"]["accepted"] and st["retry"] == {"already": True} and len(st["transactions"]) == 1
    assert ev["exercises"]["meter_single"]["signature"] == st["counted"]["signature"]
