"""Two pricing promises of the price book (docs/MARKET.md, "The billing rule"), held by knos.billing: 0.20% is paid
only on the part of a month's value above 1,000,000, and a price rise needs 90 days' notice and never touches an order
already funded. The later prices here are made up for the test: the book has one price. Nothing opens the network."""

from __future__ import annotations

from decimal import Decimal

import pytest

from knos import billing as b

D = Decimal
BOOK = b.PRICES[0]
RISE = b.Price("2027-01-04", "2027-04-04", ((D(0), D("0.0040")), (D(1_000_000), D("0.0025"))), D("0.10"))      # 90 days later


def line(inv: dict, key: str) -> dict:
    return next(row for row in inv["lines"] if row["line"] == key)


def test_the_volume_rate_is_paid_only_on_the_part_of_the_month_above_one_million():
    inv = b.invoice({"plan": "business", "accepted": [{"deliverable": "a", "value": "1500000.00"}]})
    acceptance = line(inv, "acceptance")
    assert acceptance["amount"] == "4,000.00"                                   # 1,000,000 x 0.30% + 500,000 x 0.20%
    assert acceptance["amount"] != b.show(D(1_500_000) * D("0.0020"))           # never 0.20% of the whole month (3,000)
    assert "1,000,000.00 at 0.30%, 500,000.00 at 0.20%" in acceptance["how"] and acceptance["rule"] == b.RULES["volume"]
    split = b.invoice({"plan": "business", "accepted": [{"deliverable": "a", "value": "1000000.00"}, {"deliverable": "b", "value": "500000.00"}]})
    assert line(split, "acceptance")["amount"] == "4,000.00"                    # the same month in two deliverables pays the same
    assert line(b.invoice({"plan": "none", "accepted": [{"deliverable": "a", "value": "1500000.00"}]}), "acceptance")["amount"] == "4,500.00"


def test_the_book_has_one_price_and_a_list_of_prices_obeys_the_notice_rule():
    assert b.PRICES == (b.Price("", "", b.ACCEPT_TIERS, b.ACCEPT_FLOOR),) and b.NOTICE_DAYS == 90
    b.check_prices()
    b.check_prices((BOOK, RISE))
    short = RISE._replace(starts="2027-04-03")                                  # 89 days
    with pytest.raises(b.BillingError, match="89 days of notice, and a rise needs 90"):
        b.check_prices((BOOK, short))
    cut = b.Price("2027-01-04", "2027-01-05", ((D(0), D("0.0025")), (D(1_000_000), D("0.0020"))), D("0.05"))
    b.check_prices((BOOK, cut))                                                 # a cut needs no notice
    floor_only = b.Price("2027-01-04", "2027-02-01", BOOK.tiers, D("0.06"))
    with pytest.raises(b.BillingError, match="rise"):                           # a higher floor alone is a rise
        b.check_prices((BOOK, floor_only))
    above = b.Price("2027-01-04", "2027-02-01", ((D(0), D("0.0030")), (D(2_000_000), D("0.0020"))), D("0.05"))
    with pytest.raises(b.BillingError, match="rise"):                           # so is a later start for the lower rate
        b.check_prices((BOOK, above))
    with pytest.raises(b.BillingError, match="before it was announced"):
        b.check_prices((BOOK, RISE._replace(starts="2027-01-01")))


def test_an_order_pays_the_price_in_force_on_the_day_it_was_funded():
    prices = (BOOK, RISE)
    assert b.price_at("2027-04-03", prices) == BOOK and b.price_at("2027-04-04", prices) == RISE
    month = {"plan": "none", "accepted": [{"deliverable": "old", "value": "1000.00", "funded": "2027-04-03"},
                                          {"deliverable": "new", "value": "1000.00", "funded": "2027-04-04"}]}
    inv = b.invoice(month, prices)
    assert line(inv, "acceptance")["amount"] == "7.00"                          # 3.00 at the old price, 4.00 at the rise
    said = line(inv, "price_at_funding")
    assert said["amount"] == "0.00" and said["rule"] == b.RULES["notice"] and said["how"].startswith("1 deliverable at the price in force")
    with pytest.raises(b.BillingError, match="funded: the day its order was funded"):
        b.invoice({"plan": "none", "accepted": [{"deliverable": "x", "value": "1000.00"}]}, prices)
    assert b.invoice({"plan": "none", "accepted": [{"deliverable": "x", "value": "1000.00"}]})["total"] == "3.00"      # one price: no date needed


def test_small_outcomes_funded_under_two_prices_settle_as_two_releases_each_at_its_own_price():
    month = {"plan": "none", "accepted": [{"deliverable": f"o{k}", "value": "10.00", "payee": "acme", "funded": day}
                                          for k, day in enumerate(["2027-03-01"] * 3 + ["2027-05-01"] * 3)]}
    inv = b.invoice(month, (BOOK, RISE))
    acceptance = line(inv, "acceptance")
    assert (acceptance["netted_outcomes"], acceptance["netted_releases"]) == (6, 2)
    assert acceptance["amount"] == "0.21"                                       # 30.00 at 0.30% is 0.09; 30.00 at 0.40% is 0.12
