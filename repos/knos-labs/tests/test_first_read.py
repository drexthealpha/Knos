"""The first question must not take longer than a client will wait.

An MCP client gives a server about thirty seconds to come up. The first
question on a repo knos has never read does the whole read inline, and on a
repository of any size that read is longer than the timeout - so the server
never starts and the product does not exist for that person. That happened in
a real session: `knos (CONNECT_TIMEOUT): connection timed out after 30000ms`,
against a read measured at forty seconds on this repository.

The code reader already had a budget for exactly this reason, and the code
reader is not where the time goes: eleven hundred session facts are.

Two properties, and the second is the one that keeps it honest. The read stops
when the clock runs out, and an answer built on a half-read repo says so -
because an agent cannot otherwise tell a repo with nothing in it from a repo
knos has not finished looking at, and silently returning the first is how a
tool teaches somebody it is useless.

Rewritten for 0.2.0: the cut-off is now forced (a budget no read can meet) instead of a 60-commit repo that
might or might not run out, which let the old test pass whichever way it went. A cut-off read is finished by the
next `refresh.ensure`, because offsets and the signature are only saved after a complete read.
"""

from __future__ import annotations

import time

import pytest

from knos import answer, mcp, refresh
from knos.memory import Memory


# A budget the read cannot possibly meet, so the cut-off path is taken every time rather than on a slow day.
# (Not 0: `point` treats a budget of 0 as no budget at all.)
NO_TIME = 1e-6


def test_the_read_stops_when_the_clock_does(knos_home, repo) -> None:
    """A read that runs out of time stops, and says so in its counts rather than being a smaller repo."""
    with Memory(repo) as mem:
        start = time.perf_counter()
        counts = answer.point(repo, mem, budget=NO_TIME)
        took = time.perf_counter() - start

    assert counts["ran_out"] == 1, "the budget was spent before the commits and the read did not say so"
    assert counts["commits"] == 0, "it kept reading commits after its time was up"
    assert counts["code"] == 0, "it read the code structure after its time was up"
    assert took < 20, f"a read with no time left took {took:.0f}s"


def test_a_cut_off_read_is_finished_by_the_next_one(knos_home, repo) -> None:
    """The half that makes a cut-off first read acceptable: nothing it skipped is skipped for good."""
    first = refresh.ensure(repo, budget=NO_TIME)
    assert first is not None and first["ran_out"] == 1
    assert first["commits"] == 0

    # The cut-off read must not record the repo as read, so the next check reads again.
    refresh._last_check.clear()
    later = refresh.ensure(repo)
    assert later is not None, "a cut-off read was recorded as complete, so the rest is never read"
    assert later["ran_out"] == 0
    assert later["commits"] >= 1

    with Memory(repo) as mem:
        found = answer.ask(repo, mem, "why did we drop redis")
    assert any(p.source == "git" for p in found), "the commit skipped by the first read is still missing"

    # And once it is whole, nothing new means nothing read.
    refresh._last_check.clear()
    assert refresh.ensure(repo) is None


def test_an_agent_can_still_ask_after_a_cut_off_read(knos_home, repo) -> None:
    refresh.ensure(repo, budget=NO_TIME)
    said = mcp.search("why did we drop redis")
    assert isinstance(said, str) and said


@pytest.mark.critical
def test_an_answer_after_a_real_cut_off_says_so_until_a_full_read(knos_home, repo) -> None:
    counts = refresh.ensure(repo, budget=NO_TIME)
    assert counts is not None and counts["ran_out"] == 1
    with Memory(repo) as mem:
        assert "has not finished reading" in mcp._unfinished(mem)
    refresh.ensure(repo, force=True)
    with Memory(repo) as mem:
        assert mcp._unfinished(mem) == ""


def test_no_budget_still_reads_everything(knos_home, repo) -> None:
    """`knos point` passes none, and must behave exactly as it always has."""
    with Memory(repo) as mem:
        counts = answer.point(repo, mem, budget=None)

    assert counts["ran_out"] == 0


@pytest.mark.critical
def test_an_answer_from_a_half_read_repo_says_so(knos_home, repo) -> None:
    """The honest half. Silence here teaches an agent the repo is empty."""
    with Memory(repo) as mem:
        mem.set_reference(mcp.PARTIAL, {"partial": True, "sessions": 743})
        said = mcp._unfinished(mem)

    assert "has not finished reading" in said
    assert "743" in said, "it has to say how much, or it is just an apology"
    assert "knos point" in said, "a warning without the fix is half a warning"


def test_a_fully_read_repo_says_nothing_extra(knos_home, repo) -> None:
    """The notice must not become furniture on every answer forever."""
    with Memory(repo) as mem:
        assert mcp._unfinished(mem) == ""


def test_the_budget_is_under_what_a_client_waits(knos_home) -> None:
    """The number that matters, kept where somebody will see it change."""
    assert mcp.FIRST_READ_BUDGET < 30, (
        "the first read is budgeted at or past the client timeout it exists "
        "to stay under"
    )
    assert mcp.FIRST_READ_BUDGET >= 5, (
        "so short that a normal repo gets a half read for no reason"
    )
