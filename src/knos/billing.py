"""The billing rule, as code: what one customer owes for one month, line by line, with the rule behind each line.

    a month's invoice = Control + Meter + Acceptance on value reconciled off chain + Record lookups

The price book (docs/MARKET.md, section 3; BOOK below is the same six lines, five columns each):

    Check       free, forever
    Meter       100,000 evaluations a month free per organisation, then 0.002 USD
    Acceptance  0.30% of value released or reconciled against a signed acceptance; by contract 0.20% above 1M a
                month and 0.10% above 10M a month; floor 0.05 USD; no cap
    Record      0.25 USD a lookup through the hosted API, or by subscription
    Control     Team 25,000 USD a year; Business 100,000; Enterprise from 400,000
    Pilot       2,500 USD, credited against year one

The rules, each of which a line of the invoice names:

- Value released on chain paid its Acceptance fee there, to the program, at release. It is never charged again:
  a customer-month says which accepted deliverables were released on chain, and the invoice leaves them out.
- The volume rates are marginal and by contract: a Control plan is the contract. The month's accepted value is
  laid end to end, value released on chain first; each deliverable pays the rate of the part of the month it lies
  in, and at least 0.05. On chain the program takes 0.30% whatever the month's volume, so the part of that which
  the volume rates would not have taken is a rebate, credited on the invoice.
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

Arithmetic is `decimal.Decimal`, exact, rounded half up to the cent once per line (Acceptance: once per
deliverable). Nothing here reads the network, the chain or a clock. Nothing has been sold: these are proposed
prices, there is no legal entity to invoice from, and an invoice this module prints is an estimate, not a demand
for payment. On devnet every fee the program takes is test money: 0 revenue.

    knos bill estimate --plan business --evaluations 110000 --accepted 10000000
    knos bill explain month.json
    knos bill margin month.json docs/unit_costs.json
"""
from __future__ import annotations

import json
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import Any

CENT = Decimal("0.01")
ZERO = Decimal(0)

METER_FREE = 100_000                     # evaluations a month, per organisation
METER_PRICE = Decimal("0.002")           # USD an evaluation after the free ones
ACCEPT_RATE = Decimal("0.0030")          # of value released or reconciled against a signed acceptance
ACCEPT_TIERS = ((Decimal(0), ACCEPT_RATE), (Decimal(1_000_000), Decimal("0.0020")), (Decimal(10_000_000), Decimal("0.0010")))     # (monthly value above, rate), marginal, by contract
ACCEPT_FLOOR = Decimal("0.05")           # USD per deliverable; there is no cap
RECORD_PRICE = Decimal("0.25")           # USD a lookup of a supplier's delivery record through the hosted API
CONTROL = {"none": ZERO, "team": Decimal(25_000), "business": Decimal(100_000), "enterprise": Decimal(400_000)}     # USD a year; Enterprise: from
PILOT = Decimal(2_500)                   # USD, credited against year one
BENEFIT_RULE = 3                         # what a buyer should demand before buying: a measured benefit of three times the price
PAYER = "buyer"                          # who every line of an invoice is addressed to

BOOK = (
    ("Check", "pull request or artifact checked", "free, forever", "nobody", "nowhere"),
    ("Meter", "evaluation", "100,000 a month free per organisation, then 0.002 USD", "buyer", "prepaid credits"),
    ("Acceptance", "dollar released or reconciled against a signed acceptance",
     "0.30%; by contract 0.20% above 1M a month and 0.10% above 10M a month; floor 0.05 USD; no cap", "funder, on top of the amount",
     "knos_pay at release (on chain: 0.30% and the floor; volume rates are a rebate by contract, off chain)"),
    ("Record", "lookup of a supplier's delivery record through the hosted API",
     "0.25 USD, or by subscription (the public record page and its file are free)", "the buyer, marketplace or insurer reading it",
     "API (not built: a static file today)"),
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
    "acceptance": "Acceptance: 0.30% of value reconciled against a signed acceptance, at least 0.05 USD a deliverable, with no cap.",
    "volume": "By contract the month's value above 1,000,000 pays 0.20% and above 10,000,000 pays 0.10%, each rate on its own part.",
    "on_chain": "Value released on chain paid its Acceptance fee there and is never charged again.",
    "rebate": "On chain the fee is 0.30% of every release; what the volume rates would not have taken is a rebate by contract.",
    "once": "An accepted deliverable is counted once, however many evaluations it took.",
    "credit": ("Value that is disputed or reversed never carries an Acceptance charge: in the month it was accepted it is left out of the "
               "reconciled value, and when it was accepted in an earlier month the fee it was charged, 0.30% of it unless the earlier "
               "invoice shows less, is credited on the next invoice."),
    "record": "Record: 0.25 USD a lookup through the hosted API. The public record page and its file are free.",
    "suppliers": "Connecting a supplier costs nothing.",
    "commitment": "An annual commitment is billed in twelve parts and drawn down by use; only what it does not cover is charged on top.",
    "separate": "Agreed separately, and listed as agreed.",
    "pilot": "The Pilot is 2,500 USD, credited against year one.",
    "rated": "The rated party never pays.",
    "devnet": "On devnet every fee the program takes is test money: 0 revenue.",
}


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
          "reversed", "suppliers", "record_lookups", "committed", "drawn", "credit_brought_forward", "other", "customer", "period"}


def invoice(month: dict) -> dict:
    """One customer-month in, one invoice out: every line, the arithmetic that gave it and the rule that produced it.

    `month` (all but `plan` optional):
        plan                     none | team | business | enterprise. A plan is a contract: it brings the volume rates.
        month                    1 to 12: which month of the contract year this is (default 1)
        billed_to                "buyer" (default). Anything else is refused: the rated party never pays.
        evaluations              every evaluation run in the month, rejections included
        duplicates, infrastructure_failures, knos_retries      how many of those are free of charge
        accepted                 [{"deliverable": id, "value": "1200.00", "on_chain": false}]  accepted this month, at the value
                                 the acceptance names. "on_chain": true says the program released it and took its fee then.
        disputed, reversed       [{"deliverable": id, "value": "...", "charged": "..."}]  this month's, or an earlier month's;
                                 "charged" is the fee the earlier invoice shows for it, when that is less than 0.30%
        record_lookups           lookups of a supplier's delivery record through the hosted API
        suppliers                suppliers connected (it costs nothing; the line says so)
        committed                the annual commitment, USD (default 0)
        drawn                    how much of it earlier months of this year already used
        credit_brought_forward   credit an earlier invoice could not use
        other                    [{"what": "...", "amount": "..."}]  agreed separately; a negative amount is a credit
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
    chain: set[str] = set()
    listed_again = 0
    for ident, value, row in _valued(month.get("accepted"), "accepted"):
        if ident in accepted:
            listed_again += 1                       # the same deliverable again: counted once, at the value first given
            continue
        accepted[ident] = value
        if row.get("on_chain", False) not in (True, False):
            raise BillingError(f"accepted {ident}: on_chain is true or false")
        if row.get("on_chain", False):
            chain.add(ident)
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
    for ident, value in accepted.items():
        if ident in chain or value <= 0:
            continue
        acceptance += acceptance_fee(value, below, volume)
        below += value
        deliverables += 1
    parts = [p for p in acceptance_parts(released + reconciled, volume) if p["of"] > 0]
    how = (f"{show(reconciled)} reconciled off chain over {deliverables:,} deliverables"
           + (f", above {show(released)} released on chain" if released else "")
           + (f"; the month's {show(released + reconciled)}: " + ", ".join(f"{show(p['of'])} at {p['rate']}" for p in parts) if parts else "")
           + (f"; {listed_again:,} listed again and counted once" if listed_again else "")
           + (f"; {show(left_out)} disputed or reversed this month left out" if left_out else ""))
    lines.append(_line("acceptance", "Acceptance", acceptance, "volume" if volume and released + reconciled > ACCEPT_TIERS[1][0] else "acceptance", how,
                       deliverables=deliverables, reconciled=show(reconciled)))
    if released:
        paid_there = cents(released * ACCEPT_RATE)
        lines.append(_line("on_chain", "Released on chain", ZERO, "on_chain",
                           f"{show(released)} over {len([k for k in chain if accepted[k] > 0]):,} deliverables; about {show(paid_there)} was paid to the program at release",
                           released=show(released)))

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
    return {
        "billed_to": PAYER, "currency": "USD", "plan": plan, "month": m,
        **({k: month[k] for k in ("customer", "period") if k in month}),
        "lines": lines, "total": show(total),
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


def unit_costs(doc: Any) -> dict[str, Decimal]:
    """The four unit costs of a unit-cost file (docs/unit_costs.json is one): {"costs": {name: {"usd": "0.0002", ...}}}
    or {name: "0.0002"}. A cost may have any number of decimals; it is never a float."""
    rows = doc.get("costs", doc) if isinstance(doc, dict) else None
    if not isinstance(rows, dict):
        raise BillingError("a unit-cost file is a JSON object")
    out = {}
    for name in COST_FIELDS:
        raw = rows.get(name)
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
    something to deliver, the free ones too; a deliverable released on chain is in no line (its fee is the program's,
    and on devnet that is test money)."""
    inv, unit = invoice(month), unit_costs(costs)
    by = {row["line"]: row for row in inv["lines"]}
    rows = []

    def add(key: str, what: str, revenue: Decimal, units: Any, cost: Decimal) -> None:
        cost = cents(cost)
        rows.append({"line": key, "what": what, "units": units, "revenue": show(revenue), "direct_cost": show(cost), "gross": show(revenue - cost),
                     "margin": f"{(revenue - cost) / revenue * 100:.1f}%" if revenue > 0 else "none: no revenue"})

    if "control" in by:
        add("control", by["control"]["what"], _amount(by["control"]), "1 month of 12", unit["control_year"] / 12)
    add("meter", "Meter", _amount(by["meter"]), by["meter"]["counted"], by["meter"]["counted"] * unit["evaluation"])
    add("acceptance", "Acceptance", _amount(by["acceptance"]), by["acceptance"]["deliverables"], by["acceptance"]["deliverables"] * unit["accepted_deliverable"])
    if "record" in by:
        add("record", "Record lookups", _amount(by["record"]), by["record"]["lookups"], by["record"]["lookups"] * unit["record_lookup"])
    revenue = sum((Decimal(r["revenue"].replace(",", "")) for r in rows), ZERO)
    cost = sum((Decimal(r["direct_cost"].replace(",", "")) for r in rows), ZERO)
    return {"plan": inv["plan"], "month": inv["month"], "lines": rows, "revenue": show(revenue), "direct_cost": show(cost), "gross": show(revenue - cost),
            "margin": f"{(revenue - cost) / revenue * 100:.1f}%" if revenue > 0 else "none: no revenue",
            "note": ("Revenue is the lines before credits, the commitment and anything agreed separately. Direct cost is the unit-cost file's, and "
                     "a cost it marks as a budget is a budget, not a measurement. Nothing has been sold.")}


def margin_lines(g: dict) -> list[str]:
    out = [f"Gross margin of month {g['month']} of the contract year. Plan: {g['plan']}. USD.",
           f"  {'line':<22} {'units':>14} {'revenue':>14} {'direct cost':>14} {'gross':>14}  margin"]
    for r in [*g["lines"], {"what": "All lines", "units": "", "revenue": g["revenue"], "direct_cost": g["direct_cost"], "gross": g["gross"], "margin": g["margin"]}]:
        units = f"{r['units']:,}" if isinstance(r["units"], int) else str(r["units"])
        out.append(f"  {r['what']:<22} {units:>14} {r['revenue']:>14} {r['direct_cost']:>14} {r['gross']:>14}  {r['margin']}")
    out.append(g["note"])
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
    def margin_(month: Path = typer.Argument(..., help="a customer-month, as JSON"),
                costs: Path = typer.Argument(..., help="a unit-cost file, as JSON (docs/unit_costs.json is one)"),
                as_json: bool = typer.Option(False, "--json", help="print JSON")) -> None:
        """Revenue, direct cost and gross margin of one customer-month, line by line, at the unit costs of a file."""
        from . import cli
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
