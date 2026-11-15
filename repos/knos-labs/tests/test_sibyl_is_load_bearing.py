"""Take Sibyl away and knos stops being knos.

There is no second store, no cache, no fallback file. Everything a person or
an agent asks for is answered out of Sibyl, so these tests break the store on
purpose and show the product failing rather than degrading quietly.

Read this file first if you want to know whether the memory is real.

Rewritten for 0.2.0, where claims moved out of the Sibyl store into claims.db and are annotated, never withheld.
Dropped (behaviour removed):
  - the mcp search "Withheld." reply and `mcp._held` (answers are never withheld now; see
    test_search_tells_an_agent_someone_else_holds_the_file for what replaced it)
  - `Memory.working_on` / `current_work` / `stood_down` / `claim_if_free` / `claims` (the hot claim tier)
  - status patching `cli._store_mb`, which never existed (replaced by a test that makes Sibyl's own size
    measurement report 4.2 MB)
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

import pytest
from sibyl_memory_client import FREE_TIER_CAP_BYTES

from knos import answer, paths, private, refresh
from knos.claims import Claims
from knos.cli import main
from knos.identity import Agent
from knos.memory import TOPIC, Fact, Memory, StoreGone

CLAUDE = Agent(host="claude", session="aaaa1111bbbb")
CURSOR = Agent(host="cursor", session="cccc2222dddd")


def _now() -> str:
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


def _sibyl_measures(monkeypatch, size: int) -> None:
    """Make Sibyl's own footprint measurement (what its cap gate and `Memory.footprint` read) report `size`."""
    import sibyl_memory_client._capcheck as capcheck

    monkeypatch.setattr(capcheck, "aggregate_db_size", lambda *_a, **_k: size)


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
    """No cache, no shadow copy, no markdown file quietly holding it.

    Deleting the store is refused in words; starting over on purpose finds nothing, because there was nothing else."""
    mem = _fill(repo)
    db = mem.db_path
    assert answer.ask(repo, mem, "why did we drop redis")
    mem.storage.close()

    db.unlink()

    with pytest.raises(StoreGone):
        Memory(repo)

    refresh.reset(repo)
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

    with Claims(repo) as c:
        took, _, _ = c.take(CLAUDE, "the login", ["src/auth.py"])  # claims
        assert took
    with Memory(repo) as mem:
        answer.point(repo, mem, index_code=False)  # journal + warm + reference
        mem.note_thing(TOPIC, "redis", {"note": "dropped", "when": "2026-08-30"})
        mem.supersede(TOPIC, "redis", "dropped it")  # archive

        named = {name: what for name, what, _ in mem.tiers()}

        assert [name for name, _, _ in mem.tiers()] == ["journal", "warm", "claims", "reference", "archive"]
        assert mem.journal(), "journal empty"
        assert mem.things(), "warm empty"
        assert mem.reference("knos:repo") is not None, "reference empty"
        assert mem.forgotten_count() >= 1, "archive empty"
        assert "0 things learned" not in named["journal"]
        assert "0 things named" not in named["warm"]
        assert named["claims"] == "1 claimed", named
        assert named["reference"] == repo.name
        assert named["archive"] == "1 forgotten", named


def test_the_claims_tier_says_nothing_is_claimed_when_nothing_is(knos_home, repo):
    with Memory(repo) as mem:
        named = {name: what for name, what, _ in mem.tiers()}
    assert named["claims"] == "nothing claimed"


def test_one_agent_claiming_changes_what_another_agent_is_told(knos_home, repo):
    """Coordination, not just storage: the second agent is told because of what the first one did, without either of
    them meeting."""
    from knos import mcp

    before = mcp._claim_notes(repo, "what does src/auth.py do", CURSOR)
    with Claims(repo) as c:
        c.take(CLAUDE, "the login", ["src/auth.py"])
    after = mcp._claim_notes(repo, "what does src/auth.py do", CURSOR)
    own = mcp._claim_notes(repo, "what does src/auth.py do", CLAUDE)

    assert before == ""
    assert "[claimed] src/auth.py is claimed by claude/aaaa1111" in after, after
    assert own == "", "an agent is not warned about its own claim"


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


def test_search_tells_an_agent_someone_else_holds_the_file(knos_home, repo):
    """The same query, answered with who holds the file, because another agent claimed it.

    search is the tool an agent reaches for constantly, so this is where knowing somebody is mid-change actually
    changes what it does. It is told, and it still gets the answer: nothing is withheld.
    """
    from knos import mcp

    with Memory(repo) as mem:
        mem.record(
            Fact(
                text="the login in src/auth.py refuses unknown assets",
                source="session",
                where="Claude Code session aaaa1111 2026-08-20",
                when="2026-08-20",
            )
        )

    before = mcp.search("refuses unknown assets")
    assert "[claimed]" not in before
    assert "refuses unknown assets" in before

    with Claims(repo) as c:
        c.take(CLAUDE, "the login", ["src/auth.py"])

    after = mcp.search("refuses unknown assets")
    assert after.startswith("[claimed] src/auth.py is claimed by claude/aaaa1111"), after
    assert "refuses unknown assets" in after, "the answer was withheld"


def test_deleting_the_store_ends_what_knos_was_told(knos_home, repo):
    """The claim anyone checking this will actually test.

    What knos was *told* has no second copy. Deleting the store is refused rather than answered from nothing, and
    starting over on purpose leaves it gone (except in the backup `knos reset` keeps). Claims are not in the store:
    they live in claims.db beside it, and lapse on their own.
    """
    now = _now()
    with Memory(repo) as mem:
        answer.point(repo, mem, index_code=False)
        mem.record(
            Fact(text="we chose sqlite over redis", source="note",
                 where="you said so, 2026-09-01", when=now, about="storage")
        )
        mem.note_thing(TOPIC, "storage", {"note": "we chose sqlite over redis", "when": now[:10]})
    with Claims(repo) as c:
        c.take(CLAUDE, "the parser", ["src/auth.py"])

    with Memory(repo) as mem:
        assert any("sqlite over redis" in p.text for p in answer.ask(repo, mem, "storage sqlite"))

    paths.store_for(repo).unlink()
    with pytest.raises(StoreGone):
        Memory(repo)

    refresh.reset(repo)
    with Memory(repo) as mem:
        answer.point(repo, mem, index_code=False)
        assert not any(
            "sqlite over redis" in p.text for p in answer.ask(repo, mem, "storage sqlite")
        )
    with Claims(repo) as c:
        assert [x.description for x in c.live()] == ["the parser"]


def test_the_number_status_prints_actually_counts_the_things_that_die(knos_home, repo):
    """The README points at this number as the thing not to take on trust.

    It read a key that does not exist on a journal row, so it was zero on
    every store no matter what was in it. It counts notes: what somebody told knos.
    """
    now = _now()
    with Memory(repo) as mem:
        answer.point(repo, mem, index_code=False)
        # Commits and rules, none of which are knos's to keep.
        assert mem.only_here() == 0

        mem.record(Fact(text="we chose sqlite", source="note",
                        where="you said so", when=now, about="storage"))
        assert mem.only_here() == 1

        mem.record(Fact(text="the parser is being rewritten", source="note",
                        where="you said so", when=now, about="parser"))
        assert mem.only_here() == 2

    # A claim is not a note and does not live in this store.
    with Claims(repo) as c:
        c.take(CLAUDE, "the parser", ["src/auth.py"])
    with Memory(repo) as mem:
        assert mem.only_here() == 2


def test_status_reports_the_cap_and_warns_before_it_is_reached(knos_home, repo, monkeypatch, capsys):
    """`knos status` prints the size against the 5 MB free tier and says `nearly full` from 80%.
    A cap you only learn about by hitting it is a trap."""
    _fill(repo).close()

    _sibyl_measures(monkeypatch, int(4.2 * 1024 * 1024))
    capsys.readouterr()
    assert main(["status"]) == 0
    said = capsys.readouterr().out
    assert "4.2 MB of Sibyl's 5 MB free tier" in said, said
    assert "nearly full: knos compact, or knos pro buy (Sibyl Pro, uncapped, is included)" in said, said


def test_status_does_not_cry_wolf_below_eighty_percent(knos_home, repo, monkeypatch, capsys):
    _fill(repo).close()

    _sibyl_measures(monkeypatch, int(3.9 * 1024 * 1024))
    capsys.readouterr()
    assert main(["status"]) == 0
    said = capsys.readouterr().out
    assert "3.9 MB of Sibyl's 5 MB free tier" in said, said
    assert "nearly full" not in said, said


def test_a_sibyl_account_is_not_capped(knos_home, repo, monkeypatch, capsys, tmp_path):
    """Paying Sibyl users are not told about a cap that does not apply to them."""
    creds = tmp_path / "credentials.json"
    creds.write_text(json.dumps({"account_id": "acct_test", "session_token": "tok_test"}), encoding="utf-8")
    monkeypatch.setenv("SIBYL_CREDENTIALS", str(creds))
    _fill(repo).close()

    _sibyl_measures(monkeypatch, int(4.9 * 1024 * 1024))
    with Memory(repo) as mem:
        assert not mem.capped
        assert not mem.near_full() and not mem.full()
    capsys.readouterr()
    assert main(["status"]) == 0
    said = capsys.readouterr().out
    assert "no cap" in said and "nearly full" not in said, said


def test_remember_warns_at_eighty_percent(knos_home, repo, monkeypatch, capsys):
    """The warning comes with the write that crossed the line, not only when someone thinks to run status."""
    _sibyl_measures(monkeypatch, int(4.5 * 1024 * 1024))
    capsys.readouterr()
    assert main(["remember", "we chose sqlite over redis", "--about", "storage"]) == 0
    said = capsys.readouterr().out
    assert "Noted, under storage" in said
    assert "over 80% of its 5 MB free tier" in said, said


def test_a_full_store_refuses_a_note_loudly(knos_home, repo, monkeypatch, capsys):
    """The one failure a write must never have.

    A note that silently did not land is worse than no note: the person believes it is remembered and every agent is
    told nothing. When Sibyl's own cap gate refuses the write, knos says so in words, with the two ways on.
    """
    with Memory(repo):
        pass
    # Its own MonkeyPatch, so undoing it cannot undo the test's isolated HOME (which would point Sibyl's store at
    # the real ~/.sibyl-memory).
    with pytest.MonkeyPatch.context() as full:
        _sibyl_measures(full, FREE_TIER_CAP_BYTES + 1)

        with Memory(repo) as mem:
            assert mem.full()
            assert mem.record(Fact("x", "note", "you", _now(), about="x")) is None,                 "Sibyl accepted a write past the cap"

        capsys.readouterr()
        assert main(["remember", "we chose sqlite over redis", "--about", "storage"]) == 1
        said = capsys.readouterr().out
        assert "Not remembered" in said and "nothing was written" in said, said
        assert "knos compact" in said and "knos pro buy" in said and "Sibyl Pro" in said, said

    with Memory(repo) as mem:
        assert not mem.remembered("storage"), "a refused note was written anyway"
        assert all("sqlite over redis" not in str(e.get("evaluated")) for e in mem.journal())


def test_a_full_store_refuses_an_agents_note_loudly(knos_home, repo, monkeypatch):
    """The same refusal through the MCP tool an agent actually calls."""
    from knos import mcp

    with Memory(repo):
        pass
    _sibyl_measures(monkeypatch, FREE_TIER_CAP_BYTES + 1)

    said = mcp.remember("we chose sqlite over redis", "storage")
    assert said == mcp.FULL


def test_compact_makes_room_without_touching_the_journal(knos_home, repo):
    """`knos compact` drops long-forgotten notes and vacuums. The journal is append-only and stays."""
    with Memory(repo) as mem:
        mem.record(Fact("we chose sqlite", "note", "you", _now(), about="storage"))
        mem.note_thing(TOPIC, "storage", {"note": "we chose sqlite", "when": _now()[:10]})
        mem.supersede(TOPIC, "storage", "dropped")
        journal = len(mem.journal())
        assert mem.forgotten_count() == 1

        kept = mem.compact(older_than_days=30)
        assert kept["dropped"] == 0, "a note forgotten today is not long-forgotten"
        assert mem.forgotten_count() == 1

        # Forgotten long ago: backdate the archive row rather than wait a month.
        with mem.storage.transaction() as conn:
            conn.execute("UPDATE archived_entities SET archived_at = '2000-01-01T00:00:00'")
        got = mem.compact(older_than_days=30)
        assert got["dropped"] == 1
        assert mem.forgotten_count() == 0
        assert len(mem.journal()) == journal


def test_status_shows_the_claims_being_held(knos_home, repo, capsys):
    """`knos status` answers "why is my agent being refused?" with who holds what."""
    with Claims(repo) as c:
        c.take(CLAUDE, "the parser", ["src/auth.py"])

    capsys.readouterr()
    assert main(["status"]) == 0
    said = capsys.readouterr().out
    assert "1 claimed" in said, said
    assert "claude/aaaa1111: src/auth.py (the parser," in said, said
