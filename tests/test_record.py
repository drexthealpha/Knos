"""A claim is worth as long as the agent making it has earned.

Every hold used to be thirty minutes, whoever asked. That is wrong in both
directions: an agent that closes its work has it taken away mid-task, and an
agent that claims and dies blocks everybody for the full half hour every time
without the store ever getting wiser.

The number is now learned from one thing, out of the journal the store already
keeps: the share of claims this agent actually closed. The rule is dull on
purpose - a ratio with a floor and a ceiling - because a decay-weighted trust
model fitted to eleven events would be a more impressive way of being wrong.

The load-bearing part is the last test here. The record exists nowhere but the
store, so deleting it makes every agent a stranger worth exactly thirty
minutes, which is the behaviour knos had before any of this.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from knos import record
from knos.memory import Memory


def _when(minutes_ago: int = 0) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()


def _worked(mem, who: str, rounds: int, finishing: bool) -> None:
    """`who` takes and either closes or abandons `rounds` pieces of work."""
    for n in range(rounds):
        topic = f"task {who} {n}"
        record.note_taken(mem, topic, who, _when(200 - n))
        if finishing:
            record.note_finished(mem, topic, who, _when(199 - n))


def test_an_agent_nobody_has_seen_gets_the_old_default(knos_home, repo) -> None:
    with Memory(repo) as mem:
        assert record.holds_for(mem, "Cursor") == record.UNKNOWN == 30


def test_one_claim_is_not_enough_to_judge_anyone_on(knos_home, repo) -> None:
    """A single event is noise. Nobody is punished for being new."""
    with Memory(repo) as mem:
        _worked(mem, "Cursor", rounds=1, finishing=False)
        assert record.holds_for(mem, "Cursor") == record.UNKNOWN


def test_an_agent_that_finishes_earns_a_longer_hold(knos_home, repo) -> None:
    with Memory(repo) as mem:
        _worked(mem, "Claude Code", rounds=4, finishing=True)

        assert record.holds_for(mem, "Claude Code") == record.CEILING
        assert record.reliability(mem, "Claude Code")["kept"] == 1.0


def test_an_agent_that_abandons_its_work_holds_it_for_less(knos_home, repo) -> None:
    with Memory(repo) as mem:
        _worked(mem, "Cursor", rounds=4, finishing=False)

        assert record.holds_for(mem, "Cursor") == record.FLOOR
        assert record.holds_for(mem, "Cursor") < record.UNKNOWN


def test_the_record_is_per_agent_not_a_single_global_mood(knos_home, repo) -> None:
    with Memory(repo) as mem:
        _worked(mem, "Claude Code", rounds=3, finishing=True)
        _worked(mem, "Cursor", rounds=3, finishing=False)

        assert record.holds_for(mem, "Claude Code") > record.holds_for(mem, "Cursor")
        names = [r["who"] for r in record.everyone(mem)]
        assert names[0] == "Cursor", "the worst record should sort first"


@pytest.mark.critical
def test_the_learned_hold_is_what_the_claim_actually_expires_on(
    knos_home, repo
) -> None:
    """The number has to reach the claim, or it is a report nobody acts on."""
    with Memory(repo) as mem:
        _worked(mem, "Cursor", rounds=4, finishing=False)
        took, _ = mem.claim_if_free("the parser", "Cursor", _when(0))
        assert took

        held = [c for c in mem.claims() if c["topic"] == "the parser"]
        assert held and held[0]["holds"] == record.FLOOR, held


@pytest.mark.critical
def test_an_abandoners_claim_frees_sooner_than_a_finishers(knos_home, repo) -> None:
    """The whole point, as behaviour rather than as a stored number."""
    with Memory(repo) as mem:
        _worked(mem, "Cursor", rounds=4, finishing=False)
        _worked(mem, "Claude Code", rounds=4, finishing=True)

        # Both claimed twenty minutes ago: past the abandoner's earned hold
        # of fifteen minutes, well inside the finisher's forty-five.
        mem.claim_if_free("the parser", "Cursor", _when(20))
        mem.claim_if_free("the lexer", "Claude Code", _when(20))

        live = {c["topic"] for c in mem.claims()}
        assert "the lexer" in live, "a reliable agent lost its work early"
        assert "the parser" not in live, "an abandoner still holds the file"

        # And the freed one can actually be taken by somebody else.
        took, _ = mem.claim_if_free("the parser", "Claude Code", _when(0))
        assert took, "the lapsed claim did not actually release"


@pytest.mark.critical
def test_finishing_is_what_the_store_learns_from(knos_home, repo) -> None:
    """`knos done` has to leave the trace, or nothing is ever learned."""
    with Memory(repo) as mem:
        mem.claim_if_free("the parser", "Cursor", _when(0))
        mem.done_working()

        taken, finished = record.history(mem, "Cursor")
        assert taken == 1, "claiming was not recorded"
        assert finished == 1, "finishing was not recorded"


@pytest.mark.critical
def test_the_learning_dies_with_the_store(knos_home, repo) -> None:
    """Delete the memory and every agent is a stranger again."""
    from knos import paths

    with Memory(repo) as mem:
        _worked(mem, "Cursor", rounds=4, finishing=False)
        assert record.holds_for(mem, "Cursor") == record.FLOOR

    store = paths.store_for(repo)
    store.unlink()

    with Memory(repo) as mem:
        assert record.holds_for(mem, "Cursor") == record.UNKNOWN, (
            "the record survived the store being deleted, so it was not "
            "living in the store"
        )


def test_the_published_contention_numbers_are_the_ones_quoted() -> None:
    """A figure a judge is pointed at should be one a test regenerates."""
    import json
    from pathlib import Path

    where = Path(__file__).resolve().parents[1] / "docs" / "evidence" / "contention.json"
    assert where.exists(), "run: python scripts/contention.py"
    got = json.loads(where.read_text(encoding="utf-8"))

    flat = next(a for a in got["arms"] if a["arm"] == "flat")
    learned = next(a for a in got["arms"] if a["arm"] == "learned")

    # The learned arm must wait less and get more done, or the whole module
    # is an ornament on the claim.
    assert learned["blocked_minutes"] < flat["blocked_minutes"]
    assert learned["worked"] >= flat["worked"]
    assert got["minutes_saved"] == flat["blocked_minutes"] - learned["blocked_minutes"]
    assert 0 < got["percent_less_waiting"] < 100
