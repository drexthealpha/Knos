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
store, so starting the store over makes every agent a stranger worth exactly
thirty minutes, which is the behaviour knos had before any of this.

0.2.0: the record is keyed by host name, claims live in claims.db, and the hold reaches a claim through
`mcp.remember(claiming=True)`; `mcp.done` is what writes the finish. Rewritten from `Memory.claim_if_free` /
`claims` / `done_working`, which are gone. `knos who` no longer prints the raw ratio or a "quiet" note; its test now
checks that the hold on each row is the one a claim would actually get. Nothing dropped.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from knos import record
from knos.claims import Claims
from knos.identity import Agent
from knos.memory import Memory, StoreGone


def _when(minutes_ago: int = 0) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()


def _worked(mem, who: str, rounds: int, finishing: bool) -> None:
    """`who` takes and either closes or abandons `rounds` pieces of work."""
    for n in range(rounds):
        topic = f"task {who} {n}"
        record.note_taken(mem, topic, who, _when(200 - n))
        if finishing:
            record.note_finished(mem, topic, who, _when(199 - n))


def _mcp_host() -> str:
    """The host name the MCP server records for a client that gives no name (what these tests call it with)."""
    from knos import identity

    return identity.host_from_client("agent")


def test_an_agent_nobody_has_seen_gets_the_old_default(knos_home, repo) -> None:
    with Memory(repo) as mem:
        assert record.holds_for(mem, "cursor") == record.UNKNOWN == 30


def test_one_claim_is_not_enough_to_judge_anyone_on(knos_home, repo) -> None:
    """A single event is noise. Nobody is punished for being new."""
    with Memory(repo) as mem:
        _worked(mem, "cursor", rounds=1, finishing=False)
        assert record.holds_for(mem, "cursor") == record.UNKNOWN


def test_an_agent_that_finishes_earns_a_longer_hold(knos_home, repo) -> None:
    """STRONG rounds, because the ends of the range have to be earned.

    The prior holds while the evidence is thin and lets go past STRONG, so the
    ceiling is still reachable - it just is not reachable on an afternoon.
    """
    with Memory(repo) as mem:
        _worked(mem, "claude", rounds=record.STRONG, finishing=True)

        assert record.holds_for(mem, "claude") == record.CEILING
        assert record.reliability(mem, "claude")["kept"] == 1.0


def test_an_agent_that_abandons_its_work_holds_it_for_less(knos_home, repo) -> None:
    with Memory(repo) as mem:
        _worked(mem, "cursor", rounds=record.STRONG, finishing=False)

        assert record.holds_for(mem, "cursor") == record.FLOOR
        assert record.holds_for(mem, "cursor") < record.UNKNOWN


def test_two_events_do_not_swing_the_whole_range(knos_home, repo) -> None:
    """The overreaction the prior exists to stop.

    An agent that took two claims and closed neither used to drop straight to
    the floor - a 3x change in what everybody else is kept waiting, decided by
    two events. It still moves the right way, it just moves a little.
    """
    with Memory(repo) as mem:
        _worked(mem, "unlucky", rounds=2, finishing=False)

        held = record.holds_for(mem, "unlucky")

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
    old_days = record.HALF_LIFE_DAYS * 3
    then = (datetime.now(timezone.utc) - timedelta(days=old_days)).isoformat()

    with Memory(repo) as mem:
        for n in range(record.STRONG * 2):
            record.note_taken(mem, f"t{n}", "seasonal", then)
            record.note_finished(mem, f"t{n}", "seasonal", then)

        quiet = record.standing(mem, "seasonal")

        assert quiet["quiet_days"] >= old_days - 1
        assert quiet["weight"] < 0.2, "three half-lives should weigh very little"
        assert record.UNKNOWN <= record.holds_for(mem, "seasonal") < record.CEILING, (
            "a stale record should drift toward the prior, not below it"
        )


def test_the_record_outlives_the_journal_window(knos_home, repo) -> None:
    """The reason any of this was written.

    `entries` reads the last thousand journal rows, so on a busy repo an
    agent's oldest claims fall off the back and it drifts towards looking new
    again. The promoted WARM record does not live in that window.
    """
    with Memory(repo) as mem:
        _worked(mem, "busy", rounds=record.STRONG, finishing=True)

        promoted = mem.thing(record.STANDING, "busy")
        assert promoted, "an agent with a real record should have been promoted"

        body = promoted.get("body") if isinstance(promoted.get("body"), dict) else promoted
        assert int(body["taken"]) == record.STRONG
        assert int(body["finished"]) == record.STRONG
        assert record.standing(mem, "busy")["promoted"] is True


def test_the_record_is_per_agent_not_a_single_global_mood(knos_home, repo) -> None:
    with Memory(repo) as mem:
        _worked(mem, "claude", rounds=3, finishing=True)
        _worked(mem, "cursor", rounds=3, finishing=False)

        assert record.holds_for(mem, "claude") > record.holds_for(mem, "cursor")
        names = [r["who"] for r in record.everyone(mem)]
        assert names[0] == "cursor", "the worst record should sort first"


@pytest.mark.critical
def test_the_learned_hold_is_what_the_claim_actually_expires_on(knos_home, repo) -> None:
    """The number has to reach the claim, or it is a report nobody acts on."""
    from knos import mcp

    who = _mcp_host()
    with Memory(repo) as mem:
        _worked(mem, who, rounds=record.STRONG, finishing=False)
        assert record.holds_for(mem, who) == record.FLOOR

    said = mcp.remember("rewriting the login", "the parser", claiming=True, paths=["src/auth.py"])
    assert f"for {record.FLOOR} min" in said, said

    with Claims(repo) as c:
        held = [x for x in c.live() if x.description == "the parser"]
    assert held and held[0].holds_min == record.FLOOR, held


@pytest.mark.critical
def test_an_abandoners_claim_frees_sooner_than_a_finishers(knos_home, repo) -> None:
    """The whole point, as behaviour rather than as a stored number."""
    abandoner = Agent(host="cursor", session="cccc2222dddd")
    finisher = Agent(host="claude", session="aaaa1111bbbb")
    with Memory(repo) as mem:
        _worked(mem, "cursor", rounds=record.STRONG, finishing=False)
        _worked(mem, "claude", rounds=record.STRONG, finishing=True)
        cursor_holds = record.holds_for(mem, "cursor")
        claude_holds = record.holds_for(mem, "claude")

    with Claims(repo) as c:
        assert c.take(abandoner, "the login", ["src/auth.py"], holds_min=cursor_holds)[0]
        assert c.take(finisher, "the readme", ["README.md"], holds_min=claude_holds)[0]
        # Both claimed twenty minutes ago: past the abandoner's earned hold of
        # fifteen minutes, well inside the finisher's forty-five.
        c.conn.execute("UPDATE claims SET taken_at = ?, refreshed_at = ?", (_when(20), _when(20)))

        live = {x.description for x in c.live()}
        assert "the readme" in live, "a reliable agent lost its work early"
        assert "the login" not in live, "an abandoner still holds the file"

        # And the freed one can actually be taken by somebody else.
        took, conflict, _ = c.take(finisher, "the login", ["src/auth.py"])
        assert took and conflict is None, "the lapsed claim did not actually release"


@pytest.mark.critical
def test_finishing_is_what_the_store_learns_from(knos_home, repo) -> None:
    """`done` has to leave the trace, or nothing is ever learned."""
    from knos import mcp

    said = mcp.remember("rewriting the login", "the parser", claiming=True, paths=["src/auth.py"])
    assert "Claimed src/auth.py" in said, said
    assert mcp.done().startswith("Released:")

    with Memory(repo) as mem:
        taken, finished = record.history(mem, _mcp_host())
    assert taken == 1, "claiming was not recorded"
    assert finished == 1, "finishing was not recorded"


def test_a_claim_left_to_lapse_is_not_a_finish(knos_home, repo) -> None:
    """Only `done` counts as closing. An agent that walks away has taken, not finished."""
    from knos import mcp

    mcp.remember("rewriting the login", "the parser", claiming=True, paths=["src/auth.py"])

    with Memory(repo) as mem:
        assert record.history(mem, _mcp_host()) == (1, 0)


@pytest.mark.critical
def test_the_learning_dies_with_the_store(knos_home, repo) -> None:
    """Delete the memory and every agent is a stranger again."""
    from knos import paths, refresh

    with Memory(repo) as mem:
        _worked(mem, "cursor", rounds=record.STRONG, finishing=False)
        assert record.holds_for(mem, "cursor") == record.FLOOR

    paths.store_for(repo).unlink()
    with pytest.raises(StoreGone):
        Memory(repo)

    refresh.reset(repo)
    with Memory(repo) as mem:
        assert record.holds_for(mem, "cursor") == record.UNKNOWN, (
            "the record survived the store being started over, so it was not "
            "living in the store"
        )


def test_who_shows_the_hold_a_claim_would_actually_get(knos_home, repo, capsys) -> None:
    """A row whose hold is not the one the next claim gets is a report nobody can check.

    A quiet agent that closed everything is the case that looks wrong (all closed, well short of the ceiling), so the
    number on its row has to be the aged one `holds_for` gives, not one worked out from the raw ratio.
    """
    from knos.cli import main

    quiet = (datetime.now(timezone.utc) - timedelta(days=record.HALF_LIFE_DAYS * 3)).isoformat()
    with Memory(repo) as mem:
        for n in range(record.STRONG + 2):
            record.note_taken(mem, f"t{n}", "an old runner", quiet)
            record.note_finished(mem, f"t{n}", "an old runner", quiet)
        holds = record.holds_for(mem, "an old runner")
    assert record.UNKNOWN <= holds < record.CEILING

    capsys.readouterr()
    assert main(["who"]) == 0
    said = capsys.readouterr().out

    row = next(line for line in said.splitlines() if "an old runner" in line)
    assert row.split()[-4:] == [str(record.STRONG + 2), str(record.STRONG + 2), str(holds), "min"], row


def test_who_says_so_when_nobody_has_claimed_anything(knos_home, repo, capsys) -> None:
    from knos.cli import main

    capsys.readouterr()
    assert main(["who"]) == 0
    said = capsys.readouterr().out
    assert f"Nobody has claimed anything here yet. Every agent starts at {record.UNKNOWN} minutes." in said
