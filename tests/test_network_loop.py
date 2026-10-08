"""scripts/network_loop.py: the links of the network loop, counted from job records and from this repository. Fixed
jobs, no network, no clock."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("network_loop", ROOT / "scripts" / "network_loop.py")
nl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(nl)

OWN = frozenset({1})
DAY = 86_400


def job(by: int, payee: int, at: int, repo: int = 500) -> dict:
    return {"by": by, "owner": by, "repo": repo, "state": "paid", "paid_at": at, "payee": payee, "to": f"w{payee}", "wallet": f"f{by}"}


def test_nothing_read_is_zero_and_says_it_was_not_measured():
    got = nl.rows(None, ROOT)
    assert got["measured"] is False and (got["suppliers_two_buyers"], got["buyers_through_supplier"], got["repeat_buyers"]) == (0, 0, 0)
    assert set(nl.DEFINITIONS) == set(got) - {"measured", "definitions", "reuse"}
    assert nl.loop([], OWN)["measured"] is True


def test_a_supplier_paid_by_two_unrelated_buyers_and_the_buyer_that_arrived_through_it():
    jobs = [job(10, 77, 1 * DAY), job(11, 77, 2 * DAY), job(11, 78, 40 * DAY), job(12, 79, 3 * DAY)]
    got = nl.loop(jobs, OWN)
    assert got["suppliers_two_buyers"] == 1          # 77: buyers 10 and 11
    assert got["buyers_through_supplier"] == 1       # 11's first paid job paid 77, whom 10 had already paid
    assert got["repeat_buyers"] == 1                 # 11 paid in two different months
    assert nl.loop(list(reversed(jobs)), OWN) == got  # the order the jobs are read in changes nothing


def test_knos_own_accounts_and_one_buyer_twice_are_not_a_network():
    assert nl.loop([job(1, 77, DAY), job(10, 77, 2 * DAY)], OWN)["suppliers_two_buyers"] == 0     # one of the two funders is Knos's
    assert nl.loop([job(10, 77, DAY), job(10, 77, 2 * DAY)], OWN)["suppliers_two_buyers"] == 0    # the same buyer twice
    assert nl.loop([job(10, 1, DAY), job(11, 1, 2 * DAY)], OWN)["suppliers_two_buyers"] == 0      # the payee is Knos's
    unpaid = {**job(11, 77, 2 * DAY), "state": "open", "paid_at": 0}
    assert nl.loop([job(10, 77, DAY), unpaid], OWN)["suppliers_two_buyers"] == 0                   # funded and not paid


def test_the_links_no_chain_shows_come_from_files(tmp_path):
    assert nl.from_repository(tmp_path) == {"receipt_implementations": 0, "decisions_from_record": 0, "reproductions_signed": 0}
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "facts.json").write_text(json.dumps({"by_hand": {"receipt_implementations": 2}}), encoding="utf-8")
    (tmp_path / "reproductions").mkdir()
    (tmp_path / "reproductions" / "a.json").write_text("{}", encoding="utf-8")
    assert nl.from_repository(tmp_path) == {"receipt_implementations": 2, "decisions_from_record": 0, "reproductions_signed": 1}


def test_market_prints_each_link_with_its_counter_and_reads_zero():
    market = (ROOT / "docs" / "MARKET.md").read_text(encoding="utf-8")
    table = market.split("### The loop, link by link, as it is measured today")[1].split("\n## ")[0]
    here = nl.from_repository(ROOT)
    for name in nl.DEFINITIONS:
        row = next(line for line in table.splitlines() if f"`{name}`" in line)
        assert row.rstrip().endswith(f"| {here.get(name, 0)} |"), name
    assert "scripts/network_loop.py" in table and "A larger log of events is not a network effect." in table


def test_nothing_read_counts_no_reuse_and_no_saving():
    got = nl.rows(None, ROOT)["reuse"]
    assert (got["suppliers_reused"], got["onboarding_pairs"], got["onboarding_saved_s"]) == (0, 0, None)
    assert set(got) - {"definitions"} == set(nl.REUSE)


def test_a_supplier_reused_by_a_second_buyer_and_what_the_second_buyer_saved():
    first = {**job(10, 77, 10 * DAY), "funded_at": 10 * DAY - 7_200}      # the first buyer: two hours to its first payment
    again = {**job(10, 77, 12 * DAY), "funded_at": 12 * DAY - 60}         # its later order is not its first
    second = {**job(11, 77, 20 * DAY), "funded_at": 20 * DAY - 1_800}     # the second buyer: half an hour
    got = nl.reuse([second, again, first], None, OWN)
    assert got == {"suppliers_reused": 1, "onboarding_pairs": 1, "onboarding_first_s": 7_200.0, "onboarding_second_s": 1_800.0,
                   "onboarding_saved_s": 5_400.0}
    assert nl.reuse([first, second], None, OWN) == got                     # the order of the records changes nothing


def test_a_paid_lookup_by_another_buyer_counts_as_reuse_and_knos_own_reader_does_not():
    paid = job(10, 77, DAY)
    assert nl.reuse([paid], [{"reader": "wallet:outsider", "supplier": "gh:77"}], OWN)["suppliers_reused"] == 1
    assert nl.reuse([paid], [{"reader": "gh:1", "supplier": "gh:77"}], OWN)["suppliers_reused"] == 0          # Knos read it
    assert nl.reuse([paid], [{"reader": "wallet:k", "supplier": "gh:77"}], OWN, frozenset({"k"}))["suppliers_reused"] == 0
    assert nl.reuse([paid], [{"reader": "gh:10", "supplier": "gh:77"}], OWN)["suppliers_reused"] == 0         # its own buyer again
    # a supplier with two buyers but no funding time on record is reused and not timed
    assert nl.reuse([job(10, 77, DAY), job(11, 77, 2 * DAY)], None, OWN)["onboarding_pairs"] == 0


def test_the_command_reads_job_and_lookup_files(tmp_path, capsys):
    (tmp_path / "jobs.json").write_text(json.dumps([job(10, 77, DAY)]), encoding="utf-8")
    (tmp_path / "lookups.json").write_text(json.dumps([{"reader": "wallet:x", "supplier": "gh:77"}]), encoding="utf-8")
    (tmp_path / "own.json").write_text(json.dumps({"ids": [1], "wallets": []}), encoding="utf-8")
    assert nl.main(["--jobs", str(tmp_path / "jobs.json"), "--lookups", str(tmp_path / "lookups.json"), "--own", str(tmp_path / "own.json")]) == 0
    got = json.loads(capsys.readouterr().out)
    assert got["measured"] is True and got["reuse"]["suppliers_reused"] == 1
