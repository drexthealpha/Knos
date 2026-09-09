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


def test_the_ways_in_table_names_only_things_that_exist() -> None:
    """Six reviews called this a narrow product while reading "Three ways in".

    There are eleven, and the table saying so is worth exactly as much as its
    weakest row: a judge who checks one path and finds nothing there has been
    given a reason to distrust the other ten. So every path it links is
    checked, the way the patterns table is.
    """
    import re

    guide = GUIDE.read_text(encoding="utf-8")
    block = guide[guide.index("## Every way in"): guide.index("## The same claim with")]

    paths = re.findall(r"\]\((\.\./[\w/.\-]+)\)", block)
    assert len(paths) >= 6, "the table stopped pointing at anything checkable"

    missing = [rel for rel in paths if not (ROOT / "docs" / rel).resolve().exists()]
    assert not missing, f"the ways-in table points at files that are gone: {missing}"


def test_the_ways_in_table_does_not_confuse_surface_with_adoption() -> None:
    """Eleven ways in is not eleven users, and the count is still zero."""
    guide = GUIDE.read_text(encoding="utf-8")
    block = guide[guide.index("## Every way in"): guide.index("## The same claim with")]

    assert "retained users" in block
    assert "zero" in block, "the table has to keep saying nobody depends on this"


def test_the_demo_map_lists_every_beat_the_demo_actually_has() -> None:
    """A judge reading the table and counting beats must find them equal.

    The table is the thing that tells somebody where to look. If it names ten
    beats and the command prints eleven, the first thing they check does not
    match, and that costs more than the missing row.
    """
    import re

    guide = GUIDE.read_text(encoding="utf-8")
    table = guide[guide.index("## Every strength, and where you can watch it"):
                  guide.index("### What the one command deliberately does not show")]
    rows = re.findall(r"^\| (\d+) \|", table, re.M)

    demo = (ROOT / "src" / "knos" / "demo.py").read_text(encoding="utf-8")
    beats = re.findall(r"screen\.beat\((\d+),", demo)

    assert sorted(int(x) for x in rows) == sorted(int(x) for x in beats), (
        f"the guide lists beats {sorted(rows)} and the demo runs {sorted(beats)}"
    )


def test_the_map_admits_what_the_demo_does_not_show() -> None:
    """The multiplier turns on this, so it cannot be quietly omitted.

    A partner stack scores only when a judge sees it doing real work in the
    demo. `knos demo` spends nothing by design, so the guide has to say that
    the recording needs a live payment, a live grant, or the receipts command
    on tape - rather than leaving a judge to discover the gap.
    """
    guide = GUIDE.read_text(encoding="utf-8")
    block = guide[guide.index("### What the one command deliberately does not show"):
                  guide.index("## Every way in")]

    assert "a real payment on Base" in block
    assert "live_gate.py" in block, "no route to a live settlement is offered"
    assert "documented rather than demonstrated" in block, (
        "the guide must say plainly that on-chain work not on tape is not "
        "the same as on-chain work in the demo"
    )
