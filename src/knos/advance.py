"""An advance by a third party against a funded order: the supplier is paid now, the order pays the advancer later.

    knos advance offer     an advancer writes what it will advance against: its discount, its cap, the judges it accepts
    knos advance take      a supplier takes it for one order: one transaction pays the supplier and assigns the order
    knos advance status    where one advance stands, from the chain alone
    knos advance quote     prices a closed, reserved netting period (knos.netting) as a receivable: what its reserve
                           order will pay the supplier, less the financier's discount

Not offered by Knos: a third party can do this today with the program as it is. Knos lends nothing, holds nothing and
charges nothing for it. The only instruction of knos_pay used is Assign (24): a payee names the wallet that receives
this order's payment in his place, once, and cannot take it back.

What `take` adds to Assign is one transaction with two instructions and two signatures: the advancer's transfer to
the supplier, and the supplier's Assign to the advancer. A transaction lands whole or not at all, so nobody pays for
an assignment that was not made and nobody assigns for money that did not arrive.

After that the order has one of three ends, and each pays exactly one party once:

    accepted       PayOrder pays the advancer the supplier's whole share. The supplier keeps what it was advanced.
    rejected       no acceptance is signed; the funder gives notice (Cancel) and is refunded when the notice ends.
    expired        the deadline passes; anyone sends RefundOrder and the funder is refunded.

In the last two the advancer has paid and collects nothing. It has no recourse on chain: the program gives it no
claim on the supplier or on the funder. docs/ADVANCE.md says what to check before advancing.

A netting period is financed the same way, and only when a reserve secures it: the receivable is the period's draws
on its reserve order, the supplier assigns that order's payments, and the financier collects the draws. WHO_CARRIES
says who is left with which risk. Knos never funds, lends or guarantees any of it.

Standard library and knos.settle.v2.pay only at import.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

SCHEMA = "knos.advance-offer/1"
ASSURANCES = ("black-box", "hermetic", "in-process")      # as a receipt names how the judge ran (knos.receipt)
ANY = "*"
MAX_RATE_BPS = 5_000
NOT_KNOS = "Not offered by Knos: a third party can do this today with the program as it is."
RECOURSE = "none on chain: the program gives the advancer no claim on the supplier or on the funder"
CHECK_FIRST = ("the supplier's record (knos record build <supplier>; docs/RECORD.md)",
               "the order's terms, by their hash: what the judge will accept",
               "the deadline: an order nobody accepted goes back to its funder then",
               "the judge the order pins: the workflow repository and its commit")


WHO_CARRIES = (
    ("buyer", "Its money is locked in the reserve order from before the work. It gets back what no draw took, after the deadline, and nothing sooner."),
    ("supplier", "After selling the period: the discount, and nothing else of that period. Without a sale: that the draws are signed before the "
                 "reserve's deadline, and what the period left undrawn (under one tranche)."),
    ("financier", "It paid the supplier and collects the draws. It loses if the judge the order pins signs no draw before the deadline: the money "
                  "then goes back to the buyer, and the program gives the financier no claim on anyone."),
    ("Knos", "No money at any step: it funds nothing, lends nothing, holds nothing, guarantees nothing and charges nothing for the sale."),
)
ASSIGN_COVERS = ("Assign moves every later payment of this reserve order to this supplier, not one period's: the financier collects each draw until "
                 "it assigns the order back, which only it can sign.")


def canon(o: Any) -> str:
    return json.dumps(o, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def offer(advancer: str, mint: str, rate_bps: int, cap: int, *, evaluators=(ANY,), assurances=ASSURANCES, min_seconds_left: int = 86_400,
          holdback: bool = False, expires: int = 0) -> dict:
    """What an advancer will advance against. `rate_bps`: its discount on the amount advanced against. `cap`: the
    most it advances against one order, in the mint's base units. `evaluators`: the judges it accepts, each
    "<workflow repository>@<commit>", or "*" for any. `assurances`: how the judge must have run, for a take against an
    acceptance already signed. `min_seconds_left`: the least time an order must have before its deadline.
    `holdback`: whether it advances against an order that holds part back through a warranty. ValueError in words."""
    from solders.pubkey import Pubkey
    Pubkey.from_string(advancer), Pubkey.from_string(mint)
    if not 0 < int(rate_bps) <= MAX_RATE_BPS:
        raise ValueError(f"the discount is {rate_bps} basis points: give 1 to {MAX_RATE_BPS}")
    if int(cap) <= 0:
        raise ValueError("the cap is the most advanced against one order, in base units: give more than 0")
    ev = sorted({str(e) for e in evaluators})
    if not ev or any(e != ANY and (e.count("@") != 1 or len(e.split("@")[1]) != 40) for e in ev):
        raise ValueError('an evaluator is "<workflow repository>@<40 character commit>", or "*" for any')
    how = [a for a in ASSURANCES if a in set(assurances)]
    if not how or set(assurances) - set(ASSURANCES):
        raise ValueError(f"an assurance is one of: {', '.join(ASSURANCES)}")
    doc = {"schema": SCHEMA, "advancer": advancer, "mint": mint, "rate_bps": int(rate_bps), "cap": int(cap), "evaluators": ev, "assurances": how,
           "min_seconds_left": int(min_seconds_left), "holdback": bool(holdback), "expires": int(expires),
           "recourse": RECOURSE, "check_first": list(CHECK_FIRST), "not_knos": NOT_KNOS}
    return {**doc, "sha256": hashlib.sha256(canon(doc).encode()).hexdigest()}


def check(doc) -> str | None:
    """None when `doc` is an offer this version wrote and nobody changed; else why not."""
    if not isinstance(doc, dict) or doc.get("schema") != SCHEMA:
        return f"not a {SCHEMA} file"
    if hashlib.sha256(canon({k: v for k, v in doc.items() if k != "sha256"}).encode()).hexdigest() != doc.get("sha256"):
        return "the file does not hash to the sha256 it states"
    return None


def discount(amount: int, rate_bps: int) -> int:
    """The advancer's discount on `amount`, rounded up: the advancer never advances more than it stated."""
    return -(-int(amount) * int(rate_bps) // 10_000)


def quote(doc: dict, order, *, now: int, assigned=None, share_bps: int = 10_000, wf_repo: str = "", assurance: str | None = None) -> dict:
    """What `doc` (an offer) gives for a payee's share of `order` (knos.settle.v2.pay.Order, as read now) and every
    reason it gives nothing. `assigned`: the wallet the share is already assigned to, if any. `wf_repo`: the workflow
    repository the supplier says the order pins (checked against the order's hash of it). `assurance`: how the judge
    ran, when an acceptance is already signed; None while the work is in review."""
    from .settle.v2 import pay
    why: list[str] = []
    bad = check(doc)
    if bad:
        return {"ok": False, "why": [bad], "pays_now": 0, "discount": 0, "collects": 0}
    if order is None:
        return {"ok": False, "why": ["there is no such order: it was paid, refunded, or never funded"], "pays_now": 0, "discount": 0, "collects": 0}
    left = order.amount - order.paid
    share = left * int(share_bps) // 10_000
    if order.state != "open":
        why.append(f"the order is {order.state}, not open: Assign after a payment moves nothing")
    if str(order.mint) != doc["mint"]:
        why.append(f"the order is in mint {order.mint}, not {doc['mint']}")
    if order.flags & pay.F_STANDING:
        why.append("the order is a standing offer: it pays whoever is accepted, not one supplier")
    if order.holdback_bps and not doc["holdback"]:
        why.append("the order holds part back through a warranty, and this offer does not advance against that")
    if assigned is not None:
        why.append(f"this share is already assigned to {assigned}")
    if doc["expires"] and now > doc["expires"]:
        why.append("the offer has expired")
    if order.deadline - now < doc["min_seconds_left"]:
        why.append(f"the order's deadline is {max(order.deadline - now, 0)} seconds away and the offer asks for {doc['min_seconds_left']}")
    if order.cancel_at:
        why.append("the funder gave notice on this order (Cancel)")
    if share > doc["cap"]:
        why.append(f"the share is {share} and the offer's cap is {doc['cap']}")
    if share <= 0:
        why.append("nothing is left of this order to pay")
    if ANY not in doc["evaluators"]:
        named = f"{wf_repo}@{order.wf_sha}"
        if not wf_repo or pay.wf_repo_hash(wf_repo) != order.wf_repo_hash:
            why.append("name the workflow repository the order pins (--workflows): the order stores only its hash")
        elif named not in doc["evaluators"]:
            why.append(f"the order's judge is {named}, which the offer does not accept")
    if assurance is not None and assurance not in doc["assurances"]:
        why.append(f"the judge ran {assurance}, and the offer accepts {', '.join(doc['assurances'])}")
    cut = discount(share, doc["rate_bps"])
    return {"ok": not why, "why": why, "share": share, "discount": cut if not why else 0, "pays_now": share - cut if not why else 0,
            "collects": share if not why else 0, "at_acceptance": share * (10_000 - order.holdback_bps) // 10_000 if not why else 0,
            "after_warranty": share - share * (10_000 - order.holdback_bps) // 10_000 if not why else 0,
            "assurance": assurance or "not known: the judge has not run", "recourse": RECOURSE, "knos_fee": 0}


def period_quote(doc: dict, book, order, *, now: int, period: str | None = None, assigned=None, wf_repo: str = "") -> dict:
    """What `doc` (an offer) gives for a closed, reserved netting period of `book` (a knos.netting.Book) and every reason
    it gives nothing. `order`: the period's reserve order as read now (knos.settle.v2.pay.Order, or None). `period`: its
    name, like "202610.0" (default: the last closed one). The receivable is what the period draws from its reserve:
    whole tranches. What it left undrawn is not sold. A quote that is ok goes to `take_ixs` as any other."""
    from . import netting
    from .settle.v2 import pay
    zero = {"ok": False, "pays_now": 0, "discount": 0, "collects": 0, "knos_fee": 0}
    bad = check(doc)
    if bad:
        return {**zero, "why": [bad]}
    p = next((x for x in reversed(book.periods) if x.closed is not None and period in (None, x.name)), None)
    if p is None:
        return {**zero, "why": ["the book has no such closed period: only a closed period is sold, when both books came to one root and its net is fixed"]}
    if p.reserve is None:
        return {**zero, "why": [f"period {p.name} is unsecured: no order holds its money, so there is nothing to assign. The buyer's credit is not sold here."]}
    s = netting.reserve_state(p)
    why: list[str] = [f"period {p.name} is written as settled, by {p.settled}"] if p.settled else []
    share = s["drawn"]
    if share <= 0:
        why.append(f"period {p.name} draws nothing: it comes to less than one tranche of {s['tranche']}")
    if order is None:
        why.append(f"the reserve order {s['order']} is gone: paid out or refunded")
    else:
        why += netting.reserve_check(p, order, now)
        if str(order.mint) != doc["mint"]:
            why.append(f"the reserve is in mint {order.mint}, not {doc['mint']}")
        if order.deadline - now < doc["min_seconds_left"]:
            why.append(f"the reserve's deadline is {max(order.deadline - now, 0)} seconds away and the offer asks for {doc['min_seconds_left']}")
        if ANY not in doc["evaluators"]:
            named = f"{wf_repo}@{order.wf_sha}"
            if not wf_repo or pay.wf_repo_hash(wf_repo) != order.wf_repo_hash:
                why.append("name the workflow repository the reserve pins (--workflows): the order stores only its hash")
            elif named not in doc["evaluators"]:
                why.append(f"the reserve's judge is {named}, which the offer does not accept")
    if assigned is not None:
        why.append(f"this reserve's payments are already assigned to {assigned}")
    if doc["expires"] and now > doc["expires"]:
        why.append("the offer has expired")
    if share > doc["cap"]:
        why.append(f"the period draws {share} and the offer's cap is {doc['cap']}")
    cut = discount(share, doc["rate_bps"])
    return {"ok": not why, "why": why, "period": p.name, "order": s["order"], "share": share, "draws": s["draws"], "tranche": s["tranche"],
            "undrawn_not_sold": s["undrawn"], "deadline": s["deadline"], "discount": 0 if why else cut, "pays_now": 0 if why else share - cut,
            "collects": 0 if why else share, "at_acceptance": 0 if why else share, "after_warranty": 0, "assurance": "both books came to one root",
            "recourse": RECOURSE, "assign_covers": ASSIGN_COVERS, "who_carries": [{"who": w, "what": t} for w, t in WHO_CARRIES], "knos_fee": 0}


def transfer_ix(source, mint, dest, owner, amount: int, decimals: int = 6, token_program=None):
    """A plain TransferChecked of the token program, as any wallet sends it."""
    from solders.instruction import AccountMeta, Instruction
    from .settle.v2 import pay
    return Instruction(token_program or pay.TOKEN, bytes([12]) + int(amount).to_bytes(8, "little") + bytes([decimals]),
                       [AccountMeta(source, False, True), AccountMeta(mint, False, False), AccountMeta(dest, False, True), AccountMeta(owner, True, False)])


def take_ixs(doc: dict, q: dict, order, o, payee_id: int, supplier, *, advancer_token=None, supplier_token=None, program=None) -> list:
    """The one transaction of an advance, for a quote that is ok: the supplier's token account is made if missing (the
    advancer pays its rent), the advancer pays the supplier `q["pays_now"]`, and the supplier's bound wallet assigns
    this order's payment to the advancer. Both sign. `supplier`: the supplier's bound wallet."""
    from solders.pubkey import Pubkey
    from .settle.v2 import pay
    if not q.get("ok"):
        raise ValueError("there is nothing to take: " + "; ".join(q.get("why") or ["the quote is not ok"]))
    program = program or pay.PAY_ID
    advancer, mint = Pubkey.from_string(doc["advancer"]), Pubkey.from_string(doc["mint"])
    tp = o.token_program
    return [pay.create_ata_ix(advancer, supplier, mint, tp),
            transfer_ix(advancer_token or pay.ata(advancer, mint, tp), mint, supplier_token or pay.ata(supplier, mint, tp), advancer, q["pays_now"], o.decimals, tp),
            pay.assign_ix(supplier, order, payee_id, advancer, program)]


def _field(line: str | None, name: str) -> str | None:
    for part in (line or "").split():
        if part.startswith(name + "="):
            return part[len(name) + 1:]
    return None


def status(ledger, order, payee_id: int, program=None) -> dict:
    """Where an advance stands, from the chain alone: the order while it exists, and what the program logged when it
    ended. `ledger`: account(address), now(), log_of(address, marker)."""
    from .settle.v2 import pay
    program = program or pay.PAY_ID
    o = pay.read_order(ledger.account(order))
    out: dict[str, Any] = {"order": str(order), "payee": int(payee_id), "recourse": RECOURSE}
    if o is not None:
        to = pay.read_assign(ledger.account(pay.assign_pda(order, payee_id, program)), o)
        late = ledger.now() > o.deadline and o.state == "open"
        state = "not assigned" if to is None else "expired: anyone can refund the funder" if late else \
                "in warranty: the holdback waits" if o.state == "warranty" else "assigned: waits for an acceptance"
        return {**out, "state": state, "assignee": str(to) if to else None, "amount": o.amount, "paid": o.paid, "deadline": o.deadline,
                "notice": bool(o.cancel_at)}
    said = ledger.log_of(order, "knos3:assigned", lambda line: _field(line, "payee") == str(payee_id))
    paid = ledger.log_of(order, "knos3:paid", lambda line: _field(line, "payee") == str(payee_id))
    back = ledger.log_of(order, "knos3:refunded")
    was = _field(said, "to")
    if paid:
        return {**out, "state": "paid", "assignee": was, "paid_to": _field(paid, "to"), "amount": int(_field(paid, "amount") or 0),
                "advancer_collected": was is not None and _field(paid, "to") == was}
    if back:
        return {**out, "state": "refunded to the funder: the advancer's loss", "assignee": was, "amount": int(_field(back, "amount") or 0), "advancer_collected": False}
    return {**out, "state": "unknown: the order is gone and its history was not found", "assignee": was}


def lines(q: dict, money: str = "test USDC", decimals: int = 6) -> list[str]:
    """A quote in words."""
    m = lambda units: f"{units / 10 ** decimals:,.2f} {money}"  # noqa: E731
    if not q["ok"]:
        return ["Nothing is advanced: " + "; ".join(q["why"]) + "."]
    if q.get("period"):
        return [f"The financier pays the supplier {m(q['pays_now'])} now for period {q['period']}: its {q['draws']} draws of {m(q['tranche'])}, "
                f"{m(q['share'])}, less a discount of {m(q['discount'])}.",
                f"Each draw the reserve's judge signs then pays the financier {m(q['tranche'])} from the reserve order, {m(q['collects'])} in all.",
                f"What the period left undrawn, {m(q['undrawn_not_sold'])}, is not sold.",
                "If no draw is signed before the reserve's deadline, the money goes back to the buyer and the financier collects nothing.",
                f"Recourse: {RECOURSE}.", "Knos charges nothing for this. " + NOT_KNOS]
    out = [f"The advancer pays the supplier {m(q['pays_now'])} now: the share of {m(q['share'])} less its discount of {m(q['discount'])}.",
           f"If the work is accepted the order pays the advancer {m(q['at_acceptance'])}"
           + (f", and {m(q['after_warranty'])} after the warranty unless the change is reverted." if q["after_warranty"] else "."),
           "If it is rejected or the order expires, the funder is refunded and the advancer collects nothing.",
           f"Recourse: {RECOURSE}.", "Knos charges nothing for this. " + NOT_KNOS]
    return out


def register(app: Any, help_lines: list | None = None) -> None:
    """`knos advance offer | take | status`. `help_lines`: cli._HELP, which gets the command's line."""
    import importlib
    typer = importlib.import_module("typer")
    if help_lines is not None:
        help_lines.append(("advance", "For money", "An advance by a third party against a funded order or a reserved netting period. Knos lends nothing and charges nothing."))
    group = typer.Typer(help="An advance by a third party against a funded order (docs/ADVANCE.md). " + NOT_KNOS, no_args_is_help=True)
    app.add_typer(group, name="advance", rich_help_panel="For money")

    def _stop(said: str, fix: str = ""):
        from . import cli
        return cli.Stop(said, fix)

    def _read(path: Path) -> dict:
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as why:
            raise _stop(f"{path} is not an offer: {why}", "Write one: knos advance offer --help") from None
        bad = check(doc)
        if bad:
            raise _stop(f"{path} is not an offer: {bad}.", "Write one: knos advance offer --help")
        return doc

    @group.command("offer")
    def offer_(advancer: str = typer.Argument(..., help="the wallet that advances and collects"),
               rate: float = typer.Option(..., "--rate", help="the discount, in percent of the amount advanced against"),
               cap: float = typer.Option(..., "--cap", help="the most advanced against one order, in whole units"),
               mint: str = typer.Option("4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU", "--mint", help="the token (default: devnet USDC)"),
               evaluator: list[str] = typer.Option([], "--evaluator", help='a judge it accepts, "<workflow repository>@<commit>" (repeat it; default: any)'),
               assurance: list[str] = typer.Option([], "--assurance", help="how the judge must have run: black-box, hermetic, in-process (repeat it; default: all)"),
               min_days: float = typer.Option(1.0, "--min-days", help="the least time an order must have before its deadline"),
               holdback: bool = typer.Option(False, "--holdback", help="advance against orders that hold part back through a warranty"),
               out: Path = typer.Option(Path("advance-offer.json"), "--out", help="where to write the offer")) -> None:
        """Write an advancer's offer: its discount, its cap, the judges it accepts. Nothing is sent anywhere."""
        from . import cli
        try:
            doc = offer(advancer, mint, round(rate * 100), round(cap * 10 ** 6), evaluators=evaluator or (ANY,), assurances=assurance or ASSURANCES,
                        min_seconds_left=round(min_days * 86_400), holdback=holdback)
        except ValueError as why:
            raise _stop(f"No offer was written: {why}.") from None
        out.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8", newline="\n")
        cli.out.print(f"Wrote {out}: {doc['rate_bps'] / 100:g}% on at most {cap:,.2f} an order. Recourse: {RECOURSE}.", markup=False)
        cli.out.print(NOT_KNOS, markup=False)

    @group.command("take")
    def take_(offer_file: Path = typer.Argument(..., help="the advancer's offer"),
              order: str = typer.Option(..., "--order", help="the funded order's address"),
              payee: int = typer.Option(..., "--payee", help="the supplier's GitHub id, as the order's judge will name it"),
              workflows: str = typer.Option("", "--workflows", help="the workflow repository the order pins, owner/repo"),
              assurance: str = typer.Option(None, "--assurance", help="how the judge ran, when an acceptance is already signed"),
              period: Path = typer.Option(None, "--period", help="a netting book: take against its last closed period, whose reserve is --order"),
              keypair: Path = typer.Option(None, "--keypair", help="the supplier's bound wallet: it signs Assign"),
              advancer_keypair: Path = typer.Option(None, "--advancer-keypair", help="the advancer's wallet: it signs the transfer"),
              as_json: bool = typer.Option(False, "--json", help="the quote as JSON")) -> None:
        """Quote an offer for one order; with both keys, send the one transaction that pays the supplier and assigns the order."""
        from solders.pubkey import Pubkey
        from . import chain, cli
        from .settle.v2 import pay
        doc = _read(offer_file)
        ledger, at = cli._ledger(), Pubkey.from_string(order)
        o = pay.read_order(ledger.account(at))
        assigned = pay.read_assign(ledger.account(pay.assign_pda(at, payee)), o) if o else None
        if period is not None:
            from . import netting
            try:
                book = netting.load(period)
            except ValueError as why:
                raise _stop(f"{period}: {why}") from None
            q = period_quote(doc, book, o, now=ledger.now(), assigned=assigned, wf_repo=workflows)
            if q.get("order", order) != order:
                raise _stop(f"The period's reserve is order {q['order']}, not {order}.", "Pass that address as --order.")
        else:
            q = quote(doc, o, now=ledger.now(), assigned=assigned, wf_repo=workflows, assurance=assurance)
        if as_json:
            typer.echo(json.dumps(q, indent=1))
        else:
            for line in lines(q):
                cli.out.print(line, markup=False)
        if not q["ok"]:
            raise typer.Exit(1)
        if keypair is None or advancer_keypair is None:
            cli.err.print("Nothing was sent. Both wallets sign one transaction: pass --keypair and --advancer-keypair.", markup=False)
            return
        try:
            supplier, advancer = chain.wallet(keypair), chain.wallet(advancer_keypair)
        except chain.Refused as why:
            raise _stop(str(why)) from None
        if str(advancer.pubkey()) != doc["advancer"]:
            raise _stop(f"--advancer-keypair is {advancer.pubkey()}, and the offer's advancer is {doc['advancer']}.")
        sig = ledger.send(take_ixs(doc, q, at, o, payee, supplier.pubkey()), advancer, [supplier])
        cli.out.print(f"Sent {sig}: the supplier was paid and the order is assigned. See it: knos advance status --order {order} --payee {payee}", markup=False)

    @group.command("quote")
    def quote_(offer_file: Path = typer.Argument(..., help="the financier's offer"),
               period: Path = typer.Option(..., "--period", help="the netting book (knos net) whose closed, reserved period is sold"),
               name: str = typer.Option(None, "--name", help="the period, like 202610.0 (default: the last closed one)"),
               workflows: str = typer.Option("", "--workflows", help="the workflow repository the reserve pins, owner/repo"),
               as_json: bool = typer.Option(False, "--json", help="the quote as JSON")) -> None:
        """Price a closed, reserved netting period as a receivable. Nothing is sent: `take` sends it, against the reserve order."""
        from solders.pubkey import Pubkey
        from . import cli, netting
        doc = _read(offer_file)
        try:
            book = netting.load(period)
        except ValueError as why:
            raise _stop(f"{period}: {why}") from None
        p = next((x for x in reversed(book.periods) if x.closed is not None and name in (None, x.name)), None)
        o, assigned, now = None, None, 0
        if p is not None and p.reserve is not None:
            ledger, at = cli._ledger(), Pubkey.from_string(p.reserve["order"])
            o, now = pay_order(ledger, at), ledger.now()
            assigned = _assigned(ledger, at, p.terms["seller"], o)
        q = period_quote(doc, book, o, now=now, period=name, assigned=assigned, wf_repo=workflows)
        if as_json:
            typer.echo(json.dumps(q, indent=1))
        else:
            for line in lines(q):
                cli.out.print(line, markup=False)
            if q["ok"]:
                cli.out.print(ASSIGN_COVERS, markup=False)
                cli.out.print(f"Take it: knos advance take {offer_file} --order {q['order']} --payee {p.terms['seller'] if p else ''}", markup=False)
        if not q["ok"]:
            raise typer.Exit(1)

    def pay_order(ledger, at):
        from .settle.v2 import pay
        return pay.read_order(ledger.account(at))

    def _assigned(ledger, at, payee: int, o):
        from .settle.v2 import pay
        return pay.read_assign(ledger.account(pay.assign_pda(at, payee)), o) if o else None

    @group.command("status")
    def status_(order: str = typer.Option(..., "--order", help="the order's address"),
                payee: int = typer.Option(..., "--payee", help="the supplier's GitHub id")) -> None:
        """Where an advance stands, from the chain alone."""
        from solders.pubkey import Pubkey
        from . import cli
        typer.echo(json.dumps(status(cli._ledger(), Pubkey.from_string(order), payee), indent=1))
