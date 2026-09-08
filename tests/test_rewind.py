"""Who held what, at a moment that has already passed.

Everything else in knos answers about now. This is the only thing that answers
about then, and it is the question people actually have after two agents
collide: what did the machine know, and who was holding it?

The property worth guarding is the one that is easy to get subtly wrong. A
claim with no recorded close was live for exactly the hold its agent had
earned **by that moment** - not the hold it has earned since. An agent that
spent Monday abandoning work and Tuesday finishing it has two different holds,
and reconstructing Monday with Tuesday's number produces a confident, wrong
account of the thing somebody is trying to understand.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from knos import record, rewind
from knos.memory import Fact, Memory


def _ago(minutes: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()


def test_it_reads_the_times_a_person_would_type() -> None:
    assert rewind.when("2026-09-08 14:00").startswith("2026-09-08T14:00")
    assert rewind.when("2026-09-08").startswith("2026-09-08T00:00")
    assert rewind.when("2026-09-08T14:00:00+00:00").startswith("2026-09-08T14:00")
    assert rewind.when("90m")[:4].isdigit()
    assert rewind.when("2h")[:4].isdigit()
    assert rewind.when("3d")[:4].isdigit()


def test_a_time_it_cannot_read_is_said_so_not_guessed() -> None:
    """Choosing a moment silently would be the worst failure available here."""
    assert rewind.when("last tuesday-ish") == ""
    assert rewind.when("") == ""


@pytest.fixture()
def afternoon(knos_home, repo):
    """Claude Code finishes what it starts; the runner never does."""
    with Memory(repo) as mem:
        for n in range(4):
            record.note_taken(mem, f"old {n}", "Claude Code", _ago(500 - n))
            record.note_finished(mem, f"old {n}", "Claude Code", _ago(499 - n))
        for n in range(4):
            record.note_taken(mem, f"dead {n}", "a CI runner", _ago(500 - n))

        record.note_taken(mem, "the risk guard", "Claude Code", _ago(90))
        record.note_taken(mem, "the parser", "a CI runner", _ago(80))
        mem.record(Fact(text="the risk guard refuses unknown assets",
                        source="session", where="Claude Code",
                        when=_ago(88), about="the risk guard"))
        record.note_finished(mem, "the risk guard", "Claude Code", _ago(20))
    return repo


@pytest.mark.critical
def test_it_says_who_was_holding_what(afternoon) -> None:
    with Memory(afternoon) as mem:
        held = rewind.held_at(mem, _ago(60))

    topics = {c["topic"]: c for c in held}
    assert "the risk guard" in topics
    assert topics["the risk guard"]["who"] == "Claude Code"


@pytest.mark.critical
def test_a_lapsed_claim_is_not_reported_as_held(afternoon) -> None:
    """The runner took the parser 80 minutes ago and had earned 15."""
    with Memory(afternoon) as mem:
        held = rewind.held_at(mem, _ago(60))

    assert "the parser" not in {c["topic"] for c in held}, (
        "a claim that had already lapsed was reported as live"
    )


@pytest.mark.critical
def test_the_hold_used_is_the_one_earned_by_then(afternoon) -> None:
    """The property that makes this a reconstruction rather than a guess.

    By that afternoon Claude Code had five claims taken and four closed - the
    fifth being the one it was holding - so it had earned 39 of the possible
    45 minutes. The test then gives it a pile of abandoned work *after* the
    moment being asked about, so the record then and the record now differ,
    and using the wrong one is visible.
    """
    with Memory(afternoon) as mem:
        for n in range(20):
            record.note_taken(mem, f"later {n}", "Claude Code", _ago(5))

        then = rewind.held_at(mem, _ago(60))
        earned_then = next(c for c in then if c["topic"] == "the risk guard")
        earned_now = record.holds_for(mem, "Claude Code")

    assert earned_then["would_lapse_after"] > earned_now, (
        "the reconstruction used today's record instead of the one that "
        "applied at the moment being asked about"
    )
    # Four closed of five taken by then - the claim being asked about counts
    # as taken while it is open, which is right: an agent holding something it
    # has not closed is exactly the case the hold is deciding about.
    assert earned_then["would_lapse_after"] == 39


def test_a_claim_that_was_closed_is_gone_afterwards(afternoon) -> None:
    with Memory(afternoon) as mem:
        assert rewind.held_at(mem, _ago(10)) == []


def test_it_reports_what_the_store_had_been_told_by_then(afternoon) -> None:
    with Memory(afternoon) as mem:
        early = rewind.known_at(mem, _ago(89))
        later = rewind.known_at(mem, _ago(60))

    said = [f["text"] for f in later]
    assert "the risk guard refuses unknown assets" in said
    assert len(early) < len(later), "a fact was reported before it was written"


def test_claim_bookkeeping_is_not_repeated_as_knowledge(afternoon) -> None:
    """`held_at` already answers that, and saying it twice doubles every line."""
    with Memory(afternoon) as mem:
        for fact in rewind.known_at(mem, _ago(60)):
            assert not fact["text"].startswith("knos.claim"), fact


def test_it_says_where_the_journal_stops(afternoon) -> None:
    """Reconstructing an empty machine and calling that history is a lie."""
    with Memory(afternoon) as mem:
        floor = rewind.oldest(mem)
        got = rewind.at(mem, _ago(100000))

    assert floor, "the journal floor was not reported at all"
    assert got["earliest_the_journal_holds"] == floor
    assert got["claims"] == []


@pytest.mark.critical
def test_the_collision_is_the_headline_not_a_footnote(knos_home, repo) -> None:
    """The reason somebody types this command at all.

    A stand-down and an override are the two possible endings of a collision.
    They were being reported among ordinary notes, which is finding them the
    hard way in the one situation where somebody is already frustrated.
    """
    with Memory(repo) as mem:
        mem.claim_if_free("the parser", "Claude Code", _ago(40))
        mem.stood_down("the parser", "Cursor", "Claude Code", _ago(35))
        mem.overrode("the parser", "OpenCode", "Claude Code", "the build is down",
                     _ago(30))

        got = rewind.at(mem, _ago(20))

    kinds = [c["kind"] for c in got["collisions"]]
    assert kinds == ["stood down", "overrode"], got["collisions"]
    assert "the build is down" in got["collisions"][1]["text"], (
        "an override without its reason is the half that does not matter"
    )


def test_a_collision_is_reported_once_not_twice(knos_home, repo) -> None:
    """It is a journal fact too, so it would otherwise appear in both lists."""
    with Memory(repo) as mem:
        mem.claim_if_free("the parser", "Claude Code", _ago(40))
        mem.stood_down("the parser", "Cursor", "Claude Code", _ago(35))

        got = rewind.at(mem, _ago(20))

    said = [f["text"] for f in got["known"]]
    for hit in got["collisions"]:
        assert hit["text"] not in said, "the same event was listed twice"


def test_a_collision_after_the_moment_is_not_reported(knos_home, repo) -> None:
    with Memory(repo) as mem:
        mem.claim_if_free("the parser", "Claude Code", _ago(40))
        mem.overrode("the parser", "OpenCode", "Claude Code", "later", _ago(5))

        assert rewind.collisions_at(mem, _ago(20)) == []
