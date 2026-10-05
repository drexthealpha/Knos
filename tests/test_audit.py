"""The audit export (knos.audit): every work order of one organisation from the escrow's log lines, hash-chained.

The fixture is a month of one organisation's orders as `records.events_of` gives them: a plain payment, a standing
offer paid for two pull requests and refunded its rest, a holdback reverted inside its warranty, an arbiter's ruling
split between two payees, a cancelled order that expired, an open one, another owner's order and one a wallet funded.
The checks that matter: two parties get the same bytes for the same period, and `verify` finds a removed or edited row.
"""

from __future__ import annotations

import csv
import io
import json
from types import SimpleNamespace

import pytest
from solders.pubkey import Pubkey

from knos import audit, cli, records
from knos.settle.v2 import pay as pay2

ACME, OTHER = 5001, 5002
MINT = str(pay2.USDC_DEVNET)
WALLET, WALLET2 = str(Pubkey(bytes([7]) * 32)), str(Pubkey(bytes([8]) * 32))
BAL = str(pay2.balance_pda(ACME, Pubkey.from_string(WALLET), pay2.USDC_DEVNET))
BAL2 = str(pay2.balance_pda(OTHER, Pubkey.from_string(WALLET2), pay2.USDC_DEVNET))
TERMS = '{"accept":"","checks":[{"app":0,"name":"deployed/production"}],"deny":[],"mode":"merge","paths":[],"reserve":7,"v":1}'
DAY = 86_400
T0 = 1_788_220_800       # 2026-09-01T00:00:00Z
U = 1_000_000


def line(event: str, at: int, tx: str, **fields) -> dict:
    return {"event": event, "v": 2, "at": at, "signer": "relayer", "keys": ["relayer"], "tx": tx, **fields}


def funded(order: str, at: int, tx: str, amount: int, source: str = BAL, by: int = 6001, flags: int = 0, repo: int = 7001, issue: int = 1) -> list[dict]:
    return [line("order_funded", at, tx, order=order, repo=repo, issue=issue, seq=0, amount=amount, fee=pay2.fee_of(amount), mode=0, by=by,
                 source=source, flags=flags, deadline=at + 30 * DAY),
            line("order_terms", at, tx, json=TERMS)]


def paid(order: str, at: int, tx: str, shares, of: int, sofar: int, judge: int, pr: int = 7, fee: int = 400_000) -> list[dict]:
    return [*(line("order_paid", at, tx, order=order, pr=pr, payee=i, amount=a, to=f"W{i}") for i, a in shares),
            line("order_settled", at, tx, order=order, paid=sofar, of=of, fee=fee - 50_000, tip=50_000, judge=judge)]


def month() -> list[dict]:
    d = lambda n: T0 + n * DAY       # noqa: E731
    ev = [line("balance", T0 - DAY, "B1", owner=ACME, authority=WALLET, mint=MINT), line("balance", T0 - DAY, "B2", owner=OTHER, authority=WALLET2, mint=MINT)]
    ev += funded("OrdA", d(1), "FA", 100 * U) + paid("OrdA", d(2), "PA", [(8001, 100 * U)], 100 * U, 100 * U, 0)
    ev += funded("OrdB", d(3), "FB", 30 * U, flags=pay2.F_STANDING | pay2.F_NEUTRAL)
    ev += paid("OrdB", d(4), "PB1", [(8002, 10 * U)], 30 * U, 10 * U, 1, pr=11) + paid("OrdB", d(5), "PB2", [(8003, 10 * U)], 20 * U, 10 * U, 1, pr=12)
    ev += [line("order_refunded", d(20), "RB", order="OrdB", amount=10 * U)]
    ev += funded("OrdC", d(6), "FC", 200 * U) + paid("OrdC", d(7), "PC", [(8001, 160 * U)], 200 * U, 160 * U, 2, pr=13)
    ev += [line("order_warranty", d(7), "PC", order="OrdC", held=40 * U, until=d(37)),
           line("order_reverted", d(9), "VC", order="OrdC", amount=40 * U, head="ab" * 20)]
    ev += funded("OrdD", d(8), "FD", 50 * U) + paid("OrdD", d(10), "PD", [(8001, 30 * U), (8004, 20 * U)], 50 * U, 50 * U, 3, pr=0)
    ev += funded("OrdE", d(11), "FE", 40 * U) + [line("order_cancelled", d(12), "CE", order="OrdE", at_=d(12), deadline=d(19)),
                                                 line("order_refunded", d(19), "RE", order="OrdE", amount=40 * U)]
    ev += funded("OrdF", d(13), "FF", 60 * U)
    ev += funded("OrdG", d(14), "FG", 70 * U, source=BAL2) + paid("OrdG", d(15), "PG", [(8001, 70 * U)], 70 * U, 70 * U, 0)
    ev += funded("OrdH", d(16), "FH", 80 * U, source=WALLET, by=0) + paid("OrdH", d(17), "PH", [(8005, 80 * U)], 80 * U, 80 * U, 0)
    return sorted(ev, key=lambda e: e["at"])


def later() -> list[dict]:
    """What the chain holds a month on: the open order was paid, and there are new ones. A second party exports then."""
    more = paid("OrdF", T0 + 40 * DAY, "PF", [(8001, 60 * U)], 60 * U, 60 * U, 0) + funded("OrdI", T0 + 41 * DAY, "FI", 90 * U)
    return month() + more


def rows_of(text: str) -> list[dict]:
    return audit.parse(text)[1]


SEPT = dict(first="2026-09-01", last="2026-09-30")


def test_two_parties_exporting_the_same_period_get_the_same_bytes():
    for fmt in ("csv", "json"):
        mine = audit.export(month(), ACME, fmt, **SEPT)
        theirs = audit.export(list(later()), ACME, fmt, **SEPT)       # read later, with more on chain
        assert mine == theirs and mine.encode() == theirs.encode()
        assert audit.verify(mine) == []
    assert audit.parse(audit.export(month(), ACME, "csv", **SEPT))[3] == audit.parse(audit.export(later(), ACME, "json", **SEPT))[3]   # one head, either format
    # another period, another owner, or a partial read is another file, and its head differs
    heads = {audit.parse(audit.export(month(), who, "csv", partial=part, **days))[3]
             for who, days, part in ((ACME, SEPT, False), (ACME, dict(first="2026-09-01", last="2026-09-15"), False), (OTHER, SEPT, False), (ACME, SEPT, True))}
    assert len(heads) == 4


def test_every_order_of_the_organisation_is_there_and_nobody_elses():
    rows = rows_of(audit.export(month(), ACME, **SEPT))
    assert {r["order"] for r in rows} == {"OrdA", "OrdB", "OrdC", "OrdD", "OrdE", "OrdF"}
    assert [r["seq"] for r in rows] == [str(n) for n in range(1, len(rows) + 1)]
    assert [(r["order"], r["kind"]) for r in rows] == [("OrdA", "paid"), ("OrdB", "paid"), ("OrdB", "paid"), ("OrdC", "paid"), ("OrdC", "reverted"),
                                                       ("OrdD", "paid"), ("OrdF", "open"), ("OrdE", "refunded"), ("OrdB", "refunded")]
    assert all(r["owner_id"] == str(ACME) and r["funder"] == f"gh:{ACME}" and r["currency"] == "test USDC" for r in rows)
    # the order a wallet funded itself is the organisation's only when the wallet is named
    with_wallet = rows_of(audit.export(month(), ACME, wallets=[WALLET], **SEPT))
    assert {r["order"] for r in with_wallet} - {r["order"] for r in rows} == {"OrdH"}
    assert {r["order"] for r in rows_of(audit.export(month(), OTHER, **SEPT))} == {"OrdG"}


def test_a_line_says_what_was_bought_who_supplied_who_evaluated_and_what_became_of_the_money():
    by = {(r["order"], r["kind"], r["pull_request"]): r for r in rows_of(audit.export(month(), ACME, **SEPT))}
    a = by["OrdA", "paid", "7"]
    assert (a["repository_id"], a["issue"], a["price_units"], a["price"], a["mode"]) == ("7001", "1", str(100 * U), "100.000000", "merge")
    assert a["terms_hash"] == pay2.terms_hash(TERMS.encode()).hex() and a["artifact"] == "pull:7001#7"
    assert (a["supplier_ids"], a["wallets"], a["judge"], a["verdict"]) == ("8001", "W8001", "repository", "accepted")
    assert "prove.yml" in a["evaluator"] and "own repository" in a["evaluator"]
    assert (a["paid_units"], a["fee_units"], a["transaction"], a["funded_transaction"]) == (str(100 * U), "400000", "PA", "FA")
    assert a["exception"] == "" and a["resolved_by"] == ""
    # who had authority over the money: the commenter the owner had listed, in the cell after commenter_id
    assert (a["commenter_id"], a["owner_id"], a["authorised_by"]) == ("6001", "5001", "gh:6001 (spender)")
    assert audit.COLUMNS.index("authorised_by") == audit.COLUMNS.index("commenter_id") + 1
    own = [r for r in rows_of(audit.export(month(), ACME, wallets=[WALLET], **SEPT)) if r["order"] == "OrdH"]
    assert own and all(r["authorised_by"] == f"wallet:{WALLET}" == r["funder"] for r in own)
    # a standing offer: one line per pull request, each its own milestone; its rest went back
    b1, b2 = by["OrdB", "paid", "11"], by["OrdB", "paid", "12"]
    assert (b1["standing"], b1["judge"], b1["billing_key"], b2["billing_key"]) == ("1", "neutral", "OrdB:FB:11", "OrdB:FB:12")
    rest = by["OrdB", "refunded", ""]
    assert rest["refunded_units"] == str(10 * U) and rest["exception"] == "refunded after a part was paid" and rest["verdict"] == "accepted"
    # a holdback, then a revert inside the warranty: the judge repository paid it, the revert names the commit
    c, v = by["OrdC", "paid", "13"], by["OrdC", "reverted", ""]
    assert (c["judge"], c["held_units"], c["paid_units"]) == ("attestor", str(40 * U), str(160 * U))
    assert (v["reverted_units"], v["artifact"], v["verdict"], v["transaction"]) == (str(40 * U), "commit:" + "ab" * 20, "reverted", "VC")
    assert "reverted inside the warranty" in v["exception"] and v["resolved_by"].startswith("revert:")
    # an arbiter's ruling, split between two payees: one line, one fee
    d = by["OrdD", "paid", ""]
    assert (d["supplier_ids"], d["wallets"], d["judge"], d["paid_units"]) == ("8001;8004", "W8001;W8004", "arbiter", str(50 * U))
    assert d["exception"] == "arbiter ruling" and d["resolved_by"].startswith("rule: the arbiter")
    # cancelled, and nothing accepted by the deadline
    e = by["OrdE", "refunded", ""]
    assert (e["verdict"], e["refunded_units"], e["paid_units"]) == ("expired", str(40 * U), "0")
    assert e["exception"].startswith("cancelled on 2026-09-13 (CE)") and e["resolved_by"].startswith("cancel:")
    # nothing has happened yet: the commitment is shown
    f = by["OrdF", "open", ""]
    assert (f["verdict"], f["held_units"], f["judge"]) == ("pending", str(60 * U), "")


def test_the_file_ends_with_the_totals_and_the_head():
    text = audit.export(month(), ACME, **SEPT)
    scope, rows, sums, head, count = audit.parse(text)
    assert scope == {"type": "knos.audit-export", "version": 1, "program": str(pay2.PAY_ID), "owner_id": ACME, "from": "2026-09-01", "to": "2026-09-30",
                     "wallets": "", "partial": 0}
    assert count == len(rows) == 9 and head == audit._hash(rows[-1]) and rows[0]["prev"] == audit._hash(scope)
    assert sums == {"test USDC": {"lines": 9, "paid_units": 330 * U, "fee_units": 5 * 400_000, "refunded_units": 50 * U, "reverted_units": 40 * U}}
    last = list(csv.reader(io.StringIO(text)))[-2:]
    assert last[0][:3] == ["total", "test USDC", "9"] and last[1][0] == "head" and last[1][1] == head
    doc = json.loads(audit.export(month(), ACME, "json", **SEPT))
    assert doc["head"] == head and doc["columns"] == list(audit.COLUMNS) and doc["rows"][0]["price_units"] == 100 * U
    # an owner with nothing: a file all the same, whose head is its scope's hash
    none = audit.export(month(), 4242, **SEPT)
    assert audit.verify(none) == [] and audit.parse(none)[3] == audit._hash(audit.parse(none)[0])


def csv_edit(text: str, change) -> str:
    got = list(csv.reader(io.StringIO(text)))
    change(got)
    buf = io.StringIO()
    csv.writer(buf, lineterminator="\n").writerows(got)
    return buf.getvalue()


def test_verify_finds_a_removed_an_edited_a_moved_and_an_added_row():
    text = audit.export(month(), ACME, **SEPT)
    assert csv_edit(text, lambda g: None) == text and audit.verify(text) == []
    paid_at = audit.COLUMNS.index("paid_units")

    removed = audit.verify(csv_edit(text, lambda g: g.pop(3)))                       # the third row is gone
    assert any("Row 3 is numbered 4" in s for s in removed) and any("Row 3 does not follow" in s for s in removed)
    edited = audit.verify(csv_edit(text, lambda g: g[2].__setitem__(paid_at, "1")))  # the second row's amount
    assert any("Row 3 does not follow the row before it" in s and "row 2 was edited" in s for s in edited) and any("totals" in s for s in edited)
    last = audit.verify(csv_edit(text, lambda g: g.pop(9)))                          # the last row is gone
    assert any("head does not match the last row" in s for s in last) and any("says it has 9 rows and has 8" in s for s in last)
    last_edited = audit.verify(csv_edit(text, lambda g: g[9].__setitem__(audit.COLUMNS.index("verdict"), "expired")))
    assert last_edited == ["The head does not match the last row: the last row was edited or removed, or rows were added after it."]
    moved = audit.verify(csv_edit(text, lambda g: g.insert(1, g.pop(2))))
    assert any("Row 1 is numbered 2" in s for s in moved)
    added = audit.verify(csv_edit(text, lambda g: g.insert(10, list(g[9]))))
    assert any("Row 10" in s for s in added)
    totals = audit.verify(csv_edit(text, lambda g: g[10].__setitem__(3, "1")))
    assert totals == ["The totals are not the sums of the rows."]
    # the same for JSON, and a row moved into another export does not fit its scope
    doc = json.loads(audit.export(month(), ACME, "json", **SEPT))
    del doc["rows"][4]
    assert any("Row 5" in s for s in audit.verify(json.dumps(doc)))
    doc = json.loads(audit.export(month(), ACME, "json", **SEPT))
    doc["scope"]["to"] = "2026-10-31"
    assert any("Row 1 does not follow" in s for s in audit.verify(json.dumps(doc)))
    for junk in ("", "a,b\n1,2\n", "{}", text.rsplit("head", 1)[0]):
        with pytest.raises(audit.Refused):
            audit.verify(junk)


def test_a_second_line_that_bills_the_same_order_and_milestone_is_flagged_and_fails_verify():
    twice = month() + paid("OrdB", T0 + 6 * DAY, "PB3", [(8002, 10 * U)], 10 * U, 10 * U, 1, pr=11)      # what the program refuses (["done", order, pr])
    text = audit.export(twice, ACME, **SEPT)
    flags = [(r["transaction"], r["billed_before"]) for r in rows_of(text) if r["billing_key"] == "OrdB:FB:11"]
    assert flags == [("PB1", "0"), ("PB3", "1")]
    assert any("bills OrdB:FB:11 a second time" in s for s in audit.verify(text))
    assert all(r["billed_before"] == "0" for r in rows_of(audit.export(month(), ACME, **SEPT)))
    # an address funded again is another order: its key names its own funding
    again = month() + funded("OrdA", T0 + 21 * DAY, "FA2", 100 * U) + paid("OrdA", T0 + 22 * DAY, "PA2", [(8001, 100 * U)], 100 * U, 100 * U, 0)
    keys = [r["billing_key"] for r in rows_of(audit.export(again, ACME, **SEPT)) if r["order"] == "OrdA"]
    assert keys == ["OrdA:FA:0", "OrdA:FA2:0"] and audit.verify(audit.export(again, ACME, **SEPT)) == []


# ---- the command line --------------------------------------------------------------------------------------------------

@pytest.fixture()
def world(monkeypatch):
    state = SimpleNamespace(record=records.Record(month(), limit=1000))
    monkeypatch.setattr(cli, "_ledger", lambda: SimpleNamespace(url="http://rpc"))
    monkeypatch.setattr(records, "read", lambda url, limit: state.record)
    monkeypatch.setattr(cli, "_fetch", lambda path: {"users/acme": {"id": ACME}}[path])
    return state


def run(capsys, *args: str) -> tuple[int, str, str]:
    capsys.readouterr()
    rc = cli.main(list(args))
    got = capsys.readouterr()
    return rc, got.out, got.err


def test_knos_audit_export_and_verify(capsys, world, tmp_path):
    rc, out, err = run(capsys, "audit", "export", "--owner", "acme", "--from", "2026-09-01", "--to", "2026-09-30", "--format", "csv")
    assert rc == 0 and out == audit.export(month(), ACME, **SEPT) and "9 line(s) for GitHub id 5001. Head: " in err
    path = tmp_path / "acme.json"
    rc, out, _ = run(capsys, "audit", "export", "--owner", str(ACME), "--to", "2026-09-30", "--from", "2026-09-01", "--format", "json", "--out", str(path))
    assert rc == 0 and out == "" and path.read_text(encoding="utf-8") == audit.export(month(), ACME, "json", **SEPT)
    rc, out, _ = run(capsys, "audit", "verify", str(path))
    assert rc == 0 and out.strip() == "valid. head sha256:" + audit.parse(path.read_text(encoding="utf-8"))[3]
    path.write_text(path.read_text(encoding="utf-8").replace('"paid_units":100000000', '"paid_units":100000001'), encoding="utf-8")
    rc, out, _ = run(capsys, "audit", "verify", str(path))
    assert rc == 1 and "Row 2 does not follow the row before it" in out and "totals" in out
    rc, out, _ = run(capsys, "audit", "verify", str(tmp_path / "missing.csv"))
    assert rc == 1 and out.startswith("Could not read")
    rc, out, _ = run(capsys, "audit", "export", "--owner", "acme", "--format", "xml")
    assert rc == 1 and "--format is csv or json" in out


def test_a_history_the_cluster_did_not_give_whole_is_refused_unless_partial(capsys, world):
    world.record = records.Record(month(), unread=2, limit=1000)
    rc, out, err = run(capsys, "audit", "export", "--owner", str(ACME), "--to", "2026-09-30")
    assert rc == 1 and "did not give the escrow's whole history" in out and "--partial" in out and "2 transactions could not be read" in err
    rc, out, err = run(capsys, "audit", "export", "--owner", str(ACME), "--to", "2026-09-30", "--partial")
    assert rc == 0 and audit.parse(out)[0]["partial"] == 1 and "partial: not a head to compare" in err and audit.verify(out) == []
