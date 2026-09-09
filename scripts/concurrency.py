"""How often more than one agent is actually working at once, from real transcripts.

Everything else about the problem this product addresses was asserted. The
README says two agents change the same thing without knowing; `contention.json`
models sixty-nine attempts with reliabilities somebody chose. Neither measures
whether two agents are ever really running at the same time.

The transcripts are on the disk already. Claude Code writes one JSONL file per
session with a timestamp on every turn, and knos reads them as a source. So
this counts, over every session on this machine, the windows in which two or
more different sessions each did something.

What it measures is the *precondition*, and the distinction matters:

    two agents working at once   measured here
    two agents colliding         not measured here, and not claimed

Concurrency is necessary for a collision and does not imply one. Two sessions
in the same minute may be nowhere near each other in the tree.

It is also one machine, which is a sample of one developer, and it is the
machine knos was built on - so it is evidence about the author's own working
day and nothing wider. Run it on yours; the number that matters to you is the
one your own transcripts give.

Nothing from any transcript is written down. Counts only, and session
identifiers are not published either.

    python scripts/concurrency.py     the same count `knos why` prints

Writes docs/evidence/concurrency.json. Deliberately not in the daily workflow:
a CI runner has no agent sessions, so there would be nothing to count.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

# Several window sizes, because one of them alone invites the question. If the
# share only holds at a flattering width it is an artefact of the width.
WINDOWS = (1, 5, 15, 30)


def main() -> None:
    from knos import why

    got = why.measure()
    if not got["turns"]:
        print("No agent transcripts on this machine, so there is nothing to count.")
        return

    windows = {
        f"{width}_minute": {
            "windows_with_any_agent_working": working,
            "windows_with_two_or_more": shared,
            "percent": percent,
        }
        for width, (working, shared, percent) in got["windows"].items()
    }

    out_got = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "machine": "one developer's laptop - the machine knos was built on",
        "turns": got["turns"],
        "sessions": got["sessions"],
        "clients": got["clients"],
        "windows": windows,
        "what_this_measures": (
            "Windows in which two or more different agent sessions each did "
            "something. That is the precondition for a collision."
        ),
        "what_this_does_not_measure": (
            "Collisions. Two sessions in the same minute may be nowhere near "
            "each other in the tree, and nothing here says they were. It is "
            "also one machine and one developer, so it is evidence about this "
            "working day rather than about anybody else's."
        ),
    }
    out = ROOT / "docs" / "evidence" / "concurrency.json"
    out.write_text(json.dumps(out_got, indent=2) + "\n", encoding="utf-8")
    _refresh_guide(out_got)
    print(json.dumps(out_got, indent=2))


# The judge guide prints this table so it can be read offline. These counts
# grow every time anybody works on the machine, so a copy frozen there goes
# stale faster than anything else in the document.
FENCE = "<!-- counted: docs/evidence/concurrency.json -->"
END = "<!-- /counted -->"


def _refresh_guide(got: dict) -> None:
    guide = ROOT / "docs" / "JUDGE_GUIDE.md"
    said = guide.read_text(encoding="utf-8")
    if FENCE not in said:
        return
    w = got["windows"]
    rows = [FENCE, "", "| window | with any agent working | with two or more |",
            "|---|---|---|"]
    for width, label in ((1, "1 minute"), (5, "5 minutes"),
                         (15, "15 minutes"), (30, "30 minutes")):
        one = w[f"{width}_minute"]
        rows.append(
            f"| {label} | {one['windows_with_any_agent_working']:,} "
            f"| {one['windows_with_two_or_more']:,} ({one['percent']}%) |"
        )
    said = said[:said.index(FENCE)] + "\n".join(rows) + "\n" + said[said.index(END):]

    said = re.sub(r"over\n[\d,]+ real turns across \d+ sessions",
                  f"over\n{got['turns']:,} real turns across {got['sessions']} sessions",
                  said, count=1)
    guide.write_text(said, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
