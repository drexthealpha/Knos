"""The x402 endpoint for graduation, pre-orders and paid checks (devnet test USDC), on the proposed "knos-order"
scheme of docs/reference/X402.md and the plumbing of knos.record_api (headers, limits, the socket): nothing forked.

    python -m knos.money.x402 --plans PLANS.json --offer OFFER.json [--port 8403]     (anyone runs it; Knos hosts none)

    GET /health             whether it answers; what it sells
    GET /fees               the fee schedule (config/fees.yaml, with each line's status), free
    GET /pool/<claim>       a graduated claim's pre-order pool as the chain has it now, free
    GET /preorder/<claim>   402 Payment Required: fund a pre-order in the claim's pool (a private knos_pay order in the
                            pool's scope). Asked again with PAYMENT-SIGNATURE naming the order: 200 "held" once the
                            chain shows it open, in that pool, on those terms, in that mint, with time left.
    GET /checks             402: a pack of paid checks at the config's x402_check price (the smallest order is 5.00, so
                            one order buys a pack). Each call after that is signed by the wallet that funded the order
                            over "knos-check:<order>:<n>", n counting from 0; a replay or another wallet's call is refused.
                            With --exact-asset/--pay-to it also accepts the standard x402 `exact` scheme for ONE check at
                            that price, settled by a public facilitator (knos.money.x402_exact; x402.org's needs no key),
                            and every 402 carries the Bazaar discovery extension so agents can find and call it.

The money never reaches this server: it sits in the order's own token account until the judge pays it, or goes back
to the payer after the deadline. `PAYMENT-RESPONSE` says "held". Standard library at import; solders when a
payment is checked.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from .. import record_api as ra
from . import fees_config

SCHEME, X402_VERSION, DEVNET = ra.SCHEME, ra.X402_VERSION, ra.DEVNET
ROUTES = ("/health", "/fees", "/pool/<claim>", "/preorder/<claim>", "/checks")
_CLAIM = re.compile(r"[A-Za-z0-9._-]{1,120}")
MARGIN = 3600                                            # a pre-order must have at least this long left (seconds), as record_api asks
NO_HOST = "Knos hosts no such server: whoever runs this one is its operator."


def check_message(order: str, n: int) -> bytes:
    return f"knos-check:{order}:{int(n)}".encode()


def pack(cfg: fees_config.FeeConfig) -> tuple[int, int]:
    """(checks in one pack, the pack's price): as many checks as the smallest order buys at the x402_check price."""
    from ..settle.v2 import pay
    each = fees_config.micro(cfg.doc["fees"]["x402_check"]["usd_each"])
    n = -(-pay.ORDER_MIN_AMOUNT // each)
    return n, n * each


class Server:
    """No socket: `handle(path, headers, client=, method=)` -> (status, headers, body). `plans`: {claim id: the plan
    knos.graduation.plan returned}; `offer`: what /checks sells, in knos.record_api.offer's shape (its amount is
    replaced by the pack's price); `mint`: the mint pre-orders are taken in; `chain`: infos, now, program_accounts.
    `state`: the JSON file that keeps how many checks each order has used, written before a paid call is answered, so a
    restart never sells a call twice; required with an offer."""

    def __init__(self, plans: dict[str, dict], chain, mint: str, offer: dict | None = None, cfg: fees_config.FeeConfig | None = None,
                 limiter: ra.Limiter | None = None, debug: bool = False, state: str | Path | None = None, exact: dict | None = None):
        """`exact`: {asset, pay_to, decimals, facilitator (x402_exact.Facilitator), confirm (sig -> waits)}: one check
        paid by the standard `exact` scheme at the x402_check price, beside the pack."""
        self.cfg = cfg or fees_config.load()
        self.plans, self.chain, self.mint, self.debug = dict(plans), chain, mint, debug
        self.limiter = limiter or ra.Limiter()
        self.checks, price = pack(self.cfg)
        self.offer = {**offer, "amount": price, "price": price // self.checks, "lookups": self.checks} if offer else None
        self.exact = dict(exact) if exact else None
        self._fee_payer: str | None = None
        if (self.offer or self.exact) and state is None:
            raise ValueError("paid checks need a state file: the count of each order must survive a restart")
        self.state = Path(state) if state is not None else None
        self._used: dict[str, int] = self._load()

    def _load(self) -> dict[str, int]:
        if self.state is None or not self.state.exists():
            return {}
        got = json.loads(self.state.read_text(encoding="utf-8"))
        if not isinstance(got, dict) or not all(isinstance(k, str) and isinstance(v, int) and v >= 0 for k, v in got.items()):
            raise ValueError(f"{self.state}: not a JSON object of order -> count")
        return got

    def _save(self) -> None:
        assert self.state is not None
        tmp = self.state.with_name(self.state.name + ".tmp")
        tmp.parent.mkdir(parents=True, exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._used, f, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.state)

    # -- routes ------------------------------------------------------------------------------------------------------
    def handle(self, path: str, headers: dict[str, str], client: str = "", method: str = "GET") -> tuple[int, dict, dict]:
        h = {k.lower(): v for k, v in headers.items()}
        if method not in ("GET", "HEAD"):
            return 405, {"allow": "GET"}, {"error": "only GET"}
        wait = self.limiter.take(client or "-")
        if wait:
            return 429, {"retry-after": str(int(wait) + 1)}, {"error": "too many requests"}
        path = path.split("?", 1)[0]
        if len(path) > ra.MAX_PATH or not ra._PATH.fullmatch(path):
            return 400, {}, {"error": "a path is letters, digits and ./_- only"}
        try:
            if path == "/health":
                return 200, {}, {"ok": True, "routes": list(ROUTES), "claims": sorted(self.plans), "checks": bool(self.offer), "host": NO_HOST,
                                 "network": DEVNET, "revenue": "test money on devnet: 0"}
            if path == "/fees":
                return 200, {}, self.cfg.public()
            parts = path.strip("/").split("/")
            if len(parts) == 2 and parts[0] in ("pool", "preorder"):
                claim = parts[1]
                if not _CLAIM.fullmatch(claim) or claim not in self.plans:
                    return 404, {}, {"error": f"no graduated claim {claim!r} on this server"}
                p = self.plans[claim]
                if parts[0] == "pool":
                    from .. import graduation
                    return 200, {}, {"claim": claim, "pool": graduation.pool(self.chain, p, self.mint), "spec_hash": p["spec_hash"]}
                return self._preorder(claim, p, h, path)
            if path == "/checks" and (self.offer or self.exact):
                return self._checks(h, path)
        except ra.Bad as why:
            return 400, {}, {"error": str(why)}
        return 404, {}, {"error": "no such route"}

    # -- pre-orders ------------------------------------------------------------------------------------------------------
    def requirement(self, claim: str, p: dict, payer: str | None) -> dict:
        from solders.pubkey import Pubkey
        from .. import graduation
        from ..settle.v2 import pay
        amount = pay.ORDER_MIN_AMOUNT
        return {"scheme": SCHEME, "network": DEVNET, "amount": str(amount), "asset": self.mint, "payTo": None,
                "maxTimeoutSeconds": p["pool"]["work_s"],
                "extra": {"program": p["program"], "order": str(graduation.address(p, "pool", Pubkey.from_string(payer))) if payer else None,
                          "private": True, "scope": p["pool"]["scope"], "options": p["options"], "repoId": "0", "issue": "0", "seq": 0,
                          "mode": p["mode"], "terms": p["pool"]["terms"], "termsHash": p["pool"]["terms_hash"],
                          "workflows": {"repository": p["wf_repo"], "sha": p["wf_sha"]}, "judgeRepoId": str(p["repo_id"]),
                          "fee": str(self.cfg.fee("payout", amount)), "minAmount": str(amount), "claim": claim, "specHash": p["spec_hash"],
                          "payees": [list(x) for x in p["payees"]], "refund": "after-deadline"}}

    def _required(self, accepts: list, error: str, resource: str, what: str, bazaar: dict | None = None) -> tuple[int, dict, dict]:
        body = {"x402Version": X402_VERSION, "error": error, "resource": {"url": resource, "description": what, "mimeType": "application/json"},
                "accepts": accepts, "extensions": {SCHEME: {"info": {"version": 1, "proposal": True, "settles": "on-acceptance",
                                                                     "refund": "after-deadline", "payerHeader": "Attested-Payer"}},
                                                   **({"bazaar": bazaar} if bazaar else {})}}
        return 402, {"payment-required": ra.encode(body)}, body

    # -- one check by the standard `exact` scheme ---------------------------------------------------------------------
    def exact_requirement(self) -> dict | None:
        """The `exact` entry: the x402_check price to pay_to in the asset, with the facilitator's own fee payer (asked once)."""
        if not self.exact:
            return None
        from . import x402_exact as X
        if self._fee_payer is None:
            self._fee_payer = self.exact.get("fee_payer") or self.exact["facilitator"].fee_payer(DEVNET)
        if not self._fee_payer:
            return None                 # the facilitator offers no exact on this network: the pack alone is sold
        each = fees_config.micro(self.cfg.doc["fees"]["x402_check"]["usd_each"]) * 10 ** int(self.exact.get("decimals", 6)) // 10 ** 6
        return X.requirement(each, self.exact["asset"], self.exact["pay_to"], self._fee_payer, timeout=int(self.exact.get("timeout", 60)))

    def bazaar(self) -> dict:
        from . import x402_exact as X
        return X.bazaar("GET", description="Knos paid check: the cheat checks, the repository's tests twice and a signed receipt for a "
                                           "committed change (run by `knos verify`; this endpoint meters it)",
                        output_example={"paid": True, "n": 0, "left": 0},
                        output_schema={"type": "object", "properties": {"paid": {"type": "boolean"}, "left": {"type": "integer"}},
                                       "required": ["paid"]})

    def _pack_requirement(self, payer: str | None) -> dict | None:
        if not self.offer:
            return None
        req = ra.requirement(self.offer, payer)
        req["extra"].pop("record", None)
        req["extra"]["checks"] = {"price": str(self.offer["price"]), "count": self.checks, "sign": "knos-check:<order>:<n>"}
        return req

    def _exact_paid(self, got: dict, resource: str) -> tuple[int, dict, dict]:
        from . import x402_exact as X
        req = self.exact_requirement()
        if req is None or got.get("accepted") != req:
            return self._required([r for r in (self._pack_requirement(None), req) if r], "the payment does not accept this server's exact requirement",
                                  resource, "one paid check", self.bazaar())
        try:
            s = self.exact["facilitator"].verify_and_settle(got, req, self.exact.get("confirm"))  # type: ignore[index,union-attr]  # req is set: exact_requirement() is None when self.exact is not
        except X.Refused as why:
            return 402, {}, {"error": str(why)}
        key = f"exact:{s.get('transaction')}"
        if not s.get("transaction") or key in self._used:
            return 409, {}, {"error": "this payment was already used for a check"}
        self._used[key] = 1
        self._save()                    # kept before the answer, as for a pack: a restart never sells this call again
        resp = {"success": True, "network": DEVNET, "transaction": s["transaction"], "payer": s.get("payer", ""), "status": "settled"}
        return 200, {"payment-response": ra.encode(resp)}, {"paid": True, "scheme": "exact", "transaction": s["transaction"], "n": 0, "left": 0,
                                                           "run": "knos verify runs the check; this endpoint meters it"}

    def _payer(self, h: dict) -> str | None:
        payer = h.get(ra.PAYER_HEADER)
        if payer is not None and not ra.address(payer):
            raise ra.Bad("the Attested-Payer header is not a Solana address")
        return payer

    def _payment(self, h: dict) -> tuple[dict, str]:
        raw = h.get("payment-signature", "")
        if len(raw) > ra.MAX_HEADER:
            raise ra.Bad(f"the PAYMENT-SIGNATURE header is over {ra.MAX_HEADER} characters")
        try:
            got = ra.decode(raw)
        except (ValueError, TypeError):
            raise ra.Bad("the PAYMENT-SIGNATURE header is not base64 JSON") from None
        if not isinstance(got, dict) or not isinstance(got.get("payload"), dict) or not ra.address(got["payload"].get("order")):
            raise ra.Bad("the PAYMENT-SIGNATURE header needs payload.order, the order's address")
        return got, got["payload"]["order"]

    def _preorder(self, claim: str, p: dict, h: dict, resource: str) -> tuple[int, dict, dict]:
        if "payment-signature" not in h:
            return self._required([self.requirement(claim, p, self._payer(h))], "PAYMENT-SIGNATURE header is required", resource,
                                  f"a pre-order of graduated claim {claim}: held by knos_pay, paid to its makers on accepted delivery, refunded after the deadline")
        _, order = self._payment(h)
        o, why = self.verify_pool_order(p, order)
        if o is None:
            return self._required([self.requirement(claim, p, None)], why, resource, f"a pre-order of graduated claim {claim}")  # type: ignore[arg-type]  # verify_pool_order: (None, why) always says why
        resp = {"success": True, "network": DEVNET, "transaction": "", "payer": str(o.source), "status": "escrowed", "order": order}
        return 200, {"payment-response": ra.encode(resp)}, {"escrowed": True, "claim": claim, "order": order, "amount": o.amount, "fee": o.fee,
                                                           "deadline": o.deadline, "said": "Held by knos_pay: paid to the makers on accepted delivery, "
                                                                                           "refunded with its fee after the deadline."}

    def verify_pool_order(self, p: dict, order: str) -> tuple[Any, str | None]:
        """The order a pre-order payment names: knos_pay's, in this claim's pool, open, on its terms, in the mint,
        with time left. (order, None) or (None, why)."""
        from solders.pubkey import Pubkey
        from ..settle.v2 import pay
        got = self.chain.infos([Pubkey.from_string(order)])[0]
        if got is None:
            return None, f"there is no order at {order}: fund it first (FundOrderWallet), or it was paid or refunded"
        if str(got[0]) != p["program"]:
            return None, f"{order} is not an account of {p['program']}"
        o = pay.read_order(bytes(got[1]))
        if o is None:
            return None, f"{order} is not a work order"
        if o.scope.hex() != p["pool"]["scope"] or pay.order_pda(o.scope, o.source, o.seq, Pubkey.from_string(p["program"])) != Pubkey.from_string(order):
            return None, "the order is not in this claim's pre-order pool"
        if o.state != "open":
            return None, "the order is not open"
        from .. import graduation
        why = graduation.mismatch(p, "pool", o, self.mint)     # terms, mode, judge, pinned workflows, flags, mint
        if why is not None:
            return None, f"the order is not one of this pool's: {why}"
        if o.deadline < self.chain.now() + MARGIN:
            return None, "the order's deadline leaves too little time"
        return o, None

    # -- paid checks ---------------------------------------------------------------------------------------------------
    def _checks(self, h: dict, resource: str) -> tuple[int, dict, dict]:
        off = self.offer
        if "payment-signature" not in h:
            accepts = [r for r in (self._pack_requirement(self._payer(h)), self.exact_requirement()) if r]
            each = fees_config.micro(self.cfg.doc["fees"]["x402_check"]["usd_each"])
            what = " or ".join(x for x in ((f"a pack of {self.checks} paid checks at {each / 1e6:g} test USDC each" if off else ""),
                                           (f"one paid check at {each / 1e6:g} (exact)" if self.exact else "")) if x)
            return self._required(accepts, "PAYMENT-SIGNATURE header is required", resource, what, self.bazaar())
        if self.exact:
            raw = h.get("payment-signature", "")
            try:
                peek = ra.decode(raw) if len(raw) <= 4 * ra.MAX_HEADER else None
            except (ValueError, TypeError):
                peek = None
            if isinstance(peek, dict) and isinstance(peek.get("accepted"), dict) and peek["accepted"].get("scheme") == "exact":
                return self._exact_paid(peek, resource)
        if off is None:
            raise ra.Bad("this server sells checks by the exact scheme only: pay the exact requirement of its 402")
        got, order = self._payment(h)
        n, sig = got["payload"].get("n"), got["payload"].get("signature")
        if not isinstance(n, int) or isinstance(n, bool) or n < 0 or not isinstance(sig, str):
            raise ra.Bad("payload.n (the call's number on the order, from 0) and payload.signature are needed")
        o, why = ra.verify(self.chain, off, order)
        if o is None:
            return 402, {}, {"error": why}
        from solders.pubkey import Pubkey
        from solders.signature import Signature
        try:
            ok = Signature.from_string(sig).verify(Pubkey.from_string(str(o.source)), check_message(order, n))
        except ValueError:
            ok = False
        if not ok:
            return 401, {}, {"error": "the call is not signed by the wallet that funded the order"}
        used = self._used.get(order, 0)
        if n != used:
            return 409, {}, {"error": f"call {n} on this order: the next is {used} (a replay, or one skipped)"}
        if used >= self.checks:
            return 402, {}, {"error": f"the order's {self.checks} checks are used: fund another"}
        self._used[order] = used + 1
        self._save()                    # kept before the answer: a restart never sells this call again
        resp = {"success": True, "network": DEVNET, "transaction": "", "payer": str(o.source), "status": "escrowed", "order": order}
        return 200, {"payment-response": ra.encode(resp)}, {"paid": True, "order": order, "n": n, "left": self.checks - used - 1,
                                                           "run": "knos verify runs the check; this endpoint meters it"}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m knos.money.x402", description="The x402 endpoint for graduation pre-orders and paid checks (devnet).")
    ap.add_argument("--plans", type=Path, required=True, help="JSON: {claim id: plan} (or a revenue_devnet.json, whose claims are read)")
    ap.add_argument("--mint", required=True, help="the mint pre-orders are taken in")
    ap.add_argument("--offer", type=Path, help="JSON in knos.record_api.offer's shape: what /checks sells")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8403)
    ap.add_argument("--state", type=Path, default=Path.home() / ".knos" / "x402_checks.json", help="where the count of each order's paid checks is kept")
    ap.add_argument("--exact-asset", help="also sell ONE check by the x402 `exact` scheme, paid in this mint (devnet USDC: 4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU)")
    ap.add_argument("--exact-decimals", type=int, default=6)
    ap.add_argument("--pay-to", help="the address whose token account receives `exact` payments (the operator's)")
    ap.add_argument("--facilitator", default=None, help="the x402 facilitator (default KNOS_X402_FACILITATOR, else https://x402.org/facilitator, no key)")
    a = ap.parse_args(argv)
    doc = json.loads(a.plans.read_text(encoding="utf-8"))
    plans = {c["plan"]["claim_id"]: c["plan"] for c in doc["claims"].values()} if "claims" in doc else doc
    from .. import chain
    exact = None
    if a.exact_asset:
        if not a.pay_to:
            ap.error("--exact-asset needs --pay-to")
        from . import x402_exact as X
        exact = {"asset": a.exact_asset, "pay_to": a.pay_to, "decimals": a.exact_decimals, "facilitator": X.Facilitator(a.facilitator),
                 "confirm": X.confirm_on()}
    server = Server(plans, chain.ledger(), a.mint, json.loads(a.offer.read_text(encoding="utf-8")) if a.offer else None,
                    state=a.state, exact=exact)
    http = ra.serve(server, a.host, a.port)     # type: ignore[arg-type]  # the same handle(path, headers, client=, method=)
    print(f"knos money x402 on http://{a.host}:{a.port} ({', '.join(ROUTES)})", file=sys.stderr)
    http.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
