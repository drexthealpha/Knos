"""The five tiers, and the constraint that makes WARM canonical."""

from __future__ import annotations

import multiprocessing
import sqlite3
import uuid

import pytest

from knos.memory import FILE, TOPIC, Fact, Memory


def test_tiers_round_trip(knos_home, repo):
    with Memory(repo) as m:
        m.record(Fact("we dropped redis", "session", "s1 2026-08-20", "2026-08-20", about="redis"))
        m.note_thing(TOPIC, "redis", {"decision": "dropped"})
        m.set_focus({"working_on": "auth"})
        m.set_reference("license", "MIT")

        assert m.journal()[0]["evaluated"] == "we dropped redis"
        assert m.thing(TOPIC, "redis")["body"] == {"decision": "dropped"}
        assert m.focus()["body"] == {"working_on": "auth"}
        assert m.reference("license")["body"] == "MIT"


def test_warm_is_canonical_one_record_per_thing(knos_home, repo):
    """A second write updates the record; it does not make a second one."""
    with Memory(repo) as m:
        m.note_thing(FILE, "src/auth.py", {"owner": "tess"})
        m.note_thing(FILE, "src/auth.py", {"owner": "sam"})
        rows = [t for t in m.things(FILE) if t["name"] == "src/auth.py"]
        assert len(rows) == 1
        assert rows[0]["body"] == {"owner": "sam"}


def test_archive_supersedes(knos_home, repo):
    with Memory(repo) as m:
        m.note_thing(TOPIC, "redis", {"decision": "keep"})
        m.supersede(TOPIC, "redis", "we dropped it")
        assert m.thing(TOPIC, "redis") is None


def test_search_finds_a_recorded_fact(knos_home, repo):
    with Memory(repo) as m:
        m.record(
            Fact("quokka is the parser codename", "session", "s2 2026-08-21", "2026-08-21")
        )
        texts = [h["text"] for h in m.search("quokka")]
        assert any("quokka" in t for t in texts)


# ---- the counter-test -------------------------------------------------
#
# This one bypasses the wrapper entirely and writes with raw SQL, from a
# second process. If uniqueness lived in Memory rather than in the schema,
# this would succeed and the guarantee would be worthless.


def _raw_insert(db_path: str, queue) -> None:
    conn = sqlite3.connect(db_path, timeout=20)
    try:
        conn.execute(
            "INSERT INTO entities (id, tenant_id, category, name, body, status)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (
                str(uuid.uuid4()),
                "00000000-0000-0000-0000-000000000001",
                TOPIC,
                "redis",
                '{"decision": "smuggled in"}',
                "active",
            ),
        )
        conn.commit()
        queue.put("accepted")
    except sqlite3.IntegrityError as exc:
        queue.put(f"rejected: {exc}")
    except sqlite3.Error as exc:  # pragma: no cover - a different failure
        queue.put(f"error: {exc}")
    finally:
        conn.close()


def test_schema_rejects_a_conflicting_write_from_another_process(knos_home, repo):
    with Memory(repo) as m:
        m.note_thing(TOPIC, "redis", {"decision": "dropped"})
        db = str(m.db_path)

    queue = multiprocessing.Queue()
    proc = multiprocessing.Process(target=_raw_insert, args=(db, queue))
    proc.start()
    proc.join(60)
    outcome = queue.get(timeout=10)

    assert outcome.startswith("rejected"), outcome
    assert "UNIQUE" in outcome.upper()

    with Memory(repo) as m:
        assert m.thing(TOPIC, "redis")["body"] == {"decision": "dropped"}


def test_the_counter_test_can_fail(knos_home, repo):
    """A different name is accepted, so the test above is testing something."""
    with Memory(repo) as m:
        m.note_thing(TOPIC, "redis", {"decision": "dropped"})
        db = str(m.db_path)
        conn = sqlite3.connect(db, timeout=20)
        conn.execute(
            "INSERT INTO entities (id, tenant_id, category, name, body, status)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (
                str(uuid.uuid4()),
                "00000000-0000-0000-0000-000000000001",
                TOPIC,
                "memcached",
                "{}",
                "active",
            ),
        )
        conn.commit()
        conn.close()
        assert m.thing(TOPIC, "memcached") is not None


def test_a_full_store_is_reported_not_raised(knos_home, repo, monkeypatch):
    """The free store holds 5 MB. Filling it is normal, not a crash."""
    from sibyl_memory_client import FREE_TIER_CAP_BYTES, CapExceededError

    with Memory(repo) as m:
        assert m.record(Fact("fits", "session", "s1", "2026-08-20")) is not None

        def refuse(**kwargs):
            raise CapExceededError(
                "at the cap", current_size=FREE_TIER_CAP_BYTES, cap=FREE_TIER_CAP_BYTES
            )

        monkeypatch.setattr(m.client, "write_event", refuse)
        assert m.record(Fact("does not fit", "session", "s2", "2026-08-20")) is None


def test_point_stops_cleanly_when_the_store_fills(knos_home, repo, monkeypatch):
    from knos import answer

    with Memory(repo) as m:
        monkeypatch.setattr(m, "record", lambda fact: None)
        counts = answer.point(repo, m, index_code=False)
    assert counts["full"] == 1
    assert counts["commits"] == 0


def test_reading_a_repo_twice_does_not_double_what_it_knows(knos_home, repo, monkeypatch, tmp_path):
    """`knos point` re-reads; it does not append. Appending fills the store."""
    from typer.testing import CliRunner

    from knos.cli import app

    monkeypatch.setenv("KNOS_CLAUDE_HOME", str(tmp_path / "absent"))
    monkeypatch.setenv("KNOS_CURSOR_DB", str(tmp_path / "absent.vscdb"))
    runner = CliRunner()

    runner.invoke(app, ["point", str(repo)])
    with Memory(repo) as m:
        once = m.counts()
    runner.invoke(app, ["point", str(repo)])
    with Memory(repo) as m:
        twice = m.counts()

    assert twice == once


def test_a_full_store_never_raises_from_any_kind_of_write(knos_home, repo, monkeypatch):
    """Journal, entity, state and reference writes all hit the same cap."""
    from sibyl_memory_client import FREE_TIER_CAP_BYTES, CapExceededError

    def refuse(*args, **kwargs):
        raise CapExceededError(
            "at the cap", current_size=FREE_TIER_CAP_BYTES, cap=FREE_TIER_CAP_BYTES
        )

    with Memory(repo) as m:
        for name in ("write_event", "set_entity", "set_state", "set_reference"):
            monkeypatch.setattr(m.client, name, refuse)
        # None of these may raise, because a full store is normal.
        assert m.record(Fact("x", "session", "s", "2026-08-20")) is None
        assert m.note_thing(TOPIC, "x", {}) is None
        m.set_focus({"a": 1})
        m.set_reference("k", "v")


def test_notes_are_what_was_written_down_not_what_was_read(knos_home, repo, tmp_path, monkeypatch):
    """Sessions and commits are derived. Only deliberate notes are curatable."""
    from knos import answer

    monkeypatch.setenv("KNOS_CLAUDE_HOME", str(tmp_path / "absent"))
    monkeypatch.setenv("KNOS_CURSOR_DB", str(tmp_path / "absent.vscdb"))
    with Memory(repo) as m:
        answer.point(repo, m, index_code=False)  # writes commits, not notes
        assert m.notes() == []
        m.note_thing(TOPIC, "deploy window", {"note": "Thursdays", "when": "2026-08-30"})
        assert [n["about"] for n in m.notes()] == ["deploy window"]


def test_forgetting_a_note_stops_it_being_an_answer(knos_home, repo):
    from knos import answer

    with Memory(repo) as m:
        m.record(
            Fact(
                text="The deploy window is Thursdays only.",
                source="note",
                where="Claude Code said so, 2026-08-30",
                when="2026-08-30",
                about="deploy window",
            )
        )
        m.note_thing(TOPIC, "deploy window", {"note": "Thursdays", "when": "2026-08-30"})

        before = answer.ask(repo, m, "when is the deploy window")
        assert any("Thursdays only" in p.text for p in before)

        m.supersede(TOPIC, "deploy window", "the person dropped it")

        after = answer.ask(repo, m, "when is the deploy window")
        assert not any("Thursdays only" in p.text for p in after)
        assert m.notes() == []


def test_forgetting_a_note_does_not_touch_the_commits(knos_home, repo, tmp_path, monkeypatch):
    """Derived history is not curatable, and must survive curating a note."""
    from knos import answer

    monkeypatch.setenv("KNOS_CLAUDE_HOME", str(tmp_path / "absent"))
    monkeypatch.setenv("KNOS_CURSOR_DB", str(tmp_path / "absent.vscdb"))
    with Memory(repo) as m:
        answer.point(repo, m, index_code=False)
        m.note_thing(TOPIC, "login", {"note": "x", "when": "2026-08-30"})
        m.supersede(TOPIC, "login", "dropped")
        assert answer.ask(repo, m, "who touched login last and why")


def test_a_person_can_write_a_standing_rule_and_agents_see_it(
    knos_home, repo, monkeypatch
):
    """The authoring path: no agent involved, no markdown file."""
    from typer.testing import CliRunner

    from knos import answer, private
    from knos.cli import app

    CliRunner().invoke(app, ["point", str(repo)])
    result = CliRunner().invoke(app, ["remember", "always use pnpm, never npm"])
    assert result.exit_code == 0
    assert "Noted, under pnpm npm" in result.stdout

    with Memory(repo) as m:
        found = answer.ask(repo, m, "pnpm or npm", identity=private.AGENT)
    assert found
    assert "always use pnpm" in found[0].text
    assert found[0].where.startswith("you said so, ")


def test_a_written_rule_outranks_chatter_that_merely_mentions_it(knos_home, repo):
    from knos import answer

    with Memory(repo) as m:
        for i in range(6):
            m.record(
                Fact(
                    text=f"long argument {i} about pnpm and npm and pnpm again",
                    source="session",
                    where=f"Claude Code session aaaa111{i} 2026-08-20",
                    when="2026-08-20",
                )
            )
        m.record(
            Fact(
                text="always use pnpm, never npm",
                source="note",
                where="you said so, 2026-08-30",
                when="2026-08-30",
                about="pnpm npm",
            )
        )
        m.note_thing(TOPIC, "pnpm npm", {"note": "always use pnpm", "when": "2026-08-30"})
        found = answer.ask(repo, m, "pnpm or npm")

    assert found[0].source == "note", [p.source for p in found[:3]]


def test_the_filing_name_is_the_subject_not_the_telling_off():
    from knos.answer import topic_of

    assert topic_of("always use pnpm, never npm") == "pnpm npm"
    assert topic_of("never touch the vendor directory") == "touch vendor directory"
