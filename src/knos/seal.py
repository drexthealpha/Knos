"""Proving nobody quietly edited the record of who yielded to whom.

The journal is the part of knos a team actually relies on after the fact: who
claimed what, who stood down for whom, who overrode a claim and what reason
they gave. An override is a thing an agent does *against* somebody else's
work, and the only cost it carries is that it is written down under its own
name. If that line can be edited or dropped afterwards, the cost is zero and
the override was never really a cost at all.

So every fact carries a link: a hash over its own contents and the link before
it. Change a word in an old entry, or remove one, and every link after it
stops matching. `knos verify` walks the journal and says where.

**The chain is per writer, and that is on purpose.** knos is a multi-process
product - sixteen agents racing for one claim is a test in this repository -
and a single global chain would fork the moment two processes appended at the
same instant. A fork looks exactly like tampering, and a tamper alarm that
goes off during ordinary work is worse than no alarm, because people learn to
ignore it. Each writer chains its own entries instead.

What that proves: no entry of a given writer's can be altered or removed
without the rest of that writer's chain failing.

What it does not prove: anything about the order of two different writers'
entries, and nothing at all against somebody who rewrites a whole chain from
the beginning - they hold the file. This is tamper-*evident*, not tamper-proof,
and the difference is worth stating rather than blurring.

Like everything else here it lives in the store, so deleting the store takes
the proof with it.
"""

from __future__ import annotations

import hashlib
from typing import Any

GENESIS = "0" * 16
FIELDS = ("text", "source", "where", "when", "about", "path", "seq")


def link(prev: str, fact: dict[str, Any]) -> str:
    """The link for one fact, given the one before it from the same writer."""
    body = "\x1f".join(str(fact.get(f, "")) for f in FIELDS)
    return hashlib.sha256(f"{prev}\x1e{body}".encode()).hexdigest()[:16]


def _entries(mem: Any, limit: int = 5000) -> list[dict[str, Any]]:
    """Every sealed journal fact, in no particular order.

    Deliberately not sorted here. Facts written in the same instant come back
    in whatever order the journal happens to hand them over, and a chain
    rebuilt from that order fails on entries nobody touched - which is the
    worst possible bug in a tamper alarm. Each writer's own sequence number
    is what orders them, in `check`.
    """
    out = []
    for row in mem.journal(limit=limit):
        extra = row.get("extra")
        if isinstance(extra, dict) and extra.get("link"):
            out.append(extra)
    return out


def head(mem: Any, who: str) -> tuple[str, int]:
    """(last link, last sequence number) for this writer."""
    best: tuple[str, int] | None = None
    for fact in _entries(mem):
        if str(fact.get("where", "")) != who:
            continue
        try:
            seq = int(fact.get("seq", 0))
        except (TypeError, ValueError):
            continue
        if best is None or seq > best[1]:
            best = (str(fact.get("link") or GENESIS), seq)
    return best or (GENESIS, 0)


def check(mem: Any) -> list[dict[str, Any]]:
    """Every place a writer's chain stops adding up.

    Returns one entry per break, each naming the writer, what the entry says,
    and when it was written. An empty list means every chain in the store
    recomputes exactly.
    """
    broken: list[dict[str, Any]] = []
    by_writer: dict[str, list[dict[str, Any]]] = {}
    for fact in _entries(mem):
        by_writer.setdefault(str(fact.get("where", "")), []).append(fact)

    for who, facts in by_writer.items():
        facts.sort(key=lambda f: int(f.get("seq", 0) or 0))
        prev = GENESIS
        expect_seq = 1
        for fact in facts:
            seq = int(fact.get("seq", 0) or 0)
            want = link(prev, fact)
            got = str(fact.get("link") or "")
            if seq != expect_seq:
                broken.append({
                    "who": who,
                    "text": str(fact.get("text", ""))[:80],
                    "when": str(fact.get("when", ""))[:19],
                    "expected": f"entry {expect_seq}",
                    "found": f"entry {seq} - one is missing",
                })
            elif got != want:
                broken.append({
                    "who": who,
                    "text": str(fact.get("text", ""))[:80],
                    "when": str(fact.get("when", ""))[:19],
                    "expected": want,
                    "found": got or "(none)",
                })
            # Carry the stored link forward either way, so one altered entry
            # is reported once rather than reddening every line after it.
            prev = got or want
            expect_seq = seq + 1
    return broken


def counted(mem: Any) -> dict[str, int]:
    """How much of the journal is sealed, for `knos verify` to say."""
    facts = _entries(mem)
    writers = {str(f.get("where", "")) for f in facts}
    return {"sealed": len(facts), "writers": len(writers)}
