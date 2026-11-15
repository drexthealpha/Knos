"""The chain bench runs, and its knos arm shows no conflicting write (a small run; the ship runs 200 rounds)."""

from __future__ import annotations

from _devchain import URL, devchain
from knos import bench_chain


@devchain
def test_security_race_knos_arm_has_no_conflicts():
    got = bench_chain.security(URL, rounds=2)
    assert got["knos"]["conflicting_writes"] == 0 and got["knos"]["conflicting_commits"] == 0, got
    assert got["knos"]["writes"] > 0
    assert got["none"]["conflicting_writes"] >= got["knos"]["conflicting_writes"]


@devchain
def test_cost_and_budget():
    c = bench_chain.cost(URL)
    assert c["fee_lamports"] == 5000 and c["rent_lamports_refundable"] > 0
    b = bench_chain.budget(URL, attempts=5)
    assert b["rejected"] == 5 and b["moved_past_limit_units"] == 0
