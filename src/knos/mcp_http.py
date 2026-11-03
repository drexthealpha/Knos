"""`knos mcp --http [HOST:]PORT`: the same server as `knos mcp`, over MCP's Streamable HTTP transport, for a host that
connects by URL (Hermes Agent's `mcp_servers: {knos: {url: ...}}`, for one).

What it implements of the transport (MCP specification, "Transports", Streamable HTTP):
    POST <path>   one JSON-RPC message or a batch; a request is answered with `Content-Type: application/json`,
                  a notification or a response with 202 Accepted and no body
    GET  <path>   405: this server never opens a server-to-client stream
    anything else 404 / 405
It keeps no session (every tool is stateless), so it sends no Mcp-Session-Id.

Safety: it binds to 127.0.0.1 unless told otherwise, and refuses to start on any other address unless
KNOS_MCP_HTTP_TOKEN is set; with the token set it refuses a request without `Authorization: Bearer <that>`. Without
the token, the tools that run code on this machine (knos_verify) are not served. It refuses a request whose Origin
header is not a loopback origin (DNS rebinding), and a body over 1 MB.
"""

from __future__ import annotations

import hmac
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

MOST = 1_000_000
LOOPBACK = ("127.0.0.1", "localhost", "::1", "[::1]")


def _origin_ok(origin: str | None) -> bool:
    if not origin:
        return True             # not a browser: nothing to rebind
    host = urlsplit(origin).hostname or ""
    return host in LOOPBACK


def handler_for(server, path: str = "/mcp", token: str | None = None):
    """A request handler class answering MCP on `path` with the knos.mcp.Server `server`."""

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "knos-mcp"

        def log_message(self, fmt, *args):  # noqa: D401 - quiet: stdout is not ours to write on
            pass

        def _send(self, code: int, body: bytes = b"", kind: str = "application/json") -> None:
            self.send_response(code)
            if body:
                self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if body:
                self.wfile.write(body)

        def _allowed(self) -> bool:
            if urlsplit(self.path).path != path:
                self._send(404, b'{"error":"not found"}')
                return False
            if not _origin_ok(self.headers.get("Origin")):
                self._send(403, b'{"error":"origin not allowed"}')
                return False
            if token and not hmac.compare_digest(self.headers.get("Authorization", ""), f"Bearer {token}"):
                self._send(401, b'{"error":"unauthorized"}')
                return False
            return True

        def do_GET(self):  # noqa: N802 - http.server's naming
            if self._allowed():
                self.send_response(405)
                self.send_header("Allow", "POST")
                self.send_header("Content-Length", "0")
                self.end_headers()

        do_DELETE = do_GET

        def do_POST(self):  # noqa: N802
            if not self._allowed():
                return
            try:
                size = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                size = -1
            if size < 0 or size > MOST:
                self._send(413, b'{"error":"body too large"}')
                return
            raw = self.rfile.read(size).decode("utf-8", errors="replace")
            reply = server.line(raw)
            if reply is None:
                self._send(202)
            else:
                self._send(200, json.dumps(reply, separators=(",", ":")).encode("utf-8"))

    return Handler


def parse_address(text: str) -> tuple[str, int]:
    host, _, port = text.rpartition(":")
    return (host.strip("[]") or "127.0.0.1"), int(port)


class Refused(ValueError):
    """The server will not start as asked (one sentence)."""


def make(address: str = "127.0.0.1:8808", path: str = "/mcp", server=None) -> ThreadingHTTPServer:
    """The HTTP server. Without KNOS_MCP_HTTP_TOKEN it binds to loopback only, and the tools that run code on this
    machine (knos_verify) are not served at all: any local process could otherwise make it run a command."""
    from .mcp import GAME_TOOLS, RUNS_CODE, TOOLS, Server
    host, port = parse_address(address)
    token = os.environ.get("KNOS_MCP_HTTP_TOKEN") or None
    if token is None and host not in LOOPBACK:
        raise Refused(f"knos mcp --http {address}: a non-loopback address needs KNOS_MCP_HTTP_TOKEN (a long random string) set first.")
    srv = server or Server()
    if token is None:
        # every tool that runs code here (knos_verify, the game's knos_game_submit) is neither listed nor answered
        srv.hidden = frozenset(t["name"] for t in TOOLS + GAME_TOOLS if (t.get("_meta") or {}).get(RUNS_CODE))
        for name in srv.hidden:
            srv._tools.pop(name, None)
    return ThreadingHTTPServer((host, port), handler_for(srv, path, token))


def main(address: str = "127.0.0.1:8808", path: str = "/mcp") -> int:
    try:
        httpd = make(address, path)
    except Refused as why:
        print(str(why), file=sys.stderr)
        return 2
    host, port = httpd.server_address[:2]
    host = host.decode() if isinstance(host, bytes) else host
    print(f"knos mcp: Streamable HTTP on http://{host}:{port}{path}", file=sys.stderr)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0
