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

That table is what a settled record earns. Getting there takes evidence: two
events are not a measurement, and the first version of this rule let them
swing the whole range, so an agent that took two claims and closed neither
dropped straight to the floor. Thin evidence is pooled with the thirty-minute
prior and only past STRONG observations does the ratio stand on its own -
which is why four claims closed out of four is worth thirty-eight minutes and
eight is worth forty-five.

Quiet counts too. Evidence halves every HALF_LIFE_DAYS, so a name that closed
everything it took in June is drifting back toward the prior by September
rather than still spending June's credit, and an agent nobody has seen for a
season leaves WARM entirely until it claims again.

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

# ---- the promoted record -------------------------------------------------
#
# The journal is where a claim event is written and stays. It is also a
# window: `entries` reads the last thousand rows, and a store holds about a
# thousand facts, so on a busy repo the oldest claims fall off the back and an
# agent drifts towards looking new again. That was written down in this file
# as a known limit before it was measured; measuring the cap made it real.
#
# So the counts are also kept as one canonical WARM record per agent, which
# does not fall out of a window. The journal stays the audit trail - `knos at`
# still reconstructs from it, because a point-in-time answer has to come from
# what was written at the time, not from a running total.
STANDING = "agent_record"

# Observations before the record is canonical rather than provisional. Below
# this an agent is still learning-in-public and the prior does most of the
# work; the number is the same one `holds_for` already used to decide an agent
# was worth judging at all.
PROVEN = 2

# Shrinkage. A ratio over two events is not a measurement, and the old rule
# let it swing the full 15-to-45 range: one agent that took two claims and
# closed neither dropped straight to the floor. The evidence is pooled with a
# prior worth PRIOR_WEIGHT observations at PRIOR_KEEPS, which is the ratio
# that maps to the thirty minutes an unknown agent already gets - so thin
# evidence moves the number a little and a real record moves it a lot.
PRIOR_WEIGHT = 4.0
PRIOR_KEEPS = 0.5

# Where the prior lets go. Pooling that never stops makes FLOOR and CEILING
# unreachable - an agent that closed forty claims out of forty would still be
# quoted forty-one minutes, and the two constants would describe a range the
# code cannot return. Past this many observations the record is its own
# evidence and the ratio is used as it stands.
STRONG = 8

# Decay. A name that finished everything it took in June should not still be
# spending June's credit in September. Evidence halves every HALF_LIFE_DAYS of
# silence, which pulls a quiet agent back toward the prior rather than
# punishing it - it is forgetting, not a penalty.
HALF_LIFE_DAYS = 45.0

# Archive. An agent nobody has seen for this long leaves WARM entirely, so the
# tier stays a list of who is actually around. It is recoverable: the next
# claim it makes writes the record again, and the journal never lost anything.
ARCHIVE_AFTER_DAYS = 180.0

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
        _promote(mem, who, TAKEN, when or _now())
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
        _promote(mem, who, FINISHED, when or _now())
    except Exception:
        pass


def _promote(mem: Any, who: str, kind: str, when: str) -> None:
    """Fold one claim event into this agent's canonical record.

    Schema-unique on the agent's name, so this is an update rather than a row
    per event: an agent with four hundred claims has one record, not four
    hundred. A store that cannot take the write is not a reason to fail the
    claim - the journal already has the event, and the ratio falls back to
    reading it.
    """
    if not who:
        return
    try:
        was = mem.thing(STANDING, who) or {}
        body = was.get("body") if isinstance(was.get("body"), dict) else was
        taken = int(body.get("taken", 0) or 0)
        finished = int(body.get("finished", 0) or 0)
        first = str(body.get("first_seen") or when)
        mem.note_thing(STANDING, who, {
            "taken": taken + (1 if kind == TAKEN else 0),
            "finished": finished + (1 if kind == FINISHED else 0),
            "first_seen": first,
            "last_seen": when,
        })
    except Exception:
        # Promotion is an optimisation over the journal, never a precondition
        # for it. Everything here can be recomputed from what was written.
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


def entries(mem: Any) -> list[dict[str, Any]]:
    """Every claim event in the journal, as (kind, who, topic, when).

    Read once here so `history` and `knos.rewind` walk the same list rather
    than each parsing the journal in its own slightly different way.
    """
    out: list[dict[str, Any]] = []
    for entry in mem.journal(limit=1000):
        text, where = _fields(entry)
        if not text.startswith(_MARK):
            continue
        extra = entry.get("extra") if isinstance(entry.get("extra"), dict) else {}
        kind = TAKEN if f"{TAKEN}:" in text else (
            FINISHED if f"{FINISHED}:" in text else "")
        if not kind:
            continue
        out.append({
            "kind": kind,
            "who": where,
            "topic": str(extra.get("about") or ""),
            "when": str(extra.get("when") or ""),
        })
    out.sort(key=lambda e: e["when"])
    return out


def history(mem: Any, who: str, before: str = "") -> tuple[int, int]:
    """(taken, finished) for `who`, out of the journal.

    `before` restricts it to what had happened by an ISO timestamp, which is
    what lets `knos at` say what an agent had earned *then* rather than what
    it has earned since.
    """
    taken = finished = 0
    for event in entries(mem):
        if event["who"] != who:
            continue
        if before and event["when"] and event["when"] > before:
            continue
        if event["kind"] == TAKEN:
            taken += 1
        else:
            finished += 1
    return taken, finished


def _age_days(when: str, now: str = "") -> float:
    """Days between an ISO stamp and now, or 0 when it cannot be read."""
    try:
        then = datetime.fromisoformat(str(when).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return 0.0
    try:
        here = (datetime.fromisoformat(now.replace("Z", "+00:00")) if now
                else datetime.now(timezone.utc))
    except ValueError:
        here = datetime.now(timezone.utc)
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)
    return max(0.0, (here - then).total_seconds() / 86400.0)


def standing(mem: Any, who: str, now: str = "") -> dict[str, Any]:
    """What `who` has earned, from the promoted record, aged and shrunk.

    Three things happen here that a scan of the journal cannot do.

    **It does not fall out of a window.** The counts come from the canonical
    WARM record when there is one, so an agent whose oldest claims have been
    pushed past the last thousand journal rows keeps its record. The journal
    is still consulted when no record has been promoted yet, which is what
    makes a store written by an older version of knos still work.

    **Evidence gets lighter with age.** Counts are multiplied by a half-life,
    so a name that closed everything it took in June is drifting back toward
    the prior by September rather than still spending June's credit. This is
    forgetting, not a penalty: it moves a quiet agent toward the middle, never
    below it.

    **Thin evidence is pooled with a prior.** Two events are not a
    measurement. The old rule let them swing the whole fifteen-to-forty-five
    range, so an agent that took two claims and closed neither hit the floor
    immediately. Pooling with PRIOR_WEIGHT observations at PRIOR_KEEPS means
    a short record moves the number a little and a long one moves it a lot.
    """
    body: dict[str, Any] = {}
    try:
        was = mem.thing(STANDING, who) or {}
        body = was.get("body") if isinstance(was.get("body"), dict) else was
    except Exception:
        body = {}

    if body.get("taken") is not None:
        taken = float(body.get("taken") or 0)
        finished = float(body.get("finished") or 0)
        last = str(body.get("last_seen") or "")
        promoted = True
    else:
        # No promoted record: either an older store, or an agent whose events
        # are all still inside the window. Read them the way this file always
        # has, so nothing regresses.
        raw_taken, raw_finished = history(mem, who)
        taken, finished = float(raw_taken), float(raw_finished)
        last = ""
        promoted = False

    quiet = _age_days(last, now) if last else 0.0
    weight = 0.5 ** (quiet / HALF_LIFE_DAYS) if quiet else 1.0
    aged_taken, aged_finished = taken * weight, finished * weight

    # How much evidence there is, and how fresh it is, are two questions. The
    # count decides whether the record can speak for itself; the weight
    # decides how much of what it says still applies. Deciding both with the
    # decayed count meant a record a few hours old could never reach STRONG,
    # because the weight is always a hair under one.
    if taken >= STRONG:
        raw = finished / taken if taken else PRIOR_KEEPS
        # Fresh, this is the ratio as it stands. Left alone for a season it
        # slides back toward the prior instead of holding its old credit.
        kept = weight * raw + (1.0 - weight) * PRIOR_KEEPS
    else:
        # Too thin to stand alone: pooled with the prior, and the pool uses
        # the aged counts so that old thin evidence counts for even less.
        kept = ((aged_finished + PRIOR_WEIGHT * PRIOR_KEEPS)
                / (aged_taken + PRIOR_WEIGHT))
    return {
        "who": who,
        "taken": int(taken),
        "finished": int(finished),
        "promoted": promoted and taken >= PROVEN,
        "quiet_days": round(quiet, 1),
        "weight": round(weight, 3),
        "kept": round(kept, 3),
        "raw_kept": round(finished / taken, 3) if taken else None,
    }


def archive_the_quiet(mem: Any, now: str = "") -> list[str]:
    """Move agents nobody has seen for a season out of WARM. Returns the names.

    The tier is meant to be a list of who is around, and an agent that stopped
    working in the spring is not. Nothing is lost: the journal keeps every
    event, and the next claim that agent makes writes its record again from
    the count it had - which is what makes this an archive rather than a
    delete.

    Not called on the critical path. `knos who` runs it, because that is the
    command whose whole job is looking at the list.
    """
    moved: list[str] = []
    try:
        rows = mem.things(STANDING, limit=1000)
    except Exception:
        return moved
    for row in rows:
        body = row.get("body") if isinstance(row.get("body"), dict) else row
        name = str(row.get("name") or "")
        last = str((body or {}).get("last_seen") or "")
        if not name or not last:
            continue
        if _age_days(last, now) >= ARCHIVE_AFTER_DAYS:
            try:
                mem.supersede(STANDING, name, "no claims for a season")
                moved.append(name)
            except Exception:
                pass
    return moved


def holds_for(mem: Any, who: str, before: str = "") -> int:
    """Minutes `who` may hold a claim, given what it has done before.

    Unknown agents get the old flat default. Nobody is punished for being
    new, and nobody earns a long hold without having closed anything.

    `before` asks what it had earned at a past moment, which is what a
    reconstruction of an old collision has to use - the hold that applied
    then, not the one the agent has earned since.
    """
    if before:
        # A reconstruction has to use what was written by then, so it reads
        # the journal rather than a running total that includes everything
        # since. `knos at` is the only caller that passes this.
        taken, finished = history(mem, who, before)
        if taken < PROVEN:
            return UNKNOWN
        kept = min(1.0, finished / taken)
        return max(FLOOR, min(CEILING, round(FLOOR + kept * (CEILING - FLOOR))))

    got = standing(mem, who)
    if got["taken"] < PROVEN:
        return UNKNOWN

    earned = round(FLOOR + min(1.0, got["kept"]) * (CEILING - FLOOR))
    return max(FLOOR, min(CEILING, earned))


def reliability(mem: Any, who: str) -> dict[str, Any]:
    """The whole record for one agent, for `knos who` and the tests."""
    got = standing(mem, who)
    return {
        "who": who,
        "taken": got["taken"],
        "finished": got["finished"],
        "kept": got["raw_kept"],
        "shrunk": got["kept"],
        "quiet_days": got["quiet_days"],
        "promoted": got["promoted"],
        "holds": holds_for(mem, who),
        "learned": got["taken"] >= PROVEN,
    }


def everyone(mem: Any) -> list[dict[str, Any]]:
    """Every agent the journal has seen claim anything, worst record first."""
    seen: set[str] = set()
    try:
        for row in mem.things(STANDING, limit=1000):
            name = str(row.get("name") or "")
            if name:
                seen.add(name)
    except Exception:
        pass
    # And anyone whose events are still in the window but has not been
    # promoted yet, so a first claim shows up immediately.
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
    got = standing(mem, who)
    taken, finished = got["taken"], got["finished"]
    if taken < TRIED:
        return True, ""
    # Judged on the shrunk and aged ratio, not the raw one: an agent that
    # abandoned three claims last spring and has been quiet since is drifting
    # back toward the prior rather than being refused forever on a record
    # nobody has tested lately.
    if got["kept"] >= KEEPS:
        return True, ""
    return False, (
        f"{who} has taken {taken} pieces of work here and closed {finished}. "
        "Money spent on work that gets abandoned is spent on nothing, and "
        "this machine's budget is shared. Close what you are holding with "
        "`knos done`, or ask the person to buy it for you."
    )
