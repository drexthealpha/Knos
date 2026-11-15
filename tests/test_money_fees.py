"""config/fees.yaml, the one fee config: it loads, it says what the program and the price book say (a drift fails
here), its arithmetic is the program's, every placeholder is listed, and a bad file is refused line by line."""
from __future__ import annotations

import copy
import json
import random
import re
from decimal import Decimal
from pathlib import Path

import pytest

from knos import billing, fees, plan_floor
from knos.money import fees_config as fc
from knos.settle.v2 import pay

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "fees.yaml"


@pytest.fixture(scope="module")
def cfg():
    return fc.load(CONFIG)


def test_the_one_config_loads_and_mirrors_the_program_and_the_price_book(cfg):
    o, f = cfg.doc["onchain"], cfg.doc["fees"]
    assert (o["rate_bps"], fc.micro(o["floor_usd"]), o["max_payees"], fc.micro(o["order_min_usd"])) == (pay.FEE_BPS, pay.FEE_MIN, pay.MAX_PAYEES, pay.ORDER_MIN_AMOUNT)
    assert (fc.micro(o["relayer_tip_usd"]), fc.micro(o["relayer_tip_first_usd"]), o["plan_floor_bps"]) == (pay.TIP, pay.TIP_FIRST, plan_floor.FLOOR_BPS)
    assert cfg.doc["treasury"]["fee_owner"] == str(pay.FEE_OWNER)
    assert Decimal(f["verification"]["usd_each"]) == billing.METER_PRICE and f["verification"]["free_per_month"] == billing.METER_FREE
    assert Decimal(f["payout"]["rate_bps"]) / 10_000 == billing.ACCEPT_RATE and Decimal(f["payout"]["floor_usd"]) == billing.ACCEPT_FLOOR
    assert cfg.doc["revenue_today"] == "0" and cfg.doc["network"] == "solana devnet"


def test_payout_and_bounty_fees_are_exactly_the_programs(cfg):
    rng = random.Random(329)
    amounts = [0, 1, 5_000_000, 16_666_666, 16_666_667, 20_000_000, 10 ** 11] + [rng.randrange(10 ** 11) for _ in range(500)]
    for a in amounts:
        assert cfg.fee("payout", a) == cfg.fee("bounty", a) == pay.order_fee(a) == fees.NEW.order(a), a
    assert cfg.fee("funding", 10 ** 9) == 0
    assert cfg.bounty(20_000_000) == {"amount": 20_000_000, "fee": 60_000, "total": 20_060_000, "payer": "funder, on top of the amount",
                                      "fee_to": "treasury", "treasury": str(pay.FEE_OWNER), "status": "live"}


def test_count_lines_take_the_free_month_first_and_public_repos_pay_nothing(cfg):
    each = fc.micro(cfg.doc["fees"]["verification"]["usd_each"])
    free = cfg.doc["fees"]["verification"]["free_per_month"]
    assert cfg.price("verification", 10) == 0
    assert cfg.price("verification", 10, used=free - 4) == 6 * each
    assert cfg.price("verification", 10, used=free + 7) == 10 * each
    assert cfg.price("verification", 10 ** 6, used=free, public=True) == 0
    assert cfg.doc["fees"]["x402_check"]["usd_each"] == "0.02" and cfg.price("x402_check", 3) == 3 * 20_000      # decided 14 Oct 2026
    with pytest.raises(ValueError):
        cfg.fee("verification", 5)
    with pytest.raises(ValueError):
        cfg.price("payout", 5)
    with pytest.raises(ValueError):
        cfg.fee("nonsense", 5)


def test_the_split_and_the_task_package_add_up(cfg):
    for a in (0, 1, 7, 5_000_003, 99_999_999_999):
        got = cfg.split(a)
        assert sum(x for _, x in got) == a and [r for r, _ in got] == list(cfg.roles)
    tp = cfg.task_package(2_000 * 10 ** 6)
    assert tp["knos"] + tp["maintainer"] == 2_000 * 10 ** 6 and tp["status"] == "decided"
    assert (tp["knos"], tp["maintainer"]) == (200 * 10 ** 6, 1_800 * 10 ** 6)                                  # 90 / 10, decided
    assert cfg.roles == {"researcher": 6000, "agent": 2500, "lab": 1000, "referee": 500}


def test_every_placeholder_is_listed_and_marked(cfg):
    ph = cfg.placeholders()
    for needle in ("cloud.credit_usd", "cloud.consumes.hosted_verification", "cloud.tiers.Starter.credits_month"):
        assert any(p.startswith(needle) for p in ph), needle
    # the prices decided on 14 Oct 2026 are no longer placeholders, and nothing else left the placeholder list
    assert not any(p.startswith(("fees.", "splits.")) for p in ph) and not any(p.startswith("cloud.tiers") and "USD/month" in p for p in ph)
    assert cfg.doc["cloud"]["status"] == "decided" and cfg.doc["cloud"]["units_status"] == "placeholder"
    assert all(cfg.doc["fees"][k]["status"] == "live" for k in ("payout", "bounty", "funding"))


def test_the_decided_prices_carry_the_day_they_were_set_and_their_sources(cfg):
    f = cfg.doc["fees"]
    assert (f["bounty_platform"]["rate_bps"], f["lab_order"]["rate_bps"], f["graduation"]["rate_bps"], f["task_package"]["knos_bps"]) == (500, 300, 50, 1000)
    assert f["x402_check"]["usd_each"] == "0.02" and "devnet USDC" in f["x402_check"]["mint"]
    assert [(t["name"], t["usd_month"], t["credit_usd_month"]) for t in cfg.credit_tiers] == [("Starter", "20", "22"), ("Pro", "100", "110"), ("Team", "200", "220")]
    assert cfg.doc["cloud"]["bonus_bps"] == 1000
    lines = [f[k] for k in ("bounty_platform", "lab_order", "graduation", "task_package", "x402_check")] + [cfg.doc["splits"], cfg.doc["cloud"]]
    for line in lines:
        assert line["status"] == "decided" and line["decided"] == "14 Oct 2026" and "price set 14 Oct 2026" in line["source"], line
    # an outside figure only with its page and the date it was read
    assert "https://www.scientist.com/scipay/ (read 14 Oct 2026)" in f["lab_order"]["source"]
    assert "9%" not in CONFIG.read_text(encoding="utf-8")
    d = cfg.decided()
    for needle in ("fees.bounty_platform.rate_bps = 500", "fees.lab_order.rate_bps = 300", "fees.graduation.rate_bps = 50",
                   "fees.task_package.knos_bps = 1000", "fees.x402_check.usd_each = 0.02", "splits.roles.referee = 500", "cloud.tiers.Team = 200"):
        assert any(x.startswith(needle) and "14 Oct 2026" in x for x in d), needle
    assert cfg.public()["decided"] == d


def test_the_product_prices_of_23_oct_are_decided_and_the_program_still_charges_its_own_fee(cfg):
    f = cfg.doc["fees"]
    assert (f["demand_check"]["free_a_month"], f["deep_demand_check"]["usd_each"], f["ready_brief"]["usd_each"], f["proof_page"]["usd_each"]) == (10, "500", "0", "0")
    assert f["release"]["rate_bps"] == 100 and "company" in f["release"]["payer"] and "100%" in f["release"]["what"]
    for k in ("demand_check", "deep_demand_check", "ready_brief", "proof_page", "release"):
        assert f[k]["status"] == "decided" and f[k]["decided"] == "23 Oct 2026" and "price set 23 Oct 2026" in f[k]["source"], k
    # the 1% is not live: the deployed program charges its compiled payout fee until the timelocked upgrade
    assert f["payout"]["status"] == "live" and f["payout"]["rate_bps"] == pay.FEE_BPS == 30 and "timelocked" in f["release"]["collected"]
    assert "nobody is charged today" in f["deep_demand_check"]["collected"]
    assert any(x.startswith("fees.release.rate_bps = 100 (23 Oct 2026") for x in cfg.decided())


def test_the_bounty_fee_is_five_percent_of_which_the_program_takes_its_compiled_fee(cfg):
    """knos_pay's fee is compiled into the program (0.30%): the 5% bounty fee is that on-chain fee plus an off-chain rest,
    never 5% on chain and never 5% on top of the 0.30%."""
    for a in (5_000_000, 20_000_000, 1_000_000_000, 10 ** 11 + 7):
        b = cfg.platform("bounty_platform", a)
        assert b["onchain"] == pay.order_fee(a) == cfg.bounty(a)["fee"] and b["fee"] == a * 500 // 10_000
        assert b["onchain"] + b["offchain"] == b["fee"] and b["status"] == "decided" and "program upgrade" in b["collected"]
        lab = cfg.platform("lab_order", a)
        assert lab["onchain"] == cfg.fee("payout", a) and lab["onchain"] + lab["offchain"] == lab["fee"] == a * 300 // 10_000
    b = cfg.platform("bounty_platform", 20_000_000)
    assert (b["fee"], b["onchain"], b["offchain"]) == (1_000_000, 60_000, 940_000)
    plan = cfg.platform("bounty_platform", 10 ** 9, bps=20)                                   # an order on a Plan: the rest grows
    assert (plan["fee"], plan["onchain"], plan["offchain"]) == (50_000_000, 2_000_000, 48_000_000)
    lab = cfg.platform("lab_order", 1)
    assert (lab["fee"], lab["onchain"], lab["offchain"]) == (50_000, 50_000, 0)               # the floor covers it all
    with pytest.raises(ValueError):
        cfg.platform("payout", 5)
    text = CONFIG.read_text(encoding="utf-8")
    assert "Epoch AI, 12 Jan 2026" in text                                                       # an outside figure with its source
    public = json.dumps(cfg.public()).lower()
    assert not re.search(r"\b(nous|hermes)\b", public)                              # no rival is named in what the site reads


def test_the_small_reader_reads_the_file_as_pyyaml_does():
    yaml = pytest.importorskip("yaml")
    text = CONFIG.read_text(encoding="utf-8")
    assert fc.parse_yaml(text) == yaml.safe_load(text)
    sample = 'a:\n  b: "x # not a comment"  # a comment\n  c:\n    - 1\n    - two\n  d:\n    - name: "n"\n      v: 3\n    - name: m\ne: null\n'
    assert fc.parse_yaml(sample) == yaml.safe_load(sample)
    for bad in ("a: 1\na: 2\n", "a:\n\tb: 1\n", "a: 1\n   b: 2\n"):
        with pytest.raises(ValueError):
            fc.parse_yaml(bad)


def _broken(cfg, change) -> list[str]:
    doc = copy.deepcopy(cfg.doc)
    change(doc)
    return fc.validate(doc)


@pytest.mark.parametrize("change, said", [
    (lambda d: d["onchain"].__setitem__("rate_bps", 25), "onchain.rate_bps"),
    (lambda d: d["onchain"].__setitem__("floor_usd", "0.04"), "onchain.floor_usd"),
    (lambda d: d["fees"]["bounty"].__setitem__("rate_bps", 10), "fees.bounty.rate_bps"),
    (lambda d: d["fees"]["bounty"].__setitem__("to", "the founder"), "fees.bounty.to"),
    (lambda d: d["fees"]["verification"].__setitem__("usd_each", "0.003"), "fees.verification.usd_each"),
    (lambda d: d["fees"]["verification"].__setitem__("public_repos_usd", "1"), "public_repos_usd"),
    (lambda d: d["fees"]["payout"].__setitem__("floor_usd", 0.05), "money is a quoted decimal string"),
    (lambda d: d["fees"]["graduation"].__setitem__("status", "maybe"), "fees.graduation.status"),
    (lambda d: d["fees"].pop("task_package"), "fees.task_package: missing"),
    (lambda d: d["splits"]["roles"].__setitem__("referee", 600), "add up to 10100"),
    (lambda d: d["splits"]["roles"].__setitem__("investor", 1), "splits.roles"),
    (lambda d: d["treasury"].__setitem__("fee_owner", "11111111111111111111111111111111"), "treasury.fee_owner"),
    (lambda d: d.__setitem__("revenue_today", "1000"), "revenue_today"),
    (lambda d: d.__setitem__("network", "solana mainnet"), "network"),
    (lambda d: d["sources"]["epoch_tasks"].__setitem__("source", ""), "sources.epoch_tasks"),
    (lambda d: d["sources"]["epoch_tasks"].__setitem__("audited", True), "sources.epoch_tasks"),
    (lambda d: d["cloud"]["tiers"].append({"name": "Pro", "usd_month": "5", "credits_month": 1}), "cloud.tiers"),
    (lambda d: d["cloud"]["tiers"][0].__setitem__("usd_month", "-20"), "cloud.tiers.Starter.usd_month"),
    (lambda d: d["fees"]["bounty_platform"].__setitem__("status", "live"), "fees.bounty_platform.status: not live"),
    (lambda d: d["fees"]["graduation"].__setitem__("status", "live"), "fees.graduation.status: not live"),
    (lambda d: d["fees"]["bounty_platform"].__setitem__("rate_bps", 20), "fees.bounty_platform.rate_bps: at least"),
    (lambda d: d["fees"]["lab_order"].__setitem__("onchain_line", "graduation"), "fees.lab_order.onchain_line"),
    (lambda d: d["fees"]["lab_order"].__setitem__("collected", ""), "fees.lab_order.collected"),
    (lambda d: d["fees"]["bounty_platform"].__setitem__("source", ""), "fees.bounty_platform.source"),
    (lambda d: d["fees"]["x402_check"].pop("decided"), "fees.x402_check.decided"),
    (lambda d: d["splits"].__setitem__("rationale", " "), "splits.rationale"),
    (lambda d: d["cloud"].pop("source"), "cloud.source"),
    (lambda d: d["fees"]["x402_check"].__setitem__("status", "proposed"), "fees.x402_check.usd_each"),
    (lambda d: d["fees"]["x402_check"].__setitem__("usd_each", "0"), "fees.x402_check.usd_each"),
    (lambda d: d["cloud"]["tiers"][1].__setitem__("credit_usd_month", "120"), "cloud.tiers.Pro.credit_usd_month"),
    (lambda d: d["cloud"]["tiers"][2].__setitem__("credits_month", 120000), "cloud.tiers.Team.credits_month"),
    (lambda d: d["cloud"].__setitem__("bonus_bps", -1), "cloud.bonus_bps"),
])
def test_a_config_that_drifts_is_refused(cfg, change, said):
    problems = _broken(cfg, change)
    assert any(said in p for p in problems), problems


def test_load_refuses_a_bad_file_and_honours_the_env(tmp_path, monkeypatch, cfg):
    bad = tmp_path / "fees.yaml"
    bad.write_text(CONFIG.read_text(encoding="utf-8").replace("  rate_bps: 30\n  floor_usd", "  rate_bps: 31\n  floor_usd", 1), encoding="utf-8")
    with pytest.raises(fc.FeeConfigError) as e:
        fc.load(bad)
    assert "onchain.rate_bps" in str(e.value)
    with pytest.raises(fc.FeeConfigError):
        fc.load(tmp_path / "missing.yaml")
    monkeypatch.setenv(fc.ENV, str(CONFIG))
    assert fc.load().doc == cfg.doc


def test_an_orders_own_rate_is_used_when_given(cfg):
    """Finding 42: an order pays the rate fixed at its funding (pay.Order.fee_bps), or an owner's Plan."""
    for a in (5_000_000, 20_000_000, 10 ** 10):
        for bps in (20, 25, 30):
            assert cfg.fee("payout", a, bps=bps) == pay.order_fee(a, bps)
    for bad in (10, 31, True, "20"):
        with pytest.raises(ValueError):
            cfg.fee("bounty", 20_000_000, bps=bad)
    with pytest.raises(ValueError):
        cfg.fee("graduation", 20_000_000, bps=20)
