"""Claim and withhold, as a library you can embed. No MCP, no CLI.

Almost nobody wants to install and keep running a separate server to get
this behaviour. They want it inside the tool they already have. This module
is that door: the claim, the connection-bound hold and the refusal, importable
from any Python agent or tool.

    from knos.core import Claims

    with Claims(repo=".", who="my-agent") as claims:
        taken, holder = claims.take("the risk guard")
        if not taken:
            print(claims.withheld("the risk guard"))   # or just refuse
        ...
        claims.release()

Nothing here is new logic. `take` is `Memory.claim_if_free`, the compare-and-
swap that decides exactly one winner when two agents reach for the same work
in the same second. `withheld` is the same sentence `knos` gives an agent
over MCP. `holds` is `answer.same_subject`, so a claim on "parser" covers a
question about "parsing". The MCP server in `mcp.py` is one caller of this
surface, not the definition of it.

Two things worth knowing before you embed it:

**The hold is bound to a connection, not a name.** Whatever you pass as
`session` is what a later caller must match to count as the holder. The MCP
server passes its own process id, because a client that names itself can
claim to be anyone. If you leave it empty the hold falls back to the name
alone, which is weaker; pass something the holder has and a different caller
cannot borrow.

**A claim lapses on its own.** Thirty minutes by default, so a crashed agent
cannot hold work for ever. Re-take it to refresh it.

The store is one SQLite file per repo under `~/.knos/`. It is created on
first use and needs no daemon.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import answer
from .memory import Memory

__all__ = ["Claims", "holds", "withheld_message"]

# Re-exported so a caller can match subjects without opening a store: this is
# the rule that makes a claim on "parser" cover a question about "parsing".
holds = answer.same_subject
withheld_message = answer.withheld


def _stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


class Claims:
    """One repo's claims, open for as long as you hold it.

    `who` is the name that appears to other agents. `session` is what binds
    a hold to this caller specifically; it defaults to the process id, which
    is what the MCP server uses and is right for one agent per process. Pass
    your own if a single process serves several independent agents.
    """

    def __init__(
        self, repo: str | Path = ".", who: str = "an agent", session: str | None = None
    ) -> None:
        self.repo = Path(repo).resolve()
        self.who = who
        self.session = os.getpid() if session is None else session
        self.session = str(self.session)
        self._mem: Memory | None = None

    # -- lifecycle ---------------------------------------------------------

    def __enter__(self) -> "Claims":
        self._mem = Memory(self.repo)
        return self

    def __exit__(self, *_: object) -> None:
        mem, self._mem = self._mem, None
        if mem is not None:
            close = getattr(mem, "close", None)
            if callable(close):
                close()

    @property
    def memory(self) -> Memory:
        if self._mem is None:
            raise RuntimeError("use Claims as a context manager: with Claims(...) as c:")
        return self._mem

    # -- the three things this exists for ----------------------------------

    def take(self, topic: str) -> tuple[bool, dict[str, Any] | None]:
        """Claim `topic` unless somebody else holds it.

        Returns (True, None) when it is yours, or (False, holder) when it is
        not. Calling it again with a claim you already hold refreshes it.
        """
        return self.memory.claim_if_free(topic, self.who, _stamp(), session=self.session)

    def holder(self, subject: str) -> dict[str, Any] | None:
        """Whoever holds work covering `subject`, or None if it is free.

        Subject matching is by shared word stems, so a claim on "the risk
        guard" answers a question about "guards".
        """
        for work in self.memory.claims():
            topic = str(work.get("topic", ""))
            if holds(topic, subject) and not self.mine(work):
                return work
        return None

    def withheld(self, subject: str) -> str:
        """The refusal to give an agent asking about claimed work, or "".

        The same words the MCP server uses, so an embedded agent and a
        connected one are told the same thing.
        """
        work = self.holder(subject)
        if work is None:
            return ""
        who = str(work.get("who", "")) or "another agent"
        topic = str(work.get("topic", ""))
        by_the_person = who == "you"
        held = topic if by_the_person else f"{topic} (held by {who})"
        return withheld_message(held, by_the_person)

    def release(self) -> None:
        """Give up everything this repo's store says is being worked on."""
        self.memory.done_working()

    # -- reading -----------------------------------------------------------

    def live(self) -> list[dict[str, Any]]:
        """Every claim that has not lapsed, oldest first."""
        return sorted(self.memory.claims(), key=lambda c: str(c.get("when", "")))

    def mine(self, work: dict[str, Any]) -> bool:
        """Whether this caller is the one holding `work`.

        Both the name and the session, because a name alone can be asserted
        by anyone. A claim written without a session falls back to the name,
        which is no weaker than it was before sessions existed.
        """
        held_by = str(work.get("who", ""))
        session = str(work.get("session", ""))
        if session:
            return held_by == self.who and session == self.session
        return held_by == self.who
