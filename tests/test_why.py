"""`knos why` has to be willing to tell somebody not to install knos.

The rules score a market-size slide at zero and disqualify fabricated
evidence, and both of those are the same failure: saying the pain is real
because it suits you. The pain here is checkable on the asker's own disk -
Claude Code writes a timestamped transcript per session - so the honest move
is to count it rather than assert it.

Which only means anything if the zero case is as loud as the other one. These
tests spend most of their effort on the machine that does *not* have the
problem, because that is the output nobody writes unless they meant it.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from knos import why


class _Turn:
    def __init__(self, when: datetime, session: str) -> None:
        self.when = when.isoformat()
        self.session = session
        self.client = "Claude Code"
        self.text = "did a thing"
        self.where = f"Claude Code session {session}"


def _turns(monkeypatch: pytest.MonkeyPatch, turns: list[_Turn]) -> None:
    from knos import sessions

    monkeypatch.setattr(sessions, "read_all", lambda _repo=None: turns)


NOW = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)


def test_a_machine_with_no_transcripts_says_so_rather_than_zero_percent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Nothing to count is not the same answer as counted nothing.

    Printing "0%" from an empty read would be the quietest lie available: it
    looks like a measurement and is the absence of one.
    """
    _turns(monkeypatch, [])
    got = why.measure()

    assert got["turns"] == 0
    assert not got["windows"], "no data must not produce a percentage"
    said = why.sentence(got)
    assert "nothing to count" in said
    assert "%" not in said


def test_one_session_is_told_it_does_not_need_knos(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The whole product is about two agents. One agent should hear that."""
    _turns(monkeypatch, [_Turn(NOW + timedelta(minutes=n), "aaaa") for n in range(50)])

    said = why.sentence(why.measure())

    assert "probably do not need it" in said


def test_two_sessions_that_never_overlap_are_told_the_same(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sequential agents are not concurrent agents.

    Somebody who runs one agent, finishes, then runs another has no overlap at
    all, and knos would sit there refusing nothing. Saying so is the point.
    """
    turns = [_Turn(NOW + timedelta(minutes=n), "aaaa") for n in range(20)]
    turns += [_Turn(NOW + timedelta(days=3, minutes=n), "bbbb") for n in range(20)]
    _turns(monkeypatch, turns)

    got = why.measure()
    assert got["sessions"] == 2
    assert got["windows"][5][1] == 0, "these never overlap"
    assert "do not have any" in why.sentence(got)


def test_real_overlap_is_counted_and_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    turns = [_Turn(NOW + timedelta(minutes=n), "aaaa") for n in range(20)]
    turns += [_Turn(NOW + timedelta(minutes=n), "bbbb") for n in range(20)]
    _turns(monkeypatch, turns)

    got = why.measure()
    said = why.sentence(got)

    assert got["windows"][5][2] == 100.0, "these are entirely concurrent"
    assert "100.0%" in said


def test_the_share_is_reported_at_several_widths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One width invites the question of whether it was chosen."""
    turns = [_Turn(NOW + timedelta(minutes=n), "aaaa") for n in range(60)]
    turns += [_Turn(NOW + timedelta(minutes=n), "bbbb") for n in range(0, 60, 7)]
    _turns(monkeypatch, turns)

    got = why.measure()

    assert set(got["windows"]) == set(why.WINDOWS)


def test_it_never_calls_the_overlap_a_collision(monkeypatch: pytest.MonkeyPatch) -> None:
    """The one overclaim available here, and the one that would be a lie.

    Two sessions in the same minute may be nowhere near each other in the
    tree. This measures the precondition, and the wording has to keep saying
    so, because "10% of your minutes have a collision" is the sentence
    somebody would quote back.
    """
    turns = [_Turn(NOW + timedelta(minutes=n), s) for n in range(20) for s in ("a", "b")]
    _turns(monkeypatch, turns)

    said = why.sentence(why.measure()).lower()

    assert "collision" not in said
    assert "collided" not in said


def test_it_writes_nothing(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """It reads somebody's transcripts. It should leave nothing behind."""
    _turns(monkeypatch, [_Turn(NOW, "aaaa")])
    before = set(tmp_path.rglob("*"))

    why.measure()

    assert set(tmp_path.rglob("*")) == before
