"""Two official MCP extensions on `knos mcp`, the ones of the current revision (2026-07-28) Knos did not use yet.

Tasks (io.modelcontextprotocol/tasks; modelcontextprotocol.io/extensions/tasks/overview and the schema in
github.com/modelcontextprotocol/ext-tasks schema/2026-07-28/schema.ts, read 14 Oct 2026). A referee re-run runs a
repository's tests twice in a throwaway clone: minutes, longer than many hosts keep a tool call open. When the client
declares the extension in the request's `_meta["io.modelcontextprotocol/clientCapabilities"].extensions` and calls a
long tool (`knos_verify`), the server answers at once with a CreateTaskResult (resultType "task", taskId, status
"working", createdAt, lastUpdatedAt, ttlMs, pollIntervalMs) and the client polls `tasks/get` until completed (with
`result`, what the call would have returned), failed (with `error`) or cancelled. "Never return a task to a client
that did not declare support": a client that did not gets the blocking answer, as before.

Skills (io.modelcontextprotocol/skills, SEP-2640 Final; modelcontextprotocol.io/extensions/skills/overview, same day).
An agent connected to `knos mcp` discovers the Knos skills (verify before a pull request; prove a claim on NEAR)
with `skills/list` / `skills/get` and reads them with `resources/read` at skill://<name>/<file>, each file listed with
its sha256 and size so the host verifies what it loads. The skills are the plugin's files (plugin/skills/*), served
from the wheel's copy (knos/_skills) or the source tree.
"""
from __future__ import annotations

import hashlib
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

TASKS_EXT = "io.modelcontextprotocol/tasks"
SKILLS_EXT = "io.modelcontextprotocol/skills"
CLIENT_CAPS = "io.modelcontextprotocol/clientCapabilities"
LONG_TOOLS = {"knos_verify"}       # tools that run a repository's tests: minutes, so a task when the client takes one
TASK_TTL_MS = 3_600_000
POLL_MS = 2_000
LIST_TTL_MS = 300_000


def capabilities() -> dict:
    """The extensions to add to server/discover's capabilities."""
    return {TASKS_EXT: {}, SKILLS_EXT: {"directoryRead": False}}


def client_speaks_extensions(params: dict) -> bool:
    """Whether the request's _meta carries client capabilities with an `extensions` object (any extension)."""
    meta = params.get("_meta") if isinstance(params, dict) else None
    caps = meta.get(CLIENT_CAPS) if isinstance(meta, dict) else None
    return isinstance(caps, dict) and isinstance(caps.get("extensions"), dict)


def client_takes_tasks(params: dict) -> bool:
    meta = params.get("_meta") if isinstance(params, dict) else None
    caps = meta.get(CLIENT_CAPS) if isinstance(meta, dict) else None
    ext = caps.get("extensions") if isinstance(caps, dict) else None
    return isinstance(ext, dict) and TASKS_EXT in ext


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class Tasks:
    """Tasks of one server process, kept in memory: a host that restarts the server re-runs the call (the ttlMs says
    how long a finished task is kept). Work runs on a thread; `run(params)` is the server's own tools/call."""

    def __init__(self, clock=time.monotonic):
        self._tasks: dict[str, dict] = {}
        self._lock = threading.Lock()
        self._clock = clock

    def start(self, run, params: dict) -> dict:
        tid = str(uuid.uuid4())
        task = {"taskId": tid, "status": "working", "statusMessage": f"{params.get('name')} is running",
                "createdAt": _now(), "lastUpdatedAt": _now(), "ttlMs": TASK_TTL_MS, "pollIntervalMs": POLL_MS}
        with self._lock:
            self._tasks[tid] = dict(task)

        def work():
            try:
                got = run({k: v for k, v in params.items() if k != "_meta"})
                self._finish(tid, "completed", result=got)
            except Exception as why:  # noqa: BLE001 - a failed task carries the JSON-RPC error, it does not end the server
                self._finish(tid, "failed", error={"code": -32603, "message": f"{type(why).__name__}: {why}"})
        threading.Thread(target=work, daemon=True, name=f"knos-task-{tid[:8]}").start()
        return {"resultType": "task", **task}

    def _finish(self, tid: str, status: str, **more) -> None:
        with self._lock:
            t = self._tasks.get(tid)
            if t is None or t["status"] == "cancelled":
                return
            t.update(status=status, lastUpdatedAt=_now(), statusMessage=f"{status}", **more)

    def get(self, params: dict) -> dict:
        tid = params.get("taskId")
        with self._lock:
            t = self._tasks.get(tid) if isinstance(tid, str) else None
            if t is None:
                raise KeyError(f"no task {tid!r} (it finished more than ttlMs ago, or this server restarted)")
            return {"resultType": "complete", **t}

    def cancel(self, params: dict) -> dict:
        tid = params.get("taskId")
        with self._lock:
            t = self._tasks.get(tid) if isinstance(tid, str) else None
            if t is None:
                raise KeyError(f"no task {tid!r}")
            if t["status"] in ("working", "input_required"):
                t.update(status="cancelled", lastUpdatedAt=_now(), statusMessage="cancelled: the re-run may still finish in the background")
        return {"resultType": "complete"}

    def update(self, params: dict) -> dict:
        """No Knos task asks for input mid-flight (a payment's confirmation is asked before the call, by elicitation),
        so responses are acknowledged and ignored, as the extension says for unknown keys."""
        return {"resultType": "complete"}


# -- skills --------------------------------------------------------------------------------------------------------
def _skill_roots() -> list[Path]:
    here = Path(__file__).resolve().parent
    roots = [here / "_skills"]
    tree = here.parents[1]
    roots += [tree / "plugin" / "skills"]
    return [r for r in roots if r.is_dir()]


def _frontmatter(text: str) -> dict:
    if not text.startswith("---\n"):
        return {}
    head = text[4:].split("\n---", 1)[0]
    out = {}
    for line in head.splitlines():
        if ":" in line and not line.startswith(" "):
            k, v = line.split(":", 1)
            out[k.strip()] = v.strip()
    return out


def skills() -> dict[str, dict]:
    """{name: {dir, frontmatter, files}} of every directory holding a SKILL.md whose frontmatter `name` is the
    directory's own name (the extension's rule), first root wins."""
    found: dict[str, dict] = {}
    for root in _skill_roots():
        for md in sorted(root.glob("*/SKILL.md")):
            fm = _frontmatter(md.read_text(encoding="utf-8"))
            name = fm.get("name")
            if not name or name != md.parent.name or name in found:
                continue
            files = sorted(p for p in md.parent.rglob("*") if p.is_file() and "__pycache__" not in p.parts)
            found[name] = {"dir": md.parent, "frontmatter": fm, "files": files}
    return found


def _entry(name: str, s: dict) -> dict:
    res = []
    for p in s["files"]:
        raw = p.read_bytes()
        res.append({"uri": f"skill://{name}/{p.relative_to(s['dir']).as_posix()}", "digest": "sha256:" + hashlib.sha256(raw).hexdigest(),
                    "size": len(raw)})
    return {"uri": f"skill://{name}/SKILL.md", "frontmatter": s["frontmatter"], "resources": res}


def skills_list(_params: dict) -> dict:
    return {"resultType": "complete", "skills": [_entry(n, s) for n, s in skills().items()], "ttlMs": LIST_TTL_MS, "cacheScope": "public"}


def skills_get(params: dict) -> dict:
    uri = params.get("uri")
    for n, s in skills().items():
        if uri == f"skill://{n}/SKILL.md":
            return {"resultType": "complete", "skill": _entry(n, s), "ttlMs": LIST_TTL_MS, "cacheScope": "public"}
    raise KeyError(f"no skill at {uri!r}")


def read_skill_file(uri: str) -> dict | None:
    """resources/read for a skill:// URI: {contents: [...]}; None for any other URI. Only files of a listed skill are
    served (no '..', nothing outside its directory)."""
    if not isinstance(uri, str) or not uri.startswith("skill://"):
        return None
    name, _, rel = uri[len("skill://"):].partition("/")
    s = skills().get(name)
    if s is None or not rel:
        raise KeyError(f"no skill file at {uri!r}")
    path = (s["dir"] / rel).resolve()
    if path not in [p.resolve() for p in s["files"]]:
        raise KeyError(f"no skill file at {uri!r}")
    mime = "text/markdown" if path.suffix == ".md" else "text/plain"
    return {"contents": [{"uri": uri, "mimeType": mime, "text": path.read_text(encoding="utf-8")}]}
