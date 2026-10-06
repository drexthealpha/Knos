import asyncio
import time
import logging
from dataclasses import dataclass
from typing import Optional

import httpx
from solders.keypair import Keypair
from solders.pubkey import Pubkey

logger = logging.getLogger(__name__)


@dataclass
class RelayStats:
    tokens: set = None

    def __post_init__(self) -> None:
        if self.tokens is None:
            self.tokens = set()

    def record(self, token: str) -> None:
        self.tokens.add(token)


class KnosRelay:
    """
    Relay that monitors Solana transactions and logs tokens it relays.
    """

    def __init__(
        self,
        wsol: Pubkey,
        raydium_amm: Pubkey,
        rpc_url: str,
        keypair: Optional[Keypair] = None,
        poll_interval: float = 1.0,
    ) -> None:
        self.wsol = wsol
        self.raydium_amm = raydium_amm
        self.rpc_url = rpc_url
        self.keypair = keypair or Keypair()
        self.poll_interval = poll_interval
        self.stats = RelayStats()
        self._running = False
        self._task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._relay_loop())
        logger.info("KnosRelay started")

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("KnosRelay stopped")

    async def _relay_loop(self) -> None:
        async with httpx.AsyncClient() as client:
            while self._running:
                try:
                    await self._check_new_transfers(client)
                except Exception as exc:
                    logger.error("Relay error: %s", exc)
                await asyncio.sleep(self.poll_interval)

    async def _check_new_transfers(self, client: httpx.AsyncClient) -> None:
        sign_time = int(time.time()) - 30
        resp = await client.get(
            f"{self.rpc_url}",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getSignaturesForAddress",
                "params": [str(self.wsol), {"limit": 20, "before": sign_time}],
            },
            timeout=10,
        )
        data = resp.json()
        signatures: list[dict] = data.get("result", [])
        for sig_info in signatures:
            sig = sig_info.get("signature")
            if not sig:
                continue
            await self._process_signature(client, sig)

    async def _process_signature(self, client: httpx.AsyncClient, sig: str) -> None:
        resp = await client.post(
            self.rpc_url,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getTransaction",
                "params": [
                    sig,
                    {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0},
                ],
            },
            timeout=10,
        )
        data = resp.json()
        tx = data.get("result", {}).get("transaction", {})
        if not tx:
            return
        meta = tx.get("meta", {}) or {}
        for inner in meta.get("innerInstructions", []) or []:
            for inst in inner.get("instructions", []) or []:
                program_id = inst.get("programId", "")
                accounts = inst.get("accounts", [])
                if program_id == str(self.raydium_amm) and len(accounts) >= 8:
                    token_account = accounts[7]
                    await self._on_relayed_token(token_account, sig)

    async def _on_relayed_token(self, token_account: str, signature: str) -> None:
        self.stats.record(token_account)
        logger.info("relay %s", token_account)

    def get_tokens(self) -> list[str]:
        return sorted(self.stats.tokens)

    def reset(self) -> None:
        self.stats = RelayStats()
        logger.info("Relay stats reset")
