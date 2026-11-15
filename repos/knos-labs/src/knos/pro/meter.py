"""What your agents spent, read from the logs they already write. Local only; nothing leaves the machine.

Claude Code: ~/.claude/projects/*/*.jsonl, one line per message part. The same assistant message is logged once per
content block with the same usage, so a message is counted once, keyed by message id + request id.

Codex: ~/.codex/sessions/**/rollout-*.jsonl. `token_count` events carry the running total for the session; the
spend is the sum of the increases of that total, priced at the model the latest `turn_context` names.

Reads are incremental: each file's byte offset is kept in ~/.knos/meter.db, so a second read costs only what was
appended since.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator

from .. import paths
from . import prices

_SCHEMA = """
CREATE TABLE IF NOT EXISTS usage (
    key TEXT PRIMARY KEY, ts TEXT, host TEXT, model TEXT, cwd TEXT,
    inp INTEGER, out INTEGER, cw INTEGER, cw1h INTEGER, cr INTEGER, usd REAL, known INTEGER);
CREATE INDEX IF NOT EXISTS usage_ts ON usage(ts);
CREATE TABLE IF NOT EXISTS files (path TEXT PRIMARY KEY, offset INTEGER, size INTEGER, state TEXT);
CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);
"""


def db_path() -> Path:
    return paths.home() / "meter.db"


def claude_root() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude") / "projects"


def codex_root() -> Path:
    return Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex") / "sessions"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path()), timeout=10, isolation_level=None)
    conn.execute("PRAGMA busy_timeout = 10000")
    conn.executescript(_SCHEMA)
    return conn


def _lines(path: Path, offset: int) -> Iterator[tuple[int, dict]]:
    """(end offset, record) for each complete JSON line after `offset`."""
    with path.open("rb") as fh:
        fh.seek(offset)
        pos = offset
        for raw in fh:
            if not raw.endswith(b"\n"):
                return  # a line still being written: read it next time
            pos += len(raw)
            try:
                rec = json.loads(raw)
            except ValueError:
                continue
            if isinstance(rec, dict):
                yield pos, rec


def _claude_rows(path: Path, offset: int) -> Iterator[tuple[int, tuple]]:
    for pos, rec in _lines(path, offset):
        msg = rec.get("message")
        if rec.get("type") != "assistant" or not isinstance(msg, dict):
            continue
        u = msg.get("usage")
        if not isinstance(u, dict):
            continue
        model = str(msg.get("model") or "")
        if model.startswith("<"):  # '<synthetic>': a local message, never billed
            continue
        key = f"claude:{msg.get('id') or ''}:{rec.get('requestId') or ''}"
        if key == "claude::":
            key = f"claude:{path.name}:{pos}"
        cc = u.get("cache_creation") if isinstance(u.get("cache_creation"), dict) else {}
        cw1h = int(cc.get("ephemeral_1h_input_tokens") or 0)
        cw = int(u.get("cache_creation_input_tokens") or 0) - cw1h
        inp, out, cr = int(u.get("input_tokens") or 0), int(u.get("output_tokens") or 0), \
            int(u.get("cache_read_input_tokens") or 0)
        usd, known = prices.cost(model, inp, out, max(cw, 0), cw1h, cr)
        yield pos, (key, str(rec.get("timestamp") or ""), "claude", model, str(rec.get("cwd") or ""),
                    inp, out, max(cw, 0), cw1h, cr, usd, int(known))


def _codex_rows(path: Path, offset: int, state: dict) -> Iterator[tuple[int, tuple]]:
    for pos, rec in _lines(path, offset):
        payload = rec.get("payload") if isinstance(rec.get("payload"), dict) else {}
        kind = rec.get("type")
        if kind == "session_meta":
            state["cwd"] = str(payload.get("cwd") or state.get("cwd", ""))
        if kind == "turn_context":
            state["model"] = str(payload.get("model") or state.get("model", ""))
            state["cwd"] = str(payload.get("cwd") or state.get("cwd", ""))
            continue
        if kind != "event_msg" or payload.get("type") != "token_count":
            continue
        total = ((payload.get("info") or {}).get("total_token_usage")) or {}
        if not isinstance(total, dict):
            continue
        now = {k: int(total.get(k) or 0) for k in ("input_tokens", "cached_input_tokens", "output_tokens")}
        last = state.get("total") or {"input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0}
        if sum(now.values()) < sum(int(v) for v in last.values()):
            last = {}  # the total went backwards: a new count started from zero
        d = {k: max(now[k] - int(last.get(k, 0)), 0) for k in now}
        state["total"] = now
        if not any(d.values()):
            continue  # the same total logged again
        cached = d["cached_input_tokens"]
        inp = max(d["input_tokens"] - cached, 0)
        model = state.get("model", "")
        usd, known = prices.cost(model, inp, d["output_tokens"], 0, 0, cached)
        yield pos, (f"codex:{path.name}:{pos}", str(rec.get("timestamp") or ""), "codex", model,
                    state.get("cwd", ""), inp, d["output_tokens"], 0, 0, cached, usd, int(known))


def _files() -> list[tuple[str, Path]]:
    found: list[tuple[str, Path]] = []
    root = claude_root()
    if root.is_dir():
        found += [("claude", p) for p in root.glob("*/*.jsonl")]
        found += [("claude", p) for p in root.glob("*/*/subagents/*.jsonl")]
    croot = codex_root()
    if croot.is_dir():
        found += [("codex", p) for p in croot.rglob("rollout-*.jsonl")]
    return found


def update(min_interval: float = 0.0) -> int:
    """Read what was appended since last time. Returns how many new usage rows were stored."""
    added = 0
    conn = _connect()
    try:
        if min_interval:
            row = conn.execute("SELECT v FROM meta WHERE k='updated'").fetchone()
            if row and time.time() - float(row[0]) < min_interval:
                return 0
        known = {r[0]: (int(r[1]), int(r[2]), r[3]) for r in conn.execute("SELECT path, offset, size, state FROM files")}
        for host, path in _files():
            try:
                size = path.stat().st_size
            except OSError:
                continue
            offset, seen_size, raw_state = known.get(str(path), (0, 0, None))
            if size == seen_size:
                continue
            if size < offset:  # rewritten: start again (keys make repeats harmless)
                offset, raw_state = 0, None
            state = json.loads(raw_state) if raw_state else {}
            rows = _claude_rows(path, offset) if host == "claude" else _codex_rows(path, offset, state)
            end = offset
            batch = []
            try:
                for end, row in rows:
                    batch.append(row)
            except OSError:
                continue
            conn.execute("BEGIN")
            before = conn.total_changes
            conn.executemany("INSERT OR IGNORE INTO usage VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", batch)
            added += conn.total_changes - before
            conn.execute("INSERT INTO files VALUES (?,?,?,?) ON CONFLICT(path) DO UPDATE SET offset=excluded.offset,"
                         " size=excluded.size, state=excluded.state", (str(path), end, size, json.dumps(state)))
            conn.execute("COMMIT")
        conn.execute("INSERT INTO meta VALUES ('updated', ?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
                      (str(time.time()),))
    finally:
        conn.close()
    return added


def period_start(per: str, now: datetime | None = None) -> datetime:
    """The start of the current day / week (Monday) / month, local time, as UTC."""
    local = (now or datetime.now(timezone.utc)).astimezone()
    start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    if per == "week":
        start -= timedelta(days=start.weekday())
    elif per == "month":
        start = start.replace(day=1)
    return start.astimezone(timezone.utc)


def spent(since: datetime, host: str | None = None, repo: str | None = None) -> dict:
    """Totals since a moment: usd, tokens, whether any model was unpriced, and a per-model / per-host breakdown.
    `repo` keeps only sessions whose working directory is that folder or inside it."""
    conn = _connect()
    try:
        sql = ("SELECT host, model, SUM(usd), SUM(inp+out+cw+cw1h+cr), MIN(known), COUNT(*) FROM usage "
               "WHERE ts >= ?")
        params: list = [since.strftime("%Y-%m-%dT%H:%M:%S")]
        if host:
            sql += " AND host = ?"
            params.append(host)
        if repo:
            root = str(repo).rstrip("/\\")
            sql += " AND (cwd = ? OR cwd LIKE ? OR cwd LIKE ?)"
            params += [root, root + "/%", root + "\\%"]
        rows = conn.execute(sql + " GROUP BY host, model ORDER BY SUM(usd) DESC", params).fetchall()
    finally:
        conn.close()
    return {"usd": sum(r[2] or 0 for r in rows), "tokens": sum(r[3] or 0 for r in rows),
            "estimated": any(r[4] == 0 for r in rows),
            "by": [{"host": r[0], "model": r[1] or "(unknown)", "usd": r[2] or 0.0, "tokens": r[3] or 0,
                    "messages": r[5]} for r in rows]}


def by_day(days: int = 7) -> list[tuple[str, float]]:
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")
    conn = _connect()
    try:
        return [(r[0], r[1] or 0.0) for r in conn.execute(
            "SELECT substr(ts,1,10), SUM(usd) FROM usage WHERE ts >= ? GROUP BY 1 ORDER BY 1", (since,))]
    finally:
        conn.close()
