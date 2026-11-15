"""A tool whose value is entirely in things that did not happen gets uninstalled.

Every refusal in knos is invisible when it works. An agent reaches for a file
somebody else holds, the edit guard refuses it, the agent picks up something
else, and the person never sees any of it. The collision that did not happen
leaves no trace in the day.

`knos worth` is where it left one. These check the two things that make it
worth having: the numbers come from records written at the time (claims.db's
events, and the store's withdrawn rules) rather than from a counter that could
drift, and the zero case says so plainly instead of finding something
flattering to report.

Rewritten for 0.2.0 (claims in claims.db, refusals recorded by the edit guard). Dropped (behaviour removed):
  - test_an_override_is_counted_separately_from_a_stand_down (no stand-down or override any more)
  - test_the_same_agent_standing_down_twice_counts_once (stand-downs are gone; every guard refusal is an event)
  - test_it_dies_with_the_store (the counts come from claims.db, not the Sibyl store)
"""

from __future__ import annotations

import pytest

from knos import guard, worth
from knos.claims import Claims
from knos.cli import main
from knos.identity import Agent
from knos.memory import Memory

CLAUDE = Agent(host="claude", session="aaaa1111bbbb")
CURSOR = Agent(host="cursor", session="cccc2222dddd")
OPENCODE = Agent(host="opencode", session="eeee3333ffff")


def _claim(repo, agent=CLAUDE, what="the login", globs=("src/auth.py",)) -> None:
    with Claims(repo) as c:
        took, _, _ = c.take(agent, what, list(globs))
    assert took


def _refused(repo, agent) -> None:
    """An agent tries to edit the claimed file and the real guard refuses it."""
    verdict = guard.check(repo, str(repo / "src" / "auth.py"), agent)
    assert not verdict.allow, "the guard let another agent edit a claimed file"


def _tally(repo):
    with Memory(repo) as mem:
        return worth.tally(repo, mem)


def test_an_untouched_repo_says_it_has_done_nothing(knos_home, repo) -> None:
    """The honest zero. A tool that reports a flattering number here is lying."""
    got = _tally(repo)
    said = worth.sentence(got)

    assert (got["claimed"], got["released"], got["blocked"], got["agents"], got["live"], got["withdrawn"]) == (
        0, 0, 0, 0, 0, 0)
    assert got["first"] == got["last"] == ""
    assert said == "Nothing has been claimed here yet, so there has been nothing to refuse."


def test_claims_with_no_collision_are_not_dressed_up(knos_home, repo) -> None:
    """Work happening is not the same as knos having been needed."""
    _claim(repo)
    got = _tally(repo)
    said = worth.sentence(got)

    assert got["claimed"] == 1 and got["blocked"] == 0
    assert said.startswith("One claim here"), said
    assert "Nothing has collided" in said, said


@pytest.mark.critical
def test_it_counts_the_edits_that_were_refused(knos_home, repo) -> None:
    _claim(repo)
    _refused(repo, CURSOR)
    _refused(repo, OPENCODE)

    got = _tally(repo)
    said = worth.sentence(got)

    assert got["blocked"] == 2
    assert got["claimed"] == 1 and got["agents"] == 1 and got["live"] == 1
    assert "The guard refused an edit to a file another agent held 2 times" in said, said


def test_the_holder_editing_its_own_file_is_not_a_refusal(knos_home, repo) -> None:
    """A number that counted an agent's own edits would be flattering and false."""
    _claim(repo)
    assert guard.check(repo, str(repo / "src" / "auth.py"), CLAUDE).allow

    assert _tally(repo)["blocked"] == 0


def test_releases_and_agents_are_counted(knos_home, repo) -> None:
    _claim(repo, CLAUDE, "the login", ("src/auth.py",))
    _claim(repo, CURSOR, "the readme", ("README.md",))
    with Claims(repo) as c:
        assert c.release(CLAUDE)

    got = _tally(repo)
    assert got["claimed"] == 2
    assert got["agents"] == 2
    assert got["released"] == 1
    assert got["live"] == 1


def test_it_does_not_say_between_a_day_and_the_same_day(knos_home, repo) -> None:
    """Small, and the sort of thing that costs a reader's trust in the rest."""
    _claim(repo)
    _refused(repo, CURSOR)
    got = _tally(repo)
    said = worth.sentence(got)

    assert got["first"] == got["last"] != ""
    assert "between" not in said, said
    assert f", on {got['first']}." in said, said


def test_it_counts_in_english(knos_home, repo) -> None:
    _claim(repo)
    _refused(repo, CURSOR)
    one = worth.sentence(_tally(repo))
    _refused(repo, OPENCODE)
    two = worth.sentence(_tally(repo))

    assert "held once, on " in one, one
    assert "held 2 times, on " in two, two
    assert "time(s)" not in one + two


def test_knos_worth_prints_the_counts(knos_home, repo, capsys) -> None:
    _claim(repo)
    _refused(repo, CURSOR)
    capsys.readouterr()

    assert main(["worth"]) == 0
    said = capsys.readouterr().out
    assert "The guard refused an edit to a file another agent held once" in said, said
    assert "claimed       1   by 1 agent(s); 1 live now" in said, said
    assert "blocked       1" in said, said
    assert "withdrawn     0" in said, said


def test_knos_worth_says_nothing_happened_when_nothing_did(knos_home, repo, capsys) -> None:
    capsys.readouterr()
    assert main(["worth"]) == 0
    said = capsys.readouterr().out
    assert "Nothing has been claimed here yet" in said, said
    assert "blocked       0" in said, said
