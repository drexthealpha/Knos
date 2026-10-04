"""The meter's ledger: the evaluations of one buyer and one seller, kept off chain by whoever wants to check the count.

knos_meter's batch mode writes no account per evaluation. One signed token carries a month, a sequence number, a
count, how many were accepted, their value and a 32-byte Merkle root; the program adds the numbers to a Ledger account
and folds the root into a running hash. Which evaluations those numbers stand for is in a file like the ones this
module reads and writes, held by the buyer and, separately, by the seller. With the file and the chain's account
anyone recomputes every root and the running hash (`verify`), shows that one evaluation is in a batch (`prove`,
`check_proof`), and sets the buyer's file against the seller's (`reconcile`): the events only one of them has, the
ones they judged differently, the ones entered twice, and a statement that is the same bytes whoever computes it.

The audience a batch token is signed for is written in one place (`audience_of`), exactly as the program reads it:
`knosm:batch:<buyer>:<seller>:<yyyymm>:<seq>:<count>:<accepted>:<value>:<root, 64 lowercase hex>` for the buyer's
count and `knosm:claim:...` for the seller's. `knos meter verify --rpc <url>` reads the two Ledger accounts from a
node; `attest_batch` is what the pinned workflow runs to have GitHub sign one batch of a ledger file in a repository.

A ledger file is JSON Lines. A batch is one header line, then its evaluations, one canonical line each (keys sorted,
no spaces, integers and lowercase hex only), in ascending order of id:

    {"batch":{"accepted":2,"buyer":424242,"count":3,"month":202610,"root":"<hex32>","seller":555000,"seq":0,"value":4000000}}
    {"accepted":1,"artifact":"<hex40>","buyer":424242,"id":"<hex32>","milestone":0,"order":"<hex32>","policy":"<hex32>","rate":2000000,"seller":555000}

`id` is the 32 bytes the single mode already bills once: sha256(work order || artifact, its 40 characters || policy ||
milestone u32 little-endian), `EvalAud::key` in programs-v2/knos_meter/src/gh.rs. The tree is RFC 6962's:
leaf = sha256(0x00 || id), node = sha256(0x01 || left || right), over the ids sorted ascending, none twice.

Standard library only for everything that reads and checks files: a buyer or a seller runs that without a Solana
client. Only what reads the chain (`--rpc`, `attest_batch`) imports Knos's own client, inside the function.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

FREE_PER_MONTH = 10_000     # the price book: an owner's first evaluations of a month cost nothing
RATE = 50_000               # then 0.05 USD each, in millionths (0.02 on a committed-volume plan: 20_000)
MICRO = 1_000_000
ZERO = bytes(32)            # a Ledger account's running hash before its first batch
_HEX = set("0123456789abcdef")


class Bad(ValueError):
    """A line or a ledger that cannot be read as what it says it is. The message is for the person who has the file."""


def _sha(*parts: bytes) -> bytes:
    return hashlib.sha256(b"".join(parts)).digest()


def canonical(obj) -> str:
    """The one way a line is written, so that two parties who hold the same facts hold the same bytes."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _hex(s, chars: int, what: str) -> str:
    if not isinstance(s, str) or len(s) != chars or not set(s) <= _HEX:
        raise Bad(f"{what} must be {chars} lowercase hex characters")
    return s


def _int(v, what: str, most: int = 2 ** 64 - 1, least: int = 0) -> int:
    if isinstance(v, bool) or not isinstance(v, int) or not least <= v <= most:
        raise Bad(f"{what} must be a whole number from {least} to {most}")
    return v


def month_of(text: str | int) -> int:
    """`2026-10` or `202610` -> 202610."""
    s = str(text).replace("-", "")
    if len(s) != 6 or not s.isdigit() or not 1 <= int(s[4:]) <= 12:
        raise Bad(f"a month is written YYYY-MM, not {text!r}")
    return int(s)


# -- one evaluation ---------------------------------------------------------------------------------------------------
def eval_id(order: bytes, artifact: str, policy: bytes, milestone: int) -> bytes:
    """What makes an evaluation billable once. The same bytes as `EvalAud::key` on chain and `eval_key` in
    knos.settle.v2.meter: the artifact goes in as its 40 characters, not as 20 bytes."""
    return _sha(order, artifact.encode(), policy, milestone.to_bytes(4, "little"))


@dataclass(frozen=True)
class Evaluation:
    buyer: int          # the GitHub owner id whose credits pay
    seller: int         # the GitHub owner id whose work was judged
    order: str          # the work order, 32 bytes as hex
    artifact: str       # a commit, 40 hex characters
    policy: str         # the policy it was judged under, 32 bytes as hex
    milestone: int
    accepted: bool
    rate: int           # what the seller bills when it is accepted, in the smallest units the two settle in

    def __post_init__(self) -> None:
        _int(self.buyer, "buyer", least=1), _int(self.seller, "seller", least=1)
        _hex(self.order, 64, "order"), _hex(self.artifact, 40, "artifact"), _hex(self.policy, 64, "policy")
        _int(self.milestone, "milestone", 2 ** 32 - 1), _int(self.rate, "rate")
        if not isinstance(self.accepted, bool):
            raise Bad("accepted must be 1 or 0")

    @property
    def id(self) -> bytes:
        return eval_id(bytes.fromhex(self.order), self.artifact, bytes.fromhex(self.policy), self.milestone)

    @property
    def value(self) -> int:
        """What it adds to the batch's value: its rate when accepted, nothing when rejected."""
        return self.rate if self.accepted else 0

    def audience(self) -> str:
        """The audience the single mode's token is signed for (`eval_aud` in gh.rs)."""
        return f"knosm:eval:{self.buyer}:{self.seller}:{self.order}:{self.artifact}:{self.policy}:{self.milestone}:{int(self.accepted)}:{self.rate}"

    def line(self) -> str:
        return canonical({"accepted": int(self.accepted), "artifact": self.artifact, "buyer": self.buyer, "id": self.id.hex(), "milestone": self.milestone,
                          "order": self.order, "policy": self.policy, "rate": self.rate, "seller": self.seller})


def parse(line: str | dict) -> Evaluation:
    """One evaluation from a ledger line, from the same object already decoded, or from a `knosm:eval:...` audience
    (what a workflow already has). An `id` that is not the id of the other fields is refused."""
    if isinstance(line, str) and line.startswith("knosm:eval:"):
        p = line.strip().split(":")
        if len(p) != 10 or p[8] not in ("0", "1") or not all(x.isdigit() for x in (p[2], p[3], p[7], p[9])):
            raise Bad("an evaluation's audience is knosm:eval:<buyer>:<seller>:<order>:<artifact>:<policy>:<milestone>:<1 or 0>:<rate>")
        return Evaluation(int(p[2]), int(p[3]), p[4], p[5], p[6], int(p[7]), p[8] == "1", int(p[9]))
    try:
        o = json.loads(line) if isinstance(line, str) else line
    except ValueError:
        raise Bad("the line is not JSON") from None
    if not isinstance(o, dict) or not {"accepted", "artifact", "buyer", "milestone", "order", "policy", "rate", "seller"} <= set(o):
        raise Bad("an evaluation needs accepted, artifact, buyer, milestone, order, policy, rate and seller")
    if o["accepted"] not in (0, 1) or isinstance(o["accepted"], bool):
        raise Bad("accepted must be 1 or 0")
    e = Evaluation(o["buyer"], o["seller"], o["order"], o["artifact"], o["policy"], o["milestone"], o["accepted"] == 1, o["rate"])
    if "id" in o and o["id"] != e.id.hex():
        raise Bad(f"the id {str(o['id'])[:16]}... is not the id of this order, artifact, policy and milestone")
    return e


# -- the Merkle tree (RFC 6962, section 2.1) --------------------------------------------------------------------------
def leaf(id_: bytes) -> bytes:
    return _sha(b"\x00", id_)


def _node(left: bytes, right: bytes) -> bytes:
    return _sha(b"\x01", left, right)


def _split(n: int) -> int:
    """The largest power of two smaller than n (n > 1)."""
    return 1 << ((n - 1).bit_length() - 1)


def _tree(hashes: list[bytes]) -> bytes:
    if len(hashes) <= 1:
        return hashes[0] if hashes else _sha()
    k = _split(len(hashes))
    return _node(_tree(hashes[:k]), _tree(hashes[k:]))


def _path(m: int, hashes: list[bytes]) -> list[bytes]:
    if len(hashes) <= 1:
        return []
    k = _split(len(hashes))
    return _path(m, hashes[:k]) + [_tree(hashes[k:])] if m < k else _path(m - k, hashes[k:]) + [_tree(hashes[:k])]


def merkle_root(ids) -> bytes:
    """The root over these ids, sorted ascending, each once. No ids: sha256 of nothing, as the RFC has it."""
    return _tree([leaf(i) for i in sorted(set(ids))])


def inclusion_path(ids, id_: bytes) -> tuple[int, list[bytes]]:
    """(index among the sorted ids, the sibling hashes from the leaf up)."""
    order = sorted(set(ids))
    if id_ not in order:
        raise Bad("that evaluation is not in the batch")
    m = order.index(id_)
    return m, _path(m, [leaf(i) for i in order])


def check_proof(id_: bytes, index: int, size: int, path: list[bytes], root: bytes) -> bool:
    """Whether `id_` is leaf `index` of a tree of `size` leaves with this root (RFC 9162, section 2.1.3.2). Needs
    nothing but the proof and the root: not the ledger, not the other evaluations."""
    if not 0 <= index < size:
        return False
    fn, sn, r = index, size - 1, leaf(id_)
    for p in path:
        if sn == 0:
            return False
        if fn & 1 or fn == sn:
            r = _node(p, r)
            while not fn & 1 and fn:
                fn, sn = fn >> 1, sn >> 1
        else:
            r = _node(r, p)
        fn, sn = fn >> 1, sn >> 1
    return sn == 0 and r == root


# -- a batch ----------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Batch:
    """What one RecordBatch (the buyer's) or ClaimBatch (the seller's) token says, and the evaluations behind it."""
    buyer: int
    seller: int
    month: int          # yyyymm
    seq: int            # 0 for the pair's first batch of the month, then 1, 2, ...
    count: int
    accepted: int
    value: int          # the sum of the accepted evaluations' rates
    root: bytes
    evals: tuple[Evaluation, ...] = field(default=(), compare=False)

    def header(self) -> str:
        return canonical({"batch": {"accepted": self.accepted, "buyer": self.buyer, "count": self.count, "month": self.month, "root": self.root.hex(),
                                    "seller": self.seller, "seq": self.seq, "value": self.value}})

    def lines(self) -> list[str]:
        return [self.header(), *(e.line() for e in self.evals)]


def audience_of(kind: str, buyer: int, seller: int, month: int, seq: int, count: int, accepted: int, value: int, root: bytes) -> str:
    """THE ONE PLACE the batch token's audience is written, exactly as knos_meter reads it (`batch_aud` in
    programs-v2/knos_meter/src/gh.rs): ten parts, the numbers in decimal with no leading zero, the month as six
    digits, seq from 0, the root as 64 lowercase hex characters. `kind`: batch (the buyer's) or claim (the seller's)."""
    if kind not in ("batch", "claim") or len(root) != 32:
        raise Bad("a batch token is of kind batch or claim and carries a 32-byte root")
    return f"knosm:{kind}:{int(buyer)}:{int(seller)}:{int(month):06d}:{int(seq)}:{int(count)}:{int(accepted)}:{int(value)}:{root.hex()}"


def batch_audience(b: Batch, claim: bool = False) -> str:
    """The audience of the token that anchors this batch. `claim`: the seller's own count (ClaimBatch) instead of the
    buyer's (RecordBatch)."""
    return audience_of("claim" if claim else "batch", b.buyer, b.seller, b.month, b.seq, b.count, b.accepted, b.value, b.root)


_NUM = re.compile(r"0|[1-9][0-9]{0,19}")


def parse_batch_audience(aud: str) -> tuple[bool, Batch]:
    """(whether it is the seller's claim, the batch it names, with no evaluations) from a `knosm:batch:` or
    `knosm:claim:` audience, refused as the program refuses one."""
    p = str(aud).split(":")
    if len(p) != 10 or p[0] != "knosm" or p[1] not in ("batch", "claim") or len(p[4]) != 6 or not all(_NUM.fullmatch(x) for x in p[2:9]) \
            or len(p[9]) != 64 or not set(p[9]) <= _HEX or any(int(x) >= 2 ** 64 for x in p[2:9]) or not int(p[2]) or not int(p[3]):
        raise Bad("a batch's audience is knosm:batch:<buyer>:<seller>:<yyyymm>:<seq>:<count>:<accepted>:<value>:<root, 64 lowercase hex> (or knosm:claim:...)")
    return p[1] == "claim", Batch(int(p[2]), int(p[3]), int(p[4]), int(p[5]), int(p[6]), int(p[7]), int(p[8]), bytes.fromhex(p[9]))


def batch(lines, seq: int, month: int | str) -> Batch:
    """A batch from evaluations (ledger lines, audiences or Evaluation objects). The same evaluation given twice (a
    retry) is counted once; two that share an id and differ in verdict or rate are refused, because a batch says one
    thing about each evaluation. All must be of one buyer and one seller."""
    by: dict[bytes, Evaluation] = {}
    for item in lines:
        e = item if isinstance(item, Evaluation) else parse(item)
        if by.setdefault(e.id, e) != e:
            raise Bad(f"evaluation {e.id.hex()[:16]}... is in this batch twice with different contents: keep one")
    if not by:
        raise Bad("a batch needs at least one evaluation")
    evals = tuple(by[i] for i in sorted(by))
    pairs = {(e.buyer, e.seller) for e in evals}
    if len(pairs) != 1:
        raise Bad("a batch is for one buyer and one seller; these evaluations name more than one pair")
    (buyer, seller), = pairs
    return Batch(buyer, seller, month_of(month), _int(seq, "seq"), len(evals), sum(e.accepted for e in evals), sum(e.value for e in evals),
                 merkle_root(by), evals)


def chain_hash(prev: bytes, root: bytes, seq: int, count: int, accepted: int, value: int) -> bytes:
    """The Ledger account's running hash after one more batch: sha256(prev || root || seq || count || accepted ||
    value), the four numbers as u64 little-endian. It starts at 32 zero bytes."""
    return _sha(prev, root, *(n.to_bytes(8, "little") for n in (seq, count, accepted, value)))


# -- a ledger file ----------------------------------------------------------------------------------------------------
@dataclass
class Stored:
    """A batch as the file has it: what its header declares, and the evaluation lines under it, unchecked."""
    declared: dict
    evals: list[Evaluation]
    at: int             # the header's line number, for messages

    @property
    def month(self) -> int:
        return self.declared["month"]

    @property
    def seq(self) -> int:
        return self.declared["seq"]

    def batch(self) -> Batch:
        """The batch recomputed from the lines (never from the header's root or totals)."""
        return batch(self.evals, self.seq, self.month)


def load(text: str | Path) -> list[Stored]:
    """The batches of a ledger file (a path, or the text itself), in the file's order. Reads; `verify` judges."""
    if isinstance(text, Path):
        text = text.read_text(encoding="utf-8")
    out: list[Stored] = []
    for n, raw in enumerate(text.splitlines(), 1):
        if not raw.strip():
            continue
        try:
            o = json.loads(raw)
        except ValueError:
            raise Bad(f"line {n} is not JSON") from None
        if isinstance(o, dict) and "batch" in o:
            h = o["batch"]
            if not isinstance(h, dict) or set(h) != {"accepted", "buyer", "count", "month", "root", "seller", "seq", "value"}:
                raise Bad(f"line {n}: a batch header has accepted, buyer, count, month, root, seller, seq and value")
            try:
                for k in ("accepted", "buyer", "count", "seller", "seq", "value"):
                    _int(h[k], k)
                month_of(_int(h["month"], "month")), _hex(h["root"], 64, "root")
            except Bad as why:
                raise Bad(f"line {n}: {why}") from None
            out.append(Stored(h, [], n))
            continue
        if not out:
            raise Bad(f"line {n}: an evaluation before any batch header")
        try:
            out[-1].evals.append(parse(o))
        except Bad as why:
            raise Bad(f"line {n}: {why}") from None
    return out


def dump(batches) -> str:
    """The file's text for these batches (Batch objects)."""
    return "".join(line + "\n" for b in batches for line in b.lines())


def next_seq(ledger: list[Stored], month: int) -> int:
    return 1 + max((s.seq for s in ledger if s.month == month), default=-1)


@dataclass(frozen=True)
class Totals:
    """What the chain's Ledger account holds for one buyer, one seller and one month (the seller's own count, written
    by ClaimBatch, has the same shape)."""
    next_seq: int
    count: int
    accepted: int
    value: int
    chain: bytes

    @classmethod
    def of(cls, o: dict) -> "Totals":
        """From JSON: {"next_seq":..,"count":..,"accepted":..,"value":..,"chain":"<hex32>"}."""
        try:
            return cls(_int(o["next_seq"], "next_seq"), _int(o["count"], "count"), _int(o["accepted"], "accepted"), _int(o["value"], "value"),
                       bytes.fromhex(_hex(o["chain"], 64, "chain")))
        except (KeyError, TypeError):
            raise Bad("the chain's totals are next_seq, count, accepted, value and chain (64 hex characters)") from None

    def json(self) -> dict:
        return {"accepted": self.accepted, "chain": self.chain.hex(), "count": self.count, "next_seq": self.next_seq, "value": self.value}


def totals(ledger: list[Stored], month: int) -> Totals:
    """What the chain's account must hold if these are the month's batches, sent in order of seq."""
    t = Totals(0, 0, 0, 0, ZERO)
    for s in sorted((s for s in ledger if s.month == month), key=lambda s: s.seq):
        b = s.batch()
        t = Totals(b.seq + 1, t.count + b.count, t.accepted + b.accepted, t.value + b.value, chain_hash(t.chain, b.root, b.seq, b.count, b.accepted, b.value))
    return t


def verify(ledger: list[Stored], onchain: Totals | None = None, month: int | None = None) -> list[str]:
    """Everything wrong with a ledger, in words; an empty list means it holds. Every root and total is recomputed
    from the lines; a month's batches must be numbered 0, 1, 2, ...; no evaluation may be in two batches (the chain
    cannot see that in batch mode: it has no account per evaluation, so this check is the only one). With `onchain`,
    the month's totals and running hash must be the chain's (`month` may be left out when the ledger has one)."""
    bad: list[str] = []
    if len({(s.declared["buyer"], s.declared["seller"]) for s in ledger}) > 1:
        bad.append("the file holds batches of more than one buyer and seller: keep one file per pair")
    seen: dict[bytes, tuple[int, int]] = {}
    for s in ledger:
        where = f"batch {s.seq} of {s.month} (line {s.at})"
        try:
            b = s.batch()
        except Bad as why:
            bad.append(f"{where}: {why}")
            continue
        d = s.declared
        if (b.buyer, b.seller) != (d["buyer"], d["seller"]):
            bad.append(f"{where}: its evaluations are of buyer {b.buyer} and seller {b.seller}, not the header's")
        if len(s.evals) != b.count:
            bad.append(f"{where}: {len(s.evals) - b.count} evaluation(s) are written twice")
        if b.root.hex() != d["root"]:
            bad.append(f"{where}: the lines give root {b.root.hex()}, the header says {d['root']}: a line was changed, added or removed")
        if (b.count, b.accepted, b.value) != (d["count"], d["accepted"], d["value"]):
            bad.append(f"{where}: the lines give count {b.count}, accepted {b.accepted}, value {b.value}; the header says {d['count']}, {d['accepted']}, {d['value']}")
        for e in b.evals:
            first = seen.setdefault(e.id, (s.month, s.seq))
            if first != (s.month, s.seq):
                bad.append(f"{where}: evaluation {e.id.hex()} is already in batch {first[1]} of {first[0]}: it would be counted twice")
    for m in sorted({s.month for s in ledger}):
        seqs = sorted(s.seq for s in ledger if s.month == m)
        if seqs != list(range(len(seqs))):
            bad.append(f"month {m}: its batches are numbered {seqs}, not 0 to {len(seqs) - 1}: one is missing or repeated")
    if onchain is not None and not bad:
        months = sorted({s.month for s in ledger})
        if month is None and len(months) != 1:
            return [f"the ledger has {len(months)} months: say which one the chain's totals are for"]
        mine = totals(ledger, month if month is not None else months[0])
        for name in ("next_seq", "count", "accepted", "value"):
            if getattr(mine, name) != getattr(onchain, name):
                bad.append(f"{name}: the ledger gives {getattr(mine, name)}, the chain has {getattr(onchain, name)}")
        if mine.chain != onchain.chain:
            bad.append(f"the running hash: the ledger gives {mine.chain.hex()}, the chain has {onchain.chain.hex()}: these are not the batches that were anchored")
    return bad


@dataclass(frozen=True)
class Proof:
    """That one evaluation is in one anchored batch. `root` is what to compare with the batch's root as anchored."""
    id: bytes
    month: int
    seq: int
    index: int
    size: int
    path: tuple[bytes, ...]
    root: bytes

    def ok(self) -> bool:
        return check_proof(self.id, self.index, self.size, list(self.path), self.root)

    def json(self) -> dict:
        return {"id": self.id.hex(), "index": self.index, "month": self.month, "path": [p.hex() for p in self.path], "root": self.root.hex(), "seq": self.seq,
                "size": self.size}

    @classmethod
    def of(cls, o: dict) -> "Proof":
        try:
            return cls(bytes.fromhex(_hex(o["id"], 64, "id")), _int(o["month"], "month"), _int(o["seq"], "seq"), _int(o["index"], "index"), _int(o["size"], "size"),
                       tuple(bytes.fromhex(_hex(p, 64, "a path entry")) for p in o["path"]), bytes.fromhex(_hex(o["root"], 64, "root")))
        except (KeyError, TypeError):
            raise Bad("a proof has id, month, seq, index, size, path and root") from None


def prove(ledger: list[Stored], id_: bytes) -> Proof:
    """The inclusion proof of one evaluation, from the first batch that holds it."""
    for s in ledger:
        b = s.batch()
        ids = [e.id for e in b.evals]
        if id_ in ids:
            index, path = inclusion_path(ids, id_)
            return Proof(id_, b.month, b.seq, index, b.count, tuple(path), b.root)
    raise Bad(f"evaluation {id_.hex()} is in no batch of this ledger")


# -- two ledgers ------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Dispute:
    """One evaluation both sides have and do not describe alike. `what`: verdict, rate, month, in that order."""
    id: bytes
    buyer: Evaluation
    seller: Evaluation
    buyer_month: int
    seller_month: int
    what: tuple[str, ...]


@dataclass(frozen=True)
class Row:
    """One month of the statement. count, accepted, value and fee are of the evaluations both sides have and describe
    alike; the last three columns count what they do not agree on, each in the month of the side that has it (a
    disputed one in the buyer's month)."""
    month: int
    count: int
    accepted: int
    value: int
    fee: int            # in millionths of a USD: (count beyond the free ones) x rate
    buyer_only: int
    seller_only: int
    disputed: int


@dataclass(frozen=True)
class Reconciliation:
    buyer_only: tuple[tuple[int, Evaluation], ...]      # (month, evaluation): the seller has no record of these
    seller_only: tuple[tuple[int, Evaluation], ...]     # missing events: the seller counted them, the buyer did not
    disputed: tuple[Dispute, ...]
    duplicates: dict                                    # {"buyer": (ids...), "seller": (ids...)}: entered more than once
    rows: tuple[Row, ...]
    buyer: int
    seller: int
    rate: int
    free: int

    @property
    def agreed(self) -> bool:
        return not (self.buyer_only or self.seller_only or self.disputed or self.duplicates["buyer"] or self.duplicates["seller"])

    def statement(self) -> str:
        """The statement as text. It is made only of what both ledgers say, with the two roles named, so the buyer
        and the seller get the same bytes; the last line is the sha256 of the lines above it, to compare by eye."""
        body = f"buyer,{self.buyer}\nseller,{self.seller}\nrate,{self.rate}\nfree,{self.free}\nmonth,count,accepted,value,fee,buyer_only,seller_only,disputed\n"
        body += "".join(f"{r.month},{r.count},{r.accepted},{r.value},{r.fee},{r.buyer_only},{r.seller_only},{r.disputed}\n" for r in self.rows)
        return body + f"sha256,{hashlib.sha256(body.encode()).hexdigest()}\n"

    def json(self) -> dict:
        ev = lambda pairs: [{"month": m, **json.loads(e.line())} for m, e in pairs]  # noqa: E731
        return {"agreed": self.agreed, "buyer_only": ev(self.buyer_only), "seller_only": ev(self.seller_only),
                "disputed": [{"id": d.id.hex(), "what": list(d.what), "buyer": {"month": d.buyer_month, "accepted": int(d.buyer.accepted), "rate": d.buyer.rate},
                              "seller": {"month": d.seller_month, "accepted": int(d.seller.accepted), "rate": d.seller.rate}} for d in self.disputed],
                "duplicates": {k: [i.hex() for i in v] for k, v in self.duplicates.items()},
                "statement": [vars(r) for r in self.rows]}


def _events(ledger: list[Stored]) -> tuple[dict[bytes, tuple[int, Evaluation]], tuple[bytes, ...]]:
    """id -> (month, evaluation), the first entry winning in order of month, seq and line; and the ids entered more
    than once."""
    first: dict[bytes, tuple[int, Evaluation]] = {}
    twice: set[bytes] = set()
    for s in sorted(ledger, key=lambda s: (s.month, s.seq, s.at)):
        for e in s.evals:
            if e.id in first:
                twice.add(e.id)
            else:
                first[e.id] = (s.month, e)
    return first, tuple(sorted(twice))


def fee(count: int, rate: int = RATE, free: int = FREE_PER_MONTH) -> int:
    """The price book's Meter line for one month: the first `free` evaluations cost nothing, each one after costs
    `rate` (millionths of a USD). Rejected evaluations are counted like accepted ones: the count is of evaluations."""
    return max(0, count - free) * rate


def reconcile(buyer_ledger: list[Stored], seller_ledger: list[Stored], rate: int = RATE, free: int = FREE_PER_MONTH) -> Reconciliation:
    """The buyer's ledger against the seller's. Everything in the result is in ascending order of id, so it does not
    depend on the order of either file. `free` is how many free evaluations the buyer has left for this seller in a
    month: the allowance is the buyer's across all its sellers, so a buyer with several passes what is left."""
    b, b_twice = _events(buyer_ledger)
    s, s_twice = _events(seller_ledger)
    pairs = {(e.buyer, e.seller) for _m, e in (*b.values(), *s.values())}
    if len(pairs) > 1:
        raise Bad("the two ledgers are not of the same buyer and seller")
    buyer, seller = next(iter(pairs), (0, 0))
    disputed = []
    for i in sorted(b.keys() & s.keys()):
        (bm, be), (sm, se) = b[i], s[i]
        what = tuple(w for w, differs in (("verdict", be.accepted != se.accepted), ("rate", be.rate != se.rate), ("month", bm != sm)) if differs)
        if what:
            disputed.append(Dispute(i, be, se, bm, sm, what))
    out_ids = {d.id for d in disputed}
    buyer_only = tuple(b[i] for i in sorted(b.keys() - s.keys()))
    seller_only = tuple(s[i] for i in sorted(s.keys() - b.keys()))
    months = sorted({m for m, _e in (*b.values(), *s.values())})
    rows = []
    for m in months:
        both = [e for i, (bm, e) in b.items() if bm == m and i in s and i not in out_ids]
        rows.append(Row(m, len(both), sum(e.accepted for e in both), sum(e.value for e in both), fee(len(both), rate, free),
                        sum(1 for bm, _e in buyer_only if bm == m), sum(1 for sm, _e in seller_only if sm == m), sum(1 for d in disputed if d.buyer_month == m)))
    return Reconciliation(buyer_only, seller_only, tuple(disputed), {"buyer": b_twice, "seller": s_twice}, tuple(rows), buyer, seller, rate, free)


def export_csv(ledger: list[Stored]) -> str:
    """One row per evaluation line, in the file's order, for a spreadsheet or an auditor."""
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["month", "seq", "id", "buyer", "seller", "order", "artifact", "policy", "milestone", "accepted", "rate"])
    for s in ledger:
        for e in s.evals:
            w.writerow([s.month, s.seq, e.id.hex(), e.buyer, e.seller, e.order, e.artifact, e.policy, e.milestone, int(e.accepted), e.rate])
    return buf.getvalue()


def usd(micro: int) -> str:
    return f"{micro // MICRO}.{micro % MICRO:06d}".rstrip("0").rstrip(".") if micro % MICRO else str(micro // MICRO)


# -- the chain's two accounts, and the run that asks GitHub to sign a batch ---------------------------------------------
def onchain(net, buyer: int, seller: int, month: int) -> tuple[Totals, Totals]:
    """(the buyer's count, the seller's claim) for one month as the chain has them: the Ledger accounts RecordBatch
    and ClaimBatch write, read through `net.account(address)` (a knos.chain.Ledger). One with no batch yet is zeros."""
    from .settle.v2 import meter
    both = (meter.book(net, buyer, seller, month, claim) for claim in (False, True))
    count, claimed = (Totals(b.next_seq, b.evaluations, b.accepted, b.value, b.chain) for b in both)
    return count, claimed


def verify_onchain(ledger: list[Stored], net, claim: bool = False) -> tuple[list[str], dict[int, tuple[Totals, Totals]]]:
    """`verify`, with every month of the file held to the chain's account for it: the buyer's count, or with `claim`
    the seller's. Returns (what is wrong, {month: (the buyer's count, the seller's claim)} as read)."""
    bad, seen = verify(ledger), dict[int, tuple[Totals, Totals]]()
    if bad or not ledger:
        return bad, seen
    buyer, seller = ledger[0].declared["buyer"], ledger[0].declared["seller"]
    for m in sorted({s.month for s in ledger}):
        seen[m] = onchain(net, buyer, seller, m)
        bad += [f"month {m}: {line}" for line in verify(ledger, seen[m][claim], m)]
    return bad, seen


ORDER = re.compile(r"(?P<path>[^:\s][^:]{0,255}?)(?::(?P<month>[0-9]{6})\.(?P<seq>0|[1-9][0-9]{0,18}))?")


def attest_batch(run, order: str, kind: str, no, sign) -> int:
    """`knos attest --kind batch|claim --repository R --order <ledger file>[:<yyyymm>.<seq>]`: what the pinned
    attest.yml runs for knos_meter's batch mode. It reads the ledger file at that path of R's default branch through
    GitHub's API (there is no checkout), recomputes every root and total of it, and asks GitHub to sign the audience of
    ONE batch: the one named, or the first one the chain has not taken yet (this month's or last month's).

        batch   the buyer's count (RecordBatch). The run must be in a repository of the ledger's buyer, on its first
                attempt; the meter takes the token only from attest.yml or prove.yml at the commit the buyer's Credits pin.
        claim   the seller's own count (ClaimBatch). The run must be in a repository of the ledger's seller.

    `no(why)` and `sign(run, kind, audience, said, found, number, order, no)` are knos.flow's (the refusal, and the
    end of every `knos attest`: the token is relayed here or posted as `knos-eval:` for a relayer)."""
    import base64
    import urllib.parse
    claim, m = kind == "claim", ORDER.fullmatch(str(order).strip())
    if m is None:
        return no("`--order` is the ledger file's path in the repository, optionally followed by `:<yyyymm>.<seq>` to name one batch "
                  "(for example `meter/acme.jsonl` or `meter/acme.jsonl:202610.0`).")
    path = m["path"].strip("/")
    try:
        meta = run.github(f"repos/{run.repo}/contents/{urllib.parse.quote(path)}")
        if not isinstance(meta, dict) or meta.get("type") != "file":
            raise OSError("it is not a file")
        raw = meta.get("content") or run.github(f"repos/{run.repo}/git/blobs/{meta['sha']}")["content"]     # the contents API leaves out a file over 1 MB
        book = load(base64.b64decode(raw).decode("utf-8"))
    except Bad as why:
        return no(f"{path} of {run.repo} is not a ledger file: {why}.")
    except Exception as why:  # noqa: BLE001 - GitHub said no, or did not answer
        return no(f"{path} of {run.repo} could not be read ({str(why)[:120]}). The job's token reads the repository the run is in; keep the ledger file there.")
    bad = verify(book)
    if bad or not book:
        return no(f"{path} of {run.repo} does not hold, so nothing of it is signed: {bad[0] if bad else 'it has no batch'}. Run `knos meter verify` on it.")
    buyer, seller = book[0].declared["buyer"], book[0].declared["seller"]
    owner = str(run.env.get("GITHUB_REPOSITORY_OWNER_ID") or "")
    if owner != str(seller if claim else buyer):
        return no(f"A {'claim is the seller' if claim else 'batch is the buyer'}'s own: this ledger's {'seller' if claim else 'buyer'} is GitHub id "
                  f"{seller if claim else buyer}, and this run is in a repository of GitHub id {owner or 'unknown'}.")
    if not claim and str(run.env.get("GITHUB_RUN_ATTEMPT") or "1") != "1":
        return no("This is a re-run, and knos_meter takes a batch only from a run's first attempt: start the workflow again.")
    if m["month"]:
        found = [s for s in book if (s.month, s.seq) == (int(m["month"]), int(m["seq"]))]
        if not found:
            return no(f"{path} has no batch {m['seq']} of {m['month']}.")
    else:
        try:
            from .settle.v2 import meter
            now = meter.yyyymm(run.ledger.now())
            nxt = {month: onchain(run.ledger, buyer, seller, month)[claim].next_seq for month in (meter.prev_month(now), now) if any(s.month == month for s in book)}
            found = [s for month, seq in nxt.items() for s in book if (s.month, s.seq) == (month, seq)][:1]
        except Exception as why:  # noqa: BLE001
            return no(f"Solana could not be read just now ({str(why)[:120]}). Run the workflow again, or name the batch: `--order {path}:<yyyymm>.<seq>`.")
        if not found:       # a run on a timer with no new batch: nothing is wrong, and nothing is signed
            run.note(f"Knos attest: the chain already has every batch {path} of {run.repo} holds for this month and the last one, so there is nothing to sign. "
                     "Add a batch with `knos meter batch` and commit the file.")
            return 0
    b = found[0].batch()
    said = (f"batch {b.seq} of {b.month} in {path} of {run.repo} is {b.count} evaluation(s), {b.accepted} accepted, value {b.value}, root `{b.root.hex()[:12]}`: "
            + (f"the seller's own count (GitHub id {seller}) of its work for buyer {buyer}" if claim else f"the buyer's count (GitHub id {buyer}) for seller {seller}"))
    return sign(run, "eval", batch_audience(b, claim), said, "", 0, None, no)


# -- the commands -----------------------------------------------------------------------------------------------------
def register(app, out, Stop, help_rows: list | None = None, panel: str | None = None) -> None:
    """`knos meter ...`. cli.py calls this once; `help_rows` is its list of one-line summaries, which gets the group's."""
    import sys

    import importlib
    typer = importlib.import_module("typer")       # the command line's package, named here and not imported: the relay reaches this module on an install without it

    meter = typer.Typer(add_completion=False, help="The meter's off-chain ledger: build a batch, check a ledger against the chain, prove one evaluation, "
                                                   "set the buyer's ledger against the seller's.")
    app.add_typer(meter, name="meter")
    if help_rows is not None:
        help_rows.append(("meter", panel, "The meter's ledger: batch, verify, prove, reconcile, export."))

    def read(path: Path) -> list[Stored]:
        try:
            return load(Path(path))
        except OSError:
            raise Stop(f"Cannot read {path}.") from None
        except Bad as why:
            raise Stop(f"{path}: {why}.") from None

    @meter.command("batch")
    def batch_(events: Path = typer.Argument(..., help="evaluations, one a line: ledger lines or knosm:eval:... audiences"),
               ledger: Path = typer.Option(..., "--ledger", help="the ledger file the batch is added to (made if it is not there)"),
               month: str = typer.Option(..., "--month", help="the month the batch is counted in, YYYY-MM"),
               claim: bool = typer.Option(False, "--claim", help="the seller's own count (ClaimBatch) instead of the buyer's (RecordBatch)")) -> None:
        """Add one batch to a ledger and print what its token must say: the root, the totals and the audience."""
        try:
            had = read(ledger) if ledger.exists() else []
            known = {e.id for s in had for e in s.evals}
            given = [parse(x) for x in events.read_text(encoding="utf-8").splitlines() if x.strip()]
            new = [e for e in given if e.id not in known]
            if not new:
                raise Stop(f"All {len(given)} evaluation(s) in {events} are already in {ledger}: there is nothing to add.")
            m = month_of(month)
            b = batch(new, next_seq(had, m), m)
            if had and (b.buyer, b.seller) != (had[0].declared["buyer"], had[0].declared["seller"]):
                raise Stop(f"{ledger} is the ledger of buyer {had[0].declared['buyer']} and seller {had[0].declared['seller']}; these evaluations are of another pair.",
                           "Keep one ledger file per buyer and seller.")
        except OSError:
            raise Stop(f"Cannot read {events}.") from None
        except Bad as why:
            raise Stop(f"{events}: {why}.") from None
        with ledger.open("a", encoding="utf-8", newline="\n") as f:
            f.write(dump([b]))
        if len(new) != len(given):
            out.print(f"Left out {len(given) - len(new)} evaluation(s) that {ledger} already has.", markup=False)
        out.print(f"Batch {b.seq} of {b.month}: {b.count} evaluation(s), {b.accepted} accepted, value {b.value}.", markup=False)
        out.print(f"root      {b.root.hex()}", markup=False)
        out.print(f"audience  {batch_audience(b, claim)}", markup=False)
        out.print(f"Next: have the pinned workflow ask GitHub for a token with that audience and relay it ({'ClaimBatch' if claim else 'RecordBatch'}).", markup=False)

    def net_of(rpc: str):
        from . import chain
        return chain.Ledger(rpc)

    def side(t: Totals) -> str:
        return f"{t.count} evaluation(s) in {t.next_seq} batch(es), {t.accepted} accepted, value {t.value}"

    def two(m: int, pair: tuple[Totals, Totals]) -> str:
        """One month's two counts as the chain has them, side by side."""
        b, s_ = pair
        gap = "the two counts are the same" if (b.count, b.accepted, b.value) == (s_.count, s_.accepted, s_.value) else \
            f"they differ by {abs(b.count - s_.count)} evaluation(s), {abs(b.accepted - s_.accepted)} accepted, value {abs(b.value - s_.value)}"
        return f"{m} on chain: the buyer's count {side(b)} | the seller's claim {side(s_)}: {gap}"

    @meter.command("verify")
    def verify_(ledger: Path = typer.Argument(..., help="a ledger file"),
                onchain_: Path = typer.Option(None, "--onchain", help="the chain's Ledger account for the month as JSON: next_seq, count, accepted, value, chain"),
                month: str = typer.Option(None, "--month", help="which month --onchain is for, YYYY-MM (needed when the ledger has several)"),
                rpc: str = typer.Option(None, "--rpc", metavar="URL", help="read the Ledger accounts from this Solana RPC node and hold every month of the file to them"),
                claim: bool = typer.Option(False, "--claim", help="with --rpc: the file is the seller's, so it is held to the seller's claim account")) -> None:
        """Recompute every root, every total and the running hash of a ledger; with --rpc (or --onchain), compare them with the chain's. Exit 1 if anything differs."""
        got = read(ledger)
        seen: dict = {}
        try:
            chain = Totals.of(json.loads(onchain_.read_text(encoding="utf-8"))) if onchain_ else None
            if rpc:
                try:
                    bad, seen = verify_onchain(got, net_of(rpc), claim)
                except Bad:
                    raise
                except Exception as why:  # noqa: BLE001 - the node said no, or did not answer
                    raise Stop(f"{rpc} did not answer ({str(why)[:120]}).", "Try again, or name another node with --rpc.") from None
            else:
                bad = verify(got, chain, month_of(month) if month else None)
        except (OSError, ValueError) as why:
            raise Stop(f"--onchain: {why}." if isinstance(why, Bad) else f"Cannot read {onchain_} as JSON.") from None
        for line in bad:
            out.print(line, markup=False)
        if bad:
            out.print(f"{ledger} does not hold: {len(bad)} problem(s) above.", markup=False)
            raise typer.Exit(1)
        for m in sorted({s.month for s in got}):
            t = totals(got, m)
            out.print(f"{m}: {t.next_seq} batch(es), {t.count} evaluation(s), {t.accepted} accepted, value {t.value}, running hash {t.chain.hex()}", markup=False)
            if m in seen:
                out.print(two(m, seen[m]), markup=False)
        out.print(f"The ledger holds, and its totals and running hash are those of the {'seller' if claim else 'buyer'}'s account on chain." if rpc else
                  "The ledger holds, and its totals and running hash are the chain's." if chain else
                  "The ledger holds. Compare each month's line with the chain's Ledger account (pass --rpc <url>).", markup=False)

    @meter.command("prove")
    def prove_(ledger: Path = typer.Argument(None, help="a ledger file"),
               id_: str = typer.Argument(None, metavar="ID", help="the evaluation's id, 64 hex characters"),
               check: Path = typer.Option(None, "--check", help="check a proof file instead of making one (needs no ledger)")) -> None:
        """Print the proof that one evaluation is in an anchored batch, as JSON; or check one with --check. Exit 1 if the proof does not hold."""
        try:
            if check:
                p = Proof.of(json.loads(check.read_text(encoding="utf-8")))
                if not p.ok():
                    out.print(f"The proof does not hold: evaluation {p.id.hex()} is not in a batch with root {p.root.hex()}.", markup=False)
                    raise typer.Exit(1)
                out.print(f"The proof holds: evaluation {p.id.hex()} is number {p.index} of {p.size} in the batch with root {p.root.hex()}.", markup=False)
                out.print(f"Next: see that batch {p.seq} of {p.month} was anchored with that root (the RecordBatch or ClaimBatch transaction's log).", markup=False)
                return
            if not ledger or not id_:
                raise Stop("Name a ledger and an evaluation: knos meter prove <ledger> <id>, or check a proof: knos meter prove --check <file>")
            sys.stdout.write(json.dumps(prove(read(ledger), bytes.fromhex(_hex(id_.lower(), 64, "the id"))).json(), indent=1) + "\n")
        except Bad as why:
            raise Stop(f"{why}.") from None
        except (OSError, ValueError):
            raise Stop(f"Cannot read {check} as JSON.") from None

    @meter.command("reconcile")
    def reconcile_(buyer: Path = typer.Argument(..., help="the buyer's ledger"), seller: Path = typer.Argument(..., help="the seller's ledger"),
                   rate: int = typer.Option(RATE, "--rate", help="the fee per evaluation in millionths of a USD (50000 is 0.05; a plan may be 20000)"),
                   free: int = typer.Option(FREE_PER_MONTH, "--free", help="free evaluations the buyer has left for this seller in a month"),
                   as_json: bool = typer.Option(False, "--json", help="print everything as JSON"),
                   rpc: str = typer.Option(None, "--rpc", metavar="URL", help="also read the two on-chain counts of each month from this Solana RPC node and print them side by side")) -> None:
        """Set the buyer's ledger against the seller's: events only one has, different verdicts, duplicates, and the statement both compute alike. Exit 1 if they differ."""
        try:
            r = reconcile(read(buyer), read(seller), rate, free)
        except Bad as why:
            raise Stop(f"{why}.") from None
        seen: dict = {}
        if rpc and r.buyer:
            try:
                net = net_of(rpc)
                seen = {row.month: onchain(net, r.buyer, r.seller, row.month) for row in r.rows}
            except Exception as why:  # noqa: BLE001 - the node said no, or did not answer
                raise Stop(f"{rpc} did not answer ({str(why)[:120]}).", "Try again, or leave --rpc out to compare the two files alone.") from None
        if as_json:
            sys.stdout.write(json.dumps({**r.json(), **({"onchain": {str(m): {"buyer": b.json(), "seller": s_.json()} for m, (b, s_) in seen.items()}} if rpc else {})},
                                        indent=1, sort_keys=True) + "\n")
        else:
            for m, pair in seen.items():
                out.print(two(m, pair), markup=False)
            for name, pairs, said in (("buyer", r.buyer_only, "only the buyer has (the seller has no record of it)"),
                                      ("seller", r.seller_only, "only the seller has (missing from the buyer's count)")):
                for m, e in pairs:
                    out.print(f"{m} {e.id.hex()} {said}: {'accepted' if e.accepted else 'rejected'}, rate {e.rate}", markup=False)
            for d in r.disputed:
                out.print(f"{d.buyer_month} {d.id.hex()} differs in {', '.join(d.what)}: buyer {'accepted' if d.buyer.accepted else 'rejected'} at {d.buyer.rate} in "
                          f"{d.buyer_month}, seller {'accepted' if d.seller.accepted else 'rejected'} at {d.seller.rate} in {d.seller_month}", markup=False)
            for name in ("buyer", "seller"):
                for i in r.duplicates[name]:
                    out.print(f"{i.hex()} is in the {name}'s ledger more than once", markup=False)
            sys.stdout.write(r.statement())
            out.print("The two ledgers agree." if r.agreed else
                      "The two ledgers differ. The statement counts only what both have and describe alike; settle the lines above between you.", markup=False)
        if not r.agreed:
            raise typer.Exit(1)

    @meter.command("export")
    def export_(ledger: Path = typer.Argument(..., help="a ledger file"), to: Path = typer.Option(None, "--out", help="write the CSV here instead of printing it")) -> None:
        """A ledger as CSV, one row per evaluation."""
        text = export_csv(read(ledger))
        if to:
            to.write_text(text, encoding="utf-8", newline="\n")
            out.print(f"Wrote {to}: {text.count(chr(10)) - 1} evaluation(s).", markup=False)
        else:
            sys.stdout.write(text)
