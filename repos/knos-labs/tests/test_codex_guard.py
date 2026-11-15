"""Codex's PreToolUse hook: apply_patch bodies and shell writes are guarded like any other edit.

The payload shape is Codex's documented one (developers.openai.com/codex/hooks, read 30 Sep 2026): `tool_name` is
`apply_patch` or `Bash`, and both carry the text in `tool_input.command`. A refusal is the same hookSpecificOutput
deny as Claude Code's, plus exit 2.
"""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

from knos import guard
from knos.claims import Claims
from knos.identity import Agent

HOLDER = Agent(host="claude", session="alice123-holder-session")

PATCH = """*** Begin Patch
*** Update File: src/auth.py
@@
-def login():
+def login(user):
*** Add File: src/new.py
+x = 1
*** Update File: src/old.py
*** Move to: src/renamed.py
*** End Patch"""


def test_patch_paths():
    assert guard.patch_paths(PATCH) == ["src/auth.py", "src/new.py", "src/old.py", "src/renamed.py"]
    assert guard.patch_paths("") == []


@pytest.mark.parametrize("cmd,want", [
    ("echo hi > src/auth.py", ["src/auth.py"]),
    ("cat a >> logs/x.txt 2>/dev/null", ["logs/x.txt"]),
    ("sed -i 's/a/b/' src/auth.py src/b.py", ["src/auth.py", "src/b.py"]),
    ("sed -i.bak -e 's/a/b/' src/auth.py", ["src/auth.py"]),
    ("git mv src/auth.py src/login.py && git status", ["src/auth.py", "src/login.py"]),
    ("cp templates/a.py src/auth.py", ["src/auth.py"]),
    ("mv src/auth.py /tmp/x", ["src/auth.py", "/tmp/x"]),
    ("rm -f src/auth.py; ls", ["src/auth.py"]),
    ("printf x | tee -a src/auth.py", ["src/auth.py"]),
    ("FOO=1 touch src/new.py", ["src/new.py"]),
    ("ls -la && git diff", []),
    ("python -c 'open(\"x\",\"w\")'", []),  # not visible: the commit guard is the backstop
    ("echo ok 2>&1", []),
])
def test_shell_writes(cmd, want):
    assert guard.shell_writes(cmd) == want


def _codex(repo, tool, command, session="codex-session-1"):
    payload = {"session_id": session, "cwd": str(repo), "hook_event_name": "PreToolUse", "tool_name": tool,
               "tool_use_id": "call_1", "tool_input": {"command": command}}
    return subprocess.run([sys.executable, "-m", "knos.guard_hook", "--client", "codex"], input=json.dumps(payload),
                          capture_output=True, text=True, cwd=str(repo), timeout=60)


@pytest.fixture()
def claimed(knos_home, repo):
    with Claims(repo) as c:
        took, _, _ = c.take(HOLDER, "auth rework", ["src/auth.py"])
    assert took
    return repo


def test_codex_apply_patch_to_a_claimed_file_is_refused(claimed):
    got = _codex(claimed, "apply_patch", PATCH)
    assert got.returncode == 2, got.stdout + got.stderr
    out = json.loads(got.stdout)["hookSpecificOutput"]
    assert out["permissionDecision"] == "deny" and "claimed by claude/alice123" in out["permissionDecisionReason"]


def test_codex_shell_write_to_a_claimed_file_is_refused(claimed):
    got = _codex(claimed, "Bash", "sed -i 's/True/False/' src/auth.py")
    assert got.returncode == 2
    assert "(Knos)" in json.loads(got.stdout)["hookSpecificOutput"]["permissionDecisionReason"]


def test_codex_reads_and_unclaimed_writes_pass(claimed):
    assert _codex(claimed, "Bash", "cat src/auth.py && git log -1").returncode == 0
    assert _codex(claimed, "apply_patch", "*** Begin Patch\n*** Add File: docs/x.md\n+hi\n*** End Patch").returncode == 0
    assert _codex(claimed, "mcp__fs__read", "src/auth.py").returncode == 0


def test_codex_hook_install_and_undo_keep_other_hooks(knos_home, tmp_path, monkeypatch):
    path = guard.codex_hooks()
    path.parent.mkdir(parents=True, exist_ok=True)
    mine = {"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "my-policy"}]}]}}
    path.write_text(json.dumps(mine), encoding="utf-8")
    guard.install_codex()
    guard.install_codex()  # idempotent
    got = json.loads(path.read_text(encoding="utf-8"))["hooks"]["PreToolUse"]
    assert len(got) == 2 and got[0]["hooks"][0]["command"] == "my-policy"
    assert guard.installed()["codex"]
    assert guard.uninstall_codex()
    assert json.loads(path.read_text(encoding="utf-8")) == mine


# ---- Copilot cloud agent: .github/hooks/*.json preToolUse (docs.github.com hooks reference, read 30 Sep 2026) ----

def test_copilot_edit_and_bash_are_guarded(claimed):
    for payload in ({"sessionId": "cp1", "cwd": str(claimed), "toolName": "edit",
                     "toolArgs": {"path": "src/auth.py", "old_str": "a", "new_str": "b"}},
                    {"sessionId": "cp1", "cwd": str(claimed), "toolName": "bash",
                     "toolArgs": json.dumps({"command": "echo x >> src/auth.py"})}):
        out, code = guard.run("copilot", json.dumps(payload))
        assert code == guard.REFUSE, payload
        assert json.loads(out)["permissionDecision"] == "deny"
    out, code = guard.run("copilot", json.dumps({"sessionId": "cp1", "cwd": str(claimed), "toolName": "view",
                                                  "toolArgs": {"path": "src/auth.py"}}))
    assert (out, code) == ("", guard.ALLOW)


def test_copilot_template_fails_open_when_knos_is_missing():
    """Copilot's preToolUse is fail-closed on any non-zero exit but 2, so a missing knos must exit 0."""
    from pathlib import Path
    tpl = json.loads((Path(__file__).parent.parent / ".github" / "hooks" / "knos.json.example").read_text())
    cmd = tpl["hooks"]["preToolUse"][0]["bash"]
    assert tpl["version"] == 1 and '|| exit 0' in cmd and '= 2 ] && exit 2' in cmd
