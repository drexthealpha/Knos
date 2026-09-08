"""What the record is worth in money, when one agent keeps abandoning work.

`scripts/spend.py` measures the store remembering *what* was bought. This
measures it remembering *who* is buying, which is a different claim and a
sharper one: on a machine several agents share, the budget is one pocket, and
an agent that buys a brief and then drops the work bought nothing.

Two arms over the same day, same asks, same prices:

    trusted   the gate asks only about the topic, the way it did before
              `record.may_spend` existed. Anybody who asks, buys.
    learned   the gate also asks who is buying, and refuses an agent with a
              record of taking work here and not closing it.

The difference is money that left the machine for work nobody finished. The
crashy agent in this day is not a straw man: it is a CI runner that starts a
task, buys the input, and is killed before it closes anything - which is the
ordinary way this happens.

    python scripts/budget.py

Writes docs/evidence/budget.json.
"""

from __future__ import annotations

import json
import os
import random
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

SEED = 1337
PRICE = {"news": 0.001, "brief": 0.01}

# Who is on this machine, and whether each one closes what it starts.
AGENTS = {
    "Claude Code": True,
    "Cursor": True,
    "a killed CI runner": False,
}
SUBJECTS = ["BTC", "ETH", "SOL", "the funding round", "the outage"]
ASKS = 60


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _repo(root: Path) -> Path:
    repo = root / "repo"
    repo.mkdir(parents=True)
    (repo / "trade.py").write_text("def go():\n    return 1\n", encoding="utf-8")
    run = lambda *a: subprocess.run(  # noqa: E731
        ["git", *a], cwd=repo, capture_output=True, text=True, check=False
    )
    run("init", "-q")
    run("config", "user.email", "b@example.invalid")
    run("config", "user.name", "b")
    run("add", "-A")
    run("commit", "-qm", "first")
    return repo


def _day(rng: random.Random) -> list[tuple[str, str, str]]:
    """(who, kind, topic), the same day for both arms."""
    out = []
    for n in range(ASKS):
        who = rng.choice(list(AGENTS))
        kind = "brief" if n % 3 else "news"
        out.append((who, kind, f"market {kind}: {rng.choice(SUBJECTS)}"))
    return out


def replay(repo: Path, day, learned: bool) -> dict:
    """Run the day. Returns what was spent, and on whose behalf."""
    from knos import answer, gate, paths, record
    from knos.memory import TOPIC, Fact, Memory

    paths.remember_pointed(repo)
    with Memory(repo) as mem:
        answer.point(repo, mem, index_code=False)

    # Each agent has already worked here today, and the journal knows how that
    # went. This is the history the learned arm reads and the trusted arm does
    # not have to exist for.
    when = datetime.now(timezone.utc) - timedelta(hours=6)
    with Memory(repo) as mem:
        for who, finishes in AGENTS.items():
            for n in range(6):
                topic = f"earlier {who} {n}"
                stamp = (when + timedelta(minutes=n)).isoformat()
                record.note_taken(mem, topic, who, stamp)
                if finishes:
                    record.note_finished(mem, topic, who,
                                         (when + timedelta(minutes=n, seconds=30)).isoformat())

    bought = free = refused = 0
    spent = wasted = 0.0
    for who, kind, topic in day:
        said = gate.decide(repo, topic, topic, who if learned else "the agent")
        verdict = said["verdict"]
        if verdict == "buy":
            bought += 1
            spent += PRICE[kind]
            if not AGENTS[who]:
                # Bought for work that is about to be abandoned.
                wasted += PRICE[kind]
            with Memory(repo) as mem:
                note = f"Bought over x402 on Base: {kind}. Paid: https://seller/{kind}"
                mem.record(Fact(text=note, source="note", where="the seller",
                                when=_now(), about=topic))
                mem.note_thing(TOPIC, topic, {"note": note, "when": _now()[:10]})
        elif verdict == "unproven":
            refused += 1
        else:
            free += 1

    return {
        "arm": "learned" if learned else "trusted",
        "asks": len(day),
        "bought": bought,
        "free": free,
        "refused": refused,
        "spent_usd": round(spent, 4),
        "spent_on_abandoned_work_usd": round(wasted, 4),
    }


def main() -> int:
    rng = random.Random(SEED)
    day = _day(rng)
    arms = []

    for learned in (False, True):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            os.environ["KNOS_HOME"] = str(root / "home")
            arms.append(replay(_repo(root), day, learned))

    trusted, learned_arm = arms
    saved = round(trusted["spent_usd"] - learned_arm["spent_usd"], 4)
    share = (saved / trusted["spent_usd"] * 100) if trusted["spent_usd"] else 0

    # The percentage is the weaker number and the waste is the stronger one:
    # the point is not that less money moved, it is that the money which moved
    # went to work somebody finished.
    report = {
        "generated": _now(),
        "seed": SEED,
        "asks": ASKS,
        "agents": AGENTS,
        "prices_usd": PRICE,
        "arms": arms,
        "saved_usd": saved,
        "percent_of_the_budget_saved": round(share, 1),
        "spent_on_abandoned_work_before_usd": trusted["spent_on_abandoned_work_usd"],
        "spent_on_abandoned_work_after_usd": learned_arm["spent_on_abandoned_work_usd"],
    }
    out = ROOT / "docs" / "evidence" / "budget.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    print(f"one day, {ASKS} asks, {len(AGENTS)} agents, one of which never"
          " closes anything\n")
    for arm in arms:
        print(f"  {arm['arm']:8} bought {arm['bought']:3}  refused"
              f" {arm['refused']:3}  spent ${arm['spent_usd']:.3f}"
              f"  of which ${arm['spent_on_abandoned_work_usd']:.3f} on work"
              " that was dropped")
    print()
    before = trusted["spent_on_abandoned_work_usd"]
    after = learned_arm["spent_on_abandoned_work_usd"]
    print(f"  ${before:.3f} of the day's spending went to work that was dropped."
          f" With the record: ${after:.3f}.")
    print(f"  ${saved:.3f} of the budget kept ({share:.0f}%), and the agents that"
          " finish things kept buying.")
    print(f"  wrote {out.relative_to(ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
