"""Write fixtures/order_paid.json: an order funded from a Balance and paid on the LiteSVM harness (knos_pay and
knos_oidc as built, tests/fixtures), its acceptance receipt, a statement's status file with that payment, and every
JSON-RPC answer the consumer asks for, as a cluster gives them; and the receipt and the status file on their own
(fixtures/receipt.json, fixtures/status.json). The signatures are numbered stand-ins: a LiteSVM run has no cluster.

    PYTHONPATH=src python examples/consumer/record.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def build() -> dict:
    """{receipt, rpc: {"<method> <first param>": answer}, note} of one order paid on a fresh harness."""
    from _order import AUTHOR, MAINT, REPO, USDC, issue
    from test_receipt_offline import PR, TERMS, TEST_KEY, OTHER_KEY, Recorded, host, published

    from knos import bundle
    from knos.settle.v2 import pay

    c = Recorded()
    assert c.send([pay.set_balance_x_ix(c.owner.pubkey(), c.bal, 500 * USDC, 5_000 * USDC, [REPO])], c.owner), c.err
    order = c.fund_balance(issue(), terms=TERMS)
    wallet = c.fund().pubkey()
    c.warp(60)
    assert c.pay(order, [(AUTHOR, 10_000, wallet)], pr=PR, actor_id=MAINT), c.err
    r, _files = bundle.gather(c.call, c.events(), str(order), host, published(TEST_KEY, OTHER_KEY))
    history = c.call("getSignaturesForAddress", [r["order"]])
    rpc: dict = {f"getSignaturesForAddress {r['order']}": history}
    for sig in [x["signature"] for x in history]:        # the order's own transactions: all the consumer reads
        rpc[f"getTransaction {sig}"] = c.call("getTransaction", [sig])
    from knos import ids
    line = ids.invoice_line("Acme Agents", "INV-1", 1)
    status = {"kind": "knos-statement-status", "version": 1, "statement": "0" * 64, "events": [
        {"type": "settlement", "method": "chain", "reference": r["transaction"]["signature"], "deliverable": r["ids"]["deliverable"],
         "settlement": ids.settlement(r["ids"]["deliverable"], "chain", r["transaction"]["signature"]), "line": line,
         "on": "2026-10-03", "state": "devnet_demonstration"}]}
    return {"note": "One order funded from a Balance and paid on the LiteSVM harness (knos_pay and knos_oidc as built, "
                    "tests/fixtures), its receipt, and the JSON-RPC answers a cluster would give. The signatures are "
                    "numbered stand-ins: a LiteSVM run has no cluster. Written by examples/consumer/record.py; do not edit.",
            "receipt": r, "status": status, "rpc": rpc}


if __name__ == "__main__":
    sys.path[:0] = [str(ROOT / "tests"), str(ROOT / "src")]      # the harness lives in tests/
    here, made = Path(__file__).with_name("fixtures"), build()
    here.mkdir(exist_ok=True)
    for name, doc in (("order_paid.json", made), ("receipt.json", made["receipt"]), ("status.json", made["status"])):
        (here / name).write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        print(here / name)
