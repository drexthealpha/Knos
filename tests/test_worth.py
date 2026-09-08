"""A tool whose value is entirely in things that did not happen gets uninstalled.

Every refusal in knos is invisible when it works. An agent asks about work
somebody else is holding, is told to go and ask them, picks up something else,
and the person never sees any of it. The collision that did not happen leaves
no trace in the day.

`knos worth` is where it left one. These check the two things that make it
worth having: the numbers come from records written at the time rather than
from a counter that could drift, and the zero case says so plainly instead of
finding something flattering to report.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from knos import worth
from knos.memory import Memory


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def test_an_untouched_repo_says_it_has_done_nothing(knos_home, repo) -> None:
    """The honest zero. A tool that reports a flattering number here is lying."""
    with Memory(repo) as mem:
        got = worth.tally(mem)
        said = worth.sentence(got)

    assert got["stood_down"] == 0 and got["overrode"] == 0
    assert "not earning its place" in said


def test_claims_with_no_collision_are_not_dressed_up(knos_home, repo) -> None:
    """Work happening is not the same as knos having been needed."""
    with Memory(repo) as mem:
        mem.claim_if_free("the parser", "Claude Code", _now())
        said = worth.sentence(worth.tally(mem))

    assert "Nothing has collided" in said, said


@pytest.mark.critical
def test_it_counts_the_collisions_that_were_refused(knos_home, repo) -> None:
    with Memory(repo) as mem:
        mem.claim_if_free("the parser", "Claude Code", _now())
        mem.stood_down("the parser", "Cursor", "Claude Code", _now())
        mem.stood_down("the parser", "OpenCode", "Claude Code", _now())

        got = worth.tally(mem)
        said = worth.sentence(got)

    assert got["stood_down"] == 2
    assert "went elsewhere" in said


def test_an_override_is_counted_separately_from_a_stand_down(knos_home, repo) -> None:
    """They mean opposite things and a total would hide which happened."""
    with Memory(repo) as mem:
        mem.claim_if_free("the parser", "Claude Code", _now())
        mem.stood_down("the parser", "Cursor", "Claude Code", _now())
        mem.overrode("the parser", "OpenCode", "Claude Code", "the build is down", _now())

        got = worth.tally(mem)

    assert got["stood_down"] == 1
    assert got["overrode"] == 1
    assert "went ahead anyway" in worth.sentence(got)


def test_the_same_agent_standing_down_twice_counts_once(knos_home, repo) -> None:
    """`stood_down` is deduplicated at the source; the count inherits that.

    A chatty agent that asks ten times about one claim has met one collision,
    not ten, and reporting ten would be the easiest way to make this number
    flattering and useless.
    """
    with Memory(repo) as mem:
        mem.claim_if_free("the parser", "Claude Code", _now())
        for _ in range(5):
            mem.stood_down("the parser", "Cursor", "Claude Code", _now())

        assert worth.tally(mem)["stood_down"] == 1


@pytest.mark.critical
def test_it_dies_with_the_store(knos_home, repo) -> None:
    from knos import paths

    with Memory(repo) as mem:
        mem.claim_if_free("the parser", "Claude Code", _now())
        mem.stood_down("the parser", "Cursor", "Claude Code", _now())
        assert worth.tally(mem)["stood_down"] == 1

    paths.store_for(repo).unlink()

    with Memory(repo) as mem:
        assert worth.tally(mem)["stood_down"] == 0


def test_it_does_not_say_between_a_day_and_the_same_day(knos_home, repo) -> None:
    """Small, and the sort of thing that costs a reader's trust in the rest."""
    with Memory(repo) as mem:
        mem.claim_if_free("the parser", "Claude Code", _now())
        mem.stood_down("the parser", "Cursor", "Claude Code", _now())
        said = worth.sentence(worth.tally(mem))

    assert "between" not in said, said
    assert " on 20" in said


def test_it_counts_in_english(knos_home, repo) -> None:
    with Memory(repo) as mem:
        mem.claim_if_free("the parser", "Claude Code", _now())
        mem.stood_down("the parser", "Cursor", "Claude Code", _now())
        one = worth.sentence(worth.tally(mem))
        mem.stood_down("the parser", "OpenCode", "Claude Code", _now())
        two = worth.sentence(worth.tally(mem))

    assert one.startswith("Once "), one
    assert "2 times" in two, two
    assert "time(s)" not in one + two
