"""The guard refuses an edit, or it is not a guard.

Everything else in this suite checks that knos declines to *answer*. These
check the one place it declines to let something happen, which is the only
part of knos with the authority to be actively wrong. So the cases that
matter most here are the ones where it must stay out of the way: an unclaimed
file, a claim held by the agent asking, a broken store, a payload it does not
understand.

The hook is exercised the way a client runs it — a real subprocess reading
real JSON on stdin — because the thing being tested is an exit code and a
contract with somebody else's runner, not a Python function.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from knos import guard
from knos.memory import Memory


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _rules(repo: Path, name: str, text: str) -> None:
    """Write an instruction file the way the repo would have it.

    `rules.files` asks git which instruction files this repo keeps, so that a
    vendored dependency's CLAUDE.md is never quoted as the rule here. An
    untracked file is invisible to that, which is correct and means a test
    has to commit its fixture like a person would.
    """
    (repo / name).write_text(text, encoding="utf-8")
    subprocess.run(["git", "add", name], cwd=str(repo), check=True, capture_output=True)


def _claim(repo: Path, topic: str, who: str) -> None:
    with Memory(repo) as mem:
        took, _ = mem.claim_if_free(topic, who, _now())
        assert took, f"{who} could not take {topic}"


# --- what it refuses --------------------------------------------------------


def test_an_edit_to_claimed_work_is_refused(knos_home, repo):
    """The whole point: a claim on a subject reaches the file that is it."""
    _claim(repo, "the parser", "Claude Code")
    target = repo / "src" / "parser" / "lexer.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("x = 1\n", encoding="utf-8")

    verdict = guard.check(repo, str(target), "Cursor")

    assert not verdict.allow
    assert "Claude Code" in verdict.reason
    assert "the parser" in verdict.reason


def test_a_rule_that_names_a_path_is_enforced(knos_home, repo):
    """A path rule is a pattern, so the guard may act on it."""
    _rules(
        repo,
        "AGENTS.md",
        "# Rules\n\nNever edit `src/generated/` by hand. It is written by the\n"
        "code generator and your change will be lost on the next build.\n",
    )
    target = repo / "src" / "generated" / "client.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("# generated\n", encoding="utf-8")

    verdict = guard.check(repo, str(target), "Claude Code")

    assert not verdict.allow
    assert "AGENTS.md" in verdict.reason
    assert "src/generated/" in verdict.reason


# --- what it must not refuse ------------------------------------------------


def test_an_unclaimed_file_is_left_alone(knos_home, repo):
    target = repo / "README.md"
    target.write_text("hello\n", encoding="utf-8")
    assert guard.check(repo, str(target), "Cursor").allow


def test_the_agent_holding_the_claim_may_edit_it(knos_home, repo):
    """A claim is how you take work, not how you lock yourself out of it."""
    _claim(repo, "the parser", "Claude Code")
    target = repo / "src" / "parser" / "lexer.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("x = 1\n", encoding="utf-8")

    assert guard.check(repo, str(target), "Claude Code").allow


def test_a_rule_with_no_path_in_it_is_not_enforced(knos_home, repo):
    """"Write idiomatic code" is not a pattern, and guessing at one is how a
    guard starts refusing edits nobody asked it to refuse."""
    _rules(
        repo,
        "CLAUDE.md",
        "# Rules\n\nNever write code that is hard to read. Prefer clarity to\n"
        "cleverness in every module here.\n",
    )
    target = repo / "anything.py"
    target.write_text("x = 1\n", encoding="utf-8")

    assert guard.path_rules(repo) == []
    assert guard.check(repo, str(target), "Cursor").allow


def test_a_backticked_word_that_is_not_a_path_is_ignored(knos_home, repo):
    _rules(
        repo,
        "AGENTS.md",
        "# Rules\n\nNever run `pytest` against a real store. Use a throwaway\n"
        "one, which the fixtures already build for you.\n",
    )
    assert guard.path_rules(repo) == []


def test_an_unreadable_store_allows_the_edit(knos_home, repo, monkeypatch):
    """Fail open, on purpose.

    A guard that fails closed puts a broken install between somebody and
    their own repository. That is a worse day than the collision it exists
    to prevent, so this is a decision rather than an oversight.
    """
    _claim(repo, "the parser", "Claude Code")
    target = repo / "src" / "parser" / "lexer.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("x = 1\n", encoding="utf-8")

    def broken(*a, **k):
        raise OSError("store is gone")

    monkeypatch.setattr(guard, "Memory", broken)
    assert guard.check(repo, str(target), "Cursor").allow


def test_a_file_outside_the_repo_is_not_ours_to_refuse(knos_home, repo, tmp_path):
    _claim(repo, "the parser", "Claude Code")
    stranger = tmp_path / "elsewhere" / "parser.py"
    stranger.parent.mkdir(parents=True, exist_ok=True)
    stranger.write_text("x = 1\n", encoding="utf-8")
    assert guard.check(repo, str(stranger), "Cursor").allow


# --- the shape each client reads -------------------------------------------


@pytest.mark.parametrize("client", guard.CLIENTS)
def test_a_payload_with_no_path_in_it_is_allowed(client):
    """Every hook fires on calls the guard has no opinion about."""
    out, code = guard.run(client, json.dumps({"tool_name": "Bash", "tool_input": {}}))
    assert code == guard.ALLOW
    assert out == ""


@pytest.mark.parametrize("client", guard.CLIENTS)
def test_nonsense_on_stdin_is_allowed(client):
    assert guard.run(client, "not json at all")[1] == guard.ALLOW
    assert guard.run(client, "")[1] == guard.ALLOW


def test_each_client_is_refused_in_its_own_words(knos_home, repo):
    """The exit code is the refusal; the JSON is how each client explains it."""
    _claim(repo, "the parser", "Claude Code")
    target = repo / "src" / "parser" / "lexer.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("x = 1\n", encoding="utf-8")

    payloads = {
        "claude": {"tool_name": "Edit", "tool_input": {"file_path": str(target)}, "cwd": str(repo)},
        "cursor": {"file_path": str(target), "cwd": str(repo)},
        "opencode": {"args": {"filePath": str(target)}, "cwd": str(repo)},
    }
    for client, payload in payloads.items():
        out, code = guard.run(client, json.dumps(payload))
        assert code == guard.REFUSE, client
        said = json.loads(out)
        if client == "claude":
            assert said["hookSpecificOutput"]["permissionDecision"] == "deny"
            assert "Claude Code" in said["hookSpecificOutput"]["permissionDecisionReason"]
        elif client == "cursor":
            assert said["permission"] == "deny"
            assert "Claude Code" in said["user_message"]
        else:
            assert said["deny"] is True
            assert "Claude Code" in said["reason"]


def test_the_hook_runs_as_a_real_process_and_exits_two(knos_home, repo):
    """What a client actually does: run a command, write JSON, read the code.

    A unit test on `run()` cannot catch an entry point that does not start,
    so this one pays for a subprocess.
    """
    _claim(repo, "the parser", "Claude Code")
    target = repo / "src" / "parser" / "lexer.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("x = 1\n", encoding="utf-8")

    payload = json.dumps(
        {"tool_name": "Edit", "tool_input": {"file_path": str(target)}, "cwd": str(repo)}
    )
    done = subprocess.run(
        [sys.executable, "-m", "knos.guard_hook", "--client", "claude"],
        input=payload,
        capture_output=True,
        text=True,
        env={**__import__("os").environ, "KNOS_HOME": str(knos_home)},
        timeout=120,
    )
    assert done.returncode == guard.REFUSE, done.stderr
    assert "Claude Code" in done.stdout


# --- installing and taking it back out --------------------------------------


def test_install_then_uninstall_leaves_nothing_behind(knos_home, tmp_path, monkeypatch):
    """The guard is opt-in, so getting back out has to be exact."""
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))

    settings = tmp_path / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text(json.dumps({"hooks": {"PreToolUse": []}, "theme": "dark"}), encoding="utf-8")

    guard.install_claude()
    guard.install_cursor()
    guard.install_opencode()
    assert all(guard.installed().values())

    assert guard.uninstall_claude()
    assert guard.uninstall_cursor()
    assert guard.uninstall_opencode()
    assert not any(guard.installed().values())

    # Somebody else's settings survived the round trip.
    assert json.loads(settings.read_text(encoding="utf-8"))["theme"] == "dark"


def test_installing_twice_does_not_stack_up_hooks(knos_home, tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))

    for _ in range(3):
        guard.install_claude()
        guard.install_cursor()

    claude = json.loads(guard.claude_settings().read_text(encoding="utf-8"))
    assert len(claude["hooks"]["PreToolUse"]) == 1
    cursor = json.loads(guard.cursor_hooks().read_text(encoding="utf-8"))
    assert len(cursor["hooks"]["preToolUse"]) == 1


def test_the_file_it_edits_is_backed_up_first(knos_home, tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    settings = tmp_path / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text('{"theme": "dark"}', encoding="utf-8")

    guard.install_claude()

    kept = settings.with_name("settings.json.before-knos")
    assert kept.is_file()
    assert json.loads(kept.read_text(encoding="utf-8")) == {"theme": "dark"}
