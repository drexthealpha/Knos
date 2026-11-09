"""Wanted: does someone want the result? A demand book of pre-orders locked against one sealed spec.

A pre-order counts only while it is locked in vault (`escrow_ref`: the devnet work order or pool account that holds
it); a pledge without vault is shown and never counted. Each buyer counts once however many orders it places, and
the bar is N distinct buyers AND X locked, both set by whoever asks the question (a founder or funder decision, not
the referee's). Amounts are integers in the currency's smallest unit (micro-USDC for USDC).
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

from .check import Check

STATES = ("locked", "released", "refunded")


def _key(buyer: str) -> str:
    return " ".join(str(buyer).split()).lower()


def wanted(orders, *, min_buyers: int, min_locked: int, spec_hash: str | None = None) -> Check:
    """The Wanted test over a list of orders (DemandBook.orders, or the chain's pre-order pool read by MONEY)."""
    if min_buyers < 1 or min_locked < 0:
        raise ValueError("the bar needs at least one buyer and a non-negative amount")
    rows = [o for o in orders if spec_hash is None or o.get("spec_hash") == spec_hash]
    counted = [o for o in rows if o.get("state", "locked") == "locked" and str(o.get("escrow_ref") or "").strip()
               and int(o.get("amount", 0)) > 0]
    buyers = sorted({_key(o["buyer"]) for o in counted})
    locked = sum(int(o["amount"]) for o in counted)
    currencies = sorted({o.get("currency", "USDC") for o in counted})
    reasons = []
    if len(currencies) > 1:
        reasons.append(f"orders in more than one currency ({', '.join(currencies)}); the bar is in one")
    if len(buyers) < min_buyers:
        reasons.append(f"{len(buyers)} distinct buyer(s) with money locked, the bar is {min_buyers}")
    if locked < min_locked:
        reasons.append(f"{locked} locked, the bar is {min_locked}")
    ev = {"distinct_buyers": len(buyers), "locked": locked, "currency": currencies[0] if currencies else None,
          "orders_counted": len(counted), "pledges_not_counted": len(rows) - len(counted),
          "bar": {"min_buyers": min_buyers, "min_locked": min_locked}}
    return Check("wanted", not reasons, reasons, ev)


class DemandBook:
    """A demand book kept as one JSON file (default: $KNOS_HOME/referee/demand.json). The book is the referee's view;
    the money itself is in the vault each order names."""

    def __init__(self, path=None):
        home = Path(os.environ.get("KNOS_HOME") or Path.home() / ".knos")
        self.path = Path(path) if path is not None else home / "referee" / "demand.json"

    def _load(self) -> list[dict]:
        try:
            got = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return []
        if not isinstance(got, list):
            raise ValueError(f"{self.path} is not a demand book")
        return got

    def _save(self, rows: list[dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(rows, indent=1, sort_keys=True), encoding="utf-8")
        tmp.replace(self.path)

    def lock(self, spec_hash: str, buyer: str, amount: int, *, escrow_ref: str = "", currency: str = "USDC",
             at: float | None = None) -> dict:
        if not str(spec_hash).strip() or not _key(buyer):
            raise ValueError("an order needs a spec hash and a buyer")
        if int(amount) <= 0:
            raise ValueError("an order locks a positive amount")
        rows = self._load()
        now = int(at if at is not None else time.time())
        oid = hashlib.sha256(f"{spec_hash}|{_key(buyer)}|{amount}|{escrow_ref}|{now}|{len(rows)}".encode()).hexdigest()[:16]
        row = {"id": oid, "spec_hash": spec_hash, "buyer": _key(buyer), "amount": int(amount), "currency": currency,
               "escrow_ref": escrow_ref, "state": "locked", "at": now}
        rows.append(row)
        self._save(rows)
        return row

    def _set(self, order_id: str, state: str) -> dict:
        rows = self._load()
        for r in rows:
            if r["id"] == order_id:
                if r["state"] != "locked":
                    raise ValueError(f"order {order_id} is {r['state']}, not locked")
                r["state"] = state
                self._save(rows)
                return r
        raise ValueError(f"no order {order_id}")

    def release(self, order_id: str) -> dict:
        """The buyer's money went to the work (the order was filled): it no longer counts as demand waiting."""
        return self._set(order_id, "released")

    def refund(self, order_id: str) -> dict:
        return self._set(order_id, "refunded")

    def orders(self, spec_hash: str | None = None) -> list[dict]:
        return [r for r in self._load() if spec_hash is None or r["spec_hash"] == spec_hash]

    def wanted(self, spec_hash: str, *, min_buyers: int, min_locked: int) -> Check:
        return wanted(self.orders(spec_hash), min_buyers=min_buyers, min_locked=min_locked, spec_hash=spec_hash)
