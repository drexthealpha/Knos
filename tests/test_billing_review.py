"""Exceptional manual review is priced per case by contract and billed as its own line (src/knos/billing.py)."""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from knos import billing as b

ROOT = Path(__file__).resolve().parents[1]


def test_a_manual_review_is_a_separate_line_never_drawn_from_the_commitment():
    base = {"plan": "business", "evaluations": 10, "committed": "50000", "accepted": [{"deliverable": "d1", "value": "1000.00"}]}
    plain = b.invoice(base)
    got = b.invoice({**base, "reviews": [{"case": "case-7", "amount": "25.00"}]})
    review = [x for x in got["lines"] if x["line"] == "review"]
    assert review == [{"line": "review", "what": "Exceptional review case-7", "amount": "25.00", "how": "priced per case by contract",
                       "rule": b.RULES["exceptional"], "pays": "buyer"}]
    assert Decimal(got["total"].replace(",", "")) - Decimal(plain["total"].replace(",", "")) == Decimal("25.00")
    assert got["commitment_remaining"] == plain["commitment_remaining"]
    assert [x for x in got["lines"] if x["line"] != "review"] == plain["lines"]


@pytest.mark.parametrize("row", [{"amount": "25"}, {"case": "x", "amount": "-1"}, "x"])
def test_a_review_without_a_case_or_with_a_negative_price_is_refused(row):
    with pytest.raises(b.BillingError):
        b.invoice({"plan": "team", "reviews": [row]})


def test_the_arithmetic_unit_costs_shows():
    got = b.review_budget()
    assert (got["fee"], got["budget"], got["outcomes"]) == (Decimal("0.00198"), Decimal("0.000099"), 252_525)
    doc = (ROOT / "docs" / "UNIT_COSTS.md").read_text(encoding="utf-8")
    for said in ("| Acceptance on a 0.99 USD outcome at 0.20% | 0.00198 USD |", "0.000099 USD, about 0.0001", "252,525 outcomes, about 250,000",
                 b.RULES["exceptional"], "`knos appeal`"):
        assert said in doc, said
