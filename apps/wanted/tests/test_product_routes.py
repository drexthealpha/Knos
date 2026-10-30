"""The project, company and OpenAPI routes over HTTP, and the MCP tools that reach them."""
import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from knos_wanted import agent, server
from knos_wanted.qloo_mcp import InProcess, Qloo


@pytest.fixture
def app():
    state = server.State(Qloo(InProcess(), mode="mock", sleep=lambda s: None))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.make_handler(state))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}", state
    httpd.shutdown()


def call(base, path, body=None, token=None):
    h = {"Content-Type": "application/json"}
    if token:
        h["Authorization"] = "Bearer " + token
    req = urllib.request.Request(base + path, data=None if body is None else json.dumps(body).encode(), headers=h)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read()
            return r.status, json.loads(raw) if r.headers.get("Content-Type", "").startswith("application/json") else raw
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def test_projects_over_http(app):
    base, _ = app
    st, t = call(base, "/api/templates")
    assert st == 200 and len(t["templates"]) == 5
    assert call(base, "/api/project", {"template": "internal_tool", "title": "Tool"})[0] == 401
    tok = call(base, "/api/auth/guest", {"label": "tester"})[1]["token"]
    st, p = call(base, "/api/project", {"template": "hardware_prototype", "title": "Board", "regulatory": ["iso13485"]}, tok)
    assert st == 200 and len(p["milestones"]) == 3 + 7
    st, got = call(base, f"/api/project?id={p['id']}")
    assert st == 200 and got["title"] == "Board"
    assert call(base, "/api/project?id=zzzzzzzzzzzz")[0] == 404
    st, sb = call(base, "/api/sandbox", {"template": "ai_model_eval"}, tok)
    assert st == 200 and sb["sandbox"] is True
    st, ref = call(base, "/api/referral", {"target": "p=" + p["id"], "wallet": "11111111111111111111111111111111"}, tok)
    assert st == 200
    req = urllib.request.Request(base + ref["link"])
    opener = urllib.request.build_opener(type("NoRedirect", (urllib.request.HTTPRedirectHandler,), {"redirect_request": lambda *a, **k: None}))
    try:
        opener.open(req, timeout=10)
    except urllib.error.HTTPError as e:
        assert e.code == 302 and e.headers["Location"] == f"/app/?ref={ref['code']}#projects={p['id']}"
    st, csv = call(base, f"/api/company/export?project={p['id']}&format=xero")
    assert st == 200 and csv.startswith(b"*ContactName")
    assert call(base, "/api/project/fund", {"project": p["id"], "milestone": "design", "units": 5, "account": "x"})[0] in (400, 503)


def test_openapi_and_mcp(app):
    base, state = app
    st, doc = call(base, "/openapi.json")
    assert st == 200 and doc["openapi"] == "3.1.0" and "/api/project/claim" in doc["paths"] and "/mcp" in doc["paths"]
    tools = agent.mcp(state, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})["result"]["tools"]
    names = {t["name"] for t in tools}
    assert {"knos_templates", "knos_projects", "knos_project_open", "knos_project_claim", "knos_project_post", "knos_openapi"} <= names
    got = agent.mcp(state, {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "knos_templates", "arguments": {}}})
    assert len(got["result"]["structuredContent"]["templates"]) == 5
    refused = agent.mcp(state, {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                                "params": {"name": "knos_project_open", "arguments": {"template": "internal_tool", "title": "x y", "session": "bad"}}})
    assert refused["result"]["isError"] is True


def test_pages_have_the_views(app):
    base, _ = app
    st, page = call(base, "/app/")
    assert st == 200 and b'id="v-projects"' in page and b'id="v-teams"' in page and b"/static/valley.js" in page
    st, js = call(base, "/static/valley.js")
    assert st == 200 and b"KNOS_VIEW" in js


def test_every_tool_mcp_lists_is_answered_by_a_handler(app):
    """tools/call on each name tools/list gives: a tool may refuse empty arguments, but never 'unknown tool'."""
    _, state = app
    tools = agent.mcp(state, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})["result"]["tools"]
    assert {"knos_ready", "knos_usage", "knos_milestone_prompt"} <= {t["name"] for t in tools}
    unknown = []
    for i, t in enumerate(tools):
        got = agent.mcp(state, {"jsonrpc": "2.0", "id": 10 + i, "method": "tools/call", "params": {"name": t["name"], "arguments": {}}})
        said = json.dumps(got.get("error") or got.get("result") or {})
        if "unknown tool" in said:
            unknown.append(t["name"])
    assert not unknown, unknown
    ready = agent.mcp(state, {"jsonrpc": "2.0", "id": 99, "method": "tools/call", "params": {"name": "knos_ready", "arguments": {"brief": {
        "milestones": [{"name": "Login under 300 ms", "target": "p95 under 300 ms on test_login", "verifier": {"kind": "machine", "check": "ci / test_login"},
                        "deadline_days": 7}]}}}})
    assert ready["result"]["structuredContent"]["ready"] is True
    assert "knos_ready" in agent.mcp(state, {"jsonrpc": "2.0", "id": 100, "method": "tools/call",
                                             "params": {"name": "knos_usage", "arguments": {}}})["result"]["structuredContent"]["calls"]


def test_a_project_opened_on_a_recalled_crossing_keeps_its_grounding_line(app, monkeypatch, tmp_path):
    """A crossing recalled from memory is kept only in the server's memory; opening a project on it writes the report
    where the project's Grounding (Qloo) line reads it (live: the line was missing on such a project)."""
    from knos_wanted import escrow
    base, state = app
    monkeypatch.setattr(escrow, "_state_dir", lambda: tmp_path)
    h = "c" * 64
    state.keep({"hash": h, "idea": "a recovery shoe", "decision": {"verdict": "OPEN", "plan": {"who": {"age": "25_to_29", "gender": "female"},
                "where": ["Austin"], "tier": "premium", "unit_price": 3}}, "grounding": {"comparables": ["Tracksmith"]}})
    assert not (tmp_path / "reports" / f"{h}.report").exists()
    tok = call(base, "/api/auth/guest", {"label": "tester"})[1]["token"]
    brief = {"milestones": [{"key": "m1", "name": "Sell-through", "target": "200 pairs in 60 days on test_sell_through",
                             "verifier": {"kind": "machine", "check": "ci / test_sell_through"}, "deadline_days": 14}]}
    st, p = call(base, "/api/project", {"template": "custom", "title": "Recovery shoe", "brief": brief, "report": h}, tok)
    assert st == 200, p
    g = call(base, f"/api/project?id={p['id']}")[1]["grounding"]
    assert g["launch_cities"] == ["Austin"] and g["comparables"] == ["Tracksmith"] and g["source"] == "Qloo"


def test_a_project_is_archived_by_its_buyer_or_the_operator_and_stays_readable(app, monkeypatch, tmp_path):
    """Archived: off the public list (GET /api/projects, knos_projects), still at /api/project?id=. Only its buyer or the
    operator's key (KNOS_ADMIN_KEY) may; a wrong key, another account or no session is refused."""
    from knos_wanted import escrow
    base, _ = app
    monkeypatch.setattr(escrow, "_state_dir", lambda: tmp_path)
    key = "k" * 40
    monkeypatch.setenv("KNOS_ADMIN_KEY", key)
    tok = call(base, "/api/auth/guest", {"label": "buyer"})[1]["token"]
    other = call(base, "/api/auth/guest", {"label": "someone else"})[1]["token"]
    pa = call(base, "/api/project", {"template": "internal_tool", "title": "Mine"}, tok)[1]["id"]
    pb = call(base, "/api/project", {"template": "internal_tool", "title": "Left by a test"}, tok)[1]["id"]
    listed = lambda: [p["id"] for p in call(base, "/api/projects")[1]["projects"]]  # noqa: E731
    assert {pa, pb} <= set(listed())
    assert call(base, "/api/project/archive", {"project": pa})[0] == 401                          # no session, no key
    assert call(base, "/api/project/archive", {"project": pa}, other)[0] == 400                   # not the buyer
    st, got = call(base, "/api/project/archive", {"project": pa}, tok)
    assert st == 200 and got["archived"]["by"] == "buyer" and pa not in listed()

    def post(body, header):
        req = urllib.request.Request(base + "/api/project/archive", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json", "X-Knos-Admin": header})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")
    assert post({"project": pb}, "wrong" * 8)[0] == 401
    st, got = post({"project": pb, "why": "proof run"}, key)
    assert st == 200 and got["archived"]["by"] == "operator" and pb not in listed()
    assert call(base, f"/api/project?id={pb}")[1]["unlisted"]["why"] == "proof run"             # still readable by id


def test_knos_usage_records_a_goals_token_use_only_with_the_operators_key(app, monkeypatch, tmp_path):
    """M11: the operator records a goal's measured token use through knos_usage; nobody else writes it, and the public
    answer never shows it (N3: no goal's name in a public answer)."""
    from knos_wanted import escrow
    base, _ = app
    monkeypatch.setattr(escrow, "_state_dir", lambda: tmp_path)
    monkeypatch.setenv("KNOS_ADMIN_KEY", "k" * 40)
    rec = {"v": 1, "goal": "TASK-X", "output_tokens": 1200, "input_tokens": 40, "messages": 9, "since": "2026-10-21T00:00:00Z"}

    def mcp(args, key=None):
        req = urllib.request.Request(base + "/mcp", json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                     "params": {"name": "knos_usage", "arguments": args}}).encode(),
                                     {"Content-Type": "application/json", **({"X-Knos-Admin": key} if key else {})})
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())["result"]
    refused = mcp({"record": rec})
    assert refused.get("isError") and "X-Knos-Admin" in refused["content"][0]["text"]
    got = json.loads(mcp({"record": rec}, "k" * 40)["content"][0]["text"])
    assert "goals" not in got and "TASK-X" not in json.dumps(json.loads(mcp({})["content"][0]["text"]))     # kept, never shown
    from knos_wanted import product_routes
    assert product_routes._goals()["TASK-X"]["output_tokens"] == 1200


def test_feedback_and_ask_reach_their_routes(app):
    base, _ = app
    st, fb = call(base, "/api/feedback", {"hash": "0" * 64, "useful": True, "note": ""})
    assert st in (200, 400) and "io error" not in json.dumps(fb)
    st, ask = call(base, "/api/ask", {"hash": "0" * 64, "question": "who buys"})
    assert st == 400 and "unknown result" in ask["error"]
