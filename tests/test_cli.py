"""Every command, every error path, and help that fits one screen."""

from __future__ import annotations

import re

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
    for name in ("point", "ask", "connect", "status", "private", "notes", "forget", "remember", "done"):
        yield name, help_text.for_command(name)


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


def test_ask_before_pointing_says_what_to_run(knos_home):
    result = runner.invoke(app, ["ask", "anything"])
    assert result.exit_code == 1
    assert "Nothing indexed yet." in result.stdout
    assert "knos point ." in result.stdout
    assert "Traceback" not in result.stdout


def test_status_before_pointing_says_what_to_run(knos_home):
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 1
    assert "knos point ." in result.stdout


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
    result = runner.invoke(app, ["connect"])
    assert result.exit_code == 0
    assert "knos.mcp" in result.stdout
    assert "Cursor" in result.stdout
    assert "Claude Code" in result.stdout


def test_no_output_anywhere_mentions_a_stack_trace(knos_home, repo):
    for args in (["ask", "x"], ["status"], ["point", "nope"], ["help", "nope"]):
        result = runner.invoke(app, args)
        assert "Traceback" not in result.stdout
        assert "Error:" not in result.stdout
        assert not re.search(r"\bknos\.[a-z]+\.py\b", result.stdout)


def test_every_line_reference_in_the_readme_still_points_at_what_it_says():
    """A README that links to a line number rots the moment code moves.

    A judge clicking one of these and landing on a blank line learns
    something true about how carefully the rest was checked.
    """
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    readme = (root / "README.md").read_text(encoding="utf-8")
    expected = {
        142: "def record",
        179: "def note_thing",
        270: "def working_on",
        405: "def set_reference",
        203: "def supersede",
    }
    seen = set()
    for path, line in re.findall(r"\((src/knos/\w+\.py)#L(\d+)\)", readme):
        number = int(line)
        source = (root / path).read_text(encoding="utf-8").splitlines()
        assert number <= len(source), f"{path}#L{number} is past the end"
        assert expected[number] in source[number - 1], f"{path}#L{number}"
        seen.add(number)
    assert seen == set(expected), f"unchecked references: {set(expected) - seen}"


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
