"""How long an agent gets to hold work, learned from whether it finishes.

Every claim in knos lapsed after the same thirty minutes, whoever made it.
That is the wrong number twice over. An agent that says `knos done` the moment
it finishes has its work stolen out from under it on a long task; an agent
that takes a claim and dies keeps everybody else off that file for the full
half hour, every time, and nothing about the store gets wiser.

So the length of a hold is learned, from one thing only: the share of claims
this agent has actually closed. That number comes out of the COLD journal,
which already keeps what happened - the claim being taken, and the claim being
finished - so this reads history rather than keeping a second scoreboard.

    finished / taken -> hold

    never finishes    0.0   ->  15 minutes
    unknown agent      -    ->  30 minutes, the old flat default
    always finishes   1.0   ->  45 minutes

The rule is deliberately dull. A reliability score with momentum, decay and
tiers would be more impressive and would be fitted to about eleven events;
this is a ratio with a floor and a ceiling, and it is honest about being one.

What makes it load-bearing rather than decorative: the store is the only place
this history exists. Delete it and every agent is a stranger again, worth
exactly thirty minutes - which is the behaviour knos had before this module,
and is what `scripts/contention.py` measures the cost of.

Two limits, stated rather than discovered later. The history is the last
thousand journal entries, so in a repo busy enough to push claims past that
window an agent's oldest record falls off the back and it drifts towards
looking new again; that is a forgetting curve nobody designed, and if it ever
matters the fix is a counter in WARM rather than a bigger number here. And an
agent chooses its own name, so this measures the reliability of a name, not of
a process - which is the same trust model the rest of knos already has, where
a claim is a thing an agent says about itself.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

FLOOR = 15  # minutes, the least a claim is ever worth
CEILING = 45  # minutes, the most any record can earn
UNKNOWN = 30  # an agent knos has never seen finish or fail

TAKEN = "claimed"
FINISHED = "finished"

# Written as ordinary journal facts so `knos why` and search see them like
# anything else. The prefix is what makes them findable again.
_MARK = "knos.claim"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def note_taken(mem: Any, topic: str, who: str, when: str = "") -> None:
    """Write down that `who` took `topic`."""
    from .memory import Fact

    try:
        mem.record(
            Fact(
                text=f"{_MARK} {TAKEN}: {who} took {topic}",
                source="claim",
                where=who,
                when=when or _now(),
                about=topic,
            )
        )
    except Exception:
        # The claim itself has already happened and matters more than the
        # note about it. A full store must not stop work being claimed.
        pass


def note_finished(mem: Any, topic: str, who: str, when: str = "") -> None:
    """Write down that `who` closed `topic` rather than letting it lapse."""
    from .memory import Fact

    try:
        mem.record(
            Fact(
                text=f"{_MARK} {FINISHED}: {who} finished {topic}",
                source="claim",
                where=who,
                when=when or _now(),
                about=topic,
            )
        )
    except Exception:
        pass


def _fields(entry: dict[str, Any]) -> tuple[str, str]:
    """(text, who) out of a journal row.

    A journal row keeps the fact's own keys under `extra`; the top level is
    Sibyl's shape, where the text is `evaluated` and the source is `acted`.
    Reading the top level for `where` finds nothing at all, which made every
    agent look like one nobody had ever seen.
    """
    extra = entry.get("extra")
    if isinstance(extra, dict):
        return str(extra.get("text") or ""), str(extra.get("where") or "")
    return str(entry.get("evaluated") or ""), ""


def history(mem: Any, who: str) -> tuple[int, int]:
    """(taken, finished) for `who`, out of the journal."""
    taken = finished = 0
    for entry in mem.journal(limit=1000):
        text, where = _fields(entry)
        if not text.startswith(_MARK) or where != who:
            continue
        if f"{TAKEN}:" in text:
            taken += 1
        elif f"{FINISHED}:" in text:
            finished += 1
    return taken, finished


def holds_for(mem: Any, who: str) -> int:
    """Minutes `who` may hold a claim, given what it has done before.

    Unknown agents get the old flat default. Nobody is punished for being
    new, and nobody earns a long hold without having closed anything.
    """
    taken, finished = history(mem, who)
    if taken < 2:
        return UNKNOWN

    kept = min(1.0, finished / taken)
    earned = round(FLOOR + kept * (CEILING - FLOOR))
    return max(FLOOR, min(CEILING, earned))


def reliability(mem: Any, who: str) -> dict[str, Any]:
    """The whole record for one agent, for `knos who` and the tests."""
    taken, finished = history(mem, who)
    return {
        "who": who,
        "taken": taken,
        "finished": finished,
        "kept": round(finished / taken, 2) if taken else None,
        "holds": holds_for(mem, who),
        "learned": taken >= 2,
    }


def everyone(mem: Any) -> list[dict[str, Any]]:
    """Every agent the journal has seen claim anything, worst record first."""
    seen: set[str] = set()
    for entry in mem.journal(limit=1000):
        text, where = _fields(entry)
        if text.startswith(_MARK) and where:
            seen.add(where)
    out = [reliability(mem, who) for who in seen]
    out.sort(key=lambda r: (r["kept"] if r["kept"] is not None else 1.0, r["who"]))
    return out


# Spending is the other thing a record can decide, and the reason it is worth
# deciding: on a machine several agents share, the money one of them spends is
# money out of the same pocket. An agent that buys a brief and then abandons
# the work it bought it for has spent it on nothing, and it will do it again in
# half an hour.
TRIED = 3      # claims before anyone is judged on spending at all
KEEPS = 1 / 3  # the share it has to close to keep spending on its own


def may_spend(mem: Any, who: str) -> tuple[bool, str]:
    """Whether `who` should spend shared money, and why not if not.

    Deliberately blunt, and deliberately hard to trip: nobody is refused
    without a real record of abandoning work, and one bad afternoon is not a
    record. A new agent spends freely, because refusing on no evidence is the
    failure this whole file is written against.

    This is not a security boundary and does not pretend to be one. An agent
    picks its own name. It is the same trust model as the rest of knos - what
    an agent says about itself, held against what it did last time - applied
    at the one point where being wrong costs actual money.
    """
    taken, finished = history(mem, who)
    if taken < TRIED:
        return True, ""
    if finished / taken >= KEEPS:
        return True, ""
    return False, (
        f"{who} has taken {taken} pieces of work here and closed {finished}. "
        "Money spent on work that gets abandoned is spent on nothing, and "
        "this machine's budget is shared. Close what you are holding with "
        "`knos done`, or ask the person to buy it for you."
    )
