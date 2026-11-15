"""Knos for teams: usage metered per team and per agent, invoices that bill only the bounty lines the chain confirms
(a check is never billed, LiteSVM never billed), "paid and final in N ms", and the business model labelled a model."""
from __future__ import annotations

import copy
from pathlib import Path

import pytest

from knos.money import business, fees_config, teams

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"


@pytest.fixture(scope="module")
def cfg():
    return fees_config.load()


def test_the_verified_merge_is_a_decided_starting_price_with_the_first_verification_free(cfg):
    vm = cfg.doc["fees"]["verified_merge"]
    assert (vm["status"], vm["usd_each"], vm["free_first"], vm["label"]) == ("decided", "1.00", 1, "starting price")
    assert vm["decided"] == "14 Oct 2026" and "price set 14 Oct 2026" in vm["source"] and "Airwallex" in vm["collected"]
    assert cfg.price("verified_merge", 3) == 3 * 1_000_000
    assert any(x.startswith("fees.verified_merge.usd_each = 1.00") for x in cfg.decided())
    # the other decided prices this page shows are the ones decided before
    f = cfg.doc["fees"]
    assert (f["x402_check"]["usd_each"], f["bounty_platform"]["rate_bps"], f["task_package"]["knos_bps"]) == ("0.02", 500, 1000)


@pytest.mark.parametrize("change,needle", [
    (lambda d: d["fees"]["verified_merge"].__setitem__("usd_each", "0"), "fees.verified_merge.usd_each"),
    (lambda d: d["fees"]["verified_merge"].__setitem__("free_first", -1), "fees.verified_merge.free_first"),
    (lambda d: d["fees"]["verified_merge"].__setitem__("status", "live"), "fees.verified_merge.status"),
    (lambda d: d["fees"]["verified_merge"].pop("source"), "fees.verified_merge.source"),
    (lambda d: d["fees"]["verified_merge"].pop("collected"), "fees.verified_merge.collected"),
])
def test_the_loader_refuses_a_broken_verified_merge_line(cfg, change, needle):
    doc = copy.deepcopy(cfg.doc)
    change(doc)
    assert any(p.startswith(needle) for p in fees_config.validate(doc)), fees_config.validate(doc)


def test_the_outside_figures_carry_their_page_and_day(cfg):
    s = cfg.doc["sources"]
    assert "Visual Studio Magazine, 30 Jun 2026" in s["github_merges"]["source"] and "read 14 Oct 2026" in s["github_merges"]["source"]
    assert "more than 90 million" in s["github_merges"]["said"]
    assert s["epoch_tasks"]["source"].startswith("Epoch AI, 12 Jan 2026") and "epoch.ai/gradient-updates/state-of-rl-envs" in s["epoch_tasks"]["source"]
    audit = (ROOT / "docs" / "reference" / "BENCH.md").read_text(encoding="utf-8")
    assert "1,119 of 3,736" in audit and "6,059 of 8,954" in audit
    assert "1,119 of 3,736" in s["slop_audit"]["said"] and "6,059 of the 8,954" in s["slop_audit"]["said"]


def _events():
    e = lambda kind, at, **kw: teams.event(kind, "acme", kw.pop("agent", "claude"), at=at, task="t", **kw)  # noqa: E731
    return [e("escrow_funded", "2026-10-01T00:00:00Z", sig="F1", network="devnet", amount_units=20_000_000, final_ms=400),
            e("x402_check", "2026-10-01T00:00:01Z", sig="X1", network="devnet", amount_units=20_000, final_ms=300),
            e("verification", "2026-10-01T00:00:02Z", passed=True, cheats=[], agent_tests_passed=True),
            e("verification", "2026-10-01T00:00:03Z", passed=False, cheats=["test_edited"], agent_tests_passed=True, agent="codex"),
            e("verification", "2026-10-02T00:00:00Z", passed=True, cheats=[], agent_tests_passed=True),
            e("verification", "2026-10-02T00:00:01Z", passed=False, cheats=[], agent_tests_passed=False),
            e("payout", "2026-10-02T00:00:02Z", sig="P1", network="litesvm", amount_units=20_000_000),
            e("payout", "2026-10-02T00:00:03Z", sig="P2", network="devnet", amount_units=20_000_000, final_ms=500),
            e("verification", "2026-11-01T00:00:00Z", passed=True, cheats=[], agent_tests_passed=True)]


def test_usage_is_metered_per_team_and_per_agent():
    u = teams.usage(_events())["acme"]
    assert u["claude"]["verifications"] == 4 and u["claude"]["verified"] == 3 and u["claude"]["refused"] == 1
    assert u["codex"] == {"verifications": 1, "refused": 1, "cheats_caught": 1, "failing_merges_blocked": 1}
    assert u["claude"]["failing_merges_blocked"] == 0          # it said nothing passes: not a merge that was blocked
    assert u["claude"]["paid_checks"] == 1 and u["claude"]["payouts"] == 2
    assert teams.usage(_events(), month="2026-11")["acme"]["claude"]["verifications"] == 1
    with pytest.raises(ValueError):
        teams.event("lunch", "acme", "a")
    with pytest.raises(ValueError):
        teams.event("verification", "", "a")


def test_the_invoice_bills_only_bounty_lines_the_chain_confirms_and_never_a_check(cfg):
    chain = {"F1": {"found": True, "finalized": True}, "X1": {"found": True, "finalized": True},
             "P2": {"found": True, "finalized": True, "err": None}}
    inv = teams.invoice(_events(), "acme", "2026-10", check=lambda s: chain.get(s, {"found": False}), cfg=cfg)
    assert [x["line"] for x in inv["lines"]][0] == "bounty funded, held until its test passes" and len(inv["lines"]) == 3
    assert not any("verif" in x["line"] or "check" in x["line"] for x in inv["lines"])
    paid = [x for x in inv["lines"] if x["line"].startswith("bounty paid")]
    assert paid[0]["usd"] == "0.00" and "LiteSVM" in paid[0]["evidence"] and paid[0]["would_bill_usd"] == "0.94"
    assert paid[1]["usd"] == "0.94" and paid[1]["onchain_part_usd"] == "0.06" and paid[1]["whole_fee_usd"] == "1.00"
    assert paid[1]["line"] == "bounty paid: Knos bounty fee (5%), off-chain part" and "0.30% (at least 0.05)" in paid[1]["why"]
    assert inv["due_usd"] == "0.94" and inv["test_money"] and "knos_pay" in inv["pay_with"]
    assert teams.invoice(_events(), "acme", "2026-11", cfg=cfg)["due_usd"] == "0.00"      # a verification alone bills nothing


def test_a_transaction_the_chain_does_not_confirm_is_not_billed(cfg):
    evs = [teams.event("payout", "acme", "a", at="2026-10-01T00:00:00Z", sig="P", network="devnet", amount_units=100_000_000)]
    assert teams.invoice(evs, "acme", check=lambda s: {"found": True, "finalized": False}, cfg=cfg)["due_usd"] == "0.00"
    assert teams.invoice(evs, "acme", check=lambda s: {"found": True, "finalized": True, "err": {"x": 1}}, cfg=cfg)["due_usd"] == "0.00"

    def down(sig):
        raise OSError("no route")
    assert teams.invoice(evs, "acme", check=down, cfg=cfg)["lines"][0]["evidence"].startswith("chain did not answer")
    assert teams.invoice(evs, "acme", check=lambda s: {"found": True, "finalized": True}, cfg=cfg)["due_usd"] == "4.70"


def test_paid_and_final_is_measured_from_devnet_transactions_only():
    lat = teams.latency(_events())
    assert (lat["n"], lat["p50_ms"], lat["p95_ms"]) == (3, 400, 500) and "measured" in lat["label"]      # the LiteSVM payout is not counted
    assert teams.latency([])["n"] == 0


def test_the_dashboard_and_the_record_file(tmp_path, cfg):
    p = tmp_path / "u.jsonl"
    for e in _events():
        teams.record(e, p)
    d = teams.dashboard(teams.load(p), "acme", cfg=cfg)
    assert d["totals"]["verifications"] == 5 and d["totals"]["failing_merges_blocked"] == 1 and d["cheats_by_rule"] == {"test_edited": 1}
    assert "No dollar value" in d["money_saved"]["means"] and "first_verification_free" not in d
    assert len(p.read_text().splitlines()) == 9 and teams.load(tmp_path / "none.jsonl") == []


def test_the_model_is_price_times_volume_and_says_it_is_a_model(cfg):
    zero = business.model({}, cfg)
    assert zero["month_total"] == "0.00" and zero["label"].startswith("MODEL, not a forecast") and "free cash flow" in zero["label"]
    m = business.model({"bounty_volume_usd": 10_000, "task_packages": 10, "task_package_price_usd": 2000}, cfg)
    assert m["month"] == {"bounty_fee": "500.00", "task_packages": "2000.00"}
    assert m["month_total"] == "2500.00" and m["year_total"] == "30000.00"
    assert not any("check" in p["line"] or "merge" in p["line"] for p in business.prices(cfg))     # nobody pays for a check


def test_the_teams_page_is_not_published():
    for name in ("teams_data.json", "team_data.json", "teams.js", "teams/index.html"):
        assert not (WEB / name).exists(), name
