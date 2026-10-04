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
# Where each host keeps its MCP servers. Claude Code and Codex also get the Stop hook; Cursor and Gemini CLI have no
# hook Knos uses, so they are touched only when their folder is already there.
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
