"""The waitlist number has to be fetched, never written down.

The rules allow up to ten points for evidence of a real pain point for a real
audience, require a publicly verifiable artifact a judge can check in five
minutes, and disqualify fabricated evidence - including after payout. That
combination makes this the single most dangerous number in the project: the
one where writing an encouraging figure would be worth points right up until
it is not.

So it is not written anywhere. The page asks GitHub's own search API for the
count of public issues carrying the label, in the reader's browser, and links
to the same query so anybody can run it themselves. Today it returns zero and
the page says zero.

These tests exist to keep it that way. They do not check the number - there is
nothing to check - they check that no number *can* be put there by hand.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGE = ROOT / "docs" / "index.html"
FORM = ROOT / ".github" / "ISSUE_TEMPLATE" / "wants-this.yml"


def _script() -> str:
    """The block that fills the waitlist card."""
    page = PAGE.read_text(encoding="utf-8")
    start = page.index("const box = document.querySelector('#wants')")
    return page[start:page.index("})();", start)]


def test_the_count_comes_from_github_not_from_the_page() -> None:
    said = _script()

    assert "api.github.com/search/issues" in said
    assert "total_count" in said, "the number must be the one GitHub returns"


def test_no_number_is_hardcoded_anywhere_near_it() -> None:
    """The failure this file exists to prevent, spelled out.

    A judge who finds a typed figure here is entitled to distrust every other
    number in the repository, and would be right to.
    """
    said = _script()
    # Digits that are not part of a status code, an index, or a comparison.
    typed = re.findall(r"(?<![\w.])(\d{1,6})(?![\w.])", said)
    allowed = {"0", "1", "200"}
    invented = [n for n in typed if n not in allowed]

    assert not invented, (
        f"a number appears in the waitlist block that GitHub did not supply: "
        f"{invented}"
    )


def test_the_reader_is_given_the_query_to_run_themselves() -> None:
    """Countable by anyone is the whole point; a card alone is a claim."""
    said = _script()

    assert "issues?q=" in said, "no link through to the issues being counted"
    assert "label:wants-this" in said


def test_zero_is_shown_rather_than_hidden() -> None:
    said = _script()

    assert "total_count || 0" in said, "an absent count must read as zero"
    assert "count them yourself" in said, (
        "when GitHub cannot be reached the page must say so and hand over the "
        "link, not quietly show nothing"
    )


def test_the_signup_asks_for_the_pain_not_just_the_name() -> None:
    """The rules want a validated pain point, not a headcount."""
    form = FORM.read_text(encoding="utf-8")

    assert "labels: [\"wants-this\"]" in form, "the label is what makes it countable"
    assert "stepped on each other" in form, "it never asks what actually went wrong"
    assert "Which agents" in form


def test_the_page_does_not_call_them_users() -> None:
    """A signup is not a user, and the ledger says so everywhere else."""
    page = PAGE.read_text(encoding="utf-8")
    start = page.index("Who wants this")
    section = page[start:page.index("What is not true yet", start)]

    assert "retained user" in section, (
        "the waitlist card has to keep saying that none of these is a user"
    )
