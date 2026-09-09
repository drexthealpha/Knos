"""Whether you have the problem knos is for, measured on your own machine.

Every other project in this space asserts its pain point, and so did this one:
the README says two agents change the same thing without knowing, and asks you
to believe it. That is exactly what the rules call a market-size slide.

It does not have to be asserted. Claude Code writes a timestamped transcript
for every session it runs, and knos already reads them as a source. So the
question "do you actually run more than one agent at a time?" has an answer
sitting on the asker's own disk, and `knos why` counts it.

What it counts is windows in which two or more different sessions each did
something. That is the precondition for a collision, and the distinction is
the whole honesty of this: two agents working in the same minute may be
nowhere near each other in the tree. Nothing here says they collided. It says
how often you had two of them going at once, which is the situation the rest
of the product is about.

If the answer is zero, it says zero and says knos is probably not for you.
That is a real outcome and printing it is the only reason the other number is
worth anything.

Nothing leaves the machine and nothing is written down: this reads transcripts
and prints counts.
"""

from __future__ import annotations

import collections
from datetime import datetime
from pathlib import Path

# The widths reported together, because a share that only holds at one of them
# is a property of the bucketing rather than of the day.
WINDOWS = (1, 5, 15, 30)


def _when(said: str) -> datetime | None:
    try:
        return datetime.fromisoformat(str(said).replace("Z", "+00:00"))
    except ValueError:
        return None


def measure(repo: Path | None = None) -> dict:
    """{turns, sessions, clients, windows: {width: (working, shared, percent)}}.

    `repo` narrows it to the sessions that touched one repository; without it
    the answer covers everything the machine has done.
    """
    from . import sessions

    turns = []
    for turn in sessions.read_all(repo):
        when = _when(turn.when)
        if when is not None:
            turns.append((when, turn.session, turn.client))

    if not turns:
        return {"turns": 0, "sessions": 0, "clients": [], "windows": {}}

    windows = {}
    for width in WINDOWS:
        seen: dict[int, set] = collections.defaultdict(set)
        for when, session, _client in turns:
            seen[int(when.timestamp() // (width * 60))].add(session)
        working = len(seen)
        shared = sum(1 for who in seen.values() if len(who) > 1)
        windows[width] = (working, shared, round(100 * shared / working, 1))

    return {
        "turns": len(turns),
        "sessions": len({s for _w, s, _c in turns}),
        "clients": sorted({c for _w, _s, c in turns}),
        "windows": windows,
    }


def sentence(got: dict) -> str:
    """One line that is honest when the answer is no.

    A tool that only speaks up when the number flatters it is an advert. The
    zero case is the one worth getting right, because it is the one that tells
    somebody not to install this.
    """
    if not got["turns"]:
        return (
            "No agent transcripts on this machine, so there is nothing to "
            "count. knos reads Claude Code's own session files; if you use a "
            "different agent, this cannot see it."
        )
    if got["sessions"] < 2:
        return (
            f"One session, {got['turns']} turns. You have never had two agents "
            "going at once here, so knos has nothing to coordinate and you "
            "probably do not need it."
        )

    five = got["windows"].get(5)
    if five is None or not five[1]:
        return (
            f"{got['sessions']} sessions and {got['turns']} turns, but never "
            "two at the same time. knos is for the overlap, and you do not "
            "have any."
        )
    return (
        f"{five[2]}% of the five-minute windows in which you had an agent "
        f"working, you had more than one. That is {five[1]} of {five[0]} "
        "windows, out of "
        f"{got['turns']} turns across {got['sessions']} sessions."
    )
