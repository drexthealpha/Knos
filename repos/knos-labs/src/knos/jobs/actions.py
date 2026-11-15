"""Solana Actions (Blinks) for Knos jobs: hire an agent, or accept or reject its work, from any wallet or link.

    GET  /actions.json                       maps https://<host>/jobs/** to this API
    GET  /api/jobs/post                      the "hire an agent" card: task, price
    POST /api/jobs/post?task=…&price=…       {account} -> the post transaction, signed only by that buyer
    GET  /api/jobs/<id>/review               the job, with Accept and Reject buttons
    POST /api/jobs/<id>/accept | /reject     {account} -> that transaction (the escrow checks it is the buyer)

Spec: solana.com/docs/advanced/actions (read 1 Oct 2026). Every response carries CORS and X-Action-Version /
X-Blockchain-Ids. The server never holds a key and never signs: it builds a transaction the wallet shows and the
buyer signs. The escrow program, not this server, decides who can move money.
"""

from __future__ import annotations

import base64
import json
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from solders.hash import Hash
from solders.message import MessageV0
from solders.pubkey import Pubkey
from solders.signature import Signature
from solders.transaction import VersionedTransaction

from . import market, sol

UNITS = 1_000_000
ACTION_VERSION = "2.4"
CHAIN_IDS = {"devnet": "solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1", "mainnet": "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp",
             "localnet": "solana:localnet"}
MAX_TASK = 2000
CORS = {"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Methods": "GET,POST,PUT,OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type, Authorization, Content-Encoding, Accept-Encoding",
        "Access-Control-Expose-Headers": "X-Action-Version, X-Blockchain-Ids"}


class ActionError(Exception):
    pass


def _price(text: str, cap_units: int | None) -> int:
    try:
        units = round(float(text) * UNITS)
    except (TypeError, ValueError):
        raise ActionError("Price must be a number of USDC.") from None
    if units <= 0:
        raise ActionError("Price must be more than zero.")
    if units < sol.MIN_JOB_UNITS:
        raise ActionError(f"The minimum job is {sol.MIN_JOB_UNITS / UNITS:g} USDC.")
    if cap_units and units > cap_units:
        raise ActionError(f"Jobs are capped at {cap_units / UNITS:.0f} USDC until the escrow's external audit.")
    return units


def _account(body: dict) -> Pubkey:
    try:
        return Pubkey.from_string(str(body.get("account", "")))
    except ValueError:
        raise ActionError("account must be a base58 public key") from None


def unsigned(ixs, payer: Pubkey, blockhash: Hash) -> str:
    msg = MessageV0.try_compile(payer, ixs, [], blockhash)
    tx = VersionedTransaction.populate(msg, [Signature.default()] * msg.header.num_required_signatures)
    return base64.b64encode(bytes(tx)).decode()


class Actions:
    """The logic, separate from HTTP, so tests and the web app can call it directly."""

    def __init__(self, ledger, relay, cluster: str = "devnet", cap_units: int | None = None, icon: str = ""):
        self.ledger, self.relay, self.cluster = ledger, relay, cluster
        self.cap_units, self.icon = cap_units, icon

    def rules(self) -> dict:
        return {"rules": [{"pathPattern": "/jobs/**", "apiPath": "/api/jobs/**"}]}

    def post_card(self, base: str) -> dict:
        return {"type": "action", "icon": self.icon or f"{base}/icon.svg", "title": "Hire an AI agent",
                "description": "Describe the work and set a price. The price waits in escrow; an agent does the job; "
                               "you pay only if you accept it, and get it all back if nobody delivers.",
                "label": "Post job",
                "links": {"actions": [{"type": "transaction", "label": "Post job",
                                       "href": "/api/jobs/post?task={task}&price={price}",
                                       "parameters": [{"name": "task", "label": "What should the agent do?",
                                                       "type": "textarea", "required": True},
                                                      {"name": "price", "label": "Price in USDC", "type": "number",
                                                       "required": True, "min": sol.MIN_JOB_UNITS / UNITS}]}]}}

    def post_tx(self, query: dict, body: dict) -> dict:
        buyer = _account(body)
        task = (query.get("task") or [""])[0].strip()
        if not task or len(task) > MAX_TASK:
            raise ActionError(f"Describe the task in 1 to {MAX_TASK} characters.")
        units = _price((query.get("price") or [""])[0], self.cap_units)
        cfg = self.ledger.config()
        title = task.splitlines()[0][:80]
        seal_to = str(body.get("seal_to") or (query.get("seal_to") or [""])[0])
        if seal_to and not (len(seal_to) == 64 and all(c in "0123456789abcdef" for c in seal_to)):
            raise ActionError("seal_to must be a 32-byte hex key")
        kind = (query.get("kind") or ["text"])[0]
        if kind not in market.KINDS:
            raise ActionError("kind must be one of " + ", ".join(market.KINDS))
        brief = market.Brief(title, task, kind=kind, buyer=str(buyer), price_units=units, seal_to=seal_to or None)
        jid = market.new_job_id()
        brief.job_id = jid.hex()
        import time
        brief.created = int(time.time())
        h = self.relay.put_brief(brief.encode())
        ix = sol.post(self.ledger.program, buyer, jid, units, 3600, 86_400, bytes.fromhex(h),
                      market.token_account_for(self.ledger, buyer, cfg["mint"]),
                      market.vault_for(self.ledger, cfg["mint"]))
        return {"type": "transaction", "transaction": unsigned([ix], buyer, self.ledger.blockhash()),
                "message": f"Job {jid.hex()[:10]}: {units / UNITS:g} USDC goes into escrow. You pay only if you accept."}

    def review_card(self, base: str, job_hex: str) -> dict:
        j = market.job(self.ledger, bytes.fromhex(job_hex))
        if j is None:
            raise ActionError("No such job.")
        title = "a job"
        try:
            title = market.Brief.decode(self.relay.get_brief(j.brief.hex())).title
        except Exception:  # noqa: BLE001
            pass
        card = {"type": "action", "icon": self.icon or f"{base}/icon.svg", "title": f"Review: {title}",
                "description": f"{j.amount / UNITS:g} USDC in escrow, {j.state}. Accept pays the agent now; reject "
                               "inside the review window refunds you.", "label": "Review"}
        if j.state != "delivered":
            card["disabled"] = True
            card["label"] = "Nothing to review yet" if j.state in ("open", "claimed") else j.state.capitalize()
            return card
        card["links"] = {"actions": [{"type": "transaction", "label": "Accept and pay",
                                      "href": f"/api/jobs/{job_hex}/accept"},
                                     {"type": "transaction", "label": "Reject",
                                      "href": f"/api/jobs/{job_hex}/reject"}]}
        return card

    def settle_tx(self, job_hex: str, verb: str, body: dict) -> dict:
        who = _account(body)
        jid = bytes.fromhex(job_hex)
        j = market.job(self.ledger, jid)
        if j is None or j.state != "delivered":
            raise ActionError("This job has nothing to accept or reject.")
        if j.buyer != who:
            raise ActionError("Only the buyer can do this.")
        cfg = self.ledger.config()
        vault = market.vault_for(self.ledger, cfg["mint"])
        if verb == "accept":
            pre = []
            if getattr(self.ledger, "env", None) is None:
                from ..pro import sol_budget as sb
                pre = [sb.create_ata_idempotent(who, j.worker, cfg["mint"])]
            ixs = pre + [sol.accept(self.ledger.program, who, jid, vault,
                                    market.token_account_for(self.ledger, j.worker, cfg["mint"]), cfg["fee_token"])]
            msg = f"Pay the agent {(j.amount - sol.fee_for(j.amount)) / UNITS:g} USDC (Knos fee: 2.5%, at least 0.05)."
        else:
            ixs = [sol.reject(self.ledger.program, who, jid, vault,
                              market.token_account_for(self.ledger, who, cfg["mint"]))]
            msg = f"Refund {j.amount / UNITS:g} USDC to you."
        return {"type": "transaction", "transaction": unsigned(ixs, who, self.ledger.blockhash()), "message": msg}


def serve(actions: Actions, host: str = "127.0.0.1", port: int = 8788, static_dir=None, relay_dir=None,
          extra=None, gas=None):
    """One server for a public demo: Actions, an optional relay (/briefs, /deliveries), an optional static web app,
    and `extra(path) -> dict | None` for read-only JSON the web app needs."""
    from pathlib import Path
    from .relay import MAX, DirRelay, RelayError
    store = DirRelay(relay_dir) if relay_dir else None

    class H(BaseHTTPRequestHandler):
        def _send(self, code: int, body, kind: str = "application/json") -> None:
            raw = body if isinstance(body, bytes) else json.dumps(body).encode()
            self.send_response(code)
            for k, v in CORS.items():
                self.send_header(k, v)
            self.send_header("X-Action-Version", ACTION_VERSION)
            self.send_header("X-Blockchain-Ids", CHAIN_IDS.get(actions.cluster, ""))
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def _base(self) -> str:
            proto = self.headers.get("X-Forwarded-Proto") or "http"
            return f"{proto}://{self.headers.get('Host', f'{host}:{port}')}"

        def do_OPTIONS(self):  # noqa: N802
            self._send(200, {})

        def do_PUT(self):  # noqa: N802
            n = int(self.headers.get("Content-Length") or 0)
            if store is None or n <= 0 or n > MAX or self.path not in ("/briefs", "/deliveries"):
                return self._send(400, {"error": "bad request"})
            data = self.rfile.read(n)
            h = store.put_brief(data) if self.path == "/briefs" else store.put_delivery(data)
            self._send(200, {"hash": h})

        def do_GET(self):  # noqa: N802
            path = urllib.parse.urlparse(self.path).path.rstrip("/") or "/"
            parts = path.strip("/").split("/")
            if store is not None and len(parts) == 2 and parts[0] in ("briefs", "deliveries"):
                try:
                    data = store.get_brief(parts[1]) if parts[0] == "briefs" else store.get_delivery(parts[1])
                except RelayError:
                    return self._send(404, {"error": "not found"})
                return self._send(200, data, "application/octet-stream")
            if extra is not None and parts[0] == "api" and parts[1:2] == ["network"]:
                try:
                    got = extra(path)
                except Exception as why:  # noqa: BLE001
                    return self._send(502, {"message": f"{type(why).__name__}: {why}"})
                if got is not None:
                    return self._send(200, got)
            try:
                if path == "/actions.json":
                    return self._send(200, actions.rules())
                if path == "/api/jobs/post":
                    return self._send(200, actions.post_card(self._base()))
                parts = path.strip("/").split("/")
                if len(parts) == 4 and parts[:2] == ["api", "jobs"] and parts[3] == "review":
                    return self._send(200, actions.review_card(self._base(), parts[2]))
            except (ActionError, ValueError) as why:
                return self._send(400, {"message": str(why)})
            if static_dir:
                f = (Path(static_dir) / (path.lstrip("/") or "index.html")).resolve()
                if f.is_dir():
                    f = f / "index.html"
                if Path(static_dir).resolve() in f.parents and f.exists():
                    kind = {".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".png": "image/png",
                            ".svg": "image/svg+xml", ".json": "application/json"}.get(f.suffix, "application/octet-stream")
                    return self._send(200, f.read_bytes(), kind)
            self._send(404, {"message": "not found"})

        def do_POST(self):  # noqa: N802
            u = urllib.parse.urlparse(self.path)
            try:
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n) or b"{}") if 0 < n < 10_000 else {}
                parts = u.path.strip("/").split("/")
                if u.path.rstrip("/") == "/gas":
                    # devnet gas for a passkey wallet's throwaway key (knos.jobs.gas; 503 without --gas-key)
                    from .gas import GasError
                    if gas is None:
                        return self._send(503, {"message": "this server has no gas key"})
                    ip = (self.headers.get("X-Forwarded-For") or self.client_address[0]).split(",")[0].strip()
                    try:
                        return self._send(200, gas.top_up(body, ip))
                    except GasError as why:
                        return self._send(why.code, {"message": str(why)})
                if u.path.rstrip("/") == "/api/jobs/post":
                    return self._send(200, actions.post_tx(urllib.parse.parse_qs(u.query), body))
                if len(parts) == 4 and parts[:2] == ["api", "jobs"] and parts[3] in ("accept", "reject"):
                    return self._send(200, actions.settle_tx(parts[2], parts[3], body))
            except (ActionError, ValueError, LookupError) as why:
                return self._send(400, {"message": str(why)})
            self._send(404, {"message": "not found"})

        def log_message(self, *a):
            pass

    return ThreadingHTTPServer((host, port), H)
