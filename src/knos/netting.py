"""Netted settlement of small tickets: many accepted outcomes, one release, no program change.

A 0.32 agent call cannot carry a fee floor of 0.05 and several transactions of its own, and the escrow takes no
order under 5.00. So small outcomes accumulate off chain and one release per payee per period pays their sum.

    book        a file of JSON Lines both sides keep, each from what it received: a period's header (buyer, seller,
                month, seq, cap, unit), then one line per accepted outcome (a knos.ledger evaluation line with its
                evidence id), dispute lines, and the period's closing line. `read` recomputes; nothing is trusted.
    open        a netting period between one buyer and one supplier, with a cap on what it may come to.
    add         accepted outcomes, each under SMALL (20.00) and each with its evidence id. An outcome is one
                deliverable: an order and a milestone, accepted once. Refused: a deliverable or an evidence id any
                period of the book already holds, a deliverable the events log already counts as accepted by another
                mode, and an outcome that would take the period past its cap.
    dispute     takes one line out of the net. It stays in the batch, as `disputed`, with a value of nothing; every
                other line stays payable.
    close       the period as a format 2 meter batch (knos.ledger: every field of every line is under the root), the
                net, the fee, and the terms of the one release. Given the other side's book, the two must come to the
                same root, or the lines that differ are named and nothing closes.
    release     what the one order is funded and paid on: its terms carry the root, the three numbers and the pair, so
                the hash the program stores at funding commits to the batch; the pay token names the same hash.
    reserve     money the buyer locked BEFORE the work: a standing order of knos_pay funded on terms that name the
                pair (`reserve_fund`). A period bound to it (`open --reserve ORDER`) is refused any line past what the
                order holds, and is paid at close by draws of one tranche each (`draws`), never by a new funding.
                What no draw takes goes back to the buyer by RefundOrder after the order's deadline (REFUND).
    exposure    what the supplier has delivered with no locked money behind it: nothing for a reserved period, the
                whole value of an unsecured one until the supplier writes it `settled`. `open --max-exposure` bounds
                it over the whole book, and `add` refuses the line that would pass it.

What the chain enforces and what it does not is ENFORCED below and docs/NETTING.md, word for word.

Standard library only at import; the fee is knos.settle.v2.pay's own function, asked for when a fee is computed.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterable

from . import ledger
from .ledger import Bad, Evaluation, canon

VERSION = 1
MICRO = 1_000_000
SMALL = 20 * MICRO              # the price book's Acceptance line: an outcome under 20.00 is netted
ORDER_MIN = 5 * MICRO           # the least amount knos_pay takes for an order (pay.ORDER_MIN_AMOUNT)
JOB_MIN = 1 * MICRO             # the least amount it takes for a job (pay.MIN_AMOUNT): nothing smaller is paid singly at all
MAX_CAP = 100_000 * MICRO       # the largest order (pay.MAX_AMOUNT)
MODE = 0                        # the on-chain mode of the release: the pay token of the order's own repository
REFUND = ("RefundOrder (knos_pay instruction 22). Anyone may send it once the reserve order's deadline has passed; it pays everything the order still "
          "holds, with the fee's unspent share, only to where the money came from: the buyer's Balance, or the wallet that funded it. Before the "
          "deadline nothing returns it: the buyer's Cancel (instruction 21) only moves the deadline to 7 days from the notice, and draws still pay "
          "until then. A standing order left with less than one tranche can be refunded at once.")
NOT_LOCKED = ("A Balance is not a reserve: the wallet that opened it can withdraw from it (Withdraw, instruction 2) until an order is funded, so money "
              "in a Balance covers nothing a supplier has delivered.")
ENFORCED = (
    ("on chain", "the cap: the buyer's Balance refuses an order above the cap its wallet set (knos_pay, error 93)"),
    ("on chain", "the release: one order of exactly the net, its fee on top, paid only by a token that names the order, the terms hash fixed at funding "
                 "and the supplier"),
    ("on chain", "the root: knos_meter keeps the buyer's batch and the supplier's claim in two accounts; the same running hash in both means the same root"),
    ("on chain", "the fee: 0.30% of the net, at least 0.05, once, taken when the order is funded"),
    ("off chain", "each line: committed by the batch root, not escrowed one by one; no program reads a line"),
    ("off chain", "the link from the release to the batch: the terms name the root and the program stores their hash; a reader compares, the program does not"),
    ("off chain", "that the buyer funds the release of an unsecured period: until it does, the supplier carries the buyer's credit risk, up to the "
                  "period's exposure limit"),
    ("on chain", "a reserve: a standing order holds the money in its own account from before the work; nobody withdraws it, and only a pay token of "
                 "the judge the order pins moves it to a payee, one tranche a token, each pull request number once"),
    ("on chain", "what a reserve does not pay: RefundOrder returns it to where it came from, to nobody else, and only after the order's deadline"),
    ("off chain", "that a draw is signed: the order pins its judge, and a buyer whose own repository is that judge can withhold the token; the money "
                  "then goes back to the buyer at the deadline"),
    ("off chain", "the link from a draw to the batch: the pay token names the first 40 hex characters of the root where a commit goes; the program "
                  "does not read it"),
    ("off chain", "duplicates: refused by this book and by the events log both sides acknowledge, not by a program"),
)


# -- amounts ----------------------------------------------------------------------------------------------------------
def units(text: str | int) -> int:
    """"0.32" -> 320000: an amount in millionths of one whole unit. A whole number is taken as millionths already."""
    if isinstance(text, int) and not isinstance(text, bool):
        return ledger._int(text, "amount")
    try:
        v = Decimal(str(text)) * MICRO
    except InvalidOperation:
        raise Bad(f"an amount is written like 0.32, not {text!r}") from None
    if v != v.to_integral_value() or v < 0:
        raise Bad(f"an amount has at most six decimals and is not negative, not {text!r}")
    return int(v)


def fee_of(amount: int, bps: int | None = None) -> int:
    """The fee of one release of `amount`, exactly as knos_pay computes an order's: 0.30% rounded down, at least 0.05."""
    from .settle.v2 import pay
    return pay.order_fee(amount, pay.FEE_BPS if bps is None else bps)


# -- a book -----------------------------------------------------------------------------------------------------------
@dataclass
class Period:
    terms: dict                                             # buyer, cap, month, seller, seq, unit
    evals: list[Evaluation] = field(default_factory=list)   # as added: every one accepted
    disputes: dict[str, str] = field(default_factory=dict)  # evidence id -> why
    closed: dict | None = None
    value: int = 0                                          # what the lines not disputed add up to
    settled: str = ""                                       # what paid it, as the book's keeper wrote it; "": not written as paid
    written: list[str] = field(default_factory=list)        # its outcome and dispute lines in the order they were written: a line added
                                                            # after a dispute fits only because of it, so the book is written again in that order

    @property
    def reserve(self) -> dict | None:
        return self.terms.get("reserve")

    @property
    def exposure(self) -> int:
        """Delivered and accepted with no locked money behind it: nothing with a reserve, the value until it is settled without one."""
        return 0 if self.reserve is not None or self.settled else self.value

    @property
    def name(self) -> str:
        return f"{self.terms['month']}.{self.terms['seq']}"

    def lines(self) -> list[Evaluation]:
        """The period's lines as its batch holds them: a disputed line says so and counts for nothing."""
        return [Evaluation(e.buyer, e.seller, e.order, e.artifact, e.policy, e.milestone, False, e.rate, "disputed", currency=e.currency, evidence=e.evidence)
                if e.evidence in self.disputes else e for e in self.evals]


@dataclass
class Book:
    periods: list[Period] = field(default_factory=list)
    by_id: dict[str, str] = field(default_factory=dict)         # deliverable (order and milestone) -> its period, over every period
    by_evidence: dict[str, str] = field(default_factory=dict)   # evidence id -> its period

    @property
    def open(self) -> Period | None:
        return self.periods[-1] if self.periods and self.periods[-1].closed is None else None


_TERMS = {"buyer", "cap", "month", "seller", "seq", "unit"}
_OPTIONAL = {"max_exposure", "reserve"}                     # a header without them is a period of version 1: unsecured, bounded by its cap alone
_RESERVE = {"brought", "deadline", "funded", "order", "tranche"}
_CLOSED = {"accepted", "count", "disputed", "fee", "root", "value"}


def _period(o: object) -> dict:
    if not isinstance(o, dict) or set(o) - _OPTIONAL != _TERMS or not isinstance(o["unit"], str) or not ledger._CURRENCY.fullmatch(o["unit"]) or not o["unit"]:
        raise Bad("a period has buyer, seller, month, seq, cap and unit")
    ledger._int(o["buyer"], "buyer", least=1), ledger._int(o["seller"], "seller", least=1), ledger._int(o["seq"], "seq")
    ledger.month_of(ledger._int(o["month"], "month"))
    if not ORDER_MIN <= ledger._int(o["cap"], "cap") <= MAX_CAP:
        raise Bad("a period's cap is between 5.00 and 100,000.00: one release is one order, and those are an order's bounds")
    if "reserve" in o and "max_exposure" in o:
        raise Bad("a period has a reserve or an exposure limit, not both: a reserved period exposes the supplier to nothing")
    if "max_exposure" in o:
        ledger._int(o["max_exposure"], "max_exposure")
    if "reserve" in o:
        r = o["reserve"]
        if not isinstance(r, dict) or set(r) - {"period"} != _RESERVE or not isinstance(r["order"], str) or not 32 <= len(r["order"]) <= 44:
            raise Bad("a reserve names its order and what it holds: order, funded, tranche, deadline, brought")
        if "period" in r and ledger.month_of(ledger._int(r["period"], "period")) != o["month"]:
            raise Bad(f"the reserve was locked for period {r['period']}, and this period is {o['month']}: its terms name the month it secures")
        ledger._int(r["deadline"], "deadline", least=1)
        if not 1 <= ledger._int(r["tranche"], "tranche") <= ledger._int(r["funded"], "funded") <= MAX_CAP:
            raise Bad("a reserve holds at least one tranche and at most 100,000.00")
        if not ledger._int(r["brought"], "brought") < r["tranche"]:
            raise Bad("what a reserve brings forward from the period before is under one tranche")
    return o


def carried(book: Book, order: str) -> int:
    """What the last closed period bound to this reserve order accepted and no draw of its own paid: under one
    tranche, and the first thing the next period bound to the same order draws."""
    for p in reversed(book.periods):
        if p.reserve is not None and p.reserve["order"] == order:
            return reserve_state(p).get("undrawn", 0)
    return 0


def reserve_state(p: Period) -> dict:
    """The reserve of a period as its lines leave it. Always: funded = brought + consumed + free. Once closed: what the
    period draws (whole tranches of brought + consumed) and what it leaves for the next period bound to the same order."""
    r = p.reserve
    if r is None:
        raise Bad(f"period {p.name} has no reserve")
    out = {"order": r["order"], "funded": r["funded"], "brought": r["brought"], "consumed": p.value, "free": r["funded"] - r["brought"] - p.value,
           "tranche": r["tranche"], "deadline": r["deadline"]}
    if p.closed is not None:
        k = (r["brought"] + p.value) // r["tranche"]
        out.update(draws=k, drawn=k * r["tranche"], undrawn=r["brought"] + p.value - k * r["tranche"])
    return out


def exposure(book: Book) -> int:
    """What the supplier carries over the whole book: the value of every unsecured period nobody wrote as settled."""
    return sum(p.exposure for p in book.periods)


def read(text: str) -> Book:
    """The book in `text`, checked line by line as `add`, `dispute` and `close` would have written it. A closing line
    that is not what its period's lines come to is refused: the lines say the net, never the summary."""
    book = Book()
    for n, raw in enumerate(text.splitlines(), 1):
        if not raw.strip():
            continue
        try:
            o = json.loads(raw)
            if not isinstance(o, dict):
                raise Bad("not an object")
            if "period" in o:
                if book.open is not None:
                    raise Bad(f"period {book.open.name} is still open")
                t = _period(o["period"])
                if book.periods and (t["buyer"], t["seller"], t["unit"]) != tuple(book.periods[0].terms[k] for k in ("buyer", "seller", "unit")):
                    raise Bad("a book is one buyer, one supplier and one unit")
                if any(p.name == f"{t['month']}.{t['seq']}" for p in book.periods):
                    raise Bad(f"period {t['month']}.{t['seq']} is in this book already")
                if "reserve" in t and t["reserve"]["brought"] != carried(book, t["reserve"]["order"]):
                    raise Bad(f"the reserve brings forward {ledger.usd(t['reserve']['brought'])}, and the periods before it left "
                              f"{ledger.usd(carried(book, t['reserve']['order']))} undrawn on that order")
                book.periods.append(Period(t))
                continue
            if "settled" in o:
                _settle(book, o["settled"])
                continue
            p = book.open
            if p is None:
                raise Bad("no period is open")
            if "dispute" in o:
                d = o["dispute"]
                if not isinstance(d, dict) or set(d) != {"evidence", "reason"} or not isinstance(d["reason"], str) or len(d["reason"]) > 200:
                    raise Bad("a dispute names an evidence id and a reason of at most 200 characters")
                _dispute(p, d["evidence"], d["reason"])
            elif "closed" in o:
                c = o["closed"]
                if not isinstance(c, dict) or set(c) != _CLOSED or c != closing(net_of(p)):
                    raise Bad(f"the closing line of period {p.name} is not what its lines come to")
                p.closed = c
            else:
                _add(book, p, ledger.parse(o))
        except ValueError as why:       # Bad is one
            raise Bad(f"line {n}: {why}") from None
    return book


def _settle(book: Book, s: object) -> None:
    if not isinstance(s, dict) or set(s) != {"by", "period"} or not isinstance(s["by"], str) or not 0 < len(s["by"]) <= 100:
        raise Bad("a settled line names a period and what paid it: an order's address or a transaction, at most 100 characters")
    p = next((x for x in book.periods if x.name == s["period"]), None)
    if p is None or p.closed is None:
        raise Bad(f"only a closed period is settled, and this book has no closed period {s['period']}")
    if p.settled:
        raise Bad(f"period {p.name} is settled already, by {p.settled}")
    p.settled = s["by"]


def _add(book: Book, p: Period, e: Evaluation) -> None:
    t = p.terms
    if (e.buyer, e.seller) != (t["buyer"], t["seller"]):
        raise Bad("the outcome names another buyer or supplier than this book's")
    if not e.accepted or e.verdict != "accepted":
        raise Bad("only an accepted outcome is added: a refusal moves no money and needs no netting")
    if not e.evidence:
        raise Bad("an outcome carries its evidence id: sha256 of the signed token or receipt it rests on, 64 hex characters")
    if not 0 < e.rate < SMALL:
        raise Bad(f"an outcome of {ledger.usd(e.rate)} is not netted: netting is for amounts above 0 and under {ledger.usd(SMALL)}; fund an order for it")
    if e.currency != t["unit"]:
        raise Bad(f"the outcome is in {e.currency or 'no stated unit'}; this book counts {t['unit']}")
    if e.deliverable in book.by_id:
        raise Bad(f"duplicate: this order and milestone was accepted in period {book.by_id[e.deliverable]} already, and an accepted deliverable is counted once")
    if e.evidence in book.by_evidence:
        raise Bad(f"duplicate: evidence {e.evidence[:16]}... already carries a line of period {book.by_evidence[e.evidence]}")
    if p.value + e.rate > t["cap"]:
        raise Bad(f"over the cap: period {p.name} holds {ledger.usd(p.value)} of {ledger.usd(t['cap'])}; close it and open the next")
    r = p.reserve
    if r is not None and r["brought"] + p.value + e.rate > r["funded"]:
        raise Bad(f"past the reserve: period {p.name} has consumed {ledger.usd(p.value)}" + (f" and brought {ledger.usd(r['brought'])} forward" if r["brought"] else "")
                  + f" of the {ledger.usd(r['funded'])} its order holds, and {ledger.usd(r['funded'] - r['brought'] - p.value)} is free; close it and open the "
                    "next on a reserve that holds more")
    if r is None and "max_exposure" in t and exposure(book) + e.rate > t["max_exposure"]:
        raise Bad(f"past the exposure limit: the supplier already carries {ledger.usd(exposure(book))} with no money locked behind it, and this period "
                  f"allows {ledger.usd(t['max_exposure'])}; the buyer funds what is closed, or the next period is opened on a reserve")
    p.evals.append(e)
    p.written.append(e.line())
    p.value += e.rate
    book.by_id[e.deliverable], book.by_evidence[e.evidence] = p.name, p.name


def _dispute(p: Period, evidence: str, reason: str) -> None:
    line = next((e for e in p.evals if e.evidence == evidence), None)
    if line is None:
        raise Bad(f"no line of the open period {p.name} rests on evidence {str(evidence)[:16]}...; a closed period is corrected through `knos meter`, not here")
    if evidence in p.disputes:
        raise Bad("that line is disputed already")
    p.disputes[evidence] = reason
    p.written.append(canon({"dispute": {"evidence": evidence, "reason": reason}}))
    p.value -= line.rate


def outcome(t: dict, order: str, artifact: str, policy: str, amount: str | int, evidence: str, milestone: int = 0) -> Evaluation:
    """One accepted outcome of a period with terms `t`, as the line the book and the batch hold."""
    return Evaluation(t["buyer"], t["seller"], order, artifact, policy, milestone, True, units(amount), "accepted", currency=t["unit"], evidence=evidence)


def open_line(book: Book, buyer: int, seller: int, month: int | str, cap: str | int, unit: str = "USDC", seq: int | None = None,
              reserve: dict | None = None, max_exposure: str | int | None = None) -> str:
    """The header of the next period. `seq`: the batch number of the pair's month on knos_meter, from 0 and in order;
    by default the next one this book has not used (name it when the pair also batches that month by other means).
    `reserve`: what `reserve_of` read of the order that secures the period (order, funded, tranche, deadline).
    `max_exposure`: without a reserve, the most the supplier may carry over the whole book with no money locked."""
    m = ledger.month_of(month)
    if seq is None:
        seq = 1 + max((p.terms["seq"] for p in book.periods if p.terms["month"] == m), default=-1)
    t: dict = {"buyer": buyer, "cap": units(cap), "month": m, "seller": seller, "seq": seq, "unit": unit}
    if reserve is not None:
        t["reserve"] = {**{k: reserve[k] for k in ("order", "funded", "tranche", "deadline", "period") if k in reserve}, "brought": carried(book, reserve["order"])}
    if max_exposure is not None:
        t["max_exposure"] = units(max_exposure)
    line = canon({"period": t})
    read(text_of(book) + line + "\n")
    return line


def text_of(book: Book) -> str:
    out: list[str] = []
    for p in book.periods:
        out.append(canon({"period": p.terms}))
        out += p.written
        if p.closed is not None:
            out.append(canon({"closed": p.closed}))
        if p.settled:
            out.append(canon({"settled": {"by": p.settled, "period": p.name}}))
    return "".join(line + "\n" for line in out)


def add(book: Book, outcomes: Iterable[Evaluation | dict | str], counted: Iterable[str] = ()) -> tuple[list[str], list[dict]]:
    """Adds outcomes to the open period. Returns (the lines to append, the refusals as {"evidence", "why"}). One bad
    outcome refuses itself only. `counted`: ids the events log holds (its acceptances, acc_): what another mode already counted."""
    p = book.open
    if p is None:
        raise Bad("no period is open: `knos net open` first")
    known, lines, refused = set(counted), [], []
    for item in outcomes:
        try:
            e = item if isinstance(item, Evaluation) else _from(p.terms, item)
            if _acc(e) in known:
                raise Bad("duplicate: the events log already counts this order and milestone as accepted, by another mode")
            _add(book, p, e)
            lines.append(e.line())
        except ValueError as why:
            ev = item.evidence if isinstance(item, Evaluation) else (item.get("evidence", "") if isinstance(item, dict) else "")
            refused.append({"evidence": ev, "why": str(why)})
    return lines, refused


def _from(t: dict, item: dict | str) -> Evaluation:
    o = json.loads(item) if isinstance(item, str) else item
    if isinstance(o, dict) and "amount" in o:
        if set(o) - {"milestone"} != {"amount", "artifact", "evidence", "order", "policy"}:
            raise Bad("an outcome has order, artifact, policy, amount and evidence, and a milestone when it is not 0")
        return outcome(t, o["order"], o["artifact"], o["policy"], o["amount"], o["evidence"], o.get("milestone", 0))
    return ledger.parse(o)


def _evl(e: Evaluation) -> str:
    """The id the events log gives this outcome's evaluation, whichever mode recorded it (knos.events.from_evaluation)."""
    from . import events, ids
    return ids.evaluation(ids.deliverable(e.order, e.milestone), e.artifact, e.policy, events.METER_EVALUATOR, 0)


def _acc(e: Evaluation) -> str:
    """The id the events log gives the acceptance of this outcome's deliverable."""
    from . import events, ids
    return events.acceptance(ids.deliverable(e.order, e.milestone), "import").id


def settled_line(book: Book, period: str, by: str) -> str:
    """The line that says a closed period was paid, and by what. The keeper of a book writes it on seeing the money:
    it ends that period's part of the supplier's exposure in this book, and nothing checks it but `reserve_check`
    and the chain itself."""
    s = {"by": by, "period": period}
    _settle(book, s)
    return canon({"settled": s})


def dispute_line(book: Book, evidence: str, reason: str = "") -> str:
    p = book.open
    if p is None:
        raise Bad("no period is open; a closed period is corrected through `knos meter`, not here")
    _dispute(p, evidence, reason)
    return canon({"dispute": {"evidence": evidence, "reason": reason}})


# -- the net ----------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Net:
    """What one period comes to. `value` is what the supplier is paid; the funder pays `value + fee`."""
    buyer: int
    seller: int
    month: int
    seq: int
    cap: int
    unit: str
    count: int
    accepted: int
    disputed: int
    value: int
    fee: int
    root: bytes
    batch: ledger.Batch | None = field(default=None, compare=False, repr=False)

    def json(self) -> dict:
        return {"accepted": self.accepted, "buyer": self.buyer, "cap": self.cap, "count": self.count, "disputed": self.disputed, "fee": self.fee,
                "month": self.month, "root": self.root.hex(), "seller": self.seller, "seq": self.seq, "total": self.value + self.fee, "unit": self.unit,
                "value": self.value}


def net_of(p: Period) -> Net:
    """The net of a period from its lines alone: both sides run this on their own copy and must get the same root."""
    t = p.terms
    if not p.evals:
        raise Bad(f"period {p.name} holds no outcome")
    b = ledger.batch(p.lines(), t["seq"], t["month"], format=2)
    return Net(t["buyer"], t["seller"], t["month"], t["seq"], t["cap"], t["unit"], b.count, b.accepted, len(p.disputes), b.value,
               fee_of(b.value) if b.value else 0, b.root, b)


def closing(n: Net) -> dict:
    return {"accepted": n.accepted, "count": n.count, "disputed": n.disputed, "fee": n.fee, "root": n.root.hex(), "value": n.value}


def differences(mine: Period, theirs: Period) -> list[str]:
    """Why two copies of one period do not come to the same root, one line each."""
    out = [f"{k}: {mine.terms.get(k)} here, {theirs.terms.get(k)} there" for k in sorted(_TERMS | _OPTIONAL) if mine.terms.get(k) != theirs.terms.get(k)]
    a, b = {e.id: e for e in mine.lines()}, {e.id: e for e in theirs.lines()}
    out += [f"outcome {i.hex()[:16]}... (evidence {a[i].evidence[:16]}...) is here and not there" for i in sorted(set(a) - set(b))]
    out += [f"outcome {i.hex()[:16]}... (evidence {b[i].evidence[:16]}...) is there and not here" for i in sorted(set(b) - set(a))]
    out += [f"outcome {i.hex()[:16]}... differs: {a[i].stands} {ledger.usd(a[i].rate)} here, {b[i].stands} {ledger.usd(b[i].rate)} there"
            for i in sorted(set(a) & set(b)) if a[i] != b[i]]
    return out


def close(book: Book, other: Book | None = None) -> tuple[Net, str]:
    """Closes the open period: (its net, the closing line to append). `other`: the other side's book; its copy of the
    period must come to the same root and name the same reserve. An unsecured net under 5.00 is not closed: the escrow
    takes no order that small, so the period stays open until it holds more. A reserved period needs no new order."""
    p = book.open
    if p is None:
        raise Bad("no period is open")
    n = net_of(p)
    if other is not None:
        q = next((x for x in other.periods if x.name == p.name), None)
        if q is None:
            raise Bad(f"the other book has no period {p.name}")
        if net_of(q).root != n.root:
            raise Bad(f"the two books do not agree on period {p.name}: " + "; ".join(differences(p, q)[:5]))
        if p.reserve != q.reserve:
            raise Bad(f"the two books do not agree on what secures period {p.name}: reserve {p.reserve} here, {q.reserve} there")
    if p.reserve is None and n.value < ORDER_MIN:
        raise Bad(f"period {p.name} nets {ledger.usd(n.value)}: under {ledger.usd(ORDER_MIN)}, the least one release takes. Leave it open until it holds more.")
    return n, canon({"closed": closing(n)})


def ledger_text(n: Net, before: str = "") -> str:
    """The period as a meter ledger file: what `knos meter verify`, `prove` and `reconcile` read, and what attest.yml
    anchors. A period is batch `seq` of the pair's month on knos_meter, and a ledger file holds a month's batches from
    0 on (the running hash on chain goes through each of them): `before` is the pair's ledger file so far, and the
    period is appended to it. Refused, and nothing written, when the result is not a ledger the meter takes: the
    period of seq 1 with no batch 0 before it, a batch of another pair, a period the file holds already."""
    if n.batch is None:
        raise Bad("this net has no batch")
    head = before if not before or before.endswith("\n") else before + "\n"
    text = head + ledger.dump([n.batch])
    try:
        stored = ledger.load(text)
    except Bad as why:
        raise Bad(f"the ledger file given is not one the meter reads: {why}") from None
    other = [s for s in stored if (s.declared["buyer"], s.declared["seller"]) != (n.buyer, n.seller)]
    bad = ([f"the ledger file given is of buyer {other[0].declared['buyer']} and seller {other[0].declared['seller']}, this period's pair is "
            f"{n.buyer} and {n.seller}"] if other else []) or ledger.verify(stored)
    if bad:
        said = f"period {n.month}.{n.seq} cannot be written as a meter ledger: {bad[0]}"
        if n.seq:
            held = sorted(s.seq for s in stored[:-1] if s.month == n.month)
            said += (f". It is batch {n.seq} of the pair's month, so the file must hold batches 0 to {n.seq - 1} of {n.month} before it "
                    + (f"(the file given holds {held})" if before else "(no file was given)")
                    + ": give the pair's ledger file with --ledger, and the period is appended to it")
        raise Bad(said)
    return text


def audiences(n: Net) -> dict:
    """What each side asks its forge to sign to anchor the period on knos_meter: the buyer's batch, the supplier's claim."""
    if n.batch is None:
        raise Bad("this net has no batch")
    return {"buyer": ledger.batch_audience(n.batch), "seller": ledger.batch_audience(n.batch, claim=True)}


def anchored(n: Net, buyers, sellers, before: bytes = ledger.ZERO) -> list[str]:
    """What is wrong with the two knos_meter Ledger accounts of the pair's month as an anchor of this period (each a
    knos.settle.v2.meter.BatchLedger, or None when the account does not exist); empty when both hold this batch.
    `before`: the running hash before this batch (32 zero bytes for the month's first)."""
    if n.batch is None:
        raise Bad("this net has no batch")
    want = ledger.chain_hash(before, n.root, n.seq, n.count, n.accepted, n.value)
    out = []
    for who, got in (("buyer", buyers), ("supplier", sellers)):
        if got is None or got.next_seq <= n.seq:
            out.append(f"the {who} has not anchored period {n.month}.{n.seq}")
        elif got.next_seq == n.seq + 1 and bytes(got.chain) != want:
            out.append(f"the {who} anchored another root for period {n.month}.{n.seq}")
    return out


# -- the one release --------------------------------------------------------------------------------------------------
def terms(n: Net) -> dict:
    """The terms of the release. Their canonical JSON is hashed at funding (pay.terms_json, pay.terms_hash), so the
    order commits to the root, the three numbers, the pair and the period."""
    return {"accept": n.root.hex(), "checks": [], "mode": "net", "v": 2,
            "net": {"accepted": n.accepted, "buyer": n.buyer, "count": n.count, "month": n.month, "seller": n.seller, "seq": n.seq, "value": n.value}}


def head(n: Net) -> str:
    """What the pay token names where a pull request's head commit goes: the first 40 hex characters of the root."""
    return n.root.hex()[:40]


def number(n: Net) -> int:
    """What the pay token names where a pull request's number goes: the period, as yyyymm then seq in four digits."""
    return n.month * 10_000 + n.seq


def release(n: Net, balance, issue: int, order=None, wallet=None, work_s: int = 14 * 86_400) -> dict:
    """The release in full: amount, fee, terms, and the two audiences the buyer's pinned workflows ask the forge to
    sign. `balance`: the buyer's Balance (its cap is the period's). `order`: the order's address, once funded;
    `wallet`: the supplier's address when the token names one (else the wallet the supplier bound)."""
    from .settle.v2 import pay
    raw = pay.terms_json(terms(n))
    th = pay.terms_hash(raw)
    out = {"amount": n.value, "fee": n.fee, "total": n.value + n.fee, "terms": raw.decode(), "terms_hash": th.hex(), "mode": MODE,
           "fund_audience": pay.order_fund_audience(issue, n.value, MODE, th, balance, work_s)}
    if order is not None:
        out["pay_audience"] = pay.order_pay_audience(order, head(n), th, MODE, number(n), [(n.seller, 10_000, wallet)])
    return out


# -- the reserve on chain -----------------------------------------------------------------------------------------------
def reserve_terms(buyer: int, seller: int, unit: str = "USDC", period: int | str | None = None) -> dict:
    """The terms a reserve order is funded on. The program stores their hash, so the order names its pair on chain:
    `reserve_of` refuses an order funded on any other terms. `period` (YYYYMM): the one month the reserve secures,
    also under the hash; without it the reserve secures any period of the pair until its deadline."""
    net: dict = {"buyer": buyer, "seller": seller, "unit": unit, **({"period": ledger.month_of(period)} if period is not None else {})}
    return {"accept": "", "checks": [], "mode": "net-reserve", "v": 2, "net": net}


def reserve_hash(buyer: int, seller: int, unit: str = "USDC", period: int | str | None = None) -> bytes:
    from .settle.v2 import pay
    return pay.terms_hash(pay.terms_json(reserve_terms(buyer, seller, unit, period)))


def reserve_fund(buyer: int, seller: int, funded: str | int, tranche: str | int, balance, issue: int, work_s: int = 90 * 86_400, unit: str = "USDC",
                 seq: int = 0, period: int | str | None = None) -> dict:
    """What the buyer's pinned fund.yml asks the forge to sign to lock a reserve: a standing order of `funded`, paid one
    `tranche` a draw, from the buyer's Balance. `work_s`: how long it stays locked, at most 90 days (the program's
    bound); after that RefundOrder returns what no draw took. The fee is the escrow's, taken on top at funding.
    `period` (YYYYMM): the month it secures, named in the terms (`reserve_terms`)."""
    from .settle.v2 import pay
    amount, rate = units(funded), units(tranche)
    if not ORDER_MIN <= amount <= MAX_CAP or not 1 <= rate <= amount:
        raise Bad("a reserve is between 5.00 and 100,000.00 (one order), and its tranche is no more than it")
    if not pay.MIN_WORK <= work_s <= pay.MAX_WORK:
        raise Bad("a reserve is locked for at most 90 days: an order's longest deadline")
    raw = pay.terms_json(reserve_terms(buyer, seller, unit, period))
    options = pay.opts(pay.F_STANDING, rate=rate)
    return {"amount": amount, "tranche": rate, "fee": fee_of(amount), "total": amount + fee_of(amount), "terms": raw.decode(),
            "terms_hash": pay.terms_hash(raw).hex(), "mode": MODE, "options": options.hex(), "work_s": work_s, "seq": seq,
            **({"period": ledger.month_of(period)} if period is not None else {}),
            "fund_audience": pay.order_fund_audience(issue, amount, MODE, pay.terms_hash(raw), balance, work_s, seq, options)}


def reserve_of(o, address, buyer: int, seller: int, now: int, unit: str = "USDC", month: int | str | None = None) -> dict:
    """What the order at `address` (a knos.settle.v2.pay.Order as read now, or None) is as a reserve of this pair, as
    `open_line` takes it; Bad, in words, when it secures nothing. `month`: the period it is to secure; a reserve whose
    terms name a month (`/knos reserve ... period YYYY-MM`) secures that month and no other."""
    from .settle.v2 import pay
    if o is None:
        raise Bad(f"there is no order at {address}: it was paid out, refunded, or never funded. " + NOT_LOCKED)
    if o.state != "open" or not o.flags & pay.F_STANDING or o.holdback_bps:
        raise Bad("a reserve is an open standing order with no holdback: it pays one tranche for each signed draw and keeps the rest locked")
    m = ledger.month_of(month) if month is not None else None
    period = m if m is not None and o.terms == reserve_hash(buyer, seller, unit, m) else None
    if period is None and o.terms != reserve_hash(buyer, seller, unit):
        raise Bad(f"the order at {address} was not funded on the reserve terms of buyer {buyer} and supplier {seller} in {unit}"
                  + (f" for period {m}" if m is not None else "") + ": it secures another pair, another month, or other work")
    if o.from_balance and o.owner_id != buyer:
        raise Bad(f"the order at {address} was funded from a Balance of GitHub owner {o.owner_id}, not of the buyer {buyer}")
    if now > o.deadline or o.amount - o.paid < o.rate:
        raise Bad(f"the order at {address} is past its deadline or holds less than one tranche: RefundOrder returns it to its funder")
    return {"order": str(address), "funded": o.amount - o.paid, "tranche": o.rate, "deadline": o.pay_until, "notice": bool(o.cancel_at),
            "judges": "the order's own repository" + (", or a neutral run" if o.flags & pay.F_NEUTRAL else "") + (", or its judge repository" if o.judge_repo_id else ""),
            "returns_to": str(o.refund_to), **({"period": period} if period is not None else {})}


def reserve_check(p: Period, o, now: int) -> list[str]:
    """What is wrong with the reserve of period `p` as the chain has it now (`o`: its order as read, or None); empty when
    the order still stands behind everything the period has consumed and not yet drawn."""
    s = reserve_state(p)
    if p.settled:
        return []
    if o is None:
        return [f"the reserve order {s['order']} is gone: paid out or refunded"]
    owed = s["drawn"] if p.closed is not None else s["brought"] + s["consumed"]
    out = []
    if o.rate != s["tranche"]:
        out.append(f"the order's tranche is {ledger.usd(o.rate)}, the book says {ledger.usd(s['tranche'])}")
    if o.amount - o.paid < owed:
        out.append(f"the order holds {ledger.usd(o.amount - o.paid)} and the period is owed {ledger.usd(owed)} from it")
    if now > o.deadline:
        out.append("the order is past its deadline: anyone can send RefundOrder and the buyer has it back")
    elif o.cancel_at:
        out.append(f"the buyer gave notice (Cancel): draws pay until {o.deadline} and not after")
    elif o.pay_until != s["deadline"]:
        out.append(f"the order's deadline is {o.pay_until}, the book says {s['deadline']}")
    return out


def draw_number(n: Net, k: int) -> int:
    """What draw `k` (from 1) of a period names where a pull request's number goes: the period, then the draw in four
    digits. A standing order pays a number once, so no draw of any period is paid twice."""
    if not 1 <= k < 10_000:
        raise Bad("a period draws its reserve at most 9,999 times: choose a larger tranche")
    return number(n) * 10_000 + k


def draws(p: Period, wallet=None) -> list[dict]:
    """The release of a closed, reserved period: one pay audience for each whole tranche of what it brought forward and
    accepted. Each is signed by the judge the reserve order pins and pays the supplier one tranche from the order.
    `wallet`: the supplier's address when the token names one (else the wallet the supplier bound: a standing order
    never waits for a wallet)."""
    from solders.pubkey import Pubkey
    from .settle.v2 import pay
    if p.closed is None:
        raise Bad(f"period {p.name} is open: a reserve is drawn at close, when both books came to one root")
    s, n, t = reserve_state(p), net_of(p), p.terms
    th, order = reserve_hash(t["buyer"], t["seller"], t["unit"], p.reserve.get("period") if p.reserve else None), Pubkey.from_string(s["order"])
    return [{"draw": k, "pr": draw_number(n, k), "amount": s["tranche"],
             "pay_audience": pay.order_pay_audience(order, head(n), th, MODE, draw_number(n, k), [(n.seller, 10_000, wallet)])} for k in range(1, s["draws"] + 1)]


def compare(n: Net, single_txs: int = 0, netted_txs: int = 0) -> dict:
    """The period paid as one release against each accepted line paid on its own. A line under 1.00 cannot be paid on
    its own at all (the escrow's least job); `single_fees` is what the floor alone would take if it could.
    `single_txs`: transactions one single payment takes; `netted_txs`: what the whole period took."""
    b = n.batch
    rates = [e.rate for e in b.evals if e.accepted] if b is not None else []
    return {"lines": n.accepted, "net": n.value, "netted_fee": n.fee, "single_fees": sum(fee_of(r) for r in rates),
            "payable_singly": sum(1 for r in rates if r >= JOB_MIN), "netted_txs": netted_txs, "single_txs": single_txs * n.accepted}


def statement(book: Book) -> dict:
    """Every period of the book: its state, its numbers, and what is and is not enforced on chain."""
    periods = []
    for p in book.periods:
        row: dict = {"period": p.name, "state": "closed" if p.closed else "open", "cap": p.terms["cap"], "lines": len(p.evals), "disputed": sorted(p.disputes),
                     "value": p.value, "left_under_cap": p.terms["cap"] - p.value}
        if p.evals:
            n = net_of(p)
            row.update(root=n.root.hex(), fee=n.fee, total=n.value + n.fee, **({"audiences": audiences(n)} if p.closed else {}))
        row.update(secured="reserve" if p.reserve is not None else "unsecured", exposure=p.exposure, settled=p.settled)
        if p.reserve is not None:
            row["reserve"] = reserve_state(p)
        elif "max_exposure" in p.terms:
            row["max_exposure"] = p.terms["max_exposure"]
        periods.append(row)
    t = book.periods[0].terms if book.periods else {}
    total, last = exposure(book), {p.reserve["order"]: p for p in book.periods if p.reserve is not None}
    undrawn = sum(reserve_state(p).get("undrawn", 0) for p in last.values())
    said = (f"The supplier has delivered {ledger.usd(total)} {t.get('unit', '')} that no locked money covers: unsecured periods the buyer has not funded."
            if total else "Nothing delivered is uncovered: every period is reserved, settled or empty.")
    return {"type": "knos.netting", "v": VERSION, "buyer": t.get("buyer"), "seller": t.get("seller"), "unit": t.get("unit"), "periods": periods,
            "exposure": total, "exposure_says": said, "undrawn": undrawn,
            "undrawn_says": "Accepted, covered by a reserve and under one tranche: the next period bound to the same order draws it first. With no next "
                            "period before the order's deadline it goes back to the buyer.",
            "reserve_returns": REFUND, "not_a_reserve": NOT_LOCKED,
            "enforced": [{"where": w, "what": s} for w, s in ENFORCED]}


# -- files ------------------------------------------------------------------------------------------------------------
def load(path: Path) -> Book:
    return read(path.read_text(encoding="utf-8")) if path.exists() else Book()


def _append(path: Path, lines: Iterable[str]) -> None:
    with open(path, "a", encoding="utf-8", newline="\n") as f:
        f.writelines(line + "\n" for line in lines)


def _mirror(log: Path | None, events_) -> None:
    """The book's lines into the events log, when one is named: where every recording mode's records meet."""
    from . import events
    events.keep(events.where(log), events_)


def register(app, help_lines: list | None = None) -> None:
    """`knos net open | add | dispute | close | statement`, on the main app. `help_lines`: cli._HELP."""
    import importlib
    typer = importlib.import_module("typer")       # named here and not imported: this module stays usable on an install without the command line

    net = typer.Typer(add_completion=False, no_args_is_help=True, help="Net small accepted outcomes into one release per supplier per period.")
    app.add_typer(net, name="net")
    if help_lines is not None:
        help_lines.append(("net", "For money", "Net small outcomes into one release: open, add, dispute, close, settled, statement."))

    def stop(said: str, fix: str = ""):
        from . import cli
        return cli.Stop(said, fix)

    def say(o) -> None:
        typer.echo(json.dumps(o, indent=1, sort_keys=True))

    def held(path: Path):
        from . import events
        return events.locked(path)

    def order_at(address: str):
        """The order at `address` as the chain has it now, and the chain's clock."""
        from solders.pubkey import Pubkey
        from . import cli
        from .settle.v2 import pay
        try:
            at = Pubkey.from_string(address)
        except ValueError:
            raise stop(f"{address} is not an address.", "Give the reserve order's address, as `knos net reserve` or the funding run printed it.") from None
        chain_ = cli._ledger()
        return pay.read_order(chain_.account(at)), chain_.now()

    def book_of(path: Path) -> Book:
        try:
            return load(path)
        except Bad as why:
            raise stop(f"{path}: {why}", "A book is never repaired by editing it: ask the other side for its copy.") from None

    @net.command("open")
    def open_(book: Path = typer.Argument(..., help="the book file (made when absent)"),
              buyer: int = typer.Option(..., help="the buyer's GitHub owner id"),
              seller: int = typer.Option(..., help="the supplier's GitHub owner id"),
              month: str = typer.Option(..., help="YYYY-MM"),
              cap: str = typer.Option(..., help="the most the period may come to, like 500 or 499.50"),
              unit: str = typer.Option("USDC", help="what the amounts count"),
              seq: int = typer.Option(None, help="the pair's batch number this month on knos_meter (default: the next this book has not used)"),
              reserve: str = typer.Option("", help="the address of the standing order the buyer locked for this pair: the period spends no more than it holds"),
              max_exposure: str = typer.Option("", "--max-exposure", help="without a reserve: the most the supplier may carry unpaid over the whole book "
                                                                           "(default: the cap)")):
        """Open a netting period between one buyer and one supplier, with a cap; on a reserve, or unsecured with a limit."""
        if reserve and max_exposure:
            raise stop("A period has a reserve or an exposure limit, not both.", "A reserved period exposes the supplier to nothing: leave --max-exposure out.")
        facts = None
        if reserve:
            o, now = order_at(reserve)
            try:
                facts = reserve_of(o, reserve, buyer, seller, now, unit, month)
            except Bad as why:
                raise stop(str(why), "Lock one: the buyer funds the audience `knos net reserve` prints. Or open the period unsecured, with --max-exposure.") from None
        with held(book):
            try:
                line = open_line(book_of(book), buyer, seller, month, cap, unit, seq, facts, None if reserve else (max_exposure or cap))
            except Bad as why:
                raise stop(str(why)) from None
            _append(book, [line])
        out = json.loads(line)
        out["secured"] = "reserve" if reserve else "unsecured"
        out["says"] = (f"Locked: {ledger.usd(facts['funded'])} in order {reserve}, drawn {ledger.usd(facts['tranche'])} at a time; signed by {facts['judges']}."
                       if facts else f"Unsecured: the supplier carries what it delivers until the buyer funds it, at most {ledger.usd(out['period']['max_exposure'])}.")
        if facts:
            out["reserve_returns"] = REFUND
        say(out)

    @net.command("reserve")
    def reserve_(buyer: int = typer.Option(..., help="the buyer's GitHub owner id"),
                 seller: int = typer.Option(..., help="the supplier's GitHub owner id"),
                 amount: str = typer.Option(..., help="what to lock, like 500"),
                 tranche: str = typer.Option(..., help="what one draw pays, like 50"),
                 balance: str = typer.Option(..., help="the buyer's Balance address the money comes from"),
                 issue: int = typer.Option(..., help="the issue of the buyer's repository the reserve is funded on"),
                 days: int = typer.Option(90, help="how long it stays locked: at most 90"),
                 unit: str = typer.Option("USDC", help="what the amounts count"),
                 period: str = typer.Option("", help="YYYY-MM: the one month the reserve secures, named in its terms (default: any)")):
        """Print what the buyer's funding run signs to lock a reserve for one supplier. Nothing is sent."""
        from solders.pubkey import Pubkey
        try:
            out = reserve_fund(buyer, seller, amount, tranche, Pubkey.from_string(balance), issue, days * 86_400, unit, period=period or None)
        except ValueError as why:
            raise stop(str(why)) from None
        say({**out, "reserve_returns": REFUND})

    @net.command("settled")
    def settled_(book: Path = typer.Argument(..., help="the book file"),
                 period: str = typer.Option(..., help="the closed period, like 202610.0"),
                 by: str = typer.Option(..., help="what paid it: the order's address or the payment's transaction")):
        """Write a closed period as paid. It leaves the supplier's exposure in this book."""
        with held(book):
            b = book_of(book)
            try:
                line = settled_line(b, period, by)
            except Bad as why:
                raise stop(str(why)) from None
            _append(book, [line])
        say({"settled": period, "by": by, "exposure": exposure(b)})

    @net.command("add")
    def add_(book: Path = typer.Argument(..., help="the book file"),
             outcomes: Path = typer.Argument(None, help="a file of outcomes, one JSON object a line: order, artifact, policy, amount, evidence (and milestone)"),
             order: str = typer.Option("", help="the work order, 64 hex characters"),
             artifact: str = typer.Option("", help="the commit, 40 hex characters"),
             policy: str = typer.Option("", help="the policy it was judged under, 64 hex characters"),
             milestone: int = typer.Option(0),
             amount: str = typer.Option("", help="like 0.32"),
             evidence: str = typer.Option("", help="sha256 of the signed token or receipt, 64 hex characters"),
             events_log: Path = typer.Option(None, "--events", help="the events log both sides acknowledge (default: KNOS_EVENTS)")):
        """Add accepted outcomes to the open period. A duplicate, or one past the cap, is refused and named."""
        from . import events
        try:
            items: list = [raw for raw in outcomes.read_text(encoding="utf-8").splitlines() if raw.strip()] if outcomes else []
        except OSError:
            raise stop(f"Cannot read {outcomes}.") from None
        if order or evidence:
            items.append({"order": order, "artifact": artifact, "policy": policy, "milestone": milestone, "amount": amount, "evidence": evidence})
        log = events.where(events_log)
        with held(book):
            b = book_of(book)
            try:
                counted = set(events.load(log).first) if log and log.exists() else set()
                lines, refused = add(b, items, counted)
            except Bad as why:
                raise stop(str(why)) from None
            _append(book, lines)
        p = b.open
        assert p is not None
        _mirror(log, lambda: (ev for raw in lines for ev in events.from_evaluation(ledger.parse(raw), "import", p.terms["month"],
                                                                                  f"net:{p.name}:{ledger.parse(raw).evidence}")))
        out = {"added": len(lines), "refused": refused, "period": p.name, "value": p.value, "left_under_cap": p.terms["cap"] - p.value,
               "secured": "reserve" if p.reserve is not None else "unsecured", "exposure": exposure(b)}
        if p.reserve is not None:
            out["reserve"] = reserve_state(p)
        say(out)
        if refused:
            raise typer.Exit(1)

    @net.command("dispute")
    def dispute_(book: Path = typer.Argument(..., help="the book file"),
                 evidence: str = typer.Option(..., help="the evidence id of the line"),
                 reason: str = typer.Option("", help="why, in your words"),
                 events_log: Path = typer.Option(None, "--events", help="the events log (default: KNOS_EVENTS)")):
        """Take one line out of the open period's net. Every other line stays payable."""
        from . import events
        with held(book):
            b = book_of(book)
            try:
                line = dispute_line(b, evidence, reason)
            except Bad as why:
                raise stop(str(why)) from None
            _append(book, [line])
        p = b.open
        assert p is not None
        e = next(x for x in p.evals if x.evidence == evidence)
        _mirror(events.where(events_log), lambda: [events.correction(t, "import", "disputed", reason=reason, month=p.terms["month"], evidence=f"net:{p.name}:{evidence}")
                                                   for t in (_evl(e), _acc(e))])
        say({"disputed": evidence, "period": p.name, "value": p.value})

    @net.command("close")
    def close_(book: Path = typer.Argument(..., help="the book file"),
               other: Path = typer.Option(None, help="the other side's book: the two must come to the same root"),
               ledger_out: Path = typer.Option(None, "--ledger", help="the pair's meter ledger file (what `knos meter verify` reads): the period is "
                                                                      "appended to it, and it is made when absent"),
               balance: str = typer.Option("", help="the buyer's Balance address: prints the audience that funds the release"),
               issue: int = typer.Option(0, help="the issue of the buyer's repository the release is funded on"),
               events_log: Path = typer.Option(None, "--events", help="the events log (default: KNOS_EVENTS)")):
        """Close the open period: the net, the batch root to anchor, and the one release."""
        from . import events
        with held(book):
            b = book_of(book)
            try:
                n, line = close(b, book_of(other) if other else None)
                before = ledger_out.read_text(encoding="utf-8") if ledger_out and ledger_out.exists() else ""
                whole = ledger_text(n, before) if ledger_out else ""
            except Bad as why:
                raise stop(str(why)) from None
            except OSError:
                raise stop(f"Cannot read {ledger_out}.") from None
            _append(book, [line])
        if ledger_out:
            ledger_out.write_text(whole, encoding="utf-8", newline="\n")
        text = ledger.dump([n.batch])           # the period's own batch: what the events log takes from this close
        skip = {x for e in (n.batch.evals if n.batch else ()) if e.stands == "disputed" for x in (_evl(e),)}
        _mirror(events.where(events_log), lambda: (ev for ev in events.from_ledger(text) if ev.id not in skip))
        out: dict = {"net": n.json(), "audiences": audiences(n), "terms": terms(n), "compare": compare(n)}
        done = load(book).periods[-1]
        out["secured"], out["exposure"] = "reserve" if done.reserve is not None else "unsecured", done.exposure
        if done.reserve is not None:
            # the release is not a new order: the reserve order pays it, one tranche for each audience below
            out.pop("terms")
            out["reserve"], out["draws"], out["reserve_returns"] = reserve_state(done), draws(done), REFUND
        elif balance:
            from solders.pubkey import Pubkey
            out["release"] = release(n, Pubkey.from_string(balance), issue)
        say(out)

    @net.command("statement")
    def statement_(book: Path = typer.Argument(..., help="the book file"),
                   chain_: bool = typer.Option(False, "--chain", help="read each reserve order from the chain and say what no longer holds")):
        """Every period: open or closed, its lines, its net, its fee, its reserve and the supplier's exposure."""
        b = book_of(book)
        out = statement(b)
        if chain_:
            for p, row in zip(b.periods, out["periods"]):
                if p.reserve is not None:
                    o, now = order_at(p.reserve["order"])
                    row["reserve"]["on_chain"] = reserve_check(p, o, now) or ["holds"]
        say(out)
