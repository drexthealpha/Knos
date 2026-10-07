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
ENFORCED = (
    ("on chain", "the cap: the buyer's Balance refuses an order above the cap its wallet set (knos_pay, error 93)"),
    ("on chain", "the release: one order of exactly the net, its fee on top, paid only by a token that names the order, the terms hash fixed at funding "
                 "and the supplier"),
    ("on chain", "the root: knos_meter keeps the buyer's batch and the supplier's claim in two accounts; the same running hash in both means the same root"),
    ("on chain", "the fee: 0.30% of the net, at least 0.05, once, taken when the order is funded"),
    ("off chain", "each line: committed by the batch root, not escrowed one by one; no program reads a line"),
    ("off chain", "the link from the release to the batch: the terms name the root and the program stores their hash; a reader compares, the program does not"),
    ("off chain", "that the buyer funds the release: until it does, the supplier carries the buyer's credit risk inside the period, up to the cap"),
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
_CLOSED = {"accepted", "count", "disputed", "fee", "root", "value"}


def _period(o: object) -> dict:
    if not isinstance(o, dict) or set(o) != _TERMS or not isinstance(o["unit"], str) or not ledger._CURRENCY.fullmatch(o["unit"]) or not o["unit"]:
        raise Bad("a period has buyer, seller, month, seq, cap and unit")
    ledger._int(o["buyer"], "buyer", least=1), ledger._int(o["seller"], "seller", least=1), ledger._int(o["seq"], "seq")
    ledger.month_of(ledger._int(o["month"], "month"))
    if not ORDER_MIN <= ledger._int(o["cap"], "cap") <= MAX_CAP:
        raise Bad("a period's cap is between 5.00 and 100,000.00: one release is one order, and those are an order's bounds")
    return o


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
                book.periods.append(Period(t))
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
    p.evals.append(e)
    p.value += e.rate
    book.by_id[e.deliverable], book.by_evidence[e.evidence] = p.name, p.name


def _dispute(p: Period, evidence: str, reason: str) -> None:
    line = next((e for e in p.evals if e.evidence == evidence), None)
    if line is None:
        raise Bad(f"no line of the open period {p.name} rests on evidence {str(evidence)[:16]}...; a closed period is corrected through `knos meter`, not here")
    if evidence in p.disputes:
        raise Bad("that line is disputed already")
    p.disputes[evidence] = reason
    p.value -= line.rate


def outcome(t: dict, order: str, artifact: str, policy: str, amount: str | int, evidence: str, milestone: int = 0) -> Evaluation:
    """One accepted outcome of a period with terms `t`, as the line the book and the batch hold."""
    return Evaluation(t["buyer"], t["seller"], order, artifact, policy, milestone, True, units(amount), "accepted", currency=t["unit"], evidence=evidence)


def open_line(book: Book, buyer: int, seller: int, month: int | str, cap: str | int, unit: str = "USDC", seq: int | None = None) -> str:
    """The header of the next period. `seq`: the batch number of the pair's month on knos_meter, from 0 and in order;
    by default the next one this book has not used (name it when the pair also batches that month by other means)."""
    m = ledger.month_of(month)
    if seq is None:
        seq = 1 + max((p.terms["seq"] for p in book.periods if p.terms["month"] == m), default=-1)
    line = canon({"period": {"buyer": buyer, "cap": units(cap), "month": m, "seller": seller, "seq": seq, "unit": unit}})
    read(text_of(book) + line + "\n")
    return line


def text_of(book: Book) -> str:
    out: list[str] = []
    for p in book.periods:
        out.append(canon({"period": p.terms}))
        out += [e.line() for e in p.evals]
        out += [canon({"dispute": {"evidence": k, "reason": v}}) for k, v in p.disputes.items()]
        if p.closed is not None:
            out.append(canon({"closed": p.closed}))
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
    out = [f"{k}: {mine.terms[k]} here, {theirs.terms[k]} there" for k in sorted(_TERMS) if mine.terms[k] != theirs.terms[k]]
    a, b = {e.id: e for e in mine.lines()}, {e.id: e for e in theirs.lines()}
    out += [f"outcome {i.hex()[:16]}... (evidence {a[i].evidence[:16]}...) is here and not there" for i in sorted(set(a) - set(b))]
    out += [f"outcome {i.hex()[:16]}... (evidence {b[i].evidence[:16]}...) is there and not here" for i in sorted(set(b) - set(a))]
    out += [f"outcome {i.hex()[:16]}... differs: {a[i].stands} {ledger.usd(a[i].rate)} here, {b[i].stands} {ledger.usd(b[i].rate)} there"
            for i in sorted(set(a) & set(b)) if a[i] != b[i]]
    return out


def close(book: Book, other: Book | None = None) -> tuple[Net, str]:
    """Closes the open period: (its net, the closing line to append). `other`: the other side's book; its copy of the
    period must come to the same root. A net under 5.00 is not closed: the escrow takes no order that small, so the
    period stays open until it holds more."""
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
    if n.value < ORDER_MIN:
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
        periods.append(row)
    t = book.periods[0].terms if book.periods else {}
    return {"type": "knos.netting", "v": VERSION, "buyer": t.get("buyer"), "seller": t.get("seller"), "unit": t.get("unit"), "periods": periods,
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
        help_lines.append(("net", "For money", "Net small outcomes into one release: open, add, dispute, close, statement."))

    def stop(said: str, fix: str = ""):
        from . import cli
        return cli.Stop(said, fix)

    def say(o) -> None:
        typer.echo(json.dumps(o, indent=1, sort_keys=True))

    def held(path: Path):
        from . import events
        return events.locked(path)

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
              seq: int = typer.Option(None, help="the pair's batch number this month on knos_meter (default: the next this book has not used)")):
        """Open a netting period between one buyer and one supplier, with a cap."""
        with held(book):
            try:
                line = open_line(book_of(book), buyer, seller, month, cap, unit, seq)
            except Bad as why:
                raise stop(str(why)) from None
            _append(book, [line])
        say(json.loads(line))

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
        say({"added": len(lines), "refused": refused, "period": p.name, "value": p.value, "left_under_cap": p.terms["cap"] - p.value})
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
        out = {"net": n.json(), "audiences": audiences(n), "terms": terms(n), "compare": compare(n)}
        if balance:
            from solders.pubkey import Pubkey
            out["release"] = release(n, Pubkey.from_string(balance), issue)
        say(out)

    @net.command("statement")
    def statement_(book: Path = typer.Argument(..., help="the book file")):
        """Every period: open or closed, its lines, its net, its fee, and what the chain enforces."""
        say(statement(book_of(book)))
