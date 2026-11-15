"""knos.nebius clients: the documented request and response shapes, live vs MOCK switching on the env var, labels, and
no key in any output."""
from __future__ import annotations

import json

import pytest

from knos.nebius import rerun, sources, tavily, tokenfactory
from knos.nebius.__main__ import main as cli


def _fake(reply: dict, seen: list):
    def transport(method, url, headers, body, timeout):
        seen.append({"method": method, "url": url, "headers": headers, "body": body})
        return reply
    return transport


LIVE_REPLY = {"id": "x", "object": "chat.completion", "model": sources.SUPER,
              "choices": [{"index": 0, "message": {"role": "assistant", "content": "hello"}, "finish_reason": "stop"}],
              "usage": {"prompt_tokens": 1000, "completion_tokens": 2000, "total_tokens": 3000}}


def test_the_ids_and_prices_are_the_catalogs_as_read():
    # prices as read from the Token Factory catalog on 14 Oct 2026 (src/knos/nebius/sources.py); held to the code, not re-read
    assert sources.BASE_URL == "https://api.tokenfactory.nebius.com/v1/"
    assert sources.SUPER == "nvidia/nemotron-3-super-120b-a12b" and sources.ULTRA == "nvidia/Nemotron-3-Ultra-550b-a55b"
    assert sources.PRICE_PER_M == {sources.SUPER: (0.30, 0.90), sources.ULTRA: (1.00, 3.00)}
    assert sources.token_cost(sources.SUPER, 1_000_000, 1_000_000) == pytest.approx(1.20)
    assert sources.token_cost("unknown/model", 10, 10) == 0.0


def test_live_mode_posts_the_documented_chat_completion(monkeypatch):
    monkeypatch.delenv(sources.KEY_ENV, raising=False)
    seen: list = []
    tf = tokenfactory.TokenFactory("test-key-not-real", transport=_fake(LIVE_REPLY, seen))
    assert tf.live and tf.mode == "live"
    r = tf.chat(sources.SUPER, [{"role": "user", "content": "hi"}], max_tokens=64, response_format={"type": "json_object"})
    call = seen[0]
    assert call["method"] == "POST" and call["url"] == "https://api.tokenfactory.nebius.com/v1/chat/completions"
    assert call["headers"]["Authorization"] == "Bearer test-key-not-real"
    assert call["body"] == {"model": sources.SUPER, "messages": [{"role": "user", "content": "hi"}], "max_tokens": 64,
                            "temperature": 0.2, "response_format": {"type": "json_object"}}
    assert (r.text, r.prompt_tokens, r.completion_tokens, r.mock) == ("hello", 1000, 2000, False)
    assert r.cost_usd == pytest.approx((1000 * 0.30 + 2000 * 0.90) / 1e6)
    assert "label" not in r.to_dict() and "test-key-not-real" not in json.dumps(r.to_dict())


def test_list_models_reads_data_ids_and_is_empty_in_mock(monkeypatch):
    monkeypatch.delenv(sources.KEY_ENV, raising=False)
    seen: list = []
    tf = tokenfactory.TokenFactory("k", transport=_fake({"object": "list", "data": [{"id": sources.SUPER}]}, seen))
    assert tf.models() == [sources.SUPER] and seen[0]["url"].endswith("/v1/models") and seen[0]["method"] == "GET"
    assert tokenfactory.TokenFactory(responder=lambda m, msgs: "x").models() == []


def test_mock_mode_without_the_key_is_labelled_and_shaped_like_the_api(monkeypatch):
    monkeypatch.delenv(sources.KEY_ENV, raising=False)
    tf = tokenfactory.TokenFactory(responder=lambda model, msgs: "proposal")
    assert not tf.live and tf.mode == "mock"
    r = tf.chat(sources.ULTRA, [{"role": "user", "content": "abcd" * 10}])
    assert r.mock and r.text == "proposal" and r.raw["knos_mock"] == sources.MOCK
    assert r.raw["object"] == "chat.completion" and r.raw["choices"][0]["finish_reason"] == "stop"
    assert r.prompt_tokens == 10 and r.to_dict()["label"] == sources.MOCK
    with pytest.raises(tokenfactory.TokenFactoryError):
        tokenfactory.TokenFactory().chat(sources.SUPER, [])


def test_the_env_var_switches_live_on(monkeypatch):
    monkeypatch.setenv(sources.KEY_ENV, "from-env")
    assert tokenfactory.TokenFactory().live
    monkeypatch.setenv(sources.TAVILY_KEY_ENV, "tvly-from-env")
    assert tavily.Tavily().live


def test_a_malformed_response_is_an_error_not_a_reply():
    tf = tokenfactory.TokenFactory("k", transport=_fake({"error": "nope"}, []))
    with pytest.raises(tokenfactory.TokenFactoryError):
        tf.chat(sources.SUPER, [{"role": "user", "content": "x"}])


def test_tavily_live_request_and_credit_cost(monkeypatch):
    seen: list = []
    raw = {"query": "q", "results": [{"title": "t", "url": "https://a.example", "content": "c", "score": 0.5}],
           "response_time": 1.2, "usage": {"credits": 2}}
    tv = tavily.Tavily("tvly-test", transport=_fake(raw, seen))
    s = tv.search("q", search_depth="advanced", include_domains=["github.com"])
    assert seen[0]["url"] == "https://api.tavily.com/search" and seen[0]["headers"]["Authorization"] == "Bearer tvly-test"
    assert seen[0]["body"] == {"query": "q", "search_depth": "advanced", "max_results": 5, "include_usage": True,
                               "include_domains": ["github.com"]}
    assert s.credits == 2 and s.cost_usd == pytest.approx(0.016) and not s.mock


def test_tavily_mock_and_provenance(monkeypatch):
    monkeypatch.delenv(sources.TAVILY_KEY_ENV, raising=False)
    line = "result = sum(weight * value for weight, value in zip(weights, values))"
    src = f"import json\n\n\ndef f(weights, values):\n    {line}\n    return result\n"
    hit = tavily.Tavily(responder=lambda body: [{"title": "copy", "url": "https://mock.invalid/x", "content": "..." + line, "score": 1}])
    got = tavily.provenance(hit, src)
    assert got["matches"] and got["advisory"] and got["mock"] and got["finding"].startswith("possible copy")
    assert hit.calls[0].raw["knos_mock"] == sources.MOCK and hit.calls[0].credits == 1
    miss = tavily.provenance(tavily.Tavily(responder=lambda body: []), src)
    assert miss["matches"] == [] and miss["finding"] == "no public copy found" and miss["checked_lines"] == 1
    assert tavily.distinctive_lines("import os\nreturn x\n") == []


def test_reruns_say_where_they_ran():
    assert rerun.backend({}, which=lambda n: None)["backend"] == "local-sandbox"
    assert rerun.backend({"KNOS_NEBIUS_JOBS": "1"}, which=lambda n: None)["backend"] == "local-sandbox"
    assert rerun.backend({"KNOS_NEBIUS_JOBS": "1"}, which=lambda n: "/usr/bin/nebius")["backend"] == "nebius-serverless-job"
    cmd = rerun.job_create("j", "python:3.12-slim", "bash", "-c true")
    assert cmd[:4] == ["nebius", "ai", "job", "create"] and cmd[cmd.index("--timeout") + 1] == "1h"


def test_run_job_drives_the_documented_cli_commands():
    calls = []

    class Done:
        def __init__(self, out):
            self.returncode, self.stdout, self.stderr = 0, out, ""

    states = iter(["RUNNING", "COMPLETED"])

    def runner(argv, **kw):
        calls.append(argv[3])
        if argv[3] == "get":
            return Done(next(states, "COMPLETED"))
        return Done({"create": "", "get-by-name": "job-1", "logs": "ok"}[argv[3]])

    got = rerun.run_job("j", "img", "bash", "-c true", runner=runner, sleep=lambda s: None)
    assert got == {"job_id": "job-1", "status": "COMPLETED", "logs": "ok"}
    assert calls == ["create", "get-by-name", "get", "get", "logs"]


def test_status_prints_modes_and_never_a_key(monkeypatch, capsys):
    monkeypatch.setenv(sources.KEY_ENV, "secret-value-123")
    monkeypatch.delenv(sources.TAVILY_KEY_ENV, raising=False)
    assert cli(["status"]) == 0
    out = capsys.readouterr().out
    assert "secret-value-123" not in out and '"token_factory": "live"' in out and "TAVILY_API_KEY not set" in out
