"""knos_demand_check: listed only on KNOS_MCP_TOOLS=demand, and answers with the hosted app's code-made decision.
Tested against a LOCAL demand-check server (apps/wanted) with no Qloo key: the decision must be 'cannot decide'."""
import json
import sys
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from knos import demand_tool, mcp

APP = Path(__file__).resolve().parents[1] / "apps" / "wanted"


def test_listed_only_on_opt_in(monkeypatch):
    monkeypatch.delenv("KNOS_MCP_TOOLS", raising=False)
    assert "knos_demand_check" not in {t["name"] for t in mcp._tools_now()}
    monkeypatch.setenv("KNOS_MCP_TOOLS", "ideas,demand")
    tools = {t["name"]: t for t in mcp._tools_now()}
    assert tools["knos_demand_check"]["annotations"]["readOnlyHint"] is True
    assert tools["knos_demand_check"]["inputSchema"]["required"] == ["idea"]


@pytest.fixture
def local_app(monkeypatch, tmp_path):
    for k in ("QLOO_API_KEY", "KNOS_WANTED_REFEREE_KEYS", "KNOS_WANTED_DEVNET_KEYPAIR"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("KNOS_WANTED_MOCK", "1")
    monkeypatch.setenv("KNOS_WANTED_STATE", str(tmp_path / "state"))
    monkeypatch.setenv("KNOS_WANTED_CACHE", str(tmp_path / "cache"))
    monkeypatch.syspath_prepend(str(APP))
    before = {m: v for m, v in sys.modules.items() if m.startswith("knos_wanted")}
    from knos_wanted import server
    from knos_wanted.qloo_mcp import InProcess, Qloo
    from knos_wanted.qloo_rest import Client
    state = server.State(Qloo(InProcess(), mode="mock", sleep=lambda s: None), Client(key="", folder=tmp_path / "rest"))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.make_handler(state))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    for m in [m for m in sys.modules if m.startswith("knos_wanted")]:
        sys.modules.pop(m)
    sys.modules.update(before)          # the modules other test files imported at collection stay the ones they hold


def test_calls_the_hosted_check(monkeypatch, local_app):
    monkeypatch.setenv("KNOS_WANTED_URL", local_app)
    got = demand_tool.demand_check({"idea": "A smart water bottle that glows to remind you to drink", "place": "Lagos", "picked": True})
    assert got["decision"] == "CANNOT_DECIDE" and got["reasons"][0] == "cannot decide: no Qloo evidence"
    assert got["target_units"] is None and len(got["report_hash"]) == 64 and got["report_url"].startswith(local_app)
    json.dumps(got)


def test_refuses_bad_input_and_unreachable(monkeypatch):
    monkeypatch.setenv("KNOS_WANTED_URL", "http://127.0.0.1:9")
    with pytest.raises(mcp.Failed, match="8 to 500"):
        demand_tool.demand_check({"idea": "short"})
    with pytest.raises(mcp.Failed, match="could not be reached"):
        demand_tool.demand_check({"idea": "A smart water bottle that glows"})
    monkeypatch.setenv("KNOS_WANTED_URL", "ftp://x")
    with pytest.raises(mcp.Failed, match="https"):
        demand_tool.demand_check({"idea": "A smart water bottle that glows"})
