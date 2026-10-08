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
    assert set(nl.DEFINITIONS) == set(got) - {"measured", "definitions"}
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
