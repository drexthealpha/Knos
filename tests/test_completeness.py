"""Completeness and cross-system finality (src/knos/completeness.py, `knos statement complete`, statement.settle_sync).

The statement is September's of tests/test_statement.py. Its sources (the orders the chain paid, what GitHub answers
for each reference) are written here; nothing asks the cluster, GitHub or a bank. The finality matrix runs the real
record-keeping parts (knos.events.ingest, knos.rails.apply, knos.statement.settle_sync) through retried, delayed,
dropped and unfinalized answers and checks after every step that no two records of one line contradict each other."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_statement as T                                     # noqa: E402
import test_statement_rails as R                               # noqa: E402

from knos import completeness as C                              # noqa: E402
from knos import events as E                                    # noqa: E402
from knos import ids, rails, statement                          # noqa: E402
from knos.proof import history                                  # noqa: E402
from knos.settle.v2 import pay as pay2                          # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
TERMS = "ab" * 32
PAID_1 = "1" * 44                       # order addresses (base58)
OMITTED = "2" * 44
LATE = "3" * 44
LATE_BILLED = "4" * 44
TWICE = "5" * 44


def sources(**over) -> dict:
    doc = {"kind": "knos-sources", "period": "2026-09", "closed_at": "2026-10-01T00:00:00Z", "terms": TERMS,
           "orders": [{"order": PAID_1, "reference": "acme/app#1", "amount": "100.00", "at": "2026-09-10T10:00:00Z", "seen": "2026-09-10T10:00:30Z"}],
           "github": {"acme/app#1": "present", "acme/app#2": "present", "acme/app#3": "present", "acme/app#4": "present",
                      "https://github.com/acme/app/actions/runs/21": "present"}}
    doc.update(over)
    return doc


def order(address: str, ref: str, at: str, seen: str, amount: str = "40.00") -> dict:
    return {"order": address, "reference": ref, "amount": amount, "at": at, "seen": seen}


def kinds(report: dict) -> list[tuple[str, str]]:
    return [(x["kind"], x["source"]) for x in report["exceptions"]]


def test_a_statement_that_matches_its_sources_is_complete_and_counts_each_line_once():
    report = C.check(T.sept(), sources())
    assert report["complete"] and report["exceptions"] == [] and report["carried"] == []
    assert report["counted"] == {"lines": 4, "amount": "490.00", "held": 0}          # the duplicate line 4 is not counted again
    assert C.words(report)[0].startswith("complete:")


def test_a_line_whose_pull_request_or_run_github_no_longer_has_is_a_deleted_exception_and_held():
    gh = {**sources()["github"], "acme/app#3": "deleted", "https://github.com/acme/app/actions/runs/21": "deleted"}
    report = C.check(T.sept(), sources(github=gh))
    assert kinds(report) == [("deleted", "github:acme/app/actions/runs/21"), ("deleted", "github:acme/app#3")]
    assert [x["line"] for x in report["exceptions"]] == [2, 3] and report["counted"]["held"] == 2
    assert all(x["action"].startswith("held") for x in report["exceptions"]) and not report["complete"]
    unknown = C.check(T.sept(), sources(github={**gh, "acme/app#3": "unknown", "https://github.com/acme/app/actions/runs/21": "unknown"}))
    assert unknown["exceptions"] == [] and len(unknown["sources"]["unknown"]) == 2   # no answer is not "deleted": said, not decided


def test_an_order_the_chain_paid_in_the_period_with_no_line_is_an_omitted_exception():
    doc = sources()
    doc["orders"] += [order(OMITTED, "acme/app#9", "2026-09-20T08:00:00Z", "2026-09-20T08:01:00Z"),
                      order("6" * 44, "acme/app#8", "2026-08-31T23:59:59Z", "2026-09-01T00:00:10Z")]       # paid in August: not this period's
    report = C.check(T.sept(), doc)
    assert kinds(report) == [("omitted", f"order:{OMITTED}")]
    x = report["exceptions"][0]
    assert x["line"] is None and x["amount"] == "40.00" and "no line bills it" in x["why"] and x["terms"] == TERMS
    assert report["counted"]["amount"] == "490.00"                # listed, never added to the count


def test_an_order_seen_after_the_period_closed_is_carried_never_added_and_a_line_that_bills_it_is_held():
    doc = sources()
    doc["orders"] += [order(LATE, "acme/app#9", "2026-09-30T23:00:00Z", "2026-10-01T06:00:00Z"),
                      order(LATE_BILLED, "acme/app#4", "2026-09-29T12:00:00Z", "2026-10-02T09:00:00Z", "60.00")]
    report = C.check(T.sept(), doc)
    assert kinds(report) == [("late", f"order:{LATE}"), ("late", f"order:{LATE_BILLED}")]
    assert report["exceptions"][0]["action"] == "carried to 2026-10; not added to 2026-09" and report["exceptions"][0]["line"] is None
    assert report["exceptions"][1]["line"] == 5 and report["exceptions"][1]["action"] == "held: it belongs to the statement of 2026-10"
    assert [c["order"] for c in report["carried"]] == [LATE, LATE_BILLED] and {c["to"] for c in report["carried"]} == {"2026-10"}
    assert report["counted"] == {"lines": 3, "amount": "430.00", "held": 0}          # line 5 (60.00) left out of September
    on_time = C.check(T.sept(), {**doc, "closed_at": ""})        # a period not closed yet: nothing is late
    assert [k for k, _s in kinds(on_time)] == ["omitted"]


def test_one_deliverable_under_two_ids_is_counted_once_and_flagged():
    st = T.sept()
    again = {**st["lines"][4], "line": 6, "invoice_line": "inv_again", "deliverable": "dlv_another_id_of_pull_4", "reference": "acme/app#4"}
    st = {**st, "lines": [*st["lines"], again]}
    doc = sources()
    doc["orders"] += [order(TWICE, "acme/app#1", "2026-09-11T10:00:00Z", "2026-09-11T10:00:30Z", "100.00")]
    report = C.check(st, doc)
    assert kinds(report) == [("duplicated", f"order:{TWICE}"), ("duplicated", "line:inv_again")]
    assert report["exceptions"][0]["action"] == "counted once; ask for one payment back"
    assert report["exceptions"][1]["action"] == "counted once (line 5)" and report["exceptions"][1]["line"] == 6
    assert report["counted"] == {"lines": 4, "amount": "490.00", "held": 0}          # line 6 is not counted a second time


def test_a_sources_document_that_cannot_be_read_is_refused_in_one_line():
    for bad, said in (({"kind": "other"}, "not a sources document"), (sources(period="2026-9"), "YYYY-MM"),
                      (sources(github={"acme/app#1": "gone"}), "present, deleted, unknown"),
                      (sources(closed_at="yesterday"), "is not a time"), (sources(orders=[{"amount": "1"}]), "order address")):
        with pytest.raises(C.Bad, match=said):
            C.check(T.sept(), bad)


# ---- memory: a resolution kept through knos.proof.history and recalled when the same source comes back --------------

def _omitted() -> dict:
    doc = sources()
    doc["orders"] += [order(OMITTED, "acme/app#9", "2026-09-20T08:00:00Z", "2026-09-20T08:01:00Z")]
    return doc


def test_a_resolution_is_remembered_and_recalled_when_the_same_source_comes_back_and_no_memory_recalls_nothing(tmp_path):
    store = history.SibylStore.local(tmp_path / "memory", "knos-buyer-acme")
    first = C.check(T.sept(), _omitted(), store)
    exc = first["exceptions"][0]
    assert exc["before"] is None
    C.remember(store, exc, "corrected", "Acme Agents", at=1_790_000_000.0, period="2026-09")
    october = {**_omitted(), "period": "2026-09"}
    again = C.check(T.sept(), october, store)
    assert again["exceptions"][0]["before"] == {"resolution": "corrected", "ending": "corrected_and_passed", "at": 1_790_000_000.0, "period": "202609"}
    assert "(resolved before: corrected)" in C.words(again)[1]
    kept = history.exceptions_before(store, TERMS, "completeness-omitted", "Acme Agents")      # one memory, in the engine
    assert kept["seen"] == 1 and kept["cases"][0]["id"] == f"order:{OMITTED}" and exc["id"] in kept["evidence"]
    other = C.check(T.sept(), {**_omitted(), "terms": "cd" * 32}, store)                       # other terms: nothing recalled
    assert other["exceptions"][0]["before"] is None
    null = history.NullStore()
    C.remember(null, exc, "corrected", "Acme Agents", at=1_790_000_000.0)
    assert C.check(T.sept(), _omitted(), null)["exceptions"][0]["before"] is None
    with pytest.raises(ValueError, match="resolved"):
        C.remember(store, exc, "ignored", "Acme Agents")


def test_the_command_lists_the_exceptions_and_keeps_a_resolution(tmp_path):
    st = T.sept()
    statement.write(st, tmp_path)
    (tmp_path / "sources.json").write_text(json.dumps(_omitted()), encoding="utf-8")
    app = typer.Typer()
    statement.register(app)
    run = CliRunner()
    file = str(tmp_path / f"{statement.NAME}.json")
    got = run.invoke(app, ["statement", "complete", file, "--sources", str(tmp_path / "sources.json")])
    assert got.exit_code == 0 and got.output.splitlines()[0] == "1 exception in 2026-09" and "omitted" in got.output
    report = json.loads(run.invoke(app, ["statement", "complete", file, "--sources", str(tmp_path / "sources.json"), "--json"]).output)
    eid = report["exceptions"][0]["id"]
    mem = ["--remember", "acme", "--memory", str(tmp_path / "mem")]
    done = run.invoke(app, ["statement", "complete", file, "--sources", str(tmp_path / "sources.json"), "--resolve", f"{eid}=refused", *mem])
    assert done.exit_code == 0 and "(resolved before: refused)" in done.output
    later = run.invoke(app, ["statement", "complete", file, "--sources", str(tmp_path / "sources.json"), *mem])
    assert "(resolved before: refused)" in later.output
    bad = run.invoke(app, ["statement", "complete", file, "--sources", str(tmp_path / "sources.json"), "--resolve", "cx_nothing=refused", *mem])
    assert bad.exit_code != 0 and "Traceback" not in bad.output


# ---- cross-system finality: no sequence of answers makes two records of one line that contradict each other --------

def test_a_retried_webhook_is_one_event_and_the_same_event_from_a_second_source_is_counted_once():
    log, dlv = E.Log(), ids.deliverable("ab" * 32, 1)
    paid = E.settlement(dlv, "chain", "SIG", 5_000_000, "units", "settle", supplier="4242", month=202609)
    first = E.ingest(log, [paid])
    retried = E.ingest(log, [paid, paid])                         # the same delivery, sent again twice
    other = E.ingest(log, [E.settlement(dlv, "chain", "SIG", 5_000_000, "units", "import", supplier="4242", month=202609)])
    assert (len(first.added), retried.added, retried.known) == (1, [], 2)
    assert len(other.duplicates) == 1 and other.json()["counted"] == 0
    changed = E.ingest(log, [E.settlement(dlv, "chain", "SIG", 4_000_000, "units", "import", supplier="4242", month=202609)])
    assert changed.conflicts and not changed.added                # the same id saying another amount is refused, never a second record
    assert sum(1 for e in log.events if e.first is None and e.kind == "settlement") == 1


BANK = [("unknown", "paid"), ("unknown", "unknown", "paid"), ("paid", "paid"), ("pending", "unknown", "paid", "paid"),
        ("unknown", "returned", "unknown", "paid"), ("returned", "paid")]
WORD = {"paid": "ACSC", "unknown": "timeout", "pending": "PDNG", "returned": "RJCT"}


@pytest.mark.parametrize("answers", BANK, ids=["-".join(a) for a in BANK])
def test_a_delayed_or_repeated_bank_status_books_each_line_once_and_only_when_paid(answers):
    st = R.two()
    status, _xml, found = rails.instruct(st, R.approved(st), R.PAYER)
    acme = found[0]
    for n, word in enumerate(answers):
        status, _said = rails.apply(st, status, rails.read_status(R.csv_answer((acme["end_to_end"], WORD[word]))), f"2026-10-0{n + 3}")
        assert C.contradictions(st, status) == [], (answers, n)
        paid = {r["invoice_line"]: r["payment"] for r in statement.lines_now(st, status)}
        assert all((paid[ln] == "paid_outside") == (word == "paid" or (word == "pending" and "paid" in answers[:n])) for ln in acme["lines"]), (answers, n)
    assert len(rails.accepted_rows(st, status)) == len(acme["lines"])           # billed once, however many answers said paid


def _tx(sig: str, order_: str, payee: int, amount: int) -> dict:
    pid = str(pay2.PAY_ID)
    return {"slot": 412_345_678, "blockTime": 1_788_000_000, "transaction": {"signatures": [sig], "message": {"accountKeys": ["R" * 44, order_, "W" * 44, pid]}},
            "meta": {"err": None, "loadedAddresses": {"writable": [], "readonly": []}, "logMessages": [
                f"Program {pid} invoke [1]", f"Program log: knos3:paid order={order_} pr=2 payee={payee} amount={amount} to={'W' * 44}",
                f"Program log: knos3:settled order={order_} paid={amount} of={amount} fee=0 tip=50000 judge=9", f"Program {pid} success"]}}


ORDER = "7" * 44
DROPPED, RESENT, SIG = "D" * 64, "E" * 64, "F" * 64


def _line(reference: str) -> dict:
    ln = {"line": 1, "invoice_line": "inv_1", "state": "agreed", "amount": "5.00", "supplier": "4242", "reference": reference, "deliverable": "dlv_1", "why": ""}
    return {"lines": [ln], "scale": 6, "source": "events", "date": "2026-09-30", "sha256": "s" * 64}


SEEN = [("processed", "confirmed", "finalized"), ("confirmed", "finalized", "finalized"), (None, "processed", "finalized"), ("finalized", "finalized")]


@pytest.mark.parametrize("seen", SEEN, ids=["-".join(map(str, s)) for s in SEEN])
def test_a_payment_the_cluster_has_only_processed_or_confirmed_is_never_booked_until_it_is_finalized(seen):
    st, txs = _line(f"tx:{SIG}"), {SIG: _tx(SIG, ORDER, 4242, 5_000_000)}
    status: dict | None = None
    booked_at = None
    for n, word in enumerate(seen):
        status, said = statement.settle_sync(st, status, txs.get, order=ORDER, final=lambda _s, w=word: w)
        settled = [e for e in status["events"] if e["type"] == "settlement"]
        assert C.contradictions(st, status) == []
        if word != "finalized":
            assert settled == [] and f"is {word or 'not known to the cluster'}, not finalized" in said[0][1]
        else:
            booked_at = booked_at if booked_at is not None else n
            assert len(settled) == 1 and settled[0]["chain"]["commitment"] == "finalized"
            assert said[0][1] == ("already settled" if n > booked_at else said[0][1]) and said[0][1].startswith(("settled by", "already"))


def test_a_transaction_dropped_before_finality_is_never_booked_and_its_resubmission_is_booked_once():
    st = _line("issue 1")
    txs = {RESENT: _tx(RESENT, ORDER, 4242, 5_000_000)}                     # the dropped one: the cluster never gives it
    final = {RESENT: "finalized"}.get
    status, said = statement.settle_sync(st, None, txs.get, lambda _o: [DROPPED], order=ORDER, final=final)
    assert status["events"] == [] and said[0][1].startswith("not settled")    # only the dropped signature known yet: nothing booked
    status, said = statement.settle_sync(st, status, txs.get, lambda _o: [RESENT, DROPPED], order=ORDER, final=final)
    assert [e["reference"] for e in status["events"]] == [RESENT] and said[0][1].startswith(f"settled by {RESENT}")
    both = {**txs, DROPPED: _tx(DROPPED, ORDER, 4242, 5_000_000)}           # even if the first had landed too: the line is settled once
    again, said = statement.settle_sync(st, status, both.get, lambda _o: [DROPPED, RESENT], order=ORDER, final={DROPPED: "finalized", RESENT: "finalized"}.get)
    assert again == status and said == [("inv_1", "already settled")] and C.contradictions(st, again) == []


def test_contradictions_finds_a_line_paid_under_two_ids_and_one_booked_from_a_transaction_that_was_not_final():
    st = _line(f"tx:{SIG}")
    paid = {"type": "settlement", "line": "inv_1", "settlement": "stl_a", "state": "paid_outside"}
    assert C.contradictions(st, {"events": [paid, {**paid, "settlement": "stl_b"}]}) == ["inv_1: paid under stl_a and again under stl_b"]
    assert C.contradictions(st, {"events": [paid, {**paid, "state": "payable", "returned": "RJCT"}, {**paid, "settlement": "stl_b"}]}) == []
    early = {**paid, "state": "devnet_demonstration", "chain": {"commitment": "confirmed"}}
    assert C.contradictions(st, {"events": [early]}) == ["inv_1: booked from a transaction seen only at confirmed"]


# ---- an order funded before an upgrade keeps the schedule it was funded with --------------------------------------------

def test_the_stored_schedule_of_an_order_funded_under_2_1_is_read_from_its_account():
    doc = json.loads((ROOT / "tests" / "data" / "completeness" / "order_funded_under_2_1.json").read_text(encoding="utf-8"))
    got = C.stored_terms(bytes.fromhex(doc["data"]))
    assert (got["funded_under"], got["amount"], got["fee"], got["fee_bps"], got["grace"]) == ("2.1", 5_000_000, 400_000, 250, False)
    assert got["refund"] == 5_400_000 and got["fee_now"] == 50_000           # 2.2 would charge 0.05 on 5.00; the order keeps its 0.40
    assert got["deadline"] == 1_791_555_900                                    # 2026-10-09 14:25 UTC
    with pytest.raises(ValueError, match="not an order"):
        C.stored_terms(bytes(100))


def test_an_order_given_as_its_account_bytes_is_read_from_them_and_a_status_that_contradicts_itself_is_not_complete():
    data = json.loads((ROOT / "tests" / "data" / "completeness" / "order_funded_under_2_1.json").read_text(encoding="utf-8"))["data"]
    doc = sources()
    doc["orders"] += [{"order": OMITTED, "reference": "acme/app#9", "amount": "999.00", "at": "2026-09-20T08:00:00Z", "data": data}]
    x = C.check(T.sept(), doc)["exceptions"][0]
    assert (x["kind"], x["amount"], x["terms"]) == ("omitted", "5.00", bytes.fromhex(data)[320:352].hex())     # the bytes, not the row's words
    with pytest.raises(C.Bad, match="not an order account"):
        C.check(T.sept(), {**doc, "orders": [{**doc["orders"][1], "data": "00" * 10}]})
    st = T.sept()
    line = st["lines"][0]["invoice_line"]
    paid = {"type": "settlement", "line": line, "settlement": "stl_a", "state": "paid_outside"}
    report = C.check_status(st, {"events": [paid, {**paid, "settlement": "stl_b"}]}, C.check(st, sources()))
    assert not report["complete"] and report["contradictions"] == [f"{line}: paid under stl_a and again under stl_b"]
    assert f"  contradiction {line}: paid under stl_a and again under stl_b" in C.words(report)
