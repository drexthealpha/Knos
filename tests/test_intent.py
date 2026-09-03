"""Short-lived intent: the one thing knos stores that goes out of date.

Everything else in the store is about what happened, and stays true. This is
about what is happening, so it stops being true on its own.
"""

from __future__ import annotations

import pytest

from datetime import datetime, timedelta, timezone

import knos
from knos import mcp
from knos import paths as knos_paths
from knos.memory import INTENT_HOLDS, Memory


def _worked(repo, thing, asker=""):
    """The coordination read, given its own store the way a tool gives it one."""
    with Memory(repo) as mem:
        return mcp._being_worked_on(mem, thing, asker=asker)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def test_intent_expires_so_a_stale_warning_is_never_shown(knos_home, repo):
    """An agent that said it was mid-change an hour ago is not a reason to
    hesitate now."""
    knos_paths.remember_pointed(repo)
    with Memory(repo) as mem:
        mem.working_on("parser", "Claude Code", _now())
        assert mem.current_work() is not None
        assert "started working on parser" in _worked(repo, "parser")

        stale = datetime.now(timezone.utc) - timedelta(minutes=INTENT_HOLDS + 1)
        mem.working_on("parser", "Claude Code", stale.isoformat())
        assert mem.current_work() is None
        assert _worked(repo, "parser") == ""


def test_an_agent_can_say_it_has_finished(knos_home, repo):
    with Memory(repo) as mem:
        mem.working_on("parser", "Cursor", _now())
        assert mem.current_work() is not None
        mem.done_working()
        assert mem.current_work() is None


def test_a_timestamp_that_cannot_be_read_counts_as_over(knos_home, repo):
    """Never leave a warning standing because a date would not parse."""
    with Memory(repo) as mem:
        mem.working_on("parser", "Cursor", "not a date at all")
        assert mem.current_work() is None


def test_the_warning_says_how_long_ago_not_a_date(knos_home, repo):
    """"Two minutes ago" is actionable. A date is not."""
    knos_paths.remember_pointed(repo)
    older = datetime.now(timezone.utc) - timedelta(minutes=5)
    with Memory(repo) as mem:
        mem.working_on("parser", "Cursor", older.isoformat())
    said = _worked(repo, "parser")
    assert "5 minutes ago" in said
    assert "20" not in said  # no year, no ISO date


def test_intent_only_fires_for_the_thing_it_is_about(knos_home, repo):
    """A warning on every question is a warning nobody reads."""
    knos_paths.remember_pointed(repo)
    with Memory(repo) as mem:
        mem.working_on("parser", "Cursor", _now())
    assert _worked(repo, "the parser rewrite") != ""
    assert _worked(repo, "the deploy window") == ""


# ---- the coordination pattern: claim, yield, release -------------------


def test_a_second_agent_records_that_it_stood_down(knos_home, repo):
    """Two writers, one store, and neither agent ever calls the other.

    The first puts what it is doing into HOT. The second reads it, is told
    to hold off, and writes down that it yielded. Afterwards you can see who
    stood down for whom, which a notice board alone does not give you.
    """
    knos_paths.remember_pointed(repo)
    with Memory(repo) as mem:
        mem.working_on("risk guard", "Claude Code", _now())

    assert _worked(repo, "risk guard", asker="Cursor")

    with Memory(repo) as mem:
        yielded = mem.stand_downs()
    assert len(yielded) == 1
    assert yielded[0]["who"] == "Cursor"
    assert yielded[0]["claimed_by"] == "Claude Code"
    assert yielded[0]["topic"] == "risk guard"


def test_a_chatty_agent_yields_once_not_every_time_it_asks(knos_home, repo):
    """The warm record is the lock that keeps the journal readable."""
    knos_paths.remember_pointed(repo)
    with Memory(repo) as mem:
        mem.working_on("risk guard", "Claude Code", _now())

    for _ in range(5):
        _worked(repo, "risk guard", asker="Cursor")

    with Memory(repo) as mem:
        assert len(mem.stand_downs()) == 1
        lines = [
            e for e in mem.journal(limit=1000)
            if "stood down" in str(e.get("evaluated", ""))
        ]
    assert len(lines) == 1


def test_the_agent_holding_the_claim_does_not_stand_down_to_itself(knos_home, repo):
    knos_paths.remember_pointed(repo)
    with Memory(repo) as mem:
        mem.working_on("risk guard", "Claude Code", _now())

    _worked(repo, "risk guard", asker="Claude Code")

    with Memory(repo) as mem:
        assert mem.stand_downs() == []


def test_finishing_releases_the_claim_and_the_locks(knos_home, repo):
    """The pattern has an end: the next claim warns everybody again."""
    knos_paths.remember_pointed(repo)
    with Memory(repo) as mem:
        mem.working_on("risk guard", "Claude Code", _now())
    _worked(repo, "risk guard", asker="Cursor")

    with Memory(repo) as mem:
        assert mem.stand_downs()
        mem.done_working()
        assert mem.current_work() is None
        assert mem.stand_downs() == []
        # the journal keeps the trace; only the locks go
        assert any(
            "stood down" in str(e.get("evaluated", ""))
            for e in mem.journal(limit=1000)
        )


def test_the_whole_pattern_dies_with_the_store(knos_home, repo):
    """Coordination is Sibyl. Delete it and there is nothing left."""
    knos_paths.remember_pointed(repo)
    with Memory(repo) as mem:
        mem.working_on("risk guard", "Claude Code", _now())
        db = mem.db_path
    _worked(repo, "risk guard", asker="Cursor")

    db.unlink()

    with Memory(repo) as fresh:
        assert fresh.current_work() is None
        assert fresh.stand_downs() == []
    assert _worked(repo, "risk guard", asker="Cursor") == ""


def test_a_claim_covers_the_word_in_all_its_shapes(knos_home, repo):
    """parser, parsers, parsing and parsed are one word to a person."""
    knos_paths.remember_pointed(repo)
    with Memory(repo) as mem:
        mem.working_on("parser", "Claude Code", _now())

    for asked in ("the parsing logic", "who wrote the parsers", "it parsed wrong"):
        assert _worked(repo, asked) != "", asked


def test_stemming_does_not_make_the_claim_greedy(knos_home, repo):
    """Sharing letters is not sharing a subject."""
    knos_paths.remember_pointed(repo)
    with Memory(repo) as mem:
        mem.working_on("guard", "Claude Code", _now())

    assert _worked(repo, "safeguarding the vanguard") == ""
    assert _worked(repo, "the deploy window") == ""
    assert _worked(repo, "the guards on that route") != ""


def test_every_agent_tool_says_when_someone_is_mid_change(knos_home, repo):
    """Which tool an agent happens to reach for must not decide whether it
    finds out that somebody else is already on this."""
    from knos.memory import Fact

    knos_paths.remember_pointed(repo)
    with Memory(repo) as mem:
        mem.record(
            Fact(
                text="the risk guard refuses unknown assets",
                source="session",
                where="Claude Code session aaaa1111 2026-08-20",
                when="2026-08-20",
            )
        )
        mem.working_on("risk guard", "Claude Code", _now())

    # search withholds outright; about says who holds it.
    assert mcp.search("risk guard").startswith("Withheld.")
    said = mcp.about("risk guard")
    assert "started working on risk guard" in said, said


def test_two_agents_can_hold_separate_work_at_once(knos_home, repo):
    """One claim per piece of work, not one per repo.

    Two agents on genuinely different things can both say so, and a third
    asking about either is told about that one only.
    """
    knos_paths.remember_pointed(repo)
    with Memory(repo) as mem:
        mem.working_on("parser", "Claude Code", _now())
        mem.working_on("deploy window", "Cursor", _now())
        assert len(mem.claims()) == 2

    parser = _worked(repo, "the parsing logic")
    deploys = _worked(repo, "when do we deploy")

    assert "Claude Code started working on parser" in parser
    assert "Cursor" not in parser
    assert "Cursor started working on deploy window" in deploys
    assert "Claude Code" not in deploys
    assert _worked(repo, "the risk guard") == ""


def test_one_claim_expiring_does_not_take_the_others_with_it(knos_home, repo):
    knos_paths.remember_pointed(repo)
    stale = datetime.now(timezone.utc) - timedelta(minutes=INTENT_HOLDS + 1)
    with Memory(repo) as mem:
        mem.working_on("parser", "Claude Code", stale.isoformat())
        mem.working_on("deploy window", "Cursor", _now())
        live = mem.claims()

    assert [c["topic"] for c in live] == ["deploy window"]
    assert _worked(repo, "parsing") == ""
    assert _worked(repo, "deploy") != ""


def test_a_third_agent_asking_about_both_is_told_about_both(knos_home, repo):
    knos_paths.remember_pointed(repo)
    with Memory(repo) as mem:
        mem.working_on("parser", "Claude Code", _now())
        mem.working_on("deploys", "Cursor", _now())

    said = _worked(repo, "the parser and the deploys", asker="Windsurf")
    assert "Claude Code started working on parser" in said
    assert "Cursor started working on deploys" in said

    with Memory(repo) as mem:
        assert {y["claimed_by"] for y in mem.stand_downs()} == {"Claude Code", "Cursor"}


@pytest.mark.critical
def test_the_server_tells_agents_what_to_do_about_a_claim(knos_home, repo):
    """An agent has to be told the rule before it is held to it, so the
    instructions and the tool descriptions carry it."""
    said = mcp.server.instructions or ""
    assert "withheld from you" in said
    assert "override" in said
    assert "under your name" in said
    assert "is withheld" in (mcp.search.__doc__ or "")
    assert "about to start work" in (mcp.remember.__doc__ or "")


def test_the_server_names_its_own_version(knos_home, repo):
    """A client is told the version in the handshake, and directories score
    on it. An empty string is what you get by not passing one at all."""
    import re

    said = knos.version()
    assert said, "the server would introduce itself with no version"
    assert re.fullmatch(r"\d+\.\d+\.\d+.*|0\+unknown", said), said
    assert mcp.server.version == said


# ---- enforcement: knos withholds what it knows -------------------------


@pytest.mark.critical
def test_a_claim_withholds_the_answer_not_just_a_warning(knos_home, repo):
    """The signal is not advice. knos declines to be the source.

    It cannot stop an agent editing a file — it has no authority over an
    editor. It does own what it knows, and on claimed work it refuses to
    hand it over.
    """
    from knos.memory import Fact

    knos_paths.remember_pointed(repo)
    with Memory(repo) as mem:
        mem.record(
            Fact(
                text="the risk guard refuses unknown assets on liquidity",
                source="session",
                where="Claude Code session aaaa1111 2026-08-20",
                when="2026-08-20",
            )
        )
        mem.working_on("risk guard", "Claude Code", _now())

    held = mcp.search("risk guard")
    assert held.startswith("Withheld.")
    assert "held by Claude Code" in held
    # the thing it knows is not in the reply at all
    assert "refuses unknown assets" not in held
    assert "liquidity" not in held


def test_the_agent_holding_the_claim_is_never_blocked(knos_home, repo):
    from knos.memory import Fact

    knos_paths.remember_pointed(repo)
    with Memory(repo) as mem:
        mem.record(
            Fact("the risk guard refuses unknown assets", "session", "s 2026-08-20", "2026-08-20")
        )
        mem.working_on("risk guard", "Claude Code", _now())

    import knos.mcp as m

    original = m._who
    try:
        m._who = lambda ctx: "Claude Code"
        said = m.search("risk guard")
    finally:
        m._who = original
    assert not said.startswith("Withheld.")
    assert "refuses unknown assets" in said


def test_an_override_unlocks_it_and_is_written_down(knos_home, repo):
    from knos.memory import Fact

    knos_paths.remember_pointed(repo)
    with Memory(repo) as mem:
        mem.record(
            Fact("the risk guard refuses unknown assets", "session", "s 2026-08-20", "2026-08-20")
        )
        mem.working_on("risk guard", "Claude Code", _now())

    said = mcp.search("risk guard", override="the build is broken and I need it now")
    assert not said.startswith("Withheld.")
    assert "refuses unknown assets" in said

    with Memory(repo) as mem:
        taken = mem.overrides()
        assert len(taken) == 1
        assert taken[0]["topic"] == "risk guard"
        assert "build is broken" in taken[0]["why"]
        # and it is in the journal, permanently, with a reason
        assert any(
            "took risk guard anyway" in str(e.get("evaluated", ""))
            for e in mem.journal(limit=1000)
        )


def test_an_override_holds_for_that_agent_and_that_claim_only(knos_home, repo):
    knos_paths.remember_pointed(repo)
    with Memory(repo) as mem:
        mem.working_on("risk guard", "Claude Code", _now())
        mem.working_on("parser", "Cursor", _now())
        mem.overrode("risk guard", "an agent", "Claude Code", "needed it", _now())

        assert mem.overridden("risk guard", "an agent")
        assert not mem.overridden("parser", "an agent")
        assert not mem.overridden("risk guard", "Windsurf")

    # the one it overrode is open; the other is still shut
    assert not mcp.search("risk guard").startswith("Withheld.")
    assert mcp.search("the parser").startswith("Withheld.")


def test_releasing_the_work_clears_the_overrides_too(knos_home, repo):
    knos_paths.remember_pointed(repo)
    with Memory(repo) as mem:
        mem.working_on("risk guard", "Claude Code", _now())
        mem.overrode("risk guard", "Cursor", "Claude Code", "needed it", _now())
        assert mem.overrides()
        mem.done_working()
        assert mem.overrides() == []
        # the journal still says it happened
        assert any(
            "took risk guard anyway" in str(e.get("evaluated", ""))
            for e in mem.journal(limit=1000)
        )


def test_withholding_dies_with_the_store(knos_home, repo):
    """Enforcement is Sibyl. Delete it and nothing is held back."""
    knos_paths.remember_pointed(repo)
    with Memory(repo) as mem:
        mem.working_on("risk guard", "Claude Code", _now())
        db = mem.db_path
    assert mcp.search("risk guard").startswith("Withheld.")

    db.unlink()

    assert not mcp.search("risk guard").startswith("Withheld.")


def test_naming_yourself_the_holder_does_not_get_you_past_the_block(knos_home, repo):
    """A client tells knos its own name and can tell it anything.

    If the name alone decided who holds a claim, an agent that called
    itself "Claude Code" would walk straight past enforcement in one line.
    The claim is bound to the connection it was made on as well.
    """
    knos_paths.remember_pointed(repo)
    with Memory(repo) as mem:
        # claimed on some other connection, not this one
        mem.working_on("risk guard", "Claude Code", _now(), session="99999")

    # An impostor using the holder's exact name is still not the holder.
    assert mcp.search("risk guard").startswith("Withheld.")
    assert not mcp._is_holder(
        {"who": "Claude Code", "session": "99999"}, "Claude Code"
    )


def test_the_real_holder_on_its_own_connection_is_let_through(knos_home, repo):
    knos_paths.remember_pointed(repo)
    with Memory(repo) as mem:
        mem.working_on("risk guard", "Claude Code", _now(), session=mcp._session())

    assert mcp._is_holder(
        {"who": "Claude Code", "session": mcp._session()}, "Claude Code"
    )


def test_a_claim_with_no_session_falls_back_to_the_name(knos_home, repo):
    """Older claims are no weaker than they were, and no stronger."""
    assert mcp._is_holder({"who": "Claude Code"}, "Claude Code")
    assert not mcp._is_holder({"who": "Claude Code"}, "Cursor")


def test_a_person_can_claim_work_without_going_through_an_agent(
    knos_home, repo, monkeypatch
):
    """The person is the one who can resolve a collision.

    Claiming used to be an agent-only move, which left the human with no way
    to fence off work before starting it.
    """
    from typer.testing import CliRunner

    from knos.cli import app
    from knos.memory import Memory

    knos_paths.remember_pointed(repo)
    runner = CliRunner()

    assert runner.invoke(app, ["claim", "the risk guard"]).exit_code == 0
    with Memory(repo) as mem:
        assert [w["topic"] for w in mem.claims()] == ["the risk guard"]

    # And asking about it says so, in front of the person, not afterwards in
    # a status screen they never opened.
    said = runner.invoke(app, ["ask", "how does the risk guard work"]).output
    assert "working on the risk guard right now" in said

    assert runner.invoke(app, ["done"]).exit_code == 0
    with Memory(repo) as mem:
        assert mem.claims() == []


def test_one_agent_is_enough_to_feel_the_withhold(knos_home, repo):
    """A person claims work at the terminal; their only agent is refused.

    Needing two agents open to see the one thing knos does that a worktree
    cannot is a setup cost most people will not pay before deciding.
    """
    from datetime import datetime, timezone

    from knos import mcp

    knos_paths.remember_pointed(repo)
    with Memory(repo) as mem:
        mem.working_on("the parser", "you", datetime.now(timezone.utc).isoformat())
        said = mcp._held(mem, "how does parsing work", "Claude Code", "")

    assert said.startswith("Withheld.")
    # Talking to the person who holds it, so not "go and ask them".
    assert "The person you are working with" in said
    assert "the parser" in said

    with Memory(repo) as mem:
        mem.done_working()
        assert mcp._held(mem, "how does parsing work", "Claude Code", "") == ""


# ---- concurrency: two processes, one topic -----------------------------


@pytest.mark.critical
def test_two_processes_claiming_the_same_topic_only_one_wins(knos_home, repo, tmp_path):
    """The claim is a compare-and-swap, not a blind write.

    Two agents reaching for the same work in the same second is the case
    the whole product exists for. A last-writer-wins store would tell both
    of them they had it, and the second would quietly own work the first
    was already changing. Real processes, not threads, because the lock
    that has to hold is SQLite's, across process boundaries.
    """
    import json
    import subprocess
    import sys
    from concurrent.futures import ThreadPoolExecutor

    script = tmp_path / "grab.py"
    script.write_text(
        "import json, sys\n"
        "from datetime import datetime, timezone\n"
        "from knos.memory import Memory\n"
        "repo, who = sys.argv[1], sys.argv[2]\n"
        "with Memory(repo) as mem:\n"
        "    took, holder = mem.claim_if_free(\n"
        "        'the parser', who, datetime.now(timezone.utc).isoformat()\n"
        "    )\n"
        "print(json.dumps({'who': who, 'took': took,\n"
        "                  'holder': (holder or {}).get('who')}))\n",
        encoding="utf-8",
    )

    def grab(who: str) -> dict:
        done = subprocess.run(
            [sys.executable, str(script), str(repo), who],
            capture_output=True,
            text=True,
        )
        assert done.returncode == 0, done.stderr
        return json.loads(done.stdout.strip().splitlines()[-1])

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = (f.result() for f in [
            pool.submit(grab, "Claude Code"),
            pool.submit(grab, "Cursor"),
        ])

    winners = [r for r in (first, second) if r["took"]]
    losers = [r for r in (first, second) if not r["took"]]
    assert len(winners) == 1, (first, second)
    assert len(losers) == 1, (first, second)
    # The loser is told who actually has it, not a bare refusal.
    assert losers[0]["holder"] == winners[0]["who"], (first, second)

    # And the store agrees with whoever won.
    with Memory(repo) as mem:
        held = [c for c in mem.claims() if c["topic"] == "the parser"]
    assert len(held) == 1, held
    assert held[0]["who"] == winners[0]["who"]


@pytest.mark.critical
def test_a_claim_lapses_so_a_crashed_agent_cannot_hold_work_forever(knos_home, repo):
    """An agent that dies mid-change never calls `knos done`. If the claim
    outlived the process, that work would be unaskable until a person
    noticed. It expires on its own instead."""
    dead = datetime.now(timezone.utc) - timedelta(minutes=INTENT_HOLDS + 1)
    with Memory(repo) as mem:
        mem.working_on("the parser", "a crashed agent", dead.isoformat())
        assert mem.claims() == []
        took, holder = mem.claim_if_free("the parser", "Cursor", _now())
    assert took is True and holder is None
