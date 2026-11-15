"""An agent can take work and must be able to say it has finished.

`remember(claiming=true, paths=[...])` is how an agent claims files over MCP; `done` is how it gives them back. Without
`done`, every agent claim lapsed instead of closing: other agents waited out the whole hold on finished work, and
`record.holds_for` (which learns from the share of claims an agent closed) sat every agent at zero. These tests drive
the loop through the surface an agent actually has, the MCP tools, not through Python helpers.

Rewritten for 0.2.0: claims are path globs in claims.db, `done` releases only the caller's own claims, and a person
can release everyone's with `knos done --all` (after confirming, or with `--yes`). Nothing was dropped; the two
`knos done --all` tests are new, because that is now the only way to release another agent's claim.
"""

from __future__ import annotations

import pytest

from knos import mcp, record
from knos.claims import Claims
from knos.identity import Agent
from knos.memory import Memory

CURSOR = Agent(host="cursor", session="sess-cursor-1", anchor=4202)


@pytest.fixture(autouse=True)
def _here(repo, monkeypatch):
    monkeypatch.chdir(repo)


def _live(repo):
    with Claims(repo) as c:
        return c.live()


def _me(repo):
    """The identity the MCP tools act as in this process (no client name given)."""
    return mcp._agent(repo, None)


@pytest.mark.critical
def test_an_agent_can_close_what_it_claimed(knos_home, repo) -> None:
    said = mcp.remember("starting on login", "fixing login", claiming=True, paths=["src/auth.py"])
    assert "Claimed src/auth.py" in said, said
    assert [(c.description, c.globs) for c in _live(repo)] == [("fixing login", ("src/auth.py",))]

    said = mcp.done("fixing login")

    assert said.startswith("Released: fixing login (src/auth.py)"), said
    assert _live(repo) == [], "the claim outlived the agent saying it was done"


@pytest.mark.critical
def test_closing_is_what_the_record_learns_from(knos_home, repo) -> None:
    """Without this every agent's record is zero for ever."""
    mcp.remember("starting on login", "fixing login", claiming=True, paths=["src/auth.py"])
    mcp.done("fixing login")

    host = _me(repo).host
    with Memory(repo) as mem:
        taken, finished = record.history(mem, host)

    assert (taken, finished) == (1, 1), (
        "an agent closed its work and the memory did not notice, so no agent can ever earn a longer hold"
    )


@pytest.mark.critical
def test_it_closes_only_the_caller_s_own_claims(knos_home, repo) -> None:
    """Releasing everything is right for a person and wrong for one agent among several: it would hand away work
    its colleagues are still in the middle of."""
    with Claims(repo) as c:
        assert c.take(CURSOR, "the readme", ["README.md"])[0]

    mcp.remember("starting on login", "fixing login", claiming=True, paths=["src/auth.py"])
    said = mcp.done()

    assert "fixing login" in said and "the readme" not in said, said
    assert [(c.host, c.description) for c in _live(repo)] == [("cursor", "the readme")]


def test_an_agent_cannot_close_another_agent_s_claim_by_naming_it(knos_home, repo) -> None:
    with Claims(repo) as c:
        _, _, theirs = c.take(CURSOR, "the readme", ["README.md"])

    for named in ("the readme", theirs.id):
        said = mcp.done(named)
        assert "You hold no claim on" in said, said
    assert [c.id for c in _live(repo)] == [theirs.id]


def test_closing_nothing_says_so_rather_than_pretending(knos_home, repo) -> None:
    said = mcp.done("fixing login")

    assert "You hold no claim on fixing login here." in said
    assert "this only ever releases your own" in said

    assert mcp.done().startswith("You hold no claims here."), "an empty done() must not claim to have released"


def test_closing_everything_you_hold_is_one_call(knos_home, repo) -> None:
    mcp.remember("a", "fixing login", claiming=True, paths=["src/auth.py"])
    mcp.remember("b", "the readme", claiming=True, paths=["README.md"])
    assert len(_live(repo)) == 2

    said = mcp.done()

    assert "fixing login" in said and "the readme" in said, said
    assert _live(repo) == []


def test_a_refused_claim_names_the_holder_and_takes_nothing(knos_home, repo) -> None:
    """The other half of the loop: an agent reaching for claimed files is told who has them, and gets nothing to
    close later."""
    with Claims(repo) as c:
        assert c.take(CURSOR, "fixing login", ["src/auth.py"])[0]

    said = mcp.remember("starting on login", "my login work", claiming=True, paths=["src/**"])

    assert "Not claimed: src/auth.py is held by cursor/sess-cur" in said, said
    assert [c.host for c in _live(repo)] == ["cursor"]
    assert mcp.done().startswith("You hold no claims here.")


def test_a_person_can_release_every_agent_s_claims(knos_home, repo, monkeypatch) -> None:
    """When an agent has walked away from a claim, the person is the one who ends it: `knos done --all --yes`."""
    from typer.testing import CliRunner

    from knos import identity
    from knos.cli import app

    with Claims(repo) as c:
        assert c.take(CURSOR, "the readme", ["README.md"])[0]
    mcp.remember("starting on login", "fixing login", claiming=True, paths=["src/auth.py"])
    monkeypatch.setattr(identity, "ancestors", lambda pid=None: [])  # a person at a terminal

    got = CliRunner().invoke(app, ["done", "--all", "--yes"])

    assert got.exit_code == 0, got.output
    assert "Released README.md" in got.output and "Released src/auth.py" in got.output, got.output
    assert _live(repo) == []


def test_releasing_everyone_s_asks_first(knos_home, repo, monkeypatch) -> None:
    """Without --yes, and with nobody at a terminal to answer, nothing of anybody else's is released."""
    from typer.testing import CliRunner

    from knos import identity
    from knos.cli import Stop, app

    with Claims(repo) as c:
        assert c.take(CURSOR, "the readme", ["README.md"])[0]
    monkeypatch.setattr(identity, "ancestors", lambda pid=None: [])

    got = CliRunner().invoke(app, ["done", "--all"])

    assert isinstance(got.exception, Stop), got.output
    assert got.exception.said == "Nothing released."
    assert [c.host for c in _live(repo)] == ["cursor"]


def test_every_tool_an_agent_needs_is_registered(knos_home) -> None:
    """The bug hid because nothing asserted the surface an agent actually has. It was found by a decorator landing
    between `remember`'s decorator and its function, which silently unregistered `remember`."""
    names = {tool.name for tool in mcp.server._tool_manager.list_tools()}

    assert names == {"search", "about", "remember", "done", "pay", "post_job", "find_jobs", "claim_job", "deliver_job"}, names
