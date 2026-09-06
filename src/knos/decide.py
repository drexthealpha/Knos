"""Correcting a decision, and everything that rested on it.

A claim says who is moving right now. A decision says what was settled. The
second one is the more dangerous of the two, because it goes stale silently:
somebody changes their mind in a meeting, the old sentence stays in the file,
and three agents keep building on a thing that is no longer true.

So a decision here can be **superseded**, and superseding one is not a quiet
overwrite. It does three things:

1. The old decision is archived, not deleted. Sibyl's ARCHIVE tier keeps what
   was believed and when it stopped being believed, so "why did we do it that
   way" still has an answer after the answer changed.
2. Everything on the same subject is marked **suspect**. That is the blast
   radius: a decision rarely stands alone, and the notes that leaned on it are
   exactly the ones nobody thinks to revisit.
3. Until each suspect thing is **reconsidered**, knos refuses on it - the edit
   is blocked, the purchase is refused, and the pull request is told. Not a
   warning. The same refusal a claim gets.

Reconsidering is one call and costs nothing. That asymmetry is deliberate:
carrying on with work built on a decision somebody just reversed should be a
thing you say out loud, and saying it should be cheap.

Nothing here invents a new store. It is Sibyl's WARM tier for the decision,
ARCHIVE for the superseded one, and COLD for the journal entry - the same
three the rest of knos uses.
"""

from __future__ import annotations

from typing import Any

from .memory import TOPIC

#: Things resting on a decision that was reversed, until somebody looks again.
SUSPECT = "suspect"


def _subject(a: str, b: str) -> bool:
    from .answer import same_subject

    return same_subject(a, b)


def supersede(
    mem: Any, about: str, note: str, who: str, when: str
) -> dict[str, list[str]]:
    """Replace a decision, archive the old one, and taint what leaned on it.

    Returns {"superseded": [...], "suspect": [...]} - what was replaced and
    what now needs reconsidering before knos will let work continue on it.
    """
    old = mem.thing(TOPIC, about)
    was = str((old or {}).get("body", {}).get("note", "")) if old else ""

    # 1. Keep what was believed. ARCHIVE, not delete: the question "what did we
    #    think before, and when did that change" has to stay answerable.
    if old is not None:
        try:
            mem.supersede(TOPIC, about, f"superseded by {who} on {when[:10]}: {note}")
        except Exception:  # noqa: BLE001 - an unarchivable old note must not
            pass          # block recording the new one

    # 2. The new decision takes the name.
    mem.note_thing(TOPIC, about, {"note": note, "when": when[:10]})

    # 3. The blast radius. Anything on the same subject was probably reasoned
    #    from the sentence that just changed.
    tainted: list[str] = []
    for thing in mem.things(TOPIC, limit=1000):
        name = str(thing.get("name", ""))
        if not name or name == about:
            continue
        if not _subject(about, name):
            continue
        mem.note_thing(
            SUSPECT,
            name,
            {"because": about, "was": was, "now": note, "who": who, "when": when},
        )
        tainted.append(name)

    from .memory import Fact

    mem.record(
        Fact(
            text=(
                f"{who} superseded the decision on {about}."
                + (f" It used to be: {was}." if was else "")
                + f" It is now: {note}."
                + (
                    f" {len(tainted)} thing(s) on the same subject are suspect"
                    " until reconsidered."
                    if tainted
                    else ""
                )
            ),
            source="note",
            where=f"{who}, {when[:10]}",
            when=when,
            about=about,
        )
    )
    return {"superseded": [about] if old is not None else [], "suspect": tainted}


def suspects(mem: Any) -> list[dict[str, Any]]:
    """Everything still resting on a decision that was reversed."""
    out = []
    for thing in mem.things(SUSPECT, limit=1000):
        body = thing.get("body") or {}
        out.append(
            {
                "about": str(thing.get("name", "")),
                "because": str(body.get("because", "")),
                "was": str(body.get("was", "")),
                "now": str(body.get("now", "")),
                "who": str(body.get("who", "")),
                "when": str(body.get("when", "")),
            }
        )
    return sorted(out, key=lambda s: s["when"])


def is_suspect(mem: Any, subject: str) -> dict[str, Any] | None:
    """The suspicion covering `subject`, or None.

    Subject matching is the same shared-stem rule a claim uses, so a reversed
    decision about "the risk guard" covers a note about "guards".
    """
    for found in suspects(mem):
        if found["about"] == subject or _subject(found["about"], subject):
            return found
    return None


def reconsider(mem: Any, about: str, who: str, when: str) -> bool:
    """Say this was looked at again. Returns whether anything was suspect."""
    hit = None
    for found in suspects(mem):
        if found["about"] == about or _subject(found["about"], about):
            hit = found
            break
    if hit is None:
        return False

    try:
        mem.supersede(SUSPECT, hit["about"], f"reconsidered by {who} on {when[:10]}")
    except Exception:  # noqa: BLE001
        return False

    from .memory import Fact

    mem.record(
        Fact(
            text=(
                f"{who} reconsidered {hit['about']} after the decision on"
                f" {hit['because']} changed."
            ),
            source="note",
            where=f"{who}, {when[:10]}",
            when=when,
            about=hit["about"],
        )
    )
    return True


def refusal(found: dict[str, Any]) -> str:
    """What an agent is told when it touches something suspect."""
    was = f" It used to be: {found['was']}." if found.get("was") else ""
    return (
        f"Held back. The decision on {found['because']} was changed by"
        f" {found['who']} on {found['when'][:10]}, and {found['about']} was"
        f" reasoned from it.{was} It is now: {found['now']}."
        "\n\nThis is not blocked forever. Look at it, then say so:"
        f'\n    knos reconsider "{found["about"]}"'
        "\n\nCarrying on without looking is the thing that turns one reversed"
        " decision into a week of work built on it."
    )
