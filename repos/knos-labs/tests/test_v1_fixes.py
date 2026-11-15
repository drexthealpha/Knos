"""One regression test (at least) for each of the ten defects fixed in 0.2.0. Each test names the defect it pins."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from knos import guard, identity, paths
from knos.claims import Claims
from knos.cli import main
from knos.identity import Agent
from knos.memory import Memory


def _run(capsys, *argv: str) -> tuple[int, str]:
    rc = main(list(argv))
    got = capsys.readouterr()
    return rc, got.out + got.err


# 1. point was a delete-and-reread that threw away notes; it is now incremental, and starting over is explicit.
@pytest.mark.critical
def test_1_point_never_deletes_what_was_written(repo, capsys) -> None:
    assert _run(capsys, "remember", "the deploy window is Tuesday", "--about", "deploys")[0] == 0
    assert _run(capsys, "point")[0] == 0
    with Memory(repo) as mem:
        assert mem.remembered("deploys")


def test_1_reset_asks_and_keeps_a_backup(repo, capsys) -> None:
    _run(capsys, "remember", "keep me", "--about", "k")
    rc, said = _run(capsys, "reset")
    assert rc == 1 and "--yes" in said
    rc, said = _run(capsys, "reset", "--yes")
    assert rc == 0 and "Backup:" in said
    backups = list((paths.home() / "backups").glob(f"{repo.name}-*"))
    assert backups and backups[0].stat().st_size > 0


def test_1_a_second_point_writes_nothing_twice(repo) -> None:
    from knos import refresh

    refresh.ensure(repo, force=True, index_code=False)
    with Memory(repo) as mem:
        before = len(mem.journal(limit=100000))
    counts = refresh.ensure(repo, force=True, index_code=False)
    with Memory(repo) as mem:
        assert len(mem.journal(limit=100000)) == before
    assert counts["known"] > 0


# 2. MCP, hooks and CLI each had their own idea of who an agent was; now one identity: (host, session, host pid).
@pytest.mark.critical
def test_2_the_hook_and_the_server_see_the_same_agent(repo, monkeypatch) -> None:
    monkeypatch.setattr(identity, "anchor_for", lambda host, chain=None: 4242)
    hook_agent = identity.for_hook("claude", {"session_id": "abc123", "cwd": str(repo)})
    with Claims(repo) as c:
        c.record_session(hook_agent.host, hook_agent.session, hook_agent.anchor)
    from knos.claims import lookup_session

    mcp_agent = identity.for_mcp("claude-code", lookup_session(repo))
    assert (mcp_agent.host, mcp_agent.session) == ("claude", "abc123")
    with Claims(repo) as c:
        c.take(mcp_agent, "auth", ["src/auth.py"])
    assert guard.check(repo, str(repo / "src/auth.py"), hook_agent).allow


# 3. `done` released everybody's claims; now only your own, and --all asks.
@pytest.mark.critical
def test_3_done_releases_only_your_own(repo, capsys, monkeypatch) -> None:
    with Claims(repo) as c:
        c.take(Agent("cursor", "other"), "auth", ["src/auth.py"])
    monkeypatch.setattr("knos.cli._me", lambda r: Agent("terminal", "me"))
    rc, said = _run(capsys, "done")
    assert rc == 0 and "no claims" in said
    with Claims(repo) as c:
        assert len(c.live()) == 1
    rc, said = _run(capsys, "done", "--all")  # not a terminal: asks, so refuses
    assert rc == 1
    with Claims(repo) as c:
        assert len(c.live()) == 1
    assert _run(capsys, "done", "--all", "--yes")[0] == 0
    with Claims(repo) as c:
        assert c.live() == []


# 4. Claims were words matched against words, so unrelated work was blocked; now paths, advisory when nothing resolves.
@pytest.mark.critical
def test_4_text_similarity_never_blocks(repo) -> None:
    with Claims(repo) as c:
        took, _, mine = c.take(Agent("claude", "a"), "rework the login and auth flow")
    assert took and mine.advisory
    assert guard.check(repo, str(repo / "src/auth.py"), Agent("cursor", "b")).allow


def test_4_overlapping_globs_conflict_and_disjoint_ones_do_not(repo) -> None:
    with Claims(repo) as c:
        assert c.take(Agent("a", "1"), "parser", ["src/parser/**"])[0]
        assert not c.take(Agent("b", "2"), "one file", ["src/parser/lex.py"])[0]
        assert c.take(Agent("b", "2"), "docs", ["docs/**"])[0]
        assert not c.take(Agent("c", "3"), "everything", ["src/**"])[0]


# 5. Answers about claimed work were withheld; now they are always given, with who holds what.
@pytest.mark.critical
def test_5_claimed_work_is_annotated_never_hidden(repo) -> None:
    from knos import mcp

    with Claims(repo) as c:
        c.take(Agent("cursor", "other"), "the login code", ["src/auth.py"])
    said = mcp.search("login redis sqlite")
    assert "[claimed]" in said and "cursor" in said
    assert "redis" in said.lower()  # the answer itself is there


# 6. The server answered from whichever repo was last pointed at; outside a repo it now says so.
@pytest.mark.critical
def test_6_no_wrong_repo_fallback(repo, tmp_path, monkeypatch) -> None:
    from knos import mcp

    elsewhere = tmp_path / "not-a-repo"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    assert mcp.search("redis") == mcp.NOT_A_REPO
    assert mcp.remember("x", "y") == mcp.NOT_A_REPO


# 7. `knos demo` crashed, and errors were tracebacks; errors are one line and the script entry is main().
def test_7_demo_runs(capsys) -> None:
    rc, said = _run(capsys, "demo", "--fast")
    assert rc == 0, said
    assert "allowed = False" in said and "took it" in said


def test_7_errors_are_one_line_not_a_traceback(tmp_path, capsys, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    rc, said = _run(capsys, "ask", "anything", "--in", str(tmp_path / "missing"))
    assert rc == 1 and "Traceback" not in said and len(said.strip().splitlines()) <= 2
    rc, said = _run(capsys, "notes")  # not in a repo
    assert rc == 1 and "Traceback" not in said
    rc, said = _run(capsys, "no-such-command")
    assert rc == 2 and "Traceback" not in said


def test_7_console_script_is_main() -> None:
    text = (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    assert 'knos = "knos.cli:main"' in text


# 8. `remember` said "Noted" when a full store had written nothing.
@pytest.mark.critical
def test_8_remember_reports_a_full_store(repo, capsys, monkeypatch) -> None:
    monkeypatch.setattr(Memory, "record", lambda self, fact: None)
    rc, said = _run(capsys, "remember", "this will not fit")
    assert rc == 1 and "Not remembered" in said and "Noted" not in said


# 9. `connect` crashed on some configs and pinned an interpreter path; `init` writes the knos command, backs up
#    every file, leaves unreadable files alone, and undoes cleanly.
@pytest.mark.critical
def test_9_init_writes_backs_up_and_undoes(repo, capsys) -> None:
    cursor = Path.home() / ".cursor"
    cursor.mkdir()
    (cursor / "mcp.json").write_text(json.dumps({"mcpServers": {"other": {"command": "x"}}}), encoding="utf-8")
    rc, said = _run(capsys, "init", "--hosts", "cursor", "--no-test", "--no-read")
    assert rc == 0, said
    cfg = json.loads((cursor / "mcp.json").read_text(encoding="utf-8"))
    assert "other" in cfg["mcpServers"] and cfg["mcpServers"]["knos"]["args"][-1] == "mcp"
    assert "knos-guard" in (cursor / "hooks.json").read_text(encoding="utf-8")
    assert list((paths.home() / "backups").glob("init-*/manifest.json"))
    rc, said = _run(capsys, "init", "--undo", "--hosts", "cursor")
    assert rc == 0
    cfg = json.loads((cursor / "mcp.json").read_text(encoding="utf-8"))
    assert "knos" not in cfg["mcpServers"] and "other" in cfg["mcpServers"]
    hooks = cursor / "hooks.json"  # knos created it, so undo removes it
    assert not hooks.exists() or "knos-guard" not in hooks.read_text(encoding="utf-8")


def test_9_an_unreadable_config_is_left_alone(repo, capsys) -> None:
    cursor = Path.home() / ".cursor"
    cursor.mkdir()
    (cursor / "mcp.json").write_text("{ this is not json", encoding="utf-8")
    rc, said = _run(capsys, "init", "--hosts", "cursor", "--no-test", "--no-read")
    assert rc == 1 and "left it alone" in said
    assert (cursor / "mcp.json").read_text(encoding="utf-8") == "{ this is not json"


@pytest.mark.critical
def test_9_undo_restores_every_byte_and_init_twice_changes_nothing(repo, capsys) -> None:
    cursor = Path.home() / ".cursor"
    cursor.mkdir()
    original = b'{\r\n    "mcpServers": {"other": {"command": "x"}},\r\n    "odd":   [1,2]\r\n}\r\n'
    (cursor / "mcp.json").write_bytes(original)
    codex = Path(os.environ["CODEX_HOME"])
    codex.mkdir(parents=True, exist_ok=True)
    toml = b'# mine\nmodel = "gpt-5"\n\n[mcp_servers.other]\ncommand = "x"\n'
    (codex / "config.toml").write_bytes(toml)
    assert _run(capsys, "init", "--hosts", "cursor,codex", "--no-test", "--no-read")[0] == 0
    once = {p: p.read_bytes() for p in (cursor / "mcp.json", cursor / "hooks.json", codex / "config.toml")}
    assert b"[mcp_servers.knos]" in once[codex / "config.toml"]
    backups_before = len(list((paths.home() / "backups").glob("init-*")))
    assert _run(capsys, "init", "--hosts", "cursor,codex", "--no-test", "--no-read")[0] == 0
    assert {p: p.read_bytes() for p in once} == once
    assert len(list((paths.home() / "backups").glob("init-*"))) == backups_before
    assert _run(capsys, "init", "--undo", "--hosts", "cursor,codex")[0] == 0
    assert (cursor / "mcp.json").read_bytes() == original
    assert (codex / "config.toml").read_bytes() == toml
    assert not (cursor / "hooks.json").exists()


def test_9_connect_is_init(repo, capsys) -> None:
    (Path.home() / ".cursor").mkdir()
    rc, _ = _run(capsys, "connect", "--hosts", "cursor", "--print")
    assert rc == 0


# 10. The Cursor hook guarded reads (beforeReadFile) and docs claimed a pull request is told; neither is true now.
@pytest.mark.critical
def test_10_cursor_guards_edits_not_reads(repo) -> None:
    guard.install_cursor()
    hooks = json.loads(guard.cursor_hooks().read_text(encoding="utf-8"))["hooks"]
    assert "beforeReadFile" not in hooks and "preToolUse" in hooks
    assert guard.target_of("cursor", {"tool_name": "read_file", "tool_input": {"path": "src/auth.py"}}) == ""
    assert guard.target_of("cursor", {"tool_name": "edit_file", "tool_input": {"path": "src/auth.py"}}) == "src/auth.py"


def test_10_nothing_claims_a_pull_request_is_told() -> None:
    root = Path(__file__).resolve().parents[1]
    for f in list((root / "src" / "knos").rglob("*.py")) + [root / "README.md"]:
        assert "pull request is told" not in f.read_text(encoding="utf-8", errors="replace"), f


# Also fixed in 0.2.0: Claude Code's project folder name replaces every non-alphanumeric character.
def test_claude_folder_encoding() -> None:
    from knos import sessions

    assert sessions._encoded(Path("/home/me/my_repo.v2")) == "-home-me-my-repo-v2"


def test_the_guard_exits_zero_on_garbage() -> None:
    out, code = guard.run("claude", "not json")
    assert code == 0 and out == ""
    out, code = guard.run("claude", json.dumps({"tool_input": {"file_path": "/nowhere/x.py"}}))
    assert code == 0


def test_hook_cli_never_crashes(capsys, monkeypatch) -> None:
    import io
    import sys

    monkeypatch.setattr(sys, "stdin", io.StringIO("{}"))
    assert main(["hook", "guard", "--client", "claude"]) == 0
    monkeypatch.setattr(sys, "stdin", io.StringIO("{}"))
    assert main(["hook", "nonsense"]) == 0


def test_git_is_available() -> None:
    assert subprocess.run(["git", "--version"], capture_output=True).returncode == 0
