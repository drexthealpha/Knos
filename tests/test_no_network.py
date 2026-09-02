"""Knos does not talk to anything.

Every other memory tool on the comparison list either binds ports, downloads
a model, or wants an API key. Saying "local-first" is cheap; this asserts it
by breaking the socket layer and then doing a full day's work — read a repo,
ask it questions, write to it, claim, withhold, override — with no way to
reach the network at all.

`knos share` is the deliberate exception: it sends one transaction to Base
because a permission two people rely on cannot live only on one of their
machines. It is the only thing here that opens a socket, it happens when a
person types it, and nothing on this path touches it.
"""

from __future__ import annotations

import socket
from datetime import datetime, timezone

import pytest

from knos import answer, mcp, private
from knos.memory import TOPIC, Fact, Memory


class Blocked(AssertionError):
    """Raised the moment anything tries to reach the network."""


@pytest.fixture()
def no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise Blocked("knos tried to open a network connection")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket.socket, "bind", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)


def test_a_whole_day_of_work_happens_with_the_network_broken(
    knos_home, repo, no_network
):
    now = datetime.now(timezone.utc).isoformat()

    with Memory(repo) as mem:
        counts = answer.point(repo, mem, index_code=True, code_budget=5.0)
        assert counts["commits"] >= 1

        # Ask it things, including the slow structural path.
        assert answer.ask(repo, mem, "why did we drop redis")
        answer.ask(repo, mem, "where is login defined")

        # Write to it, and coordinate.
        mem.record(
            Fact(text="we chose sqlite", source="note", where="you said so",
                 when=now, about="storage")
        )
        mem.note_thing(TOPIC, "storage", {"note": "we chose sqlite", "when": now[:10]})
        mem.working_on("the parser", "Claude Code", now)
        assert mcp._held(mem, "the parser", "Cursor", "").startswith("Withheld.")
        mcp._took_it_anyway(mem, "the parser", "Cursor", "the build is broken")
        assert mem.coordination()
        assert mem.only_here() > 0
        mem.done_working()

        # And the private path stays private without asking anything.
        assert private.is_private(repo, ".env")


def test_the_agent_facing_tools_do_not_reach_the_network(
    knos_home, repo, no_network, monkeypatch
):
    """The path an agent actually drives, including the read on first use."""
    monkeypatch.chdir(repo)
    said = mcp.search("why did we drop redis")
    assert "redis" in said.lower(), said
    assert "Nothing known" not in said
    mcp.remember("the retry logic moved to auth.py", "retries")
    assert "retr" in mcp.about("retries").lower()


def test_the_guard_itself_works(knos_home, no_network):
    """A test that cannot fail is not evidence."""
    with pytest.raises(Blocked):
        socket.create_connection(("example.com", 80))


def test_a_live_session_sees_a_claim_made_by_another_process(knos_home, repo, monkeypatch):
    """The complaint was that a shared backend "isn't as good at agents
    working together live - they don't always pull the newest context every
    action". Knos opens the store per call, so there is no context to be
    stale: the next call sees what another process just wrote."""
    from datetime import datetime, timezone

    monkeypatch.chdir(repo)

    # Agent B asks, and is told nothing is held.
    with Memory(repo) as mem:
        assert mcp._held(mem, "the tokeniser", "Cursor", "") == ""

    # A different process claims it.
    with Memory(repo) as other:
        other.working_on(
            "the tokeniser", "Claude Code", datetime.now(timezone.utc).isoformat()
        )

    # B's very next call sees it, with nothing reloaded or restarted.
    with Memory(repo) as mem:
        assert mcp._held(mem, "the tokeniser", "Cursor", "").startswith("Withheld.")
