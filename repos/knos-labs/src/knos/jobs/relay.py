"""Briefs and sealed deliverables, off chain and checked against the chain.

The chain holds only hashes: the brief's sha256 in the job account, the sealed deliverable's sha256 as the job's
result. Both are content-addressed, so nobody can overwrite anyone's.
The bytes themselves live on a relay: a directory (one machine, tests) or an HTTP relay anyone can run
(`knos jobs relay`). A relay cannot forge a brief or a delivery (every read is checked against its hash) and never
touches money. Deliverables are sealed to the buyer's key, so a relay cannot read them either.
"""

from __future__ import annotations

import hashlib
import json
import re
import urllib.request
from pathlib import Path

_HEX = re.compile(r"^[0-9a-f]{64}$")


class RelayError(Exception):
    pass


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


class DirRelay:
    def __init__(self, root: Path):
        self.root = Path(root)
        (self.root / "briefs").mkdir(parents=True, exist_ok=True)
        (self.root / "deliveries").mkdir(parents=True, exist_ok=True)

    def put_brief(self, data: bytes) -> str:
        h = sha(data)
        (self.root / "briefs" / h).write_bytes(data)
        return h

    def get_brief(self, h: str) -> bytes:
        if not _HEX.match(h):
            raise RelayError("bad hash")
        p = self.root / "briefs" / h
        if not p.exists():
            raise RelayError("brief not on this relay")
        data = p.read_bytes()
        if sha(data) != h:
            raise RelayError("brief does not match its hash")
        return data

    def put_delivery(self, data: bytes) -> str:
        h = sha(data)
        (self.root / "deliveries" / h).write_bytes(data)
        return h

    def get_delivery(self, h: str) -> bytes:
        p = self.root / "deliveries" / h
        if not _HEX.match(h) or not p.exists():
            raise RelayError("no delivery on this relay")
        return p.read_bytes()


class HttpRelay:
    def __init__(self, url: str, timeout: float = 15.0):
        self.url, self.timeout = url.rstrip("/"), timeout

    def _req(self, method: str, path: str, body: bytes | None = None) -> bytes:
        req = urllib.request.Request(self.url + path, data=body, method=method,
                                     headers={"Content-Type": "application/octet-stream", "User-Agent": "knos"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:  # noqa: S310 - the chosen relay
                return r.read()
        except OSError as e:
            raise RelayError(f"relay {self.url}: {e}") from None

    def put_brief(self, data: bytes) -> str:
        got = json.loads(self._req("PUT", "/briefs", data))
        if got.get("hash") != sha(data):
            raise RelayError("relay stored something else")
        return got["hash"]

    def get_brief(self, h: str) -> bytes:
        data = self._req("GET", f"/briefs/{h}")
        if sha(data) != h:
            raise RelayError("brief does not match its hash")
        return data

    def put_delivery(self, data: bytes) -> str:
        got = json.loads(self._req("PUT", "/deliveries", data))
        if got.get("hash") != sha(data):
            raise RelayError("relay stored something else")
        return got["hash"]

    def get_delivery(self, h: str) -> bytes:
        return self._req("GET", f"/deliveries/{h}")


def open_relay(where: str | Path):
    s = str(where)
    return HttpRelay(s) if s.startswith(("http://", "https://")) else DirRelay(Path(s))


MAX = 2_000_000


def serve(root: Path, host: str = "127.0.0.1", port: int = 8787):
    """`knos jobs relay`: a relay anyone can run. It stores bytes by their sha256 and nothing else."""
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    store = DirRelay(root)

    class H(BaseHTTPRequestHandler):
        def _send(self, code: int, body: bytes, kind: str = "application/json") -> None:
            self.send_response(code)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)

        def do_OPTIONS(self):  # noqa: N802
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, PUT, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.end_headers()

        def do_PUT(self):  # noqa: N802
            n = int(self.headers.get("Content-Length") or 0)
            if n <= 0 or n > MAX or self.path not in ("/briefs", "/deliveries"):
                return self._send(400, b'{"error":"bad request"}')
            data = self.rfile.read(n)
            h = store.put_brief(data) if self.path == "/briefs" else store.put_delivery(data)
            self._send(200, json.dumps({"hash": h}).encode())

        def do_GET(self):  # noqa: N802
            parts = self.path.strip("/").split("/")
            if parts == ["health"]:
                return self._send(200, b'{"ok":true}')
            if len(parts) != 2 or parts[0] not in ("briefs", "deliveries"):
                return self._send(404, b'{"error":"not found"}')
            try:
                data = store.get_brief(parts[1]) if parts[0] == "briefs" else store.get_delivery(parts[1])
            except RelayError:
                return self._send(404, b'{"error":"not found"}')
            self._send(200, data, "application/octet-stream")

        def log_message(self, *a):
            pass

    return ThreadingHTTPServer((host, port), H)
