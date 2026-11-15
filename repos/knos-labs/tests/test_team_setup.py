"""`knos init --team` and the commit guard: the guard travels with the repo, and `init --undo` takes it all back
byte for byte."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from knos import commit_guard, guard, team_setup
from knos.cli import main


def _sha(p: Path) -> str | None:
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None


@pytest.fixture()
def no_claude(monkeypatch):
    monkeypatch.setenv("KNOS_NO_CLAUDE_CLI", "1")


def test_init_team_writes_repo_hooks_and_undo_restores_every_byte(knos_home, repo, no_claude, capsys):
    settings = repo / ".claude" / "settings.json"
    settings.parent.mkdir()
    settings.write_text('{"permissions": {"allow": ["Bash(ls)"]}}\n', encoding="utf-8")
    hooks = commit_guard.hooks_dir(repo)
    hooks.mkdir(parents=True, exist_ok=True)
    (hooks / "pre-commit").write_text("#!/bin/sh\necho mine\n", encoding="utf-8")
    before = {p: _sha(p) for p in (settings, repo / ".codex" / "hooks.json", hooks / "pre-commit",
                                    hooks / "pre-push")}

    assert main(["init", "--hosts", "cursor", "--no-test", "--no-read", "--team"]) == 0
    data = json.loads(settings.read_text(encoding="utf-8"))
    assert data["permissions"] == {"allow": ["Bash(ls)"]}
    assert data["enabledPlugins"]["knos@knos"] is True
    assert data["extraKnownMarketplaces"]["knos"]["source"]["repo"] == "drexthealpha/Knos"
    cmd = data["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
    assert cmd.startswith("knos hook guard --client claude")  # bare knos: the file is committed
    assert str(Path.home()) not in settings.read_text(encoding="utf-8")
    codex = json.loads((repo / ".codex" / "hooks.json").read_text(encoding="utf-8"))
    assert codex["hooks"]["PreToolUse"][0]["matcher"] == "apply_patch|Bash"
    pre = (hooks / "pre-commit").read_text(encoding="utf-8")
    assert pre.startswith("#!/bin/sh\n") and "knos-guard" in pre and "echo mine" in pre
    assert team_setup.installed(repo) == {"claude_repo": True, "codex_repo": True, "commit": True}

    assert main(["init", "--undo", "--hosts", "cursor"]) == 0
    after = {p: _sha(p) for p in before}
    assert after == before


def test_undo_takes_only_knos_entries_from_a_file_edited_since(knos_home, repo, no_claude):
    from knos import init as setup
    setup.install(["cursor"], repo)
    settings = repo / ".claude" / "settings.json"
    data = json.loads(settings.read_text(encoding="utf-8"))
    data["theme"] = "dark"  # the person edited it since
    settings.write_text(json.dumps(data), encoding="utf-8")
    setup.undo(["cursor"], repo)
    left = json.loads(settings.read_text(encoding="utf-8"))
    assert left.get("theme") == "dark" and "knos-guard-repo" not in json.dumps(left)
    assert not commit_guard.installed(repo)


def test_guard_answers_once_per_tool_use_id(knos_home, repo):
    calls = []

    def compute():
        calls.append(1)
        return guard.Verdict(False, "claimed (Knos)")

    event = {"tool_use_id": "toolu_123"}
    first = guard.once(event, compute)
    second = guard.once(event, compute)
    assert first == second and len(calls) == 1
    guard.once({"tool_use_id": "toolu_other"}, compute)
    assert len(calls) == 2


def test_commit_guard_passes_without_a_team(knos_home, repo):
    (repo / "src" / "auth.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    assert commit_guard.run("commit", repo) == 0
