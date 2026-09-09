"""What every agent is told at the start of a session, before it asks anything.

Knos has always been able to answer "who is on what" - but only when an agent
chose to call a tool. An agent that never calls `search` never learns that
somebody else is mid-change on the file it is about to open, and the first
thing it does is the collision this product exists to prevent.

A `SessionStart` hook closes that. It runs once when a session opens, prints
the live claims and the most recent decisions, and the client puts them in the
session's own context. No tool call, no cooperation from the model, no
prompting the person to remember to ask.

Deliberately small, and deliberately quiet:

  - it prints nothing at all when nothing is claimed and nothing was decided,
    because a hook that speaks every time teaches people to ignore it
  - it never fails a session: any error exits 0 with no output, the same rule
    `guard_hook` follows, because a broken install must not sit between an
    agent and its own repository
  - it imports the store and nothing else - no Typer, no rich - since this is
    on the path of opening a session

What it is not: it does not claim anything, write anything, or change what the
agent may do. It is the notice board, read aloud once on the way in.
"""

from __future__ import annotations

import sys

# Enough to be useful at a glance, few enough that nobody scrolls past it.
CLAIMS = 6
DECISIONS = 3


def _lines(repo) -> list[str]:
    """The notice, or an empty list when there is nothing worth saying."""
    from .memory import INTENT_HOLDS, Memory, _minutes_since

    said: list[str] = []
    with Memory(repo) as mem:
        claims = mem.claims()[:CLAIMS]
        if claims:
            said.append("Work other agents are holding here right now:")
            for one in claims:
                who = str(one.get("who") or "somebody")
                topic = str(one.get("topic") or "").strip()
                # What is left, not what it started with. `holds` is the
                # length the claim was written with, so printing it raw told
                # an agent a claim taken twenty-five minutes ago still had
                # thirty to run - in the one line somebody reads to decide
                # whether waiting is worth it. The withhold has always
                # subtracted the elapsed time; this now does too.
                try:
                    holds = int(one.get("holds", INTENT_HOLDS))
                except (TypeError, ValueError):
                    holds = INTENT_HOLDS
                left = holds - _minutes_since(str(one.get("when", "")))
                when = ""
                if left == left and left > 0:  # not NaN, not already lapsed
                    when = f", lapses in about {max(1, round(left))} min"
                said.append(f"  - {topic} - {who}{when}")
            said.append("")
            said.append(
                "Before you change any of that, ask knos about it. If you take "
                "something, say so with remember(claiming=true), and call "
                "done(about) when you finish."
            )

        # `notes()` returns rows keyed `note`, not `text`. Reading the wrong
        # one filtered every note out and the decisions half printed nothing -
        # the same trap `written_rules` fell into, where a bare `source` key
        # lives inside `extra`. Both are read here.
        def said_in(row: dict) -> str:
            return " ".join(str(row.get("note") or row.get("text") or "").split())

        try:
            notes = [n for n in mem.notes() if said_in(n)]
        except Exception:
            notes = []
        if notes:
            if said:
                said.append("")
            said.append("Recently written down here:")
            for note in notes[:DECISIONS]:
                said.append(f"  - {said_in(note)[:160]}")
    return said


def main(argv: list[str] | None = None) -> int:
    """Print the notice. Never fail the session."""
    try:
        from . import paths

        repo = paths.repo_here()
        if repo is None or not paths.has_store(repo):
            return 0
        said = _lines(repo)
        if not said:
            # Nothing claimed, nothing decided. Say nothing: a hook that
            # speaks on every session is a hook people learn to skip.
            return 0
        sys.stdout.write("knos, this repo's shared memory:\n" + "\n".join(said) + "\n")
    except Exception:
        # A session must open whatever state knos is in.
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
