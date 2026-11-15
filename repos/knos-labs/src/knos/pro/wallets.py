"""An agent's own budget wallet, on Solana (USDC) or Tempo (pathUSD).

An agent that pays for APIs (x402 on Solana, MPP on Tempo) signs only from its own wallet. The wallet holds what you
funded it with and nothing else, so the most the agent can ever spend is its balance: the chain enforces the cap, even
if Knos itself is bypassed. Knos adds a softer cap on top (`knos budget`), refused before anything is signed.

    ~/.knos/wallets/<agent>.<chain>.json   the key, owner-only (0600), never printed, never inside a repo

Funding is done by you, from your wallet, with the link `knos budget fund` prints. `knos budget sweep` sends what is
left back to you.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from .. import paths
from . import solana, tempo

CHAINS = ("solana", "tempo")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")


class NeedsExtra(Exception):
    """The optional agent-payment libraries are not installed."""


def wallet_dir() -> Path:
    d = paths.home() / "wallets"
    d.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(d, 0o700)
    except OSError:
        pass
    return d


def key_file(agent: str, chain: str) -> Path:
    if not _ID.match(agent or ""):
        raise ValueError("an agent id is letters, digits, '.', '_' or '-', up to 64 characters")
    if chain not in CHAINS:
        raise ValueError(f"chain must be one of {', '.join(CHAINS)}")
    return wallet_dir() / f"{agent}.{chain}.json"


def _write_secret(path: Path, body: dict) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(body, fh)


def _new_solana() -> dict:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    key = Ed25519PrivateKey.generate()
    seed = key.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
                             serialization.NoEncryption())
    pub = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    # the Solana CLI keypair layout: 64 bytes, seed then public key
    return {"address": solana.b58encode(pub), "keypair": list(seed + pub)}


def _new_tempo() -> dict:
    try:
        from eth_account import Account
    except ImportError as why:
        raise NeedsExtra("Tempo wallets need the agent-payment extra:  pipx inject knos 'knos[agentpay]'") from why
    acct = Account.create()
    return {"address": acct.address, "private_key": acct.key.hex()}


def create(agent: str, chain: str) -> str:
    """Make the agent's wallet if it has none; return its public address. The key is never returned or printed."""
    path = key_file(agent, chain)
    if path.exists():
        return address(agent, chain)
    body = _new_solana() if chain == "solana" else _new_tempo()
    body["agent"], body["chain"] = agent, chain
    _write_secret(path, body)
    return body["address"]


def address(agent: str, chain: str) -> str:
    return json.loads(key_file(agent, chain).read_text(encoding="utf-8"))["address"]


def _secret(agent: str, chain: str) -> dict:
    return json.loads(key_file(agent, chain).read_text(encoding="utf-8"))


def listed() -> list[dict]:
    got = []
    for f in sorted(wallet_dir().glob("*.json")):
        try:
            body = json.loads(f.read_text(encoding="utf-8"))
            got.append({"agent": body["agent"], "chain": body["chain"], "address": body["address"]})
        except (OSError, ValueError, KeyError):
            continue
    return got


def fund_link(agent: str, chain: str, amount: float, network: str) -> str:
    """A payment request that sends `amount` stablecoin from the user's own wallet to the agent's."""
    to = address(agent, chain)
    if chain == "solana":
        ref = solana.new_reference()
        return solana.link("fund", amount, ref, network, order=agent[:16], recipient=to,
                           message="Knos agent budget")
    units = int(round(amount * 10 ** tempo.DECIMALS))
    return f"ethereum:{tempo.TOKENS[network]['pathUSD']}@{tempo.CHAINS[network]['id']}/transfer?address={to}&uint256={units}"


def balance(agent: str, chain: str, network: str) -> float:
    """The agent wallet's stablecoin balance, read from the chain (public RPC)."""
    owner = address(agent, chain)
    if chain == "solana":
        got = solana.rpc(network, "getTokenAccountsByOwner",
                         [owner, {"mint": solana.USDC[network]}, {"encoding": "jsonParsed"}]) or {}
        units = 0
        for acct in got.get("value", []):
            info = ((acct.get("account") or {}).get("data") or {}).get("parsed", {}).get("info", {})
            units += int((info.get("tokenAmount") or {}).get("amount") or 0)
        return units / 10 ** solana.USDC_DECIMALS
    data = "0x70a08231" + owner.lower()[2:].rjust(64, "0")
    raw = tempo.rpc(network, "eth_call", [{"to": tempo.TOKENS[network]["pathUSD"], "data": data}, "latest"])
    return int(raw or "0x0", 16) / 10 ** tempo.DECIMALS


def sweep(agent: str, chain: str, network: str, to: str) -> dict:
    """Send the agent wallet's whole stablecoin balance back to `to`. Returns {amount, tx}."""
    amount = balance(agent, chain, network)
    if amount <= 0:
        return {"amount": 0.0, "tx": ""}
    if chain == "tempo":
        if not tempo.is_address(to):
            raise ValueError("a Tempo address is 0x followed by 40 hex characters")
        return {"amount": amount, "tx": _sweep_tempo(agent, network, to, amount)}
    if not solana.is_address(to):
        raise ValueError("that is not a Solana address")
    return {"amount": amount, "tx": _sweep_solana(agent, network, to, amount)}


def _sweep_tempo(agent: str, network: str, to: str, amount: float) -> str:
    """A TIP-20 transfer signed by the agent's key (a Tempo 0x76 transaction, fees paid in pathUSD), via pympp."""
    import asyncio

    try:
        from mpp.methods.tempo import ChargeIntent, TempoAccount
        from mpp.methods.tempo import tempo as tempo_method
    except ImportError as why:
        raise NeedsExtra("Sweeping a Tempo wallet needs:  pipx inject knos 'knos[agentpay]'") from why
    chain_id = tempo.CHAINS[network]["id"]
    m = tempo_method(account=TempoAccount.from_key(tempo_key(agent)), chain_id=chain_id,
                     intents={"charge": ChargeIntent()})
    # leave a cent for the fee, which Tempo takes in the same stablecoin
    units = max(int(amount * 10 ** tempo.DECIMALS) - 10_000, 0)
    raw, _ = asyncio.run(m._build_tempo_transfer(amount=str(units), currency=tempo.TOKENS[network]["pathUSD"],
                                                 recipient=to, rpc_url=tempo.rpc_url(network),
                                                 expected_chain_id=chain_id))
    return str(tempo.rpc(network, "eth_sendRawTransaction", [raw]))


def _sweep_solana(agent: str, network: str, to: str, amount: float) -> str:
    """SPL TransferChecked from the agent's USDC account to the recipient's (created if missing). The agent wallet
    pays the network fee, so it needs a little SOL; say so plainly if it has none."""
    try:
        from solders.hash import Hash
        from solders.instruction import AccountMeta, Instruction
        from solders.message import MessageV0
        from solders.pubkey import Pubkey
        from solders.transaction import VersionedTransaction
    except ImportError as why:
        raise NeedsExtra("Sweeping a Solana wallet needs solders:  pip install -U knos") from why
    from . import sol_budget as sb
    token_program = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"  # USDC is a classic SPL token
    kp = solana_keypair(agent)
    owner = kp.pubkey()
    mint = Pubkey.from_string(solana.USDC[network])
    src = sb.ata(owner, mint)
    dst = sb.ata(Pubkey.from_string(to), mint)
    ata_program = Pubkey.from_string("ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL")
    system = Pubkey.from_string("11111111111111111111111111111111")
    tok = Pubkey.from_string(token_program)
    create = Instruction(ata_program, bytes([1]), [  # CreateIdempotent
        AccountMeta(owner, True, True), AccountMeta(dst, False, True), AccountMeta(Pubkey.from_string(to), False, False),
        AccountMeta(mint, False, False), AccountMeta(system, False, False), AccountMeta(tok, False, False)])
    units = int(round(amount * 10 ** solana.USDC_DECIMALS))
    transfer = Instruction(tok, bytes([12]) + units.to_bytes(8, "little") + bytes([solana.USDC_DECIMALS]), [
        AccountMeta(src, False, True), AccountMeta(mint, False, False), AccountMeta(dst, False, True),
        AccountMeta(owner, True, False)])
    blockhash = Hash.from_string(solana.rpc(network, "getLatestBlockhash", [{"commitment": "confirmed"}])["value"]
                                 ["blockhash"])
    msg = MessageV0.try_compile(owner, [create, transfer], [], blockhash)
    tx = VersionedTransaction(msg, [kp])
    import base64

    lamports = int((solana.rpc(network, "getBalance", [str(owner)]) or {}).get("value", 0))
    if lamports < 5000:
        raise ValueError(f"the agent wallet {owner} has no SOL for the network fee; send it 0.001 SOL, then sweep")
    return str(solana.rpc(network, "sendTransaction", [base64.b64encode(bytes(tx)).decode(), {"encoding": "base64"}]))


def solana_keypair(agent: str):
    """The agent's key as a solders Keypair, for signing x402 payments and sweeps. Never logged."""
    from solders.keypair import Keypair
    return Keypair.from_bytes(bytes(_secret(agent, "solana")["keypair"]))


def tempo_key(agent: str) -> str:
    """The agent's Tempo private key, for signing inside the MPP client. Never logged."""
    return _secret(agent, "tempo")["private_key"]
