"""Durable memory. Sibyl owns the store; this is a thin wrapper.

Sibyl is local-first: a SQLite file on this machine, no account, no network.
The five tiers are used plainly.

    WARM entities    one canonical record per thing (schema-unique)
    COLD journal     what was learned, when, from which source
    HOT state        what the current work is about
    REFERENCE        facts that do not change
    ARCHIVE          superseded

No extraction model, no scoring, no pressure. Facts come from sessions, git
and code structure, stated as they were found.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sibyl_memory_client import (
    FREE_TIER_CAP_BYTES,
    CapExceededError,
    MemoryClient,
    Storage,
)

from . import paths

# knos keeps its own bookkeeping in the same store as the facts. Internal
# keys carry this prefix so an answer never quotes knos's plumbing back at
# the person who asked.
INTERNAL = "knos:"

# How long one agent's statement of what it is doing stays worth telling
# another agent. This is the only thing knos stores that expires, because
# it is the only thing that is about now rather than about what happened.
INTENT_HOLDS = 30  # minutes


def _minutes_since(when: str) -> float:
    """Age of a timestamp in minutes, or forever if it cannot be read."""
    from datetime import datetime, timezone

    try:
        then = datetime.fromisoformat(when.replace("Z", "+00:00"))
    except ValueError:
        return float("inf")
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - then).total_seconds() / 60

# WARM categories knos writes.
FILE = "file"
TOPIC = "topic"
PERSON = "person"
SYMBOL = "symbol"

# One record per agent that yielded on one claim: the lock that keeps a
# chatty agent from writing the same stand-down ten times.
STOOD_DOWN = "stood_down"

# One record per agent that forced its way past a claim, so an override is
# something you can look up rather than something that happened once.
OVERRODE = "overrode"


@dataclass(frozen=True)
class Fact:
    """One thing knos learned, with where it came from."""

    text: str
    source: str  # "session", "git", "code", "user"
    where: str  # file:line, session id + date, or commit hash
    when: str  # ISO date
    about: str = ""
    path: str = ""  # repo-relative file this fact concerns, if any

    def as_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "source": self.source,
            "where": self.where,
            "when": self.when,
            "about": self.about,
            "path": self.path,
        }


class Memory:
    """knos's view of one repo's memory."""

    def __init__(self, repo: Path) -> None:
        self.repo = Path(repo).resolve()
        self.db_path = paths.store_for(self.repo)
        self.storage = Storage(str(self.db_path))
        self.client = MemoryClient(self.storage, cap_gate=self._cap_gate())

    def _cap_gate(self) -> Any:
        """The store's own cap check, asked to measure less often.

        Sibyl re-measures the whole database on every single write to keep
        the 5 MB free tier honest. That is 70% of the cost of writing one
        fact, and reading a repo writes hundreds, so it dominated `knos
        point`.

        The size is measured for real whenever the store is anywhere near
        full, and only estimated while it is comfortably below. The cap is
        enforced exactly where it matters and guessed only where guessing
        cannot cross it.
        """
        from sibyl_memory_client import CapGate
        from sibyl_memory_client._capcheck import aggregate_db_size

        measure = lambda: aggregate_db_size(self.storage.db_path)  # noqa: E731
        state = {"size": measure(), "written": 0}
        # Below this, an estimate cannot be wrong enough to matter.
        relaxed = int(FREE_TIER_CAP_BYTES * 0.8)

        def size() -> int:
            if state["size"] + state["written"] >= relaxed:
                state["size"] = measure()
                state["written"] = 0
            return state["size"] + state["written"]

        self._grew = lambda n: state.__setitem__("written", state["written"] + n)
        return CapGate(account_id=None, session_token=None, db_size_fn=size)

    def close(self) -> None:
        self.storage.close()

    def __enter__(self) -> "Memory":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ---- COLD: the journal of what was learned -------------------------

    def record(self, fact: Fact) -> str | None:
        """Append one learned fact to the journal.

        Returns None when the store is full. Sibyl's free store holds 5 MB
        and knos does not ask anyone to activate an account to use it, so a
        full store is a normal thing that happens, not an error. The caller
        stops reading and says so.
        """
        try:
            written = self.client.write_event(
                evaluated=fact.text,
                acted=fact.source,
                extra=fact.as_dict(),
            )
        except CapExceededError:
            return None
        # Roughly what that fact just cost on disk, so the cap gate can tell
        # how close it is getting without re-measuring the whole store.
        self._grew(len(fact.text) * 3 + 512)
        return written

    def _size_bytes(self) -> int:
        with self.storage.connection() as conn:
            return int(self.storage.logical_size_bytes(conn))

    def full(self) -> bool:
        """True when the store has no room for more."""
        return self._size_bytes() >= FREE_TIER_CAP_BYTES

    def size_mb(self) -> float:
        return self._size_bytes() / (1024 * 1024)

    def journal(self, limit: int = 200) -> list[dict[str, Any]]:
        return self.client.read_events(limit=limit)

    def only_here(self) -> int:
        """How many things exist nowhere but this file.

        Everything knos read out of your repo it can read again. These it
        cannot: what somebody told it, what was claimed, who stood down for
        whom, who overrode whom and why. Delete the store and this number is
        what is actually gone — which is the whole question anyone should ask
        of a memory that claims to be load-bearing.
        """
        # The journal row keeps the source in `acted`; `source` is a key
        # inside `extra`, not a column. Reading the wrong one made this
        # count zero on every store, which is worse than not printing it:
        # the README points at this number as the thing not to take on
        # trust.
        told = sum(1 for e in self.journal(limit=5000) if e.get("acted") == "note")
        return told + len(self.claims())

    def written_rules(self, limit: int = 400) -> list[dict[str, Any]]:
        """The instruction files, in the order they were read.

        Asked for by name rather than by search, because "what are the rules
        here?" shares no word with the rule it is asking about.
        """
        return [e for e in self.journal(limit=limit * 4) if e.get("source") == "rules"][
            :limit
        ]

    # ---- WARM: one canonical record per thing --------------------------

    def note_thing(
        self, category: str, name: str, body: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Write the canonical record for one thing.

        Uniqueness is the schema's job: entities carry
        UNIQUE (tenant_id, category, name). This wrapper does not check.

        Returns None when the store is full, like `record`.
        """
        try:
            return self.client.set_entity(category, name, body)
        except CapExceededError:
            return None

    def thing(self, category: str, name: str) -> dict[str, Any] | None:
        try:
            return self.client.get_entity(category, name)
        except Exception:
            return None

    def things(self, category: str | None = None, limit: int = 500) -> list[dict[str, Any]]:
        return self.client.list_entities(category, limit=limit)

    def supersede(self, category: str, name: str, reason: str) -> dict[str, Any]:
        """Move a thing to ARCHIVE."""
        return self.client.archive_entity(category, name, reason)

    def notes(self) -> list[dict[str, Any]]:
        """What has been deliberately remembered, newest first.

        Sessions, commits and code are derived: `knos point` reads them
        again every time, so there is nothing to curate there. These are the
        things a person or an agent chose to write down, which is the part
        a CLAUDE.md would have held.
        """
        found = [
            {
                "about": e.get("name", ""),
                "note": (e.get("body") or {}).get("note", ""),
                "when": (e.get("body") or {}).get("when", ""),
            }
            for e in self.things(TOPIC, limit=1000)
        ]
        return sorted(found, key=lambda n: n["when"], reverse=True)

    def remembered(self, about: str) -> bool:
        """Whether that note is still standing, or has been forgotten."""
        return self.thing(TOPIC, about) is not None

    # ---- HOT: what the current work is about ---------------------------

    def set_focus(self, body: dict[str, Any]) -> None:
        try:
            self.client.set_state(INTERNAL + "focus", body)
        except CapExceededError:
            pass  # bookkeeping is the first thing to go when there is no room

    def focus(self) -> dict[str, Any] | None:
        return self.client.get_state(INTERNAL + "focus")

    def claims(self) -> list[dict[str, Any]]:
        """Every piece of work an agent says it is in the middle of.

        One record per topic, not one for the whole repo. Two agents on
        genuinely separate things can both say so; a third asking about
        either is told about that one only. Each expires on its own.
        """
        live = []
        for key in self._claim_keys():
            state = self.client.get_state(key)
            body = (state or {}).get("body") if state else None
            if not body or not body.get("topic"):
                continue
            if _minutes_since(str(body.get("when", ""))) <= INTENT_HOLDS:
                live.append(body)
        return live

    def _claim_keys(self) -> list[str]:
        """The hot keys holding claims, read straight from the store."""
        prefix = INTERNAL + "working_on"
        try:
            with self.storage.connection() as conn:
                rows = conn.execute(
                    "SELECT document_key FROM state_documents WHERE document_key LIKE ?",
                    (prefix + "%",),
                ).fetchall()
            return [r[0] for r in rows]
        except Exception:
            return []

    def working_on(self, topic: str, who: str, when: str, session: str = "") -> None:
        """Record what is being worked on now, and by which agent.

        This is the HOT tier doing its actual job. It holds one thing, it is
        overwritten rather than appended, and it is the only part of the
        store that is about *now* rather than about what happened. An agent
        that writes something down here is telling every other agent on this
        machine what it is in the middle of.
        """
        try:
            self.client.set_state(
                self._claim_key(topic),
                {"topic": topic, "who": who, "when": when, "session": session},
            )
        except CapExceededError:
            pass

    def _claim_key(self, topic: str) -> str:
        return f"{INTERNAL}working_on:{topic.strip().lower()}"

    def current_work(self) -> dict[str, Any] | None:
        """The most recent live claim, or None.

        Intent goes stale. An agent that said it was rewriting the parser an
        hour ago is not a reason to hesitate now, and a warning that is
        always on is a warning nobody reads. Anything older than
        INTENT_HOLDS is treated as over.
        """
        live = self.claims()
        return max(live, key=lambda c: str(c.get("when", ""))) if live else None

    def done_working(self) -> None:
        """Say the current piece of work is finished.

        The stand-down locks go with it, so the next claim on the same thing
        warns everybody again rather than being silently pre-acknowledged.
        The journal keeps the trace of who yielded; only the locks go.
        """
        for key in self._claim_keys():
            try:
                self.client.set_state(key, {})
            except CapExceededError:
                pass
        for category in (STOOD_DOWN, OVERRODE):
            for e in self.things(category, limit=1000):
                try:
                    self.client.delete_entity(category, e.get("name", ""))
                except Exception:
                    pass

    def stood_down(self, topic: str, who: str, claimed_by: str, when: str) -> bool:
        """Record that one agent backed off because another had the work.

        The second half of the pattern. The first agent writes intent into
        HOT; every other agent that asks about the same thing reads it and
        writes down that it stood down, which is what turns a notice board
        into coordination: afterwards you can see who yielded to whom.

        Written once per agent per claim. A warm record is the lock that
        makes that true, so a chatty agent asking ten times leaves one line
        in the journal rather than ten.
        """
        seen = f"{topic} :: {who} :: {claimed_by}"
        if self.thing(STOOD_DOWN, seen) is not None:
            return False
        if self.note_thing(STOOD_DOWN, seen, {"when": when}) is None:
            return False
        self.record(
            Fact(
                text=f"{who} stood down on {topic}; {claimed_by} had it.",
                source="note",
                where=f"{who} yielded to {claimed_by}, {when[:10]}",
                when=when,
                about=topic,
            )
        )
        return True

    def overrode(self, topic: str, who: str, claimed_by: str, why: str, when: str) -> None:
        """Record that an agent took contested work anyway, and why.

        Standing down is the quiet path. This is the loud one: knos withheld
        what it knew, the agent said it needed it regardless, and that is
        now a permanent line in the journal with a reason attached. An
        override nobody can see would be the same as no rule at all.
        """
        self.note_thing(OVERRODE, f"{topic} :: {who}", {"why": why, "when": when})
        self.record(
            Fact(
                text=f"{who} took {topic} anyway, over {claimed_by}: {why}",
                source="note",
                where=f"{who} overrode {claimed_by}, {when[:10]}",
                when=when,
                about=topic,
            )
        )

    def overridden(self, topic: str, who: str) -> bool:
        """Whether this agent already forced its way past this claim."""
        return self.thing(OVERRODE, f"{topic} :: {who}") is not None

    def overrides(self, limit: int = 50) -> list[dict[str, Any]]:
        """Who took contested work anyway, and why."""
        rows = []
        for e in self.things(OVERRODE, limit=limit):
            topic, _, who = e.get("name", "").partition(" :: ")
            body = e.get("body") or {}
            rows.append(
                {
                    "topic": topic,
                    "who": who,
                    "why": body.get("why", ""),
                    "when": body.get("when", ""),
                }
            )
        return sorted(rows, key=lambda r: r["when"], reverse=True)

    def stand_downs(self, limit: int = 50) -> list[dict[str, Any]]:
        """Who has yielded to whom, most recent first."""
        rows = []
        for e in self.things(STOOD_DOWN, limit=limit):
            topic, _, rest = e.get("name", "").partition(" :: ")
            who, _, claimed_by = rest.partition(" :: ")
            rows.append(
                {
                    "topic": topic,
                    "who": who,
                    "claimed_by": claimed_by,
                    "when": (e.get("body") or {}).get("when", ""),
                }
            )
        return sorted(rows, key=lambda r: r["when"], reverse=True)

    # ---- REFERENCE: facts that do not change ---------------------------

    def set_reference(self, key: str, body: Any) -> None:
        try:
            self.client.set_reference(key, body)
        except CapExceededError:
            pass  # as above

    def reference(self, key: str) -> dict[str, Any] | None:
        return self.client.get_reference(key)

    # ---- search --------------------------------------------------------

    def search(self, query: str, limit: int = 40) -> list[dict[str, Any]]:
        """Search every tier. Returns raw hits; filtering happens above.

        Failures are not swallowed here. Sibyl already sanitises the query,
        so anything that raises is the store itself being broken, and a
        broken store must not look like a repo with nothing in it.
        """
        hits = self.client.search(query, limit=limit)
        return [
            f
            for f in (_flatten(h) for h in hits)
            if not str(f.get("key") or "").startswith(INTERNAL)
        ]

    def tiers(self) -> list[tuple[str, str, str]]:
        """What is in each of Sibyl's five tiers right now.

        Each holds a different shape of thing and behaves differently:
        the journal only ever grows, warm records are replaced in place,
        hot state holds exactly one thing and is overwritten, reference is
        written once when a repo is read, and archive is where forgetting
        puts things. Shown so a person can see the store working rather
        than take it on trust.
        """
        live = self.claims()
        return [
            (
                "journal",
                f"{len(self.journal(limit=1000000))} things learned",
                "appended, never rewritten",
            ),
            (
                "warm",
                f"{len(self.things(limit=1000000))} things named",
                "replaced in place",
            ),
            (
                "hot",
                (
                    f"{len(live)} claimed" if live else "nothing in progress"
                ),
                f"one each, expires after {INTENT_HOLDS} min",
            ),
            ("reference", f"{self.repo.name}", "written once, when read"),
            ("archive", f"{self.forgotten_count()} forgotten", "on knos forget"),
        ]

    def claimed_now(self) -> list[str]:
        """What each agent says it is in the middle of, one per line."""
        return [
            f"{c.get('who')} on {c.get('topic')}"
            for c in sorted(self.claims(), key=lambda c: str(c.get("when", "")))
        ]

    def coordination(self) -> list[str]:
        """Who yielded to whom, and who took contested work anyway."""
        lines = [
            f"{r['who']} stood down for {r['claimed_by']} on {r['topic']}"
            for r in self.stand_downs(limit=5)
        ]
        lines += [
            f"{r['who']} took {r['topic']} anyway: {r['why']}"
            for r in self.overrides(limit=5)
        ]
        return lines

    def forgotten_count(self) -> int:
        """How many notes have been dropped."""
        try:
            with self.storage.connection() as conn:
                row = conn.execute("SELECT COUNT(*) FROM archived_entities").fetchone()
            return int(row[0]) if row else 0
        except Exception:
            return 0

    def counts(self) -> dict[str, int]:
        return {
            "entities": len(self.things(limit=1000000)),
            "journal": len(self.journal(limit=100000)),
        }


def _flatten(hit: dict[str, Any]) -> dict[str, Any]:
    """Lift knos's own fields out of whatever Sibyl wrapped them in."""
    out = dict(hit)
    for _ in range(3):
        moved = False
        for key in ("extra", "body", "payload"):
            raw = out.pop(key, None)
            if isinstance(raw, str):
                try:
                    raw = json.loads(raw)
                except ValueError:
                    raw = None
            if isinstance(raw, dict):
                moved = True
                for k, v in raw.items():
                    out.setdefault(k, v)
        if not moved:
            break
    if not out.get("text"):
        out["text"] = out.get("evaluated") or out.get("snippet") or ""
    if not out.get("about"):
        out["about"] = out.get("key") or ""
    return out
