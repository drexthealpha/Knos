"""The table of what the memory decides has to keep being true.

Knos has a dozen distinct memory patterns and never presented them as a list,
so a judge scanning for sophistication had to assemble it from twenty files.
The judge guide now has the list.

A table like that is the easiest thing in a repository to let rot: a function
gets renamed, a test file moves, and the page keeps confidently naming
something that is not there any more - which is worse than not having listed
it, because the first row a reader checks and cannot find costs them the other
eleven.

So every row is checked against the source and the tests. Nothing here asserts
the patterns are *good*; it asserts the page is not lying about them existing.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GUIDE = ROOT / "docs" / "JUDGE_GUIDE.md"

# | **A claim** | [`memory.claim_if_free`](../src/knos/memory.py) | ... | [`test_collide.py`](../tests/test_collide.py) |
ROW = re.compile(
    r"^\| \*\*(?P<what>[^*]+)\*\* \| \[`(?P<mod>\w+)\.(?P<sym>\w+)`\]"
    r"\(\.\./src/knos/(?P<file>\w+\.py)\) \| (?P<decides>[^|]+) \| "
    r"\[`(?P<test>[\w.]+)`\]\(\.\./(?P<testpath>[\w/.]+)\) \|$",
    re.M,
)


def _rows():
    return list(ROW.finditer(GUIDE.read_text(encoding="utf-8")))


def test_the_table_is_there_and_is_not_a_short_list() -> None:
    rows = _rows()
    assert len(rows) >= 10, (
        f"the patterns table has {len(rows)} rows; it is the answer to the "
        "heaviest criterion and should not quietly shrink"
    )


def test_every_pattern_names_a_function_that_exists() -> None:
    missing = []
    for row in _rows():
        source = ROOT / "src" / "knos" / row["file"]
        if not source.exists():
            missing.append(f"{row['what']}: no {row['file']}")
            continue
        if f"def {row['sym']}(" not in source.read_text(encoding="utf-8"):
            missing.append(f"{row['what']}: {row['mod']}.{row['sym']} is gone")

    assert not missing, (
        "the judge guide names code that is not there:\n  " + "\n  ".join(missing)
    )


def test_every_pattern_names_a_test_that_exists() -> None:
    """A row whose proof has moved is a row a reader cannot check."""
    missing = [
        f"{row['what']}: {row['testpath']}"
        for row in _rows()
        if not (ROOT / row["testpath"]).exists()
    ]

    assert not missing, "the judge guide points at tests that are gone:\n  " + "\n  ".join(missing)


def test_each_row_says_what_it_decides_not_what_it_stores() -> None:
    """The gate's own distinction: a wrapper writes, a product decides.

    A row that describes storage rather than a consequence is the shape the
    rules call decorative, and it would be the easiest way to pad this table.
    """
    lazy = [
        row["what"] for row in _rows()
        if not re.search(r"\bwhether\b|\bwho\b|\bhow long\b|\bis held\b|\bgets\b"
                         r"|\bsurvive\b|\bprevented\b|\bcannot\b|\bdoes not\b",
                         row["decides"])
    ]

    assert not lazy, (
        "these rows describe what is kept rather than what changes because of "
        f"it: {lazy}"
    )
