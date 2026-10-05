"""The audit export (knos.audit): everything one organisation's money paid for, from the escrow's log lines, hash-chained.

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

import _finance as fin
from knos import audit, cli, receipt, records
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
FEES = 2_500_000 + 250_000 + 250_000 + 4_000_000 + 1_250_000      # of the month's five payments: 2.5% of what each paid (A, B twice, C, D)


def line(event: str, at: int, tx: str, **fields) -> dict:
    return {"event": event, "v": 2, "at": at, "signer": "relayer", "keys": ["relayer"], "tx": tx, **fields}


def funded(order: str, at: int, tx: str, amount: int, source: str = BAL, by: int = 6001, flags: int = 0, repo: int = 7001, issue: int = 1) -> list[dict]:
    return [line("order_funded", at, tx, order=order, repo=repo, issue=issue, seq=0, amount=amount, fee=pay2.fee_of(amount), mode=0, by=by,
                 source=source, flags=flags, deadline=at + 30 * DAY),
            line("order_terms", at, tx, json=TERMS)]


def paid(order: str, at: int, tx: str, shares, of: int, sofar: int, judge: int, pr: int = 7, fee: int | None = None) -> list[dict]:
    """One payment's log lines. Its fee is the program's (order_pay.rs): the order's fee, which its funder put in on
    top under the tiers (2.50 on an order of 100), in the share of the order this payment pays; the relayer's tip is
    0.05 of it."""
    if fee is None:
        fee = pay2.order_fee(of) * sum(a for _, a in shares) // of
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
    assert (a["paid_units"], a["fee_units"], a["transaction"], a["funded_transaction"]) == (str(100 * U), str(pay2.order_fee(100 * U)), "PA", "FA")
    assert pay2.order_fee(100 * U) == 2_500_000 == int(a["funder_fee_units"])          # 2.50 on 100, in and out
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
    assert scope == {"type": "knos.audit-export", "version": 2, "program": str(pay2.PAY_ID), "owner_id": ACME, "from": "2026-09-01", "to": "2026-09-30",
                     "wallets": "", "partial": 0}
    assert count == len(rows) == 9 and head == audit._hash(rows[-1]) and rows[0]["prev"] == audit._hash(scope)
    assert sums == {"test USDC": {"lines": 9, "paid_units": 330 * U, "fee_units": FEES, "refunded_units": 50 * U, "reverted_units": 40 * U}}
    last = list(csv.reader(io.StringIO(text)))[-2:]
    assert last[0][:3] == ["total", "test USDC", "9"] and last[1][0] == "head" and last[1][1] == head
    doc = json.loads(audit.export(month(), ACME, "json", **SEPT))
    assert doc["head"] == head and doc["columns"] == list(audit.COLUMNS) and doc["rows"][0]["price_units"] == 100 * U
    # an owner with nothing: a file all the same, whose head is its scope's hash
    none = audit.export(month(), 4242, **SEPT)
    assert audit.verify(none) == [] and audit.parse(none)[3] == audit._hash(audit.parse(none)[0])


def csv_edit(text: str, change) -> str:
    """The file with its lines changed: `g[0]` is the columns, `g[n]` row n (the line that names the version stays first)."""
    version, *got = list(csv.reader(io.StringIO(text)))
    change(got)
    buf = io.StringIO()
    csv.writer(buf, lineterminator="\n").writerows([version, *got])
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
    monkeypatch.setattr(cli, "_fetch", lambda path: {"users/acme": {"id": ACME}, "users/dev1": {"id": 8001}}[path])
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
    assert rc == 0 and out.strip() == "valid. version 2. head sha256:" + audit.parse(path.read_text(encoding="utf-8"))[3]
    path.write_text(path.read_text(encoding="utf-8").replace('"paid_units":100000000', '"paid_units":100000001'), encoding="utf-8")
    rc, out, _ = run(capsys, "audit", "verify", str(path))
    assert rc == 1 and "Row 2 does not follow the row before it" in out and "totals" in out
    rc, out, _ = run(capsys, "audit", "verify", str(tmp_path / "missing.csv"))
    assert rc == 1 and out.startswith("Could not read")
    rc, out, _ = run(capsys, "audit", "export", "--owner", "acme", "--format", "xml")
    assert rc == 1 and "--format is csv or json, or netsuite, sap, coupa, quickbooks, generic" in out


def test_a_history_the_cluster_did_not_give_whole_is_refused_unless_partial(capsys, world):
    world.record = records.Record(month(), unread=2, limit=1000)
    rc, out, err = run(capsys, "audit", "export", "--owner", str(ACME), "--to", "2026-09-30")
    assert rc == 1 and "did not give the escrow's whole history" in out and "--partial" in out and "2 transactions could not be read" in err
    rc, out, err = run(capsys, "audit", "export", "--owner", str(ACME), "--to", "2026-09-30", "--partial")
    assert rc == 0 and audit.parse(out)[0]["partial"] == 1 and "partial: not a head to compare" in err and audit.verify(out) == []


# ---- version 2: bounties beside work orders, and files of version 1 --------------------------------------------------------

def test_an_organisation_that_only_posted_bounties_gets_its_bounties_not_an_empty_file():
    text = audit.export(fin.bounties(), ACME, **SEPT)
    rows = rows_of(text)
    assert audit.verify(text) == [] and text.splitlines()[0] == "knos.audit-export,version,2"
    assert [(r["record"], r["kind"], r["issue"]) for r in rows] == [("bounty", "paid", "21"), ("bounty", "paid", "22"), ("bounty", "held", "23"),
                                                                    ("bounty", "open", "25"), ("bounty", "refunded", "24")]
    faucet, own, held, still, back = rows
    # the faucet's test money, spent by whoever commented: 20 funded, 19.50 to the payee, 0.50 kept, out of the price
    assert (faucet["authorised_by"], faucet["source"], faucet["currency"]) == ("gh:9100 (faucet)", fin.FAUCET, "test USDC")
    assert (faucet["price_units"], faucet["paid_units"], faucet["fee_units"], faucet["funder_fee_units"]) == ("20000000", "19500000", "500000", "0")
    assert (faucet["supplier_ids"], faucet["wallets"], faucet["paid_each"], faucet["artifact"]) == ("8001", "W8001", "19500000", "pull:7001#31")
    assert (faucet["judge"], faucet["verdict"], faucet["mode"], faucet["terms_version"]) == ("repository", "accepted", "tests", "1")
    assert faucet["terms_hash"] == pay2.terms_hash(fin.JOB_TERMS.encode()).hex() and "bounty's own repository" in faucet["evaluator"]
    assert faucet["billing_key"] == f"{faucet['order']}:JF1:0" and faucet["order"] == str(pay2.job_pda(7001, 21, Pubkey.from_string(fin.FAUCET)))
    assert (own["authorised_by"], own["source"], own["transaction"], own["funded_transaction"]) == ("gh:6001 (spender)", BAL, "JP2", "JF2")
    # what applies to an order only is blank or 0 on a bounty's line
    assert all((r["standing"], r["private"], r["reverted_units"], r["funder_fee_units"]) == ("0", "0", "0", "0") for r in rows)
    assert (held["verdict"], held["held_units"], held["held_until"], held["supplier_ids"], held["transaction"]) == \
        ("accepted", "10000000", "2027-03-06T00:01:00Z", "8006", "JH3")
    assert (still["verdict"], still["held_units"], still["judge"]) == ("pending", "15000000", "")
    assert (back["verdict"], back["refunded_units"], back["transaction"]) == ("expired", "12000000", "JR4")
    assert audit.parse(text)[2] == {"test USDC": {"lines": 5, "paid_units": 58_500_000, "fee_units": 1_500_000, "refunded_units": 12_000_000, "reverted_units": 0}}
    assert {r["issue"] for r in rows_of(audit.export(fin.bounties(), OTHER, **SEPT))} == {"26"}


def test_a_mix_of_orders_and_bounties_is_one_chain_and_the_same_bytes_for_both_parties():
    for fmt in ("csv", "json"):
        mine, theirs = audit.export(fin.mix(), ACME, fmt, **SEPT), audit.export(fin.mix() + later()[len(month()):], ACME, fmt, **SEPT)
        assert mine == theirs and audit.verify(mine) == []
    rows = rows_of(audit.export(fin.mix(), ACME, **SEPT))
    assert [r["record"] for r in rows].count("bounty") == 5 and [r["record"] for r in rows].count("order") == 9
    assert [r["seq"] for r in rows] == [str(n) for n in range(1, 15)] and [r["time"] for r in rows] == sorted(r["time"] for r in rows)
    # the orders' lines say what they said in version 1, and more: which Balance, the terms' version, each payee's share
    old = {(r["order"], r["kind"], r["transaction"]): r for r in audit.parse((fin.DATA / "audit_v1.csv").read_text(encoding="utf-8"))[1]}
    for r in rows:
        if r["record"] == "order":
            was = old[r["order"], r["kind"], r["transaction"]]
            assert all(r[c] == was[c] for c in audit.COLUMNS_V1 if c not in ("seq", "prev")) and r["source"] == BAL and r["terms_version"] == "1"
    split = next(r for r in rows if r["order"] == "OrdD")
    assert (split["supplier_ids"], split["paid_each"]) == ("8001;8004", "30000000;20000000")
    assert next(r for r in rows if r["transaction"] == "PC")["held_until"] == "2026-10-08T00:00:00Z"        # the end of the review window
    assert next(r for r in rows if r["order"] == "OrdF")["held_until"] == "2026-10-14T00:00:00Z"             # an open order's deadline
    doc = json.loads(audit.export(fin.mix(), ACME, "json", **SEPT))
    assert doc["version"] == 2 == doc["scope"]["version"] and doc["columns"] == list(audit.COLUMNS)


def test_a_file_of_version_1_still_verifies_and_is_told_from_version_2():
    # in the format 0.3.15 wrote: `write` with a scope of version 1 gave 0.3.15's own two files byte for byte when it was
    # given the month 0.3.15 had. The month's payments have since been given the fee the program takes (2.50 on an order
    # of 100, where the old fixture said a flat 0.40), and the two files were written again from it, so the head moved.
    for name in ("audit_v1.csv", "audit_v1.json"):
        text = (fin.DATA / name).read_text(encoding="utf-8")
        scope, rows, _sums, head, count = audit.parse(text)
        assert audit.verify(text) == [] and scope["version"] == 1 and count == 9 and head == "97490bd9b957baba28969a0ff4c88c80ad0fcfbbb65388ed865d12052aacc068"
        assert set(rows[0]) == set(audit.COLUMNS_V1) and "record" not in rows[0]
    text = (fin.DATA / "audit_v1.csv").read_text(encoding="utf-8")
    assert audit.write(*(audit.parse(text)[i] for i in (0, 1, 3)), "csv") == text                # version 1 is written back as version 1 was
    got = list(csv.reader(io.StringIO(text)))
    got[2][audit.COLUMNS_V1.index("paid_units")] = "1"                                             # the second row's amount, in a version 1 file
    buf = io.StringIO()
    csv.writer(buf, lineterminator="\n").writerows(got)
    assert any("Row 3 does not follow the row before it" in s for s in audit.verify(buf.getvalue()))
    # a version 2 head never equals a version 1 head for the same orders: the scope's version is hashed first
    assert audit.parse(audit.export(month(), ACME, **SEPT))[3] != audit.parse(text)[3]
    v2 = audit.export(month(), ACME, **SEPT)
    for wrong in (v2.replace("knos.audit-export,version,2", "knos.audit-export,version,3", 1),     # a version this release does not know
                  v2.split("\n", 1)[1],                                                             # version 2's columns with no version line
                  "knos.audit-export,version,2\n" + text,                                           # version 1's columns under a version 2 line
                  json.dumps({**json.loads(audit.export(month(), ACME, "json", **SEPT)), "version": 1})):
        with pytest.raises(audit.Refused):
            audit.verify(wrong)


# ---- the four linked objects ---------------------------------------------------------------------------------------------

def mix_rows() -> list[dict]:
    return rows_of(audit.export(fin.mix(), ACME, **SEPT))


def test_a_record_is_four_linked_objects_made_from_the_statement_alone():
    by = {r["id"]: r for r in audit.records_of(mix_rows(), audit.read_refs(fin.REFS))}
    assert len(by) == 13 and all(tuple(k for k in r if k in audit.OBJECTS) == audit.OBJECTS for r in by.values())
    assert {r["settlement"]["status"] for r in by.values()} <= set(audit.SETTLEMENTS)
    a = by["OrdA:FA:0"]
    assert a["authorisation"]["buyer"] == {"owner_id": "5001", "funder": "gh:5001", "login": None}
    assert a["authorisation"]["supplier"] == [{"github_id": "8001", "wallet": "W8001", "units": 100 * U}]
    assert a["authorisation"]["scope"] == {"repository_id": "7001", "issue": "1", "deliverable": "OrdA:FA:0", "private": False}
    assert a["authorisation"]["budget"] == {"kind": "Balance", "address": BAL, "limits_at_funding": None, "said": audit.NO_LIMITS}
    assert a["authorisation"]["approved_by"] == {"funder": "gh:6001", "role": "spender", "two_person": False, "multisig": None, "said": audit.NO_SECOND}
    assert a["acceptance"]["artifact"] == "pull:7001#7" and a["acceptance"]["verdict"] == "accepted" and a["acceptance"]["accepted"] is True
    assert a["acceptance"]["policy"] == {"terms_hash": pay2.terms_hash(TERMS.encode()).hex(), "version": "1", "mode": "merge"}
    assert a["acceptance"]["evaluators"] == [{"kind": "repository", "rule": audit.JUDGES[0][1], "independent_of_buyer": False, "independent_of_seller": None}]
    assert [e["what"] for e in a["acceptance"]["evidence"]] == ["funded", "paid"] and a["acceptance"]["evidence"][1]["link"] == "https://explorer.solana.com/tx/PA?cluster=devnet"
    assert (a["commercial"]["amount_units"], a["commercial"]["fee_units"], a["commercial"]["invoice_ref"], a["commercial"]["billed_before"]) == (100 * U, 2_500_000, "PO-4411 line 2", False)
    assert a["settlement"]["status"] == "paid on devnet (test money)" and a["settlement"]["paid_units"] == 100 * U
    # each state, from what the chain shows
    assert by["OrdC:FC:0"]["settlement"]["status"] == "reverted" and by["OrdC:FC:0"]["settlement"]["reverted_units"] == 40 * U
    assert by["OrdC:FC:0"]["commercial"]["correction"]["kind"] == "credit" and by["OrdC:FC:0"]["commercial"]["correction"]["units"] == 40 * U
    assert by["OrdC:FC:0"]["commercial"]["amount_units"] == 160 * U and by["OrdC:FC:0"]["acceptance"]["artifact"] == "pull:7001#13"
    assert by["OrdE:FE:0"]["settlement"]["status"] == "refunded" and by["OrdE:FE:0"]["acceptance"]["accepted"] is False
    assert by["OrdF:FF:0"]["settlement"]["status"] == "held" and "2026-10-14T00:00:00Z" in by["OrdF:FF:0"]["settlement"]["said"]
    held = next(r for r in by.values() if r["record"] == "bounty" and r["settlement"]["status"] == "payable")
    assert held["commercial"]["amount_units"] == 10 * U and "binds a wallet" in held["settlement"]["said"] and held["authorisation"]["supplier"][0]["github_id"] == "8006"
    # a standing order: each pull request its own deliverable, and the rest that went back is nobody's
    assert by["OrdB:FB:11"]["commercial"]["amount_units"] == 10 * U and by["OrdB:FB:-"]["settlement"]["status"] == "refunded"
    assert by["OrdB:FB:-"]["acceptance"]["accepted"] is False and by["OrdB:FB:-"]["authorisation"]["supplier"] == []
    # what only the buyer can say: its reference, a payment by bank (and the chain paid too: said), a dispute
    b12 = by["OrdB:FB:12"]
    assert b12["settlement"]["status"] == "paid outside Knos" and b12["settlement"]["paid_outside"] == "2026-09-28 bank ref 77120"
    assert "not paid twice" in b12["settlement"]["said"] and b12["commercial"]["invoice_ref"] == "PO-4412 line 1" and by["OrdB:FB:11"]["commercial"]["invoice_ref"] is None
    d = by["OrdD:FD:0"]
    assert d["commercial"]["dispute"] == "open, as the refs file says: the second payee's share is contested"
    assert [e["units"] for e in d["authorisation"]["supplier"]] == [30 * U, 20 * U]
    assert next(r for r in audit.records_of(mix_rows()) if r["id"] == "OrdD:FD:0")["commercial"]["dispute"].startswith("ruled by the arbiter the order named (line ")
    # the faucet's money is said to be nobody's approval
    faucet = next(r for r in by.values() if r["authorisation"]["budget"]["kind"] == "faucet Balance")
    assert faucet["authorisation"]["approved_by"]["said"] == audit.FAUCET and faucet["authorisation"]["budget"]["address"] == fin.FAUCET
    # nothing but the rows went in: the same rows give the same records, whoever holds them
    assert audit.records_of(mix_rows(), audit.read_refs(fin.REFS)) == list(by.values())
    shown = audit.record_lines(a)
    assert [s for s in shown if s.isupper()] == ["AUTHORISATION", "ACCEPTANCE", "COMMERCIAL RECORD", "SETTLEMENT STATUS"]


def test_a_receipt_adds_the_limits_at_funding_and_each_evaluators_independence():
    got = audit.records_of(mix_rows(), None, fin.extras()["receipts"])
    c = next(r for r in got if r["id"] == "OrdC:FC:0")
    assert c["authorisation"]["budget"]["limits_at_funding"] == {"cap_per_order": "250000000", "daily": "0", "total": "1000000000", "repositories": [7001]}
    assert c["authorisation"]["budget"]["said"] is None and c["authorisation"]["buyer"]["login"] == "acme-bot"
    assert c["acceptance"]["evaluators"] == [{"kind": "attestor", "repository_id": 9900, "owner_id": 9901, "actor_id": 9902, "runner": "github-hosted",
                                               "independent_of_buyer": True, "independent_of_seller": True}]
    assert c["acceptance"]["independence"] == receipt.ONE_JUDGE
    assert next(r for r in got if r["id"] == "OrdA:FA:0")["authorisation"]["budget"]["limits_at_funding"] is None      # no receipt given for it
    assert any("independent of the buyer: yes; of the seller: yes" in s for s in audit.record_lines(c))


def squads_accounts(threshold: int = 2):
    """A Squads multisig, its first vault and one executed proposal, as bytes laid out the way knos.mainnet_check reads them."""
    from knos import mainnet_check as mc
    squads = Pubkey.from_string("SQDS4ep65T869zMMBKyuUq6aD6EgTu8psMjkvj52pCf")
    create, members = Pubkey(bytes([21]) * 32), [Pubkey(bytes([n]) * 32) for n in (31, 32, 33)]
    ms = mc.multisig_address(create, squads)
    data = (mc.MULTISIG + bytes(create) + bytes(32) + threshold.to_bytes(2, "little") + (0).to_bytes(4, "little") + (4).to_bytes(8, "little")
            + (0).to_bytes(8, "little") + b"\0" + b"\xff" + len(members).to_bytes(4, "little") + b"".join(bytes(m) + b"\x07" for m in members))
    proposal = mc.proposal_address(ms, 4, squads)
    approved = members[:2]
    pdata = (mc.PROPOSAL + bytes(ms) + (4).to_bytes(8, "little") + bytes([5]) + (T0).to_bytes(8, "little", signed=True) + b"\xfe"
             + len(approved).to_bytes(4, "little") + b"".join(bytes(m) for m in approved) + (0).to_bytes(4, "little") * 2)
    held = {str(ms): (str(squads), data), str(proposal): (str(squads), pdata)}
    return str(squads), str(ms), str(mc.vault_address(ms, squads)), str(proposal), [str(m) for m in members], held


def test_an_order_a_squads_vault_funded_names_the_vault_its_threshold_and_who_approved():
    squads, ms, vault, proposal, members, held = squads_accounts()
    keys = ["relayer", "11111111111111111111111111111111", proposal, ms, vault, "OrdV"]
    found = audit.squads_approval(held.get, keys, vault, squads)
    assert found == {"multisig": ms, "vault": vault, "threshold": 2, "members": members, "time_lock": 0, "proposal": 4, "approved": members[:2]}
    assert audit.squads_approval(held.get, keys, WALLET, squads) is None                 # an ordinary wallet: no multisig among the accounts has it as vault
    assert audit.squads_approval(held.get, ["relayer", vault], vault, squads) is None    # the funding names no multisig
    closed = audit.squads_approval({ms: held[ms]}.get, keys, vault, squads)             # the proposal's account was closed since
    assert closed["threshold"] == 2 and closed["approved"] is None and closed["proposal"] is None

    ev = month() + funded("OrdV", T0 + 18 * DAY, "FV", 90 * U, source=vault, by=0) + paid("OrdV", T0 + 19 * DAY, "PV", [(8005, 90 * U)], 90 * U, 90 * U, 0)
    rows = rows_of(audit.export(ev, ACME, wallets=[vault], **SEPT))
    rec = next(r for r in audit.records_of(rows, approvals={"FV": found}) if r["id"] == "OrdV:FV:0")
    by = rec["authorisation"]["approved_by"]
    assert (by["funder"], by["role"], by["two_person"], by["multisig"]) == (f"wallet:{vault}", "wallet", True, found)
    assert by["said"] == ("A Squads vault funded this: 2 of its 3 members had to approve, and 2 did. This is the two-person approval Knos has today. "
                          "It is the multisig's own rule, not a workflow inside Knos.")
    assert rec["authorisation"]["budget"] == {"kind": "wallet", "address": vault, "limits_at_funding": None, "said": "A wallet has no limits of Knos's: it spends what it holds."}
    shown = "\n".join(audit.record_lines(rec))
    assert f"Multisig     {ms}, vault {vault}: 2 of 3" in shown and f"Approved     {members[0]}, {members[1]}" in shown
    # with no approval read, a wallet is one signature, and the record says where the threshold would be read
    plain = next(r for r in audit.records_of(rows) if r["id"] == "OrdV:FV:0")["authorisation"]["approved_by"]
    assert (plain["two_person"], plain["said"]) == (False, audit.ONE_WALLET)
    # a threshold of one is not two people, and is said
    one = audit.squads_approval(squads_accounts(1)[5].get, keys, vault, squads)
    single = next(r for r in audit.records_of(rows, approvals={"FV": one}) if r["id"] == "OrdV:FV:0")["authorisation"]["approved_by"]
    assert single["two_person"] is False and "one member alone could approve" in single["said"]


# ---- the supplier's side ---------------------------------------------------------------------------------------------------

def review() -> list[dict]:
    """The mix, and an order paid with a part held back whose review window is still open at the month's end."""
    more = funded("OrdW", T0 + 22 * DAY, "FW", 100 * U) + paid("OrdW", T0 + 23 * DAY, "PW", [(8001, 80 * U)], 100 * U, 80 * U, 2, pr=44)
    return fin.mix() + more + [line("order_warranty", T0 + 23 * DAY, "PW", order="OrdW", held=20 * U, until=T0 + 53 * DAY)]


def test_what_a_supplier_is_owed_and_why_from_the_chain_alone():
    mine = audit.owed(review(), 8001, "2026-09-30")
    assert [(r["line"], r["reason"], r["units"], r["until"], r["deliverable"], r["transaction"]) for r in mine] == [
        (1, "reverted", 40 * U, "", "OrdC:FC:0", "VC"), (2, "in a review window", 20 * U, "2026-10-24T00:00:00Z", "OrdW:FW:0", "PW")]
    assert all(r["evidence"] == f"https://explorer.solana.com/tx/{r['transaction']}?cluster=devnet" and r["currency"] == "test USDC" for r in mine)
    waiting = audit.owed(review(), 8006)
    assert [(r["reason"], r["units"], r["until"], r["record"]) for r in waiting] == [("held for a wallet", 10 * U, "2027-03-06T00:01:00Z", "bounty")]
    assert audit.owed(review(), 8002) == [] and audit.owed(review(), 8001, "2026-09-09")[0]["reason"] == "in a review window"   # before the revert: OrdC's holdback
    # a dispute is the parties' word, from a refs file, and names its deliverable
    said = audit.owed(review(), 8004, refs=audit.read_refs(fin.REFS))
    assert [(r["reason"], r["deliverable"]) for r in said] == [("disputed", "OrdD:FD:0")] and "second payee's share is contested" in said[0]["said"]
    text = "\n".join(audit.owed_lines(mine, "dev1"))
    assert "in a review window until 2026-10-24T00:00:00Z: 20.000000 test USDC" in text and "What a supplier cannot see without the buyer:" in text
    assert "private order" in text and "Nothing is held" in "\n".join(audit.owed_lines([], "dev9"))


def test_a_refs_file_is_read_and_a_wrong_one_is_refused():
    refs = audit.read_refs(fin.REFS)
    assert audit.ref_of(refs, "OrdB:FB:12")["ref"] == "PO-4412 line 1" and audit.ref_of(refs, "OrdB:FB:11") is None
    assert audit.ref_of(refs, "OrdA:FA:0") == {"order": "OrdA", "ref": "PO-4411 line 2", "paid_outside": "", "dispute": ""}
    assert audit.read_refs("order,ref\nOrdA,PO-1\n\n") == {"OrdA": {"order": "OrdA", "ref": "PO-1", "paid_outside": "", "dispute": ""}}
    for wrong in ("", "ref,order\nPO-1,OrdA\n", "order,ref,amount\nOrdA,PO-1,5\n", "order,ref\n,PO-1\n", "order,ref\nOrdA,PO-1,extra\n"):
        with pytest.raises(audit.Refused):
            audit.read_refs(wrong)


def test_knos_audit_show_owed_and_a_finance_format(capsys, world, tmp_path):
    world.record = records.Record(review(), limit=1000)
    refs = tmp_path / "refs.csv"
    refs.write_text(fin.REFS, encoding="utf-8")
    rc, out, _ = run(capsys, "audit", "show", "OrdA", "--chain-lines-only", "--refs", str(refs))
    assert rc == 0 and out.splitlines()[0] == "Deliverable OrdA:FA:0 (a work order)" and "Invoice line PO-4411 line 2" in out
    assert [s for s in out.splitlines() if s.isupper()] == ["AUTHORISATION", "ACCEPTANCE", "COMMERCIAL RECORD", "SETTLEMENT STATUS"]
    rc, out, _ = run(capsys, "audit", "show", "OrdB", "--chain-lines-only", "--json")       # a standing order: every deliverable of it
    assert rc == 0 and [r["id"] for r in json.loads(out)] == ["OrdB:FB:11", "OrdB:FB:12", "OrdB:FB:-"]
    rc, out, _ = run(capsys, "audit", "show", "Nowhere", "--chain-lines-only")
    assert rc == 1 and "shows no order, bounty or deliverable Nowhere" in out
    rc, out, _ = run(capsys, "audit", "owed", "--payee", "dev1", "--to", "2026-09-30")
    assert rc == 0 and out.startswith("Owed to dev1, from the escrow's own records on devnet") and "in a review window until 2026-10-24T00:00:00Z" in out
    rc, out, _ = run(capsys, "audit", "owed", "--payee", "8006", "--json")
    assert rc == 0 and json.loads(out)[0]["reason"] == "held for a wallet"
    from knos import exports
    for fmt in exports.FORMATS:
        rc, out, err = run(capsys, "audit", "export", "--owner", str(ACME), "--from", "2026-09-01", "--to", "2026-09-30", "--format", fmt, "--refs", str(refs))
        scope, rows, _s, head, _n = audit.parse(audit.export(review(), ACME, **SEPT))
        assert rc == 0 and out == exports.write(fmt, scope, rows, head, audit.read_refs(fin.REFS)) and exports.FORMATS[fmt]["source"] in err.replace("\n", "")
    path = tmp_path / "generic.csv"
    rc, _, _ = run(capsys, "audit", "export", "--owner", str(ACME), "--to", "2026-09-30", "--from", "2026-09-01", "--format", "generic", "--out", str(path))
    rc2, out, _ = run(capsys, "audit", "verify", str(path))
    assert (rc, rc2) == (0, 0) and out.strip() == "valid. version 2. head sha256:" + audit.parse(audit.export(review(), ACME, **SEPT))[3]
    rc, out, _ = run(capsys, "audit", "export", "--owner", str(ACME), "--format", "netsuite", "--refs", str(tmp_path / "none.csv"))
    assert rc == 1 and out.startswith("Could not read")
