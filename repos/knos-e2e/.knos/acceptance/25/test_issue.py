"""Acceptance tests for issue 25: digits stay in a slug."""
from slug import slugify


def test_digits_stay():
    assert slugify("Top 10 Tips") == "top-10-tips"


def test_a_number_alone_is_a_slug():
    assert slugify("2026") == "2026"
