"""`knos recall exception`: how the same exception under the same terms ended before, from the memory engine.

What these show: the answer survives a new process; each of the engine's five tiers holds the part it is named for;
the engine's store is the only place any of it is kept; one buyer organisation never answers for another; and with
no memory (history.NullStore) the same calls answer nothing.
"""

from __future__ import annotations

import contextlib
import json
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from knos import recall, store
from knos.proof import history

ROOT = Path(__file__).resolve().parents[1]
TERMS, OTHER = "a1" * 32, "b2" * 32
T0 = 1_790_000_000.0            # a fixed clock: 2026-09-21 UTC
DAY = 86400.0
TEXT = "Pay when the named tests pass on the merged commit. Appeals within 7 days."


def _open(tmp_path, buyer="Acme Corp"):
    return history.SibylStore.for_buyer(buyer, tmp_path / "memory")


def _fill(st) -> None:
    """Three disputed lines of one supplier under TERMS: two won on appeal, one refused; and one of another supplier."""
    history.terms_text(st, TERMS, TEXT)
    for n, (ending, days) in enumerate((("accepted_on_appeal", 2), ("refused", 5), ("accepted_on_appeal", 3)), 1):
        history.exception_opened(st, TERMS, "disputed", "Nimbus", f"inv_{n:04d}", [f"evl_{n:04d}"], at=T0 + n)
        history.exception_resolved(st, TERMS, "disputed", "nimbus", f"inv_{n:04d}", ending, [f"dlv_{n:04d}"], at=T0 + n + days * DAY)
    history.exception_resolved(st, TERMS, "disputed", "orbit", "inv_0009", "corrected_and_passed", ["evl_0009"], opened_at=T0, at=T0 + DAY)
    history.exception_opened(st, TERMS, "disputed", "nimbus", "inv_0004", ["evl_0004"], at=T0 + 9 * DAY)


def _tables(db: Path, tenant: str) -> dict[str, int]:
    with contextlib.closing(sqlite3.connect(db)) as con:
        return {t: con.execute(f"select count(*) from {t} where tenant_id = ?", (tenant,)).fetchone()[0]   # noqa: S608 - fixed names
                for t in ("state_documents", "entities", "journal_events", "reference_documents", "archived_entities")}


def test_recall_says_how_the_same_exception_ended_before(tmp_path):
    st = _open(tmp_path)
    _fill(st)
    row = recall.exception(st, TERMS, "disputed", "Nimbus")
    assert row["kind"] == "knos.recall/1" and row["seen"] == 3 and row["memory"] is True and row["terms_text_kept"] is True
    assert row["endings"] == {"accepted_on_appeal": 2, "corrected_and_passed": 0, "refused": 1} and row["most_often"] == "accepted_on_appeal"
    assert row["seconds"] == {"median": 3 * DAY, "fastest": 2 * DAY, "slowest": 5 * DAY, "timed": 3}
    assert row["evidence"][:2] == ["evl_0002", "dlv_0002"] and set(row["evidence"]) == {f"{k}_000{n}" for k in ("evl", "dlv") for n in (1, 2, 3)}
    assert [c["id"] for c in row["cases"]] == ["inv_0002", "inv_0003", "inv_0001"] and row["open"] == 1
    assert row["said"] == "refused after 432000 s: disputed (nimbus)"          # the journal's own line for the newest
    assert row["words"] == "Seen 3 times under these terms: 2 accepted on appeal, 1 refused. Median time to end: 3 days."
    everyone = recall.exception(st, TERMS, "disputed")
    assert everyone["seen"] == 4 and everyone["endings"]["corrected_and_passed"] == 1 and everyone["supplier"] == ""
    for terms, reason, who in ((OTHER, "disputed", "nimbus"), (TERMS, "duplicate", "nimbus"), (TERMS, "disputed", "nobody")):
        got = recall.exception(st, terms, reason, who)                          # other terms, another reason, another supplier
        assert got["seen"] == 0 and got["cases"] == [] and got["words"] == "Not seen before under these terms."


def test_each_tier_holds_the_part_it_is_named_for(tmp_path):
    st = _open(tmp_path)
    _fill(st)
    closed = history.period_closed(st, "202609", at=T0 + 40 * DAY)
    assert closed["resolved"] == 4 and closed["endings"] == {"accepted_on_appeal": 2, "corrected_and_passed": 1, "refused": 1}
    assert history.period_closed(st, "202609", at=T0 + 99 * DAY) == closed and history.periods_closed(st) == [closed]   # closed once
    got = _tables(tmp_path / "memory" / "sibyl.db", store.buyer_tenant("Acme Corp"))
    assert got == {"state_documents": 1,        # HOT: the live queue, one document
                   "entities": 2,               # WARM: one entity per supplier-and-terms (nimbus, orbit)
                   "journal_events": 4,         # COLD: one event per resolution
                   "reference_documents": 1,    # REFERENCE: the text of the terms
                   "archived_entities": 1}      # ARCHIVE: the closed period
    assert [r["id"] for r in history.exception_queue(st)] == ["inv_0004"]
    assert history.terms_text(st, TERMS) == TEXT
    with pytest.raises(ValueError):
        history.terms_text(st, TERMS, TEXT + " And more.")                       # a text is not replaced under its hash
    assert recall.exception(st, TERMS, "disputed")["seen"] == 4                  # closing a period loses no recall
    assert [r["id"] for r in recall.queue(st)] == ["inv_0004"] and recall.queue(st)[0]["seen"] == 3


def test_the_same_exception_is_one_memory_and_its_later_ending_stands(tmp_path):
    st = _open(tmp_path)
    for _ in range(2):
        history.exception_resolved(st, TERMS, "tests-touched", "nimbus", "evl_01", "refused", opened_at=T0, at=T0 + 60)
    assert recall.exception(st, TERMS, "tests-touched")["endings"]["refused"] == 1 and len(st.events()) == 1
    history.exception_resolved(st, TERMS, "tests-touched", "nimbus", "evl_01", "accepted_on_appeal", opened_at=T0, at=T0 + 120)
    row = recall.exception(st, TERMS, "tests-touched")
    assert row["seen"] == 1 and row["endings"] == {"accepted_on_appeal": 1, "corrected_and_passed": 0, "refused": 0}
    assert len(st.events()) == 2                                                 # the journal keeps both: it is never rewritten
    for bad in (dict(terms="short"), dict(reason="Not A Code"), dict(ending="forgiven"), dict(period="2026-09"), dict(supplier="")):
        args = {"terms": TERMS, "reason": "disputed", "supplier": "nimbus", "exception_id": "x", "ending": "refused", **bad}
        with pytest.raises(ValueError):
            history.exception_resolved(st, **args)


_WRITE = """
import sys
from knos import recall
from knos.proof import history
st = history.SibylStore.for_buyer("Acme Corp", sys.argv[1])
appeal = {"id": "evl_aa", "terms_hash": sys.argv[2], "supplier": "nimbus", "was": "rejected", "evaluation": "evl_aa", "deliverable": "dlv_aa",
          "at": 1790000000, "state": "open", "history": [{"at": 1790000000}]}
recall.appeal_moved(st, appeal)
recall.appeal_moved(st, {**appeal, "state": "accepted", "history": [{"at": 1790000000}, {"at": 1790172800}]})
"""
_READ = """
import json, sys
from knos import recall
from knos.proof import history
print(json.dumps(recall.exception(history.SibylStore.for_buyer("Acme Corp", sys.argv[1]), sys.argv[2], "rejected", "nimbus")))
"""


def _python(code: str, *args: str) -> str:
    got = subprocess.run([sys.executable, "-c", code, *args], capture_output=True, text=True, encoding="utf-8", timeout=120,
                         env={**__import__("os").environ, "PYTHONPATH": str(ROOT / "src")})
    assert got.returncode == 0, got.stderr
    return got.stdout


def test_a_recall_survives_a_restart_and_the_store_is_the_only_place_it_is_kept(tmp_path, knos_home):
    memory = tmp_path / "memory"
    before = {p for p in (*tmp_path.rglob("*"), *knos_home.rglob("*")) if p.is_file()}
    _python(_WRITE, str(memory), TERMS)                                          # one process writes and exits
    row = json.loads(_python(_READ, str(memory), TERMS))                         # another, started later, recalls
    assert row["seen"] == 1 and row["endings"]["accepted_on_appeal"] == 1 and row["seconds"]["median"] == 2 * DAY
    assert row["evidence"] == ["evl_aa", "dlv_aa"] and row["open"] == 0
    made = {p for p in (*tmp_path.rglob("*"), *knos_home.rglob("*")) if p.is_file()} - before
    assert made and all(p.parent == memory and p.name.startswith("sibyl.db") for p in made), sorted(map(str, made))   # no side file
    for p in made:
        p.unlink()                                                               # take the engine's store away
    gone = json.loads(_python(_READ, str(memory), TERMS))
    assert gone["seen"] == 0 and gone["cases"] == [] and gone["evidence"] == []  # and the recall goes with it


def test_one_buyer_organisation_never_answers_for_another(tmp_path):
    acme, other = _open(tmp_path, "Acme Corp"), _open(tmp_path, "Borealis")     # one file, two tenants
    _fill(acme)
    assert store.buyer_tenant("Acme Corp") != store.buyer_tenant("acme-corp") and store.buyer_tenant("Acme Corp") == store.buyer_tenant(" acme corp ")
    assert recall.exception(acme, TERMS, "disputed")["seen"] == 4
    row = recall.exception(other, TERMS, "disputed")
    assert row["seen"] == 0 and row["terms_text_kept"] is False and recall.queue(other) == [] and history.periods_closed(other) == []
    with pytest.raises(ValueError):
        store.buyer_tenant("  ")


def test_with_no_memory_every_answer_disappears(tmp_path):
    """The same calls against history.NullStore: this is the list of what the engine is needed for here."""
    real, null = _open(tmp_path), history.NullStore()
    for st in (real, null):
        _fill(st)
        history.period_closed(st, "202609", at=T0 + 40 * DAY)
    answers = {
        "how the exception ended before": lambda st: recall.exception(st, TERMS, "disputed", "nimbus")["seen"],
        "how long it took": lambda st: recall.exception(st, TERMS, "disputed", "nimbus")["seconds"],
        "the evidence ids": lambda st: recall.exception(st, TERMS, "disputed", "nimbus")["evidence"],
        "the journal's line": lambda st: recall.exception(st, TERMS, "disputed", "nimbus")["said"],
        "the live queue": lambda st: recall.queue(st),
        "the text of the terms": lambda st: history.terms_text(st, TERMS),
        "the closed periods": lambda st: history.periods_closed(st),
    }
    for what, ask in answers.items():
        assert ask(real), what
        assert not ask(null), what
    assert recall.exception(null, TERMS, "disputed")["memory"] is False


def test_the_hooks_for_a_line_and_a_correction(tmp_path):
    st = _open(tmp_path)
    line = {"state": "insufficient_evidence", "supplier": "nimbus", "invoice_line": "inv_77", "deliverable": "dlv_77", "evaluations": ["evl_77"]}
    assert recall.line_opened(st, TERMS, {**line, "state": "agreed"}) is None and recall.line_resolved(st, TERMS, {**line, "state": "agreed"}, "refused") is None
    assert recall.line_opened(st, TERMS, line, at=T0)["evidence"] == ["dlv_77", "evl_77"]
    assert recall.queue(st)[0]["id"] == "inv_77" and recall.queue(st)[0]["seen"] == 0
    assert recall.line_resolved(st, TERMS, line, "corrected_and_passed", at=T0 + 3600)["seconds"] == 3600 and recall.queue(st) == []
    assert recall.exception(st, TERMS, "insufficient_evidence", "nimbus")["words"] == \
        "Seen 1 time under these terms: 1 corrected and passed. Median time to end: 1 h."
    assert recall.correction_made(st, TERMS, "nimbus", "ab" * 32, "verdict", accepted=True, at=T0)["ending"] == "corrected_and_passed"
    assert recall.correction_made(st, TERMS, "nimbus", "cd" * 32, "duplicate", at=T0)["ending"] == "refused"
    assert recall.exception(st, TERMS, "correction-verdict")["seen"] == 1 and recall.exception(st, TERMS, "correction-duplicate")["seen"] == 1
    assert recall.appeal_moved(st, {"id": "e", "terms_hash": "", "supplier": "nimbus", "state": "open"}) is None
    assert [recall.took(x) for x in (None, 40, 720, 5 * 3600, DAY, 3 * DAY)] == ["", "40 s", "12 min", "5 h", "1 day", "3 days"]


def test_the_command_prints_the_row_the_queue_reads(tmp_path):
    typer = pytest.importorskip("typer")
    from typer.testing import CliRunner
    _fill(_open(tmp_path))
    app, lines = typer.Typer(), []
    recall.register(app, lines)
    app.command("noop")(lambda: None)
    assert lines == [("recall", "For money", "What memory holds: past exceptions, who approved what, what a supplier brings.")]
    args = ["recall", "exception", "--buyer", "Acme Corp", "--memory", str(tmp_path / "memory"), "--terms", TERMS, "--reason", "disputed"]
    got = CliRunner().invoke(app, [*args, "--supplier", "nimbus", "--json"])
    assert got.exit_code == 0, got.output
    assert json.loads(got.output) == recall.exception(_open(tmp_path), TERMS, "disputed", "nimbus")
    said = CliRunner().invoke(app, args).output
    assert said.startswith("Seen 4 times under these terms: 2 accepted on appeal, 1 corrected and passed, 1 refused.") and "Open now: 1." in said
    rows = json.loads(CliRunner().invoke(app, ["recall", "queue", "--buyer", "Acme Corp", "--memory", str(tmp_path / "memory"), "--json"]).output)
    assert [r["id"] for r in rows] == ["inv_0004"]
    assert CliRunner().invoke(app, [*args[:-1], "Not A Code"]).exit_code != 0


@pytest.mark.skipif(not shutil.which("node"), reason="needs node")
def test_the_site_module_draws_the_same_row(tmp_path):
    st = _open(tmp_path)
    _fill(st)
    rows = [recall.exception(st, TERMS, "disputed", "nimbus"), recall.exception(st, OTHER, "disputed")]
    script = ("import { recallHtml, took, SCHEMA, ENDINGS, WORDS } from " + json.dumps((ROOT / "web" / "recall.js").as_uri()) + ";"
              "const rows = JSON.parse(process.argv[1]);"
              "console.log(JSON.stringify({ html: recallHtml(rows), none: recallHtml([]), took: [40, 720, 18000, 259200].map(took), SCHEMA, ENDINGS, WORDS }));")
    got = subprocess.run([shutil.which("node"), "--input-type=module", "-e", script, json.dumps(rows)], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert got.returncode == 0, got.stderr
    out = json.loads(got.stdout)
    assert out["SCHEMA"] == recall.SCHEMA and out["ENDINGS"] == list(history.EXCEPTION_ENDINGS) and out["WORDS"] == recall.ENDING_WORDS
    assert out["took"] == [recall.took(x) for x in (40, 720, 18000, 259200)]
    assert out["html"].count('class="k-card rc-row"') == 2 and 'data-seen="3"' in out["html"] and 'data-seen="0"' in out["html"]
    assert "evl_0002" in out["html"] and "median <strong>3 days</strong>" in out["html"] and "This exception has not been seen before." in out["none"]


def _open_now(st) -> list[dict]:
    """Three exceptions open now, in the order they opened: a duplicate never seen before, a dispute of orbit (seen
    once), and a dispute of nimbus (with _fill and one more, accepted on appeal 3 of 4 times before)."""
    rows = [("inv_0101", "duplicate", "nimbus"), ("inv_0102", "disputed", "orbit"), ("inv_0103", "disputed", "nimbus")]
    return [{"id": i, "terms": TERMS, "reason": r, "supplier": s, "at": T0 + 20 * DAY + n, "evidence": [f"evl_{i[-4:]}"]}
            for n, (i, r, s) in enumerate(rows)]


def test_the_queue_is_ranked_and_labelled_from_memory_and_without_it_nothing_is(tmp_path):
    """Delete the memory layer and the approver's queue changes: with memory, an exception whose history shows one
    ending most times comes first, labelled ("ended accepted on appeal 3 of 4 times before"); with no memory the same
    open exceptions keep the order they opened in and carry no label."""
    st = _open(tmp_path)
    _fill(st)
    history.exception_resolved(st, TERMS, "disputed", "nimbus", "inv_0005", "accepted_on_appeal", ["evl_0005"], opened_at=T0, at=T0 + DAY)
    open_now = _open_now(st)
    got = recall.queue(st, open_now)
    assert [r["id"] for r in got] == ["inv_0103", "inv_0101", "inv_0102"] and [r["rank"] for r in got] == [1, 2, 3]
    assert got[0]["label"] == "ended accepted on appeal 3 of 4 times before"
    assert got[0]["pattern"] == {"ending": "accepted_on_appeal", "times": 3, "of": 4, "label": got[0]["label"]}
    assert got[1]["label"] == "" and got[2]["label"] == "" and got[2]["seen"] == 1      # once is no pattern
    null = recall.queue(history.NullStore(), open_now)
    assert [r["id"] for r in null] == ["inv_0101", "inv_0102", "inv_0103"] and all(r["label"] == "" and r["pattern"] is None for r in null)
    # a split history is no pattern: 3 accepted on appeal and 3 refused
    for eid in ("inv_0006", "inv_0007"):
        history.exception_resolved(st, TERMS, "disputed", "nimbus", eid, "refused", [], opened_at=T0, at=T0 + DAY)
    assert recall.queue(st, open_now)[0]["id"] == "inv_0101" and all(not r["label"] for r in recall.queue(st, open_now))


def test_the_command_prints_the_label_first(tmp_path):
    from typer.testing import CliRunner

    from knos.cli import app, load
    load()
    st = _open(tmp_path)
    _fill(st)
    history.exception_resolved(st, TERMS, "disputed", "nimbus", "inv_0005", "accepted_on_appeal", ["evl_0005"], opened_at=T0, at=T0 + DAY)
    del st
    out = CliRunner().invoke(app, ["recall", "queue", "--buyer", "Acme Corp", "--memory", str(tmp_path / "memory")]).output
    assert out.startswith("1. inv_0004 (disputed, nimbus): Ended accepted on appeal 3 of 4 times before. Seen 4 times"), out


@pytest.mark.skipif(not shutil.which("node"), reason="needs node")
def test_the_site_ranks_and_labels_the_same_way(tmp_path):
    st = _open(tmp_path)
    _fill(st)
    history.exception_resolved(st, TERMS, "disputed", "nimbus", "inv_0005", "accepted_on_appeal", ["evl_0005"], opened_at=T0, at=T0 + DAY)
    rows, null = recall.queue(st, _open_now(st)), recall.queue(history.NullStore(), _open_now(st))
    script = ("import { ranked, patternOf, labelFor, recallHtml } from " + json.dumps((ROOT / "web" / "recall.js").as_uri()) + ";"
              "const [rows, nul] = JSON.parse(process.argv[1]); const rev = [...rows].reverse();"
              "console.log(JSON.stringify({ order: ranked(rev).map((r) => r.id), labels: rows.map((r) => (patternOf(r) || {}).label || ''),"
              " nul: ranked(nul).map((r) => r.id), nulLabels: nul.map((r) => patternOf(r)), html: recallHtml(rev),"
              " byReason: labelFor(rows, 'disputed', 'Nimbus'), other: labelFor(rows, 'disputed', 'orbit'), none: labelFor(nul, 'disputed') }));")
    got = subprocess.run([shutil.which("node"), "--input-type=module", "-e", script, json.dumps([rows, null])], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert got.returncode == 0, got.stderr
    out = json.loads(got.stdout)
    assert out["order"] == [r["id"] for r in rows] and out["labels"] == [r["label"] for r in rows]
    assert out["nul"] == [r["id"] for r in null] and out["nulLabels"] == [None, None, None]
    assert out["html"].index("inv_0103") < out["html"].index("inv_0101") and "Ended accepted on appeal 3 of 4 times before." in out["html"]
    assert out["byReason"] == rows[0]["label"] and out["other"] == "" and out["none"] == ""
