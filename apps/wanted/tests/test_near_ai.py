"""The model steps' rules, with NEAR AI Cloud faked: no model is called here, no attestation is fetched, no real key."""
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
    from knos_wanted import near_ai, near_attest
    m = importlib.reload(near_ai)
    m._state["seeded"] = True   # no saved ledger read
    monkeypatch.setattr(near_attest, "verify_model", lambda model: {"ok": model.startswith("deepseek"), "signers": ["0xabc"], "url": "u", "sha256": "s"})
    monkeypatch.setattr(near_attest, "check_signature", lambda *a, **k: {"ok": True, "signer": "0xabc"})
    calls = []

    def answer(content='{"approve": true, "reason": "uses the claimed method"}', model_fail=None):
        def urlopen(req, timeout=0):
            body = json.loads(req.data) if req.data else {}
            calls.append(body.get("model"))
            assert req.headers.get("Authorization") == "Bearer " + FAKE and body.get("max_tokens") == 800
            if model_fail and body.get("model") == model_fail:
                raise urllib.error.HTTPError(req.full_url, 503, "busy", {}, None)
            return _Resp(json.dumps({"id": "chatcmpl-1", "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
                                     "usage": {"prompt_tokens": 3000, "completion_tokens": 40}}).encode())
        monkeypatch.setattr(m.urllib.request, "urlopen", urlopen)
    return m, answer, calls


def test_one_call_then_the_cache_and_the_answer_is_private(ai):
    m, answer, calls = ai
    answer()
    a = m.review("jump-hash", "q", "test text", "code text", "v1")
    b = m.review("jump-hash", "q", "test text", "code text", "v2")
    assert a["approve"] is True and not a["cached"] and b["cached"] and calls == ["deepseek-ai/DeepSeek-V4.1-Flash-1017"]
    assert a["cost_usd"] == pytest.approx(3000 * 0.30e-6 + 40 * 1.20e-6) and a["id"] == "chatcmpl-1" and a["private"]
    assert m.status()["spent_usd"] == pytest.approx(a["cost_usd"])
    assert FAKE not in json.dumps([a, b, m.status(), m.ledger()])


def test_the_fallback_model_answers_and_says_it_is_not_verified_private(ai):
    m, answer, calls = ai
    answer(model_fail="deepseek-ai/DeepSeek-V4.1-Flash-1017")
    a = m.review("x", "q", "t", "c", "v")
    assert a["model"] == "moonshotai/kimi-k2.6" and not a["private"] and calls == ["deepseek-ai/DeepSeek-V4.1-Flash-1017", "moonshotai/kimi-k2.6"]


def test_agent_a_writes_its_code_with_one_call(ai):
    m, answer, calls = ai
    answer("```python\nclass Counter:\n    pass\n```")
    w = m.write_code("hyperloglog", "q", "import solution\n", "v")
    assert w["code"] == "class Counter:\n    pass\n" and len(calls) == 1 and w["kind"] == "write"


def test_at_8_dollars_the_fixed_rule_decides_and_says_so(ai):
    m, answer, calls = ai
    answer()
    m._state["spent_usd"] = 8.0
    a = m.review("x", "q", "t", "c", "v")
    assert a["approve"] is None and "locked test alone" in a["note"] and calls == []
    assert m.write_code("x", "q", "t", "v")["code"] is None and calls == []


def test_ten_an_hour_per_visitor_and_200_a_day(ai):
    m, answer, calls = ai
    answer()
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
    assert m.review("x", "q", "t", "c")["approve"] is None and m.write_code("x", "q", "t")["code"] is None


def test_the_reviewer_can_only_make_it_stricter():
    from knos_wanted.near_live import final_verdict
    assert final_verdict(True, True) and not final_verdict(True, False)
    assert not final_verdict(False, True) and final_verdict(True, None)


def test_an_answer_cut_short_is_still_read(ai):
    m, answer, calls = ai
    answer('{"approve": false, "reason": "reads the test file')
    a = m.review("x", "q", "t", "c", "v")
    assert a["approve"] is False and a["reason"] == "reads the test file"


def test_the_attestation_checks_follow_near_ai_docs():
    import hashlib
    import struct

    from knos_wanted import near_attest
    ev = [{"imr": 3, "event_type": 1, "event": "app-id", "event_payload": "ab"}, {"imr": 0, "event_type": 2, "event": "x", "event_payload": ""}]
    d = hashlib.sha384(struct.pack("<I", 1) + b":app-id:" + bytes.fromhex("ab")).digest()
    assert near_attest.replay_rtmr3(json.dumps(ev)) == hashlib.sha384(bytes(48) + d).digest()
    with pytest.raises(ValueError):
        near_attest.replay_rtmr3([{**ev[0], "digest": "00" * 48}])
