"""The billing rule (src/knos/billing.py): a month's invoice = subscription + the greater of Meter and Verify + what
was agreed separately. The years of tests/data/billing_vectors.json are worked by hand from the price book, and the
site's calculator (web/price.js) is held to the same file by tests/web/price.mjs. Nothing here opens the network."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from knos import billing as b

ROOT = Path(__file__).resolve().parents[1]
VECTORS = json.loads((ROOT / "tests" / "data" / "billing_vectors.json").read_text(encoding="utf-8"))
D = Decimal


def amount(inv: dict, line: str) -> str:
    return next(row["amount"] for row in inv["lines"] if row["line"] == line)


def test_the_constants_are_the_price_book():
    book = VECTORS["book"]
    assert (b.METER_FREE, b.METER_PRICE, b.METER_COMMITTED) == (book["meter_free"], D(book["meter_price"]), D(book["meter_committed"]))
    assert (b.VERIFY_RATE, b.VERIFY_CAP) == (D(book["verify_rate"]), D(book["verify_cap"]))
    assert b.CONTROL == {k: D(v) for k, v in book["control"].items()}
    assert (b.SUPPLIERS_INCLUDED, b.SUPPLIER_PRICE, b.PILOT, b.BENEFIT_RULE) == (book["suppliers_included"], D(book["supplier_price"]), D(book["pilot"]), book["benefit_rule"])
    assert [list(row) for row in b.BOOK] == VECTORS["lines"]
    market = (ROOT / "docs" / "MARKET.md").read_text(encoding="utf-8")
    for line, unit, price in b.BOOK:                    # and the document prints the same seven lines, word for word
        assert f"| {line} | {unit} | {price} |" in market, line


@pytest.mark.parametrize("year", VECTORS["years"], ids=lambda y: y["name"])
def test_a_year_at_the_price_book(year):
    got = b.estimate(year["in"]["plan"], year["in"]["evaluations"], year["in"]["accepted"], year["in"]["suppliers"])
    assert {k: got[k] for k in year["out"]} == year["out"]


def test_the_worked_example_month_by_month_adds_up_to_130_000():
    """Business, 110,000 evaluations a month, 10 million accepted a year in deliverables of 20,000 (none reaches the
    cap): Meter 24,000, Verify 50,000, Control 80,000, and 130,000 in all, with Meter never added to Verify."""
    per_month = [40] * 8 + [45] * 4                     # deliverables accepted each month: 500 in the year, 20,000 each
    assert sum(per_month) * 20_000 == 10_000_000
    total = meter = verify = control = D(0)
    for m, n in enumerate(per_month, 1):
        inv = b.invoice({"plan": "business", "month": m, "evaluations": 110_000, "suppliers": 5,
                         "accepted": [{"deliverable": f"dlv_{m}_{i}", "value": "20000.00"} for i in range(n)]})
        assert inv["chosen"] == "verify" and amount(inv, "usage") == amount(inv, "verify") and amount(inv, "meter") == "2,000.00"
        assert [row["charged"] for row in inv["lines"] if row["line"] in ("meter", "verify")] == [False, True]
        total += D(inv["total"].replace(",", ""))
        meter, verify, control = (x + D(amount(inv, k).replace(",", "")) for x, k in ((meter, "meter"), (verify, "verify"), (control, "control")))
    assert (meter, verify, control, total) == (D(24_000), D(50_000), D(80_000), D(130_000))
    assert b.estimate("business", 110_000, "10000000", 5)["benefit_to_demand"] == "390,000.00"       # three to one


def test_verify_is_capped_at_250_a_deliverable():
    assert [str(b.verify_fee(D(v))) for v in ("49999.00", "50000.00", "50001.00", "4000000.00", "0.99", "1.00")] == ["250.00", "250.00", "250.00", "250.00", "0.00", "0.01"]
    inv = b.invoice({"plan": "none", "accepted": [{"deliverable": "big", "value": "4000000"}, {"deliverable": "small", "value": "1000"}]})
    assert amount(inv, "verify") == "255.00" == inv["total"] and "1 at the 250 cap" in inv["lines"][1]["how"]


def test_an_accepted_deliverable_is_counted_once_and_nothing_is_charged_for_what_knos_or_the_network_caused():
    month = {"plan": "none", "evaluations": 20_600, "duplicates": 300, "infrastructure_failures": 250, "knos_retries": 50,
             "accepted": [{"deliverable": "a", "value": "100000"}] * 20}
    inv = b.invoice(month)
    assert amount(inv, "meter") == "500.00"             # 20,000 counted, 10,000 free, 10,000 at 0.05
    assert amount(inv, "verify") == "250.00"            # one deliverable, however often it was evaluated or listed
    assert inv["chosen"] == "meter" and inv["total"] == "500.00" and amount(inv, "not_charged") == "0.00"
    with pytest.raises(b.BillingError, match="exceed"):
        b.invoice({"plan": "none", "evaluations": 5, "duplicates": 6})


def test_a_rejection_that_ran_is_an_evaluation_and_not_an_outcome():
    inv = b.invoice({"plan": "none", "evaluations": 10_100})        # a hundred runs over the allowance, none accepted
    assert (amount(inv, "meter"), amount(inv, "verify"), inv["total"]) == ("5.00", "0.00", "5.00")


def test_disputed_or_reversed_value_is_left_out_this_month_and_credited_when_it_is_an_earlier_month_s():
    inv = b.invoice({"plan": "none", "accepted": [{"deliverable": "a", "value": "10000"}, {"deliverable": "b", "value": "2000"}],
                     "disputed": [{"deliverable": "b", "value": "2000"}],                         # this month's: left out
                     "reversed": [{"deliverable": "old", "value": "3000"}, {"deliverable": "older", "value": "90000"}]})   # earlier: credited
    assert amount(inv, "verify") == "50.00" and amount(inv, "credit") == "-50.00"                 # 15.00 + 250.00 of credit, 50.00 usable now
    assert inv["total"] == "0.00" and inv["credit_carried_forward"] == "215.00"
    again = b.invoice({"plan": "none", "accepted": [{"deliverable": "c", "value": "100000"}], "credit_brought_forward": "215.00"})
    assert again["total"] == "35.00" and again["credit_carried_forward"] == "0.00"
    assert b.RULES["credit"].count(".") == 2 and b.RULES["credit"].endswith(".")                  # one sentence (and the point of 0.5%)


def test_a_price_by_the_year_is_twelve_parts_that_add_up_to_the_cent():
    for annual in (b.CONTROL["team"], b.CONTROL["business"], b.SUPPLIER_PRICE, D("12345.67")):
        parts = [b.part_of_year(annual, m) for m in range(1, 13)]
        assert sum(parts) == annual and max(parts) - min(parts) <= D("0.01")
    inv = b.invoice({"plan": "team", "month": 12, "suppliers": 8})
    assert amount(inv, "control") == "2,083.34" and amount(inv, "suppliers") == "1,250.00"


def test_an_annual_commitment_is_drawn_down_by_use_and_only_the_rest_is_charged():
    first = b.invoice({"plan": "none", "committed": "12000", "evaluations": 60_000})              # 50,000 at the committed rate: 1,000
    assert amount(first, "meter") == "1,000.00" and amount(first, "commitment") == "1,000.00" and amount(first, "drawn") == "-1,000.00"
    assert first["total"] == "1,000.00" and first["commitment_remaining"] == "11,000.00"
    last = b.invoice({"plan": "none", "month": 12, "committed": "12000", "drawn": "11500", "evaluations": 60_000})
    assert amount(last, "drawn") == "-500.00" and last["total"] == "1,500.00" and last["commitment_remaining"] == "0.00"
    assert b.estimate("none", 60_000, "0", 0, "12000")["total"] == "12,000.00" and b.estimate("none", 110_000, "0", 0, "12000")["total"] == "24,000.00"


def test_the_rated_party_never_pays_and_a_float_is_not_money():
    with pytest.raises(b.BillingError, match="The rated party never pays"):
        b.invoice({"plan": "team", "billed_to": "supplier"})
    with pytest.raises(b.BillingError, match="not"):
        b.invoice({"plan": "none", "accepted": [{"deliverable": "a", "value": 0.1}]})
    with pytest.raises(b.BillingError, match="two decimals"):
        b.invoice({"plan": "none", "accepted": [{"deliverable": "a", "value": "0.125"}]})
    with pytest.raises(b.BillingError, match="not a field"):
        b.invoice({"plan": "none", "evaluatons": 1})
    inv = b.invoice({"plan": "none", "other": [{"what": "Pilot", "amount": "2500"}, {"what": "Pilot, credited against year one", "amount": "-2500"}]})
    assert inv["total"] == "0.00" and inv["billed_to"] == "buyer" and b.RULES["rated"] in inv["rules"]
    assert any("test money: 0 revenue" in rule for rule in inv["rules"])


def test_every_line_names_the_rule_that_produced_it():
    inv = b.invoice({"plan": "business", "month": 3, "evaluations": 110_500, "duplicates": 300, "infrastructure_failures": 150, "knos_retries": 50,
                     "accepted": [{"deliverable": "a", "value": "800000"}, {"deliverable": "b", "value": "1200.10"}],
                     "disputed": [{"deliverable": "old", "value": "90000"}], "suppliers": 7, "committed": "12000", "drawn": "11500"})
    assert all(row["rule"] in b.RULES.values() and row["what"] and row["amount"] for row in inv["lines"])
    assert [row["line"] for row in inv["lines"]] == ["control", "commitment", "not_charged", "meter", "verify", "usage", "credit", "drawn", "suppliers"]
    assert inv["total"] == "9,750.01"                   # 6,666.67 + 1,000.00 + 2,000.00 - 250.00 - 500.00 + 833.34
    text = "\n".join(b.explain(inv))
    assert "rule: The greater of Meter and Verify is charged." in text and "(not charged)" in text and "Total" in text


def test_knos_bill_estimate_and_explain(tmp_path):
    import typer
    from typer.testing import CliRunner

    app, lines = typer.Typer(), []
    b.register(app, lines)
    assert [row[0] for row in lines] == ["bill"]
    run = CliRunner().invoke(app, ["bill", "estimate", "--plan", "business", "--evaluations", "110000", "--accepted", "10000000", "--suppliers", "5"])
    assert run.exit_code == 0 and "130,000.00" in run.output and "390,000.00" in run.output and "The rated party never pays." in run.output
    as_json = json.loads(CliRunner().invoke(app, ["bill", "estimate", "--plan", "business", "--evaluations", "110000", "--accepted", "10000000", "--json"]).output)
    assert as_json["total"] == "130,000.00" and as_json["chosen"] == "verify"
    month = tmp_path / "month.json"
    month.write_text(json.dumps({"plan": "team", "evaluations": 30_000, "accepted": [{"deliverable": "a", "value": "60000"}]}), encoding="utf-8")
    run = CliRunner().invoke(app, ["bill", "explain", str(month)])
    assert run.exit_code == 0 and "Meter" in run.output and "rule:" in run.output and "2,483.33" in run.output       # 2,083.33 + 400.00
