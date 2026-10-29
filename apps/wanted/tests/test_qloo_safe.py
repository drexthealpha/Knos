"""Qloo's quota and terms on the hosted app: no Qloo tool on the public MCP without an agent key, nothing sent to Qloo
while a 429's Retry-After runs, nothing asked of Qloo at boot, and the audience filter Qloo's docs list today.
Network is replaced by counting stubs answering SYNTHETIC bodies (not Qloo data)."""
import io
import json
import threading
import time
import urllib.error

import pytest

from knos_wanted import agent, check, qloo_rest
from knos_wanted.qloo_mcp import WORKFLOWS, InProcess, Qloo
from knos_wanted.qloo_rest import Client, QlooError

KEY = "test-key-not-real-0123456789"


class State:
    q = Qloo(InProcess(), mode="mock")


def _names(got):
    return [t["name"] for t in got["result"]["tools"]]


def test_the_public_mcp_lists_and_answers_no_qloo_tool_without_an_agent_key():
    listed = _names(agent.mcp(State(), {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}))
    assert [n for n in listed if n.startswith("qloo_")] == []
    store = _names(agent.mcp(State(), {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, profile="store"))
    assert [n for n in store if n.startswith("qloo_")] == []
    got = agent.mcp(State(), {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "qloo_find_tags", "arguments": {"query": "tea"}}})
    assert got["result"]["isError"] and "agent key only" in got["result"]["content"][0]["text"]


def test_an_agent_key_sees_the_qloo_tools_and_each_call_counts_on_its_own_budget(monkeypatch):
    from knos_wanted import agentkeys
    taken = []
    monkeypatch.setattr(agent, "_agent", lambda: {"kind": "agent", "agent_key": "k1"})
    monkeypatch.setattr(agentkeys, "take_qloo", lambda kid: taken.append(kid))
    listed = _names(agent.mcp(State(), {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}))
    assert sorted(n for n in listed if n.startswith("qloo_")) == sorted(("qloo_capabilities",) + WORKFLOWS)
    agent.mcp(State(), {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "qloo_capabilities", "arguments": {}}})
    assert taken == ["k1"]


class Opener:
    def __init__(self, code=None, retry_after=None):
        self.n, self.code, self.retry_after = 0, code, retry_after

    def __call__(self, req, timeout=None):
        self.n += 1
        if self.code:
            hdrs = {"Retry-After": self.retry_after} if self.retry_after is not None else {}
            raise urllib.error.HTTPError(req.full_url, self.code, "err", hdrs, io.BytesIO(b"{}"))
        return io.BytesIO(json.dumps({"results": [{"name": "X (synthetic)"}]}).encode())


@pytest.fixture(autouse=True)
def no_hold():
    qloo_rest._hold["until"] = 0.0
    yield
    qloo_rest._hold["until"] = 0.0


def _client(tmp_path, opener):
    return Client(key=KEY, base="https://example.test", folder=tmp_path, budget=100, opener=opener, bucket=qloo_rest._Bucket(1000.0))


def test_no_qloo_request_is_sent_while_a_429s_retry_after_runs(tmp_path, monkeypatch):
    now = [1_790_000_000.0]
    monkeypatch.setattr(qloo_rest.time, "time", lambda: now[0])
    first = Opener(429, "120")
    with pytest.raises(QlooError, match="HTTP 429"):
        _client(tmp_path, first).get("/search", {"query": "tea"})
    assert first.n == 1                                   # not asked again at once
    later = Opener()
    for q in ("coffee", "kombucha", "swimwear"):          # 119 s later, other questions: none is sent
        now[0] += 39
        with pytest.raises(QlooError, match="HTTP 429"):
            _client(tmp_path, later).get("/search", {"query": q})
    assert later.n == 0
    now[0] += 5                                            # the window has passed: the next question goes
    assert _client(tmp_path, later).get("/search", {"query": "tea"})["body"]["results"]
    assert later.n == 1


def test_retry_after_reads_seconds_or_an_http_date_and_defaults_to_300():
    assert qloo_rest.retry_after("120", now=0) == 120
    assert qloo_rest.retry_after("Wed, 21 Oct 2015 07:28:00 GMT", now=1445412420.0) == 60
    assert qloo_rest.retry_after(None) == 300 and qloo_rest.retry_after("soon") == 300


def test_a_429_without_retry_after_holds_for_300_seconds(tmp_path, monkeypatch):
    monkeypatch.setattr(qloo_rest.time, "time", lambda: 1_790_000_000.0)
    with pytest.raises(QlooError):
        _client(tmp_path, Opener(429)).get("/search", {"query": "tea"})
    assert qloo_rest.held() == 300


def test_boot_sends_no_qloo_request(monkeypatch):
    from knos_wanted import front, preorder, qloo_harness, server, tasks, valley
    sent = []
    real = qloo_rest.Client._get
    monkeypatch.setattr(qloo_rest.Client, "_get", lambda self, path, params=None: sent.append(path) or real(self, path, params))
    monkeypatch.setattr(qloo_harness.Harness, "call", lambda self, tool, args: sent.append(tool))
    # what boot does that is not about Qloo (devnet, GitHub, a sweep) is left out of this count
    monkeypatch.setattr(server, "_restore_projects", lambda: None)
    monkeypatch.setattr(preorder, "preflight_status", lambda force=False: None)
    monkeypatch.setattr(tasks, "available", lambda: None)
    monkeypatch.setattr(valley, "start_sweeper", lambda: None)
    monkeypatch.setattr(qloo_harness.Harness, "warm", lambda self: None)
    monkeypatch.setattr(front, "_started", False)

    class Httpd:
        def __init__(self, *a, **k):
            pass

        def serve_forever(self):
            time.sleep(2.0)                                # threads started at boot get their chance to ask

    monkeypatch.setattr(server, "ThreadingHTTPServer", Httpd)
    before = set(threading.enumerate())
    server.serve("127.0.0.1", 0)
    started = [t.name for t in set(threading.enumerate()) - before]
    assert sent == [] and not front._started and not {"knos-recorded", "knos-front-seeds"} & set(started), started


def test_the_deprecated_audience_filter_is_never_sent():
    import inspect

    from knos_wanted import qloo_guard
    src = inspect.getsource(check)
    assert '"filter.type": "urn:entity:audience"' not in src and '"filter.type": "urn:audience"' not in src
    for t in ("urn:entity:audience", "urn:audience"):
        assert qloo_guard.problems("/v2/insights", {"filter.type": t, "take": 6}), t
    # the documented route: segments from /v2/audiences (1 to 50 a page), scored with signal.demographics.audiences
    assert '"take": AUDIENCE_TAKE' in src and check.AUDIENCE_TAKE <= 50
    assert not qloo_guard.problems("/v2/insights", {"filter.type": "urn:entity:brand", "signal.interests.entities": "x",
                                                     "filter.results.entities": "y", "signal.demographics.audiences": "z",
                                                     "signal.demographics.audiences.weight": "high", "take": 10})
