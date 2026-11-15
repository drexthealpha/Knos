"""knos.recall: no-LLM conversational recall over Sibyl (the 0.3.1 LongMemEval strategy), on a tiny history."""

from __future__ import annotations

import pytest

from knos import recall


@pytest.fixture
def client(tmp_path):
    from sibyl_memory_client import MemoryClient
    return MemoryClient.local(str(tmp_path / "m.db"), tenant_id="t")


def test_the_right_past_session_comes_back(client):
    noise = [{"id": f"n{i}", "date": "2026/01/01", "turns": [
        {"role": "user", "content": f"How do I {t}?"}, {"role": "assistant", "content": "Here is how."}]}
        for i, t in enumerate(["reset my router", "boil an egg", "learn guitar", "fix a bike chain"])]
    pref = {"id": "p", "date": "2026/02/01", "turns": [
        {"role": "user", "content": "I love hiking in the Lake District, and I prefer quiet trails."},
        {"role": "assistant", "content": "Noted."}]}
    said = {"id": "a", "date": "2026/03/01", "turns": [
        {"role": "user", "content": "Suggest a name for my bakery."},
        {"role": "assistant", "content": "How about Crumb and Kettle for the bakery?"}]}
    recall.index(client, noise + [pref, said])
    got = [r["session"] for r in recall.retrieve(client, "Can you recommend some hiking trails for this weekend?", k=3)]
    assert "p" in got
    got = [r["session"] for r in recall.retrieve(client, "What bakery name did you suggest to me?", k=3)]
    assert got[0] == "a"
