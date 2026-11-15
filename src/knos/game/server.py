"""The game for players: one static page + a small JSON API, Python standard library only (the server style of
apps/wanted/knos_wanted/server.py). People play here; agents use the same API, the MCP tools or `knos game`.

    knos game serve DIR            (HOST, default 127.0.0.1; PORT, default 8090)

    GET  /api/state                the goal, rules, board, pot, verdicts (never the sealed data or a hidden score)
    GET  /api/board                the leaderboard
    GET  /api/baseline             the editable file's baseline (text)
    GET  /api/data?which=train|val the public rows (CSV)
    POST /api/join     {name, payee?, github_id? | orcid? | pubkey+signature?}  -> {player, key}   (kind "human"; agents
                       say kind "agent"); one player per identity and per payee; a player with no identity is never paid
    POST /api/submit   {player, key, file}               -> the referee's answer
    POST /api/mine     {player, key}                     -> your attempts

No login: a player's key is its secret (shown once). Rate limits per client address. The referee runs submitted code
on this machine (see knos.game.engine LIMIT): keep the default loopback address unless the judge runs isolated.
"""
from __future__ import annotations

import json
import os
import threading
import time
from collections import defaultdict, deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .. import version
from .engine import Game, GameError

STATIC = Path(__file__).parent / "static"
MAX_BODY = 220_000
LIMITS = {"join": (5, 3600), "submit": (12, 600), "read": (240, 600)}     # (calls, seconds) per client address
FILES = {"/": ("index.html", "text/html; charset=utf-8"), "/index.html": ("index.html", "text/html; charset=utf-8"),
         "/static/game.js": ("game.js", "text/javascript; charset=utf-8"), "/static/game.css": ("game.css", "text/css; charset=utf-8")}


class Limiter:
    def __init__(self):
        self.hits: dict[tuple[str, str], deque] = defaultdict(deque)
        self.lock = threading.Lock()

    def allow(self, client: str, kind: str) -> bool:
        n, window = LIMITS[kind]
        now = time.monotonic()
        with self.lock:
            d = self.hits[(client, kind)]
            while d and now - d[0] > window:
                d.popleft()
            if len(d) >= n:
                return False
            d.append(now)
            return True


def make_handler(game: Game, limiter: Limiter | None = None):
    lim = limiter or Limiter()

    class H(BaseHTTPRequestHandler):
        server_version = f"knos-game/{version()}"

        def log_message(self, fmt, *args):  # no request logging: keys travel in bodies, never in URLs
            pass

        def _client(self) -> str:
            fwd = self.headers.get("X-Forwarded-For", "") if os.environ.get("KNOS_GAME_TRUST_PROXY") == "1" else ""
            return (fwd.split(",")[0].strip() or self.client_address[0])[:64]

        def _send(self, code: int, body, ctype: str = "application/json") -> None:
            data = body if isinstance(body, bytes) else (body.encode() if isinstance(body, str) else json.dumps(body, default=str).encode())
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            u = urlparse(self.path)
            if u.path in FILES:
                name, ctype = FILES[u.path]
                return self._send(200, (STATIC / name).read_bytes(), ctype)
            if not lim.allow(self._client(), "read"):
                return self._send(429, {"error": "too many requests from this address; try again in a few minutes"})
            try:
                if u.path == "/api/state":
                    return self._send(200, game.public())
                if u.path == "/api/board":
                    return self._send(200, {"board": game.board(), "round": game.s["round"], "status": game.s["status"]})
                if u.path == "/api/baseline":
                    return self._send(200, game.baseline(), "text/plain; charset=utf-8")
                if u.path == "/api/data":
                    which = (parse_qs(u.query).get("which") or [""])[0]
                    return self._send(200, game.public_data(which), "text/csv; charset=utf-8")
                if u.path == "/healthz":
                    return self._send(200, {"ok": True})
            except GameError as why:
                return self._send(400, {"error": str(why)})
            return self._send(404, {"error": "not found"})

        def do_POST(self):
            u = urlparse(self.path)
            kind = {"/api/join": "join", "/api/submit": "submit", "/api/mine": "read"}.get(u.path)
            if kind is None:
                return self._send(404, {"error": "not found"})
            if not lim.allow(self._client(), kind):
                return self._send(429, {"error": "too many requests from this address; try again in a few minutes"})
            try:
                n = int(self.headers.get("Content-Length") or 0)
                if n > MAX_BODY:
                    raise GameError("request too large")
                body = json.loads(self.rfile.read(n) or b"{}")
                if not isinstance(body, dict):
                    raise GameError("send a JSON object")
                if kind == "join":
                    k = body.get("kind", "human")
                    gid = body.get("github_id")
                    return self._send(200, game.join(str(body.get("name", "")), kind=k if k in ("human", "agent") else "human",
                                                     label=str(body.get("label", ""))[:80], payee=body.get("payee") or None,
                                                     github_id=int(gid) if isinstance(gid, (int, str)) and str(gid).isdigit() else None,
                                                     orcid=body.get("orcid") or None, pubkey=body.get("pubkey") or None,
                                                     signature=body.get("signature") or None))
                pid = str(body.get("player", ""))
                game.check_key(pid, body.get("key"))
                if kind == "submit":
                    f = body.get("file")
                    if not isinstance(f, str) or not f.strip():
                        raise GameError("file: the whole editable file, as text")
                    return self._send(200, game.submit(pid, {game.task.editable: f}))
                return self._send(200, {"attempts": game.history(pid)})
            except (GameError, ValueError, TypeError) as why:
                return self._send(400, {"error": str(why)[:300]})

    return H


def serve(root, host: str | None = None, port: int | None = None) -> None:
    host = host or os.environ.get("HOST", "127.0.0.1")
    port = port or int(os.environ.get("PORT", "8090"))
    g = Game.open(root)
    httpd = ThreadingHTTPServer((host, port), make_handler(g))
    print(f"Knos game {g.s['id']} on http://{host}:{port}")
    httpd.serve_forever()
