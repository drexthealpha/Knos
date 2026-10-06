"""The billing rule, as code: what one customer owes for one month, line by line, with the rule behind each line.

    a month's invoice = subscription + the greater of Meter charges and Verify charges + anything agreed separately

The price book (docs/MARKET.md, section 3; BOOK below is the same seven lines):

    Check                free, forever
    Pilot                2,500 USD, credited against year one
    Meter                10,000 evaluations a month free per organisation, then 0.05 USD; 0.02 on an annual commitment
    Verify               0.5% of reconciled accepted invoice value, capped at 250 USD per deliverable
    Control              Team 25,000 USD a year; Business 80,000; Enterprise from 250,000
    Supplier connection  5,000 USD a year for each supplier beyond the first five; the buyer pays
    Settle               on chain, by the funder; on devnet it is test money and no revenue, so it is never on an invoice

The rules, each of which a line of the invoice names:

- Meter and Verify are never added for the same activity: the larger of the two is charged, and the other is shown
  as not charged.
- No charge for a duplicate, an infrastructure failure or a retry Knos caused. A rejection that ran correctly is an
  evaluation, and is counted.
- An accepted deliverable is counted once, however many evaluations it took and however often it is listed.
- THE CREDIT RULE, in one sentence: value that is disputed or reversed never carries a Verify charge, so in the
  month it was accepted it is left out of the reconciled value, and when it was accepted in an earlier month 0.5%
  of it, at most 250 USD per deliverable, is credited on the next invoice.
- A price by the year is billed in twelve parts that add up to the year's price to the cent.
- An annual commitment is sold by the year, billed in twelve parts, and drawn down by use: a month's Meter or Verify
  charge comes out of what is left of it, and only what the commitment does not cover is charged on top.
- The 0.02 Meter rate is the rate of an annual commitment: a Control plan (sold by the year) or a committed amount.
- The rated party never pays: an invoice is the buyer's, and a customer-month billed to a supplier is refused.

Arithmetic is `decimal.Decimal`, exact, rounded half up to the cent once per line (Verify: once per deliverable).
Nothing here reads the network, the chain or a clock. Nothing has been sold: these are proposed prices, there is no
legal entity to invoice from, and an invoice this module prints is an estimate, not a demand for payment.

    knos bill estimate --plan business --evaluations 110000 --accepted 10000000 --suppliers 5
    knos bill explain month.json
"""
from __future__ import annotations

import json
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import Any

CENT = Decimal("0.01")
ZERO = Decimal(0)

METER_FREE = 10_000                      # evaluations a month, per organisation
METER_PRICE = Decimal("0.05")            # USD an evaluation after the free ones
METER_COMMITTED = Decimal("0.02")        # the same, on an annual commitment
VERIFY_RATE = Decimal("0.005")           # of reconciled accepted invoice value
VERIFY_CAP = Decimal("250.00")               # USD per deliverable
CONTROL = {"none": ZERO, "team": Decimal(25_000), "business": Decimal(80_000), "enterprise": Decimal(250_000)}     # USD a year; Enterprise: from
SUPPLIERS_INCLUDED = 5
SUPPLIER_PRICE = Decimal(5_000)          # USD a year, each supplier beyond the included ones
PILOT = Decimal(2_500)                   # USD, credited against year one
BENEFIT_RULE = 3                         # what a buyer should demand before buying: a measured benefit of three times the price

BOOK = (
    ("Check", "pull request or artifact checked", "free, forever"),
    ("Pilot", "one buyer, two suppliers, 30 days, one reconciled invoice",
     "2,500 USD, credited against year one (nobody has bought it; no legal entity to invoice from yet)"),
    ("Meter", "evaluation", "10,000 a month free per organisation, then 0.05 USD; 0.02 on an annual commitment"),
    ("Verify", "dollar of reconciled accepted invoice value", "0.5%, capped at 250 USD per deliverable (proposed; nobody has bought it)"),
    ("Control", "organisation, per year", "Team 25,000 USD; Business 80,000; Enterprise from 250,000 (not deliverable yet: it needs single "
     "sign-on, private deployment and support that do not exist)"),
    ("Supplier connection", "supplier beyond the first five, per year", "5,000 USD; the buyer pays"),
    ("Settle", "dollar settled, paid by the funder on top",
     "2.5% of the first 1,000, 1% to 50,000, 0.5% above; minimum 0.40. On devnet: test money, zero revenue"),
)

RULES = {
    "subscription": "Control is sold by the year and billed in twelve parts that add up to the year's price.",
    "enterprise": "Enterprise is from 250,000 USD a year and is not deliverable yet.",
    "meter": "Meter: the first 10,000 evaluations a month are free, then 0.05 USD each; 0.02 on an annual commitment.",
    "free_of_charge": "No charge for a duplicate, an infrastructure failure or a retry Knos caused.",
    "rejection": "A rejection that ran correctly is an evaluation, and is counted.",
    "verify": "Verify: 0.5% of reconciled accepted invoice value, capped at 250 USD per deliverable.",
    "once": "An accepted deliverable is counted once, however many evaluations it took.",
    "greater": "The greater of Meter and Verify is charged. They are never added for the same activity.",
    "credit": ("Value that is disputed or reversed never carries a Verify charge: in the month it was accepted it is left out of the "
               "reconciled value, and when it was accepted in an earlier month 0.5% of it, at most 250 USD per deliverable, is "
               "credited on the next invoice."),
    "suppliers": "The first five supplier connections are included; each one beyond is 5,000 USD a year, and the buyer pays.",
    "commitment": "An annual commitment is billed in twelve parts and drawn down by use; only what it does not cover is charged on top.",
    "separate": "Agreed separately, and listed as agreed.",
    "pilot": "The Pilot is 2,500 USD, credited against year one.",
    "rated": "The rated party never pays.",
    "settle": "Settle is paid on chain by the funder. On devnet it is test money: 0 revenue.",
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


def verify_fee(value: Decimal) -> Decimal:
    """Verify on one deliverable: 0.5% of its reconciled accepted value, rounded half up to the cent, at most 250."""
    return min(cents(value * VERIFY_RATE), VERIFY_CAP)


def meter_rate(plan: str, committed: Decimal) -> Decimal:
    return METER_COMMITTED if (CONTROL[plan] > 0 or committed > 0) else METER_PRICE


def _plan(name: Any) -> str:
    plan = str(name or "none").strip().lower()
    if plan not in CONTROL:
        raise BillingError(f"plan: {name!r} is not one of {', '.join(CONTROL)}")
    return plan


def _line(key: str, what: str, amount: Decimal, rule: str, how: str = "", **more: Any) -> dict:
    return {"line": key, "what": what, "amount": show(amount), "how": how, "rule": RULES[rule], **more}


def _in_total(row: dict) -> Decimal:
    """What a line adds to the total. Meter and Verify are shown, and charged only through the line that chooses."""
    return ZERO if row["line"] in ("meter", "verify") else Decimal(row["amount"].replace(",", ""))


def _valued(rows: Any, what: str) -> list[tuple[str, Decimal]]:
    out = []
    for n, row in enumerate(rows or [], 1):
        if not isinstance(row, dict) or not str(row.get("deliverable", "")).strip():
            raise BillingError(f"{what} {n}: needs a deliverable id")
        value = money(row.get("value", "0"), f"{what} {n}, value")
        if value < 0:
            raise BillingError(f"{what} {n}: a value is 0 or more")
        out.append((str(row["deliverable"]).strip(), value))
    return out


def invoice(month: dict) -> dict:
    """One customer-month in, one invoice out: every line, the arithmetic that gave it and the rule that produced it.

    `month` (all but `plan` optional):
        plan                     none | team | business | enterprise
        month                    1 to 12: which month of the contract year this is (default 1)
        billed_to                "buyer" (default). Anything else is refused: the rated party never pays.
        evaluations              every evaluation run in the month, rejections included
        duplicates, infrastructure_failures, knos_retries      how many of those are free of charge
        accepted                 [{"deliverable": id, "value": "1200.00"}]  accepted this month, at invoice value
        disputed, reversed       [{"deliverable": id, "value": "..."}]  this month's, or an earlier month's
        suppliers                suppliers connected
        committed                the annual commitment, USD (default 0)
        drawn                    how much of it earlier months of this year already used
        credit_brought_forward   credit an earlier invoice could not use
        other                    [{"what": "...", "amount": "..."}]  agreed separately; a negative amount is a credit
    """
    if not isinstance(month, dict):
        raise BillingError("a customer-month is a JSON object")
    known = {"plan", "month", "billed_to", "evaluations", "duplicates", "infrastructure_failures", "knos_retries", "accepted", "disputed",
             "reversed", "suppliers", "committed", "drawn", "credit_brought_forward", "other", "customer", "period"}
    unknown = sorted(set(month) - known)
    if unknown:
        raise BillingError(f"not a field of a customer-month: {', '.join(unknown)}")
    if str(month.get("billed_to", "buyer")).strip().lower() != "buyer":
        raise BillingError(f"billed_to: {month['billed_to']!r}. {RULES['rated']} An invoice is the buyer's.")
    plan = _plan(month.get("plan"))
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
    rate = meter_rate(plan, committed)
    meter = cents(billable * rate)
    if sum(free.values()):
        lines.append(_line("not_charged", "Evaluations not charged", ZERO, "free_of_charge",
                           f"{free['duplicates']:,} duplicates, {free['infrastructure_failures']:,} infrastructure failures, {free['knos_retries']:,} retries Knos caused"))

    # 3. Verify: each accepted deliverable once, less what is disputed or reversed this month
    accepted: dict[str, Decimal] = {}
    listed_again = 0
    for ident, value in _valued(month.get("accepted"), "accepted"):
        if ident in accepted:
            listed_again += 1                       # the same deliverable again: counted once, at the value first given
        else:
            accepted[ident] = value
    earlier: list[tuple[str, str, Decimal]] = []
    left_out = ZERO
    for kind in ("disputed", "reversed"):
        for ident, value in _valued(month.get(kind), kind):
            if ident in accepted:
                taken = min(value, accepted[ident])
                accepted[ident] -= taken
                left_out += taken
            else:
                earlier.append((kind, ident, value))
    capped = sum(1 for v in accepted.values() if cents(v * VERIFY_RATE) > VERIFY_CAP)
    reconciled = sum(accepted.values(), ZERO)
    verify = sum((verify_fee(v) for v in accepted.values()), ZERO)

    # 4. the greater of the two, never both
    chosen = "verify" if verify > meter else "meter"
    usage = max(meter, verify)
    meter_how = f"{evaluations:,} evaluations, {counted:,} counted, {min(counted, METER_FREE):,} free, {billable:,} at {rate}"
    verify_how = (f"0.5% of {show(reconciled)} reconciled over {len(accepted):,} deliverables"
                  + (f", {capped:,} at the 250 cap" if capped else "") + (f"; {listed_again:,} listed again and counted once" if listed_again else "")
                  + (f"; {show(left_out)} disputed or reversed this month left out" if left_out else ""))
    lines.append(_line("meter", "Meter", meter, "meter", meter_how, charged=chosen == "meter"))
    lines.append(_line("verify", "Verify", verify, "verify", verify_how, charged=chosen == "verify"))
    lines.append(_line("usage", "The greater of Meter and Verify", usage, "greater", f"{'Verify' if chosen == 'verify' else 'Meter'} is charged; the other is not",
                       chosen=chosen))

    # 5. credits for value disputed or reversed after the month it was charged in
    credit = brought + sum((verify_fee(v) for _k, _i, v in earlier), ZERO)
    used = min(credit, usage)
    if credit > 0:
        how = "; ".join(f"{kind} {ident}: {show(verify_fee(v))} on {show(v)}" for kind, ident, v in earlier)
        if brought:
            how = "; ".join(x for x in (how, f"{show(brought)} brought forward") if x)
        lines.append(_line("credit", "Credit for disputed or reversed value", -used, "credit", how, carried_forward=show(credit - used)))
    payable = usage - used

    # 6. the commitment pays for use first
    covered = min(payable, committed - drawn)
    if committed > 0:
        lines.append(_line("drawn", "Drawn from the commitment", -covered, "commitment",
                           f"{show(committed - drawn)} was left of {show(committed)}; {show(committed - drawn - covered)} is left", remaining=show(committed - drawn - covered)))

    # 7. supplier connections beyond the five that are included
    suppliers = _count(month.get("suppliers", 0), "suppliers")
    extra = max(0, suppliers - SUPPLIERS_INCLUDED)
    if suppliers:
        lines.append(_line("suppliers", "Supplier connections", part_of_year(SUPPLIER_PRICE * extra, m), "suppliers",
                           f"{suppliers:,} connected, {min(suppliers, SUPPLIERS_INCLUDED)} included, {extra:,} at month {m} of 12 of {show(SUPPLIER_PRICE)} a year"))

    # 8. anything agreed separately
    for n, row in enumerate(month.get("other") or [], 1):
        if not isinstance(row, dict) or not str(row.get("what", "")).strip():
            raise BillingError(f"other {n}: needs a `what`")
        what = str(row["what"]).strip()
        lines.append(_line("other", what, money(row.get("amount", "0"), f"other {n}, amount"), "pilot" if "pilot" in what.lower() else "separate"))

    total = sum((_in_total(row) for row in lines), ZERO)
    return {
        "billed_to": "buyer", "currency": "USD", "plan": plan, "month": m,
        **({k: month[k] for k in ("customer", "period") if k in month}),
        "lines": lines, "chosen": chosen, "total": show(total),
        "credit_carried_forward": show(credit - used),
        "commitment_remaining": show(committed - drawn - covered),
        "rules": [RULES["greater"], RULES["rated"], RULES["settle"]],
        "note": "An estimate at proposed prices. Nothing has been sold and there is no legal entity to invoice from.",
    }


def estimate(plan: str, evaluations: int, accepted_per_year: Any, suppliers: int = 0, committed: Any = "0") -> dict:
    """A year at the price book, from the four things a buyer knows before work starts: the plan, evaluations a month,
    accepted invoice value a year, and suppliers. The limits shown before work starts are this. It assumes twelve equal
    months and no deliverable large enough to reach the Verify cap; `invoice` works a real month, deliverable by
    deliverable."""
    plan = _plan(plan)
    evaluations, suppliers = _count(evaluations, "evaluations"), _count(suppliers, "suppliers")
    value, committed = money(accepted_per_year, "accepted value a year"), money(committed, "committed")
    if value < 0 or committed < 0:
        raise BillingError("accepted value and committed are 0 or more")
    rate = meter_rate(plan, committed)
    billable = max(0, evaluations - METER_FREE)
    meter = cents(billable * rate * 12)
    verify = cents(value * VERIFY_RATE)
    chosen = "verify" if verify > meter else "meter"
    usage = max(meter, verify)
    extra = max(0, suppliers - SUPPLIERS_INCLUDED)
    connections = SUPPLIER_PRICE * extra
    over = max(ZERO, usage - committed)                 # use beyond what the commitment covers
    total = CONTROL[plan] + committed + over + connections
    return {
        "plan": plan, "evaluations_a_month": evaluations, "accepted_a_year": show(value), "suppliers": suppliers, "committed": show(committed),
        "meter_rate": str(rate), "billable_a_month": billable,
        "control": show(CONTROL[plan]), "meter": show(meter), "verify": show(verify), "chosen": chosen, "usage": show(usage),
        "supplier_connections": show(connections), "total": show(total), "benefit_to_demand": show(total * BENEFIT_RULE),
        "deliverable": plan != "enterprise",
    }


def explain(inv: dict) -> list[str]:
    """An invoice in plain lines: each line, how it was reached, and the rule that produced it."""
    out = [f"Invoice for month {inv['month']} of the contract year, billed to the buyer, in USD. Plan: {inv['plan']}."]
    for row in inv["lines"]:
        mark = "" if row.get("charged", True) else "  (not charged)"
        out.append(f"  {row['what']:<38} {row['amount']:>14}{mark}")
        if row["how"]:
            out.append(f"      how:  {row['how']}")
        out.append(f"      rule: {row['rule']}")
    out.append(f"  {'Total':<38} {inv['total']:>14}")
    if inv["credit_carried_forward"] != "0.00":
        out.append(f"  Credit carried forward: {inv['credit_carried_forward']}")
    if inv["commitment_remaining"] != "0.00":
        out.append(f"  Commitment left: {inv['commitment_remaining']}")
    out += [RULES["rated"], RULES["settle"], inv["note"]]
    return out


def estimate_lines(e: dict) -> list[str]:
    other = "Meter" if e["chosen"] == "verify" else "Verify"
    return [
        f"A year at the price book: {e['plan']}, {e['evaluations_a_month']:,} evaluations a month, {e['accepted_a_year']} accepted a year, {e['suppliers']} suppliers.",
        f"  {'Control':<38} {e['control']:>14}" + ("" if e["deliverable"] else "  (from; not deliverable yet)"),
        f"  {'Meter':<38} {e['meter']:>14}  ({e['billable_a_month']:,} billable a month at {e['meter_rate']}, 12 months)",
        f"  {'Verify':<38} {e['verify']:>14}  (0.5% of {e['accepted_a_year']})",
        f"  {'The greater of Meter and Verify':<38} {e['usage']:>14}  ({other} is not charged)",
        *([f"  {'Annual commitment':<38} {e['committed']:>14}  (use is drawn from it first)"] if e["committed"] != "0.00" else []),
        f"  {'Supplier connections':<38} {e['supplier_connections']:>14}",
        f"  {'Total a year':<38} {e['total']:>14}",
        f"Demand a measured benefit of {BENEFIT_RULE} to 1 before buying: {e['benefit_to_demand']} a year.",
        RULES["rated"], RULES["settle"],
        "An estimate at proposed prices. Nothing has been sold and there is no legal entity to invoice from.",
    ]


def register(app: Any, help_lines: list | None = None) -> None:
    """`knos bill estimate` and `knos bill explain`, on the main app. `help_lines`: cli._HELP, which gets the command's line."""
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
                  accepted: str = typer.Option("0", "--accepted", help="accepted invoice value a year, USD"),
                  suppliers: int = typer.Option(0, "--suppliers", help="suppliers connected"),
                  committed: str = typer.Option("0", "--committed", help="an annual commitment, USD"),
                  as_json: bool = typer.Option(False, "--json", help="print JSON")) -> None:
        """What a year costs before any work starts: Control, the greater of Meter and Verify, and supplier connections beyond five."""
        try:
            e = estimate(plan, evaluations, accepted, suppliers, committed)
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
