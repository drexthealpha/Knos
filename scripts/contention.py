"""What the learned hold is worth, in work nobody could get at.

`scripts/collide.py` shows the claim is correct: exactly one agent gets the
work. Correct is not the same as useful. A lock that is right and too long
still costs a day, because every other agent sits behind an abandoned claim
until it lapses.

So this measures the cost rather than the correctness. A working day of a
repo where some agents finish what they claim and some take work and die:

    flat        every claim worth thirty minutes, whoever made it
    learned     the hold each agent has earned by closing its own claims

The number is blocked-minutes: for every attempt an agent made on work
somebody else was no longer really doing, how long it stayed shut out. It is
not a benchmark of knos against another tool. It is knos against the version
of itself that does not read its own journal.

    python scripts/contention.py

Writes docs/evidence/contention.json.
"""

from __future__ import annotations

import json
import random
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

SEED = 1337
DAY = 8 * 60  # minutes
TOPICS = ["the parser", "the lexer", "the guard", "the store", "the report"]

# Who is in the repo, and how often each actually closes what it claims.
AGENTS = {
    "Claude Code": 0.95,
    "Cursor": 0.90,
    "a crashy runner": 0.10,
    "a stale CI agent": 0.05,
}


def _repo(root: Path) -> Path:
    repo = root / "repo"
    repo.mkdir(parents=True)
    (repo / "parser.py").write_text("x = 1\n", encoding="utf-8")
    run = lambda *a: subprocess.run(  # noqa: E731
        ["git", *a], cwd=repo, capture_output=True, text=True, check=False
    )
    run("init", "-q")
    run("config", "user.email", "c@example.invalid")
    run("config", "user.name", "c")
    run("add", "-A")
    run("commit", "-qm", "first")
    return repo


def _day(rng: random.Random) -> list[tuple[int, str, str, bool]]:
    """(minute, who, topic, finishes) for one day, the same for both arms."""
    out = []
    for minute in range(0, DAY, 7):
        who = rng.choice(list(AGENTS))
        out.append((minute, who, rng.choice(TOPICS), rng.random() < AGENTS[who]))
    return out


def _run(repo: Path, events, learned: bool) -> dict:
    """Play the day. Returns what it cost."""
    from knos import record
    from knos.memory import Memory

    start = datetime.now(timezone.utc) - timedelta(minutes=DAY + 60)
    held: dict[str, tuple[str, int, int]] = {}  # topic -> (who, taken_at, hold)
    blocked = 0
    blocked_minutes = 0
    worked = 0

    with Memory(repo) as mem:
        for minute, who, topic, finishes in events:
            hold = record.holds_for(mem, who) if learned else record.UNKNOWN

            owner = held.get(topic)
            if owner is not None:
                other, at, their_hold = owner
                if other != who and minute - at < their_hold:
                    # Somebody else still holds it. How much of that hold is
                    # left is the cost this agent is paying right now.
                    blocked += 1
                    blocked_minutes += their_hold - (minute - at)
                    continue

            held[topic] = (who, minute, hold)
            worked += 1
            record.note_taken(mem, topic, who,
                              (start + timedelta(minutes=minute)).isoformat())
            if finishes:
                record.note_finished(
                    mem, topic, who,
                    (start + timedelta(minutes=minute + 1)).isoformat(),
                )
                held.pop(topic, None)

    return {
        "arm": "learned" if learned else "flat",
        "attempts": len(events),
        "worked": worked,
        "blocked": blocked,
        "blocked_minutes": blocked_minutes,
    }


def main() -> int:
    import os

    rng = random.Random(SEED)
    events = _day(rng)

    home = Path(tempfile.mkdtemp(prefix="knos-contention-home-"))
    work = Path(tempfile.mkdtemp(prefix="knos-contention-"))
    os.environ["KNOS_HOME"] = str(home)

    try:
        print(f"One working day: {len(events)} attempts, {len(TOPICS)} files,")
        print(f"{len(AGENTS)} agents, two of which mostly do not finish.")
        print()

        arms = []
        for learned in (False, True):
            # A fresh repo per arm, so neither inherits the other's journal.
            repo = _repo(work / ("learned" if learned else "flat"))
            from knos import paths

            paths.remember_pointed(repo)
            got = _run(repo, events, learned)
            arms.append(got)
            print(f"  {got['arm']:8} {got['worked']:3} claims taken,"
                  f" {got['blocked']:3} attempts blocked,"
                  f" {got['blocked_minutes']:5} minutes waiting")

        flat, learned_arm = arms
        saved = flat["blocked_minutes"] - learned_arm["blocked_minutes"]
        share = (saved / flat["blocked_minutes"] * 100) if flat["blocked_minutes"] else 0

        report = {
            "generated": datetime.now(timezone.utc).isoformat(),
            "seed": SEED,
            "day_minutes": DAY,
            "agents": AGENTS,
            "arms": arms,
            "minutes_saved": saved,
            "percent_less_waiting": round(share, 1),
        }
        out = ROOT / "docs" / "evidence" / "contention.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

        print()
        print(f"  {saved} fewer minutes spent waiting on work nobody was doing"
              f" ({share:.0f}% less).")
        print(f"  wrote {out.relative_to(ROOT).as_posix()}")
        return 0
    finally:
        os.environ.pop("KNOS_HOME", None)
        shutil.rmtree(work, ignore_errors=True)
        shutil.rmtree(home, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
