"""Proof: AI agent work counts only when Knos proves it. The Stop hook blocks an unproven "done", lets a stop through
after 3 blocks on unchanged evidence, the safety guard refuses unread overwrites and deletes outside the repo, and
Sibyl history is load-bearing: the replay of Knos's own releases."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from knos.proof import checks, claims, engine, history, hook, receipt

import _replay as replay

DATA = Path(__file__).parent / "data" / "release_replay.json"


def _sibyl(tmp_path):
    from sibyl_memory_client import MemoryClient
    return history.SibylStore(MemoryClient.local(str(tmp_path / "proof.db"), tenant_id="repo"))


def test_claims_are_read_by_kind_not_phrasing():
    c = claims.read("Knos 0.3.4 is shipped: tagged, on PyPI, 801 passed, CI is green. "
                    "Removed src/knos/bundle.py. Live at https://drexthealpha.github.io/Knos/.")
    assert {"release", "pypi", "tests", "ci", "deleted", "urls"} <= c.kinds
    assert c.deleted == ["src/knos/bundle.py"] and c.urls == ["https://drexthealpha.github.io/Knos/"]
    assert c.version == "0.3.4"
    assert not claims.read("I looked at the parser; here is what I think we should do.").says_done


def test_replay_sibyl_blocks_031_and_032_and_null_store_passes_them(tmp_path, repo):
    data = json.loads(DATA.read_text(encoding="utf-8"))
    store = _sibyl(tmp_path)
    replay.seed(store, data["history"])
    assert {r["require"] for r in history.rules(store)} == {"ci"}          # learned from 0.2.0 false done
    got = {v: ok for v, ok, _ in replay.with_sibyl(store, data["replay"], repo)}
    assert got == {"0.3.0": True, "0.3.1": False, "0.3.2": False, "0.3.3": True}
    base = {v: ok for v, ok, _ in replay.null_baseline(data["replay"], repo)}
    assert base == {"0.3.0": True, "0.3.1": True, "0.3.2": True, "0.3.3": True}   # wrongly passes 0.3.1, 0.3.2
    assert {x.failed for x in history.lint(store)} == {"ci"}


def test_the_stop_hook_blocks_then_lets_go_after_three_on_unchanged_evidence(tmp_path, repo, knos_home):
    payload = {"cwd": str(repo), "session_id": "s1", "last_assistant_message": "All done: CI is green."}
    fail = {"ci": lambda r, c, cfg: checks.Result("ci", False, "CI failed for abc", {"sha": "abc"})}
    said = [hook.stop(payload, history.NullStore(), fail)[0] for _ in range(4)]
    assert said == ["block", "block", "block", "warn"]
    ok = {"ci": lambda r, c, cfg: checks.Result("ci", True, "green", {"sha": "abc"})}
    assert hook.stop(payload, history.NullStore(), ok)[0] == "allow"
    assert hook.stop({**payload, "last_assistant_message": "Here is a plan."}, history.NullStore())[0] == "allow"


def test_the_stop_hook_reads_claude_codes_transcript(tmp_path):
    t = tmp_path / "t.jsonl"
    t.write_text("\n".join(json.dumps(r) for r in [
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "working"}]}},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "Shipped; tests pass."}]}}]) + "\n",
        encoding="utf-8")
    assert hook.last_message({"transcript_path": str(t)}) == "Shipped; tests pass."


def test_safety_refuses_unread_overwrites_and_deletes_outside_the_repo(tmp_path, repo):
    f = repo / "notes.md"
    f.write_text("mine", encoding="utf-8")
    t = tmp_path / "t.jsonl"
    t.write_text("", encoding="utf-8")
    base = {"cwd": str(repo), "transcript_path": str(t)}
    assert "never read it" in hook.safety({**base, "tool_name": "Write", "tool_input": {"file_path": str(f)}})
    t.write_text(json.dumps({"message": {"content": [{"type": "tool_use", "name": "Read",
                                                      "input": {"file_path": str(f)}}]}}) + "\n", encoding="utf-8")
    assert hook.safety({**base, "tool_name": "Write", "tool_input": {"file_path": str(f)}}) is None
    outside = Path(Path(str(repo)).anchor) / "knos-not-yours"   # outside the repo and the temp dir
    assert "outside this repository" in hook.safety({**base, "tool_name": "Bash",
                                                     "tool_input": {"command": f"rm -rf {outside}"}})
    assert hook.safety({**base, "tool_name": "Bash", "tool_input": {"command": "rm -rf build/"}}) is None


def test_checks_run_by_knos_not_the_agent(tmp_path, repo):
    assert not checks.deleted(repo, ["README.md"]).ok if (repo / "README.md").exists() else True
    assert checks.deleted(repo, ["nope.txt"]).ok
    assert checks.urls(["https://x.test/a"], getter=lambda u: (404, b"")).ok is False
    assert checks.urls(["https://x.test/a"], getter=lambda u: (200, b"")).ok
    (repo / "pyproject.toml").write_text('[project]\nname = "demo-pkg"\nversion = "9.9.9"\n', encoding="utf-8")
    assert checks.pypi(repo, getter=lambda u: (404, b"")).ok is False
    runs = {("run", "list"): (0, json.dumps([{"databaseId": 1, "status": "completed", "conclusion": "failure",
                                               "workflowName": "tests"}])),
            ("run", "view"): (0, json.dumps({"jobs": [{"name": "pytest", "conclusion": "failure"}]}))}
    got = checks.ci(repo, "abc123", runner=lambda a: runs[tuple(a[:2])])
    assert not got.ok and "tests/pytest: failure" in got.detail


def test_receipt_root_commits_to_every_check():
    ev = [{"name": "ci", "ok": True, "evidence": {"sha": "a"}}, {"name": "tests", "ok": True, "evidence": {}}]
    r1 = receipt.merkle_root(receipt.leaves(ev))
    ev[0]["evidence"]["sha"] = "b"
    assert receipt.merkle_root(receipt.leaves(ev)) != r1 and len(r1) == 32


def test_init_installs_the_stop_and_safety_hooks(knos_home, tmp_path, monkeypatch):
    from knos import guard
    monkeypatch.setattr(guard, "claude_settings", lambda: tmp_path / "settings.json")
    guard.install_claude()
    hooks = json.loads((tmp_path / "settings.json").read_text())["hooks"]
    assert "hook proof" in json.dumps(hooks["Stop"]) and "hook safety" in json.dumps(hooks["PreToolUse"])
    assert guard.uninstall_claude() and "hooks" not in json.loads((tmp_path / "settings.json").read_text()) or \
        "Stop" not in json.loads((tmp_path / "settings.json").read_text()).get("hooks", {})


def test_ci_reads_gh_json_followed_by_a_notice(tmp_path):
    from knos.proof import checks
    notice = "\nA new release of gh is available: 2.80.0\n"

    def gh(args):
        if args[1] == "list":
            return 0, '[{"databaseId": 1, "status": "completed", "conclusion": "failure", "workflowName": "ci"}]' + notice
        return 0, '{"jobs": [{"name": "tests", "conclusion": "failure"}]}' + notice
    r = checks.ci(tmp_path, "a" * 40, runner=gh)
    assert not r.ok and "ci/tests: failure" in r.detail
