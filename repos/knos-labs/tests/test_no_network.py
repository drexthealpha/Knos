"""Knos's coding-agent memory does not talk to anything (jobs and teams use their chain's RPC; this is the rest).

Every other memory tool on the comparison list either binds ports, downloads
a model, or wants an API key. Saying "local-first" is cheap; this asserts it
by recording every attempt to reach anything but this machine and then doing a
full day's work - read a repo, ask it questions, remember, claim, be refused by
the guard, release - and checking the record is empty.

conftest.py already refuses non-loopback sockets for every test; the fixture
here records as well as refuses, so a swallowed error inside knos cannot hide
an attempt.

Dropped in 0.2.0 (removed behaviour): the withhold/override path
(`mcp._held`, `mcp._took_it_anyway`, `Memory.working_on`, `Memory.coordination`,
`Memory.done_working`). Answers are no longer withheld; claims are path globs in
claims.db, enforced by the edit guard. The day and the live-claim test below
drive that instead.
"""

from __future__ import annotations

import socket
from types import SimpleNamespace

import pytest

from knos import answer, guard, mcp, private, refresh
from knos.claims import Claims
from knos.identity import Agent
from knos.memory import Memory

pytestmark = pytest.mark.critical

_LOCAL = ("127.0.0.1", "::1", "localhost", None, "")


class Blocked(AssertionError):
    """Raised the moment anything tries to reach the network."""


@pytest.fixture()
def attempts(monkeypatch):
    """Every non-loopback connection or lookup knos tries, recorded and refused."""
    tried: list[str] = []
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex
    real_getaddrinfo = socket.getaddrinfo

    def _remote(address) -> str | None:
        host = address[0] if isinstance(address, tuple) else address
        if isinstance(host, str) and host not in _LOCAL and not host.startswith("/"):
            return host
        return None

    def connect(self, address):
        host = _remote(address) if self.family in (socket.AF_INET, socket.AF_INET6) else None
        if host:
            tried.append(f"connect {host}")
            raise Blocked(f"knos tried to reach {host}")
        return real_connect(self, address)

    def connect_ex(self, address):
        host = _remote(address) if self.family in (socket.AF_INET, socket.AF_INET6) else None
        if host:
            tried.append(f"connect_ex {host}")
            raise Blocked(f"knos tried to reach {host}")
        return real_connect_ex(self, address)

    def getaddrinfo(host, *args, **kwargs):
        if _remote((host,)):
            tried.append(f"getaddrinfo {host}")
            raise Blocked(f"knos tried to look up {host}")
        return real_getaddrinfo(host, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket.socket, "connect_ex", connect_ex)
    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
    return tried


def _ctx(client: str):
    """The slice of an MCP request context knos reads: the client's name."""
    info = SimpleNamespace(name=client)
    return SimpleNamespace(request_context=SimpleNamespace(
        session=SimpleNamespace(client_params=SimpleNamespace(client_info=info))))


def test_a_whole_day_of_work_opens_no_socket(knos_home, repo, attempts):
    # Read the repo, the way the MCP server does on first use, including the code structure.
    counts = refresh.ensure(repo, force=True, index_code=True)
    assert counts is not None and counts["commits"] >= 1

    # Ask it things, including the slow structural path.
    with Memory(repo) as mem:
        assert answer.ask(repo, mem, "why did we drop redis")
        answer.ask(repo, mem, "where is login defined")
    assert "redis" in mcp.search("why did we drop redis", ctx=_ctx("claude-code")).lower()

    # Remember, and claim a file.
    said = mcp.remember("login moves to token auth", "the login rewrite", claiming=True,
                        paths=["src/auth.py"], ctx=_ctx("claude-code"))
    assert "Claimed src/auth.py" in said, said

    # Another agent asks: nothing is hidden, the claim is named.
    other = mcp.search("login", ctx=_ctx("Cursor"))
    assert "[claimed] src/auth.py" in other, other

    # Another agent edits: the guard refuses it.
    assert not guard.check(repo, str(repo / "src" / "auth.py"), Agent(host="cursor", session="c-1")).allow

    # Done: the claim is released and the other agent may edit.
    assert mcp.done(ctx=_ctx("claude-code")).startswith("Released")
    assert guard.check(repo, str(repo / "src" / "auth.py"), Agent(host="cursor", session="c-1")).allow

    # And the private path stays private without asking anything.
    assert private.is_private(repo, ".env")

    assert attempts == [], f"a day of work reached for the network: {attempts}"


def test_the_agent_facing_tools_do_not_reach_the_network(knos_home, repo, attempts):
    """The path an agent actually drives, including the lazy read on first use."""
    said = mcp.search("why did we drop redis")
    assert "redis" in said.lower(), said
    assert "Nothing known" not in said
    mcp.remember("the retry logic moved to auth.py", "retries")
    assert "retr" in mcp.about("retries").lower()
    assert attempts == []


def test_the_guard_itself_works(attempts):
    """A test that cannot fail is not evidence."""
    with pytest.raises(Blocked):
        socket.create_connection(("example.com", 80))
    assert attempts == ["getaddrinfo example.com"]


def test_a_live_session_sees_a_claim_made_by_another_process(knos_home, repo):
    """Knos opens the claim list per call, so there is no context to be stale: the next call sees what another
    process just wrote."""
    asking = Agent(host="cursor", session="b-1")
    holder = Agent(host="claude", session="a-1")

    with Claims(repo) as c:
        assert c.holder("src/tokeniser.py", asking) is None

    with Claims(repo) as other:
        took, conflict, _mine = other.take(holder, "the tokeniser", ["src/tokeniser.py"])
    assert took and conflict is None

    with Claims(repo) as c:
        held = c.holder("src/tokeniser.py", asking)
    assert held is not None and held.held_by(holder)
    assert not guard.check(repo, str(repo / "src" / "tokeniser.py"), asking).allow
