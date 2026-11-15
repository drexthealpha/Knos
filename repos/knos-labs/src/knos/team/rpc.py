"""A small Solana JSON-RPC client for the team registry: standard library HTTP, `solders` for signing.

Every call takes an explicit endpoint and timeout. A transport failure raises OSError and an RPC error raises
RpcError, so a caller on the guard path can fall back to local mode instead of blocking work.
"""

from __future__ import annotations

import base64
import json
import time
import urllib.error
import urllib.request
from typing import Any

from solders.hash import Hash
from solders.instruction import Instruction
from solders.keypair import Keypair
from solders.message import Message
from solders.pubkey import Pubkey
from solders.transaction import Transaction

CLUSTERS = {
    "devnet": "https://api.devnet.solana.com",
    "mainnet": "https://api.mainnet-beta.solana.com",
    "localnet": "http://127.0.0.1:8899",
}


class RpcError(ValueError):
    def __init__(self, message: str, data: Any = None):
        super().__init__(message)
        self.data = data

    @property
    def logs(self) -> list[str]:
        return list((self.data or {}).get("logs") or []) if isinstance(self.data, dict) else []


def call(url: str, method: str, params: list, timeout: float = 10.0) -> Any:
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json", "User-Agent": "knos"})
    for wait in (1, 2, 4, 8, None):     # public endpoints rate-limit (429): back off rather than fail the work
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - the configured cluster endpoint
                got = json.loads(resp.read())
            break
        except urllib.error.HTTPError as e:
            if e.code != 429 or wait is None:
                raise
            import time
            time.sleep(wait)
    if "error" in got:
        err = got["error"]
        raise RpcError(str(err.get("message", err)), err.get("data"))
    return got.get("result")


def account_data(url: str, address: Pubkey, commitment: str = "confirmed", min_context_slot: int | None = None,
                 timeout: float = 10.0) -> tuple[int, bytes | None]:
    """(context slot, raw data or None if the account does not exist)."""
    cfg: dict[str, Any] = {"encoding": "base64", "commitment": commitment}
    if min_context_slot is not None:
        cfg["minContextSlot"] = min_context_slot
    got = call(url, "getAccountInfo", [str(address), cfg], timeout)
    value = got["value"]
    return got["context"]["slot"], (base64.b64decode(value["data"][0]) if value else None)


def balance(url: str, address: Pubkey, timeout: float = 10.0) -> int:
    return call(url, "getBalance", [str(address), {"commitment": "confirmed"}], timeout)["value"]


def latest_blockhash(url: str, timeout: float = 10.0) -> Hash:
    got = call(url, "getLatestBlockhash", [{"commitment": "confirmed"}], timeout)
    return Hash.from_string(got["value"]["blockhash"])


def build(instructions: list[Instruction], payer: Keypair, signers: list[Keypair], blockhash: Hash) -> Transaction:
    everyone = {bytes(k.pubkey()): k for k in [payer, *signers]}
    msg = Message.new_with_blockhash(instructions, payer.pubkey(), blockhash)
    return Transaction(list(everyone.values()), msg, blockhash)


def send(url: str, instructions: list[Instruction], payer: Keypair, signers: list[Keypair] | None = None,
         timeout: float = 10.0, confirm: bool = True, confirm_within: float = 30.0) -> str:
    """Sign, send (with preflight, so a failing program returns its logs), and wait for `confirmed`."""
    tx = build(instructions, payer, signers or [], latest_blockhash(url, timeout))
    raw = base64.b64encode(bytes(tx)).decode()
    sig = call(url, "sendTransaction", [raw, {"encoding": "base64", "preflightCommitment": "confirmed"}], timeout)
    if confirm:
        wait(url, sig, confirm_within, timeout)
    return sig


def wait(url: str, signature: str, within: float = 30.0, timeout: float = 10.0, commitment: str = "confirmed") -> dict:
    """Wait until `signature` reaches `commitment`; raise RpcError if it failed on chain, TimeoutError if it never
    landed."""
    end = time.monotonic() + within
    good = ("finalized",) if commitment == "finalized" else ("confirmed", "finalized")
    while time.monotonic() < end:
        got = call(url, "getSignatureStatuses", [[signature]], timeout)["value"][0]
        # A failure is reported only once it reaches `commitment`: a caller that lost a race (the claim protocol) then
        # reads the winner at that same commitment, and must find it there. Raising at `processed` made it read too
        # early, see no winner, and fail open.
        if got and got.get("confirmationStatus") in good:
            if got.get("err"):
                raise RpcError(f"transaction failed: {got['err']}", got)
            return got
        time.sleep(0.1)
    raise TimeoutError(f"{signature} not confirmed within {within:.0f}s")


def signatures_for(url: str, address: Pubkey, limit: int = 20, min_context_slot: int | None = None,
                   timeout: float = 10.0) -> list[dict]:
    cfg: dict[str, Any] = {"limit": limit, "commitment": "confirmed"}
    if min_context_slot is not None:
        cfg["minContextSlot"] = min_context_slot
    return call(url, "getSignaturesForAddress", [str(address), cfg], timeout) or []


def transaction(url: str, signature: str, timeout: float = 10.0) -> dict | None:
    return call(url, "getTransaction", [signature, {"encoding": "json", "commitment": "confirmed",
                                                    "maxSupportedTransactionVersion": 0}], timeout)


def airdrop(url: str, address: Pubkey, lamports: int, timeout: float = 10.0) -> str:
    sig = call(url, "requestAirdrop", [str(address), lamports, {"commitment": "confirmed"}], timeout)
    wait(url, sig, 30.0, timeout)
    return sig
