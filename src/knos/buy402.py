"""Pay for one thing over x402, and hand back what was bought.

The buying half of `pay.py`. That module sells an answer out of this
machine's memory; this one spends a penny on somebody else's endpoint so the
agent can bring something back that was not already here.

Nothing about the protocol is reimplemented: the 402, the signature, the
retry and the settlement are all the official client's. What this adds is the
part that matters to knos — the bought content is returned to the caller so
it can be written into the store, where the next agent gets it for free.

    python -m knos.buy402 <url> [json-body]

Prints JSON: {"ok", "content", "paid", "tx", "payer", "network", "why"}.
Never raises at the top level, because the caller is a bot answering a person
and a stack trace is not an answer.

`paid` is the settlement header exactly as the facilitator sent it, and it is
base64 of a JSON object. `tx` and `payer` are that object already opened, so
nothing downstream has to know the encoding to link a payment to the chain.
Storing only the encoded blob is what let a truncated receipt sit in the
store looking complete: cut base64 still decodes, just to a shorter hash.

The key comes from ~/.knos-keys/bot.json, outside the repository. This file
never holds one and never prints one.
"""

from __future__ import annotations

import asyncio
import base64
import json

import httpx
import os
import sys
from pathlib import Path
from typing import Any

# Path("") is Path("."), which is truthy, so the empty env var cannot be
# used as the falsy branch of an `or`.
_named = os.environ.get("KNOS_BOT_SETTINGS", "").strip()
SETTINGS = Path(_named) if _named else Path.home() / ".knos-keys" / "bot.json"


_V1_NAME = {"eip155:8453": "base", "eip155:84532": "base-sepolia"}


def _settings() -> dict[str, Any]:
    return json.loads(SETTINGS.read_text(encoding="utf-8")) if SETTINGS.exists() else {}


def _key() -> bytes:
    """The key knos already made, decrypted here and nowhere else.

    knos generates its own wallet the first time `knos share` runs, and that
    keystore is what deployed Access.sol and signed every grant since. There
    is no reason to ask a person to paste a private key into a settings file
    when the machine already holds one it made itself: one fewer copy of a
    secret, and one fewer thing to get wrong.

    `payerPrivateKey` in bot.json still wins if it is set, for anyone who
    wants to pay from a different wallet than the one knos shares from.
    """
    from eth_account import Account

    told = str(_settings().get("payerPrivateKey", "")).strip()
    if told:
        return bytes.fromhex(told.removeprefix("0x"))

    from . import team

    keystore = team.keys_dir() / "owner"
    password = team.keys_dir() / "password"
    if not (keystore.exists() and password.exists()):
        raise ValueError(
            f"no wallet: neither payerPrivateKey in {SETTINGS} nor a keystore"
            f" at {keystore}. `knos share` makes one."
        )
    return Account.decrypt(
        keystore.read_text(encoding="utf-8"),
        password.read_text(encoding="utf-8").strip(),
    )


def address() -> str:
    """Which wallet will pay. Safe to print; the key is not."""
    from eth_account import Account

    return Account.from_key(_key()).address


async def _buy(
    url: str, key: bytes, network: str, body: dict[str, Any] | None = None
) -> dict[str, Any]:
    from eth_account import Account
    from x402 import x402Client
    from x402.http.clients.httpx import wrapHttpxWithPayment
    from x402.mechanisms.evm.exact import register_exact_evm_client
    from x402.mechanisms.evm.signers import EthAccountSigner

    signer = EthAccountSigner(Account.from_key(key))
    # One helper registers both protocol versions: v2 under `eip155:*` and v1
    # under every EVM network name it knows. Sellers disagree about which they
    # speak - `/brief` is v2, the news search is v1 - and hand-registering one
    # scheme meant the other was unreachable.
    client = register_exact_evm_client(x402Client(), signer)

    # The transport's own 402 retry does not fire for every v1 seller, so the
    # handshake is done here: ask, read the requirements from header or body,
    # sign, ask again with the header the seller's version expects.
    from x402.http.x402_http_client import x402HTTPClient

    helper = x402HTTPClient(client)

    async with httpx.AsyncClient(timeout=90.0) as http:
        # Some sellers take a GET with query params, some a POST with a body.
        # Both are one call; the difference is not worth two code paths in the
        # caller, so it is decided here by whether a body was given.
        async def ask(headers: dict[str, str] | None = None) -> Any:
            return (
                await http.post(url, json=body, headers=headers)
                if body is not None
                else await http.get(url, headers=headers)
            )

        reply = await ask()
        if reply.status_code == 402:
            try:
                asked = reply.json()
            except Exception:  # noqa: BLE001 - a seller may send no body
                asked = None
            need = helper.get_payment_required_response(reply.headers.get, asked)
            payload = await client.create_payment_payload(need)
            reply = await ask(helper.encode_payment_signature_header(payload))

        # v2 answers in `payment-response`, v1 in `x-payment-response`.
        paid = (
            reply.headers.get("payment-response")
            or reply.headers.get("x-payment-response")
            or ""
        )
        settled = _settlement(paid)
        if reply.status_code >= 400:
            return {
                "ok": False,
                "content": "",
                "paid": paid,
                **settled,
                "why": f"HTTP {reply.status_code}",
            }
        return {"ok": True, "content": reply.text, "paid": paid, **settled, "why": ""}


def _settlement(header: str) -> dict[str, str]:
    """The transaction hash out of the settlement header, or empty strings.

    The header is base64 of a JSON object the facilitator writes; the field
    that matters is the transaction hash, because that is the one thing a
    person can paste into a block explorer. Everything here is best-effort:
    a payment that settled but whose receipt will not decode is still a
    payment, and refusing to report it would be worse than reporting it
    without the hash.
    """
    if not header:
        return {"tx": "", "payer": "", "network": ""}
    raw = header.strip()
    # Tolerate missing padding: some facilitators strip it, and base64 that
    # is one or two characters short of a multiple of four is otherwise a
    # hard decode failure for no reason.
    raw += "=" * (-len(raw) % 4)
    try:
        opened = json.loads(base64.b64decode(raw).decode("utf-8"))
    except Exception:  # noqa: BLE001 - any malformed receipt lands here
        return {"tx": "", "payer": "", "network": ""}
    if not isinstance(opened, dict):
        return {"tx": "", "payer": "", "network": ""}
    return {
        "tx": str(opened.get("transaction") or ""),
        "payer": str(opened.get("payer") or ""),
        "network": str(opened.get("network") or ""),
    }


def main(argv: list[str]) -> int:
    url = argv[1] if len(argv) > 1 else ""
    body = None
    if len(argv) > 2 and argv[2].strip():
        body = json.loads(argv[2])
    said: dict[str, Any] = {"ok": False, "content": "", "paid": "", "why": "", "from": ""}
    try:
        if not url:
            raise ValueError("give a url to buy from")
        network = str(_settings().get("payNetwork", "eip155:8453"))
        said = asyncio.run(_buy(url, _key(), network, body))
        said["from"] = address()
    except Exception as why:  # noqa: BLE001 - the caller is a chat message
        said["why"] = f"{type(why).__name__}: {why}"
    print(json.dumps(said))
    return 0 if said["ok"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
