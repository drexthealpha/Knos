"""Claims: which agent is working on which files, right now.

A claim is a set of repo-relative path globs plus a description, held by one agent (`identity.Agent`). Taking one is a
single `BEGIN IMMEDIATE` transaction that fails when any glob overlaps a live claim held by another agent, so of two
agents reaching for the same files in the same second exactly one wins.

A claim given only as a description ("the retry queue") is resolved to paths from exact file names and exact symbol
names in the code index. If nothing resolves, the claim is advisory: other agents are shown it, and it never blocks an
edit or hides an answer. Text similarity alone never blocks anything.

Claims live in `claims.db` beside the repo's memory store: small, hot, and separate from what was learned, so either
memory backend can sit beside it. A claim lapses on its own (30 minutes unless refreshed), and a released or lapsed
claim is kept as history for `knos board` and `knos worth`.
"""

from __future__ import annotations

import contextlib
import json
import re
import sqlite3
import subprocess
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

from . import paths
from .identity import Agent

HOLDS_MIN = 30

_SCHEMA = """
CREATE TABLE IF NOT EXISTS claims (
  id TEXT PRIMARY KEY, globs TEXT NOT NULL, description TEXT NOT NULL,
  host TEXT NOT NULL, session TEXT NOT NULL DEFAULT '', anchor INTEGER, label TEXT NOT NULL,
  taken_at TEXT NOT NULL, refreshed_at TEXT NOT NULL, holds_min INTEGER NOT NULL,
  advisory INTEGER NOT NULL DEFAULT 0, released_at TEXT, released_by TEXT
);
CREATE INDEX IF NOT EXISTS claims_live ON claims (released_at);
CREATE TABLE IF NOT EXISTS sessions (
  host TEXT NOT NULL, session TEXT NOT NULL, anchor INTEGER, started_at TEXT NOT NULL,
  PRIMARY KEY (host, session)
);
CREATE TABLE IF NOT EXISTS events (
  ts TEXT NOT NULL, kind TEXT NOT NULL, detail TEXT NOT NULL
);
"""


def _prepare(conn: sqlite3.Connection) -> None:
    """WAL and the tables, once per file. Many processes can open a new claims.db in the same instant, and switching
    the journal mode or creating tables takes a lock that the busy timeout does not always wait for, so both are
    retried; a file already set up costs one read."""
    import time as _time

    for attempt in range(40):
        try:
            ready = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='events'").fetchone()
            if conn.execute("PRAGMA journal_mode").fetchone()[0].lower() != "wal":
                conn.execute("PRAGMA journal_mode = WAL")
            if not ready:
                conn.executescript(_SCHEMA)
            return
        except sqlite3.OperationalError as why:
            if "locked" not in str(why) and "busy" not in str(why):
                raise
            _time.sleep(0.02 * (attempt + 1))
    raise sqlite3.OperationalError("claims.db stayed locked")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(t: datetime) -> str:
    return t.isoformat()


def _parse(ts: str) -> datetime:
    try:
        t = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return datetime.fromtimestamp(0, timezone.utc)
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


# ---- globs ----------------------------------------------------------------

_WILD = re.compile(r"[*?\[]")


def norm(path: str) -> str:
    """A repo-relative path or glob in one spelling: forward slashes, no leading ./ or /."""
    p = str(path).replace("\\", "/").strip()
    while p.startswith("./"):
        p = p[2:]
    return p.lstrip("/")


def _glob_re(glob: str) -> re.Pattern:
    """`**` crosses directories, `*` and `?` do not; `dir/` means everything under dir."""
    g = norm(glob)
    if g.endswith("/"):
        g += "**"
    out, i = "", 0
    while i < len(g):
        c = g[i]
        if g.startswith("**/", i):
            out += "(?:.*/)?"
            i += 3
        elif g.startswith("**", i):
            out += ".*"
            i += 2
        elif c == "*":
            out += "[^/]*"
            i += 1
        elif c == "?":
            out += "[^/]"
            i += 1
        else:
            out += re.escape(c)
            i += 1
    return re.compile(out + r"\Z", re.IGNORECASE)


def matches(rel: str, glob: str) -> bool:
    rel, g = norm(rel), norm(glob)
    if not _WILD.search(g) and not g.endswith("/"):
        # a plain path claims that file, or everything under it when it is a directory
        return rel.lower() == g.lower() or rel.lower().startswith(g.lower().rstrip("/") + "/")
    return bool(_glob_re(g).match(rel))


def _literal_prefix(glob: str) -> str:
    g = norm(glob)
    m = _WILD.search(g)
    head = g[: m.start()] if m else g
    return head[: head.rfind("/") + 1] if m else head


def overlap(a: str, b: str) -> bool:
    """Whether two globs could name the same file. Conservative: when unsure, they overlap."""
    a, b = norm(a), norm(b)
    wa, wb = bool(_WILD.search(a)), bool(_WILD.search(b))
    if not wa and not wb:
        return matches(a, b) or matches(b, a)
    if not wa:
        return matches(a, b)
    if not wb:
        return matches(b, a)
    pa, pb = _literal_prefix(a).lower(), _literal_prefix(b).lower()
    return pa.startswith(pb) or pb.startswith(pa)


# ---- resolving a description to paths ---------------------------------------

_PATHISH = re.compile(r"[\w.*?\-/\\\[\]]+")
_IDENT = re.compile(r"^(?:[a-z]+_[a-z0-9_]+|[a-z]+[A-Z]\w*|[A-Z][a-z]+[A-Z]\w*)$")


def _tracked(repo: Path) -> list[str]:
    try:
        out = subprocess.run(["git", "-C", str(repo), "ls-files"], capture_output=True, text=True, timeout=15).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    return [norm(line) for line in out.splitlines() if line.strip()]


def resolve(repo: Path, description: str) -> list[str]:
    """Exact paths, globs, file names and symbol names mentioned in `description`, as repo-relative globs.

    Only exact matches: a file named in full, a path that exists, a glob that matches something, or a symbol whose
    name is exactly a word in the description. Prose words resolve to nothing, on purpose."""
    repo = Path(repo)
    files = _tracked(repo)
    lower = {f.lower(): f for f in files}
    by_name: dict[str, list[str]] = {}
    for f in files:
        by_name.setdefault(f.rsplit("/", 1)[-1].lower(), []).append(f)
    found: list[str] = []

    def add(g: str) -> None:
        if g and g not in found:
            found.append(g)

    for token in _PATHISH.findall(description or ""):
        t = norm(token.strip(".,;:'\"()"))
        if not t or len(t) < 2:
            continue
        if _WILD.search(t):
            if any(matches(f, t) for f in files):
                add(t)
            continue
        if t.lower() in lower:
            add(lower[t.lower()])
            continue
        if "/" in t and any(f.lower().startswith(t.lower().rstrip("/") + "/") for f in files):
            add(t.rstrip("/") + "/**")
            continue
        if "." in t and t.lower() in by_name and len(by_name[t.lower()]) <= 5:
            for f in by_name[t.lower()]:
                add(f)
            continue
        if _IDENT.match(t):
            try:
                from . import code
                symbols, _ = code.search(repo, t, limit=10)
            except Exception:
                symbols = []
            for s in symbols:
                if s.name.lower() == t.lower() and s.path:
                    add(norm(s.path))
    return found


# ---- the store ---------------------------------------------------------------

@dataclass(frozen=True)
class Claim:
    id: str
    globs: tuple[str, ...]
    description: str
    host: str
    session: str
    anchor: int | None
    label: str
    taken_at: str
    refreshed_at: str
    holds_min: int
    advisory: bool

    @property
    def expires(self) -> datetime:
        return _parse(self.refreshed_at) + timedelta(minutes=self.holds_min)

    @property
    def minutes_left(self) -> float:
        return (self.expires - _now()).total_seconds() / 60

    def covers(self, rel: str) -> bool:
        return not self.advisory and any(matches(rel, g) for g in self.globs)

    def held_by(self, agent: Agent) -> bool:
        return agent.owns(self.host, self.session, self.anchor)

    def as_dict(self) -> dict[str, Any]:
        return {"id": self.id, "globs": list(self.globs), "description": self.description, "host": self.host,
                "session": self.session, "anchor": self.anchor, "who": self.label, "since": self.taken_at,
                "refreshed": self.refreshed_at, "minutes_left": round(self.minutes_left, 1), "advisory": self.advisory}


def claims_db(repo: Path) -> Path:
    return paths.work_root(Path(repo).resolve()) / "claims.db"


class Claims:
    """One repo's claim list. Open it as a context manager."""

    def __init__(self, repo: str | Path = ".", db: Path | None = None) -> None:
        """`db` names the file directly. Claims across machines are the team registry on Solana (`knos team`)."""
        self.repo = Path(repo).resolve()
        self.path = Path(db) if db is not None else claims_db(self.repo)
        self._conn: sqlite3.Connection | None = None

    def __enter__(self) -> "Claims":
        conn = sqlite3.connect(str(self.path), timeout=10, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 10000")
        conn.execute("PRAGMA synchronous = NORMAL")
        _prepare(conn)
        self._conn = conn
        return self

    def __exit__(self, *exc: object) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("use Claims as a context manager: with Claims(repo) as c:")
        return self._conn

    @contextlib.contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            yield self.conn
        except BaseException:
            self.conn.execute("ROLLBACK")
            raise
        else:
            self.conn.execute("COMMIT")

    @staticmethod
    def _row(r: sqlite3.Row) -> Claim:
        return Claim(id=r["id"], globs=tuple(json.loads(r["globs"])), description=r["description"], host=r["host"],
                     session=r["session"], anchor=r["anchor"], label=r["label"], taken_at=r["taken_at"],
                     refreshed_at=r["refreshed_at"], holds_min=int(r["holds_min"]), advisory=bool(r["advisory"]))

    def _live_rows(self, conn: sqlite3.Connection) -> list[Claim]:
        rows = [self._row(r) for r in conn.execute("SELECT * FROM claims WHERE released_at IS NULL")]
        return [c for c in rows if c.minutes_left > 0]

    def live(self) -> list[Claim]:
        """Every claim that has not been released or lapsed, oldest first."""
        return sorted(self._live_rows(self.conn), key=lambda c: c.taken_at)

    # -- taking ------------------------------------------------------------------
    def take(self, agent: Agent, description: str, globs: list[str] | None = None,
             holds_min: int = HOLDS_MIN, resolve_names: bool = True) -> tuple[bool, Claim | None, Claim | None]:
        """(taken, conflicting claim or None, your claim or None).

        `globs` given explicitly are used as they are; otherwise they are resolved from the description. The agent's
        own overlapping claim is refreshed rather than duplicated; another agent's overlapping claim refuses it."""
        named = globs if globs else (resolve(self.repo, description) if resolve_names else [])
        wanted = [norm(g) for g in named if norm(g)]
        advisory = not wanted
        now = _iso(_now())
        with self._tx() as conn:
            live = self._live_rows(conn)
            if not advisory:
                for c in live:
                    if c.advisory or c.held_by(agent):
                        continue
                    if any(overlap(a, b) for a in wanted for b in c.globs):
                        return False, c, None
            for c in live:
                if c.held_by(agent) and (set(c.globs) == set(wanted)) and c.description == description:
                    conn.execute("UPDATE claims SET refreshed_at=? WHERE id=?", (now, c.id))
                    fresh = self._row(conn.execute("SELECT * FROM claims WHERE id=?", (c.id,)).fetchone())
                    return True, None, fresh
            cid = uuid.uuid4().hex[:12]
            conn.execute("INSERT INTO claims (id, globs, description, host, session, anchor, label, taken_at, refreshed_at,"
                         " holds_min, advisory) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                         (cid, json.dumps(wanted), description, agent.host, agent.session, agent.anchor, agent.label,
                          now, now, int(holds_min), int(advisory)))
            conn.execute("INSERT INTO events (ts, kind, detail) VALUES (?, 'claim', ?)",
                         (now, json.dumps({"id": cid, "who": agent.label, "globs": wanted, "description": description})))
            mine = self._row(conn.execute("SELECT * FROM claims WHERE id=?", (cid,)).fetchone())
        return True, None, mine

    # -- checking ------------------------------------------------------------------
    def holder(self, rel: str, agent: Agent) -> Claim | None:
        """The live, non-advisory claim held by another agent that covers `rel`, or None."""
        for c in self.live():
            if c.covers(rel) and not c.held_by(agent):
                return c
        return None

    def about(self, text: str) -> list[Claim]:
        """Live claims whose paths or description a question mentions: for annotating answers, never for hiding them."""
        low = (text or "").lower()
        out = []
        for c in self.live():
            if any(g.lower().rstrip("*/") and g.lower().rstrip("*/") in low for g in c.globs) or \
                    any(f.rsplit("/", 1)[-1].lower() in low for f in c.globs if not _WILD.search(f)) or \
                    (c.description and c.description.lower() in low):
                out.append(c)
        return out

    def note_block(self, agent: Agent, rel: str, claim: Claim) -> None:
        try:
            self.conn.execute("INSERT INTO events (ts, kind, detail) VALUES (?, 'blocked', ?)",
                              (_iso(_now()), json.dumps({"path": rel, "by": agent.label, "held_by": claim.label, "claim": claim.id})))
        except sqlite3.Error:
            pass

    def events(self, kind: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        sql, params = "SELECT ts, kind, detail FROM events", []
        if kind:
            sql += " WHERE kind=?"
            params.append(kind)
        sql += " ORDER BY ts DESC LIMIT ?"
        params.append(limit)
        return [dict(ts=r["ts"], kind=r["kind"], **json.loads(r["detail"])) for r in self.conn.execute(sql, params)]

    # -- releasing -------------------------------------------------------------------
    def release(self, agent: Agent, description: str = "", everyone: bool = False) -> list[Claim]:
        """Release the agent's own live claims (or one of them, by description or id). `everyone` releases every live
        claim in the repo, which only a person at a terminal should ask for (the CLI confirms first)."""
        now = _iso(_now())
        gone: list[Claim] = []
        with self._tx() as conn:
            for c in self._live_rows(conn):
                if not everyone and not c.held_by(agent):
                    continue
                if description and description not in (c.description, c.id):
                    continue
                conn.execute("UPDATE claims SET released_at=?, released_by=? WHERE id=?", (now, agent.label, c.id))
                conn.execute("INSERT INTO events (ts, kind, detail) VALUES (?, 'release', ?)",
                             (now, json.dumps({"id": c.id, "who": c.label, "by": agent.label})))
                gone.append(c)
        return gone

    # -- sessions: SessionStart records session id -> host process -----------------------
    def record_session(self, host: str, session: str, anchor: int | None) -> None:
        if not session:
            return
        with self._tx() as conn:
            conn.execute("INSERT INTO sessions (host, session, anchor, started_at) VALUES (?,?,?,?) "
                         "ON CONFLICT(host, session) DO UPDATE SET anchor=excluded.anchor, started_at=excluded.started_at",
                         (host, session, anchor, _iso(_now())))

    def session_for(self, host: str, anchor: int) -> str | None:
        row = self.conn.execute("SELECT session FROM sessions WHERE host=? AND anchor=? ORDER BY started_at DESC LIMIT 1",
                                (host, anchor)).fetchone()
        return row["session"] if row else None

    def agents(self) -> list[dict[str, Any]]:
        """Sessions seen in the last day, newest first: who has been working in this repo."""
        since = _iso(_now() - timedelta(days=1))
        return [dict(r) for r in self.conn.execute(
            "SELECT host, session, anchor, started_at FROM sessions WHERE started_at >= ? ORDER BY started_at DESC", (since,))]


def lookup_session(repo: Path):
    """A `sessions_lookup(host, anchor)` for identity.for_mcp / for_cli, reading this repo's claims.db."""
    def find(host: str, anchor: int) -> str | None:
        if not claims_db(repo).exists():
            return None
        with Claims(repo) as c:
            return c.session_for(host, anchor)
    return find

