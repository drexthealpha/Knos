"""The agent call has its own live proofs a day: page proofs never use them up, and once they are used the call
answers with the last verified proof, marked reused, with no money moved."""
import time

from knos_wanted import near_live


def _today(monkeypatch, n, a):
    monkeypatch.setenv("KNOS_NEAR_LIVE", "on")
    monkeypatch.setenv("KNOS_NEAR_KEYS_FILE", "unused")
    monkeypatch.setattr(near_live, "prepare", lambda: None)
    monkeypatch.setitem(near_live._day, "day", time.strftime("%Y-%m-%d", time.gmtime()))
    monkeypatch.setitem(near_live._day, "n", n)
    monkeypatch.setitem(near_live._day, "a", a)


def test_page_cap_does_not_block_the_agent_call(monkeypatch):
    _today(monkeypatch, near_live.daily_cap(), 0)
    assert "live runs are used" in near_live.claim_prove()["why"]
    taken = []
    monkeypatch.setattr(near_live, "_take_ready", lambda: taken.append(1) or None)
    monkeypatch.setattr(near_live.time, "sleep", lambda s: None)
    monkeypatch.setattr(near_live.threading, "Thread", lambda **k: type("T", (), {"start": lambda self: None})())
    clock = iter(range(0, 10_000, 50))
    monkeypatch.setattr(near_live.time, "time", lambda: next(clock))
    out = near_live.claim_prove(agent=True)
    assert taken, "the agent call went past the page's cap to take a readied job"
    assert "live runs" not in out["why"]


def test_agent_cap_reuses_the_last_proof(monkeypatch):
    _today(monkeypatch, 0, near_live.agent_cap())
    out = near_live.claim_prove(agent=True)
    assert out["ok"] is False and "for the agent call are used" in out["why"]
    monkeypatch.setitem(near_live._proofs, "last", {"job": "job-1", "verdict": "Yes", "release_url": "x"})
    monkeypatch.setattr(near_live, "claim_look", lambda url: {"known": True, "quote": "q"})
    flow = near_live.claim_flow("https://doi.org/10.46298/dmtcs.3545")
    assert flow["reused"] is True and flow["paid"] is False and flow["job"] == "job-1"
