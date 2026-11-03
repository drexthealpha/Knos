"""One paid route, priced per use over x402 V2: GET /api/x402/report?hash=… costs 1 test unit on devnet.

x402 V2 as solana.com/docs/payments/agentic-payments/x402 describes it (read 21 Oct 2026; "Do not use those V1 fields in a
new integration"): the first call answers HTTP 402 with a PaymentRequired object, base64 in the PAYMENT-REQUIRED header
(and as the body): scheme "exact", network the CAIP-2 id of devnet (solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1), asset = this
app's test mint, payTo = the app's devnet test wallet's token account, amount in base units. The client signs that transfer
and retries with a PaymentPayload in the PAYMENT-SIGNATURE header ({"x402Version": 2, "accepted": <the requirement>,
"payload": {"transaction": <base64>}}); this server self-facilitates (sendTransaction, then confirmation) and serves the full
report with the settlement result in PAYMENT-RESPONSE. Devnet test money: the point is the mechanism, not revenue. An agent
pays for a report the way a person pre-orders: per use, no account.
"""
from __future__ import annotations

import base64
import binascii
import json

from . import escrow

PRICE_UNITS = 1
NETWORK = "solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1"   # CAIP-2: devnet's genesis hash, first 32 characters


class PaymentRequired(Exception):
    def __init__(self, challenge: dict):
        super().__init__("payment required")
        self.challenge = challenge


def ready() -> bool:
    try:
        return escrow.available() and bool(escrow.demo_key())
    except Exception:  # noqa: BLE001
        return False


def challenge(report_hash: str, base_url: str) -> dict:
    from knos.settle.v2 import pay
    led = escrow.ledger()
    mint = escrow.mint(led, create=True)
    to = pay.ata(escrow.demo_key().pubkey(), mint)
    return {"x402Version": 2, "error": "payment required",
            "resource": {"url": f"{base_url}/api/x402/report?hash={report_hash}", "mimeType": "application/json",
                         "description": f"The full Knos demand report {report_hash[:12]}… ({PRICE_UNITS} test unit; devnet test money)"},
            "accepts": [{"scheme": "exact", "network": NETWORK, "amount": str(PRICE_UNITS * escrow.UNIT), "payTo": str(to),
                         "asset": str(mint), "maxTimeoutSeconds": 60,
                         "extra": {"decimals": 6, "note": "test units of Knos's devnet test mint stand in for USDC"}}]}


def header(obj: dict) -> str:
    """A protocol object as its x402 V2 header carries it: base64 of the JSON."""
    return base64.b64encode(json.dumps(obj, separators=(",", ":")).encode()).decode()


def expected() -> tuple[str, str, int]:
    """What this server's order asks: (payTo token account, mint, amount in base units), the same as challenge() names."""
    from knos.settle.v2 import pay
    mint = escrow.mint(escrow.ledger(), create=True)
    return str(pay.ata(escrow.demo_key().pubkey(), mint)), str(mint), PRICE_UNITS * escrow.UNIT


def paid_to(tx: dict, pay_to: str, mint: str) -> int:
    """Base units of `mint` a confirmed transaction (getTransaction, jsonParsed) moved into `pay_to`: its token balance
    after minus before. 0 when the transaction failed or never touched that account."""
    meta = (tx or {}).get("meta") or {}
    if meta.get("err") is not None:
        return 0
    keys = [k.get("pubkey") if isinstance(k, dict) else k for k in (((tx or {}).get("transaction") or {}).get("message") or {}).get("accountKeys", [])]
    if pay_to not in keys:
        return 0
    i = keys.index(pay_to)

    def bal(rows) -> int:
        return next((int(r["uiTokenAmount"]["amount"]) for r in rows or [] if r.get("accountIndex") == i and r.get("mint") == mint), 0)
    return bal(meta.get("postTokenBalances")) - bal(meta.get("preTokenBalances"))


def settle(header: str) -> dict:
    """The PAYMENT-SIGNATURE header -> the payment sent on devnet. Returns the SettlementResponse PAYMENT-RESPONSE carries.
    The report is served only when the confirmed transaction moved exactly this order's amount, in its mint, into its
    payTo account: any other confirmed transaction (a smaller amount, another payee) is refused."""
    from knos import chain
    try:
        doc = json.loads(base64.b64decode(str(header or ""), validate=True))
    except (ValueError, binascii.Error):
        raise ValueError("PAYMENT-SIGNATURE: base64 JSON, as the x402 spec encodes it") from None
    acc = doc.get("accepted") or {}
    if doc.get("x402Version") != 2 or acc.get("scheme") != "exact" or acc.get("network") != NETWORK:
        raise ValueError(f"PAYMENT-SIGNATURE: x402Version 2, accepted.scheme exact, accepted.network {NETWORK}")
    tx = (doc.get("payload") or {}).get("transaction")
    if not isinstance(tx, str) or not 100 < len(tx) < 6000:
        raise ValueError("PAYMENT-SIGNATURE.payload.transaction: the signed transfer, base64")
    pay_to, mint, amount = expected()
    if (str(acc.get("payTo")), str(acc.get("asset")), str(acc.get("amount"))) != (pay_to, mint, str(amount)):
        raise ValueError("PAYMENT-SIGNATURE.accepted: not the requirement this server offers (its payTo, asset and amount)")
    led = escrow.ledger()
    sig = chain.call(led.url, "sendTransaction", [tx, {"encoding": "base64", "preflightCommitment": "confirmed"}], timeout=30)
    for _ in range(30):
        got = chain.call(led.url, "getSignatureStatuses", [[sig]], timeout=10)
        st = (got.get("value") or [None])[0]
        if st and st.get("confirmationStatus") in ("confirmed", "finalized"):
            tx = chain.call(led.url, "getTransaction", [sig, {"encoding": "jsonParsed", "commitment": "confirmed",
                                                               "maxSupportedTransactionVersion": 0}], timeout=15)
            got = paid_to(tx, pay_to, mint)
            if got != amount:
                raise ValueError(f"the confirmed transaction {sig} moved {got} base units of {mint} to {pay_to}, not the {amount} "
                                 "this order asks: nothing is served")
            keys = (((tx or {}).get("transaction") or {}).get("message") or {}).get("accountKeys") or [{}]
            payer = keys[0].get("pubkey") if isinstance(keys[0], dict) else keys[0]
            return {"success": True, "transaction": sig, "network": NETWORK, "payer": payer, "amount": str(amount),
                    "explorer": escrow.explorer(sig)}
        import time
        time.sleep(1)
    raise ValueError("the payment transaction was not confirmed in time")
