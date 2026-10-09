"""Policy met is not agreed: every statement line carries four steps, recorded apart (policy satisfied, parties accepted,
payment authorised, settled), and a line whose evidence met the terms that the buyer refused, or left unauthorised
past the acceptance window, is owed to the supplier: a wrongful refusal, counted beside the unsupported charges.

The public sample (examples/shadow/) is the case that was found: two lines totalling 650.00 read "agreed" while nobody
had approved them. Old statement files still read: the key `agreed` is kept and its words say what it means.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from knos import ids, recall, statement
from knos.proof import history

ROOT = Path(__file__).resolve().parents[1]
DAY = "2026-10-06"
TERMS = "d4" * 32


def sample() -> dict:
    text = (ROOT / "examples" / "shadow" / "invoice.csv").read_text(encoding="utf-8")
    answers = json.loads((ROOT / "examples" / "shadow" / "recorded.json").read_text(encoding="utf-8"))
    return statement.from_shadow({"invoice": text, "answers": answers}, {"currency": "USD"})


def met(st: dict) -> list[dict]:
    return [ln for ln in st["lines"] if ln["state"] == "agreed"]


def test_the_sample_no_longer_calls_650_agreed_while_nobody_approved_it():
    st = sample()
    assert [ln["amount"] for ln in met(st)] == ["400.00", "250.00"] and st["totals"]["agreed"]["amount"] == "650.00"
    said = dict(statement.answers(st))
    assert said["Policy met"] == "2 lines, 650.00 USD: the evidence met the terms, nothing more"
    assert said["Accepted"] == "0 lines, 0.00 USD" and said["Approved"] == "nobody yet" and said["Payable"] == "0 lines, 0.00 USD authorised, not paid"
    words = statement.as_csv(st)
    assert ",agreed," not in words and "Passed" not in words and "total,policy met,2,650.00" in words
    for r in statement.lines_now(st):
        if r["state"] == "agreed":
            assert [(x["step"], x["state"]) for x in r["steps"]] == [("policy", "done"), ("accepted", "open"), ("authorised", "open"), ("settled", "open")]


def test_four_steps_are_recorded_apart_and_in_words():
    st = sample()
    one, five = met(st)
    s = statement.accept(st, None, "Dana", "AP lead", DAY, [one["invoice_line"]])
    r = {x["invoice_line"]: x for x in statement.lines_now(st, s)}
    assert [x["state"] for x in r[one["invoice_line"]]["steps"]] == ["done", "done", "open", "open"]       # accepted is not authorised
    s = statement.approve(st, s, "Dana", "AP lead", DAY)
    s = statement.pay(st, s, one["invoice_line"], "bank", "BACS 1", DAY)
    steps = {x["invoice_line"]: x for x in statement.lines_now(st, s)}[one["invoice_line"]]["steps"]
    assert [x["state"] for x in steps] == ["done", "done", "done", "done"]
    assert steps[1]["said"] == f"by Dana (AP lead) on {DAY}" and steps[2]["said"].startswith(f"by Dana (AP lead) on {DAY}, under knos statement approve")
    assert steps[3]["said"] == f"paid outside Knos by bank, reference BACS 1, on {DAY}"
    assert [x["state"] for x in {x["invoice_line"]: x for x in statement.lines_now(st, s)}[five["invoice_line"]]["steps"]] == ["done", "open", "done", "open"]
    assert tuple(x["step"] for x in steps) == ids.STEPS and set(ids.STEP_WORDS) == set(ids.STEPS)


def test_old_words_and_old_files_still_read():
    assert ids.LINE_STATES == ("agreed", "disputed", "duplicate", "insufficient_evidence")          # the keys files hold
    assert "agreed" not in ids.LINE_WORDS.values() and ids.LINE_WORDS["agreed"] == "policy met"
    assert [ids.line_state(w) for w in ("agreed", "policy met", "Policy-Met", "clean", "failed", "billed twice", "unverified", "duplicate")] == [
        "agreed", "agreed", "agreed", "agreed", "disputed", "duplicate", "insufficient_evidence", "duplicate"]
    with pytest.raises(ValueError, match="not a line state"):
        ids.line_state("paid")
    old = json.loads((ROOT / "tests" / "data" / "statement" / "sept.json").read_text(encoding="utf-8"))
    status = json.loads((ROOT / "tests" / "data" / "statement" / "sept.status.json").read_text(encoding="utf-8"))
    assert statement.digest(old) == old["sha256"]                                                  # a file made before still checks
    now = statement.lines_now(old, status)
    assert [r["steps"][2]["state"] for r in now] == ["done", "open", "open", "open", "done"]        # its approval reads as authorised
    assert [r["steps"][1]["state"] for r in now] == ["open"] * 5                                    # and nobody claimed acceptance for it


def test_a_refused_line_whose_policy_is_met_is_owed_and_counted_as_a_wrongful_refusal():
    st = sample()
    one, five = met(st)
    disputed = next(ln for ln in st["lines"] if ln["state"] == "disputed")
    s = statement.refuse(st, None, five["invoice_line"], "Dana", "AP lead", DAY, "not needed")
    s = statement.refuse(st, s, disputed["invoice_line"], "Dana", "AP lead", DAY, "a check failed")
    r = {x["invoice_line"]: x for x in statement.lines_now(st, s)}
    assert r[five["invoice_line"]]["owed"] is True and r[five["invoice_line"]]["steps"][1] == {
        "step": "accepted", "state": "failed", "said": f"refused by Dana (AP lead) on {DAY}: not needed"}
    assert r[disputed["invoice_line"]]["owed"] is False                                            # the other way: refused and not owed
    said = dict(statement.answers(st, s))
    assert said["Wrongful refusals"].startswith("1 line, 250.00 USD, owed to the supplier") and "the supplier may appeal" in said["Wrongful refusals"]
    assert said["Unsupported charges"] == "4 lines, 1750.00 USD, not owed"
    after = statement.approve(st, s, "Dana", "AP lead", DAY)                                       # a blanket approval leaves the refused line out
    assert after["events"][-1]["lines"] == [one["invoice_line"]]
    assert "refusal" in statement.as_csv(st, s) and "refused: not needed" in statement.as_csv(st, s)
    with pytest.raises(statement.Refused, match="--why"):
        statement.refuse(st, None, five["invoice_line"], "Dana", "AP lead", DAY, " ")


def test_silence_past_the_window_is_owed_and_inside_it_is_not():
    st = sample()                                                                                   # the statement's day: the last merge, 2026-09-07
    assert st["date"] == "2026-09-07"
    inside = statement.lines_now(st, None, "2026-10-07")
    past = statement.lines_now(st, None, "2026-10-08")
    assert [r["owed"] for r in inside] == [False] * 7
    assert [r["line"] for r in past if r["owed"]] == [1, 5]
    assert dict(statement.answers(st, None, "2026-10-08"))["Wrongful refusals"].startswith("2 lines, 650.00 USD, owed to the supplier")
    authorised = statement.approve(st, None, "Dana", "AP lead", "2026-09-08")
    assert not any(r["owed"] for r in statement.lines_now(st, authorised, "2026-12-01"))          # authorised, not paid: payable, not wrongly refused
    assert [r["line"] for r in statement.lines_now(st, None, "2026-10-08", window=60) if r["owed"]] == []


def test_a_closed_month_is_accepted_by_both_ledgers(monkeypatch):
    st = {**sample(), "source": "month"}
    assert {r["steps"][1]["said"] for r in statement.lines_now(st) if r["state"] == "agreed"} == {"by the buyer and the supplier: both ledgers, month closed 2026-09-07"}


def test_a_decision_is_remembered_and_recalled_when_the_same_supplier_and_terms_return(tmp_path):
    pytest.importorskip("sibyl_memory_client")
    st = sample()
    five = met(st)[1]
    store = history.SibylStore.for_buyer("Northwind", tmp_path / "memory")
    s = statement.refuse(st, None, five["invoice_line"], "Dana", "AP lead", DAY, "not needed")
    kept = recall.decision_made(store, st, s["events"][-1], TERMS)
    assert [(k["deliverable"], k["decision"], k["by"]) for k in kept] == [(five["deliverable"], "refused", "Dana")]
    assert recall.decision_made(store, st, s["events"][-1], TERMS) == kept and len(history.line_decisions(store, five["supplier"], TERMS)) == 1    # once
    s = statement.approve(st, s, "Dana", "AP lead", DAY)
    recall.decision_made(store, st, s["events"][-1], TERMS)
    again = history.SibylStore.for_buyer("Northwind", tmp_path / "memory")                          # the same supplier and terms come back, later
    rows = {r["line"]: r for r in recall.decisions(again, st, TERMS)}
    assert rows[5]["same"] and rows[5]["words"] == "Refused before by Dana (AP lead) on 2026-10-06: not needed."
    assert rows[1]["words"] == "Authorised for payment before by Dana (AP lead) on 2026-10-06."
    assert 2 not in rows and 3 not in rows                                                          # another line's decision says nothing of a failed one
    assert recall.decisions(again, st, "e5" * 32) == []                                             # other terms: nothing recalled
    assert {r["kind"] for r in rows.values()} == {recall.DECISION_SCHEMA}


def test_with_no_memory_nothing_is_kept_or_recalled():
    st = sample()
    s = statement.approve(st, None, "Dana", "AP lead", DAY)
    store = history.NullStore()
    assert recall.decision_made(store, st, s["events"][-1], TERMS) == [] and recall.decisions(store, st, TERMS) == []
    assert history.line_decisions(store, st["supplier"], TERMS) == []
    with pytest.raises(ValueError, match="terms hash"):
        history.line_decided(store, "acme", "not-a-hash", "dlv_x", "refused", "Dana", "AP lead")


def test_the_commands_accept_refuse_and_show_the_steps(tmp_path):
    import typer
    from typer.testing import CliRunner
    app = typer.Typer()
    statement.register(app)
    run = CliRunner()
    file = tmp_path / "ap-statement.json"
    st = sample()
    file.write_bytes(statement.canonical(st))
    five = met(st)[1]

    def ok(*args) -> str:
        got = run.invoke(app, [str(a) for a in args])
        assert got.exit_code == 0, got.output
        return got.output

    shown = ok("statement", "show", file, "--on", "2026-10-08")
    assert "OWED TO THE SUPPLIER" in shown and "knos appeal" in shown and "agreed" not in shown.replace("--agreed", "")
    ok("statement", "refuse", file, "--line", five["invoice_line"], "--by", "Dana", "--role", "AP lead", "--why", "not needed", "--on", DAY)
    ok("statement", "accept", file, "--by", "Dana", "--role", "AP lead", "--on", DAY)
    shown = ok("statement", "show", file, "--on", DAY)
    assert "NOT parties accepted: refused by Dana (AP lead) on 2026-10-06: not needed" in shown and "parties accepted: by Dana (AP lead)" in shown
    status = json.loads((tmp_path / "ap-statement.status.json").read_text(encoding="utf-8"))
    assert [e["type"] for e in status["events"]] == ["refusal", "acceptance"] and status["events"][1]["lines"] == [met(st)[0]["invoice_line"]]
