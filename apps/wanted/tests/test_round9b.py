"""Round 9B: the stack, load-bearing and labelled — receipts (finality + verifier + USDC wording), the x402 paid route,
the record anchor, Sibyl tiers (HOT plan, REFERENCE shelf, conflict refusal, FTS search), the harness proxy at /mcp,
and the hosted MCP registration. SYNTHETIC fixtures; no network, no chain."""
import base64
import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest
from test_check import IDEA, FakeQloo

from knos_wanted import agent, escrow, preorder, research, server, x402
from knos_wanted.qloo_mcp import MOCK_LABEL, InProcess, Qloo

ROOT = Path(server.__file__).resolve().parents[3]


def test_the_receipt_names_the_verifier_the_settlement_and_measured_finality(monkeypatch):
    rec = {"order": "R" * 43, "claim_id": "knos-idea:" + "0" * 32, "report": "b" * 64, "units": 5, "buyer": "demo buyer, test money",
           "maker_wallet": "4dFAUoXNDbmPCJ1CPCFyaJqLW5WWY3i2TE3VKEdSbC31", "status": "released", "deadline_days": 30,
           "signatures": {"lock": "S" * 64}, "doc": {"panel": {"keys": [], "label": "UNLISTED PANEL"}, "program": "F" * 43, "mint": "M" * 43}}
    from knos.platform import finality
    monkeypatch.setattr(finality, "timing_of", lambda sig: {"final_ms": 412, "commitment": "confirmed", "final": False, "alpenglow": False})
    got = preorder.public(rec)
    assert got["finality"]["lock"]["final_ms"] == 412
    assert "knos_pay" in got["verifier"] and "knos_oidc" in got["verifier"] and "not used for this panel stage" in got["verifier"]
    assert "USDC" in got["verifier"] and "devnet" in got["verifier"]


def test_x402_challenge_and_settlement(monkeypatch):
    from solders.keypair import Keypair
    from solders.pubkey import Pubkey
    monkeypatch.setattr(escrow, "ledger", lambda: type("L", (), {"url": "https://api.devnet.solana.com"})())
    monkeypatch.setattr(escrow, "mint", lambda led, create=True: Pubkey.from_string("So11111111111111111111111111111111111111112"))
    monkeypatch.setattr(escrow, "demo_key", lambda: Keypair())
    ch = x402.challenge("a" * 64, "https://knos.example")
    acc = ch["accepts"][0]
    assert ch["x402Version"] == 2 and acc["scheme"] == "exact" and acc["network"] == "solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1"
    assert acc["amount"] == str(x402.PRICE_UNITS * escrow.UNIT) and "test money" in ch["resource"]["description"]
    assert json.loads(base64.b64decode(x402.header(ch))) == ch                     # PAYMENT-REQUIRED carries the same object
    assert "USDC" in acc["extra"]["note"]
    with pytest.raises(ValueError, match="base64 JSON"):
        x402.settle("not-base64!!")
    with pytest.raises(ValueError, match="x402Version"):
        x402.settle(base64.b64encode(json.dumps({"x402Version": 1, "scheme": "exact", "network": "solana-devnet"}).encode()).decode())
    from knos import chain
    calls = []

    def fake(url, method, params, timeout=10):
        calls.append(method)
        return "5" * 64 if method == "sendTransaction" else {"value": [{"confirmationStatus": "confirmed"}]}
    monkeypatch.setattr(chain, "call", fake)
    hdr = x402.header({"x402Version": 2, "accepted": acc, "payload": {"transaction": "T" * 200}})
    out = x402.settle(hdr)
    assert out["success"] and out["transaction"] == "5" * 64 and calls[0] == "sendTransaction"


@pytest.fixture
def app():
    st = server.State(Qloo(InProcess(), mode="mock", sleep=lambda s: None), FakeQloo())
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.make_handler(st))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}", st
    httpd.shutdown()


def call(base, path, body=None, tok=None, headers=None):
    h = {"Content-Type": "application/json", **({"Authorization": "Bearer " + tok} if tok else {}), **(headers or {})}
    req = urllib.request.Request(base + path, None if body is None else json.dumps(body).encode(), h)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def test_the_paid_route_and_the_anchor_are_honest_without_the_escrow(app):
    base, _ = app
    assert call(base, "/api/x402/report?hash=" + "0" * 64)[0] == 404
    assert call(base, "/api/anchor", {})[0] == 401
    tok = call(base, "/api/auth/guest", {"label": "a"})[1]["token"]
    st, got = call(base, "/api/anchor", {}, tok)
    assert st == 200 and got["anchored"] is False and got["why"]
    st, s = call(base, "/api/status")
    assert s["x402"]["route"].startswith("/api/x402/report") and s["x402"]["ready"] is False


def _card(ref, product=None, **k):
    return {"hash": "c" * 64, "ref": ref, "title": "Synthetic landmark paper", "year": 2016, "cited_by_count": 5000,
            "retraction": {"retracted": False}, "nobel": None, "regulator": None, "topics": [],
            "proven_result": {"quote": "We present a sensor.", "source": None}, "product": product or IDEA,
            "product_source": "synthetic", "field": "Engineering", "topic": "Wearables", "ids": {"doi": "10.0/x"}}


def test_sibyl_is_the_shared_memory_with_tiers_and_conflict_refusal(monkeypatch):
    pytest.importorskip("sibyl_memory_client")
    st = server.State(Qloo(InProcess(), mode="mock", sleep=lambda s: None), FakeQloo())
    monkeypatch.setattr(research, "research_card", lambda ref, product=None, **k: _card(ref, product))
    job = agent.start(st, ref="10.0/x", wait=True)
    titles = [s_["title"] for s_ in job["steps"]]
    assert "the agent's plan, in shared memory" in titles                 # HOT: the crossing's plan and cursor
    assert "the paper on the reference shelf" in titles                   # REFERENCE: the paper document
    shelf = next(s_ for s_ in job["steps"] if s_["title"] == "the paper on the reference shelf")
    assert shelf["output"].startswith("seq ")
    key = agent.memory_key("10.0/x", None)
    assert agent.hot_get("lock:" + key).get("last_report") == job["report"]
    # a second agent while one runs: its conflicting writes are refused
    agent.JOBS["ghost"] = {"id": "ghost", "status": "running", "started": 0.0, "steps": []}
    agent.hot_set("lock:" + key, {"running": "ghost"})
    second = agent.start(st, ref="10.0/x", wait=True)
    t2 = [s_["title"] for s_ in second["steps"]]
    assert "another agent holds this crossing" in t2 and "nothing written: the other agent holds this crossing" in t2
    assert "the agent remembers this crossing" not in t2
    assert agent.hot_get("lock:" + key).get("running") == "ghost"         # the running agent's lock was not overwritten
    agent.JOBS.pop("ghost")
    # the FTS search finds the shelved paper
    from knos.record import search as rsearch
    from knos_wanted import company
    got = rsearch.search("Synthetic landmark", root=company.root())
    assert any("Synthetic landmark" in json.dumps(r, default=str) for r in got["rows"]), got["said"]


def test_memory_search_over_http_and_the_harness_proxy(app, monkeypatch):
    base, _ = app
    assert call(base, "/api/memory/search")[0] == 400
    st, lst = call(base, "/mcp", {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert not [t for t in lst["result"]["tools"] if t["name"].startswith("qloo_")]          # no agent key: no Qloo tool
    from knos_wanted import agent, agentkeys
    monkeypatch.setattr(agent, "_agent", lambda: {"kind": "agent", "agent_key": "k1"})       # an agent key's caller
    monkeypatch.setattr(agentkeys, "take_qloo", lambda kid: None)
    st, lst = call(base, "/mcp", {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    qloo_tools = [t for t in lst["result"]["tools"] if t["name"].startswith("qloo_")]
    assert len(qloo_tools) == 10 and all("MOCK" in t["description"] for t in qloo_tools)   # labelled: this state is mock
    st, x = call(base, "/mcp", {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                                "params": {"name": "qloo_find_tags", "arguments": {"query": "coffee"}}})
    sc = x["result"]["structuredContent"]
    assert sc.get("_mock") == MOCK_LABEL                                   # a mock answer says so in the envelope
    assert call(base, "/mcp", {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "qloo_nope"}})[1]["error"]["code"] == -32602


def test_the_hosted_mcp_is_registered_and_the_report_states_qloos_limits():
    doc = json.loads((ROOT / "server.hosted.json").read_text(encoding="utf-8"))   # the hosted server, by its own name
    assert doc["remotes"] == [{"type": "streamable-http", "url": "https://knos.onrender.com/mcp"}]
    rep = __import__("knos_wanted.check", fromlist=["demand_check"]).demand_check(IDEA, client=FakeQloo())
    assert "no prices, no market sizes" in rep["limits"] and "willingness to pay" in rep["limits"]
    assert rep["persona"] and rep["ladder"] and rep["tag_families"]
    plan = rep["decision"]["plan"]
    assert plan["persona"] and plan["ladder"][0]["name"] and plan["venue_price_level"] == 3
