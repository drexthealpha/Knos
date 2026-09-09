"""The notice an agent gets before it asks anything, and when it must stay quiet.

Every other way knos speaks depends on an agent choosing to call a tool. An
agent that never calls `search` never learns that somebody else is mid-change
on the file it is about to open - and opening that file is the collision this
product exists to prevent. `SessionStart` closes that: the client runs it once
when a session opens and puts what it prints into the session's own context.

Two properties matter more than the wording.

**It must be silent when there is nothing to say.** A hook that speaks every
time an agent starts is a hook people learn to skip, and then it is worse than
absent, because the one session where it mattered scrolls past unread.

**It must never fail a session.** A broken install sitting between an agent and
its own repository is worse than the collision it was meant to prevent, so
everything here exits 0 - the same rule the guard hook follows.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from knos import start_hook
from knos.memory import Memory


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    repo = tmp_path / "work"
    repo.mkdir()
    (repo / "a.py").write_text("x = 1\n", encoding="utf-8")
    for args in (("init", "-q"), ("config", "user.email", "t@t"),
                 ("config", "user.name", "t"), ("add", "-A"),
                 ("commit", "-qm", "first")):
        subprocess.run(["git", *args], cwd=repo, capture_output=True, check=False)
    monkeypatch.setenv("KNOS_HOME", str(tmp_path / "home"))
    monkeypatch.chdir(repo)
    return repo


def test_it_says_nothing_when_there_is_no_store(repo: Path, capsys) -> None:
    """A repo knos has never read is not a repo knos should talk about."""
    assert start_hook.main([]) == 0
    assert capsys.readouterr().out == ""


def test_it_says_nothing_when_nothing_is_claimed(repo: Path, capsys) -> None:
    """The case that decides whether anybody reads it at all.

    A quiet repo must produce an empty session preamble, or the notice becomes
    noise that people filter out before the day it matters.
    """
    from knos import answer

    with Memory(repo) as mem:
        answer.point(repo, mem, index_code=False)
    capsys.readouterr()

    assert start_hook.main([]) == 0
    assert capsys.readouterr().out == ""


def test_a_live_claim_is_named_with_who_holds_it(repo: Path, capsys) -> None:
    from knos import answer
    from knos.core import Claims

    with Memory(repo) as mem:
        answer.point(repo, mem, index_code=False)
    with Claims(repo=str(repo), who="Cursor") as claims:
        assert claims.take("the settlement path")[0]
    capsys.readouterr()

    start_hook.main([])
    said = capsys.readouterr().out

    assert "the settlement path" in said
    assert "Cursor" in said, "a notice that does not say who holds it is not useful"
    assert "done(" in said, "it should say how to release the claim"


def test_the_notice_counts_down_rather_than_repeating_the_hold(
    repo: Path, capsys
) -> None:
    """How long is left, not how long it started with.

    `holds` is the length the claim was written with. Printed raw, a claim
    taken twenty-five minutes ago still announced thirty minutes to run - in
    the one line an agent reads to decide whether waiting is worth it. A
    claim already past its hold is not live at all and says no time.
    """
    from datetime import datetime, timedelta, timezone

    from knos import answer

    with Memory(repo) as mem:
        answer.point(repo, mem, index_code=False)
        old = (datetime.now(timezone.utc) - timedelta(minutes=25)).isoformat()
        mem.working_on("the settlement path", "Cursor", old)
    capsys.readouterr()

    start_hook.main([])
    said = capsys.readouterr().out

    assert "the settlement path" in said
    assert "30 min" not in said, said
    assert "5 min" in said, said


def test_a_written_decision_reaches_the_session(repo: Path, capsys) -> None:
    """`notes()` returns rows keyed `note`; reading `text` filtered them all out.

    The same trap `written_rules` fell into - a key that lives somewhere other
    than where the caller looked - and it silently emptied half of this hook.
    """
    from knos import answer

    with Memory(repo) as mem:
        answer.point(repo, mem, index_code=False)
        # TOPIC is the category `notes()` reads; "note" is not, and using it
        # wrote a row the hook could never see.
        from knos.memory import TOPIC

        mem.note_thing(TOPIC, "redis", {"note": "we dropped redis for sqlite",
                                        "when": "2026-09-09"})
    capsys.readouterr()

    start_hook.main([])
    said = capsys.readouterr().out

    assert "dropped redis" in said


def test_a_broken_store_does_not_fail_the_session(repo: Path, capsys,
                                                  monkeypatch) -> None:
    """Exit 0, always. A session must open whatever state knos is in."""
    def explode(*_a, **_k):
        raise RuntimeError("the store is a smoking hole")

    monkeypatch.setattr(start_hook, "_lines", explode)

    assert start_hook.main([]) == 0
    assert capsys.readouterr().out == ""


def test_the_plugin_registers_it(capsys) -> None:
    """A hook nothing calls is a file, not a feature."""
    import json

    root = Path(__file__).resolve().parent.parent
    hooks = json.loads(
        (root / "plugins" / "knos" / "hooks" / "hooks.json").read_text(encoding="utf-8")
    )["hooks"]

    assert "SessionStart" in hooks, "the plugin does not run the notice"
    command = hooks["SessionStart"][0]["hooks"][0]["command"]
    assert "knos.start_hook" in command
