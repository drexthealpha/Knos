"""The billing rule, as code: what one customer owes for one month, line by line, with the rule behind each line.

    a month's invoice = Control + Meter + Acceptance on value reconciled off chain + Record lookups

The price book (docs/MARKET.md, section 3; BOOK below is the same six lines, five columns each):

    Check       free, forever
    Meter       100,000 evaluations a month free per organisation, then 0.002 USD
    Acceptance  0.30% of value released or reconciled against a signed acceptance; by contract 0.20% on monthly
                value above 1M, and never lower; outcomes under 20 USD are netted: one release per payee per
                period, 0.30% of the netted amount, the 0.05 floor once per release; no cap
    Record      0.10 USD a lookup through the machine-priced API, paid per call by the caller
    Control     Team 25,000 USD a year; Business 100,000; Enterprise from 400,000
    Pilot       2,500 USD, credited against year one

The rules, each of which a line of the invoice names:

- Value released on chain paid its Acceptance fee there, to the program, at release. It is never charged again:
  a customer-month says which accepted deliverables were released on chain, and the invoice leaves them out.
- The volume rates are marginal and by contract: a Control plan is the contract. The month's accepted value is
  laid end to end, value released on chain first; each deliverable pays the rate of the part of the month it lies
  in, and at least 0.05. On chain the program takes 0.30% whatever the month's volume, so the part of that which
  the volume rates would not have taken is a rebate, credited on the invoice.
- Small tickets are netted. Accepted outcomes under 20 USD that name their payee accumulate, and settle as one
  release per payee per period: 0.30% of the netted amount, the 0.05 floor once per release, not once per outcome.
  An outcome that names no payee is charged by itself.
- No charge for a duplicate, an infrastructure failure or a retry Knos caused. A rejection that ran correctly is an
  evaluation, and is counted; it is not an outcome, and carries no Acceptance.
- An accepted deliverable is counted once, however many evaluations it took and however often it is listed.
- THE CREDIT RULE, in one sentence: see RULES["credit"].
- A price by the year is billed in twelve parts that add up to the year's price to the cent.
- An annual commitment is sold by the year, billed in twelve parts, and drawn down by use: a month's Meter,
  Acceptance and Record charges come out of what is left of it, and only what it does not cover is charged on
  top. It is never counted twice with usage.
- Connecting a supplier costs nothing, however many are connected.
- The rated party never pays: an invoice is the buyer's, every line of it is addressed to the buyer, and a
  customer-month billed to a supplier is refused.
- Acceptance is charged once, whichever rail pays. An accepted deliverable names its rail: "chain" (the program
  released it and took the fee then) or "bank" (it was paid by a bank or any other rail, and the invoice carries the
  fee). The same deliverable under both rails is counted once, on the rail first given.
- A rail's own charge (a bank's wire fee, a network's fee) is not Knos's price. It is listed apart, under
  `rail_charges`, and is in no line and not in the total: `payable` is the total and those charges together.
- Money held or passed on is never revenue: a reserve the customer funds, rent that returns, a supplier's principal.
  It is listed apart, under `held`, in no line, not in the total and not in `payable`.

Arithmetic is `decimal.Decimal`, exact, rounded half up to the cent once per line (Acceptance: once per
deliverable). Nothing here reads the network, the chain or a clock. Nothing has been sold: these are proposed
prices, there is no legal entity to invoice from, and an invoice this module prints is an estimate, not a demand
for payment. On devnet every fee the program takes is test money: 0 revenue.

    knos bill estimate --plan business --evaluations 110000 --accepted 10000000
    knos bill explain month.json
    knos bill margin month.json docs/unit_costs.json      (GROSS margin; the three leaks; who earns what at the floor;
                                                           what netting saves; the second worked customer; the budget
                                                           today against what the price book requires; gross fee
                                                           against cash kept)
    knos bill margin --sensitivity docs/unit_costs.json   (the worked customers at a realised Acceptance rate of 30, 20,
                                                           10 and 5 bps)

THE ACCOUNTING RULES, each held by a test: an annual commitment is drawn down by use and is never a second revenue line;
on a release on chain the relayer's tip and the chain costs it pays are the relayer's (`release_split`), never counted
as Knos's revenue and again as Knos's cost; money a customer puts in a reserve, rent that returns and a supplier's
principal are held or passed on (`held` in a customer-month), never revenue.

GROSS MARGIN IS NOT OPERATING MARGIN. Gross margin = (revenue - the direct cost of delivering it) / revenue. Operating
margin subtracts building, selling and administering as well. Nobody is employed and nothing has been sold, so no
operating cost is known: every margin this module prints is gross and says so, and it prints no operating margin.
"""
from __future__ import annotations

import json
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from . import netting

CENT = Decimal("0.01")
ZERO = Decimal(0)

METER_FREE = 100_000                     # evaluations a month, per organisation
METER_PRICE = Decimal("0.002")           # USD an evaluation after the free ones
ACCEPT_RATE = Decimal("0.0030")          # of value released or reconciled against a signed acceptance
ACCEPT_TIERS = ((Decimal(0), ACCEPT_RATE), (Decimal(1_000_000), Decimal("0.0020")))     # (monthly value above, rate), marginal, by contract; the rate never goes below 0.20%
ACCEPT_FLOOR = Decimal("0.05")           # USD per release (a deliverable by itself, or one payee's netted small outcomes); there is no cap
NET_BELOW = Decimal(netting.SMALL) / netting.MICRO     # USD (20; the one definition is netting.SMALL): an outcome under this accumulates, and settles as one release per payee per period
RECORD_PRICE = Decimal("0.10")           # USD a lookup of a supplier's delivery record through the machine-priced API
CONTROL = {"none": ZERO, "team": Decimal(25_000), "business": Decimal(100_000), "enterprise": Decimal(400_000)}     # USD a year; Enterprise: from
PILOT = Decimal(2_500)                   # USD, credited against year one
BENEFIT_RULE = 3                         # what a buyer should demand before buying: a measured benefit of three times the price
PAYER = "buyer"                          # who every line of an invoice is addressed to

BOOK = (
    ("Check", "pull request or artifact checked", "free, forever", "nobody", "nowhere"),
    ("Meter", "evaluation", "100,000 a month free per organisation, then 0.002 USD", "buyer", "prepaid credits"),
    ("Acceptance", "dollar released or reconciled against a signed acceptance",
     "0.30%; by contract 0.20% on monthly value above 1M (the rate never goes below 0.20%); small tickets "
     "are netted: outcomes under 20 USD accumulate and settle as one release per payee per period, charged 0.30% of the netted amount with the "
     "0.05 floor once per release; no cap", "funder, on top of the amount",
     "knos_pay at release (on chain: 0.30% and the floor; volume rates are a rebate by contract, off chain)"),
    ("Record", "lookup of a supplier's delivery record through the machine-priced API",
     "0.10 USD a lookup, paid per call by the caller (an agent, a marketplace, an underwriter) through the knos-order/x402 flow; the public "
     "record page and its file stay free", "the buyer, marketplace or insurer reading it",
     "`knos record serve` (anyone runs it; Knos hosts none); budgeted at ZERO revenue until someone buys it"),
    ("Control", "organisation, per year", "Team 25,000; Business 100,000; Enterprise from 400,000 (not deliverable yet: it needs single "
     "sign-on, private deployment and support that do not exist)", "buyer", "contract"),
    ("Pilot", "one buyer, two suppliers, 30 days, one reconciled invoice", "2,500 USD, credited against year one", "buyer", "contract"),
)

RULES = {
    "subscription": "Control is sold by the year and billed in twelve parts that add up to the year's price.",
    "enterprise": "Enterprise is from 400,000 USD a year and is not deliverable yet.",
    "meter": "Meter: the first 100,000 evaluations a month are free, then 0.002 USD each.",
    "free_of_charge": "No charge for a duplicate, an infrastructure failure or a retry Knos caused.",
    "rejection": "A rejection that ran correctly is an evaluation, not an outcome.",
    "acceptance": "Acceptance: 0.30% of value reconciled against a signed acceptance, at least 0.05 USD a release, with no cap.",
    "volume": "By contract the month's value above 1,000,000 pays 0.20%, each rate on its own part; the rate never goes below 0.20%.",
    "netted": "Outcomes under 20 USD are netted: one release per payee per period, 0.30% of the netted amount, the 0.05 floor once.",
    "on_chain": "Value released on chain paid its Acceptance fee there and is never charged again.",
    "rebate": "On chain the fee is 0.30% of every release; what the volume rates would not have taken is a rebate by contract.",
    "once": "An accepted deliverable is counted once, however many evaluations it took.",
    "credit": ("Value that is disputed or reversed never carries an Acceptance charge: in the month it was accepted it is left out of the "
               "reconciled value, and when it was accepted in an earlier month the fee it was charged, 0.30% of it unless the earlier "
               "invoice shows less, is credited on the next invoice."),
    "record": "Record: 0.10 USD a lookup through the machine-priced API, paid per call. The public record page and its file are free.",
    "suppliers": "Connecting a supplier costs nothing.",
    "commitment": "An annual commitment is billed in twelve parts and drawn down by use; only what it does not cover is charged on top.",
    "separate": "Agreed separately, and listed as agreed.",
    "pilot": "The Pilot is 2,500 USD, credited against year one.",
    "rated": "The rated party never pays.",
    "once_any_rail": "Acceptance is charged once, whichever rail pays: on chain at release, or on the invoice when a bank pays.",
    "rails": "A rail's own charge is not Knos's price: it is listed apart from the software price and is in no line of it.",
    "devnet": "On devnet every fee the program takes is test money: 0 revenue.",
    "held": ("A reserve the customer funds, rent that returns and a supplier's principal are held or passed on, never Knos's revenue: "
             "listed apart, in no line, not in the total."),
    "relayer": ("On a release on chain the relayer's tip and the chain costs it pays are the relayer's: Knos counts the fee owner's part as "
                "revenue, or, when Knos relays, the whole fee as revenue and the chain costs as its cost; never both."),
}
HELD = ("reserve", "rent", "principal")   # what `held` may name: money that is never Knos's revenue


class BillingError(ValueError):
    """A customer-month that cannot be billed, said in one line."""


def money(value: Any, what: str = "an amount") -> Decimal:
    """A USD amount from a string or a whole number: at most two decimals, never a float (a float is not exact)."""
    if isinstance(value, Decimal):
        d = value
    elif isinstance(value, bool) or isinstance(value, float):
        raise BillingError(f"{what}: write it as a string like \"1250.00\", not {value!r}")
    else:
        try:
            d = Decimal(str(value).replace(",", "").strip())
        except InvalidOperation:
            raise BillingError(f"{what}: {value!r} is not an amount") from None
    if not d.is_finite() or d != d.quantize(CENT):
        raise BillingError(f"{what}: {value!r} has more than two decimals")
    return d.quantize(CENT)


def cents(d: Decimal) -> Decimal:
    return d.quantize(CENT, rounding=ROUND_HALF_UP)


def show(d: Decimal) -> str:
    """1234567.5 -> "1,234,567.50"."""
    return f"{cents(d) + ZERO:,.2f}"          # + 0: a credit of nothing is 0.00, never -0.00


def _count(value: Any, what: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise BillingError(f"{what}: a whole number, 0 or more, not {value!r}")
    return value


def part_of_year(annual: Decimal, month: int) -> Decimal:
    """Month `month` (1 to 12) of a price by the year. The twelve parts add up to `annual` to the cent."""
    whole = int(cents(annual) * 100)
    return Decimal(whole * month // 12 - whole * (month - 1) // 12) / 100


def _marginal(upto: Decimal, tiers: tuple = ACCEPT_TIERS) -> Decimal:
    """The fee on the first `upto` dollars of a period at marginal rates, not rounded."""
    fee = ZERO
    for n, (start, rate) in enumerate(tiers):
        end = tiers[n + 1][0] if n + 1 < len(tiers) else None
        if upto > start:
            fee += ((upto if end is None else min(upto, end)) - start) * rate
    return fee


def acceptance_span(below: Decimal, value: Decimal, volume: bool = True, months: int = 1) -> Decimal:
    """The fee on `value` dollars that lie above the first `below` of a period, not rounded. `volume`: by contract, the
    marginal rates; otherwise 0.30% of all of it. `months`: 1 for a month, 12 for a year of twelve equal months."""
    if not volume:
        return value * ACCEPT_RATE
    tiers = tuple((start * months, rate) for start, rate in ACCEPT_TIERS)
    return _marginal(below + value, tiers) - _marginal(below, tiers)


def acceptance_fee(value: Decimal, below: Decimal = ZERO, volume: bool = False) -> Decimal:
    """Acceptance on one deliverable: its rate, rounded half up to the cent, at least 0.05. Nothing for no value. No cap."""
    return max(ACCEPT_FLOOR, cents(acceptance_span(below, value, volume))) if value > 0 else ZERO


def netted(outcomes: Any, below: Decimal = ZERO, volume: bool = False) -> dict:
    """Small tickets, netted: `outcomes` is [(payee, value)], each value under 20 USD. They accumulate, and each payee's
    settle as ONE release for the period: 0.30% of the netted amount (the contract's rate where the month has reached
    it), and the 0.05 floor once per release. `individually` is what the same outcomes cost one release each."""
    by: dict[str, list[Decimal]] = {}
    for who, value in outcomes:
        if not str(who).strip() or not ZERO < value < NET_BELOW:
            raise BillingError(f"a netted outcome names its payee and is more than 0 and under {show(NET_BELOW)}")
        by.setdefault(str(who).strip(), []).append(value)
    releases, fee, alone = [], ZERO, ZERO
    for who, values in by.items():
        amount = sum(values, ZERO)
        one = acceptance_fee(amount, below, volume)
        micro = amount * netting.MICRO
        if not volume and micro == micro.to_integral_value():      # the release's fee is the one knos_pay takes for an order of the net (netting.fee_of), to the cent
            one = cents(Decimal(netting.fee_of(int(micro))) / netting.MICRO)
        releases.append({"payee": who, "outcomes": len(values), "amount": show(amount), "fee": show(one), "share": share(one, amount)})
        fee, below = fee + one, below + amount
        alone += sum((acceptance_fee(v) for v in values), ZERO)
    return {"releases": releases, "outcomes": sum(len(v) for v in by.values()), "fee": fee, "individually": alone}


def share(fee: Decimal, amount: Decimal) -> str:
    """A fee as a share of what it is charged on: "0.30%"."""
    return f"{fee / amount * 100:.2f}%" if amount > 0 else "none"


def acceptance_parts(value: Decimal, volume: bool = True, months: int = 1) -> list[dict]:
    """How a period's value falls into the tiers: [{"rate", "of", "fee"}], the fee of each part not rounded."""
    out = []
    for n, (start, rate) in enumerate(ACCEPT_TIERS if volume else ACCEPT_TIERS[:1]):
        start = start * months
        end = ACCEPT_TIERS[n + 1][0] * months if volume and n + 1 < len(ACCEPT_TIERS) else None
        of = max(ZERO, (value if end is None else min(value, end)) - start)
        out.append({"rate": f"{rate * 100:.2f}%", "of": of, "fee": of * rate})
    return out


def _plan(name: Any) -> str:
    plan = str(name or "none").strip().lower()
    if plan not in CONTROL:
        raise BillingError(f"plan: {name!r} is not one of {', '.join(CONTROL)}")
    return plan


def _line(key: str, what: str, amount: Decimal, rule: str, how: str = "", **more: Any) -> dict:
    return {"line": key, "what": what, "amount": show(amount), "how": how, "rule": RULES[rule], "pays": PAYER, **more}


def _amount(row: dict) -> Decimal:
    return Decimal(row["amount"].replace(",", ""))


def _valued(rows: Any, what: str) -> list[tuple[str, Decimal, dict]]:
    out = []
    for n, row in enumerate(rows or [], 1):
        if not isinstance(row, dict) or not str(row.get("deliverable", "")).strip():
            raise BillingError(f"{what} {n}: needs a deliverable id")
        value = money(row.get("value", "0"), f"{what} {n}, value")
        if value < 0:
            raise BillingError(f"{what} {n}: a value is 0 or more")
        out.append((str(row["deliverable"]).strip(), value, row))
    return out


FIELDS = {"plan", "month", "billed_to", "evaluations", "duplicates", "infrastructure_failures", "knos_retries", "accepted", "disputed",
          "reversed", "suppliers", "record_lookups", "committed", "drawn", "credit_brought_forward", "other", "customer", "period",
          "rail_charges", "held"}
RAILS = ("chain", "bank")                # how an accepted deliverable was paid: by the program, or by any other rail


def invoice(month: dict) -> dict:
    """One customer-month in, one invoice out: every line, the arithmetic that gave it and the rule that produced it.

    `month` (all but `plan` optional):
        plan                     none | team | business | enterprise. A plan is a contract: it brings the volume rates.
        month                    1 to 12: which month of the contract year this is (default 1)
        billed_to                "buyer" (default). Anything else is refused: the rated party never pays.
        evaluations              every evaluation run in the month, rejections included
        duplicates, infrastructure_failures, knos_retries      how many of those are free of charge
        accepted                 [{"deliverable": id, "value": "1200.00", "on_chain": false, "payee": "acme"}]  accepted this
                                 month, at the value the acceptance names. "on_chain": true says the program released it and
                                 took its fee then. "payee": who is paid; an outcome under 20 USD that names one is netted.
        disputed, reversed       [{"deliverable": id, "value": "...", "charged": "..."}]  this month's, or an earlier month's;
                                 "charged" is the fee the earlier invoice shows for it, when that is less than 0.30%
        record_lookups           lookups of a supplier's delivery record through the machine-priced API
        suppliers                suppliers connected (it costs nothing; the line says so)
        committed                the annual commitment, USD (default 0)
        drawn                    how much of it earlier months of this year already used
        credit_brought_forward   credit an earlier invoice could not use
        other                    [{"what": "...", "amount": "..."}]  agreed separately; a negative amount is a credit
        rail_charges             [{"what": "bank wire fees", "amount": "45.00"}]  what a payment rail charged, passed on as it
                                 was charged: listed apart, in no line and not in `total`; `payable` adds them
        held                     [{"kind": "reserve", "what": "...", "amount": "..."}]  money held or passed on (kind: reserve,
                                 rent or principal): listed apart, in no line, not in `total` and not in `payable`
    An accepted row may say "rail": "chain" (the same as "on_chain": true) or "bank" (the same as leaving it out).
    """
    if not isinstance(month, dict):
        raise BillingError("a customer-month is a JSON object")
    unknown = sorted(set(month) - FIELDS)
    if unknown:
        raise BillingError(f"not a field of a customer-month: {', '.join(unknown)}")
    if str(month.get("billed_to", PAYER)).strip().lower() != PAYER:
        raise BillingError(f"billed_to: {month['billed_to']!r}. {RULES['rated']} An invoice is the buyer's.")
    plan = _plan(month.get("plan"))
    volume = plan != "none"
    m = _count(month.get("month", 1), "month")
    if not 1 <= m <= 12:
        raise BillingError("month: 1 to 12, the month of the contract year")
    committed = money(month.get("committed", "0"), "committed")
    drawn = money(month.get("drawn", "0"), "drawn")
    brought = money(month.get("credit_brought_forward", "0"), "credit_brought_forward")
    if committed < 0 or drawn < 0 or brought < 0 or drawn > committed:
        raise BillingError("committed, drawn and credit_brought_forward are 0 or more, and drawn is at most committed")
    lines: list[dict] = []

    # 1. the subscription
    if plan != "none":
        part = part_of_year(CONTROL[plan], m)
        lines.append(_line("control", f"Control, {plan.capitalize()}", part, "enterprise" if plan == "enterprise" else "subscription",
                           f"month {m} of 12 of {show(CONTROL[plan])} a year"))
    if committed > 0:
        lines.append(_line("commitment", "Annual commitment", part_of_year(committed, m), "commitment", f"month {m} of 12 of {show(committed)} a year"))

    # 2. Meter: evaluations, less the ones nobody is charged for, less the free allowance
    evaluations = _count(month.get("evaluations", 0), "evaluations")
    free = {name: _count(month.get(name, 0), name) for name in ("duplicates", "infrastructure_failures", "knos_retries")}
    if sum(free.values()) > evaluations:
        raise BillingError("duplicates, infrastructure_failures and knos_retries are counted among the evaluations: together they exceed them")
    counted = evaluations - sum(free.values())
    billable = max(0, counted - METER_FREE)
    meter = cents(billable * METER_PRICE)
    if sum(free.values()):
        lines.append(_line("not_charged", "Evaluations not charged", ZERO, "free_of_charge",
                           f"{free['duplicates']:,} duplicates, {free['infrastructure_failures']:,} infrastructure failures, {free['knos_retries']:,} retries Knos caused"))
    lines.append(_line("meter", "Meter", meter, "meter", f"{evaluations:,} evaluations, {counted:,} counted, {min(counted, METER_FREE):,} free, {billable:,} at {METER_PRICE}",
                       counted=counted, billable=billable))

    # 3. Acceptance: each accepted deliverable once, less what is disputed or reversed this month; never what the chain released
    accepted: dict[str, Decimal] = {}
    payee: dict[str, str] = {}
    chain: set[str] = set()
    listed_again = banked = 0
    said_rail = False                     # a row named its rail: the invoice then says the once-on-either-rail rule as a line
    for ident, value, row in _valued(month.get("accepted"), "accepted"):
        if ident in accepted:
            listed_again += 1                       # the same deliverable again: counted once, at the value first given
            continue
        accepted[ident] = value
        if row.get("on_chain", False) not in (True, False):
            raise BillingError(f"accepted {ident}: on_chain is true or false")
        rail = str(row.get("rail", "chain" if row.get("on_chain", False) else "bank")).strip().lower()
        if rail not in RAILS or ("on_chain" in row and row["on_chain"] != (rail == "chain")):
            raise BillingError(f"accepted {ident}: rail is one of {', '.join(RAILS)}, and agrees with on_chain when both are given")
        said_rail = said_rail or "rail" in row
        if rail == "chain":
            chain.add(ident)
        else:
            banked += 1
        payee[ident] = str(row.get("payee") or "").strip()
    earlier: list[tuple[str, str, Decimal]] = []
    left_out = ZERO
    for kind in ("disputed", "reversed"):
        for ident, value, row in _valued(month.get(kind), kind):
            if ident in accepted:
                taken = min(value, accepted[ident])
                accepted[ident] -= taken
                left_out += taken
            else:
                fee = max(ACCEPT_FLOOR, cents(value * ACCEPT_RATE)) if value > 0 else ZERO
                if "charged" in row:
                    fee = min(fee, max(ZERO, money(row["charged"], f"{kind} {ident}, charged")))
                earlier.append((kind, ident, fee))
    released = sum((v for k, v in accepted.items() if k in chain), ZERO)
    reconciled = sum((v for k, v in accepted.items() if k not in chain), ZERO)
    below, acceptance, deliverables = released, ZERO, 0      # value released on chain lies first in the month
    small: dict[str, list[Decimal]] = {}                      # payee -> its outcomes under 20 USD: netted, one release each
    for ident, value in accepted.items():
        if ident in chain or value <= 0:
            continue
        deliverables += 1
        if value < NET_BELOW and payee[ident]:
            small.setdefault(payee[ident], []).append(value)
            continue
        acceptance += acceptance_fee(value, below, volume)
        below += value
    net = netted([(who, value) for who, values in small.items() for value in values], below, volume)
    acceptance += net["fee"]
    parts = [p for p in acceptance_parts(released + reconciled, volume) if p["of"] > 0]
    how = (f"{show(reconciled)} reconciled off chain over {deliverables:,} deliverables"
           + (f", above {show(released)} released on chain" if released else "")
           + (f"; the month's {show(released + reconciled)}: " + ", ".join(f"{show(p['of'])} at {p['rate']}" for p in parts) if parts else "")
           + (f"; {net['outcomes']:,} outcomes under {show(NET_BELOW)} netted into {len(net['releases']):,} releases: {show(net['fee'])}, "
              f"not {show(net['individually'])}" if small else "")
           + (f"; {listed_again:,} listed again and counted once" if listed_again else "")
           + (f"; {show(left_out)} disputed or reversed this month left out" if left_out else ""))
    lines.append(_line("acceptance", "Acceptance", acceptance, "volume" if volume and released + reconciled > ACCEPT_TIERS[1][0] else "netted" if small else "acceptance", how,
                       deliverables=deliverables, reconciled=show(reconciled), netted_outcomes=net["outcomes"], netted_releases=len(net["releases"])))
    if released:
        paid_there = cents(released * ACCEPT_RATE)
        lines.append(_line("on_chain", "Released on chain", ZERO, "on_chain",
                           f"{show(released)} over {len([k for k in chain if accepted[k] > 0]):,} deliverables; about {show(paid_there)} was paid to the program at release",
                           released=show(released)))
    if said_rail and released and banked:
        lines.append(_line("once_any_rail", "Acceptance, once on either rail", ZERO, "once_any_rail",
                           f"{len(chain):,} paid by the program, {banked:,} by another rail; none is charged on both"))

    # 4. Record lookups
    lookups = _count(month.get("record_lookups", 0), "record_lookups")
    records = cents(lookups * RECORD_PRICE)
    if lookups:
        lines.append(_line("record", "Record lookups", records, "record", f"{lookups:,} at {RECORD_PRICE}", lookups=lookups))
    usage = meter + acceptance + records

    # 5. the commitment pays for use first
    covered = min(usage, committed - drawn)
    if committed > 0:
        lines.append(_line("drawn", "Drawn from the commitment", -covered, "commitment",
                           f"{show(committed - drawn)} was left of {show(committed)}; {show(committed - drawn - covered)} is left", remaining=show(committed - drawn - covered)))

    # 6. connecting a supplier costs nothing
    suppliers = _count(month.get("suppliers", 0), "suppliers")
    if suppliers:
        lines.append(_line("suppliers", "Supplier connections", ZERO, "suppliers", f"{suppliers:,} connected"))

    # 7. credits: the volume rebate on what the chain released, and value disputed or reversed after the month it was charged in
    rebate = max(ZERO, cents(released * ACCEPT_RATE - acceptance_span(ZERO, released, volume)))
    charges = sum((_amount(row) for row in lines), ZERO)
    credit = brought + rebate + sum((fee for _k, _i, fee in earlier), ZERO)
    used = min(credit, max(ZERO, charges))
    if rebate:
        lines.append(_line("rebate", "Volume rebate on value released on chain", ZERO, "rebate",
                           f"0.30% of {show(released)} less the volume rates on it: {show(rebate)}, in the credit below", rebate=show(rebate)))
    if credit > 0:
        how = "; ".join([f"{kind} {ident}: {show(fee)}" for kind, ident, fee in earlier] + ([f"volume rebate {show(rebate)}"] if rebate else [])
                        + ([f"{show(brought)} brought forward"] if brought else []))
        lines.append(_line("credit", "Credit", -used, "credit" if earlier or brought else "rebate", how, carried_forward=show(credit - used)))

    # 8. anything agreed separately
    for n, row in enumerate(month.get("other") or [], 1):
        if not isinstance(row, dict) or not str(row.get("what", "")).strip():
            raise BillingError(f"other {n}: needs a `what`")
        what = str(row["what"]).strip()
        lines.append(_line("other", what, money(row.get("amount", "0"), f"other {n}, amount"), "pilot" if "pilot" in what.lower() else "separate"))

    total = sum((_amount(row) for row in lines), ZERO)
    rails = []
    for n, row in enumerate(month.get("rail_charges") or [], 1):
        if not isinstance(row, dict) or not str(row.get("what", "")).strip():
            raise BillingError(f"rail_charges {n}: needs a `what`")
        charge = money(row.get("amount", "0"), f"rail_charges {n}, amount")
        if charge < 0:
            raise BillingError(f"rail_charges {n}: a charge is 0 or more")
        rails.append({"what": str(row["what"]).strip(), "amount": show(charge), "rule": RULES["rails"]})
    rail_total = sum((_amount(row) for row in rails), ZERO)
    held = []
    for n, row in enumerate(month.get("held") or [], 1):
        if not isinstance(row, dict) or str(row.get("kind", "")).strip().lower() not in HELD:
            raise BillingError(f"held {n}: kind is one of {', '.join(HELD)}")
        amount = money(row.get("amount", "0"), f"held {n}, amount")
        if amount < 0:
            raise BillingError(f"held {n}: an amount is 0 or more")
        held.append({"kind": str(row["kind"]).strip().lower(), "what": str(row.get("what") or row["kind"]).strip(), "amount": show(amount), "rule": RULES["held"]})
    return {
        "billed_to": PAYER, "currency": "USD", "plan": plan, "month": m,
        **({k: month[k] for k in ("customer", "period") if k in month}),
        "lines": lines, "total": show(total),
        "rail_charges": rails, "rail_total": show(rail_total), "payable": show(total + rail_total),
        "held": held, "held_total": show(sum((_amount(row) for row in held), ZERO)),
        "credit_carried_forward": show(credit - used),
        "commitment_remaining": show(committed - drawn - covered),
        "rules": [RULES["on_chain"], RULES["suppliers"], RULES["rated"], RULES["devnet"]],
        "note": "An estimate at proposed prices. Nothing has been sold and there is no legal entity to invoice from.",
    }


def estimate(plan: str, evaluations: int, accepted_per_year: Any, on_chain_percent: int = 0, lookups: int = 0, committed: Any = "0") -> dict:
    """A year at the price book, from what a buyer knows before work starts: the plan, evaluations a month, accepted
    value a year, the share of it released on chain (a whole percentage) and record lookups a month. The limits shown
    before work starts are this. It assumes twelve equal months and no deliverable small enough to pay the floor;
    `invoice` works a real month, deliverable by deliverable."""
    plan = _plan(plan)
    evaluations, lookups, share = _count(evaluations, "evaluations"), _count(lookups, "record lookups"), _count(on_chain_percent, "the share released on chain")
    value, committed = money(accepted_per_year, "accepted value a year"), money(committed, "committed")
    if value < 0 or committed < 0 or share > 100:
        raise BillingError("accepted value and committed are 0 or more, and the share released on chain is 0 to 100")
    volume = plan != "none"
    billable = max(0, evaluations - METER_FREE)
    meter = cents(billable * METER_PRICE * 12)
    released = (value * share / 100).quantize(CENT, rounding=ROUND_DOWN)
    reconciled = value - released
    acceptance = cents(acceptance_span(released, reconciled, volume, 12))
    paid_on_chain = cents(released * ACCEPT_RATE)
    rebate = max(ZERO, cents(released * ACCEPT_RATE - acceptance_span(ZERO, released, volume, 12)))
    records = cents(lookups * RECORD_PRICE * 12)
    usage = meter + acceptance + records
    over = max(ZERO, usage - committed)                 # use beyond what the commitment covers
    charges = CONTROL[plan] + committed + over
    used = min(rebate, charges)
    total = charges - used
    tiers = [{"rate": p["rate"], "of": show(p["of"]), "fee": show(p["fee"])} for p in acceptance_parts(value / 12, volume)]
    return {
        "plan": plan, "evaluations_a_month": evaluations, "accepted_a_year": show(value), "on_chain_percent": share, "lookups_a_month": lookups,
        "committed": show(committed), "billable_a_month": billable, "volume_rates": volume,
        "control": show(CONTROL[plan]), "meter": show(meter), "released_on_chain": show(released), "reconciled": show(reconciled),
        "acceptance": show(acceptance), "paid_on_chain": show(paid_on_chain), "rebate": show(used), "records": show(records), "usage": show(usage),
        "tiers_a_month": tiers, "total": show(total), "benefit_to_demand": show(total * BENEFIT_RULE),
        "deliverable": plan != "enterprise",
    }


def explain(inv: dict) -> list[str]:
    """An invoice in plain lines: each line, how it was reached, and the rule that produced it."""
    out = [f"Invoice for month {inv['month']} of the contract year, billed to the buyer, in USD. Plan: {inv['plan']}."]
    for row in inv["lines"]:
        out.append(f"  {row['what']:<42} {row['amount']:>14}")
        if row["how"]:
            out.append(f"      how:  {row['how']}")
        out.append(f"      rule: {row['rule']}")
    out.append(f"  {'Total':<42} {inv['total']:>14}")
    if inv.get("rail_charges"):
        out.append("Rail charges, apart from the software price:")
        out += [f"  {row['what']:<42} {row['amount']:>14}" for row in inv["rail_charges"]]
        out += [f"      rule: {RULES['rails']}", f"  {'Payable in all':<42} {inv['payable']:>14}"]
    if inv.get("held"):
        out.append("Held or passed on, never revenue:")
        out += [f"  {row['what']:<42} {row['amount']:>14}" for row in inv["held"]]
        out.append(f"      rule: {RULES['held']}")
    if inv["credit_carried_forward"] != "0.00":
        out.append(f"  Credit carried forward: {inv['credit_carried_forward']}")
    if inv["commitment_remaining"] != "0.00":
        out.append(f"  Commitment left: {inv['commitment_remaining']}")
    out += [*inv["rules"], inv["note"]]
    return out


def estimate_lines(e: dict) -> list[str]:
    tiers = ", ".join(f"{t['of']} at {t['rate']}" for t in e["tiers_a_month"] if t["of"] != "0.00") or "nothing accepted"
    return [
        f"A year at the price book: {e['plan']}, {e['evaluations_a_month']:,} evaluations a month, {e['accepted_a_year']} accepted a year, "
        f"{e['on_chain_percent']}% of it released on chain, {e['lookups_a_month']:,} record lookups a month.",
        f"  {'Control':<42} {e['control']:>14}" + ("" if e["deliverable"] else "  (from; not deliverable yet)"),
        f"  {'Meter':<42} {e['meter']:>14}  ({e['billable_a_month']:,} billable a month at {METER_PRICE}, 12 months)",
        f"  {'Acceptance, reconciled off chain':<42} {e['acceptance']:>14}  (on {e['reconciled']}; a month: {tiers})",
        f"  {'Acceptance, paid on chain at release':<42} {'not invoiced':>14}  ({e['paid_on_chain']} on {e['released_on_chain']}; never charged again)",
        *([f"  {'Volume rebate on value released on chain':<42} {'-' + e['rebate']:>14}"] if e["rebate"] != "0.00" else []),
        f"  {'Record lookups':<42} {e['records']:>14}",
        *([f"  {'Annual commitment':<42} {e['committed']:>14}  (use is drawn from it first)"] if e["committed"] != "0.00" else []),
        f"  {'Total a year':<42} {e['total']:>14}",
        f"Demand a measured benefit of {BENEFIT_RULE} to 1 before buying: {e['benefit_to_demand']} a year.",
        RULES["suppliers"], RULES["rated"], RULES["devnet"],
        "An estimate at proposed prices. Nothing has been sold and there is no legal entity to invoice from.",
    ]


# ---- gross margin: what a month's lines cost Knos to deliver, from a unit-cost file --------------------------------------
COST_FIELDS = ("evaluation", "accepted_deliverable", "record_lookup", "control_year")
MORE_COSTS = {"pair_month": ZERO, "payee_account": Decimal("0.18"), "control_year_target": Decimal(7_000), "release_chain": Decimal("0.0072")}
#   optional in a unit-cost file: one anchored batch for one buyer-supplier pair in a month; the rent of a payee's first token
#   account; what a year of Control has to cost once onboarding is self-service (a target, not a measurement); the chain fees
#   of one order funded and paid (12 transactions, measured in the simulator)
TARGET = Decimal("0.95")                 # the GROSS margin each line is held to in `leaks`
GROSS = ("Every margin here is GROSS: revenue less the direct cost of delivering it, over revenue. Operating margin also subtracts "
         "building, selling and administering; nobody is employed and nothing is sold, so none of that is known and no operating margin is printed.")
WORKED: dict[str, Any] = {"plan": "business", "evaluations": 110_000, "accepted": "10000000.00", "suppliers": 5, "deliverable": "20000.00"}
#   the worked customer of docs/MARKET.md, section 6: 130,240 a year
SENSITIVITY_BPS = (30, 20, 10, 5)        # the realised Acceptance rates `sensitivity` works, in basis points
SUPPORT_RATES = (("the assumption docs/UNIT_COSTS.md has always used", Decimal(75)),
                 ("a computer support specialist's median wage, 30.24 an hour (BLS, May 2025), over wages' 70.0% share of an employer's cost (BLS, June 2026)",
                  Decimal("43.20")))
#   https://www.bls.gov/ooh/computer-and-information-technology/computer-support-specialists.htm and https://www.bls.gov/news.release/ecec.nr0.htm
SECOND: dict[str, Any] = {"plan": "business", "evaluations": 1_000_000, "accepted": "120000000.00", "suppliers": 5, "deliverable": "20000.00"}
#   the second worked customer: 120 million accepted a year in twelve even months, 1 million evaluations a month, no record lookups
SPLIT_AMOUNTS = (5, 20, 100, 1_000)      # whole test USDC: the releases `floor_split` works
REMEDY = (5, 100)                        # `floor_remedy`: outcomes of 5 test USDC, 100 of them to one payee in a period
NET_EXAMPLE = (Decimal("0.99"), 100)     # the outcome `netting_example` works, and how many of them one payee is owed in a period


def unit_costs(doc: Any) -> dict[str, Decimal]:
    """The four unit costs of a unit-cost file (docs/unit_costs.json is one): {"costs": {name: {"usd": "0.0002", ...}}}
    or {name: "0.0002"}. A cost may have any number of decimals; it is never a float."""
    rows = doc.get("costs", doc) if isinstance(doc, dict) else None
    if not isinstance(rows, dict):
        raise BillingError("a unit-cost file is a JSON object")
    out = {}
    for name in (*COST_FIELDS, *MORE_COSTS):
        raw = rows.get(name, str(MORE_COSTS[name]) if name in MORE_COSTS else None)
        raw = raw.get("usd") if isinstance(raw, dict) else raw
        if isinstance(raw, (bool, float)) or raw is None:
            raise BillingError(f"unit cost {name}: write it as a string like \"0.0002\"")
        try:
            out[name] = Decimal(str(raw))
        except InvalidOperation:
            raise BillingError(f"unit cost {name}: {raw!r} is not an amount") from None
        if not out[name].is_finite() or out[name] < 0:
            raise BillingError(f"unit cost {name}: 0 or more")
    return out


def margin(month: dict, costs: Any) -> dict:
    """Revenue, direct cost and gross margin of one customer-month, line by line. Every counted evaluation costs
    something to deliver, the free ones too, and the month's batch is anchored once for each supplier connected (the
    file's `pair_month`); a deliverable released on chain is in no line (its fee is the program's, and on devnet that
    is test money). With it: who earns what at the floor under both builds of the program (`floor_split`) and what a
    small outcome pays by itself and netted (`netting_example`)."""
    inv, unit = invoice(month), unit_costs(costs)
    measured = measured_parts(costs)
    by = {row["line"]: row for row in inv["lines"]}
    rows = []

    def add(key: str, what: str, revenue: Decimal, units: Any, cost: Decimal) -> None:
        cost = cents(cost)
        rows.append({"line": key, "what": what, "units": units, "revenue": show(revenue), "direct_cost": show(cost), "gross": show(revenue - cost),
                     "margin": f"{(revenue - cost) / revenue * 100:.1f}%" if revenue > 0 else "none: no revenue"})

    if "control" in by:
        add("control", by["control"]["what"], _amount(by["control"]), "1 month of 12", unit["control_year"] / 12)
    pairs = _count(month.get("suppliers", 0), "suppliers") if by["meter"]["counted"] else 0
    add("meter", "Meter", _amount(by["meter"]), by["meter"]["counted"], by["meter"]["counted"] * unit["evaluation"] + pairs * unit["pair_month"])
    add("acceptance", "Acceptance", _amount(by["acceptance"]), by["acceptance"]["deliverables"], by["acceptance"]["deliverables"] * unit["accepted_deliverable"])
    if "record" in by:
        add("record", "Record lookups", _amount(by["record"]), by["record"]["lookups"], by["record"]["lookups"] * unit["record_lookup"])
    revenue = sum((Decimal(r["revenue"].replace(",", "")) for r in rows), ZERO)
    cost = sum((Decimal(r["direct_cost"].replace(",", "")) for r in rows), ZERO)
    return {"plan": inv["plan"], "month": inv["month"], "lines": rows, "revenue": show(revenue), "direct_cost": show(cost), "gross": show(revenue - cost),
            "margin": f"{(revenue - cost) / revenue * 100:.1f}%" if revenue > 0 else "none: no revenue",
            "free_tier_year": show(12 * (METER_FREE * unit["evaluation"] + pairs * unit["pair_month"])),
            "floor": floor_split(unit["payee_account"]), "netting": netting_example(), "remedy": floor_remedy(),
            "kind": "gross", "operating": "not computed: no operating cost is known", "gross_note": GROSS,
            "leaks": leaks(by, pairs, unit, measured), "second": second_customer(unit), "gaps": gaps(unit), "cash": cash_example(unit),
            "note": ("Revenue is the lines before credits, the commitment and anything agreed separately. Direct cost is the unit-cost file's, and "
                     "a cost it marks as a budget is a budget, not a measurement. Nothing has been sold.")}


def measured_parts(doc: Any) -> dict[str, Decimal]:
    """The part of each unit cost that the file marks as measured: all of a cost whose kind is "measured", the sum of
    `of_which_measured` of one that is a budget, and nothing where the file does not say."""
    rows = doc.get("costs", doc) if isinstance(doc, dict) else {}
    out = {}
    for name, row in rows.items():
        if isinstance(row, dict) and row.get("kind") == "measured":
            out[name] = Decimal(str(row["usd"]))
        elif isinstance(row, dict):
            out[name] = sum((Decimal(str(v)) for v in (row.get("of_which_measured") or {}).values()), ZERO)
    return out


def _pct(revenue: Decimal, cost: Decimal) -> str:
    return f"{(revenue - cost) / revenue * 100:.1f}%" if revenue > 0 else "none: no revenue"


def meter_break_even(unit: dict[str, Decimal], pairs: int, target: Decimal = TARGET) -> int | None:
    """The least count of evaluations a month at which the Meter line reaches `target` gross at these unit costs: every
    counted evaluation costs `evaluation`, each supplier's batch `pair_month`, and only those past the free ones earn."""
    keep = METER_PRICE * (1 - target) - unit["evaluation"]          # what one more billable evaluation leaves toward the fixed part
    if keep <= 0:
        return None
    need = (METER_FREE * METER_PRICE * (1 - target) + pairs * unit["pair_month"]) / keep
    return int(need.to_integral_value(rounding="ROUND_CEILING"))


def leaks(by: dict, pairs: int, unit: dict[str, Decimal], measured: dict[str, Decimal]) -> dict:
    """The three places a line earns less than `TARGET` gross, each with its number and the design that closes it.
    meter: what one delivered evaluation may cost for the month's Meter line to keep 95%, what it costs at the file's
    budget, what the measured part of that is, and the count from which the budget meets it. control: the budget, the
    target once onboarding is self-service, and the margin at each. The floor is `floor_split` and `floor_remedy`."""
    counted, revenue = by["meter"]["counted"], _amount(by["meter"])
    cost = counted * unit["evaluation"] + pairs * unit["pair_month"]
    known = counted * measured.get("evaluation", ZERO) + pairs * measured.get("pair_month", ZERO)
    allowed = revenue * (1 - TARGET)
    meter = {"evaluations": counted, "revenue": show(revenue), "cost": show(cost), "gross_margin": _pct(revenue, cents(cost)),
             "allowed_cost": show(allowed), "allowed_each": f"{allowed / counted:.7f}" if counted else "none",
             "cost_each": f"{cost / counted:.7f}" if counted else "none", "meets": bool(counted) and cost <= allowed,
             "measured_cost": show(known), "measured_each": f"{known / counted:.7f}" if counted else "none",
             "measured_meets": bool(counted) and known <= allowed, "gross_margin_measured_only": _pct(revenue, known),
             "ceiling_each_at_scale": f"{METER_PRICE * (1 - TARGET):.4f}", "reaches_at": meter_break_even(unit, pairs),
             "design": "one anchored batch a supplier a month, a ledger event of 370 bytes, reconciliation each side runs itself"}
    year, now, want = CONTROL["business"], unit["control_year"], unit["control_year_target"]
    control = {"plan": "business", "price": show(year), "cost": show(now), "gross_margin": _pct(year, now), "target_cost": show(want),
               "gross_margin_at_target": _pct(year, want), "to_remove": show(now - want), "ceiling_at_95": show(year * (1 - TARGET)),
               "design": "self-service onboarding: the buyer copies one pinned workflow file and runs `knos shadow` on its first invoice; a supplier runs `knos preflight`; support is pooled"}
    return {"target": f"{TARGET * 100:.0f}%", "meter": meter, "control": control}


def second_customer(unit: dict[str, Decimal] | None = None) -> dict:
    """The second worked customer (SECOND), as a year at the price book and, with unit costs, as a gross margin: Control
    100,000 + Acceptance 12 x (1M x 0.30% + 9M x 0.20%) = 252,000 + Meter 12 x 900,000 x 0.002 = 21,600 = 373,600. No
    record revenue. `hurdle`: three times the price, a benefit a pilot has to measure; nothing shows any buyer gets it."""
    e = estimate(SECOND["plan"], SECOND["evaluations"], SECOND["accepted"])
    total = Decimal(e["total"].replace(",", ""))
    out = {"plan": e["plan"], "evaluations_a_month": e["evaluations_a_month"], "accepted_a_year": e["accepted_a_year"], "control": e["control"],
           "acceptance": e["acceptance"], "meter": e["meter"], "records": e["records"], "total": e["total"], "hurdle": e["benefit_to_demand"],
           "hurdle_is": "a hurdle to be measured in a pilot, not a claim", "cost_ceiling_at_95": show(total * (1 - TARGET))}
    if unit is not None:
        n, parts = _year_cost(SECOND, unit)
        cost = sum(parts.values(), ZERO)
        at_target = cost - unit["control_year"] + unit["control_year_target"]
        out |= {"suppliers": SECOND["suppliers"], "deliverables": n, "direct_cost": show(cost), "gross_margin": _pct(total, cents(cost)),
                "direct_cost_at_control_target": show(at_target), "gross_margin_at_control_target": _pct(total, cents(at_target)),
                "cost_by_line": {k: show(v) for k, v in parts.items()}}
    return out


def _year_cost(customer: dict, unit: dict[str, Decimal]) -> tuple[int, dict[str, Decimal]]:
    """What a worked customer's year costs to deliver, by line: Control's budget, every evaluation and each supplier's
    monthly batch, and each accepted deliverable. The count of deliverables comes first."""
    n = int(money(customer["accepted"]) / money(customer["deliverable"]))
    return n, {"control": unit["control_year"], "meter": 12 * (customer["evaluations"] * unit["evaluation"] + customer["suppliers"] * unit["pair_month"]),
               "acceptance": n * unit["accepted_deliverable"]}


def sensitivity(unit: dict[str, Decimal], rates: tuple = SENSITIVITY_BPS) -> dict:
    """Pricing power: each worked customer's year at a REALISED Acceptance rate of `rates` basis points, the rate that is
    left of the price book once volume rebates, credits for disputed or reversed value and any discount are applied.
    Control, Meter and direct cost do not move with the rate; revenue and gross margin do. `book_bps` is what the price
    book itself realises for that customer; a rate above it is printed and marked: the book does not reach it."""
    out = []
    for name, c in (("the worked customer", WORKED), ("the second worked customer", SECOND)):
        e = estimate(c["plan"], c["evaluations"], c["accepted"])
        value = money(c["accepted"])
        fixed = Decimal(e["control"].replace(",", "")) + Decimal(e["meter"].replace(",", "")) + Decimal(e["records"].replace(",", ""))
        book = (Decimal(e["acceptance"].replace(",", "")) - Decimal(e["rebate"].replace(",", ""))) / value * 10_000
        cost = cents(sum(_year_cost(c, unit)[1].values(), ZERO))
        rows = []
        for bps in rates:
            acceptance = cents(value * bps / 10_000)
            revenue = fixed + acceptance
            rows.append({"bps": bps, "acceptance": show(acceptance), "revenue": show(revenue), "gross": show(revenue - cost), "gross_margin": _pct(revenue, cost),
                         "acceptance_share": share(acceptance, revenue), "above_book": Decimal(bps) > book})
        out.append({"customer": name, "plan": c["plan"], "accepted_a_year": e["accepted_a_year"], "evaluations_a_month": c["evaluations"],
                    "fixed": show(fixed), "direct_cost": show(cost), "book_bps": f"{book:.1f}", "one_bps": show(value / 10_000), "rows": rows})
    return {"rates_bps": list(rates), "customers": out, "kind": "gross",
            "realised": "the Acceptance rate left after volume rebates, credits for disputed or reversed value and discounts",
            "note": "Examples at the price book's prices; no such customer exists and nothing has been sold. Direct cost is the unit-cost file's budget."}


def sensitivity_lines(s: dict) -> list[str]:
    out = [f"Pricing power: the worked customers' year at a realised Acceptance rate of {', '.join(str(r) for r in s['rates_bps'])} bps.",
           f"Realised: {s['realised']}. Control, Meter and direct cost stay where they are. USD a year.", GROSS]
    for c in s["customers"]:
        out += ["", f"{c['customer'].capitalize()}: {c['plan']}, {c['evaluations_a_month']:,} evaluations a month, {c['accepted_a_year']} accepted a year. "
                f"The price book realises {c['book_bps']} bps; one bps is {c['one_bps']}.",
                f"  Control, Meter and Record: {c['fixed']}. Direct cost: {c['direct_cost']}.",
                f"  {'bps':>4} {'Acceptance':>14} {'revenue':>14} {'gross':>14}  gross margin  Acceptance's share"]
        out += [f"  {r['bps']:>4} {r['acceptance']:>14} {r['revenue']:>14} {r['gross']:>14}  {r['gross_margin']:>12}  {r['acceptance_share']:>8}"
                + ("  (above the book's own rate: not reached)" if r["above_book"] else "") for r in c["rows"]]
    w = s["customers"][-1]
    out += ["", f"Defending the rate matters more than shaving verification time: each bps given up costs {w['customer']} {w['one_bps']} a year, "
            f"and its whole direct cost is {w['direct_cost']}.",
            "What would defend it, measured separately: recoveries, avoided labour, financing benefit. None is measured.", s["note"]]
    return out


def release_split(amount: int, relayer: str = "outside", first: bool = False, unit: dict[str, Decimal] | None = None) -> dict:
    """One release on chain, in the token's base units (6 decimals), under knos_pay 2.2, counted once. The funder pays
    the fee on top of the amount; the amount is the payee's principal and is never revenue. Out of the fee the relayer
    takes its tip (0.30 on a payee's first payment, when it also puts up the token account's rent). With an OUTSIDE
    relayer, Knos's revenue is the fee owner's part and the chain costs are the relayer's, paid out of its tip: none is
    Knos's cost. When KNOS relays, the whole fee is Knos's revenue and the chain costs and the rent are its cost. The
    tip is never Knos's revenue and Knos's cost at once. On devnet all of it is test money: 0 revenue."""
    from . import fees
    from .settle.v2 import pay

    if relayer not in ("outside", "knos"):
        raise BillingError("relayer: outside or knos")
    if isinstance(amount, bool) or not isinstance(amount, int) or amount < pay.ORDER_MIN_AMOUNT:
        raise BillingError(f"amount: base units, at least {pay.ORDER_MIN_AMOUNT:,}")
    unit = unit or {"release_chain": MORE_COSTS["release_chain"], "payee_account": MORE_COSTS["payee_account"]}
    fee = Decimal(fees.NEW.order(amount)) / 1_000_000
    tip = Decimal(min(pay.TIP_FIRST if first else pay.TIP, fees.NEW.order(amount))) / 1_000_000
    chain = unit["release_chain"] + (unit["payee_account"] if first else ZERO)
    mine = relayer == "knos"
    revenue, cost = (fee, chain) if mine else (fee - tip, ZERO)
    return {"build": fees.NEW.build, "relayer": relayer, "first": first, "amount": show(Decimal(amount) / 1_000_000), "principal_is_revenue": False,
            "fee": show(fee), "tip": show(tip), "relayer_revenue": show(ZERO if mine else tip), "relayer_cost": f"{ZERO if mine else chain:.4f}",
            "revenue": show(revenue), "direct_cost": f"{cost:.4f}", "devnet": RULES["devnet"], "rule": RULES["relayer"]}


def ceilings(target: Decimal = TARGET) -> list[dict]:
    """The most one unit may cost to deliver and keep `target` gross, at its price: an evaluation past the free ones; 10,000
    settled at 20 bps (by contract, above the month's first million); a year of Business Control."""
    keep = 1 - target
    units = (("evaluation", METER_PRICE), ("10,000 settled at 0.20%", Decimal(10_000) * ACCEPT_TIERS[-1][1]), ("Control, Business, a year", CONTROL["business"]))
    return [{"unit": what, "price": f"{price.normalize():f}", "ceiling": f"{(price * keep).normalize():f}"} for what, price in units]


def support_hours(budget: Decimal = Decimal(5_000), rates: tuple = SUPPORT_RATES) -> list[dict]:
    """What a delivery budget buys in hours of a person, at each rate in `rates` (USD an hour): see SUPPORT_RATES."""
    return [{"rate": show(rate), "hours": f"{budget / rate:.1f}", "hours_a_month": f"{budget / rate / 12:.1f}", "what": what} for what, rate in rates]


def floor_remedy(value: int = REMEDY[0], count: int = REMEDY[1]) -> dict:
    """Netting as the remedy for the floor, under knos_pay 2.2: `count` outcomes of `value` test USDC to one payee in a
    period, released one by one and as one netted release. One by one the tip is the whole fee each time; netted,
    the tip is paid once and the rate applies to the sum."""
    from . import fees
    from .settle.v2 import pay

    unit, r = 1_000_000, fees.NEW
    u = lambda n: show(Decimal(n) / unit)      # noqa: E731
    one = r.order(value * unit)
    net = r.order(value * count * unit)
    return {"build": r.build, "value": show(Decimal(value)), "count": count,
            "one_by_one": {"releases": count, "fee": u(one * count), "tips": u(min(pay.TIP, one) * count), "fee_owner": u((one - min(pay.TIP, one)) * count)},
            "netted": {"releases": 1, "amount": show(Decimal(value * count)), "fee": u(net), "tips": u(min(pay.TIP, net)), "fee_owner": u(net - min(pay.TIP, net))}}


def floor_split(payee_account: Decimal = MORE_COSTS["payee_account"], amounts: tuple = SPLIT_AMOUNTS) -> list[dict]:
    """Who earns what on a release of each size, under both builds of knos_pay (knos.fees: 2.1 charges the 0.3.14 fee,
    2.2 the 0.3.18 one; `knos status` says which is live). The fee is the funder's, on top. Out of it the relayer takes
    its tip (0.05, or 0.30 when the paying transaction created the payee's token account, never more than the fee) and
    the fee owner keeps the rest. `payee_account` is the rent the relayer puts up for that account, in USD: on a first
    payment its tip less that rent is what it nets. `nothing_at`: the largest release that leaves the fee owner 0."""
    from . import fees
    from .settle.v2 import pay

    unit, out = 1_000_000, []
    u = lambda n: Decimal(n) / unit      # noqa: E731

    def most(r: Any, tip: int) -> str:
        """The largest whole-cent order, from the least an order holds, whose fee is no more than `tip`: "none" when even that one earns."""
        lo, hi = pay.ORDER_MIN_AMOUNT // 10_000, pay.MAX_AMOUNT // 10_000
        if r.order(lo * 10_000) > tip:
            return "none"
        while lo < hi:
            mid = (lo + hi + 1) // 2
            lo, hi = (mid, hi) if r.order(mid * 10_000) <= tip else (lo, mid - 1)
        return show(Decimal(lo) / 100)

    for r in (fees.OLD, fees.NEW):
        rows = []
        for a in amounts:
            fee = r.order(a * unit)
            tip, first = min(pay.TIP, fee), min(pay.TIP_FIRST, fee)
            rows.append({"amount": show(Decimal(a)), "fee": show(u(fee)), "share": share(u(fee), Decimal(a)), "tip": show(u(tip)), "fee_owner": show(u(fee - tip)),
                         "first_tip": show(u(first)), "first_relayer_net": show(u(first) - payee_account), "first_fee_owner": show(u(fee - first))})
        out.append({"build": r.build, "release": r.release, "rate": r.rate(), "rows": rows, "account": show(payee_account),
                    "nothing_at": most(r, pay.TIP), "first_nothing_at": most(r, pay.TIP_FIRST)})
    return out


def netting_example(value: Decimal = NET_EXAMPLE[0], count: int = NET_EXAMPLE[1]) -> dict:
    """What an outcome of `value` (under 20 USD) costs in fees by itself, and as one of `count` owed to one payee in a
    period. By itself it pays the floor; netted, the release pays 0.30% of the netted amount and the floor once.
    `reaches_rate`: how many such outcomes one payee needs in a period before the floor stops being the fee, counted as
    knos_pay counts: in the token's base units (6 decimals), the rate's fee rounded down, against the floor's 50,000 units."""
    alone = acceptance_fee(value)
    net = netted([("payee", value)] * count)
    units, floor_units = int(value * 10**6), int(ACCEPT_FLOOR * 10**6)
    need = next(n for n in range(1, 10_000) if int(units * n * ACCEPT_RATE) > floor_units)
    return {"value": show(value), "alone_fee": show(alone), "alone_share": share(alone, value), "count": count, "netted_amount": net["releases"][0]["amount"],
            "netted_fee": show(net["fee"]), "netted_share": net["releases"][0]["share"], "individually": show(net["individually"]),
            "one_in_a_period": share(netted([("payee", value)])["fee"], value), "reaches_rate": need,
            "on_chain_least": show(Decimal(5)), "floor": show(ACCEPT_FLOOR)}


# ---- 0.3.22: the budget today against what the price book requires; the gross fee against the cash Knos keeps ----------------
DELIVERABLE_TARGET = Decimal("0.02")     # what one accepted deliverable may cost to deliver: a target nobody has reached
GAP_DESIGN = {
    "evaluation": "one anchored batch a supplier a month (`knos meter batch`); each side reconciles itself (`knos meter reconcile`); no person in the routine path",
    "accepted_deliverable": "exceptions are self-service: a difference is a named line the two parties settle (`knos statement verify`); "
                            "outcomes under 20 USD are netted into one release; a person deciding a dispute is a separate service at a separate price",
    "record_lookup": "anyone runs `knos record serve`; Knos hosts none, so Knos carries no cost and books no revenue",
    "control_business": "self-service onboarding: one pinned workflow file, `knos shadow` on the first invoice, `knos preflight` for suppliers; support is pooled",
    "control_team": "the same self-service path; a Team account gets no named person",
    "release_at_floor": "netting: one release a payee a period; an outside relayer pays the chain fees out of its tip",
}


def _smallest(price_rate: Decimal, cost: Decimal, target: Decimal = TARGET) -> str:
    """The least deliverable (USD, to the cent, rounded up) whose Acceptance fee at `price_rate` leaves `target` gross over `cost`."""
    least = cost / (price_rate * (1 - target))
    return show(least.quantize(CENT, rounding="ROUND_CEILING"))


def _plain(d: Decimal) -> str:
    """15000 -> "15,000"; 0.1 -> "0.10"; 0.0000893 -> "0.0000893"."""
    if d == d.to_integral_value():
        return f"{int(d):,}"
    text = f"{d.normalize():f}"
    return text if len(text.split(".")[1]) >= 2 else f"{d:.2f}"


def gaps(unit: dict[str, Decimal], target: Decimal = TARGET) -> list[dict]:
    """Each unit's cost to deliver: what the unit-cost file budgets TODAY against what the price book REQUIRES for `target`
    gross, the gap between them and the design that closes it. `required` is arithmetic on the price book, except an
    accepted deliverable's, which is a target (DELIVERABLE_TARGET): its row says from what deliverable each cost keeps
    `target`. Every budget is a budget, not a measurement; nothing has been sold."""
    keep = 1 - target
    second = SECOND["evaluations"]
    billable = second - METER_FREE
    per_eval = (billable * METER_PRICE * keep - SECOND["suppliers"] * unit["pair_month"]) / second
    floor_fee = ACCEPT_FLOOR
    rows = [
        ("evaluation", "one evaluation delivered, free ones included, at 1,000,000 a month and five suppliers (the second worked customer)",
         unit["evaluation"], per_eval.quantize(Decimal("0.0000001"), rounding=ROUND_DOWN),
         "0.002 × 900,000 billable × 5%, less five monthly batches, over 1,000,000 delivered"),
        ("accepted_deliverable", "one accepted deliverable reconciled off chain", unit["accepted_deliverable"], DELIVERABLE_TARGET,
         f"a target: at {DELIVERABLE_TARGET} a deliverable keeps {target * 100:.0f}% gross from {_smallest(ACCEPT_RATE, DELIVERABLE_TARGET, target)} at 0.30% "
         f"({_smallest(ACCEPT_TIERS[-1][1], DELIVERABLE_TARGET, target)} at 0.20%); at {_plain(unit['accepted_deliverable'])} only from "
         f"{_smallest(ACCEPT_RATE, unit['accepted_deliverable'], target)} ({_smallest(ACCEPT_TIERS[-1][1], unit['accepted_deliverable'], target)})"),
        ("record_lookup", "one record lookup", unit["record_lookup"], RECORD_PRICE * keep, "0.10 × 5%"),
        ("control_business", "Control, Business, a year of onboarding and support", unit["control_year"], CONTROL["business"] * keep, "100,000 × 5%"),
        ("control_team", "Control, Team, a year of onboarding and support", None, CONTROL["team"] * keep, "25,000 × 5%"),
        ("release_at_floor", "the chain fees of one release at the 0.05 floor, when Knos relays", unit["release_chain"], floor_fee * keep, "0.05 × 5%"),
    ]
    out = []
    for key, what, budget, need, how in rows:
        need = need.normalize()
        gap = None if budget is None else budget - need
        out.append({"unit": key, "what": what, "budget": "not budgeted" if budget is None else _plain(budget), "required": _plain(need), "how": how,
                    "gap": "unknown" if gap is None else ("none" if gap <= 0 else _plain(gap)),
                    "meets": None if gap is None else gap <= 0, "kind": "budget, not measured" if key not in ("release_at_floor",) else "measured in the simulator",
                    "design": GAP_DESIGN[key]})
    return out


CASH_RULE = ("The gross protocol fee is not the cash Knos keeps. Cash kept = the gross fee - the tips outside relayers take out of it - discounts "
             "and volume rebates - credits for disputed, reversed or failed work - channel commissions on what is left. "
             "A fee counter on chain counts the gross fee in the fee owner's token accounts: it is not company cash, and on devnet it is test money, 0 revenue.")
CASH_EXAMPLE: dict[str, Any] = {"releases": 100, "amount": 1_000, "first_payments": 10, "discount": "0.10", "credits": "3.00", "channel": "0.20"}
#   an example, not a customer: 100 releases of 1,000 test USDC by outside relayers, 10 of them a payee's first payment; a 10% discount
#   [assumption]; 3.00 credited for one reversed release [assumption]; a channel partner taking 20% of what is left [assumption]


def cash_kept(gross: Any, tips: Any = "0", discounts: Any = "0", credits: Any = "0", channel_rate: Any = "0") -> dict:
    """From the gross protocol fee to the cash Knos keeps, step by step (CASH_RULE). `tips`: what outside relayers took
    out of the fee (a relayer Knos runs takes none); `discounts`: discounts and volume rebates given back; `credits`:
    credits for disputed, reversed or failed work; `channel_rate`: the share of what is left a reseller or partner is
    paid. What is left may be below zero, and is shown so: it is never floored to make the line look earned."""
    g, t, d, c = (money(v, w) for v, w in ((gross, "the gross fee"), (tips, "tips"), (discounts, "discounts"), (credits, "credits")))
    if min(g, t, d, c) < 0:
        raise BillingError("the fee, tips, discounts and credits: 0 or more")
    if isinstance(channel_rate, (bool, float)):
        raise BillingError("channel_rate: write it as a string like \"0.20\"")
    try:
        r = Decimal(str(channel_rate))
    except InvalidOperation:
        raise BillingError(f"channel_rate: {channel_rate!r} is not a share") from None
    if not (r.is_finite() and ZERO <= r <= 1):
        raise BillingError("channel_rate: a share from 0 to 1")
    if t > g:
        raise BillingError("tips: never more than the fee they come out of")
    net = g - t - d - c
    channel = cents(net * r) if net > 0 else ZERO
    kept = net - channel
    return {"gross_fee": show(g), "relayer_tips": show(t), "discounts": show(d), "credits": show(c), "channel": show(channel),
            "cash_kept": show(kept), "kept_share": share(kept, g) if g > 0 else "none: no fee", "fee_counter_is_cash": False, "rule": CASH_RULE,
            "devnet": RULES["devnet"]}


def cash_example(unit: dict[str, Decimal] | None = None) -> dict:
    """CASH_EXAMPLE worked: the gross fee and the tips from `release_split` (knos_pay 2.2, outside relayers), then the
    discount, the credit and the channel's share. Every input after the fee is an assumption."""
    e = CASH_EXAMPLE
    plain = release_split(e["amount"] * 1_000_000, "outside", False, unit)
    first = release_split(e["amount"] * 1_000_000, "outside", True, unit)
    n, k = e["releases"], e["first_payments"]
    fee = money(plain["fee"]) * n
    tips = money(plain["tip"]) * (n - k) + money(first["tip"]) * k
    discount = cents((fee - tips) * Decimal(e["discount"]))
    return {**cash_kept(fee, tips, discount, e["credits"], e["channel"]), "example": e, "build": plain["build"]}


def margin_lines(g: dict) -> list[str]:
    out = [f"Gross margin of month {g['month']} of the contract year. Plan: {g['plan']}. USD.", g["gross_note"],
           f"  {'line':<22} {'units':>14} {'revenue':>14} {'direct cost':>14} {'gross':>14}  gross margin"]
    for r in [*g["lines"], {"what": "All lines", "units": "", "revenue": g["revenue"], "direct_cost": g["direct_cost"], "gross": g["gross"], "margin": g["margin"]}]:
        units = f"{r['units']:,}" if isinstance(r["units"], int) else str(r["units"])
        out.append(f"  {r['what']:<22} {units:>14} {r['revenue']:>14} {r['direct_cost']:>14} {r['gross']:>14}  {r['margin']}")
    out.append(g["note"])
    out.append(f"The free evaluations: at most {g['free_tier_year']} a year for this organisation at these costs. It is acquisition cost.")
    k, c, w = g["leaks"]["meter"], g["leaks"]["control"], g["second"]
    out += ["", f"The three leaks, against a gross margin of {g['leaks']['target']}.",
            f"1. Meter: {k['evaluations']:,} evaluations delivered earn {k['revenue']} and cost {k['cost']}: {k['gross_margin']} gross.",
            f"   For {g['leaks']['target']} one delivered evaluation may cost {k['allowed_each']}; at the file's costs it is {k['cost_each']} "
            f"({'meets it' if k['meets'] else 'does not meet it'}); the measured part alone is {k['measured_each']} "
            f"({'meets it' if k['measured_meets'] else 'does not meet it'}: {k['gross_margin_measured_only']} gross).",
            f"   At scale the ceiling is {k['ceiling_each_at_scale']} an evaluation; these costs meet {g['leaks']['target']} from "
            + (f"{k['reaches_at']:,} evaluations a month." if k["reaches_at"] else "no count: an evaluation costs more than it may.") + f" Design: {k['design']}.",
            f"2. Control, Business: {c['cost']} a year of onboarding and support on {c['price']} is {c['gross_margin']} gross. The target is {c['target_cost']}: "
            f"{c['gross_margin_at_target']} gross, {c['to_remove']} to remove. Design: {c['design']}.",
            "3. The floor: the funder pays the fee on top of the amount and the relayer's tip comes out of that fee, under both builds. The tables follow."]
    for b in g["floor"]:
        out += ["", f"Who earns what at the floor, knos_pay {b['build']} (the {b['release']} fee: {b['rate']}). Test USDC; `knos status` says which build is live.",
                f"  {'release':>10} {'fee':>8} {'share':>7} {'tip':>6} {'fee owner':>10}   a payee's first payment: {'tip':>5} {'less ' + b['account'] + ' rent':>15} {'fee owner':>10}"]
        out += [f"  {r['amount']:>10} {r['fee']:>8} {r['share']:>7} {r['tip']:>6} {r['fee_owner']:>10}   {'':>24}{r['first_tip']:>5} {r['first_relayer_net']:>15} {r['first_fee_owner']:>10}" for r in b["rows"]]
        said = lambda size: "never" if size == "none" else f"at {size} or less"      # noqa: E731
        out.append(f"  The fee owner earns nothing: on a release, {said(b['nothing_at'])}; on a payee's first payment, {said(b['first_nothing_at'])}.")
    n = g["netting"]
    out += ["", f"Netting: an outcome of {n['value']} by itself pays the floor, {n['alone_fee']}: {n['alone_share']} of it. (On chain the least order is {n['on_chain_least']}.)",
            f"  {n['count']:,} of them to one payee in a period, netted: one release of {n['netted_amount']} pays {n['netted_fee']}, {n['netted_share']}; one by one they pay {n['individually']}.",
            f"  One alone in a period still pays the floor, {n['one_in_a_period']}; from {n['reaches_rate']} of them the rate is the fee."]
    m, a, b = g["remedy"], g["remedy"]["one_by_one"], g["remedy"]["netted"]
    out += [f"  The remedy for the floor, knos_pay {m['build']}: {m['count']:,} outcomes of {m['value']} to one payee, one by one: fee {a['fee']}, tips {a['tips']}, "
            f"fee owner {a['fee_owner']}. Netted into one release of {b['amount']}: fee {b['fee']}, tip {b['tips']}, fee owner {b['fee_owner']}.",
            "", f"The second worked customer: {w['plan']}, {w['evaluations_a_month']:,} evaluations a month, {w['accepted_a_year']} accepted a year, no record revenue.",
            f"  Control {w['control']} + Acceptance {w['acceptance']} + Meter {w['meter']} = {w['total']} a year.",
            f"  Direct cost {w['direct_cost']}: {w['gross_margin']} gross; with Control at its target, {w['direct_cost_at_control_target']}: {w['gross_margin_at_control_target']} gross.",
            f"  Three to one is {w['hurdle']} a year of benefit: {w['hurdle_is']}."]
    out += ["", f"The budget today against what the price book requires for {g['leaks']['target']} gross, unit by unit. Budgets, not measurements, but for the chain fees (counted in the simulator).",
            f"  {'unit':<22} {'budget today':>14} {'required':>12} {'gap':>10}  how required is reached; the design that closes the gap"]
    for r in g["gaps"]:
        out.append(f"  {r['unit']:<22} {r['budget']:>14} {r['required']:>12} {r['gap']:>10}  {r['how']}. Design: {r['design']}.")
    c = g["cash"]
    e = c["example"]
    out += ["", f"Gross fee against cash kept (knos_pay {c['build']}; an example, its inputs after the fee assumed): {e['releases']} releases of "
            f"{e['amount']:,} by outside relayers, {e['first_payments']} of them a payee's first payment.",
            f"  gross fee {c['gross_fee']} - relayer tips {c['relayer_tips']} - discounts {c['discounts']} - credits {c['credits']} - channel {c['channel']} "
            f"= cash kept {c['cash_kept']} ({c['kept_share']} of the gross fee).", f"  {c['rule']}"]
    return out


def register(app: Any, help_lines: list | None = None) -> None:
    """`knos bill estimate`, `knos bill explain` and `knos bill margin`, on the main app. `help_lines`: cli._HELP, which gets the command's line."""
    import typer

    if help_lines is not None:
        help_lines.append(("bill", "For money", "What a year or a month costs at the price book, line by line, with the rule behind each line."))
    bill = typer.Typer(no_args_is_help=True, help="The price book as arithmetic. Reads nothing but what you give it; charges nobody.")
    app.add_typer(bill, name="bill", rich_help_panel="For money")

    def stop(why: BillingError) -> Exception:
        from . import cli
        return cli.Stop(str(why), "See `knos bill explain --help` for the fields of a customer-month.")

    @bill.command("estimate")
    def estimate_(plan: str = typer.Option("none", "--plan", help="none, team, business or enterprise"),
                  evaluations: int = typer.Option(0, "--evaluations", help="evaluations a month"),
                  accepted: str = typer.Option("0", "--accepted", help="accepted value a year, USD"),
                  on_chain: int = typer.Option(0, "--on-chain", help="the share of it released on chain, a whole percentage"),
                  lookups: int = typer.Option(0, "--lookups", help="record lookups a month"),
                  suppliers: int = typer.Option(0, "--suppliers", help="suppliers connected (it costs nothing)"),
                  committed: str = typer.Option("0", "--committed", help="an annual commitment, USD"),
                  as_json: bool = typer.Option(False, "--json", help="print JSON")) -> None:
        """What a year costs before any work starts: Control, Meter, Acceptance on value reconciled off chain, and record lookups."""
        try:
            _count(suppliers, "suppliers")
            e = estimate(plan, evaluations, accepted, on_chain, lookups, committed)
        except BillingError as why:
            raise stop(why) from None
        if as_json:
            typer.echo(json.dumps(e, indent=2))
            return
        for line in estimate_lines(e):
            typer.echo(line)

    @bill.command("explain")
    def explain_(month: Path = typer.Argument(..., help="a customer-month, as JSON (the fields are in `knos.billing.invoice`)"),
                 as_json: bool = typer.Option(False, "--json", help="print the invoice's JSON")) -> None:
        """One customer-month as an invoice: every line, how it was reached and the rule that produced it."""
        try:
            data = json.loads(month.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError) as why:
            from . import cli
            raise cli.Stop(f"{month} could not be read: {why}", "Give a JSON file of one customer-month.") from None
        try:
            inv = invoice(data)
        except BillingError as why:
            raise stop(why) from None
        if as_json:
            typer.echo(json.dumps(inv, indent=2))
            return
        for line in explain(inv):
            typer.echo(line)

    @bill.command("margin")
    def margin_(month: Path = typer.Argument(None, help="a customer-month, as JSON (with --sensitivity: leave it out)"),
                costs: Path = typer.Argument(None, help="a unit-cost file, as JSON (docs/unit_costs.json is one)"),
                sensitivity_: bool = typer.Option(False, "--sensitivity", help="the worked customers at a realised Acceptance rate of 30, 20, 10 and 5 bps"),
                as_json: bool = typer.Option(False, "--json", help="print JSON")) -> None:
        """Revenue, direct cost and GROSS margin of one customer-month, line by line, at the unit costs of a file; the three leaks, the floor and netting."""
        from . import cli
        if sensitivity_:
            if month is None or costs is not None:
                raise cli.Stop("--sensitivity takes one file: the unit costs.", "knos bill margin --sensitivity docs/unit_costs.json")
            try:
                unit = unit_costs(json.loads(month.read_text(encoding="utf-8-sig")))
            except (OSError, ValueError) as why:
                raise cli.Stop(f"a file could not be read: {why}", "Give a unit-cost file, as JSON.") from None
            s = sensitivity(unit)
            for line in ([json.dumps(s, indent=2)] if as_json else sensitivity_lines(s)):
                typer.echo(line)
            return
        if month is None or costs is None:
            raise cli.Stop("give a customer-month and a unit-cost file", "knos bill margin month.json docs/unit_costs.json")
        try:
            data, unit = (json.loads(p.read_text(encoding="utf-8-sig")) for p in (month, costs))
        except (OSError, ValueError) as why:
            raise cli.Stop(f"a file could not be read: {why}", "Give a customer-month and a unit-cost file, both JSON.") from None
        try:
            g = margin(data, unit)
        except BillingError as why:
            raise stop(why) from None
        if as_json:
            typer.echo(json.dumps(g, indent=2))
            return
        for line in margin_lines(g):
            typer.echo(line)
