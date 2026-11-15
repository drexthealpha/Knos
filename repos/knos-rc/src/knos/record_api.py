"""A supplier's record as a machine-priced API: pay, then the JSON (examples/record_api, docs/reference/X402.md "Record").

    knos record serve      (python -m knos.record_api) a small server anyone can run. Knos hosts none.

    GET /records/<slug>.json    the record file, free, as it always was
    GET /lookup/<slug>          0.10 test USDC a lookup, paid through the proposed x402 "knos-order" scheme
    GET /orders/<order>         how many lookups an order has bought and used
    GET /health                 whether it can answer, whether it signs, and what its operator promises (nothing)

What the paid answer adds to the free file (knos.record_answer, docs/reference/RECORD.md section 5): the operator's signature
over the record's hash, the time and slot the chain was read and an expiry (`knos record verify` checks it with no
network); a summary computed the same way for every supplier; and the supplier's history, field by field, only to a
reader the supplier granted (header Record-Grant). Without a grant the answer says "not granted". With no signing
key the answer says it is unsigned. Revenue from lookups is budgeted at zero until someone buys one.

The payment is a Knos work order, as in examples/x402_attested: the caller funds an order in escrow and names it. Two
things differ, and both come from the program as it is:

    the smallest order knos_pay takes is 5.00 (ORDER_MIN_AMOUNT), so one order buys fifty lookups (PACK), not one;
    an order's address is public, so naming it proves nothing: each call is signed by the wallet that funded the order
    over "knos-record:<order>:<n>:<slug>", where n counts that order's lookups from 0.

A call whose n was already served is a replay and is refused; so is a call another wallet signed.

WHO MAY CALL WHAT (ROUTES). Only GET; any other method is 405, any other path 404. Every route is public by design
except /lookup, which needs the payment above. Each client (its address) has a token bucket: RATE requests a second,
BURST at once (`--rate`, `--burst`); past it, 429 with Retry-After. Every input is checked before anything is read:
the path's length and characters, a slug's charset, an order's address, each header's size and its JSON's shape; a
bad one is 400 with one line saying why. With
single sign-on (`--sso CONFIG`, the self-host bundle's knos.toml with [sso]; knos.sso) the PRIVATE routes, the record
files and the order counts, also need a signed-in person (the site's session cookie; any role): else 401. No answer carries a stack trace: an unforeseen error is a 500 with one line;
`--debug` or KNOS_DEBUG=1 prints the trace to the operator's terminal, never to the caller. The server keeps the
count of each order in the memory engine (knos.proof.history's store) when it is given one, so a restart does not
sell a lookup twice. The escrow pays the server when the order's pinned judge signs an acceptance (PayOrder), or
returns everything to the caller after the deadline (RefundOrder). No judge for a lookup is built: docs/reference/X402.md says so.

Standard library at import; solders and knos.settle.v2.pay when a payment is checked.
"""
from __future__ import annotations

import base64
import json
import math
import os
import re
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable

SCHEME, X402_VERSION = "knos-order", 2
DEVNET = "solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1"       # x402's network id of Solana devnet (CAIP-2)
PRICE = 100_000                                          # 0.10 of a 6-decimal token: price book 3, the Record line
PACK = 50                                                # lookups one order buys: the smallest order is 5.00
STATE = "knos_record_api"                                # the state document the counts are kept in
PAYER_HEADER = "attested-payer"
GRANT_HEADER = "record-grant"                            # base64 JSON: the supplier's signed grant to this reader (knos.record_answer.grant)
NO_HOST = "Knos hosts no such server: whoever runs this one is its seller."
RATE, BURST = 2.0, 30                                    # each client: 2 requests a second on average, 30 at once
CLIENTS = 10_000                                         # buckets kept at most; the fullest are forgotten first
MAX_PATH, MAX_HEADER = 200, 4096                         # characters of a path; of the PAYMENT-SIGNATURE or Record-Grant header
ROUTES = (      # (path, who may call it, why): the server answers these and nothing else
    ("/records/<slug>.json", "public", "the free record file: built from public chain data and public pull requests"),
    ("/lookup/<slug>", "paid", "the signed answer: an order of this server's offer, each call signed by the wallet that funded it; "
                               "the supplier's history only to a reader the supplier granted"),
    ("/orders/<order>", "public", "how many of an order's lookups are used: the order, its funder and its amount are public on chain"),
    ("/health", "public", "whether the server can answer; no key, no RPC address"),
)
PRIVATE = ("/records/", "/orders/")                     # what --sso puts behind sign-in; /lookup keeps its payment, /health stays open
_SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_B58 = re.compile(r"[1-9A-HJ-NP-Za-km-z]+")
_PATH = re.compile(r"/[A-Za-z0-9._/-]*")


class Bad(ValueError):
    """An input the server refuses before reading anything: 400, with this one line."""


def debugging() -> bool:
    """Whether KNOS_DEBUG asks for traces (on the operator's terminal only)."""
    return os.environ.get("KNOS_DEBUG", "").strip().lower() not in ("", "0", "false", "no")


def one_line(text: object, most: int = 300) -> str:
    """A reason as one line: never a trace, never a page."""
    line = " ".join(str(text).split())
    return line if len(line) <= most else line[: most - 3] + "..."


class Limiter:
    """A token bucket per client: `rate` tokens a second, `burst` at most. `take(client)` is 0.0 when the request may
    go on, else the seconds until it may. `clock`: monotonic seconds (a test gives its own)."""

    def __init__(self, rate: float = RATE, burst: int = BURST, clock: Callable[[], float] = time.monotonic, most: int = CLIENTS):
        if not rate > 0 or int(burst) < 1:
            raise ValueError("the rate must be above 0 and the burst at least 1")
        self.rate, self.burst, self.clock, self.most = float(rate), int(burst), clock, int(most)
        self._buckets: dict[str, tuple[float, float]] = {}
        self._lock = threading.Lock()

    def take(self, client: str) -> float:
        with self._lock:
            now = self.clock()
            tokens, then = self._buckets.get(client, (float(self.burst), now))
            tokens = min(float(self.burst), tokens + (now - then) * self.rate)
            if tokens >= 1.0:
                self._buckets[client] = (tokens - 1.0, now)
                wait = 0.0
            else:
                self._buckets[client] = (tokens, now)
                wait = (1.0 - tokens) / self.rate
            if len(self._buckets) > self.most:      # a flood of new addresses forgets the clients with the most tokens left
                for gone in sorted(self._buckets, key=lambda k: -self._buckets[k][0])[: len(self._buckets) - self.most]:
                    self._buckets.pop(gone, None)
            return wait


def address(text: object) -> bool:
    """A Solana address as text: base58, 32 to 44 characters."""
    return isinstance(text, str) and 32 <= len(text) <= 44 and _B58.fullmatch(text) is not None


def slug_of(text: str) -> str:
    if len(text) > 64 or not _SLUG.fullmatch(text):
        raise Bad("a supplier's slug is lower-case letters, digits and single dashes, 64 at most")
    return text


def payment_of(header: str) -> tuple[dict, str, int, str]:
    """The PAYMENT-SIGNATURE header, checked against its schema: (the whole payment, order, n, signature)."""
    if len(header) > MAX_HEADER:
        raise Bad(f"the PAYMENT-SIGNATURE header is over {MAX_HEADER} characters")
    try:
        p = decode(header)
    except (ValueError, TypeError):
        raise Bad("the PAYMENT-SIGNATURE header is not base64 JSON") from None
    if not isinstance(p, dict) or not isinstance(p.get("payload"), dict):
        raise Bad("the PAYMENT-SIGNATURE header is not base64 JSON with payload {order, n, signature}")
    if not isinstance(p.get("x402Version"), int) or isinstance(p.get("x402Version"), bool) or not isinstance(p.get("accepted"), dict):
        raise Bad("the payment needs x402Version (a number) and accepted (the requirement it pays)")
    x = p["payload"]
    order, n, sig, tx = x.get("order"), x.get("n"), x.get("signature"), x.get("transaction", "")
    if not address(order):
        raise Bad("payload.order is not a Solana address")
    if not isinstance(n, int) or isinstance(n, bool) or not 0 <= n < 2 ** 32:
        raise Bad("payload.n is the lookup's number on the order: a whole number from 0")
    if not isinstance(sig, str) or not 64 <= len(sig) <= 88 or not _B58.fullmatch(sig):
        raise Bad("payload.signature is not a base58 signature")
    if not isinstance(tx, str) or len(tx) > 100 or (tx and not _B58.fullmatch(tx)):
        raise Bad("payload.transaction, when given, is a base58 transaction signature")
    return p, str(order), int(n), str(sig)


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
    (then the count lives as long as this object). `key`: the operator's signing key (a solders Keypair), or None:
    then every paid answer is unsigned and says so. `history`: the folder of <slug>.history.json files, never the free
    folder. `suppliers`: {slug: the supplier's public key}, the keys this operator accepts grants from. `ttl`: the
    seconds an answer stays fresh."""

    def __init__(self, off: dict, chain, records: Path, store=None, now: Callable[[], int] | None = None, *, key=None, history: Path | None = None,
                 suppliers: dict[str, str] | None = None, ttl: int | None = None, limiter: Limiter | None = None, debug: bool | None = None,
                 gate=None):
        from . import record_answer
        self.offer, self.chain, self.records, self.store = off, chain, Path(records), store
        self.limiter = limiter or Limiter()
        self.debug = debugging() if debug is None else bool(debug)
        self.now = now or chain.now
        self._used: dict[str, int] = {}
        self.key, self.history, self.suppliers = key, Path(history) if history else None, dict(suppliers or {})
        self.ttl = int(ttl if ttl is not None else off.get("ttlSeconds") or record_answer.TTL)
        self.promise = {**record_answer.PROMISE, **(off.get("availability") or {})}
        self.gate = gate                                                 # a knos.sso.Gate: PRIVATE routes need its session

    def read_chain(self) -> tuple[int, int | None]:
        """(the cluster's time, its slot) from one read of the Clock account; the slot is None where the chain gives
        only a time."""
        try:
            from .chain import CLOCK
            data = self.chain.account(CLOCK)
            if data is not None and len(data) >= 40:
                return int.from_bytes(data[32:40], "little", signed=True), int.from_bytes(data[0:8], "little")
        except Exception:  # noqa: BLE001  (a chain without that call still has a clock)
            pass
        return int(self.now()), None

    def past(self, slug: str) -> dict | None:
        from . import record_answer
        if self.history is None:
            return None
        try:
            doc = json.loads(_inside(self.history, f"{slug}.history.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return doc if record_answer.check_history(doc, slug) is None else None

    def health(self) -> dict:
        """What `knos record serve --health` and GET /health say: whether records are there, whether the chain
        answers, whether answers are signed, and what is promised."""
        try:
            n = sum(1 for p in self.records.glob("*.json") if self.record(p.stem) is not None)
        except OSError:
            n = 0
        try:
            at, slot = self.read_chain()
            chain: dict = {"ok": True, "time": at, "slot": slot}
        except Exception as why:  # noqa: BLE001  (its words can carry the RPC address, and a key in it: the operator's terminal only, with --debug)
            if self.debug:
                print(f"health: the chain did not answer: {one_line(why)}", file=sys.stderr)
            chain = {"ok": False, "why": "the chain did not answer"}
        return {"ok": bool(n) and chain["ok"], "records": n, "chain": chain, "signing": self.key is not None,
                "key": str(self.key.pubkey()) if self.key is not None else None, "ttl_seconds": self.ttl,
                "history": self.history is not None, "suppliers_with_a_key": len(self.suppliers), "counts_survive_restart": self.store is not None,
                "sign_in": self.gate is not None,
                "promise": self.promise, "note": NO_HOST}

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
            doc = json.loads(_inside(self.records, f"{name}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return doc if name == slug and record_page.check(doc) is None else None

    def handle(self, path: str, headers: dict[str, str], client: str | None = None, method: str = "GET") -> tuple[int, dict[str, str], dict]:
        """One request: (status, headers, body). `client`: the caller's address, which the rate limit counts by (None:
        a call in this process, not limited). Inputs are checked first: 400 with one line; nothing is charged for one."""
        if client is not None:
            wait = self.limiter.take(client)
            if wait > 0:
                return 429, {"Retry-After": str(max(1, math.ceil(wait)))}, {"error": f"too many requests from this client: try again in {max(1, math.ceil(wait))} s"}
        if method.upper() != "GET":
            return 405, {"Allow": "GET"}, {"error": f"{one_line(method, 20)} is not served: every route is GET"}
        if self.gate is not None and path.startswith(PRIVATE) and self.gate.who(headers) is None:
            return 401, {}, {"error": "sign in first: open /sso/login on this deployment's site", "login": "/sso/login"}
        try:
            return self._route(path, {str(k).lower(): str(v) for k, v in headers.items()})
        except Bad as why:
            return 400, {}, {"error": one_line(why)}

    def _route(self, path: str, h: dict[str, str]) -> tuple[int, dict[str, str], dict]:
        if len(path) > MAX_PATH:
            raise Bad(f"the path is over {MAX_PATH} characters")
        if "?" in path or "#" in path:
            raise Bad("this API takes no query string")
        if not _PATH.fullmatch(path):
            raise Bad("the path has characters no route has")
        if h.get(PAYER_HEADER) and not address(h[PAYER_HEADER]):
            raise Bad("the Attested-Payer header is not a Solana address")
        if len(h.get(GRANT_HEADER, "")) > MAX_HEADER:
            raise Bad(f"the Record-Grant header is over {MAX_HEADER} characters")
        if path.startswith("/records/") and path.endswith(".json"):
            doc = self.record(slug_of(path[9:-5]))
            return (200, {}, doc) if doc else (404, {}, {"error": "no such record"})
        if path == "/health":
            got = self.health()
            return (200 if got["ok"] else 503), {}, got
        if path.startswith("/orders/"):
            if not address(path[8:]):
                raise Bad("an order is named by its Solana address")
            return 200, {}, {"order": path[8:], "lookups": self.offer["lookups"], "used": self.used(path[8:]), "note": NO_HOST}
        if not path.startswith("/lookup/"):
            return 404, {}, {"error": "no such resource", "routes": [r[0] for r in ROUTES]}
        slug = slug_of(path[8:])
        doc = self.record(slug)
        if doc is None:
            return 404, {}, {"error": "no such record"}                # nothing is charged for a record that is not there

        def refuse(error: str, payer: str | None = None):
            body = payment_required(self.offer, payer, error, f"{self.offer['url']}/lookup/{slug}")
            return 402, {"PAYMENT-REQUIRED": encode(body)}, body
        proof = h.get("payment-signature")
        if not proof:
            return refuse("PAYMENT-SIGNATURE header is required", h.get(PAYER_HEADER))
        p, order, n, sig = payment_of(proof)
        payload = p["payload"]
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
        from . import record_answer
        granted: list[str] = []
        why = shown = None
        if h.get(GRANT_HEADER):
            try:
                shown = decode(h[GRANT_HEADER])
            except (ValueError, TypeError):
                shown = None
            if not isinstance(shown, dict):
                shown = None
            granted, why = record_answer.check_grant(shown, slug, payer, self.suppliers.get(slug), int(self.now()))
        read_time, slot = self.read_chain()                              # before the lookup is spent: a chain that does not answer costs the caller nothing
        self._spend(order, n)
        ans = record_answer.answer(doc, reader=payer, read_time=read_time, slot=slot, produced=int(self.now()), ttl=self.ttl, key=self.key,
                                   past=self.past(slug) if granted else None, granted=granted, why=why, grant_doc=shown, promise=self.promise)
        body = {"record": doc, "served": {"order": order, "n": n, "left": bought - n - 1, "at": int(self.now()), "record_sha256": doc["sha256"],
                                           "price": str(self.offer["price"])}, "answer": ans}
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


def _inside(folder: Path, name: str) -> Path:
    """`folder`/`name`, refused (OSError) when it is a link or resolves anywhere but directly in `folder`: one
    deployment's folder never hands out another's file."""
    p = Path(folder) / name
    if p.is_symlink() or p.resolve().parent != Path(folder).resolve():
        raise OSError(f"{name} is not a file of {folder}")
    return p


def serve(server: Server, host: str = "127.0.0.1", port: int = 8402):
    """The server on a socket (http.server). Returns the HTTPServer: call serve_forever(). One request at a time (the
    count of each order is read then written), and a connection that sends nothing for 10 s is closed."""
    import traceback
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class Handler(BaseHTTPRequestHandler):
        server_version, sys_version, timeout = "knos-record", "", 10

        def answer(self, method: str) -> None:
            status: int
            headers: dict[str, str]
            body: dict
            try:
                if int(self.headers.get("content-length") or 0) or self.headers.get("transfer-encoding"):
                    status, headers, body = 400, {}, {"error": "a request to this API carries no body"}
                else:
                    status, headers, body = server.handle(self.path, dict(self.headers.items()), client=self.client_address[0], method=method)
            except ValueError:
                status, headers, body = 400, {}, {"error": "the Content-Length header is not a number"}
            except Exception:  # noqa: BLE001  (a caller gets one line, whatever went wrong; the operator gets the trace with --debug)
                if server.debug:
                    traceback.print_exc(file=sys.stderr)
                status, headers, body = 500, {}, {"error": "the server could not answer this request (its operator can run it with --debug to see why)"}
            raw = json.dumps(body).encode()
            self.send_response(status)
            for k, v in {"content-type": "application/json", "content-length": str(len(raw)), "x-content-type-options": "nosniff",
                         "cache-control": "no-store", **headers}.items():
                self.send_header(k, v)
            self.end_headers()
            if method != "HEAD":
                self.wfile.write(raw)

        def do_GET(self):
            self.answer("GET")

        def do_POST(self):
            self.answer("POST")

        def do_PUT(self):
            self.answer("PUT")

        def do_DELETE(self):
            self.answer("DELETE")

        def do_PATCH(self):
            self.answer("PATCH")

        def do_HEAD(self):
            self.answer("HEAD")

        def do_OPTIONS(self):
            self.answer("OPTIONS")

        def log_message(self, *a):
            pass

    return HTTPServer((host, port), Handler)


def build_server(offer_file: Path | None, records: Path = Path("docs/records"), memory: Path | None = None, key: Path | None = None,
                 history: Path | None = None, suppliers: Path | None = None, ttl: int | None = None, ledger=None, *, tenant: str | None = None,
                 rate: float = RATE, burst: int = BURST, debug: bool | None = None, gate=None) -> Server:
    """The server `knos record serve` runs: the seller's offer (the JSON `offer` writes), the chain from KNOS_RPC as
    every command does. `memory`: the folder of a Sibyl store that keeps each order's count. `key`: the operator's
    signing key file. `history`: the folder of history files. `suppliers`: a JSON file {slug: supplier's public key}.
    `tenant`: whose deployment this is (the self-host bundle names it): its counts live in a tenant of their own in
    the store, so two deployments sharing a memory folder never read each other's. `rate`, `burst`: each client's
    limit. `gate`: a knos.sso.Gate (PRIVATE routes then need a signed-in person)."""
    from . import chain, record_answer
    off = json.loads(Path(offer_file).read_text(encoding="utf-8")) if offer_file else {}
    store = None
    if memory is not None:
        from .proof import history as memory_engine
        store = memory_engine.SibylStore.local(memory, tenant_id=tenant_id(tenant))
    known = json.loads(Path(suppliers).read_text(encoding="utf-8")) if suppliers else {}
    return Server(off, ledger or chain.ledger(), records, store, key=record_answer.load_key(key) if key else None, history=history,
                  suppliers={str(k): str(v) for k, v in known.items()}, ttl=ttl, limiter=Limiter(rate, burst), debug=debug, gate=gate)


def tenant_id(tenant: str | None) -> str:
    """The store's tenant for a deployment: "knos-record-api", or "knos-record-api:<tenant>"."""
    if tenant is None:
        return STATE.replace("_", "-")
    if len(tenant) > 64 or not _SLUG.fullmatch(tenant):
        raise ValueError("a tenant is lower-case letters, digits and single dashes, 64 at most")
    return f"{STATE.replace('_', '-')}:{tenant}"


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="knos record serve", description="Serve supplier records: 0.10 test USDC a lookup; the file stays free. " + NO_HOST)
    ap.add_argument("offer", type=Path, nargs="?", default=None, help="the seller's offer (knos.record_api.offer as JSON); --health works without one")
    ap.add_argument("--records", type=Path, default=Path("docs/records"))
    ap.add_argument("--memory", type=Path, default=None, help="a folder: the count of each order survives a restart")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8402)
    ap.add_argument("--key", type=Path, default=None, help="the operator's signing key (a solana-keygen file): without it every paid answer is unsigned")
    ap.add_argument("--history", type=Path, default=None, help="the folder of <slug>.history.json files (knos record history); never the free folder")
    ap.add_argument("--suppliers", type=Path, default=None, help="a JSON file {slug: the supplier's public key}: whose grants this server accepts")
    ap.add_argument("--ttl", type=int, default=None, help="seconds a signed answer stays fresh (default 3600)")
    ap.add_argument("--health", action="store_true", help="print what the server would answer at /health and stop: exit 0 when it can serve")
    ap.add_argument("--rate", type=float, default=RATE, help=f"requests a second each client may make on average (default {RATE:g}); past it, 429")
    ap.add_argument("--burst", type=int, default=BURST, help=f"requests a client may make at once (default {BURST})")
    ap.add_argument("--tenant", default=None, help="whose deployment this is: its counts are kept apart from any other's in the same --memory")
    ap.add_argument("--sso", type=Path, default=None, help="the self-host knos.toml with [sso]: the record files and order counts need a signed-in person")
    ap.add_argument("--debug", action="store_true", help="print the trace of an unforeseen error here (KNOS_DEBUG=1 does the same); callers never see one")
    a = ap.parse_args(argv)
    if a.offer is None and not a.health:
        ap.error("name the seller's offer file")
    if not a.rate > 0 or a.burst < 1:
        ap.error("--rate must be above 0 and --burst at least 1")
    debug = a.debug or debugging()
    try:
        gate = None
        if a.sso is not None:
            from . import selfhost, sso
            c = selfhost._load(a.sso)
            if c.errors:
                raise ValueError(c.errors[0])
            gate = sso.gate_of(c.config, a.sso.parent)
            if gate is None:
                raise ValueError(f"{a.sso} has no [sso] table")
        server = build_server(a.offer, a.records, a.memory, a.key, a.history, a.suppliers, a.ttl, tenant=a.tenant, rate=a.rate, burst=a.burst, debug=debug,
                              gate=gate)
        if a.health:
            got = server.health()
            print(json.dumps(got, indent=1))
            return 0 if got["ok"] else 1
        httpd = serve(server, a.host, a.port)
    except Exception as why:  # noqa: BLE001  (one line by default; the trace with --debug)
        if debug:
            raise
        print(f"knos record serve stopped: {one_line(why)}", file=sys.stderr)
        return 1
    signs = "signed answers" if a.key else "UNSIGNED answers (no --key)"
    print(f"Serving on http://{a.host}:{httpd.server_address[1]}  paid: /lookup/<slug> ({signs})  free: /records/<slug>.json  health: /health  "
          f"limit: {a.rate:g}/s, {a.burst} at once per client{'; sign-in on /records/ and /orders/' if gate else ''}. {NO_HOST}", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
