"""Paying for Knos with Solana Pay: a transfer-request link, then a public RPC to see it land. No account, no server.

    solana:<wallet>?amount=10&spl-token=<USDC mint>&reference=<one-off key>&label=Knos&message=Knos%20Pro
           &memo=knos:<plan>:<id>

The reference is 32 random bytes written as a Solana address. The wallet adds it to the transfer as a read-only
account, so `getSignaturesForAddress(reference)` finds exactly this payment and nothing else. The payment is then
checked from the transaction itself: it succeeded, it carries the reference, and the merchant's USDC balance went
up by at least the price. Only public, read-only RPC methods are used, and only by `knos pro buy` / `knos pro check`:
nothing on the memory or guard path opens a socket.
"""

from __future__ import annotations

import json
import os
import secrets
import urllib.parse
import urllib.request
from typing import Any

# The address Knos is paid to. Public by design; its key is not in this repository.
MERCHANT = "CVhqj6hcugFDKZxzSkiUG64cRbHn2kguZy9n6zv47FqL"

# USDC, from Circle's published contract addresses (developers.circle.com/stablecoins/usdc-contract-addresses).
USDC = {
    "mainnet": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
    "devnet": "4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU",
}
RPC = {"mainnet": "https://api.mainnet-beta.solana.com", "devnet": "https://api.devnet.solana.com"}
USDC_DECIMALS = 6

_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def b58encode(raw: bytes) -> str:
    n = int.from_bytes(raw, "big")
    out = ""
    while n:
        n, r = divmod(n, 58)
        out = _B58[r] + out
    pad = len(raw) - len(raw.lstrip(b"\0"))
    return "1" * pad + out


def b58decode(text: str) -> bytes:
    n = 0
    for ch in text:
        i = _B58.find(ch)
        if i < 0:
            raise ValueError(f"not base58: {ch!r}")
        n = n * 58 + i
    body = n.to_bytes((n.bit_length() + 7) // 8, "big") if n else b""
    pad = len(text) - len(text.lstrip("1"))
    return b"\0" * pad + body


def is_address(text: str) -> bool:
    try:
        return len(b58decode(text)) == 32
    except ValueError:
        return False


def new_reference() -> str:
    return b58encode(secrets.token_bytes(32))


def link(plan: str, amount: float, reference: str, network: str = "mainnet", order: str = "",
         recipient: str = MERCHANT, message: str = "") -> str:
    """The Solana Pay transfer-request URL. Amount is in USDC, as a decimal string (never scientific notation)."""
    if network not in USDC:
        raise ValueError(f"unknown network {network}")
    amt = f"{amount:.6f}".rstrip("0").rstrip(".")
    q = [("amount", amt), ("spl-token", USDC[network]), ("reference", reference), ("label", "Knos"),
         ("message", message or ("Knos Pro" if plan.startswith("pro") else "Knos Team")),
         ("memo", f"knos:{plan}:{order or reference[:8]}")]
    return f"solana:{recipient}?" + urllib.parse.urlencode(q, quote_via=urllib.parse.quote, safe=":")


def rpc_url(network: str) -> str:
    return os.environ.get("KNOS_SOLANA_RPC") or RPC[network]


def rpc(network: str, method: str, params: list, timeout: float = 20.0) -> Any:
    """One JSON-RPC call to a public endpoint. Raises OSError on a transport failure, ValueError on an RPC error."""
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    req = urllib.request.Request(rpc_url(network), data=body, headers={"Content-Type": "application/json",
                                                                        "User-Agent": "knos"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - fixed https endpoints
        got = json.loads(resp.read())
    if "error" in got:
        raise ValueError(str(got["error"].get("message", got["error"])))
    return got.get("result")


def signatures_for(network: str, address: str, limit: int = 20) -> list[dict]:
    return rpc(network, "getSignaturesForAddress", [address, {"limit": limit, "commitment": "confirmed"}]) or []


def transaction(network: str, signature: str) -> dict | None:
    return rpc(network, "getTransaction", [signature, {"encoding": "jsonParsed", "commitment": "confirmed",
                                                       "maxSupportedTransactionVersion": 0}])


def _keys(tx: dict) -> list[str]:
    keys = ((tx.get("transaction") or {}).get("message") or {}).get("accountKeys") or []
    out = [k.get("pubkey") if isinstance(k, dict) else k for k in keys]
    loaded = (tx.get("meta") or {}).get("loadedAddresses") or {}
    return out + list(loaded.get("readonly") or []) + list(loaded.get("writable") or [])


def _usdc_delta(tx: dict, owner: str, mint: str) -> float:
    meta = tx.get("meta") or {}

    def total(rows: list) -> int:
        return sum(int(((r.get("uiTokenAmount") or {}).get("amount")) or 0) for r in rows or []
                   if r.get("owner") == owner and r.get("mint") == mint)

    return (total(meta.get("postTokenBalances")) - total(meta.get("preTokenBalances"))) / 10 ** USDC_DECIMALS


def memo_of(tx: dict) -> str:
    for ix in ((tx.get("transaction") or {}).get("message") or {}).get("instructions") or []:
        if ix.get("program") == "spl-memo" and isinstance(ix.get("parsed"), str):
            return ix["parsed"]
    for line in (tx.get("meta") or {}).get("logMessages") or []:
        if "Memo (len" in line and '"' in line:
            return line.split('"', 1)[1].rsplit('"', 1)[0]
    return ""


def check_payment(tx: dict | None, reference: str, amount: float, network: str,
                  recipient: str = MERCHANT) -> tuple[bool, str, float]:
    """(paid, why-not, usdc received). Every condition is read from the transaction itself."""
    if not tx:
        return False, "transaction not found yet", 0.0
    if (tx.get("meta") or {}).get("err") is not None:
        return False, "the transaction failed on chain", 0.0
    if reference not in _keys(tx):
        return False, "the transaction does not carry this purchase's reference", 0.0
    got = _usdc_delta(tx, recipient, USDC[network])
    if got + 1e-9 < amount:
        return False, f"{got:g} USDC reached Knos, {amount:g} was due", got
    return True, "", got


def explorer_tx(network: str, signature: str) -> str:
    return f"https://explorer.solana.com/tx/{signature}" + ("" if network == "mainnet" else f"?cluster={network}")


def find_payment(reference: str, amount: float, network: str, recipient: str = MERCHANT) -> dict | None:
    """The first confirmed transaction for this reference that pays in full, or None (not yet)."""
    for sig in signatures_for(network, reference):
        if sig.get("err") is not None:
            continue
        tx = transaction(network, sig["signature"])
        ok, _why, got = check_payment(tx, reference, amount, network, recipient)
        if ok:
            return {"signature": sig["signature"], "paid": got, "memo": memo_of(tx or {})}
    return None
