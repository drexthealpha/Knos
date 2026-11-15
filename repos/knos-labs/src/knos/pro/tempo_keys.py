"""Agent budgets enforced by the Tempo protocol: one Keychain access key per agent.

The team's budget account (the root key, encrypted at rest) authorizes an access key for each agent through the
AccountKeychain precompile at 0xAAAAAAAA00000000000000000000000000000000:

    authorizeKey(keyId, SignatureType.Secp256k1, KeyRestrictions{
        expiry, enforceLimits = true, limits = [TokenLimit{token, amount, period = 86400}],
        allowAnyCalls = false, allowedCalls = [token.transferWithMemo]})

The agent then signs its own payments (type-0x76 transactions with a Keychain signature, sender = the budget
account). Tempo itself refuses anything over the remaining allowance for the period, or any call outside the
allowed list, whatever the agent's software does. `revokeKey` ends it for good (a keyId can never be reused).

Built on Tempo's own Python SDK, pytempo (github.com/tempoxyz/pytempo), for the 0x76 encoding and signatures.
Sources, read 30 Sep 2026: tempo.xyz/developers/docs/protocol/transactions/AccountKeychain; pytempo 0.5.1
contracts/account_keychain.py and keychain.py. `getRemainingLimitWithPeriod` is selector 0xa7f72cab.
"""

from __future__ import annotations

import json
import time
import urllib.request
from dataclasses import dataclass
from typing import Any

KEYCHAIN = "0xaAAAaaAA00000000000000000000000000000000"
SEL_REMAINING_WITH_PERIOD = "a7f72cab"
DAY = 86_400
CHAINS = {"mainnet": (4217, "https://rpc.tempo.xyz"), "moderato": (42431, "https://rpc.moderato.tempo.xyz")}
DECIMALS = 6


class TempoError(Exception):
    pass


def rpc(url: str, method: str, params: list, timeout: float = 20.0) -> Any:
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json", "User-Agent": "knos"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - the chosen Tempo endpoint
        got = json.loads(resp.read())
    if "error" in got:
        raise TempoError(str(got["error"].get("message", got["error"])))
    return got.get("result")


def _addr_word(a: str) -> str:
    return a.lower().removeprefix("0x").rjust(64, "0")


def remaining(url: str, account: str, key_id: str, token: str) -> tuple[int, int]:
    """(remaining allowance in token base units, end of the current period as unix time)."""
    data = "0x" + SEL_REMAINING_WITH_PERIOD + _addr_word(account) + _addr_word(key_id) + _addr_word(token)
    got = rpc(url, "eth_call", [{"to": KEYCHAIN, "data": data}, "latest"])
    raw = bytes.fromhex(got[2:])
    if len(raw) < 64:
        raise TempoError("unexpected getRemainingLimitWithPeriod reply")
    return int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:64], "big")


@dataclass
class Sent:
    tx: str
    ok: bool
    status: str


def _send(url: str, chain_id: int, calls: tuple, sign, sender: str, fee_token: str, key_id: str | None = None,
          wait: float = 60.0, estimate: bool = True) -> Sent:
    """Build, sign (with `sign(tx) -> tx`), send and wait for one 0x76 transaction. A transaction the pool or
    the protocol refuses comes back as ok=False with the reason; it never raises for that."""
    from pytempo import TempoTransaction
    nonce = int(rpc(url, "eth_getTransactionCount", [sender, "pending"]), 16)
    gas_price = int(rpc(url, "eth_gasPrice", []), 16)
    draft = TempoTransaction.create(chain_id=chain_id, gas_limit=1_000_000, max_fee_per_gas=gas_price * 2,
                                    max_priority_fee_per_gas=gas_price, nonce=nonce, fee_token=fee_token, calls=calls)
    gas = 300_000  # without estimation (a bypass attempt skips every client-side check)
    if estimate:
        try:
            est = draft.to_estimate_gas_request(sender, key_id=key_id)
            est["feeToken"] = fee_token
            gas = int(rpc(url, "eth_estimateGas", [est]), 16)
        except TempoError as e:
            return Sent("", False, f"refused before sending: {e}")
    tx = TempoTransaction.create(chain_id=chain_id, gas_limit=int(gas * 1.3) + 20_000,
                                 max_fee_per_gas=gas_price * 2, max_priority_fee_per_gas=gas_price, nonce=nonce,
                                 fee_token=fee_token, calls=calls)
    signed = sign(tx)
    try:
        h = rpc(url, "eth_sendRawTransaction", ["0x" + signed.encode().hex()])
    except TempoError as e:
        return Sent("", False, f"refused by the node: {e}")
    end = time.monotonic() + wait
    while time.monotonic() < end:
        rec = rpc(url, "eth_getTransactionReceipt", [h])
        if rec:
            ok = rec.get("status") in ("0x1", 1)
            return Sent(h, ok, "succeeded" if ok else "reverted on chain (the fee was still paid)")
        time.sleep(1)
    return Sent(h, False, "not mined in time")


def authorize(url: str, chain_id: int, root_key: str, agent: str, token: str, amount_units: int,
              period_s: int = DAY, expiry: int | None = None, recipients: list[str] | None = None) -> Sent:
    """The root key authorizes `agent` to send at most `amount_units` of `token` per `period_s`, and only through
    the token's `transferWithMemo` (to `recipients` if given)."""
    from eth_account import Account
    from pytempo import CallScope, KeyRestrictions, SignatureType, TokenLimit
    from pytempo.contracts import AccountKeychain
    root = Account.from_key(root_key).address
    restrictions = KeyRestrictions(expiry=expiry, limits=[TokenLimit(token=token, limit=amount_units,
                                                                     period=period_s)],
                                   allowed_calls=[CallScope.transfer_with_memo(target=token,
                                                                               recipients=recipients or [])])
    call = AccountKeychain.authorize_key(key_id=agent, signature_type=SignatureType.SECP256K1,
                                         restrictions=restrictions)
    return _send(url, chain_id, (call,), lambda tx: tx.sign(root_key), root, token)


def revoke(url: str, chain_id: int, root_key: str, agent: str, fee_token: str) -> Sent:
    from eth_account import Account
    from pytempo.contracts import AccountKeychain
    root = Account.from_key(root_key).address
    return _send(url, chain_id, (AccountKeychain.revoke_key(key_id=agent),), lambda tx: tx.sign(root_key), root,
                 fee_token)


def balance(url: str, token: str, who: str) -> int:
    data = "0x70a08231" + _addr_word(who)
    return int(rpc(url, "eth_call", [{"to": token, "data": data}, "latest"]), 16)
