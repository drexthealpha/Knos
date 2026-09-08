"""Point the judge guide's critical-path table at where the calls are now.

The table cites `memory.py:NNN` because that is the most useful form of the
answer for somebody checking the gate in two minutes, and the most fragile:
add six lines to `memory.py` and every citation quietly points at something
else. `tests/test_judge_guide.py` fails when that happens, and this is what it
tells you to run.

    python scripts/refresh_citations.py

Reads the line numbers out of the source rather than being told them, so the
table cannot be wrong in a way this script agrees with.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GUIDE = ROOT / "docs" / "JUDGE_GUIDE.md"
SOURCE = ROOT / "src" / "knos" / "memory.py"

# Calls that appear once, so the name alone finds them.
UNIQUE = (
    "write_event", "set_entity", "set_reference", "archive_entity",
    "read_events", "get_entity", "search", "get_reference",
)


def main() -> int:
    lines = SOURCE.read_text(encoding="utf-8").splitlines()

    def find(needle: str, after: int = 0) -> int:
        for n, text in enumerate(lines, 1):
            if n > after and needle in text:
                return n
        raise SystemExit(f"{needle} is no longer in memory.py")

    where = {call: find(f"self.client.{call}(") for call in UNIQUE}
    # `set_state` is written twice and read once, and which is which matters:
    # the focus write comes first, the claim write after it.
    focus = find("self.client.set_state(INTERNAL")
    claim = find("self.client.set_state(", after=focus)
    get_state = find("self.client.get_state(INTERNAL")
    cas = find("INSERT INTO state_documents")

    doc = GUIDE.read_text(encoding="utf-8")
    before = doc

    for call, line in where.items():
        doc = re.sub(
            r"\[`memory\.py:\d+`\]\(\.\./src/knos/memory\.py#L\d+\) `" + call + "`",
            f"[`memory.py:{line}`](../src/knos/memory.py#L{line}) `{call}`",
            doc, count=1,
        )

    for line, tail in (
        (claim, r"`set_state` \| the live claim, into HOT"),
        (focus, r"`set_state` \| what the session"),
        (get_state, r"`get_state`"),
    ):
        doc = re.sub(
            r"\[`memory\.py:\d+`\]\(\.\./src/knos/memory\.py#L\d+\) " + tail,
            lambda m, n=line: re.sub(r"memory\.py:\d+", f"memory.py:{n}",
                                     re.sub(r"#L\d+", f"#L{n}", m.group(0))),
            doc, count=1,
        )

    doc = re.sub(
        r"\[`memory\.py:\d+`\]\(\.\./src/knos/memory\.py#L\d+\) - one",
        f"[`memory.py:{cas}`](../src/knos/memory.py#L{cas}) - one",
        doc, count=1,
    )

    if doc == before:
        print("Every citation already points at the right line.")
        return 0

    GUIDE.write_text(doc, encoding="utf-8", newline="\n")
    print("Updated docs/JUDGE_GUIDE.md:")
    for call, line in sorted(where.items()):
        print(f"  {call:16} L{line}")
    print(f"  {'set_state (claim)':16} L{claim}")
    print(f"  {'set_state (focus)':16} L{focus}")
    print(f"  {'get_state':16} L{get_state}")
    print(f"  {'claim_if_free CAS':16} L{cas}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
