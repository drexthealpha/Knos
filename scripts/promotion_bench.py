"""What the promoted record is worth, over many seeds, with the spread reported.

`contention.json` compared two arms on one seed. A single seed is an anecdote:
it cannot show whether the difference is the rule or the dice. This runs the
same day many times over, with three arms, and reports the distribution rather
than a headline.

    blind        no memory at all. Every agent is a stranger worth thirty
                 minutes and may spend freely. This is knos with the store
                 deleted, and it is the arm the gate is decided on.
    journal      the ratio as it was read straight off the last thousand
                 journal rows, no prior, no decay.
    promoted     the WARM record: pooled while thin, raw once settled, and
                 lighter the longer an agent has been quiet.

Two things are measured, both of which somebody pays for:

    blocked minutes   time other agents spend waiting on a claim held by an
                      agent that is not going to finish it
    wasted spend      money spent on work that was then abandoned

**What this is not.** There is no model in this loop and no real money. It is
a simulation of agent behaviour with seeded profiles, so it measures what the
*rule* does given that behaviour, not what a language model would do. That is
weaker evidence than a live economic run and it is labelled as such wherever
the number appears. What it does establish is that the difference between the
arms is not one lucky seed.

    python scripts/promotion_bench.py

Writes docs/evidence/promotion.json. No network.
"""

from __future__ import annotations

import json
import random
import statistics
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

SEEDS = 200
DAY_MINUTES = 480
DAYS = 30           # long enough for a busy repo's journal to forget
PRICE = 0.01        # what one bought answer costs, in dollars

# How many claim events the journal arm can still see. The real number is a
# thousand journal rows shared with every fact knos read out of the repo; this
# is that pressure at the scale of this simulation. It is the whole reason the
# promoted record exists, so a bench that leaves it out cannot measure it.
WINDOW = 40

# Agents, and the share of claims each actually closes. These are the input
# assumption and the reason this is a simulation: a real machine's mix is not
# known, so the mix is stated rather than discovered.
AGENTS = {
    "Claude Code": 0.95,
    "Cursor": 0.90,
    "a crashy runner": 0.10,
    "a stale CI agent": 0.05,
}
TOPICS = ("the parser", "the risk guard", "the settlement path", "the lexer")


def _run_one(seed: int, arm: str) -> dict:
    """One working day, one arm. Returns blocked minutes and wasted spend."""
    from knos import record

    rng = random.Random(seed)
    # who holds what, and until when
    held: dict[str, tuple[str, float]] = {}
    # The promoted record: cumulative, and it does not fall out of a window.
    seen: dict[str, list[float]] = {who: [0.0, 0.0, 0.0] for who in AGENTS}
    # The journal: the last WINDOW events, which is all the ratio could read.
    events: list[tuple[str, bool]] = []
    blocked = 0.0
    wasted = 0.0
    spent = 0.0

    def from_window(who: str) -> tuple[float, float]:
        recent = events[-WINDOW:]
        taken = sum(1 for name, _done in recent if name == who)
        finished = sum(1 for name, done in recent if name == who and done)
        return float(taken), float(finished)

    def hold_for(who: str, now: float) -> float:
        if arm == "blind":
            return float(record.UNKNOWN)
        if arm == "journal":
            # Only what is still in the window, which is the point.
            taken, finished = from_window(who)
            if taken < record.PROVEN:
                return float(record.UNKNOWN)
            kept = min(1.0, finished / taken)
        else:
            taken, finished, last = seen[who]
            if taken < record.PROVEN:
                return float(record.UNKNOWN)
            quiet_days = (now - last) / (60 * 24)
            weight = 0.5 ** (quiet_days / record.HALF_LIFE_DAYS)
            if taken >= record.STRONG:
                raw = finished / taken
                kept = weight * raw + (1.0 - weight) * record.PRIOR_KEEPS
            else:
                kept = ((finished * weight + record.PRIOR_WEIGHT * record.PRIOR_KEEPS)
                        / (taken * weight + record.PRIOR_WEIGHT))
        return float(max(record.FLOOR,
                         min(record.CEILING,
                             round(record.FLOOR + kept * (record.CEILING - record.FLOOR)))))

    def may_spend(who: str) -> bool:
        if arm == "blind":
            return True
        if arm == "journal":
            taken, finished = from_window(who)
        else:
            taken, finished, _last = seen[who]
        if taken < record.TRIED:
            return True
        return (finished / taken) >= record.KEEPS

    minute = 0.0
    while minute < DAY_MINUTES * DAYS:
        minute += rng.expovariate(1 / 7.0)
        who = rng.choice(list(AGENTS))
        topic = rng.choice(TOPICS)

        owner = held.get(topic)
        if owner and owner[1] > minute:
            if owner[0] != who:
                # Somebody else is holding it. This agent waits.
                blocked += owner[1] - minute
            continue

        held[topic] = (who, minute + hold_for(who, minute))
        seen[who][0] += 1
        seen[who][2] = minute

        finishes = rng.random() < AGENTS[who]
        if may_spend(who):
            spent += PRICE
            if not finishes:
                wasted += PRICE
        events.append((who, finishes))
        if finishes:
            seen[who][1] += 1
            held[topic] = (who, minute)  # closed, free again

    return {"blocked": blocked, "wasted": wasted, "spent": spent}


def _summary(values: list[float]) -> dict:
    values = sorted(values)
    n = len(values)
    return {
        "mean": round(statistics.fmean(values), 2),
        "median": round(statistics.median(values), 2),
        "p05": round(values[int(0.05 * n)], 2),
        "p95": round(values[int(0.95 * n)], 2),
    }


def main() -> None:
    arms = ("blind", "journal", "promoted")
    got: dict[str, dict] = {}
    per_seed: dict[str, list[dict]] = {arm: [] for arm in arms}

    for arm in arms:
        for seed in range(SEEDS):
            per_seed[arm].append(_run_one(seed, arm))
        got[arm] = {
            "blocked_minutes": _summary([r["blocked"] for r in per_seed[arm]]),
            "wasted_usd": _summary([r["wasted"] for r in per_seed[arm]]),
        }

    # WINDOW is a number somebody chose, and it decides the whole comparison:
    # make it large enough and the journal never forgets, so promotion has
    # nothing to add. Swept rather than asserted, so a reader can see where
    # the advantage comes from and where it disappears.
    global WINDOW
    was = WINDOW
    sweep = {}
    for width in (10, 20, 40, 80, 160, 320):
        WINDOW = width
        journal = [_run_one(seed, "journal")["wasted"] for seed in range(40)]
        promoted = [_run_one(seed, "promoted")["wasted"] for seed in range(40)]
        sweep[width] = {
            "journal_wasted_usd": round(statistics.fmean(journal), 3),
            "promoted_wasted_usd": round(statistics.fmean(promoted), 3),
        }
    WINDOW = was

    # Paired by seed, which is the comparison that matters: the same day, the
    # same dice, one rule changed.
    wins = sum(
        1 for a, b in zip(per_seed["blind"], per_seed["promoted"])
        if b["blocked"] < a["blocked"]
    )
    better = [
        a["blocked"] - b["blocked"]
        for a, b in zip(per_seed["blind"], per_seed["promoted"])
    ]

    out = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "seeds": SEEDS,
        "day_minutes": DAY_MINUTES,
        "days": DAYS,
        "journal_window_events": WINDOW,
        "agents": AGENTS,
        "window_sweep": sweep,
        "arms": got,
        "promoted_vs_blind": {
            "seeds_with_less_waiting": wins,
            "share_of_seeds": round(100 * wins / SEEDS, 1),
            "minutes_saved": _summary(better),
        },
        "what_this_is_not": (
            "A live economic run. This is a simulation: there is no model in "
            "this loop and no real "
            "money: agent behaviour is seeded from the reliabilities listed "
            "above, so this measures what the rule does given that behaviour, "
            "not what a language model would do. It is weaker evidence than a "
            "real-money ablation, and its only claim is that the difference "
            "between the arms is not one lucky seed. An earlier version of "
            "this bench ran a single day with every event visible for ever, "
            "which gave the journal arm a perfect memory and left promotion "
            "nothing to beat - the prior's caution showed up as pure cost. "
            "That was a broken experiment, not a result: the window is the "
            "thing the promoted record exists to survive, so the bench has to "
            "have one."
        ),
    }
    (ROOT / "docs" / "evidence" / "promotion.json").write_text(
        json.dumps(out, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
