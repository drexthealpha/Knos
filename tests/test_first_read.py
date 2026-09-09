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
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

import pytest

from knos import answer, mcp, paths
from knos.memory import Memory


@pytest.fixture()
def wordy(knos_home, repo):
    """A repo with more history than a first question can afford to read."""
    for n in range(60):
        (repo / f"mod{n}.py").write_text(f"def f{n}():\n    return {n}\n",
                                         encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=repo, capture_output=True)
        subprocess.run(["git", "commit", "-qm", f"add mod{n}"], cwd=repo,
                       capture_output=True)
    return repo


def test_the_read_stops_when_the_clock_does(wordy) -> None:
    with Memory(wordy) as mem:
        start = time.perf_counter()
        counts = answer.point(wordy, mem, budget=1.0)
        took = time.perf_counter() - start

    assert took < 20, f"a one second budget took {took:.0f}s"
    # It either finished inside the budget or said it did not. Both are fine;
    # running long without saying so is not.
    assert counts["ran_out"] in (0, 1)


def test_no_budget_still_reads_everything(knos_home, repo) -> None:
    """`knos point` passes none, and must behave exactly as it always has."""
    with Memory(repo) as mem:
        counts = answer.point(repo, mem, budget=None)

    assert counts["ran_out"] == 0


@pytest.mark.critical
def test_an_answer_from_a_half_read_repo_says_so(knos_home, repo) -> None:
    """The honest half. Silence here teaches an agent the repo is empty."""
    with Memory(repo) as mem:
        mem.set_reference(mcp.PARTIAL, {"sessions": 743})
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
