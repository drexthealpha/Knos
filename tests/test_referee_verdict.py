"""Wanted (a demand book of held pre-orders), Makeable (a cost check from sourced quotes) and the verdict (all
three, recorded). Every number here is synthetic test data."""

from __future__ import annotations

import datetime as dt
import sys

import pytest

from knos import cheats, referee

SPEC = "a" * 64
USDC = 1_000_000            # micro-USDC per USDC


def test_wanted_counts_distinct_buyers_with_money_in_escrow_only(tmp_path):
    book = referee.DemandBook(tmp_path / "demand.json")
    book.lock(SPEC, "Lab A", 100 * USDC, escrow_ref="devnet-order-1")
    book.lock(SPEC, "lab a", 100 * USDC, escrow_ref="devnet-order-2")          # the same buyer twice counts once
    book.lock(SPEC, "Lab B", 50 * USDC)                                         # a pledge, no vault: not counted
    c = book.wanted(SPEC, min_buyers=2, min_locked=200 * USDC)
    assert not c.passed and c.evidence["distinct_buyers"] == 1 and c.evidence["locked"] == 200 * USDC
    assert c.evidence["pledges_not_counted"] == 1 and "1 distinct buyer" in c.reasons[0]
    o = book.lock(SPEC, "Lab C", 10 * USDC, escrow_ref="devnet-order-3")
    assert book.wanted(SPEC, min_buyers=2, min_locked=200 * USDC).passed
    book.refund(o["id"])
    assert not book.wanted(SPEC, min_buyers=2, min_locked=200 * USDC).passed
    with pytest.raises(ValueError):
        book.refund(o["id"])
    with pytest.raises(ValueError):
        book.lock(SPEC, "x", 0, escrow_ref="r")
    assert book.wanted("b" * 64, min_buyers=1, min_locked=0).evidence["distinct_buyers"] == 0


def Q(**kw):
    base = {"kind": "compute", "supplier": "cloud X (synthetic)", "unit_cost": 2.0, "quantity": 10, "source": "quote #1, synthetic"}
    return referee.Quote(**{**base, **kw})


def test_makeable_passes_under_the_margin_and_refuses_unsourced_expired_or_too_costly():
    today = dt.date(2026, 10, 13)
    ok = referee.makeable([Q(), Q(kind="manufacturing", unit_cost=30, quantity=1)], locked_price=100, min_margin=0.3, fees=5, today=today)
    assert ok.passed and ok.evidence["cost"] == 55 and ok.evidence["ceiling"] == 70
    assert not referee.makeable([Q(unit_cost=8)], locked_price=100, min_margin=0.3, today=today).passed
    assert "has no source" in referee.makeable([Q(source="")], locked_price=100, today=today).reasons[0]
    assert "expired" in referee.makeable([Q(valid_until="2026-01-01")], locked_price=100, today=today).reasons[0]
    assert "more than one currency" in referee.makeable([Q(), Q(currency="EUR")], locked_price=100, today=today).reasons[0]
    assert "no quote for cloud_lab" in referee.makeable([Q()], locked_price=100, required_kinds=["cloud_lab"], today=today).reasons[0]
    assert referee.makeable([], locked_price=100).reasons == ["no quotes"]


def _works(passed=True, cheat=False):
    f = [cheats.Finding("test_edited", "test_edited", "tests/t.py", "x")] if cheat else []
    return referee.Check("works", passed and not cheat, [] if passed else ["no"], {}, f)


def test_the_verdict_is_all_three_and_is_recorded(monkeypatch, tmp_path):
    got = []
    fake = type(sys)("knos.record")
    fake.append = lambda kind, payload, **kw: got.append((kind, payload, kw)) or {"kind": kind}
    monkeypatch.setitem(sys.modules, "knos.record", fake)
    import knos
    monkeypatch.setattr(knos, "record", fake, raising=False)
    yes_w, yes_d, yes_m = _works(), referee.Check("wanted", True), referee.Check("makeable", True)
    v = referee.verdict(yes_w, yes_d, yes_m, spec_hash=SPEC, domain="ml", record_root=tmp_path)
    assert v["passed"] and v["failed"] == [] and v["recorded"] is True and got[0][0] == "verdict"
    assert got[0][2]["root"] == tmp_path and got[0][1]["spec_hash"] == SPEC
    got.clear()
    v = referee.verdict(_works(cheat=True), yes_d, referee.Check("makeable", False), spec_hash=SPEC)
    assert not v["passed"] and v["failed"] == ["works", "makeable"]
    assert [k for k, _, _ in got] == ["verdict", "cheat"] and got[1][1]["cheat"] == "test_edited"
    with pytest.raises(ValueError):
        referee.verdict(yes_d, yes_w, yes_m, spec_hash=SPEC)


def test_without_knos_record_the_verdict_is_the_same_and_says_nothing_was_recorded(monkeypatch):
    monkeypatch.setattr("knos.referee.check.record_module", lambda: None)
    v = referee.verdict(_works(), referee.Check("wanted", True), referee.Check("makeable", True), spec_hash=SPEC)
    assert v["passed"] and v["recorded"] is False


def test_the_reward_never_makes_cheating_better_than_failing():
    assert referee.reward(_works()) == 1.0 and referee.reward(_works(passed=False)) == 0.0
    assert referee.reward(_works(cheat=True)) == -1.0
    assert referee.redact_hidden(["hidden tests: rejected: pr: x (the suite's last words: slugify('q') returned 'r')"]) == \
        ["hidden tests: rejected: pr: x (sealed: details withheld)"]
