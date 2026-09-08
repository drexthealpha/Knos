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

What that proves, exactly, because the two halves are not the same strength:

  altered   caught for every entry, always. The link is computed over the
            entry's own contents, so changing a word breaks it whether that
            writer wrote one entry or a thousand.
  removed   caught only inside a chain of more than one, because a sequence
            number is what shows a gap. A writer with a single entry has
            nothing left to notice its absence.

That distinction matters here rather than being pedantry. The facts knos reads
out of your code carry a file and a line as their source, so almost every one
of them is its own writer and its own chain of one. The facts that describe
what agents *did* - claimed, stood down, overrode, were told - carry the agent
as the writer, and those are the chains with length, which is exactly where
deleting a line would be worth somebody's while.

What it does not prove at all: anything about the order of two different
writers' entries, and nothing against somebody who rewrites a whole chain from
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
    """How much of the journal is sealed, and how much of it can lose a line.

    `chained` is the part where a deletion would show up: entries belonging to
    a writer with more than one of them. Reporting only a total would let
    "59 entries, 59 writers" read as a strong claim when it is fifty-nine
    chains of one, each of which detects an edit and none of which can notice
    a removal.
    """
    facts = _entries(mem)
    per: dict[str, int] = {}
    for fact in facts:
        who = str(fact.get("where", ""))
        per[who] = per.get(who, 0) + 1
    chained = sum(n for n in per.values() if n > 1)
    return {
        "sealed": len(facts),
        "writers": len(per),
        "chained": chained,
        "sequences": sum(1 for n in per.values() if n > 1),
    }
