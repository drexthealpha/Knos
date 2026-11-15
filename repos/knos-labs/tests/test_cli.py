"""Every command, every error path, `knos init` on a fake home, and help that fits one screen.

The console script is `knos.cli:main(argv) -> int`: a failure is one line and the command that fixes it, never a
traceback; exit 1 for a failure a person can fix, 2 for a usage error. These tests call `main([...])` and read what
it printed, the way a person reads it.

Rewritten for 0.2.0. Dropped, because the thing they tested is gone from the product:

  - the `knos connect --print` paste text (`knos.mcp` module path, "knos connect" by hand) and the 0.1 writer's
    private helpers (`_config_files`, `_write_configs`, `_claude_cli`, `*.before-knos` copies, "already has it",
    "nothing to restart"); the same purposes are now tested through `knos init` (adds and keeps everything else,
    idempotent, leaves an unreadable config alone, skips agents that are not installed, `claude mcp add`, the
    OpenCode shape and its env var, every platform's config path, the exact restart line per app);
  - the Claude Desktop extension manifest check: extension/ is not part of 0.2.0 (it still pins knos==0.1.8 and
    advertises three tools); the plugin and marketplace manifests are still checked;
  - the README first-screen test: it asserted the GitHub Action and the CI pull-request warning, which 0.2.0 removed;
  - "CLAUDE.md cannot do that" on the main screen: the 0.2.0 screen states the pitch differently (checked below);
  - status's "things learned" / "MB of 5 MB used" wording from the 0.1 store (status is checked against 0.2.0's).

The jargon list no longer bans "mcp" (0.2.0's `knos init` page names the memory server "(MCP)" because that is what
every agent's settings call it) nor "wallet", "onchain" and "gas" (Knos Pro is bought from a Solana wallet).
"""

from __future__ import annotations

import ast
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from knos import help as help_text
from knos import init as setup
from knos.cli import main

ROOT = Path(__file__).resolve().parents[1]

# Words a developer would have to look up, or that describe knos's insides rather than their repo.
JARGON = ["stdio", "tier", "entity", "schema", "index", "sqlite", "traceback", "exception", "serialize", "daemon"]


def run(capsys, *args: str) -> tuple[int, str]:
    rc = main(list(args))
    got = capsys.readouterr()
    return rc, got.out + got.err


# ---- agents on this machine: never the real ones ------------------------------------------------------------

_AGENT_CLIS = {"claude", "codex", "cursor", "opencode"}


@pytest.fixture(autouse=True)
def _no_agent_clis(monkeypatch):
    """The machine running the tests may have `claude` on PATH (it does under WSL). `knos init` must never run the
    real one from a test, and "is Claude Code installed" must be decided by the fake home alone."""
    real = shutil.which

    def which(name, *a, **k):
        if Path(str(name)).stem.lower() in _AGENT_CLIS:
            return None
        return real(name, *a, **k)

    monkeypatch.setattr(shutil, "which", which)


def _init(capsys, *extra: str) -> tuple[int, str]:
    return run(capsys, "init", "--no-test", "--no-read", *extra)


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _server() -> dict:
    cmd = setup.server_command()
    return {"command": cmd[0], "args": cmd[1:]}


# ---- version, help ---------------------------------------------------------------------------------------------


@pytest.mark.critical
def test_the_cli_reports_the_package_version(capsys):
    """One number, read from package metadata, so it cannot drift from what the MCP handshake reports."""
    from knos import version

    rc, said = run(capsys, "--version")
    assert rc == 0
    assert said.strip() == version()
    assert version() not in ("", "0+unknown")
    assert "version=version()" in (ROOT / "src" / "knos" / "mcp.py").read_text(encoding="utf-8")


def test_knos_on_its_own_shows_the_one_screen(capsys):
    rc, said = run(capsys)
    assert rc == 0
    assert "knos init" in said and "knos help <cmd>" in said
    assert "Usage:" not in said


def test_help_fits_one_screen():
    assert len(help_text.main().splitlines()) <= 24


def _screens():
    yield "main", help_text.main()
    for name in sorted(help_text.PER_COMMAND):
        yield name, help_text.for_command(name)


_WIDE = {}  # every bug once listed here is fixed; a new one goes here as a strict xfail


@pytest.mark.parametrize("name,screen", [
    pytest.param(n, s, marks=pytest.mark.xfail(reason=_WIDE[n], strict=True)) if n in _WIDE else (n, s)
    for n, s in _screens()])
def test_every_screen_fits_eighty_columns(name, screen):
    assert max(len(line) for line in screen.splitlines()) <= 80


@pytest.mark.parametrize("name,screen", list(_screens()))
def test_no_jargon_anywhere(name, screen):
    low = screen.lower()
    for word in JARGON:
        assert word not in low, f"{name} says {word!r}"


def test_the_one_screen_states_the_one_product():
    """One product up front: paste an agent PR, protect a repo, fund an issue, paid on GitHub's proof; the free Stop
    hook. Claims, budgets, Pro, Tempo and text jobs are one `knos labs` line, not the pitch."""
    screen = help_text.main()
    assert "AI agent work gets paid only when GitHub's own signature, checked" in screen
    for step in ("paste an agent PR", "protect a repo", "fund an issue", "paid on GitHub's proof", "Stop hook"):
        assert step in screen
    assert "knos labs" in screen
    for gone in ("knos jobs post", "knos claim", "knos budget", "knos pro buy", "who works on"):
        assert gone not in screen


@pytest.mark.parametrize("old", [["claim", "--help"], ["budget", "--help"], ["jobs", "--help"], ["pro", "--help"],
                                 ["work", "--help"], ["team", "--help"]])
def test_labs_commands_keep_their_old_names(old, capsys):
    """Everything under `knos labs` still answers to its old top-level name, hidden from the screens."""
    import typer

    from knos.cli import app

    group = typer.main.get_command(app)
    assert group.commands[old[0]].hidden
    assert old[0] in group.commands["labs"].commands
    rc_old, said_old = run(capsys, *old)
    rc_new, said_new = run(capsys, "labs", *old)
    assert rc_old == rc_new == 0
    assert said_old.split("Usage:")[1].split("\n", 1)[1] == said_new.split("Usage:")[1].split("\n", 1)[1]


def _commands() -> list[str]:
    """Every command a person can type: visible commands and groups, not the hidden plumbing."""
    import typer

    from knos.cli import app

    group = typer.main.get_command(app)
    return sorted(name for name, cmd in group.commands.items() if not getattr(cmd, "hidden", False) and name != "help")


_NO_PAGE = {}  # every bug once listed here is fixed; a new one goes here as a strict xfail


@pytest.mark.parametrize("command", [
    pytest.param(c, marks=pytest.mark.xfail(reason=_NO_PAGE[c], strict=True)) if c in _NO_PAGE else c
    for c in _commands()])
def test_every_command_has_a_help_page(command, capsys):
    """`knos help export` once said "No command called export" while export worked. Nothing compared them."""
    rc, said = run(capsys, "help", command)
    assert rc == 0
    assert "No command called" not in said
    assert f"knos {command}" in said


def test_the_old_names_share_the_init_page():
    assert help_text.for_command("connect") == help_text.for_command("init")
    assert help_text.for_command("guard") == help_text.for_command("init")


def _flags_named_in_help():
    """(page, command words, flag) for every `--flag` shown in a `knos <cmd> ...` example line of a help page."""
    import typer

    from knos.cli import app

    group = typer.main.get_command(app)
    found = []
    for page, screen in help_text.PER_COMMAND.items():
        for line in screen.splitlines():
            m = re.match(r"\s*knos ([a-z-]+)((?: [^ ].*?)?)(?:\s{2,}.*)?$", line)
            if not m or m.group(1) not in group.commands:
                continue
            cmd, words = group.commands[m.group(1)], [m.group(1)]
            rest = m.group(2).split()
            if rest and hasattr(cmd, "commands") and rest[0] in cmd.commands:
                cmd, words = cmd.commands[rest[0]], words + [rest[0]]
            known = {o for p in cmd.params for o in (*p.opts, *p.secondary_opts)}
            for flag in re.findall(r"(?<![\w-])(--?[a-z][\w-]*)", m.group(2)):
                found.append((page, " ".join(words), flag, flag in known))
    return found


_BAD_FLAG = {}  # every bug once listed here is fixed; a new one goes here as a strict xfail


@pytest.mark.parametrize("page,command,flag,known", [
    pytest.param(*f, marks=pytest.mark.xfail(reason=_BAD_FLAG[(f[0], f[2])], strict=True))
    if (f[0], f[2]) in _BAD_FLAG else f
    for f in _flags_named_in_help()])
def test_every_flag_a_help_page_shows_exists(page, command, flag, known):
    """A help page that shows a flag the command refuses is a usage error the person was told to type."""
    assert known, f"`knos help {page}` shows `knos {command} {flag}`, which `knos {command}` does not take"


def test_help_runs(capsys):
    rc, said = run(capsys, "help")
    assert rc == 0
    assert "paste an agent PR" in said and "knos labs" in said


def test_help_for_one_command(capsys):
    rc, said = run(capsys, "help", "private")
    assert rc == 0
    assert "knos private notes/salary.md" in said


def test_help_for_a_command_that_does_not_exist(capsys):
    rc, said = run(capsys, "help", "teleport")
    assert rc == 0
    assert "No command called teleport" in said
    assert "knos help" in said


def test_no_help_screen_is_defined_twice():
    """A duplicate key in the help table silently wins, and the loser rots."""
    tree = ast.parse((ROOT / "src" / "knos" / "help.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "PER_COMMAND":
            names = [k.value for k in node.value.keys]
            assert len(names) == len(set(names)), f"defined twice: {names}"
            return
    raise AssertionError("PER_COMMAND not found")


# ---- errors are one line and a fix --------------------------------------------------------------------------


def test_a_usage_error_is_one_line_and_exit_two(capsys):
    rc, said = run(capsys, "claim")
    assert rc == 2
    assert "Traceback" not in said
    assert "See:  knos help" in said
    assert len([ln for ln in said.splitlines() if ln.strip()]) == 2, said


def test_an_unknown_command_is_a_usage_error(capsys):
    rc, said = run(capsys, "teleport")
    assert rc == 2
    assert "teleport" in said
    assert "See:  knos help" in said


def test_asking_somewhere_that_is_not_a_repo_says_so(knos_home, tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    rc, said = run(capsys, "ask", "anything")
    assert rc == 1
    assert "not a git repo" in said
    assert "knos point" in said
    assert "Traceback" not in said


@pytest.mark.parametrize("command", [["status"], ["notes"], ["compact"], ["claim", "x"], ["done"], ["reset", "--yes"],
                                     ["remember", "x"], ["worth"], ["who"], ["export"], ["restore"]])
def test_every_repo_command_outside_a_repo_says_so(command, knos_home, tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    rc, said = run(capsys, *command)
    assert rc == 1, said
    assert "not a git repo" in said


def test_point_at_a_folder_that_is_not_there(knos_home, capsys):
    rc, said = run(capsys, "point", "no/such/folder")
    assert rc == 1
    assert "No such folder" in said
    assert "knos point ." in said


def test_no_output_anywhere_mentions_a_stack_trace(knos_home, repo, capsys):
    for args in (["ask", "x"], ["status"], ["point", "nope"], ["help", "nope"], ["forget", "nope"], ["claim"],
                 ["init", "--hosts", "vscode"], ["reset"]):
        _, said = run(capsys, *args)
        assert "Traceback" not in said, args
        assert "Error:" not in said, args
        assert not re.search(r"\bknos[/\\.][a-z_]+\.py\b", said), args


def test_an_unforeseen_error_is_one_line_not_a_traceback(knos_home, repo, monkeypatch, capsys):
    from knos import worth

    def explode(*a, **k):
        raise KeyError("boom")

    monkeypatch.setattr(worth, "tally", explode)
    rc, said = run(capsys, "worth")
    assert rc == 1
    assert "knos stopped: KeyError" in said
    assert "Traceback" not in said


# ---- reading and asking ------------------------------------------------------------------------------------------


def test_the_first_question_reads_the_repo_by_itself(knos_home, repo, capsys):
    """Install, ask, answer. Running `point` first was a step between a person and the first thing knos is good for."""
    rc, said = run(capsys, "ask", "why did we drop redis")
    assert rc == 0, said
    assert "First time in repo" in said
    assert "redis" in said.lower()

    # And it does not read it again on the next question.
    rc, again = run(capsys, "ask", "why did we drop redis")
    assert rc == 0
    assert "First time in" not in again


def test_point_then_status_then_ask(knos_home, repo, capsys):
    rc, said = run(capsys, "point", str(repo))
    assert rc == 0, said
    assert "Read repo in" in said
    assert "new commits" in said

    rc, status = run(capsys, "status")
    assert rc == 0, status
    # each of Sibyl's tiers and how each behaves, so a person can see the store working rather than take it on trust
    for tier in ("journal", "warm", "claims", "reference", "archive"):
        assert tier in status, tier
    assert " MB" in status
    assert "notes exist nowhere else" in status
    assert "edit guard: off (knos init)" in status

    rc, asked = run(capsys, "ask", "why did we drop redis")
    assert rc == 0
    assert "redis" in asked.lower()


def test_point_never_deletes(knos_home, repo, capsys):
    run(capsys, "remember", "we deploy on tuesdays", "--about", "deploy window")
    rc, _ = run(capsys, "point")
    assert rc == 0
    _, notes = run(capsys, "notes")
    assert "deploy window: we deploy on tuesdays" in notes


def test_private_command(knos_home, repo, capsys):
    rc, said = run(capsys, "private", "notes/salary.md")
    assert rc == 0
    assert "is private" in said
    assert "agents cannot see it" in said


def test_remember_notes_forget(knos_home, repo, capsys):
    rc, said = run(capsys, "remember", "we deploy on tuesdays", "--about", "deploy window")
    assert rc == 0, said
    assert "Noted, under deploy window." in said

    _, notes = run(capsys, "notes")
    assert "deploy window: we deploy on tuesdays" in notes

    rc, said = run(capsys, "forget", "deploy window")
    assert rc == 0
    assert "Forgotten: deploy window." in said
    _, notes = run(capsys, "notes")
    assert "Nothing written down yet." in notes

    rc, said = run(capsys, "forget", "deploy window")
    assert rc == 1
    assert "Nothing written down about deploy window." in said
    assert "knos notes" in said


def test_compact_runs(knos_home, repo, capsys):
    run(capsys, "remember", "we deploy on tuesdays", "--about", "deploy window")
    run(capsys, "forget", "deploy window")

    rc, said = run(capsys, "compact")
    assert rc == 0, said
    assert re.search(r"\d+\.\d\d MB -> \d+\.\d\d MB", said), said
    # forgotten today, so not older than the default 30 days: kept
    assert "Dropped 0 forgotten note(s)." in said

    rc, said = run(capsys, "compact", "--older-than", "0")
    assert rc == 0, said
    assert re.search(r"Dropped \d+ forgotten note\(s\)\.", said), said


def test_reset_refuses_without_yes(knos_home, repo, capsys):
    from knos import paths

    run(capsys, "remember", "we deploy on tuesdays", "--about", "deploy window")
    assert paths.has_store(repo)

    rc, said = run(capsys, "reset")
    assert rc == 1
    assert "This starts repo's memory over" in said
    assert "knos reset --yes" in said
    assert paths.has_store(repo), "reset without --yes started over anyway"


def test_reset_with_yes_starts_over_and_keeps_a_backup(knos_home, repo, capsys):
    from knos import paths

    run(capsys, "remember", "we deploy on tuesdays", "--about", "deploy window")

    rc, said = run(capsys, "reset", "--yes")
    assert rc == 0, said
    assert "Started repo over." in said
    backups = list((knos_home / "backups").glob("repo-*"))
    assert len(backups) == 1 and backups[0].stat().st_size > 0, backups
    assert str(backups[0]) in said
    assert not paths.has_store(repo)


# ---- claims through the command line ---------------------------------------------------------------------------


def test_claim_then_done(knos_home, repo, capsys):
    from knos import cli, guard
    from knos.identity import Agent

    rc, said = run(capsys, "claim", "the login", "-p", "src/auth.py")
    assert rc == 0, said
    assert "Claimed src/auth.py for 30 min." in said
    assert "knos done" in said

    other = Agent(host="cursor", session="sess-other")
    assert not guard.check(repo, str(repo / "src" / "auth.py"), other).allow
    assert guard.check(repo, str(repo / "src" / "auth.py"), cli._me(repo)).allow, "the holder was refused"

    _, status = run(capsys, "status")
    assert "claimed" in status and "src/auth.py" in status

    rc, said = run(capsys, "done")
    assert rc == 0
    assert "Released src/auth.py (the login" in said
    assert guard.check(repo, str(repo / "src" / "auth.py"), other).allow

    rc, said = run(capsys, "done")
    assert rc == 0
    assert "You hold no claims here." in said


def test_claim_for_minutes(knos_home, repo, capsys):
    rc, said = run(capsys, "claim", "the readme", "-p", "README.md", "--for", "5")
    assert rc == 0, said
    assert "Claimed README.md for 5 min." in said


def test_claim_without_files_is_advisory(knos_home, repo, capsys):
    rc, said = run(capsys, "claim", "something vague about performance")
    assert rc == 0, said
    assert "advisory" in said
    assert "nothing is blocked" in said


def test_claim_held_by_another_agent_is_refused(knos_home, repo, capsys):
    from knos.claims import Claims
    from knos.identity import Agent

    with Claims(repo) as c:
        assert c.take(Agent(host="cursor", session="sess-other-1"), "the login", ["src/auth.py"])[0]

    rc, said = run(capsys, "claim", "mine", "-p", "src/**")
    assert rc == 1
    assert "Not claimed: src/auth.py is held by cursor/sess-oth" in said
    assert "knos done --all" in said


def test_done_all_asks_before_releasing_other_agents_claims(knos_home, repo, capsys):
    from knos.claims import Claims
    from knos.identity import Agent

    with Claims(repo) as c:
        c.take(Agent(host="cursor", session="sess-other-1"), "the login", ["src/auth.py"])

    rc, said = run(capsys, "done", "--all")
    assert rc == 1, "released another agent's claim without asking"
    assert "cursor/sess-oth" in said
    assert "Nothing released." in said
    assert "knos done --all --yes" in said
    with Claims(repo) as c:
        assert len(c.live()) == 1

    rc, said = run(capsys, "done", "--all", "--yes")
    assert rc == 0
    assert "Released src/auth.py (the login, cursor/sess-oth" in said
    with Claims(repo) as c:
        assert c.live() == []

    rc, said = run(capsys, "done", "--all")
    assert "Nothing is claimed here." in said


def test_done_releases_only_your_own(knos_home, repo, capsys):
    from knos.claims import Claims
    from knos.identity import Agent

    with Claims(repo) as c:
        c.take(Agent(host="cursor", session="sess-other-1"), "the login", ["src/auth.py"])

    rc, said = run(capsys, "done")
    assert rc == 0
    assert "You hold no claims here." in said
    with Claims(repo) as c:
        assert len(c.live()) == 1


# ---- knos init: wiring every agent, on a fake home --------------------------------------------------------------


def _home() -> Path:
    return Path.home()


def test_init_with_no_agent_installed_says_so(capsys):
    rc, said = _init(capsys)
    assert rc == 1
    assert "No coding agent found" in said
    assert "knos init --hosts claude" in said


def test_init_with_an_unknown_host_says_which(capsys):
    rc, said = _init(capsys, "--hosts", "vscode")
    assert rc == 1
    assert "unknown host vscode" in said
    assert "claude, codex, cursor, desktop, opencode" in said


def test_init_claude_code(capsys):
    rc, said = _init(capsys, "--hosts", "claude")
    assert rc == 0, said
    assert "Claude Code: memory server, edit guard and session notice" in said

    assert _json(_home() / ".claude.json")["mcpServers"]["knos"] == _server()
    hooks = _json(_home() / ".claude" / "settings.json")["hooks"]
    pre = hooks["PreToolUse"]
    assert [h["matcher"] for h in pre] == ["Edit|Write|MultiEdit|NotebookEdit", "Write|Bash"]
    assert "hook guard --client claude" in pre[0]["hooks"][0]["command"]
    start = hooks["SessionStart"]
    assert "hook start --client claude" in start[0]["hooks"][0]["command"]


def test_init_cursor(capsys):
    rc, said = _init(capsys, "--hosts", "cursor")
    assert rc == 0, said
    assert "Cursor: memory server, edit guard and session notice" in said
    assert "Restart Cursor: quit and reopen." in said

    assert _json(_home() / ".cursor" / "mcp.json")["mcpServers"]["knos"] == _server()
    hooks = _json(_home() / ".cursor" / "hooks.json")
    assert hooks["version"] == 1
    assert [h["command"] for h in hooks["hooks"]["preToolUse"]][0].count("hook guard --client cursor") == 1


def test_init_claude_desktop(capsys):
    rc, said = _init(capsys, "--hosts", "desktop")
    assert rc == 0, said
    assert "Claude Desktop: memory server" in said
    assert "Restart Claude Desktop" in said
    assert _json(setup.desktop_config())["mcpServers"]["knos"] == _server()


def test_init_opencode_gets_the_shape_opencode_reads(capsys):
    """OpenCode names the key `mcp`, marks a local server `"type": "local"`, and takes one command array. Writing
    Claude's shape into it would look like it worked and do nothing."""
    rc, said = _init(capsys, "--hosts", "opencode")
    assert rc == 0, said

    written = _json(setup.opencode_config())
    assert setup.opencode_config() == _home() / ".config" / "opencode" / "opencode.json"
    assert "mcpServers" not in written
    entry = written["mcp"]["knos"]
    assert entry == {"type": "local", "command": setup.server_command(), "enabled": True}
    assert written["$schema"] == "https://opencode.ai/config.json"

    plugin = _home() / ".config" / "opencode" / "plugin" / "knos-guard.js"
    assert "hook guard --client opencode" in plugin.read_text(encoding="utf-8")
    assert "tool.execute.before" in plugin.read_text(encoding="utf-8")


def test_opencode_config_location_follows_its_own_env_var(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("OPENCODE_CONFIG", str(tmp_path / "custom.json"))
    assert setup.opencode_config() == tmp_path / "custom.json"
    rc, _ = _init(capsys, "--hosts", "opencode")
    assert rc == 0
    assert _json(tmp_path / "custom.json")["mcp"]["knos"]["type"] == "local"


def test_init_codex_adds_one_table_and_keeps_the_rest(capsys):
    config = _home() / ".codex" / "config.toml"
    config.parent.mkdir(parents=True)
    original = '# my settings\nmodel = "o4"\n\n[mcp_servers.other]\ncommand = "npx"\n'
    config.write_text(original, encoding="utf-8")

    rc, said = _init(capsys, "--hosts", "codex")
    assert rc == 0, said
    assert "Codex: memory server, edit guard (apply_patch and shell writes)" in said
    hooks = json.loads((config.parent / "hooks.json").read_text(encoding="utf-8"))
    assert hooks["hooks"]["PreToolUse"][0]["matcher"] == "apply_patch|Bash"

    text = config.read_text(encoding="utf-8")
    assert text.startswith(original)
    cmd = setup.server_command()
    try:
        import tomllib
    except ImportError:  # Python 3.10
        assert "[mcp_servers.knos]" in text
    else:
        parsed = tomllib.loads(text)
        assert parsed["model"] == "o4"
        assert parsed["mcp_servers"]["other"] == {"command": "npx"}
        assert parsed["mcp_servers"]["knos"] == {"command": cmd[0], "args": cmd[1:]}


def test_init_adds_knos_and_keeps_everything_else(capsys):
    existing = {"somethingElse": "keep me", "mcpServers": {"filesystem": {"command": "npx", "args": ["-y", "fs"]}}}
    desktop = setup.desktop_config()
    desktop.parent.mkdir(parents=True)
    desktop.write_text(json.dumps(existing), encoding="utf-8")
    settings = _home() / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    mine = {"matcher": "Bash", "hooks": [{"type": "command", "command": "echo mine"}]}
    settings.write_text(json.dumps({"model": "opus", "hooks": {"PreToolUse": [mine]}}), encoding="utf-8")

    rc, said = _init(capsys, "--hosts", "desktop,claude")
    assert rc == 0, said

    after = _json(desktop)
    assert after["somethingElse"] == "keep me"
    assert after["mcpServers"]["filesystem"] == existing["mcpServers"]["filesystem"]
    assert after["mcpServers"]["knos"] == _server()
    hooks = _json(settings)
    assert hooks["model"] == "opus"
    assert hooks["hooks"]["PreToolUse"][0] == mine
    assert len(hooks["hooks"]["PreToolUse"]) == 3


def test_init_backs_up_every_file_it_changes(knos_home, capsys):
    mcp = _home() / ".cursor" / "mcp.json"
    mcp.parent.mkdir(parents=True)
    mcp.write_text('{"mcpServers": {}}', encoding="utf-8")

    rc, said = _init(capsys, "--hosts", "cursor")
    assert rc == 0

    runs = list((knos_home / "backups").glob("init-*"))
    assert len(runs) == 1, runs
    assert f"Copies of every file it changed: {runs[0]}" in said
    manifest = _json(runs[0] / "manifest.json")
    assert set(manifest) == {str(mcp), str(_home() / ".cursor" / "hooks.json")}
    kept = Path(manifest[str(mcp)]["backup"])
    assert kept.read_text(encoding="utf-8") == '{"mcpServers": {}}'
    assert manifest[str(_home() / ".cursor" / "hooks.json")]["backup"] is None, "hooks.json did not exist before"


def _every_file() -> list[Path]:
    return sorted({p for h in setup.HOSTS for p in setup.files_of(h)}, key=str)


def test_init_twice_changes_nothing(knos_home, capsys):
    rc, _ = _init(capsys, "--hosts", ",".join(setup.HOSTS))
    assert rc == 0
    first = {p: p.read_bytes() for p in _every_file()}
    assert len(first) == len(_every_file()), "some host got no file"
    runs = sorted((knos_home / "backups").glob("init-*/manifest.json"))

    rc, said = _init(capsys, "--hosts", ",".join(setup.HOSTS))
    assert rc == 0, said
    assert {p: p.read_bytes() for p in _every_file()} == first
    assert sorted((knos_home / "backups").glob("init-*/manifest.json")) == runs, "a second run backed something up"
    assert "Copies of every file it changed" not in said
    assert _json(_home() / ".cursor" / "hooks.json")["hooks"]["preToolUse"].__len__() == 1
    assert len(_json(_home() / ".claude" / "settings.json")["hooks"]["PreToolUse"]) == 2


def test_init_skips_an_agent_that_is_not_installed(capsys):
    (_home() / ".cursor").mkdir()

    rc, said = _init(capsys)
    assert rc == 0, said
    assert "Cursor" in said
    assert (_home() / ".cursor" / "mcp.json").exists()
    for absent in (_home() / ".claude.json", _home() / ".claude", setup.desktop_config().parent,
                   setup.codex_config(), setup.opencode_config()):
        assert not absent.exists(), absent


def test_init_leaves_a_config_it_cannot_read_alone(knos_home, capsys):
    """Somebody's editor settings are not a thing to guess at."""
    broken = _home() / ".cursor" / "mcp.json"
    broken.parent.mkdir(parents=True)
    broken.write_text("{ this is not json", encoding="utf-8")

    rc, said = _init(capsys, "--hosts", "cursor,desktop")
    assert rc == 1
    assert "Cursor:" in said and "is not readable JSON, so knos left it alone" in said
    assert broken.read_text(encoding="utf-8") == "{ this is not json"
    # the other agent is still wired
    assert _json(setup.desktop_config())["mcpServers"]["knos"] == _server()
    for manifest in (knos_home / "backups").glob("init-*/manifest.json"):
        assert str(broken) not in _json(manifest)


def test_init_leaves_a_settings_file_it_cannot_read_alone(capsys):
    settings = _home() / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text("[1, 2, 3]", encoding="utf-8")

    rc, said = _init(capsys, "--hosts", "claude")
    assert rc == 1
    assert "is not a JSON object, so knos left it alone" in said
    assert settings.read_text(encoding="utf-8") == "[1, 2, 3]"


def test_init_print_changes_nothing(capsys):
    rc, said = run(capsys, "init", "--print", "--hosts", "cursor,desktop")
    assert rc == 0
    assert "Would add this MCP server to: Cursor, Claude Desktop" in said
    assert setup.server_command()[0] in said
    assert not (_home() / ".cursor").exists()
    assert not setup.desktop_config().exists()


def test_connect_is_the_old_name_for_init(capsys):
    rc, said = run(capsys, "connect", "--print", "--hosts", "cursor")
    assert rc == 0
    assert "Would add this MCP server to: Cursor" in said


def test_claude_code_is_added_through_its_own_cli_when_that_exists(monkeypatch, capsys):
    """`claude mcp add` registers the server with a running session too, so its tools work without a restart; a
    running session has already read ~/.claude.json and will not read it again."""
    real_which, real_run = shutil.which, subprocess.run
    monkeypatch.setattr(shutil, "which", lambda name, *a, **k: "/usr/bin/claude" if name == "claude"
                        else real_which(name, *a, **k))
    calls = []

    def fake_run(cmd, *a, **kw):
        if cmd and cmd[0] == "/usr/bin/claude":
            calls.append(list(cmd))
            return subprocess.CompletedProcess(cmd, 0, "Added knos", "")
        return real_run(cmd, *a, **kw)

    monkeypatch.setattr(subprocess, "run", fake_run)

    rc, said = _init(capsys, "--hosts", "claude")
    assert rc == 0, said
    assert ["/usr/bin/claude", "mcp", "add", "--scope", "user", "knos", "--", *setup.server_command()] in calls
    assert not (_home() / ".claude.json").exists(), "it wrote the file by hand as well"
    assert (_home() / ".claude" / "settings.json").exists(), "the hooks still go in settings.json"
    assert not any("Restart Claude Code" in ln for ln in said.splitlines())

    calls.clear()
    rc, said = run(capsys, "init", "--undo", "--hosts", "claude")
    assert rc == 0
    assert ["/usr/bin/claude", "mcp", "remove", "--scope", "user", "knos"] in calls


def test_without_the_claude_cli_the_config_file_is_written(capsys):
    rc, _ = _init(capsys, "--hosts", "claude")
    assert rc == 0
    assert _json(_home() / ".claude.json")["mcpServers"]["knos"]["args"] == setup.server_command()[1:]


def test_the_server_command_is_an_absolute_path_or_this_interpreter(monkeypatch):
    """A GUI app starts the server with its own PATH and no shell profile, so a bare `knos` would not be found."""
    monkeypatch.setattr(shutil, "which", lambda name, *a, **k: None)
    monkeypatch.setattr(setup, "own_script", lambda: None)
    assert setup.server_command() == [sys.executable, "-m", "knos", "mcp"]
    fake = str(Path("/opt/pipx/bin/knos"))
    monkeypatch.setattr(shutil, "which", lambda name, *a, **k: fake if name == "knos" else None)
    assert setup.server_command() == [fake, "mcp"]
    # the script installed beside this interpreter wins over whatever `knos` is first on PATH
    mine = str(Path("/venv/bin/knos"))
    monkeypatch.setattr(setup, "own_script", lambda: mine)
    assert setup.server_command() == [mine, "mcp"]


@pytest.mark.parametrize("platform", ["linux", "darwin", "win32"])
def test_config_paths_resolve_on_every_platform(platform, monkeypatch):
    monkeypatch.setattr(setup.sys, "platform", platform)
    where = setup.mcp_files()
    assert sorted(where) == sorted(setup.HOSTS)
    home = _home()
    desktop = {"linux": home / ".config" / "Claude", "darwin": home / "Library" / "Application Support" / "Claude",
               "win32": home / "AppData" / "Roaming" / "Claude"}[platform]
    assert where["desktop"] == desktop / "claude_desktop_config.json"
    assert where["cursor"] == home / ".cursor" / "mcp.json"
    assert where["codex"] == home / ".codex" / "config.toml"


def test_init_names_the_exact_restart_for_each_app_that_needs_one():
    """"Restart your agents" makes a person guess which app and how. Claude Code is absent: `claude mcp add` and the
    hooks reach a running session."""
    assert set(setup.RESTART) == {"desktop", "cursor", "opencode", "codex"}
    for host, line in setup.RESTART.items():
        assert line.startswith(setup.NAMES[host] + ":"), line
        assert line.endswith("."), line


# ---- knos init --undo --------------------------------------------------------------------------------------------


def _seed() -> dict[Path, bytes]:
    """A home where a person already configured things, in their own formatting."""
    seeded = {
        _home() / ".cursor" / "mcp.json": b'{"mcpServers":{"fs":{"command":"npx"}},"x":1}',
        _home() / ".claude" / "settings.json": b'{\n    "hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": []}]}\n}',
        setup.codex_config(): b'# mine\nmodel = "o4"\n',
        setup.desktop_config(): b'{"mcpServers": {}}\r\n',
    }
    for path, raw in seeded.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    return seeded


def test_undo_restores_every_file_byte_for_byte(capsys):
    seeded = _seed()
    created = [p for p in _every_file() if p not in seeded]

    rc, said = _init(capsys, "--hosts", ",".join(setup.HOSTS))
    assert rc == 0, said
    assert all(p.read_bytes() != raw for p, raw in seeded.items())

    rc, said = run(capsys, "init", "--undo")
    assert rc == 0, said
    for name in setup.NAMES.values():
        assert f"Removed from {name}." in said
    for path, raw in seeded.items():
        assert path.read_bytes() == raw, path
    for path in created:
        assert not path.exists(), f"{path} was made by knos init and is still there"


def test_undo_after_a_person_edited_the_file_removes_only_knos(capsys):
    mcp = _home() / ".cursor" / "mcp.json"
    mcp.parent.mkdir(parents=True)
    mcp.write_text('{"mcpServers": {"fs": {"command": "npx"}}}', encoding="utf-8")
    rc, _ = _init(capsys, "--hosts", "cursor")
    assert rc == 0

    data = _json(mcp)
    data["mcpServers"]["added-later"] = {"command": "uvx"}
    mcp.write_text(json.dumps(data), encoding="utf-8")

    rc, said = run(capsys, "init", "--undo", "--hosts", "cursor")
    assert rc == 0, said
    assert "Removed from Cursor." in said
    after = _json(mcp)
    assert "knos" not in after["mcpServers"]
    assert set(after["mcpServers"]) == {"fs", "added-later"}
    assert not (_home() / ".cursor" / "hooks.json").exists() or "knos-guard" not in (
        _home() / ".cursor" / "hooks.json").read_text(encoding="utf-8")


def test_undo_when_nothing_was_installed(capsys):
    rc, said = run(capsys, "init", "--undo")
    assert rc == 0
    assert "Nothing to remove" in said


def test_undo_leaves_an_unreadable_file_alone(capsys):
    rc, _ = _init(capsys, "--hosts", "cursor")
    assert rc == 0
    mcp = _home() / ".cursor" / "mcp.json"
    mcp.write_text("{ broken since", encoding="utf-8")

    rc, said = run(capsys, "init", "--undo", "--hosts", "cursor")
    assert "not readable JSON, so knos left it alone" in said
    assert mcp.read_text(encoding="utf-8") == "{ broken since"


# ---- the hidden old names -----------------------------------------------------------------------------------------


def test_guard_shows_whether_each_agent_is_guarded(capsys):
    rc, said = run(capsys, "guard")
    assert rc == 0
    assert re.search(r"cursor\s+not wired", said)
    assert "knos init wires it" in said

    _init(capsys, "--hosts", "cursor")
    rc, said = run(capsys, "guard")
    assert re.search(r"cursor\s+guarding", said)
    assert re.search(r"claude\s+not wired", said)


def test_guard_install_and_uninstall_are_init_and_undo(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (_home() / ".cursor").mkdir()
    tested = []
    monkeypatch.setattr(setup, "selftest", lambda *a, **k: tested.append(1) or [])

    rc, said = run(capsys, "guard", "--install")
    assert rc == 0, said
    assert tested, "guard --install skipped the self-test knos init runs"
    assert "knos-guard" in (_home() / ".cursor" / "hooks.json").read_text(encoding="utf-8")

    rc, said = run(capsys, "guard", "--uninstall")
    assert rc == 0, said
    assert not (_home() / ".cursor" / "hooks.json").exists()
    assert not (_home() / ".cursor" / "mcp.json").exists()


def test_a_config_written_by_0_1_still_starts_the_server(monkeypatch):
    """0.1 wrote `knos plane mcp` into host configs; after an upgrade that must still start the server."""
    import types

    import knos

    started = []
    fake = types.ModuleType("knos.mcp")
    fake.main = lambda: started.append(1)
    monkeypatch.setitem(sys.modules, "knos.mcp", fake)
    monkeypatch.setattr(knos, "mcp", fake, raising=False)
    assert main(["plane", "mcp"]) == 0
    assert started == [1]


def test_hook_guard_exits_zero_when_it_breaks(monkeypatch):
    from knos import guard_hook

    def explode(argv=None):
        raise RuntimeError("boom")

    monkeypatch.setattr(guard_hook, "main", explode)
    assert main(["hook", "guard", "--client", "claude"]) == 0
    assert main(["hook", "nonsense"]) == 0


def test_init_self_test_starts_the_server_and_the_guard(capsys):
    """The one test that starts the memory server the way an agent does: handshake, the memory tools, and the guard
    allowing an empty edit."""
    rc, said = run(capsys, "init", "--hosts", "cursor", "--no-read")
    assert rc == 0, said
    assert "Self-test passed" in said


def test_init_reads_the_repo_it_is_run_in(knos_home, repo, capsys):
    from knos import paths

    rc, said = run(capsys, "init", "--hosts", "cursor", "--no-test")
    assert rc == 0, said
    assert "read repo into Sibyl memory" in said
    assert paths.has_store(repo)


# ---- the files that carry the product -----------------------------------------------------------------------------


def test_the_plugin_manifests_agree_with_the_package():
    """Two ways in, one server. A version or command that drifts between them is a broken install for whoever
    picked that path."""
    version = re.search(r'^version = "([^"]+)"', (ROOT / "pyproject.toml").read_text(encoding="utf-8"),
                        re.M).group(1)

    market = _json(ROOT / ".claude-plugin" / "marketplace.json")
    assert market["plugins"][0]["source"] == "./plugins/knos"
    assert market["plugins"][0]["version"] == version

    plugin = _json(ROOT / "plugins" / "knos" / ".claude-plugin" / "plugin.json")
    assert plugin["version"] == version
    assert plugin["mcpServers"]["knos"] == {"command": "knos", "args": ["mcp"]}


def test_every_check_command_in_the_readme_selects_a_real_test():
    """The README tells a stranger to run these to verify each claim. A renamed test would leave an instruction that
    quietly selects nothing. Collection happens once, not once per command."""
    import shlex

    commands = re.findall(r"`(pytest [^`]+)`", "".join((ROOT / f).read_text(encoding="utf-8") for f in ("README.md", "docs/LABS.md")))
    assert commands, "the README stopped offering any way to check it"

    done = subprocess.run(
        [sys.executable, "-m", "pytest", "-m", "", "-o", "addopts=", "-p", "no:cacheprovider", "--collect-only", "-q"],
        cwd=str(ROOT), capture_output=True, text=True, timeout=600)
    ids = [line.strip() for line in done.stdout.splitlines() if "::" in line]
    assert ids, f"nothing collected at all: {done.stdout[-2000:]}"

    for command in commands:
        args = shlex.split(command)[1:]
        files = [a for a in args if a.endswith(".py")]
        selector = args[args.index("-k") + 1] if "-k" in args else ""
        picked = ids
        if files:
            wanted = {p.replace("\\", "/") for p in files}
            picked = [i for i in picked if i.replace("\\", "/").split("::")[0] in wanted]
            assert picked, f"README says `{command}` but that file has no tests"
        if selector:
            words = [w for w in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", selector) if w not in {"or", "and", "not"}]
            picked = [i for i in picked if any(w in i for w in words)]
        assert picked, f"README says `{command}` but that selects no tests"
