"""The MCP tasks and skills extensions on `knos mcp` (knos.mcp_ext) and Knos's A2A agent (knos.a2a). The long tool is
a stand-in (synthetic verdict); the A2A server runs on loopback only; no outside network."""
from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.request
from pathlib import Path

from knos import a2a, mcp

ROOT = Path(__file__).resolve().parents[1]
TASKS = {"_meta": {"io.modelcontextprotocol/clientCapabilities": {"extensions": {"io.modelcontextprotocol/tasks": {}}}}}


def server_with_slow_verify(result=None, fail=False, seconds=0.05):
    s = mcp.Server()

    def verify(_args):
        time.sleep(seconds)
        if fail:
            raise RuntimeError("synthetic failure")
        return result or {"verdict": "pass", "synthetic": True}
    s._tools["knos_verify"] = verify
    return s


def rpc(s, method, params, rid=1):
    return s.answer({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})


def test_discover_advertises_both_extensions_to_a_client_that_speaks_extensions():
    got = rpc(mcp.Server(), "server/discover", TASKS)["result"]["capabilities"]["extensions"]
    assert "io.modelcontextprotocol/tasks" in got and "io.modelcontextprotocol/skills" in got
    assert "extensions" not in rpc(mcp.Server(), "server/discover", {})["result"]["capabilities"]


def test_a_long_call_becomes_a_task_only_for_a_client_that_takes_tasks():
    s = server_with_slow_verify()
    started = rpc(s, "tools/call", {"name": "knos_verify", "arguments": {"path": "/synthetic"}, **TASKS})["result"]
    assert started["resultType"] == "task" and started["status"] == "working" and started["pollIntervalMs"] > 0 and "createdAt" in started
    for _ in range(100):
        got = rpc(s, "tasks/get", {"taskId": started["taskId"]})["result"]
        if got["status"] != "working":
            break
        time.sleep(0.02)
    assert got["status"] == "completed" and got["resultType"] == "complete" and got["result"]["structuredContent"]["verdict"] == "pass"
    plain = rpc(s, "tools/call", {"name": "knos_verify", "arguments": {"path": "/synthetic"}})["result"]     # no tasks declared: the answer itself
    assert plain["resultType"] == "complete" and plain["structuredContent"]["verdict"] == "pass"
    assert rpc(s, "tasks/get", {"taskId": "nope"})["error"]["code"] == -32602
    assert rpc(s, "tasks/update", {"taskId": started["taskId"], "inputResponses": {}})["result"] == {"resultType": "complete"}


def test_a_task_can_be_cancelled_while_it_works():
    s = server_with_slow_verify(seconds=1.0)
    started = rpc(s, "tools/call", {"name": "knos_verify", "arguments": {"path": "/synthetic"}, **TASKS})["result"]
    assert rpc(s, "tasks/cancel", {"taskId": started["taskId"]})["result"] == {"resultType": "complete"}
    time.sleep(1.3)                                         # the work finished after the cancel: the task stays cancelled
    assert rpc(s, "tasks/get", {"taskId": started["taskId"]})["result"]["status"] == "cancelled"


def test_skills_are_listed_with_digests_and_read_as_resources():
    s = mcp.Server()
    listed = rpc(s, "skills/list", {})["result"]
    names = {x["frontmatter"]["name"] for x in listed["skills"]}
    assert "knos-verify" in names and listed["cacheScope"] == "public"
    entry = next(x for x in listed["skills"] if x["frontmatter"]["name"] == "knos-verify")
    md = next(r for r in entry["resources"] if r["uri"] == "skill://knos-verify/SKILL.md")
    raw = (ROOT / "plugin" / "skills" / "knos-verify" / "SKILL.md").read_bytes()
    assert md["digest"] == "sha256:" + hashlib.sha256(raw).hexdigest() and md["size"] == len(raw)
    read = rpc(s, "resources/read", {"uri": "skill://knos-verify/SKILL.md"})["result"]
    assert read["contents"][0]["text"].encode() == raw
    assert rpc(s, "skills/get", {"uri": "skill://knos-verify/SKILL.md"})["result"]["skill"]["uri"] == "skill://knos-verify/SKILL.md"
    assert rpc(s, "resources/read", {"uri": "skill://knos-verify/../../pyproject.toml"})["error"]["code"] == -32602
    assert rpc(s, "skills/get", {"uri": "skill://nope/SKILL.md"})["error"]["code"] == -32602


REQUIRED = ("name", "description", "supportedInterfaces", "version", "capabilities", "defaultInputModes", "defaultOutputModes", "skills")


def test_the_agent_card_has_every_required_field_of_a2a_1_0():
    c = a2a.card("http://127.0.0.1:8765/a2a/v1", version="0.0.0-synthetic")
    assert all(k in c for k in REQUIRED) and "Knos" in c["name"] and c["url"] == c["supportedInterfaces"][0]["url"]
    assert c["supportedInterfaces"][0]["protocolBinding"] == "JSONRPC" and c["supportedInterfaces"][0]["protocolVersion"] == "1.0"
    assert all({"id", "name", "description", "tags"} <= set(sk) for sk in c["skills"]) and isinstance(c["capabilities"], dict)


def test_the_published_card_file_is_the_one_the_server_serves():
    path = ROOT / "examples" / "a2a" / ".well-known" / "agent-card.json"
    got = json.loads(path.read_text(encoding="utf-8"))
    version = re.search(r'(?m)^version = "([^"]+)"', (ROOT / "pyproject.toml").read_text(encoding="utf-8")).group(1)
    want = a2a.card(got["url"], version=version)          # the package's own version, not the one the file says
    assert got == want


def test_send_message_runs_a_skill_and_get_task_reads_it_back():
    calls = []
    agent = a2a.Agent(call=lambda tool, args: calls.append((tool, args)) or {"synthetic": True, "tool": tool})
    msg = {"messageId": "m1", "role": "ROLE_USER", "parts": [{"text": "please check https://github.com/o/r/pull/12"}]}
    out = agent.handle({"jsonrpc": "2.0", "id": 1, "method": "SendMessage", "params": {"message": msg}}, "1.0")["result"]["task"]
    assert out["status"]["state"] == "TASK_STATE_COMPLETED" and calls == [("knos_check_pr", {"pr": "o/r#12"})]
    assert agent.handle({"jsonrpc": "2.0", "id": 2, "method": "GetTask", "params": {"id": out["id"]}})["result"]["id"] == out["id"]
    assert agent.handle({"jsonrpc": "2.0", "id": 3, "method": "GetTask", "params": {"id": "nope"}})["error"]["code"] == -32001
    assert agent.handle({"jsonrpc": "2.0", "id": 4, "method": "CancelTask", "params": {"id": out["id"]}})["error"]["code"] == -32002
    assert agent.handle({"jsonrpc": "2.0", "id": 5, "method": "SendStreamingMessage", "params": {}})["error"]["code"] == -32004
    assert agent.handle({"jsonrpc": "2.0", "id": 6, "method": "GetTask", "params": {"id": out["id"]}}, "0.3")["error"]["code"] == -32009


def test_verify_runs_code_so_it_is_refused_unless_the_operator_allowed_it():
    agent = a2a.Agent(call=lambda tool, args: {"ran": tool})
    msg = {"messageId": "m2", "role": "ROLE_USER", "parts": [{"data": {"skill": "verify", "path": "/synthetic"}}]}
    assert agent.send({"message": msg})["task"]["status"]["state"] == "TASK_STATE_REJECTED"
    agent.allow_verify = True
    assert agent.send({"message": msg})["task"]["status"]["state"] == "TASK_STATE_COMPLETED"
    odd = {"messageId": "m3", "role": "ROLE_USER", "parts": [{"text": "hello"}]}
    assert agent.send({"message": odd})["task"]["status"]["state"] == "TASK_STATE_REJECTED"


def test_the_server_serves_the_card_and_answers_json_rpc_on_loopback():
    srv = a2a.serve(port=0)
    port = srv.server_address[1]
    srv.agent._call = lambda tool, args: {"synthetic": True}
    import threading
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        card = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/.well-known/agent-card.json", timeout=5).read())
        assert card["name"] == "Knos" and card["supportedInterfaces"][0]["url"].endswith("/a2a/v1")
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "SendMessage",
                           "params": {"message": {"messageId": "m", "role": "ROLE_USER", "parts": [{"data": {"skill": "find-work"}}]}}}).encode()
        req = urllib.request.Request(f"http://127.0.0.1:{port}/a2a/v1", data=body, headers={"Content-Type": "application/json", "A2A-Version": "1.0"})
        got = json.loads(urllib.request.urlopen(req, timeout=5).read())
        assert got["result"]["task"]["status"]["state"] == "TASK_STATE_COMPLETED"
    finally:
        srv.shutdown()
