"""`knos init`: wire knos into every agent on this machine in one command, and take it all back out with `--undo`.

What it writes, per host:

  claude    the MCP server (via `claude mcp add` when the CLI is here, so a running session gets it without a
            restart; else ~/.claude.json) and two hooks in ~/.claude/settings.json: SessionStart -> `knos hook start`,
            PreToolUse on Edit|Write|MultiEdit|NotebookEdit -> `knos hook guard`, PreToolUse on Write|Bash ->
            `knos hook safety`, and Stop -> `knos hook proof` (no "done" Knos cannot prove)
  desktop   the MCP server in Claude Desktop's config (it has no hooks)
  cursor    the MCP server in ~/.cursor/mcp.json and a preToolUse hook in ~/.cursor/hooks.json
  opencode  the MCP server in opencode.json and a guard plugin
  codex     the MCP server under [mcp_servers.knos] in ~/.codex/config.toml, and PreToolUse (guard, safety) and Stop
            (proof) hooks in ~/.codex/hooks.json

Every file is copied to ~/.knos/backups/init-<time>/ before it is changed, and a file that is not JSON knos can read
is left exactly as it is. `--undo` removes only what knos added (entries named "knos", hooks marked knos-guard), so
anything the person changed since is kept. Then a self-test: the MCP server is started the way an agent starts it and
must answer the handshake and list the memory tools; the guard hook must exit 0 on an empty event.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import guard, paths

HOSTS = ("claude", "codex", "cursor", "desktop", "opencode")
TOOLS = {"search", "about", "remember", "done"}
READ_BUDGET = 15.0  # seconds of `knos init` spent reading the repo; the rest is read on the first question


def server_command() -> list[str]:
    """How an agent starts the server: the `knos` script on PATH, by its absolute path, because a GUI app starts it
    with its own PATH and no shell profile. `pipx upgrade` keeps that path. Without a `knos` script (a source tree),
    this interpreter runs the module."""
    exe = own_script() or shutil.which("knos")
    if exe:
        return [str(Path(exe)), "mcp"]
    return [sys.executable, "-m", "knos", "mcp"]


def own_script() -> str | None:
    """The `knos` script installed beside the interpreter running this, when there is one. Preferred over the first
    `knos` on PATH: an older install earlier on PATH must not be the one every agent gets wired to."""
    folder = Path(sys.executable).parent
    for name in ("knos.exe", "knos") if os.name == "nt" else ("knos",):
        cand = folder / name
        if cand.is_file():
            return str(cand)
    return None


def desktop_config() -> Path:
    home = Path.home()
    if sys.platform == "darwin":
        return home / "Library/Application Support/Claude/claude_desktop_config.json"
    if sys.platform.startswith("win"):
        return Path(os.environ.get("APPDATA", home / "AppData/Roaming")) / "Claude" / "claude_desktop_config.json"
    return home / ".config/Claude/claude_desktop_config.json"


def opencode_config() -> Path:
    given = os.environ.get("OPENCODE_CONFIG")
    if given:
        return Path(given)
    base = os.environ.get("XDG_CONFIG_HOME")
    return (Path(base) if base else Path.home() / ".config") / "opencode" / "opencode.json"


def codex_config() -> Path:
    return Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex") / "config.toml"


def mcp_files() -> dict[str, Path]:
    return {"claude": Path.home() / ".claude.json", "desktop": desktop_config(), "codex": codex_config(),
            "cursor": Path.home() / ".cursor" / "mcp.json", "opencode": opencode_config()}


def present(host: str) -> bool:
    """Whether that agent is installed here: its config folder exists (or, for Claude Code and Codex, its CLI)."""
    if host == "claude":
        return (Path.home() / ".claude").is_dir() or shutil.which("claude") is not None
    if host == "codex":
        return codex_config().parent.is_dir() or shutil.which("codex") is not None
    return mcp_files()[host].parent.is_dir()


# Codex keeps MCP servers in TOML. knos owns exactly one table, [mcp_servers.knos], and touches nothing else in the
# file: it is added as a block at the end and removed by that block's header, so comments and formatting survive.
_CODEX_HEADER = "[mcp_servers.knos]"


def _toml_str(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _codex_without(text: str) -> str:
    lines = text.splitlines(keepends=True)
    out, skipping = [], False
    for line in lines:
        head = line.strip()
        if head == _CODEX_HEADER or head.startswith("[mcp_servers.knos."):
            skipping = True
            continue
        if skipping and head.startswith("["):
            skipping = False
        if not skipping:
            out.append(line)
    return "".join(out).rstrip("\n") + ("\n" if out else "")


def _codex_add(backups: "Backups") -> bool:
    path = codex_config()
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    cmd = server_command()
    block = (f"{_CODEX_HEADER}\ncommand = {_toml_str(cmd[0])}\n"
             f"args = [{', '.join(_toml_str(a) for a in cmd[1:])}]\n")
    base = _codex_without(text)
    new = (base + ("\n" if base else "") + block)
    if new == text:
        return False
    backups.keep(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(new, encoding="utf-8")
    return True


def _codex_remove(backups: "Backups") -> bool:
    path = codex_config()
    if not path.exists():
        return False
    text = path.read_text(encoding="utf-8")
    if _CODEX_HEADER not in text:
        return False
    backups.keep(path)
    path.write_text(_codex_without(text), encoding="utf-8")
    return True


@dataclass
class Report:
    done: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    backups: Path | None = None
    restart: list[str] = field(default_factory=list)


def _snapshot(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except OSError:
        return None


def _sha(path: Path) -> str | None:
    import hashlib

    got = _snapshot(path)
    return hashlib.sha256(got).hexdigest() if got is not None else None


class Backups:
    """One folder per run. Each file's bytes are copied once, before its first change; `seal` then records the hash
    of what knos left, so `undo` can tell an untouched file (restored byte for byte) from one edited since (only
    knos's own entries are taken out)."""

    def __init__(self, kind: str = "init") -> None:
        self.dir = paths.home() / "backups" / f"{kind}-{time.strftime('%Y%m%dT%H%M%S')}-{os.getpid()}"
        self.manifest: dict[str, dict] = {}

    def record(self, path: Path, before: bytes | None) -> None:
        key = str(path)
        if key in self.manifest:
            return
        self.dir.mkdir(parents=True, exist_ok=True)
        dest = None
        if before is not None:
            dest = self.dir / f"{len(self.manifest):02d}-{path.name}"
            dest.write_bytes(before)
        self.manifest[key] = {"backup": str(dest) if dest else None}
        self._write()

    def keep(self, path: Path) -> None:
        self.record(path, _snapshot(path))

    def seal(self) -> None:
        for key, rec in self.manifest.items():
            rec["after"] = _sha(Path(key))
        if self.manifest:
            self._write()

    def _write(self) -> None:
        (self.dir / "manifest.json").write_text(json.dumps(self.manifest, indent=2), encoding="utf-8")


def restore_exact() -> set[str]:
    """Undo every `knos init` whose files are still exactly as it left them, newest first: each such file gets its
    original bytes back (or is removed, if init created it). Returns the paths restored."""
    restored: set[str] = set()
    root = paths.home() / "backups"
    for manifest in sorted(root.glob("init-*/manifest.json"), reverse=True):
        try:
            entries = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for key, rec in entries.items():
            if not isinstance(rec, dict) or "after" not in rec:
                continue
            path = Path(key)
            if _sha(path) != rec["after"]:
                continue
            if rec.get("backup"):
                path.write_bytes(Path(rec["backup"]).read_bytes())
            else:
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass
            restored.add(key)
    return restored


def _edit(path: Path, change, backups: Backups) -> bool:
    """Apply `change(data) -> bool` to a JSON file; write only when it changed something. Raises guard.Unreadable."""
    data = guard._load(path)
    before = json.dumps(data, sort_keys=True)
    change(data)
    if json.dumps(data, sort_keys=True) == before:
        return False
    backups.keep(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return True


def _mcp_entry(host: str) -> dict:
    cmd = server_command()
    if host == "opencode":
        return {"type": "local", "command": cmd, "enabled": True}
    return {"command": cmd[0], "args": cmd[1:]}


def _add_mcp(host: str, backups: Backups) -> bool:
    entry = _mcp_entry(host)
    key = "mcp" if host == "opencode" else "mcpServers"

    def change(data: dict) -> None:
        servers = data.setdefault(key, {})
        if not isinstance(servers, dict):
            raise guard.Unreadable(f"{mcp_files()[host]} has a {key} that is not an object, so knos left it alone")
        servers["knos"] = entry
        if host == "opencode":
            data.setdefault("$schema", "https://opencode.ai/config.json")

    return _edit(mcp_files()[host], change, backups)


def _remove_mcp(host: str, backups: Backups) -> bool:
    key = "mcp" if host == "opencode" else "mcpServers"

    def change(data: dict) -> None:
        servers = data.get(key)
        if isinstance(servers, dict):
            servers.pop("knos", None)

    path = mcp_files()[host]
    return path.exists() and _edit(path, change, backups)


def _claude_cli_add() -> bool:
    """`claude mcp add --scope user`: registers with a running Claude Code session too, so no restart."""
    tool = None if os.environ.get("KNOS_NO_CLAUDE_CLI") else shutil.which("claude")
    if tool is None:
        return False
    cmd = server_command()
    try:
        subprocess.run([tool, "mcp", "remove", "--scope", "user", "knos"], capture_output=True, text=True, timeout=20)
        got = subprocess.run([tool, "mcp", "add", "--scope", "user", "knos", "--", *cmd],
                             capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return False
    return got.returncode == 0 or "already exists" in (got.stdout + got.stderr).lower()


def _claude_cli_remove() -> bool:
    tool = None if os.environ.get("KNOS_NO_CLAUDE_CLI") else shutil.which("claude")
    if tool is None:
        return False
    try:
        got = subprocess.run([tool, "mcp", "remove", "--scope", "user", "knos"], capture_output=True, text=True,
                             timeout=20)
    except (OSError, subprocess.SubprocessError):
        return False
    return got.returncode == 0


_HOOKS = {
    "claude": (guard.claude_settings, guard.install_claude, guard.uninstall_claude),
    "cursor": (guard.cursor_hooks, guard.install_cursor, guard.uninstall_cursor),
    "codex": (guard.codex_hooks, guard.install_codex, guard.uninstall_codex),
    "opencode": (guard.opencode_plugin, guard.install_opencode, guard.uninstall_opencode),
}


def _hooks(host: str, backups: Backups) -> Path | None:
    """Install the host's hooks; back the file up only if that changed it, so a second init changes nothing."""
    if host not in _HOOKS:
        return None
    where, install_fn, _ = _HOOKS[host]
    before = _snapshot(where())
    got = install_fn()
    if _snapshot(where()) != before:
        backups.record(where(), before)
    return got


def _unhooks(host: str, backups: Backups) -> bool:
    if host not in _HOOKS:
        return False
    where, _, uninstall_fn = _HOOKS[host]
    before = _snapshot(where())
    took = uninstall_fn()
    if _snapshot(where()) != before:
        backups.record(where(), before)
    return took


def files_of(host: str) -> list[Path]:
    got = [mcp_files()[host]]
    if host in _HOOKS:
        got.append(_HOOKS[host][0]())
    return got


RESTART = {
    "desktop": "Claude Desktop: quit it from the tray and open it again.",
    "cursor": "Cursor: quit and reopen.",
    "opencode": "OpenCode: exit and start it again.",
    "codex": "Codex: start a new session.",
}
NAMES = {"claude": "Claude Code", "codex": "Codex", "desktop": "Claude Desktop", "cursor": "Cursor",
         "opencode": "OpenCode"}


def pick(hosts: str | None) -> list[str]:
    if not hosts:
        return [h for h in HOSTS if present(h)]
    wanted = [h.strip().lower() for h in hosts.split(",") if h.strip()]
    unknown = [h for h in wanted if h not in HOSTS]
    if unknown:
        raise ValueError(f"unknown host {', '.join(unknown)}; choose from {', '.join(HOSTS)}")
    return wanted


def install(hosts: list[str], team_repo: Path | None = None) -> Report:
    rep = Report()
    backups = Backups()
    if team_repo is not None:
        from . import team_setup
        try:
            rep.done.extend(team_setup.install(team_repo, backups))
        except (guard.Unreadable, OSError, UnicodeDecodeError) as why:
            rep.problems.append(f"team setup: {why}")
    for host in hosts:
        name = NAMES[host]
        try:
            if host == "codex":
                _codex_add(backups)
            elif not (host == "claude" and _claude_cli_add()):
                _add_mcp(host, backups)
            hooked = _hooks(host, backups)
        except (guard.Unreadable, OSError, UnicodeDecodeError) as why:
            rep.problems.append(f"{name}: {why}")
            continue
        what = ", edit guard (apply_patch and shell writes)" if host == "codex" else ", edit guard and session notice"
        rep.done.append(f"{name}: memory server" + (what if hooked else ""))
        if host in RESTART:
            rep.restart.append(RESTART[host])
    backups.seal()
    rep.backups = backups.dir if backups.manifest else None
    return rep


def undo(hosts: list[str], repo: Path | None = None) -> Report:
    """Byte-for-byte where the file is as knos left it; otherwise only knos's own entries come out."""
    rep = Report()
    exact = restore_exact()
    if repo is not None:
        from . import team_setup
        try:
            if team_setup.uninstall(repo):
                rep.done.append("the team guard in this repo")
        except (guard.Unreadable, OSError, UnicodeDecodeError) as why:
            rep.problems.append(f"team setup: {why}")
    backups = Backups("undo")
    for host in hosts:
        name = NAMES[host]
        try:
            took = any(str(p) in exact for p in files_of(host))
            if host == "claude":
                took = _claude_cli_remove() or took
            if host == "codex":
                took = _codex_remove(backups) or took
            else:
                took = _remove_mcp(host, backups) or took
            took = _unhooks(host, backups) or took
        except (guard.Unreadable, OSError, UnicodeDecodeError) as why:
            rep.problems.append(f"{name}: {why}")
            continue
        (rep.done if took else rep.skipped).append(name)
    backups.seal()
    rep.backups = backups.dir if backups.manifest else None
    return rep


# ---- self-test --------------------------------------------------------------------------


def _rpc(proc: subprocess.Popen, msg: dict) -> None:
    assert proc.stdin is not None
    proc.stdin.write((json.dumps(msg) + "\n").encode())
    proc.stdin.flush()


def _read_reply(proc: subprocess.Popen, want_id: int, deadline: float) -> dict | None:
    import threading

    got: dict = {}

    def pump() -> None:
        assert proc.stdout is not None
        for raw in proc.stdout:
            try:
                msg = json.loads(raw)
            except ValueError:
                continue
            if msg.get("id") == want_id:
                got.update(msg)
                return

    t = threading.Thread(target=pump, daemon=True)
    t.start()
    t.join(max(0.1, deadline - time.monotonic()))
    return got or None


def selftest(timeout: float = 45.0, cwd: Path | None = None) -> list[str]:
    """Start the server exactly as an agent would and speak MCP to it. Returns problems; empty means it works.
    The handshake normally takes ~3 s; the deadline is generous because a busy spinning disk can make a cold start
    take 20+ s, and a false "failed" is worse than a slow success."""
    problems: list[str] = []
    deadline = time.monotonic() + timeout
    try:
        proc = subprocess.Popen(server_command(), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, cwd=str(cwd) if cwd else None)
    except OSError as why:
        return [f"the memory server would not start: {why}"]
    try:
        _rpc(proc, {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                               "clientInfo": {"name": "knos-init", "version": "0"}}})
        hello = _read_reply(proc, 1, deadline)
        if not hello or (hello.get("result") or {}).get("serverInfo", {}).get("name") != "knos":
            return ["the memory server started but did not answer the MCP handshake"]
        _rpc(proc, {"jsonrpc": "2.0", "method": "notifications/initialized"})
        _rpc(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        listed = _read_reply(proc, 2, deadline)
        names = {t.get("name") for t in ((listed or {}).get("result") or {}).get("tools", [])}
        if not TOOLS <= names:
            problems.append(f"the memory server is missing tools: {', '.join(sorted(TOOLS - names))}")
    finally:
        try:
            proc.kill()
            proc.wait(5)
        except Exception:
            pass
    try:
        hook = subprocess.run(guard.knos_cmd_argv() + ["hook", "guard", "--client", "claude"], input="{}",
                              capture_output=True, text=True, timeout=max(1.0, deadline - time.monotonic()))
        if hook.returncode != 0:
            problems.append(f"the edit guard exited {hook.returncode} on an empty event (it must allow)")
    except (OSError, subprocess.SubprocessError) as why:
        problems.append(f"the edit guard did not run: {why}")
    return problems
