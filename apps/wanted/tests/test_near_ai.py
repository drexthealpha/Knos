"""The AI reviewer's rules, with NEAR AI Cloud faked: no model is called here and no real key is used."""
import importlib
import io
import json
import urllib.error

import pytest

FAKE = "fake-key-for-tests"


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture()
def ai(monkeypatch, tmp_path):
    monkeypatch.setenv("NEAR_AI_API_KEY", FAKE)
    monkeypatch.delenv("KNOS_NEAR_AI_OFF", raising=False)
    monkeypatch.setenv("KNOS_NEAR_AI_LEDGER", str(tmp_path / "ledger.json"))
    from knos_wanted import near_ai
    m = importlib.reload(near_ai)
    m._state["balance_at"] = 1e18   # no balance read
    calls = []

    def answer(approve=True, model_fail=None):
        def urlopen(req, timeout=0):
            body = json.loads(req.data) if req.data else {}
            calls.append(body.get("model"))
            assert req.headers.get("Authorization") == "Bearer " + FAKE
            if model_fail and body.get("model") == model_fail:
                raise urllib.error.HTTPError(req.full_url, 503, "busy", {}, None)
            content = json.dumps({"approve": approve, "reason": "uses the claimed method"})
            return _Resp(json.dumps({"id": "x", "choices": [{"message": {"content": content}}],
                                     "usage": {"prompt_tokens": 3000, "completion_tokens": 40}}).encode())
        monkeypatch.setattr(m.urllib.request, "urlopen", urlopen)
    return m, answer, calls


def test_one_call_then_the_cache(ai):
    m, answer, calls = ai
    answer(True)
    a = m.review("jump-hash", "q", "test text", "code text", "v1")
    b = m.review("jump-hash", "q", "test text", "code text", "v2")
    assert a["approve"] is True and not a["cached"] and b["cached"] and calls == ["anthropic/claude-haiku-5-5"]
    assert a["cost_usd"] == pytest.approx(3000 * 0.10e-6 + 40 * 0.50e-6)
    assert m.status()["spent_usd"] == pytest.approx(a["cost_usd"])
    assert FAKE not in json.dumps([a, b, m.status()])


def test_the_fallback_model_answers_when_the_first_does_not(ai):
    m, answer, calls = ai
    answer(True, model_fail="anthropic/claude-haiku-5-5")
    a = m.review("x", "q", "t", "c", "v")
    assert a["model"] == "google/gemini-2.5-flash-lite" and calls == ["anthropic/claude-haiku-5-5", "google/gemini-2.5-flash-lite"]


def test_at_8_dollars_the_fixed_rule_decides_and_says_so(ai):
    m, answer, calls = ai
    answer(True)
    m._state["spent_usd"] = 8.0
    a = m.review("x", "q", "t", "c", "v")
    assert a["approve"] is None and "fixed rule" in a["note"] and calls == []


def test_ten_an_hour_per_visitor_and_200_a_day(ai):
    m, answer, calls = ai
    answer(True)
    for i in range(10):
        assert m.review("x", "q", "t", f"code {i}", "same")["approve"] is True
    assert m.review("x", "q", "t", "code 10", "same")["approve"] is None
    assert m.review("x", "q", "t", "code 10", "other")["approve"] is True
    m._state["today"] = 200
    assert m.review("x", "q", "t", "code 11", "third")["approve"] is None
    assert len(calls) == 11


def test_no_key_no_call(monkeypatch, tmp_path):
    monkeypatch.delenv("NEAR_AI_API_KEY", raising=False)
    monkeypatch.setenv("KNOS_NEAR_AI_LEDGER", str(tmp_path / "l.json"))
    from knos_wanted import near_ai
    m = importlib.reload(near_ai)
    monkeypatch.setattr(m.urllib.request, "urlopen", lambda *a, **k: pytest.fail("no call without a key"))
    assert m.review("x", "q", "t", "c")["approve"] is None


def test_the_reviewer_can_only_make_it_stricter():
    from knos_wanted.near_live import final_verdict
    assert final_verdict(True, True) and not final_verdict(True, False)
    assert not final_verdict(False, True) and final_verdict(True, None)
