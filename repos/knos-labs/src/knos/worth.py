"""What knos has actually done here, so a person can decide to keep it.

A refusal that works leaves no trace in the day: the collision that did not happen is invisible. So this counts
what happened, from records written at the time for their own reasons (claims.db's `events` and the store's withdrawn
rules). There is no separate counter:

    claimed      claims taken, and by how many agents
    released     claims given back rather than left to lapse
    blocked      edits the guard refused because another agent held the file
    withdrawn    rules the instruction file itself stopped carrying, no longer served

    knos worth

Not a score. If everything is zero it says so: knos has not been needed here yet.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def tally(repo: Path, mem: Any | None = None) -> dict[str, Any]:
    from .claims import Claims, claims_db
    from .memory import WITHDRAWN

    got: dict[str, Any] = {"claimed": 0, "released": 0, "blocked": 0, "agents": 0, "withdrawn": 0,
                           "first": "", "last": "", "live": 0}
    if claims_db(repo).exists():
        with Claims(repo) as c:
            events = c.events(limit=100000)
            got["live"] = len(c.live())
        who: set[str] = set()
        for e in events:
            if e["kind"] == "claim":
                got["claimed"] += 1
                who.add(str(e.get("who", "")))
            elif e["kind"] == "release":
                got["released"] += 1
            elif e["kind"] == "blocked":
                got["blocked"] += 1
        got["agents"] = len({w for w in who if w})
        stamps = sorted(e["ts"] for e in events if e.get("ts"))
        if stamps:
            got["first"], got["last"] = stamps[0][:10], stamps[-1][:10]
    if mem is not None:
        try:
            got["withdrawn"] = len(mem.things(WITHDRAWN, limit=1000))
        except Exception:
            pass
    return got


def _times(n: int) -> str:
    return "once" if n == 1 else f"{n} times"


def _span(first: str, last: str) -> str:
    if not first:
        return ""
    return f", on {first}" if first == last else f", between {first} and {last}"


def sentence(got: dict[str, Any]) -> str:
    """One line a person can act on, or an honest nothing."""
    if got["blocked"]:
        said = (f"The guard refused an edit to a file another agent held {_times(got['blocked'])}"
                f"{_span(got['first'], got['last'])}.")
        return said
    if got["claimed"]:
        n = got["claimed"]
        return (f"{'One claim' if n == 1 else f'{n} claims'} here, and no agent has yet tried to edit a file another "
                "one held. Nothing has collided, so nothing has been refused.")
    if got["withdrawn"]:
        n = got["withdrawn"]
        return (f"{'One rule' if n == 1 else f'{n} rules'} this repo's instruction files stopped carrying "
                f"{'is' if n == 1 else 'are'} no longer served. Nothing has been claimed here yet.")
    return "Nothing has been claimed here yet, so there has been nothing to refuse."
