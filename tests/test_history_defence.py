"""The approver's defence and supplier reuse live in the memory engine, and nowhere else.

What these show: an approval record kept in the buyer's tenant answers "who approved what, under which policy
version, and does its evidence still match" from a new process, from the store only; an entity edited after the fact
is caught by the engine's append-only journal; a supplier brings from its other buyers only what each granted, a
withdrawn grant goes to the archive and stops showing, and the onboarding counter sets the second buyer against the
first. With no memory (history.NullStore) every one of these answers disappears.
"""

from __future__ import annotations

import contextlib
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from knos import recall, store
from knos.proof import history

ROOT = Path(__file__).resolve().parents[1]
TERMS, OTHER = "c3" * 32, "d4" * 32
T0 = 1_790_000_000.0            # a fixed clock: 2026-09-21 UTC
DAY = 86400.0
EVIDENCE = {"deliverable": "dlv_0001", "evaluation": "evl_0001", "terms": TERMS, "acceptance": "agreed", "settlement": "stl_0001"}
RECORD = {"commitment": "ord_7f3a", "approver": "dana", "policy_version": "3", "amount": "12500.00", "at": "2026-10-08T09:00:00Z",
          "why": "within PO 4471 and the approver's limit", "beneficiary": "nimbus", "purchase_order": "PO 4471", "expires": "2026-11-08",
          "evidence": EVIDENCE}


def _buyer(tmp_path, buyer="Acme Corp"):
    return history.SibylStore.for_buyer(buyer, tmp_path / "memory")


def _supplier(tmp_path, supplier="nimbus"):
    return history.SibylStore.for_supplier(supplier, tmp_path / "memory")


def _python(code: str, *args: str) -> str:
    got = subprocess.run([sys.executable, "-c", code, *args], capture_output=True, text=True, encoding="utf-8", timeout=120,
                         env={**os.environ, "PYTHONPATH": str(ROOT / "src")})
    assert got.returncode == 0, got.stderr
    return got.stdout


_KEEP = """
import json, sys
from knos.proof import history
history.approval_kept(history.SibylStore.for_buyer("Acme Corp", sys.argv[1]), json.loads(sys.argv[2]))
"""
_ASK = """
import json, sys
from knos import recall
from knos.proof import history
print(json.dumps(recall.approval(history.SibylStore.for_buyer("Acme Corp", sys.argv[1]), "ord_7f3a", json.loads(sys.argv[2]))))
"""


def test_the_approval_is_answered_after_a_restart_from_the_store_only(tmp_path, knos_home):
    memory = tmp_path / "memory"
    before = {p for p in (*tmp_path.rglob("*"), *knos_home.rglob("*")) if p.is_file()}
    _python(_KEEP, str(memory), json.dumps(RECORD))                               # one process keeps it and exits
    row = json.loads(_python(_ASK, str(memory), json.dumps(EVIDENCE)))            # another, later, is asked
    assert row["kind"] == "knos.recall.approval/1" and row["seen"] == 1 and row["intact"] is True and row["matches"] is True
    a = row["approvals"][0]
    assert (a["approver"], a["policy_version"], a["amount"], a["purchase_order"]) == ("dana", "3", "12500.00", "PO 4471")
    assert a["evidence_sha256"] == history.evidence_hash(EVIDENCE) and "evidence" not in a
    assert row["words"] == ("dana approved 12,500.00 on 2026-10-08T09:00:00Z under policy 3 for nimbus against PO 4471. "
                            "The evidence still matches what was approved.")
    changed = json.loads(_python(_ASK, str(memory), json.dumps({**EVIDENCE, "acceptance": "disputed"})))
    assert changed["matches"] is False and changed["words"].endswith("The evidence has changed since it was approved.")
    made = {p for p in (*tmp_path.rglob("*"), *knos_home.rglob("*")) if p.is_file()} - before
    assert made and all(p.parent == memory and p.name.startswith("sibyl.db") for p in made), sorted(map(str, made))   # no side file
    for p in made:
        p.unlink()                                                                # take the engine's store away
    gone = json.loads(_python(_ASK, str(memory), json.dumps(EVIDENCE)))
    assert gone["seen"] == 0 and gone["approvals"] == [] and gone["matches"] is None


def test_each_approval_is_one_entity_per_commitment_and_one_journal_event(tmp_path):
    st = _buyer(tmp_path)
    history.approval_kept(st, RECORD)
    history.approval_kept(st, RECORD)                                             # kept twice: one memory
    history.approval_kept(st, {**RECORD, "approver": "lee", "at": "2026-10-08T10:00:00Z", "why": "finance"})
    db, tenant = tmp_path / "memory" / "sibyl.db", store.buyer_tenant("Acme Corp")
    with contextlib.closing(sqlite3.connect(db)) as con:
        ents = con.execute("select count(*) from entities where tenant_id = ? and category = 'approval'", (tenant,)).fetchone()[0]
        events = con.execute("select count(*) from journal_events where tenant_id = ?", (tenant,)).fetchone()[0]
    assert (ents, events) == (1, 2)
    row = recall.approval(st, "ord_7f3a")
    assert [a["approver"] for a in row["approvals"]] == ["dana", "lee"] and row["intact"] and row["matches"] is None
    assert recall.approval(_buyer(tmp_path, "Globex"), "ord_7f3a")["approvals"] == []          # another buyer's tenant knows nothing


def test_a_record_edited_after_the_fact_is_caught_by_the_journal(tmp_path):
    st = _buyer(tmp_path)
    history.approval_kept(st, RECORD)
    name = history._id("approval", "ord_7f3a")
    body = st.get("approval", name)
    forged = {**body["approvals"][0], "amount": "125000.00"}
    st.put("approval", name, {**body, "approvals": [forged]})                     # someone rewrites the entity
    row = recall.approval(st, "ord_7f3a", EVIDENCE)
    assert row["intact"] is False and row["matches"] is False and len(row["journal_only"]) == 1
    assert row["journal_only"][0]["amount"] == "12500.00" and "does not match the journal" in row["words"]


def test_an_approval_record_needs_its_parts():
    with pytest.raises(ValueError, match="policy_version"):
        history.approval_record({k: v for k, v in RECORD.items() if k != "policy_version"})
    with pytest.raises(ValueError, match="evidence"):
        history.approval_record({k: v for k, v in RECORD.items() if k != "evidence"})
    assert history.approval_record({**RECORD, "evidence": None, "evidence_sha256": "AB" * 32})["evidence_sha256"] == "ab" * 32


def _supply(tmp_path) -> history.SibylStore:
    st = _supplier(tmp_path)
    history.onboarded(st, "Acme Corp", ordered_at=T0)
    history.onboarded(st, "Acme Corp", paid_at=T0 + 9 * DAY)
    history.onboarded(st, "Globex", ordered_at=T0 + 30 * DAY)
    history.onboarded(st, "Globex", paid_at=T0 + 32 * DAY)
    history.outcome_granted(st, "nimbus", "Acme Corp", TERMS, "accepted", "dlv_1", 5_000_000, at=T0 + DAY)
    history.outcome_granted(st, "nimbus", "Acme Corp", TERMS, "accepted", "dlv_1", 5_000_000, at=T0 + DAY)   # once
    history.outcome_granted(st, "nimbus", "Acme Corp", TERMS, "refused", "dlv_2", at=T0 + 2 * DAY)
    history.outcome_granted(st, "nimbus", "Initech", OTHER, "accepted", "dlv_9", 1_250_000_000, at=T0 + 3 * DAY)
    return st


def test_a_supplier_brings_what_other_buyers_granted_and_the_second_buyer_saves(tmp_path):
    st = _supply(tmp_path)
    row = recall.supplier(st, "Nimbus", "Globex")
    assert row["kind"] == "knos.recall.supplier/1" and row["buyers"] == 2 and row["value"] == 1_255_000_000
    assert row["outcomes"] == {"accepted": 2, "refused": 1, "disputed": 0, "reverted": 0}
    assert [(r["buyer"], r["results"]) for r in row["from"]] == [("acme corp", 2), ("initech", 1)]
    assert row["reuse"] == {"buyers": 2, "paid": 2, "seconds": [9 * DAY, 2 * DAY], "first_seconds": 9 * DAY,
                            "second_seconds": 2 * DAY, "saved_seconds": 7 * DAY} and row["you"] == 2
    assert row["words"] == ("2 other buyers granted: 2 accepted, 1 refused, 0 disputed, 0 reverted; 1,255.00 accepted. "
                            "First buyer onboarded in 9 days, second in 2 days.")
    own = recall.supplier(st, "nimbus", "Acme Corp")                              # a buyer is never shown its own results
    assert [r["buyer"] for r in own["from"]] == ["initech"] and own["you"] == 1


def test_a_withdrawn_grant_goes_to_the_archive_and_stops_showing(tmp_path):
    st = _supply(tmp_path)
    assert history.grant_withdrawn(st, "Initech", OTHER) is True
    assert [r["buyer"] for r in recall.supplier(st, "nimbus", "Globex")["from"]] == ["acme corp"]
    assert [n for n, _b in st.archived("granted")] == [history._id("granted", history._buyer_key("Initech"), OTHER)]
    assert history.grant_withdrawn(st, "Initech", OTHER) is False


def test_another_suppliers_memory_and_ungranted_results_answer_nothing(tmp_path):
    _supply(tmp_path)
    other = recall.supplier(_supplier(tmp_path, "orbit"), "orbit", "Globex")
    assert other["from"] == [] and other["reuse"]["buyers"] == 0 and other["words"] == "No other buyer granted a record of this supplier."
    assert recall.supplier(_buyer(tmp_path, "Globex"), "nimbus", "Globex")["from"] == []          # a buyer's tenant is not the supplier's


def test_with_no_memory_both_answers_disappear(tmp_path):
    null = history.NullStore()
    history.approval_kept(null, RECORD)
    row = recall.approval(null, "ord_7f3a", EVIDENCE)
    assert row["approvals"] == [] and row["matches"] is None and row["memory"] is False
    assert row["words"] == "No approval of this commitment is remembered."
    history.outcome_granted(null, "nimbus", "Acme Corp", TERMS, "accepted", "dlv_1", 5_000_000)
    history.onboarded(null, "Acme Corp", ordered_at=T0, paid_at=T0 + DAY)
    got = recall.supplier(null, "nimbus", "Globex")
    assert got["from"] == [] and got["reuse"]["saved_seconds"] is None and got["memory"] is False
    real = _supply(tmp_path)
    assert recall.supplier(real, "nimbus", "Globex")["from"] != []                # the same calls, with the engine, answer


def test_the_hooks_keep_onboarding_times_in_the_suppliers_memory(tmp_path):
    memory = tmp_path / "memory"
    assert recall.order_funded("Acme Corp", "nimbus", at=T0, memory=memory)["ordered_at"] == T0
    recall.order_paid("Acme Corp", "nimbus", at=T0 + DAY, memory=memory)
    recall.order_funded("Acme Corp", "nimbus", at=T0 + 5 * DAY, memory=memory)    # a later order keeps the first time
    assert history.reuse(_supplier(tmp_path))["seconds"] == [DAY]
    assert recall.order_funded("", "nimbus", memory=memory) is None


def test_the_commands(tmp_path):
    typer = pytest.importorskip("typer")
    from typer.testing import CliRunner
    app = typer.Typer()
    recall.register(app, [])
    app.command("noop")(lambda: None)
    mem = ["--memory", str(tmp_path / "memory")]
    (tmp_path / "record.json").write_text(json.dumps(RECORD), encoding="utf-8")
    (tmp_path / "now.json").write_text(json.dumps(EVIDENCE), encoding="utf-8")
    run = lambda *a: CliRunner().invoke(app, [*a, *mem])  # noqa: E731
    assert run("recall", "approval", "ord_7f3a", "--buyer", "Acme Corp").exit_code == 1               # nothing kept yet
    kept = run("recall", "keep-approval", str(tmp_path / "record.json"), "--buyer", "Acme Corp")
    assert kept.exit_code == 0 and "12,500.00" in kept.output
    said = run("recall", "approval", "ord_7f3a", "--buyer", "Acme Corp", "--evidence", str(tmp_path / "now.json"))
    assert said.exit_code == 0 and "still matches" in said.output
    granted = run("recall", "grant", "--supplier", "nimbus", "--buyer", "Acme Corp", "--terms", TERMS, "--outcome", "accepted",
                  "--ref", "dlv_1", "--value", "5000000")
    assert granted.exit_code == 0, granted.output
    row = json.loads(run("recall", "supplier", "nimbus", "--buyer", "Globex", "--json").output)
    assert row["outcomes"]["accepted"] == 1 and row["value"] == 5_000_000
    assert run("recall", "grant", "--supplier", "nimbus", "--buyer", "Acme Corp", "--terms", "nothex", "--outcome", "accepted", "--ref", "x").exit_code != 0
