"""The notice an agent gets before it asks anything, and when it must stay quiet.

Every other way knos speaks depends on an agent choosing to call a tool. An agent that never calls `search` never
learns that somebody else is mid-change on the file it is about to open. `SessionStart` closes that: the host runs
`knos hook start` once when a session opens and puts what it prints into the session's own context. In 0.2.0 it also
records the host's session id against the host process in claims.db, which is how the MCP server that host starts
learns which session it serves.

Properties pinned here:

  - it is silent when there is nothing to say (a hook that speaks every time is a hook people learn to skip);
  - a live claim is named with who holds it and how long is left, and notes written down reach the session;
  - it records (host, session_id, anchor) from the hook's JSON payload, in the repo the payload's `cwd` names;
  - it never fails a session: every path returns 0, including a broken store and an unreadable payload;
  - the Claude Code plugin registers it, and `knos hook start` reaches it.

Rewritten for 0.2.0. Dropped with the 0.1 store: the `knos.core.Claims(repo=, who=)` and `Memory.working_on` ways of
taking a claim (claims are `knos.claims.Claims` with an `identity.Agent` now), and `answer.point` as the way to read a
repo in a test (`refresh.ensure` is what the product calls).
"""

from __future__ import annotations

import io
import json
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


from knos import start_hook
from knos.claims import Claims, claims_db
from knos.identity import Agent
from knos.memory import TOPIC, Memory

ROOT = Path(__file__).resolve().parent.parent
CURSOR = Agent(host="cursor", session="sess-cursor-0001")


def _read(repo: Path) -> None:
    """Give the repo a memory store, the way the first question does."""
    from knos import refresh

    refresh.ensure(repo, force=True, index_code=False)


def _payload(monkeypatch, event: dict | str) -> None:
    text = event if isinstance(event, str) else json.dumps(event)
    monkeypatch.setattr(sys, "stdin", io.StringIO(text))


def test_it_says_nothing_when_there_is_no_store(repo: Path, capsys) -> None:
    """A repo knos has never read, with nothing claimed, is not a repo knos should talk about."""
    assert start_hook.main([]) == 0
    assert capsys.readouterr().out == ""


def test_it_says_nothing_when_nothing_is_claimed_or_written(repo: Path, capsys) -> None:
    """The case that decides whether anybody reads it at all: a quiet repo gives an empty session preamble, even
    though knos has read its commits."""
    _read(repo)
    capsys.readouterr()

    assert start_hook.main([]) == 0
    assert capsys.readouterr().out == ""


def test_a_live_claim_is_named_with_who_holds_it(repo: Path, capsys) -> None:
    _read(repo)
    with Claims(repo) as c:
        took, _, _ = c.take(CURSOR, "the settlement path", ["src/auth.py"])
    assert took
    capsys.readouterr()

    assert start_hook.main([]) == 0
    said = capsys.readouterr().out

    assert "src/auth.py" in said
    assert "the settlement path" in said
    assert CURSOR.label in said, "a notice that does not say who holds it is not useful"
    assert "done()" in said, "it should say how to release a claim"


def test_a_claim_reaches_the_session_before_knos_has_read_the_repo(repo: Path, capsys) -> None:
    with Claims(repo) as c:
        assert c.take(CURSOR, "the settlement path", ["src/auth.py"])[0]
    capsys.readouterr()

    assert start_hook.main([]) == 0
    assert "src/auth.py" in capsys.readouterr().out


def _age(repo: Path, minutes: int) -> None:
    """Pretend every claim was last refreshed `minutes` ago."""
    then = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()
    conn = sqlite3.connect(str(claims_db(repo)))
    try:
        conn.execute("UPDATE claims SET taken_at=?, refreshed_at=?", (then, then))
        conn.commit()
    finally:
        conn.close()


def test_the_notice_counts_down_rather_than_repeating_the_hold(repo: Path, capsys) -> None:
    """How long is left, not how long it started with: a 30-minute claim taken 25 minutes ago has about 5 left."""
    _read(repo)
    with Claims(repo) as c:
        c.take(CURSOR, "the settlement path", ["src/auth.py"], holds_min=30)
    _age(repo, 25)
    capsys.readouterr()

    start_hook.main([])
    said = capsys.readouterr().out

    assert "the settlement path" in said
    assert "30 min" not in said, said
    assert "about 5 min" in said, said


def test_a_lapsed_claim_is_not_announced(repo: Path, capsys) -> None:
    _read(repo)
    with Claims(repo) as c:
        c.take(CURSOR, "the settlement path", ["src/auth.py"], holds_min=30)
    _age(repo, 31)
    capsys.readouterr()

    start_hook.main([])
    assert capsys.readouterr().out == ""


def test_a_written_note_reaches_the_session(repo: Path, capsys) -> None:
    """`notes()` returns rows keyed `note`; reading `text` once filtered them all out."""
    _read(repo)
    with Memory(repo) as mem:
        mem.note_thing(TOPIC, "redis", {"note": "we dropped redis for sqlite", "when": "2026-09-09"})
    capsys.readouterr()

    start_hook.main([])
    said = capsys.readouterr().out

    assert "Recently written down here:" in said
    assert "dropped redis" in said


def test_it_records_the_session_from_the_payload(repo: Path, tmp_path: Path, monkeypatch, capsys) -> None:
    """The session id Claude Code sends is written against the host process, in the repo the payload names (the
    hook's own working directory may be anywhere)."""
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    _payload(monkeypatch, {"session_id": "abc-123-session", "cwd": str(repo), "hook_event_name": "SessionStart"})

    assert start_hook.main(["--client", "claude"]) == 0

    with Claims(repo) as c:
        seen = c.agents()
    assert [(a["host"], a["session"]) for a in seen] == [("claude", "abc-123-session")]


def test_the_client_flag_names_the_host(repo: Path, monkeypatch) -> None:
    _payload(monkeypatch, {"conversation_id": "cur-77", "cwd": str(repo)})

    assert start_hook.main(["--client", "cursor"]) == 0

    with Claims(repo) as c:
        assert [(a["host"], a["session"]) for a in c.agents()] == [("cursor", "cur-77")]


def test_outside_a_repo_it_does_nothing(tmp_path: Path, monkeypatch, capsys) -> None:
    lost = tmp_path / "not-a-repo"
    lost.mkdir()
    monkeypatch.chdir(lost)
    _payload(monkeypatch, {"session_id": "s", "cwd": str(lost)})

    assert start_hook.main(["--client", "claude"]) == 0
    assert capsys.readouterr().out == ""


def test_an_unreadable_payload_does_not_fail_the_session(repo: Path, monkeypatch, capsys) -> None:
    _payload(monkeypatch, "{ this is not json")

    assert start_hook.main(["--client", "claude"]) == 0
    assert capsys.readouterr().out == ""


def test_a_broken_store_does_not_fail_the_session(repo: Path, capsys, monkeypatch) -> None:
    """Exit 0, always. A session must open whatever state knos is in."""
    _read(repo)

    def explode(*_a, **_k):
        raise RuntimeError("the store is a smoking hole")

    monkeypatch.setattr(start_hook, "_lines", explode)
    capsys.readouterr()

    assert start_hook.main([]) == 0
    assert capsys.readouterr().out == ""


def test_the_plugin_registers_it_and_fails_open() -> None:
    """A hook nothing calls is a file, not a feature. The plugin runs the installed `knos` script (a bare
    `python -m` cannot import knos after `pipx install`), and neither hook can fail a session or block an edit
    except by the guard's own exit 2."""
    hooks = json.loads((ROOT / "plugins" / "knos" / "hooks" / "hooks.json").read_text(encoding="utf-8"))["hooks"]

    start = hooks["SessionStart"][0]["hooks"][0]["command"]
    assert start.startswith("knos hook start --client claude")
    assert "exit 0" in start or start.endswith("|| true"), start

    guard = hooks["PreToolUse"][0]
    assert set(guard["matcher"].split("|")) >= {"Edit", "Write", "MultiEdit", "NotebookEdit"}
    command = guard["hooks"][0]["command"]
    assert command.startswith("knos hook guard --client claude")
    assert "exit 2" in command and "exit 0" in command, command


def test_knos_hook_start_reaches_this_module(monkeypatch) -> None:
    from knos.cli import main

    ran = []
    monkeypatch.setattr(start_hook, "main", lambda argv=None: ran.append(argv) or 0)

    assert main(["hook", "start", "--client", "claude"]) == 0
    assert ran == [["--client", "claude"]]


def test_knos_hook_start_exits_zero_even_when_the_module_raises(monkeypatch) -> None:
    from knos.cli import main

    def explode(argv=None):
        raise RuntimeError("boom")

    monkeypatch.setattr(start_hook, "main", explode)
    assert main(["hook", "start", "--client", "claude"]) == 0


def test_the_hook_as_a_process_exits_zero_and_records_the_session(repo: Path) -> None:
    """The command the hosts run, end to end, in its own process."""
    done = subprocess.run([sys.executable, "-m", "knos", "hook", "start", "--client", "claude"],
                          input=json.dumps({"session_id": "proc-session-1", "cwd": str(repo)}),
                          capture_output=True, text=True, encoding="utf-8", timeout=300)

    assert done.returncode == 0, done.stderr[-800:]
    assert "Traceback" not in done.stderr
    with Claims(repo) as c:
        assert ("claude", "proc-session-1") in [(a["host"], a["session"]) for a in c.agents()]
