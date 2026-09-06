"""Every command, every error path, and help that fits one screen."""

from __future__ import annotations

import re
import subprocess
import sys

import pytest
from typer.testing import CliRunner

from knos import help as help_text
from knos.cli import app

runner = CliRunner()

# Words a developer would have to look up, or that describe knos's insides
# rather than their repo.
JARGON = [
    "mcp",
    "stdio",
    "tier",
    "entity",
    "schema",
    "index",
    "sqlite",
    "traceback",
    "exception",
    "serialize",
    "daemon",
    "onchain",
    "wallet",
    "gas",
]


def _screens():
    yield "help", help_text.main()
    for name in ("point", "ask", "connect", "status", "private", "notes", "forget", "remember", "claim", "done"):
        yield name, help_text.for_command(name)


@pytest.mark.critical
def test_the_cli_and_the_handshake_report_the_same_version():
    """One number, read from package metadata, so it cannot drift.

    A client that is told the empty string cannot say which knos it is
    talking to, and a person who runs --version should get the same answer.
    """
    from knos import version

    said = subprocess.run(
        [sys.executable, "-c", "from knos.cli import app; app()", "--version"],
        capture_output=True, text=True, encoding="utf-8",
    )

    assert said.returncode == 0
    assert said.stdout.strip() == version()
    assert version() not in ("", "0+unknown")


def test_help_fits_one_screen():
    lines = help_text.main().splitlines()
    assert len(lines) <= 24, f"{len(lines)} lines"
    assert max(len(line) for line in lines) <= 80


@pytest.mark.parametrize("name,screen", list(_screens()))
def test_no_jargon_anywhere(name, screen):
    low = screen.lower()
    for word in JARGON:
        assert word not in low, f"{name} says {word!r}"


@pytest.mark.parametrize("name,screen", list(_screens()))
def test_every_screen_fits_eighty_columns(name, screen):
    assert max(len(line) for line in screen.splitlines()) <= 80


def test_help_runs():
    result = runner.invoke(app, ["help"])
    assert result.exit_code == 0
    assert "in your code right now" in result.stdout


def test_help_for_one_command():
    result = runner.invoke(app, ["help", "private"])
    assert result.exit_code == 0
    assert "knos private .env" in result.stdout


def test_help_for_a_command_that_does_not_exist():
    result = runner.invoke(app, ["help", "teleport"])
    assert "No command called teleport" in result.stdout
    assert "knos help" in result.stdout


def test_asking_somewhere_that_is_not_a_repo_says_so(knos_home, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["ask", "anything"])
    assert result.exit_code == 1
    assert "not a git repo" in result.stdout
    assert "Traceback" not in result.stdout


def test_status_somewhere_that_is_not_a_repo_says_so(knos_home, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 1
    assert "not a git repo" in result.stdout


def test_the_first_question_reads_the_repo_by_itself(knos_home, repo, monkeypatch):
    """Install, ask, answer. Running `point` first was a step and a concept
    between a person and the first thing knos is good for."""
    asked = runner.invoke(app, ["ask", "why did we drop redis"])
    assert asked.exit_code == 0, asked.stdout
    assert "First time in repo" in asked.stdout
    assert "redis" in asked.stdout.lower()

    # And it does not read it again on the next question.
    again = runner.invoke(app, ["ask", "why did we drop redis"])
    assert "First time in" not in again.stdout


def test_point_at_a_folder_that_is_not_there(knos_home):
    result = runner.invoke(app, ["point", "no/such/folder"])
    assert result.exit_code == 1
    assert "No such folder" in result.stdout
    assert "knos point ." in result.stdout


def test_point_then_status_then_ask(knos_home, repo, monkeypatch, tmp_path):
    monkeypatch.setenv("KNOS_CLAUDE_HOME", str(tmp_path / "absent"))
    monkeypatch.setenv("KNOS_CURSOR_DB", str(tmp_path / "absent.vscdb"))

    assert runner.invoke(app, ["point", str(repo)]).exit_code == 0

    status = runner.invoke(app, ["status"])
    assert status.exit_code == 0
    # status shows each of Sibyl's five tiers and how each one behaves,
    # so a person can see the store working rather than take it on trust.
    for tier in ("journal", "warm", "hot", "reference", "archive"):
        assert tier in status.stdout, tier
    assert "things learned" in status.stdout
    assert "MB of 5 MB used" in status.stdout

    asked = runner.invoke(app, ["ask", "why did we drop redis"])
    assert asked.exit_code == 0
    assert "redis" in asked.stdout.lower()


def test_private_command(knos_home, repo, monkeypatch, tmp_path):
    monkeypatch.setenv("KNOS_CLAUDE_HOME", str(tmp_path / "absent"))
    monkeypatch.setenv("KNOS_CURSOR_DB", str(tmp_path / "absent.vscdb"))
    runner.invoke(app, ["point", str(repo)])
    result = runner.invoke(app, ["private", "notes/salary.md"])
    assert result.exit_code == 0
    assert "is private" in result.stdout
    assert "agents cannot see it" in result.stdout


def test_connect_prints_something_copyable(knos_home):
    """--print is the by-hand path. Plain `knos connect` does it for you."""
    result = runner.invoke(app, ["connect", "--print"])
    assert result.exit_code == 0
    assert "knos.mcp" in result.stdout
    assert "Cursor" in result.stdout
    assert "Claude Code" in result.stdout
    # And it says how to stop doing it by hand.
    assert "knos connect" in result.stdout


def test_no_output_anywhere_mentions_a_stack_trace(knos_home, repo):
    for args in (["ask", "x"], ["status"], ["point", "nope"], ["help", "nope"]):
        result = runner.invoke(app, args)
        assert "Traceback" not in result.stdout
        assert "Error:" not in result.stdout
        assert not re.search(r"\bknos\.[a-z]+\.py\b", result.stdout)


def test_every_source_reference_in_the_docs_still_exists():
    """Docs used to name a line number, which drifted every time the file
    changed — five times. They name the method now, and this checks it is
    still there."""
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    doc = (root / "docs" / "core-flow.md").read_text(encoding="utf-8")
    named = re.findall(r"\[`Memory\.(\w+)`\]\(\.\./(src/knos/\w+\.py)\)", doc)
    assert named, "the walkthrough stopped naming any source at all"
    for method, path in named:
        source = (root / path).read_text(encoding="utf-8")
        assert f"def {method}(" in source, f"{path} has no {method}"


def _configs(tmp_path):
    return [
        ("Claude Desktop", str(tmp_path / "Claude" / "claude_desktop_config.json")),
        ("Cursor", str(tmp_path / ".cursor" / "mcp.json")),
    ]


def test_connect_write_adds_knos_and_keeps_everything_else(tmp_path, monkeypatch):
    """Hand-editing JSON was the last step markdown did not ask of you."""
    import json

    from knos import cli

    (tmp_path / "Claude").mkdir()
    (tmp_path / ".cursor").mkdir()
    existing = {
        "somethingElse": "keep me",
        "mcpServers": {"filesystem": {"command": "npx", "args": ["-y", "fs"]}},
    }
    desktop = tmp_path / "Claude" / "claude_desktop_config.json"
    desktop.write_text(json.dumps(existing), encoding="utf-8")

    monkeypatch.setattr(cli, "_config_files", lambda: _configs(tmp_path))
    cli._write_configs("C:/python.exe")

    after = json.loads(desktop.read_text(encoding="utf-8"))
    assert after["somethingElse"] == "keep me"
    assert "filesystem" in after["mcpServers"]
    assert after["mcpServers"]["knos"] == {
        "command": "C:/python.exe",
        "args": ["-m", "knos.mcp"],
    }
    assert desktop.with_suffix(".json.before-knos").exists()
    # a client with no config yet gets one
    assert "knos" in json.loads(
        (tmp_path / ".cursor" / "mcp.json").read_text(encoding="utf-8")
    )["mcpServers"]


def test_connect_write_is_idempotent(tmp_path, monkeypatch):
    import json

    from knos import cli

    (tmp_path / "Claude").mkdir()
    (tmp_path / ".cursor").mkdir()
    monkeypatch.setattr(cli, "_config_files", lambda: _configs(tmp_path))

    cli._write_configs("C:/python.exe")
    first = (tmp_path / ".cursor" / "mcp.json").read_text(encoding="utf-8")
    cli._write_configs("C:/python.exe")
    assert (tmp_path / ".cursor" / "mcp.json").read_text(encoding="utf-8") == first
    assert len(json.loads(first)["mcpServers"]) == 1


def test_connect_write_refuses_to_touch_a_config_it_cannot_parse(tmp_path, monkeypatch):
    """Somebody's editor settings are not a thing to guess at."""
    from knos import cli

    (tmp_path / "Claude").mkdir()
    (tmp_path / ".cursor").mkdir()
    broken = tmp_path / "Claude" / "claude_desktop_config.json"
    broken.write_text("{ this is not json", encoding="utf-8")

    monkeypatch.setattr(cli, "_config_files", lambda: _configs(tmp_path))
    cli._write_configs("C:/python.exe")

    assert broken.read_text(encoding="utf-8") == "{ this is not json"
    assert not broken.with_suffix(".json.before-knos").exists()


def test_connect_write_skips_a_client_that_is_not_installed(tmp_path, monkeypatch):
    from knos import cli

    monkeypatch.setattr(cli, "_config_files", lambda: _configs(tmp_path))
    cli._write_configs("C:/python.exe")  # neither folder exists
    assert not (tmp_path / "Claude").exists()
    assert not (tmp_path / ".cursor").exists()


def test_no_help_screen_is_defined_twice():
    """A duplicate key in the help table silently wins, and the loser rots."""
    import ast
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "src/knos/help.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "PER_COMMAND":
            names = [k.value for k in node.value.keys]
            assert len(names) == len(set(names)), f"defined twice: {names}"
            return
    raise AssertionError("PER_COMMAND not found")


def test_the_one_screen_says_what_a_markdown_file_cannot_do():
    """The claim has to be in the product, not only in the README."""
    screen = help_text.main()
    assert "in your code right now" in screen
    assert "CLAUDE.md cannot do that" in screen
    assert "one local memory every coding agent on this machine shares" in screen


def test_the_plugin_and_extension_manifests_agree_with_the_package():
    """Three ways in, one server. A version or command that drifts between
    them is a broken install for whoever picked that path."""
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    version = re.search(
        r'^version = "([^"]+)"',
        (root / "pyproject.toml").read_text(encoding="utf-8"),
        re.M,
    ).group(1)

    manifest = json.loads(
        (root / "extension" / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["version"] == version
    assert [t["name"] for t in manifest["tools"]] == ["search", "about", "remember"]

    # The extension resolves knos itself, with uv, from the pyproject beside
    # its entry point. That is what makes it one click, so the three things
    # that carry it are asserted rather than assumed: the runtime, the pinned
    # dependency, and the absence of the user_config that used to ask a
    # person to find and paste a Python path.
    assert manifest["manifest_version"] == "0.4"
    assert manifest["server"]["type"] == "uv"
    assert "user_config" not in manifest
    deps = (root / "extension" / "pyproject.toml").read_text(encoding="utf-8")
    assert f'"knos=={version}"' in deps, "the extension must pin this version"

    market = json.loads(
        (root / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8")
    )
    assert market["plugins"][0]["source"] == "./plugins/knos"
    assert market["plugins"][0]["version"] == version

    plugin = json.loads(
        (root / "plugins" / "knos" / ".claude-plugin" / "plugin.json").read_text(
            encoding="utf-8"
        )
    )
    assert plugin["version"] == version
    assert plugin["mcpServers"]["knos"]["args"] == ["-m", "knos.mcp"]


def test_the_readme_leads_with_the_problem_and_the_action():
    """A stranger scanning the first screen must not have to guess.

    Rewritten three times now, and every rewrite was about who is reading.
    It first asserted the MCP server and its three tools were on the first
    screen; then the pull request check; then where the memory is written.

    It now asserts the first screen leads with the thing that costs a reader
    nothing: the Action, copyable, with no install in front of it. Almost
    nobody wants to run a server to find out whether a tool is worth running,
    so the server is no longer what greets them. What moved is checked below
    rather than dropped - the store, the deletion test and the three tools
    are all still in the file.
    """
    from pathlib import Path

    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text(
        encoding="utf-8"
    )
    first = readme[:1800]
    assert "same thing" in first, "the first screen does not state the problem"
    assert "knos demo" in first, "the one command a judge runs is not on the first screen"
    assert "install" in first.lower(), "the first screen does not address the cost"

    # The Action and the copyable workflow moved down one screen when `knos
    # demo` took the top. They are still the zero-install path and must still
    # be reachable without scrolling far.
    near = readme[:5200]
    assert "drexthealpha/Knos/action@" in near, "the Action fell too far down"
    assert "knos-claims.yml" in near, "no workflow a maintainer can copy"

    # The embeddable core is the other zero-server path, and is named early.
    assert "knos.core" in readme[:4000], "the importable core is not near the top"

    # Moved, not dropped.
    assert "memory.db" in readme, "the store is no longer named anywhere"
    assert "test_sibyl_is_load_bearing" in readme, "the deletion test is gone"
    assert "pull_request" in readme
    for tool in ("search", "about", "remember"):
        assert tool in readme, tool


def test_claude_code_is_added_through_its_own_cli_when_that_exists(
    knos_home, tmp_path, monkeypatch
):
    """`claude mcp add` registers the server with the running session, so its
    tools work without a restart. Writing ~/.claude.json by hand does not:
    a session already running has read that file and will not read it again.
    """
    from knos import cli

    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)

        class Done:
            returncode = 0
            stdout = "Added knos"
            stderr = ""

        return Done()

    monkeypatch.setattr(cli, "_claude_cli", lambda: "/usr/bin/claude")
    monkeypatch.setattr("subprocess.run", fake_run)
    monkeypatch.setattr(cli, "_config_files", lambda: [("Claude Code", str(tmp_path / ".claude.json"))])

    result = runner.invoke(app, ["connect"])
    assert result.exit_code == 0
    assert calls, "never asked the claude CLI"
    assert calls[0][1:4] == ["mcp", "add", "--scope"]
    assert calls[0][-2:] == ["-m", "knos.mcp"]
    assert "nothing to restart" in result.stdout
    # And it did not also write the file by hand.
    assert not (tmp_path / ".claude.json").exists()


def test_without_the_claude_cli_the_config_is_written_and_a_restart_is_asked_for(
    knos_home, tmp_path, monkeypatch
):
    import json

    from knos import cli

    monkeypatch.setattr(cli, "_claude_cli", lambda: None)
    target = tmp_path / ".claude.json"
    monkeypatch.setattr(cli, "_config_files", lambda: [("Claude Code", str(target))])

    result = runner.invoke(app, ["connect"])
    assert result.exit_code == 0
    assert "Restart" in result.stdout
    assert json.loads(target.read_text(encoding="utf-8"))["mcpServers"]["knos"]["args"] == [
        "-m",
        "knos.mcp",
    ]


def test_opencode_gets_the_shape_opencode_reads(knos_home, tmp_path, monkeypatch):
    """OpenCode names the key `mcp`, marks a local server `"type": "local"`,
    and takes one command array. Writing Claude's shape into it would look
    like it worked and do nothing."""
    import json

    from knos import cli

    target = tmp_path / "opencode.json"
    monkeypatch.setattr(cli, "_claude_cli", lambda: None)
    monkeypatch.setattr(cli, "_config_files", lambda: [("OpenCode", str(target))])

    assert runner.invoke(app, ["connect"]).exit_code == 0
    written = json.loads(target.read_text(encoding="utf-8"))
    assert "mcpServers" not in written
    knos_entry = written["mcp"]["knos"]
    assert knos_entry["type"] == "local"
    assert knos_entry["command"][-2:] == ["-m", "knos.mcp"]
    assert knos_entry["enabled"] is True
    assert written["$schema"] == "https://opencode.ai/config.json"

    # Run twice: it must not duplicate or rewrite.
    assert runner.invoke(app, ["connect"]).exit_code == 0
    assert "already has it" in runner.invoke(app, ["connect"]).stdout


def test_opencode_config_location_follows_its_own_env_var(monkeypatch, tmp_path):
    from knos import cli

    monkeypatch.setenv("OPENCODE_CONFIG", str(tmp_path / "custom.json"))
    where = dict((n, w) for n, w in cli._config_files())
    assert where["OpenCode"].endswith("custom.json")


def test_every_check_command_in_the_readme_selects_a_real_test():
    """The README tells a stranger to run these to verify each claim. A
    renamed test would leave an instruction that quietly selects nothing,
    which is worse than not offering the check at all.

    Collection happens once, not once per command. Spawning a pytest for
    each backtick cost eight minutes and grew every time the README offered
    another check, which is a good way to make people stop offering them.
    """
    import re
    import shlex
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    commands = re.findall(
        r"`(pytest [^`]+)`", (root / "README.md").read_text(encoding="utf-8")
    )
    assert commands, "the README stopped offering any way to check it"

    # -m "" clears the critical-path default in pyproject, so non-critical
    # tests named in the README still show up here.
    done = subprocess.run(
        [sys.executable, "-m", "pytest", "-m", "", "--collect-only", "-q"],
        cwd=str(root),
        capture_output=True,
        text=True,
    )
    ids = [line.strip() for line in done.stdout.splitlines() if "::" in line]
    assert ids, f"nothing collected at all: {done.stdout[-2000:]}"

    for command in commands:
        args = shlex.split(command)[1:]
        paths = [a for a in args if a.endswith(".py")]
        selector = ""
        if "-k" in args:
            selector = args[args.index("-k") + 1]

        picked = ids
        if paths:
            wanted = {p.replace("\\", "/") for p in paths}
            picked = [i for i in picked if i.replace("\\", "/").split("::")[0] in wanted]
            assert picked, f"README says `{command}` but that file has no tests"
        if selector:
            # -k takes an expression; the names in it are what must exist.
            words = [
                w
                for w in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", selector)
                if w not in {"or", "and", "not"}
            ]
            picked = [i for i in picked if any(w in i for w in words)]
        assert picked, f"README says `{command}` but that selects no tests"


@pytest.mark.parametrize("platform", ["linux", "darwin", "win32"])
def test_config_paths_resolve_on_every_platform(platform, monkeypatch, tmp_path):
    """A stale `import os` inside the Windows branch made `os` local to the
    whole function, so every non-Windows caller hit UnboundLocalError before
    it could read OPENCODE_CONFIG. It passed on Windows and broke `knos
    connect` on Linux and macOS.
    """
    from knos import cli

    monkeypatch.setattr(cli.sys, "platform", platform)
    monkeypatch.setattr(cli.Path, "home", staticmethod(lambda: tmp_path))
    monkeypatch.delenv("OPENCODE_CONFIG", raising=False)

    where = dict(cli._config_files())
    assert sorted(where) == ["Claude Code", "Claude Desktop", "Cursor", "OpenCode"]
    assert all(w for w in where.values())


def test_connect_names_the_exact_restart_for_each_client_that_needs_one():
    """`knos connect` telling somebody to "restart your agents" makes them
    guess which app and how. Each line names the app and the keystroke, and
    Claude Code is deliberately absent because it needs no restart."""
    from knos.cli import RESTART

    assert set(RESTART) == {"Cursor", "Claude Desktop", "OpenCode"}
    assert "Claude Code" not in RESTART
    for name, line in RESTART.items():
        assert name in line, name
        assert line.endswith(".") or line.endswith(")"), line


def test_every_command_has_a_help_page():
    """`knos help export` said "No command called export" while export was
    in the command list and worked. Help drifted from the CLI because
    nothing compared them."""
    from knos import help as knos_help
    from knos.cli import app

    commands = {c.name or (c.callback and c.callback.__name__) for c in app.registered_commands}
    commands = {c.replace("_cmd", "").replace("_", "-") for c in commands if c}
    commands -= {"help"}  # help itself is the thing being asked for
    missing = sorted(c for c in commands if c not in knos_help.PER_COMMAND)
    assert not missing, f"no `knos help` page for: {missing}"
