"""A Qloo call is live only when this request got HTTP 200 from Qloo: every other answered call is recorded, with its day."""
from knos_wanted import recorded


def _rep(**kw):
    calls = [{"n": 1, "call": "GET /search", "cached": False, "at": "2026-10-29T10:00:00Z"},
             {"n": 2, "call": "GET /v2/insights", "cached": True, "at": "2026-10-21T22:27:05Z"},
             {"n": 3, "call": "GET /v2/audiences", "cached": False, "error": "HTTP 429"}]
    return {"label": "LIVE Qloo data (Qloo REST API, read for this report, cached privately on the server)", "made": "2026-10-29T10:00:01Z",
            "calls": calls, **kw}


def test_a_fresh_answer_is_live_a_cached_one_recorded_and_a_refused_one_neither():
    out = recorded.live_or_recorded(_rep())
    assert [c["live"] for c in out["calls"]] == [True, False, False]
    assert [c["recorded"] for c in out["calls"]] == [None, "2026-10-21", None]
    assert out["qloo_calls"] == {"total": 3, "live": 1, "recorded": 1, "failed": 1, "ms": 0, "days": ["2026-10-21"]}
    assert out["label"].startswith("LIVE")


def test_a_card_served_from_a_recording_has_no_live_call_and_never_says_live():
    out = recorded.live_or_recorded(_rep(stale={"code": 429, "from": "2026-10-22T13:26:44Z"}))
    assert out["qloo_calls"]["live"] == 0 and out["qloo_calls"]["recorded"] == 2
    assert not out["label"].startswith("LIVE") and "LIVE" not in out["label"] and "2026-10-29" in out["label"]
    assert all(not c["live"] for c in out["calls"])
