"""L46: no single run spends more than its model budget (near_ai.RUN_CAP_USD, about $30): with stubbed token counts, a
run whose running cost would pass the cap stops before the next call and says so in plain words."""
import io
import json

from knos_wanted import near_ai, near_attest


class Answer(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_a_run_stops_before_the_call_that_would_pass_its_cap(monkeypatch):
    monkeypatch.setenv("NEAR_AI_API_KEY", "test-not-a-key")
    monkeypatch.delenv("KNOS_NEAR_AI_OFF", raising=False)
    monkeypatch.setattr(near_ai, "_seed", lambda: None)
    monkeypatch.setattr(near_ai, "_save", lambda: None)
    monkeypatch.setitem(near_ai._state, "spent_usd", 0.0)
    monkeypatch.setitem(near_ai._state, "other_usd", 0.0)
    monkeypatch.setitem(near_ai._state, "cache", {})
    monkeypatch.setitem(near_ai._state, "today", 0)
    monkeypatch.setattr(near_ai, "_visits", {})
    monkeypatch.setattr(near_attest, "verify_model", lambda m: {"ok": False, "why": "stub"})
    sent = []
    # each answer reports 1,000,000 output tokens: $1.20 at the first model's price
    monkeypatch.setattr(near_ai.urllib.request, "urlopen", lambda req, timeout=0: (sent.append(1), Answer(json.dumps(
        {"id": f"c{len(sent)}", "usage": {"prompt_tokens": 0, "completion_tokens": 1_000_000},
         "choices": [{"message": {"content": "{\"approve\": true, \"reason\": \"ok\"}"}, "finish_reason": "stop"}]}).encode()))[1])
    with near_ai.run_budget(cap=2.0) as b:
        a = near_ai.review("c", "q", "test one", "code one", "v")
        c = near_ai.review("c", "q", "test two", "code two", "v")
        d = near_ai.review("c", "q", "test three", "code three", "v")
    assert len(sent) == 2 and a["approve"] is True and c["approve"] is True
    assert b["spent"] == 2.4 and d.get("run_capped") is True and d["approve"] is None
    assert "spend limit of $2.00" in d["note"] and "stopped before the next call" in d["note"]


def test_the_cap_is_about_30_dollars_and_one_run_keeps_one_budget():
    assert near_ai.RUN_CAP_USD == 30.0
    with near_ai.run_budget() as outer:
        with near_ai.run_budget(cap=1.0) as inner:
            assert inner is outer and inner["cap"] == 30.0
    assert near_ai.worst_cost("s" * 200, "u" * 200, 800) > 0
