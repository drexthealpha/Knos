"""The billing rule (src/knos/billing.py), Price book 3: a month's invoice = Control + Meter + Acceptance on value
reconciled off chain + Record lookups. The years and months of tests/data/billing_vectors.json are worked by hand from
the price book, and the site's calculator (web/price.js) is held to the same file by tests/web/price.mjs. Nothing here
opens the network."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from knos import billing as b

ROOT = Path(__file__).resolve().parents[1]
VECTORS = json.loads((ROOT / "tests" / "data" / "billing_vectors.json").read_text(encoding="utf-8"))
COSTS = json.loads((ROOT / "docs" / "unit_costs.json").read_text(encoding="utf-8"))
D = Decimal


def amount(inv: dict, line: str) -> str:
    return next(row["amount"] for row in inv["lines"] if row["line"] == line)


def month_of(given: dict) -> dict:
    """A month of the vectors as `invoice` takes it: "accepted_each": [value, n] is n deliverables of that value."""
    month = dict(given)
    if "accepted_each" in month:
        value, n = month.pop("accepted_each")
        month["accepted"] = [{"deliverable": f"d{k}", "value": value} for k in range(n)]
    return month


def test_the_constants_are_the_price_book():
    book = VECTORS["book"]
    assert (b.METER_FREE, b.METER_PRICE) == (book["meter_free"], D(book["meter_price"]))
    assert (b.ACCEPT_RATE, b.ACCEPT_FLOOR) == (D(book["acceptance_rate"]), D(book["acceptance_floor"]))
    assert [(str(start), str(rate)) for start, rate in b.ACCEPT_TIERS] == [tuple(t) for t in book["acceptance_tiers"]]
    assert b.CONTROL == {k: D(v) for k, v in book["control"].items()}
    assert (b.RECORD_PRICE, b.PILOT, b.BENEFIT_RULE) == (D(book["record_price"]), D(book["pilot"]), book["benefit_rule"])
    assert [list(row) for row in b.BOOK] == VECTORS["lines"]
    market = (ROOT / "docs" / "MARKET.md").read_text(encoding="utf-8")
    for row in b.BOOK:                                  # and the document prints the same six lines, word for word
        assert "| " + " | ".join(row) + " |" in market, row[0]


def test_the_lines_that_were_removed_are_gone():
    names = [row[0] for row in b.BOOK]
    assert names == ["Check", "Meter", "Acceptance", "Record", "Control", "Pilot"] and not set(names) & set(VECTORS["removed"])
    source = (ROOT / "src" / "knos" / "billing.py").read_text(encoding="utf-8")
    for gone in ("VERIFY", "verify_fee", "greater of", "SUPPLIER_PRICE", "SUPPLIERS_INCLUDED", "METER_COMMITTED"):
        assert gone not in source, gone
    assert not hasattr(b, "ACCEPT_CAP") and "no cap" in b.RULES["acceptance"]


@pytest.mark.parametrize("year", VECTORS["years"], ids=lambda y: y["name"])
def test_a_year_at_the_price_book(year):
    given = year["in"]
    got = b.estimate(given["plan"], given["evaluations"], given["accepted"], given["on_chain_percent"], given["lookups"])
    assert {k: got[k] for k in year["out"]} == year["out"]


@pytest.mark.parametrize("month", VECTORS["months"], ids=lambda m: m["name"])
def test_a_month_at_the_price_book(month):
    inv = b.invoice(month_of(month["in"]))
    got = {row["line"]: row["amount"] for row in inv["lines"]} | {"total": inv["total"]}
    assert {k: got[k] for k in month["out"]} == month["out"]


def test_the_worked_customer_month_by_month_adds_up_to_130_240():
    """Business, 110,000 evaluations a month, 10 million accepted a year in deliverables of 20,000, none released on
    chain: Control 100,000, Meter 240, Acceptance 30,000 (no month reaches a million), and 130,240 in all."""
    per_month = [40] * 8 + [45] * 4                     # deliverables accepted each month: 500 in the year, 20,000 each
    assert sum(per_month) * 20_000 == 10_000_000
    total = meter = acceptance = control = D(0)
    for m, n in enumerate(per_month, 1):
        inv = b.invoice({"plan": "business", "month": m, "evaluations": 110_000, "suppliers": 5,
                         "accepted": [{"deliverable": f"dlv_{m}_{i}", "value": "20000.00"} for i in range(n)]})
        assert amount(inv, "meter") == "20.00" and amount(inv, "suppliers") == "0.00"
        total += D(inv["total"].replace(",", ""))
        meter, acceptance, control = (x + D(amount(inv, k).replace(",", "")) for x, k in ((meter, "meter"), (acceptance, "acceptance"), (control, "control")))
    assert (meter, acceptance, control, total) == (D(240), D(30_000), D(100_000), D(130_240))
    year = b.estimate("business", 110_000, "10000000")
    assert (year["total"], year["benefit_to_demand"]) == ("130,240.00", "390,720.00")           # and three to one


def test_acceptance_is_marginal_has_a_floor_and_no_cap():
    fee = lambda value, below="0", volume=True: str(b.acceptance_fee(D(value), D(below), volume))      # noqa: E731
    assert [fee(v, volume=False) for v in ("0.00", "0.01", "5.00", "16.67", "20.00", "1000.00", "4000000.00")] == ["0", "0.05", "0.05", "0.05", "0.06", "3.00", "12000.00"]
    assert fee("1000000") == "3000.00" and fee("1000000", "1000000") == "2000.00" and fee("1000000", "10000000") == "1000.00"
    assert fee("2000000", "500000") == "4500.00"                       # 500,000 at 0.30% and 1,500,000 at 0.20%
    assert fee("20000000") == "31000.00" and fee("20000000", volume=False) == "60000.00"      # the rates are by contract
    assert fee("100000000") == "111000.00"                              # no cap: 3,000 + 18,000 + 90,000


def test_value_released_on_chain_is_never_charged_again():
    rows = [{"deliverable": "a", "value": "50000", "on_chain": True}, {"deliverable": "b", "value": "50000"}]
    inv = b.invoice({"plan": "none", "accepted": rows})
    assert amount(inv, "acceptance") == "150.00" == inv["total"] and amount(inv, "on_chain") == "0.00"
    assert b.RULES["on_chain"] in inv["rules"] and "50,000.00 released on chain" in next(r["how"] for r in inv["lines"] if r["line"] == "acceptance")
    all_chain = b.invoice({"plan": "none", "accepted": [{"deliverable": "a", "value": "50000", "on_chain": True}]})
    assert all_chain["total"] == "0.00"
    with pytest.raises(b.BillingError, match="true or false"):
        b.invoice({"plan": "none", "accepted": [{"deliverable": "a", "value": "5", "on_chain": "yes"}]})
    assert b.estimate("none", 0, "1000000", 100)["total"] == "0.00" and b.estimate("none", 0, "1000000", 25)["acceptance"] == "2,250.00"


def test_an_accepted_deliverable_is_counted_once_and_nothing_is_charged_for_what_knos_or_the_network_caused():
    month = {"plan": "none", "evaluations": 200_600, "duplicates": 300, "infrastructure_failures": 250, "knos_retries": 50,
             "accepted": [{"deliverable": "a", "value": "100000"}] * 20}
    inv = b.invoice(month)
    assert amount(inv, "meter") == "200.00"             # 200,000 counted, 100,000 free, 100,000 at 0.002
    assert amount(inv, "acceptance") == "300.00"        # one deliverable, however often it was evaluated or listed
    assert inv["total"] == "500.00" and amount(inv, "not_charged") == "0.00"
    with pytest.raises(b.BillingError, match="exceed"):
        b.invoice({"plan": "none", "evaluations": 5, "duplicates": 6})


def test_a_rejection_that_ran_is_an_evaluation_and_not_an_outcome():
    inv = b.invoice({"plan": "none", "evaluations": 101_000})       # a thousand runs over the allowance, none accepted
    assert (amount(inv, "meter"), amount(inv, "acceptance"), inv["total"]) == ("2.00", "0.00", "2.00")
    assert b.RULES["rejection"] == "A rejection that ran correctly is an evaluation, not an outcome."


def test_disputed_or_reversed_value_is_left_out_this_month_and_credited_when_it_is_an_earlier_month_s():
    inv = b.invoice({"plan": "none", "accepted": [{"deliverable": "a", "value": "10000"}, {"deliverable": "b", "value": "2000"}],
                     "disputed": [{"deliverable": "b", "value": "2000"}],                         # this month's: left out
                     "reversed": [{"deliverable": "old", "value": "3000"}, {"deliverable": "older", "value": "90000", "charged": "180.00"}]})   # earlier: credited
    assert amount(inv, "acceptance") == "30.00" and amount(inv, "credit") == "-30.00"             # 9.00 + 180.00 of credit, 30.00 usable now
    assert inv["total"] == "0.00" and inv["credit_carried_forward"] == "159.00"
    again = b.invoice({"plan": "none", "accepted": [{"deliverable": "c", "value": "100000"}], "credit_brought_forward": "159.00"})
    assert again["total"] == "141.00" and again["credit_carried_forward"] == "0.00"
    assert b.RULES["credit"].count(". ") == 0 and b.RULES["credit"].endswith(".")                  # one sentence


def test_a_price_by_the_year_is_twelve_parts_that_add_up_to_the_cent():
    for annual in (b.CONTROL["team"], b.CONTROL["business"], b.CONTROL["enterprise"], D("12345.67")):
        parts = [b.part_of_year(annual, m) for m in range(1, 13)]
        assert sum(parts) == annual and max(parts) - min(parts) <= D("0.01")
    inv = b.invoice({"plan": "team", "month": 12, "suppliers": 80})
    assert amount(inv, "control") == "2,083.34" and amount(inv, "suppliers") == "0.00" and inv["total"] == "2,083.34"       # connecting a supplier costs nothing


def test_an_annual_commitment_is_drawn_down_by_use_and_never_counted_twice_with_it():
    month = {"plan": "none", "committed": "12000", "evaluations": 350_000, "accepted": [{"deliverable": "a", "value": "100000"}], "record_lookups": 800}
    first = b.invoice(month)                            # use: 500 of Meter, 300 of Acceptance, 200 of lookups
    assert (amount(first, "meter"), amount(first, "acceptance"), amount(first, "record")) == ("500.00", "300.00", "200.00")
    assert amount(first, "commitment") == "1,000.00" and amount(first, "drawn") == "-1,000.00"
    assert first["total"] == "1,000.00" and first["commitment_remaining"] == "11,000.00"
    last = b.invoice({**month, "month": 12, "drawn": "11500"})
    assert amount(last, "drawn") == "-500.00" and last["total"] == "1,500.00" and last["commitment_remaining"] == "0.00"
    assert b.estimate("none", 600_000, "0", committed="12000")["total"] == "12,000.00"          # 12,000 of use is the commitment
    assert b.estimate("none", 1_100_000, "0", committed="12000")["total"] == "24,000.00"        # 24,000 of use: 12,000 on top


def test_the_rated_party_never_pays_no_line_is_ever_addressed_to_a_supplier():
    with pytest.raises(b.BillingError, match="The rated party never pays"):
        b.invoice({"plan": "team", "billed_to": "supplier"})
    months = [month_of(m["in"]) for m in VECTORS["months"]] + [
        {"plan": "enterprise", "month": 7, "evaluations": 5_000_000, "duplicates": 9, "suppliers": 400, "record_lookups": 12, "committed": "50000",
         "accepted": [{"deliverable": "x", "value": "25000000.00"}, {"deliverable": "y", "value": "1.00", "on_chain": True}],
         "reversed": [{"deliverable": "old", "value": "100"}], "other": [{"what": "Pilot, credited against year one", "amount": "-2500"}]}]
    for month in months:
        inv = b.invoice(month)
        assert inv["billed_to"] == "buyer" and {row["pays"] for row in inv["lines"]} == {"buyer"}
        assert not [row for row in inv["lines"] if "supplier" in row["what"].lower() and row["amount"] != "0.00"]
    assert "pays" not in b.FIELDS and "supplier" not in {row[3] for row in b.BOOK}         # nothing in a customer-month can say otherwise
    assert not [row for row in b.BOOK if "supplier" in row[3] or "payee" in row[3]]


def test_a_float_is_not_money_and_an_unknown_field_is_refused():
    with pytest.raises(b.BillingError, match="not"):
        b.invoice({"plan": "none", "accepted": [{"deliverable": "a", "value": 0.1}]})
    with pytest.raises(b.BillingError, match="two decimals"):
        b.invoice({"plan": "none", "accepted": [{"deliverable": "a", "value": "0.125"}]})
    with pytest.raises(b.BillingError, match="not a field"):
        b.invoice({"plan": "none", "evaluatons": 1})
    inv = b.invoice({"plan": "none", "other": [{"what": "Pilot", "amount": "2500"}, {"what": "Pilot, credited against year one", "amount": "-2500"}]})
    assert inv["total"] == "0.00" and b.RULES["rated"] in inv["rules"] and b.RULES["suppliers"] in inv["rules"]
    assert any("test money: 0 revenue" in rule for rule in inv["rules"])


def test_every_line_names_the_rule_that_produced_it():
    inv = b.invoice({"plan": "business", "month": 3, "evaluations": 110_500, "duplicates": 300, "infrastructure_failures": 150, "knos_retries": 50,
                     "accepted": [{"deliverable": "chain", "value": "2000000", "on_chain": True}, {"deliverable": "a", "value": "800000"}, {"deliverable": "b", "value": "1200.10"}],
                     "disputed": [{"deliverable": "old", "value": "90000"}], "suppliers": 7, "record_lookups": 4, "committed": "12000", "drawn": "11500"})
    assert all(row["rule"] in b.RULES.values() and row["what"] and row["amount"] for row in inv["lines"])
    assert [row["line"] for row in inv["lines"]] == ["control", "commitment", "not_charged", "meter", "acceptance", "on_chain", "record", "drawn", "suppliers", "rebate", "credit"]
    # 8,333.34 + 1,000.00 + 20.00 + 1,602.40 + 1.00 - 500.00 - (2,000 x 0.10% = 1,000.00 rebate + 270.00 credit) = 9,186.74
    assert amount(inv, "acceptance") == "1,602.40" and amount(inv, "credit") == "-1,270.00" and inv["total"] == "9,186.74"
    text = "\n".join(b.explain(inv))
    assert "rule: By contract the month's value above 1,000,000 pays 0.20%" in text and "Total" in text and "Connecting a supplier costs nothing." in text


def test_gross_margin_per_line_from_a_unit_cost_file():
    want = VECTORS["margin"]["out"]
    got = b.margin(month_of(VECTORS["months"][VECTORS["margin"]["month"]]["in"]), COSTS)
    assert {row["line"]: [row["revenue"], row["direct_cost"], row["margin"]] for row in got["lines"]} == {k: v for k, v in want.items() if k != "all"}
    assert [got["revenue"], got["direct_cost"], got["margin"]] == want["all"]
    assert b.margin({"plan": "none"}, {"evaluation": "0.0002", "accepted_deliverable": "0.10", "record_lookup": "0.01", "control_year": "0"})["margin"] == "none: no revenue"
    with pytest.raises(b.BillingError, match="unit cost evaluation"):
        b.margin({"plan": "none"}, {"costs": {"evaluation": 0.0002}})
    assert set(COSTS["costs"]) == set(b.COST_FIELDS) and all("budget" in row["kind"] for row in COSTS["costs"].values())


def test_knos_bill_estimate_explain_and_margin(tmp_path):
    import typer
    from typer.testing import CliRunner

    app, lines = typer.Typer(), []
    b.register(app, lines)
    assert [row[0] for row in lines] == ["bill"]
    run = CliRunner().invoke(app, ["bill", "estimate", "--plan", "business", "--evaluations", "110000", "--accepted", "10000000", "--suppliers", "5"])
    assert run.exit_code == 0 and "130,240.00" in run.output and "390,720.00" in run.output and "The rated party never pays." in run.output
    assert "Connecting a supplier costs nothing." in run.output
    as_json = json.loads(CliRunner().invoke(app, ["bill", "estimate", "--plan", "business", "--evaluations", "110000", "--accepted", "10000000", "--json"]).output)
    assert as_json["total"] == "130,240.00" and as_json["acceptance"] == "30,000.00"
    month = tmp_path / "month.json"
    month.write_text(json.dumps({"plan": "team", "evaluations": 300_000, "accepted": [{"deliverable": "a", "value": "60000"}]}), encoding="utf-8")
    run = CliRunner().invoke(app, ["bill", "explain", str(month)])
    assert run.exit_code == 0 and "Meter" in run.output and "rule:" in run.output and "2,663.33" in run.output       # 2,083.33 + 400.00 + 180.00
    run = CliRunner().invoke(app, ["bill", "margin", str(month), str(ROOT / "docs" / "unit_costs.json")])
    assert run.exit_code == 0 and "direct cost" in run.output and "All lines" in run.output and "2,663.33" in run.output
