"""Knos as an A2A agent: other agent platforms find Knos's Agent Card and hire it as the judge of their agents' work.

A2A 1.0.0 (github.com/a2aproject/A2A docs/specification.md and specification/a2a.proto, read 14 Oct 2026). The card is
served at `https://{server_domain}/.well-known/agent-card.json` ("The resource at this URI MUST return an AgentCard
object as defined in Section 4.4.1"); its required fields are name, description, supportedInterfaces (url,
protocolBinding, protocolVersion), version, capabilities, defaultInputModes, defaultOutputModes and skills (id, name,
description, tags). The JSON-RPC binding's methods are SendMessage, GetTask, ListTasks, CancelTask (section 5.3), its
task states TASK_STATE_SUBMITTED ... TASK_STATE_REJECTED, its errors -32001 TaskNotFoundError, -32002
TaskNotCancelableError, -32004 UnsupportedOperationError, -32009 VersionNotSupportedError (section 5.4); a client sends
`A2A-Version: 1.0` (section 3.6.1).

The card is served by the same process that answers, so it never names an endpoint that does not run:
`python -m knos.a2a serve [--port N] [--url PUBLIC_URL]` serves both, on 127.0.0.1 unless told otherwise. These A2A
methods are not hosted; the app hosts its own Agent Card (knos_wanted.agentkeys.card), whose interface is its MCP endpoint
and whose security is an agent key's OAuth 2.0 client credentials (docs/reference/A2A.md).

Skills, each one of Knos's own tools behind the same checks as `knos mcp`:
    verify      a checkout with a committed change -> the referee's cheat checks and two re-runs of its tests, a
                signed receipt (knos_verify; it runs the repository's tests on this machine, so it is off unless the
                server is started with --allow-verify)
    check-pr    a public pull request -> whether its description's claims agree with GitHub's record of its tests
                (knos_check_pr, read-only)
    find-work   open, funded work an agent can take (knos_find_work, read-only)
Input: one `data` part {"skill": ..., <the tool's arguments>}, or a text part naming a pull request URL (check-pr).
"""
from __future__ import annotations

import json
import re
import threading
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .mcp import Server

PROTOCOL_VERSION = "1.0"
CARD_PATH = "/.well-known/agent-card.json"
RPC_PATH = "/a2a/v1"
SKILLS = {"verify": "knos_verify", "check-pr": "knos_check_pr", "find-work": "knos_find_work"}
_PR = re.compile(r"https://github\.com/([^/\s]+/[^/\s]+)/pull/(\d+)")


def card(url: str, version: str | None = None) -> dict:
    """The Agent Card for an A2A JSON-RPC endpoint at `url`."""
    from . import version as installed
    return {
        "name": "Knos",
        "description": ("Knos checks research work: it re-runs the work against sealed checks and refuses known cheats, "
                        "on Solana devnet and NEAR testnet, in test money."),
        "supportedInterfaces": [{"url": url, "protocolBinding": "JSONRPC", "protocolVersion": PROTOCOL_VERSION}],
        # the same endpoint where A2A 0.3.0 cards named it (top-level url, preferredTransport); the methods answered are 1.0's
        "url": url, "preferredTransport": "JSONRPC",
        "provider": {"organization": "Knos", "url": "https://github.com/drexthealpha/Knos"},
        "version": version or installed(),
        "documentationUrl": "https://github.com/drexthealpha/Knos/blob/main/docs/reference/A2A.md",
        "capabilities": {"streaming": False, "pushNotifications": False, "extendedAgentCard": False},
        "defaultInputModes": ["application/json", "text/plain"],
        "defaultOutputModes": ["application/json"],
        "skills": [
            {"id": "verify", "name": "Verify a change as the referee would",
             "description": "Runs Knos's cheat checks on a committed change and re-runs its tests twice in a throwaway clone; returns a signed receipt.",
             "tags": ["referee", "verification", "tests", "receipt"],
             "examples": ['{"skill": "verify", "path": "/work/repo"}'], "inputModes": ["application/json"], "outputModes": ["application/json"]},
            {"id": "check-pr", "name": "Check a pull request's claims",
             "description": "Whether a public pull request's description agrees with GitHub's record of its tests at its head commit.",
             "tags": ["referee", "claims", "github", "tests"],
             "examples": ["https://github.com/OWNER/REPO/pull/12"], "inputModes": ["application/json", "text/plain"], "outputModes": ["application/json"]},
            {"id": "find-work", "name": "Find funded work",
             "description": "Lists open work orders with held money that an agent can take, with the terms that decide payment.",
             "tags": ["work", "bounty", "funded"],
             "examples": ['{"skill": "find-work"}'], "inputModes": ["application/json"], "outputModes": ["application/json"]},
        ],
    }


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class A2AError(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code, self.message = code, message


class Agent:
    """The JSON-RPC side. `call(tool, args)` runs one Knos tool (default: a knos.mcp.Server's own tools/call)."""

    def __init__(self, call=None, allow_verify: bool = False):
        self._call = call or self._mcp_call
        self.allow_verify = allow_verify
        self.tasks: dict[str, dict] = {}
        self._lock = threading.Lock()
        self._mcp: Server | None = None

    def _mcp_call(self, tool: str, args: dict) -> dict:
        from .mcp import Server
        if self._mcp is None:
            self._mcp = Server()
        got = self._mcp._call_now({"name": tool, "arguments": args})
        if got.get("isError"):
            raise A2AError(-32603, got["content"][0]["text"])
        return got.get("structuredContent") or {}

    def handle(self, msg: dict, version: str | None = None) -> dict:
        rid = msg.get("id")
        try:
            if version and version.split(".")[:2] != PROTOCOL_VERSION.split(".")[:2]:
                raise A2AError(-32009, f"A2A version {version} is not supported; this agent speaks {PROTOCOL_VERSION}")
            method, params = msg.get("method"), msg.get("params") or {}
            fn = {"SendMessage": self.send, "GetTask": self.get, "ListTasks": self.list, "CancelTask": self.cancel}.get(method) if isinstance(method, str) else None
            if fn is None:
                raise A2AError(-32004 if isinstance(method, str) else -32600, f"{method} is not supported by this agent")
            return {"jsonrpc": "2.0", "id": rid, "result": fn(params)}
        except A2AError as e:
            return {"jsonrpc": "2.0", "id": rid, "error": {"code": e.code, "message": e.message}}

    def _request(self, message: dict) -> tuple[str, dict]:
        args: dict = {}
        for part in message.get("parts") or []:
            if isinstance(part.get("data"), dict):
                args.update(part["data"])
            elif isinstance(part.get("text"), str) and (m := _PR.search(part["text"])):
                args.setdefault("skill", "check-pr")
                args.setdefault("pr", f"{m.group(1)}#{m.group(2)}")
        skill = args.pop("skill", None)
        if skill not in SKILLS:
            raise A2AError(-32005, "send one data part {\"skill\": \"verify\" | \"check-pr\" | \"find-work\", ...} or a pull request URL")
        return skill, args

    def send(self, params: dict) -> dict:
        message = params.get("message")
        if not isinstance(message, dict) or not message.get("messageId"):
            raise A2AError(-32602, "SendMessage needs a message with a messageId")
        tid, ctx = str(uuid.uuid4()), message.get("contextId") or str(uuid.uuid4())
        task = {"id": tid, "contextId": ctx, "status": {"state": "TASK_STATE_WORKING", "timestamp": _now()},
                "history": [message], "artifacts": []}
        try:
            skill, args = self._request(message)
        except A2AError as e:
            task["status"] = {"state": "TASK_STATE_REJECTED", "timestamp": _now(),
                              "message": {"messageId": str(uuid.uuid4()), "role": "ROLE_AGENT", "parts": [{"text": e.message}]}}
            self._keep(task)
            return {"task": task}
        if skill == "verify" and not self.allow_verify:
            task["status"] = {"state": "TASK_STATE_REJECTED", "timestamp": _now(),
                              "message": {"messageId": str(uuid.uuid4()), "role": "ROLE_AGENT",
                                          "parts": [{"text": "verify runs a repository's tests on this machine; this server was started without --allow-verify"}]}}
            self._keep(task)
            return {"task": task}
        try:
            got = self._call(SKILLS[skill], args)
            task["artifacts"] = [{"artifactId": str(uuid.uuid4()), "name": f"knos {skill}", "parts": [{"data": got, "mediaType": "application/json"}]}]
            task["status"] = {"state": "TASK_STATE_COMPLETED", "timestamp": _now()}
        except Exception as why:  # noqa: BLE001 - the caller gets a failed task with the reason, the server keeps running
            task["status"] = {"state": "TASK_STATE_FAILED", "timestamp": _now(),
                              "message": {"messageId": str(uuid.uuid4()), "role": "ROLE_AGENT", "parts": [{"text": str(why)}]}}
        self._keep(task)
        return {"task": task}

    def _keep(self, task: dict) -> None:
        with self._lock:
            self.tasks[task["id"]] = task

    def get(self, params: dict) -> dict:
        with self._lock:
            tid = params.get("id")
            t = self.tasks.get(tid) if isinstance(tid, str) else None
        if t is None:
            raise A2AError(-32001, f"no task {params.get('id')!r}")
        return t

    def list(self, params: dict) -> dict:
        with self._lock:
            rows = [t for t in self.tasks.values() if not params.get("contextId") or t["contextId"] == params["contextId"]]
        return {"tasks": rows, "nextPageToken": "", "pageSize": len(rows), "totalSize": len(rows)}

    def cancel(self, params: dict) -> dict:
        t = self.get(params)
        raise A2AError(-32002, f"task {t['id']} is {t['status']['state']}: a finished task cannot be cancelled")


def serve(port: int = 8765, host: str = "127.0.0.1", url: str | None = None, allow_verify: bool = False) -> ThreadingHTTPServer:
    agent = Agent(allow_verify=allow_verify)
    state: dict[str, Any] = {}

    class H(BaseHTTPRequestHandler):
        def _send(self, code: int, body: dict, ctype: str = "application/json") -> None:
            raw = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):  # noqa: N802 - the http.server name
            if self.path == CARD_PATH:
                self._send(200, state["card"])
            else:
                self._send(404, {"error": "not found"})

        def do_POST(self):  # noqa: N802
            if self.path != RPC_PATH:
                return self._send(404, {"error": "not found"})
            try:
                msg = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)))
            except ValueError:
                return self._send(200, {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}})
            self._send(200, srv.agent.handle(msg, self.headers.get("A2A-Version")), "application/a2a+json")

        def log_message(self, *_a):
            pass

    srv = ThreadingHTTPServer((host, port), H)
    state["card"] = card(url or f"http://{host}:{srv.server_address[1]}{RPC_PATH}")    # the port actually bound (0 picks one)
    srv.agent = agent      # type: ignore[attr-defined]
    return srv


def main(argv: list[str] | None = None) -> int:
    import argparse
    p = argparse.ArgumentParser(prog="knos a2a")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve", help="serve the Agent Card and the JSON-RPC endpoint")
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--url", help="the public URL of the JSON-RPC endpoint, when a proxy serves it over HTTPS")
    s.add_argument("--allow-verify", action="store_true", help="let callers run the verify skill (it runs tests on this machine)")
    c = sub.add_parser("card", help="print the Agent Card for an endpoint URL")
    c.add_argument("url")
    a = p.parse_args(argv)
    if a.cmd == "card":
        print(json.dumps(card(a.url), indent=1))
        return 0
    srv = serve(a.port, a.host, a.url, a.allow_verify)
    print(f"knos a2a: card at http://{a.host}:{a.port}{CARD_PATH}, JSON-RPC at {a.url or f'http://{a.host}:{a.port}{RPC_PATH}'}")
    srv.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
