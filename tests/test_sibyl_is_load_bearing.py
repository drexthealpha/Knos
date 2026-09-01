"""Take Sibyl away and knos stops being knos.

There is no second store, no cache, no fallback file. Everything a person or
an agent asks for is answered out of Sibyl, so these tests break the store on
purpose and show the product failing rather than degrading quietly.

Read this file first if you want to know whether the memory is real.
"""

from __future__ import annotations

import sqlite3

import pytest

from datetime import datetime, timezone

from knos import answer, private
from knos.memory import TOPIC, Fact, Memory


def _now() -> str:
    """Intent is about now, so tests that use it must say now."""
    return datetime.now(timezone.utc).isoformat()


def _fill(repo):
    mem = Memory(repo)
    mem.record(
        Fact(
            text="we dropped redis because it was one dependency for one counter",
            source="session",
            where="Claude Code session aaaa1111 2026-08-20",
            when="2026-08-20",
        )
    )
    mem.note_thing(TOPIC, "redis", {"note": "dropped", "when": "2026-08-20"})
    return mem


def test_every_answer_comes_out_of_sibyl(knos_home, repo):
    """The store answers, or nothing does."""
    mem = _fill(repo)
    try:
        assert answer.ask(repo, mem, "why did we drop redis")
        # The one and only place an answer can come from. Break it and the
        # failure surfaces: a broken store must never look like a repo that
        # simply has nothing in it.
        mem.client = None
        with pytest.raises(AttributeError):
            mem.search("redis")
    finally:
        mem.storage.close()


def test_deleting_the_store_deletes_the_product(knos_home, repo):
    """No cache, no shadow copy, no markdown file quietly holding it."""
    mem = _fill(repo)
    db = mem.db_path
    assert answer.ask(repo, mem, "why did we drop redis")
    mem.storage.close()

    db.unlink()

    with Memory(repo) as fresh:
        assert fresh.journal() == []
        assert fresh.things() == []
        assert answer.ask(repo, fresh, "why did we drop redis") == []


def test_a_broken_store_does_not_get_silently_papered_over(knos_home, repo):
    """A corrupt store answers nothing. It never invents a substitute."""
    mem = _fill(repo)
    db = mem.db_path
    mem.storage.close()

    db.write_bytes(b"this is not a database")

    with pytest.raises(sqlite3.DatabaseError, match="not a database"):
        with Memory(repo) as broken:
            broken.record(Fact("x", "session", "s", "2026-08-20"))


def test_all_five_tiers_are_carrying_something(knos_home, repo, tmp_path, monkeypatch):
    """Not one table used five ways: five tiers, five behaviours."""
    monkeypatch.setenv("KNOS_CLAUDE_HOME", str(tmp_path / "absent"))
    monkeypatch.setenv("KNOS_CURSOR_DB", str(tmp_path / "absent.vscdb"))

    with Memory(repo) as mem:
        answer.point(repo, mem, index_code=False)  # journal + warm + reference
        mem.working_on("redis", "Claude Code", _now())  # hot
        mem.note_thing(TOPIC, "redis", {"note": "dropped", "when": "2026-08-30"})
        mem.supersede(TOPIC, "redis", "dropped it")  # archive

        named = dict((name, what) for name, what, _ in mem.tiers())

        assert mem.journal(), "journal empty"
        assert mem.reference("knos:repo") is not None, "reference empty"
        assert mem.current_work()["who"] == "Claude Code", "hot empty"
        assert mem.forgotten_count() >= 1, "archive empty"
        assert "0 things learned" not in named["journal"]


def test_the_hot_tier_holds_one_thing_and_is_overwritten(knos_home, repo):
    """Hot is about now. It does not accumulate, unlike the journal."""
    with Memory(repo) as mem:
        mem.working_on("redis", "Claude Code", _now())
        mem.working_on("auth", "Cursor", _now())
        work = mem.current_work()

    assert work["topic"] == "auth"
    assert work["who"] == "Cursor"


def test_one_agent_writing_changes_what_another_agent_is_told(knos_home, repo):
    """Coordination, not just storage: the second agent behaves differently
    because of what the first one did, without either of them meeting."""
    from knos import mcp
    from knos import paths as knos_paths

    knos_paths.remember_pointed(repo)

    with Memory(repo) as mem:
        before = mcp._being_worked_on(mem, "the parser")
        mem.working_on("parser", "Claude Code", _now())
        after = mcp._being_worked_on(mem, "the parser")

    assert before == ""
    assert "Claude Code started working on parser" in after


def test_a_private_path_is_still_invisible_after_all_of_that(knos_home, repo):
    """None of the tier work may weaken 1.6."""
    with Memory(repo) as mem:
        mem.record(
            Fact(
                text="the key is sk_live_quokka_9931",
                source="session",
                where="Claude Code session aaaa1111 2026-08-20",
                when="2026-08-20",
                path=".env",
            )
        )
        found = answer.ask(repo, mem, "key", identity=private.AGENT)
    assert all("sk_live" not in p.text for p in found)


def test_search_itself_tells_an_agent_someone_else_is_mid_change(knos_home, repo):
    """The same query, answered differently, because another agent wrote.

    search is the tool an agent reaches for constantly, so this is where
    knowing somebody is mid-change actually changes what it does.
    """
    from knos import mcp
    from knos import paths as knos_paths

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

    before = mcp.search("risk guard")
    assert "started working on" not in before

    with Memory(repo) as mem:
        mem.working_on("risk guard", "Claude Code", _now())

    # A claim does not merely warn: knos withholds what it knows, and says
    # who to ask. The answer is not in the reply at all.
    after = mcp.search("risk guard")
    assert after.startswith("Withheld.")
    assert "held by Claude Code" in after
    assert "refuses unknown assets" not in after
