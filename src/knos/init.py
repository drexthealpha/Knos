"""`knos init`: install the Stop hook and the `knos mcp` server for the coding agents on this machine.
`knos init --undo` removes both.

    Claude Code   Stop -> `knos hook proof --client claude` in ~/.claude/settings.json
                  mcpServers.knos in ~/.claude.json
    Codex         Stop -> `knos hook proof --client codex` in ~/.codex/hooks.json (Codex asks you to trust it once)
                  [mcp_servers.knos] in ~/.codex/config.toml
    Cursor        mcpServers.knos in ~/.cursor/mcp.json       (only when ~/.cursor exists)
    Gemini CLI    mcpServers.knos in ~/.gemini/settings.json  (only when ~/.gemini exists)

Nothing else is written. A settings file that is not JSON Knos understands is left exactly as it is. Before a file is
changed for the first time it is copied to <file>.knos-backup.

`knos init --host <name>` installs for one host in one project instead (`project`, below): Cursor, Gemini CLI,
GitHub Copilot and VS Code, opencode, Hermes Agent, goose, aider, Windsurf, Cline, Roo Code. It writes the project's
files, and the user's home only with --global.

Knos before 0.3.10 also installed a memory MCP server and edit hooks (now in drexthealpha/knos-labs). `knos init`
removes those entries, so an upgrade does not leave a host calling commands that no longer exist. A server named
`knos` that runs `... mcp` with a command that still exists is left as it is (it starts this server); any other is
an older one, or points at a command that is gone, and is replaced. Such a `knos` that Claude Code keeps for one
project (projects.<path>.mcpServers in ~/.claude.json, where it wins over the user's) is removed.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
from pathlib import Path

MARK = "knos-guard"   # every hook Knos ever installed carries this marker in its command


class Unreadable(Exception):
    """A settings file that is not JSON knos understands. It is left exactly as it is, never overwritten."""


def own_script() -> str | None:
    """The `knos` script installed beside the interpreter running this (preferred over a stale one on PATH)."""
    folder = Path(sys.executable).parent
    for name in ("knos.exe", "knos") if os.name == "nt" else ("knos",):
        if (folder / name).is_file():
            return str(folder / name)
    return shutil.which("knos")


def knos_argv() -> list[str]:
    """How a host starts knos: the script by its absolute path (a host runs it with its own PATH, not the shell's);
    without a script, this interpreter with -m."""
    exe = own_script()
    return [os.path.abspath(exe)] if exe else [sys.executable, "-m", "knos"]


def hook_cmd(client: str) -> str:
    """The hook's command line, with forward slashes (a Windows path through bash loses its backslashes)."""
    exe, *rest = knos_argv()
    return " ".join([f'"{exe.replace(os.sep, "/")}"', *rest, "hook", "proof", "--client", client]) + f" #{MARK}"


def mcp_server() -> tuple[str, list[str]]:
    """(command, args) a host runs to start `knos mcp`."""
    exe, *rest = knos_argv()
    return exe, [*rest, "mcp"]


def claude_settings() -> Path:
    return Path.home() / ".claude" / "settings.json"


def codex_hooks() -> Path:
    return Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex") / "hooks.json"


def codex_config() -> Path:
    return codex_hooks().parent / "config.toml"


HOSTS = {"claude": claude_settings, "codex": codex_hooks}
# Where each host keeps its MCP servers, for the whole machine. Claude Code and Codex also get the Stop hook here;
# Cursor and Gemini CLI get theirs per project (`knos init --host`, below), so here they are touched only when their
# folder is already there.
MCP = {"claude": lambda: Path.home() / ".claude.json", "codex": codex_config,
       "cursor": lambda: Path.home() / ".cursor" / "mcp.json",
       "gemini": lambda: Path.home() / ".gemini" / "settings.json"}


def present(host: str) -> bool:
    """Whether that agent is installed here: its config folder exists, or (Claude Code, Codex) its CLI is on PATH."""
    if host not in HOSTS:
        return MCP[host]().parent.is_dir()
    return HOSTS[host]().parent.is_dir() or shutil.which(host) is not None


def _load(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        got = json.loads(path.read_text(encoding="utf-8-sig") or "{}")
    except (ValueError, OSError) as why:
        raise Unreadable(f"{path} is not readable JSON, so knos left it alone") from why
    if not isinstance(got, dict):
        raise Unreadable(f"{path} is not a JSON object, so knos left it alone")
    return got


def _backup(path: Path) -> Path:
    return path.with_name(path.name + ".knos-backup")


def _write(path: Path, text: str) -> None:
    """Replace the file in one step (a crash never leaves half a settings file), keeping its permissions: these
    files can hold other servers' tokens. The first time, the original is kept beside it, with its permissions."""
    if path.exists() and not _backup(path).exists():
        shutil.copy2(path, _backup(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".knos-tmp")
    tmp.write_bytes(text.encode("utf-8"))
    if path.exists():
        shutil.copymode(path, tmp)
    os.replace(tmp, path)


def _save(path: Path, data: dict) -> None:
    _write(path, json.dumps(data, indent=2) + "\n")


def _put_back(path: Path, text: str) -> None:
    """Write what is left after Knos took its entry out. A file Knos itself created (it has no backup) and that is
    empty again is removed, so undo leaves no file behind."""
    if text.strip() in ("", "{}") and not _backup(path).exists():
        path.unlink()
    else:
        _write(path, text)


def _strip(hooks: dict) -> bool:
    """Remove every Knos hook (this version's and older ones) from a host's hooks table. True if any was there."""
    took = False
    for event in list(hooks):
        entries = hooks.get(event)
        if not isinstance(entries, list):
            continue
        kept = [h for h in entries if MARK not in json.dumps(h)]
        took = took or len(kept) != len(entries)
        if kept:
            hooks[event] = kept
        else:
            hooks.pop(event)
    return took


def _set(host: str, install: bool) -> Path | None:
    """Install (or remove) the Stop hook for one host. Returns the file when it was changed."""
    path = HOSTS[host]()
    data = _load(path)
    before = json.dumps(data, sort_keys=True)
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        hooks = {}
    _strip(hooks)
    if install:
        entry = {"type": "command", "command": hook_cmd(host), "timeout": 600}
        if host == "codex":
            entry["statusMessage"] = "Knos: checking what you said is done"
        hooks.setdefault("Stop", []).append({"hooks": [entry]})
    if hooks:
        data["hooks"] = hooks
    else:
        data.pop("hooks", None)
    if json.dumps(data, sort_keys=True) == before:
        return None
    _save(path, data)
    return path


# ---- the `knos mcp` server ------------------------------------------------------------------------------------------

_HEADER = re.compile(r"""^\s*\[\s*mcp_servers\s*\.\s*(?:knos|"knos"|'knos')\s*(\.[^\]]*)?\]\s*(?:\#.*)?$""")
_ANY_HEADER = re.compile(r"^\s*\[")


def _ours(entry) -> bool:
    """Whether a server named `knos` is exactly what this install writes."""
    command, args = mcp_server()
    return isinstance(entry, dict) and entry.get("command") == command and entry.get("args") == args


def _works(entry) -> bool:
    """Whether a server named `knos` starts this product's server: it runs `... mcp` with a command that exists (the
    one this install writes, an older install's that is still there, or `uvx knos mcp` from a registry). Such an
    entry is left as it is. Anything else named knos is an older version's server, or points at a command that is
    gone, and is replaced."""
    if not isinstance(entry, dict) or not isinstance(entry.get("command"), str):
        return False
    args = entry.get("args")
    if not isinstance(args, list) or not args or args[-1] != "mcp":
        return False
    command = entry["command"]
    if "knos" not in Path(command).name.lower() and not any("knos" in str(a).lower() for a in args):
        return False
    return (os.path.isabs(command) and Path(command).is_file()) or shutil.which(command) is not None


def _toml(text: str, path: Path) -> dict:
    try:
        import tomllib
    except ModuleNotFoundError:   # Python 3.10
        import tomli as tomllib  # type: ignore[no-redef]
    try:
        return tomllib.loads(text)
    except ValueError as why:
        raise Unreadable(f"{path} is not TOML knos can read, so knos left it alone") from why


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    try:
        return path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError) as why:
        raise Unreadable(f"{path} is not readable text, so knos left it alone") from why


def _toml_without(text: str) -> str:
    """The file's text without the [mcp_servers.knos] table and its sub-tables. Codex's config is edited as text, so
    every other line stays exactly as written, line endings included. The table runs from its header to its last
    setting; comments and blank lines after that belong to whatever follows and are kept. One blank line before the
    header goes with it, so adding the table and taking it out again leaves the file as it was."""
    lines = text.splitlines(keepends=True)
    out: list[str] = []
    tail: list[str] = []          # blank and comment lines seen since the table's last setting
    inside = False
    for line in lines:
        if _HEADER.match(line):
            if not inside and out and not out[-1].strip():
                out.pop()
            inside, tail = True, []      # (a sub-table of ours: what lay between is ours too)
            continue
        if inside and _ANY_HEADER.match(line):
            inside = False
            out += tail
            tail = []
        if not inside:
            out.append(line)
        elif not line.strip() or line.lstrip().startswith("#"):
            tail.append(line)
        else:
            tail = []
    if inside:
        out += [t for t in tail if t.lstrip().startswith("#")]
    return "".join(out)


def _mcp_toml(path: Path, install: bool) -> bool:
    text = _read_text(path)
    before = _toml(text, path)
    servers = before.get("mcp_servers") if isinstance(before.get("mcp_servers"), dict) else {}
    have = servers.get("knos")
    if install and have is not None and _works(have):
        return False                          # this product's server is already there: leave the user's file alone
    if not install and not _ours(have):
        return False
    rest = _toml_without(text) if have is not None else text
    if have is not None and "knos" in (_toml(rest, path).get("mcp_servers") or {}):
        raise Unreadable(f"{path} sets mcp_servers.knos in a form knos does not edit, so knos left it alone")
    new = rest
    if install:
        nl = "\r\n" if "\r\n" in text else "\n"
        command, args = mcp_server()
        gap = "" if not rest else nl if rest.endswith(("\n", "\r\n")) else nl + nl
        new = rest + gap + nl.join(["[mcp_servers.knos]", f"command = {json.dumps(command)}",
                                    f"args = [{', '.join(json.dumps(a) for a in args)}]"]) + nl
    # the edit may change nothing but mcp_servers.knos; anything else and the file is left alone
    after = _toml(new, path)
    strip = lambda d: {**d, "mcp_servers": {k: v for k, v in (d.get("mcp_servers") or {}).items() if k != "knos"}}  # noqa: E731
    if strip(after) != strip(before):
        raise Unreadable(f"{path} could not be edited without touching other settings, so knos left it alone")
    if install:
        _write(path, new)
    else:
        _put_back(path, new)
    return True


def _mcp_json(host: str, path: Path, install: bool) -> bool:
    data = _load(path)
    before = json.dumps(data, sort_keys=True)
    servers = data.get("mcpServers", {})
    if not isinstance(servers, dict):
        raise Unreadable(f"{path} has an mcpServers that is not an object, so knos left it alone")
    if install and not _works(servers.get("knos")):
        command, args = mcp_server()
        entry = {"command": command, "args": args}
        servers["knos"] = entry if host == "gemini" else {"type": "stdio", **entry}
    elif not install and _ours(servers.get("knos")):
        servers.pop("knos")
    if servers:
        data["mcpServers"] = servers
    else:
        data.pop("mcpServers", None)   # to a host, no table and an empty one are the same
    if json.dumps(data, sort_keys=True) == before:
        return False
    if install:
        _save(path, data)
    else:
        _put_back(path, json.dumps(data, indent=2) + "\n")
    return True


def _mcp(host: str, install: bool) -> Path | None:
    """Register (or remove) the `knos mcp` server with one host. Returns the file when it was changed."""
    path = MCP[host]()
    changed = _mcp_toml(path, install) if host == "codex" else _mcp_json(host, path, install)
    return path if changed else None


# ---- what Knos before 0.3.10 installed, removed on init and on undo ------------------------------------------------

def _legacy_json() -> list[tuple[Path, str]]:
    home = Path.home()
    if sys.platform == "darwin":
        desktop = home / "Library/Application Support/Claude/claude_desktop_config.json"
    elif sys.platform.startswith("win"):
        desktop = Path(os.environ.get("APPDATA", home / "AppData/Roaming")) / "Claude" / "claude_desktop_config.json"
    else:
        desktop = home / ".config/Claude/claude_desktop_config.json"
    xdg = Path(os.environ.get("XDG_CONFIG_HOME") or home / ".config")
    return [(home / ".claude.json", "mcpServers"), (desktop, "mcpServers"), (home / ".cursor" / "mcp.json", "mcpServers"),
            (Path(os.environ.get("OPENCODE_CONFIG") or xdg / "opencode" / "opencode.json"), "mcp")]


def _remove_project_servers(path: Path) -> list[str]:
    """Claude Code keeps a server added for one project (`claude mcp add` without --scope) under
    projects.<path>.mcpServers, and in that project it wins over the user's: an older install's `knos` there, or one
    whose command is gone, would fail to start (spawn ... ENOENT) whatever `knos init` registered. Those are taken out;
    a project's working knos server is left as it is."""
    try:
        data = _load(path)
    except Unreadable:
        return []
    projects = data.get("projects")
    stale = [p for p, v in projects.items() if isinstance(v, dict) and isinstance(v.get("mcpServers"), dict)
             and "knos" in v["mcpServers"] and not _works(v["mcpServers"]["knos"])] if isinstance(projects, dict) else []
    for p in stale:
        projects[p]["mcpServers"].pop("knos")
    if stale:
        _save(path, data)
    return [f"the knos MCP server of the project {p} in {path}" for p in stale]


def remove_legacy() -> list[str]:
    """Take out the `knos` MCP server entries and the edit hooks earlier versions installed. Returns what it removed.
    An entry that starts this product's server is not one of them (see _works); `undo` removes the one this install
    wrote."""
    gone: list[str] = []
    for path, key in _legacy_json():
        try:
            data = _load(path)
        except Unreadable:
            continue
        servers = data.get(key)
        if isinstance(servers, dict) and "knos" in servers and not _works(servers["knos"]):
            servers.pop("knos")
            _save(path, data)
            gone.append(f"the knos MCP server in {path}")
    gone += _remove_project_servers(Path.home() / ".claude.json")
    codex = codex_config()
    try:
        text = _read_text(codex)
        have = (_toml(text, codex).get("mcp_servers") or {}).get("knos") if text else None
        if have is not None and not _works(have):
            rest = _toml_without(text)
            if "knos" not in (_toml(rest, codex).get("mcp_servers") or {}):
                _write(codex, rest)
                gone.append(f"the knos MCP server in {codex}")
    except Unreadable:
        pass
    cursor = Path.home() / ".cursor" / "hooks.json"
    try:
        data = _load(cursor)
        if isinstance(data.get("hooks"), dict) and _strip(data["hooks"]):
            _save(cursor, data)
            gone.append(f"the edit hook in {cursor}")
    except Unreadable:
        pass
    plugin = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "opencode" / "plugin" / "knos-guard.js"
    if plugin.exists():
        plugin.unlink()
        gone.append(f"the edit plugin {plugin}")
    return gone


def install(hosts: list[str] | None = None) -> dict:
    """{"done": [(host, hook file)], "mcp": [(host, MCP file)], "skipped": [(host, why)], "removed": [what]}"""
    rep: dict = {"done": [], "mcp": [], "skipped": [], "removed": remove_legacy()}
    for host in hosts or list(MCP):
        if host not in MCP:
            rep["skipped"].append((host, f"unknown host: use {', '.join(MCP)}"))
            continue
        if not present(host) and not (hosts and host in HOSTS):
            if hosts or host in HOSTS:
                rep["skipped"].append((host, "not installed here"))
            continue
        for kind, table, change in (("done", HOSTS, _set), ("mcp", MCP, _mcp)):
            if host in table:
                try:
                    change(host, True)
                    rep[kind].append((host, str(table[host]())))
                except Unreadable as why:
                    rep["skipped"].append((host, str(why)))
    return rep


def undo(hosts: list[str] | None = None) -> dict:
    rep: dict = {"done": [], "mcp": [], "skipped": [], "removed": remove_legacy()}
    for host in hosts or list(MCP):
        for kind, table, change in (("done", HOSTS, _set), ("mcp", MCP, _mcp)):
            if host in table:
                try:
                    if change(host, False):
                        rep[kind].append((host, str(table[host]())))
                except Unreadable as why:
                    rep["skipped"].append((host, str(why)))
    return rep


# ---- `knos init --host <name>`: one project, one host ----------------------------------------------------------------
# Each route writes the files that host reads from a project folder, in the fields its documentation names (the pages
# and the day they were read are in integrations/hosts/README.md). The user's home is written only with --global, and
# only for the three hosts that read their MCP servers from nowhere else. A second run changes nothing.

GATES = {"yes": "a false \"done\" is sent back to the agent with the check that failed",
         "each edit": "there is no \"done\" to check: the host runs Knos after each edit and gives the model what failed",
         "annotate": "the host cannot hold a turn: the person sees which check failed, the agent is not sent back",
         "no": "this host has no hook that runs when the agent says it is done"}
ALIASES = {"vscode": "copilot", "copilot-cli": "copilot", "roo-code": "roo", "cascade": "windsurf", "devin": "windsurf"}


def read_only_tools() -> list[str]:
    """The `knos mcp` tools that only read. A host is told to run these without asking, or to offer only these."""
    from . import mcp
    return [t["name"] for t in mcp.TOOLS if t["annotations"]["readOnlyHint"]]


def posting_tools() -> list[str]:
    from . import mcp
    return [t["name"] for t in mcp.TOOLS if not t["annotations"]["readOnlyHint"]]


def portable_argv() -> list[str]:
    """How a file in a project starts knos. A project's files are committed and run on other machines, so they say
    `uvx knos` as the plugin does; only where uv is missing here do they name this machine's own command."""
    return ["uvx", "knos"] if shutil.which("uvx") else knos_argv()


def _line(argv: list[str], *more: str) -> str:
    """A command line for a host's shell: forward slashes (a Windows path through bash loses its backslashes)."""
    words = [a.replace(os.sep, "/") for a in argv]
    return " ".join([*(f'"{a}"' if " " in a else a for a in words), *more])


def _is_knos_hook(entry) -> bool:
    return "hook proof --client" in json.dumps(entry)


def _edit(path: Path, change) -> bool:
    """Apply `change` to a JSON file's object and save it when that changed something."""
    data = _load(path)
    before = json.dumps(data, sort_keys=True)
    change(data)
    if json.dumps(data, sort_keys=True) == before:
        return False
    _save(path, data)
    return True


def _own(path: Path, text: str) -> bool:
    """A file that is Knos's alone: written whole, and left alone when it already says this."""
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))
    return True


def _table(data: dict, key: str, path: Path) -> dict:
    got = data.setdefault(key, {})
    if not isinstance(got, dict):
        raise Unreadable(f"{path} has a `{key}` that is not an object, so knos left it alone")
    return got


def _hooks(data: dict, path: Path, events: dict[str, dict]) -> None:
    """Put one Knos entry under each event, in place of any Knos entry already there."""
    hooks = _table(data, "hooks", path)
    for event, entry in events.items():
        kept = [h for h in hooks.get(event, []) if not _is_knos_hook(h)] if isinstance(hooks.get(event, []), list) else []
        hooks[event] = [*kept, entry]


def _server(argv: list[str], **more) -> dict:
    return {"command": argv[0], "args": [*argv[1:], "mcp"], **more}


RULE = """# Knos

Before you say that work here is done, that tests pass, that CI is green or that something shipped, run the check
yourself and say what it printed. This host has no hook that checks the claim for you, so the same check runs on the
pull request: a description that says "tests pass" over a failed check is refused there.

- Run the repository's own tests, and quote the last lines of their output.
- If a check failed and you could not fix it, say so plainly instead of "done".
- `knos_check_pr` (the `knos` MCP server) says whether a pull request's claims agree with GitHub's record.
"""

OPENCODE_PLUGIN = """// Written by `knos init --host opencode`. When a session goes idle, Knos checks what the agent's last message
// claims; a claim it cannot prove goes back to the agent as the next prompt, with the check that failed.
// opencode's plugin events: https://opencode.ai/docs/plugins/ (the shape of session.idle is not documented there).
const KNOS = %s

export const Knos = async ({ client, $, directory }) => ({
  event: async ({ event }) => {
    if (event.type !== "session.idle") return
    const id = event.properties?.sessionID
    if (!id) return
    try {
      const got = await client.session.messages({ path: { id } })
      const last = (got.data ?? got).filter((m) => m.info?.role === "assistant").pop()
      const text = (last?.parts ?? []).filter((p) => p.type === "text").map((p) => p.text).join("\\n")
      if (!text) return
      const sent = JSON.stringify({ cwd: directory, session_id: id, last_assistant_message: text })
      const out = await $`${KNOS} hook proof --client opencode < ${new Response(sent)}`.quiet().nothrow().text()
      const verdict = out.trim() ? JSON.parse(out) : {}
      if (verdict.decision === "block") {
        await client.session.prompt({ path: { id }, body: { parts: [{ type: "text", text: verdict.reason }] } })
      }
    } catch {
      // a broken install never traps a session
    }
  },
})
"""

YAML_MARK = "# knos-guard"


def hermes_block(argv: list[str]) -> str:
    """The lines for ~/.hermes/config.yaml: the server with only the reading tools offered, the hook that holds a
    turn whose claim fails (pre_verify), and the one that tells the agent what was refused here before (pre_llm_call).
    Every scalar is written as JSON, which YAML reads as it is."""
    q = json.dumps
    hook = q(_line(argv, "hook", "proof", "--client", "hermes"))
    return "\n".join([
        f"{YAML_MARK}: begin (written by `knos init --host hermes --global`; delete down to the end line to undo)",
        "mcp_servers:", "  knos:", f"    command: {q(argv[0])}", f"    args: {q([*argv[1:], 'mcp'])}",
        "    tools:", f"      include: {q(read_only_tools())}",
        "hooks:", "  pre_verify:", f"    - command: {hook}", "      timeout: 300",
        "  pre_llm_call:", f"    - command: {hook}", "      timeout: 30",
        f"{YAML_MARK}: end", ""])


def _yaml_keys(text: str) -> set[str]:
    return {m.group(1) for m in re.finditer(r"^([A-Za-z_][\w-]*)\s*:", text, re.M)}


def _yaml_add(path: Path, block: str, keys: set[str]) -> str | None:
    """Add Knos's block to a YAML file Knos cannot parse (no YAML reader is a dependency), so only when none of the
    block's top-level keys is in the file yet. Returns None when written or already there, else why not."""
    text = _read_text(path)
    if block in text:
        return None
    if YAML_MARK in text:
        return f"{path} holds an older Knos block: delete it (from `{YAML_MARK}: begin` to `{YAML_MARK}: end`) and run this again"
    clash = sorted(keys & _yaml_keys(text))
    if clash:
        return f"{path} already sets {', '.join(clash)}, and knos does not rewrite YAML it did not write: add the lines below by hand"
    _write(path, text + ("" if not text or text.endswith("\n") else "\n") + block)
    return None


def _cursor(root: Path, home: Path | None, argv: list[str], rep: dict) -> None:
    hook = _line(argv, "hook", "proof", "--client", "cursor")
    f = root / ".cursor" / "mcp.json"
    rep["files"].append((f, "MCP server", _edit(f, lambda d: _table(d, "mcpServers", f).update(knos={"type": "stdio", **_server(argv)}))))
    f = root / ".cursor" / "hooks.json"
    def hooks(d: dict) -> None:
        d.setdefault("version", 1)
        _hooks(d, f, {"afterAgentResponse": {"command": hook}, "stop": {"command": hook, "timeout": 600}})
    rep["files"].append((f, "stop hook", _edit(f, hooks)))
    f = root / ".cursor" / "cli.json"
    def allow(d: dict) -> None:
        perms = _table(d, "permissions", f)
        have = perms.get("allow") if isinstance(perms.get("allow"), list) else []
        perms["allow"] = [*have, *(a for a in (f"Mcp(knos:{t})" for t in read_only_tools()) if a not in have)]
    rep["files"].append((f, "tools the Cursor CLI may run without asking: the reading ones", _edit(f, allow)))
    rep["notes"].append("Cursor's editor asks before each MCP tool unless you allow it in its settings; mcp.json has no field for that.")


def _gemini(root: Path, home: Path | None, argv: list[str], rep: dict) -> None:
    f = root / ".gemini" / "settings.json"
    entry = {"hooks": [{"name": "knos", "type": "command", "command": _line(argv, "hook", "proof", "--client", "gemini"),
                        "timeout": 600000, "description": "Knos checks what the agent says is done"}]}
    def change(d: dict) -> None:
        _table(d, "mcpServers", f).update(knos=_server(argv, includeTools=read_only_tools()))
        _hooks(d, f, {"AfterAgent": entry})
    rep["files"].append((f, "MCP server (reading tools only) and AfterAgent hook", _edit(f, change)))


def _copilot(root: Path, home: Path | None, argv: list[str], rep: dict) -> None:
    hook = _line(argv, "hook", "proof", "--client", "copilot")
    f = root / ".github" / "hooks" / "knos.json"
    text = json.dumps({"version": 1, "hooks": {"agentStop": [
        {"type": "command", "bash": hook, "powershell": hook, "timeoutSec": 600}]}}, indent=2) + "\n"
    rep["files"].append((f, "agentStop hook (Copilot CLI, Copilot cloud agent; VS Code reads the same file)", _own(f, text)))
    f = root / ".vscode" / "mcp.json"
    rep["files"].append((f, "MCP server for VS Code", _edit(f, lambda d: _table(d, "servers", f).update(knos={"type": "stdio", **_server(argv)}))))
    rep["notes"].append("VS Code asks before each MCP tool; .vscode/mcp.json has no field that allows one.")
    rep["manual"].append("Copilot cloud agent reads its MCP servers from the repository's settings, not from a file. Paste this under "
                         "Settings > Copilot > MCP servers:\n" + json.dumps({"mcpServers": {"knos": {
                             "type": "local", **_server(argv), "tools": read_only_tools()}}}, indent=2))


def _opencode(root: Path, home: Path | None, argv: list[str], rep: dict) -> None:
    f = root / "opencode.json"
    if (root / "opencode.jsonc").exists():
        raise Unreadable(f"{root / 'opencode.jsonc'} has comments knos cannot keep, so knos left it alone")
    def change(d: dict) -> None:
        d.setdefault("$schema", "https://opencode.ai/config.json")
        _table(d, "mcp", f).update(knos={"type": "local", "command": [*argv, "mcp"], "enabled": True})
        _table(d, "tools", f).update({f"knos_{t}": False for t in posting_tools()})   # opencode names a tool <server>_<tool>
    rep["files"].append((f, "MCP server, with the tools that post turned off", _edit(f, change)))
    f = root / ".opencode" / "plugins" / "knos.js"
    rep["files"].append((f, "session.idle plugin", _own(f, OPENCODE_PLUGIN % json.dumps(argv))))


def _cline(root: Path, home: Path | None, argv: list[str], rep: dict) -> None:
    f = root / ".clinerules" / "knos.md"
    rep["files"].append((f, "rule", _own(f, RULE)))
    entry = _server(argv, disabled=False, autoApprove=read_only_tools())
    if home is None:
        rep["manual"].append("Cline keeps MCP servers in your home, not in a project (~/.cline/mcp.json for its CLI). Run this again "
                             "with --global to add it there, or add this under mcpServers:\n" + json.dumps({"knos": entry}, indent=2))
        return
    f = home / ".cline" / "mcp.json"
    rep["files"].append((f, "MCP server (reading tools approved)", _edit(f, lambda d: _table(d, "mcpServers", f).update(knos=entry))))


def _roo(root: Path, home: Path | None, argv: list[str], rep: dict) -> None:
    f = root / ".roo" / "mcp.json"
    entry = _server(argv, disabled=False, alwaysAllow=read_only_tools())
    rep["files"].append((f, "MCP server (reading tools approved)", _edit(f, lambda d: _table(d, "mcpServers", f).update(knos=entry))))
    rep["notes"].append("Roo Code's makers ended the product on 15 May 2026; this is for installs still in use.")


def _windsurf(root: Path, home: Path | None, argv: list[str], rep: dict) -> None:
    hook = _line(argv, "hook", "proof", "--client", "windsurf")
    f = root / ".windsurf" / "hooks.json"
    entry = {"command": hook, "powershell": hook, "show_output": True}
    rep["files"].append((f, "post_cascade_response hook", _edit(f, lambda d: _hooks(d, f, {"post_cascade_response": entry}))))
    rep["manual"].append("Its MCP servers are read from your home only (mcp_config.json). Add this under mcpServers there:\n"
                         + json.dumps({"knos": _server(argv, disabledTools=posting_tools())}, indent=2))


def _hermes(root: Path, home: Path | None, argv: list[str], rep: dict) -> None:
    block = hermes_block(argv)
    if home is None:
        rep["manual"].append("Hermes Agent reads one file, ~/.hermes/config.yaml, and nothing from a project. Run this again with "
                             "--global to add these lines there, or add them by hand:\n" + block)
        return
    f = Path(os.environ.get("HERMES_HOME") or home / ".hermes") / "config.yaml"
    before = _read_text(f)
    why = _yaml_add(f, block, {"mcp_servers", "hooks"})
    if why:
        rep["manual"].append(why + "\n" + block)
    else:
        rep["files"].append((f, "MCP server (reading tools only), pre_verify and pre_llm_call hooks", _read_text(f) != before))
    rep["notes"].append("Hermes asks once before it runs a new shell hook (or start it with --accept-hooks).")


def _goose(root: Path, home: Path | None, argv: list[str], rep: dict) -> None:
    from . import version
    plugin = root / ".agents" / "plugins" / "knos"
    f = plugin / "plugin.json"
    rep["files"].append((f, "plugin manifest", _own(f, json.dumps(
        {"name": "knos", "version": version(), "description": "Knos checks what the agent says is done"}, indent=2) + "\n")))
    f = plugin / "hooks" / "hooks.json"
    rep["files"].append((f, "Stop hook", _own(f, json.dumps({"hooks": {"Stop": [{"hooks": [
        {"type": "command", "command": _line(argv, "hook", "proof", "--client", "goose"), "timeout": 600}]}]}}, indent=2) + "\n")))
    rep["manual"].append("goose reads its extensions from ~/.config/goose/config.yaml only. Add this under extensions there "
                         "(its documentation names no field that limits an extension's tools):\n"
                         f"  knos:\n    name: Knos\n    cmd: {json.dumps(argv[0])}\n    args: {json.dumps([*argv[1:], 'mcp'])}\n"
                         "    enabled: true\n    type: stdio\n    timeout: 300")


def _aider(root: Path, home: Path | None, argv: list[str], rep: dict) -> None:
    f = root / ".aider.conf.yml"
    block = "\n".join([f"{YAML_MARK}: aider runs this after each edit and gives the model what it prints when it fails",
                       f"test-cmd: {json.dumps(_line(argv, 'hook', 'proof', '--client', 'aider'))}", "auto-test: true", ""])
    before = _read_text(f)
    why = _yaml_add(f, block, {"test-cmd", "auto-test"})
    if why:
        rep["manual"].append(why + "\n" + block)
    else:
        rep["files"].append((f, "test command", _read_text(f) != before))
    rep["notes"].append("aider has no MCP client and no hooks: its test command is the nearest thing.")


#        host        route      can it stop a false "done"   what it is called
ROUTES = {"cursor":   (_cursor,   "yes",      "Cursor"),
          "gemini":   (_gemini,   "yes",      "Gemini CLI"),
          "copilot":  (_copilot,  "yes",      "GitHub Copilot (CLI, cloud agent, VS Code agent mode)"),
          "opencode": (_opencode, "yes",      "opencode"),
          "hermes":   (_hermes,   "yes",      "Hermes Agent"),
          "goose":    (_goose,    "yes",      "goose"),
          "aider":    (_aider,    "each edit", "aider"),
          "windsurf": (_windsurf, "annotate", "Windsurf (Cascade)"),
          "cline":    (_cline,    "no",       "Cline"),
          "roo":      (_roo,      "no",       "Roo Code")}


def project(host: str, root: Path | None = None, everywhere: bool = False) -> dict:
    """Write one host's files into the project at `root` (the current folder). With `everywhere` (--global), also the
    file in the user's home, for a host that reads its MCP servers from nowhere else.
    {"host", "name", "gate", "files": [(path, what, changed)], "manual": [text], "notes": [text]}"""
    host = ALIASES.get(host, host)
    if host not in ROUTES:
        raise ValueError(f"`{host}` has no project install: use one of {', '.join(ROUTES)} "
                         "(Claude Code and Codex are installed for the whole machine by `knos init`)")
    route, gate, name = ROUTES[host]
    rep: dict = {"host": host, "name": name, "gate": gate, "files": [], "manual": [], "notes": []}
    route(Path(root) if root is not None else Path.cwd(), Path.home() if everywhere else None, portable_argv(), rep)
    return rep


def project_cli(host: str, everywhere: bool = False, say=print, root: Path | None = None) -> int:
    """`knos init --host <name> [--global]`: write, and say what was written."""
    try:
        rep = project(host, root, everywhere)
    except (ValueError, Unreadable) as why:
        say(str(why))
        return 1
    say(f"Knos for {rep['name']}:")
    for path, what, changed in rep["files"]:
        say(f"  {'wrote' if changed else 'already there'}: {path} ({what})")
    for text in rep["manual"]:
        say("  by hand: " + text.replace("\n", "\n    "))
    for text in rep["notes"]:
        say("  note: " + text)
    say(f"Can it stop a false \"done\"? {rep['gate']}: {GATES[rep['gate']]}.")
    return 0


def main(argv: list[str] | None = None) -> int:
    """`python -m knos.init --host <name> [--global] [--dir <folder>]`."""
    import argparse
    ap = argparse.ArgumentParser(prog="knos init", description="Install Knos for one coding agent in this project.")
    ap.add_argument("--host", required=True, help=", ".join(ROUTES))
    ap.add_argument("--global", dest="everywhere", action="store_true", help="also write the host's file in your home, where it reads nothing else")
    ap.add_argument("--dir", default=None, help="the project folder (default: the current one)")
    got = ap.parse_args(argv)
    return project_cli(got.host, got.everywhere, root=Path(got.dir) if got.dir else None)


# ---- `knos init --pr`: Knos in a repository, by one pull request ---------------------------------------------------
# GitHub opens its file editor with a file filled in from the address: /<owner>/<repo>/new/<branch>?filename=&value=.
# Committing there offers a new branch and a pull request (or, without write access, a fork and "Propose new file").
# So installing is one link, and the file is short enough for one: GitHub refuses an address over 8,191 bytes
# (https://github.com/github/docs/issues/5136). Nothing here names a commit of the workflows: the wheel is built
# before that commit exists, so the file is read from the release's examples/ when it is needed.

WORKFLOW_PATH = ".github/workflows/knos.yml"
URL_LIMIT = 8191
_SPEC = re.compile(r"(?:https://github\.com/)?([A-Za-z0-9](?:-?[A-Za-z0-9]){0,38})/([A-Za-z0-9._-]{1,100}?)(?:\.git)?/?(?:@([A-Za-z0-9._/-]{1,200}))?")   # web/install.js reads the same
_RAW = "https://raw.githubusercontent.com/drexthealpha/Knos/{ref}/examples/knos-install.yml"


def spec(text: str) -> tuple[str, str, str]:
    """(owner, repository, branch) from `owner/repo` or `owner/repo@branch`. The branch is `main` unless named."""
    m = _SPEC.fullmatch(text.strip())
    if not m or m.group(2) in (".", ".."):
        raise ValueError(f"`{text}` is not a repository: write it as owner/repo, or owner/repo@branch when its default branch is not main")
    return m.group(1), m.group(2), m.group(3) or "main"


def install_link(repo: str, text: str, path: str = WORKFLOW_PATH) -> str:
    """The address that opens GitHub's editor in `repo` with `text` as a new file at `path`. Raises ValueError when
    GitHub would refuse it for its length."""
    import urllib.parse
    owner, name, branch = spec(repo)
    url = (f"https://github.com/{owner}/{name}/new/{urllib.parse.quote(branch, safe='/')}"
           f"?filename={urllib.parse.quote(path, safe='')}&value={urllib.parse.quote(text, safe='')}")
    if len(url) > URL_LIMIT:
        raise ValueError(f"the link would be {len(url)} bytes and GitHub takes at most {URL_LIMIT}: copy the file into {path} by hand")
    return url


def workflow_text(fetch=None) -> str:
    """examples/knos-install.yml: from a source tree when this runs in one, else from this release's tag on GitHub."""
    from . import version
    local = Path(__file__).resolve().parents[2] / "examples" / "knos-install.yml"
    if fetch is None and local.is_file():
        return local.read_text(encoding="utf-8")
    if fetch is None:
        import urllib.request

        def fetch(url: str) -> str:
            with urllib.request.urlopen(url, timeout=20) as r:   # noqa: S310 (a fixed https address)
                return r.read().decode("utf-8")
    try:
        return fetch(_RAW.format(ref=f"v{version()}"))
    except OSError as why:
        raise ValueError(f"the workflow file of knos {version()} could not be read from GitHub ({why}). Copy it from "
                         "https://github.com/drexthealpha/Knos/blob/main/examples/knos-install.yml") from why


def _gh_pull(owner: str, name: str, text: str, gh) -> str:
    """Open the pull request with the GitHub CLI: a branch `knos-install` from the default branch, the one file, the
    pull request. `gh(*args)` returns the CLI's output and raises OSError with its words. Returns the pull request's URL."""
    import base64
    repo = f"repos/{owner}/{name}"
    base = gh("api", repo, "--jq", ".default_branch").strip()
    sha = gh("api", f"{repo}/git/ref/heads/{base}", "--jq", ".object.sha").strip()
    gh("api", "-X", "POST", f"{repo}/git/refs", "-f", "ref=refs/heads/knos-install", "-f", f"sha={sha}")
    gh("api", "-X", "PUT", f"{repo}/contents/{WORKFLOW_PATH}", "-f", "message=Install Knos", "-f", "branch=knos-install",
       "-f", "content=" + base64.b64encode(text.encode("utf-8")).decode("ascii"))
    return gh("api", "-X", "POST", f"{repo}/pulls", "-f", "title=Install Knos", "-f", "head=knos-install", "-f", f"base={base}",
              "-f", "body=Adds .github/workflows/knos.yml: a `/knos fund` comment funds an issue with test USDC on Solana devnet, and the merged "
                    "pull request that closes it is paid. No secret, and no write access to this repository's code. "
                    "https://github.com/drexthealpha/Knos/blob/main/docs/INSTALL.md", "--jq", ".html_url").strip()


def _gh(*args: str) -> str:
    import subprocess
    done = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=60)   # noqa: S603, S607
    if done.returncode:
        raise OSError((done.stderr or done.stdout).strip().splitlines()[-1] if (done.stderr or done.stdout).strip() else "gh failed")
    return done.stdout


def pull_request(repo: str, say=print, gh=None, text: str | None = None) -> int:
    """`knos init --pr owner/repo`: print the link that opens the pull request, and the file it adds. With the GitHub
    CLI on this machine, open the pull request too; when that fails, say why and leave the link."""
    try:
        owner, name, _ = spec(repo)
        text = workflow_text() if text is None else text
        link = install_link(repo, text)
    except ValueError as why:
        say(str(why))
        return 1
    say(f"The file, for {WORKFLOW_PATH} of {owner}/{name}:\n\n{text}")
    say(f"Open this link, press \"Commit changes\", and choose the new branch and pull request GitHub offers:\n\n{link}\n")
    gh = gh if gh is not None else (_gh if shutil.which("gh") else None)
    if gh is None:
        say("The GitHub CLI (gh) is not installed here, so nothing was sent: the link above is the whole install.")
        return 0
    try:
        say(f"Opened the pull request with the GitHub CLI: {_gh_pull(owner, name, text, gh)}\nMerge it and Knos is installed.")
    except OSError as why:
        say(f"The GitHub CLI could not open the pull request ({why}), so nothing was changed by this command: use the link above.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
