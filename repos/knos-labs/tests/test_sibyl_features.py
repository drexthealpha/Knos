"""Sibyl is load-bearing, and Knos never routes around its gate or cap: Sibyl Pro comes with Knos Pro (one payment;
see test_sibyl_pro.py). Tiers are mocked here, and only here (never in src/)."""

from __future__ import annotations

import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from knos import sibyl
from knos.cli import main
from knos.memory import Fact, Memory

SRC = Path(__file__).parent.parent / "src"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@pytest.fixture()
def paid(monkeypatch):
    """A Sibyl Pro account, as Sibyl's own gate would see it after a server-verified check (tests only)."""
    from sibyl_memory_client import MemoryClient
    monkeypatch.setattr(MemoryClient, "_effective_tier", lambda self: "pro")


# ---- never around the gate or the cap -------------------------------------------------------------------------------

def test_src_never_bypasses_the_gate():
    bad = re.compile(r"""tier\s*=\s*["'](pro|lifetime|team|stake|sync|enterprise)["']|\bLearner\(|\bLinter\(|"""
                     r"""tier_cache\.json|MemoryClient\([^)]*\btier\s*=""")
    hits = []
    for f in SRC.rglob("*.py"):
        for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if bad.search(line):
                hits.append(f"{f.relative_to(SRC)}:{n}: {line.strip()}")
    assert not hits, hits


def test_every_repo_lives_where_sibyls_cap_counts_it(knos_home, repo, tmp_path):
    from sibyl_memory_client._capcheck import aggregate_db_size
    with Memory(repo) as mem:
        mem.record(Fact(text="one", source="note", where="you", when=_now()))
        assert mem.db_path == Path.home() / ".sibyl-memory" / "memory.db"
        counted = aggregate_db_size(tmp_path / "some-other-store.db")  # whatever store Sibyl is writing to
    assert counted >= mem.db_path.stat().st_size > 0
    other = tmp_path / "second"
    (other / ".git").mkdir(parents=True)
    with Memory(other) as mem2:
        assert mem2.db_path == mem.db_path and mem2.tenant != mem.tenant  # one store, a tenant per repo


def test_a_020_store_is_migrated_into_the_counted_store_once(knos_home, repo):
    from sibyl_memory_client import MemoryClient, Storage

    from knos import paths
    legacy = paths.legacy_store_for(repo)
    st = Storage(str(legacy))
    MemoryClient(st).write_event(evaluated="we chose sqlite in 0.2", acted="note", extra={"text": "we chose sqlite"})
    st.close()
    with Memory(repo) as mem:
        assert any("sqlite in 0.2" in str(e.get("evaluated")) for e in mem.journal())
    assert not legacy.exists() and Path(str(legacy) + ".migrated").exists()  # kept, never deleted
    with Memory(repo) as mem:  # opening again migrates nothing twice
        assert sum("sqlite in 0.2" in str(e.get("evaluated")) for e in mem.journal()) == 1


# ---- learn and lint: Sibyl Pro through MemoryClient only ------------------------------------------------------------

def test_learn_and_lint_on_the_free_tier_say_how_to_get_pro(knos_home, repo, capsys):
    with Memory(repo) as mem:
        mem.record(Fact(text="x", source="note", where="you", when=_now()))
    assert main(["learn"]) == 1
    assert "needs Sibyl Pro, which Knos Pro includes: knos pro buy" in capsys.readouterr().out
    assert main(["lint"]) == 1
    assert "needs Sibyl Pro" in capsys.readouterr().out


def test_accepted_playbooks_are_exported_and_imported_on_every_machine(knos_home, repo, paid):
    with Memory(repo) as mem:
        with mem.storage.transaction() as conn:  # a proposal as Sibyl's learner would leave it
            conn.execute("INSERT INTO skill_proposals (id, tenant_id, pattern_kind, proposed_slug, proposed_title, "
                         "proposed_body, evidence, confidence, summarizer) VALUES (?,?,?,?,?,?,?,?,?)",
                         ("p1", mem.tenant, "repeated_action", "run-migrations-first", "Run migrations first",
                          "Before editing models, run the migrations.", "[]", 0.9, "local-deterministic"))
        got = sibyl.learn(mem, run=False)
        assert [p["id"] for p in got["pending"]] == ["p1"]
        path = sibyl.accept(mem, repo, "p1")
    assert path == repo / ".knos" / "playbooks" / "run-migrations-first.md"
    assert "run the migrations" in path.read_text(encoding="utf-8")
    other = repo.parent / "clone"
    (other / ".git").mkdir(parents=True)
    (other / ".knos" / "playbooks").mkdir(parents=True)
    (other / ".knos" / "playbooks" / path.name).write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    with Memory(other) as mem2:
        assert sibyl.import_playbooks(mem2, other) == 1
        assert "run the migrations" in mem2.reference("playbook/run-migrations-first")["body"]
        assert sibyl.import_playbooks(mem2, other) == 0


def test_lint_finds_agents_that_recorded_opposite_things(knos_home, repo, paid):
    with Memory(repo) as mem:
        mem.record(Fact(text="we use redis for the session cache", source="note",
                        where="claude/aaaa said so, 2026-09-30", when=_now(), about="cache"))
        mem.record(Fact(text="we do not use redis for the session cache", source="note",
                        where="codex/bbbb said so, 2026-09-30", when=_now(), about="cache"))
        got = sibyl.lint(mem)
    assert got["contradictions"], got
    c = got["contradictions"][0]
    assert {c["a_by"], c["b_by"]} == {"claude/aaaa", "codex/bbbb"}
    assert not got["ok"]


def test_contradiction_rule():
    assert sibyl.contradicts("we use redis for sessions", "we don't use redis for sessions")
    assert not sibyl.contradicts("we use redis for sessions", "we use redis for sessions")
    assert not sibyl.contradicts("we use redis", "we never deploy on fridays")


# ---- remove Sibyl and each of the five breaks -----------------------------------------------------------------------

def test_without_sibyl_there_is_no_memory(monkeypatch, knos_home, repo):
    monkeypatch.setitem(sys.modules, "sibyl_memory_client", None)
    with pytest.raises(ImportError):
        Memory(repo)


def test_without_sibyls_learner_there_are_no_playbooks(knos_home, repo, paid, monkeypatch):
    from sibyl_memory_client import MemoryClient
    monkeypatch.delattr(MemoryClient, "learn")
    with Memory(repo) as mem, pytest.raises(AttributeError):
        sibyl.learn(mem)


def test_without_sibyls_linter_and_search_there_is_no_lint(knos_home, repo, paid, monkeypatch):
    from sibyl_memory_client import MemoryClient
    monkeypatch.delattr(MemoryClient, "lint")
    with Memory(repo) as mem, pytest.raises(AttributeError):
        sibyl.lint(mem)
    monkeypatch.setitem(sys.modules, "sibyl_memory_client.multi_record", None)
    with Memory(repo) as mem, pytest.raises((ImportError, AttributeError)):
        sibyl.lint(mem)


def test_without_sibyls_langgraph_store_the_framework_example_has_no_memory(monkeypatch):
    monkeypatch.setitem(sys.modules, "sibyl_memory_langgraph", None)
    sys.path.insert(0, str(SRC.parent / "examples"))
    try:
        sys.modules.pop("langgraph_team", None)
        with pytest.raises(ImportError):
            import langgraph_team  # noqa: F401
    finally:
        sys.path.remove(str(SRC.parent / "examples"))
        sys.modules.pop("langgraph_team", None)


def test_records_anchor_sibyl_journal_entries(knos_home, repo):
    from knos.team import records
    with Memory(repo) as mem:
        mem.record(Fact(text="decided to shard by tenant", source="note", where="codex said so", when=_now()))
        with_journal = records.build(b"s" * 32, b"h" * 32, records.period_start(), [], mem.journal())
    without = records.build(b"s" * 32, b"h" * 32, records.period_start(), [], [])
    assert with_journal.data().merkle_root != without.data().merkle_root
