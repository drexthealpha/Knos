"""`knos recall` answers from real events: a statement's lines that were set aside, how one of them ended, a correction
of a meter ledger, an appeal, and a closed month. Each is written through knos.proof.history where it happens
(knos.statement, knos.ledger, knos.appeal), into one buyer organisation's memory; with no --remember nothing is kept.
The close of a month is refused while the log of events has a number that never arrived.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import typer

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))

import test_events as TE                    # noqa: E402
import test_ledger_periods as TL            # noqa: E402
import test_statement as TS                 # noqa: E402

from knos import appeal, cli, events as E, ledger as L, recall, shadow, statement   # noqa: E402
from knos.proof import history              # noqa: E402

pytest.importorskip("sibyl_memory_client")
TERMS = "c3" * 32


def _store(tmp_path):
    return history.SibylStore.for_buyer("Northwind", tmp_path / "memory")


def test_a_statements_lines_that_were_set_aside_are_recalled_and_a_payment_ends_one(tmp_path):
    from typer.testing import CliRunner
    app = typer.Typer()
    shadow.register(app)
    statement.register(app)
    run = CliRunner()

    def ok(*args) -> str:
        got = run.invoke(app, [str(a) for a in args])
        assert got.exit_code == 0, got.output
        return got.output

    (tmp_path / "invoice.csv").write_text(TS.SEPT, encoding="utf-8")
    (tmp_path / "book.json").write_text(json.dumps(TS.BOOK), encoding="utf-8")
    out, memory = tmp_path / "sept", tmp_path / "memory"
    ok("shadow", tmp_path / "invoice.csv", "--recorded", tmp_path / "book.json", "--out", out)
    make = ["statement", "make", out / "evidence.json", "--invoice", "INV-2026-09", "--buyer", "Northwind", "--currency", "USD", "--date", "2026-09-30"]
    plain = ok(*make)
    assert "Remembered" not in plain and not memory.exists()                              # nothing is kept unless it is asked for
    said = ok(*make, "--remember", "Northwind", "--memory", memory, "--terms", TERMS)
    st = TS.sept()
    aside = [ln for ln in st["lines"] if ln["state"] != "agreed"]
    assert len(aside) == 3 and "Remembered for Northwind: 3 lines set aside." in said
    assert (out / "ap-statement.json").read_bytes() == statement.canonical(st)             # remembering changes no byte of the statement
    store = _store(tmp_path)
    assert sorted(r["id"] for r in recall.queue(store)) == sorted(ln["invoice_line"] for ln in aside)
    disputed = next(ln for ln in aside if ln["state"] == "disputed")
    before = recall.exception(store, TERMS, "disputed", disputed["supplier"])
    assert before["seen"] == 0 and before["open"] == 1
    assert run.invoke(app, ["statement", "make", str(out / "evidence.json"), "--remember", "Northwind", "--memory", str(memory), "--terms", "xyz"]).exit_code != 0
    # the buyer pays the disputed line after all: the exception ends, and the next one under the same terms is told so
    file = out / "ap-statement.json"
    paid = ok("statement", "pay", file, "--line", disputed["invoice_line"], "--ref", "BACS 9", "--on", "2026-10-03", "--remember", "Northwind", "--memory", memory, "--terms", TERMS)
    assert "this line had been set aside, and it ended accepted on appeal" in paid
    after = recall.exception(_store(tmp_path), TERMS, "disputed", disputed["supplier"])
    assert (after["seen"], after["endings"]["accepted_on_appeal"], after["open"]) == (1, 1, 0) and disputed["invoice_line"] not in [r["id"] for r in recall.queue(_store(tmp_path))]
    # an agreed line that is paid ends nothing, and a refund of a line set aside ends it refused
    agreed = next(ln for ln in st["lines"] if ln["state"] == "agreed")
    assert "Remembered" not in ok("statement", "pay", file, "--line", agreed["invoice_line"], "--ref", "BACS 10", "--on", "2026-10-03", "--remember", "Northwind", "--memory", memory, "--terms", TERMS)
    dup = next(ln for ln in aside if ln["state"] == "duplicate")
    assert "it ended refused" in ok("statement", "pay", file, "--line", dup["invoice_line"], "--ref", "CR 1", "--state", "refunded", "--on", "2026-10-04",
                                    "--remember", "Northwind", "--memory", memory, "--terms", TERMS)
    assert recall.exception(_store(tmp_path), TERMS, "duplicate")["endings"]["refused"] == 1


def test_with_no_terms_named_the_lines_are_kept_under_the_two_parties_and_no_other_pair_recalls_them(tmp_path):
    store, st = _store(tmp_path), TS.sept()
    opened = recall.statement_made(store, st, at=1_790_000_000.0)
    assert len(opened) == 3 and recall.statement_made(history.NullStore(), st) == []
    mine = recall.unnamed_terms(st["buyer"], st["lines"][0]["supplier"])
    assert mine != recall.unnamed_terms("Another buyer", st["lines"][0]["supplier"]) and len(mine) == 64
    assert recall.exception(store, mine, "disputed")["open"] == 1 and recall.exception(store, recall.unnamed_terms("Another buyer", "Acme Agents"), "disputed")["open"] == 0
    assert recall.statement_paid(store, st, {"state": "held", "line": opened[0]["id"]}) is None     # held ends nothing
    assert recall.memory_of("", tmp_path).__class__ is history.NullStore


def test_a_correction_and_a_closed_month_reach_memory_from_the_meters_commands(tmp_path, capsys):
    e = [TL._ev(i) for i in range(1, 9)]
    buyer, seller, memory = tmp_path / "buyer.jsonl", tmp_path / "seller.jsonl", tmp_path / "memory"
    buyer.write_text(L.dump(s.batch() for s in TL._raw(e[:4], e[3:6])), encoding="utf-8", newline="\n")       # e[3] anchored twice
    seller.write_text(L.dump(s.batch() for s in TL._book(e[:6], e[6:])), encoding="utf-8", newline="\n")
    rc, said = TL._run(capsys, "correct", str(buyer), e[3].id.hex(), "--batch", "202610.1", "--kind", "duplicate", "--remember", "Northwind", "--memory", str(memory), "--terms", TERMS)
    assert rc == 0 and "Remembered for Northwind: `knos recall exception --reason correction-duplicate` counts it." in said
    row = recall.exception(_store(tmp_path), TERMS, "correction-duplicate")
    assert row["seen"] == 1 and row["endings"]["refused"] == 1 and row["cases"][0]["period"] == "202610"
    assert TL._run(capsys, "correct", str(buyer), e[3].id.hex(), "--batch", "202610.1", "--kind", "duplicate", "--remember", "Northwind", "--memory", str(memory), "--terms", "no")[0] == 1
    assert cli.main(["recall", "exception", "--buyer", "Northwind", "--memory", str(memory), "--terms", TERMS, "--reason", "correction-duplicate", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["seen"] == 1


def test_a_month_is_not_closed_over_a_number_that_never_arrived(tmp_path, capsys):
    e = [TL._ev(i) for i in range(1, 5)]
    buyer, seller, close_file = tmp_path / "buyer.jsonl", tmp_path / "seller.jsonl", tmp_path / "close.json"
    for path in (buyer, seller):
        path.write_text(L.dump(s.batch() for s in TL._book(e[:2], e[2:])), encoding="utf-8", newline="\n")
    whole, holed = tmp_path / "whole.jsonl", tmp_path / "holed.jsonl"
    whole.write_text(TE._batches(0, 1, 2).text(), encoding="utf-8", newline="\n")
    holed.write_text(TE._batches(0, 2).text(), encoding="utf-8", newline="\n")
    rc, said = TL._run(capsys, "close", str(buyer), str(seller), "--month", "2026-10", "--out", str(close_file), "--events", str(holed))
    assert rc == 1 and f"2026-10 is not closed: Number 1 of {TE.STREAM} never arrived." in said and "Nothing was written." in said and not close_file.exists()
    rc, said = TL._run(capsys, "close", str(buyer), str(seller), "--month", "2026-10", "--out", str(close_file), "--events", str(whole),
                       "--remember", "Northwind", "--memory", str(tmp_path / "memory"))
    assert rc == 0 and "202610 is AGREED" in said and "Remembered for Northwind: the month's 0 ended exception(s) are archived." in said and close_file.exists()
    assert E.close_problems(E.load(whole), 202610) == []


def test_an_appeal_that_is_remembered_is_an_exception_under_its_terms(tmp_path):
    store = _store(tmp_path)
    opened = appeal.open_(repo="acme/app", pull=7, supplier="Nimbus", by="Nimbus", reason="the check that failed is flaky", at=1_790_000_000.0, terms_hash=TERMS,
                          evaluation="evl_" + "1" * 24, deliverable="dlv_" + "2" * 24)
    appeal.remember(store, opened)
    assert [r["id"] for r in recall.queue(store)] == [opened["id"]] and recall.exception(store, TERMS, "rejected", "Nimbus")["open"] == 1
    ended = appeal.resolve(opened, 1_790_000_000.0 + 7200, ruling={"by": "arbiter-ann", "accepted": True, "why": "the check was flaky"})
    appeal.remember(store, ended)
    row = recall.exception(store, TERMS, "rejected", "Nimbus")
    assert (row["seen"], row["endings"]["accepted_on_appeal"], row["open"]) == (1, 1, 0) and row["seconds"]["median"] == 7200
    appeal.remember(history.NullStore(), opened)                                             # no memory: nothing is kept and nothing fails
