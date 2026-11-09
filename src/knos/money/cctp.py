"""CCTP V2 into a Knos vault: a funder whose USDC sits on Ethereum, Base or Arbitrum funds a Solana order in one flow.

Design (no transfer was run for this build: the EVM leg needs testnet ETH and testnet USDC, which Knos does not hold).
Sources, all read 14 Oct 2026 on developers.circle.com:
  - Solana is domain 5; Ethereum 0, Arbitrum 3, Base 6, Arc 26 (cctp/concepts/supported-chains-and-domains);
    Fast Transfer is supported with Solana as source and as destination.
  - On Solana, MessageTransmitterV2 is CCTPV2Sm4AdWt5296sk4P66VBZ7bEhcARwFaaS9YPbeC and TokenMessengerMinterV2 is
    CCTPV2vPZJS2u2BBsUoscuikbYjnpFmbFsvVuJdgUMQe, on mainnet and devnet alike (cctp/references/solana-programs).
    "When Solana is the destination, convert the recipient's token account from Base58 to hex", and "the token account
    must exist at receiveMessage execution or the instruction reverts".
  - The attestation API: GET {https://iris-api-sandbox.circle.com | https://iris-api.circle.com}/v2/messages/{sourceDomainId}
    ?transactionHash=... returns messages[] with message, attestation (or PENDING), status (complete |
    pending_confirmations) and decodedMessage (mintRecipient, amount, hookData). The reference page says "API key
    required"; the sandbox answered without one on 14 Oct 2026 (a made-up hash: HTTP 404 "Message not found", not 401).
  - Message layout (cctp/references/technical-guide): header version u32 | sourceDomain u32 | destinationDomain u32 |
    nonce bytes32 | sender bytes32 | recipient bytes32 | destinationCaller bytes32 | minFinalityThreshold u32 |
    finalityThresholdExecuted u32 | body; BurnMessageV2 body version u32 | burnToken bytes32 | mintRecipient bytes32 |
    amount u256 | messageSender bytes32 | maxFee u256 | feeExecuted u256 | expirationBlock u256 | hookData. Thresholds:
    1000 confirmed (Fast), 2000 finalized (Standard). CCTP V1 deprecation runs 31 Oct to 1 Dec 2026 (migration guide):
    V2 only.

The flow Knos runs:
  1. Knos tells the funder the order's wallet and its USDC token account (`plan`): mintRecipient = that token account,
     destinationDomain 5, hookData = "knos:order:v1" + the order's scope (32 bytes) + the terms hash (32 bytes), so the
     burn names the order it pays for (depositForBurnWithHook).
  2. The funder burns on the EVM chain with their own wallet (Knos signs nothing there).
  3. Knos polls Iris for the message (`attestation`), checks the decoded message against the plan (`check`): domain 5,
     the right token account, the amount net of the fee executed, the hookData.
  4. receiveMessage on Solana mints into the funder's own token account (anyone may submit it); then the funder's
     FundOrderWallet moves it into vault, which the funder signs, or signs ahead with a durable nonce
     (knos.platform.nonce) so the whole thing completes unattended once the mint lands.
Step 4's receiveMessage instruction (Anchor, with the token messenger's remaining accounts) is not built here: it is
the next step once a testnet transfer can be made.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass

from solders.pubkey import Pubkey

DOMAINS = {"ethereum": 0, "avalanche": 1, "op": 2, "arbitrum": 3, "solana": 5, "base": 6, "polygon": 7, "arc": 26}
MESSAGE_TRANSMITTER_V2 = Pubkey.from_string("CCTPV2Sm4AdWt5296sk4P66VBZ7bEhcARwFaaS9YPbeC")
TOKEN_MESSENGER_MINTER_V2 = Pubkey.from_string("CCTPV2vPZJS2u2BBsUoscuikbYjnpFmbFsvVuJdgUMQe")
IRIS = {"sandbox": "https://iris-api-sandbox.circle.com", "mainnet": "https://iris-api.circle.com"}
FAST, STANDARD = 1000, 2000
HOOK_TAG = b"knos:order:v1"


def bytes32(key: Pubkey) -> str:
    """A Solana address as the 0x-prefixed 32 bytes an EVM depositForBurn takes."""
    return "0x" + bytes(key).hex()


def hook_data(scope: bytes, terms_hash: bytes) -> bytes:
    if len(scope) != 32 or len(terms_hash) != 32:
        raise ValueError("the scope and the terms hash are 32 bytes each")
    return HOOK_TAG + scope + terms_hash


@dataclass(frozen=True)
class Plan:
    destination_domain: int
    mint_recipient: str          # bytes32 hex of the funder's USDC token account on Solana
    hook_data: str               # hex
    amount: int                  # what must arrive, in USDC's smallest units (6 decimals)
    max_fee: int
    min_finality: int


def plan(funder_token: Pubkey, scope: bytes, terms_hash: bytes, amount: int, max_fee: int = 0, fast: bool = False) -> Plan:
    """What the funder's depositForBurnWithHook must carry for Knos to take the arriving USDC as this order's money."""
    return Plan(DOMAINS["solana"], bytes32(funder_token), hook_data(scope, terms_hash).hex(), amount + max_fee, max_fee, FAST if fast else STANDARD)


@dataclass(frozen=True)
class Message:
    version: int
    source_domain: int
    destination_domain: int
    nonce: bytes
    sender: bytes
    recipient: bytes
    destination_caller: bytes
    min_finality: int
    finality_executed: int
    burn_token: bytes
    mint_recipient: bytes
    amount: int
    message_sender: bytes
    max_fee: int
    fee_executed: int
    expiration_block: int
    hook_data: bytes


def decode(message_hex: str) -> Message:
    m = bytes.fromhex(message_hex[2:] if message_hex.startswith("0x") else message_hex)
    if len(m) < 148 + 228:
        raise ValueError("too short for a CCTP V2 burn message")
    def u32(a: int) -> int:
        return int.from_bytes(m[a:a + 4], "big")

    def u256(a: int) -> int:
        return int.from_bytes(m[a:a + 32], "big")
    b = 148
    return Message(u32(0), u32(4), u32(8), m[12:44], m[44:76], m[76:108], m[108:140], u32(140), u32(144),
                   m[b + 4:b + 36], m[b + 36:b + 68], u256(b + 68), m[b + 100:b + 132], u256(b + 132), u256(b + 164), u256(b + 196),
                   m[b + 228:])


def check(msg: Message, want: Plan) -> list[str]:
    """Why an attested message does not fund the planned order; empty when it does."""
    out = []
    if msg.destination_domain != want.destination_domain:
        out.append(f"the message goes to domain {msg.destination_domain}, not Solana (5)")
    if "0x" + msg.mint_recipient.hex() != want.mint_recipient:
        out.append("the minted USDC goes to another token account")
    if msg.amount - msg.fee_executed < want.amount - want.max_fee:
        out.append(f"{msg.amount - msg.fee_executed} arrives, the order needs {want.amount - want.max_fee}")
    if msg.hook_data.hex() != want.hook_data:
        out.append("the hook data names another order")
    return out


def attestation(source_domain: int, tx_hash: str, env: str = "sandbox", fetch=None) -> dict | None:
    """The first message of a burn transaction as Iris has it: {message, attestation, status, decodedMessage}; None
    while Iris has not seen it. `fetch(url) -> (status, body)` stands in for the network in tests."""
    url = f"{IRIS[env]}/v2/messages/{source_domain}?transactionHash={tx_hash}"
    if fetch is None:
        def fetch(u):
            try:
                with urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "knos"}), timeout=20) as r:  # noqa: S310
                    return r.status, r.read()
            except urllib.error.HTTPError as e:
                return e.code, e.read()
    status, body = fetch(url)
    if status == 404:
        return None
    if status != 200:
        raise RuntimeError(f"Iris answered {status}")
    msgs = json.loads(body).get("messages") or []
    return msgs[0] if msgs else None


def ready(got: dict | None) -> bool:
    if not got:
        return False
    return got.get("status") == "complete" and got.get("attestation") not in (None, "", "PENDING")
