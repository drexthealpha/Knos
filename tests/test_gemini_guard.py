"""Gemini CLI's BeforeTool hook: file writes and shell writes are guarded like any other edit.

The payload shape is Gemini CLI's documented one (https://geminicli.com/docs/hooks/, read 01 Oct 2026):
hook_event_name is "BeforeTool", tool_name is e.g. write_file, replace_file_content, run_command,
with arguments in tool_input. A refusal exits 2 with {"decision": "deny", "reason": ...}.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from knos import guard, init as setup
from knos.claims import Claims
from knos.identity import Agent

HOLDER = Agent(host="claude", session="alice123-holder-session")


def _gemini(repo, tool, args, session="gemini-session-1"):
    payload = {
        "session_id": session,
        "cwd": str(repo),
        "hook_event_name": "BeforeTool",
        "tool_name": tool,
        "tool_input": args if isinstance(args, dict) else {"command": args},
    }
    return subprocess.run([sys.executable, "-m", "knos.guard_hook", "--client", "gemini"],
                          input=json.dumps(payload),
                          capture_output=True, text=True, cwd=str(repo), timeout=60)


@pytest.fixture()
def claimed(knos_home, repo):
    with Claims(repo) as c:
        took, _, _ = c.take(HOLDER, "auth rework", ["src/auth.py"])
    assert took
    return repo


def test_gemini_file_write_to_a_claimed_file_is_refused(claimed):
    for tool, args in [
        ("write_file", {"file_path": "src/auth.py", "content": "secret"}),
        ("write_to_file", {"TargetFile": str(claimed / "src" / "auth.py"), "CodeContent": "x"}),
        ("replace_file_content", {"TargetFile": "src/auth.py", "ReplacementContent": "y"}),
    ]:
        got = _gemini(claimed, tool, args)
        assert got.returncode == 2, got.stdout + got.stderr
        out = json.loads(got.stdout)
        assert out["decision"] == "deny"
        assert "claimed by claude/alice123" in out["reason"] or "(Knos)" in out["reason"]


def test_gemini_shell_write_to_a_claimed_file_is_refused(claimed):
    for tool, args in [
        ("run_command", {"CommandLine": "sed -i 's/True/False/' src/auth.py"}),
        ("run_shell_command", {"command": "echo hi > src/auth.py"}),
        ("Bash", {"command": "truncate -s 0 src/auth.py"}),
    ]:
        got = _gemini(claimed, tool, args)
        assert got.returncode == 2, got.stdout + got.stderr
        out = json.loads(got.stdout)
        assert out["decision"] == "deny"
        assert "(Knos)" in out["reason"]


def test_gemini_reads_and_unclaimed_writes_pass(claimed):
    assert _gemini(claimed, "run_shell_command", {"command": "cat src/auth.py && git log -1"}).returncode == 0
    assert _gemini(claimed, "read_file", {"file_path": "src/auth.py"}).returncode == 0
    assert _gemini(claimed, "write_file", {"file_path": "src/other.py", "content": "ok"}).returncode == 0


def test_gemini_hook_install_and_undo_keep_other_hooks(knos_home, tmp_path, monkeypatch):
    path = guard.gemini_settings()
    path.parent.mkdir(parents=True, exist_ok=True)
    mine = {"hooks": {"BeforeTool": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "my-policy"}]}]}}
    path.write_text(json.dumps(mine), encoding="utf-8")
    guard.install_gemini()
    guard.install_gemini()  # idempotent
    got = json.loads(path.read_text(encoding="utf-8"))["hooks"]["BeforeTool"]
    assert len(got) == 2 and got[0]["hooks"][0]["command"] == "my-policy"
    assert guard.installed()["gemini"]
    assert guard.uninstall_gemini()
    assert json.loads(path.read_text(encoding="utf-8")) == mine


def test_gemini_init_undo_restores_file_byte_for_byte(knos_home, capsys):
    path = guard.gemini_settings()
    path.parent.mkdir(parents=True, exist_ok=True)
    original_raw = b'{\n  "theme": "dark",\n  "hooks": {}\n}\n'
    path.write_bytes(original_raw)

    rep = setup.install(["gemini"])
    assert any("Gemini CLI" in d for d in rep.done)
    assert path.read_bytes() != original_raw

    un_rep = setup.undo(["gemini"])
    assert "Gemini CLI" in un_rep.done
    assert path.read_bytes() == original_raw
