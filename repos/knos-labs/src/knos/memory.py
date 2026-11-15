"""Durable memory, one Sibyl store per repo, on this machine only.

Every answer knos gives comes out of Sibyl's memory engine (sibyl-memory-client). Sibyl's free tier caps the stores
an agent on this machine writes to at 5 MB together; knos does not patch or route around that cap. It keeps what can
be rebuilt out of the store (the code-structure index is a tags file beside it), warns at 80%, and names the two ways
on: `knos compact`, or Knos Pro, which includes Sibyl Pro (`knos pro buy`). A Sibyl account already on this machine
(~/.sibyl-memory/credentials.json) is passed to Sibyl's own cap gate, so paying Sibyl users are not capped.

    WARM entities    one canonical record per thing (schema-unique)
    COLD journal     what was learned, when, from which source
    HOT state        what the current work is about
    REFERENCE        facts that do not change
    ARCHIVE          superseded

No extraction model, no scoring, no pressure. Facts come from sessions, git and code structure, stated as found.
"""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import paths

from sibyl_memory_client import FREE_TIER_CAP_BYTES, CapExceededError, Storage

# Warn when a capped store is this full, with the exact choices.
WARN_AT = 0.8

# knos keeps its own bookkeeping in the same store as the facts. Internal
# keys carry this prefix so an answer never quotes knos's plumbing back at
# the person who asked.
INTERNAL = "knos:"

_OPEN_TRIES = 8  # attempts to open a store two agents reached at once
_OPEN_BACKOFF = 0.05  # seconds, multiplied by the attempt number


class StoreGone(Exception):
    """This repo had a memory here and its store file is gone.

    Refused rather than replaced. An empty store opened in its place would
    answer every question with "nothing is known", which an agent reads as a
    fact about the repo, not about a missing file. The marker next to the
    store holds no data; it only records that a store was born here. `knos
    reset --yes` starts over on purpose (and keeps a backup).
    """


def sibyl_account() -> dict[str, str]:
    """The Sibyl account on this machine, if its owner activated one (`sibyl init`): account_id and session_token,
    handed only to Sibyl's own cap gate. Empty when there is none."""
    import os

    path = Path(os.environ.get("SIBYL_CREDENTIALS") or Path.home() / ".sibyl-memory" / "credentials.json")
    try:
        got = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(got, dict) or not got.get("account_id") or not got.get("session_token"):
        return {}
    return {"account_id": str(got["account_id"]), "session_token": str(got["session_token"])}


# WARM categories knos writes.
FILE = "file"
TOPIC = "topic"
PERSON = "person"
SYMBOL = "symbol"

# One record per rule its own file stopped carrying. Written when a read finds
# the citation no longer holds, not when the file changes: knos does not watch
# the filesystem, it checks the receipt at the moment it would show it.
WITHDRAWN = "rule_withdrawn"


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


def _open(db_path: Path) -> Storage:
    """Open the store, waiting if another agent got there in the same moment.

    The first connection to a new store switches it to WAL, and that pragma
    needs the database briefly to itself. `busy_timeout` does not cover it,
    so two agents starting together on a repo neither has read yet can have
    one of them raise `database is locked` instead of waiting - which is the
    exact case knos exists for.

    Waiting is right here: the store is about to exist, the other process is
    the reason it does not yet, and the whole delay is milliseconds.
    """
    from sibyl_memory_client import Storage

    for attempt in range(_OPEN_TRIES):
        try:
            return Storage(str(db_path))
        except sqlite3.OperationalError:
            if attempt == _OPEN_TRIES - 1:
                raise
            time.sleep(_OPEN_BACKOFF * (attempt + 1))
    raise AssertionError("unreachable")


class Memory:
    """knos's view of one repo's memory."""

    def __init__(self, repo: Path) -> None:
        self.repo = Path(repo).resolve()
        self.db_path = paths.store_for(self.repo)
        self.tenant = paths.tenant_for(self.repo)
        born = paths.born_for(self.repo)
        legacy = paths.legacy_store_for(self.repo)
        if not self.db_path.exists() and born.exists() and not legacy.exists():
            raise StoreGone(
                f"knos's memory of {self.repo.name} is gone ({self.db_path} was "
                "deleted). knos will not answer from an empty store as if "
                "nothing were known. To start over on purpose: knos reset --yes"
            )
        from sibyl_memory_client import MemoryClient

        self.storage = _open(self.db_path)
        if legacy.exists():
            migrate_legacy(self.storage, legacy, self.tenant)
        self.client = MemoryClient(self.storage, tenant_id=self.tenant, cap_gate=self._cap_gate())
        if not born.exists():
            born.write_text(
                "a knos store was created here; if it goes missing, knos "
                "refuses rather than start an empty one\n",
                encoding="utf-8",
            )

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
        state = {"size": measure(), "written": 0, "writes": 0}
        # Below this, an estimate cannot be wrong enough to matter.
        relaxed = int(FREE_TIER_CAP_BYTES * 0.8)

        def size() -> int:
            # The per-fact estimate can undercount what a write really costs (the row plus its full-text index
            # entries). So the real size is also measured every 64 writes or 256 KB of estimated growth: an
            # estimate never drifts far enough from the truth to carry the store past the cap unmeasured.
            if (state["size"] + state["written"] >= relaxed or state["writes"] >= 64
                    or state["written"] >= 256 * 1024):
                state["size"] = measure()
                state["written"] = 0
                state["writes"] = 0
            return state["size"] + state["written"]

        def grew(n: int) -> None:
            state["written"] += n
            state["writes"] += 1

        self._grew = grew
        account = sibyl_account()
        return CapGate(account_id=account.get("account_id"), session_token=account.get("session_token"),
                       db_size_fn=size)

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
        body = fact.as_dict()

        try:
            written = self.client.write_event(
                evaluated=fact.text,
                acted=fact.source,
                extra=body,
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

    @property
    def capped(self) -> bool:
        """Whether Sibyl's free-tier cap applies: no Sibyl account on this machine."""
        return not sibyl_account()

    def footprint(self) -> int:
        """What Sibyl's cap counts: this store plus the other Sibyl stores on the machine."""
        from sibyl_memory_client._capcheck import aggregate_db_size

        try:
            return int(aggregate_db_size(self.storage.db_path))
        except Exception:
            return self._size_bytes()

    def full(self) -> bool:
        """True when the store has no room for more."""
        return self.capped and self.footprint() >= FREE_TIER_CAP_BYTES

    def near_full(self) -> bool:
        """At or past 80% of the free tier: the moment to show the choices, before anything is refused."""
        return self.capped and self.footprint() >= WARN_AT * FREE_TIER_CAP_BYTES

    def size_mb(self) -> float:
        return self._size_bytes() / (1024 * 1024)

    def journal(self, limit: int = 200) -> list[dict[str, Any]]:
        return self.client.read_events(limit=limit)

    def only_here(self) -> int:
        """How many things exist nowhere but this file.

        Everything knos read out of your repo it can read again. These it
        cannot: what somebody told it. Delete the store and this number is
        what is actually gone — which is the whole question anyone should ask
        of a memory that claims to be load-bearing.
        """
        # The journal row keeps the source in `acted`; `source` is a key
        # inside `extra`, not a column. Reading the wrong one made this
        # count zero on every store, which is worse than not printing it.
        told = sum(1 for e in self.journal(limit=5000) if e.get("acted") == "note")
        return told

    def written_rules(self, limit: int = 400) -> list[dict[str, Any]]:
        """The instruction files, in the order they were read.

        Asked for by name rather than by search, because "what are the rules
        here?" shares no word with the rule it is asking about.

        Flattened, and that is not a detail: a journal row keeps knos's own
        fields inside `extra`, so filtering on a bare `source` matched nothing
        and this returned an empty list on every store that has ever existed.
        The by-name path was dead and the question it exists for was being
        answered only by whatever the search terms happened to hit. The same
        trap is recorded two methods up, in `only_here`.
        """
        rows = (_flatten(e) for e in self.journal(limit=limit * 4))
        return [e for e in rows if e.get("source") == "rules"][:limit]

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

    # Claims live in claims.db (claims.py): path globs held by one agent identity, taken in one transaction.

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
        """What is in each tier right now, so a person can see the store working rather than take it on trust."""
        from .claims import Claims, claims_db

        live = 0
        if claims_db(self.repo).exists():
            with Claims(self.repo) as c:
                live = len(c.live())
        return [
            ("journal", f"{len(self.journal(limit=1000000))} things learned", "appended, never rewritten"),
            ("warm", f"{len(self.things(limit=1000000))} things named", "replaced in place"),
            ("claims", f"{live} claimed" if live else "nothing claimed", "file claims, each lapsing on its own"),
            ("reference", f"{self.repo.name}", "written once, when read"),
            ("archive", f"{self.forgotten_count()} forgotten", "on knos forget"),
        ]

    def forgotten_count(self) -> int:
        """How many notes have been dropped."""
        try:
            with self.storage.connection() as conn:
                row = conn.execute("SELECT COUNT(*) FROM archived_entities WHERE tenant_id = ?",
                                   (self.tenant,)).fetchone()
            return int(row[0]) if row else 0
        except Exception:
            return 0

    def compact(self, older_than_days: int = 30) -> dict[str, int]:
        """Make room without losing anything an answer uses.

        Drops notes superseded (`knos forget`) more than `older_than_days` ago: they sit in the archive tier, which no
        search reads. Counts journal entries recorded twice but does not delete them: Sibyl's journal is append-only
        and its search index has no delete path, so removing rows would leave the index pointing at nothing. Then
        vacuums, which is what returns freed pages to the disk and to the cap."""
        from datetime import datetime, timedelta, timezone

        before = self.footprint()
        cutoff = (datetime.now(timezone.utc) - timedelta(days=older_than_days)).strftime("%Y-%m-%dT%H:%M:%S")
        with self.storage.transaction() as conn:
            dropped = conn.execute("DELETE FROM archived_entities WHERE tenant_id = ? AND archived_at < ?",
                                   (self.tenant, cutoff)).rowcount
        with self.storage.connection() as conn:
            twice = conn.execute(
                "SELECT COALESCE(SUM(n - 1), 0) FROM (SELECT COUNT(*) AS n FROM journal_events WHERE tenant_id = ? "
                "GROUP BY evaluated, acted, extra HAVING n > 1)", (self.tenant,)).fetchone()[0]
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            conn.execute("VACUUM")
        return {"dropped": int(dropped or 0), "duplicates": int(twice or 0), "before": before,
                "after": self.footprint()}


_TENANT_TABLES = ("entities", "entity_relations", "state_documents", "journal_events", "revenue_events",
                  "error_events", "reference_documents", "archived_entities", "flagged_actors", "skill_proposals",
                  "learning_runs")


def migrate_legacy(storage: Storage, legacy: Path, tenant: str) -> int:
    """Move a 0.1-0.2 per-repo store into the shared store as this repo's tenant, once.

    Those stores sat outside Sibyl's account-wide cap. The rows are copied as they are (same ids, same text, the
    search index rebuilt by Sibyl's own triggers) and the old file is renamed `memory.db.migrated`, never deleted.
    Returns the bytes moved, so the caller can say what now counts toward Sibyl's free 5 MB."""
    size = legacy.stat().st_size
    with storage.connection() as conn:
        conn.execute("ATTACH DATABASE ? AS old", (str(legacy),))
        try:
            conn.execute("BEGIN IMMEDIATE")
            old_tables = {r[0] for r in conn.execute("SELECT name FROM old.sqlite_master WHERE type='table'")}
            for table in _TENANT_TABLES:
                if table not in old_tables:
                    continue
                cols = [r[1] for r in conn.execute(f"PRAGMA old.table_info({table})")]
                here = {r[1] for r in conn.execute(f"PRAGMA main.table_info({table})")}
                cols = [c for c in cols if c in here]
                pick = ", ".join("?" if c == "tenant_id" else c for c in cols)
                conn.execute(f"INSERT OR IGNORE INTO main.{table} ({', '.join(cols)}) SELECT {pick} FROM old.{table}",
                             (tenant,))
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        finally:
            conn.execute("DETACH DATABASE old")
    for suffix in ("", "-wal", "-shm"):
        p = Path(str(legacy) + suffix)
        if p.exists():
            p.replace(Path(str(legacy) + ".migrated" + suffix))
    return size


def drop_tenant(storage: Storage, tenant: str) -> None:
    """Remove one repo's rows from the shared store (knos reset); other repos and Sibyl's own tenants untouched."""
    try:
        from sibyl_memory_client.shadow import SHADOW_TABLE
    except ImportError:
        SHADOW_TABLE = ""
    with storage.transaction() as conn:
        for table in _TENANT_TABLES:
            try:
                conn.execute(f"DELETE FROM {table} WHERE tenant_id = ?", (tenant,))
            except sqlite3.OperationalError:
                continue
        # The journal's search index and search shadow are append-only (insert triggers only): clear them for this
        # tenant too, or the next journal row would collide with an index entry left behind.
        for index in ("journal_events_fts", SHADOW_TABLE):
            if not index:
                continue
            try:
                conn.execute(f"DELETE FROM {index} WHERE tenant_id = ?", (tenant,))
            except sqlite3.OperationalError:
                continue


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
