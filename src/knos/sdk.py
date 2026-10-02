"""The Knos Python SDK: claims, memory, budgets and records for any agent, not only coding agents. (To hire or be
hired, see knos.jobs.api: post_job, find_jobs, claim_job, deliver_job and serve.)

    from knos import sdk

    k = sdk.Knos(agent="researcher")               # a workspace (default: this directory) and an agent name
    if k.claim("task:invoice-4411"):                # False if another agent holds it; .holder says who
        ...do the work...
        k.remember("invoice 4411 was a duplicate", about="invoice-4411")
        k.release("task:invoice-4411")
    k.recall("invoice 4411")                        # what any agent here recorded, from Sibyl

Units are generic: `file:src/a.py` (or a plain path), `task:…`, `market:…`, `wallet:…`. In a workspace with a
`.knos/team.json`, claims are placed on Solana too, so agents on other machines are refused the same way; if the
chain cannot be reached the claim is local only, with a warning. Memory is the workspace's Sibyl store.
"""

from __future__ import annotations

import warnings
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .claims import Claims
from .identity import Agent
from .memory import TOPIC, Fact, Memory


class Held(Exception):
    """Raised when `k.claimed(unit)` cannot be taken because another agent holds it."""

    def __init__(self, unit: str, holder: str) -> None:
        super().__init__(f"{unit} is held by {holder}")
        self.unit = unit
        self.holder = holder


@dataclass
class Knos:
    agent: str
    workspace: Path = field(default_factory=Path.cwd)
    host: str = "sdk"
    holder: str | None = None  # after a refused claim: who holds it

    def __post_init__(self) -> None:
        self.workspace = Path(self.workspace).resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)
        self._me = Agent(host=self.host, session=self.agent)

    # -- claims --------------------------------------------------------------------------------------------------
    @contextmanager
    def claimed(self, unit: str, minutes: int = 30):
        """Context manager: takes `unit` on enter and releases it on exit.
        Raises `Held(unit, holder)` if another agent already holds it."""
        if not self.claim(unit, minutes=minutes):
            raise Held(unit, self.holder or "another agent")
        try:
            yield self
        finally:
            self.release(unit)

    def claim(self, unit: str, minutes: int = 30) -> bool:
        """Take `unit` for this agent. True if held (or already held by it); False if another agent has it."""
        self.holder = None
        with Claims(self.workspace) as c:
            took, clash, _ = c.take(self._me, unit, [unit], holds_min=minutes)
        if not took:
            self.holder = clash.label if clash else "another agent"
            return False
        rt = self._team()
        if rt is not None:
            from .team import live
            try:
                (_, v), = live.claim_units(rt, [unit], self.host, self.agent)
            except Exception as exc:  # noqa: BLE001
                warnings.warn(f"team registry unreachable ({type(exc).__name__}); claim is local only (Knos)")
                return True
            if v.outcome == "lost" and v.lost_to is not None:
                self.release(unit)
                self.holder = live.who(rt, str(v.lost_to.signer), v.lost_to.data.holder)
                return False
            if v.outcome == "offline":
                warnings.warn("team registry unreachable: claim is local only (Knos)")
        return True

    def release(self, unit: str | None = None) -> int:
        """Give back one claim (or all of this agent's). Returns how many were released."""
        with Claims(self.workspace) as c:
            gone = c.release(self._me, unit or "")
        rt = self._team()
        if rt is not None:
            from .team import live
            try:
                live.release_all(rt, self.host, self.agent)
            except Exception:  # noqa: BLE001 - it lapses at its lease
                pass
        return len(gone)

    def holder_of(self, unit: str) -> str | None:
        with Claims(self.workspace) as c:
            got = c.holder(unit, self._me)
        return got.label if got else None

    # -- memory --------------------------------------------------------------------------------------------------
    def remember(self, fact: str, about: str = "") -> bool:
        now = datetime.now(timezone.utc).isoformat()
        with Memory(self.workspace) as mem:
            written = mem.record(Fact(text=fact, source="note", where=f"{self.host}/{self.agent} said so, {now[:10]}",
                                      when=now, about=about))
            if written is None:
                return False
            if about:
                mem.note_thing(TOPIC, about, {"note": fact, "when": now[:10], "who": f"{self.host}/{self.agent}"})
        return True

    def recall(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        from .memory import _flatten
        from . import recall
        with Memory(self.workspace) as mem:
            hits = mem.search(query, limit=limit)
            got = [{"text": h.get("text") or h.get("note") or "", "about": h.get("about", ""),
                    "where": h.get("where", "")} for h in (_flatten(x) for x in hits)]
            shown = {g["text"].strip() for g in got}
            for r in recall.retrieve(mem.client, query, k=limit):
                text = r["text"].split(": ", 1)[-1].strip()
                if text and text not in shown:
                    shown.add(text)
                    got.append({"text": text, "about": "past session", "where": r.get("where") or r.get("date") or ""})
        return got[:limit]

    def memory_client(self):
        """This workspace's Sibyl MemoryClient (for Sibyl's LangGraph BaseStore). Close it with
        the returned Memory: `mem, client = k.memory_client()`."""
        mem = Memory(self.workspace)
        return mem, mem.client

    # -- budgets and records -------------------------------------------------------------------------------------
    def budget(self) -> dict | None:
        """This agent's chain-enforced budget, read from the chain now (None if it has none)."""
        try:
            from .pro import chainbudget as cb
        except ImportError:
            return None
        for key, e in cb.entries().items():
            if key.split("@")[0] == self.agent:
                return {**e, **(cb.tempo_show(e) if e["chain"] == "tempo" else cb.solana_show(e))}
        return None

    def record(self) -> list[dict]:
        """This agent's claim events on this machine (the log its on-chain records are built from)."""
        rt = self._team()
        if rt is None:
            return []
        from .team import live
        me = rt.holder(self.host, self.agent).hash(rt.salt).hex()
        return [e for e in live.events(rt) if e.get("holder") == me]

    def _team(self):
        if not (self.workspace / ".knos" / "team.json").exists():
            return None
        try:
            from .team import live
            return live.runtime(self.workspace)
        except Exception:  # noqa: BLE001
            return None
