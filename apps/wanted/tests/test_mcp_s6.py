"""Spec S6 on the remote MCP (knos_wanted.agent, POST /mcp): every tool has a title and readOnlyHint or
destructiveHint; arguments are checked against the inputSchema before anything runs; every error is isError with one
next action; knos_near_swarm_job and knos_iris_check_proof are listed and read only. The rate limit is server.py's
state.allow (tests/test_mcp_limit.py)."""
import types

from knos_wanted import agent, near_jobs


def state():
    return types.SimpleNamespace(q=types.SimpleNamespace(mode="mock", server=None, tools=[], capabilities={}))


def call(name, args):
    return agent.mcp(state(), {"id": 7, "method": "tools/call", "params": {"name": name, "arguments": args}})["result"]


def test_every_tool_has_a_title_and_a_read_only_or_destructive_hint():
    tools = agent.mcp(state(), {"id": 1, "method": "tools/list"})["result"]["tools"]
    for t in tools:
        assert t.get("title") and t["annotations"]["title"], t["name"]
        assert isinstance(t["annotations"]["readOnlyHint"], bool) and isinstance(t["annotations"]["destructiveHint"], bool), t["name"]
    got = {t["name"]: t for t in tools}
    for n in ("knos_near_swarm_job", "knos_iris_check_proof"):
        assert got[n]["annotations"]["readOnlyHint"] is True and got[n]["annotations"]["destructiveHint"] is False


def test_a_bad_argument_is_an_error_with_a_next_action_before_anything_runs():
    for name, args, said in (("knos_demand_check", {}, "idea: required"),
                             ("knos_demand_check", {"idea": 5}, "idea: a string"),
                             ("knos_research_card", {"ref": "x", "nope": 1}, "nope: not an argument"),
                             ("knos_iris_check_proof", {"brief": {"milestones": [{"key": "m"}]}, "kind": "fax", "proof": "x"}, "kind: one of"),
                             ("knos_near_swarm_job", {"id": "../etc"}, "id: a job id")):
        r = call(name, args)
        assert r["isError"] is True and said in r["content"][0]["text"], (name, r)
        assert r["structuredContent"]["next"] and r["content"][-1]["text"].startswith("Next: "), name


def test_check_proof_runs_the_rules_referee_iris_runs():
    brief = {"milestones": [{"key": "m1", "name": "CI", "target": "the check passes", "verifier": {"kind": "machine", "check": "unit"}}]}
    proof = {"check_run": {"name": "unit", "conclusion": "success", "status": "completed"}}
    r = call("knos_iris_check_proof", {"brief": brief, "kind": "checkrun", "proof": proof})
    assert r.get("isError") is not True and "IRIS" in r["structuredContent"]["referee"], r
    bare = call("knos_iris_check_proof", {"brief": brief, "kind": "checkrun", "proof": proof["check_run"]})
    assert bare["structuredContent"].get("decision") == r["structuredContent"].get("decision"), bare


def test_the_swarm_job_reads_the_contract_and_says_when_it_is_not_there(monkeypatch):
    monkeypatch.setattr(near_jobs, "_view", lambda m, a, timeout=20: None)
    r = call("knos_near_swarm_job", {"id": "job-0"})
    assert r["structuredContent"]["found"] is False and r["structuredContent"]["next"]
    monkeypatch.setattr(near_jobs, "_view", lambda m, a, timeout=20: {"bid": "1000", "paid": "agent-a.knos-swarm-1105.testnet"})
    r = call("knos_near_swarm_job", {"id": "job-1105164458"})
    assert r["structuredContent"]["job"]["bid"] == "1000" and r["structuredContent"]["network"] == "testnet"

    def down(m, a, timeout=20):
        raise OSError("timed out")
    monkeypatch.setattr(near_jobs, "_view", down)
    r = call("knos_near_swarm_job", {"id": "job-1"})
    assert r["isError"] and "wait a minute" in r["structuredContent"]["next"]
