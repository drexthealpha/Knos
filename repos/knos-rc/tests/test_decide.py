"""`knos decide`: the decision is the relay's own reads, a provisional receipt never authorises payment, the final
receipt supersedes it by name, the offline half reads nothing, the chain half is one request, and the speed targets hold on this machine (scripts/decide_bench.py measures them)."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

pytest.importorskip("solders.litesvm")

import test_relay2 as t2  # noqa: E402
from _pay2 import Chain  # noqa: E402

from knos import decide, receipt  # noqa: E402
from knos.settle.v2 import relay  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
VECTORS = json.loads((ROOT / "docs" / "receipt" / "vectors.json").read_text(encoding="utf-8"))


def _script(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def env():
    return t2._setup(Chain())


def test_the_decision_is_what_the_relay_would_answer_before_it_sends_and_it_sends_nothing(env):
    c, net = env
    org, repo, n = t2.user(), t2.user(), t2.issue()
    fund, now, txs = t2.faucet_jwt(c, n, org, repo), c.now(), net.txs
    d = decide.token(fund, t2.TERMS, ledger=net, payer=c.payer, jwks=t2.JWKS, now=now)
    assert relay.precheck(net, c.payer, fund, t2.TERMS, t2.JWKS, now=now) is None
    assert d == {"decision": "accepted", "why": "everything the chain will ask of this token holds now", "kind": "fund", "chain_read": True, "already": False}
    # a refusal is the relay's refusal, in the relay's words: there is no second set of rules to drift from it
    nothing = t2.pay_jwt(c, repo, n, t2.user())
    refused = relay.precheck(net, c.payer, nothing, None, t2.JWKS, now=now)
    d = decide.token(nothing, None, ledger=net, payer=c.payer, jwks=t2.JWKS, now=now)
    assert refused and not refused["ok"] and d["decision"] == "rejected" and d["why"] == " ".join(refused["why"].split()) and d["kind"] == "pay"
    wrong = decide.token(fund, b'{"mode":"merge"}', ledger=net, payer=c.payer, jwks=t2.JWKS, now=now)
    assert wrong["decision"] == "rejected" and wrong["why"] == relay.precheck(net, c.payer, fund, b'{"mode":"merge"}', t2.JWKS, now=now)["why"]
    forged = fund[:-6] + ("AAAAAA" if not fund.endswith("AAAAAA") else "BBBBBB")
    assert decide.token(forged, t2.TERMS, ledger=net, payer=c.payer, jwks=t2.JWKS, now=now) == {
        "decision": "rejected", "why": "the signature is not the issuer's", "kind": "fund", "chain_read": True, "already": False}
    assert net.txs == txs                                       # four decisions, and not one transaction
    # once the chain has it, the decision is still accepted and says the chain shows it already
    assert t2.go(env, fund, t2.TERMS)["ok"]
    done = decide.token(fund, t2.TERMS, ledger=net, payer=c.payer, jwks=t2.JWKS, now=c.now())
    assert done["decision"] == "accepted" and done["already"] is True


def test_what_cannot_be_read_is_insufficient_evidence_never_an_acceptance_and_never_a_rejection(env):
    c, net = env
    fund, now = t2.faucet_jwt(c, t2.issue(), t2.user(), t2.user()), c.now()

    class Down:
        url = "down"

        def __getattr__(self, name):
            raise ConnectionError("no route to the cluster")
    d = decide.token(fund, t2.TERMS, ledger=Down(), payer=c.payer, jwks=t2.JWKS, now=now)
    assert d["decision"] == "insufficient_evidence" and d["why"].startswith("the chain did not answer (") and d["chain_read"] is True
    # with no chain at all a token can be refused for what it is, and never accepted
    alone = decide.token(fund, t2.TERMS, jwks=t2.JWKS, now=now)
    assert alone["decision"] == "insufficient_evidence" and "was not read" in alone["why"] and alone["chain_read"] is False and alone["kind"] == "fund"
    assert decide.token(fund, t2.TERMS, jwks=t2.JWKS, now=now + 3 * 3600)["why"] == "token expired"
    assert decide.token(fund, None, jwks=t2.JWKS, now=now)["decision"] == "rejected"                    # a fund token without its terms
    assert decide.token("not a token", None, jwks=t2.JWKS, now=now)["decision"] == "rejected"
    # a refusal the relay would try again is not a rejection
    again = {"ok": False, "kind": "fund", "retry": True, "wait": 30, "why": "the faucet serves a repository once a minute"}
    real, relay.precheck = relay.precheck, lambda *a, **k: again
    try:
        d = decide.token(fund, t2.TERMS, ledger=net, payer=c.payer, jwks=t2.JWKS, now=now)
    finally:
        relay.precheck = real
    assert d["decision"] == "insufficient_evidence" and d["why"].endswith("the faucet serves a repository once a minute")


def test_the_free_check_is_decided_from_its_named_checks_alone():
    ok = [{"name": "test", "conclusion": "passed"}, {"name": "build", "conclusion": "passed"}]
    assert decide.checks(ok)["decision"] == "accepted" and [c["name"] for c in decide.checks(ok)["checks"]] == ["build", "test"]
    assert decide.checks([*ok, {"name": "lint", "conclusion": "failed"}]) | {"checks": []} == {
        "kind": "check", "chain_read": False, "already": False, "checks": [], "decision": "rejected", "why": "failed: lint"}
    assert decide.checks([*ok, {"name": "lint", "conclusion": "missing"}])["decision"] == "insufficient_evidence"
    assert decide.checks([{"name": "a", "conclusion": "failed"}, {"name": "b", "conclusion": "missing"}])["decision"] == "rejected"
    assert decide.checks([])["decision"] == "insufficient_evidence"         # nothing named is nothing shown
    with pytest.raises(ValueError, match="conclusion"):
        decide.checks([{"name": "test", "conclusion": "success"}])


def test_a_provisional_receipt_never_authorises_payment_and_never_says_paid(env):
    c, net = env
    fund, now = t2.faucet_jwt(c, t2.issue(), t2.user(), t2.user()), c.now()
    d = decide.token(fund, t2.TERMS, ledger=net, payer=c.payer, jwks=t2.JWKS, now=now)
    p = decide.provisional(d, at=now, jwt=fund, terms=t2.TERMS)
    assert d["decision"] == "accepted" and decide.check(p) is None
    assert p["settlement"] == "provisional" and p["authorises_payment"] is False and decide.authorises_payment(p) is False
    assert receipt.check(p) is not None and receipt.authorises_payment(p) is False       # and nothing that reads receipts takes it for one
    assert "paid" not in json.dumps({k: v for k, v in p.items() if k not in ("limitations", "says")}).lower()
    assert p["limitations"][-1] == decide.SAYS and "never authorises payment" in decide.SAYS
    assert receipt.limitations_of("issuer_token", "accepted", "merge", False, False) == p["limitations"][:-1]      # receipt.py's own sentences
    assert p["evidence"] == {"kind": "issuer_token", "reference": decide._sha(fund), "signed_by": "https://token.actions.githubusercontent.com"}
    assert p["rules"] == {"by": "knos.settle.v2.relay.precheck", "chain_read": True, "already_on_chain": False}
    assert p["subject"]["terms_sha256"] == decide._sha(t2.TERMS) and p["subject"]["audience"].startswith("knos2:fund:")
    assert decide.provisional(d, at=now, jwt=fund, terms=t2.TERMS) == p and len(decide.digest(p)) == 64         # the same evidence, the same receipt
    line = decide.comment_line(p)
    assert line.startswith("Provisional: accepted (") and "Not paid yet" in line and decide.digest(p)[:16] in line
    # whatever is changed toward "paid" is no provisional receipt any more
    for change in ({"settlement": "paid"}, {"settlement": "final"}, {"authorises_payment": True}, {"says": "Paid."}, {"decision": "disputed"}):
        assert "provisional" in decide.check({**p, **change}) or "decision" in decide.check({**p, **change}), change
    with pytest.raises(ValueError):
        decide.provisional({**d, "decision": "paid"}, at=now, jwt=fund)
    # the free check's: no issuer signed, and it says so in receipt.py's words
    free = decide.provisional(decide.checks([{"name": "test", "conclusion": "failed"}]), at=now, subject={"repository": "octo/widgets", "pull_request": 7, "commit": "a" * 40})
    assert free["evidence"]["kind"] == "run_record" and free["evidence"]["signed_by"] is None and free["decision"] == "rejected"
    assert free["limitations"][0].startswith("No issuer signed this") and free["authorises_payment"] is False


def test_the_final_receipt_supersedes_the_provisional_one_by_naming_it(env):
    c, net = env
    fund, now = t2.faucet_jwt(c, t2.issue(), t2.user(), t2.user()), c.now()
    p = decide.provisional(decide.token(fund, t2.TERMS, ledger=net, payer=c.payer, jwks=t2.JWKS, now=now), at=now, jwt=fund, terms=t2.TERMS)
    final = VECTORS["valid"][0]["receipt"]
    with pytest.raises(ValueError, match="another token"):
        decide.supersede(final, p)
    mine = {**p, "evidence": {**p["evidence"], "reference": final["judge"]["token_sha256"]}}         # the provisional receipt of the token this final receipt is of
    line = decide.supersede(final, mine)
    assert line == {"type": "knos-supersedes", "version": 1, "final": {"sha256": receipt.digest(final), "verdict": "accepted", "settlement": "paid"},
                    "supersedes": {"sha256": decide.digest(mine), "decision": "accepted", "settlement": "provisional"}, "agrees": True}
    assert decide.superseded(mine, line) and decide.superseded(mine, line, final) and not decide.superseded(p, line)
    # the chain decided otherwise than the provisional receipt said: the line says so, and the final receipt stands
    doubted = {**mine, "decision": "insufficient_evidence"}
    assert decide.supersede(final, doubted)["agrees"] is False
    with pytest.raises(ValueError):
        decide.supersede({**final, "version": 9}, mine)
    with pytest.raises(ValueError):
        decide.supersede(final, {**mine, "settlement": "paid"})


def test_a_cached_ledger_answers_again_from_memory_for_its_time_and_sends_nothing(env):
    """Counted against the first pass, never against a fixed number: the relay keeps the cluster's version for the
    whole process (`relay.version`), so how many reads the FIRST decision makes depends on what ran before it."""
    c, net = env
    fund, now, clock = t2.faucet_jwt(c, t2.issue(), t2.user(), t2.user()), c.now(), [100.0]
    for primed in (False, True):                                # alone in a fresh process, and after other decisions: the same
        if not primed:
            relay.forget()
        kept = decide.Cached(net, ttl=30, clock=lambda: clock[0])
        first = decide.token(fund, t2.TERMS, ledger=kept, payer=c.payer, jwks=t2.JWKS, now=now)
        reads = kept.reads
        assert first["decision"] == "accepted" and reads > 0 and kept.hits == 0
        assert decide.token(fund, t2.TERMS, ledger=kept, payer=c.payer, jwks=t2.JWKS, now=now) == first and kept.reads == reads
        again = kept.hits                                       # every read of the second decision came from memory
        assert again >= 2 and reads - again == (0 if primed else 1), (primed, reads, again)
        clock[0] += 31                                          # past its time: the chain is asked again
        assert decide.token(fund, t2.TERMS, ledger=kept, payer=c.payer, jwks=t2.JWKS, now=now) == first and kept.reads == reads + again
        with pytest.raises(AttributeError, match="cannot send transactions: it has no send"):
            kept.send([], c.payer)


class FakeRpc:
    """An RPC endpoint that counts its round trips: every method of `chain.Ledger` that is one request."""

    def __init__(self, net, down: bool = False):
        self.net, self.down, self.calls, self.url = net, down, [], "fake-rpc"

    def __getattr__(self, name):
        got = getattr(self.net, name)
        if not callable(got):
            return got

        def asked(*a, **k):
            self.calls.append(name)
            if self.down:
                raise ConnectionError("no route to the cluster")
            return got(*a, **k)
        return asked


def _kept():
    return {relay.oidc.ISSUERS[number]: doc for number, doc in t2.JWKS.items() if number in relay.oidc.ISSUERS}


def test_the_offline_half_decides_from_the_signed_evidence_with_kept_keys_and_reads_nothing(env, tmp_path, monkeypatch):
    c, net = env
    fund, now, keys = t2.faucet_jwt(c, t2.issue(), t2.user(), t2.user()), c.now(), _kept()

    def no_network(*a, **k):
        raise AssertionError("the offline half fetched something")
    monkeypatch.setattr(relay.first, "fetch_jwks", no_network)
    monkeypatch.setattr(relay.urllib.request, "urlopen", no_network)
    d = decide.offline(fund, t2.TERMS, keys=keys, now=now)
    assert d == {"decision": "accepted", "why": "decided from the signed evidence; chain state not yet read", "kind": "fund", "chain_read": False,
                 "already": False, "rules": "knos.decide.offline"}
    p = decide.provisional(d, at=now, jwt=fund, terms=t2.TERMS)
    assert decide.check(p) is None and p["authorises_payment"] is False and p["why"] == decide.OFFLINE
    assert p["rules"] == {"by": "knos.decide.offline", "chain_read": False, "already_on_chain": False}
    # refused for what it is, in the relay's words; and the same answers the relay's own token-alone reads give
    forged = fund[:-6] + ("AAAAAA" if not fund.endswith("AAAAAA") else "BBBBBB")
    assert decide.offline(forged, t2.TERMS, keys=keys, now=now)["why"] == "the signature is not the issuer's"
    for jwt, terms, at in ((fund, None, now), (fund, b'{"mode":"merge"}', now), (fund, t2.TERMS, now + 3 * 3600), ("not a token", None, now)):
        got, old = decide.offline(jwt, terms, keys=keys, now=at), decide.token(jwt, terms, jwks=t2.JWKS, now=at)
        assert got["decision"] == old["decision"] == "rejected" and got["why"] == old["why"], (got, old)
    # keys that are not kept are not fetched: no answer, and never the supplier's failure
    none = decide.offline(fund, t2.TERMS, keys={}, now=now)
    assert none["decision"] == "insufficient_evidence" and "none was fetched" in none["why"]
    other = {k: {"keys": []} for k in keys}
    assert decide.offline(fund, t2.TERMS, keys=other, now=now)["decision"] == "insufficient_evidence"
    # kept on this machine: written once, read back the same, and a file that is not one keeps nothing
    monkeypatch.setenv(decide.KEYS_ENV, str(tmp_path / "keys" / "issuer_keys.json"))
    assert decide.kept_keys() == {} and decide.keep_keys(keys, at=now) == decide.keys_path() and decide.kept_keys() == keys
    assert decide.offline(fund, t2.TERMS, now=now)["decision"] == "accepted"
    decide.keys_path().write_text("[]", encoding="utf-8")
    assert decide.kept_keys() == {}


def test_the_chain_half_is_one_request_with_a_timeout_and_a_silent_chain_changes_nothing(env):
    c, net = env
    org, repo, n = t2.user(), t2.user(), t2.issue()
    fund, now, keys = t2.faucet_jwt(c, n, org, repo), c.now(), _kept()
    d = decide.offline(fund, t2.TERMS, keys=keys, now=now)
    # before: the relay's precheck through the same counter. After: one getMultipleAccounts
    relay.forget()
    before = FakeRpc(net)
    assert decide.token(fund, t2.TERMS, ledger=before, payer=c.payer, jwks=t2.JWKS)["decision"] == "accepted"
    rpc = FakeRpc(net)
    seen = decide.chain_check(fund, ledger=rpc)
    assert rpc.calls == ["infos"] and len(before.calls) > 1 and before.calls.count("infos") >= 2, before.calls
    assert seen == {"read": True, "round_trips": 1, "why": "", "now": c.now(), "token_used": False, "paused_until": 0, "order": None}
    after = decide.after_chain(d, seen, fund)
    assert after["decision"] == "accepted" and after["chain_read"] is True and after["why"].startswith("decided from the signed evidence; the chain shows the token is unused")
    first = decide.provisional(d, at=now, jwt=fund, terms=t2.TERMS)
    second = decide.provisional(after, at=now, jwt=fund, terms=t2.TERMS, updates=decide.digest(first))
    assert decide.check(second) is None and second["rules"]["updates"] == decide.digest(first) and second["rules"]["chain"]["round_trips"] == 1
    assert second["authorises_payment"] is False and second["rules"]["chain_read"] is True
    # a chain that is down, or slower than the timeout: one request made, the offline answer stands, nothing raised
    down = FakeRpc(net, down=True)
    lost = decide.chain_check(fund, ledger=down)
    assert down.calls == ["infos"] and lost["read"] is False and lost["why"].startswith("the chain did not answer (ConnectionError")
    kept = decide.after_chain(d, lost, fund)
    assert kept["decision"] == "accepted" and kept["chain_read"] is False and kept["why"].startswith(decide.OFFLINE + "; the chain did not answer")
    import threading
    gate = threading.Event()

    class Slow:
        def infos(self, addresses):
            gate.wait(30)
            return []
    slow = decide.chain_check(fund, ledger=Slow(), timeout=0.05)
    gate.set()
    assert slow["read"] is False and "TimeoutError" in slow["why"]
    # what the chain shows can take an acceptance back, and never turns a rejection into one
    job = relay.pay.job_pda(repo, n, relay.pay.faucet_balance_pda(org))
    absent = decide.chain_check(fund, ledger=rpc, order=job)
    assert absent["order"] == {"address": str(job), "found": False, "state": None, "deadline": None}
    assert decide.after_chain({**d, "kind": "pay"}, absent, fund)["decision"] == "rejected"
    assert t2.go(env, fund, t2.TERMS)["ok"]
    done = decide.chain_check(fund, ledger=rpc, order=job)
    assert done["token_used"] is True and done["order"]["found"] and done["order"]["state"] == "open" and done["order"]["deadline"] > c.now()
    used = decide.after_chain(d, done, fund)
    assert used["decision"] == "accepted" and used["already"] is True
    assert decide.after_chain({**d, "kind": "pay"}, {**done, "token_used": False}, fund)["why"].endswith("the order is open and before its deadline")
    assert decide.after_chain({**d, "kind": "pay"}, {**done, "token_used": False, "now": done["order"]["deadline"] + 1}, fund)["decision"] == "rejected"
    assert decide.after_chain({**d, "decision": "rejected", "why": "x"}, done, fund)["decision"] == "rejected"


def test_a_meter_batch_the_chain_took_is_not_called_unused_by_the_chain_half():
    # Found on devnet (0.3.19): knos_meter keeps no marker of a batch or claim token, so the chain half read only
    # knos_pay's marker and said "the chain shows the token is unused" for batch 1 of 202610 an hour after RecordBatch
    # had taken it. It now reads the pair's Ledger account in the same one request.
    import base64
    from knos import chain
    from knos.settle.v2 import meter, pay

    def b64(raw: bytes) -> str:
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    now, aud = 1_791_378_000, "knosm:batch:142920951:142920951:202610:1:20:20:6400000:" + "2f" * 32
    jwt = ".".join((b64(b'{"alg":"RS256"}'), b64(json.dumps({"aud": aud, "exp": now + 300}).encode()), b64(b"s" * 256)))
    where = meter.ledger_pda(142920951, 142920951, 202610, False)

    def account(next_seq: int) -> bytes:
        return (bytes([1, 0, 0, 0]) + (202610).to_bytes(4, "little") + (142920951).to_bytes(8, "little") * 2 + next_seq.to_bytes(8, "little")
                + bytes(meter.LEDGER_LEN - 32))

    class Rpc:
        def __init__(self, held):
            self.held, self.asked = held, []

        def infos(self, addresses):
            self.asked.append(list(addresses))
            clock = bytes(32) + now.to_bytes(8, "little")
            return [(chain.CLOCK, clock) if a == chain.CLOCK else (meter.METER_ID, self.held) if a == where and self.held else None for a in addresses]
    d = {"decision": "accepted", "why": decide.OFFLINE, "kind": "batch", "chain_read": False, "already": False}
    for next_seq, decision, already, said in ((2, "accepted", True, "the chain shows batch 1 of this pair's month taken already (it takes 2 next)"),
                                              (1, "accepted", False, "the chain shows batch 1 is the one the pair's Ledger account takes next"),
                                              (0, "insufficient_evidence", False, "the chain takes batch 0 of this pair's month next, and this token names batch 1")):
        rpc = Rpc(account(next_seq))
        seen = decide.chain_check(jwt, ledger=rpc)
        assert len(rpc.asked) == 1 and where in rpc.asked[0] and pay.used_pda(jwt) in rpc.asked[0]          # still one request
        assert seen["token_used"] is False and seen["batch"] == {"address": str(where), "claim": False, "seq": 1, "next_seq": next_seq}
        got = decide.after_chain(d, seen, jwt)
        assert (got["decision"], got.get("already", False)) == (decision, already) and said in got["why"], got
        assert "the token is unused" not in got["why"]
    # a pair with no batch yet takes batch 0 next; a token that is not a batch's asks nothing of knos_meter
    assert decide.chain_check(jwt, ledger=Rpc(None))["batch"]["next_seq"] == 0
    other = ".".join((b64(b'{"alg":"RS256"}'), b64(json.dumps({"aud": "knos3:fund:1", "exp": now}).encode()), b64(b"t" * 256)))
    assert "batch" not in decide.chain_check(other, ledger=Rpc(None))


def test_the_targets_hold_here_a_warm_offline_decision_under_100_ms_a_cached_one_under_200_ms_and_evidence_to_decision_under_2_s():
    """Generous bounds on purpose: the measured figures are a few milliseconds (docs/reference/BENCH.md, "Decision time"), so the
    100 ms bound has a margin of more than ten times on a machine shared with other work. The chain is LiteSVM in this
    process, so this is Knos's own time; a cluster's round trips are not in it."""
    bench = _script("decide_bench")
    r = bench.measure(12)
    rows = r["rows"]
    assert all(s["n"] == 12 for s in rows.values()) and set(rows) == {name for name, _t, _w in bench.ROWS}
    assert rows["cached, accepted"]["p95"] < 200 and rows["no chain"]["p95"] < 200 and rows["free check"]["p95"] < 200, rows
    assert rows["fresh, accepted"]["p95"] < 2000 and rows["fresh, rejected"]["p95"] < 2000, rows
    assert r["decisions"] == {"fresh, accepted": ["accepted"], "fresh, rejected": ["rejected"], "cached, accepted": ["accepted"],
                              "no chain": ["insufficient_evidence"], "free check": ["accepted"], "offline, accepted": ["accepted"], "chain check": ["accepted"],
                              "offline, warm": ["accepted"]}
    assert bench.TARGETS["warm"] == bench.TARGETS["local"] == 100 and rows["offline, warm"]["p95"] < 100, rows     # once the evidence is in hand
    # the table states its machine and its sample, and the document holds what the script writes
    lines = bench.table(r, "2026-10-06")
    assert "on this machine: " in lines[0] and "no network" in lines[0] and "4.3 to 32.6 s" in lines[0] and "timed there on 24 real tokens" in lines[0]
    assert len(lines) == 4 + len(bench.ROWS) and "a target, not a measurement" in lines[2]
    assert rows["offline, accepted"]["p95"] < 100 and rows["chain check"]["p95"] < 250, rows       # the target, held on this machine
    trips = bench.round_trips()
    assert trips["after"] == {"n": 1, "calls": ["infos"]} and trips["before"]["n"] > trips["after"]["n"]
    under = bench.split_lines(trips, {"n": 1, "p50": 700.0, "p95": 900.0, "max": 900.0, "inside": {"p50": 300.0, "p95": 400.0}, "decisions": ["x"]})
    assert "the chain check makes 1 (1 infos: one getMultipleAccounts)" in under[1] and "does not meet it here" in under[3]
    apart = bench.split_lines(trips, {"n": 1, "p50": 700.0, "p95": 900.0, "max": 900.0, "inside": {"p50": 300.0, "p95": 400.0}, "decisions": ["x"],
                                      "loaded": {"p50": 290.0, "p95": 380.0}, "offline": {"p50": 1.2, "p95": 2.4}})[3]
    assert "loading the rules" in apart and "p50 290 ms, p95 380 ms; the decision itself p50 1.2 ms, p95 2.4 ms" in apart and "The 100 ms target" in apart
    # what the document says of the process that stays up, and of real tokens, is what was measured: no file, no sentence
    assert bench.warm_lines(None, None) == [] and "the file given held none" in bench.warm_lines(None, {"n": 0})[1]
    said = bench.warm_lines({"n": 3, "p50": 0.7, "p95": 120.0, "max": 130.0, "loaded": 90.0, "decisions": ["accepted (x)"]},
                            {"n": 2, "p50": 0.8, "p95": 0.9, "max": 0.9, "decisions": {"accepted": 2}, "skipped": 1})
    assert "NOT met here" in said[1] and "n 2: p50 0.8 ms, p95 0.9 ms" in said[3] and "2 accepted; 1 lines skipped" in said[3]
    kept = json.loads((ROOT / "docs" / "bench.json").read_text(encoding="utf-8"))["decision"]
    assert kept["local"]["rows"]["offline, warm"]["p95"] < 100 and kept["local"]["target_ms_p95_warm"] == 100 and "CPUs" in kept["local"]["machine"]
    assert kept["devnet"]["offline"] == {"n": 24, "fastest": 170, "median": 356, "slowest": 863, "p95": None}                 # the last release run's
    doc = (ROOT / "docs" / "reference" / "BENCH.md").read_text(encoding="utf-8")
    assert "## Decision time" in doc and bench.OPEN in doc and bench.CLOSE in doc
    held = doc.split(bench.OPEN)[1].split(bench.CLOSE)[0]
    assert all(f"| {name} |" in held for name, _t, _w in bench.ROWS) and "| 40 |" in held
    assert bench.render(doc, held.strip("\n").split("\n")) == doc                                       # rendering again changes nothing


def test_the_command_is_registered_by_its_own_module_and_names_typer_only_inside_register(tmp_path):
    src = (ROOT / "src" / "knos" / "decide.py").read_text(encoding="utf-8")
    assert "\nimport typer" not in src and "from typer" not in src and 'importlib.import_module("typer")' in src
    typer = pytest.importorskip("typer")
    from typer.testing import CliRunner
    app, lines = typer.Typer(), []
    decide.register(app, lines)

    @app.command("other")
    def _other() -> None:
        pass
    assert lines == [("decide", "For money", "The decision the moment the evidence arrives, as a provisional receipt. It never authorises payment.")]
    run = CliRunner()
    file = tmp_path / "checks.json"
    file.write_text(json.dumps([{"name": "test", "conclusion": "passed"}]), encoding="utf-8")
    got = run.invoke(app, ["decide", "--checks-file", str(file)])
    assert got.exit_code == 0, got.output
    doc = json.loads(got.stdout[got.stdout.index("{"):got.stdout.rindex("}") + 1])
    assert decide.check(doc) is None and doc["decision"] == "accepted" and doc["settlement"] == "provisional"
    file.write_text(json.dumps([{"name": "test", "conclusion": "failed"}]), encoding="utf-8")
    assert run.invoke(app, ["decide", "--checks-file", str(file)]).exit_code == 1
    assert run.invoke(app, ["decide"]).exit_code == 2


def test_the_standalone_command_loads_no_command_line_library_and_the_relay_only_to_decide_on_a_token(tmp_path):
    """`python -m knos.decide` reads its options with argparse: typer, click and rich are never imported, and the relay's
    rules (solders under them) only by the half that decides on a token. The answers are `knos decide`'s."""
    import os
    import subprocess
    checks = tmp_path / "checks.json"
    checks.write_text(json.dumps([{"name": "test", "conclusion": "passed"}]), encoding="utf-8")
    token = tmp_path / "token.txt"
    token.write_text("not-a-token", encoding="utf-8")
    probe = ("import json, sys\nfrom knos import decide\ncode = decide.main(sys.argv[1:])\n"
             "print(json.dumps({'code': code, 'loaded': sorted(m for m in sys.modules if m.split('.')[0] in ('typer', 'click', 'rich', 'solders') "
             "or m == 'knos.settle.v2.relay')}), file=sys.stderr)\n")
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src"), "KNOS_ISSUER_KEYS": str(tmp_path / "no-keys.json")}

    def run(*args: str) -> tuple[dict, str]:
        done = subprocess.run([sys.executable, "-c", probe, *args], capture_output=True, text=True, encoding="utf-8", env=env, timeout=120)
        assert done.returncode == 0, done.stderr
        return json.loads(done.stderr.strip().splitlines()[-1]), done.stdout
    said, out = run("--checks-file", str(checks))
    assert said == {"code": 0, "loaded": []} and json.loads(out)["decision"] == "accepted"          # the free check: neither typer nor the relay
    said, out = run("--token-file", str(token), "--no-chain", "--out", str(tmp_path / "p.json"))
    assert said["code"] == 1 and "knos.settle.v2.relay" in said["loaded"] and not {"typer", "click", "rich"} & {m.split(".")[0] for m in said["loaded"]}
    assert out.startswith("Provisional: rejected (this is not a token GitHub Actions or GitLab CI issued)")
    assert decide.check(json.loads((tmp_path / "p.json").read_text(encoding="utf-8"))) is None
    # one thing to decide, or the usage and exit 2, as the typer command gives
    none = subprocess.run([sys.executable, "-m", "knos.decide"], capture_output=True, text=True, encoding="utf-8", env=env, timeout=120)
    assert none.returncode == 2 and "give --token-file or --checks-file, one of them" in none.stderr
    src = (ROOT / "src" / "knos" / "decide.py").read_text(encoding="utf-8")
    assert "argparse.ArgumentParser(" in src.split("\ndef main(")[1] and "typer" not in src.split("\ndef main(")[1].split('"""', 2)[2]


def test_a_decider_is_built_before_the_evidence_and_answers_as_the_offline_half_does_with_nothing_kept_between_tokens(env):
    c, _net = env
    now, keys = c.now(), _kept()
    fund, other = t2.faucet_jwt(c, t2.issue(), t2.user(), t2.user()), t2.faucet_jwt(c, t2.issue(), t2.user(), t2.user())
    forged = fund[:-6] + ("AAAAAA" if not fund.endswith("AAAAAA") else "BBBBBB")
    warm = decide.Decider(keys)
    assert warm.loaded_ms >= 0

    cases = ((fund, t2.TERMS, now), (forged, t2.TERMS, now), (other, t2.TERMS, now), (fund, None, now), (fund, t2.TERMS, now + 3 * 3600), ("not a token", None, now),
             (fund, t2.TERMS, now))
    first = [warm.offline(jwt, terms, now=at) for jwt, terms, at in cases]
    again = [warm.offline(jwt, terms, now=at) for jwt, terms, at in reversed(cases)][::-1]
    assert first == again == [decide.offline(jwt, terms, keys=keys, now=at) for jwt, terms, at in cases]        # order and history change nothing
    assert [d["decision"] for d in first] == ["accepted", "rejected", "accepted", "rejected", "rejected", "rejected", "accepted"]
    assert first[1]["why"] == "the signature is not the issuer's"       # a forged token after a good one: nothing remembered lets it through
    assert decide.Decider({}).offline(fund, t2.TERMS, now=now)["decision"] == "insufficient_evidence"


def test_the_stream_decides_one_token_a_line_in_one_process_and_times_each_from_the_line_in_hand(env, tmp_path, capsys):
    c, _net = env
    now, keys = c.now(), _kept()
    fund = t2.faucet_jwt(c, t2.issue(), t2.user(), t2.user())
    lines = [fund, "", json.dumps({"token": fund, "terms": t2.TERMS.decode(), "kind": "fund"}), f"<!-- knos-fund: {fund} -->", "junk", '{"token": 7}']
    out: list[str] = []
    got = decide.stream(lines, out.append, keys=keys, clock=lambda: now)
    rows = [json.loads(line) for line in out]
    assert got["n"] == len(rows) == 5 and got["accepted"] == 1 and round(got["slowest_ms"], 3) == max(r["ms"] for r in rows) < 2000
    assert [r["decision"] for r in rows] == ["rejected", "accepted", "rejected", "rejected", "rejected"]      # only the line that carries its terms
    assert rows[0]["why"] == rows[2]["why"] == "its terms are missing, or are not the terms the token names"
    for r in rows:
        assert set(r) == {"decision", "why", "kind", "ms", "provisional_sha256", "provisional"} and decide.check(r["provisional"]) is None
        assert r["provisional_sha256"] == decide.digest(r["provisional"]) and r["provisional"]["authorises_payment"] is False
        assert r["provisional"]["rules"]["by"] == "knos.decide.offline" and r["provisional"]["decided_at"] == now
    assert rows[1]["provisional"] == decide.provisional(decide.offline(fund, t2.TERMS, keys=keys, now=now), at=now, jwt=fund, terms=t2.TERMS)
    # the command: the rules are loaded once and said apart; it takes no other thing to decide; all accepted or exit 1
    file = decide.keep_keys(keys, at=now, path=tmp_path / "keys.json")
    said: list[str] = []
    assert decide.command(keys_file=file, stream_lines=["junk"], say=out.append, note=said.append) == 1
    assert said[0].startswith("rules loaded in ") and "decided 1 offline, 0 accepted" in said[1] and "nothing was fetched" in said[1]
    assert decide.command(keys_file=file, stream_lines=[], say=out.append, note=said.append) == 1              # nothing decided is not a pass
    with pytest.raises(ValueError, match="--stream reads its tokens from standard input"):
        decide.command(token_file=tmp_path / "t.txt", stream_lines=[], say=out.append, note=said.append)
    # the one-shot command says the load and the decision apart
    (tmp_path / "t.txt").write_text(fund, encoding="utf-8")
    said.clear()
    decide.command(token_file=tmp_path / "t.txt", keys_file=file, no_chain=True, out=tmp_path / "p.json", say=out.append, note=said.append)
    assert " (rules loaded in " in said[-1] and " ms, offline " in said[-1] and said[-1].startswith("decided in ")
