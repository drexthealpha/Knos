"""POST /gas {pubkey}: 0.01 devnet SOL for a browser's throwaway gas key (the passkey wallet in web/wallet.js), so a
first visit needs no extension, no seed phrase and no SOL of its own.

Devnet only. Opt-in: `knos jobs serve --gas-key <keypair.json>` (or KNOS_GAS_KEY_FILE); without a key the endpoint
answers 503 and the server still holds no key. Rate-limited in memory: one top-up per gas key per day, PER_IP per
address per hour, and never to a key that already has the amount. The key is never logged or returned.
"""

from __future__ import annotations

import threading
import time

from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.system_program import TransferParams, transfer

LAMPORTS = 10_000_000          # 0.01 SOL
PER_IP = 5                     # per hour
KEY_PERIOD = 24 * 3600
IP_PERIOD = 3600


class GasError(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code


class Gas:
    def __init__(self, ledger, key: Keypair | None, cluster: str = "devnet", clock=time.time):
        self.ledger, self.key, self.cluster, self.clock = ledger, key, cluster, clock
        self.by_key: dict[str, float] = {}
        self.by_ip: dict[str, list[float]] = {}
        self.lock = threading.Lock()

    def balance(self, who: Pubkey) -> int:
        get = getattr(self.ledger, "lamports", None)
        if get is not None:
            return int(get(who))
        import json
        import urllib.request
        req = urllib.request.Request(self.ledger.url, json.dumps({"jsonrpc": "2.0", "id": 1, "method": "getBalance",
                                                                  "params": [str(who)]}).encode(),
                                     {"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as r:
            return int(json.loads(r.read())["result"]["value"])

    def top_up(self, body: dict, ip: str) -> dict:
        if self.cluster != "devnet":
            raise GasError(403, "gas is devnet only")
        if self.key is None:
            raise GasError(503, "this server has no gas key")
        try:
            who = Pubkey.from_string(str(body.get("pubkey", "")))
        except Exception:  # noqa: BLE001
            raise GasError(400, "pubkey: a base58 Solana address") from None
        now = self.clock()
        with self.lock:
            if now - self.by_key.get(str(who), -1e18) < KEY_PERIOD:
                raise GasError(429, "this key was topped up in the last day")
            hits = [t for t in self.by_ip.get(ip, []) if now - t < IP_PERIOD]
            if len(hits) >= PER_IP:
                raise GasError(429, "too many top-ups from this address; try again in an hour")
            if self.balance(who) >= LAMPORTS:
                raise GasError(409, "this key already has gas")
            self.by_key[str(who)] = now
            self.by_ip[ip] = hits + [now]
        sig = self.ledger.send([transfer(TransferParams(from_pubkey=self.key.pubkey(), to_pubkey=who,
                                                        lamports=LAMPORTS))], self.key)
        return {"signature": str(sig), "lamports": LAMPORTS, "to": str(who)}


def load_key(path) -> Keypair | None:
    import json
    import os
    from pathlib import Path
    p = path or os.environ.get("KNOS_GAS_KEY_FILE")
    if not p or not Path(p).exists():
        return None
    return Keypair.from_bytes(bytes(json.loads(Path(p).read_text())))
