"""The four SAS schemas every Knos team creates under its own credential, and their data codecs.

Only salted hashes, sealed boxes, counters and times go on chain: no path, repo, org, user name or description.
`scripts/network_stats.py` counts a credential as a Knos team only if its `knos.claim.v1` layout matches `CLAIM`
byte for byte.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from . import sas

# name: (description, layout, field names)
CLAIM = ("knos.claim.v1", "Knos claim: salted unit hash, ancestor prefixes, salted holder, lease end, kind",
         [sas.VEC_U8, sas.VEC_U8, sas.VEC_U8, sas.I64, sas.U8],
         ["unit_hash", "ancestors", "holder_hash", "lease_until", "kind"])
RENEW = ("knos.renew.v1", "Knos claim renewal",
         [sas.VEC_U8, sas.VEC_U8, sas.I64], ["claim", "holder_hash", "lease_until"])
MEMBER = ("knos.member.v1", "Knos team member: sealed display name and team secret",
          [sas.VEC_U8, sas.VEC_U8], ["name_box", "salt_box"])
RECORD = ("knos.record.v1", "Knos agent record: counters and a Merkle root for one period",
          [sas.VEC_U8, sas.I64, sas.U32, sas.U32, sas.U32, sas.U32, sas.U64, sas.VEC_U8],
          ["holder_hash", "period_start", "taken", "finished", "abandoned", "collisions", "spent_micro_usd",
           "merkle_root"])
ALL = [CLAIM, RENEW, MEMBER, RECORD]


class Reader:
    def __init__(self, raw: bytes):
        self.raw, self.at = raw, 0

    def vec(self) -> bytes:
        (n,) = struct.unpack_from("<I", self.raw, self.at)
        out = self.raw[self.at + 4:self.at + 4 + n]
        if len(out) != n:
            raise ValueError("truncated")
        self.at += 4 + n
        return bytes(out)

    def fmt(self, f: str) -> int:
        (v,) = struct.unpack_from(f, self.raw, self.at)
        self.at += struct.calcsize(f)
        return v

    def done(self) -> None:
        if self.at != len(self.raw):
            raise ValueError("trailing bytes")


def _vec(b: bytes) -> bytes:
    return struct.pack("<I", len(b)) + b


@dataclass(frozen=True)
class ClaimData:
    unit_hash: bytes
    ancestors: bytes
    holder: bytes
    lease_until: int
    kind: int

    def encode(self) -> bytes:
        return (_vec(self.unit_hash) + _vec(self.ancestors) + _vec(self.holder) + struct.pack("<q", self.lease_until)
                + bytes([self.kind]))

    @classmethod
    def decode(cls, raw: bytes) -> "ClaimData":
        r = Reader(raw)
        out = cls(r.vec(), r.vec(), r.vec(), r.fmt("<q"), r.fmt("<B"))
        r.done()
        return out


@dataclass(frozen=True)
class RenewData:
    claim: bytes
    holder: bytes
    lease_until: int

    def encode(self) -> bytes:
        return _vec(self.claim) + _vec(self.holder) + struct.pack("<q", self.lease_until)

    @classmethod
    def decode(cls, raw: bytes) -> "RenewData":
        r = Reader(raw)
        out = cls(r.vec(), r.vec(), r.fmt("<q"))
        r.done()
        return out


@dataclass(frozen=True)
class MemberData:
    name_box: bytes
    salt_box: bytes

    def encode(self) -> bytes:
        return _vec(self.name_box) + _vec(self.salt_box)

    @classmethod
    def decode(cls, raw: bytes) -> "MemberData":
        r = Reader(raw)
        out = cls(r.vec(), r.vec())
        r.done()
        return out


@dataclass(frozen=True)
class RecordData:
    holder: bytes
    period_start: int
    taken: int
    finished: int
    abandoned: int
    collisions: int
    spent_micro_usd: int
    merkle_root: bytes

    def encode(self) -> bytes:
        return (_vec(self.holder) + struct.pack("<qIIIIQ", self.period_start, self.taken, self.finished,
                                                self.abandoned, self.collisions, self.spent_micro_usd)
                + _vec(self.merkle_root))

    @classmethod
    def decode(cls, raw: bytes) -> "RecordData":
        r = Reader(raw)
        holder = r.vec()
        vals = [r.fmt("<q"), r.fmt("<I"), r.fmt("<I"), r.fmt("<I"), r.fmt("<I"), r.fmt("<Q")]
        out = cls(holder, *vals, r.vec())
        r.done()
        return out


def schema_account_bytes(credential: sas.Pubkey, spec: tuple) -> bytes:
    """The schema account exactly as SAS writes it for `spec` (state/schema.rs): used to recognise Knos teams."""
    name, desc, layout, fields = spec
    names = b"".join(_vec(f.encode()) for f in fields)
    return (bytes([sas.SCHEMA]) + bytes(credential) + _vec(name.encode()) + _vec(desc.encode()) + _vec(bytes(layout))
            + _vec(names) + b"\x00" + b"\x01")
