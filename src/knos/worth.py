"""What knos has actually done here, so a person can decide to keep it.

Every refusal in this product is invisible when it works. An agent asks about
something another agent is holding, is told to go and ask them, and picks up
something else - and the person never sees any of it. The collision that did
not happen leaves no trace in the day, only in the store.

That is a real problem rather than a philosophical one. A tool whose value is
entirely in things that did not happen gets uninstalled by somebody who
reasonably concludes it is doing nothing. So this counts the times it did
something, out of records written for their own reasons at the time:

    stood down    an agent asked about claimed work and went elsewhere
    overrode      an agent forced past a claim, and said why
    reversed      a decision was withdrawn and work under it was held
    finished      claims closed rather than left to lapse

There is no separate counter and nothing is incremented anywhere. These are
read back out of WARM and the journal, which means the numbers cannot drift
from what happened, and deleting the store takes them with it - the same
property everything else here has.

    knos worth

Deliberately not a score, a streak, or a graph. It is four counts and the
dates they span, and if they are all zero it says that plainly: knos has not
been needed here yet, which is a true and useful thing to be told.
"""

from __future__ import annotations

from typing import Any


def _dates(rows: list[dict[str, Any]]) -> tuple[str, str]:
    stamps = sorted(str((r.get("body") or {}).get("when", "")) for r in rows)
    stamps = [s for s in stamps if s]
    return (stamps[0][:10], stamps[-1][:10]) if stamps else ("", "")


def tally(mem: Any) -> dict[str, Any]:
    """What has happened here, counted from what was written down."""
    from . import decide, record
    from .memory import OVERRODE, STOOD_DOWN

    stood = mem.things(STOOD_DOWN, limit=1000)
    forced = mem.things(OVERRODE, limit=1000)

    taken = finished = 0
    people: set[str] = set()
    for event in record.entries(mem):
        people.add(event["who"])
        if event["kind"] == record.TAKEN:
            taken += 1
        else:
            finished += 1

    first, last = _dates(stood + forced)

    return {
        "stood_down": len(stood),
        "overrode": len(forced),
        "held": len(decide.suspects(mem)),
        "claims_taken": taken,
        "claims_finished": finished,
        "agents": len({p for p in people if p}),
        "first": first,
        "last": last,
    }


def _times(n: int) -> str:
    return "once" if n == 1 else f"{n} times"


def _span(first: str, last: str) -> str:
    """A date range, or a single date when both ends are the same day.

    "between 2026-09-08 and 2026-09-08" is the sort of thing that makes a
    person stop trusting the rest of the line.
    """
    if not first:
        return ""
    return f", on {first}" if first == last else f", between {first} and {last}"


def sentence(got: dict[str, Any]) -> str:
    """One line a person can act on, or an honest nothing."""
    if not got["stood_down"] and not got["overrode"]:
        if got["claims_taken"]:
            claims = "One claim" if got["claims_taken"] == 1 else (
                f"{got['claims_taken']} claims")
            return (
                f"{claims} here, and no agent has yet asked about work another "
                "one was holding. Nothing has collided, so nothing has been "
                "refused."
            )
        return (
            "Nothing has been claimed here yet, so there has been nothing to "
            "refuse. knos is not earning its place on this repo."
        )

    parts = []
    if got["stood_down"]:
        parts.append(f"{_times(got['stood_down'])} an agent asked about work "
                     "somebody else was holding and went elsewhere")
    if got["overrode"]:
        parts.append(f"{_times(got['overrode'])} one went ahead anyway, and "
                     "said why")
    said = "; ".join(parts) + _span(got["first"], got["last"]) + "."
    return said[0].upper() + said[1:]
