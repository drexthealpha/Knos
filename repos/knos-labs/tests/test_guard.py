"""The guard refuses an edit, or it is not a guard.

In 0.2.0 it refuses exactly one thing: an edit to a repo file covered by a live, non-advisory claim held by a
*different* agent (claims.db, `Claims(repo).take(agent, description, globs)`), including that file after a rename.
So the cases that matter most here are the ones where it must stay out of the way: an unclaimed file, the holder
itself, an advisory claim, a rule in CLAUDE.md, a broken store, a payload it does not understand.

The hook is exercised the way a client runs it, a real subprocess reading real JSON on stdin, because the thing being
tested is an exit code and a contract with somebody else's runner, not a Python function.

Dropped from the 0.1 version of this file, because the behaviour is gone:
  - test_a_claim_the_person_made_is_refused_in_the_second_person and
    test_another_agents_claim_still_says_go_and_ask_them: claims are held by an Agent with a label (host/session),
    there is no "you" holder and no "which X claimed and is working on now" sentence any more. The one-line wording
    is pinned by test_the_refusal_is_one_line_that_names_holder_time_and_way_out instead.
  - test_a_rule_that_names_a_path_is_enforced, test_a_rule_with_no_path_in_it_is_not_enforced,
    test_a_backticked_word_that_is_not_a_path_is_ignored: rules never block and `guard.path_rules` is gone. Replaced
    by test_a_rule_in_claude_md_never_blocks_an_edit.
  - test_the_file_it_edits_is_backed_up_first: backups on install moved to `knos init` (init.py).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest

from knos import guard
from knos.claims import Claims, claims_db
from knos.identity import Agent

HOLDER = Agent(host="claude", session="alice123-holder-session")
OTHER_CLAUDE = Agent(host="claude", session="bob45678-other-session")
CURSOR = Agent(host="cursor", session="carol999-cursor-chat")

CLIENTS = ("claude", "codex", "cursor", "opencode")  # the hosts whose hook payloads the guard reads


def _take(repo: Path, agent: Agent, description: str, globs: list[str] | None) -> None:
    with Claims(repo) as c:
        took, clash, _mine = c.take(agent, description, globs)
    assert took, f"{agent.label} could not take {globs}: {clash}"


@pytest.fixture()
def claimed(knos_home, repo):
    """src/auth.py claimed by one Claude Code session."""
    _take(repo, HOLDER, "auth rework", ["src/auth.py"])
    return repo


# --- what it refuses --------------------------------------------------------


@pytest.mark.critical
def test_an_edit_to_a_file_another_agent_claimed_is_refused(claimed):
    for who in (CURSOR, OTHER_CLAUDE, "Cursor"):
        verdict = guard.check(claimed, str(claimed / "src" / "auth.py"), who)
        assert not verdict.allow, who
        assert "claude/alice123" in verdict.reason
        assert "auth rework" in verdict.reason


def test_the_refusal_is_one_line_that_names_holder_time_and_way_out(claimed):
    reason = guard.check(claimed, str(claimed / "src" / "auth.py"), CURSOR).reason
    assert "\n" not in reason
    assert re.fullmatch(
        r"knos: src/auth\.py is claimed by claude/alice123 since \d\d:\d\d \(auth rework\)\. "
        r"Ask them, or take other work; the claim lapses in \d+ min\. A person can release it: knos done --all \(Knos\)",
        reason,
    ), reason


def test_a_glob_claim_reaches_files_created_after_it(knos_home, repo):
    _take(repo, HOLDER, "the parser", ["src/parser/**"])
    target = repo / "src" / "parser" / "deep" / "lexer.py"
    target.parent.mkdir(parents=True)
    target.write_text("x = 1\n", encoding="utf-8")
    assert not guard.check(repo, str(target), CURSOR).allow


def test_a_refusal_is_recorded_for_the_board(claimed):
    guard.check(claimed, str(claimed / "src" / "auth.py"), CURSOR)
    with Claims(claimed) as c:
        blocked = c.events("blocked")
    assert blocked and blocked[0]["path"] == "src/auth.py" and blocked[0]["by"] == CURSOR.label


# --- what it must not refuse ------------------------------------------------


@pytest.mark.critical
def test_the_agent_holding_the_claim_may_edit_it(claimed):
    """A claim is how you take work, not how you lock yourself out of it."""
    assert guard.check(claimed, str(claimed / "src" / "auth.py"), HOLDER).allow
    # same host process, session id not known to this caller: still the holder
    anchored = Agent(host="claude", anchor=4242)
    _take(claimed, anchored, "readme", ["README.md"])
    assert guard.check(claimed, str(claimed / "README.md"), Agent(host="claude", session="x", anchor=4242)).allow


def test_an_unclaimed_file_is_left_alone(claimed):
    target = claimed / "README.md"
    target.write_text("hello\n", encoding="utf-8")
    assert guard.check(claimed, str(target), CURSOR).allow


def test_no_claims_at_all_is_allowed_without_making_a_store(knos_home, repo):
    assert guard.check(repo, str(repo / "src" / "auth.py"), CURSOR).allow
    assert not claims_db(repo).exists()


def test_a_released_claim_no_longer_blocks(claimed):
    with Claims(claimed) as c:
        assert c.release(HOLDER)
    assert guard.check(claimed, str(claimed / "src" / "auth.py"), CURSOR).allow


def test_a_lapsed_claim_no_longer_blocks(knos_home, repo):
    with Claims(repo) as c:
        c.take(HOLDER, "auth rework", ["src/auth.py"], holds_min=0)
    assert guard.check(repo, str(repo / "src" / "auth.py"), CURSOR).allow


def test_an_advisory_claim_never_blocks(knos_home, repo):
    """A description that resolves to no path is advisory: shown to others, never enforced."""
    with Claims(repo) as c:
        took, _, mine = c.take(HOLDER, "tidying up the login flow", None)
    assert took and mine.advisory and not mine.globs
    for rel in ("src/auth.py", "README.md", ".env"):
        assert guard.check(repo, str(repo / rel), CURSOR).allow, rel


def test_a_rule_in_claude_md_never_blocks_an_edit(knos_home, repo):
    """0.1 enforced "never edit `src/gen/`" rules. 0.2 does not: rules are read, never enforced by the guard."""
    for name in ("CLAUDE.md", "AGENTS.md"):
        (repo / name).write_text("# Rules\n\nNever edit `src/gen/` by hand. Never touch `README.md`.\n",
                                 encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "rules"], cwd=repo, check=True, capture_output=True)
    target = repo / "src" / "gen" / "client.py"
    target.parent.mkdir(parents=True)
    target.write_text("# generated\n", encoding="utf-8")
    _take(repo, HOLDER, "something else", ["docs/**"])  # a store exists, so this is not the no-store path

    assert guard.check(repo, str(target), CURSOR).allow
    assert guard.check(repo, str(repo / "README.md"), CURSOR).allow


def test_an_unreadable_store_allows_the_edit(claimed, knos_home):
    """Fail open, on purpose: a broken install must never stand between an agent and its own repo."""
    claims_db(claimed).write_bytes(b"this is not a sqlite database at all" * 100)
    for extra in ("-wal", "-shm"):
        Path(str(claims_db(claimed)) + extra).unlink(missing_ok=True)

    assert guard.check(claimed, str(claimed / "src" / "auth.py"), CURSOR).allow
    assert "guard allowed src/auth.py" in (knos_home / "hook.log").read_text(encoding="utf-8")


def test_a_crashing_claims_module_allows_the_edit(claimed, monkeypatch):
    import knos.claims

    class Broken:
        def __init__(self, *a, **k):
            raise OSError("store is gone")

    monkeypatch.setattr(knos.claims, "Claims", Broken)
    assert guard.check(claimed, str(claimed / "src" / "auth.py"), CURSOR).allow


def test_a_file_outside_the_repo_is_not_ours_to_refuse(claimed, tmp_path):
    _take(claimed, HOLDER, "everything", ["**"])
    stranger = tmp_path / "elsewhere" / "auth.py"
    stranger.parent.mkdir(parents=True)
    stranger.write_text("x = 1\n", encoding="utf-8")
    assert guard.check(claimed, str(stranger), CURSOR).allow


# --- the shape each client reads -------------------------------------------


def _payload(client: str, target: str, cwd: Path, session: str = "zed00000-someone-else") -> dict:
    if client == "claude":
        return {"session_id": session, "tool_name": "Edit", "tool_input": {"file_path": target}, "cwd": str(cwd)}
    if client == "cursor":
        return {"conversation_id": session, "tool_name": "edit_file", "file_path": target, "cwd": str(cwd)}
    if client == "codex":
        return {"session_id": session, "tool_name": "apply_patch", "cwd": str(cwd),
                "tool_input": {"command": f"*** Begin Patch\n*** Update File: {target}\n*** End Patch"}}
    return {"session_id": session, "args": {"filePath": target}, "cwd": str(cwd)}


@pytest.mark.parametrize("client", CLIENTS)
def test_a_payload_with_no_path_in_it_is_allowed(client, claimed):
    out, code = guard.run(client, json.dumps({"tool_name": "Bash", "tool_input": {}, "cwd": str(claimed)}))
    assert (out, code) == ("", guard.ALLOW)


@pytest.mark.parametrize("client", CLIENTS)
def test_nonsense_on_stdin_is_allowed(client, knos_home):
    for said in ("not json at all", "", "[1, 2]", "null"):
        assert guard.run(client, said) == ("", guard.ALLOW), said


@pytest.mark.critical
def test_each_client_is_refused_in_its_own_words(claimed):
    """The exit code is the refusal; the JSON is how each client explains it."""
    target = str(claimed / "src" / "auth.py")
    for client in CLIENTS:
        out, code = guard.run(client, json.dumps(_payload(client, target, claimed)))
        assert code == guard.REFUSE, client
        said = json.loads(out)
        if client in ("claude", "codex"):
            hso = said["hookSpecificOutput"]
            assert hso["hookEventName"] == "PreToolUse"
            assert hso["permissionDecision"] == "deny"
            reason = hso["permissionDecisionReason"]
        elif client == "cursor":
            assert said["permission"] == "deny"
            reason = said["user_message"]
            assert said["agent_message"] == reason
        else:
            assert said["deny"] is True
            reason = said["reason"]
        assert reason.startswith("knos: src/auth.py is claimed by claude/alice123"), (client, reason)


@pytest.mark.parametrize("client", CLIENTS)
def test_the_holders_own_session_is_allowed_through_the_hook(client, knos_home, repo):
    host = {"claude": "claude", "cursor": "cursor", "opencode": "opencode", "codex": "codex"}[client]
    _take(repo, Agent(host=host, session="mine0000-session"), "auth", ["src/auth.py"])
    out, code = guard.run(client, json.dumps(_payload(client, str(repo / "src" / "auth.py"), repo,
                                                      session="mine0000-session")))
    assert (out, code) == ("", guard.ALLOW)


def test_a_relative_path_is_taken_from_the_payload_cwd(claimed):
    event = {"session_id": "zzz", "tool_name": "Write", "tool_input": {"file_path": "src/auth.py"},
             "cwd": str(claimed / "src")}
    assert guard.decide("claude", event).allow is False


def test_a_notebook_edit_is_guarded_too(knos_home, repo):
    _take(repo, HOLDER, "analysis", ["nb/*.ipynb"])
    event = {"session_id": "zzz", "tool_name": "NotebookEdit",
             "tool_input": {"notebook_path": str(repo / "nb" / "a.ipynb")}, "cwd": str(repo)}
    assert guard.decide("claude", event).allow is False


def test_cursor_reads_are_never_guarded(claimed):
    event = {"conversation_id": "zzz", "tool_name": "read_file", "file_path": str(claimed / "src" / "auth.py"),
             "cwd": str(claimed)}
    assert guard.run("cursor", json.dumps(event)) == ("", guard.ALLOW)


def _hook(argv: list[str], payload: dict | str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, *argv], input=payload if isinstance(payload, str) else json.dumps(payload),
                          capture_output=True, text=True, cwd=str(cwd), env=dict(os.environ), timeout=120)


@pytest.mark.critical
def test_the_hook_runs_as_a_real_process_and_exits_two_on_a_refusal(claimed):
    """What a client does: run a command, write JSON, read the exit code. A unit test on `run()` cannot catch an
    entry point that does not start, so this pays for a subprocess."""
    done = _hook(["-m", "knos.guard_hook", "--client", "claude"],
                 _payload("claude", str(claimed / "src" / "auth.py"), claimed), claimed)
    assert done.returncode == guard.REFUSE, done.stderr
    said = json.loads(done.stdout)
    assert "claude/alice123" in said["hookSpecificOutput"]["permissionDecisionReason"]


def test_the_hook_process_exits_zero_when_it_has_nothing_to_refuse(claimed):
    for payload in (_payload("claude", str(claimed / "README.md"), claimed),
                    _payload("claude", str(claimed / "src" / "auth.py"), claimed, session=HOLDER.session),
                    "{not json"):
        done = _hook(["-m", "knos.guard_hook", "--client", "claude"], payload, claimed)
        assert done.returncode == guard.ALLOW, (payload, done.stderr)
        assert done.stdout == ""


def test_the_hook_process_exits_zero_on_an_unreadable_store(claimed, knos_home):
    claims_db(claimed).write_bytes(b"garbage" * 500)
    for extra in ("-wal", "-shm"):
        Path(str(claims_db(claimed)) + extra).unlink(missing_ok=True)
    done = _hook(["-m", "knos.guard_hook", "--client", "claude"],
                 _payload("claude", str(claimed / "src" / "auth.py"), claimed), claimed)
    assert done.returncode == guard.ALLOW, done.stderr
    assert (knos_home / "hook.log").read_text(encoding="utf-8").strip()


def test_the_installed_command_form_refuses_too(claimed):
    """`<knos> hook guard --client cursor` is what the installers write; the CLI route must keep exit 2."""
    done = _hook(["-m", "knos", "hook", "guard", "--client", "cursor"],
                 _payload("cursor", str(claimed / "src" / "auth.py"), claimed), claimed)
    assert done.returncode == guard.REFUSE, done.stderr
    assert json.loads(done.stdout)["permission"] == "deny"


# --- speed: it runs before every edit ------------------------------------------


def test_the_guard_is_fast_with_twenty_live_claims(knos_home, repo):
    """200 checks against ~20 live claims: p95 under 100 ms on a normal machine. Asserted at 250 ms so a noisy CI
    box does not flake; the measured number is printed."""
    old = time.time() - 3600
    for i in range(20):
        d = repo / f"pkg{i}"
        d.mkdir()
        (d / "mod.py").write_text(f"x = {i}\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "pkgs"], cwd=repo, check=True, capture_output=True)
    for root, dirs, _ in os.walk(repo):
        dirs[:] = [d for d in dirs if d != ".git"]
        os.utime(root, (old, old))
    for i in range(20):
        glob = f"pkg{i}/**" if i % 2 else f"pkg{i}/mod.py"
        _take(repo, Agent(host="claude", session=f"agent{i:03d}-session"), f"work {i}", [glob])

    # The per-edit path: every one of these is allowed, and walks all 20 claims plus the rename pre-check.
    calls = [(repo / f"pkg{2 * (i % 10)}" / ("mod2.py" if i % 2 else "new.py"), CURSOR) for i in range(100)]
    calls += [(repo / rel, CURSOR) for rel in ("src/auth.py", "README.md", "docs/new.md", "pkg0/sub/x.py")] * 15
    calls += [(repo / f"pkg{i}" / "mod.py", Agent(host="claude", session=f"agent{i:03d}-session")) for i in range(20)] * 2
    assert len(calls) == 200
    guard.check(repo, str(calls[0][0]), CURSOR)  # warm imports and caches
    took = []
    for target, who in calls:
        start = time.perf_counter()
        verdict = guard.check(repo, str(target), who)
        took.append(time.perf_counter() - start)
        assert verdict.allow, verdict.reason
    took.sort()
    p95 = took[int(len(took) * 0.95) - 1] * 1000

    # A refusal also writes a 'blocked' event, so it pays for a disk sync; reported, not asserted (disk-bound).
    refusals = []
    for i in range(1, 6):
        start = time.perf_counter()
        assert not guard.check(repo, str(repo / f"pkg{i}" / "mod.py"), CURSOR).allow
        refusals.append(time.perf_counter() - start)
    print(f"\nguard.check p95 = {p95:.1f} ms over {len(took)} allowed calls, 20 live claims; "
          f"refusal median = {sorted(refusals)[2] * 1000:.1f} ms")
    assert p95 < 250, f"guard.check p95 {p95:.1f} ms"


# --- installing and taking it back out --------------------------------------


def test_install_then_uninstall_leaves_nothing_behind(knos_home):
    """The guard is opt-in, so getting back out has to be exact."""
    settings = guard.claude_settings()
    settings.parent.mkdir(parents=True, exist_ok=True)
    mine = {"matcher": "Bash", "hooks": [{"type": "command", "command": "echo mine"}]}
    settings.write_text(json.dumps({"hooks": {"PreToolUse": [mine]}, "theme": "dark"}), encoding="utf-8")

    guard.install_claude()
    guard.install_cursor()
    guard.install_opencode()
    guard.install_codex()
    assert guard.installed() == {"claude": True, "cursor": True, "opencode": True, "codex": True}

    assert guard.uninstall_claude()
    assert guard.uninstall_cursor()
    assert guard.uninstall_opencode()
    assert guard.uninstall_codex()
    assert guard.installed() == {"claude": False, "cursor": False, "opencode": False, "codex": False}
    assert not guard.uninstall_opencode()

    kept = json.loads(settings.read_text(encoding="utf-8"))
    assert kept["theme"] == "dark"
    assert kept["hooks"]["PreToolUse"] == [mine]


def test_installing_twice_does_not_stack_up_hooks(knos_home):
    for _ in range(3):
        guard.install_claude()
        guard.install_cursor()
    claude = json.loads(guard.claude_settings().read_text(encoding="utf-8"))
    assert len(claude["hooks"]["PreToolUse"]) == 2
    assert len(claude["hooks"]["SessionStart"]) == 1
    cursor = json.loads(guard.cursor_hooks().read_text(encoding="utf-8"))
    assert len(cursor["hooks"]["preToolUse"]) == 1


def test_the_hook_commands_have_the_documented_shape(knos_home, monkeypatch):
    import knos.init as setup

    monkeypatch.setattr(setup, "own_script", lambda: "/usr/local/bin/knos")
    guard.install_claude()
    guard.install_cursor()
    claude = json.loads(guard.claude_settings().read_text(encoding="utf-8"))["hooks"]
    pre = claude["PreToolUse"][0]
    assert pre["matcher"] == "Edit|Write|MultiEdit|NotebookEdit"
    assert pre["hooks"][0]["command"] == '"/usr/local/bin/knos" hook guard --client claude #knos-guard'
    assert claude["SessionStart"][0]["hooks"][0]["command"] == '"/usr/local/bin/knos" hook start --client claude #knos-guard'
    cursor = json.loads(guard.cursor_hooks().read_text(encoding="utf-8"))["hooks"]
    assert cursor["preToolUse"] == [{"command": '"/usr/local/bin/knos" hook guard --client cursor #knos-guard'}]


def test_cursor_gets_pre_tool_use_only_and_loses_the_old_read_hook(knos_home):
    """0.1 put a hook on beforeReadFile; the guard guards edits, not reads. Somebody else's read hook stays."""
    path = guard.cursor_hooks()
    path.parent.mkdir(parents=True, exist_ok=True)
    theirs = {"command": "their-read-hook"}
    path.write_text(json.dumps({"version": 1, "hooks": {"beforeReadFile": [
        {"command": "knos hook guard --client cursor #knos-guard"}, theirs]}}), encoding="utf-8")

    guard.install_cursor()
    hooks = json.loads(path.read_text(encoding="utf-8"))["hooks"]
    assert hooks["beforeReadFile"] == [theirs]
    assert "knos-guard" in json.dumps(hooks["preToolUse"])

    path.write_text(json.dumps({"version": 1, "hooks": {}}), encoding="utf-8")
    guard.install_cursor()
    assert "beforeReadFile" not in json.loads(path.read_text(encoding="utf-8"))["hooks"]


def test_the_opencode_plugin_calls_the_guard_and_throws_on_exit_two(knos_home, monkeypatch):
    monkeypatch.setattr(guard.shutil, "which", lambda name: "/usr/local/bin/knos")
    js = guard.install_opencode().read_text(encoding="utf-8")
    assert "hook guard --client opencode" in js
    assert '"tool.execute.before"' in js and "=== 2" in js and "throw" in js


@pytest.mark.parametrize("raw", ["{ this is not json", "[1, 2, 3]"])
def test_an_unparseable_settings_file_is_never_overwritten(knos_home, raw):
    for path, install in ((guard.claude_settings(), guard.install_claude), (guard.cursor_hooks(), guard.install_cursor)):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(raw, encoding="utf-8")
        with pytest.raises(guard.Unreadable):
            install()
        assert path.read_text(encoding="utf-8") == raw
    assert not guard.uninstall_claude() and not guard.uninstall_cursor()
    assert guard.claude_settings().read_text(encoding="utf-8") == raw


@pytest.mark.critical
def test_the_hook_command_survives_a_shell_when_knos_is_not_on_path(monkeypatch) -> None:
    """The bug that silently disarmed the guard on every Windows machine.

    Clients run the hook command through a shell, often bash, which eats backslashes. The interpreter path lost
    every separator, the hook never started, the failure was non-blocking, and every edit went through unguarded.
    Forward slashes survive a shell and Windows accepts them; the quotes cover a space in the path.
    """
    import knos.init as setup

    monkeypatch.setattr(guard.shutil, "which", lambda name: None)
    monkeypatch.setattr(setup, "own_script", lambda: None)
    said = " ".join(guard.knos_cmd())
    assert "\\" not in said
    assert said.startswith('"') and said.count('"') == 2
    assert said.endswith('" -m knos')
    assert guard.hook_cmd("guard", "claude") == said + " hook guard --client claude"
    assert guard.knos_cmd_argv() == [sys.executable, "-m", "knos"]


def test_the_knos_installed_with_this_one_beats_a_stale_copy_on_path(monkeypatch):
    """An older knos earlier on PATH must not be what every hook runs."""
    import knos.init as setup

    monkeypatch.setattr(guard.shutil, "which", lambda name: "/stale/bin/knos")
    monkeypatch.setattr(setup, "own_script", lambda: "/venv/bin/knos")
    assert guard.knos_cmd() == ['"/venv/bin/knos"']
    assert guard.knos_cmd_argv() == ["/venv/bin/knos"]
    monkeypatch.setattr(setup, "own_script", lambda: None)
    assert guard.knos_cmd_argv() == ["/stale/bin/knos"]  # with no script beside this interpreter, PATH decides
