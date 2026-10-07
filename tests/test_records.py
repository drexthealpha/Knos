"""Receipts, statements, the SIEM export and invoices (knos.records): all recomputed from the escrows' log lines.

The recorded inputs are the ones tests/test_network_stats.py reads: every transaction of the first deployment on devnet, and
twelve jobs played through the second deployment's test build. The check that matters is the first one: what these
records add up to is what scripts/network_stats.py says was paid, to the unit.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import network_stats  # noqa: E402

from knos import cli, fees, ghwords, records  # noqa: E402
from knos.settle.v2 import pay as pay2  # noqa: E402

RECORDED = ROOT / "tests" / "web" / "recorded"
KNOS = 142920951
OWN = frozenset({KNOS})
SCENARIO_DAY = "2026-09-21"            # the scenario's block times are not real: its first transaction is at 1790000000 (2026-09-21)


def history(name: str) -> list[dict]:
    out = []
    for t in json.loads((RECORDED / name).read_text(encoding="utf-8"))["transactions"]:
        out += [{**ev, "tx": t["signature"]} for ev in records.events_of(t)]
    return out


@pytest.fixture(scope="module")
def scenario() -> list[dict]:
    return history("second_deployment_scenario.json")


@pytest.fixture(scope="module")
def first() -> list[dict]:
    return history("devnet_first_deployment.json")


def line(event: str, at: int, tx: str, signer: str = "relayer", v: int = 2, **fields) -> dict:
    """An event as `events_of` gives it, for the cases the recordings do not hold."""
    return {"event": event, "v": v, "at": at, "signer": signer, "keys": [signer], "tx": tx, **fields}


TERMS = '{"accept":"","checks":[],"deny":[],"mode":"merge","paths":[],"reserve":7,"v":1}'


def funded_and_paid(n: int, at: int, repo=7001, issue=1, by=6001, payee=8001, amount=20_000_000, source="Bal1", **paid) -> list[dict]:
    fee = fees.OLD.job(amount)          # made by knos_pay 2.1: a record keeps the fee that was charged
    return [line("funded", at, f"F{n}", repo=repo, issue=issue, amount=amount, mode=0, by=by, source=source, faucet=0),
            line("terms", at, f"F{n}", json=TERMS),
            line("paid", at + 100, f"P{n}", repo=repo, issue=issue, payee=payee, amount=amount - fee, fee=fee, to=f"Wallet{payee}", **paid)]


# ---- the sums are the chain's sums -------------------------------------------------------------------------------------
def test_receipts_add_up_to_what_the_public_numbers_say_to_the_unit(scenario, first):
    for events, paid, count in ((scenario, 134_550_000, 8), (first, 62_400_000, 6), (first + scenario, 196_950_000, 14)):
        rows = records.payments(events)
        s = network_stats.summarize(events, OWN)
        sides = [s["outside"], *s["apart"].values()]
        assert sum(r["amount_units"] for r in rows) == s["totals"]["paid_amount"] == paid
        assert sum(r["fee_units"] for r in rows) == sum(x["fees"] for x in sides)
        assert len(rows) == s["totals"]["completed"] == count
        assert sum(r["total_units"] for r in rows) == sum(r["amount_units"] + r["fee_units"] for r in rows)
        assert [r["unix"] for r in rows] == sorted(r["unix"] for r in rows)          # oldest first
    # and the sum of the text column, read back from the CSV, is the same figure
    rows = records.payments(scenario)
    got = list(csv.DictReader(io.StringIO(records.receipts_csv(rows))))
    assert sum(int(x["amount"].replace(".", "")) for x in got) == 134_550_000 and len(got) == 8


def test_a_receipt_names_the_terms_the_funding_logged_and_both_transactions(scenario):
    jobs, _ = records.jobs_of(scenario)
    row = records.payments(scenario)[0]
    job = next(j for j in jobs if (j["repo"], j["issue"]) == (7001, 1))
    assert row["terms_hash"] == hashlib.sha256(job["terms"].encode()).hexdigest() == pay2.terms_hash(job["terms"].encode()).hex()
    assert (row["transaction"], row["funded_transaction"]) == (job["paid_tx"], job["tx"]) and row["transaction"] != row["funded_transaction"]
    assert (row["deployment"], row["repository_id"], row["issue"], row["payee_id"], row["funder"], row["owner_id"], row["commenter_id"]) == (2, 7001, 1, 8001, "gh:5001", 5001, 6001)
    assert (row["amount"], row["fee"], row["total"], row["currency"]) == ("19.500000", "0.500000", "20.000000", "test USDC")
    assert row["wallet"] == "5peSS7w49SKcpbHCEhpzajWqi7gbgRVKAXWej2WjL9yw" and row["date"] == SCENARIO_DAY and row["time"].startswith(SCENARIO_DAY + "T")
    # the first deployment has no terms and does not print the wallet: those are empty, not guessed
    old = records.payments(history("devnet_first_deployment.json"))[0]
    assert (old["terms_hash"], old["wallet"], old["deployment"]) == ("", "", 1) and old["funder"].startswith("gh:")


def test_a_payment_whose_funding_is_older_than_the_history_still_has_a_receipt():
    events = [line("paid", 5000, "P9", repo=7001, issue=9, payee=8001, amount=19_500_000, fee=500_000, to="W")] + funded_and_paid(1, 1000)
    rows = records.payments(events)
    assert [(r["issue"], r["funder"], r["terms_hash"], r["funded_transaction"]) for r in rows] == [(1, "gh:6001", rows[0]["terms_hash"], "F1"), (9, "", "", "")]
    assert rows[0]["terms_hash"] and sum(r["amount_units"] for r in rows) == 39_000_000
    s = network_stats.summarize(events, OWN)
    assert s["totals"]["completed"] == 2 and s["totals"]["unmatched_paid"] == 1 and s["totals"]["paid_amount"] == 19_500_000     # the stats leave it out of the sum, and say so


def test_the_pull_request_a_paid_line_names_is_in_the_receipt_and_otherwise_empty():
    rows = records.payments(funded_and_paid(1, 1000, pr=42) + funded_and_paid(2, 2000, issue=2))
    assert [r["pull_request"] for r in rows] == [42, None]
    assert list(csv.DictReader(io.StringIO(records.receipts_csv(rows))))[1]["pull_request"] == ""
    assert json.loads(records.receipts_jsonl(rows).splitlines()[1])["pull_request"] is None


def test_units_are_written_exactly_and_a_mint_that_is_not_test_usdc_is_not_dressed_as_it():
    assert [records.units_text(n) for n in (0, 1, 19_500_000, 123_456_789_012)] == ["0.000000", "0.000001", "19.500000", "123456.789012"]
    other = [line("balance", 1, "B1", owner=5001, authority="Auth1", mint="MintOther")]
    events = other + funded_and_paid(1, 1000, source="Bal1")
    jobs, _ = records.jobs_of(events)
    job = {**jobs[0], "mint": "MintOther", "faucet": False}
    assert records._currency(job) == "mint MintOther" and records._currency({**job, "mint": str(pay2.USDC_DEVNET)}) == "test USDC"
    row = records._row(job)
    assert (row["amount"], row["fee"], row["total"], row["currency"], row["amount_units"]) == ("", "", "", "mint MintOther", 19_500_000)
    assert records.money_text(19_500_000, "mint MintOther") == "19500000 units of mint MintOther"
    assert records.totals([row, records._row({**job, "mint": ""})]).keys() == {"mint MintOther", "test USDC"}      # never added across mints


# ---- who and when ---------------------------------------------------------------------------------------------------
def test_select_by_owner_payee_and_days(scenario):
    rows = records.payments(scenario)
    ids = lambda picked: [(r["repository_id"], r["issue"]) for r in picked]  # noqa: E731
    assert ids(records.select(rows, owner_id=5001)) == [(7001, 1), (7001, 2)]                  # the Balance's owner
    assert ids(records.select(rows, owner_id=6001)) == []                                       # a commenter who spent someone else's Balance is not its owner
    assert ids(records.select(rows, owner_id=5005)) == [(7006, 1)]
    assert ids(records.select(rows, payee_id=8001)) == [(7001, 1), (7003, 3)]
    assert ids(records.select(rows, owner_id=5001, payee_id=8002)) == [(7001, 2)]
    assert records.select(rows, owner_id=99) == [] and records.select(rows, payee_id=99) == []
    day = SCENARIO_DAY
    assert len(records.select(rows, first=day, last=day)) == 8 and records.select(rows, first="2026-09-22") == [] and records.select(rows, last="2026-09-20") == []
    # a wallet that funded itself has no owner: its repository's owner is found only when GitHub can say
    wallet_funded = records.select(rows, owner_id=777)
    assert wallet_funded == []
    names = records.Names(lambda path: {"full_name": "acme/widgets", "owner": {"id": 777}} if path == "repositories/7003" else {"full_name": "other/x", "owner": {"id": 1}})
    got = records.select(rows, owner_id=777, names=names)
    assert ids(got) == [(7003, 3)] and got[0]["repository"] == "acme/widgets" and got[0]["payee"] == ""      # the stand-in has no logins: empty, not guessed


def test_names_are_asked_once_each_and_stop_at_the_first_refusal():
    asked = []

    def get(path: str) -> dict:
        asked.append(path)
        if path == "user/2":
            raise OSError("nope")
        if path == "user/3":
            err = OSError("HTTP Error 403: rate limit exceeded")
            err.code = 403                                      # type: ignore[attr-defined]
            raise err
        return {"login": f"u{path.split('/')[-1]}", "full_name": "o/r"}
    names = records.Names(get)
    assert names.user(1) == "u1" and names.user(1) == "u1" and asked == ["user/1"]                  # once
    assert names.user(0) == "" and names.repo(0) == {} and asked == ["user/1"]                      # id 0 is nobody and costs nothing
    assert names.user(2) == "" and names.problems == ["GitHub did not answer for user/2: nope."]    # a failure is words, and then it stops asking
    assert names.user(4) == "" and asked == ["user/1", "user/2"]
    assert names.repo(5) == {} and names.problems and len(names.problems) == 1
    # a 404 is only an unnamed account: the next one is still asked
    gone = OSError("HTTP Error 404")
    gone.code = 404                                             # type: ignore[attr-defined]
    seen = []
    names = records.Names(lambda path: seen.append(path) or (_ for _ in ()).throw(gone) if path == "user/1" else {"login": "kept"})
    assert (names.user(1), names.user(2), names.problems) == ("", "kept", [])
    # a 403 carries the rate-limit hint
    forbidden = records.Names(get)
    assert forbidden.user(3) == "" and forbidden.problems == [f"GitHub refused user/3 (HTTP 403); {ghwords.RATE}."]
    assert records.Names(None).user(5) == "" and records.Names(None).problems == []                  # not asked: not named


def test_days_and_months_are_checked_in_words():
    assert records.month_days("2026-09") == ("2026-09-01", "2026-09-30") and records.month_days("2028-02")[1] == "2028-02-29" and records.month_days("2026-12")[1] == "2026-12-31"
    for bad in ("2026-9", "2026-13", "2026-00", "26-09", "", "2026-09-01", "1969-12", None):
        with pytest.raises(ValueError, match="YYYY-MM"):
            records.month_days(bad)
    assert records.day_of("2026-02-28") == "2026-02-28"
    for bad in ("2026-02-30", "2026-2-3", "yesterday", "", "2026-09-01T00:00"):
        with pytest.raises(ValueError, match="a day like 2026-09-30"):
            records.day_of(bad, "--from")


# ---- the files --------------------------------------------------------------------------------------------------------
def test_csv_has_one_header_one_row_each_and_no_cell_a_spreadsheet_would_run(scenario):
    rows = records.select(records.payments(scenario), owner_id=5001, names=records.Names(lambda p: {"full_name": "=HYPERLINK(1)", "login": "-2+3"}))
    text = records.receipts_csv(rows)
    got = list(csv.reader(io.StringIO(text)))
    assert tuple(got[0]) == records.RECEIPT_COLUMNS and len(got) == 3 and all(len(x) == len(records.RECEIPT_COLUMNS) for x in got)
    head = {c: got[1][i] for i, c in enumerate(records.RECEIPT_COLUMNS)}
    assert head["repository"] == "'=HYPERLINK(1)" and head["payee"] == "'-2+3" and head["amount"] == "19.500000" and head["amount_units"] == "19500000"
    assert records.receipts_csv([]) == ",".join(records.RECEIPT_COLUMNS) + "\n"
    lines = records.receipts_jsonl(rows).splitlines()
    assert [list(json.loads(x)) for x in lines] == [list(records.RECEIPT_COLUMNS)] * 2 and json.loads(lines[0])["amount_units"] == 19_500_000
    assert records.receipts_jsonl([]) == ""


def test_a_statement_is_one_sellers_month_with_its_transactions(scenario):
    rows = records.payments(scenario)
    st = records.statement(rows, 8001, "vendor-bot", "2026-09")
    assert (st["from"], st["to"], len(st["payments"])) == ("2026-09-01", "2026-09-30", 2)
    assert st["totals"] == {"test USDC": {"payments": 2, "amount_units": 34_125_000, "fee_units": 875_000, "total_units": 35_000_000}}
    said = records.statement_lines(st)
    assert said[0].startswith("Statement for vendor-bot (GitHub id 8001), 2026-09:")
    assert all(r["transaction"] in x for r, x in zip(st["payments"], said[1:3], strict=True)) and "repository 7001#1" in said[1]
    assert said[-1] == "  2 payments: 34.125000 test USDC received, 0.875000 test USDC in fees, 35.000000 test USDC out of escrow."
    assert "funded by gh:5001" in said[1] and "funded by wallet:GLWd" in said[2]
    # another month, an unknown seller and a seller that could not be told are empty, and say so
    for st in (records.statement(rows, 8001, "vendor-bot", "2026-10"), records.statement(rows, 31337, "nobody", "2026-09"), records.statement(rows, 0, "x", "2026-09")):
        assert st["payments"] == [] and st["totals"] == {} and records.statement_lines(st)[-1] == "  No payment to this account in that month."
    named = records.statement(rows, 8001, "vendor-bot", "2026-09", records.Names(lambda p: {"login": "vendor-bot", "full_name": "octo/widgets"}))
    assert "octo/widgets#1" in records.statement_lines(named)[1]
    with pytest.raises(ValueError):
        records.statement(rows, 8001, "vendor-bot", "September")


def test_an_invoice_is_a_plain_page_with_every_outside_string_escaped(scenario):
    rows = records.payments(scenario)
    evil = records.Names(lambda p: {"full_name": "<script>alert(1)</script>/\"x\"", "login": "a&b<i>"})
    inv = records.invoice(rows, 5001, "acme <b>", "2026-09", evil, issued=1_791_000_000)
    assert inv["number"] == "KNOS-acmeb-202609" and inv["issued"] == "2026-10-03" and len(inv["lines"]) == 2
    assert inv["totals"]["test USDC"] == {"payments": 2, "amount_units": 48_750_000, "fee_units": 1_250_000, "total_units": 50_000_000}
    page = records.invoice_html(inv)
    assert page.startswith("<!doctype html>") and "<script" not in page.lower() and "<b>" not in page and "<i>" not in page and "http" not in page
    assert "&lt;script&gt;" in page and "acme &lt;b&gt;" in page and "a&amp;b&lt;i&gt;" in page
    assert "19.500000 test USDC" in page and "50.000000 test USDC" in page and "test money, not money" in page and "No tax is calculated" in page
    assert all(r["transaction"] in page for r in inv["lines"])
    sheet = list(csv.DictReader(io.StringIO(records.invoice_csv(inv))))
    assert [x["transaction"] for x in sheet] == [r["transaction"] for r in inv["lines"]] and sum(int(x["total_units"]) for x in sheet) == 50_000_000
    # a month with nothing says so, and an owner that could not be told has no lines
    for empty in (records.invoice(rows, 5001, "acme", "2026-08"), records.invoice(rows, 0, "x", "2026-09")):
        assert empty["lines"] == [] and "No payment was made out of this owner's money" in records.invoice_html(empty)
    assert records.invoice(rows, 5001, "###", "2026-09")["number"] == "KNOS-5001-202609"


def test_month_spent_is_what_an_owner_funded_that_month_less_what_came_back(scenario):
    assert records.month_spent(scenario, 5001, "2026-09") == 72          # 20 + 30 + 10 + 12 funded from its Balance; the 5 of issue 4 was refunded
    assert records.month_spent(scenario, 5001, "2026-10") == 0 and records.month_spent(scenario, 99, "2026-09") == 0 and records.month_spent(scenario, 0, "2026-09") == 0
    assert records.month_spent(scenario + funded_and_paid(1, 1_790_100_000, by=0, source="W", amount=12_500_000), 5003, "2026-09") == 8
    events = [line("funded", 1_790_000_000, "F1", repo=1, issue=1, amount=12_500_000, mode=0, by=77, source="Wal", faucet=0)]
    assert records.month_spent(events, 77, "2026-09") == records.Decimal("12.5")        # a commenter's own funding counts for them


# ---- the SIEM export --------------------------------------------------------------------------------------------------
def test_the_siem_export_is_one_json_object_per_event_with_the_same_keys(scenario, first):
    events = first + scenario
    text = records.siem_lines(events)
    got = [json.loads(x) for x in text.splitlines()]
    assert len(got) == len(events) and text.endswith("\n") and "\n\n" not in text
    assert all(tuple(x)[:len(records.SIEM_FIELDS)] == records.SIEM_FIELDS for x in got)
    assert {x["action"] for x in got} >= {"funded", "terms", "paid", "held", "refunded", "balance", "bound"}
    assert [x["transaction"] for x in got] == [ev["tx"] for ev in events]
    paid = [x for x in got if x["action"] == "paid" and x["deployment"] == 2]
    assert len(paid) == 8 and sum(x["amount"] for x in paid) == 134_550_000 and sum(x["fee"] for x in paid) == 3_450_000
    p = paid[0]
    assert (p["repository_id"], p["issue"], p["payee"], p["to"], p["repository"]) == (7001, 1, 8001, "5peSS7w49SKcpbHCEhpzajWqi7gbgRVKAXWej2WjL9yw", None)
    assert p["time"].endswith("Z") and p["unix"] > 0 and p["actor"].startswith("wallet:")
    f = next(x for x in got if x["action"] == "funded" and x["deployment"] == 2)
    t = next(x for x in got if x["action"] == "terms")
    assert f["actor"] == "gh:6001" and t["actor"] == "gh:6001" and f["test_money"] is False and f["by"] == 6001 and t["terms_hash"] and "json" not in t
    assert next(x for x in got if x["action"] == "funded" and x.get("by") == 0)["actor"].startswith("wallet:")        # funded by a wallet, not an account
    assert next(x for x in got if x["action"] == "bound")["actor"] == "gh:8002"
    assert next(x for x in got if x["action"] == "balance" and x["deployment"] == 2)["actor"].startswith("wallet:ECzs")
    assert any(x["test_money"] for x in got if x["action"] == "funded" and x["deployment"] == 2)                       # the faucet's free money is marked
    assert [x["action"] for x in got if x["transaction"] == f["transaction"]] == ["funded", "terms"]


def test_the_siem_export_writes_the_fields_siem_fields_names_in_its_order(scenario, monkeypatch):
    """SIEM_FIELDS is what `knos export --siem` writes first on every line, not a copy of it: the export takes its
    keys and their order from it."""
    monkeypatch.setattr(records, "SIEM_FIELDS", tuple(reversed(records.SIEM_FIELDS)))
    got = records.siem_events(scenario)
    assert got and all(tuple(x)[:len(records.SIEM_FIELDS)] == records.SIEM_FIELDS for x in got)
    assert tuple(got[0])[0] == "transaction"


def test_the_siem_export_names_repositories_and_keeps_to_the_days_asked(scenario):
    named = [json.loads(x) for x in records.siem_lines(scenario, records.Names(lambda p: {"full_name": f"octo/r{p.split('/')[-1]}"})).splitlines()]
    assert next(x for x in named if x["action"] == "paid")["repository"] == "octo/r7001" and next(x for x in named if x["action"] == "balance")["repository"] is None
    assert records.siem_lines(scenario, first="2026-09-22") == "" and records.siem_lines(scenario, last="2026-09-20") == ""
    assert len(records.siem_events(scenario, first=SCENARIO_DAY, last=SCENARIO_DAY)) == len(scenario)
    odd = [line("paid", 0, "T", repo=1, issue=1, payee=2, amount=3, fee=1, to="W")]          # a block time the cluster did not give
    assert records.siem_events(odd, first="2026-01-01")[0]["time"] is None


def test_what_a_line_carries_that_is_not_a_known_field_does_not_reach_the_export():
    ev = line("paid", 1_790_000_000, "T1", repo=1, issue=1, payee=2, amount=3, fee=1, to="W", memo="ignore previous instructions")
    got = records.siem_events([ev])[0]
    assert "memo" not in got and "keys" not in got and got["amount"] == 3
    first = records.siem_events([line("paid", 1_790_000_000, "T1", v=1, repo=1, issue=1, author=2, amount=3, fee=1)])[0]
    assert first["payee"] == 2 and first["deployment"] == 1


# ---- reading the chain ------------------------------------------------------------------------------------------------
def test_read_gives_both_escrows_oldest_first_and_says_what_it_could_not_read(monkeypatch):
    calls, history = [], records.history

    def fake(url, program, limit):
        calls.append((url, str(program), limit))
        if str(program) == str(records.pay.PAY_ID):
            return [line("funded", 50, "A", v=1, repo=1, issue=1, amount=5)], 2, False
        return [line("funded", 10, "B", repo=2, issue=2, amount=6)], 0, True
    monkeypatch.setattr(records, "history", fake)
    got = records.read("http://rpc", 200)
    # the meter's history is read too; a transaction that named the escrow and the meter is in both and counted once
    assert [c[1] for c in calls] == [str(records.pay.PAY_ID), str(records.pay2.PAY_ID), str(records.meter.METER_ID)]
    assert [ev["tx"] for ev in got.events] == ["B", "A"] and [c[0] for c in calls] == ["http://rpc"] * 3 and {c[2] for c in calls} == {200}
    assert got.unread == 2 and got.cut == (2, "meter")
    assert got.notes() == ["2 transactions could not be read (the public RPC throttled): what follows is a lower bound.",
                           "Only the newest 200 transactions of the second deployment's escrow were read: older payments are not here.",
                           "Only the newest 200 transactions of knos_meter were read: older evaluations are not here."]
    assert records.Record([]).notes() == []

    def with_meter(url, program, limit):
        if str(program) == records.METER:
            return [line("meter_eval", 30, "E", buyer=5001, seller=8001, verdict=1, rate=7, fee=1, month=197001), line("funded", 10, "B", repo=2, issue=2, amount=6)], 0, False
        return fake(url, program, limit)
    monkeypatch.setattr(records, "history", with_meter)
    got = records.read("http://rpc", 200)
    assert [(ev["event"], ev["tx"]) for ev in got.events] == [("funded", "B"), ("meter_eval", "E"), ("funded", "A")] and got.cut == (2,)
    assert [ev["tx"] for ev in records.read("http://rpc", 200, with_meter=False).events] == ["B", "A"]         # a caller that only counts money
    # a relay's transactions are version 1 on a 2.1 cluster: asked for with a lower version, the cluster would refuse every one of them
    asked = []
    monkeypatch.setattr(records.chain, "call", lambda url, method, params, timeout=0: asked.append((method, params)) or
                        ([{"signature": "S", "err": None}] if method == "getSignaturesForAddress" else None))
    assert history("http://rpc", records.METER, 5) == ([], 0, False)
    assert [m for m, _p in asked] == ["getSignaturesForAddress", "getTransaction"] and asked[1][1][1]["maxSupportedTransactionVersion"] == 1


def test_a_transactions_fee_payer_and_logs_come_from_one_reader_that_asks_for_version_1(monkeypatch):
    """chain.Ledger.payer_of (the relay asks it whose transaction did a token's work) and logs read one answer."""
    asked = []
    tx = {"transaction": {"message": {"accountKeys": ["Payer1111", "Other"]}}, "meta": {"logMessages": ["Program log: x"]}}
    monkeypatch.setattr(records.chain, "call", lambda url, method, params, timeout=0: asked.append((method, params)) or tx)
    led = records.chain.Ledger("http://rpc")
    assert led.payer_of("S") == "Payer1111" and led.logs("S") == ["Program log: x"]
    assert [m for m, _p in asked] == ["getTransaction"] * 2 and all(p[1]["maxSupportedTransactionVersion"] == 1 for _m, p in asked)
    monkeypatch.setattr(records.chain, "call", lambda url, method, params, timeout=0: None)
    assert led.payer_of("S") is None and led.logs("S") == []


def test_every_reader_of_a_transaction_asks_for_version_1():
    """A relay's transactions are version 1 on a 2.1 cluster, and a cluster refuses to give one to a reader that names a
    lower version (or none: then it gives legacy transactions only). So every place that asks a cluster for a
    transaction, in the package, the scripts, the site and the JavaScript client, names version 1."""
    root = Path(__file__).resolve().parents[1]
    readers = {}
    for folder, kinds in (("src", (".py",)), ("scripts", (".py", ".mjs", ".js", ".sh")), ("web", (".js", ".html")), ("sdk", (".js", ".mjs")), (".github", (".yml",))):
        for path in sorted(p for p in (root / folder).rglob("*") if p.is_file() and p.suffix in kinds and "node_modules" not in p.parts and ".test." not in p.name):
            text = path.read_text(encoding="utf-8")
            asks = len(re.findall(r"""["']getTransaction["']\s*,""", text))
            if asks:
                readers[path.relative_to(root).as_posix()] = (asks, re.findall(r"""maxSupportedTransactionVersion["']?\s*:\s*(\w+)""", text))
    assert readers == {"scripts/rehearse_fork.py": (1, ["1"]), "sdk/settle/agent.js": (1, ["1"]), "scripts/latency_stages.py": (1, ["1"]),
                       "src/knos/bundle.py": (2, ["1", "1", "1"]), "src/knos/chain.py": (1, ["1"]), "src/knos/observe.py": (1, ["1"]),      # bundle.py's third is its getBlock
                       "src/knos/records.py": (2, ["1", "1"]), "web/buyer.js": (1, ["1"]), "web/first.js": (1, ["1"]), "scripts/provenance.py": (1, ["1"]), "scripts/exercise_public.py": (1, ["1"])}, readers


# ---- the commands -----------------------------------------------------------------------------------------------------
@pytest.fixture
def world(monkeypatch, scenario):
    asked = []
    monkeypatch.setattr(cli, "_ledger", lambda: SimpleNamespace(url="http://rpc"))
    monkeypatch.setattr(records, "read", lambda url, limit: records.Record(scenario, unread=1, limit=limit))

    def fetch(path: str) -> dict:
        asked.append(path)
        if path.startswith("repositories/"):         # only repository 7001 is acme's: the wallet-funded jobs on 7003 and 7007 belong to someone else
            return {"full_name": "octo/widgets", "owner": {"id": 5001 if path.endswith("/7001") else 1}}
        return {"users/acme": {"id": 5001}, "users/vendor-bot": {"id": 8001}}.get(path) or {"login": "someone"}
    monkeypatch.setattr(cli, "_fetch", fetch)
    return asked


def run(capsys, *args: str) -> tuple[int, str, str]:
    capsys.readouterr()
    rc = cli.main(list(args))
    got = capsys.readouterr()
    return rc, got.out, got.err


def test_knos_receipts_prints_csv_or_jsonl_for_an_owner(capsys, world):
    rc, text, err = run(capsys, "receipts", "--owner", "acme")
    rows = list(csv.DictReader(io.StringIO(text)))
    assert rc == 0 and len(rows) == 2 and {r["repository"] for r in rows} == {"octo/widgets"} and {r["payee"] for r in rows} == {"someone"}
    assert "1 transactions could not be read" in err and "users/acme" in world
    rc, text, _ = run(capsys, "receipts", "--owner", "5001", "--format", "jsonl", "--no-names", "--from", SCENARIO_DAY, "--to", SCENARIO_DAY)
    assert rc == 0 and [json.loads(x)["issue"] for x in text.splitlines()] == [1, 2] and json.loads(text.splitlines()[0])["repository"] == ""
    rc, text, err = run(capsys, "receipts", "--owner", "5001", "--no-names", "--from", "2026-10-01")
    assert rc == 0 and text.splitlines() == [",".join(records.RECEIPT_COLUMNS)] and "No payment out of 5001's money in that range." in err


def test_knos_receipts_refuses_in_one_line(capsys, world, tmp_path):
    assert run(capsys, "receipts", "--owner", "5001", "--format", "xml")[:2] == (1, "--format is csv or jsonl; 'xml' is neither.\n")
    assert run(capsys, "receipts", "--owner", "5001", "--from", "2026-13-01")[1] == "--from is a day like 2026-09-30; '2026-13-01' is not one.\n"
    assert run(capsys, "receipts", "--owner", "5001", "--from", "2026-09-30", "--to", "2026-09-01")[1] == "--from 2026-09-30 is after --to 2026-09-01.\n"
    assert run(capsys, "receipts", "--owner", "5001", "--limit", "0")[1] == "--limit is a number of transactions, at least 1.\n"
    assert run(capsys, "receipts")[0] == 2                                                                                  # --owner is required
    out_file = tmp_path / "r.csv"
    rc, text, _ = run(capsys, "receipts", "--owner", "5001", "--no-names", "--out", str(out_file))
    assert rc == 0 and text == f"Wrote 2 payments to {out_file}.\n" and len(out_file.read_text(encoding="utf-8").splitlines()) == 3


def test_a_cluster_that_will_not_answer_is_one_line_and_a_github_refusal_has_its_hint(capsys, monkeypatch, scenario):
    def down(url, limit):
        raise OSError("Connection refused")
    monkeypatch.setattr(cli, "_ledger", lambda: SimpleNamespace(url="http://rpc"))
    monkeypatch.setattr(records, "read", down)
    assert run(capsys, "receipts", "--owner", "5001", "--no-names")[:2] == (1, "Solana did not give the escrows' history: Connection refused.\n")
    monkeypatch.setattr(records, "read", lambda url, limit: records.Record(scenario))

    def refused(path):
        err = OSError("HTTP Error 403: rate limit exceeded")
        err.code = 403                                          # type: ignore[attr-defined]
        raise err
    monkeypatch.setattr(cli, "_fetch", refused)
    rc, text, err = run(capsys, "receipts", "--owner", "acme")
    assert rc == 1 and text == f"GitHub refused users/acme (HTTP 403); {ghwords.RATE}.\n"
    rc, text, err = run(capsys, "receipts", "--owner", "5001")                       # names asked for and refused: the rows stay, the names are empty, and it says why
    assert rc == 0 and len(text.splitlines()) == 3 and err.count("HTTP 403") == 1 and "Names it could not get are left empty." in err


def test_knos_statement_text_csv_and_json(capsys, world):
    rc, text, _ = run(capsys, "statement", "--seller", "vendor-bot", "--month", "2026-09")
    lines = text.splitlines()
    assert rc == 0 and lines[0].startswith("Statement for vendor-bot (GitHub id 8001), 2026-09") and lines[-1].startswith("  2 payments: 34.125000 test USDC received")
    rc, text, _ = run(capsys, "statement", "--seller", "8001", "--month", "2026-09", "--format", "csv", "--no-names")
    assert rc == 0 and len(list(csv.DictReader(io.StringIO(text)))) == 2
    rc, text, _ = run(capsys, "statement", "--seller", "8001", "--month", "2026-09", "--format", "json", "--no-names")
    doc = json.loads(text)
    assert rc == 0 and doc["seller_id"] == 8001 and doc["totals"]["test USDC"]["amount_units"] == 34_125_000 and list(doc["payments"][0]) == list(records.RECEIPT_COLUMNS)
    assert run(capsys, "statement", "--seller", "8001", "--month", "09-2026")[:2] == (1, "A month is written YYYY-MM, like 2026-09; '09-2026' is not one.\n")
    assert run(capsys, "statement", "--seller", "8001", "--month", "2026-09", "--format", "pdf")[0] == 1
    # `knos statement` is a group since 0.3.17 (make, approve, pay, ...), so --seller is no longer an option the
    # parser requires: the month's statement without it stops with a sentence that says what to write
    rc, text, said = run(capsys, "statement", "--month", "2026-09")
    assert rc == 1 and "Say whose month: knos statement --seller X --month YYYY-MM" in text + said


def test_knos_export_needs_siem_and_prints_json_lines(capsys, world, tmp_path):
    rc, text, _ = run(capsys, "export")
    assert rc == 1 and text.startswith("Say what to export: knos export --siem")
    rc, text, _ = run(capsys, "export", "--siem", "--no-names")
    got = [json.loads(x) for x in text.splitlines()]
    assert rc == 0 and len(got) == len(records.siem_events(records.read("", 1).events)) and got[0]["action"] == "balance"
    rc, text, _ = run(capsys, "export", "--siem", "--no-names", "--from", "2027-01-01")
    assert (rc, text) == (0, "")
    out_file = tmp_path / "events.jsonl"
    rc, text, _ = run(capsys, "export", "--siem", "--no-names", "--out", str(out_file))
    assert rc == 0 and text.startswith(f"Wrote {len(got)} events to ") and len(out_file.read_text(encoding="utf-8").splitlines()) == len(got)


def test_knos_invoice_writes_a_page_and_a_csv(capsys, world, tmp_path):
    rc, text, _ = run(capsys, "invoice", "--owner", "acme", "--month", "2026-09", "--out", str(tmp_path / "out"))
    page, sheet = tmp_path / "out" / "KNOS-acme-202609.html", tmp_path / "out" / "KNOS-acme-202609.csv"
    assert rc == 0 and f"Wrote {page} and {sheet}: 2 payment(s), 50.000000 test USDC out of escrow." in text
    assert "Invoice KNOS-acme-202609" in page.read_text(encoding="utf-8") and len(sheet.read_text(encoding="utf-8").splitlines()) == 3
    rc, text, _ = run(capsys, "invoice", "--owner", "acme", "--month", "2026-08", "--out", str(tmp_path))
    assert rc == 0 and text.endswith("no payment that month.\n")
    blocked = tmp_path / "file"
    blocked.write_text("x", encoding="utf-8")
    rc, text, _ = run(capsys, "invoice", "--owner", "5001", "--month", "2026-09", "--out", str(blocked), "--no-names")
    assert rc == 1 and text.startswith(f"Could not write the invoice in {blocked}:")
    assert run(capsys, "invoice", "--owner", "5001", "--month", "2026-9")[0] == 1


def test_the_records_commands_are_listed_under_money_in_the_help(capsys):
    rc, text, _ = run(capsys, "--help")
    money = text[text.index("For money"):]
    assert rc == 0 and all(f"│ {name} " in money for name in ("receipts", "statement", "export", "invoice"))
    assert "--meter" in " ".join(money.split())                                     # the meter's statement is named where statements are
    rc, text, _ = run(capsys, "statement", "--help")
    assert rc == 0 and "--meter" in text and "--buyer" in text and "knos_meter" in " ".join(text.split())
    for name in ("receipts", "statement", "export", "invoice"):
        rc, text, _ = run(capsys, name, "--help")
        assert rc == 0 and "--no-names" in text and "--limit" in text


# ---- work orders and the meter: the programs' own lines, from the test builds in LiteSVM ---------------------------------
class Recorder:
    """Every transaction a harness chain lands, as a cluster would return it: what `events_of` reads."""

    def __init__(self, c):
        self.c, self.txs, self._send = c, [], c.send
        c.send = self.send

    def send(self, ixs, payer=None, signers=(), tag=None) -> bool:
        ok = self._send(ixs, payer, signers, tag)
        if ok:
            keys = list(dict.fromkeys([str((payer or self.c.payer).pubkey()), *[str(a.pubkey) for i in ixs for a in i.accounts], *[str(i.program_id) for i in ixs]]))
            self.txs.append({"signature": f"T{len(self.txs)}", "blockTime": self.c.now(), "meta": {"err": None, "logMessages": self.c.logs},
                             "transaction": {"message": {"accountKeys": keys}}})
        return ok

    def events(self) -> list[dict]:
        return [{**ev, "tx": t["signature"]} for t in self.txs for ev in records.events_of(t)]


@pytest.fixture(scope="module")
def orders() -> tuple[list[dict], dict]:
    """Six work orders through the tree's knos_pay (2.2: every fee below is 0.30% of the amount, the fee this build takes): a split, one held, one with a holdback that is released, one reverted,
    a standing offer whose rest goes back, and one reserved, cancelled and refunded with a kill fee. And a job, to
    show the two are kept apart. Returns (events, the names of what happened)."""
    pytest.importorskip("solders.litesvm")
    sys.path.insert(0, str(ROOT / "tests"))
    from solders.keypair import Keypair

    import test_order_terms as terms_
    from _order import MAINT, OWNER, REPO, USDC, OrderChain

    c = OrderChain()
    rec = Recorder(c)
    wallet = lambda: Keypair().pubkey()  # noqa: E731
    a, b, taker = (9001, wallet()), (9002, wallet()), (9003, wallet())
    split = c.fund_balance(11, 100 * USDC)
    assert c.pay(split, [(a[0], 7000, a[1]), (b[0], 3000, b[1])], pr=21), c.err
    held = c.fund_balance(12, 20 * USDC)
    assert c.pay(held, [(9004, 10_000, None)], pr=22), c.err
    hold = pay2.opts(holdback_bps=2000, warranty_days=2)
    kept, undone = c.fund_balance(13, 50 * USDC, options=hold), c.fund_balance(14, 50 * USDC, options=hold)
    assert c.pay(kept, [(a[0], 10_000, a[1])], pr=23) and c.pay(undone, [(b[0], 10_000, b[1])], pr=24), c.err
    c.warp(3600)
    assert terms_.revert(c, undone), c.err
    c.warp(2 * 86_400)
    assert terms_.release(c, kept), c.err
    standing = c.fund_wallet(15, 25 * USDC, options=pay2.opts(flags=pay2.F_STANDING, rate=10 * USDC))
    assert terms_.pay_pr(c, standing, [(a[0], 10_000, a[1])], pr=31) and terms_.pay_pr(c, standing, [(b[0], 10_000, b[1])], pr=32), c.err
    assert c.refund(standing), c.err                     # less than one rate is left: the rest goes back at once
    taken = c.fund_balance(16, 40 * USDC, options=pay2.opts(reserve_days=7, kill_bps=1000), work=30 * 86_400)
    assert c.bind(taker[0], taker[1]) and terms_.reserve(c, taken, taker[0], 5) and terms_.cancel(c, taken), c.err
    c.warp(7 * 86_400 + 1)
    c.token_account(taker[1], c.usdc)
    assert terms_.refund(c, taken, pay2.ata(taker[1], c.usdc)), c.err
    # the Balance was opened before anything here: its line, as the escrow printed it then (it says whose money the orders spent)
    opened = line("balance", 1, "B0", owner=OWNER, authority=str(c.owner.pubkey()), mint=str(c.usdc))
    return [opened, *rec.events()], dict(split=str(split), held=str(held), kept=str(kept), undone=str(undone), standing=str(standing), taken=str(taken), a=a, b=b,
                              taker=taker, repo=REPO, owner=OWNER, maint=MAINT, funder=str(c.funder.pubkey()), balance=str(c.bal))


def test_a_work_orders_lines_are_read_as_its_own_events_and_folded_into_orders(orders):
    events, n = orders
    names = {ev["event"] for ev in events}
    assert names >= {"balance", "order_funded", "order_terms", "order_paid", "order_settled", "order_held", "order_warranty", "order_released", "order_reverted",
                     "order_reserved", "order_cancelled", "order_kill", "order_refunded", "bound"}
    assert not names & {"funded", "paid", "held", "refunded"}            # no job was funded here: an order's line is never taken for a job's
    assert records.jobs_of(events)[0] == []
    got, other = records.orders_of(events)
    by = {o["order"]: o for o in got}
    assert [o["issue"] for o in got] == [11, 12, 13, 14, 15, 16] and all(o["repo"] == n["repo"] and o["v"] == 2 for o in got)
    s = by[n["split"]]
    assert (s["state"], s["amount"], s["fee_escrowed"], s["net"], s["fee"], s["by"], s["owner"], s["funder"], s["from_balance"], s["source"]) == (
        "paid", 100_000_000, 300_000, 100_000_000, 300_000, n["maint"], n["owner"], f"gh:{n['owner']}", True, n["balance"])
    assert [(p["payee"], p["amount"], p["to"], p["pr"], p["kind"]) for p in s["payments"]] == [(9001, 70_000_000, str(n["a"][1]), 21, "paid"),
                                                                                             (9002, 30_000_000, str(n["b"][1]), 21, "paid")]
    assert [p["fee"] for p in s["payments"]] == [300_000, 0] and s["payees"] == [9001, 9002] and s["terms"] and s["pr"] == 21
    assert (by[n["held"]]["state"], by[n["held"]]["payee"], by[n["held"]]["net"]) == ("held", 9004, 0)
    k = by[n["kept"]]                                                    # 80% at the merge, the holdback after its warranty: all of it reached the payee
    assert (k["state"], k["net"], k["fee"], [p["kind"] for p in k["payments"]], [p["amount"] for p in k["payments"]]) == (
        "paid", 50_000_000, 150_000, ["paid", "released"], [40_000_000, 10_000_000])
    u = by[n["undone"]]                                                  # reverted inside the warranty: the holdback and the fee on it went back
    assert (u["state"], u["net"], u["reverted_amount"], u["fee"]) == ("paid", 40_000_000, 10_030_000, 120_000)
    st = by[n["standing"]]                                               # a wallet's standing offer: two pull requests paid, the rest refunded
    assert (st["state"], st["standing"], st["funder"], st["net"], st["from_balance"], st["by"]) == ("paid", True, f"wallet:{n['funder']}", 20_000_000, False, 0)
    assert [p["pr"] for p in st["payments"]] == [31, 32] and st["refunded_amount"] > 5_000_000 and st["paid_at"] <= st["refunded_at"]
    t = by[n["taken"]]                                                   # reserved, cancelled, refunded: the taker's kill fee is a payment of its own kind
    assert (t["state"], t["reserved_by"], t["net"], t["kill"]) == ("refunded", 9003, 0, {"taker": 9003, "amount": 4_000_000, "held": False})
    assert t["cancelled_at"] and t["refunded_amount"] == 36_120_000 and [(p["kind"], p["amount"]) for p in t["payments"]] == [("kill", 4_000_000)]
    assert (other["refunded"], other["reverted"], other["released"], other["cancelled"], other["reserved"], other["kill_fees"]) == (2, 1, 1, 1, 1, 1)
    # jobs and orders together: what the public numbers and a budget count
    work, both = records.work_of(events + funded_and_paid(1, events[-1]["at"] + 10))
    assert len(work) == 7 and [("seq" in j) for j in work].count(True) == 6 and both["refunded"] == 2 and both["bound"] == 1


def test_receipts_a_budget_and_the_export_count_work_orders_too(orders):
    events, n = orders
    rows = records.payments(events)
    assert [(r["issue"], r["pull_request"], r["payee_id"], r["amount_units"], r["fee_units"]) for r in rows] == [
        (11, 21, 9001, 70_000_000, 300_000), (11, 21, 9002, 30_000_000, 0), (13, 23, 9001, 40_000_000, 120_000), (14, 24, 9002, 40_000_000, 120_000),
        (13, None, 9001, 10_000_000, 30_000), (15, 31, 9001, 10_000_000, rows[5]["fee_units"]), (15, 32, 9002, 10_000_000, rows[6]["fee_units"]),
        (16, None, 9003, 4_000_000, 0)]
    assert all(r["deployment"] == 2 and r["repository_id"] == n["repo"] and r["terms_hash"] and r["funded_transaction"] and r["transaction"] for r in rows)
    assert {r["funder"] for r in rows} == {f"gh:{n['owner']}", f"wallet:{n['funder']}"} and rows[0]["wallet"] == str(n["a"][1])
    assert records.totals(records.select(rows, owner_id=n["owner"]))[rows[0]["currency"]]["amount_units"] == 194_000_000
    month = records._day(events[1]["at"])[:7]
    # the owner's month: 100 + 20 + 50 + 50 funded from its Balance; the 40 of the cancelled order went back (its kill fee is not a purchase)
    assert records.month_spent(events, n["owner"], month) == 220 and records.month_spent(events, 99, month) == 0
    siem = records.siem_events(events)
    f = next(x for x in siem if x["action"] == "order_funded")
    assert f["actor"] == f"gh:{n['maint']}" and f["order"] == n["split"] and f["test_money"] is False and (f["repository_id"], f["issue"], f["amount"]) == (n["repo"], 11, 100_000_000)
    assert next(x for x in siem if x["action"] == "order_terms")["actor"] == f"gh:{n['maint']}"
    assert next(x for x in siem if x["action"] == "order_paid")["pr"] == 21 and next(x for x in siem if x["action"] == "order_reserved")["taker"] == 9003
    assert all(tuple(x)[:len(records.SIEM_FIELDS)] == records.SIEM_FIELDS for x in siem)


def test_the_public_numbers_count_a_work_order_as_one_job_under_the_same_four_kinds(orders):
    events, n = orders
    s = network_stats.summarize(events, OWN)
    assert s["totals"]["funded"] == 6 and s["by_deployment"]["second"] == {"funded": 6, "completed": 4} and s["totals"]["held"] == 1
    # the stand-in for Circle's USDC is real money to the record, and none of these funders paid itself: all six are outside
    assert (s["outside"]["funded"], s["outside"]["completed"], s["outside"]["funders"], s["outside"]["payees"]) == (6, 4, 2, 2)
    assert s["outside"]["paid_amount"] == 210_000_000 and s["totals"]["refunded"] == 2
    assert s["orders"] == {"funded": 6, "completed": 4, "open": 0, "held": 1, "in_warranty": 0, "refunded": 1, "standing": 1, "private": 0, "payments": 7,
                           "funded_amount": 285_000_000, "paid_amount": 210_000_000, "held_back": 0, "outside": 6, "reverted": 1, "released": 1, "cancelled": 1,
                           "reserved": 1, "assigned": 0, "topped_up": 0, "kill_fees": 1}
    assert [p["issue"] for p in s["recent"]] == [15, 14, 13, 11] and s["recent"][0]["order"] == n["standing"]
    # a split that pays its funder a share, or Knos's own account, is never outside use
    own = network_stats.summarize(events, frozenset({9002}))
    assert (own["apart"]["own"]["funded"], own["outside"]["funded"]) == (3, 3)
    mine = [dict(ev, payee=n["maint"]) if ev["event"] == "order_paid" and ev.get("pr") == 21 and ev["payee"] == 9002 else ev for ev in events]
    assert network_stats.summarize(mine, OWN)["apart"]["self"]["funded"] == 1
    assert network_stats.kind_of({"v": 2, "by": 0, "owner": 0, "payee": 5, "payees": [5, 6], "wallet": "W", "to": "X", "tos": ["X", "W"], "state": "paid",
                                  "faucet": False}) == "self"


def test_the_meters_evaluations_are_counted_per_month():
    pytest.importorskip("solders.litesvm")
    sys.path.insert(0, str(ROOT / "tests"))
    from _meter import BUYER, SELLER, Meter

    from knos.settle.v2 import meter
    c = Meter()
    rec = Recorder(c)
    mint = c.new_mint()
    _wallet, credits = c.open(mint, BUYER, 5 * 1_000_000)
    c.set_used(BUYER, meter.FREE_PER_MONTH)
    c.fees(mint)                                         # FEE_OWNER's token account of the mint, made
    assert c.record(credits, c.aud("a" * 40)) and c.record(credits, c.aud("b" * 40, verdict=0)), c.err
    first = meter.yyyymm(c.now())
    c.warp(meter.next_month(c.now()) - c.now() + 60)
    assert c.record(credits, c.aud("c" * 40, rate=3_000_000)), c.err
    events = rec.events()
    assert [ev["event"] for ev in events if ev["event"].startswith("meter_")] == ["meter_credits", "meter_eval", "meter_eval", "meter_eval"]
    months = records.meter_months(events)
    one, two = (f"{str(m)[:4]}-{str(m)[4:]}" for m in (first, meter.yyyymm(c.now())))
    assert list(months) == [one, two]
    assert months[one] == {"evaluations": 2, "accepted": 1, "rejected": 1, "value": 2_000_000, "fees": 100_000, "buyers": 1, "sellers": 1}
    assert months[two]["evaluations"] == 1 and months[two]["value"] == 3_000_000
    s = network_stats.summarize(events, OWN)
    assert s["meter"] == {"evaluations": 3, "accepted": 2, "rejected": 1, "fees": s["meter"]["fees"], "by_month": months} and s["totals"]["funded"] == 0
    assert records.jobs_of(events)[0] == [] and records.orders_of(events)[0] == [] and BUYER and SELLER
    assert next(x for x in records.siem_events(events) if x["action"] == "meter_eval")["buyer"] == BUYER


def test_knos_statement_meter_is_the_meters_month_and_an_invoice_and_the_export_list_its_evaluations(capsys, monkeypatch, tmp_path):
    """The meter's own lines, from its test build in LiteSVM: `knos statement --meter` recomputes one buyer's and one
    seller's month from them and holds it against the account the program keeps; an owner's invoice lists the
    evaluations it was billed for; the SIEM export has each one."""
    pytest.importorskip("solders.litesvm")
    sys.path.insert(0, str(ROOT / "tests"))
    from _meter import BUYER, SELLER, Meter

    from knos.settle.v2 import meter
    c = Meter()
    rec = Recorder(c)
    mint = c.new_mint()
    _wallet, credits = c.open(mint, BUYER, 5 * 1_000_000)
    c.set_used(BUYER, meter.FREE_PER_MONTH)
    c.fees(mint)
    assert c.record(credits, c.aud("a" * 40)) and c.record(credits, c.aud("b" * 40, verdict=0)), c.err
    first = meter.yyyymm(c.now())
    c.warp(meter.next_month(c.now()) - c.now() + 60)
    assert c.record(credits, c.aud("c" * 40, rate=3_000_000)), c.err
    one, two = (f"{str(m)[:4]}-{str(m)[4:]}" for m in (first, meter.yyyymm(c.now())))
    events = rec.events()

    class Cluster:      # what knos.chain.Ledger gives of a cluster: the transactions that named an address, their logs, an account
        url, most = "http://rpc", None

        def history(self, address, most=500):
            sigs = [t["signature"] for t in reversed(rec.txs) if str(address) in t["transaction"]["message"]["accountKeys"]]
            yield from sigs[:self.most]

        def logs(self, signature):
            return next(t["meta"]["logMessages"] for t in rec.txs if t["signature"] == signature)

        def account(self, address):
            return c.data(address)
    led = Cluster()
    monkeypatch.setattr(cli, "_ledger", lambda: led)
    monkeypatch.setattr(cli, "_fetch", lambda path: {"users/acme": {"id": BUYER}, "users/vendor-bot": {"id": SELLER}}[path])
    # -- the statement, printed like the escrow's
    rc, text, _ = run(capsys, "statement", "--meter", "--buyer", "acme", "--seller", "vendor-bot", "--month", one)
    lines = text.splitlines()
    assert rc == 0 and lines[0].startswith(f"Meter statement for buyer acme (GitHub id {BUYER}) and seller vendor-bot (GitHub id {SELLER}), {one}: UTC days {one}-01 to ")
    assert lines[0].endswith("recomputed from knos_meter's log lines on Solana devnet.")
    assert lines[1:] == ["  2 billable evaluations: 1 accepted, 1 rejected.",
                         "  Declared value of the accepted ones: 2.000000 (2000000 units). Fees from the buyer's credits: 0.100000 (100000 units).",
                         "  Both are in the smallest unit of the credits' mint, written with six decimals as test USDC has; the log does not name the mint.",
                         "  The month's account on chain says the same."]
    rc, text, _ = run(capsys, "statement", "--meter", "--buyer", str(BUYER), "--seller", str(SELLER), "--month", two, "--format", "json")
    doc = json.loads(text)
    want = {"evaluations": 1, "accepted": 1, "rejected": 0, "value_units": 3_000_000, "fee_units": doc["totals"]["fee_units"]}
    assert rc == 0 and doc["totals"] == doc["account"] == want and doc["agrees"] is True and (doc["buyer_id"], doc["seller_id"], doc["month"]) == (BUYER, SELLER, two)
    st = meter.statement(led, BUYER, SELLER, first)        # the function the command prints
    assert (st.evaluations, st.accepted, st.rejected, st.value, st.fees) == (2, 1, 1, 2_000_000, 100_000)
    rc, text, _ = run(capsys, "statement", "--meter", "--buyer", str(BUYER), "--seller", str(SELLER), "--month", one, "--format", "csv")
    [sheet] = list(csv.DictReader(io.StringIO(text)))
    assert rc == 0 and (sheet["evaluations"], sheet["accepted"], sheet["rejected"], sheet["value_units"], sheet["fee_units"], sheet["agrees_with_account"]) == (
        "2", "1", "1", "2000000", "100000", "yes")
    # a node whose history is cut short: the account is the count, and the statement says so
    led.most = 1
    rc, text, _ = run(capsys, "statement", "--meter", "--buyer", str(BUYER), "--seller", str(SELLER), "--month", one)
    assert rc == 0 and "  1 billable evaluation: 0 accepted, 1 rejected." in text.splitlines()
    assert "The month's account on chain says 2 evaluations (1 accepted, 1 rejected), value 2.000000, fees 0.100000: the cluster no longer has every" in " ".join(text.split())
    led.most = None
    # nothing counted; and what the command line must say
    rc, text, _ = run(capsys, "statement", "--meter", "--buyer", str(BUYER), "--seller", "777", "--month", one)
    assert rc == 0 and text.splitlines()[-1] == "  No evaluation was counted for this buyer and this seller in that month."
    assert run(capsys, "statement", "--meter", "--seller", str(SELLER), "--month", one)[:2] == (
        1, "The meter's statement is for one buyer and one seller: knos statement --meter --buyer X --seller Y --month YYYY-MM\n")
    assert run(capsys, "statement", "--buyer", str(BUYER), "--seller", str(SELLER), "--month", one)[:2] == (
        1, "--buyer goes with --meter: knos statement --meter --buyer X --seller Y --month YYYY-MM\n")
    assert run(capsys, "statement", "--meter", "--buyer", str(BUYER), "--seller", str(SELLER), "--month", "10-2026")[0] == 1

    def down(*_a, **_k):
        raise OSError("connection refused")
    monkeypatch.setattr(led, "history", down, raising=False)
    assert run(capsys, "statement", "--meter", "--buyer", str(BUYER), "--seller", str(SELLER), "--month", one)[:2] == (
        1, "Solana did not give the meter's history: connection refused.\n")
    # -- the rows: one per evaluation, as the invoice and the export list them
    rows = records.evaluations(events)
    assert [list(r)[1:] for r in rows] == [list(records.EVAL_COLUMNS)] * 3 and [r["month"] for r in rows] == [one, one, two]
    assert [(r["buyer_id"], r["seller_id"], r["artifact"], r["verdict"], r["rate_units"]) for r in rows] == [
        (BUYER, SELLER, "a" * 40, "accepted", 2_000_000), (BUYER, SELLER, "b" * 40, "rejected", rows[1]["rate_units"]), (BUYER, SELLER, "c" * 40, "accepted", 3_000_000)]
    assert records.meter_totals(rows[:2]) == {"evaluations": 2, "accepted": 1, "rejected": 1, "value_units": 2_000_000, "fee_units": 100_000}
    monkeypatch.setattr(records, "read", lambda url, limit: records.Record(events, limit=limit))
    rc, text, _ = run(capsys, "invoice", "--owner", str(BUYER), "--month", one, "--out", str(tmp_path), "--no-names")
    page, evals = tmp_path / f"KNOS-{BUYER}-{one.replace('-', '')}.html", tmp_path / f"KNOS-{BUYER}-{one.replace('-', '')}-evaluations.csv"
    assert rc == 0 and f"Wrote {evals}: 2 evaluation(s) knos_meter counted for this owner, 0.100000 in fees from their credits." in " ".join(text.split())
    html_ = page.read_text(encoding="utf-8")
    assert "<h2>Evaluations counted by knos_meter</h2>" in html_ and "a" * 40 in html_ and "c" * 40 not in html_ and "2 evaluations" in html_
    assert "1 accepted, 1 rejected" in html_ and "not from an escrow" in html_ and "<script" not in html_.lower() and "http" not in html_
    listed = list(csv.DictReader(io.StringIO(evals.read_text(encoding="utf-8"))))
    assert [x["transaction"] for x in listed] == [r["transaction"] for r in rows[:2]] and list(listed[0]) == list(records.EVAL_COLUMNS)
    # an owner with no evaluation that month gets the invoice it always got, and no third file
    rc, text, _ = run(capsys, "invoice", "--owner", "777", "--month", one, "--out", str(tmp_path / "none"), "--no-names")
    assert rc == 0 and "evaluation" not in text and sorted(f.name for f in (tmp_path / "none").iterdir()) == [f"KNOS-777-{one.replace('-', '')}.csv", f"KNOS-777-{one.replace('-', '')}.html"]
    assert "Evaluations counted" not in (tmp_path / "none" / f"KNOS-777-{one.replace('-', '')}.html").read_text(encoding="utf-8")
    rc, text, _ = run(capsys, "export", "--siem", "--no-names")
    got = [json.loads(x) for x in text.splitlines()]
    assert rc == 0 and [x["artifact"] for x in got if x["action"] == "meter_eval"] == ["a" * 40, "b" * 40, "c" * 40]
