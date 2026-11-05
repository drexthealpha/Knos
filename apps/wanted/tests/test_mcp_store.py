"""The app-store MCP profile (knos_wanted.agent, POST /mcp/store): every tool annotated; the store lists only read-only
tools (knos_ready, knos_demand_check, qloo_*); any other tool is refused there; a daily cap holds every caller."""
import types

from knos_wanted import agent


def state():
    return types.SimpleNamespace(q=types.SimpleNamespace(mode="mock", server=None, tools=[], capabilities={}))


def names(out):
    return [t["name"] for t in out["result"]["tools"]]


def test_every_tool_is_annotated_and_every_writing_tool_is_destructive():
    tools = agent.mcp(state(), {"id": 1, "method": "tools/list"})["result"]["tools"]
    assert tools and all(t["annotations"]["title"] and isinstance(t["annotations"]["readOnlyHint"], bool) for t in tools)
    assert all(t["annotations"]["readOnlyHint"] or t["annotations"]["destructiveHint"] for t in tools)   # spec S6
    assert "knos_preorder" in [t["name"] for t in tools if t["annotations"]["destructiveHint"]]
    assert all(t["annotations"]["readOnlyHint"] for t in tools if t["name"] in ("knos_ready", "knos_demand_check"))


def test_the_store_lists_and_answers_only_read_only_tools(monkeypatch):
    got = names(agent.mcp(state(), {"id": 1, "method": "tools/list"}, "store"))
    assert "knos_ready" in got and "knos_demand_check" in got and "knos_preorder" not in got
    assert all(n in ("knos_ready", "knos_demand_check") or n.startswith("qloo_") for n in got)
    no = agent.mcp(state(), {"id": 2, "method": "tools/call", "params": {"name": "knos_preorder", "arguments": {}}}, "store")
    assert "money moves on the Knos site" in no["error"]["message"]
    monkeypatch.setattr(agent, "_store_day", {"day": "", "n": 0})
    monkeypatch.setattr(agent, "STORE_DAILY_CAP", 1)
    brief = {"milestones": [{"key": "m1", "name": "Pilot", "target": "100 units pass a 72 h soak test", "verifier": {"check": "test_soak"},
                             "deadline_days": 30}]}
    first = agent.mcp(state(), {"id": 3, "method": "tools/call", "params": {"name": "knos_ready", "arguments": {"brief": brief}}}, "store")
    assert "error" not in first
    capped = agent.mcp(state(), {"id": 4, "method": "tools/call", "params": {"name": "knos_ready", "arguments": {"brief": brief}}}, "store")
    assert "cap" in capped["error"]["message"]


def test_a_store_demand_check_naming_a_person_is_refused_before_any_call(monkeypatch):
    monkeypatch.setattr(agent, "_store_day", {"day": "", "n": 0})
    out = agent.mcp(state(), {"id": 5, "method": "tools/call",
                              "params": {"name": "knos_demand_check", "arguments": {"idea": "a gift for jane.doe@example.com"}}}, "store")
    assert out["result"]["isError"]
