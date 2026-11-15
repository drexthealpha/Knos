"""Read what coding agents already learned and then forgot.

The decision lives in a session that is gone when it ends. This is the
highest-value source knos has, and the reason the product exists.

Three clients are read: Claude Code (JSONL transcripts), Codex (rollout JSONL)
and Cursor (a SQLite key-value store). Both are read-only and both are read on demand, when a
person runs a command. Nothing watches, nothing polls.
"""

from __future__ import annotations

import json
import os
import re
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

    client: str  # "Claude Code" | "Codex" | "Cursor"
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


def _encoded(path: Path) -> str:
    """A path the way Claude Code names the folder it keeps it under.

    Every character that is not a letter or a digit becomes a dash: `C:\\Users\\me\\my_app.v2` is
    `C--Users-me-my-app-v2` (separators, the drive colon, `.`, `_`, `-` and spaces alike; see
    anthropics/claude-code#35162). The encoding is lossy, which is why the per-line `cwd` check still decides.
    """
    return re.sub(r"[^A-Za-z0-9]", "-", str(path))


def _encoded_legacy(path: Path) -> str:
    """The rule knos 0.1 assumed (only separators and the colon), kept so folders it matched still match."""
    return re.sub(r"[:\\/]", "-", str(path))


def _transcripts(root: Path, repo: Path | None) -> list[Path]:
    """The transcript files that could possibly concern this repo.

    Claude Code files every session under a folder named after the directory
    it was started in, so a repo's sessions are in folders whose name starts
    with that repo's. Reading them all instead meant opening 95 MB of other
    projects' transcripts to find none — seven of the twelve seconds a cold
    read took here.

    When the naming does not look the way this expects, everything is read,
    because a slow answer is better than a missing one.
    """
    if repo is None:
        return list(root.rglob("*.jsonl"))
    try:
        folders = [d for d in root.iterdir() if d.is_dir()]
    except OSError:
        return list(root.rglob("*.jsonl"))

    # The folder is named for where the session *started*, not where it went.
    # A session opened in a parent directory and then moved into the repo
    # keeps the parent's folder name — on this machine that is 2,774 records
    # about this repo filed under its parent. So: folders for the repo and
    # anything under it, plus one folder per ancestor. Every other project on
    # the disk is skipped, and the per-line cwd check below still decides.
    here = Path(repo).resolve()
    wanted = {_encoded(here), _encoded_legacy(here)}
    ancestors = {enc(a) for a in here.parents for enc in (_encoded, _encoded_legacy)}
    mine = [
        d
        for d in folders
        if d.name in wanted or any(d.name.startswith(w + "-") for w in wanted) or d.name in ancestors
    ]
    if mine:
        return [f for d in mine for f in d.rglob("*.jsonl")]

    # Nothing matched. That is either a repo with no sessions, or a naming
    # scheme this does not know. Tell them apart by the root: if some folder
    # is named for a path on the same drive, the scheme holds and the answer
    # is genuinely none.
    anchor = _encoded(Path(repo).resolve().anchor)
    if anchor and any(d.name.startswith(anchor) for d in folders):
        return []
    return list(root.rglob("*.jsonl"))


def _inside_repo(cwd: str, repo: str) -> bool:
    """Whether a session's working directory is this repo or inside it.

    A bare prefix test let `.../app` take in the sessions of a sibling `.../app-secret`, and so hand another
    project's conversations to agents working here. Only the directory itself, or a path under it, counts."""
    cwd, repo = cwd.rstrip("/\\"), repo.rstrip("/\\")
    return cwd == repo or cwd.startswith(repo + "/") or cwd.startswith(repo + "\\")


def read_claude(repo: Path | None = None, offsets: dict[str, int] | None = None) -> Iterator[Turn]:
    """Every Claude Code turn about `repo`. With `offsets` ({file: byte offset}), each file is read from where the
    last read stopped and the dict is advanced to the end of the last complete line: transcripts only grow, so a
    refresh reads what was appended and nothing else (ported from the plane's import, attach.py)."""
    root = claude_root()
    if not root.exists():
        return
    want = str(Path(repo).resolve()).lower() if repo else None
    # Every transcript on this machine lives in one folder, so reading a repo
    # means opening every other project's transcripts too and throwing them
    # away one parsed line at a time. A line whose cwd cannot be this repo
    # cannot become a turn, and json.loads was most of what reading a repo
    # spent its time on. The needle is the path as JSON writes it, backslashes
    # doubled, so this is the same test the parsed check makes.
    needle = json.dumps(want)[1:-1] if want else ""
    for f in sorted(_transcripts(root, repo)):
        key = str(f)
        start = int((offsets or {}).get(key, 0))
        try:
            size = f.stat().st_size
            if start > size:
                start = 0  # the file was replaced: read it again from the top
            handle = f.open("rb")
        except OSError:
            continue  # corrupt or locked: skip it, keep going
        with handle:
            handle.seek(start)
            data = handle.read()
        end = data.rfind(b"\n") + 1
        if offsets is not None:
            offsets[key] = start + end
        lines = data[:end].decode("utf-8", errors="replace").splitlines()
        if lines:
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                if needle:
                    low = line.lower()
                    # A record with no cwd at all is still read, exactly as
                    # before: only a cwd that is somewhere else is skipped.
                    if '"cwd"' in low and needle not in low:
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
                if want and cwd and not _inside_repo(cwd.lower(), want):
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
    want = Path(repo).resolve() if repo else None
    try:
        folders = _folders_by_composer(conn)
        started = _composer_dates(conn)
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
            # The turn's own time when Cursor recorded one, else its conversation's start. Never the database's
            # modification time, which dated every turn ever written to the moment Cursor last saved anything.
            when = _stamp(rec.get("createdAt")) or started.get(composer, "")
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


def _stamp(value: object) -> str:
    """An ISO timestamp from Cursor's createdAt (epoch milliseconds, or already ISO), or "" when absent."""
    if isinstance(value, (int, float)) and value > 0:
        secs = value / 1000 if value > 1e11 else value
        try:
            return datetime.fromtimestamp(secs, tz=timezone.utc).isoformat()
        except (OverflowError, OSError, ValueError):
            return ""
    if isinstance(value, str) and value[:4].isdigit():
        return value
    return ""


def _composer_dates(conn: sqlite3.Connection) -> dict[str, str]:
    """When each Cursor conversation started, from its composerData record."""
    out: dict[str, str] = {}
    try:
        rows = conn.execute("SELECT key, value FROM cursorDiskKV WHERE key LIKE 'composerData:%'")
        for key, value in rows:
            try:
                rec = json.loads(value)
            except (ValueError, TypeError):
                continue
            got = _stamp(rec.get("createdAt"))
            if got:
                out[key.split(":", 1)[1]] = got
    except sqlite3.Error:
        return out
    return out


def _within(folder: Path, repo: Path) -> bool:
    """Whether a Cursor window's folder is this repo or inside it. A window opened on a parent folder is not this
    repo's: counting it put every sibling project's conversations into each child repo."""
    try:
        folder = folder.resolve()
    except OSError:
        return False
    return folder == repo or repo in folder.parents


# ---- Codex ------------------------------------------------------------


def codex_root() -> Path:
    override = os.environ.get("KNOS_CODEX_HOME") or os.environ.get("CODEX_HOME")
    return (Path(override) if override else Path.home() / ".codex") / "sessions"


def _codex_text(content: object) -> str:
    if not isinstance(content, list):
        return ""
    parts = [str(c.get("text") or "") for c in content if isinstance(c, dict)
             and c.get("type") in ("input_text", "output_text", "text")]
    return "\n".join(p for p in parts if p).strip()


def read_codex(repo: Path | None = None, offsets: dict[str, int] | None = None) -> Iterator[Turn]:
    """Every Codex turn about `repo`, from ~/.codex/sessions/**/rollout-*.jsonl. A rollout names its working
    directory in `session_meta` (and again in each `turn_context`); only a rollout whose directory is this repo, or
    inside it, is read. Offsets work as for Claude Code."""
    root = codex_root()
    if not root.is_dir():
        return
    want = str(Path(repo).resolve()).lower() if repo else None
    for f in sorted(root.rglob("rollout-*.jsonl")):
        key = str(f)
        try:
            with f.open("rb") as fh:
                head = fh.readline(65536)  # session_meta is the first line
            meta = json.loads(head).get("payload") or {}
        except (OSError, ValueError, AttributeError):
            continue
        cwd = str(meta.get("cwd") or "")
        if want and not (cwd and _inside_repo(cwd.lower(), want)):
            continue
        session = str(meta.get("id") or meta.get("session_id") or f.stem)
        start = int((offsets or {}).get(key, 0))
        try:
            if start > f.stat().st_size:
                start = 0
            with f.open("rb") as fh:
                fh.seek(start)
                data = fh.read()
        except OSError:
            continue
        end = data.rfind(b"\n") + 1
        if offsets is not None:
            offsets[key] = start + end
        for line in data[:end].decode("utf-8", errors="replace").splitlines():
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            payload = rec.get("payload") if isinstance(rec, dict) else None
            if rec.get("type") != "response_item" or not isinstance(payload, dict) or payload.get("type") != "message":
                continue
            role = payload.get("role")
            if role not in ("user", "assistant"):
                continue
            text = _codex_text(payload.get("content"))
            if text.startswith("<") or not MIN_CHARS <= len(text) <= MAX_CHARS:
                continue  # injected context (<environment_context>, <user_instructions>) is not something said
            yield Turn(client="Codex", session=session, role="user" if role == "user" else "agent", text=text,
                       when=str(rec.get("timestamp") or ""), cwd=cwd)


# ---- all of them --------------------------------------------------------


def read_all(repo: Path | None = None, offsets: dict[str, int] | None = None) -> list[Turn]:
    """Every turn from every supported client. Read on demand only. `offsets` makes Claude Code and Codex
    transcripts incremental; Cursor's database is read whole and de-duplicated by the store."""
    turns = list(read_claude(repo, offsets)) + list(read_codex(repo, offsets)) + list(read_cursor(repo))
    turns.sort(key=lambda t: t.when)
    return turns


def clients_found() -> dict[str, bool]:
    return {
        "Claude Code": claude_root().exists(),
        "Codex": codex_root().exists(),
        "Cursor": cursor_db().exists(),
    }
