"""The billing rule (src/knos/billing.py), Price book 3.1: a month's invoice = Control + Meter + Acceptance on value
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
    assert (b.RECORD_PRICE, b.PILOT, b.BENEFIT_RULE, b.NET_BELOW) == (D(book["record_price"]), D(book["pilot"]), book["benefit_rule"], D(book["net_below"]))
    assert min(rate for _start, rate in b.ACCEPT_TIERS) == D("0.0020") and b.RECORD_PRICE == D("0.10")      # the 0.10% tier is withdrawn
    assert [list(row) for row in b.BOOK] == VECTORS["lines"]
    market = (ROOT / "docs" / "MARKET.md").read_text(encoding="utf-8")
    for row in b.BOOK:                                  # and the document prints the same six lines, word for word
        assert "| " + " | ".join(row) + " |" in market, row[0]


def test_no_price_book_names_a_0_10_percent_tier():
    """The withdrawn tier is not printed beside the rate: not in the book, the document's row, nor the site's book (web/
    index.html's row without scripts, web/price.js's with them). The program's own Plan bound is another fact."""
    site = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    book = site[site.index('id="price-book"'):]
    book = book[:book.index("</table>")]
    js = (ROOT / "web" / "price.js").read_text(encoding="utf-8")
    js = js[js.index('["Acceptance", '):]
    for where, text in (("BOOK", " ".join(" ".join(row) for row in b.BOOK)), ("web/index.html", book), ("web/price.js", js.splitlines()[0])):
        assert "0.10%" not in text and "tier" not in text, where


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
    assert fee("1000000") == "3000.00" and fee("1000000", "1000000") == "2000.00" and fee("1000000", "10000000") == "2000.00"
    assert fee("2000000", "500000") == "4500.00"                       # 500,000 at 0.30% and 1,500,000 at 0.20%
    assert fee("20000000") == "41000.00" and fee("20000000", volume=False) == "60000.00"      # the rates are by contract
    assert fee("100000000") == "201000.00"                              # no cap, and never under 0.20%: 3,000 + 198,000


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
    first = b.invoice(month)                            # use: 500 of Meter, 300 of Acceptance, 80 of lookups
    assert (amount(first, "meter"), amount(first, "acceptance"), amount(first, "record")) == ("500.00", "300.00", "80.00")
    assert amount(first, "commitment") == "1,000.00" and amount(first, "drawn") == "-880.00"
    assert first["total"] == "1,000.00" and first["commitment_remaining"] == "11,120.00"
    last = b.invoice({**month, "month": 12, "drawn": "11500"})
    assert amount(last, "drawn") == "-500.00" and last["total"] == "1,380.00" and last["commitment_remaining"] == "0.00"
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
    # 8,333.34 + 1,000.00 + 20.00 + 1,602.40 + 0.40 - 500.00 - (1,000,000 x 0.10% = 1,000.00 rebate + 270.00 credit) = 9,186.14
    assert amount(inv, "acceptance") == "1,602.40" and amount(inv, "credit") == "-1,270.00" and inv["total"] == "9,186.14"
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
    assert got["free_tier_year"] == VECTORS["margin"]["free_tier_year"]                # what the free evaluations cost at most: acquisition cost
    assert set(COSTS["costs"]) == set(b.COST_FIELDS) | set(b.MORE_COSTS)
    assert all(row["kind"] in ("budget, not measured", "measured") for row in COSTS["costs"].values())      # two labels, and nothing in between
    text = "\n".join(b.margin_lines(got))
    assert "Gross margin" in text and "acquisition cost" in text and "knos_pay 2.1" in text and "knos_pay 2.2" in text and "Netting:" in text


def test_small_tickets_are_netted_one_release_per_payee_and_the_floor_once():
    for values, fee, alone in VECTORS["netting"]["rows"]:
        got = b.netted([("acme", D(v) / 100) for v in values])
        assert (got["fee"] * 100, got["individually"] * 100, len(got["releases"])) == (fee, alone, 1), values
    two = b.netted([("acme", D("0.99")), ("bolt", D("0.99"))])
    assert two["fee"] == D("0.10") and len(two["releases"]) == 2          # one release per payee: the floor once each
    for bad in ([("acme", D(20))], [("", D(1))], [("acme", D(0))]):       # 20 is not small; a netted outcome names its payee
        with pytest.raises(b.BillingError, match="netted outcome"):
            b.netted(bad)
    rows = [{"deliverable": f"s{k}", "value": "0.99", "payee": "acme"} for k in range(100)]
    inv = b.invoice({"plan": "none", "accepted": rows + rows})             # listed twice: still counted once
    line = next(r for r in inv["lines"] if r["line"] == "acceptance")
    assert (line["amount"], line["netted_outcomes"], line["netted_releases"], line["rule"]) == ("0.30", 100, 1, b.RULES["netted"])
    assert b.invoice({"plan": "none", "accepted": [{"deliverable": f"s{k}", "value": "0.99"} for k in range(100)]})["total"] == "5.00"      # no payee named: one by one
    chain = b.invoice({"plan": "none", "accepted": [{"deliverable": "c", "value": "5.00", "payee": "acme", "on_chain": True}]})
    assert chain["total"] == "0.00"                                         # released on chain: its fee was paid there
    n = b.netting_example()
    assert (n["alone_share"], n["netted_share"], n["netted_fee"], n["individually"], n["reaches_rate"]) == ("5.05%", "0.30%", "0.30", "5.00", 19)


def test_who_earns_what_at_the_floor_under_both_builds():
    got = {x["build"]: x for x in b.floor_split()}
    for build in ("2.1", "2.2"):
        want = VECTORS["floor"][build]
        assert [[r["amount"], r["fee"], r["tip"], r["fee_owner"], r["first_tip"], r["first_fee_owner"]] for r in got[build]["rows"]] == want["rows"]
        assert (got[build]["nothing_at"], got[build]["first_nothing_at"]) == (want["nothing_at"], want["first_nothing_at"])
    small = got["2.2"]["rows"][0]                                           # 5.00 under 2.2: the tip is the whole fee,
    assert small["first_relayer_net"] == "-0.13"                            # and a relayer that opens the account is out 0.13


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


# ---- 0.3.20: margins said correctly, the three leaks, the second worked customer, and the rails ---------------------------

def worked_month() -> dict:
    return {"plan": "business", "month": 1, "evaluations": 110_000, "suppliers": 5,
            "accepted": [{"deliverable": f"d{k}", "value": "20000.00"} for k in range(40)]}


def test_every_margin_is_labelled_gross_and_no_operating_margin_is_printed():
    got = b.margin(worked_month(), COSTS)
    assert got["kind"] == "gross" and got["operating"].startswith("not computed") and got["gross_note"] == b.GROSS
    text = "\n".join(b.margin_lines(got))
    assert b.GROSS in text and "gross margin" in text.splitlines()[2]
    for line in text.splitlines():                       # a percentage that is a margin says gross on its line
        if "margin" in line.lower() and "%" in line:
            assert "gross" in line.lower(), line
    assert "operating margin" not in text.lower().replace("no operating margin is printed", "").replace("operating margin also subtracts", "")


def test_the_three_leaks_each_with_its_number_and_its_design():
    got = b.margin(worked_month(), COSTS)
    want, leaks = VECTORS["leaks"], got["leaks"]
    assert leaks["target"] == "95%"
    assert {k: leaks["meter"][k] for k in want["meter"]} == want["meter"]
    assert {k: leaks["control"][k] for k in want["control"]} == want["control"]
    assert got["remedy"]["one_by_one"] == want["remedy"]["one_by_one"] and got["remedy"]["netted"] == want["remedy"]["netted"]
    # the arithmetic, by hand: 20.00 x 5% = 1.00 over 110,000 delivered; the budget 110,000 x 0.00005 + 5 x 0.1393 = 6.1965
    assert f"{D('1.00') / 110_000:.7f}" == leaks["meter"]["allowed_each"] and f"{D('6.1965') / 110_000:.7f}" == leaks["meter"]["cost_each"]
    unit = b.unit_costs(COSTS)
    n = leaks["meter"]["reaches_at"]                     # the first count that keeps 95%, and the one before it does not
    cost = lambda k: k * unit["evaluation"] + 5 * unit["pair_month"]      # noqa: E731
    assert cost(n) <= (n - b.METER_FREE) * b.METER_PRICE * D("0.05") and cost(n - 1) > (n - 1 - b.METER_FREE) * b.METER_PRICE * D("0.05")
    assert b.meter_break_even({**unit, "evaluation": D("0.0001")}, 5) is None       # at the ceiling itself no count reaches it
    assert b.measured_parts(COSTS)["evaluation"] == D("0.00000047") and b.measured_parts(COSTS)["pair_month"] == D("0.1393")
    assert unit["control_year_target"] == D(7_000) and COSTS["costs"]["control_year_target"]["kind"] == "budget, not measured"
    big = b.margin({**worked_month(), "evaluations": 1_000_000}, COSTS)["leaks"]["meter"]
    assert big["meets"] and big["gross_margin"] == "97.2%"                           # the same costs at a million a month
    text = "\n".join(b.margin_lines(got))
    assert "The three leaks" in text and "does not meet it" in text and "the relayer's tip comes out of that fee" in text and "fee owner 1.45" in text


def test_the_second_worked_customer_is_373_600_and_its_hurdle_is_not_a_claim():
    got, want = b.second_customer(b.unit_costs(COSTS)), VECTORS["second"]
    assert {k: got[k] for k in want["out"]} == want["out"]
    assert (got["control"], got["acceptance"], got["meter"], got["records"]) == ("100,000.00", "252,000.00", "21,600.00", "0.00")
    assert 100_000 + 12 * (1_000_000 * 30 + 9_000_000 * 20) // 10_000 + 12 * 900_000 * 2 // 1_000 == 373_600 and 373_600 * 3 == 1_120_800
    assert got["hurdle_is"] == "a hurdle to be measured in a pilot, not a claim"
    month = b.margin(month_of({"plan": "business", "month": 1, "evaluations": 1_000_000, "suppliers": 5, "accepted_each": ["20000.00", 500]}), COSTS)
    rows = {r["line"]: [r["revenue"], r["direct_cost"], r["margin"]] for r in month["lines"]} | {"all": [month["revenue"], month["direct_cost"], month["margin"]]}
    assert rows == want["month"]
    year = sum((D(b.invoice(month_of({"plan": "business", "month": m, "evaluations": 1_000_000, "accepted_each": ["20000.00", 500]}))["total"].replace(",", ""))
                for m in range(1, 13)), D(0))
    assert year == D("373600.00")                        # twelve invoices, deliverable by deliverable, add up to the estimate
    assert b.second_customer()["total"] == "373,600.00" and "direct_cost" not in b.second_customer()


def test_acceptance_is_charged_once_whichever_rail_pays():
    chain = {"deliverable": "x", "value": "1000.00", "rail": "chain"}
    bank = {"deliverable": "x", "value": "1000.00", "rail": "bank"}
    assert b.invoice({"plan": "none", "accepted": [bank]})["total"] == "3.00"            # paid by bank: the invoice carries the fee
    assert b.invoice({"plan": "none", "accepted": [chain]})["total"] == "0.00"           # released by the program: the fee was paid there
    assert b.invoice({"plan": "none", "accepted": [chain, bank]})["total"] == "0.00"     # the same deliverable under both: once
    assert b.invoice({"plan": "none", "accepted": [bank, chain]})["total"] == "3.00"     # once, on the rail first given
    assert b.invoice({"plan": "none", "accepted": [{"deliverable": "x", "value": "1000.00", "on_chain": True}]})["total"] == "0.00"
    both = b.invoice({"plan": "none", "accepted": [chain, {**bank, "deliverable": "y"}]})
    line = next(r for r in both["lines"] if r["line"] == "once_any_rail")
    assert both["total"] == "3.00" and line["rule"] == b.RULES["once_any_rail"] and line["amount"] == "0.00"
    for bad in ({**chain, "rail": "card"}, {**chain, "on_chain": False}, {**bank, "on_chain": True}):
        with pytest.raises(b.BillingError, match="rail is one of chain, bank"):
            b.invoice({"plan": "none", "accepted": [bad]})


def test_rail_charges_are_shown_apart_from_the_software_price():
    month = {"plan": "team", "accepted": [{"deliverable": "a", "value": "60000.00", "rail": "bank"}],
             "rail_charges": [{"what": "bank wire fees", "amount": "45.00"}, {"what": "network fees", "amount": "0.02"}]}
    inv, bare = b.invoice(month), b.invoice({k: v for k, v in month.items() if k != "rail_charges"})
    assert inv["total"] == bare["total"] == "2,263.33" and inv["lines"] == bare["lines"]      # 2,083.33 + 180.00: no rail charge is in a line
    assert (inv["rail_total"], inv["payable"]) == ("45.02", "2,308.35") and (bare["rail_total"], bare["payable"]) == ("0.00", "2,263.33")
    assert [r["rule"] for r in inv["rail_charges"]] == [b.RULES["rails"]] * 2
    text = "\n".join(b.explain(inv))
    assert text.index("Total") < text.index("Rail charges, apart from the software price:") < text.index("Payable in all")
    assert b.margin(month, COSTS)["revenue"] == b.margin({k: v for k, v in month.items() if k != "rail_charges"}, COSTS)["revenue"]      # nor is it revenue
    for bad in ([{"amount": "1.00"}], [{"what": "wire", "amount": "-1.00"}], [{"what": "wire", "amount": 1.5}]):
        with pytest.raises(b.BillingError, match="rail_charges 1"):
            b.invoice({"plan": "none", "rail_charges": bad})


def test_small_outcomes_are_netted_before_the_floor_and_a_reversed_acceptance_is_credited():
    rows = [{"deliverable": f"s{k}", "value": "5.00", "payee": "acme"} for k in range(100)]
    assert b.invoice({"plan": "none", "accepted": rows})["total"] == "1.50"               # 500.00 x 0.30%, not 100 floors of 0.05
    assert b.invoice({"plan": "none", "accepted": [{**r, "payee": ""} for r in rows]})["total"] == "5.00"
    first = b.invoice({"plan": "none", "accepted": [{"deliverable": "r", "value": "10000.00"}]})
    assert first["total"] == "30.00"
    after = b.invoice({"plan": "none", "accepted": [{"deliverable": "n", "value": "10000.00"}], "reversed": [{"deliverable": "r", "value": "10000.00"}]})
    assert amount(after, "credit") == "-30.00" and after["total"] == "0.00"               # the next invoice gives the 30.00 back
    same = b.invoice({"plan": "none", "accepted": [{"deliverable": "r", "value": "10000.00"}], "reversed": [{"deliverable": "r", "value": "10000.00"}]})
    assert same["total"] == "0.00" and amount(same, "acceptance") == "0.00"               # reversed in its own month: never charged


def test_a_commitment_and_its_consumption_are_never_both_counted():
    use = {"plan": "none", "evaluations": 600_000, "accepted": [{"deliverable": "a", "value": "100000.00"}]}       # Meter 1,000 + Acceptance 300
    assert b.invoice(use)["total"] == "1,300.00"
    inv = b.invoice({**use, "committed": "24000.00"})
    assert (amount(inv, "commitment"), amount(inv, "drawn"), inv["total"], inv["commitment_remaining"]) == ("2,000.00", "-1,300.00", "2,000.00", "22,700.00")
    spent = b.invoice({**use, "committed": "24000.00", "drawn": "23500.00", "month": 12})
    assert (amount(spent, "drawn"), spent["total"], spent["commitment_remaining"]) == ("-500.00", "2,800.00", "0.00")     # 2,000 + the 800 it does not cover


def test_the_record_line_says_who_runs_it_and_is_budgeted_at_zero():
    row = next(r for r in b.BOOK if r[0] == "Record")
    assert row[4] == "`knos record serve` (anyone runs it; Knos hosts none); budgeted at ZERO revenue until someone buys it"
    assert b.second_customer()["records"] == "0.00" and (ROOT / "src" / "knos" / "record_api.py").is_file()


# ---- 0.3.21: pricing power, and money counted once ----------------------------------------------------------------------

def test_sensitivity_prints_the_worked_customers_at_30_20_10_and_5_bps_realised():
    got = b.sensitivity(b.unit_costs(COSTS))
    want = VECTORS["sensitivity"]
    assert got["rates_bps"] == [30, 20, 10, 5] and got["kind"] == "gross"
    for c, w in zip(got["customers"], want["customers"]):
        assert (c["book_bps"], c["fixed"], c["direct_cost"], c["one_bps"]) == tuple(w["head"]), c["customer"]
        assert [[r["bps"], r["revenue"], r["gross_margin"], r["above_book"]] for r in c["rows"]] == w["rows"], c["customer"]
    first, second = got["customers"]
    assert first["rows"][0]["revenue"] == "130,240.00" and b.second_customer()["total"] == "373,600.00"      # at the book's own rate, the book
    assert D(second["book_bps"]) * 120_000_000 / 10_000 == 252_000                                           # 21 bps: 252,000 on 120 million
    # the direct cost does not move with the rate, and every row is gross arithmetic on it
    for c in got["customers"]:
        cost = D(c["direct_cost"].replace(",", ""))
        for r in c["rows"]:
            assert D(r["revenue"].replace(",", "")) - cost == D(r["gross"].replace(",", ""))
    assert b.second_customer(b.unit_costs(COSTS))["direct_cost"] == second["direct_cost"]
    text = "\n".join(b.sensitivity_lines(got))
    assert "matters more than shaving verification time" in text and "None is measured." in text and "not reached" in text
    for line in text.splitlines():
        if "margin" in line.lower() and "%" in line:
            assert "gross" in line.lower(), line


def test_knos_bill_margin_sensitivity(tmp_path):
    import typer
    from typer.testing import CliRunner

    app = typer.Typer()
    b.register(app)
    costs = str(ROOT / "docs" / "unit_costs.json")
    run = CliRunner().invoke(app, ["bill", "margin", "--sensitivity", costs])
    assert run.exit_code == 0 and "481,600.00" in run.output and "105,240.00" in run.output and "21.0 bps" in run.output
    as_json = json.loads(CliRunner().invoke(app, ["bill", "margin", "--sensitivity", costs, "--json"]).output)
    assert [r["bps"] for r in as_json["customers"][0]["rows"]] == [30, 20, 10, 5]
    assert CliRunner().invoke(app, ["bill", "margin", "--sensitivity"]).exit_code != 0
    assert CliRunner().invoke(app, ["bill", "margin", costs]).exit_code != 0                 # a month needs its cost file too


def test_a_year_under_a_commitment_is_the_larger_of_the_two_never_their_sum():
    use = {"plan": "none", "evaluations": 600_000, "accepted": [{"deliverable": "a", "value": "100000.00"}]}       # 1,300 a month of use

    def year(committed: str) -> tuple[D, D]:
        drawn, total = D(0), D(0)
        for m in range(1, 13):
            inv = b.invoice({**use, "month": m, "committed": committed, "drawn": str(drawn)})
            total += D(inv["total"].replace(",", ""))
            drawn = D(committed) - D(inv["commitment_remaining"].replace(",", ""))
        return total, drawn

    assert year("0") == (D("15600.00"), D(0))
    assert year("24000.00") == (D("24000.00"), D("15600.00"))          # under the commitment: the commitment, not 24,000 + 15,600
    assert year("12000.00") == (D("15600.00"), D("12000.00"))          # over it: the use, of which the commitment paid 12,000
    # and the gross margin's revenue never adds the commitment line to the use it pays for
    assert b.margin({**use, "committed": "24000.00"}, COSTS)["revenue"] == b.margin(use, COSTS)["revenue"] == "1,300.00"


def test_the_relayers_tip_and_chain_costs_are_counted_once():
    unit = b.unit_costs(COSTS)
    assert unit["release_chain"] == D("0.0072") and f"{60_000 * D('120.82') / 10**9:.4f}" == "0.0072"
    for first in (False, True):
        out, mine = b.release_split(1_000_000_000, "outside", first, unit), b.release_split(1_000_000_000, "knos", first, unit)
        fee, tip = D(out["fee"]), D(out["tip"])
        assert fee == D("3.00") and tip == (D("0.30") if first else D("0.05"))
        # outside: Knos has the fee less the tip, and no chain cost; the relayer has the tip and pays the chain
        assert (D(out["revenue"]), D(out["direct_cost"]), D(out["relayer_revenue"])) == (fee - tip, D(0), tip)
        assert D(out["relayer_cost"]) == unit["release_chain"] + (unit["payee_account"] if first else 0)
        # Knos relays: the whole fee, and the chain costs as its own
        assert (D(mine["revenue"]), D(mine["direct_cost"]), D(mine["relayer_revenue"]), D(mine["relayer_cost"])) == (fee, D(out["relayer_cost"]), D(0), D(0))
        # the fee is shared once: nothing of it is anyone's twice, and the principal is nobody's revenue
        assert D(out["revenue"]) + D(out["relayer_revenue"]) == fee == D(mine["revenue"]) + D(mine["relayer_revenue"])
        assert out["principal_is_revenue"] is False and "test money" in out["devnet"]
    small = b.release_split(5_000_000, "outside", True, unit)
    assert (small["fee"], small["tip"], small["revenue"]) == ("0.05", "0.05", "0.00")      # at the floor the tip is the whole fee
    for bad in ((4_999_999, "outside"), (5_000_000, "anyone"), (True, "outside")):
        with pytest.raises(b.BillingError):
            b.release_split(*bad)
    raw = (ROOT / "docs" / "UNIT_COSTS.md").read_text(encoding="utf-8")
    for relayer, first, label in (("outside", False, "an outside relayer"), ("knos", True, "Knos relays, a payee's first payment")):
        r = b.release_split(1_000_000_000, relayer, first, unit)
        assert f"| {label} | {r['fee']} | {r['tip']} | {r['revenue']} | {r['direct_cost']} | {r['relayer_revenue']} | {r['relayer_cost']} |" in raw


def test_reserves_rent_and_principal_are_never_revenue():
    month = {"plan": "team", "accepted": [{"deliverable": "a", "value": "60000.00", "rail": "bank"}]}
    held = [{"kind": "reserve", "what": "netting reserve, funded by the buyer", "amount": "5000.00"},
            {"kind": "rent", "what": "token account rent, returned on close", "amount": "0.18"},
            {"kind": "principal", "what": "paid to the supplier", "amount": "60000.00"}]
    inv, bare = b.invoice({**month, "held": held}), b.invoice(month)
    assert inv["lines"] == bare["lines"] and (inv["total"], inv["payable"]) == (bare["total"], bare["payable"]) == ("2,263.33", "2,263.33")
    assert inv["held_total"] == "65,000.18" and [h["rule"] for h in inv["held"]] == [b.RULES["held"]] * 3 and bare["held"] == []
    assert b.margin({**month, "held": held}, COSTS)["revenue"] == b.margin(month, COSTS)["revenue"]
    text = "\n".join(b.explain(inv))
    assert text.index("Total") < text.index("Held or passed on, never revenue:") and "65,000" not in text.split("Total")[0]
    for bad in ([{"kind": "fee", "amount": "1.00"}], [{"kind": "reserve", "amount": "-1.00"}], [{"kind": "rent", "amount": 0.5}]):
        with pytest.raises(b.BillingError, match="held 1"):
            b.invoice({"plan": "none", "held": bad})


def test_the_ceilings_at_95_and_what_5000_buys_in_support_hours():
    assert [(c["price"], c["ceiling"]) for c in b.ceilings()] == [("0.002", "0.0001"), ("20", "1"), ("100000", "5000")]
    hours = b.support_hours()
    assert [(h["rate"], h["hours"], h["hours_a_month"]) for h in hours] == [("75.00", "66.7", "5.6"), ("43.20", "115.7", "9.6")]
    assert D("30.24") / D("0.700") == D("43.20")                       # the BLS median wage over wages' share of what an employer pays
    raw = (ROOT / "docs" / "UNIT_COSTS.md").read_text(encoding="utf-8")
    assert "| 20.00 | 2.00 | 1.00 |" in raw and "| 75 USD, the assumption above | 66.7 | 5.6 |" in raw and "| 43.20 USD, from public wages (the inputs) | 115.7 | 9.6 |" in raw
    assert "https://www.bls.gov/news.release/ecec.nr0.htm" in raw and "Automated onboarding\nis therefore an economic requirement" in raw


def test_market_says_defending_the_rate_matters_more_and_that_nothing_defends_it_yet():
    s = b.sensitivity(b.unit_costs(COSTS))
    raw = (ROOT / "docs" / "MARKET.md").read_text(encoding="utf-8")
    flat = " ".join(raw.split())
    for a, c in zip(*(x["rows"] for x in s["customers"])):
        rev = lambda r: r["revenue"].replace(".00", "")      # noqa: E731
        assert f"| {a['bps']} bps | {rev(a)} | {a['gross_margin']} | {rev(c)}" in raw and f"| {c['gross_margin']} |" in raw
    assert "Defending the rate matters more than shaving verification time." in flat and "None of the three is measured." in flat
    for kind in ("recoveries", "avoided labour", "financing benefit"):
        assert kind in flat and kind in " ".join((ROOT / "docs" / "PILOT.md").read_text(encoding="utf-8").split())
    assert "costs the second customer's account 12,000 USD a year; its whole direct cost is 16,208.36" in flat


# ---- 0.3.22: the budget today against what the price book requires; the gross fee against the cash Knos keeps -------------

def test_the_budget_today_against_what_the_price_book_requires_each_with_its_design():
    rows = {r["unit"]: r for r in b.gaps(b.unit_costs(COSTS))}
    assert list(rows) == ["evaluation", "accepted_deliverable", "record_lookup", "control_business", "control_team", "release_at_floor"]
    assert [(rows[k]["budget"], rows[k]["required"], rows[k]["gap"]) for k in rows] == [
        ("0.00005", "0.0000893", "none"), ("0.10", "0.02", "0.08"), ("0.01", "0.005", "0.005"), ("15,000", "5,000", "10,000"),
        ("not budgeted", "1,250", "unknown"), ("0.0072", "0.0025", "0.0047")]
    assert (D(900_000) * D("0.002") * D("0.05") - 5 * D("0.1393")) / 1_000_000 >= D("0.0000893")       # the evaluation's required cost, by hand
    assert D("133.34") * D("0.003") * D("0.05") >= D("0.02") > D("133.33") * D("0.003") * D("0.05")     # the least deliverable 0.02 keeps 95% on
    assert "666.67" in rows["accepted_deliverable"]["how"] and "200.00 at 0.20%" in rows["accepted_deliverable"]["how"]
    assert all(r["design"] for r in rows.values()) and rows["evaluation"]["meets"] and not rows["control_business"]["meets"]
    text = "\n".join(b.margin_lines(b.margin(worked_month(), COSTS)))
    assert "The budget today against what the price book requires for 95% gross" in text and "control_business" in text and "15,000        5,000" in text


def test_the_gross_fee_is_not_the_cash_knos_keeps():
    c = b.cash_kept("300.00", "7.50", "29.25", "3.00", "0.20")
    assert (c["cash_kept"], c["channel"], c["fee_counter_is_cash"]) == ("208.20", "52.05", False)
    assert D("300.00") - D("7.50") - D("29.25") - D("3.00") - D("52.05") == D("208.20") and D("260.25") * D("0.20") == D("52.05")
    assert "not company cash" in c["rule"] and c["devnet"] == b.RULES["devnet"]
    assert b.cash_kept("3.00")["cash_kept"] == "3.00"                                   # a relayer Knos runs takes no tip; nothing given back
    loss = b.cash_kept("0.05", "0.05", "0", "0.10", "0.20")
    assert loss["cash_kept"] == "-0.10" and loss["channel"] == "0.00"                   # below zero is shown, never floored
    for bad in (("1.00", "2.00"), ("1.00", "0", "-1.00"), ("1.00", "0", "0", "0", "1.5"), ("1.00", "0", "0", "0", 0.2)):
        with pytest.raises(b.BillingError):
            b.cash_kept(*bad)
    e = b.cash_example(b.unit_costs(COSTS))                                             # 100 releases of 1,000 under 2.2: 3.00 each; tips 90 x 0.05 + 10 x 0.30
    assert (e["gross_fee"], e["relayer_tips"], e["discounts"], e["cash_kept"]) == ("300.00", "7.50", "29.25", "208.20")
    text = "\n".join(b.margin_lines(b.margin(worked_month(), COSTS)))
    assert "cash kept 208.20" in text and b.CASH_RULE in text
