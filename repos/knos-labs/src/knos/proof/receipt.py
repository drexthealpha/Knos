"""A receipt for a proven "done": the Merkle root of the evidence, attested on Solana (devnet) with the Solana
Attestation Service, and a page anyone can open (web/receipt.html?a=<attestation>).

The leaves are the sha256 of each check's evidence (name, verdict, what it saw), sorted; the root commits to all of
them. The attestation holds the root, the commit and the claim's hash, nothing readable. Keep the evidence JSON to
show any leaf later.
"""

from __future__ import annotations

import hashlib
import json
import time

CREDENTIAL_NAME = "knos-receipts"
SCHEMA = ("knos.receipt.v1", "Knos proof receipt: Merkle root of the evidence, commit, claim hash, time",
          None, ["root", "commit", "claim_hash", "at"])


def merkle_root(leaves: list[bytes]) -> bytes:
    level = sorted(leaves) or [hashlib.sha256(b"").digest()]
    while len(level) > 1:
        if len(level) % 2:
            level.append(level[-1])
        level = [hashlib.sha256(level[i] + level[i + 1]).digest() for i in range(0, len(level), 2)]
    return level[0]


def evidence(results) -> list[dict]:
    return [{"name": r.name, "ok": r.ok, "evidence": r.evidence} for r in results]


def leaves(ev: list[dict]) -> list[bytes]:
    return [hashlib.sha256(json.dumps(e, sort_keys=True, default=str).encode()).digest() for e in ev]


def _layout():
    from ..team import sas
    return [sas.VEC_U8, sas.VEC_U8, sas.VEC_U8, sas.I64]


def encode(root: bytes, commit: str, claim_text: str, at: int | None = None) -> bytes:
    import struct
    from ..team import sas
    return (sas._bytes(root) + sas._bytes(bytes.fromhex(commit) if commit else b"")
            + sas._bytes(hashlib.sha256(claim_text.encode()).digest()) + struct.pack("<q", at or int(time.time())))


def publish(url: str, key, root: bytes, commit: str, claim_text: str) -> tuple[str, str]:
    """Attest the receipt with `key` (its own receipts credential, created on first use). Returns (signature,
    attestation address)."""
    from solders.pubkey import Pubkey

    from ..team import rpc, sas
    me = key.pubkey()
    cred = sas.credential_pda(me, CREDENTIAL_NAME)
    schema = sas.schema_pda(cred, SCHEMA[0])
    ixs = []
    if rpc.account_data(url, cred)[1] is None:
        ixs.append(sas.create_credential(me, me, CREDENTIAL_NAME, [me]))
    if rpc.account_data(url, schema)[1] is None:
        ixs.append(sas.create_schema(me, me, cred, SCHEMA[0], SCHEMA[1], _layout(), SCHEMA[3]))
    nonce = Pubkey.from_bytes(root)
    att = sas.attestation_pda(cred, schema, nonce)
    ixs.append(sas.create_attestation(me, me, cred, schema, nonce, encode(root, commit, claim_text)))
    return rpc.send(url, ixs, key), str(att)


def page_url(attestation: str, base: str = "https://drexthealpha.github.io/Knos/") -> str:
    return f"{base}receipt.html?a={attestation}"
