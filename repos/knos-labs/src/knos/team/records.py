"""Records: who did what, verifiable by anyone. One `knos.record.v1` attestation per agent per day.

A record holds the agent's counters for the period (claims taken, finished, abandoned, collisions caused, spend) and
a Merkle root over that period's claim events and the agent's new Sibyl journal entries, each leaf salted with the
team salt. So the chain carries no plaintext, yet anyone holding the log can prove one entry was in it, and a
record cannot be quietly rewritten: it is signed by the agent's member key and lives at
attestation(credential, knos.record.v1, sha256(holder || period_start)).
"""

from __future__ import annotations

import hashlib
import json
import struct
import time
from dataclasses import dataclass

from solders.pubkey import Pubkey

from . import rpc, sas, schemas

DAY = 86_400


def period_start(ts: float | None = None, length: int = DAY) -> int:
    t = int(time.time() if ts is None else ts)
    return t - t % length


def leaf(salt: bytes, item: dict) -> bytes:
    return hashlib.sha256(salt + b"knos.leaf" + json.dumps(item, sort_keys=True, separators=(",", ":")).encode()
                          ).digest()


def merkle_root(leaves: list[bytes]) -> bytes:
    """Sorted leaves, sorted pairs, sha256: the order of the log does not matter, only its content."""
    level = sorted(leaves)
    if not level:
        return b"\0" * 32
    while len(level) > 1:
        nxt = []
        for i in range(0, len(level), 2):
            a, b = level[i], level[i + 1] if i + 1 < len(level) else level[i]
            nxt.append(hashlib.sha256(min(a, b) + max(a, b)).digest())
        level = nxt
    return level[0]


def proof(leaves: list[bytes], target: bytes) -> list[bytes]:
    level = sorted(leaves)
    if target not in level:
        raise LookupError("not in this log")
    idx, out = level.index(target), []
    while len(level) > 1:
        sib = idx ^ 1
        out.append(level[sib] if sib < len(level) else level[idx])
        nxt = []
        for i in range(0, len(level), 2):
            a, b = level[i], level[i + 1] if i + 1 < len(level) else level[i]
            nxt.append(hashlib.sha256(min(a, b) + max(a, b)).digest())
        level, idx = nxt, idx // 2
    return out


def verify_proof(target: bytes, path: list[bytes], root: bytes) -> bool:
    h = target
    for sib in path:
        h = hashlib.sha256(min(h, sib) + max(h, sib)).digest()
    return h == root


@dataclass
class Period:
    holder: bytes
    start: int
    taken: int = 0
    finished: int = 0
    abandoned: int = 0
    collisions: int = 0
    spent_micro_usd: int = 0
    leaves: list[bytes] = None  # type: ignore[assignment]

    def data(self) -> schemas.RecordData:
        return schemas.RecordData(self.holder, self.start, self.taken, self.finished, self.abandoned, self.collisions,
                                  self.spent_micro_usd, merkle_root(self.leaves or []))


def build(salt: bytes, holder: bytes, start: int, events: list[dict], journal: list[dict],
          spent_micro_usd: int = 0, length: int = DAY) -> Period:
    """Counters and leaves for one holder and one period, from this machine's event log and Sibyl journal."""
    end = start + length
    p = Period(holder, start, spent_micro_usd=spent_micro_usd, leaves=[])
    mine = [e for e in events if e.get("holder") == holder.hex() and start <= float(e["ts"]) < end]
    claimed: set[str] = set()
    released: set[str] = set()
    for e in mine:
        kind = e["kind"]
        if kind == "claim":
            p.taken += 1
            claimed.add(e.get("claim", ""))
        elif kind == "release":
            p.finished += 1
            released.add(e.get("claim", ""))
        elif kind == "lapsed":
            p.abandoned += 1
        elif kind == "blocked":
            p.collisions += 1
        p.leaves.append(leaf(salt, {k: v for k, v in e.items()}))
    for j in journal:
        p.leaves.append(leaf(salt, {"journal": j}))
    return p


def record_address(credential: Pubkey, holder: bytes, start: int) -> Pubkey:
    nonce = Pubkey.from_bytes(hashlib.sha256(holder + struct.pack("<q", start)).digest())
    return sas.attestation_pda(credential, sas.schema_pda(credential, schemas.RECORD[0]), nonce)


def write(url: str, credential: Pubkey, key, period: Period) -> str | None:
    """Write the record once; None if this period already has one."""
    addr = record_address(credential, period.holder, period.start)
    if rpc.account_data(url, addr)[1] is not None:
        return None
    nonce = Pubkey.from_bytes(hashlib.sha256(period.holder + struct.pack("<q", period.start)).digest())
    schema = sas.schema_pda(credential, schemas.RECORD[0])
    return rpc.send(url, [sas.create_attestation(key.pubkey(), key.pubkey(), credential, schema, nonce,
                                                 period.data().encode())], key)


def read(url: str, credential: Pubkey, holder: bytes, start: int) -> tuple[sas.Attestation, schemas.RecordData] | None:
    _, raw = rpc.account_data(url, record_address(credential, holder, start))
    if raw is None:
        return None
    att = sas.parse_attestation(raw)
    return att, schemas.RecordData.decode(att.data)


def verify(url: str, credential: Pubkey, period: Period) -> dict:
    """Compare this machine's log for a period with the record on chain."""
    got = read(url, credential, period.holder, period.start)
    if got is None:
        return {"on_chain": False}
    att, rec = got
    mine = period.data()
    return {"on_chain": True, "signer": str(att.signer), "counters_match": (rec.taken, rec.finished, rec.abandoned,
                                                                            rec.collisions) ==
            (mine.taken, mine.finished, mine.abandoned, mine.collisions),
            "root_matches": rec.merkle_root == mine.merkle_root, "record": rec}
