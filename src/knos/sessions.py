"""Read what coding agents already learned and then forgot.

The decision lives in a session that is gone when it ends. This is the
highest-value source knos has, and the reason the product exists.

Two clients are read: Claude Code (JSONL transcripts) and Cursor (a SQLite
key-value store). Both are read-only and both are read on demand, when a
person runs a command. Nothing watches, nothing polls.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator
from urllib.parse import urlparse
from urllib.request import url2pathname

# A turn worth remembering is a person's or an agent's prose, not a tool call.
MIN_CHARS = 25
MAX_CHARS = 4000


@dataclass(frozen=True)
class Turn:
    """One thing said in one agent session."""

    client: str  # "Claude Code" | "Cursor"
    session: str
    role: str  # "user" | "agent"
    text: str
    when: str  # ISO date, "" when the client records none
    cwd: str = ""

    @property
    def where(self) -> str:
        stamp = self.when[:10] if self.when else "undated"
        return f"{self.client} session {self.session[:8]} {stamp}"


# ---- Claude Code ------------------------------------------------------


def claude_root() -> Path:
    override = os.environ.get("KNOS_CLAUDE_HOME")
    return Path(override) if override else Path.home() / ".claude" / "projects"


def _text_of(content: object) -> str:
    """Claude Code content is a string or a list of typed blocks."""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
        return "\n".join(parts).strip()
    return ""


def read_claude(repo: Path | None = None) -> Iterator[Turn]:
    root = claude_root()
    if not root.exists():
        return
    want = str(Path(repo).resolve()).lower() if repo else None
    for f in sorted(root.rglob("*.jsonl")):
        try:
            handle = f.open(encoding="utf-8", errors="replace")
        except OSError:
            continue  # corrupt or locked: skip it, keep going
        with handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if rec.get("type") not in ("user", "assistant"):
                    continue
                if rec.get("isSidechain") or rec.get("isMeta"):
                    continue
                msg = rec.get("message")
                if not isinstance(msg, dict):
                    continue
                text = _text_of(msg.get("content"))
                if not MIN_CHARS <= len(text) <= MAX_CHARS:
                    continue
                cwd = str(rec.get("cwd") or "")
                if want and cwd and not cwd.lower().startswith(want):
                    continue
                yield Turn(
                    client="Claude Code",
                    session=str(rec.get("sessionId") or f.stem),
                    role="user" if rec["type"] == "user" else "agent",
                    text=text,
                    when=str(rec.get("timestamp") or ""),
                    cwd=cwd,
                )


# ---- Cursor -----------------------------------------------------------


def cursor_db() -> Path:
    override = os.environ.get("KNOS_CURSOR_DB")
    if override:
        return Path(override)
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming"))
        return base / "Cursor/User/globalStorage/state.vscdb"
    if os.uname().sysname == "Darwin":  # type: ignore[attr-defined]
        return Path.home() / "Library/Application Support/Cursor/User/globalStorage/state.vscdb"
    return Path.home() / ".config/Cursor/User/globalStorage/state.vscdb"


def workspace_store() -> Path:
    """Where Cursor records which folder each window had open."""
    override = os.environ.get("KNOS_CURSOR_WORKSPACES")
    if override:
        return Path(override)
    return cursor_db().parent.parent / "workspaceStorage"


def _folders_by_workspace() -> dict[str, Path]:
    """Workspace id to the folder that window had open.

    Cursor keeps one directory per workspace, each holding a
    `workspace.json` naming the folder as a file:// URI. A window opened
    with no folder has no entry, and its conversations therefore belong to
    no repo.
    """
    out: dict[str, Path] = {}
    root = workspace_store()
    if not root.is_dir():
        return out
    for d in root.iterdir():
        f = d / "workspace.json"
        if not f.is_file():
            continue
        try:
            uri = str(json.loads(f.read_text(encoding="utf-8")).get("folder") or "")
        except (ValueError, OSError):
            continue
        if not uri.startswith("file:"):
            continue
        path = url2pathname(urlparse(uri).path)
        out[d.name] = Path(path)
    return out


def _folders_by_composer(conn: sqlite3.Connection) -> dict[str, Path]:
    """Which folder each conversation happened in, where that is knowable."""
    workspaces = _folders_by_workspace()
    if not workspaces:
        return {}
    out: dict[str, Path] = {}
    try:
        rows = conn.execute(
            "SELECT key, value FROM cursorDiskKV WHERE key LIKE 'composerData:%'"
        )
    except sqlite3.Error:
        return {}
    for key, value in rows:
        try:
            rec = json.loads(value)
        except (ValueError, TypeError):
            continue
        marker = rec.get("workspaceIdentifier")
        name = marker.get("id") if isinstance(marker, dict) else None
        folder = workspaces.get(str(name)) if name else None
        if folder is not None:
            out[key.split(":", 1)[1]] = folder
    return out


def read_cursor(repo: Path | None = None) -> Iterator[Turn]:
    """Cursor stores turns as `bubbleId:<composer>:<bubble>` rows.

    Type 1 is the person, type 2 is the agent. The live file is copied first
    so an open Cursor window is never disturbed.

    A conversation counts only when Cursor had a folder open and that folder
    is the repo being read. Cursor keeps every window's history in one file
    with no path on the turns themselves, so a conversation whose folder
    cannot be established belongs to no repo and is skipped: putting it in
    every repo would mean answering a question about one project with a
    conversation about another.
    """
    src = cursor_db()
    if not src.exists():
        return
    tmp = Path(tempfile.mkdtemp(prefix="knos-cursor-")) / "state.vscdb"
    try:
        shutil.copy(src, tmp)
    except OSError:
        return
    try:
        conn = sqlite3.connect(f"file:{tmp}?mode=ro", uri=True)
    except sqlite3.Error:
        return
    when = datetime.fromtimestamp(src.stat().st_mtime, tz=timezone.utc).isoformat()
    want = Path(repo).resolve() if repo else None
    try:
        folders = _folders_by_composer(conn)
        rows = conn.execute(
            "SELECT key, value FROM cursorDiskKV WHERE key LIKE 'bubbleId:%'"
        )
        for key, value in rows:
            parts = key.split(":")
            composer = parts[1] if len(parts) > 2 else key
            folder = folders.get(composer)
            if folder is None:
                continue  # no folder, so no repo it can be said to belong to
            if want is not None and not _within(folder, want):
                continue
            try:
                rec = json.loads(value)
            except (ValueError, TypeError):
                continue
            text = str(rec.get("text") or "").strip()
            if not MIN_CHARS <= len(text) <= MAX_CHARS:
                continue
            yield Turn(
                client="Cursor",
                session=composer,
                role="user" if rec.get("type") == 1 else "agent",
                text=text,
                when=when,
                cwd=str(folder),
            )
    except sqlite3.Error:
        return
    finally:
        conn.close()
        shutil.rmtree(tmp.parent, ignore_errors=True)


def _within(folder: Path, repo: Path) -> bool:
    try:
        folder = folder.resolve()
    except OSError:
        return False
    return folder == repo or repo in folder.parents or folder in repo.parents


# ---- both -------------------------------------------------------------


def read_all(repo: Path | None = None) -> list[Turn]:
    """Every turn from every supported client. Read on demand only."""
    turns = list(read_claude(repo)) + list(read_cursor(repo))
    turns.sort(key=lambda t: t.when)
    return turns


def clients_found() -> dict[str, bool]:
    return {
        "Claude Code": claude_root().exists(),
        "Cursor": cursor_db().exists(),
    }
