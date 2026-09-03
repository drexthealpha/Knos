"""Prove the claim/withhold loop, in two real processes, with no editor open.

    python scripts/withhold.py

Six steps, each printed as it happens: agent A claims, agent B is refused,
the claim is released, the answer returns, and the shared file is written.
Nothing here is a fixture. Both agents are separate OS processes talking to
the same store on disk, which is the only arrangement that proves anything
about two agents on one machine.

Exits non-zero if any step does not behave as described, so it is also a
smoke test.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

# One child process, standing in for an agent. It opens the store itself, so
# nothing is shared in memory between it and this script.
AGENT = """
import json, sys
from datetime import datetime, timezone
from knos import answer
from knos.memory import Memory

repo, who, what = sys.argv[1], sys.argv[2], sys.argv[3]
topic = sys.argv[4]
with Memory(repo) as mem:
    if what == "claim":
        took, holder = mem.claim_if_free(
            topic, who, datetime.now(timezone.utc).isoformat()
        )
        print(json.dumps({"took": took, "holder": (holder or {}).get("who")}))
    elif what == "ask":
        held = mem.claims()
        mine = [c for c in held if c["topic"] == topic]
        found = answer.ask(repo, mem, topic)
        print(json.dumps({
            "withheld": bool(mine) and mine[0]["who"] != who,
            "holder": mine[0]["who"] if mine else None,
            "answers": len(found),
        }))
    elif what == "release":
        mem.done_working()
        print(json.dumps({"released": True}))
"""


def agent(who: str, what: str, topic: str, repo: Path) -> dict:
    """Run one agent as its own process and hand back what it saw."""
    done = subprocess.run(
        [sys.executable, "-c", AGENT, str(repo), who, what, topic],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    if done.returncode != 0:
        sys.exit(f"agent {who} failed:\n{done.stderr}")
    return json.loads(done.stdout.strip().splitlines()[-1])


def step(n: int, said: str) -> None:
    print(f"\n[{n}] {said}")


def main() -> int:
    repo = ROOT
    topic = "the parser"
    print(f"repo: {repo}")
    print(f"two processes, one store, topic: {topic!r}")

    step(0, "clearing anything held from an earlier run")
    agent("setup", "release", topic, repo)

    step(1, "agent A claims it")
    a = agent("Claude Code", "claim", topic, repo)
    print(f"    {a}")
    assert a["took"] is True, "agent A did not get the claim"

    step(2, "agent B asks about the same thing, in another process")
    b = agent("Cursor", "ask", topic, repo)
    print(f"    {b}")
    assert b["withheld"] is True, "agent B was NOT withheld - the gate is open"
    assert b["holder"] == "Claude Code", b

    step(3, "agent B tries to claim it too")
    c = agent("Cursor", "claim", topic, repo)
    print(f"    {c}")
    assert c["took"] is False, "two agents both hold the same claim"
    assert c["holder"] == "Claude Code", c

    step(4, "agent A gives it back")
    agent("Claude Code", "release", topic, repo)

    step(5, "agent B asks again")
    d = agent("Cursor", "ask", topic, repo)
    print(f"    {d}")
    assert d["withheld"] is False, "still withheld after release"

    step(6, "export the shareable half into the repo")
    # The console script by way of the running interpreter, so this works
    # from a checkout with nothing on PATH. check=True on purpose: an export
    # that quietly did nothing would leave step 6 passing on a file an
    # earlier run wrote, which is the kind of green this project exists to
    # refuse.
    shared = ROOT / ".knos" / "decisions.md"
    before = shared.stat().st_mtime if shared.exists() else 0.0
    subprocess.run(
        [sys.executable, "-c", "from knos.cli import app; app()", "export"],
        cwd=str(ROOT),
        check=True,
    )
    assert shared.exists(), "knos export wrote nothing"
    assert shared.stat().st_mtime > before, "knos export did not rewrite the file"
    print(f"    {shared} written")

    print("\nOK - claimed, withheld, refused a second claim, released, answered.")
    print(f"    {datetime.now(timezone.utc).isoformat(timespec='seconds')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
