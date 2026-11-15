"""Claims as a library you can embed. No MCP, no CLI.

    from knos.core import Claims

    with Claims(repo=".", who="my-agent") as claims:
        taken, holder = claims.take("the parser", paths=["src/parser/**"])
        if not taken:
            print(holder["who"], "has", holder["globs"])
        ...
        claims.release()

`take` is the same single-transaction claim the MCP server and CLI use (`claims.Claims.take`): of two callers
reaching for overlapping paths in the same second, exactly one wins. `holder(path)` is the check the edit guard
makes. A claim given only a description resolves exact file and symbol names; if none resolve it is advisory and
never blocks.

`who` and `session` make the identity. `session` defaults to this process id, so two processes are two agents; pass
your own when one process serves several independent agents, or share one when several processes are one agent.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from . import claims as _claims
from .identity import Agent

__all__ = ["Claims"]


class Claims:
    """One repo's claims, open for as long as you hold it."""

    def __init__(self, repo: str | Path = ".", who: str = "agent", session: str | None = None) -> None:
        self.repo = Path(repo).resolve()
        self.who = who
        self.session = str(os.getpid() if session is None else session)
        self.agent = Agent(host=who, session=self.session)
        self._c: _claims.Claims | None = None

    def __enter__(self) -> "Claims":
        self._c = _claims.Claims(self.repo).__enter__()
        return self

    def __exit__(self, *exc: object) -> None:
        if self._c is not None:
            self._c.__exit__(*exc)
            self._c = None

    @property
    def store(self) -> _claims.Claims:
        if self._c is None:
            raise RuntimeError("use Claims as a context manager: with Claims(...) as c:")
        return self._c

    def take(self, description: str, paths: list[str] | None = None) -> tuple[bool, dict[str, Any] | None]:
        """(True, None) when the claim is yours (taken or refreshed), or (False, holder) when another agent holds
        overlapping paths."""
        took, conflict, _mine = self.store.take(self.agent, description, paths)
        return took, (conflict.as_dict() if conflict else None)

    def holder(self, path: str) -> dict[str, Any] | None:
        """Whoever else holds `path` (repo-relative), or None if you may edit it."""
        got = self.store.holder(_claims.norm(path), self.agent)
        return got.as_dict() if got else None

    def release(self, description: str = "") -> list[str]:
        """Release your own claims (one, by description or id, or all of yours). Never anyone else's."""
        return [c.description for c in self.store.release(self.agent, description)]

    def live(self) -> list[dict[str, Any]]:
        return [c.as_dict() for c in self.store.live()]

    def mine(self, work: dict[str, Any]) -> bool:
        return self.agent.owns(str(work.get("host", "")), str(work.get("session", "")), work.get("anchor"))
