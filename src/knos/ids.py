"""The four things a statement names, each with an identity of its own, and the four verdicts.

One purchased milestone can take ten pull requests, three agents and twenty evaluations. So four different things
are never called by one id:

    deliverable    what was bought: one milestone of one order (or one line of a standing offer). Billed once.
    evaluation     one run of the agreed acceptance on one artifact. Many per deliverable.
    invoice line   one line a supplier sent for payment. It names a deliverable; two lines naming one are a duplicate.
    settlement     one movement of money (or its record, when paid by bank) for one deliverable.

An id is a short prefix and 24 hex characters of a SHA-256 over a tagged, length-prefixed list of parts, so the same
parts give the same id in every interface, export and language, and an id of one kind is never taken for another.

A verdict is one of four words. `insufficient_evidence` is its own answer: a run that could not tell is never
turned into acceptance, and never into the supplier's failure. `disputed` is a verdict somebody has contested and
nobody has resolved yet.
"""
from __future__ import annotations

import hashlib

VERDICTS = ("accepted", "rejected", "insufficient_evidence", "disputed")
VERDICT_WORDS = {"accepted": "accepted", "rejected": "rejected", "insufficient_evidence": "insufficient evidence",
                 "disputed": "disputed"}
BILLABLE = frozenset({"accepted"})          # the only verdict a deliverable is billed on, and once

# What a statement says of one invoice line, after it is set against the count.
LINE_STATES = ("agreed", "disputed", "duplicate", "insufficient_evidence")
LINE_WORDS = {"agreed": "agreed", "disputed": "disputed", "duplicate": "duplicate",
              "insufficient_evidence": "insufficient evidence"}

PREFIX = {"deliverable": "dlv", "evaluation": "evl", "invoice_line": "inv", "settlement": "stl"}


def _id(kind: str, *parts: str | int | bytes) -> str:
    h = hashlib.sha256(b"knos.id.v1\x00" + kind.encode() + b"\x00")
    for p in parts:
        b = p if isinstance(p, bytes) else str(p).encode("utf-8")
        h.update(len(b).to_bytes(4, "big") + b)
    return f"{PREFIX[kind]}_{h.hexdigest()[:24]}"


_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def order_scope(order: str) -> str:
    """An order as the scope of its deliverables: its 32 bytes as 64 lowercase hex characters. A ledger writes an
    order that way already; a receipt and an audit export write its base58 address. Both name one order, so both
    must give one deliverable id. ValueError for a text that is neither."""
    if len(order) == 64 and all(c in "0123456789abcdef" for c in order):
        return order
    n = 0
    for c in order:
        if c not in _B58:
            raise ValueError(f"not an order: {order!r} (64 lowercase hex characters, or a base58 address)")
        n = n * 58 + _B58.index(c)
    if not 32 <= len(order) <= 44 or n >= 1 << 256:
        raise ValueError(f"not an order: {order!r} (64 lowercase hex characters, or a base58 address)")
    return n.to_bytes(32, "big").hex()


def expect(kind: str, an_id) -> str:
    """`an_id` when it is an id of this kind; ValueError, in words, when it is of another kind or of none."""
    got = kind_of(an_id) if isinstance(an_id, str) else None
    if got != kind:
        was = f"{'an' if got[0] in 'aeiou' else 'a'} {got.replace('_', ' ')} id" if got else "not an id"
        raise ValueError(f"{'an' if kind[0] in 'aeiou' else 'a'} {kind.replace('_', ' ')} id ({PREFIX[kind]}_ and 24 hex characters) is expected here; {str(an_id)[:40]!r} is {was}")
    return an_id


def deliverable(scope: str, key: str | int) -> str:
    """`scope`: the order (hex) or the standing offer's terms hash. `key`: the milestone number or the task's key."""
    return _id("deliverable", scope, key)


def evaluation(deliverable_id: str, artifact: str, policy: str, evaluator: str, run: str | int) -> str:
    """One run: this artifact (a commit or a content hash), under this policy version, by this evaluator, in this run."""
    return _id("evaluation", deliverable_id, artifact, policy, evaluator, run)


def invoice_line(supplier: str, invoice: str, line: str | int) -> str:
    """The supplier's own line: who sent it, on which invoice, at which line. It does not depend on what it claims."""
    return _id("invoice_line", supplier, invoice, line)


def settlement(deliverable_id: str, method: str, reference: str) -> str:
    """`method`: chain, bank or other. `reference`: the transaction signature, or the payer's own reference."""
    return _id("settlement", deliverable_id, method, reference)


def kind_of(an_id: str) -> str | None:
    """Which of the four an id is, or None when it is none of them."""
    head, _, tail = an_id.partition("_")
    for kind, prefix in PREFIX.items():
        if head == prefix and len(tail) == 24 and all(c in "0123456789abcdef" for c in tail):
            return kind
    return None


def verdict(word: str) -> str:
    """The verdict a loose word means, or ValueError. Older records said passed, failed, unverified and pending."""
    w = word.strip().lower().replace(" ", "_").replace("-", "_")
    old = {"passed": "accepted", "clean": "accepted", "failed": "rejected", "refused": "rejected",
           "unverified": "insufficient_evidence", "pending": "insufficient_evidence", "none": "insufficient_evidence"}
    w = old.get(w, w)
    if w not in VERDICTS:
        raise ValueError(f"not a verdict: {word!r} (one of: {', '.join(VERDICT_WORDS.values())})")
    return w
