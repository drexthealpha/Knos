"""knos.period: each party signs a month (Ed25519); a month closes by both signatures or by a closure the terms allow.
The stand-alone verifier an archive carries checks the same, with nothing but Python. Fixed keys, no clock, no network."""
from __future__ import annotations

import json
import subprocess
import sys

import pytest
from solders.keypair import Keypair

from knos import archive as A
from knos import ids
from knos import events as E
from knos import period as P
from knos import standalone_verify as V
from knos import terms3
from knos.ledger import Bad

BUYER_KEY, SUPPLIER_KEY, OTHER_KEY = Keypair.from_seed(bytes([1] * 32)), Keypair.from_seed(bytes([2] * 32)), Keypair.from_seed(bytes([3] * 32))
MONTH = 202610


def _terms(silence: int = 0) -> dict:
    doc = terms3.template("bug-fix")
    doc["window"] = {"warranty_days": 0, "holdback_percent": 0,
                     "period_close": {"buyer_key": str(BUYER_KEY.pubkey()), "supplier_key": str(SUPPLIER_KEY.pubkey()), "silence_days": silence}}
    return terms3.validate(doc, strict=False)


def _log(lines: int = 3, month: int = MONTH) -> E.Log:
    log = E.Log()
    assert E.ingest(log, [E.invoice_line("7", "INV-7", n, "import", deliverable=ids.deliverable("ab" * 32, n), month=month, amount=2_000_000, unit="units")
                          for n in range(lines)]).ok
    return log


def _more(log: E.Log, n: int, month: int = MONTH) -> E.Log:
    assert E.ingest(log, [E.invoice_line("7", "INV-7", n, "import", deliverable=ids.deliverable("ab" * 32, n), month=month, amount=1_000_000, unit="units")]).ok
    return log


def _both(log: E.Log, doc: dict) -> list[dict]:
    h = terms3.digest(doc)
    return [P.acknowledge(BUYER_KEY, log, MONTH, "buyer", h, "2026-11-02"), P.acknowledge(SUPPLIER_KEY, log, MONTH, "supplier", h, "2026-11-03")]


def test_the_stand_alone_ed25519_agrees_with_solders():
    msg = b"knos-period-ack/v1\nrole buyer\n"
    sig = bytes(BUYER_KEY.sign_message(msg))
    assert V.ed25519(bytes(BUYER_KEY.pubkey()), msg, sig)
    assert not V.ed25519(bytes(BUYER_KEY.pubkey()), msg + b"x", sig)
    assert not V.ed25519(bytes(SUPPLIER_KEY.pubkey()), msg, sig)
    assert V.b58(str(SUPPLIER_KEY.pubkey())) == bytes(SUPPLIER_KEY.pubkey())


def test_terms_name_the_keys_and_say_so():
    doc = _terms(silence=10)
    assert terms3.period_close(doc)["silence_days"] == 10
    assert "both sign its last line, or when one signed and the other has not answered in 10 days." in doc["window"]["says"]
    assert terms3.period_close(terms3.template("bug-fix")) is None          # terms without it are the terms they were
    bad = dict(doc, window={**doc["window"], "period_close": {**doc["window"]["period_close"], "supplier_key": str(BUYER_KEY.pubkey())}})
    with pytest.raises(terms3.Refused, match="two keys"):
        terms3.validate(bad, strict=False)


def test_both_acknowledgements_close_the_month():
    log, doc = _log(), _terms()
    acks = _both(log, doc)
    got = P.check(log, acks, [doc])[MONTH]
    assert got["closed"] and got["problems"] == [] and "both parties signed line 2" in got["how"]
    assert P.close_problems(log, MONTH, acks, [doc]) == []
    assert E.close_problems(log, MONTH, acks=acks, terms_docs=[doc]) == []


def test_one_acknowledgement_does_not_close_the_month():
    log, doc = _log(), _terms()
    one = _both(log, doc)[:1]
    said = P.close_problems(log, MONTH, one, [doc])
    assert said and said[0].startswith("OPEN:") and "buyer's acknowledgement" in said[0]
    assert E.close_problems(log, MONTH, acks=[], terms_docs=[doc])[0].startswith("Nobody has signed")


def test_a_key_the_terms_do_not_name_is_refused():
    log, doc = _log(), _terms()
    stranger = P.acknowledge(OTHER_KEY, log, MONTH, "supplier", terms3.digest(doc), "2026-11-03")
    got = P.check(log, [_both(log, doc)[0], stranger], [doc])[MONTH]
    assert not got["closed"] and "not by the key the terms name for the supplier" in got["problems"][0]


def test_an_edited_acknowledgement_fails_its_signature():
    log, doc = _log(), _terms()
    a, b = _both(log, doc)
    b = {**b, "events": b["events"] + 1}
    assert "the signature is not that key's" in P.check(log, [a, b], [doc])[MONTH]["problems"][0]


def test_a_closure_after_the_silence_the_terms_allow():
    log, doc = _log(), _terms(silence=10)
    a = _both(log, doc)[0]
    early = P.close_alone(BUYER_KEY, a, 10, "2026-11-05")
    assert not P.check(log, [a, early], [doc])[MONTH]["closed"]
    late = P.close_alone(BUYER_KEY, a, 10, "2026-11-12")
    got = P.check(log, [a, late], [doc])[MONTH]
    assert got["closed"] and "after 10 days without an answer" in got["how"]
    no_rule = _terms(silence=0)
    a0 = P.acknowledge(BUYER_KEY, log, MONTH, "buyer", terms3.digest(no_rule), "2026-11-02")
    got0 = P.check(log, [a0, P.close_alone(BUYER_KEY, a0, 0, "2027-01-01")], [no_rule])[MONTH]
    assert not got0["closed"] and "no closure without both acknowledgements" in got0["problems"][0]


def test_missing_after_ack_is_a_named_discrepancy():
    log, doc = _log(4), _terms()
    acks = _both(log, doc)
    cut, _ = E.read("".join(e.line() + "\n" for e in log.events[:2]))
    got = P.check(cut, acks, [doc])[MONTH]
    assert not got["closed"] and got["problems"][0].startswith(V.MISSING_AFTER_ACK + ":") and "2 acknowledged lines are missing" in got["problems"][0]


def test_changed_after_ack_is_a_named_discrepancy():
    log, doc = _log(3), _terms()
    acks = [P.acknowledge(k, log, MONTH, r, terms3.digest(doc), "2026-11-02", last=1) for k, r in ((BUYER_KEY, "buyer"), (SUPPLIER_KEY, "supplier"))]
    other = _log(1)
    _more(other, 9)
    _more(other, 2)
    assert P.check(other, acks, [doc])[MONTH]["problems"][0].startswith(V.CHANGED_AFTER_ACK + ":")


def test_an_event_after_the_close_is_a_named_discrepancy():
    log, doc = _log(3), _terms()
    acks = _both(log, doc)
    _more(log, 5)
    got = P.check(log, acks, [doc])[MONTH]
    assert got["closed"] and got["problems"] == [f"{V.AFTER_CLOSE}: line 3 belongs to {MONTH}, which was closed at line 2: it was added after the month closed"]
    _more(log, 6, month=202611)                     # another month's line is not late
    assert len(P.check(log, acks, [doc])[MONTH]["problems"]) == 1


def test_sign_refuses_a_line_the_log_does_not_have():
    with pytest.raises(Bad):
        P.acknowledge(BUYER_KEY, _log(2), MONTH, "buyer", "0" * 64, "2026-11-02", last=9)
    with pytest.raises(Bad):
        P.acknowledge(BUYER_KEY, _log(2), MONTH, "auditor", "0" * 64, "2026-11-02")


def _archive(log: E.Log, acks: list[dict], doc: dict) -> dict[str, bytes]:
    return A.files_of(events=log.text().encode(), terms=[terms3.dumps(doc).encode()], acks=[P.dumps(a).encode() for a in acks], sealed="2026-11-04")


def test_the_archive_carries_the_acknowledgements_and_its_verifier_checks_them(tmp_path):
    log, doc = _log(), _terms()
    files = _archive(log, _both(log, doc), doc)
    assert sum(1 for n in files if n.startswith("acks/")) == 2
    done, notes, problems = V.check(files)
    assert problems == [] and any(f"{MONTH} is closed: both parties signed line 2" in d for d in done)
    assert not any(n.startswith("UNSIGNED: nobody has acknowledged the log") for n in notes)
    assert A.holds(files) == []
    (tmp_path / "a.zip").write_bytes(A.pack(files))
    run = subprocess.run([sys.executable, "-I", str(V.__file__), str(tmp_path / "a.zip"), "--strict"], capture_output=True, encoding="utf-8")
    assert run.returncode == 0, run.stdout


def test_the_archive_verifier_names_a_month_left_open_and_an_event_after_close():
    log, doc = _log(), _terms()
    one = _archive(log, _both(log, doc)[:1], doc)
    done, notes, problems = V.check(one)
    assert problems == [] and any(n.startswith("OPEN:") for n in notes)
    assert any("is open" in w for w in A.holds(one))
    acks = _both(log, doc)
    _more(log, 8)
    _d, _n, problems = V.check(_archive(log, acks, doc))
    assert len(problems) == 1 and V.AFTER_CLOSE in problems[0]


def test_the_archive_verifier_names_lines_cut_after_an_acknowledgement():
    log, doc = _log(4), _terms()
    acks = _both(log, doc)
    cut, _ = E.read("".join(e.line() + "\n" for e in log.events[:3]))
    _d, _n, problems = V.check(_archive(cut, acks, doc))
    assert len(problems) == 2 and all(V.MISSING_AFTER_ACK in p for p in problems)


def test_the_cli_signs_and_closes(tmp_path):
    from typer.testing import CliRunner

    from knos import cli
    log, doc = _log(), _terms()
    (tmp_path / "log.jsonl").write_text(log.text(), encoding="utf-8")
    (tmp_path / "terms.json").write_text(terms3.dumps(doc), encoding="utf-8")
    for name, k in (("buyer", BUYER_KEY), ("supplier", SUPPLIER_KEY)):
        (tmp_path / f"{name}.key").write_text(json.dumps(list(bytes(k))), encoding="utf-8")
    run = CliRunner()
    base = ["events", "sign", str(tmp_path / "log.jsonl"), "--month", "2026-10", "--terms", str(tmp_path / "terms.json"), "--on", "2026-11-02"]
    for name in ("buyer", "supplier"):
        got = run.invoke(cli.app, [*base, "--role", name, "--key", str(tmp_path / f"{name}.key"), "--out", str(tmp_path / f"{name}.ack.json")])
        assert got.exit_code == 0, got.output
    wrong = run.invoke(cli.app, [*base, "--role", "buyer", "--key", str(tmp_path / "supplier.key")])
    assert wrong.exit_code != 0 and "the terms name" in str(wrong.exception)
    close = ["events", "close", str(tmp_path / "log.jsonl"), "--month", "2026-10", "--terms", str(tmp_path / "terms.json")]
    half = run.invoke(cli.app, [*close, "--ack", str(tmp_path / "buyer.ack.json")])
    assert half.exit_code != 0 and "is not closed" in str(half.exception)
    full = run.invoke(cli.app, [*close, "--ack", str(tmp_path / "buyer.ack.json"), "--ack", str(tmp_path / "supplier.ack.json")])
    assert full.exit_code == 0 and "can be closed" in full.output, full.output
