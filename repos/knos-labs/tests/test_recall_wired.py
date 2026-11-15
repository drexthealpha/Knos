"""knos.recall (the 96.8% no-LLM recall) is what the product uses, not a side module: session ingest indexes every turn
for it, and MCP search, the SDK's recall and the reference worker all retrieve through it."""

from __future__ import annotations

import pytest

from knos import answer, recall
from knos.memory import Memory

from test_sessions import ONLY_IN_A_SESSION, _claude_log


@pytest.fixture
def read_repo(knos_home, tmp_path, repo, monkeypatch):
    root = tmp_path / "claude"
    _claude_log(root, repo, ONLY_IN_A_SESSION)
    monkeypatch.setenv("KNOS_CLAUDE_HOME", str(root / "projects"))
    monkeypatch.setenv("KNOS_CURSOR_DB", str(tmp_path / "absent.vscdb"))
    with Memory(repo) as mem:
        answer.point(repo, mem, index_code=False)
    return repo


def test_session_ingest_indexes_turns_for_recall(read_repo):
    with Memory(read_repo) as mem:
        got = recall.retrieve(mem.client, "why did we drop redis", k=5)
    assert any("one dependency for one counter" in r["text"] for r in got)
    assert any("Claude Code session" in r["where"] for r in got)


def test_mcp_search_returns_what_recall_finds(read_repo, monkeypatch):
    from knos import mcp
    monkeypatch.chdir(read_repo)
    monkeypatch.setattr(mcp.answer, "ask", lambda *a, **k: [])       # only recall can answer now
    said = mcp.search("why did we drop redis")
    assert "one dependency for one counter" in said and "source: Claude Code session" in said


def test_sdk_recall_returns_what_recall_finds(read_repo, monkeypatch):
    from knos import sdk
    monkeypatch.setattr(Memory, "search", lambda self, q, limit=40: [])   # only recall can answer now
    hits = sdk.Knos("a", read_repo).recall("why did we drop redis")
    assert any("one dependency for one counter" in h["text"] for h in hits), hits


def test_the_worker_recalls_its_own_similar_past_jobs(tmp_path):
    pytest.importorskip("solders.litesvm")
    from sibyl_memory_client import MemoryClient
    from knos.jobs import market
    from _jobharness import LocalLedger
    from _jobharness import Escrow
    from knos.jobs.relay import DirRelay
    from knos.jobs.worker import Worker
    env = Escrow()
    ledger, relay = LocalLedger(env), DirRelay(tmp_path / "relay")
    buyer, _ = env.party(5 * 1_000_000)
    wkey, _ = env.party()
    prompts = []

    def model(prompt: str) -> str:
        prompts.append(prompt)
        return "Mama Put Bakery: the warmest bread in Lagos." if len(prompts) == 1 else "Fresh loaves for Lagos."

    w = Worker(ledger, relay, wkey, model, memory=MemoryClient.local(str(tmp_path / "w.db"), tenant_id="w"))
    market.post(ledger, relay, buyer, market.Brief("Bakery tagline", "Write a tagline for a Lagos bakery.",
                                                   kind="copy", checks={"must_include": ["Lagos"]}), 1_000_000)
    assert [o.delivered for o in w.once()] == [True]
    market.post(ledger, relay, buyer, market.Brief("Another bakery tagline", "A new tagline for our Lagos bakery.",
                                                   kind="copy", checks={"must_include": ["Lagos"]}), 1_000_000)
    assert [o.delivered for o in w.once()] == [True]
    assert "Similar jobs you delivered before" in prompts[1] and "warmest bread in Lagos" in prompts[1]
