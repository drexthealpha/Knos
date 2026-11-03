"""knos_verify and knos_receipt in the existing `knos mcp` server, over stdio and over Streamable HTTP
(knos.mcp_http), on loopback only."""

from __future__ import annotations

import http.client
import io
import json
import subprocess
from pathlib import Path

import pytest

from knos import init, mcp, mcp_http


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(repo), check=True, capture_output=True, text=True)


@pytest.fixture()
def proj(tmp_path):
    r = tmp_path / "p"
    r.mkdir()
    (r / "m.py").write_text("X = 1\n", encoding="utf-8")
    _git(r, "init", "-q", "-b", "main")
    _git(r, "config", "user.email", "t@example.com")
    _git(r, "config", "user.name", "T")
    _git(r, "add", "-A")
    _git(r, "commit", "-qm", "base")
    _git(r, "checkout", "-qb", "work")
    (r / "m.py").write_text("X = 2\n", encoding="utf-8")
    _git(r, "commit", "-qam", "x")
    return r


def _talk(lines: list[dict]) -> list[dict]:
    out = io.StringIO()
    mcp.serve(io.StringIO("".join(json.dumps(x) + "\n" for x in lines)), out)
    return [json.loads(x) for x in out.getvalue().splitlines()]


def test_the_two_tools_are_listed_read_only_with_string_and_integer_arguments_only():
    tools = {t["name"]: t for t in mcp.TOOLS}
    for name in ("knos_verify", "knos_receipt"):
        t = tools[name]
        assert {s["type"] for s in t["inputSchema"]["properties"].values()} <= {"string", "integer"}
        assert "sends nothing" in t["description"].lower()
    # knos_receipt only reads; knos_verify runs the repository's tests: not read-only, on no allowlist, not a poster
    assert tools["knos_receipt"]["annotations"] == {"readOnlyHint": True, "openWorldHint": True}
    assert tools["knos_verify"]["annotations"] == {"readOnlyHint": False, "openWorldHint": True, "destructiveHint": False}
    assert tools["knos_verify"]["_meta"] == {mcp.RUNS_CODE: True}
    assert "knos_verify" not in init.read_only_tools() and "knos_verify" not in init.posting_tools()
    assert "knos_verify" not in init.hermes_block(["knos"]) and "knos_receipt" in init.hermes_block(["knos"])
    assert "knos_verify" in mcp.INSTRUCTIONS and "banned" in mcp.INSTRUCTIONS


def test_knos_verify_over_stdio_returns_the_receipt_and_the_markdown(proj):
    (listed, called) = _talk([
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
         "params": {"name": "knos_verify", "arguments": {"path": str(proj), "base": "main", "tests": "git --version", "runs": 1, "agent": "Hermes Agent"}}},
    ])
    assert "knos_verify" in [t["name"] for t in listed["result"]["tools"]]
    got = called["result"]["structuredContent"]
    assert called["result"]["isError"] is False and got["verdict"] == "pass" and got["may_open_pr"] is True
    assert "Hermes Agent" in got["pr_markdown"] and Path(got["receipt_file"]).is_file()
    (checked,) = _talk([{"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "knos_receipt", "arguments": {"file": got["receipt_file"]}}}])
    assert checked["result"]["structuredContent"]["valid"] is True and checked["result"]["structuredContent"]["verdict"] == "pass"


def test_out_must_stay_inside_the_checkout(proj, tmp_path):
    outside = tmp_path / "elsewhere.json"
    (called,) = _talk([{"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "knos_verify",
                       "arguments": {"path": str(proj), "base": "main", "tests": "git --version", "runs": 1, "out": str(outside)}}}])
    got = called["result"]["structuredContent"]
    assert got["verdict"] == "error" and "inside the checkout" in got["reasons"][0] and not outside.exists()
    (called,) = _talk([{"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "knos_verify",
                       "arguments": {"path": str(proj), "base": "main", "tests": "git --version", "runs": 1, "out": "r.json"}}}])
    assert called["result"]["structuredContent"]["receipt_file"] == str((proj / "r.json").resolve())


def test_bad_arguments_are_one_sentence(proj):
    (called,) = _talk([{"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "knos_verify", "arguments": {"path": str(proj), "runs": 9}}}])
    assert called["result"]["isError"] is True and "runs must be a whole number from 1 to 3" in called["result"]["content"][0]["text"]
    (called,) = _talk([{"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "knos_receipt", "arguments": {"file": str(proj / "nope.json")}}}])
    assert called["result"]["structuredContent"]["valid"] is False


@pytest.fixture()
def http_server(monkeypatch):
    import threading
    monkeypatch.delenv("KNOS_MCP_HTTP_TOKEN", raising=False)
    servers = []

    def start(token: str | None = None):
        if token:
            monkeypatch.setenv("KNOS_MCP_HTTP_TOKEN", token)
        httpd = mcp_http.make("127.0.0.1:0")
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        servers.append(httpd)
        return httpd.server_address[1]
    yield start
    for s in servers:
        s.shutdown()
        s.server_close()


def _post(port: int, body, headers=None, path="/mcp"):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    c.request("POST", path, body=json.dumps(body), headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream", **(headers or {})})
    r = c.getresponse()
    data = r.read()
    return r.status, r.getheader("Content-Type"), (json.loads(data) if data else None)


def test_streamable_http_initialize_list_and_notification(http_server):
    port = http_server()
    status, kind, hello = _post(port, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18", "capabilities": {}}})
    assert status == 200 and kind == "application/json" and hello["result"]["serverInfo"]["name"] == "knos"
    assert _post(port, {"jsonrpc": "2.0", "method": "notifications/initialized"})[:1] == (202,)
    status, _k, listed = _post(port, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    runs_code = {t["name"] for t in mcp.TOOLS if (t.get("_meta") or {}).get(mcp.RUNS_CODE)}   # hidden without a token
    assert status == 200 and len(listed["result"]["tools"]) == len(mcp.TOOLS) - len(runs_code) and runs_code
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    c.request("GET", "/mcp")
    assert c.getresponse().status == 405
    assert _post(port, {"jsonrpc": "2.0", "id": 3, "method": "ping"}, path="/other")[0] == 404


def test_http_refuses_a_foreign_origin_and_without_the_token(http_server):
    port = http_server(token="s3cret-for-tests")
    ping = {"jsonrpc": "2.0", "id": 1, "method": "ping"}
    assert _post(port, ping)[0] == 401
    assert _post(port, ping, {"Authorization": "Bearer s3cret-for-tests", "Origin": "https://evil.example"})[0] == 403
    status, _k, pong = _post(port, ping, {"Authorization": "Bearer s3cret-for-tests", "Origin": "http://localhost:3000"})
    assert status == 200 and pong == {"jsonrpc": "2.0", "id": 1, "result": {}}


def test_without_a_token_http_never_leaves_loopback_and_does_not_serve_knos_verify(http_server, monkeypatch):
    monkeypatch.delenv("KNOS_MCP_HTTP_TOKEN", raising=False)
    with pytest.raises(mcp_http.Refused, match="KNOS_MCP_HTTP_TOKEN"):
        mcp_http.make("0.0.0.0:0")
    assert mcp_http.main("0.0.0.0:0") == 2
    port = http_server()
    status, _k, got = _post(port, {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "knos_verify", "arguments": {"path": "."}}})
    assert status == 200 and got["error"]["message"] == "Unknown tool: knos_verify"


def test_the_command_line_takes_http_and_binds_loopback_by_default():
    assert mcp_http.parse_address("127.0.0.1:8808") == ("127.0.0.1", 8808)
    assert mcp_http.parse_address(":9000") == ("127.0.0.1", 9000)
    assert mcp_http.parse_address("[::1]:9000") == ("::1", 9000)
    assert not mcp_http._origin_ok("http://attacker.test") and mcp_http._origin_ok(None) and mcp_http._origin_ok("http://127.0.0.1:1")
