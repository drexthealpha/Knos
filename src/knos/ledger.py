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
    {"accepted":1,"artifact":"<hex40>","buyer":424242,"deliverable":"<hex32>","id":"<hex32>","milestone":0,"order":"<hex32>","policy":"<hex32>","rate":2000000,"seller":555000}
    {"correction":{"batch":"202610.0","by":424242,"id":"<hex32>","kind":"duplicate"}}

`id` is the 32 bytes the single mode already bills once: sha256(work order || artifact, its 40 characters || policy ||
milestone u32 little-endian), `EvalAud::key` in programs-v2/knos_meter/src/gh.rs. `deliverable` is what was bought:
sha256(work order || milestone), the same for every artifact that carried it. The tree is RFC 6962's:
leaf = sha256(0x00 || id), node = sha256(0x01 || left || right), over the ids sorted ascending, none twice, then one
leaf sha256(0x02 || sha256(line)) per correction line of the batch.

That tree is commitment format 1, and it binds the set of evaluation ids, the count, the accepted count and the value;
not which evaluation was accepted. A new batch is format 2 (`FORMAT`, `BINDS`): each leaf is the hash of the whole
event in canonical bytes (`FIELDS`, `encode_event`, `event_hash`), the header says `"format":2` beside the root, and
the format is inside what is hashed, so a root or a proof of one format never checks as the other. `migrate`
re-commits a format 1 batch as a new batch that names it and rewrites nothing. No root proves that every evaluation
was supplied: that is `reconcile`'s, from two ledgers kept independently.

What the program cannot see is decided here, off chain. `canonical` is the one function that says what counts once
(within a batch, across batches, against the individual mode) and applies the corrections; `numbers` gives a month's
three numbers (evaluations, accepted outcomes, rejected evaluations); `close` sets the buyer's ledger against the
seller's and writes the record both sign, `agreed` or `disputed`; `statement` prints a month and refuses a disputed
one; `month_bundle` and `verify_month` keep a closed month in one archive that is checked with no network.

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

from . import ids

FREE_PER_MONTH = 100_000    # the price book's Meter line: an organisation's first evaluations of a month cost nothing
RATE = 2_000                # then 0.002 USD each, in millionths, from prepaid credits (knos_meter on devnet keeps its own constants: knos.settle.v2.meter)
MICRO = 1_000_000
ZERO = bytes(32)            # a Ledger account's running hash before its first batch
_HEX = set("0123456789abcdef")
_CURRENCY = re.compile(r"[A-Za-z0-9._:-]{0,64}")

# The commitment format of a batch: what its 32-byte root is a hash of. The program reads the root as 32 opaque bytes,
# so the format is the ledger's to state and a reader's to check: it is inside what is hashed, and written beside the root.
FORMAT = 2                  # what a new batch is written in
FORMATS = (1, 2)
BINDS = {1: "the set of evaluation ids, the count, the accepted count and the value; not which evaluation was accepted",
         2: "every field of every evaluation: its four ids, verdict, amount and currency, buyer and seller, policy, artifact, evidence digest, evaluator, "
            "run, month and sequence; not that every evaluation was supplied"}


class Bad(ValueError):
    """A line or a ledger that cannot be read as what it says it is. The message is for the person who has the file."""


def _sha(*parts: bytes) -> bytes:
    return hashlib.sha256(b"".join(parts)).digest()


def canon(obj) -> str:
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
def deliverable_id(order: bytes, milestone: int) -> bytes:
    """What was bought: the work order and the milestone, sha256(order || milestone as u32 little-endian). It is the
    same whatever number of pull requests or artifacts carried the work, so ten evaluations of ten artifacts for one
    milestone share it. An accepted outcome is counted per deliverable, never per evaluation."""
    return _sha(order, milestone.to_bytes(4, "little"))


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
    verdict: str = ""   # one of the four verdicts when the line says one; "" for a line that says accepted 1 or 0 only
    evaluator: str = ""     # who judged, as `<judge>@<version>`, when the writer knows; it is a part of the evaluation's id
    run: str = ""       # the run the issuer signed for, when the writer knows; a part of the evaluation's id
    inv: str = ""       # the invoice line that names this deliverable, when one is known (an inv_ id)
    stl: str = ""       # the settlement of this deliverable, when money moved for it (an stl_ id); only on an accepted line
    currency: str = ""  # what `rate` counts, when the writer says: a currency code or a mint's address
    evidence: str = ""  # sha256 of the issuer-signed token or receipt this verdict rests on, 32 bytes as hex, when the writer has it

    def __post_init__(self) -> None:
        _int(self.buyer, "buyer", least=1), _int(self.seller, "seller", least=1)
        _hex(self.order, 64, "order"), _hex(self.artifact, 40, "artifact"), _hex(self.policy, 64, "policy")
        _int(self.milestone, "milestone", 2 ** 32 - 1), _int(self.rate, "rate")
        if not isinstance(self.accepted, bool):
            raise Bad("accepted must be 1 or 0")
        if self.verdict not in ("", *ids.VERDICTS) or (self.verdict and self.accepted != (self.verdict == "accepted")):
            raise Bad("a line's verdict is accepted, rejected, insufficient_evidence or disputed, and accepted is 1 for the verdict accepted and 0 for the "
                      "other three")
        if not all(isinstance(x, str) and len(x) <= 200 for x in (self.evaluator, self.run)):
            raise Bad("evaluator and run are texts of at most 200 characters")
        for kind, got in (("invoice_line", self.inv), ("settlement", self.stl)):
            if got:
                try:
                    ids.expect(kind, got)
                except ValueError as why:
                    raise Bad(str(why)) from None
        if not isinstance(self.currency, str) or not _CURRENCY.fullmatch(self.currency):
            raise Bad("currency is a code or an address: at most 64 letters, digits, dots, colons, dashes and underscores")
        if self.evidence != "":
            _hex(self.evidence, 64, "evidence")
        if self.stl and not self.accepted:
            raise Bad("a settlement is named on an accepted line only: a verdict that is not accepted authorises no payment")
        if (self.evaluator or self.run or self.inv or self.stl) and not self.verdict:
            raise Bad("a line that names its evaluator, run, invoice line or settlement also says its verdict in words")

    @property
    def stands(self) -> str:
        """The verdict in one of the four words: the one the line says, else accepted or rejected from its 1 or 0."""
        return self.verdict or ("accepted" if self.accepted else "rejected")

    @property
    def dlv(self) -> str:
        """The deliverable's id as every interface writes it (knos.ids): the order and the milestone."""
        return ids.deliverable(self.order, self.milestone)

    @property
    def evl(self) -> str:
        """The evaluation's id as every interface writes it: this deliverable, artifact and policy, and the evaluator
        and run when the line names them (empty when it does not: then it is one id per deliverable, artifact and policy)."""
        return ids.evaluation(self.dlv, self.artifact, self.policy, self.evaluator, self.run)

    def ids(self) -> dict:
        """The four ids of this line; null for the invoice line and the settlement the ledger was not told."""
        return {"deliverable": self.dlv, "evaluation": self.evl, "invoice_line": self.inv or None, "settlement": self.stl or None}

    def entry(self) -> dict:
        """The line as an interface shows it: its fields, the verdict in words and the four ids, whatever the line wrote."""
        return {**json.loads(self.line()), "verdict": self.stands, "ids": self.ids()}

    @property
    def id(self) -> bytes:
        return eval_id(bytes.fromhex(self.order), self.artifact, bytes.fromhex(self.policy), self.milestone)

    @property
    def deliverable(self) -> str:
        return deliverable_id(bytes.fromhex(self.order), self.milestone).hex()

    @property
    def value(self) -> int:
        """What it adds to the batch's value: its rate when accepted, nothing when rejected."""
        return self.rate if self.accepted else 0

    def audience(self) -> str:
        """The audience the single mode's token is signed for (`eval_aud` in gh.rs)."""
        return f"knosm:eval:{self.buyer}:{self.seller}:{self.order}:{self.artifact}:{self.policy}:{self.milestone}:{int(self.accepted)}:{self.rate}"

    def line(self) -> str:
        """The ledger line. A line that says its verdict in words also carries its ids (`dlv`, `evl`, and `inv`, `stl`,
        `evaluator`, `run` when known); a line that does not is written as 0.3.16 wrote it, byte for byte."""
        more: dict = {} if not self.verdict else {"verdict": self.verdict, "dlv": self.dlv, "evl": self.evl,
                                            **{k: v for k, v in (("evaluator", self.evaluator), ("run", self.run), ("inv", self.inv), ("stl", self.stl)) if v}}
        more.update({k: v for k, v in (("currency", self.currency), ("evidence", self.evidence)) if v})
        return canon({"accepted": int(self.accepted), "artifact": self.artifact, "buyer": self.buyer, "deliverable": self.deliverable, "id": self.id.hex(), "milestone": self.milestone,
                      "order": self.order, "policy": self.policy, "rate": self.rate, "seller": self.seller, **more})


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
    if not all(isinstance(o.get(k, ""), str) for k in ("verdict", "evaluator", "run", "inv", "stl", "dlv", "evl", "currency", "evidence")) or o.get("verdict", "x") == "":
        raise Bad("verdict, evaluator, run, dlv, evl, inv and stl are texts, and a verdict is one of the four words")
    e = Evaluation(o["buyer"], o["seller"], o["order"], o["artifact"], o["policy"], o["milestone"], o["accepted"] == 1, o["rate"],
                   o.get("verdict", ""), o.get("evaluator", ""), o.get("run", ""), o.get("inv", ""), o.get("stl", ""), o.get("currency", ""), o.get("evidence", ""))
    for key, kind, want in (("dlv", "deliverable", e.dlv), ("evl", "evaluation", e.evl)):
        if key in o:
            try:
                ids.expect(kind, o[key])
            except ValueError as why:
                raise Bad(f"{key}: {why}") from None
            if o[key] != want:
                raise Bad(f"{key} {o[key]} is not the {kind} id of this line's own fields ({want})")
    if "id" in o and o["id"] != e.id.hex():
        raise Bad(f"the id {str(o['id'])[:16]}... is not the id of this order, artifact, policy and milestone")
    if "deliverable" in o and o["deliverable"] != e.deliverable:
        raise Bad(f"the deliverable {str(o['deliverable'])[:16]}... is not the one of this order and milestone")
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


def correction_leaf(key: bytes) -> bytes:
    """A correction's leaf. Its prefix is neither an evaluation's (0x00) nor a node's (0x01), so no correction can be
    read as an evaluation and no evaluation as a correction."""
    return _sha(b"\x02", key)


def _leaves(ids, corrections=()) -> list[bytes]:
    """The evaluations' leaves in ascending order of id, then the corrections' in ascending order of key. A batch with
    no correction has exactly the tree it had before corrections existed."""
    return [leaf(i) for i in sorted(set(ids))] + [correction_leaf(k) for k in sorted(set(corrections))]


def merkle_root(ids, corrections=()) -> bytes:
    """The root over these ids, sorted ascending, each once, followed by the keys of the batch's corrections. No
    leaves: sha256 of nothing, as the RFC has it."""
    return _tree(_leaves(ids, corrections))


def inclusion_path(ids, id_: bytes, corrections=()) -> tuple[int, list[bytes]]:
    """(index among the leaves, the sibling hashes from the leaf up) of an evaluation's id, or of a correction's key."""
    order, keys = sorted(set(ids)), sorted(set(corrections))
    if id_ not in order and id_ not in keys:
        raise Bad("that evaluation or correction is not in the batch")
    m = order.index(id_) if id_ in order else len(order) + keys.index(id_)
    return m, _path(m, _leaves(ids, corrections))


def check_proof(id_: bytes, index: int, size: int, path: list[bytes], root: bytes, correction: bool = False) -> bool:
    """Whether `id_` is leaf `index` of a tree of `size` leaves with this root (RFC 9162, section 2.1.3.2). Needs
    nothing but the proof and the root: not the ledger, not the other evaluations. `correction`: `id_` is a
    correction's key, not an evaluation's id."""
    if not 0 <= index < size:
        return False
    fn, sn, r = index, size - 1, (correction_leaf if correction else leaf)(id_)
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


# -- commitment format 2: the leaf is the complete event ----------------------------------------------------------------
# One evaluation as the eighteen texts format 2 hashes, in this order. Every one is UTF-8; a whole number is written in
# decimal with no leading zero; a field the line does not state is the empty text, and its emptiness is hashed too.
FIELDS = ("deliverable_id", "evaluation_id", "invoice_line_id", "settlement_id", "verdict", "amount", "currency", "buyer", "seller", "order", "milestone",
          "policy", "artifact", "evidence", "evaluator", "run", "month", "seq")
EVENT_TAG = b"knos.event\x00"
LEAF2, NODE2, FIX2, ROOT2 = b"knos.leaf.2\x00", b"knos.node.2\x00", b"knos.fix.2\x00", b"knos.root.2\x00"
_DEC = re.compile(r"0|[1-9][0-9]{0,19}")


def event_fields(e: "Evaluation", month: int, seq: int) -> tuple[str, ...]:
    """The texts of FIELDS for one evaluation counted in batch `seq` of `month`."""
    return (e.dlv, e.evl, e.inv, e.stl, e.stands, str(e.rate), e.currency, str(e.buyer), str(e.seller), e.order, str(e.milestone), e.policy, e.artifact,
            e.evidence, e.evaluator, e.run, f"{int(month):06d}", str(int(seq)))


def event_problem(fields) -> str | None:
    """Why these are not the eighteen texts of one evaluation, or None. The two ids that can be recomputed are: a proof
    cannot say one deliverable and carry another's order."""
    if not isinstance(fields, (tuple, list)) or len(fields) != len(FIELDS) or not all(isinstance(x, str) for x in fields):
        return f"an event is {len(FIELDS)} texts: " + ", ".join(FIELDS)
    f = dict(zip(FIELDS, fields))
    if f["verdict"] not in ids.VERDICTS:
        return "the verdict is accepted, rejected, insufficient_evidence or disputed"
    if not all(_DEC.fullmatch(f[k]) and int(f[k]) < 2 ** 64 for k in ("amount", "buyer", "seller", "milestone", "seq")) or not re.fullmatch(r"[0-9]{6}", f["month"]):
        return "amount, buyer, seller, milestone and seq are whole numbers in decimal with no leading zero, and the month is six digits"
    if not all(len(f[k]) == n and set(f[k]) <= _HEX for k, n in (("order", 64), ("policy", 64), ("artifact", 40))) \
            or not (f["evidence"] == "" or (len(f["evidence"]) == 64 and set(f["evidence"]) <= _HEX)) or int(f["milestone"]) >= 2 ** 32:
        return "order, policy and evidence are 64 lowercase hex characters (evidence may be empty) and the artifact is 40"
    dlv = ids.deliverable(f["order"], int(f["milestone"]))
    if f["deliverable_id"] != dlv or f["evaluation_id"] != ids.evaluation(dlv, f["artifact"], f["policy"], f["evaluator"], f["run"]):
        return "the deliverable id or the evaluation id is not the id of the event's own order, milestone, artifact, policy, evaluator and run"
    for key, kind in (("invoice_line_id", "invoice_line"), ("settlement_id", "settlement")):
        if f[key] and ids.kind_of(f[key]) != kind:
            return f"{key} is not {'an' if kind[0] == 'i' else 'a'} {kind.replace('_', ' ')} id"
    return None


def encode_event(fields) -> bytes:
    """THE canonical bytes of one event, the same in every language: the tag `knos.event` and a zero byte, the format
    as one byte (2), the number of fields as one byte (18), then each field of FIELDS in order as its length in bytes
    (u32 big-endian) and its UTF-8 bytes. No JSON, no separators, no optional field: nothing to write two ways."""
    why = event_problem(fields)
    if why:
        raise Bad(why)
    out = [EVENT_TAG, bytes([2, len(FIELDS)])]
    for x in fields:
        raw = x.encode("utf-8")
        out += [len(raw).to_bytes(4, "big"), raw]
    return b"".join(out)


def event_key(fields) -> bytes:
    """The 32-byte evaluation id of an event's fields: what the leaves of a batch are sorted by, and what the program bills once."""
    f = dict(zip(FIELDS, fields))
    return eval_id(bytes.fromhex(f["order"]), f["artifact"], bytes.fromhex(f["policy"]), int(f["milestone"]))


def leaf2(fields) -> bytes:
    """A format 2 leaf: sha256(`knos.leaf.2` 0x00 || the event's canonical bytes)."""
    return _sha(LEAF2, encode_event(fields))


def event_hash(e: "Evaluation", month: int, seq: int) -> bytes:
    """The hash of one evaluation as an event: its format 2 leaf. The one definition: the batch's tree and the log of
    events (knos.events) both use this function, so they cannot disagree about what an event is."""
    return leaf2(event_fields(e, month, seq))


def correction_leaf2(key: bytes) -> bytes:
    return _sha(FIX2, key)


def _node2(left: bytes, right: bytes) -> bytes:
    return _sha(NODE2, left, right)


def _top(hashes: list[bytes], node) -> bytes:
    """The tree over these leaf hashes, split at the largest power of two below their number (RFC 6962's shape). A
    last leaf with no sibling is carried up as it is and never hashed with a copy of itself, so a tree of three leaves
    and a tree of four whose last two are the same are different trees."""
    if len(hashes) == 1:
        return hashes[0]
    k = _split(len(hashes))
    return node(_top(hashes[:k], node), _top(hashes[k:], node))


def _path2(m: int, hashes: list[bytes]) -> list[bytes]:
    if len(hashes) <= 1:
        return []
    k = _split(len(hashes))
    return _path2(m, hashes[:k]) + [_top(hashes[k:], _node2)] if m < k else _path2(m - k, hashes[k:]) + [_top(hashes[:k], _node2)]


def seal2(size: int, top: bytes) -> bytes:
    """A format 2 root: sha256(`knos.root.2` 0x00 || the number of leaves, u32 big-endian || the top of the tree; no
    leaves: nothing after the number). The format and the size are inside the hash, so a format 1 root is never a
    format 2 root, and a subtree is never a batch."""
    return _sha(ROOT2, int(size).to_bytes(4, "big"), top)


def _leaves2(events, corrections=()) -> tuple[list[bytes], list[bytes], list[bytes]]:
    """(the events' keys in ascending order, the corrections' keys in ascending order, every leaf hash in that order).
    Two events with one key are refused: a batch says one thing about each evaluation."""
    by: dict[bytes, bytes] = {}
    for fields in events:
        k = event_key(fields) if event_problem(fields) is None else b""
        if k in by:
            raise Bad(f"evaluation {k.hex()[:16]}... is in this batch twice: a format 2 batch holds each evaluation once")
        by[k] = leaf2(fields)
    keys = sorted(set(corrections))
    order = sorted(by)
    return order, keys, [by[k] for k in order] + [correction_leaf2(k) for k in keys]


def merkle_root2(events, corrections=()) -> bytes:
    """The format 2 root over these events (each the texts of FIELDS), sorted by evaluation id ascending, each once,
    followed by the keys of the batch's corrections, sorted ascending, as leaves sha256(`knos.fix.2` 0x00 || key);
    a node is sha256(`knos.node.2` 0x00 || left || right)."""
    _order, _keys, hashes = _leaves2(events, corrections)
    return seal2(len(hashes), _top(hashes, _node2) if hashes else b"")


def _climb(r: bytes, index: int, size: int, path: list[bytes], node) -> bytes | None:
    """The top of a tree of `size` leaves, from leaf hash `r` at `index` and its siblings (RFC 9162, 2.1.3.2)."""
    if not 0 <= index < size:
        return None
    fn, sn = index, size - 1
    for p in path:
        if sn == 0:
            return None
        if fn & 1 or fn == sn:
            r = node(p, r)
            while not fn & 1 and fn:
                fn, sn = fn >> 1, sn >> 1
        else:
            r = node(r, p)
        fn, sn = fn >> 1, sn >> 1
    return r if sn == 0 else None


def check_proof2(fields, index: int, size: int, path: list[bytes], root: bytes, correction: bytes | None = None) -> bool:
    """Whether the event with these fields (or, with `correction`, the correction with that key) is leaf `index` of a
    format 2 batch of `size` leaves with this root. It needs the proof and the root only. What holds then: that batch
    committed to exactly this verdict and this amount for this deliverable, and to every other field given."""
    try:
        leaf_ = correction_leaf2(correction) if correction is not None else leaf2(fields)
    except Bad:
        return False
    top = _climb(leaf_, index, size, list(path), _node2)
    return top is not None and seal2(size, top) == root


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
    corrections: tuple["Correction", ...] = field(default=(), compare=False)
    format: int = field(default=1, compare=False)   # the commitment format of `root`; an audience alone does not say it

    @property
    def binds(self) -> str:
        """What this batch's root commits to, in words."""
        return BINDS[self.format]

    def header(self) -> str:
        """A format 1 header is written as it always was, byte for byte; a later format names itself."""
        return canon({"batch": {"accepted": self.accepted, "buyer": self.buyer, "count": self.count, "month": self.month, "root": self.root.hex(),
                                    "seller": self.seller, "seq": self.seq, "value": self.value, **({"format": self.format} if self.format != 1 else {})}})

    def lines(self) -> list[str]:
        return [self.header(), *(e.line() for e in self.evals), *(c.line() for c in self.corrections)]


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


def root_of(evals, month: int, seq: int, keys=(), format: int = FORMAT) -> bytes:
    """The root of these evaluations and correction keys as a batch `seq` of `month`, in one commitment format."""
    if format == 1:
        return merkle_root([e.id for e in evals], keys)
    if format != 2:
        raise Bad(f"commitment format {format} is not one this version reads (it reads {', '.join(map(str, FORMATS))})")
    return merkle_root2([event_fields(e, month, seq) for e in evals], keys)


def batch(lines, seq: int, month: int | str, corrections=(), format: int = FORMAT) -> Batch:
    """A batch from evaluations (ledger lines, audiences or Evaluation objects). The same evaluation given twice (a
    retry) is counted once; two that share an id and differ in verdict or rate are refused, because a batch says one
    thing about each evaluation. All must be of one buyer and one seller. `corrections` ride in the batch's tree and
    change none of its three numbers: the chain's counters only go up, and the statement nets them. `format`: the
    commitment format of the root, 2 unless an old batch is being recomputed (BINDS says what each one binds)."""
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
    fixes = tuple(sorted({c.key: c for c in corrections}.values(), key=lambda c: c.key))
    m = month_of(month)
    return Batch(buyer, seller, m, _int(seq, "seq"), len(evals), sum(e.accepted for e in evals), sum(e.value for e in evals),
                 root_of(evals, m, seq, [c.key for c in fixes], format), evals, fixes, format)


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
    corrections: list = field(default_factory=list)     # the correction lines under it
    superseded: dict | None = None      # the header of the format 2 batch that re-commits this one (`knos meter migrate`), when the file has one

    @property
    def format(self) -> int:
        """The commitment format the header states: 1 when it states none (every batch before format 2 existed)."""
        return self.declared.get("format", 1)

    @property
    def month(self) -> int:
        return self.declared["month"]

    @property
    def seq(self) -> int:
        return self.declared["seq"]

    def batch(self) -> Batch:
        """The batch recomputed from the lines (never from the header's root or totals)."""
        return batch(self.evals, self.seq, self.month, self.corrections, self.format)

    def recommitted(self) -> Batch:
        """The same lines as a format 2 batch: what a batch that supersedes this one must say."""
        return batch(self.evals, self.seq, self.month, self.corrections, 2)


def load(text: str | Path) -> list[Stored]:
    """The batches of a ledger file (a path, or the text itself), in the file's order. Reads; `verify` judges."""
    if isinstance(text, Path):
        text = text.read_text(encoding="utf-8")
    out: list[Stored] = []
    closed = False
    for n, raw in enumerate(text.splitlines(), 1):
        if not raw.strip():
            continue
        try:
            o = json.loads(raw)
        except ValueError:
            raise Bad(f"line {n} is not JSON") from None
        if isinstance(o, dict) and "batch" in o:
            h = o["batch"]
            if not isinstance(h, dict) or set(h) - {"format", "supersedes"} != {"accepted", "buyer", "count", "month", "root", "seller", "seq", "value"} \
                    or ("supersedes" in h and "format" not in h):
                raise Bad(f"line {n}: a batch header has accepted, buyer, count, month, root, seller, seq and value, and its format when that is not 1")
            if "format" in h and (h["format"] != 2 or isinstance(h["format"], bool)):
                raise Bad(f"line {n}: a header names its commitment format only when it is 2 (a format 1 header names none); this version reads no other")
            try:
                for k in ("accepted", "buyer", "count", "seller", "seq", "value"):
                    _int(h[k], k)
                month_of(_int(h["month"], "month")), _hex(h["root"], 64, "root")
            except Bad as why:
                raise Bad(f"line {n}: {why}") from None
            if "supersedes" in h:
                # A batch that re-commits an earlier one in format 2. It has no lines of its own: its events are the
                # lines of the batch it names, which stay where and as they were.
                old = [s for s in out if f"{s.month}.{s.seq}:{s.declared['root']}" == h["supersedes"] and s.format == 1 and s.superseded is None]
                if len(old) != 1 or (old[0].month, old[0].seq) != (h["month"], h["seq"]):
                    raise Bad(f"line {n}: a batch that supersedes another names one earlier format 1 batch of this file as <yyyymm>.<seq>:<its root>, once, "
                              "and keeps its month and seq")
                old[0].superseded, closed = {**h, "at": n}, True
                continue
            out.append(Stored(h, [], n))
            closed = False
            continue
        if not out:
            raise Bad(f"line {n}: an evaluation before any batch header")
        if closed:
            raise Bad(f"line {n}: a batch that supersedes another has no lines of its own")
        try:
            if isinstance(o, dict) and "correction" in o:
                out[-1].corrections.append(Correction.of(o))
                continue
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


def _structure(ledger: list[Stored]) -> list[str]:
    """What is wrong with a ledger as a file: roots, totals, numbering, corrections that point at nothing. Repeats are
    `verify`'s second half: a repeat is a fact about what was anchored, and a correction answers it."""
    bad: list[str] = []
    if len({(s.declared["buyer"], s.declared["seller"]) for s in ledger}) > 1:
        bad.append("the file holds batches of more than one buyer and seller: keep one file per pair")
    held = {(s.month, s.seq): {e.id.hex() for e in s.evals} for s in ledger}
    keys: set[bytes] = set()
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
            other = next((f for f in FORMATS if f != s.format and root_of(b.evals, b.month, b.seq, [c.key for c in b.corrections], f).hex() == d["root"]), None)
            bad.append(f"{where}: the lines give root {b.root.hex()} in format {s.format}, the header says {d['root']}: "
                       + (f"that is the root of these lines in format {other}, and a root of one format is never taken as a root of another" if other else
                          "a line was changed, added or removed"))
        if s.superseded is not None:
            n2, h = s.recommitted(), s.superseded
            if (n2.root.hex(), n2.count, n2.accepted, n2.value, n2.buyer, n2.seller) != (h["root"], h["count"], h["accepted"], h["value"], h["buyer"], h["seller"]):
                bad.append(f"{where}: the batch at line {h['at']} that supersedes it does not commit to these lines in format 2 (they give root {n2.root.hex()}, "
                           f"count {n2.count}, accepted {n2.accepted}, value {n2.value})")
        if (b.count, b.accepted, b.value) != (d["count"], d["accepted"], d["value"]):
            bad.append(f"{where}: the lines give count {b.count}, accepted {b.accepted}, value {b.value}; the header says {d['count']}, {d['accepted']}, {d['value']}")
        for c in s.corrections:
            said = f"{where}: the correction of evaluation {c.id[:16]}... in batch {c.seq} of {c.month}"
            if c.by not in (d["buyer"], d["seller"]):
                bad.append(f"{said} is issued by GitHub id {c.by}, which is neither this ledger's buyer nor its seller")
            if (c.month, c.seq) >= (s.month, s.seq) or c.id not in held.get((c.month, c.seq), ()):
                bad.append(f"{said} names an evaluation that no earlier batch of this ledger holds there: a correction refers to a batch before its own")
            if c.key in keys:
                bad.append(f"{said} is written twice: keep one")
            keys.add(c.key)
    for m in sorted({s.month for s in ledger}):
        seqs = sorted(s.seq for s in ledger if s.month == m)
        if seqs != list(range(len(seqs))):
            bad.append(f"month {m}: its batches are numbered {seqs}, not 0 to {len(seqs) - 1}: one is missing or repeated")
    return bad


def verify(ledger: list[Stored], onchain: Totals | None = None, month: int | None = None, individual=None) -> list[str]:
    """Everything wrong with a ledger, in words; an empty list means it holds. Every root and total is recomputed
    from the lines; a month's batches must be numbered 0, 1, 2, ...; and no evaluation may be counted twice: in two
    batches, or in a batch and singly (`individual`: the ids the individual mode recorded). The chain cannot see a
    repeat in batch mode, because it has no account per evaluation, so this check is the only one. A repeat that is
    anchored was billed twice and cannot be taken back on chain; it stops failing here once a `duplicate` correction
    for it is in a later batch. With `onchain`, the month's totals and running hash must be the chain's (`month` may
    be left out when the ledger has one)."""
    bad = _structure(ledger)
    for r in canonical(ledger, individual or ()).dropped:
        if r.reason in (BATCH, SINGLY) and r.corrected is None:
            bad.append(f"batch {r.seq} of {r.month}: evaluation {r.id.hex()} is {r.where()}: it is counted twice. If batch {r.seq} is not anchored yet, take the line out "
                       f"and build the batch again; if it is anchored, the chain billed it twice: run `knos meter correct <ledger> {r.id.hex()} --batch "
                       f"{r.month}.{r.seq} --kind duplicate` and anchor the next batch, which carries the correction")
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
    correction: bool = False    # `id` is a correction's key: its leaf has the corrections' prefix
    format: int = 1             # the commitment format of `root`
    event: tuple[str, ...] | None = None    # format 2, an evaluation: the texts of FIELDS the leaf is the hash of

    @property
    def binds(self) -> str:
        return BINDS[self.format]

    def ok(self) -> bool:
        """Format 1: the id is in the batch. Format 2: the event is, with the verdict, the amount and every other field
        the proof states, and it is the event of this id, month and seq. A proof of one format never holds as the other."""
        if self.format == 1:
            return self.event is None and check_proof(self.id, self.index, self.size, list(self.path), self.root, self.correction)
        if self.correction:
            return self.event is None and check_proof2(None, self.index, self.size, list(self.path), self.root, self.id)
        if self.format != 2 or self.event is None or event_problem(self.event) is not None:
            return False
        f = dict(zip(FIELDS, self.event))
        return (event_key(self.event), int(f["month"]), int(f["seq"])) == (self.id, self.month, self.seq) \
            and check_proof2(self.event, self.index, self.size, list(self.path), self.root)

    def json(self) -> dict:
        """A format 1 proof is written as it always was; a format 2 proof names its format and carries the event."""
        return {"id": self.id.hex(), "index": self.index, "month": self.month, "path": [p.hex() for p in self.path], "root": self.root.hex(), "seq": self.seq,
                "size": self.size, **({"correction": 1} if self.correction else {}),
                **({"format": self.format} if self.format != 1 else {}), **({"event": dict(zip(FIELDS, self.event))} if self.event is not None else {})}

    @classmethod
    def of(cls, o: dict) -> "Proof":
        try:
            return cls(bytes.fromhex(_hex(o["id"], 64, "id")), _int(o["month"], "month"), _int(o["seq"], "seq"), _int(o["index"], "index"), _int(o["size"], "size"),
                       tuple(bytes.fromhex(_hex(p, 64, "a path entry")) for p in o["path"]), bytes.fromhex(_hex(o["root"], 64, "root")), o.get("correction") == 1,
                       cls._format(o), cls._event(o))
        except (KeyError, TypeError):
            raise Bad("a proof has id, month, seq, index, size, path and root, and from format 2 on its format and the event") from None

    @staticmethod
    def _format(o: dict) -> int:
        f = o.get("format", 1)
        if f not in FORMATS or isinstance(f, bool) or ("format" in o and f == 1):
            raise Bad("a proof names its commitment format only when it is 2; this version reads no other")
        return f

    @staticmethod
    def _event(o: dict) -> tuple[str, ...] | None:
        ev = o.get("event")
        if ev is None:
            return None
        if not isinstance(ev, dict) or tuple(sorted(ev)) != tuple(sorted(FIELDS)) or event_problem(tuple(ev[k] for k in FIELDS)):
            raise Bad("a proof's event is these texts: " + ", ".join(FIELDS))
        return tuple(ev[k] for k in FIELDS)


def prove(ledger: list[Stored], id_: bytes, format: int | None = None) -> Proof:
    """The inclusion proof of one evaluation (by its id) or of one correction (by its key), from the first batch that
    holds it. `size` is the batch's leaves: its evaluations and then its corrections. The proof is in the batch's own
    format, or in format 2 when a batch that supersedes it is in the file; `format` asks for one of the two."""
    for s in ledger:
        if id_ not in [e.id for e in s.evals] and id_ not in [c.key for c in s.corrections]:
            continue
        f = format or (2 if s.superseded is not None else s.format)
        if f != s.format and not (f == 2 and s.superseded is not None):
            raise Bad(f"batch {s.seq} of {s.month} is committed in format {s.format} only: a proof in format {f} needs a batch that says so "
                      "(`knos meter migrate` re-commits a format 1 batch)")
        b = s.batch() if f == s.format else s.recommitted()
        ids_, keys = [e.id for e in b.evals], [c.key for c in b.corrections]
        if f == 1:
            index, path = inclusion_path(ids_, id_, keys)
            return Proof(id_, b.month, b.seq, index, len(ids_) + len(keys), tuple(path), b.root, id_ not in ids_)
        events = [event_fields(e, b.month, b.seq) for e in b.evals]
        order, fixes, hashes = _leaves2(events, keys)
        index = order.index(id_) if id_ in order else len(order) + fixes.index(id_)
        return Proof(id_, b.month, b.seq, index, len(hashes), tuple(_path2(index, hashes)), b.root, id_ not in order, 2,
                     next((x for x in events if event_key(x) == id_), None))
    raise Bad(f"{id_.hex()} is in no batch of this ledger, as an evaluation or as a correction")


def migrate(ledger: list[Stored], month: int | str | None = None) -> list[str]:
    """The header lines that re-commit this ledger's format 1 batches (of one month, or of all) in format 2, one new
    batch for each, to be appended to the file. Nothing already written is changed: the old batch, its root and its
    lines stay, and the new batch names it as `<yyyymm>.<seq>:<its root>`. The new batch has no lines of its own and
    the old one's month, seq and three numbers, so the count is the same count: it is the same evaluations, hashed in
    full. The program takes each evaluation into its totals once, so the new root is not sent as a RecordBatch."""
    m = month_of(month) if month is not None else None
    out = []
    for s in ledger:
        if s.format == 1 and s.superseded is None and m in (None, s.month):
            b = s.recommitted()
            if b.count != len(s.evals) or s.batch().root.hex() != s.declared["root"]:
                raise Bad(f"batch {s.seq} of {s.month} does not hold as it is: run `knos meter verify` first")
            out.append(canon({"batch": {"accepted": b.accepted, "buyer": b.buyer, "count": b.count, "format": 2, "month": b.month, "root": b.root.hex(),
                                        "seller": b.seller, "seq": b.seq, "supersedes": f"{s.month}.{s.seq}:{s.declared['root']}", "value": b.value}}))
    return out


def commitments(ledger: list[Stored]) -> list[dict]:
    """Every batch of a ledger with the format of its root and what that root binds, in words: what every surface that
    shows a batch says of it."""
    return [{"month": s.month, "seq": s.seq, "format": s.format, "root": s.declared["root"], "binds": BINDS[s.format],
             **({"superseded_by": {"format": 2, "root": s.superseded["root"], "binds": BINDS[2]}} if s.superseded else {})} for s in ledger]


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
    fields: tuple[str, ...] = ()        # every field of FIELDS the two differ in, by name (apart from seq, which is each side's own)


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
    verdicts: dict = field(default_factory=dict, compare=False)     # of `count`: how many of each of the four verdicts
    accepted_outcomes: int = field(default=0, compare=False)    # deliverables among them first accepted this month: billed once each


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
    formats: dict = field(default_factory=dict)         # {"buyer": (1, 2), "seller": (2,)}: the commitment formats of each ledger's batches
    corrections: dict = field(default_factory=dict)     # {"buyer": (...), "seller": (...)}: each side's corrections, and whether the other carries the same

    @property
    def complete(self) -> bool:
        """Whether both ledgers are format 2 throughout, so that every field of every evaluation was compared."""
        return all(tuple(self.formats.get(k, ())) in ((), (2,)) for k in ROLES)

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
        ev = lambda pairs: [{"month": m, **e.entry()} for m, e in pairs]  # noqa: E731
        one = lambda m, e: {"month": m, "accepted": int(e.accepted), "verdict": e.stands, "rate": e.rate}  # noqa: E731
        return {"agreed": self.agreed, "buyer_only": ev(self.buyer_only), "seller_only": ev(self.seller_only),
                "disputed": [{"id": d.id.hex(), "ids": d.buyer.ids(), "what": list(d.what), "buyer": one(d.buyer_month, d.buyer),
                              "seller": one(d.seller_month, d.seller)} for d in self.disputed],
                "duplicates": {k: [i.hex() for i in v] for k, v in self.duplicates.items()},
                "statement": [vars(r) for r in self.rows], **self.findings()}

    def findings(self) -> dict:
        """The four things two independent ledgers can show that neither root can: what one side left out, what one
        side entered twice, what both hold and describe differently (each differing field by name), and the
        corrections each side carries. A root commits to what was supplied; only this comparison finds what was not."""
        return {"formats": {k: list(v) for k, v in self.formats.items()},
                "compared": "every field of every evaluation" if self.complete else
                            "verdict, rate and month only: a format 1 batch binds " + BINDS[1],
                "omissions": {"buyer": [e.id.hex() for _m, e in self.seller_only], "seller": [e.id.hex() for _m, e in self.buyer_only]},
                "conflicts": [{"id": d.id.hex(), "fields": list(d.fields or d.what)} for d in self.disputed],
                "corrections": {k: list(v) for k, v in self.corrections.items()}}


def _differs(be: Evaluation, bm: int, se: Evaluation, sm: int) -> tuple[str, ...]:
    """The fields of FIELDS two entries of one evaluation differ in, by name. `seq` is left out: each side numbers its
    own batches."""
    b, s = event_fields(be, bm, 0), event_fields(se, sm, 0)
    return tuple(name for name, x, y in zip(FIELDS, b, s) if x != y and name != "seq")


def _events(ledger: list[Stored]) -> tuple[dict[bytes, tuple[int, Evaluation]], tuple[bytes, ...]]:
    """id -> (month, evaluation) of everything that counts in one party's ledger, and the ids it entered more than
    once with no correction for it. What counts is `canonical`'s to say, here as everywhere: the first entry of an
    id in order of month, seq and id stands, a withdrawn evaluation is out, a corrected verdict is the verdict, and
    an entry a `duplicate` correction names is settled (it is not a finding any more)."""
    c = canonical(ledger)
    return ({x.e.id: (x.month, x.e) for x in c.kept},
            tuple(sorted({d.id for d in c.dropped if d.reason in (WITHIN, BATCH) and d.corrected is None})))


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
    formats = {"buyer": tuple(sorted({x.format for x in buyer_ledger})), "seller": tuple(sorted({x.format for x in seller_ledger}))}
    full = all(f in ((), (2,)) for f in formats.values())
    fixes = {name: {c.key: {"kind": c.kind, "id": c.id, "of": f"{c.month}.{c.seq}", "batch": f"{x.month}.{x.seq}", "by": c.by} for x in book for c in x.corrections}
             for name, book in (("buyer", buyer_ledger), ("seller", seller_ledger))}
    corrections = {name: tuple({**v, "both": int(k in fixes[ROLES[1 - ROLES.index(name)]])} for k, v in sorted(fixes[name].items())) for name in ROLES}
    pairs = {(e.buyer, e.seller) for _m, e in (*b.values(), *s.values())}
    if len(pairs) > 1:
        raise Bad("the two ledgers are not of the same buyer and seller")
    buyer, seller = next(iter(pairs), (0, 0))
    disputed = []
    for i in sorted(b.keys() & s.keys()):
        (bm, be), (sm, se) = b[i], s[i]
        what = tuple(w for w, differs in (("verdict", be.stands != se.stands), ("rate", be.rate != se.rate), ("month", bm != sm)) if differs)
        fields = _differs(be, bm, se, sm)
        if what or (full and fields):       # two format 2 ledgers: a difference in any field is a conflict, and it is named
            disputed.append(Dispute(i, be, se, bm, sm, what or ("content",), fields))
    out_ids = {d.id for d in disputed}
    buyer_only = tuple(b[i] for i in sorted(b.keys() - s.keys()))
    seller_only = tuple(s[i] for i in sorted(s.keys() - b.keys()))
    months = sorted({m for m, _e in (*b.values(), *s.values())})
    rows = []
    agreed = sorted(((bm, i, e) for i, (bm, e) in b.items() if i in s and i not in out_ids), key=lambda t: (t[0], t[1]))
    won: dict[str, int] = {}        # deliverable -> the month both sides first hold it accepted: billed there, once
    for bm, _i, e in agreed:
        if e.stands in ids.BILLABLE:
            won.setdefault(e.deliverable, bm)
    for m in months:
        both = [e for bm, _i, e in agreed if bm == m]
        rows.append(Row(m, len(both), sum(e.accepted for e in both), sum(e.value for e in both), fee(len(both), rate, free),
                        sum(1 for bm, _e in buyer_only if bm == m), sum(1 for sm, _e in seller_only if sm == m), sum(1 for d in disputed if d.buyer_month == m),
                        {v: sum(e.stands == v for e in both) for v in ids.VERDICTS}, sum(1 for at in won.values() if at == m)))
    return Reconciliation(buyer_only, seller_only, tuple(disputed), {"buyer": b_twice, "seller": s_twice}, tuple(rows), buyer, seller, rate, free, formats, corrections)


def export_csv(ledger: list[Stored]) -> str:
    """One row per evaluation line, in the file's order, for a spreadsheet or an auditor."""
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["month", "seq", "id", "buyer", "seller", "order", "artifact", "policy", "milestone", "accepted", "rate",
                "verdict", "deliverable_id", "evaluation_id", "invoice_line_id", "settlement_id"])
    for s in ledger:
        for e in s.evals:
            w.writerow([s.month, s.seq, e.id.hex(), e.buyer, e.seller, e.order, e.artifact, e.policy, e.milestone, int(e.accepted), e.rate,
                        e.stands, e.dlv, e.evl, e.inv, e.stl])
    return buf.getvalue()


def usd(micro: int) -> str:
    return f"{micro // MICRO}.{micro % MICRO:06d}".rstrip("0").rstrip(".") if micro % MICRO else str(micro // MICRO)


# -- corrections, the canonical ledger, and the three numbers ------------------------------------------------------------
KINDS = ("duplicate", "verdict", "withdrawn")
WITHIN, BATCH, SINGLY, WITHDRAWN = "written twice in its batch", "in another batch", "recorded singly", "withdrawn"


@dataclass(frozen=True)
class Correction:
    """What its issuer says about one evaluation in one earlier batch. The program's counters only go up, so this is
    a ledger line and not a chain write: it rides in the next batch's tree under its own leaf prefix, so the root
    GitHub signs for that batch anchors it, and the statement nets it.

        duplicate   that entry is a repeat: the evaluation is counted elsewhere (another batch, or singly)
        verdict     the verdict that stands is not the one the batch recorded: `accepted` (1 or 0), or `verdict`, one of
                    the four words (a line carries one of the two, never both)
        withdrawn   the evaluation should not have been counted at all"""
    by: int             # the GitHub owner id that issues it: the ledger's buyer or its seller
    id: str             # the evaluation, 32 bytes as hex
    month: int          # the batch it corrects
    seq: int
    kind: str
    accepted: bool | None = None
    verdict: str | None = None      # in words, instead of `accepted`: any of the four

    def __post_init__(self) -> None:
        _int(self.by, "by", least=1), _hex(self.id, 64, "id"), month_of(_int(self.month, "month")), _int(self.seq, "seq")
        if self.verdict is not None and self.verdict not in ids.VERDICTS:
            raise Bad("a correction's verdict is accepted, rejected, insufficient_evidence or disputed")
        if self.kind not in KINDS or (self.kind == "verdict") != (isinstance(self.accepted, bool) != (self.verdict is not None)) \
                or (self.accepted is not None and self.verdict is not None):
            raise Bad("a correction is of kind duplicate, verdict or withdrawn, and only a verdict correction carries accepted (1 or 0) or verdict "
                      "(one of the four words), one of the two")

    @property
    def stands(self) -> str | None:
        """The verdict a verdict correction sets, in one of the four words; None for the other kinds."""
        return self.verdict if self.verdict is not None else None if self.accepted is None else "accepted" if self.accepted else "rejected"

    def said(self) -> dict:
        """What the line carries of the verdict: {"accepted": 1 or 0}, {"verdict": word} or nothing."""
        return {"verdict": self.verdict} if self.verdict is not None else {"accepted": int(self.accepted)} if self.accepted is not None else {}

    def line(self) -> str:
        return canon({"correction": {"batch": f"{self.month}.{self.seq}", "by": self.by, "id": self.id, "kind": self.kind, **self.said()}})

    @property
    def key(self) -> bytes:
        """What the batch's tree holds of it: the sha256 of its line."""
        return _sha(self.line().encode())

    @classmethod
    def of(cls, o: dict) -> "Correction":
        c = o.get("correction") if isinstance(o, dict) else None
        if not isinstance(c, dict) or not {"batch", "by", "id", "kind"} <= set(c) <= {"accepted", "batch", "by", "id", "kind", "verdict"}:
            raise Bad("a correction has batch (<yyyymm>.<seq>), by, id and kind, and accepted or verdict when its kind is verdict")
        if "verdict" in c and not isinstance(c["verdict"], str):
            raise Bad("a correction's verdict is accepted, rejected, insufficient_evidence or disputed")
        m = re.fullmatch(r"([0-9]{6})\.(0|[1-9][0-9]{0,18})", str(c["batch"]))
        if m is None or c.get("accepted", 0) not in (0, 1) or isinstance(c.get("accepted"), bool):
            raise Bad("a correction's batch is written <yyyymm>.<seq>, and accepted is 1 or 0")
        return cls(c["by"], c["id"], int(m[1]), int(m[2]), c["kind"], c["accepted"] == 1 if "accepted" in c else None, c.get("verdict"))


@dataclass(frozen=True)
class Entry:
    """One evaluation that counts, in the batch that has it first, with the verdict that stands."""
    month: int
    seq: int
    e: Evaluation
    fixed: tuple[int, int] | None = None    # the batch whose correction changed its verdict


@dataclass(frozen=True)
class Dropped:
    """One entry that does not count, and why. `first`: where the evaluation is counted instead (a batch, or None for
    the individual mode or unknown). `corrected`: the batch that carries the correction for it, None when there is none."""
    id: bytes
    month: int
    seq: int
    reason: str
    first: tuple[int, int] | None = None
    corrected: tuple[int, int] | None = None

    def where(self) -> str:
        return {BATCH: f"already in batch {self.first[1]} of {self.first[0]}" if self.first else "counted elsewhere",
                SINGLY: "also recorded singly (the individual mode has a mark for it)"}.get(self.reason, self.reason)

    def said(self) -> str:
        """The statement's words for it."""
        fix = f"corrected in batch {self.corrected[1]} of {self.corrected[0]}" if self.corrected else "not corrected"
        return f"withdrawn, {fix}" if self.reason == WITHDRAWN else "written twice in its batch, counted once" if self.reason == WITHIN else \
            f"billed twice on chain, {fix}"


@dataclass(frozen=True)
class Canon:
    kept: tuple[Entry, ...]                                 # in order of (month, seq, id)
    dropped: tuple[Dropped, ...]
    corrections: tuple[tuple[int, int, Correction], ...]    # (the batch that carries it, the correction)


def canonical(ledger: list[Stored], individual=()) -> Canon:
    """THE ONE PLACE that decides what counts once. Identity is the 32-byte evaluation id the program bills by. Of the
    entries that share an id, the first in order of time (month, then seq: the order the chain takes batches in), then
    id, is kept; every other is dropped and listed with the reason: written twice in one batch, in another batch, or
    recorded singly as well (`individual`: the ids the individual mode has marks for; they come first, because each
    stands on chain by itself). Corrections are applied here too: a `duplicate` drops the entry it names, a
    `withdrawn` takes the evaluation out, a `verdict` replaces the verdict (the last one anchored stands)."""
    from dataclasses import replace
    single = {bytes(i) for i in individual}
    fixes = sorted(((s.month, s.seq, c) for s in ledger for c in s.corrections), key=lambda t: (t[0], t[1], t[2].key))
    by_kind: dict[str, dict] = {k: {} for k in KINDS}
    for m, q, c in fixes:
        by_kind[c.kind][(c.id, c.month, c.seq)] = ((m, q), c)
    places: dict[bytes, list[tuple[int, int]]] = {}
    for s in ledger:
        for i in {e.id for e in s.evals}:
            places.setdefault(i, []).append((s.month, s.seq))
    kept, dropped, seen = [], [], dict[bytes, tuple[int, int]]()
    for s in sorted(ledger, key=lambda s: (s.month, s.seq, s.at)):
        here, at = set(), (s.month, s.seq)
        for e in sorted(s.evals, key=lambda e: e.id):
            i, k = e.id, (e.id.hex(), *at)
            if i in here:
                dropped.append(Dropped(i, *at, WITHIN, at))
            elif k in by_kind["duplicate"]:
                other = min((p for p in places[i] if p != at), default=None)
                dropped.append(Dropped(i, *at, SINGLY if i in single and other is None else BATCH, other, by_kind["duplicate"][k][0]))
            elif i in single:
                dropped.append(Dropped(i, *at, SINGLY))
            elif i in seen:
                dropped.append(Dropped(i, *at, BATCH, seen[i]))
            elif k in by_kind["withdrawn"]:
                seen[i] = at
                dropped.append(Dropped(i, *at, WITHDRAWN, None, by_kind["withdrawn"][k][0]))
            else:
                seen[i] = at
                where, c = by_kind["verdict"].get(k, (None, None))
                # a correction in words gives the entry its verdict in words; one that says 1 or 0 leaves an old line an old line
                fixed = None if c is None else replace(e, accepted=c.stands == "accepted", stl=e.stl if c.stands == "accepted" else "",
                                                       verdict=c.stands if c.verdict is not None or e.verdict else "")
                kept.append(Entry(*at, fixed or e, where))
            here.add(i)
    return Canon(tuple(sorted(kept, key=lambda x: (x.month, x.seq, x.e.id))), tuple(sorted(dropped, key=lambda d: (d.month, d.seq, d.id))), tuple(fixes))


@dataclass(frozen=True)
class Numbers:
    """One month, after `canonical`. The first three are the statement's three numbers and are never added together."""
    evaluations: int            # the Meter's billable unit: every evaluation that counts, accepted or rejected
    accepted_outcomes: int      # deliverables (order + milestone) accepted for the first time this month: what a per-outcome price multiplies
    rejected: int               # evaluations whose verdict is rejected
    accepted: int               # evaluations whose verdict is accepted: ten pull requests for one deliverable are ten here
    value: int                  # the sum of the accepted evaluations' rates, as the chain's `value` adds them
    outcome_value: int          # the sum over the accepted outcomes of the rate of the evaluation that first accepted each
    insufficient_evidence: int = 0      # evaluations that could not tell: not accepted, and not the supplier's failure
    disputed: int = 0           # evaluations whose verdict somebody contested and nobody has resolved

    def three(self) -> dict:
        return {"accepted_outcomes": self.accepted_outcomes, "evaluations": self.evaluations, "rejected": self.rejected}

    def four(self) -> dict:
        """The month's evaluations by verdict. They add up to `evaluations`. On chain the last three are one number:
        the batch's count less its accepted."""
        return {"accepted": self.accepted, "rejected": self.rejected, "insufficient_evidence": self.insufficient_evidence, "disputed": self.disputed}

    def extra(self) -> dict:
        """The two verdicts 0.3.16 did not have, when the month holds any: what a close record and a statement add."""
        return {k: v for k, v in (("disputed", self.disputed), ("insufficient_evidence", self.insufficient_evidence)) if v}


def outcomes(c: Canon) -> dict[str, Entry]:
    """deliverable -> the entry that first accepted it. One per deliverable, however many pull requests or artifacts
    carried it and however many months it was evaluated in."""
    first: dict[str, Entry] = {}
    for x in c.kept:
        if x.e.accepted:
            first.setdefault(x.e.deliverable, x)
    return first


def numbers(c: Canon, month: int) -> Numbers:
    mine = [x.e for x in c.kept if x.month == month]
    won = [x.e for x in outcomes(c).values() if x.month == month]
    return Numbers(len(mine), len(won), sum(e.stands == "rejected" for e in mine), sum(e.accepted for e in mine), sum(e.value for e in mine), sum(e.rate for e in won),
                   sum(e.stands == "insufficient_evidence" for e in mine), sum(e.stands == "disputed" for e in mine))


# -- one deliverable is billed once ------------------------------------------------------------------------------------------
# The rules, as docs/METER.md prints them (tests hold the two together). `case`: what happened. `is`: what the ledger
# makes of it. `billed`: what it adds to the accepted outcomes, the number a per-outcome price multiplies.
RULES = (
    ("a retry", "the same deliverable and artifact, judged again", "a new evaluation", "nothing: the deliverable is billed once"),
    ("an alternate branch", "the same deliverable, another artifact", "a new evaluation", "nothing: the first accepted one stands"),
    ("a reopened ticket, inside the warranty", "the same deliverable, contested after it was accepted",
     "a correction of the accepted evaluation's verdict", "nothing new: the correction takes the outcome back, or leaves it"),
    ("a reopened ticket, after the warranty", "the same work, asked for again", "a new deliverable only when the terms say so",
     "one outcome when the terms say so, else nothing"),
    ("ten pull requests for one milestone", "one deliverable, ten artifacts", "ten evaluations", "one outcome, when the first is accepted"),
)
OUTCOME, RETRY, ALTERNATE, FIRST = "outcome", "retry", "alternate", "evaluation"
CORRECTION, NEW_DELIVERABLE, CLOSED = "correction", "new deliverable", "closed"


@dataclass(frozen=True)
class Billed:
    """One evaluation that counts, and what it is to the invoice. `role`: outcome (the first accepted evaluation of its
    deliverable: the one line that is billed), retry (its deliverable and artifact were judged before), alternate (its
    deliverable was judged before on another artifact), or evaluation (the first look at a deliverable, not accepted)."""
    entry: Entry
    role: str

    @property
    def billed(self) -> bool:
        return self.role == OUTCOME


def billing(c: Canon) -> tuple[Billed, ...]:
    """THE ONE PLACE that says which evaluation is the billed outcome of its deliverable: the first, in order of month,
    seq and id, whose verdict is accepted after every correction. One per deliverable under one order, whatever number
    of artifacts, branches, pull requests, retries or months carried the work. An accepted evaluation after it is an
    evaluation and no more. A verdict that is rejected, insufficient evidence or disputed is never billed as an outcome."""
    first, seen, out = outcomes(c), dict[str, set[str]](), []
    for x in c.kept:
        e, before = x.e, seen.setdefault(x.e.deliverable, set())
        role = OUTCOME if first.get(e.deliverable) is x else RETRY if e.artifact in before else ALTERNATE if before else FIRST
        if e.stands in ids.BILLABLE and role == FIRST:        # accepted, the first of its deliverable, and not the outcome: cannot be
            raise Bad(f"evaluation {e.id.hex()[:16]}... is accepted and is not its deliverable's outcome")
        before.add(e.artifact)
        out.append(Billed(x, role))
    return tuple(out)


def billed_once(evaluations) -> list[int]:
    """Which of these evaluations are billed as outcomes, as their places in the list: the first accepted one of each
    deliverable, and no other. `evaluations`: (deliverable id, verdict) in the order they count. The same rule as
    `billing`, for a caller that has ids and verdicts and no ledger; an id that is not a deliverable's, or a word
    that is not a verdict, is refused."""
    seen, out = set[str](), []
    for n, (dlv, verdict) in enumerate(evaluations):
        try:
            ids.expect("deliverable", dlv)
        except ValueError as why:
            raise Bad(str(why)) from None
        if verdict not in ids.VERDICTS:
            raise Bad(f"not a verdict: {verdict!r}")
        if verdict in ids.BILLABLE and dlv not in seen:
            seen.add(dlv)
            out.append(n)
    return out


def reopened(accepted_at: int, reopened_at: int, warranty_s: int, new_after: bool = False) -> str:
    """What a ticket reopened after its deliverable was accepted is. Inside the warranty window (`warranty_s` seconds
    from the acceptance, the window the terms set): a correction of the accepted evaluation's verdict, never a new
    line. After it: a new deliverable when the terms say so (`new_after`), else closed: nothing is billed and nothing
    is taken back. Times are seconds; a reopening before the acceptance is refused."""
    if min(accepted_at, reopened_at, warranty_s) < 0 or reopened_at < accepted_at:
        raise Bad("a ticket is reopened after its deliverable was accepted, and a warranty is a number of seconds, 0 or more")
    return CORRECTION if reopened_at - accepted_at <= warranty_s else NEW_DELIVERABLE if new_after else CLOSED


def reopened_key(key: str | int, n: int) -> str:
    """The key of the new deliverable a reopening after the warranty makes, when the terms allow one: the first
    deliverable's key and which reopening this is, from 1. `ids.deliverable(scope, reopened_key(key, n))` is its id."""
    if isinstance(n, bool) or not isinstance(n, int) or n < 1:
        raise Bad("reopenings are numbered from 1")
    return f"{key}/reopened/{n}"


def read_ids(text: str) -> list[bytes]:
    """The ids the individual mode recorded, from a file: one 64-character hex id a line (`knosm:eval:...` audiences
    and ledger lines are read too)."""
    out = []
    for raw in text.splitlines():
        raw = raw.strip()
        if raw:
            out.append(bytes.fromhex(_hex(raw, 64, "an id")) if len(raw) == 64 else parse(raw).id)
    return out


def individual_onchain(net, ledger: list[Stored]) -> list[bytes]:
    """The evaluations of this ledger that the individual mode has a mark for on chain now, one account read each.
    A mark may be closed from two hours into the month after its own, so a month that is over is checked from a file
    of ids kept while the marks stood."""
    from .settle.v2 import meter
    return [e.id for e in {e.id: e for s in ledger for e in s.evals}.values() if meter.read_mark(net.account(meter.mark_pda(e.buyer, e.id))) is not None]


# -- the period close ----------------------------------------------------------------------------------------------------
CLOSE_TYPE, MONTH_TYPE = "knos.meter-close", "knos.meter-month"
GITHUB_ISSUER = "https://token.actions.githubusercontent.com"
GITHUB_JWKS = GITHUB_ISSUER + "/.well-known/jwks"
ROLES = ("buyer", "seller")


def side(ledger: list[Stored], month: int, individual=()) -> dict:
    """What one party's ledger says of a month: the final running hash of its batches (what its Ledger account on
    chain must hold), how many evaluations they anchored, and the three numbers after `canonical`."""
    t, c = totals(ledger, month), canonical(ledger, individual)
    n = numbers(c, month)
    return {**n.three(), **n.extra(), "anchored": t.count, "batches": t.next_seq, "chain": t.chain.hex(),
            "corrections": sum(1 for _m, _q, x in c.corrections if x.month == month)}


def close(buyer_ledger: list[Stored], seller_ledger: list[Stored], month: int | str, individual=()) -> dict:
    """The close record of one month for one buyer and one seller: both ledgers' final hashes and three numbers, every
    correction and who issued it, and `state`: `agreed` when the two ledgers hold the same evaluations with the same
    verdicts and rates after `canonical`, else `disputed` with every line in dispute and why. It is made only of what
    the two files say, so both parties compute the same bytes (`close_bytes`) and each has its own GitHub run sign
    their sha256. The chain holds the batches, not the close: knos_meter has no instruction for one."""
    month = month_of(month)
    for name, led in zip(ROLES, (buyer_ledger, seller_ledger)):
        bad = _structure(led)
        if bad:
            raise Bad(f"the {name}'s ledger does not hold, so the month cannot be closed: {bad[0]}")
    pairs = {(s.declared["buyer"], s.declared["seller"]) for s in (*buyer_ledger, *seller_ledger)}
    if len(pairs) != 1 or not any(s.month == month for s in (*buyer_ledger, *seller_ledger)):
        raise Bad("the two ledgers are not of the same buyer and seller" if len(pairs) > 1 else f"neither ledger has a batch of {month}")
    (buyer, seller), = pairs
    cb, cs = canonical(buyer_ledger, individual), canonical(seller_ledger, individual)
    b_all, s_all = {x.e.id: x for x in cb.kept}, {x.e.id: x for x in cs.kept}
    # the two newer verdicts are written out; accepted and rejected stay 1 and 0, so a month without them closes to the bytes it always did
    show = lambda x: {"accepted": int(x.e.accepted), "batch": f"{x.month}.{x.seq}", "rate": x.e.rate,  # noqa: E731
                      **({"verdict": x.e.stands} if x.e.stands in ("insufficient_evidence", "disputed") else {})} if x else None
    lines = []
    for i in sorted(i for i in b_all.keys() | s_all.keys() if month in {x.month for x in (b_all.get(i), s_all.get(i)) if x}):
        b, s = b_all.get(i), s_all.get(i)
        why = "missing from the seller's ledger" if s is None else "missing from the buyer's ledger" if b is None else \
            "month differs" if b.month != s.month else "verdict differs" if b.e.stands != s.e.stands else "rate differs" if b.e.rate != s.e.rate else ""
        if why:
            lines.append({"buyer": show(b), "id": i.hex(), "seller": show(s), "why": why})
    for name, c in zip(ROLES, (cb, cs)):
        lines += [{"buyer": None, "id": d.id.hex(), "seller": None, "why": f"duplicate in the {name}'s ledger: batch {d.seq} of {d.month}, {d.where()}"}
                  for d in c.dropped if d.month == month and d.corrected is None and d.reason in (BATCH, SINGLY)]
    fixes = [{"batch": f"{m}.{q}", "by": x.by, "id": x.id, "in": name, "kind": x.kind, "of": f"{x.month}.{x.seq}", **x.said()}
             for name, c in zip(ROLES, (cb, cs)) for m, q, x in c.corrections if x.month == month]
    return {"buyer": buyer, "buyer_ledger": side(buyer_ledger, month, individual), "corrections": fixes, "disputed": sorted(lines, key=lambda d: (d["id"], d["why"])),
            "month": month, "seller": seller, "seller_ledger": side(seller_ledger, month, individual), "state": "disputed" if lines else "agreed",
            "type": CLOSE_TYPE, "version": 1}


def close_bytes(record: dict) -> bytes:
    """The close record as the bytes both parties sign: canonical JSON and one newline."""
    return (canon(record) + "\n").encode()


def read_close(raw: bytes | str) -> dict:
    """A close record from its file. One that is not in the form `close` writes is refused: its sha256 would not be
    the one anybody signed."""
    raw = raw.encode() if isinstance(raw, str) else raw
    try:
        r = json.loads(raw)
        assert r["type"] == CLOSE_TYPE and r["version"] == 1 and r["state"] in ("agreed", "disputed") and close_bytes(r) == raw
        assert (r["state"] == "disputed") == bool(r["disputed"]) and all(set(r[k]) == set(side([], 0)) for k in ("buyer_ledger", "seller_ledger"))
        _int(r["buyer"], "buyer", least=1), _int(r["seller"], "seller", least=1), month_of(r["month"])
    except Exception:  # noqa: BLE001 - missing, not JSON, or not a close record: one sentence either way
        raise Bad("this is not a close record as `knos meter close` writes one (canonical JSON, version 1)") from None
    return r


def close_audience(record: dict) -> str:
    """The audience of the token by which one party's GitHub run signs a close record:
    `knosm:close:<buyer>:<seller>:<yyyymm>:<sha256 of the record's bytes>`. knos_oidc can verify any GitHub token, but
    knos_meter reads no such audience, so the token is kept beside the ledger and checked off chain (`check_close_token`)."""
    return f"knosm:close:{record['buyer']}:{record['seller']}:{record['month']:06d}:{hashlib.sha256(close_bytes(record)).hexdigest()}"


def _jwt_part(token: str, n: int) -> dict:
    from . import bundle
    try:
        got = json.loads(bundle._unb64(token.strip().split(".")[n]))
    except Exception:  # noqa: BLE001
        got = None
    if not isinstance(got, dict):
        raise Bad("the token is not a signed token (three parts, the first two JSON)")
    return got


def keys_used(jwks: dict, tokens) -> dict:
    """The JWKS document cut down to the keys these tokens name, in canonical order: what an archive keeps."""
    kids = {_jwt_part(t, 0).get("kid") for t in tokens}
    return {"keys": sorted((k for k in jwks.get("keys", []) if isinstance(k, dict) and k.get("kid") in kids), key=canon)}


def check_close_token(record: dict, token: str, jwks: dict, role: str) -> dict:
    """The claims of `token` when it is this party's signature of this close record, checked with no network: an RS256
    signature of one of the keys in `jwks` (the verifier the evidence bundle uses, knos.bundle.rs256), issued by GitHub
    Actions, for the record's audience, in a repository whose owner is the record's buyer (`role` buyer) or seller.
    Raises Bad, in words, otherwise. The token's expiry is not held against it: a close is read long after GitHub's
    few minutes, and what is asked is whether GitHub signed these bytes for this owner, at the time `iat` names.
    Whether `jwks` really are GitHub's keys is the reader's to check once, against GITHUB_JWKS or the knos_oidc key
    accounts; an archive carries the keys it was signed with so that the check is possible later."""
    from . import bundle
    token, head, claims = token.strip(), _jwt_part(token, 0), _jwt_part(token, 1)
    moduli = [int.from_bytes(bundle._unb64(k["n"]), "big") for k in jwks.get("keys", [])
              if isinstance(k, dict) and k.get("kty") == "RSA" and k.get("e") == "AQAB" and k.get("kid") == head.get("kid") and isinstance(k.get("n"), str)]
    if not any(bundle.rs256(token, n) for n in moduli):
        raise Bad(f"the {role}'s token does not carry the signature of any of the given keys (key id {head.get('kid')!r}): the token or the keys were changed")
    if claims.get("iss") != GITHUB_ISSUER:
        raise Bad(f"the {role}'s token was not issued by GitHub Actions")
    if claims.get("aud") != close_audience(record):
        raise Bad(f"the {role}'s token was signed for something else than this close record (its audience is not {close_audience(record)})")
    if str(claims.get("repository_owner_id")) != str(record[role]):
        raise Bad(f"the {role}'s token is from a repository of GitHub id {claims.get('repository_owner_id')}, and the record's {role} is {record[role]}")
    return claims


class Disputed(Bad):
    """A month in dispute was asked for as if it were settled."""


def statement(ledger: list[Stored], month: int | str, record: dict | None = None, individual=(), rate: int = RATE, free: int = FREE_PER_MONTH,
              disputed: bool = False) -> str:
    """One month of one ledger as text, for the invoice and for whoever checks it later. Three numbers that are never
    added together (evaluations, accepted outcomes, rejected evaluations), the Meter fee on the evaluations, and the
    value a per-outcome price multiplies. The lines down to the first `sha256` are made only of what both parties
    hold once a month is agreed, so the buyer and the seller compare that hash; the lines after it are this ledger's
    own record: what it anchored, every repeat, every correction.

    `record` is the month's close record. Without one the state is `open`. A month whose close is `disputed` is
    refused (Disputed) unless `disputed` is set, and then every line in dispute is listed and the text says it is
    not an invoice."""
    month = month_of(month)
    bad = _structure(ledger)
    if bad or not any(s.month == month for s in ledger):
        raise Bad(f"the ledger does not hold: {bad[0]}" if bad else f"the ledger has no batch of {month}")
    c, mine = canonical(ledger, individual), side(ledger, month, individual)
    n = numbers(c, month)
    state = "open"
    if record is not None:
        if record["month"] != month or mine not in (record["buyer_ledger"], record["seller_ledger"]):
            raise Bad("the close record is not of this ledger and month (its hashes and numbers are another's): the ledger changed after the close, or this is "
                      "another month. Run `knos meter close` again")
        state = record["state"]
        if state == "disputed" and not disputed:
            raise Disputed(f"{month} is in dispute ({len(record['disputed'])} line(s)), so there are no totals to invoice. Settle the lines `knos meter close` "
                           f"names, anchor the corrections and close again; or pass --disputed to see the numbers with every disputed line marked")
    d = ledger[0].declared
    more = n.extra()        # a month that holds either of the two newer verdicts is stated as version 2, with a line for each
    body = (f"knos meter statement,{2 if more else 1}\nbuyer,{d['buyer']}\nseller,{d['seller']}\nmonth,{month}\nstate,{state}\n"
            + (f"close,{hashlib.sha256(close_bytes(record)).hexdigest()}\n" if record is not None else "")
            + ("note,DISPUTED: this is not an invoice; the lines marked disputed below are not settled\n" if state == "disputed" else "")
            + f"evaluations,{n.evaluations}\naccepted_outcomes,{n.accepted_outcomes}\nrejected_evaluations,{n.rejected}\n"
            + (f"insufficient_evidence_evaluations,{n.insufficient_evidence}\ndisputed_evaluations,{n.disputed}\n" if more else "")
            +            f"accepted_evaluations,{n.accepted}\nmeter_rate,{rate}\nmeter_free,{free}\nmeter_fee,{fee(n.evaluations, rate, free)}\n"
            f"value_of_accepted_evaluations,{n.value}\nvalue_of_accepted_outcomes,{n.outcome_value}\n")
    body += "".join(f"disputed,{x['id']},{x['why']}\n" for x in (record["disputed"] if record is not None else []))
    out = body + f"sha256,{hashlib.sha256(body.encode()).hexdigest()}\n"
    out += f"anchored,{mine['anchored']},in {mine['batches']} batch(es),running hash {mine['chain']}\n"
    out += f"anchored_and_not_counted,{mine['anchored'] - n.evaluations}\n"
    out += "".join(f"repeat,{r.id.hex()},batch {r.seq} of {r.month},{r.said()}\n" for r in c.dropped if r.month == month)
    out += "".join(f"correction,{x.kind},{x.id},of batch {x.seq} of {x.month},in batch {q} of {m},by {x.by}"
                   + (f",verdict {x.verdict}" if x.verdict is not None else f",accepted {int(x.accepted)}" if x.accepted is not None else "") + "\n"
                   for m, q, x in c.corrections if x.month == month)
    return out


STATEMENT_TYPE, STATEMENT_VERSION = "knos.meter-statement", 1


def statement_json(ledger: list[Stored], month: int | str, record: dict | None = None, individual=(), rate: int = RATE, free: int = FREE_PER_MONTH,
                   disputed: bool = False) -> dict:
    """The same month as `statement`, as one JSON object: the four verdicts counted, and one line per evaluation that
    counts with its four ids, its verdict, and whether it is the billed outcome of its deliverable (`billing`).
    `text_sha256` is the hash the text statement prints, so the two are known to be of one month of one ledger.
    Refused exactly where `statement` is refused."""
    text = statement(ledger, month, record, individual, rate, free, disputed)
    month = month_of(month)
    c = canonical(ledger, individual)
    n, d = numbers(c, month), ledger[0].declared
    lines: list[dict] = [{"id": b.entry.e.id.hex(), "ids": b.entry.e.ids(), "verdict": b.entry.e.stands, "role": b.role, "billed": b.billed,
              "batch": f"{b.entry.month}.{b.entry.seq}", "artifact": b.entry.e.artifact, "rate": b.entry.e.rate,
              "corrected_in": f"{b.entry.fixed[0]}.{b.entry.fixed[1]}" if b.entry.fixed else None}
             for b in billing(c) if b.entry.month == month]
    head = dict(line.split(",", 1) for line in text.split("sha256,", 1)[0].splitlines())
    return {"type": STATEMENT_TYPE, "version": STATEMENT_VERSION, "buyer": d["buyer"], "seller": d["seller"], "month": month, "state": head["state"],
            "invoice": head["state"] != "disputed", "evaluations": n.evaluations, "verdicts": n.four(), "accepted_outcomes": n.accepted_outcomes,
            "meter": {"rate": rate, "free": free, "fee": fee(n.evaluations, rate, free)},
            "value_of_accepted_evaluations": n.value, "value_of_accepted_outcomes": n.outcome_value,
            "billed_deliverables": sorted(x["ids"]["deliverable"] for x in lines if x["billed"]), "lines": lines,
            "disputed": [x["id"] for x in (record["disputed"] if record is not None else [])],
            "repeats": [{"id": r.id.hex(), "batch": f"{r.month}.{r.seq}", "said": r.said()} for r in c.dropped if r.month == month],
            "corrections": [{"batch": f"{m}.{q}", "by": x.by, "id": x.id, "kind": x.kind, "of": f"{x.month}.{x.seq}", "verdict": x.stands}
                            for m, q, x in c.corrections if x.month == month],
            "text_sha256": text.split("\nsha256,", 1)[1].split("\n", 1)[0]}


# -- a month in one archive ----------------------------------------------------------------------------------------------
def _tar(files: dict[str, bytes]) -> bytes:
    """One form only (names in order, times zero, one mode, no owner), as knos.bundle.make writes its own."""
    import tarfile
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w", format=tarfile.USTAR_FORMAT) as tar:
        for name, data in sorted(files.items()):
            info = tarfile.TarInfo(name)
            info.size, info.mtime, info.mode, info.uid, info.gid, info.uname, info.gname = len(data), 0, 0o644, 0, 0, "", ""
            tar.addfile(info, io.BytesIO(data))
    return out.getvalue()


def _corrections_text(ledger: list[Stored], month: int) -> str:
    return "".join(canon({"anchored_in": f"{m}.{q}", **json.loads(x.line())}) + "\n" for m, q, x in canonical(ledger).corrections if x.month == month)


def month_bundle(record: dict, ledgers: dict[str, str], tokens: dict[str, str], jwks: dict) -> bytes:
    """One archive of a closed month, the same bytes whoever builds it from the same files: the close record, the
    ledger file of each party given (`ledgers`: buyer and/or seller -> the file's text), the month's corrections drawn
    from them, each party's signed token as far as there is one, and the GitHub keys those tokens name. Everything in
    it is checked first (`verify_month`), so no archive is written that would not verify."""
    if not ledgers or not set(ledgers) <= set(ROLES) or not set(tokens) <= set(ROLES):
        raise Bad("an archive holds the buyer's ledger, the seller's, or both")
    files = {"close.json": close_bytes(record), "jwks.json": (canon(keys_used(jwks, tokens.values())) + "\n").encode()}
    for role, text in ledgers.items():
        files[f"ledger.{role}.jsonl"] = text.encode()
        files[f"corrections.{role}.jsonl"] = _corrections_text(load(text), record["month"]).encode()
    files.update({f"{role}.jwt": tokens[role].strip().encode() + b"\n" for role in tokens})
    manifest = {"type": MONTH_TYPE, "version": 1, "buyer": record["buyer"], "seller": record["seller"], "month": record["month"],
                "files": {name: hashlib.sha256(data).hexdigest() for name, data in sorted(files.items())}}
    blob = _tar({**files, "MANIFEST.json": (canon(manifest) + "\n").encode()})
    verify_month(blob)
    return blob


def verify_month(blob: bytes) -> tuple[dict, list[str]]:
    """(the close record, what was checked, one line each) for a month's archive that holds together, with no network.
    Raises Bad with the first thing that does not: a file that is not the one the manifest lists, an archive that was
    repacked, a ledger that does not recompute, a close record that is not the one these ledgers give, a token that
    is not GitHub's signature of this record by that party."""
    import tarfile
    try:
        with tarfile.open(fileobj=io.BytesIO(blob), mode="r:") as tar:
            members = tar.getmembers()
            if any(not m.isfile() for m in members) or len({m.name for m in members}) != len(members):
                raise Bad("the archive holds something that is not a plain file, or a name twice")
            files = {m.name: (tar.extractfile(m) or io.BytesIO()).read() for m in members}       # every member is a plain file (checked above), so each has bytes
    except Bad:
        raise
    except Exception as e:  # noqa: BLE001 - a damaged tar fails in many ways; all of them are one answer
        raise Bad(f"this is not a month's archive (not a tar: {e})") from None
    try:
        manifest = json.loads(files["MANIFEST.json"])
        listed = manifest["files"]
        assert manifest["type"] == MONTH_TYPE and manifest["version"] == 1 and isinstance(listed, dict)
    except Exception:  # noqa: BLE001
        raise Bad("the archive has no MANIFEST.json of a Knos meter month, version 1") from None
    if set(listed) != set(files) - {"MANIFEST.json"} or not {"close.json", "jwks.json"} <= set(listed):
        raise Bad("the archive's files are not the ones its manifest lists")
    for name in sorted(listed):
        if hashlib.sha256(files[name]).hexdigest() != listed[name]:
            raise Bad(f"{name} is not the file the manifest lists (its sha256 differs): the archive was changed after it was made")
    if blob != _tar(files):
        raise Bad("the archive is not in the one form `knos meter export --bundle` writes (order of files, times, modes): it was repacked or changed")
    done = [f"every file is the one the manifest lists ({len(listed)} files)"]
    record = read_close(files["close.json"])
    month = record["month"]
    if (manifest.get("buyer"), manifest.get("seller"), manifest.get("month")) != (record["buyer"], record["seller"], month):
        raise Bad("the manifest names another buyer, seller or month than the close record")
    books = {}
    for role in ROLES:
        if f"ledger.{role}.jsonl" not in files:
            continue
        try:
            text = files[f"ledger.{role}.jsonl"].decode("utf-8")
            books[role] = load(text)
        except (Bad, UnicodeDecodeError) as why:
            raise Bad(f"the {role}'s ledger in the archive cannot be read: {why}") from None
        bad = _structure(books[role])
        if bad:
            raise Bad(f"the {role}'s ledger in the archive does not hold: {bad[0]}")
        if side(books[role], month) != record[f"{role}_ledger"]:
            raise Bad(f"the close record's hash and numbers for the {role} are not what the {role}'s ledger in the archive gives")
        if files.get(f"corrections.{role}.jsonl") != _corrections_text(books[role], month).encode():
            raise Bad(f"corrections.{role}.jsonl is not the list of corrections the {role}'s ledger holds for {month}")
        done.append(f"the {role}'s ledger recomputes: every root and total, its running hash {record[f'{role}_ledger']['chain'][:16]}... and the close record's three numbers for it")
    if not books:
        raise Bad("the archive holds no ledger")
    if len(books) == 2:
        if close(books["buyer"], books["seller"], month) != record:
            raise Bad("the close record is not the one the two ledgers in the archive give")
        done.append(f"the close record is the one the two ledgers give: {record['state']}" + (f", {len(record['disputed'])} line(s) in dispute" if record["disputed"] else ""))
    else:
        done.append(f"only the {next(iter(books))}'s ledger is in the archive: the other side's numbers and the state ({record['state']}) are the close record's word")
    try:
        jwks = json.loads(files["jwks.json"])
        assert isinstance(jwks, dict)
    except Exception:  # noqa: BLE001
        raise Bad("jwks.json in the archive is not a set of keys") from None
    for role in ROLES:
        if f"{role}.jwt" in files:
            claims = check_close_token(record, files[f"{role}.jwt"].decode("ascii", "replace"), jwks, role)
            done.append(f"the {role} signed this close record: GitHub's token for run {claims.get('run_id')} of {claims.get('repository')} (owner id {record[role]}), "
                        f"issued at {claims.get('iat')}, carries the signature of the included key")
        else:
            done.append(f"the {role} has NOT signed: there is no {role}.jwt in the archive")
    done.append("the chain was not asked: compare each running hash with its Ledger account (`knos meter verify <ledger> --rpc <url>`), and the included keys with GitHub's "
                f"({GITHUB_JWKS}) if you have not before")
    return record, done


# -- the chain's two accounts, and the run that asks GitHub to sign a batch ---------------------------------------------
def onchain(net, buyer: int, seller: int, month: int) -> tuple[Totals, Totals]:
    """(the buyer's count, the seller's claim) for one month as the chain has them: the Ledger accounts RecordBatch
    and ClaimBatch write, read through `net.account(address)` (a knos.chain.Ledger). One with no batch yet is zeros."""
    from .settle.v2 import meter
    both = (meter.book(net, buyer, seller, month, claim) for claim in (False, True))
    count, claimed = (Totals(b.next_seq, b.evaluations, b.accepted, b.value, b.chain) for b in both)
    return count, claimed


def verify_onchain(ledger: list[Stored], net, claim: bool = False, individual=None) -> tuple[list[str], dict[int, tuple[Totals, Totals]]]:
    """`verify`, with every month of the file held to the chain's account for it: the buyer's count, or with `claim`
    the seller's. Returns (what is wrong, {month: (the buyer's count, the seller's claim)} as read)."""
    bad, seen = verify(ledger, individual=individual), dict[int, tuple[Totals, Totals]]()
    if bad or not ledger:
        return bad, seen
    buyer, seller = ledger[0].declared["buyer"], ledger[0].declared["seller"]
    for m in sorted({s.month for s in ledger}):
        seen[m] = onchain(net, buyer, seller, m)
        bad += [f"month {m}: {line}" for line in verify(ledger, seen[m][claim], m, individual)]
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
    said = (f"batch {b.seq} of {b.month} in {path} of {run.repo} is {b.count} evaluation(s), {b.accepted} accepted, value {b.value}, root `{b.root.hex()[:12]}` in commitment format {b.format} (it binds {b.binds}): "
            + (f"the seller's own count (GitHub id {seller}) of its work for buyer {buyer}" if claim else f"the buyer's count (GitHub id {buyer}) for seller {seller}"))
    return sign(run, "eval", batch_audience(b, claim), said, "", 0, None, no)


# -- the commands -----------------------------------------------------------------------------------------------------
def register(app, out, Stop, help_rows: list | None = None, panel: str | None = None) -> None:
    """`knos meter ...`. cli.py calls this once; `help_rows` is its list of one-line summaries, which gets the group's."""
    import sys

    import importlib
    typer = importlib.import_module("typer")       # the command line's package, named here and not imported: the relay reaches this module on an install without it

    meter = typer.Typer(add_completion=False, help="The meter's off-chain ledger: build a batch, check a ledger against the chain, prove one evaluation, "
                                                   "set the buyer's ledger against the seller's, correct an entry, close a month and state it.")
    app.add_typer(meter, name="meter")
    if help_rows is not None:
        help_rows.append(("meter", panel, "The meter's ledger: batch, verify, prove, reconcile, correct, close, statement, export."))

    def read(path: Path) -> list[Stored]:
        try:
            return load(Path(path))
        except OSError:
            raise Stop(f"Cannot read {path}.") from None
        except Bad as why:
            raise Stop(f"{path}: {why}.") from None

    def text_of(path: Path, what: str) -> str:
        try:
            return Path(path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            raise Stop(f"Cannot read {what} {path}.") from None

    def singles(path: Path | None) -> list[bytes]:
        try:
            return read_ids(text_of(path, "the list of individually recorded ids")) if path else []
        except Bad as why:
            raise Stop(f"{path}: {why}.") from None

    def pending_of(ledger: Path) -> Path:
        return ledger.with_name(ledger.name + ".corrections")

    def beside(close_file: Path, name: str) -> Path:
        return close_file.with_name(f"{close_file.name}.{name}")

    @meter.command("batch")
    def batch_(events: Path = typer.Argument(..., help="evaluations, one a line: ledger lines or knosm:eval:... audiences"),
               ledger: Path = typer.Option(..., "--ledger", help="the ledger file the batch is added to (made if it is not there)"),
               month: str = typer.Option(..., "--month", help="the month the batch is counted in, YYYY-MM"),
               claim: bool = typer.Option(False, "--claim", help="the seller's own count (ClaimBatch) instead of the buyer's (RecordBatch)"),
               corrections: Path = typer.Option(None, "--corrections", help="correction lines to carry in this batch (default: <ledger>.corrections, where `knos meter correct` writes)"),
               events_log: Path = typer.Option(None, "--events", help="also take the batch into this log of events (`knos events`); default: the file KNOS_EVENTS names, else none"),
               format_: int = typer.Option(FORMAT, "--format", help="the commitment format of the root: 2 hashes every field of every evaluation; 1 hashes the ids only")) -> None:
        """Add one batch to a ledger and print what its token must say: the root, the totals and the audience. Corrections waiting beside the ledger ride in it."""
        try:
            had = read(ledger) if ledger.exists() else []
            known = {e.id for s in had for e in s.evals}
            given = [parse(x) for x in events.read_text(encoding="utf-8").splitlines() if x.strip()]
            new = [e for e in given if e.id not in known]
            waiting = corrections or (pending_of(ledger) if pending_of(ledger).exists() else None)
            carried = {c.key for s in had for c in s.corrections}
            fixes = [c for c in (Correction.of(json.loads(x)) for x in (text_of(waiting, "the corrections") if waiting else "").splitlines() if x.strip()) if c.key not in carried]
            if not new:
                raise Stop(f"All {len(given)} evaluation(s) in {events} are already in {ledger}: there is nothing to add."
                           + (f" {len(fixes)} correction(s) are waiting: a batch needs at least one new evaluation to carry them, because the program takes no batch of none." if fixes else ""))
            m = month_of(month)
            b = batch(new, next_seq(had, m), m, fixes, format_)
            wrong = _structure(load(dump([x.batch() for x in had] + [b]))) if fixes else []
            if wrong:
                raise Stop(f"A correction does not fit {ledger}: {wrong[0]}.", f"Fix or remove its line in {waiting}.")
            if had and (b.buyer, b.seller) != (had[0].declared["buyer"], had[0].declared["seller"]):
                raise Stop(f"{ledger} is the ledger of buyer {had[0].declared['buyer']} and seller {had[0].declared['seller']}; these evaluations are of another pair.",
                           "Keep one ledger file per buyer and seller.")
        except OSError:
            raise Stop(f"Cannot read {events}.") from None
        except (Bad, ValueError) as why:
            raise Stop(f"{events}: {why}." if isinstance(why, Bad) else f"A line of {waiting} is not JSON.") from None
        with ledger.open("a", encoding="utf-8", newline="\n") as f:
            f.write(dump([b]))
        from . import events as _events
        _events.keep(_events.where(events_log), lambda: _events.from_ledger(dump([b])))     # best effort: the ledger is written whatever the log says
        if b.corrections:
            out.print(f"Carries {len(b.corrections)} correction(s): they are in the root, and change none of the batch's numbers.", markup=False)
        if len(new) != len(given):
            out.print(f"Left out {len(given) - len(new)} evaluation(s) that {ledger} already has.", markup=False)
        out.print(f"Batch {b.seq} of {b.month}: {b.count} evaluation(s), {b.accepted} accepted, value {b.value}.", markup=False)
        out.print(f"root      {b.root.hex()}", markup=False)
        out.print(f"format    {b.format}: the root binds {b.binds}.", markup=False)
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

    def said(book: list[Stored]) -> None:
        """What every format 1 batch of a ledger binds, in one line; nothing for a ledger that is format 2 throughout."""
        old = [c for c in commitments(book) if c["format"] == 1]
        if old:
            again = sum(1 for c in old if "superseded_by" in c)
            out.print(f"{len(old)} batch(es) are in commitment format 1 ({', '.join(str(c['month']) + '.' + str(c['seq']) for c in old[:8])}{', ...' if len(old) > 8 else ''}): "
                      f"such a root binds {BINDS[1]}." + (f" {again} of them are re-committed in format 2 by a later batch of this file." if again else "")
                      + (f" `knos meter migrate` re-commits {'the others' if again else 'them'} in format 2." if again < len(old) else ""), markup=False)

    @meter.command("migrate")
    def migrate_(ledger: Path = typer.Argument(..., help="your ledger file"),
                 month: str = typer.Option(None, "--month", help="only this month, YYYY-MM (default: every format 1 batch of the file)"),
                 dry: bool = typer.Option(False, "--dry-run", help="print the new batches and write nothing")) -> None:
        """Re-commit a ledger's format 1 batches in format 2. Each becomes a NEW batch at the end of the file that names the batch it supersedes; no line
        already in the file is changed."""
        got = read(ledger)
        bad = _structure(got)
        if bad:
            raise Stop(f"{ledger} does not hold as it is: {bad[0]}.", "Run `knos meter verify` on it first.")
        try:
            lines = migrate(got, month)
        except Bad as why:
            raise Stop(f"{why}.") from None
        if not lines:
            out.print(f"{ledger} has no format 1 batch left to re-commit{' in ' + month if month else ''}.", markup=False)
            return
        if not dry:
            with ledger.open("a", encoding="utf-8", newline="\n") as f:
                f.write("".join(x + "\n" for x in lines))
        for x in lines:
            h = json.loads(x)["batch"]
            out.print(f"batch {h['seq']} of {h['month']}: format 2 root {h['root']} supersedes {h['supersedes']}", markup=False)
        out.print(f"{'Would add' if dry else 'Added'} {len(lines)} batch(es) to {ledger}. The old batches and their roots are as they were: a format 1 root still binds "
                  f"{BINDS[1]}.", markup=False)
        out.print("The new roots are on your disk only: the program counts an evaluation once, so they are not sent as a RecordBatch. Send the file to the other "
                  "party; `knos meter reconcile` then compares every field.", markup=False)

    @meter.command("verify")
    def verify_(ledger: Path = typer.Argument(..., help="a ledger file"),
                onchain_: Path = typer.Option(None, "--onchain", help="the chain's Ledger account for the month as JSON: next_seq, count, accepted, value, chain"),
                month: str = typer.Option(None, "--month", help="which month --onchain is for, YYYY-MM (needed when the ledger has several)"),
                rpc: str = typer.Option(None, "--rpc", metavar="URL", help="read the Ledger accounts from this Solana RPC node and hold every month of the file to them"),
                claim: bool = typer.Option(False, "--claim", help="with --rpc: the file is the seller's, so it is held to the seller's claim account"),
                individual: Path = typer.Option(None, "--individual", help="ids the individual mode recorded, one a line: an evaluation here and in a batch is counted twice"),
                marks: bool = typer.Option(False, "--marks", help="with --rpc: read the individual mode's mark of every evaluation in the file (one read each) instead of --individual"),
                bundle_: bool = typer.Option(False, "--bundle", help="the file is a month's archive (`knos meter export --bundle`): check all of it, with no network")) -> None:
        """Recompute every root, every total and the running hash of a ledger, and refuse one that counts an evaluation twice; with --rpc (or --onchain), compare
        with the chain's. With --bundle, check a month's archive instead. Exit 1 if anything differs."""
        if bundle_:
            try:
                record, done = verify_month(Path(ledger).read_bytes())
            except OSError:
                raise Stop(f"Cannot read {ledger}.") from None
            except Bad as why:
                out.print(f"{ledger} does not verify: {why}.", markup=False)
                raise typer.Exit(1) from None
            for line in done:
                out.print(line, markup=False)
            out.print(f"The archive holds: {record['month']} of buyer {record['buyer']} and seller {record['seller']} is {record['state'].upper()}.", markup=False)
            return
        got = read(ledger)
        seen: dict = {}
        single = singles(individual)
        try:
            chain = Totals.of(json.loads(onchain_.read_text(encoding="utf-8"))) if onchain_ else None
            if rpc:
                try:
                    net = net_of(rpc)
                    single += individual_onchain(net, got) if marks else []
                    bad, seen = verify_onchain(got, net, claim, single)
                except Bad:
                    raise
                except Exception as why:  # noqa: BLE001 - the node said no, or did not answer
                    raise Stop(f"{rpc} did not answer ({str(why)[:120]}).", "Try again, or name another node with --rpc.") from None
            else:
                bad = verify(got, chain, month_of(month) if month else None, single)
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
        said(got)
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
                    out.print(f"The proof does not hold: evaluation {p.id.hex()} is not in a format {p.format} batch with root {p.root.hex()}.", markup=False)
                    raise typer.Exit(1)
                out.print(f"The proof holds: evaluation {p.id.hex()} is number {p.index} of {p.size} in the batch with root {p.root.hex()}.", markup=False)
                if p.event is not None:
                    f = dict(zip(FIELDS, p.event))
                    out.print(f"That batch committed to this: deliverable {f['deliverable_id']} is {ids.VERDICT_WORDS[f['verdict']]}, amount {f['amount']}"
                              f"{' ' + f['currency'] if f['currency'] else ''}, buyer {f['buyer']}, seller {f['seller']}.", markup=False)
                out.print(f"Commitment format {p.format}: the root binds {p.binds}.", markup=False)
                out.print(f"Next: see that batch {p.seq} of {p.month} was anchored with that root (the RecordBatch or ClaimBatch transaction's log).", markup=False)
                return
            if not ledger or not id_:
                raise Stop("Name a ledger and an evaluation: knos meter prove <ledger> <id>, or check a proof: knos meter prove --check <file>")
            made = prove(read(ledger), bytes.fromhex(_hex(id_.lower(), 64, "the id")))
            sys.stdout.write(json.dumps(made.json(), indent=1) + "\n")
            if made.format == 1:
                sys.stderr.write(f"Commitment format 1: this proof shows {BINDS[1]}.\n")
        except Bad as why:
            raise Stop(f"{why}.") from None
        except (OSError, ValueError):
            raise Stop(f"Cannot read {check} as JSON.") from None

    @meter.command("reconcile")
    def reconcile_(buyer: Path = typer.Argument(..., help="the buyer's ledger"), seller: Path = typer.Argument(..., help="the seller's ledger"),
                   rate: int = typer.Option(RATE, "--rate", help="the fee per evaluation in millionths of a USD (2000 is 0.002, the price book's)"),
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
                    out.print(f"{m} {e.id.hex()} {said}: {ids.VERDICT_WORDS[e.stands]}, rate {e.rate}", markup=False)
            for d in r.disputed:
                out.print(f"{d.buyer_month} {d.id.hex()} differs in {', '.join(d.fields or d.what)}: buyer {ids.VERDICT_WORDS[d.buyer.stands]} at {d.buyer.rate} in "
                          f"{d.buyer_month}, seller {ids.VERDICT_WORDS[d.seller.stands]} at {d.seller.rate} in {d.seller_month}", markup=False)
            for name in ("buyer", "seller"):
                for i in r.duplicates[name]:
                    out.print(f"{i.hex()} is in the {name}'s ledger more than once", markup=False)
            for name in ROLES:
                for c in r.corrections.get(name, ()):
                    out.print(f"correction ({c['kind']}) of {c['id']} in batch {c['of']} is in the {name}'s ledger (batch {c['batch']})"
                              + ("" if c["both"] else "; the other ledger does not carry it"), markup=False)
            if not r.complete:
                out.print(f"Compared verdict, rate and month only: a format 1 batch binds {BINDS[1]}.", markup=False)
            sys.stdout.write(r.statement())
            for row in r.rows:
                out.print(f"{row.month} verdicts of what both hold: " + ", ".join(f"{row.verdicts[v]} {ids.VERDICT_WORDS[v]}" for v in ids.VERDICTS)
                          + f"; {row.accepted_outcomes} deliverable(s) accepted for the first time (billed once each)", markup=False)
            out.print("The two ledgers agree." if r.agreed else
                      "The two ledgers differ. The statement counts only what both have and describe alike; settle the lines above between you.", markup=False)
        if not r.agreed:
            raise typer.Exit(1)

    def close_of(path: Path) -> dict:
        try:
            return read_close(Path(path).read_bytes())
        except OSError:
            raise Stop(f"Cannot read {path}.") from None
        except Bad as why:
            raise Stop(f"{path}: {why}.") from None

    def signed(close_file: Path) -> tuple[dict[str, str], dict]:
        """The tokens and the keys kept beside a close record."""
        tokens = {role: beside(close_file, f"{role}.jwt").read_text(encoding="ascii").strip() for role in ROLES if beside(close_file, f"{role}.jwt").exists()}
        try:
            jwks = json.loads(beside(close_file, "jwks.json").read_text(encoding="utf-8")) if beside(close_file, "jwks.json").exists() else {"keys": []}
        except ValueError:
            raise Stop(f"Cannot read {beside(close_file, 'jwks.json')} as JSON.") from None
        return tokens, jwks

    def _memory():
        """knos.recall, named here and not imported: the relay reaches this module, and a job that signs installs no memory engine."""
        import importlib
        return importlib.import_module(f"{__package__}.recall")

    @meter.command("correct")
    def correct_(ledger: Path = typer.Argument(..., help="your ledger file"),
                 id_: str = typer.Argument(..., metavar="ID", help="the evaluation's id, 64 hex characters"),
                 of: str = typer.Option(..., "--batch", metavar="YYYYMM.SEQ", help="the batch that holds the entry to correct"),
                 kind: str = typer.Option(..., "--kind", help="duplicate (that entry is a repeat), verdict (the verdict was wrong) or withdrawn (it should not have been counted)"),
                 accepted: int = typer.Option(None, "--accepted", help="with --kind verdict: the verdict that stands, 1 or 0"),
                 verdict: str = typer.Option(None, "--verdict", help="with --kind verdict, instead of --accepted: accepted, rejected, insufficient-evidence or disputed"),
                 by: str = typer.Option("buyer", "--by", help="who issues it: buyer or seller (the owner of this ledger)"),
                 remember: str = typer.Option("", "--remember", metavar="ORG", help="the buyer organisation whose memory keeps this correction, for `knos recall`; nothing is remembered when left out"),
                 memory_dir: Path = typer.Option(None, "--memory", metavar="DIR", help="with --remember: the directory of the memory store"),
                 terms: str = typer.Option("", "--terms", metavar="HASH", help="with --remember: the hash of the terms the evaluation fell under; without it the correction is kept under the two parties' ids")) -> None:
        """Write a correction of one anchored entry. The chain's counters only go up, so nothing is sent: the line waits in <ledger>.corrections, the next
        `knos meter batch` carries it in its root, and `knos meter statement` nets it."""
        got = read(ledger)
        try:
            if by not in ROLES or not got:
                raise Bad("--by is buyer or seller, and the ledger needs at least one batch")
            m = re.fullmatch(r"([0-9]{6})\.([0-9]{1,19})", of)
            try:
                word = ids.verdict(verdict) if verdict is not None else None
            except ValueError as why:
                raise Bad(f"--verdict: {why}") from None
            if m is None or (kind == "verdict") != ((accepted in (0, 1)) != (word is not None)) or (accepted is not None and word is not None):
                raise Bad("--batch is written <yyyymm>.<seq>, and --accepted 1 or 0, or --verdict with one of the four words, goes with --kind verdict "
                          "and with no other: one of the two")
            c = Correction(got[0].declared[by], _hex(id_.lower(), 64, "the id"), int(m[1]), int(m[2]), kind, accepted == 1 if accepted is not None else None, word)
            if not any((s.month, s.seq) == (c.month, c.seq) and any(e.id.hex() == c.id for e in s.evals) for s in got):
                raise Bad(f"batch {c.seq} of {c.month} in {ledger} holds no evaluation {c.id}")
        except Bad as why:
            raise Stop(f"{why}.") from None
        waiting = pending_of(ledger)
        had = waiting.read_text(encoding="utf-8") if waiting.exists() else ""
        if c.line() not in had.splitlines():
            waiting.write_text(had + c.line() + "\n", encoding="utf-8", newline="\n")
        out.print(f"Correction ({kind}) of evaluation {c.id} in batch {c.seq} of {c.month}, issued by the {by} (GitHub id {c.by}), is waiting in {waiting}.", markup=False)
        out.print("Next: `knos meter batch` puts it in your next batch, whose root GitHub signs; until then it is only on your disk. Send the other party the line.", markup=False)
        if remember:
            recall = _memory()
            if terms and not re.fullmatch(r"[0-9a-f]{64}", terms.lower()):
                raise Stop("--terms is the hash of the terms: 64 hex characters.")
            buyer_id, seller_id = got[0].declared.get("buyer", ""), got[0].declared.get("seller", "")
            try:
                recall.correction_made(recall.memory_of(remember, memory_dir), terms.lower() or recall.unnamed_terms(buyer_id, seller_id), str(seller_id), c.id, kind,
                                       accepted == 1 or word == "accepted", period=str(c.month))
            except ValueError as why:
                raise Stop(f"The correction is written, and nothing was remembered: {why}.") from None
            out.print(f"Remembered for {remember}: `knos recall exception --reason correction-{kind}` counts it.", markup=False)

    @meter.command("close")
    def close_(buyer: Path = typer.Argument(None, help="the buyer's ledger"), seller: Path = typer.Argument(None, help="the seller's ledger"),
               month: str = typer.Option(None, "--month", help="the month to close, YYYY-MM"),
               to: Path = typer.Option(None, "--out", help="where the close record is written (default: knos-close-<yyyymm>.json)"),
               individual: Path = typer.Option(None, "--individual", help="ids the individual mode recorded, one a line"),
               sign: Path = typer.Option(None, "--sign", metavar="CLOSE", help="in a GitHub Actions job: have GitHub sign this close record for your side, and keep the token beside it"),
               role: str = typer.Option(None, "--as", help="with --sign: buyer or seller"),
               token_file: Path = typer.Option(None, "--token", metavar="FILE", help="with --sign: the token GitHub already signed for this record (a job that installs nothing "
                                                                                    "asked for it): check it and keep it, and ask GitHub for none"),
               check: Path = typer.Option(None, "--check", metavar="CLOSE", help="check the tokens kept beside this close record, with no network"),
               events_log: Path = typer.Option(None, "--events", metavar="LOG", help="the log of events (knos events): the month is not closed while a number a sender gave never arrived and no acknowledged correction explains it"),
               remember: str = typer.Option("", "--remember", metavar="ORG", help="the buyer organisation whose memory archives the month's exceptions once it is agreed"),
               memory_dir: Path = typer.Option(None, "--memory", metavar="DIR", help="with --remember: the directory of the memory store")) -> None:
        """Close a month: set the two ledgers against each other and write the record both sides sign. `agreed`, or `disputed` with every line in dispute.
        Exit 1 when disputed. --sign and --check handle the two GitHub-signed tokens; the chain holds the batches, not the close."""
        if sign:
            record = close_of(sign)
            if role not in ROLES:
                raise Stop("Say whose signature this is: --as buyer or --as seller.")
            try:
                import urllib.request

                from . import flow
                # With --token nothing is asked of GitHub: the job that may ask installs nothing (examples/knos-meter-batch.yml),
                # and this one, which installs knos, holds the token to the record before it is kept.
                token = token_file.read_text(encoding="ascii").strip() if token_file else flow.mint(close_audience(record))
                with urllib.request.urlopen(GITHUB_JWKS, timeout=20) as r:  # noqa: S310 - a fixed https URL
                    jwks = json.load(r)
                check_close_token(record, token, jwks, role)
            except Bad as why:
                raise Stop(f"{why}.", f"Run this in a repository of the {role}.") from None
            except Exception as why:  # noqa: BLE001 - GitHub said no, or did not answer
                if token_file:
                    raise Stop(f"{token_file} could not be checked ({str(why)[:160]}).", "Give the token as GitHub signed it, and try again when GitHub's keys can be read.") from None
                raise Stop(f"GitHub gave no signed token ({str(why)[:160]}).", "Run this in a GitHub Actions job with `permissions: id-token: write`.") from None
            tokens, had = signed(sign)
            beside(sign, f"{role}.jwt").write_text(token + "\n", encoding="ascii", newline="\n")
            keys = keys_used({"keys": [*had.get("keys", []), *jwks.get("keys", [])]}, [*tokens.values(), token])
            beside(sign, "jwks.json").write_text(canon({"keys": sorted({canon(k): k for k in keys["keys"]}.values(), key=canon)}) + "\n", encoding="utf-8", newline="\n")
            out.print(f"GitHub signed {close_audience(record)} for the {role}.", markup=False)
            out.print(f"Kept: {beside(sign, f'{role}.jwt')} and {beside(sign, 'jwks.json')}. Commit them, or upload them as the run's artifact, and send them to the other party.", markup=False)
            return
        if check:
            record = close_of(check)
            tokens, jwks = signed(check)
            wrong = 0
            for r_ in ROLES:
                if r_ not in tokens:
                    out.print(f"The {r_} has not signed: there is no {beside(check, f'{r_}.jwt')}.", markup=False)
                    continue
                try:
                    claims = check_close_token(record, tokens[r_], jwks, r_)
                    out.print(f"The {r_} signed: GitHub's token for run {claims.get('run_id')} of {claims.get('repository')}, issued at {claims.get('iat')}.", markup=False)
                except Bad as why:
                    wrong += 1
                    out.print(f"{why}.", markup=False)
            both = not wrong and len(tokens) == 2
            out.print(f"{record['month']} is {record['state'].upper()}" + (" and signed by both sides." if both else "; it is NOT signed by both sides."), markup=False)
            if not both or record["state"] != "agreed":
                raise typer.Exit(1)
            return
        if not buyer or not seller or not month:
            raise Stop("Name the two ledgers and the month: knos meter close <buyer ledger> <seller ledger> --month YYYY-MM")
        if events_log is not None:      # completeness the two ledgers cannot show: a number that never arrived (knos.events.close_problems)
            from . import events
            beside_log = events_log.with_name(events_log.name + ".jwks.json")
            try:
                log_keys = json.loads(beside_log.read_text(encoding="utf-8")) if beside_log.exists() else None
                missing = events.close_problems(events.load(events_log, log_keys), month_of(month), signatures_checked=log_keys is not None)
            except (Bad, events.Bad, OSError, ValueError) as why:
                raise Stop(f"{str(why).rstrip('.')}.") from None
            if missing:
                raise Stop(f"{month} is not closed: {missing[0]}" + (f" ({len(missing) - 1} more: knos events gaps {events_log})" if len(missing) > 1 else ""),
                           "Nothing was written.")
        try:
            record = close(read(buyer), read(seller), month, singles(individual))
        except Bad as why:
            raise Stop(f"{why}.") from None
        to = to or Path(f"knos-close-{record['month']}.json")
        to.write_bytes(close_bytes(record))
        for name in ROLES:
            n = record[f"{name}_ledger"]
            out.print(f"the {name}'s ledger: {n['evaluations']} evaluation(s), {n['accepted_outcomes']} accepted outcome(s), {n['rejected']} rejected evaluation(s); "
                      f"anchored {n['anchored']} in {n['batches']} batch(es), running hash {n['chain']}", markup=False)
        for x in record["corrections"]:
            out.print(f"correction ({x['kind']}) of {x['id']} in batch {x['of']}, anchored in batch {x['batch']} of the {x['in']}'s ledger, issued by GitHub id {x['by']}", markup=False)
        for x in record["disputed"]:
            out.print(f"IN DISPUTE {x['id']}: {x['why']}", markup=False)
        out.print(f"{record['month']} is {record['state'].upper()}. Wrote {to} (sha256 {hashlib.sha256(close_bytes(record)).hexdigest()}).", markup=False)
        if record["state"] == "agreed" and remember:
            recall = _memory()
            try:
                kept = recall.history.period_closed(recall.memory_of(remember, memory_dir), str(month_of(month)))
            except ValueError as why:
                raise Stop(f"The close record is written, and nothing was archived: {why}.") from None
            out.print(f"Remembered for {remember}: the month's {kept.get('resolved', 0)} ended exception(s) are archived.", markup=False)
        if record["state"] == "agreed":
            out.print(f"Next: each side has its own GitHub run sign it (`knos meter close --sign {to} --as buyer`, and `--as seller`), then `knos meter close --check {to}`.", markup=False)
        else:
            out.print("A disputed month is not an invoice. Settle the lines above (add the missing evaluation in a later batch, or `knos meter correct`), then close again.", markup=False)
            raise typer.Exit(1)

    @meter.command("statement")
    def statement_(ledger: Path = typer.Argument(..., help="a ledger file"),
                   month: str = typer.Option(..., "--month", help="the month, YYYY-MM"),
                   close_file: Path = typer.Option(None, "--close", help="the month's close record; without it the statement's state is `open`"),
                   individual: Path = typer.Option(None, "--individual", help="ids the individual mode recorded, one a line"),
                   rate: int = typer.Option(RATE, "--rate", help="the Meter fee per evaluation in millionths of a USD (2000 is 0.002, the price book's)"),
                   free: int = typer.Option(FREE_PER_MONTH, "--free", help="free evaluations the buyer has left for this seller in the month"),
                   disputed: bool = typer.Option(False, "--disputed", help="print a disputed month anyway, with every disputed line marked"),
                   as_json: bool = typer.Option(False, "--json", help="the month as JSON: the four verdicts counted, and every line with its four ids")) -> None:
        """One month as three numbers that are never added together: evaluations (what the Meter bills), accepted outcomes (one per deliverable, what a
        per-outcome price multiplies) and rejected evaluations; with every repeat and correction. A disputed month is refused without --disputed."""
        try:
            args = (read(ledger), month, close_of(close_file) if close_file else None, singles(individual), rate, free, disputed)
            sys.stdout.write(json.dumps(statement_json(*args), indent=1, sort_keys=True) + "\n" if as_json else statement(*args))
        except Disputed as why:
            out.print(f"{why}.", markup=False)
            raise typer.Exit(1) from None
        except Bad as why:
            raise Stop(f"{why}.") from None

    @meter.command("export")
    def export_(ledger: Path = typer.Argument(..., help="a ledger file"), to: Path = typer.Option(None, "--out", help="write the CSV here instead of printing it"),
                bundle_: Path = typer.Option(None, "--bundle", metavar="FILE", help="write one archive of a closed month here instead: ledger, corrections, close record, tokens, keys"),
                close_file: Path = typer.Option(None, "--close", help="with --bundle: the month's close record (its tokens and keys are read from beside it)"),
                role: str = typer.Option("buyer", "--as", help="with --bundle: whose ledger this is, buyer or seller"),
                other: Path = typer.Option(None, "--other", help="with --bundle: the other party's ledger, to keep both in the archive")) -> None:
        """A ledger as CSV, one row per evaluation; or, with --bundle, a closed month as one archive either party checks with `knos meter verify <file> --bundle`."""
        if bundle_:
            if role not in ROLES or not close_file:
                raise Stop("An archive is of a closed month: pass --close <close record> and --as buyer or --as seller.")
            record = close_of(close_file)
            tokens, jwks = signed(close_file)
            ledgers = {role: text_of(ledger, "the ledger"), **({ROLES[1 - ROLES.index(role)]: text_of(other, "the other ledger")} if other else {})}
            try:
                blob = month_bundle(record, ledgers, tokens, jwks)
            except Bad as why:
                raise Stop(f"{why}.", "Nothing was written.") from None
            bundle_.write_bytes(blob)
            out.print(f"Wrote {bundle_}: {record['month']}, {record['state']}, signed by {', '.join(sorted(tokens)) or 'nobody yet'} "
                      f"(sha256 {hashlib.sha256(blob).hexdigest()}). Anyone checks it with `knos meter verify {bundle_} --bundle`.", markup=False)
            return
        text = export_csv(read(ledger))
        if to:
            to.write_text(text, encoding="utf-8", newline="\n")
            out.print(f"Wrote {to}: {text.count(chr(10)) - 1} evaluation(s).", markup=False)
        else:
            sys.stdout.write(text)
