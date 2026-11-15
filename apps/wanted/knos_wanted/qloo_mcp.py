"""Knos's Qloo client: the nine canonical Qloo workflows over MCP, through Qloo's own local server.

    Python service  --MCP stdio (JSON-RPC lines)-->  `qloo mcp`                       (live: Direct)
    Python service  --JSON lines-->  bridge/qloo_bridge.mjs (official MCP SDK 1.30.1)  --MCP stdio-->  MOCK server

Live, the service speaks MCP to Qloo's server itself, as qloo_harness does to `qloo api mcp`: the Node bridge and the
server it started were two Node processes of about 100 MB each on a free instance of 512 MB (24 Oct 2026). The bridge
(the exact SDK Qloo's starter pins) still runs the MOCK server. This flow does not use `qloo api` (raw endpoints; the
decision check does, qloo_harness.py): the nine workflows cover every question this MCP flow asks
(docs/reference/DEMAND_CHECK.md, "How Knos reaches Qloo (MCP flow, optional)"). The demand check (check.py) asks
through qloo_rest.py instead.

Mode, decided once at start and shown on every answer:
  live  `qloo mcp` started and `qloo_capabilities` says `adapter.ready: true` (a credential is configured on the
        server: `qloo setup --qloo`, or QLOO_API_KEY in the server's environment);
  mock  otherwise, or KNOS_WANTED_MOCK=1: Knos's MOCK server (knos_wanted.mock_mcp), labelled MOCK everywhere. It
        runs through the same bridge and SDK when Node and the SDK are installed, else in process.

Rules kept here (Qloo kit docs/API_ACCESS.md and docs/SAFE_USE.md):
  - the key never leaves the server process environment: it is not read, logged, cached or returned here;
  - every argument passes knos_wanted.privacy before it is sent (no personal data to Qloo);
  - bounded retries: only when the envelope says `error.retryable`, at most RETRIES more times, with backoff;
  - minimal cache: live `ok`/`empty` answers only, 15 minutes, at most CACHE_MAX files, under .cache/ (git-ignored);
    MOCK answers are never cached and nothing Qloo returns is ever written into the repository.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

from . import mock_mcp, privacy

APP = Path(__file__).resolve().parents[1]
BRIDGE = APP / "bridge" / "qloo_bridge.mjs"
SDK = APP / "bridge" / "node_modules" / "@modelcontextprotocol" / "sdk"
MOCK_LABEL = mock_mcp.MOCK_LABEL
LIVE_LABEL = "LIVE Qloo data via qloo mcp (fetched for this request, cached privately on the server for 15 minutes, never stored in the repository)"
AGGREGATE = "aggregate taste, not a prediction about one person"
WORKFLOWS = ("qloo_find_tags", "qloo_describe", "qloo_audience_demographics", "qloo_entity_tags", "qloo_where_popular",
             "qloo_trends", "qloo_compare_audiences", "qloo_rank", "qloo_recommend")
RETRIES = 2
BACKOFF_S = (0.5, 1.5)
CACHE_TTL_S = 15 * 60
CACHE_MAX = 200
TIMEOUT_S = 90.0


class QlooUnavailable(RuntimeError):
    pass


# ---- transports -------------------------------------------------------------------------------------------------
class InProcess:
    """MOCK only: Knos's MOCK server called in this process (no Node needed)."""
    name = "in-process MOCK server"

    def __init__(self, fail: str | None = None):
        self.state = {"fail": mock_mcp.fail_plan(fail if fail is not None else os.environ.get("KNOS_WANTED_MOCK_FAIL"))}
        self.n = 0

    def init(self) -> dict:
        tools = mock_mcp.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, self.state)["result"]["tools"]
        return {"server": {"name": mock_mcp.SERVER_NAME, "version": "0.1.0"}, "tools": [t["name"] for t in tools],
                "capabilities": mock_mcp.call("qloo_capabilities", {})}

    def call(self, name: str, arguments: dict) -> dict:
        self.n += 1
        got = mock_mcp.handle({"jsonrpc": "2.0", "id": self.n, "method": "tools/call", "params": {"name": name, "arguments": arguments}},
                              self.state)["result"]
        return {"structuredContent": got["structuredContent"], "isError": got["isError"]}

    def close(self) -> None:
        pass


class Bridge:
    """The Node sidecar (official MCP SDK) in front of `qloo mcp`, or in front of the MOCK server (mock=True)."""

    def __init__(self, mock: bool = False, node: str | None = None, timeout: float = TIMEOUT_S, extra_env: dict | None = None):
        self.mock, self.timeout = mock, timeout
        self.node = node or shutil.which("node") or "node"
        self.name = "qloo mcp via the official MCP SDK" if not mock else "MOCK MCP server via the official MCP SDK"
        env = dict(os.environ)
        if mock:
            env["QLOO_MCP_COMMAND"] = sys.executable
            env["QLOO_MCP_ARGS_JSON"] = json.dumps(["-m", "knos_wanted.mock_mcp"])
            env["PYTHONPATH"] = os.pathsep.join([str(APP)] + [p for p in env.get("PYTHONPATH", "").split(os.pathsep) if p])
            env.pop("QLOO_API_KEY", None)          # the MOCK server never needs it
        elif env.get("QLOO_BASE_URL") and not env.get("QLOO_TRUSTED_BASE_URL"):
            # qloo-harness 0.1.26 exits at startup when QLOO_BASE_URL is set without QLOO_TRUSTED_BASE_URL matching it
            # (measured 17 Oct 2026): the harness trusts only endpoints it is told to trust, so tell it.
            env["QLOO_TRUSTED_BASE_URL"] = env["QLOO_BASE_URL"]
        env.update(extra_env or {})
        self._env = env
        self._p: subprocess.Popen | None = None
        self._id = 0
        self._lock = threading.Lock()

    @staticmethod
    def available() -> str | None:
        """None when the bridge can run; else why not (one sentence)."""
        if not shutil.which("node"):
            return "Node.js is not installed (the Qloo harness needs Node 22.19+)"
        if not SDK.is_dir():
            return "the MCP SDK is not installed beside the bridge (sh apps/wanted/bridge/install.sh)"
        return None

    def _start(self) -> None:
        self._p = subprocess.Popen([self.node, str(BRIDGE)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                   env=self._env, text=True, encoding="utf-8", bufsize=1, cwd=str(APP))

    def _ask(self, msg: dict) -> dict:
        with self._lock:
            if self._p is None or self._p.poll() is not None:
                self._start()
            self._id += 1
            msg = {**msg, "id": self._id}
            assert self._p and self._p.stdin and self._p.stdout
            self._p.stdin.write(json.dumps(msg) + "\n")
            self._p.stdin.flush()
            deadline = time.monotonic() + self.timeout
            out: list[dict] = []

            def read():
                line = self._p.stdout.readline() if self._p and self._p.stdout else ""
                out.append(json.loads(line) if line.strip() else {"id": msg["id"], "ok": False, "error": "the bridge stopped"})
            t = threading.Thread(target=read, daemon=True)
            t.start()
            t.join(max(0.1, deadline - time.monotonic()))
            if not out:
                self.close()
                raise QlooUnavailable(f"no answer from the Qloo MCP bridge in {self.timeout:.0f} s")
            got = out[0]
            if not got.get("ok"):
                raise QlooUnavailable(str(got.get("error", "bridge error"))[:300])
            return got

    def init(self) -> dict:
        got = self._ask({"op": "init"})
        return {"server": got.get("server") or {}, "tools": got.get("tools") or [], "capabilities": got.get("capabilities") or {}}

    def call(self, name: str, arguments: dict) -> dict:
        got = self._ask({"op": "call", "name": name, "arguments": arguments})
        return {"structuredContent": got.get("structuredContent"), "isError": got.get("isError", False)}

    def close(self) -> None:
        p, self._p = self._p, None
        if p and p.poll() is None:
            try:
                p.stdin.close() if p.stdin else None
                p.wait(timeout=5)
            except Exception:  # noqa: BLE001
                p.kill()


class Direct:
    """`qloo mcp` spoken to over stdio from this process (MCP JSON-RPC lines, as qloo_harness speaks to `qloo api mcp`):
    no Node bridge in between. The bridge and the server it started were two Node processes of about 100 MB each on a
    free instance of 512 MB, which ran out of memory under load on 24 Oct 2026."""
    name = "qloo mcp over stdio"

    def __init__(self, timeout: float = TIMEOUT_S, command: list[str] | None = None, env: dict | None = None):
        from . import qloo_harness
        q = (shutil.which("qloo.cmd") if os.name == "nt" else None) or shutil.which("qloo")
        if not (command or q):
            raise QlooUnavailable("the qloo command is not installed (npm install --global @qloo/qloo-harness)")
        self.h = qloo_harness.Harness(command=command or [q, "mcp"], env=env, call_s=timeout)

    def _rpc(self, method: str, params: dict) -> dict:
        try:
            self.h._ensure()
            got = self.h._wait(self.h._send(method, params)) or {}
        except (OSError, ValueError, TimeoutError, AssertionError) as why:
            raise QlooUnavailable(f"qloo mcp: {type(why).__name__}: {str(why)[:200]}") from None
        if got.get("error"):
            raise QlooUnavailable(str(got["error"].get("message") if isinstance(got["error"], dict) else got["error"])[:300])
        return got.get("result") or {}

    def init(self) -> dict:
        tools = [t.get("name") for t in self._rpc("tools/list", {}).get("tools") or []]
        cap = self._rpc("tools/call", {"name": "qloo_capabilities", "arguments": {}}).get("structuredContent")
        return {"server": self.h.server_info, "tools": tools, "capabilities": cap or {}}

    def call(self, name: str, arguments: dict) -> dict:
        r = self._rpc("tools/call", {"name": name, "arguments": arguments})
        return {"structuredContent": r.get("structuredContent"), "isError": r.get("isError", False)}

    def close(self) -> None:
        self.h.stop(self.h.proc)                    # the whole process group: `qloo` and the server it started


# ---- the client --------------------------------------------------------------------------------------------------
class Qloo:
    def __init__(self, transport=None, *, mode: str | None = None, reason: str = "", cache_dir: str | os.PathLike | None = None,
                 sleep=time.sleep, now=time.time):
        self._sleep, self._now = sleep, now
        self.cache_dir = Path(cache_dir or os.environ.get("KNOS_WANTED_CACHE") or ".cache/qloo-mcp")
        self.reason = reason
        if transport is None:
            transport, mode, self.reason = self._choose()
        self.t = transport
        info = self.t.init()
        self.server = info["server"]
        self.tools = info["tools"]
        self.capabilities = info["capabilities"] or {}
        self.mode = mode or ("mock" if self.server.get("name") == mock_mcp.SERVER_NAME else "live")
        missing = [w for w in WORKFLOWS if w not in self.tools]
        if missing:
            raise QlooUnavailable(f"the MCP server does not list {', '.join(missing)}")
        self.calls = 0

    @staticmethod
    def _choose():
        """live when qloo mcp is ready; else the MOCK server (through the bridge when it can run)."""
        why_not = Bridge.available()
        if os.environ.get("KNOS_WANTED_MOCK") == "1":
            return (Bridge(mock=True) if why_not is None else InProcess()), "mock", "KNOS_WANTED_MOCK=1"
        if shutil.which("qloo"):
            b = Direct()                                # live: Qloo's own server, no Node bridge in front of it
            try:
                info = b.init()
                ready = bool(((info.get("capabilities") or {}).get("adapter") or {}).get("ready"))
                if ready:
                    return b, "live", "qloo mcp ready (qloo_capabilities: adapter.ready true)"
                b.close()
                return (Bridge(mock=True) if why_not is None else InProcess()), "mock", "qloo mcp started but has no Qloo credential (qloo_capabilities: adapter.ready false)"
            except QlooUnavailable as why:
                b.close()
                return (Bridge(mock=True) if why_not is None else InProcess()), "mock", f"qloo mcp did not start: {why}"
        if why_not is None:
            return Bridge(mock=True), "mock", "the qloo command is not installed (npm install --global @qloo/qloo-harness)"
        return InProcess(), "mock", why_not

    @property
    def live(self) -> bool:
        return self.mode == "live"

    @property
    def label(self) -> str:
        return LIVE_LABEL if self.live else MOCK_LABEL

    def status(self) -> dict:
        adapter = self.capabilities.get("adapter") or {}
        return {"mode": self.mode, "label": self.label, "reason": self.reason, "transport": self.t.name,
                "server": self.server, "tools": self.tools, "ready": bool(adapter.get("ready")),
                "contract_version": self.capabilities.get("contract_version"),
                "contract_checksum": self.capabilities.get("contract_checksum"), "aggregate": AGGREGATE}

    # -- cache (live only) --------------------------------------------------------------------------------------
    def _key(self, tool: str, args: dict) -> Path:
        return self.cache_dir / (hashlib.sha256(json.dumps([tool, args], sort_keys=True).encode()).hexdigest() + ".json")

    def _cached(self, tool: str, args: dict) -> dict | None:
        if not self.live:
            return None
        p = self._key(tool, args)
        try:
            if self._now() - p.stat().st_mtime > CACHE_TTL_S:
                p.unlink(missing_ok=True)
                return None
            return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def _store(self, tool: str, args: dict, env: dict) -> None:
        if not self.live or env.get("status") not in ("ok", "empty"):
            return
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            files = sorted(self.cache_dir.glob("*.json"), key=lambda f: f.stat().st_mtime)
            for f in files[: max(0, len(files) - CACHE_MAX + 1)]:
                f.unlink(missing_ok=True)
            p = self._key(tool, args)
            tmp = p.with_suffix(".tmp")
            tmp.write_text(json.dumps(env), encoding="utf-8")
            os.replace(tmp, p)
        except OSError:
            pass

    # -- one call ----------------------------------------------------------------------------------------------
    def call(self, tool: str, args: dict, *, why: str, trail: list | None = None, step: str = "") -> dict:
        """The envelope of one workflow call (status ok/empty/needs_input/partial/degraded/error), with one trail
        entry appended: which tool, the request as sent (no key, no personal data), why, and what came back."""
        if tool not in WORKFLOWS:
            raise ValueError(f"not a Qloo workflow tool: {tool}")
        privacy.check(args, tool)
        entry = {"step": step or tool, "tool": tool, "why": why, "request": args, "mode": self.mode}
        env = self._cached(tool, args)
        attempts, cached = 0, env is not None
        while env is None:
            attempts += 1
            try:
                got = self.t.call(tool, args)
                env = got.get("structuredContent") or {"status": "error", "summary": "empty answer from the MCP server",
                                                       "error": {"code": "UNKNOWN", "retryable": False, "recovery": ""}}
            except QlooUnavailable as why_down:
                env = {"status": "error", "summary": str(why_down), "error": {"code": "TRANSPORT", "retryable": attempts == 1,
                                                                               "recovery": "restart the bridge"}}
            err = env.get("error") or {}
            if env.get("status") == "error" and err.get("retryable") and attempts <= RETRIES:
                self._sleep(BACKOFF_S[min(attempts - 1, len(BACKOFF_S) - 1)])
                env = None
                continue
            self._store(tool, args, env)
        self.calls += 0 if cached else attempts
        entry.update(status=env.get("status"), summary=env.get("summary", ""), result_count=env.get("result_count"),
                     attempts=attempts, cached=cached, correlation_id=(env.get("execution") or {}).get("correlation_id"),
                     endpoint=(env.get("provenance") or {}).get("endpoint"),
                     error=(env.get("error") or {}).get("code") if env.get("status") == "error" else None)
        if not self.live:
            entry["label"] = MOCK_LABEL
        if trail is not None:
            trail.append(entry)
        return env

    def close(self) -> None:
        self.t.close()


# ---- reading envelopes ------------------------------------------------------------------------------------------
def candidates(env: dict) -> list[dict]:
    """The choices to show the user: needs_input candidates, or the resolved entity and its alternatives."""
    out: list[dict] = []
    for issue in ((env.get("resolution") or {}).get("issues") or []):
        for c in issue.get("candidates") or []:
            if isinstance(c, dict) and c.get("id"):
                out.append({"id": c["id"], "name": c.get("name", c["id"]), "type": c.get("type"), "input": issue.get("input"),
                            "description": c.get("description")})
    if env.get("status") in ("ok", "partial", "degraded"):
        for o in ((env.get("resolution") or {}).get("outcomes") or []):
            for c in ([o.get("selected")] if o.get("selected") else []) + (o.get("alternatives") or []) + (o.get("candidates") or []):
                if isinstance(c, dict) and c.get("id") and c["id"] not in {x["id"] for x in out}:
                    out.append({"id": c["id"], "name": c.get("name", c["id"]), "type": c.get("type"), "input": o.get("input")})
        for r in env.get("results") or []:
            rid = r.get("entity_id") or r.get("id") if isinstance(r, dict) else None
            if rid and rid not in {x["id"] for x in out}:
                out.append({"id": rid, "name": r.get("name", rid), "type": r.get("type")})
    return out


def results(env: dict | None) -> list:
    if not env or env.get("status") not in ("ok", "partial", "degraded"):
        return []
    r = env.get("results")
    if isinstance(r, dict):
        r = r.get("entities") or r.get("tags") or []
    return r if isinstance(r, list) else []


def num(v) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


class Lazy:
    """The MCP flow's client, started at its first use: `qloo mcp` is a Node process of about 120 MB, and a demand check
    never asks it (the crossing agent, the MCP proxy and the guided flows do). Under MOCK it starts at once (in process,
    cheap). Until it has started, status() says so."""

    IDLE_S = 600.0              # stopped after this long unused, started again at the next call

    def __init__(self, factory=None):
        self._factory = factory or Qloo
        self._q: Qloo | None = None
        self._lock = threading.Lock()
        self._used = 0.0
        self._timer: threading.Thread | None = None
        if os.environ.get("KNOS_WANTED_MOCK") == "1":
            self._get()

    def _get(self) -> Qloo:
        with self._lock:
            self._used = time.monotonic()
            if self._q is None:
                self._q = self._factory()
                if os.environ.get("KNOS_WANTED_MOCK") != "1" and (self._timer is None or not self._timer.is_alive()):
                    self._timer = threading.Thread(target=self._watch, daemon=True, name="qloo-mcp-idle")
                    self._timer.start()
            return self._q

    def _watch(self) -> None:
        while True:
            time.sleep(60)
            if self._q is not None and time.monotonic() - self._used > self.IDLE_S:
                self.idle()
                return

    def idle(self) -> None:
        """Stop `qloo mcp` now (its 120 MB back to the instance); the next call starts it again."""
        with self._lock:
            q, self._q = self._q, None
        if q is not None:
            q.close()

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return getattr(self._get(), name)

    def status(self) -> dict:
        if self._q is None:
            return {"mode": "not started", "label": "qloo mcp starts at the first MCP call", "aggregate": AGGREGATE,
                    "reason": "the MCP flow's server is started when an agent first asks it; a demand check does not"}
        return self._q.status()

    def close(self) -> None:
        if self._q is not None:
            self._q.close()
