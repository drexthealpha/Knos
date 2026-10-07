"""`knos decide`: the decision is the relay's own reads, a provisional receipt never authorises payment, the final
receipt supersedes it by name, and both speed targets hold on this machine (scripts/decide_bench.py measures them)."""
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
    c, net = env
    fund, now, clock = t2.faucet_jwt(c, t2.issue(), t2.user(), t2.user()), c.now(), [100.0]
    kept = decide.Cached(net, ttl=30, clock=lambda: clock[0])
    first = decide.token(fund, t2.TERMS, ledger=kept, payer=c.payer, jwks=t2.JWKS, now=now)
    reads = kept.reads
    assert first["decision"] == "accepted" and reads > 0 and kept.hits == 0
    assert decide.token(fund, t2.TERMS, ledger=kept, payer=c.payer, jwks=t2.JWKS, now=now) == first and kept.reads == reads and kept.hits == reads
    clock[0] += 31                                              # past its time: the chain is asked again
    assert decide.token(fund, t2.TERMS, ledger=kept, payer=c.payer, jwks=t2.JWKS, now=now) == first and kept.reads == 2 * reads
    with pytest.raises(AttributeError, match="sends nothing"):
        kept.send([], c.payer)


def test_the_two_targets_hold_here_a_cached_decision_under_200_ms_and_evidence_to_decision_under_2_s():
    """Generous bounds on purpose: the measured figures are a few milliseconds (docs/BENCH.md, "Decision time"). The
    chain is LiteSVM in this process, so this is Knos's own time; a cluster's round trips are not in it."""
    bench = _script("decide_bench")
    r = bench.measure(12)
    rows = r["rows"]
    assert all(s["n"] == 12 for s in rows.values()) and set(rows) == {name for name, _t, _w in bench.ROWS}
    assert rows["cached, accepted"]["p95"] < 200 and rows["no chain"]["p95"] < 200 and rows["free check"]["p95"] < 200, rows
    assert rows["fresh, accepted"]["p95"] < 2000 and rows["fresh, rejected"]["p95"] < 2000, rows
    assert r["decisions"] == {"fresh, accepted": ["accepted"], "fresh, rejected": ["rejected"], "cached, accepted": ["accepted"],
                              "no chain": ["insufficient_evidence"], "free check": ["accepted"]}
    # the table states its machine and its sample, and the document holds what the script writes
    lines = bench.table(r, "2026-10-06")
    assert "on this machine: " in lines[0] and "no network" in lines[0] and "not been measured" in lines[0] and len(lines) == 4 + len(bench.ROWS)
    doc = (ROOT / "docs" / "BENCH.md").read_text(encoding="utf-8")
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
