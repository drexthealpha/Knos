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
    """STRONG rounds, because the ends of the range have to be earned.

    Four used to be enough, back when the ratio alone decided and two events
    could swing the whole fifteen-to-forty-five range. The prior holds while
    the evidence is thin and lets go past STRONG, so the ceiling is still
    reachable - it just is not reachable on an afternoon.
    """
    with Memory(repo) as mem:
        _worked(mem, "Claude Code", rounds=record.STRONG, finishing=True)

        assert record.holds_for(mem, "Claude Code") == record.CEILING
        assert record.reliability(mem, "Claude Code")["kept"] == 1.0


def test_an_agent_that_abandons_its_work_holds_it_for_less(knos_home, repo) -> None:
    with Memory(repo) as mem:
        _worked(mem, "Cursor", rounds=record.STRONG, finishing=False)

        assert record.holds_for(mem, "Cursor") == record.FLOOR
        assert record.holds_for(mem, "Cursor") < record.UNKNOWN


def test_two_events_do_not_swing_the_whole_range(knos_home, repo) -> None:
    """The overreaction the prior exists to stop.

    An agent that took two claims and closed neither used to drop straight to
    the floor - a 3x change in what everybody else is kept waiting, decided by
    two events. It still moves the right way, it just moves a little.
    """
    with Memory(repo) as mem:
        _worked(mem, "Unlucky", rounds=2, finishing=False)

        held = record.holds_for(mem, "Unlucky")

        assert held < record.UNKNOWN, "two abandoned claims should still count"
        assert held > record.FLOOR, (
            "two events are not a measurement and must not earn the floor"
        )


def test_evidence_gets_lighter_when_an_agent_goes_quiet(knos_home, repo) -> None:
    """A name that finished everything in the spring is not that name now.

    Decay pulls a quiet agent back toward the prior rather than below it: this
    is forgetting, not a penalty, so the number moves down from the ceiling
    and never past the middle.
    """
    from datetime import datetime, timedelta, timezone

    old_days = record.HALF_LIFE_DAYS * 3
    then = (datetime.now(timezone.utc) - timedelta(days=old_days)).isoformat()

    with Memory(repo) as mem:
        for n in range(record.STRONG * 2):
            record.note_taken(mem, f"t{n}", "Seasonal", then)
            record.note_finished(mem, f"t{n}", "Seasonal", then)

        quiet = record.standing(mem, "Seasonal")

        assert quiet["quiet_days"] >= old_days - 1
        assert quiet["weight"] < 0.2, "three half-lives should weigh very little"
        assert record.UNKNOWN <= record.holds_for(mem, "Seasonal") < record.CEILING, (
            "a stale record should drift toward the prior, not below it"
        )


def test_the_record_outlives_the_journal_window(knos_home, repo) -> None:
    """The reason any of this was written.

    `entries` reads the last thousand journal rows and a store holds about a
    thousand facts, so on a busy repo an agent's oldest claims fall off the
    back and it drifts towards looking new again. The promoted WARM record
    does not live in that window.
    """
    with Memory(repo) as mem:
        _worked(mem, "Busy", rounds=record.STRONG, finishing=True)

        promoted = mem.thing(record.STANDING, "Busy")
        assert promoted, "an agent with a real record should have been promoted"

        body = promoted.get("body") if isinstance(promoted.get("body"), dict) else promoted
        assert int(body["taken"]) == record.STRONG
        assert int(body["finished"]) == record.STRONG
        assert record.standing(mem, "Busy")["promoted"] is True


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
        _worked(mem, "Cursor", rounds=record.STRONG, finishing=False)
        took, _ = mem.claim_if_free("the parser", "Cursor", _when(0))
        assert took

        held = [c for c in mem.claims() if c["topic"] == "the parser"]
        assert held and held[0]["holds"] == record.FLOOR, held


@pytest.mark.critical
def test_an_abandoners_claim_frees_sooner_than_a_finishers(knos_home, repo) -> None:
    """The whole point, as behaviour rather than as a stored number."""
    with Memory(repo) as mem:
        _worked(mem, "Cursor", rounds=record.STRONG, finishing=False)
        _worked(mem, "Claude Code", rounds=record.STRONG, finishing=True)

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
        _worked(mem, "Cursor", rounds=record.STRONG, finishing=False)
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


def test_who_explains_a_quiet_agent_rather_than_looking_broken(
    knos_home, repo, capsys
) -> None:
    """A row reading "100% closed, 32 min" is arithmetic that does not work.

    The hold comes from the shrunk and aged figure, not the raw ratio, so an
    agent that has been quiet for months looks like the tool is miscounting
    unless the number actually being used is on the row beside it.
    """
    from datetime import datetime, timedelta, timezone

    from knos import cli

    quiet = (datetime.now(timezone.utc)
             - timedelta(days=record.HALF_LIFE_DAYS * 3)).isoformat()
    with Memory(repo) as mem:
        for n in range(record.STRONG + 2):
            record.note_taken(mem, f"t{n}", "an old runner", quiet)
            record.note_finished(mem, f"t{n}", "an old runner", quiet)

    cli.who()
    said = capsys.readouterr().out

    assert "counted" in said, "the number the hold is computed from is not shown"
    assert "quiet" in said, "a stale record does not say it is stale"
    assert "100%" in said, "the raw ratio is a fact and should still be there"
