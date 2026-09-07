"""The judge guide cites line numbers. Line numbers rot.

The hackathon gate asks for the critical-path calls to be findable in under
two minutes, write sites and read sites. `docs/JUDGE_GUIDE.md` answers that
with a table of `memory.py:NNN` links, which is the most useful form of the
answer and the most fragile: add six lines to `memory.py` and every one of
them quietly points at the wrong call.

A citation that used to be true is worse than no citation, because a judge
following it finds something unrelated and stops believing the rest of the
page. So this checks each one against the file it names.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GUIDE = ROOT / "docs" / "JUDGE_GUIDE.md"

# `memory.py:190`](../src/knos/memory.py#L190) `write_event`
CITATION = re.compile(
    r"\[`memory\.py:(\d+)`\]\(\.\./src/knos/memory\.py#L(\d+)\)\s*`([a-z_]+)`"
)


def test_the_guide_exists_and_states_the_critical_path() -> None:
    text = GUIDE.read_text(encoding="utf-8")
    assert "**write**" in text and "**read**" in text, (
        "the guide no longer separates write sites from read sites, which is "
        "what the gate asks for by name"
    )


def test_every_line_number_the_guide_cites_is_still_that_call() -> None:
    text = GUIDE.read_text(encoding="utf-8")
    lines = (ROOT / "src" / "knos" / "memory.py").read_text(
        encoding="utf-8"
    ).splitlines()

    cited = CITATION.findall(text)
    assert cited, "the critical-path table has gone from the judge guide"

    wrong = []
    for shown, linked, call in cited:
        assert shown == linked, f"`memory.py:{shown}` links to L{linked}"
        n = int(shown)
        if not (1 <= n <= len(lines)) or f"client.{call}(" not in lines[n - 1]:
            found = lines[n - 1].strip()[:60] if 1 <= n <= len(lines) else "past EOF"
            wrong.append(f"L{n} should be `client.{call}(` but is: {found}")

    assert not wrong, (
        "the judge guide points at lines that have moved:\n  "
        + "\n  ".join(wrong)
        + "\n\nRegenerate the table rather than editing the numbers by hand."
    )


def test_the_four_reads_that_change_something_are_all_named() -> None:
    """The wrapper test: written and never read back is a hard fail."""
    text = GUIDE.read_text(encoding="utf-8")
    for module in ("mcp.py", "guard.py", "gate.py", "record.py"):
        assert module in text, (
            f"{module} is a place the store is read to change what happens, "
            "and the guide no longer says so"
        )
