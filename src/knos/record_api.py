"""A supplier's record as a machine-priced API: pay, then the JSON (examples/record_api, docs/X402.md "Record").

    knos record serve      (python -m knos.record_api) a small server anyone can run. Knos hosts none.

    GET /records/<slug>.json    the record file, free, as it always was
    GET /lookup/<slug>          0.10 test USDC a lookup, paid through the proposed x402 "knos-order" scheme
    GET /orders/<order>         how many lookups an order has bought and used

The payment is a Knos work order, as in examples/x402_attested: the caller funds an order in escrow and names it. Two
things differ, and both come from the program as it is:

    the smallest order knos_pay takes is 5.00 (ORDER_MIN_AMOUNT), so one order buys fifty lookups (PACK), not one;
    an order's address is public, so naming it proves nothing: each call is signed by the wallet that funded the order
    over "knos-record:<order>:<n>:<slug>", where n counts that order's lookups from 0.

A call whose n was already served is a replay and is refused; so is a call another wallet signed. The server keeps the
count of each order in the memory engine (knos.proof.history's store) when it is given one, so a restart does not
sell a lookup twice. The escrow pays the server when the order's pinned judge signs an acceptance (PayOrder), or
returns everything to the caller after the deadline (RefundOrder). No judge for a lookup is built: docs/X402.md says so.

Standard library at import; solders and knos.settle.v2.pay when a payment is checked.
"""
from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any, Callable

SCHEME, X402_VERSION = "knos-order", 2
DEVNET = "solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1"       # x402's network id of Solana devnet (CAIP-2)
PRICE = 100_000                                          # 0.10 of a 6-decimal token: price book 3, the Record line
PACK = 50                                                # lookups one order buys: the smallest order is 5.00
STATE = "knos_record_api"                                # the state document the counts are kept in
PAYER_HEADER = "attested-payer"
NO_HOST = "Knos hosts no such server: whoever runs this one is its seller."


def encode(obj) -> str:
    return base64.b64encode(json.dumps(obj, separators=(",", ":")).encode()).decode()


def decode(text: str):
    return json.loads(base64.b64decode(text).decode("utf-8"))


def call_message(order: str, n: int, slug: str) -> bytes:
    """What the funding wallet signs for its n-th lookup (from 0) on `order`."""
    return f"knos-record:{order}:{int(n)}:{slug}".encode()


def offer(seller_wallet: str, seller_id: int, mint: str, repo_id: int, issue: int, wf_repo: str, wf_sha: str, terms: str, *,
          url: str = "http://127.0.0.1:8402", work_seconds: int = 7 * 86_400, seq: int = 0, mode: int = 0, program: str | None = None,
          network: str = DEVNET, fee_version: int | None = None, margin_seconds: int = 3600) -> dict:
    """What the server sells and under which order: a pack of PACK lookups for PACK * PRICE."""
    from .settle.v2 import pay
    return {"url": url.rstrip("/"), "network": network, "program": program or str(pay.PAY_ID), "mint": mint, "amount": PACK * PRICE, "price": PRICE,
            "lookups": PACK, "workSeconds": int(work_seconds), "repoId": int(repo_id), "issue": int(issue), "seq": int(seq), "mode": int(mode),
            "terms": terms, "wfRepo": wf_repo, "wfSha": wf_sha, "seller": {"githubId": int(seller_id), "wallet": seller_wallet},
            "feeVersion": fee_version, "marginSeconds": int(margin_seconds)}


def order_address(off: dict, payer: str) -> str:
    from solders.pubkey import Pubkey
    from .settle.v2 import pay
    return str(pay.order_pda(pay.scope_of(off["repoId"], off["issue"]), Pubkey.from_string(payer), off["seq"], Pubkey.from_string(off["program"])))


def requirement(off: dict, payer: str | None = None) -> dict:
    """The PaymentRequirements entry, in the shape examples/x402_attested/attested.mjs gives, with the pack beside it."""
    from . import fees
    from .settle.v2 import pay
    return {"scheme": SCHEME, "network": off["network"], "amount": str(off["amount"]), "asset": off["mint"], "payTo": off["seller"]["wallet"],
            "maxTimeoutSeconds": off["workSeconds"],
            "extra": {"program": off["program"], "order": order_address(off, payer) if payer else None, "repoId": str(off["repoId"]),
                      "issue": str(off["issue"]), "seq": off["seq"], "mode": off["mode"], "terms": off["terms"],
                      "termsHash": pay.terms_hash(off["terms"].encode()).hex(), "workflows": {"repository": off["wfRepo"], "sha": off["wfSha"]},
                      "fee": str(fees.rule(off["feeVersion"]).order(off["amount"]) if off.get("feeVersion") is not None else fees.rule().order(off["amount"])),
                      "payee": {"githubId": str(off["seller"]["githubId"])},
                      "record": {"price": str(off["price"]), "lookups": off["lookups"], "sign": "knos-record:<order>:<n>:<slug>", "free": "/records/<slug>.json"}}}


def payment_required(off: dict, payer: str | None, error: str, resource: str) -> dict:
    return {"x402Version": X402_VERSION, "error": error,
            "resource": {"url": resource, "description": "a supplier's delivery record (knos.supplier-record/1)", "mimeType": "application/json"},
            "accepts": [requirement(off, payer)],
            "extensions": {SCHEME: {"info": {"version": 1, "proposal": True, "settles": "on-acceptance", "refund": "after-deadline",
                                             "payerHeader": "Attested-Payer"}}}}


def verify(chain, off: dict, order: str) -> tuple[Any, str | None]:
    """The order a caller names: it exists, is knos_pay's, and is the one this server's requirement asks for, with time
    left. Returns (the order, None) or (None, why). `chain`: infos([address]) -> [(owner, data) | None], now()."""
    from solders.pubkey import Pubkey
    from .settle.v2 import pay
    try:
        at = Pubkey.from_string(order)
    except (ValueError, TypeError):
        return None, "the payment names no order"
    got = chain.infos([at])[0]
    if got is None:
        return None, f"there is no order at {order}: fund it first (FundOrderWallet), or it was already paid out or refunded"
    if str(got[0]) != off["program"]:
        return None, f"{order} is not an account of {off['program']}"
    o = pay.read_order(got[1])
    if o is None:
        return None, f"{order} is not a work order"
    scope = pay.scope_of(off["repoId"], off["issue"])
    if o.scope != scope or pay.order_pda(o.scope, o.source, o.seq, Pubkey.from_string(off["program"])) != at:
        return None, "the order is for another resource than this server sells"
    if o.state != "open":
        return None, "the order is not open"
    if o.amount < off["amount"]:
        return None, f"the order holds {o.amount} for its payees and a pack costs {off['amount']}"
    if str(o.mint) != off["mint"]:
        return None, f"the order is in mint {o.mint}, not {off['mint']}"
    if o.terms != pay.terms_hash(off["terms"].encode()) or o.mode != off["mode"]:
        return None, "the order's terms are not the ones this server offers"
    if o.wf_repo_hash != pay.wf_repo_hash(off["wfRepo"]) or o.wf_sha != off["wfSha"]:
        return None, "the order pins other workflows as its judge"
    if o.flags & (pay.F_PRIVATE | pay.F_STANDING) or o.holdback_bps:
        return None, "the order is private, standing or holds part back: a pack is sold for a plain order"
    if o.deadline < chain.now() + off["marginSeconds"]:
        return None, "the order's deadline leaves too little time"
    return o, None


class Server:
    """The record server, with no socket: `handle(path, headers)` gives (status, headers, body). `records`: the folder
    of record files (docs/records). `store`: a knos.proof.history store that remembers each order's count, or None
    (then the count lives as long as this object)."""

    def __init__(self, off: dict, chain, records: Path, store=None, now: Callable[[], int] | None = None):
        self.offer, self.chain, self.records, self.store = off, chain, Path(records), store
        self.now = now or chain.now
        self._used: dict[str, int] = {}

    def used(self, order: str) -> int:
        if self.store is not None:
            return int(self.store.state(STATE).get(order, 0))
        return self._used.get(order, 0)

    def _spend(self, order: str, n: int) -> None:
        if self.store is not None:
            self.store.set_state(STATE, {**self.store.state(STATE), order: n + 1})
        self._used[order] = n + 1

    def record(self, slug: str) -> dict | None:
        from . import record_page
        try:
            name = record_page.slug(slug)
            doc = json.loads((self.records / f"{name}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return doc if name == slug and record_page.check(doc) is None else None

    def handle(self, path: str, headers: dict[str, str]) -> tuple[int, dict[str, str], dict]:
        h = {k.lower(): v for k, v in headers.items()}
        path = path.split("?")[0]
        if path.startswith("/records/") and path.endswith(".json"):
            doc = self.record(path[9:-5])
            return (200, {}, doc) if doc else (404, {}, {"error": "no such record"})
        if path.startswith("/orders/"):
            return 200, {}, {"order": path[8:], "lookups": self.offer["lookups"], "used": self.used(path[8:]), "note": NO_HOST}
        if not path.startswith("/lookup/"):
            return 404, {}, {"error": "no such resource", "paid": "/lookup/<slug>", "free": "/records/<slug>.json"}
        slug = path[8:]
        doc = self.record(slug)
        if doc is None:
            return 404, {}, {"error": "no such record"}                # nothing is charged for a record that is not there

        def refuse(error: str, payer: str | None = None):
            body = payment_required(self.offer, payer, error, f"{self.offer['url']}/lookup/{slug}")
            return 402, {"PAYMENT-REQUIRED": encode(body)}, body
        proof = h.get("payment-signature")
        if not proof:
            return refuse("PAYMENT-SIGNATURE header is required", h.get(PAYER_HEADER))
        try:
            p = decode(proof)
            payload = p["payload"]
            order, n, sig = str(payload["order"]), int(payload["n"]), str(payload["signature"])
        except (ValueError, KeyError, TypeError):
            return refuse("the PAYMENT-SIGNATURE header is not base64 JSON with payload {order, n, signature}")
        o, why = verify(self.chain, self.offer, order)
        if o is None:
            return refuse(str(why))
        payer = str(o.source)
        from solders.pubkey import Pubkey
        from solders.signature import Signature
        try:
            signed = Signature.from_string(sig).verify(Pubkey.from_string(payer), call_message(order, n, slug))
        except (ValueError, TypeError):
            signed = False
        if not signed:
            return refuse("the call is not signed by the wallet that funded the order", payer)
        if p.get("x402Version") != X402_VERSION or p.get("accepted") not in (requirement(self.offer, payer), requirement(self.offer)):
            return refuse("the accepted requirement is not the one this server offers", payer)
        used, bought = self.used(order), min(self.offer["lookups"], o.amount // self.offer["price"])
        if n < used:
            return refuse(f"this payment was already used: lookup {n} of this order was served. Sign lookup {used}", payer)
        if n != used:
            return refuse(f"the next lookup of this order is {used}, not {n}", payer)
        if used >= bought:
            return refuse(f"this order bought {bought} lookups and all are used: fund another (a new seq)", payer)
        self._spend(order, n)
        body = {"record": doc, "served": {"order": order, "n": n, "left": bought - n - 1, "at": int(self.now()), "record_sha256": doc["sha256"],
                                           "price": str(self.offer["price"])}}
        settle = {"success": True, "payer": payer, "transaction": str(payload.get("transaction") or ""), "network": self.offer["network"],
                  "amount": str(self.offer["price"]),
                  "extensions": {SCHEME: {"info": {"order": order, "state": "escrowed", "deadline": o.deadline}}}}
        return 200, {"PAYMENT-RESPONSE": encode(settle)}, body


def lookup(ask: Callable[[str, dict[str, str]], tuple[int, dict[str, str], dict]], slug: str, wallet, fund: Callable[[dict], str], *,
           max_amount: int, mints: tuple[str, ...], programs: tuple[str, ...] | None = None, order: str | None = None, n: int = 0) -> dict:
    """A caller's side, for an agent: ask, read the 402, check it against its own limits, fund the order (`fund(req)`
    sends FundOrderWallet and returns the transaction) unless `order` is one it funded before, sign the call, ask
    again. `wallet`: a solders Keypair. `ask(path, headers)`: the transport. Returns {status, body, order, n}."""
    from . import fees
    from .settle.v2 import pay
    me = str(wallet.pubkey())
    status, headers, body = ask(f"/lookup/{slug}", {"Attested-Payer": me})
    if status != 402:
        return {"status": status, "body": body, "order": None, "n": None}
    req = next((a for a in decode(headers["PAYMENT-REQUIRED"])["accepts"] if a["scheme"] == SCHEME), None)
    if req is None:
        raise ValueError(f"the server offers no {SCHEME} payment")
    x = req["extra"]
    # never trust the server's arithmetic: the order is ours to derive, the terms ours to hash, the price ours to cap
    if x["program"] not in (programs or (str(pay.PAY_ID),)):
        raise ValueError(f"refusing to fund an order of {x['program']}: not a program this caller knows")
    if req["asset"] not in mints:
        raise ValueError(f"refusing to pay in mint {req['asset']}")
    if int(req["amount"]) > int(max_amount):
        raise ValueError(f"the price {req['amount']} is over this caller's limit {max_amount}")
    if x["termsHash"] != pay.terms_hash(x["terms"].encode()).hex():
        raise ValueError("the terms hash is not the hash of the terms")
    if int(x["fee"]) not in {fees.rule(v).order(int(req["amount"])) for v in (fees.NEW_VERSION, fees.NEW_VERSION - 1)}:
        raise ValueError("the fee is not knos_pay's fee for this amount")
    mine = order_address({"repoId": int(x["repoId"]), "issue": int(x["issue"]), "seq": x["seq"], "program": x["program"]}, me)
    if x["order"] not in (None, mine):
        raise ValueError("the order the server names is not the one this wallet's funding creates")
    tx = "" if order else fund(req)
    order = order or mine
    payment = {"x402Version": X402_VERSION, "accepted": req,
               "payload": {"order": order, "n": n, "signature": str(wallet.sign_message(call_message(order, n, slug))), "transaction": tx}}
    status, headers, body = ask(f"/lookup/{slug}", {"PAYMENT-SIGNATURE": encode(payment)})
    return {"status": status, "body": body, "order": order, "n": n, "payment": payment}


def serve(server: Server, host: str = "127.0.0.1", port: int = 8402):
    """The server on a socket (http.server). Returns the HTTPServer: call serve_forever()."""
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            try:
                status, headers, body = server.handle(self.path, dict(self.headers.items()))
            except Exception as why:  # noqa: BLE001  (a caller gets an answer, whatever went wrong)
                status, headers, body = 500, {}, {"error": str(why)}
            raw = json.dumps(body).encode()
            self.send_response(status)
            for k, v in {"content-type": "application/json", "content-length": str(len(raw)), **headers}.items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, *a):
            pass

    return HTTPServer((host, port), Handler)


def run_serve(offer_file: Path, records: Path = Path("docs/records"), memory: Path | None = None, host: str = "127.0.0.1", port: int = 8402):
    """What `knos record serve` does: read the seller's offer (the JSON `offer` writes), the chain from KNOS_RPC as
    every command does, and serve. `memory`: the folder of a Sibyl store that keeps each order's count."""
    from . import chain
    off = json.loads(Path(offer_file).read_text(encoding="utf-8"))
    store = None
    if memory is not None:
        from .proof import history
        store = history.SibylStore.local(memory, tenant_id="knos-record-api")
    return serve(Server(off, chain.ledger(), records, store), host, port)


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="knos record serve", description="Serve supplier records: 0.10 test USDC a lookup; the file stays free. " + NO_HOST)
    ap.add_argument("offer", type=Path, help="the seller's offer (knos.record_api.offer as JSON)")
    ap.add_argument("--records", type=Path, default=Path("docs/records"))
    ap.add_argument("--memory", type=Path, default=None, help="a folder: the count of each order survives a restart")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8402)
    a = ap.parse_args(argv)
    httpd = run_serve(a.offer, a.records, a.memory, a.host, a.port)
    print(f"Serving on http://{a.host}:{httpd.server_address[1]}  paid: /lookup/<slug>  free: /records/<slug>.json. {NO_HOST}", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
