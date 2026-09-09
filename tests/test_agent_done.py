"""An agent could take work and never say it had finished.

`remember(claiming=true)` is how an agent takes work over MCP. There was no
matching way to close it: `knos done` is a command a person types, and an
agent cannot type it. So every agent claim lapsed instead of closing, and
three things downstream were broken for the users this product is for.

  - Other agents waited out the whole hold on work already done.
  - `record.holds_for` learns from the share of claims an agent closed, so
    every agent sat at zero and sank to the fifteen minute floor.
  - `record.may_spend` refuses an agent that has taken work three or more
    times and closed less than a third. Every agent qualified, permanently,
    and the refusal told it to run `knos done`, which it cannot.

Two features were dead on arrival for agents and the tests all passed, because
every test drove the claim loop from Python or the CLI - never through the
surface an agent actually has.
"""

from __future__ import annotations

import pytest

from knos import mcp, record
from knos.memory import Memory


@pytest.fixture(autouse=True)
def _here(repo, monkeypatch):
    monkeypatch.chdir(repo)


@pytest.mark.critical
def test_an_agent_can_close_what_it_claimed(knos_home, repo) -> None:
    mcp.remember("starting on the parser", "the parser", claiming=True)
    assert [c["topic"] for c in _claims(repo)] == ["the parser"]

    said = mcp.done("the parser")

    assert "Finished: the parser" in said
    assert _claims(repo) == [], "the claim outlived the agent saying it was done"


@pytest.mark.critical
def test_closing_is_what_the_record_learns_from(knos_home, repo) -> None:
    """The whole point. Without this every agent's record is zero for ever."""
    mcp.remember("starting on the parser", "the parser", claiming=True)
    mcp.done("the parser")

    with Memory(repo) as mem:
        taken, finished = record.history(mem, "an agent")

    assert (taken, finished) == (1, 1), (
        "an agent closed its work and the memory did not notice, so no agent "
        "can ever earn a longer hold or the right to spend"
    )


@pytest.mark.critical
def test_it_closes_only_the_caller_s_own_claims(knos_home, repo) -> None:
    """`knos done` clears everything, which is right for a person and wrong
    for one agent among several: it would hand away work its colleagues are
    still in the middle of."""
    with Memory(repo) as mem:
        mem.claim_if_free("the lexer", "Cursor", record._now())

    mcp.remember("starting on the parser", "the parser", claiming=True)
    mcp.done()

    held = {c["topic"]: c["who"] for c in _claims(repo)}
    assert held == {"the lexer": "Cursor"}, held


def test_closing_nothing_says_so_rather_than_pretending(knos_home, repo) -> None:
    said = mcp.done("the parser")

    assert "not holding the parser" in said
    assert "only ever closes your own" in said


def test_closing_everything_you_hold_is_one_call(knos_home, repo) -> None:
    mcp.remember("a", "the parser", claiming=True)
    mcp.remember("b", "the lexer", claiming=True)

    said = mcp.done()

    assert "the parser" in said and "the lexer" in said
    assert _claims(repo) == []


def test_every_tool_an_agent_needs_is_registered(knos_home) -> None:
    """The bug hid because nothing asserted the surface an agent actually has.

    It was found by a decorator landing between `remember`'s decorator and its
    function, which silently unregistered `remember` - the tool that writes
    anything at all - and the server logged one warning and carried on.
    """
    names = {tool.name for tool in mcp.server._tool_manager.list_tools()}

    assert names == {"search", "about", "remember", "done"}, names


def _claims(repo):
    with Memory(repo) as mem:
        return mem.claims()
