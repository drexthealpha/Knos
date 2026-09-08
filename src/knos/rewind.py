"""Who held what, at a moment that has already passed.

Two agents collided on Tuesday afternoon. One of them edited a file the other
was in the middle of, or a purchase went through that should not have, or a
decision was reversed and something got built on the old wording anyway. The
question afterwards is always the same: *what did the machine know at the
time, and who was holding what?*

Every other part of knos answers about now. `knos claim` is about now, the
withhold is about now, the guard is about now. This is the only one that
answers about then, and it answers from the journal rather than from anything
kept for the purpose - the claim events, the notes, the reversals, all of
which were written for their own reasons and carry the time they happened.

    knos at "2026-09-08 14:00"

It is read-only and it never guesses. A claim with no recorded close is
reconstructed as live for exactly the hold that agent had earned **by that
moment**, not the one it has earned since - because the hold that applied on
Tuesday is the one that decided whether Tuesday's edit was refused. Getting
that backwards would produce a confident, wrong account of the thing somebody
is trying to understand, which is worse than no account.

What it cannot do is stated where it happens: the journal keeps the last
thousand entries, so a long enough history has a floor below which this says
so rather than pretending the store was empty.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from . import record


def when(text: str) -> str:
    """An ISO timestamp from what a person is likely to type.

    Accepts an ISO string, a date, "2026-09-08 14:00", or a plain "90m" /
    "3h" / "2d" meaning that long ago. Returns "" when it cannot tell, and
    the caller says so rather than silently choosing a moment.
    """
    text = (text or "").strip()
    if not text:
        return ""

    if text[-1:] in "mhd" and text[:-1].strip().isdigit():
        size = {"m": "minutes", "h": "hours", "d": "days"}[text[-1]]
        ago = timedelta(**{size: int(text[:-1])})
        return (datetime.now(timezone.utc) - ago).isoformat()

    for shape in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            got = datetime.strptime(text, shape)
        except ValueError:
            continue
        return got.replace(tzinfo=timezone.utc).isoformat()

    try:
        got = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return ""
    if got.tzinfo is None:
        got = got.replace(tzinfo=timezone.utc)
    return got.isoformat()


def _minutes_between(start: str, end: str) -> float:
    try:
        a = datetime.fromisoformat(start.replace("Z", "+00:00"))
        b = datetime.fromisoformat(end.replace("Z", "+00:00"))
    except ValueError:
        return float("inf")
    if a.tzinfo is None:
        a = a.replace(tzinfo=timezone.utc)
    if b.tzinfo is None:
        b = b.replace(tzinfo=timezone.utc)
    return (b - a).total_seconds() / 60


def held_at(mem: Any, moment: str) -> list[dict[str, Any]]:
    """Every claim that was live at `moment`, and who had it.

    A claim is live from the event that took it until either the event that
    closed it, or the hold running out. The hold used is the one its agent had
    earned by then - `record.holds_for(..., before=moment)` - because that is
    the number that decided whether an edit at that moment was refused.
    """
    events = record.entries(mem)
    live: dict[tuple[str, str], dict[str, Any]] = {}

    for event in events:
        if not event["when"] or event["when"] > moment:
            continue
        key = (event["who"], event["topic"])
        if event["kind"] == record.TAKEN:
            live[key] = event
        else:
            live.pop(key, None)

    out = []
    for (who, topic), event in live.items():
        holds = record.holds_for(mem, who, before=moment)
        age = _minutes_between(event["when"], moment)
        if age > holds:
            continue  # it had already lapsed by then
        out.append({
            "topic": topic,
            "who": who,
            "taken": event["when"],
            "held_for": round(age, 1),
            "would_lapse_after": holds,
        })
    out.sort(key=lambda c: c["taken"])
    return out


def known_at(mem: Any, moment: str, about: str = "") -> list[dict[str, Any]]:
    """What the store had been told by `moment`, newest first.

    Facts only, and only the ones with a timestamp on or before the moment.
    Claim bookkeeping is left out: it is answered by `held_at` and repeating
    it here would double every line.
    """
    seen = []
    for entry in mem.journal(limit=1000):
        extra = entry.get("extra")
        if not isinstance(extra, dict):
            continue
        text = str(extra.get("text") or "")
        if text.startswith("knos.claim"):
            continue
        stamp = str(extra.get("when") or "")
        if not stamp or stamp > moment:
            continue
        if about and about.lower() not in (str(extra.get("about") or "")).lower():
            continue
        seen.append({
            "text": text,
            "about": str(extra.get("about") or ""),
            "where": str(extra.get("where") or ""),
            "when": stamp,
        })
    seen.sort(key=lambda f: f["when"], reverse=True)
    return seen


# How a stand-down and an override sign themselves in the journal. Both are
# written by `Memory` for their own reasons; this reads the signature rather
# than adding a field, so an older store reconstructs the same way a new one
# does.
YIELDED = " yielded to "
OVERRODE = " overrode "


def collisions_at(mem: Any, moment: str) -> list[dict[str, Any]]:
    """The times two agents wanted the same thing, up to `moment`.

    Separated from `known_at` because this is the reason somebody typed the
    command. A stand-down and an override are the two possible endings of a
    collision, and finding them mixed in among ordinary notes is finding them
    the hard way.
    """
    out = []
    for entry in mem.journal(limit=1000):
        extra = entry.get("extra")
        if not isinstance(extra, dict):
            continue
        where = str(extra.get("where") or "")
        stamp = str(extra.get("when") or "")
        if not stamp or stamp > moment:
            continue
        if YIELDED in where:
            kind = "stood down"
        elif OVERRODE in where:
            kind = "overrode"
        else:
            continue
        out.append({
            "kind": kind,
            "text": str(extra.get("text") or ""),
            "about": str(extra.get("about") or ""),
            "when": stamp,
        })
    out.sort(key=lambda c: c["when"])
    return out


def oldest(mem: Any) -> str:
    """The earliest moment the journal can still speak for.

    The journal read is capped, so there is a floor. Saying where it is beats
    reconstructing an empty machine and calling that history.
    """
    stamps = []
    for entry in mem.journal(limit=1000):
        extra = entry.get("extra")
        if isinstance(extra, dict) and extra.get("when"):
            stamps.append(str(extra["when"]))
    return min(stamps) if stamps else ""


def at(mem: Any, moment: str, about: str = "", facts: int = 8) -> dict[str, Any]:
    """The whole answer for one moment: who held what, and what was known."""
    collisions = collisions_at(mem, moment)
    said = [c["text"] for c in collisions]
    return {
        "moment": moment,
        "earliest_the_journal_holds": oldest(mem),
        "claims": held_at(mem, moment),
        "collisions": collisions,
        # Reported once. A stand-down is a fact like any other and would
        # otherwise appear in both lists, which reads like two events.
        "known": [f for f in known_at(mem, moment, about)
                  if f["text"] not in said][:facts],
    }
