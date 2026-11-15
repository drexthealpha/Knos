"""An agent pays for an API over HTTP 402, from its own budget wallet, inside its Knos cap.

Two protocols: MPP through its reference SDK (the optional `knos[agentpay]` extra), x402 built here with solders:

  MPP on Tempo   pympp (github.com/tempoxyz/pympp): the server answers 402 with `WWW-Authenticate: Payment ...`;
                 the client signs a TIP-20 transfer and retries with `Authorization: Payment ...`.
                 Spec: https://mpp.dev/protocol , https://mpp.dev/payment-methods/tempo/charge
  x402 on Solana the x402 v2 `exact` scheme (github.com/x402-foundation/x402), built here with solders exactly as
                 the reference client builds it: the server answers 402 with its payment requirements; the client
                 signs an SPL TransferChecked (the facilitator pays the fee) and retries with PAYMENT-SIGNATURE.

Two limits, in this order, before anything is signed:
  1. Knos's cap for this agent (`knos budget fund` sets it): what it has spent, from the ledger in
     ~/.knos/agentpay.db, plus this payment, must not exceed it. The asset must be the stablecoin the wallet holds.
  2. The chain: the agent signs from its own wallet, which holds only what you funded it with. Even with Knos
     bypassed, it cannot spend more than that balance.
"""

from __future__ import annotations

import asyncio
import sqlite3
import time
from dataclasses import dataclass
from typing import Any

from .. import paths
from . import budget, solana, tempo, wallets

SOLANA_CAIP2 = {"mainnet": "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp",
                "devnet": "solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1"}


class Refused(Exception):
    """Knos refused to sign: no wallet, over the cap, wrong asset or network. Nothing was signed."""


@dataclass
class Paid:
    status: int
    paid: float
    chain: str
    body: str
    receipt: str = ""


# ---- the ledger -------------------------------------------------------------------------

def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(paths.home() / "agentpay.db"), timeout=10, isolation_level=None)
    conn.execute("PRAGMA busy_timeout = 10000")
    conn.execute("CREATE TABLE IF NOT EXISTS payments (ts REAL, agent TEXT, chain TEXT, network TEXT, url TEXT, "
                 "amount REAL, status TEXT)")
    return conn


def spent(agent: str | None = None, since: float = 0.0) -> float:
    conn = _db()
    try:
        sql, args = "SELECT COALESCE(SUM(amount), 0) FROM payments WHERE status IN ('signed','paid') AND ts >= ?", [since]
        if agent:
            sql += " AND agent = ?"
            args.append(agent)
        return float(conn.execute(sql, args).fetchone()[0])
    finally:
        conn.close()


def _record(agent: str, chain: str, network: str, url: str, amount: float, status: str) -> None:
    conn = _db()
    try:
        conn.execute("INSERT INTO payments VALUES (?,?,?,?,?,?,?)", (time.time(), agent, chain, network, url,
                                                                    amount, status))
    finally:
        conn.close()


# ---- the gate: runs before any signature ------------------------------------------------------

def agent_config(agent: str) -> dict:
    got = (budget.agents() or {}).get(agent)
    if not got:
        raise Refused(f"knos: agent {agent} has no budget wallet. A person sets one up: "
                      f"knos budget fund --agent {agent} 5 --chain tempo")
    return got


def gate(agent: str, chain: str, network: str, asset: str, amount: float, url: str) -> None:
    """Refuse unless this payment fits the agent's Knos cap, on its chain, network and stablecoin."""
    cfg = agent_config(agent)
    if cfg["chain"] != chain:
        raise Refused(f"knos: {agent}'s budget wallet is on {cfg['chain']}; this API asks for {chain}.")
    if cfg.get("network", "mainnet") != network:
        raise Refused(f"knos: {agent}'s wallet is on {cfg.get('network')}; this API asks for {network}.")
    ok_assets = ({a.lower() for a in tempo.TOKENS[network].values()} if chain == "tempo"
                 else {solana.USDC[network].lower()})
    if asset.lower() not in ok_assets:
        raise Refused(f"knos: this API wants to be paid in {asset}, which is not the stablecoin in {agent}'s wallet.")
    used = spent(agent)
    if used + amount > float(cfg["cap"]) + 1e-9:
        raise Refused(f"knos: {agent} has spent {used:g} of its {float(cfg['cap']):g} cap; this payment of "
                      f"{amount:g} would go past it. A person can raise it: knos budget fund --agent {agent} ...")
    over = budget.refusal()
    if over:
        raise Refused(over)
    _record(agent, chain, network, url, amount, "signed")


# ---- the two protocols ------------------------------------------------------------------------

def _need(module: str) -> None:
    import importlib.util

    if importlib.util.find_spec(module) is None:
        raise Refused("knos: agent payments need the optional libraries:  pipx inject knos 'knos[agentpay]'")


async def _pay_tempo(agent: str, url: str, method: str, body: bytes | None, network: str) -> Paid:
    _need("mpp")
    import httpx
    from mpp.client import Client
    from mpp.methods.tempo import ChargeIntent, TempoAccount
    from mpp.methods.tempo import tempo as tempo_method

    chain_id = tempo.CHAINS[network]["id"]
    m = tempo_method(account=TempoAccount.from_key(wallets.tempo_key(agent)), chain_id=chain_id,
                     intents={"charge": ChargeIntent()})
    signed: dict[str, float] = {}
    original = m.create_credential

    async def guarded(challenge: Any) -> Any:
        req = challenge.request or {}
        amount = int(str(req.get("amount", "0"))) / 10 ** tempo.DECIMALS
        gate(agent, "tempo", network, str(req.get("currency", "")), amount, url)
        signed["amount"] = amount
        return await original(challenge)

    m.create_credential = guarded  # type: ignore[method-assign]
    async with Client(methods=[m]) as client:
        try:
            resp: httpx.Response = await client.request(method, url, content=body)
        except Refused:
            raise
        except Exception as why:
            if type(why).__name__ == "PaymentOutcomeUnknownError":
                raise Refused(f"knos: a payment of {signed.get('amount', 0):g} was sent but the API did not answer, so "
                              "whether it went through is unknown. It is counted against the cap. Check the agent "
                              "wallet (knos budget agents) before trying again.") from why
            raise
    return Paid(resp.status_code, signed.get("amount", 0.0), "tempo", resp.text[:4000],
                resp.headers.get("payment-receipt", ""))


def _x402_payment(agent: str, accepted: dict, resource: Any, network: str) -> tuple[dict, float]:
    """The x402 v2 `exact` scheme on Solana, as the reference client builds it (x402-foundation/x402,
    mechanisms/svm/exact/client.py): compute-unit limit and price, an SPL TransferChecked from the agent's token account
    to the payee's, and a memo; the facilitator is the fee payer (signature 0, left empty) and the agent signs as the
    token owner (signature 1). Built with solders alone, so no `solana` package (and its solders pin) is needed."""
    import base64
    import os

    from solders.hash import Hash
    from solders.instruction import AccountMeta, Instruction
    from solders.message import MessageV0
    from solders.pubkey import Pubkey
    from solders.signature import Signature
    from solders.transaction import VersionedTransaction

    from . import sol_budget as sb
    extra = accepted.get("extra") or {}
    if not extra.get("feePayer"):
        raise Refused("knos: this x402 API names no fee payer")
    key = wallets.solana_keypair(agent)
    mint = Pubkey.from_string(accepted["asset"])
    units = int(accepted.get("amount") or accepted.get("maxAmountRequired"))
    budget_ = Pubkey.from_string("ComputeBudget111111111111111111111111111111")
    memo = (extra.get("memo") or "").encode() or os.urandom(16).hex().encode()
    ixs = [Instruction(budget_, bytes([2]) + (20_000).to_bytes(4, "little"), []),
           Instruction(budget_, bytes([3]) + (1).to_bytes(8, "little"), []),
           Instruction(sb.TOKEN_PROGRAM, bytes([12]) + units.to_bytes(8, "little") + bytes([solana.USDC_DECIMALS]),
                       [AccountMeta(sb.ata(key.pubkey(), mint), False, True), AccountMeta(mint, False, False),
                        AccountMeta(sb.ata(Pubkey.from_string(accepted["payTo"]), mint), False, True),
                        AccountMeta(key.pubkey(), True, False)]),
           Instruction(sb.MEMO_PROGRAM, memo, [])]
    if extra.get("recentBlockhash"):
        blockhash = Hash.from_string(extra["recentBlockhash"])
    else:
        from ..team import rpc
        blockhash = rpc.latest_blockhash(solana.rpc_url(network))
    msg = MessageV0.try_compile(Pubkey.from_string(extra["feePayer"]), ixs, [], blockhash)
    tx = VersionedTransaction.populate(msg, [Signature.default(), key.sign_message(bytes([0x80]) + bytes(msg))])
    payload = {"x402Version": 2, "payload": {"transaction": base64.b64encode(bytes(tx)).decode()},
               "accepted": accepted}
    if resource:
        payload["resource"] = resource
    return payload, units / 10 ** solana.USDC_DECIMALS


async def _pay_x402(agent: str, url: str, method: str, body: bytes | None, network: str) -> Paid:
    import base64
    import json

    import httpx
    async with httpx.AsyncClient(timeout=30) as http:
        first = await http.request(method, url, content=body)
        if first.status_code != 402:
            return Paid(first.status_code, 0.0, "solana", first.text[:4000])
        header = first.headers.get("payment-required")
        required = json.loads(base64.b64decode(header)) if header else first.json()
        offers = [a for a in required.get("accepts", []) if a.get("scheme") == "exact"
                  and str(a.get("network")) == SOLANA_CAIP2[network]]
        if not offers:
            raise Refused(f"knos: this API asks for {[a.get('network') for a in required.get('accepts', [])]}, "
                          f"not Solana {network}")
        accepted = offers[0]
        amount = int(accepted.get("amount") or accepted.get("maxAmountRequired")) / 10 ** solana.USDC_DECIMALS
        gate(agent, "solana", network, str(accepted["asset"]), amount, url)   # raises Refused before signing
        payload, amount = _x402_payment(agent, accepted, required.get("resource"), network)
        sig = base64.b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode()
        resp = await http.request(method, url, content=body, headers={"PAYMENT-SIGNATURE": sig})
    return Paid(resp.status_code, amount, "solana", resp.text[:4000], resp.headers.get("payment-response", ""))


def protocol_of(resp: Any) -> str | None:
    """Which 402 this is: 'mpp' (WWW-Authenticate: Payment), 'x402', or None when it is not a payment request."""
    if resp.status_code != 402:
        return None
    for h in resp.headers.get_list("www-authenticate") if hasattr(resp.headers, "get_list") else []:
        if h.strip().lower().startswith("payment"):
            return "mpp"
    if resp.headers.get("payment-required"):
        return "x402"
    try:
        body = resp.json()
    except Exception:
        body = {}
    if isinstance(body, dict) and ("accepts" in body or "x402Version" in body):
        return "x402"
    return None


def pay(agent: str, url: str, method: str = "GET", body: bytes | None = None) -> Paid:
    """Fetch `url`; if it asks for payment, pay it from `agent`'s wallet within its cap, and return the answer."""
    import httpx

    cfg = agent_config(agent)
    network = cfg.get("network", "mainnet")
    with httpx.Client(timeout=30) as http:
        first = http.request(method, url, content=body)
    kind = protocol_of(first)
    if kind is None:
        return Paid(first.status_code, 0.0, "", first.text[:4000])
    if kind == "mpp":
        if cfg["chain"] != "tempo":
            raise Refused(f"knos: this API is paid over MPP (Tempo); {agent}'s wallet is on {cfg['chain']}.")
        return asyncio.run(_pay_tempo(agent, url, method, body, network))
    if cfg["chain"] != "solana":
        raise Refused(f"knos: this API is paid over x402 (Solana); {agent}'s wallet is on {cfg['chain']}.")
    return asyncio.run(_pay_x402(agent, url, method, body, network))


def summary() -> list[dict]:
    """Per agent: chain, network, cap and what has been signed."""
    out = []
    for name, cfg in (budget.agents() or {}).items():
        out.append({"agent": name, **cfg, "spent": spent(name)})
    return out
