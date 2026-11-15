"""Which escrow, which relay, which key: the settings `knos jobs`, `knos work`, the MCP tools and the SDK share.

    KNOS_JOBS_CLUSTER   devnet (default), localnet, or mainnet (refused unless KNOS_ALLOW_MAINNET=1)
    KNOS_JOBS_RPC       a custom RPC endpoint for that cluster
    KNOS_ESCROW_PROGRAM the escrow program id (default: the devnet deployment)
    KNOS_RELAY          an HTTP relay (https://…) or a directory; default ~/.knos/jobs/relay
    KNOS_MEMBER_KEY     the Solana key to sign with; default ~/.knos/team/member.json (created on first use)
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from solders.keypair import Keypair

from .. import paths
from . import sol
from .ledger import Ledger
from .relay import open_relay

MAINNET_CAP_UNITS = 500 * 1_000_000   # $500 per job until an external audit


class Refused(Exception):
    pass


def cluster() -> str:
    c = os.environ.get("KNOS_JOBS_CLUSTER", "devnet")
    if c == "mainnet" and os.environ.get("KNOS_ALLOW_MAINNET") != "1":
        raise Refused("Mainnet escrow is locked until its external audit. Use devnet (the default).")
    if c not in ("devnet", "localnet", "mainnet"):
        raise Refused(f"Unknown cluster {c!r}: use devnet or localnet.")
    return c


def ledger() -> Ledger:
    from ..team import rpc
    c = cluster()
    url = os.environ.get("KNOS_JOBS_RPC") or rpc.CLUSTERS[c]
    return Ledger(url, sol.program_id(), commitment=finality(url), network=c)


def finality(url: str) -> str:
    """`finalized` where Alpenglow has made it as fast as `confirmed` (lag of 2 slots or less), else `confirmed`."""
    forced = os.environ.get("KNOS_COMMITMENT")
    if forced in ("confirmed", "finalized"):
        return forced
    try:
        from .finality import mode
        return mode(url)[0]
    except Exception:  # noqa: BLE001 - an unreachable RPC: the safe default
        return "confirmed"


POINTER = "q6F1zDrYM1skVMyfFLsvgbxALDouZQURheFhr5dT4xY"   # signs the `knos-api:<url>` memo (web/chain.js reads it too)
MEMO = "MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr"


def api_url() -> str | None:
    """The live API (relay + Actions): the newest `knos-api:<url>` memo signed by POINTER on devnet."""
    from ..team import rpc
    url = rpc.CLUSTERS["devnet"]
    for s in rpc.call(url, "getSignaturesForAddress", [POINTER, {"limit": 10}]) or []:
        if s.get("err"):
            continue
        tx = rpc.call(url, "getTransaction", [s["signature"], {"encoding": "json",
                                                                "maxSupportedTransactionVersion": 0}])
        m = tx and tx["transaction"]["message"]
        if not m or m["accountKeys"][0] != POINTER:
            continue
        for ix in m["instructions"]:
            if m["accountKeys"][ix["programIdIndex"]] != MEMO:
                continue
            text = _b58decode(ix["data"]).decode(errors="replace")
            if text.startswith("knos-api:https://"):
                return text[len("knos-api:"):]
    return None


def _b58decode(s: str) -> bytes:
    alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    n = 0
    for c in s:
        n = n * 58 + alphabet.index(c)
    body = n.to_bytes((n.bit_length() + 7) // 8, "big") if n else b""
    return bytes(len(s) - len(s.lstrip("1"))) + body


def relay():
    """KNOS_RELAY: a directory, an http(s) relay, or `pointer` (the live API named on devnet: always-on workers)."""
    where = os.environ.get("KNOS_RELAY") or (paths.home() / "jobs" / "relay")
    if where == "pointer":
        where = api_url()
        if not where:
            raise Refused("No live Knos API is named on devnet right now.")
    return open_relay(where)


def key() -> Keypair:
    from ..team import config
    return config.member_key(create=True)


def _index_path() -> Path:
    d = paths.home() / "jobs"
    d.mkdir(parents=True, exist_ok=True)
    return d / "jobs.json"


def remember_job(job_id: bytes, role: str, title: str) -> None:
    p = _index_path()
    try:
        idx = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        idx = {}
    idx[job_id.hex()] = {"role": role, "title": title}
    p.write_text(json.dumps(idx, indent=1), encoding="utf-8")


def known_jobs() -> dict[str, dict]:
    try:
        return json.loads(_index_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def resolve(prefix: str) -> bytes:
    prefix = prefix.lower().strip()
    hits = [h for h in known_jobs() if h.startswith(prefix)]
    if len(prefix) == 64:
        return bytes.fromhex(prefix)
    if len(hits) == 1:
        return bytes.fromhex(hits[0])
    raise Refused(f"No single job matches {prefix!r}." + (" Give more characters." if hits else ""))
