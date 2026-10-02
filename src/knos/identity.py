"""Who is asking: one agent identity for the MCP server, the hooks and the CLI.

An agent is `(host, session, anchor)`:

    host     which tool: claude, cursor, codex, opencode, or terminal for a person
    session  the host's own session id when it tells us (Claude Code's hooks do)
    anchor   the process id of the host application above us

The anchor is what makes one identity out of three processes. A Claude Code session starts the knos MCP server and
runs every hook as children of the same `claude` process, so walking up the process tree from any of them reaches
the same pid. The SessionStart hook records `session_id` against that pid, so the MCP server, which is never told the
session id, can learn it.

Two claims are the same agent's when the host matches and either the session id or the anchor matches. That rule is
chosen so the holder of a claim is never refused by its own guard (a missing or stale session id falls back to the
process). The cost is stated, not hidden: two chats inside one Cursor window share a process and count as one agent.
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass

# Processes that sit between a host and knos and are never the host itself.
_SHIMS = {
    "python", "python3", "pythonw", "py", "knos", "uv", "uvx", "pipx", "sh", "bash", "zsh", "fish", "dash", "cmd",
    "powershell", "pwsh", "conhost", "env", "sudo", "timeout", "npx", "wsl", "wslhost", "winpty", "git",
}
# What each host's own process is called, most specific first.
_HOST_PROCS = {
    "claude": ("claude",),
    "cursor": ("cursor",),
    "codex": ("codex",),
    "opencode": ("opencode",),
    "vscode": ("code",),
    "gemini": ("gemini",),
}
MAX_DEPTH = 16


def _norm(name: str) -> str:
    base = os.path.basename(str(name or "")).lower()
    for ext in (".exe", ".cmd", ".bat"):
        if base.endswith(ext):
            base = base[: -len(ext)]
    return base


def _table_windows() -> dict[int, tuple[int, str]]:
    """pid -> (parent pid, exe name) for every process, from one Toolhelp snapshot."""
    import ctypes
    from ctypes import wintypes

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                    ("th32DefaultHeapID", ctypes.c_void_p), ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                    ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD),
                    ("szExeFile", ctypes.c_wchar * 260)]

    k32 = ctypes.windll.kernel32
    k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    snap = k32.CreateToolhelp32Snapshot(0x2, 0)  # TH32CS_SNAPPROCESS
    if not snap or snap == wintypes.HANDLE(-1).value:
        return {}
    out: dict[int, tuple[int, str]] = {}
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        ok = k32.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            out[int(entry.th32ProcessID)] = (int(entry.th32ParentProcessID), entry.szExeFile)
            ok = k32.Process32NextW(snap, ctypes.byref(entry))
    finally:
        k32.CloseHandle(snap)
    return out


def _parent_linux(pid: int) -> tuple[int, str] | None:
    try:
        with open(f"/proc/{pid}/stat", "rb") as fh:
            raw = fh.read().decode("utf-8", "replace")
        name = raw[raw.index("(") + 1: raw.rindex(")")]
        ppid = int(raw[raw.rindex(")") + 2:].split()[1])
        return ppid, name
    except (OSError, ValueError, IndexError):
        return None


def _table_ps() -> dict[int, tuple[int, str]]:
    """macOS and other Unixes without /proc: one `ps` for the whole table."""
    try:
        out = subprocess.run(["ps", "-A", "-o", "pid=,ppid=,comm="], capture_output=True, text=True, timeout=3).stdout
    except (OSError, subprocess.SubprocessError):
        return {}
    table: dict[int, tuple[int, str]] = {}
    for line in out.splitlines():
        parts = line.split(None, 2)
        if len(parts) == 3 and parts[0].isdigit() and parts[1].isdigit():
            table[int(parts[0])] = (int(parts[1]), parts[2])
    return table


def ancestors(pid: int | None = None) -> list[tuple[int, str]]:
    """(pid, process name) from our parent upward, at most MAX_DEPTH levels. Empty when the OS will not say."""
    pid = os.getpid() if pid is None else pid
    chain: list[tuple[int, str]] = []
    try:
        if sys.platform == "win32":
            table = _table_windows()
            lookup = table.get
        elif os.path.isdir("/proc"):
            table = None
            lookup = _parent_linux
        else:
            table = _table_ps()
            lookup = table.get
        me = lookup(pid)
        cur = me[0] if me else (os.getppid() if pid == os.getpid() else 0)
        seen = {pid}
        while cur and cur not in seen and len(chain) < MAX_DEPTH:
            seen.add(cur)
            got = lookup(cur)
            if got is None:
                break
            chain.append((cur, _norm(got[1])))
            cur = got[0]
    except Exception:
        return chain
    return chain


def anchor_for(host: str | None, chain: list[tuple[int, str]] | None = None) -> int | None:
    """The pid of the host application above this process: the nearest ancestor named like the host, else the nearest
    ancestor that is not a shell, interpreter or launcher. None when the process table cannot be read."""
    chain = ancestors() if chain is None else chain
    want = _HOST_PROCS.get(host or "", ())
    for pid, name in chain:
        if want and any(w in name for w in want):
            return pid
    for pid, name in chain:
        if name not in _SHIMS and not name.startswith("python"):
            return pid
    return chain[0][0] if chain else None


def host_from_client(name: str) -> str:
    """The host for an MCP clientInfo name ('claude-code', 'Cursor', 'codex-mcp-client', ...)."""
    low = (name or "").lower()
    for host in ("claude", "cursor", "codex", "opencode", "gemini"):
        if host in low:
            return host
    if "visual studio code" in low or low.startswith("vscode"):
        return "vscode"
    return low.strip() or "agent"


def host_from_ancestors(chain: list[tuple[int, str]] | None = None) -> str:
    """For the CLI: the agent host above us if an agent ran the command, else 'terminal' (a person)."""
    chain = ancestors() if chain is None else chain
    for _pid, name in chain:
        for host, procs in _HOST_PROCS.items():
            if host != "vscode" and any(p in name for p in procs):
                return host
    return "terminal"


@dataclass(frozen=True)
class Agent:
    host: str
    session: str = ""
    anchor: int | None = None

    @property
    def label(self) -> str:
        """How other agents see this one: host/short-session, or host/pid."""
        if self.session:
            return f"{self.host}/{self.session[:8]}"
        if self.anchor:
            return f"{self.host}/pid{self.anchor}"
        return self.host

    def owns(self, host: str, session: str, anchor: int | None) -> bool:
        """Whether a claim written with (host, session, anchor) is this agent's."""
        if host != self.host:
            return False
        if session and self.session and session == self.session:
            return True
        if anchor and self.anchor and int(anchor) == int(self.anchor):
            return True
        # neither side can be told apart: a legacy claim with nothing but a host is not refused to its own host
        return not session and not anchor


def for_hook(client: str, event: dict) -> Agent:
    host = {"claude": "claude", "cursor": "cursor", "opencode": "opencode", "codex": "codex", "gemini": "gemini"}.get(client, client)
    session = str(event.get("session_id") or event.get("sessionId") or event.get("conversation_id") or "")
    return Agent(host=host, session=session, anchor=anchor_for(host))


def for_mcp(client_name: str, sessions_lookup=None) -> Agent:
    """The MCP server's agent: host from the client's name, anchor from the process tree, session from what the
    SessionStart hook recorded for that anchor (when the host has one)."""
    host = host_from_client(client_name)
    anchor = anchor_for(host)
    session = ""
    if sessions_lookup is not None and anchor:
        try:
            session = sessions_lookup(host, anchor) or ""
        except Exception:
            session = ""
    return Agent(host=host, session=session, anchor=anchor)


def for_cli(sessions_lookup=None) -> Agent:
    chain = ancestors()
    host = host_from_ancestors(chain)
    anchor = anchor_for(host if host != "terminal" else None, chain)
    session = ""
    if host != "terminal" and sessions_lookup is not None and anchor:
        try:
            session = sessions_lookup(host, anchor) or ""
        except Exception:
            session = ""
    return Agent(host=host, session=session, anchor=anchor)
