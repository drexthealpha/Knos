"""The statement of one invoice as the bill-import file of the approver's accounting system: `knos statement export
FILE --to xero|quickbooks|netsuite|csv`.

The person who approves an invoice works in an accounting system, not here. This module writes, from one statement and
its status file, the file that system's bill import documents (TARGETS: the columns, where they come from, what could
not be confirmed), and a second sheet beside it:

    the payable file   one bill per line whose policy is met and that is not owed to the supplier; its memo (or, for
                       Xero, whose bill template has no memo, its description) carries the line's four steps (policy
                       satisfied, parties accepted, payment authorised, settled) and its assurance level
    the held sheet     every other line: disputed, owed to the supplier (refused, or not authorised in time, though its
                       policy is met), duplicate, or without enough evidence, each with why. These never reach the payable

The same statement, status, options and day give the same bytes. web/erp.js is the same code for the statement page
(tests/web/erp.mjs holds the two equal). Each file is a file export, not an integration: nobody has imported one
into the product yet (knos.exports.IMPORTED).
"""

from __future__ import annotations

from pathlib import Path

from . import exports, ids, statement

Refused = statement.Refused

XERO = ("ContactName", "InvoiceNumber", "Reference", "InvoiceDate", "DueDate", "Description", "Quantity", "UnitAmount", "AccountCode", "TaxType",
        "InventoryItemCode", "Discount", "Currency")
PLAIN = ("bill_no", "invoice", "line", "supplier", "reference", "date", "amount", "currency", "policy", "accepted", "authorised", "settled",
         "assurance", "payment", "invoice_line", "deliverable", "settlement", "statement_sha256")
HELD = ("bill_no", "invoice", "line", "supplier", "reference", "amount", "currency", "held_because", "policy", "accepted", "authorised",
        "settled", "assurance", "invoice_line", "deliverable", "statement_sha256")

TARGETS = {
    "xero": {"name": "Xero: import bills", "columns": XERO, "date": "DD/MM/YYYY",
             "source": "https://central.xero.com/s/article/Import-bills-and-credit-notes-US",
             "seen": "https://invoicedataextraction.com/blog/import-invoices-xero",
             "confirmed": "read 2026-10-09 in a published guide, not on Xero's own page: the 13 columns in this order; ContactName, InvoiceNumber, "
                          "InvoiceDate, DueDate, Description, Quantity, UnitAmount, AccountCode and TaxType required; rows with the same "
                          "InvoiceNumber make one bill; DD/MM/YYYY for UK, AU and NZ organisations and MM/DD/YYYY for US ones (--date-format); "
                          "about 500 lines a file",
             "unverified": "Xero's own help page draws its text by script and could not be read here; whether the template's header carries "
                           "asterisks on the required columns; AccountCode and TaxType are codes from your own Xero organisation: pass "
                           "--account and --tax-code. The whole file is " + exports.UNVERIFIED},
    "quickbooks": {"name": "QuickBooks Online: import bills", "columns": exports.QUICKBOOKS, "date": exports.FORMATS["quickbooks"]["date"],
                   "source": "https://quickbooks.intuit.com/learn-support/en-us/help-articles/importing-your-bills/00/261324",
                   "seen": "",
                   "confirmed": "read 2026-10-09 on the United States edition's page: the mandatory columns Bill no., Supplier, Bill Date, Due Date, "
                                "Account, Line Amount and Line Tax Code; every line of a bill repeats Bill no., Supplier and Bill Date; the date "
                                "format is chosen at import; at most 100 bills a file is recommended; a bill's total is 0 or more",
                   "unverified": "the optional columns Line Description and Memo (the page names none); Line Tax Code is left empty unless "
                                 "--tax-code gives one"},
    "netsuite": {"name": "NetSuite: CSV Import, Vendor Bill", "columns": exports.NETSUITE, "date": exports.FORMATS["netsuite"]["date"],
                 "source": exports.FORMATS["netsuite"]["source"], "seen": "",
                 "confirmed": "read 2026-10-09: a unique id per record (External ID) on every line of it; the Vendor field names the vendor "
                              "record by an id, not a name; at least one line per new record; on the Expenses sublist, Account, Amount and "
                              "Memo; an account is written with its number when the account uses account numbers",
                 "unverified": "the date format (the page's samples are M/D/YYYY), the body field Memo, and the fields an account's own form "
                               "makes mandatory; Vendor is the supplier's name here: map it to the vendor's id in the import's mapping step"},
    "csv": {"name": "Knos: plain bill file", "columns": PLAIN, "date": "YYYY-MM-DD", "source": "docs/reference/FINANCE.md", "seen": "",
            "confirmed": "Knos's own format, one column per step", "unverified": ""},
}


def held_path(path: Path) -> Path:
    """Where the held sheet of a payable file written to `path` goes: beside it, `<stem>.held.csv`."""
    p = Path(path)
    return p.with_name((p.name[: -len(p.suffix)] if p.suffix else p.name) + ".held.csv")


def _step(x: dict) -> str:
    done = {"done": "yes", "failed": "no"}.get(x["state"], "not yet")
    return f"{done}, {x['said']}" if x["said"] else done


def lines(st: dict, status: dict | None = None, today: str = "") -> list[dict]:
    """Every line of the statement, in its order, with its bill number, its four steps in words, its memo and whether it
    is payable: policy met, not owed to the supplier, and an amount. `held_because` says why a line is not."""
    out = []
    for ln in statement.lines_now(st, status, today):
        steps = {x["step"]: _step(x) for x in ln["steps"]}
        payable = ln["state"] == "agreed" and not ln["owed"] and bool(ln["amount"])
        held = ("" if payable else f"{ids.OWED_WORDS}: the policy is met and the buyer refused it or left it unauthorised; the supplier may appeal"
                if ln["owed"] else "no amount" if ln["state"] == "agreed"
                else ids.LINE_WORDS[ln["state"]] + (f": {ln['why']}" if ln["why"] else ""))
        memo = " | ".join([*(f"{ids.STEP_WORDS[s]}: {steps[s]}" for s in ids.STEPS), f"assurance {ln['assurance']}",
                           f"Knos statement sha256:{st['sha256']}", f"invoice line {ln['invoice_line']}", f"deliverable {ln['deliverable']}"])
        out.append({"payable": payable, "held_because": held, "bill_no": exports.bill_number(ln["deliverable"], ln["supplier"]),
                    "invoice": st["invoice"], "line": ln["line"], "supplier": ln["supplier"], "reference": ln["reference"], "date": st["date"],
                    "amount": ln["amount"], "currency": st["currency"], **steps, "assurance": ln["assurance"],
                    "payment": statement.PAY_WORDS.get(ln["payment"], ln["payment"]), "invoice_line": ln["invoice_line"],
                    "deliverable": ln["deliverable"], "settlement": ln["settlement"] or "", "statement_sha256": st["sha256"],
                    "description": f"Invoice {st['invoice']} line {ln['line']}: {ln['reference']}".rstrip(": "), "memo": memo})
    return out


def write(to: str, st: dict, status: dict | None = None, options: dict | None = None, today: str = "") -> tuple[str, str]:
    """(the payable file, the held sheet) for `to`. options: account, tax_code, date_format (written with YYYY, MM, DD,
    M and D). The held sheet is the same CSV whatever the system."""
    if to not in TARGETS:
        raise Refused(f"--to is {', '.join(TARGETS)}; {to!r} is none of them.")
    o = {**exports.DEFAULTS, **({"account": ""} if to == "xero" else {}), **{k: v for k, v in (options or {}).items() if v}}
    found = lines(st, status, today)
    pay = [b for b in found if b["payable"]]
    when = lambda b: exports.day(b["date"], o["date_format"] or str(TARGETS[to]["date"]))        # noqa: E731
    if to == "xero":
        rows = [[b["supplier"], b["bill_no"], b["invoice_line"], when(b), when(b), f"{b['description']} | {b['memo']}", 1, b["amount"], o["account"],
                 o["tax_code"], "", "", b["currency"]] for b in pay]
    elif to == "quickbooks":
        rows = [[b["bill_no"], b["supplier"], when(b), when(b), o["account"], b["description"], b["amount"], o["tax_code"], b["memo"]] for b in pay]
    elif to == "netsuite":
        rows = [[b["bill_no"], b["supplier"], when(b), b["bill_no"], b["memo"], o["account"], b["amount"], b["description"]] for b in pay]
    else:
        rows = [[b[c] if c != "date" else when(b) for c in PLAIN] for b in pay]
    held = [[b[c] for c in HELD] for b in found if not b["payable"]]
    return exports._csv([TARGETS[to]["columns"], *rows]), exports._csv([HELD, *held])


def export_file(file: Path, to: str, out: Path | None = None, options: dict | None = None, today: str | None = None) -> list[str]:
    """Write the payable file (to `out`, or `<statement>.<to>.csv` beside the statement) and its held sheet beside it.
    `today` (UTC today when None) decides whether a line nobody authorised in time is owed to the supplier, as the
    statement page does. Returns what to tell the person, one sentence a line."""
    if today is None:
        import datetime
        today = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
    st, status = statement.load(Path(file))
    payable, held = write(to, st, status, options, today)
    file = Path(file)
    name = file.name[:-5] if file.name.endswith(".json") else file.name
    out = Path(out) if out else file.parent / f"{name}.{to}.csv"
    out.write_bytes(payable.encode("utf-8"))
    held_path(out).write_bytes(held.encode("utf-8"))
    t = TARGETS[to]
    found = lines(st, status, today)
    n, m = sum(b["payable"] for b in found), sum(not b["payable"] for b in found)
    said = [f"wrote {out}: {n} {'bill' if n == 1 else 'bills'} for {t['name']} ({exports.label(to)}).",
            f"wrote {held_path(out)}: {m} held {'line' if m == 1 else 'lines'} (disputed, owed, duplicate or without enough evidence), never in the payable."]
    if t["unverified"]:
        said.append(f"Unverified: {t['unverified']}.")
    return said
