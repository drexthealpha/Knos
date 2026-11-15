"""Keeping a repo's memory current without ever deleting it.

knos 0.1 caught up by deleting the store and reading everything again, which threw away everything that exists
nowhere else: notes, claims history, what agents wrote down. Now reading is incremental:

  - every fact is recorded once. `read.db`, beside the store, keeps a key per fact already read (source, location and
    text), so reading twice is the same as reading once;
  - Claude Code transcripts are read from the byte where the last read stopped (they only grow);
  - a read happens when something changed: HEAD moved, a transcript grew, or Cursor's database was saved. That is
    checked when the MCP server answers or a CLI command reads the repo, at most every CHECK_EVERY seconds per process.

Starting over is a separate, explicit `knos reset --yes`, which exports a backup first.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
import time
from pathlib import Path

from . import paths

CHECK_EVERY = 30.0
PARTIAL = "knos:internal:partial-read"  # reference key: was the last read cut short by its time budget?
_last_check: dict[str, float] = {}

_SCHEMA = """
PRAGMA journal_mode = WAL;
CREATE TABLE IF NOT EXISTS seen (key TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS offsets (file TEXT PRIMARY KEY, bytes INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS state (k TEXT PRIMARY KEY, v TEXT NOT NULL);
"""


def read_db(repo: Path) -> Path:
    return paths.work_root(Path(repo).resolve()) / "read.db"


class ReadLog:
    """What has been read from a repo already: fact keys, transcript offsets, and the last signature."""

    def __init__(self, repo: Path) -> None:
        self.conn = sqlite3.connect(str(read_db(repo)), timeout=10, isolation_level=None)
        self.conn.execute("PRAGMA busy_timeout = 10000")
        self.conn.executescript(_SCHEMA)
        self._pending: list[str] = []

    def __enter__(self) -> "ReadLog":
        return self

    def __exit__(self, *exc: object) -> None:
        self.flush()
        self.conn.close()

    @staticmethod
    def key(source: str, where: str, text: str) -> str:
        return hashlib.sha1(f"{source}\x1f{where}\x1f{' '.join(text.split())[:400]}".encode("utf-8", "replace")).hexdigest()

    def has(self, key: str) -> bool:
        return key in self._pending or self.conn.execute("SELECT 1 FROM seen WHERE key=?", (key,)).fetchone() is not None

    def add(self, key: str) -> None:
        self._pending.append(key)
        if len(self._pending) >= 200:
            self.flush()

    def flush(self) -> None:
        if self._pending:
            self.conn.execute("BEGIN")
            self.conn.executemany("INSERT OR IGNORE INTO seen (key) VALUES (?)", [(k,) for k in self._pending])
            self.conn.execute("COMMIT")
            self._pending = []

    def offsets(self) -> dict[str, int]:
        return {f: int(b) for f, b in self.conn.execute("SELECT file, bytes FROM offsets")}

    def save_offsets(self, offsets: dict[str, int]) -> None:
        self.conn.execute("BEGIN")
        self.conn.executemany("INSERT INTO offsets (file, bytes) VALUES (?, ?) ON CONFLICT(file) DO UPDATE SET bytes=excluded.bytes",
                              list(offsets.items()))
        self.conn.execute("COMMIT")

    def get(self, k: str) -> str | None:
        row = self.conn.execute("SELECT v FROM state WHERE k=?", (k,)).fetchone()
        return row[0] if row else None

    def put(self, k: str, v: str) -> None:
        self.conn.execute("INSERT INTO state (k, v) VALUES (?, ?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, v))


def signature(repo: Path) -> str:
    """What would have to change for there to be anything new to read: HEAD, transcript sizes, Cursor's database."""
    from . import sessions

    parts: list[str] = []
    try:
        head = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=10)
        parts.append(head.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        parts.append("")
    root = sessions.claude_root()
    if root.exists():
        try:
            files = sessions._transcripts(root, Path(repo))
            parts.append(str(sum(f.stat().st_size for f in files)) + ":" + str(len(files)))
        except OSError:
            parts.append("?")
    codex = sessions.codex_root()
    if codex.is_dir():
        try:
            rolls = list(codex.rglob("rollout-*.jsonl"))
            parts.append("codex:" + str(sum(f.stat().st_size for f in rolls)) + ":" + str(len(rolls)))
        except OSError:
            parts.append("codex:?")
    db = sessions.cursor_db()
    try:
        parts.append(str(int(db.stat().st_mtime)) if db.exists() else "")
    except OSError:
        parts.append("")
    return json.dumps(parts)


def ensure(repo: Path, *, budget: float | None = None, force: bool = False, index_code: bool | None = None,
           on_progress=None) -> dict | None:
    """Read what is new in `repo`, if anything is. Returns the counts when it read, None when nothing changed.
    Never deletes. The first read of a repo also reads its code structure (inside `budget`)."""
    from . import answer, code
    from .memory import Memory

    repo = Path(repo).resolve()
    key = str(repo)
    now = time.monotonic()
    if not force and key in _last_check and now - _last_check[key] < CHECK_EVERY:
        return None
    _last_check[key] = now
    first = not paths.has_store(repo)
    with ReadLog(repo) as log:
        sig = signature(repo)
        if not force and not first and log.get("signature") == sig:
            return None
        offsets = log.offsets()
        with Memory(repo) as mem:
            counts = answer.point(repo, mem, seen=log, offsets=offsets, budget=budget,
                                  index_code=first if index_code is None else index_code,
                                  code_budget=code.CODE_BUDGET if first else None, on_progress=on_progress)
            # An answer after a cut-off read says the repo is only partly read, until a later read finishes it.
            mem.set_reference(PARTIAL, {"partial": bool(counts.get("ran_out")), "sessions": counts.get("sessions", 0),
                                        "commits": counts.get("commits", 0)})
        log.flush()
        # offsets move only after a complete read: a read cut short (budget, or a full capped store) must not skip
        # the turns it never got to; the de-duplication keys make reading them again harmless
        if not counts.get("ran_out") and not counts.get("full"):
            log.save_offsets(offsets)
            log.put("signature", sig)
    return counts


def reset(repo: Path) -> Path | None:
    """Start over on purpose: copy the store to ~/.knos/backups/<repo>-<time>.db, then remove the store, its marker
    and the read log. Returns the backup path (None when there was no store)."""
    repo = Path(repo).resolve()
    store = paths.store_for(repo)
    backup = None
    if store.exists():
        dest = paths.home() / "backups"
        dest.mkdir(parents=True, exist_ok=True)
        backup = dest / f"{repo.name}-{time.strftime('%Y%m%dT%H%M%S')}{store.suffix}"
        src = sqlite3.connect(str(store))
        try:
            out = sqlite3.connect(str(backup))
            with out:
                src.backup(out)
            out.close()
        finally:
            src.close()
    if store.exists():  # the store is shared: only this repo's tenant goes
        from .memory import _open, drop_tenant
        st = _open(store)
        try:
            drop_tenant(st, paths.tenant_for(repo))
        finally:
            st.close()
    legacy = paths.legacy_store_for(repo)
    for p in (legacy, Path(str(legacy) + "-wal"), Path(str(legacy) + "-shm"), Path(str(legacy) + ".born"),
              paths.born_for(repo), read_db(repo), Path(str(read_db(repo)) + "-wal"),
              Path(str(read_db(repo)) + "-shm")):
        try:
            p.unlink()
        except FileNotFoundError:
            pass
    _last_check.pop(str(repo), None)
    return backup
