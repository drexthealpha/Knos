"""H6: the right idea is answered, offline: recorded fixtures and fakes only, 0 live Qloo calls (any request that would
leave this machine fails the test).
1. no request the demand check builds names filter.type urn:entity:audience, and the client refuses one before sending
2. "a vegan meal kit for students, like HelloFresh" is read as an idea, never sent to a paper search
3. a typed idea with no exact recording says "no recorded answer for this idea", never the nearest idea's verdict
4. Qloo's 429 with Retry-After holds every request for that long, and nothing is sent meanwhile
5. the month's call counter survives a restart (its file) and a redeploy (the recorded secret file carries it)
"""
import io
import json
import time
import urllib.error

import pytest
from test_check import FakeQloo

from knos_wanted import check, qloo_rest, recorded, which
from knos_wanted.qloo_rest import BudgetExceeded, Client, QlooError

HELLO = "a vegan meal kit for students, like HelloFresh"


def no_network(*a, **k):
    raise AssertionError("a request left this machine")


def test_1_no_request_names_urn_entity_audience(monkeypatch):
    fake = FakeQloo()
    rep = check.demand_check("a smart water bottle that glows to remind you to drink", "Lagos", client=fake)
    assert rep.get("decision") and fake.seen                                      # a whole check ran on the fake
    sent = [json.dumps(p) for _path, p in fake.seen]
    assert not any("urn:entity:audience" in s for s in sent), [s for s in sent if "audience" in s][:3]
    c = Client(key="k", base="https://qloo.example", opener=no_network)
    with pytest.raises(QlooError, match="deprecated|not documented|urn:entity:audience"):
        c.get("/v2/insights", {"filter.type": "urn:entity:audience"})


def test_2_a_meal_kit_like_hellofresh_is_an_idea_not_a_paper(monkeypatch):
    monkeypatch.setattr(recorded, "_last", {})
    monkeypatch.setattr(recorded, "_answered", {})
    asked = []
    got = which.step(HELLO, paper_of=lambda text: asked.append(text) or {"title": "Making a meal of it", "doi": "10.0/x"})
    assert asked == []                                                            # OpenAlex is never asked for a plain idea
    assert got is None or got.get("of") != "paper"
    from knos import readings
    assert not readings.is_paper(HELLO) and readings.is_paper("10.1038/nature12373")


def test_3_no_exact_recording_never_shows_the_nearest_idea_s_verdict(monkeypatch):
    near = {"idea": "a vegan meal kit for students", "made": "2026-10-22", "hash": "c" * 64,
            "decision": {"verdict": "OPEN", "reasons": ["recorded"]}, "calls": [{"n": 1, "call": "GET /search", "cached": False}]}
    monkeypatch.setattr(recorded, "_last", {})
    monkeypatch.setattr(recorded, "_answered", {recorded.key(near["idea"]): near})
    failed = {"idea": HELLO, "calls": [{"n": 1, "error": "HTTP 429: not sent: the month is used up"}], "decision": {"verdict": "CANNOT_DECIDE"}}
    out = recorded.honest(HELLO, failed)
    assert out["no_recording"] == "no recorded answer for this idea"
    assert out["idea"] == HELLO and out["decision"]["verdict"] == "CANNOT_DECIDE"   # its own (undecided) answer, not OPEN
    assert out.get("hash") != near["hash"] and "nearest" not in out and "stale" not in out
    assert near["idea"] in out.get("nearest_options", [])                         # offered by name, to pick


def test_4_retry_after_holds_every_request(monkeypatch, tmp_path):
    monkeypatch.setitem(qloo_rest._hold, "until", 0.0)
    calls = []

    def limited(req, timeout=None):
        calls.append(req.full_url)
        raise urllib.error.HTTPError(req.full_url, 429, "Too Many Requests", {"Retry-After": "120"}, io.BytesIO(b"{}"))
    c = Client(key="k", base="https://qloo.example", folder=tmp_path, opener=limited)
    monkeypatch.setattr(c, "harness", False)
    with pytest.raises(QlooError):
        c.get("/search", {"query": "kombucha"})
    assert len(calls) == 1 and 115 <= qloo_rest.held() <= 120
    with pytest.raises(QlooError, match="HTTP 429: Qloo asked for a pause; no request sent"):
        c.get("/search", {"query": "a different question"})
    assert len(calls) == 1                                                        # nothing sent while the pause holds
    assert qloo_rest.retry_after("Wed, 21 Oct 2026 07:28:00 GMT", now=time.mktime((2026, 10, 21, 7, 26, 0, 0, 0, 0)) - time.timezone) > 0
    monkeypatch.setitem(qloo_rest._hold, "until", 0.0)


def test_5_the_month_s_count_survives_a_restart_and_a_redeploy(monkeypatch, tmp_path):
    monkeypatch.delenv("KNOS_RECORDED_UPLOAD_KEY", raising=False)
    monkeypatch.setattr(qloo_rest, "refusal", lambda *a, **k: None)
    first = tmp_path / "first"
    a = Client(key="k", base="https://qloo.example", folder=first, budget=3, opener=no_network)
    a._count_one("check")
    a._count_one("check")
    # a restart: a new process, the same disk
    b = Client(key="k", base="https://qloo.example", folder=first, budget=3, opener=no_network)
    assert b.used() == 2
    b._count_one("check")
    with pytest.raises(BudgetExceeded):
        Client(key="k", base="https://qloo.example", folder=first, budget=3, opener=no_network)._count_one("check")
    # a redeploy: the disk starts empty; the secret file the last write-back left holds the count
    monkeypatch.setenv("KNOS_WANTED_CACHE", str(first.parent / "cache-of-the-old-deploy"))
    (first.parent / "cache-of-the-old-deploy" / "qloo-rest").mkdir(parents=True)
    (first.parent / "cache-of-the-old-deploy" / "qloo-rest" / "calls.txt").write_text((first / "calls.txt").read_text())
    secret = tmp_path / "knos-recorded.json"
    secret.write_text(json.dumps(recorded._doc()), encoding="utf-8")
    assert json.loads(secret.read_text())["budget"]["calls"] == 3
    monkeypatch.setenv("KNOS_WANTED_CACHE", str(tmp_path / "new-deploy-empty-disk"))
    assert Client(key="k", base="https://qloo.example", budget=3, opener=no_network).used() == 0     # before the boot reads it
    recorded.load(str(secret))
    c = Client(key="k", base="https://qloo.example", budget=3, opener=no_network)
    assert c.used() == 3
    with pytest.raises(BudgetExceeded):
        c._count_one("check")
