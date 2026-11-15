"""Claims: the one thing knos stores that goes out of date.

Everything else in the store is about what happened, and stays true. A claim is about what is happening, so it
stops being true on its own: it lapses after its hold unless refreshed, and a released or lapsed claim never blocks.

Rewritten for 0.2.0, where a claim is a set of path globs held by one agent (host, session, anchor) in claims.db, and
knos never withholds an answer: it annotates answers with who holds the files they touch, and the edit guard refuses
edits to another agent's files.

Dropped, because their purpose no longer exists in 0.2.0:
  - the stand-down tests (a second agent records it stood down, yields once, not to itself, finishing clears the
    locks, a third agent stands down to both): nobody stands down any more; answers are always given.
  - the withholding tests (withholds the answer, paraphrased question withheld, withholding dies with the store,
    one agent is enough to feel the withhold as a withhold): nothing is withheld. Their surviving purposes are
    rewritten below as "the answer is given and annotated" and "a person's claim refuses their agent's edit".
  - the override tests (override unlocks and is written down, holds for that claim only, release clears overrides):
    there are no overrides.
  - the stemming / topic-word tests (a claim covers the word in all its shapes, stemming is not greedy,
    a subject matcher): claims are path globs now; prose never matches. Replaced by "prose never blocks" and
    "`*` does not cross directories".
  - "the whole pattern dies with the store": coordination lives in claims.db, not in the Sibyl memory store.
  - "the time is the soonest of several holds" and "no time is promised when it cannot be worked out": a file is
    covered by at most one blocking claim, and the refusal's time comes from guard.refusal (tested below), not the
    0.1 answer._lapses_in helper.
"""

from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

import knos
from knos import guard, identity, mcp
from knos.claims import HOLDS_MIN, Claims, claims_db, lookup_session, resolve
from knos.identity import Agent
from knos.memory import Fact, Memory

CLAUDE = Agent(host="claude", session="sess-claude-1", anchor=4101)
CURSOR = Agent(host="cursor", session="sess-cursor-1", anchor=4202)
WINDSURF = Agent(host="windsurf", session="sess-windsurf", anchor=4303)


def _age(repo, minutes: float, description: str | None = None, stamp: str | None = None) -> None:
    """Move claims back in time (all, or one by description), the way a clock would."""
    when = stamp or (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()
    conn = sqlite3.connect(str(claims_db(repo)))
    try:
        if description is None:
            conn.execute("UPDATE claims SET taken_at=?, refreshed_at=?", (when, when))
        else:
            conn.execute("UPDATE claims SET taken_at=?, refreshed_at=? WHERE description=?", (when, when, description))
        conn.commit()
    finally:
        conn.close()


def _take(repo, agent, description, globs=None, holds_min=HOLDS_MIN):
    with Claims(repo) as c:
        return c.take(agent, description, globs, holds_min=holds_min)


def _live(repo):
    with Claims(repo) as c:
        return c.live()


def _about(repo, text):
    with Claims(repo) as c:
        return c.about(text)


# ---- lapsing ------------------------------------------------------------------------------


def test_a_claim_lapses_so_a_stale_claim_is_never_shown(knos_home, repo):
    """An agent that said it was mid-change an hour ago is not a reason to hesitate now."""
    took, _, mine = _take(repo, CLAUDE, "fixing login", ["src/auth.py"])
    assert took and mine is not None
    assert [c.id for c in _live(repo)] == [mine.id]
    assert _about(repo, "how does src/auth.py work")

    _age(repo, HOLDS_MIN + 1)
    assert _live(repo) == []
    assert _about(repo, "how does src/auth.py work") == []
    with Claims(repo) as c:
        assert c.holder("src/auth.py", CURSOR) is None


@pytest.mark.critical
def test_a_claim_lapses_so_a_crashed_agent_cannot_hold_work_forever(knos_home, repo):
    """An agent that dies mid-change never calls done. The work frees up on its own, and the next agent can take it."""
    assert _take(repo, CLAUDE, "fixing login", ["src/auth.py"])[0]
    assert _take(repo, CURSOR, "also login", ["src/auth.py"])[0] is False

    _age(repo, HOLDS_MIN + 1)

    took, conflict, mine = _take(repo, CURSOR, "also login", ["src/auth.py"])
    assert took is True and conflict is None
    assert mine is not None and mine.host == "cursor"
    assert guard.check(repo, str(repo / "src" / "auth.py"), CURSOR).allow


def test_a_timestamp_that_cannot_be_read_counts_as_over(knos_home, repo):
    """Never leave a claim standing because a date would not parse."""
    assert _take(repo, CLAUDE, "fixing login", ["src/auth.py"])[0]
    _age(repo, 0, stamp="not a date at all")
    assert _live(repo) == []
    assert guard.check(repo, str(repo / "src" / "auth.py"), CURSOR).allow


def test_one_claim_expiring_does_not_take_the_others_with_it(knos_home, repo):
    assert _take(repo, CLAUDE, "fixing login", ["src/auth.py"])[0]
    assert _take(repo, CURSOR, "the readme", ["README.md"])[0]
    _age(repo, HOLDS_MIN + 1, description="fixing login")

    assert [c.description for c in _live(repo)] == ["the readme"]
    assert _about(repo, "src/auth.py") == []
    assert [c.host for c in _about(repo, "README.md")] == ["cursor"]


def test_retaking_your_own_claim_refreshes_it_rather_than_duplicating(knos_home, repo):
    """Claiming again is how an agent keeps a long job; it must not pile up rows or reset who got there first."""
    _, _, first = _take(repo, CLAUDE, "fixing login", ["src/auth.py"])
    _age(repo, 20)
    took, conflict, again = _take(repo, CLAUDE, "fixing login", ["src/auth.py"])

    assert took and conflict is None
    assert again.id == first.id
    assert len(_live(repo)) == 1
    assert again.minutes_left > HOLDS_MIN - 1, "refreshing did not restart the hold"


def test_an_agent_can_say_it_has_finished(knos_home, repo):
    assert _take(repo, CURSOR, "fixing login", ["src/auth.py"])[0]
    with Claims(repo) as c:
        gone = c.release(CURSOR)
    assert [g.description for g in gone] == ["fixing login"]
    assert _live(repo) == []
    assert guard.check(repo, str(repo / "src" / "auth.py"), CLAUDE).allow


# ---- what other agents are told ------------------------------------------------------------


def test_the_annotation_says_who_and_since_not_a_date(knos_home, repo):
    """"cursor since 14:05" is actionable. An ISO date is not."""
    assert _take(repo, CURSOR, "fixing login", ["src/auth.py"])[0]
    _age(repo, 5)

    said = mcp._claim_notes(repo, "how does src/auth.py log people in", CLAUDE)

    assert said.startswith("[claimed] src/auth.py is claimed by cursor/sess-cur since "), said
    assert re.search(r"since \d\d:\d\d \(fixing login\)", said), said
    assert not re.search(r"20\d\d-\d\d-\d\d", said), "no ISO date in what an agent reads"


def test_a_claim_only_annotates_the_thing_it_is_about(knos_home, repo):
    """A note on every question is a note nobody reads."""
    assert _take(repo, CURSOR, "fixing login", ["src/auth.py"])[0]
    assert [c.host for c in _about(repo, "what does src/auth.py return")] == ["cursor"]
    assert [c.host for c in _about(repo, "is auth.py tested")] == ["cursor"]
    assert _about(repo, "the deploy window") == []
    assert mcp._claim_notes(repo, "the deploy window", CLAUDE) == ""


def test_every_agent_tool_answers_and_says_who_holds_it(knos_home, repo):
    """Which tool an agent reaches for must not decide whether it finds out somebody is already on this, and neither
    tool hides what it knows."""
    with Memory(repo) as mem:
        mem.record(Fact(text="login in src/auth.py always returns true until the SSO work lands",
                        source="session", where="Claude Code session aaaa1111 2026-08-20", when="2026-08-20",
                        path="src/auth.py"))
    assert _take(repo, CURSOR, "fixing login", ["src/auth.py"])[0]

    searched = mcp.search("why does login in src/auth.py always return true")
    assert searched.startswith("[claimed] src/auth.py is claimed by cursor/"), searched
    assert "until the SSO work lands" in searched, "the answer was withheld"
    assert not searched.startswith("Withheld")

    about = mcp.about("src/auth.py")
    assert "[claimed] src/auth.py is claimed by cursor/" in about, about


def test_two_agents_can_hold_separate_work_at_once(knos_home, repo):
    """One claim per piece of work, not one per repo. A third agent asking about either is told about that one only."""
    assert _take(repo, CLAUDE, "fixing login", ["src/auth.py"])[0]
    assert _take(repo, CURSOR, "the readme", ["README.md"])[0]
    assert len(_live(repo)) == 2

    login = mcp._claim_notes(repo, "how does src/auth.py work", WINDSURF)
    readme = mcp._claim_notes(repo, "what does README.md say", WINDSURF)

    assert "claude/sess-cla" in login and "cursor" not in login
    assert "cursor/sess-cur" in readme and "claude" not in readme
    assert mcp._claim_notes(repo, "the deploy window", WINDSURF) == ""

    assert not guard.check(repo, str(repo / "src" / "auth.py"), CURSOR).allow
    assert not guard.check(repo, str(repo / "README.md"), CLAUDE).allow


def test_a_third_agent_asking_about_both_is_told_about_both(knos_home, repo):
    assert _take(repo, CLAUDE, "fixing login", ["src/auth.py"])[0]
    assert _take(repo, CURSOR, "the readme", ["README.md"])[0]

    said = mcp._claim_notes(repo, "src/auth.py and README.md", WINDSURF)
    lines = said.splitlines()
    assert len(lines) == 2, said
    assert any("claude/" in line and "fixing login" in line for line in lines)
    assert any("cursor/" in line and "the readme" in line for line in lines)


def test_the_agent_holding_the_claim_is_never_blocked_or_told_about_itself(knos_home, repo):
    assert _take(repo, CLAUDE, "fixing login", ["src/auth.py"])[0]
    assert guard.check(repo, str(repo / "src" / "auth.py"), CLAUDE).allow
    assert mcp._claim_notes(repo, "src/auth.py", CLAUDE) == ""
    # and everybody else is
    assert not guard.check(repo, str(repo / "src" / "auth.py"), CURSOR).allow


@pytest.mark.critical
def test_a_refused_agent_is_told_when_the_work_frees_up(knos_home, repo):
    """"Come back later" is not usable advice without a later."""
    assert _take(repo, CLAUDE, "fixing login", ["src/auth.py"])[0]
    _age(repo, 8)

    verdict = guard.check(repo, str(repo / "src" / "auth.py"), CURSOR)
    assert not verdict.allow
    assert "claimed by claude/sess-cla" in verdict.reason
    assert "lapses in 22 min" in verdict.reason, verdict.reason
    assert "knos done --all" in verdict.reason, "a person has to be told how to end it early"


# ---- what a claim covers -------------------------------------------------------------------


def test_a_claim_reaches_the_file_it_names(knos_home, repo):
    """A description that names a file claims that file, by path or by name; prose names nothing."""
    assert resolve(repo, "tidy src/auth.py before the release") == ["src/auth.py"]
    assert resolve(repo, "the bug in auth.py") == ["src/auth.py"]
    assert resolve(repo, "the authentication rewrite") == []

    took, _, mine = _take(repo, CLAUDE, "tidy src/auth.py before the release")
    assert took and not mine.advisory and mine.globs == ("src/auth.py",)
    assert not guard.check(repo, str(repo / "src" / "auth.py"), CURSOR).allow


def test_prose_alone_never_blocks_anything(knos_home, repo):
    """Sharing words is not sharing files. A claim nothing resolves for is advisory: shown, never enforced."""
    took, _, mine = _take(repo, CLAUDE, "the parser rewrite")
    assert took and mine.advisory and mine.globs == ()

    assert guard.check(repo, str(repo / "src" / "auth.py"), CURSOR).allow
    took, conflict, _ = _take(repo, CURSOR, "fixing login", ["src/auth.py"])
    assert took and conflict is None
    # and a second advisory claim on the same words is not refused either
    assert _take(repo, WINDSURF, "the parser rewrite")[0]
    # but it is still shown to the others
    assert [c.host for c in _about(repo, "how is the parser rewrite going")] == ["claude", "windsurf"]


def test_a_single_star_does_not_cross_directories(knos_home, repo):
    """`src/*` is the files in src; `src/**` is everything under it."""
    assert _take(repo, CLAUDE, "top of src", ["src/*"])[0]
    assert _take(repo, CURSOR, "deep module", ["src/deep/mod.py"])[0], "`*` claimed a subdirectory"
    assert _take(repo, WINDSURF, "src itself", ["src/auth.py"])[0] is False

    with Claims(repo) as c:
        c.release(CLAUDE)
    assert _take(repo, CLAUDE, "all of src", ["src/**"])[0] is False, "`**` did not reach the claimed subdirectory"


# ---- identity: who holds a claim -------------------------------------------------------------


def test_naming_yourself_the_holder_does_not_get_you_past_the_guard(knos_home, repo):
    """A client can call itself anything. Same host, different session and process is a different agent."""
    assert _take(repo, CLAUDE, "fixing login", ["src/auth.py"])[0]
    impostor = Agent(host="claude", session="sess-other", anchor=9999)

    assert not impostor.owns(CLAUDE.host, CLAUDE.session, CLAUDE.anchor)
    assert not guard.check(repo, str(repo / "src" / "auth.py"), impostor).allow


@pytest.mark.critical
def test_naming_yourself_the_holder_does_not_let_you_take_the_claim_either(knos_home, repo):
    """The write side binds to the session as well as the read side: an impostor cannot re-take the holder's claim
    and walk out of its own refusal."""
    _, _, first = _take(repo, CLAUDE, "fixing login", ["src/auth.py"])
    impostor = Agent(host="claude", session="sess-other", anchor=9999)

    took, conflict, mine = _take(repo, impostor, "fixing login", ["src/auth.py"])
    assert took is False and mine is None
    assert conflict is not None and conflict.session == CLAUDE.session

    # The session that made it can still restate it.
    took, _, again = _take(repo, CLAUDE, "fixing login", ["src/auth.py"])
    assert took and again.id == first.id


def test_a_reconnect_keeps_the_claim(knos_home, repo):
    """The same host process (anchor) with a new session id is the same agent: a reconnected MCP server is not
    refused by its own claim."""
    assert _take(repo, CLAUDE, "fixing login", ["src/auth.py"])[0]
    reconnected = Agent(host="claude", session="sess-claude-2", anchor=CLAUDE.anchor)
    assert guard.check(repo, str(repo / "src" / "auth.py"), reconnected).allow
    assert _take(repo, reconnected, "fixing login again", ["src/auth.py"])[0]


def test_two_sessions_of_one_host_are_two_agents(knos_home, repo):
    assert _take(repo, CLAUDE, "fixing login", ["src/auth.py"])[0]
    other_chat = Agent(host="claude", session="sess-claude-9", anchor=5555)
    assert not guard.check(repo, str(repo / "src" / "auth.py"), other_chat).allow


def test_a_claim_written_without_a_session_is_still_its_hosts(knos_home, repo):
    """Older claims are no weaker than they were, and no stronger."""
    bare = Agent(host="cursor")
    assert bare.owns("cursor", "", None)
    assert not bare.owns("claude", "", None)

    assert _take(repo, bare, "fixing login", ["src/auth.py"])[0]
    assert _take(repo, Agent(host="cursor"), "fixing login", ["src/auth.py"])[0] is True
    assert _take(repo, CLAUDE, "fixing login", ["src/auth.py"])[0] is False


def test_the_mcp_server_and_the_hooks_of_one_session_are_one_agent(knos_home, repo, monkeypatch):
    """The MCP server is never told the session id; SessionStart records it against the host process, and the
    server finds it there. So a claim taken over MCP is never refused by the same session's edit hook."""
    monkeypatch.setattr(identity, "ancestors", lambda pid=None: [(3001, "node"), (4242, "claude")])
    with Claims(repo) as c:
        c.record_session("claude", "sess-abc", 4242)

    served = identity.for_mcp("claude-code", lookup_session(repo))
    hooked = identity.for_hook("claude", {"session_id": "sess-abc"})
    assert served == Agent(host="claude", session="sess-abc", anchor=4242)
    assert hooked == served

    assert _take(repo, served, "fixing login", ["src/auth.py"])[0]
    assert guard.check(repo, str(repo / "src" / "auth.py"), hooked).allow


# ---- people ---------------------------------------------------------------------------------


def _as_a_person(monkeypatch):
    """The CLI decides person or agent from the process tree; the test is a person at a terminal."""
    monkeypatch.setattr(identity, "ancestors", lambda pid=None: [])


def test_a_person_can_claim_work_without_going_through_an_agent(knos_home, repo, monkeypatch):
    """The person is the one who can resolve a collision, so they can fence work off before starting it."""
    from typer.testing import CliRunner

    from knos.cli import app

    _as_a_person(monkeypatch)
    runner = CliRunner()

    got = runner.invoke(app, ["claim", "fixing login", "-p", "src/auth.py"])
    assert got.exit_code == 0, got.output
    assert "Claimed src/auth.py" in got.output
    live = _live(repo)
    assert [(c.host, c.globs) for c in live] == [("terminal", ("src/auth.py",))]

    # Asking about it says so, in front of the person.
    said = runner.invoke(app, ["ask", "what does src/auth.py do"]).output
    assert "You hold src/auth.py (fixing login)" in said, said

    got = runner.invoke(app, ["done"])
    assert got.exit_code == 0, got.output
    assert "Released src/auth.py" in got.output
    assert _live(repo) == []


def test_one_agent_is_enough_to_feel_a_claim(knos_home, repo, monkeypatch):
    """A person claims work at the terminal; their only agent's edit is refused, and told whose it is."""
    from typer.testing import CliRunner

    from knos.cli import app

    _as_a_person(monkeypatch)
    assert CliRunner().invoke(app, ["claim", "fixing login", "-p", "src/auth.py"]).exit_code == 0

    verdict = guard.check(repo, str(repo / "src" / "auth.py"), CLAUDE)
    assert not verdict.allow
    assert "claimed by terminal/" in verdict.reason
    assert "fixing login" in verdict.reason

    assert CliRunner().invoke(app, ["done"]).exit_code == 0
    assert guard.check(repo, str(repo / "src" / "auth.py"), CLAUDE).allow


def test_a_person_is_told_who_has_it_when_the_claim_is_refused(knos_home, repo, monkeypatch):
    from typer.testing import CliRunner

    from knos.cli import Stop, app

    assert _take(repo, CURSOR, "fixing login", ["src/auth.py"])[0]
    _as_a_person(monkeypatch)
    got = CliRunner().invoke(app, ["claim", "my login work", "-p", "src/**"])
    assert got.exit_code != 0
    # `knos` prints a Stop as one line (cli.main); under the runner it surfaces as the exception.
    assert isinstance(got.exception, Stop), got.output
    assert "held by cursor/sess-cur" in got.exception.said, got.exception.said
    assert "fixing login" in got.exception.said
    assert [c.host for c in _live(repo)] == ["cursor"]


# ---- the server ---------------------------------------------------------------------------


@pytest.mark.critical
def test_the_server_tells_agents_what_to_do_about_a_claim(knos_home, repo):
    """An agent has to be told the rule before it is held to it, so the instructions and tool descriptions carry it."""
    said = mcp.server.instructions or ""
    assert "claim them" in said
    assert "refused by the knos edit guard" in said
    assert "done()" in said
    assert "withheld" not in said.lower() and "override" not in said.lower()
    assert "say who holds them" in (mcp.search.__doc__ or "")
    assert "claiming" in (mcp.remember.__doc__ or "") and "paths" in (mcp.remember.__doc__ or "")
    assert "Only ever your own" in (mcp.done.__doc__ or "")


def test_the_server_names_its_own_version(knos_home, repo):
    """A client is told the version in the handshake. An empty string is what you get by not passing one."""
    said = knos.version()
    assert said, "the server would introduce itself with no version"
    assert re.fullmatch(r"\d+\.\d+\.\d+.*|0\+unknown", said), said
    assert mcp.server.version == said


# ---- concurrency: two processes, one file ------------------------------------------------------


@pytest.mark.critical
def test_two_processes_claiming_the_same_file_only_one_wins(knos_home, repo, tmp_path):
    """The claim is one transaction, not a blind write. Real processes, because the lock that has to hold is
    SQLite's, across process boundaries. The claim is given as a description naming the file, so resolving it is
    inside the race too."""
    import json
    import subprocess
    import sys
    from concurrent.futures import ThreadPoolExecutor

    script = tmp_path / "grab.py"
    script.write_text(
        "import json, sys\n"
        "from knos.claims import Claims\n"
        "from knos.identity import Agent\n"
        "repo, who = sys.argv[1], sys.argv[2]\n"
        "with Claims(repo) as c:\n"
        "    took, conflict, mine = c.take(Agent(host=who, session='s-' + who), 'rework src/auth.py')\n"
        "print(json.dumps({'who': who, 'took': took, 'holder': conflict.host if conflict else None,\n"
        "                  'globs': list(mine.globs) if mine else None}))\n",
        encoding="utf-8",
    )

    def grab(who: str) -> dict:
        done = subprocess.run([sys.executable, str(script), str(repo), who], capture_output=True, text=True)
        assert done.returncode == 0, done.stderr
        return json.loads(done.stdout.strip().splitlines()[-1])

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = (f.result() for f in [pool.submit(grab, "claude"), pool.submit(grab, "cursor")])

    winners = [r for r in (first, second) if r["took"]]
    losers = [r for r in (first, second) if not r["took"]]
    assert len(winners) == 1 and len(losers) == 1, (first, second)
    assert winners[0]["globs"] == ["src/auth.py"], "the description did not resolve to the file, so nothing raced"
    # The loser is told who actually has it, not a bare refusal.
    assert losers[0]["holder"] == winners[0]["who"], (first, second)

    live = _live(repo)
    assert [c.host for c in live] == [winners[0]["who"]]
