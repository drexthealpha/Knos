"""A JSON-RPC endpoint that lags the real one by 2-5 slots, for the claim protocol's property test.

Reads that carry a context (getProgramAccounts with withContext, getAccountInfo) are answered from a cache that may
be up to `lag` slots old, as a lagging RPC node would. A read asking for `minContextSlot` beyond what this node has
"reached" (real slot minus lag) gets the standard -32016 error, exactly as a real node answers. Everything else is
forwarded unchanged.
"""

from __future__ import annotations

import json
import random
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LAGGED = {"getProgramAccounts", "getAccountInfo", "getMultipleAccounts"}


class LagProxy:
    def __init__(self, upstream: str, lag: tuple[int, int] = (2, 5), seed: int = 0):
        self.upstream, self.lag, self.rng = upstream, lag, random.Random(seed)
        self.cache: dict[str, tuple[int, dict]] = {}
        self.lock = threading.Lock()
        self.stale_served = 0
        self.min_context_refused = 0
        proxy = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):  # quiet
                pass

            def do_POST(self):
                body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                out = proxy.handle(json.loads(body))
                raw = json.dumps(out).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()

    def _forward(self, req: dict) -> dict:
        r = urllib.request.Request(self.upstream, data=json.dumps(req).encode(),
                                   headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(r, timeout=30) as resp:
            return json.loads(resp.read())

    def _slot(self) -> int:
        return self._forward({"jsonrpc": "2.0", "id": 1, "method": "getSlot",
                              "params": [{"commitment": "confirmed"}]})["result"]

    def handle(self, req: dict) -> dict:
        method = req.get("method")
        if method not in LAGGED:
            return self._forward(req)
        params = json.loads(json.dumps(req.get("params") or []))
        cfg = params[-1] if params and isinstance(params[-1], dict) else {}
        want = cfg.pop("minContextSlot", None)
        key = json.dumps([method, params], sort_keys=True)
        with self.lock:
            lag = self.rng.randint(*self.lag)
        reached = self._slot() - lag
        if want is not None and want > reached:
            self.min_context_refused += 1
            return {"jsonrpc": "2.0", "id": req.get("id"),
                    "error": {"code": -32016, "message": "Minimum context slot has not been reached",
                              "data": {"contextSlot": reached}}}
        with self.lock:
            hit = self.cache.get(key)
        if hit is not None and hit[0] >= reached and (want is None or hit[0] >= want):
            self.stale_served += 1
            return {**hit[1], "id": req.get("id")}
        fresh = self._forward({**req, "params": params})
        ctx = ((fresh.get("result") or {}).get("context") or {}).get("slot")
        if ctx is not None:
            with self.lock:
                self.cache[key] = (int(ctx), fresh)
        return fresh
