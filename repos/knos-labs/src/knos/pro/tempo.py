"""Paying for Knos on Tempo: a TIP-20 `transferWithMemo` to the Knos address, found and checked over Tempo's public
RPC. No account, no server.

Sources (read 2026-09-29):
  chain ids, RPC, explorers   https://tempo.xyz/developers/docs/quickstart/connection-details
  transferWithMemo, events    https://tempo.xyz/developers/docs/protocol/tip20/spec
  pathUSD (mainnet predeploy) https://tempo.xyz/developers/docs/protocol/exchange/quote-tokens
  testnet tokens, faucet      https://tempo.xyz/developers/docs/quickstart/faucet

    function transferWithMemo(address to, uint256 amount, bytes32 memo)
    event TransferWithMemo(address indexed from, address indexed to, uint256 amount, bytes32 indexed memo)

The memo is this purchase's `knos:<plan>:<id>`, packed into the 32 bytes. Because it is indexed, the payment is found
with one `eth_getLogs` filtered on (event, to = Knos, memo), and then checked from its receipt: the transaction
succeeded, the log came from an accepted stablecoin, it paid the Knos address, it carries this memo, and the amount
(6 decimals) is at least the price.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import urllib.request
from typing import Any

MERCHANT = "0x580C2842ec71C432D5d2fc4dDCDf37CE493FbB3A"

CHAINS = {
    "mainnet": {"id": 4217, "rpc": "https://rpc.tempo.xyz", "explorer": "https://explore.tempo.xyz"},
    "testnet": {"id": 42431, "rpc": "https://rpc.moderato.tempo.xyz", "explorer": "https://explore.testnet.tempo.xyz"},
}
# Stablecoins accepted as payment (TIP-20, 6 decimals).
TOKENS = {
    # USDC.e address from Tempo's own MPP SDKs (pympp mpp/methods/tempo/_defaults.py USDC; mpp-go MainnetUSDCAddress)
    "mainnet": {"pathUSD": "0x20c0000000000000000000000000000000000000",
                "USDC.e": "0x20C000000000000000000000b9537d11c60E8b50"},
    "testnet": {"pathUSD": "0x20c0000000000000000000000000000000000000",
                "AlphaUSD": "0x20c0000000000000000000000000000000000001"},
}
DECIMALS = 6
# keccak256 of the signatures above (checked in tests/test_tempo.py against the ERC-20 Transfer topic)
TOPIC_TRANSFER_WITH_MEMO = "0x57bc7354aa85aed339e000bccffabbc529466af35f0772c8f8ee1145927de7f0"
_ADDR = re.compile(r"^0x[0-9a-fA-F]{40}$")


def is_address(text: str) -> bool:
    return bool(_ADDR.match(text or ""))


def new_order() -> str:
    return secrets.token_hex(4)


def memo(plan: str, order: str) -> str:
    """`knos:<plan>:<order>` as a bytes32 hex string, left-aligned and zero-padded."""
    raw = f"knos:{plan}:{order}".encode("ascii")
    if len(raw) > 32:
        raise ValueError("memo longer than 32 bytes")
    return "0x" + raw.hex().ljust(64, "0")


def memo_text(b32: str) -> str:
    try:
        return bytes.fromhex(b32[2:] if b32.startswith("0x") else b32).rstrip(b"\0").decode("ascii")
    except (ValueError, UnicodeDecodeError):
        return ""


def _topic_addr(addr: str) -> str:
    return "0x" + addr.lower()[2:].rjust(64, "0")


def link(amount: float, memo32: str, network: str = "mainnet", token: str = "pathUSD",
         recipient: str = MERCHANT) -> str:
    """An EIP-681 payment request calling transferWithMemo on the stablecoin (wallets that read EIP-681 fill it in)."""
    chain = CHAINS[network]["id"]
    units = int(round(amount * 10 ** DECIMALS))
    return (f"ethereum:{TOKENS[network][token]}@{chain}/transferWithMemo?address={recipient}"
            f"&uint256={units}&bytes32={memo32}")


def rpc_url(network: str) -> str:
    return os.environ.get("KNOS_TEMPO_RPC") or CHAINS[network]["rpc"]


def rpc(network: str, method: str, params: list, timeout: float = 20.0) -> Any:
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    req = urllib.request.Request(rpc_url(network), data=body, headers={"Content-Type": "application/json",
                                                                        "User-Agent": "knos"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - fixed https endpoints
        got = json.loads(resp.read())
    if "error" in got:
        raise ValueError(str(got["error"].get("message", got["error"])))
    return got.get("result")


def block_number(network: str) -> int:
    return int(rpc(network, "eth_blockNumber", []), 16)


def check_receipt(receipt: dict | None, memo32: str, amount: float, network: str,
                  recipient: str = MERCHANT) -> tuple[bool, str, float, str]:
    """(paid, why-not, amount paid, payer). Every condition is read from the receipt."""
    if not receipt:
        return False, "transaction not found yet", 0.0, ""
    if str(receipt.get("status", "")).lower() not in ("0x1", "1"):
        return False, "the transaction failed on chain", 0.0, ""
    accepted = {a.lower() for a in TOKENS[network].values()}
    wrong_token = False
    for log in receipt.get("logs") or []:
        topics = [str(t).lower() for t in log.get("topics") or []]
        if len(topics) != 4 or topics[0] != TOPIC_TRANSFER_WITH_MEMO:
            continue
        if topics[2] != _topic_addr(recipient) or topics[3] != memo32.lower():
            continue
        if str(log.get("address", "")).lower() not in accepted:
            wrong_token = True
            continue
        paid = int(log.get("data") or "0x0", 16) / 10 ** DECIMALS
        payer = "0x" + topics[1][-40:]
        if paid + 1e-9 < amount:
            return False, f"{paid:g} reached Knos, {amount:g} was due", paid, payer
        return True, "", paid, payer
    if wrong_token:
        return False, "paid in a token Knos does not accept", 0.0, ""
    return False, "no transfer to Knos with this purchase's memo", 0.0, ""


def find_payment(memo32: str, amount: float, network: str, from_block: int,
                 recipient: str = MERCHANT) -> dict | None:
    """The first transfer to Knos carrying this memo since `from_block` that pays in full, or None (not yet)."""
    logs = rpc(network, "eth_getLogs", [{
        "fromBlock": hex(max(from_block, 0)), "toBlock": "latest",
        "address": list(TOKENS[network].values()),
        "topics": [TOPIC_TRANSFER_WITH_MEMO, None, _topic_addr(recipient), memo32]}]) or []
    for log in logs:
        tx = log.get("transactionHash")
        if not tx:
            continue
        receipt = rpc(network, "eth_getTransactionReceipt", [tx])
        ok, _why, paid, payer = check_receipt(receipt, memo32, amount, network, recipient)
        if ok:
            return {"signature": tx, "paid": paid, "payer": payer, "memo": memo_text(memo32)}
    return None


def explorer_tx(network: str, tx: str) -> str:
    return f"{CHAINS[network]['explorer']}/tx/{tx}"
