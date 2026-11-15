"""One log of events under every recording mode: what was already counted, said in one place.

Knos records work in several modes: one evaluation in one transaction (`record`), a month's evaluations under one
Merkle root (`batch`), a paid order or bounty (`settle`), an invoice set against GitHub's record (`shadow`), and a
file somebody hands over (`import`). Each mode refuses its own repeats. None of them sees the others: a batch root
commits to a set and says nothing about a single record made the week before. This module is where they meet.

    Event       one thing that happened, with an id derived from WHAT it is (knos.ids), never from when or how it
                arrived. Kinds: evaluation, acceptance, invoice_line, settlement, correction, acknowledgement.
    Log         an append-only file of events, JSON Lines, each line canonical (knos.ledger.canon) and carrying the
                sha256 of the line before it. `read` recomputes the chain: a removed, reordered or edited line is found.
    ingest      THE one way in, for every mode. An id the log has not seen is appended and counted. The same id with
                the same content from another source is appended as a repeat (`first` names the line that counts), so
                it is counted once and both sources stay on record. The same id with different content is a conflict:
                refused, reported, and not written. The very same arrival twice (a retry) changes nothing.
    acknowledge the other party signs the log up to a head hash: a token of the issuer both already use (GitHub
                Actions, RS256, checked off line exactly as a `knosm:close:` token is) whose audience is
                `knosm:ack:<owner id>:<last line>:<head hash>`. A log in which that line no longer has that hash fails
                `read`. What was acknowledged is changed only by a later correction event.
    correction  an event that names another and says what it is now (a verdict, an amount, or void). Nothing is rewritten.
    statement   one month from the index (by month, by deliverable, by supplier) the log keeps as it grows: only that
                month's events are read, and a deliverable's other lines are found by key.
    export      a folder with the log, the acknowledgements, the keys, the index and every month's statement, and
                `check_export`, which rebuilds all of it from the log alone.
    gaps        what a root cannot say. A source numbers what it sends, per buyer, supplier and month, from 0; the
                number rides in `evidence` (`batch:` or `sent:`). `gaps` names the numbers that never arrived, and
                `close_problems` refuses a month over one unless a correction of the number itself (`gap:...`, void,
                with a reason) sits under a head a party signed. `across` names a deliverable billed or settled in
                more than one month: one deliverable id, ever.

What this proves and what it does not is in docs/reference/EVENTS.md. In one line: uniqueness is enforced here and by both
parties' acknowledgements, not on chain.

Standard library only. The adapters import the module of their mode inside the function.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator

from . import ids
from .ledger import GITHUB_ISSUER, Bad, canon, keys_used, month_of

KINDS = ("evaluation", "acceptance", "invoice_line", "settlement", "correction", "acknowledgement")
SOURCES = ("record", "batch", "settle", "shadow", "import")
COUNTED = ("evaluation", "acceptance", "invoice_line", "settlement")       # what a correction can name
ZERO = "0" * 64                                                            # `prev` of the first line
OWN = {"acceptance": "acc", "correction": "cor", "acknowledgement": "ack"}  # ids of the kinds knos.ids does not name
ACK = "knosm:ack"
KEYS = ("ack", "amount", "corrects", "deliverable", "evaluation", "evidence", "first", "id", "invoice_line", "kind", "month", "prev", "reason", "seq",
        "settlement", "source", "supplier", "unit", "verdict", "void")
TYPE, VERSION = "knos.events-export", 1
GAP = "gap:"                        # what a correction of a number nobody received names: gap:<buyer>:<supplier>:<yyyymm>.<number>
_PART = r"[A-Za-z0-9._-]{1,64}"
_STREAM = rf"({_PART}:{_PART}:[0-9]{{6}})\.(0|[1-9][0-9]{{0,18}})"
_SENT = re.compile(rf"(?:batch|sent):{_STREAM}(?::.*)?", re.S)
_GAP = re.compile(GAP + _STREAM)


def _own(kind: str, *parts: str | int) -> str:
    """An id for an acceptance, a correction or an acknowledgement: built as knos.ids builds the four it names (a tag,
    then every part with its length), under a tag of its own, so none is ever taken for one of those."""
    h = hashlib.sha256(b"knos.event.v1\x00" + kind.encode() + b"\x00")
    for p in parts:
        b = str(p).encode("utf-8")
        h.update(len(b).to_bytes(4, "big") + b)
    return f"{OWN[kind]}_{h.hexdigest()[:24]}"


def _hash(line: str) -> str:
    return hashlib.sha256(line.encode("utf-8")).hexdigest()


# -- one event --------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Event:
    id: str                     # what it is: an evl_, inv_ or stl_ id of knos.ids, or acc_, cor_, ack_
    kind: str                   # one of KINDS
    source: str                 # the mode it arrived by, one of SOURCES
    deliverable: str = ""       # the four ids, where they apply
    evaluation: str = ""
    invoice_line: str = ""
    settlement: str = ""
    verdict: str = ""           # one of ids.VERDICTS, or empty
    amount: int | None = None   # in `unit`; None when the event states no amount
    unit: str = ""              # what `amount` counts: "cents", a currency's smallest unit, ...
    supplier: str = ""
    month: int = 0              # yyyymm the event belongs to (0: none); where a statement looks for it
    evidence: str = ""          # where the issuer's evidence is: a transaction, a batch and its root, a statement's hash
    corrects: str = ""          # a correction: the id of the event it corrects
    void: bool = False          # a correction: the event it names no longer counts
    reason: str = ""            # a correction: why, in the words of whoever made it
    ack: dict | None = None     # an acknowledgement: {"head", "party", "token", "upto"}
    seq: int = -1               # its line in the log, from 0 (set by the log)
    prev: str = ""              # sha256 of the line before (set by the log)
    first: int | None = None    # a repeat: the line that counts (set by the log)

    def body(self) -> dict:
        return {"ack": self.ack, "amount": self.amount, "corrects": self.corrects, "deliverable": self.deliverable, "evaluation": self.evaluation,
                "evidence": self.evidence, "first": self.first, "id": self.id, "invoice_line": self.invoice_line, "kind": self.kind, "month": self.month,
                "prev": self.prev, "reason": self.reason, "seq": self.seq, "settlement": self.settlement, "source": self.source, "supplier": self.supplier,
                "unit": self.unit, "verdict": self.verdict, "void": int(self.void)}

    def line(self) -> str:
        return canon(self.body())

    def stated(self) -> tuple:
        """What the event says, apart from how it came. Two arrivals of one id must agree on this, or one is refused.
        An acceptance does not state which evaluation carried it: a deliverable is accepted once, whatever number of
        runs it took. The month and the evidence are where and when, not what."""
        return (self.kind, self.deliverable, "" if self.kind == "acceptance" else self.evaluation, self.invoice_line, self.settlement, self.verdict,
                self.amount, self.unit, self.supplier, self.corrects, self.void, self.reason, canon(self.ack) if self.ack else "")

    @classmethod
    def of(cls, o: object) -> "Event":
        if not isinstance(o, dict) or tuple(sorted(o)) != KEYS:
            raise Bad("an event has exactly these fields: " + ", ".join(KEYS))
        text = ("corrects", "deliverable", "evaluation", "evidence", "id", "invoice_line", "kind", "prev", "reason", "settlement", "source", "supplier", "unit", "verdict")
        if not all(isinstance(o[k], str) for k in text) or o["void"] not in (0, 1) or isinstance(o["void"], bool):
            raise Bad("an event's fields are text, and void is 1 or 0")
        for k in ("amount", "first", "month", "seq"):
            if isinstance(o[k], bool) or not (isinstance(o[k], int) or (o[k] is None and k in ("amount", "first"))):
                raise Bad(f"an event's {k} is a whole number")
        if o["ack"] is not None and not isinstance(o["ack"], dict):
            raise Bad("an event's ack is an acknowledgement or null")
        return cls(**{**o, "void": o["void"] == 1})


STATED = ("kind", "deliverable", "evaluation", "invoice_line", "settlement", "verdict", "amount", "unit", "supplier", "corrects", "void", "reason", "ack")


def problem_of(e: Event) -> str | None:
    """Why `e` is not an event this log takes, or None. The id must be the id of what the event says it is."""
    if e.kind not in KINDS:
        return f"{e.kind!r} is not a kind of event (one of: {', '.join(KINDS)})"
    if e.source not in SOURCES:
        return f"{e.source!r} is not a recording mode (one of: {', '.join(SOURCES)})"
    if e.verdict and e.verdict not in ids.VERDICTS:
        return f"{e.verdict!r} is not a verdict (one of: {', '.join(ids.VERDICTS)})"
    for name in ids.PREFIX:
        value = getattr(e, name)
        if value and ids.kind_of(value) != name:
            return f"{value!r} is not the id of a {name.replace('_', ' ')}"
    if e.month and not (190001 <= e.month <= 999912 and 1 <= e.month % 100 <= 12):
        return f"{e.month} is not a month (yyyymm)"
    if e.amount is not None and (isinstance(e.amount, bool) or not isinstance(e.amount, int) or not e.unit or e.amount < 0):
        return "an amount is a whole number, zero or more, and names its unit"
    if e.kind != "correction" and (e.corrects or e.void or e.reason):
        return "only a correction names another event, voids one or gives a reason"
    if (e.kind == "acknowledgement") != (e.ack is not None):
        return "an acknowledgement, and nothing else, carries a signed token"
    if e.kind == "evaluation":
        if e.id != e.evaluation or not e.deliverable or not e.verdict:
            return "an evaluation's id is its evaluation id, and it names its deliverable and its verdict"
    elif e.kind == "acceptance":
        if not e.deliverable or e.id != _own("acceptance", e.deliverable) or e.verdict != "accepted":
            return "an acceptance names its deliverable, takes its id from it, and its verdict is accepted"
    elif e.kind == "invoice_line":
        if e.id != e.invoice_line:
            return "an invoice line's id is its invoice line id"
    elif e.kind == "settlement":
        if e.id != e.settlement or not e.deliverable or e.amount is None:
            return "a settlement's id is its settlement id, and it names its deliverable and its amount"
    elif e.kind == "correction":
        if not e.corrects or e.id != _own("correction", e.corrects, e.verdict, "" if e.amount is None else e.amount, e.unit, int(e.void), e.reason):
            return "a correction names the event it corrects and takes its id from what it changes"
        if e.corrects.startswith(GAP) and not (_GAP.fullmatch(e.corrects) and e.void and e.reason.strip() and not e.verdict and e.amount is None):
            return f"a correction of a missing number names it as {GAP}<buyer>:<supplier>:<yyyymm>.<number>, is void, gives its reason and changes nothing else"
        if not (e.void or e.verdict or e.amount is not None):
            return "a correction says what changes: a verdict, an amount, or that the event is void"
    else:
        a = e.ack or {}
        if sorted(a) != ["head", "party", "token", "upto"] or not isinstance(a["token"], str) or not isinstance(a["head"], str) \
                or isinstance(a["upto"], bool) or not isinstance(a["upto"], int) or isinstance(a["party"], bool) or not isinstance(a["party"], int):
            return "an acknowledgement carries head, party, token and upto"
        if e.id != _own("acknowledgement", a["party"], a["upto"], a["head"]):
            return "an acknowledgement takes its id from the party and the head it signed"
    return None


# -- the events of each kind, from what they are ------------------------------------------------------------------------
def evaluation(deliverable: str, artifact: str, policy: str, evaluator: str, run: str | int, verdict: str, source: str, supplier: str = "",
               month: int = 0, amount: int | None = None, unit: str = "", evidence: str = "") -> Event:
    eid = ids.evaluation(deliverable, artifact, policy, evaluator, run)
    return Event(eid, "evaluation", source, deliverable=deliverable, evaluation=eid, verdict=ids.verdict(verdict), amount=amount, unit=unit,
                 supplier=supplier, month=month, evidence=evidence)


def acceptance(deliverable: str, source: str, supplier: str = "", month: int = 0, amount: int | None = None, unit: str = "", evaluation: str = "",
               evidence: str = "") -> Event:
    """A deliverable accepted: one per deliverable, whatever number of evaluations it took."""
    return Event(_own("acceptance", deliverable), "acceptance", source, deliverable=deliverable, evaluation=evaluation, verdict="accepted", amount=amount,
                 unit=unit, supplier=supplier, month=month, evidence=evidence)


def invoice_line(supplier: str, invoice: str, line: str | int, source: str, deliverable: str = "", month: int = 0, amount: int | None = None,
                 unit: str = "", evidence: str = "") -> Event:
    lid = ids.invoice_line(supplier, invoice, line)
    return Event(lid, "invoice_line", source, deliverable=deliverable, invoice_line=lid, amount=amount, unit=unit, supplier=supplier, month=month,
                 evidence=evidence)


def settlement(deliverable: str, method: str, reference: str, amount: int, unit: str, source: str, supplier: str = "", month: int = 0,
               evidence: str = "") -> Event:
    sid = ids.settlement(deliverable, method, reference)
    return Event(sid, "settlement", source, deliverable=deliverable, settlement=sid, amount=amount, unit=unit, supplier=supplier, month=month,
                 evidence=evidence or f"{method}:{reference}")


def correction(target: str, source: str = "import", verdict: str = "", amount: int | None = None, unit: str = "", void: bool = False, reason: str = "",
               month: int = 0, evidence: str = "") -> Event:
    """What the event `target` is from now on. The event itself stays as it was written."""
    verdict = ids.verdict(verdict) if verdict else ""
    return Event(_own("correction", target, verdict, "" if amount is None else amount, unit, int(void), reason), "correction", source, verdict=verdict,
                 amount=amount, unit=unit, month=month, evidence=evidence, corrects=target, void=void, reason=reason)


# -- acknowledgements ---------------------------------------------------------------------------------------------------
def ack_audience(party: int, upto: int, head: str) -> str:
    """The audience of the token by which `party` (a GitHub owner id) acknowledges the log's lines 0 to `upto`, the
    last of which has the hash `head`: `knosm:ack:<party>:<upto>:<head>`. The same family as `knosm:close:`, signed
    the same way, kept off chain the same way: no program reads it."""
    return f"{ACK}:{party}:{upto}:{head}"


def _claims(token: str) -> dict:
    from .ledger import _jwt_part
    return _jwt_part(token, 1)


def check_ack_token(token: str, jwks: dict | None, issuers: tuple[str, ...] = (GITHUB_ISSUER,)) -> tuple[int, int, str]:
    """(party, upto, head) when `token` is an acknowledgement: issued by one of `issuers`, for an audience
    `ack_audience` writes, from a repository whose owner is the party the audience names, and, when `jwks` is given,
    carrying the RS256 signature of one of its keys (knos.bundle.rs256, the check `knosm:close:` tokens get). Raises
    Bad in words otherwise. Expiry is not held against it, for the reason a close token's is not: it is read later."""
    from . import bundle
    from .ledger import _jwt_part
    token = token.strip()
    head, claims = _jwt_part(token, 0), _jwt_part(token, 1)
    if jwks is not None:
        moduli = [int.from_bytes(bundle._unb64(k["n"]), "big") for k in jwks.get("keys", [])
                  if isinstance(k, dict) and k.get("kty") == "RSA" and k.get("e") == "AQAB" and k.get("kid") == head.get("kid") and isinstance(k.get("n"), str)]
        if not any(bundle.rs256(token, n) for n in moduli):
            raise Bad(f"the token does not carry the signature of any of the given keys (key id {head.get('kid')!r}): the token or the keys were changed")
    if claims.get("iss") not in issuers:
        raise Bad("the token was not issued by " + " or ".join(issuers))
    p = str(claims.get("aud", "")).split(":")
    if len(p) != 5 or ":".join(p[:2]) != ACK or not p[2].isdigit() or not p[3].isdigit() or len(p[4]) != 64 or not set(p[4]) <= set("0123456789abcdef"):
        raise Bad(f"the token was signed for something else than a head of this log (its audience is not {ACK}:<owner id>:<line>:<head hash>)")
    if str(claims.get("repository_owner_id")) != p[2]:
        raise Bad(f"the token is from a repository of GitHub id {claims.get('repository_owner_id')}, and it acknowledges for {p[2]}")
    return int(p[2]), int(p[3]), p[4]


def acknowledgement(token: str, source: str = "import", month: int = 0) -> Event:
    """The event for a signed acknowledgement. `ingest` checks the signature and that the log has that head."""
    party, upto, head = check_ack_token(token, None)
    token = token.strip()
    return Event(_own("acknowledgement", party, upto, head), "acknowledgement", source, month=month, evidence="token:" + _hash(token),
                 ack={"head": head, "party": party, "token": token, "upto": upto})


# -- the log ----------------------------------------------------------------------------------------------------------
class Log:
    """The events in order, and the index kept as they are added: by id, by deliverable, by month, by supplier."""

    def __init__(self) -> None:
        self.events: list[Event] = []
        self.hashes: list[str] = []
        self.first: dict[str, int] = {}                  # id -> the line that counts
        self.arrivals: dict[str, list[int]] = {}         # id -> every line that carries it
        self.seen: set[tuple[str, str, str]] = set()     # (id, source, evidence): an arrival already written
        self.fixes: dict[str, list[int]] = {}            # id -> the corrections that name it, in order
        self.by_deliverable: dict[str, list[int]] = {}
        self.by_month: dict[int, list[int]] = {}
        self.by_supplier: dict[str, list[int]] = {}
        self.acks: list[int] = []
        self.on_disk = 0                                 # how many lines the file already has

    @property
    def head(self) -> str:
        return self.hashes[-1] if self.hashes else ZERO

    def _put(self, e: Event, h: str) -> None:
        n = len(self.events)
        self.events.append(e)
        self.hashes.append(h)
        self.first.setdefault(e.id, n)
        self.arrivals.setdefault(e.id, []).append(n)
        self.seen.add((e.id, e.source, e.evidence))
        if e.deliverable:
            self.by_deliverable.setdefault(e.deliverable, []).append(n)
        if e.month:
            self.by_month.setdefault(e.month, []).append(n)
        if e.supplier:
            self.by_supplier.setdefault(e.supplier, []).append(n)
        if e.kind == "correction" and e.first is None:
            self.fixes.setdefault(e.corrects, []).append(n)
        if e.kind == "acknowledgement" and e.first is None:
            self.acks.append(n)

    def append(self, e: Event) -> Event:
        e = replace(e, seq=len(self.events), prev=self.head, first=self.first.get(e.id))
        self._put(e, _hash(e.line()))
        return e

    def text(self, start: int = 0) -> str:
        return "".join(e.line() + "\n" for e in self.events[start:])

    def write(self, path: Path) -> int:
        """Append the lines the file does not have yet. Nothing already written is touched. Returns how many."""
        new = len(self.events) - self.on_disk
        if new:
            with open(path, "a", encoding="utf-8", newline="\n") as f:
                f.write(self.text(self.on_disk))
            self.on_disk = len(self.events)
        return new

    # -- what an event is now -------------------------------------------------------------------------------------------
    def state(self, e: Event) -> tuple[str, int | None, str, bool]:
        """(verdict, amount, unit, void) of a counted event after every correction that names it, in the log's order."""
        verdict, amount, unit, void = e.verdict, e.amount, e.unit, False
        for n in self.fixes.get(e.id, ()):
            c = self.events[n]
            void = c.void
            verdict = c.verdict or verdict
            if c.amount is not None:
                amount, unit = c.amount, c.unit
        return verdict, amount, unit, void

    def verdict_of(self, deliverable: str) -> tuple[str, int | None, str]:
        """(verdict, accepted amount, its unit) of a deliverable, from its own lines only (the index by deliverable).
        Its acceptance says it when there is one; otherwise its evaluations do: disputed before accepted before
        rejected, and insufficient evidence when nothing says more."""
        said: set[str] = set()
        amount: int | None = None
        unit = ""
        for n in self.by_deliverable.get(deliverable, ()):
            e = self.events[n]
            if e.first is not None or e.kind not in ("evaluation", "acceptance"):
                continue
            v, a, u, void = self.state(e)
            if void:
                continue
            if e.kind == "acceptance":
                return v, a, u
            said.add(v)
            if v == "accepted" and amount is None and a is not None:
                amount, unit = a, u
        for v in ("disputed", "accepted", "rejected"):
            if v in said:
                return v, (amount if v == "accepted" else None), (unit if v == "accepted" else "")
        return "insufficient_evidence", None, ""

    def acknowledged(self) -> dict[str, int]:
        """party -> the last line that party has acknowledged."""
        out: dict[str, int] = {}
        for n in self.acks:
            a = self.events[n].ack or {}
            out[str(a["party"])] = max(out.get(str(a["party"]), -1), a["upto"])
        return out

    def dupes(self) -> list[dict]:
        """Every id that arrived more than once: counted at its first line, with every source it came by."""
        return [{"id": i, "kind": self.events[at[0]].kind, "counted_at": at[0],
                 "sources": [{"line": n, "source": self.events[n].source, "evidence": self.events[n].evidence} for n in at]}
                for i, at in self.arrivals.items() if len(at) > 1]

    def index(self) -> dict:
        return {"by_deliverable": dict(sorted(self.by_deliverable.items())), "by_month": {str(m): at for m, at in sorted(self.by_month.items())},
                "by_supplier": dict(sorted(self.by_supplier.items())), "events": len(self.events), "head": self.head}


def _named(log: Log, e: Event) -> bool:
    """Whether a correction names something it can: a counted event already in the log, or a number of a stream."""
    return bool(_GAP.fullmatch(e.corrects)) or (e.corrects in log.first and log.events[log.first[e.corrects]].kind in COUNTED)


def _arrived(log: Log, name: str) -> int | None:
    """The first line that arrived under the number a `gap:` name says, or None."""
    want = sent_of(name.replace(GAP, "sent:", 1))
    return next((n for n, x in enumerate(log.events) if sent(x) == want), None)


def _ack_problem(log: Log, e: Event, jwks: dict | None, at: int) -> str | None:
    a = e.ack or {}
    try:
        got = check_ack_token(a["token"], jwks)
    except Bad as why:
        return str(why)
    if got != (a["party"], a["upto"], a["head"]):
        return "the token was signed for another party or another head than the line says"
    if not 0 <= a["upto"] < at:
        return f"it acknowledges line {a['upto']}, which is not before it"
    if log.hashes[a["upto"]] != a["head"]:
        return (f"GitHub id {a['party']} acknowledged lines 0 to {a['upto']} with the head {a['head'][:16]}..., and that line's hash is now "
                f"{log.hashes[a['upto']][:16]}...: something in the acknowledged range was changed")
    return None


def read(text: str, jwks: dict | None = None, head: str | None = None) -> tuple[Log, list[str]]:
    """The log in `text`, and everything wrong with it, in words. One pass. `jwks`: the keys to check the
    acknowledgements' signatures with (without them the tokens are read and matched to the log, and not verified).
    `head`: the head you expect, from an acknowledgement you hold or an export: the only way to find lines removed
    from the END, which leave a shorter chain that is still a chain."""
    log, said = Log(), []
    for n, line in enumerate(x for x in text.split("\n") if x):
        try:
            e = Event.of(json.loads(line))
        except (ValueError, TypeError) as why:
            said.append(f"Line {n} is not an event ({why}). Nothing after it was read.")
            break
        if e.line() != line:
            said.append(f"Line {n} is not written in the canonical form: it was edited.")
        if e.seq != n or e.prev != log.head:
            said.append(f"Line {n} does not follow the line before it (it says it is line {e.seq} after {e.prev[:16]}...): a line was removed, reordered or edited.")
        why_not = problem_of(e)
        if why_not:
            said.append(f"Line {n}: {why_not}.")
        counted = log.first.get(e.id)
        if e.first != counted:
            said.append(f"Line {n} says " + ("it counts" if e.first is None else f"line {e.first} counts") + " for " + e.id
                        + (f", and line {counted} is the first with that id." if counted is not None else ", and no earlier line has that id."))
        elif counted is not None and log.events[counted].stated() != e.stated():
            said.append(f"Lines {counted} and {n} carry the id {e.id} and say different things: a conflict that should have been refused.")
        if e.kind == "correction" and not why_not and not _named(log, e):
            said.append(f"Line {n} corrects {e.corrects}, which no earlier line is.")
        if e.kind == "acknowledgement" and not why_not and (bad := _ack_problem(log, e, jwks, n)):
            said.append(f"Line {n}: {bad}.")
        log._put(e, _hash(line))
    log.on_disk = len(log.events)
    if head is not None and log.head != head:
        at = log.hashes.index(head) if head in log.hashes else None
        said.append(f"The log's head is {log.head[:16]}..., not {head[:16]}...: " + (f"that is line {at}, and {len(log.events) - 1 - at} lines came after it."
                                                                                   if at is not None else "lines were removed from the end, or this is another log."))
    return log, said


def load(path: Path, jwks: dict | None = None) -> Log:
    """The log in a file (an absent file is an empty log). Raises Bad when it does not check."""
    log, said = read(path.read_text(encoding="utf-8") if path.exists() else "", jwks)
    if said:
        raise Bad(f"{path} does not check. " + said[0] + (f" ({len(said) - 1} more: knos events verify)" if len(said) > 1 else ""))
    return log


# -- the one way in ---------------------------------------------------------------------------------------------------
@dataclass
class Report:
    added: list[Event]
    duplicates: list[dict]      # counted once: {"id", "kind", "counted_at", "sources": [the first arrival, this one]}
    conflicts: list[dict]       # refused: {"id", "differs", "kept", "refused"}
    refused: list[dict]         # not an event, or names what the log does not have: {"why", "event"}
    known: int = 0              # the very same arrival again: nothing written

    @property
    def ok(self) -> bool:
        return not self.conflicts and not self.refused

    def json(self) -> dict:
        return {"added": len(self.added), "counted": sum(1 for e in self.added if e.first is None), "duplicates": self.duplicates,
                "conflicts": self.conflicts, "refused": self.refused, "known": self.known}


def _where(e: Event) -> dict:
    return {"line": e.seq, "source": e.source, "evidence": e.evidence}


def ingest(log: Log, events: Iterable[Event], jwks: dict | None = None) -> Report:
    """Every mode's way into the log. See the module's first lines for the four outcomes. An acknowledgement is taken
    only with `jwks`, the keys its signature is checked with."""
    r = Report([], [], [], [])
    for e in events:
        why = problem_of(e)
        if not why and e.kind == "correction" and not _named(log, e):
            why = f"it corrects {e.corrects}, which is not an event of this log"
        if not why and e.kind == "correction" and e.corrects.startswith(GAP) and (at_line := _arrived(log, e.corrects)) is not None:
            why = f"it says nothing was sent under {e.corrects[len(GAP):]}, and line {at_line} of this log arrived under that number"
        if not why and e.kind == "acknowledgement":
            why = "an acknowledgement needs the issuer's keys to be checked" if jwks is None else _ack_problem(log, e, jwks, len(log.events))
        if why:
            r.refused.append({"why": why, "event": e.body()})
            continue
        at = log.first.get(e.id)
        if at is None:
            r.added.append(log.append(e))
            continue
        kept = log.events[at]
        if kept.stated() != e.stated():
            r.conflicts.append({"id": e.id, "differs": [k for k, a, b in zip(STATED, kept.stated(), e.stated()) if a != b],
                                "kept": {**_where(kept), **{k: v for k, v in kept.body().items() if k in STATED}},
                                "refused": {"source": e.source, "evidence": e.evidence, **{k: v for k, v in e.body().items() if k in STATED}}})
        elif (e.id, e.source, e.evidence) in log.seen:
            r.known += 1
        else:
            again = log.append(e)
            r.added.append(again)
            r.duplicates.append({"id": e.id, "kind": e.kind, "counted_at": at, "sources": [_where(kept), _where(again)]})
    return r


# -- two writers, one file ----------------------------------------------------------------------------------------------
# A line names the line before it, so two processes that each read the log and then append would both write line N.
# A writer therefore holds `<log>.lock` from before it reads until after it appends. The lock is a file made with
# exclusive create (O_CREAT | O_EXCL), which one process wins on every platform Python runs on, Windows included; no
# fcntl, no msvcrt. A writer that finds it held tries again, a little later each time, for `wait` seconds and then
# gives up with Busy. A lock older than `stale` seconds was left by a writer that died: it is taken away by a rename
# only one process can win, and the wait goes on.
ENV = "KNOS_EVENTS"                 # the log every recording mode writes to when no --events names one
LOCK_WAIT, LOCK_STALE = 30.0, 120.0


class Busy(OSError):
    """Another writer held the log's lock for longer than this one waits."""


def lock_of(path: Path) -> Path:
    return path.with_name(path.name + ".lock")


@contextmanager
def locked(path: Path, wait: float = LOCK_WAIT, stale: float = LOCK_STALE, clock: Callable[[], float] = time.monotonic,
           sleep: Callable[[float], None] = time.sleep, now: Callable[[], float] = time.time) -> Iterator[Path]:
    """Hold the lock of the log at `path` for the body. Raises Busy when it stays held for `wait` seconds."""
    lock, began, pause = lock_of(path), clock(), 0.005
    lock.parent.mkdir(parents=True, exist_ok=True)
    while True:
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            break
        except FileExistsError:
            pass
        except PermissionError:         # Windows, while another process is deleting the lock: it is free in a moment
            pass
        try:
            if now() - lock.stat().st_mtime > stale:
                gone = lock.with_name(f"{lock.name}.{os.getpid()}.{time.monotonic_ns()}.stale")
                os.replace(lock, gone)          # only one process's rename finds the file
                gone.unlink()
                continue
        except OSError:                 # it went away between the two calls, or another process took it away: try again
            pass
        if clock() - began >= wait:
            raise Busy(f"{path} is being written by another process (its lock, {lock.name}, has been held for {wait:g} seconds). Try again; "
                       f"if no process is writing, the lock is removed by itself {stale:g} seconds after it was made.")
        sleep(pause)
        pause = min(pause * 2, 0.2)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(f"{os.getpid()} {int(now())}\n")
        yield lock
    finally:
        try:
            lock.unlink()
        except OSError:
            pass


def record(path: Path, events: Iterable[Event], jwks: dict | None = None, **lock) -> Report:
    """Read the log at `path`, take `events` in and append what is new, as one writer: under the log's lock. The one
    call a recording mode makes. Raises Bad when the log does not check, Busy when it stays locked."""
    found = list(events)            # made before the lock is taken: nothing slow is done while it is held
    with locked(path, **lock):
        log = load(path, jwks)
        r = ingest(log, found, jwks)
        log.write(path)
    return r


def where(given: Path | str | None = None, env=None) -> Path | None:
    """The log a recording mode writes to: `--events`, else KNOS_EVENTS, else none (the modes then write none)."""
    said = given or (os.environ if env is None else env).get(ENV)
    return Path(said) if said else None


def keep(path: Path | str | None, events: Callable[[], Iterable[Event]], say: Callable[[str], None] | None = None) -> Report | None:
    """What a recording mode calls after its own record is written: its events into the log at `path`, when one is
    named. Best effort: the mode's own record is already made, so a log that cannot be read, locked or written is one
    line on stderr and nothing else. Returns the report, or None when no log is named or nothing was written."""
    if not path:
        return None
    try:
        r = record(Path(path), events())
    except Exception as why:  # noqa: BLE001 - never in the way of the mode that called
        (say or (lambda line: print(line, file=sys.stderr)))(f"The events log {path} was not written ({why}). `knos events ingest` takes the same records in later.")
        return None
    if not r.ok:
        (say or (lambda line: print(line, file=sys.stderr)))(
            f"The events log {path} refused {len(r.conflicts) + len(r.refused)} event(s): the same id with other contents, or not an event. "
            "`knos events ingest` on the same records says which.")
    return r


# -- each mode's events -------------------------------------------------------------------------------------------------
METER_EVALUATOR = "knos_meter"      # the meter bills (order, artifact, policy, milestone) once: one run, by the program's rule


def from_evaluation(e, source: str, month: int, evidence: str = "") -> Iterator[Event]:
    """One evaluation of the meter (knos.ledger.Evaluation), whichever mode recorded it: the evaluation, and the
    acceptance of its deliverable when it was accepted. The record mode and the batch mode give the same ids."""
    dlv = ids.deliverable(e.order, e.milestone)
    ev = evaluation(dlv, e.artifact, e.policy, METER_EVALUATOR, 0, "accepted" if e.accepted else "rejected", source, supplier=str(e.seller), month=month,
                    amount=e.rate, unit="units", evidence=evidence)
    yield ev
    if e.accepted:
        yield acceptance(dlv, source, supplier=str(e.seller), month=month, amount=e.rate, unit="units", evaluation=ev.id, evidence=evidence)


def from_records(lines: Iterable[str], month: int | str) -> Iterator[Event]:
    """The record mode: one evaluation a line, a `knosm:eval:...` audience or a ledger line, then (after a space) the
    transaction that recorded it when you have it."""
    from . import ledger
    for line in lines:
        if line.strip():
            what, _, tx = line.strip().partition(" ") if line.startswith("knosm:") else (line.strip(), "", "")
            yield from from_evaluation(ledger.parse(what), "record", month_of(month), f"tx:{tx.strip()}" if tx.strip() else "record")


def from_ledger(text: str) -> Iterator[Event]:
    """The batch mode: every evaluation of a meter ledger file, with its batch and that batch's root as evidence."""
    from . import ledger
    for b in ledger.load(text):
        d = b.declared
        for e in b.evals:
            where = f"batch:{d['buyer']}:{d['seller']}:{b.month}.{b.seq}:{d['root']}"
            # From format 2 on the batch commits to the whole event, so the log names the event's hash: the leaf itself.
            yield from from_evaluation(e, "batch", b.month, where if b.format == 1 else f"{where}:event:{event_hash(e, b.month, b.seq)}")


def event_hash(e, month: int | str, seq: int) -> str:
    """The hash of one evaluation of the meter as an event, in hex: the leaf of its format 2 batch. There is one
    definition, knos.ledger.event_hash, and this is it: the log and the batch agree on what an event is."""
    from . import ledger
    return ledger.event_hash(e, month_of(month), seq).hex()


def from_audit(rows: Iterable[dict]) -> Iterator[Event]:
    """The settle mode: the paid lines of an audit export (knos.audit), one settlement each. The deliverable is the
    line's billing key: the order and the transaction that funded it, and the milestone."""
    for r in rows:
        if str(r.get("kind")) not in ("paid", "released") or not str(r.get("billing_key") or "") or not int(r.get("paid_units") or 0):
            continue
        scope, _, milestone = str(r["billing_key"]).rpartition(":")
        yield settlement(ids.deliverable(scope, milestone), "chain", str(r["transaction"]), int(r["paid_units"]), str(r.get("currency") or "units"), "settle",
                         supplier=str(r.get("supplier_ids") or ""), month=month_of(str(r["date"])[:7]), evidence=f"tx:{r['transaction']}")


SHADOW_VERDICT = {"clean": "accepted", "failed": "rejected", "not_merged": "rejected", "unverified": "insufficient_evidence", "unreadable": "insufficient_evidence"}


def from_shadow(statement: dict, invoice: str, month: int | str, supplier: str = "") -> Iterator[Event]:
    """The shadow mode: a statement `knos shadow` wrote for an invoice named `invoice`. Each line is an invoice line,
    and each pull request GitHub answered for is an evaluation by its checks. The deliverable is the pull request; a
    line the statement found billed twice names the deliverable of the line it repeats."""
    m, digest = month_of(month), hashlib.sha256(canon(statement).encode()).hexdigest()
    dlv: dict[int, str] = {}
    for row in statement["lines"]:
        who, n = str(row.get("supplier") or supplier or statement.get("supplier") or ""), row["line"]
        repo, _, number = str(row.get("pr") or "").partition("#")
        dlv[n] = dlv.get(row.get("duplicate_of"), "") if row.get("class") == "duplicate" and row.get("duplicate_of") in dlv \
            else ids.deliverable("github:" + repo.lower(), number) if repo and number else ""
        amount = None if row.get("amount") in (None, "") else int(str(row["amount"]).replace(".", "").replace(",", ""))
        yield invoice_line(who, invoice, n, "shadow", deliverable=dlv[n], month=m, amount=amount, unit="cents" if amount is not None else "",
                           evidence=f"shadow:{digest}#{n}")
        if dlv[n] and row.get("class") in SHADOW_VERDICT and row.get("class") != "unreadable":
            yield evaluation(dlv[n], str(row.get("merge_commit") or row.get("head") or ""), f"shadow.v{statement.get('version', 1)}", "github-checks", 0,
                             SHADOW_VERDICT[row["class"]], "shadow", supplier=who, month=m, evidence=f"shadow:{digest}#{n}")


def from_import(lines: Iterable[str]) -> Iterator[Event]:
    """The import mode: one JSON object a line. Either an event's own fields (what `Event.body` writes; seq, prev and
    first are ignored), or a short form that names its parts and lets the id be derived:
        {"evaluation": {"deliverable", "artifact", "policy", "evaluator", "run", "verdict"}, ...}
        {"acceptance": {"deliverable"}, ...}       {"invoice_line": {"supplier", "invoice", "line"}, ...}
        {"settlement": {"deliverable", "method", "reference", "amount", "unit"}, ...}
        {"correction": {"of": <id>, "verdict"?, "amount"?, "unit"?, "void"?, "reason"?}, ...}
    with supplier, month, amount, unit, deliverable and evidence beside it where they apply."""
    for n, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            o = json.loads(line)
            if not isinstance(o, dict):
                raise ValueError("not an object")
            c: dict[str, Any] = {"supplier": str(o.get("supplier", "")), "month": month_of(o["month"]) if o.get("month") else 0, "evidence": str(o.get("evidence", "")),
                 "amount": o.get("amount"), "unit": str(o.get("unit", ""))}
            src = str(o.get("source", "import"))
            if isinstance(p := o.get("evaluation"), dict):
                yield evaluation(p["deliverable"], str(p["artifact"]), str(p["policy"]), str(p["evaluator"]), p["run"], p["verdict"], src, **c)
            elif isinstance(p := o.get("acceptance"), dict):
                yield acceptance(p["deliverable"], src, evaluation=str(p.get("evaluation", "")), **c)
            elif isinstance(p := o.get("invoice_line"), dict):
                yield invoice_line(str(p["supplier"]), str(p["invoice"]), p["line"], src, deliverable=str(o.get("deliverable", "")),
                                   **{k: v for k, v in c.items() if k != "supplier"})
            elif isinstance(p := o.get("settlement"), dict):
                yield settlement(p["deliverable"], str(p["method"]), str(p["reference"]), p["amount"], str(p["unit"]), src, supplier=c["supplier"],
                                 month=c["month"], evidence=c["evidence"])
            elif isinstance(p := o.get("correction"), dict):
                yield correction(str(p["of"]), src, verdict=str(p.get("verdict", "")), amount=p.get("amount"), unit=str(p.get("unit", "")),
                                 void=bool(p.get("void")), reason=str(p.get("reason", "")), month=c["month"], evidence=c["evidence"])
            else:
                yield replace(Event.of({**{k: None for k in ("ack", "amount", "first")}, **{k: "" for k in KEYS if k not in ("ack", "amount", "first")},
                                        "month": 0, "void": 0, **o, "seq": -1, "prev": ""}), first=None)
        except (KeyError, TypeError, ValueError) as why:
            raise Bad(f"line {n} is not an event to import: {why}") from None


# -- a month ----------------------------------------------------------------------------------------------------------
def statement(log: Log, month: int | str, supplier: str = "") -> dict:
    """One month, from the index: the month's own lines are read once, and a deliverable's verdict and earlier
    invoice lines are found by key, wherever in the log they are. A line is `agreed`, `disputed`, `duplicate` or
    `insufficient_evidence` (ids.LINE_STATES). The statement names the head it was made at: the same log gives the
    same bytes, and a later correction gives a later statement, never a changed one."""
    m = month_of(month)
    evals = {v: 0 for v in ids.VERDICTS}
    lines: list[dict] = []
    accepted: set[str] = set()
    money: dict[str, dict[str, int]] = {}
    repeats = voided = 0
    fixes: list[int] = []

    def add(unit: str, what: str, amount: int | None) -> None:
        if amount is not None and unit:
            money.setdefault(unit, {k: 0 for k in ("billed", *ids.LINE_STATES, "settled")})[what] += amount

    for n in log.by_month.get(m, ()):
        e = log.events[n]
        if e.first is not None:
            repeats += 1
            continue
        if e.kind == "correction":
            fixes.append(n)
            continue
        if e.kind == "acknowledgement" or (supplier and e.supplier != supplier):
            continue
        verdict, amount, unit, void = log.state(e)
        if void:
            voided += 1
        elif e.kind == "evaluation":
            evals[verdict] += 1
        elif e.kind == "acceptance":
            if verdict == "accepted":
                accepted.add(e.deliverable)
        elif e.kind == "settlement":
            add(unit, "settled", amount)
        else:
            earlier = next((k for k in log.by_deliverable.get(e.deliverable, ()) if k < n and log.events[k].kind == "invoice_line"
                            and log.events[k].first is None and not log.state(log.events[k])[3]), None) if e.deliverable else None
            state, why = "insufficient_evidence", "the line names no deliverable" if not e.deliverable else "nothing accepted or rejected this deliverable"
            if earlier is not None:
                state, why = "duplicate", f"line {earlier} already bills this deliverable ({log.events[earlier].id})"
            elif e.deliverable:
                v, agreed_amount, agreed_unit = log.verdict_of(e.deliverable)
                if v == "accepted" and amount is not None and agreed_amount is not None and (amount, unit) != (agreed_amount, agreed_unit):
                    state, why = "disputed", f"billed {amount} {unit}, accepted at {agreed_amount} {agreed_unit}"
                elif v == "accepted":
                    state, why = "agreed", ""
                elif v in ("rejected", "disputed"):
                    state, why = "disputed", f"the deliverable is {ids.VERDICT_WORDS[v]}"
            add(unit, "billed", amount)
            add(unit, state, amount)
            lines.append({"amount": amount, "deliverable": e.deliverable, "id": e.id, "line": n, "state": state, "supplier": e.supplier, "unit": unit, "why": why})
    acked = log.acknowledged()
    last = max(log.by_month.get(m, [-1]))
    st = {"type": "knos.events-statement", "version": 1, "month": m, "supplier": supplier, "head": log.head, "events": len(log.events),
          "evaluations": evals, "accepted_deliverables": len(accepted), "invoice_lines": lines,
          "line_states": {s: sum(1 for x in lines if x["state"] == s) for s in ids.LINE_STATES}, "amounts": dict(sorted(money.items())),
          "repeats_not_counted": repeats, "voided": voided, "corrections": fixes,
          "acknowledged": {"upto": dict(sorted(acked.items())), "covers_month": sorted(p for p, upto in acked.items() if upto >= last >= 0)}}
    return {**st, "sha256": hashlib.sha256(canon(st).encode()).hexdigest()}


# -- what a root cannot say: completeness ---------------------------------------------------------------------------------
# A root commits to what was put under it. It cannot say that something was left out. So each source numbers what it
# sends, per buyer, supplier and month, from 0, and the number travels in `evidence`:
#     batch:<buyer>:<supplier>:<yyyymm>.<number>:<root>...     the batch mode writes this already (the batch's seq)
#     sent:<buyer>:<supplier>:<yyyymm>.<number>[:anything]     any other mode, when its sender numbers what it sends
# A number below the highest seen that never arrived is a gap. Nothing fills it but the missing arrival itself, or a
# correction that names the number (`gap:<buyer>:<supplier>:<yyyymm>.<number>`), is void and gives a reason, under a
# head a party acknowledged with a signed token. The last numbers of a stream are found only when its sender says its
# last number (`last`): numbers cut from the end leave a shorter run that is still a run.
def sent_of(evidence: str) -> tuple[str, int] | None:
    m = _SENT.fullmatch(evidence)
    return (m[1], int(m[2])) if m else None


def sent(e: Event) -> tuple[str, int] | None:
    """(stream, number) when the event's evidence carries its sender's number: `<buyer>:<supplier>:<yyyymm>`, and the number."""
    return sent_of(e.evidence) if e.kind in COUNTED else None


def gap_name(stream: str, number: int) -> str:
    return f"{GAP}{stream}.{int(number)}"


def gap_correction(stream: str, number: int, reason: str, source: str = "import", evidence: str = "") -> Event:
    """The record that explains a missing number: nothing was sent under it, and why. It counts once a party has
    acknowledged a head after it. It rewrites nothing, and it is refused when the number did arrive."""
    return correction(gap_name(stream, number), source, void=True, reason=reason, month=int(stream.rsplit(":", 1)[1]), evidence=evidence)


def signed_by(log: Log, line: int) -> list[str]:
    """The parties whose acknowledgement covers `line`: each signed a head at or after it."""
    return sorted(p for p, upto in log.acknowledged().items() if upto >= line)


def gaps(log: Log, month: int | str = 0, last: dict[str, int] | None = None) -> list[dict]:
    """Every number of every stream that should be in the log and is not, lowest first: {"stream", "number", "state",
    "line", "reason", "signed_by"}. `state` is `open` (nothing explains it), `unsigned` (a correction explains it and
    no party has acknowledged a head after that correction) or `explained` (a correction, acknowledged). `last`:
    stream -> the last number its sender says it sent; without it only numbers below the highest that arrived are
    known to be missing. `month`: one month only."""
    m = month_of(month) if month else 0
    seen: dict[str, set[int]] = {}
    told: dict[tuple[str, int], int] = {}
    for n, e in enumerate(log.events):
        got = sent(e)
        if got:
            seen.setdefault(got[0], set()).add(got[1])
        elif e.kind == "correction" and e.first is None and (g := _GAP.fullmatch(e.corrects)):
            told[(g[1], int(g[2]))] = n
            seen.setdefault(g[1], set())
    for stream, number in (last or {}).items():
        if not re.fullmatch(rf"{_PART}:{_PART}:[0-9]{{6}}", stream) or isinstance(number, bool) or not isinstance(number, int) or number < 0:
            raise Bad(f"a stream's last number is written <buyer>:<supplier>:<yyyymm>.<number>, not {stream}.{number}")
        seen.setdefault(stream, set())
    out: list[dict] = []
    for stream in sorted(seen):
        if m and int(stream.rsplit(":", 1)[1]) != m:
            continue
        top = max([*seen[stream], *(k for s, k in told if s == stream), (last or {}).get(stream, -1)], default=-1)
        for number in range(top + 1):
            if number in seen[stream]:
                continue
            line = told.get((stream, number))
            who = signed_by(log, line) if line is not None else []
            out.append({"stream": stream, "number": number, "state": "open" if line is None else "explained" if who else "unsigned", "line": line,
                        "reason": log.events[line].reason if line is not None else "", "signed_by": who})
    return out


def close_problems(log: Log, month: int | str, last: dict[str, int] | None = None, signatures_checked: bool = True,
                   acks: Iterable[dict] | None = None, terms_docs: Iterable[dict] = ()) -> list[str]:
    """Why the month cannot be closed, in words; an empty list when it can. A month is not closed over a missing number:
    either the number arrives, or a correction explains it under a head a party signed (and the signature was checked
    against the issuer's keys: `signatures_checked`). With `acks` (the parties' signed acknowledgements and closures of
    months, knos.period) and the Knos Terms 3 documents that name their keys, the month must also be CLOSED by them:
    both parties signed its last line, or one did and closed it after the silence the terms allow."""
    said = []
    if acks is not None:
        from . import period
        said += period.close_problems(log, month, acks, terms_docs)
    for g in gaps(log, month, last):
        what = f"Number {g['number']} of {g['stream']} never arrived"
        if g["state"] == "open":
            said.append(f"{what}. Ask its sender for it, or record why nothing was sent: a correction of {gap_name(g['stream'], g['number'])}.")
        elif g["state"] == "unsigned":
            said.append(f"{what}. Line {g['line']} explains it ({g['reason']}), and no party has acknowledged a head after that line: `knos events ack`.")
        elif not signatures_checked:
            said.append(f"{what}. Line {g['line']} explains it and GitHub id {', '.join(g['signed_by'])} acknowledged it, but the signature was not checked: give the issuer's keys.")
    return said


def across(log: Log) -> list[dict]:
    """One deliverable id, ever: every deliverable with more than one counted invoice line, or more than one counted
    settlement, wherever in the log and in whichever months they are. A second invoice line is a `duplicate` in its
    month's statement and is never agreed. A second settlement is money that moved twice for one deliverable (or in
    two parts): it is named here, with both lines, for a person to read."""
    out = []
    for dlv, at in sorted(log.by_deliverable.items()):
        for kind in ("invoice_line", "settlement"):
            mine = [n for n in at if log.events[n].kind == kind and log.events[n].first is None and not log.state(log.events[n])[3]]
            if len(mine) > 1:
                out.append({"deliverable": dlv, "kind": kind, "counted_at": mine[0], "months": sorted({log.events[n].month for n in mine}),
                            "lines": [{"line": n, "id": log.events[n].id, "month": log.events[n].month, "amount": log.state(log.events[n])[1],
                                       "unit": log.state(log.events[n])[2]} for n in mine]})
    return out


# -- the evidence, in one folder ------------------------------------------------------------------------------------------
def export_files(log: Log, jwks: dict | None = None, refused: str = "") -> dict[str, bytes]:
    """Everything needed to reach every conclusion again: the log, the acknowledgements and the keys they were signed
    with, the repeats, the index, and each month's statement. `manifest.json` names each file's sha256 and the head."""
    acks = [{"line": n, **(log.events[n].ack or {})} for n in log.acks]
    files = {"events.jsonl": log.text().encode(), "acknowledgements.json": (canon(acks) + "\n").encode(),
             "jwks.json": (canon(keys_used(jwks or {"keys": []}, [a["token"] for a in acks])) + "\n").encode(),
             "duplicates.json": (canon(log.dupes()) + "\n").encode(), "index.json": (canon(log.index()) + "\n").encode(),
             **{f"statements/{m}.json": (canon(statement(log, m)) + "\n").encode() for m in sorted(log.by_month)}}
    if refused:
        files["refused.jsonl"] = refused.encode()
    manifest = {"type": TYPE, "version": VERSION, "head": log.head, "events": len(log.events),
                "files": {name: hashlib.sha256(raw).hexdigest() for name, raw in sorted(files.items())}}
    return {**files, "manifest.json": (canon(manifest) + "\n").encode()}


def check_export(files: dict[str, bytes]) -> list[str]:
    """What is wrong with an export, with no network: the log is read again (its chain, its acknowledgements against
    the keys beside it, its head against the manifest's), and every other file is rebuilt from it and compared."""
    try:
        manifest = json.loads(files["manifest.json"])
        jwks = json.loads(files["jwks.json"])
        text = files["events.jsonl"].decode("utf-8")
        assert manifest["type"] == TYPE and manifest["version"] == VERSION and isinstance(manifest["files"], dict)
    except Exception:  # noqa: BLE001 - missing, not JSON, or not an export: one sentence either way
        return ["This is not an export as `knos events export` writes one."]
    log, said = read(text, jwks, manifest.get("head"))
    again = export_files(log, jwks, files.get("refused.jsonl", b"").decode("utf-8", "replace"))
    for name in sorted(set(again) | set(files)):
        if files.get(name) != again.get(name):
            said.append(f"{name} is not what the log gives: " + ("it is missing." if name not in files else "it is not part of an export." if name not in again
                                                                else "it was changed, or the log was."))
    return said


# -- the command line -------------------------------------------------------------------------------------------------
def register(app, help_lines: list | None = None) -> None:
    """`knos events ingest | verify | ack | sign | dupes | gaps | close | statement | export`, on the main app. `help_lines`: cli._HELP."""
    import importlib
    typer = importlib.import_module("typer")       # the command line's package, named here and not imported: the relay reaches this module on an install without it

    events = typer.Typer(add_completion=False, no_args_is_help=True,
                         help="One log of events under every recording mode: what was counted, what arrived twice, what both sides acknowledged.")
    app.add_typer(events, name="events")
    if help_lines is not None:
        help_lines.append(("events", "For money", "One log under every recording mode: ingest, verify, ack, sign, dupes, gaps, close, statement, export."))

    def stop(said: str, fix: str = ""):
        from . import cli
        return cli.Stop(said, fix)

    def beside(log: Path, name: str) -> Path:
        return log.with_name(log.name + "." + name)

    def keys_of(log: Path, given: Path | None = None) -> dict | None:
        path = given or beside(log, "jwks.json")
        if not path.exists():
            if given:
                raise stop(f"Cannot read {given}.")
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            raise stop(f"Cannot read {path} as JSON.") from None

    def opened(path: Path, jwks: dict | None = None) -> Log:
        try:
            return load(path, jwks)
        except Bad as why:
            raise stop(str(why), "Run `knos events verify` on it. A log is never repaired by editing it.") from None

    def say(o) -> None:
        typer.echo(json.dumps(o, indent=1, sort_keys=True))

    @events.command("ingest")
    def ingest_(log: Path = typer.Argument(..., help="the log file (made when absent)"),
                what: Path = typer.Argument(..., help="what to take in"),
                mode: str = typer.Option(..., "--from", help="record (evaluations, one a line), batch (a meter ledger file), settle (an audit export), "
                                                              "shadow (a statement.json of `knos shadow`) or import (events as JSON, one a line)"),
                month: str = typer.Option(None, "--month", help="record and shadow: the month these belong to, YYYY-MM"),
                invoice: str = typer.Option(None, "--invoice", help="shadow: the invoice's own number or name"),
                supplier: str = typer.Option("", "--supplier", help="shadow: the supplier, when the invoice does not say"),
                as_json: bool = typer.Option(False, "--json", help="print the report as JSON")) -> None:
        """Take one mode's records into the log. What the log has not seen is counted; what it has, from another source, is kept as a repeat and counted once; the same id with different content is refused and written to <log>.refused.jsonl. Exit 1 when anything was refused."""
        if mode not in SOURCES:
            raise stop(f"--from is one of: {', '.join(SOURCES)}.")
        if mode in ("record", "shadow") and not month or mode == "shadow" and not invoice:
            raise stop("--from record needs --month; --from shadow needs --month and --invoice.")
        opened(log, keys_of(log))        # a log that does not check is said before anything else is read
        try:
            text = what.read_text(encoding="utf-8-sig")
            if mode == "record":
                found = list(from_records(text.splitlines(), month))
            elif mode == "batch":
                found = list(from_ledger(text))
            elif mode == "settle":
                from . import audit
                found = list(from_audit(audit.parse(text)[1]))
            elif mode == "shadow":
                found = list(from_shadow(json.loads(text), invoice, month, supplier))
            else:
                found = list(from_import(text.splitlines()))
        except OSError:
            raise stop(f"Cannot read {what}.") from None
        except (ValueError, KeyError, TypeError) as why:
            raise stop(f"{what} could not be read as --from {mode}: {why}") from None
        try:
            with locked(log):               # one writer at a time: the log is read, added to and appended under its lock
                book = opened(log, keys_of(log))
                r = ingest(book, found, keys_of(log))
                book.write(log)
        except Busy as why:
            raise stop(str(why)) from None
        if r.conflicts or r.refused:
            with open(beside(log, "refused.jsonl"), "a", encoding="utf-8", newline="\n") as f:
                f.write("".join(canon({"from": mode, **x}) + "\n" for x in (*r.conflicts, *r.refused)))
        if as_json:
            say({**r.json(), "head": book.head})
        else:
            counted = sum(1 for e in r.added if e.first is None)
            typer.echo(f"{counted} counted, {len(r.duplicates)} already counted (kept as repeats, with both sources), {r.known} seen before from this "
                       f"source, {len(r.conflicts)} in conflict, {len(r.refused)} refused. Head {book.head}")
            for c in r.conflicts:
                typer.echo(f"  conflict {c['id']}: {', '.join(c['differs'])} differ from line {c['kept']['line']} ({c['kept']['source']}). Refused.")
            for x in r.refused:
                typer.echo(f"  refused {x['event']['id'] or x['event']['kind']}: {x['why']}.")
        if not r.ok:
            raise typer.Exit(1)

    @events.command("verify")
    def verify_(log: Path = typer.Argument(..., help="the log file, or a folder `knos events export` wrote"),
                keys: Path = typer.Option(None, "--keys", help="the issuer's keys (a JWKS file) to check acknowledgements with; default: <log>.jwks.json"),
                head: str = typer.Option(None, "--head", help="the head you expect: the one you acknowledged, or the other side's")) -> None:
        """Read the log again from its first line: every hash, every id, every repeat, every acknowledgement. Says what was removed, reordered or edited. Exit 1 when anything is wrong."""
        if log.is_dir():
            said = check_export({p.relative_to(log).as_posix(): p.read_bytes() for p in sorted(log.rglob("*")) if p.is_file()})
            typer.echo("\n".join(said) if said else "The export checks: the log, its acknowledgements, the index and every statement are what the log gives.")
            raise typer.Exit(1 if said else 0)
        if not log.exists():
            raise stop(f"Cannot read {log}.")
        jwks = keys_of(log, keys)
        book, said = read(log.read_text(encoding="utf-8"), jwks, head)
        for s in said:
            typer.echo(s)
        if not said:
            acked = book.acknowledged()
            typer.echo(f"{len(book.events)} lines check. Head {book.head}")
            typer.echo("Acknowledged: " + (", ".join(f"GitHub id {p} up to line {n}" for p, n in sorted(acked.items())) if acked else "by nobody yet")
                       + ("" if jwks is not None or not acked else " (signatures NOT checked: no keys given)"))
        raise typer.Exit(1 if said else 0)

    @events.command("ack")
    def ack_(log: Path = typer.Argument(..., help="the log file"),
             party: int = typer.Option(None, "--as", help="your GitHub owner id: print the audience your run asks GitHub to sign"),
             token: Path = typer.Option(None, "--token", metavar="FILE", help="a token GitHub signed for that audience: check it and add the acknowledgement"),
             keys: Path = typer.Option(None, "--keys", help="GitHub's keys (a JWKS file); the ones the token used are kept in <log>.jwks.json")) -> None:
        """Acknowledge the log up to its head. With --as: print the audience to sign (`knosm:ack:<id>:<line>:<head>`). With --token: check the signature and the head, and append the acknowledgement. From then on that range changes only by a correction."""
        if token is None:
            book = opened(log, keys_of(log))
            if party is None or not book.events:
                raise stop("Give --as <your GitHub owner id> to print what to sign, or --token <file> to add a signed acknowledgement.", "An empty log has nothing to acknowledge.")
            typer.echo(ack_audience(party, len(book.events) - 1, book.head))
            return
        jwks = keys_of(log, keys)
        if jwks is None:
            raise stop("An acknowledgement is checked against the issuer's keys.", "Give --keys <a JWKS file>.")
        kept = keys_of(log) or {"keys": []}
        book = opened(log, {"keys": [*kept.get("keys", []), *jwks.get("keys", [])]})
        try:
            raw = token.read_text(encoding="ascii").strip()
            r = ingest(book, [acknowledgement(raw)], jwks)
        except (OSError, ValueError) as why:
            raise stop(f"{token}: {why}") from None
        if r.refused:
            raise stop(f"Not acknowledged: {r.refused[0]['why']}.")
        book.write(log)
        all_keys = {"keys": [*kept.get("keys", []), *jwks.get("keys", [])]}
        beside(log, "jwks.json").write_text(canon(keys_used(all_keys, [(book.events[n].ack or {})["token"] for n in book.acks])) + "\n", encoding="utf-8")
        a = acknowledgement(raw).ack or {}
        typer.echo(f"GitHub id {a['party']} acknowledged lines 0 to {a['upto']}." if r.added else "That acknowledgement is already in the log.")

    @events.command("dupes")
    def dupes_(log: Path = typer.Argument(..., help="the log file"), as_json: bool = typer.Option(False, "--json", help="print JSON")) -> None:
        """Every event that arrived more than once, with each source it came by and the line that counts; then what was refused."""
        book = opened(log, keys_of(log))
        refused = beside(log, "refused.jsonl").read_text(encoding="utf-8").splitlines() if beside(log, "refused.jsonl").exists() else []
        if as_json:
            say({"duplicates": book.dupes(), "refused": [json.loads(x) for x in refused], "across_periods": across(book)})
            return
        for d in book.dupes():
            typer.echo(f"{d['id']} ({d['kind'].replace('_', ' ')}) counted once, at line {d['counted_at']}: "
                       + "; ".join(f"{s['source']} {s['evidence']}".strip() for s in d["sources"]))
        typer.echo(f"{len(book.dupes())} events arrived more than once and were counted once. {len(refused)} arrivals were refused (see {beside(log, 'refused.jsonl').name})."
                   if refused else f"{len(book.dupes())} events arrived more than once and were counted once. Nothing was refused.")
        for a in across(book):
            typer.echo(f"{a['deliverable']} has {len(a['lines'])} counted {a['kind'].replace('_', ' ')}s, at lines {', '.join(str(x['line']) for x in a['lines'])} "
                       f"(months {', '.join(str(m) for m in a['months'])}): one deliverable is billed and paid once.")

    def last_of(given: list[str]) -> dict[str, int]:
        out = {}
        for text in given or []:
            got = sent_of("sent:" + text)
            if got is None:
                raise stop(f"--last is written <buyer>:<supplier>:<yyyymm>.<number>, not {text}.")
            out[got[0]] = got[1]
        return out

    @events.command("gaps")
    def gaps_(log: Path = typer.Argument(..., help="the log file"), month: str = typer.Option(None, "--month", help="one month only, YYYY-MM"),
              last: list[str] = typer.Option(None, "--last", metavar="BUYER:SUPPLIER:YYYYMM.N", help="the last number a sender says it sent (repeat for each stream)"),
              explain: str = typer.Option(None, "--explain", metavar="BUYER:SUPPLIER:YYYYMM.N", help="record why nothing was sent under this number (with --reason)"),
              reason: str = typer.Option("", "--reason", help="with --explain: why, in your words"),
              as_json: bool = typer.Option(False, "--json", help="print JSON")) -> None:
        """Name every number a sender gave that never arrived. A root commits to what was supplied; this is what says something was not. Exit 1 while a number is missing and no acknowledged correction explains it."""
        try:
            if explain is not None:
                got = sent_of("sent:" + explain)
                if got is None or not reason.strip():
                    raise stop("--explain is written <buyer>:<supplier>:<yyyymm>.<number> and needs --reason.")
                with locked(log):
                    book = opened(log, keys_of(log))
                    r = ingest(book, [gap_correction(got[0], got[1], reason.strip())])
                    book.write(log)
                if r.refused:
                    raise stop(f"Not recorded: {r.refused[0]['why']}.")
                typer.echo(f"Recorded at line {len(book.events) - 1}. It counts once a party acknowledges the head: `knos events ack`." if r.added
                           else "That explanation is already in the log.")
                return
            jwks = keys_of(log)
            found = gaps(opened(log, jwks), month or 0, last_of(last))
        except (Bad, Busy) as why:
            raise stop(str(why)) from None
        still = [g for g in found if g["state"] != "explained" or jwks is None]
        if as_json:
            say({"gaps": found, "signatures_checked": jwks is not None, "blocking": len(still)})
        else:
            for g in found:
                typer.echo(f"{g['stream']} number {g['number']}: " + ("missing, and nothing explains it" if g["state"] == "open" else
                           f"missing; line {g['line']} says why ({g['reason']}); " + ("acknowledged by GitHub id " + ", ".join(g["signed_by"]) if g["signed_by"]
                                                                                    else "nobody has acknowledged that line yet")))
            typer.echo(f"{len(found)} numbers never arrived; {len(still)} of them stop a close." if found else "No number is missing below the highest that arrived"
                       + (" or the last you gave." if last else ". A sender's last numbers are checked only with --last."))
        raise typer.Exit(1 if still else 0)

    @events.command("close")
    def close_(log: Path = typer.Argument(..., help="the log file"), month: str = typer.Option(..., "--month", help="YYYY-MM"),
               last: list[str] = typer.Option(None, "--last", metavar="BUYER:SUPPLIER:YYYYMM.N", help="the last number a sender says it sent"),
               ack: list[Path] = typer.Option(None, "--ack", help="a party's signed acknowledgement or closure of the month (`knos events sign`); repeat"),
               terms_file: list[Path] = typer.Option(None, "--terms", help="the Knos Terms 3 file that names the parties' keys; repeat")) -> None:
        """Say whether a month can be closed. Refused over a missing number unless an acknowledged correction explains it. With --ack and --terms, refused too unless both parties signed the month's last line, or one did and closed it after the silence the terms allow. Prints the statement's hash and the head both parties sign."""
        try:
            jwks = keys_of(log)
            book = opened(log, jwks)
            signed = [json.loads(p.read_text(encoding="utf-8")) for p in ack or []] if ack or terms_file else None
            docs = [json.loads(p.read_text(encoding="utf-8")) for p in terms_file or []]
            said = close_problems(book, month, last_of(last), jwks is not None, signed, docs)
            st = statement(book, month)
        except Bad as why:
            raise stop(str(why)) from None
        if said:
            raise stop(f"{month} is not closed. " + said[0] + (f" ({len(said) - 1} more: knos events gaps)" if len(said) > 1 else ""))
        typer.echo(f"{month} can be closed: no number is missing without an acknowledged reason. Statement {st['sha256']}, head {book.head}. "
                   "Each party signs the head: `knos events ack`.")

    @events.command("sign")
    def sign_(log: Path = typer.Argument(..., help="the log file"), month: str = typer.Option(..., "--month", help="YYYY-MM"),
              role: str = typer.Option(..., "--role", help="buyer or supplier: whose key signs"),
              key: Path = typer.Option(..., "--key", help="your Ed25519 key, the JSON list of 64 numbers solana-keygen writes; the terms name its public half"),
              terms_file: Path = typer.Option(..., "--terms", help="the Knos Terms 3 file that names both parties' keys"),
              on: str = typer.Option(..., "--on", help="the day you sign, YYYY-MM-DD"),
              closing: Path = typer.Option(None, "--closing", help="your own earlier acknowledgement: sign a closure of the month, which holds only after the silence the terms allow"),
              out: Path = typer.Option(None, "--out", help="write the signed file here and not to standard output")) -> None:
        """Sign a month of the log: its last line, that line's hash and the month's root, under the terms that name your key. Both parties' acknowledgements close the month; so does one party's closure after the days of silence the terms allow."""
        from . import period, terms3
        try:
            doc = json.loads(terms_file.read_text(encoding="utf-8"))
            rule = terms3.period_close(doc)
            if rule is None:
                raise Bad("these terms name no keys to close a month (`window.period_close`)")
            signer = period.load_key(key)
            if str(signer.pubkey()) != rule.get(f"{role}_key"):
                raise Bad(f"this key is {signer.pubkey()}; the terms name {rule.get(role + '_key')} for the {role}")
            if closing is not None:
                got = period.close_alone(signer, json.loads(closing.read_text(encoding="utf-8")), rule["silence_days"], on)
            else:
                got = period.acknowledge(signer, opened(log, keys_of(log)), month, role, terms3.digest(doc), on)
        except (Bad, ValueError, OSError) as why:
            raise stop(str(why)) from None
        text = period.dumps(got)
        if out:
            out.write_text(text, encoding="utf-8")
            typer.echo(f"wrote {out}: the {role} signed {got['month']} up to line {got['last']}", err=True)
        else:
            typer.echo(text, nl=False)

    @events.command("statement")
    def statement_(log: Path = typer.Argument(..., help="the log file"), month: str = typer.Option(..., "--month", help="YYYY-MM"),
                   supplier: str = typer.Option("", "--supplier", help="one supplier only")) -> None:
        """One month from the index, as JSON: evaluations by verdict, accepted deliverables, each invoice line as agreed, disputed, duplicate or insufficient evidence."""
        try:
            say(statement(opened(log, keys_of(log)), month, supplier))
        except Bad as why:
            raise stop(str(why)) from None

    @events.command("export")
    def export_(log: Path = typer.Argument(..., help="the log file"), to: Path = typer.Option(..., "--out", help="the folder to write")) -> None:
        """Write the evidence behind every conclusion: the log, the acknowledgements and their keys, the repeats, what was refused, the index and each month's statement, with a manifest of hashes. `knos events verify <folder>` rebuilds all of it from the log."""
        jwks = keys_of(log)
        book = opened(log, jwks)
        refused = beside(log, "refused.jsonl").read_text(encoding="utf-8") if beside(log, "refused.jsonl").exists() else ""
        files = export_files(book, jwks, refused)
        for name, raw in files.items():
            (to / name).parent.mkdir(parents=True, exist_ok=True)
            (to / name).write_bytes(raw)
        typer.echo(f"{len(files)} files in {to}. Head {book.head}")
