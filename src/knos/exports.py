"""A statement as the files a finance system imports: `knos audit export --format netsuite|sap|coupa|quickbooks|generic`.

Every file is made from one statement (knos.audit: scope, rows, head) and, when given, the buyer's refs file. One line
is one ACCEPTED deliverable for one supplier: a deliverable split between two payees is two lines, an order nothing
was accepted on is none. The same statement, refs and options give the same bytes. web/finance_data.js is the same
code for the console; tests/data/finance holds the files both must produce.

What every line carries, whatever the product calls the column:

    bill number    KNOS- and 11 hex digits of sha256(deliverable, supplier): 16 characters, the longest reference the
                   narrowest of these systems takes, and the same for whoever makes the file
    date           the UTC day the deliverable was accepted (its first paid or held line)
    vendor         gh:<GitHub id>. The chain has ids, not names: map them to vendor records in the import's mapping step
    amount         what was accepted for that supplier, as a decimal with two to six places (never rounded)
    memo           TEST MONEY when the amount is devnet test USDC, the settlement status, the statement's hash (the
                   head) and the receipt link: the paying transaction, which `knos receipt` rebuilds the acceptance
                   receipt from

FORMATS says, per product, where its column names come from and what could not be confirmed from the product's own
documentation. docs/FINANCE.md repeats it with the links. None of the four products' files has a place for a comment, so
an unverified format says so there and on the command's standard error, not in the file. The `generic` file is Knos's
own, says its version in its first line, and carries the whole statement after its lines, so `statement_of` gives the
statement back and its head is the head the two parties compare.

A second source is the statement of one invoice (knos.statement): `knos statement export <file> --format quickbooks|
netsuite|generic|match|ariba`. `match` is every line with its purchase order number and the result of the match
accounts payable performs (`match_of`); `ariba` is the agreed lines as one cXML InvoiceDetailRequest (STATEMENT_MORE
says what of it was seen in a vendor's published sample and what was not). There one bill is one AGREED invoice line; a disputed or duplicate line, or one without enough
evidence, is never a bill. Its memo carries the line's state, its payment status and the four ids (knos.ids), so the
record in the accounting system leads back to the line. The generic file lists every line with its state.

Every file here is LABEL, "file export, not an integration", until somebody has imported it into the product and
reconciled the result: IMPORTED is the list of formats that happened for, and it is empty.

Money here is devnet test USDC. The files write it as USD because an accounting system has no currency for test money:
import them into a sandbox company, or use them for the count only.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json

from . import audit, records

TYPE, VERSION = "knos.finance-export", 1
UNVERIFIED = "best effort, unverified"
LABEL = "file export, not an integration"
IMPORTED: dict[str, str] = {}      # format -> where a successful import and reconciliation is written up. None has been done.


def label(fmt: str) -> str:
    """What a file of this format may be called: an integration only once an import was verified."""
    return f"integration (import verified: {IMPORTED[fmt]})" if fmt in IMPORTED else LABEL


FORMATS = {
    "netsuite": {"name": "NetSuite: CSV Import, Vendor Bill", "extension": "csv", "date": "M/D/YYYY",
                 "source": "https://docs.oracle.com/en/cloud/saas/netsuite/ns-online-help/section_N427250.html",
                 "confirmed": "External ID is the unique id of a record and is written on every line of it; it is mapped to Reference No.; the body "
                              "fields Vendor and Date; on the Expenses sublist, Account, Amount and Memo; at least one line per new record; the "
                              "currency is taken from the vendor record, so the file has no currency column; a Purchase Order field exists and cannot be "
                              "mapped together with the Expenses sublist, so this file carries no order column (read again 2026-10-07)",
                 "unverified": "the date format (the page names none: M/D/YYYY is written, change it with --date-format), the body field Memo, "
                               "and which fields an account's own form makes mandatory"},
    "sap": {"name": "SAP S/4HANA: Import Supplier Invoices (app F3041)", "extension": "csv", "date": "YYYYMMDD",
            "source": "https://userapps.support.sap.com/sap/support/knowledge/en/3782347",
            "confirmed": "the app takes a spreadsheet template with one row per item, the invoice ID in the first column and the header fields "
                         "repeated on every row of an invoice (read again 2026-10-07: the note names no column but the first)",
            "unverified": "every column name, the date format and the field lengths: SAP publishes the template inside the app, not on a public "
                          "page. The whole file is " + UNVERIFIED},
    "coupa": {"name": "Coupa: flat file (CSV) import, Invoices", "extension": "csv", "date": "YYYY-MM-DD",
              "source": "https://compass.coupa.com/en-us/products/product-documentation/integration-technical-documentation/"
                        "coupa-core-flat-files-(csv)/flat-file-(csv)-import/invoices-import",
              "confirmed": "the row types Invoice, Invoice Line and Invoice Charge, the first 24 columns of the Invoice row in order, and that a "
                           "date carries no time (read again 2026-10-07)",
              "unverified": "the Invoice Line row written here is NOT the page's: read 2026-10-07, the page lists Supplier Part Number and Auxiliary "
                            "Part Number between Description and Price, names the unit column Unit of Measure (this file writes UOM), puts some twenty "
                            "columns between it and PO Number, and has PO Line Number and Match Reference, which this file lacks. Also not "
                            "confirmed: the Invoice row's columns after the 24th and the date's order. The whole file is " + UNVERIFIED},
    "quickbooks": {"name": "QuickBooks Online: import bills", "extension": "csv", "date": "D/M/YYYY",
                   "source": "https://quickbooks.intuit.com/learn-support/en-ca/help-article/import-transactions/import-bills-quickbooks-online/L4Q6QWsRw_ROW_en",
                   "confirmed": "the mandatory columns Bill no., Supplier, Bill Date, Due Date, Account, Line Amount and Line Tax Code; every "
                                "line of a bill repeats Bill no., Supplier and Bill Date; the date format is chosen at import (D/M/YYYY is the "
                                "page's example); at most 100 bills a file is recommended; the page names no purchase-order column (read again 2026-10-07)",
                   "unverified": "the optional columns Line Description and Memo, and the United States edition, whose own page could not be read"},
    "generic": {"name": "Knos: generic finance export", "extension": "csv", "date": "YYYY-MM-DD", "source": "docs/FINANCE.md", "confirmed": "Knos's own format",
                "unverified": ""},
}
DEFAULTS = {"account": "Accepted agent work", "entity": "", "tax_code": "", "date_format": ""}
"""Options of a file. account: the expense or general-ledger account every line is booked to. entity: SAP's company
code and Coupa's chart of accounts. tax_code: QuickBooks' Line Tax Code and SAP's tax code (empty: none). date_format:
another format than the product's default, written with YYYY, MM, DD, M and D."""
NETSUITE = ("External ID", "Vendor", "Date", "Reference No.", "Memo", "Expenses : Account", "Expenses : Amount", "Expenses : Memo")
QUICKBOOKS = ("Bill no.", "Supplier", "Bill Date", "Due Date", "Account", "Line Description", "Line Amount", "Line Tax Code", "Memo")
COUPA_INVOICE = ("Invoice", "Invoice Number", "Supplier Name", "Supplier Number", "Status", "Invoice Date", "Submit For Approval?", "Handling Amount",
                 "Misc Amount", "Shipping Amount", "Line Level Taxation", "Tax Amount", "Tax Rate", "Tax Code", "Tax Rate Type", "Supplier Note",
                 "Payment Terms", "Shipping Terms", "Requester Email", "Requester Name", "Requester Lookup Name", "Chart of Accounts", "Currency",
                 "Contract Number")
COUPA_LINE = ("Invoice Line", "Invoice Number", "Supplier Name", "Supplier Number", "Line Number", "Description", "Price", "Quantity", "UOM",
              "PO Number", "Account Name", "Billing Notes")
SAP = ("Invoice ID", "Company Code", "Transaction", "Invoicing Party", "Reference", "Document Date", "Posting Date", "Document Type",
       "Document Header Text", "Document Currency", "Gross Invoice Amount", "G/L Account", "Item Text", "Debit/Credit", "Amount", "Tax Code", "Assignment")
GENERIC = ("bill_no", "deliverable", "record", "date", "supplier", "supplier_wallet", "repository_id", "issue", "artifact", "amount", "amount_units",
           "currency", "fee_units", "status", "invoice_ref", "billed_before", "dispute", "correction", "terms_hash", "terms_version", "evaluator",
           "authorised_by", "receipt", "statement_head")
ISO = {records.TEST: "USD"}        # what an accounting system is told: it has no currency for test money (the memo says TEST MONEY)


def decimal(units: int) -> str:
    """19500000 as "19.50", 404999 as "0.404999": two to six places, never rounded."""
    whole, part = divmod(int(units), 1_000_000)
    text = f"{part:06d}".rstrip("0")
    return f"{whole}.{text:0<2}"


def day(date: str, fmt: str) -> str:
    """A day (2026-09-03) in a product's format: YYYY, MM, DD, and M and D without the leading zero."""
    y, m, d = date.split("-")
    out, at = "", 0
    while at < len(fmt):
        for token, value in (("YYYY", y), ("MM", m), ("DD", d), ("M", str(int(m))), ("D", str(int(d)))):
            if fmt.startswith(token, at):
                out, at = out + value, at + len(token)
                break
        else:
            out, at = out + fmt[at], at + 1
    return out


def bill_number(deliverable: str, supplier: str) -> str:
    return "KNOS-" + hashlib.sha256(f"{deliverable}|{supplier}".encode()).hexdigest()[:11].upper()


def bills(scope: dict, rows: list[dict], head: str, refs: dict | None = None) -> list[dict]:
    """One dict per accepted deliverable per supplier, in the statement's order: what every format is written from."""
    out = []
    for rec in audit.records_of(rows, refs):
        a, c, m, s = (rec[k] for k in audit.OBJECTS)
        if not c["accepted"]:
            continue
        mine = [r for r in rows if audit.deliverable_of(r) == rec["id"]]
        first = next(r for r in mine if audit._text(r["verdict"]) == "accepted")
        tx = next((e["transaction"] for e in c["evidence"] if e["what"] in ("paid", "held")), "")
        for sup in a["supplier"]:
            units = sup["units"] or (m["amount_units"] if len(a["supplier"]) == 1 else 0)
            if not units:
                continue
            vendor = f"gh:{sup['github_id']}"
            test = m["currency"] == records.TEST and s["status"] != audit.OUTSIDE
            where = "a private order" if a["scope"]["private"] else f"repository {a['scope']['repository_id']} issue {a['scope']['issue']}"
            out.append({
                "bill_no": bill_number(rec["id"], vendor), "deliverable": rec["id"], "record": rec["record"], "date": audit._text(first["date"]),
                "supplier": vendor, "supplier_wallet": sup["wallet"], "repository_id": a["scope"]["repository_id"], "issue": a["scope"]["issue"],
                "artifact": c["artifact"] or "", "amount": decimal(units), "amount_units": units, "currency": m["currency"],
                "iso": ISO.get(m["currency"], ""), "fee_units": m["fee_units"], "status": s["status"], "invoice_ref": m["invoice_ref"] or "",
                "billed_before": int(m["billed_before"]), "dispute": m["dispute"] or "",
                "correction": f"{m['correction']['kind']} {m['correction']['units']}" if m["correction"] else "",
                "terms_hash": c["policy"]["terms_hash"] or "", "terms_version": c["policy"]["version"] or "",
                "evaluator": ";".join(e["kind"] for e in c["evaluators"]), "authorised_by": f"{a['approved_by']['funder']} ({a['approved_by']['role']})",
                "receipt": audit.EXPLORER.format(tx) if tx else "", "transaction": tx, "statement_head": head,
                "description": f"Accepted deliverable: {where}" + (f", {c['artifact']}" if c["artifact"] else ""),
                "memo": " | ".join(x for x in ("TEST MONEY (devnet test USDC): not a payable" if test else "", s["status"], f"Knos statement sha256:{head}",
                                                f"receipt {audit.EXPLORER.format(tx)}" if tx else "", f"deliverable {rec['id']}",
                                                f"ref {m['invoice_ref']}" if m["invoice_ref"] else "") if x)})
    return out


def _csv(lines: list) -> str:
    buf = io.StringIO()
    out = csv.writer(buf, lineterminator="\n")
    for cells in lines:
        out.writerow([records._cell(c) for c in cells])
    return buf.getvalue()


def write(fmt: str, scope: dict, rows: list[dict], head: str, refs: dict | None = None, options: dict | None = None) -> str:
    """The file of one format. `rows`: the statement's rows with `seq` and `prev` (audit.chained, or audit.parse)."""
    if fmt not in FORMATS:
        raise audit.Refused(f"--format is csv, json, {', '.join(FORMATS)}; {fmt!r} is none of them.")
    o = {**DEFAULTS, **{k: v for k, v in (options or {}).items() if v}}
    rows = [{k: audit._text(v) for k, v in r.items()} for r in rows]
    found = bills(scope, rows, head, refs)
    when = lambda b: day(b["date"], o["date_format"] or FORMATS[fmt]["date"])       # noqa: E731
    if fmt == "netsuite":
        return _csv([NETSUITE, *([b["bill_no"], b["supplier"], when(b), b["bill_no"], b["memo"], o["account"], b["amount"], b["description"]]
                                 for b in found)])
    if fmt == "quickbooks":
        return _csv([QUICKBOOKS, *([b["bill_no"], b["supplier"], when(b), when(b), o["account"], b["description"], b["amount"], o["tax_code"], b["memo"]]
                                   for b in found)])
    if fmt == "coupa":
        lines: list = [COUPA_INVOICE, COUPA_LINE]
        for b in found:
            lines.append(["Invoice", b["bill_no"], b["supplier"], b["supplier"], "draft", when(b), "No", "", "", "", "No", "", "", "", "", b["memo"], "", "",
                          "", "", "", o["entity"], b["iso"], ""])
            lines.append(["Invoice Line", b["bill_no"], b["supplier"], b["supplier"], 1, b["description"], b["amount"], 1, "EA", b["invoice_ref"],
                          o["account"], f"Knos {head}"])
        return _csv(lines)
    if fmt == "sap":
        return _csv([SAP, *([b["bill_no"], o["entity"], 1, b["supplier"], b["bill_no"], when(b), when(b), "KR", f"Knos {head[:20]}", b["iso"], b["amount"],
                             o["account"], f"Knos {head[:16]} tx {b['transaction'][:24]}", "S", b["amount"], o["tax_code"], b["invoice_ref"][:18]]
                            for b in found)])
    sums = audit.totals(rows)
    return _csv([[TYPE, "version", VERSION, "generic"], GENERIC, *([b[c] for c in GENERIC] for b in found),
                 *(["statement", r["seq"], json.dumps(r, sort_keys=True, separators=(",", ":"), ensure_ascii=True)] for r in rows),
                 *(["total", cur, t["lines"], *(t[c] for c in audit.SUMS)] for cur, t in sums.items()),
                 ["head", head, len(rows), json.dumps(scope, sort_keys=True, separators=(",", ":"), ensure_ascii=True)]])


def statement_of(text: str) -> str:
    """The statement a generic file carries, as `knos audit export --format csv` wrote it: the same bytes, so
    `knos audit verify` checks it and its head is the one to compare. Refused, in words, for another file."""
    got = list(csv.reader(io.StringIO(text)))
    if not got or got[0] != [TYPE, "version", str(VERSION), "generic"]:
        raise audit.Refused("This is not a generic finance export of this version: its first line does not say so.")
    try:
        tail = next(c for c in got if c[:1] == ["head"] and len(c) == 4)
        scope = json.loads(tail[3])
        rows = [json.loads(c[2][1:] if c[2][:1] == "'" else c[2]) for c in got if c[:1] == ["statement"] and len(c) == 3]
    except (StopIteration, ValueError):
        raise audit.Refused("This generic finance export has no statement at its end: it was cut short or edited.") from None
    return audit.write(scope, rows, tail[1], "csv")



# ---- from the statement of one invoice (knos.statement) -----------------------------------------------------------------
STATEMENT_FORMATS = ("quickbooks", "netsuite", "generic")
STATEMENT_GENERIC = ("bill_no", "line", "state", "payment", "date", "supplier", "reference", "amount", "currency", "why", "deliverable", "evaluations",
                     "invoice_line", "settlement", "evidence", "evidence_sha256", "duplicate_of", "statement_sha256", "po_reference", "grn_reference", "assurance")


def statement_bills(st: dict, status: dict | None = None) -> list[dict]:
    """One dict per line of a statement, in its order, with what the status file adds. `bill` is true for an agreed
    line only: that is what the two products' files hold. Each carries the three things a three-way match keys on: the
    purchase order's reference (when a goods-received note was recorded: `knos statement grn --record`), the note's
    reference and the assurance level. The generic file has a column for each; QuickBooks' and NetSuite's import
    templates have none, so there they are in the memo."""
    from . import ids, statement
    out = []
    for ln in statement.lines_now(st, status):
        words, paid = ids.LINE_WORDS[ln["state"]], statement.PAY_WORDS[ln["payment"]]
        out.append({"bill": ln["state"] == "agreed", "bill_no": bill_number(ln["deliverable"], ln["supplier"]), "line": ln["line"], "state": words,
                    "payment": paid, "date": st["date"], "supplier": ln["supplier"], "reference": ln["reference"], "amount": ln["amount"],
                    "currency": st["currency"], "why": ln["why"], "deliverable": ln["deliverable"], "evaluations": " ".join(ln["evaluations"]),
                    "invoice_line": ln["invoice_line"], "settlement": ln["settlement"] or "", "evidence": ln["evidence"],
                    "evidence_sha256": ln["evidence_sha256"], "duplicate_of": ln["duplicate_of"], "statement_sha256": st["sha256"],
                    "po_reference": ln["po_reference"], "grn_reference": ln["grn_reference"], "assurance": ln["assurance"],
                    "description": f"Invoice {st['invoice']} line {ln['line']}: {ln['reference']}".rstrip(": "),
                    "memo": " | ".join(x for x in (f"{words}, {paid}", f"Knos statement sha256:{st['sha256']}", f"deliverable {ln['deliverable']}",
                                                    f"invoice line {ln['invoice_line']}", *(f"evaluation {e}" for e in ln["evaluations"]),
                                                    f"settlement {ln['settlement']}" if ln["settlement"] else "",
                                                    f"PO {ln['po_reference']}" if ln["po_reference"] else "", f"GRN {ln['grn_reference']}" if ln["grn_reference"] else "",
                                                    f"assurance {ln['assurance']}") if x)})
    return out


def write_statement(fmt: str, st: dict, status: dict | None = None, options: dict | None = None) -> str:
    """The file of one format for the statement of one invoice. QuickBooks and NetSuite get the agreed lines as bills;
    the generic file gets every line with its state. The same statement, status and options give the same bytes."""
    if fmt in STATEMENT_MORE:
        return write_more(fmt, st, status, options)
    if fmt not in STATEMENT_FORMATS:
        raise audit.Refused(f"--format is {', '.join((*STATEMENT_FORMATS, *STATEMENT_MORE))}; {fmt!r} is none of them.")
    o = {**DEFAULTS, **{k: v for k, v in (options or {}).items() if v}}
    found = statement_bills(st, status)
    bills_ = [b for b in found if b["bill"] and b["amount"]]
    when = lambda b: day(b["date"], o["date_format"] or FORMATS[fmt]["date"])       # noqa: E731
    if fmt == "netsuite":
        return _csv([NETSUITE, *([b["bill_no"], b["supplier"], when(b), b["bill_no"], b["memo"], o["account"], b["amount"], b["description"]] for b in bills_)])
    if fmt == "quickbooks":
        return _csv([QUICKBOOKS, *([b["bill_no"], b["supplier"], when(b), when(b), o["account"], b["description"], b["amount"], o["tax_code"], b["memo"]]
                                   for b in bills_)])
    return _csv([[TYPE, "version", VERSION, "statement", LABEL], STATEMENT_GENERIC, *([b[c] for c in STATEMENT_GENERIC] for b in found)])


# ---- the purchase-order match, and the invoice as cXML ---------------------------------------------------------------------
STATEMENT_MORE = {
    "match": {"name": "Knos: purchase-order match", "extension": "csv", "source": "docs/RAILS.md", "confirmed": "Knos's own format", "unverified": ""},
    "ariba": {"name": "SAP Ariba: cXML InvoiceDetailRequest", "extension": "xml",
              "source": "https://compass.coupa.com/en-us/products/product-documentation/supplier-resources/for-suppliers/integration-resources/"
                        "standard-invoice-examples/sample-cxml-invoice-with-both-backed-and-unbacked-lines",
              "confirmed": "from two published samples of the cXML invoice (read 2026-10-07; neither is SAP's own page): the document type line; the "
                           "Header's From, To and Sender; InvoiceDetailRequestHeader with invoiceID, purpose, operation and invoiceDate, then "
                           "InvoiceDetailHeaderIndicator and InvoiceDetailLineIndicator; one InvoiceDetailOrder per order, its OrderReference with a "
                           "DocumentReference, or a MasterAgreementReference with an empty DocumentReference for lines no order backs; "
                           "InvoiceDetailItem with UnitOfMeasure, UnitPrice, InvoiceDetailItemReference and SubtotalAmount in that order; "
                           "InvoiceDetailSummary with SubtotalAmount, Tax and NetAmount",
              "unverified": "SAP Ariba's own guide and the cXML document type definition could not be read here, so the file was held to neither; the "
                            "place of the Extrinsic elements; the orderID attribute; the Sender's SharedSecret, which is left out on purpose (the "
                            "sending gateway adds it); the order's own payload id and line numbers, which a statement does not know (the order's "
                            "number and the invoice's line are written instead). The whole file is " + UNVERIFIED},
}
MATCH = ("bill_no", "line", "supplier", "reference", "amount", "currency", "state", "payment", "po_number", "grn_reference", "match", "match_legs",
         "match_why", "assurance", "invoice_line", "deliverable", "settlement", "statement_sha256")
MATCH_WORDS = {"3-way": "purchase order + receipt of goods + invoice line", "2-way": "receipt of goods + invoice line", "none": ""}


def match_of(st: dict, status: dict | None = None) -> list[dict]:
    """Every line of a statement with its purchase order number and the match accounts payable performs:

        3-way    a goods-received note is recorded for the line (`knos statement grn --record`) and it matches: the
                 order, the acceptance and the invoice line agree
        2-way    the line is agreed and an evaluation stands behind it, and no order is on record: the receipt of goods
                 and the invoice line agree. (Accounts payable usually means order against invoice by "2-way"; a
                 statement knows the acceptance before it knows the order, so `match_legs` names the two legs.)
        none     anything else, with why: the note's mismatches, or the line's own state
    """
    from . import ids, statement
    events = statement._status(st, status)["events"]
    out = []
    for b, ln in zip(statement_bills(st, status), statement.lines_now(st, status)):
        noted = [e["grn"] for e in events if e["type"] == "grn" and e["line"] == ln["invoice_line"]]
        if noted:
            got, why = ("3-way", "") if noted[-1]["match"] else ("none", "; ".join(noted[-1]["mismatches"]))
        elif ln["state"] == "agreed" and ln["evaluations"]:
            got, why = "2-way", "no purchase order on record: record the goods-received note from the payment's receipt (knos statement grn --record)"
        else:
            got, why = "none", ids.LINE_WORDS[ln["state"]] + (f": {ln['why']}" if ln["why"] else "") if ln["state"] != "agreed" else "no evaluation on record"
        out.append({**b, "po_number": b["po_reference"], "match": got, "match_legs": MATCH_WORDS[got], "match_why": why})
    return out


def _x(text) -> str:
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def cxml(st: dict, status: dict | None = None, options: dict | None = None) -> str:
    """The agreed lines of a statement as one cXML InvoiceDetailRequest. Lines are grouped by purchase order number; a
    line with none goes under an agreement reference left empty, as an invoice no order backs. Each line carries its
    ids, its goods-received note and its match as Extrinsic elements. `options`: supplier_id, buyer_id (the two parties'
    identities on the network) and deployment (test, the default, or production)."""
    o = {"supplier_id": "", "buyer_id": "", "deployment": "test", **{k: v for k, v in (options or {}).items() if v}}
    found = [m for m in match_of(st, status) if m["bill"] and m["amount"]]
    cur, total = _x(st["currency"]), sum(_units(m["amount"], st["scale"]) for m in found)
    money = lambda amount: f'<Money currency="{cur}">{_x(amount)}</Money>'              # noqa: E731
    who = lambda tag, ident: f'    <{tag}><Credential domain="NetworkID"><Identity>{_x(ident)}</Identity></Credential></{tag}>'      # noqa: E731
    out = ['<?xml version="1.0" encoding="UTF-8"?>', '<!DOCTYPE cXML SYSTEM "http://xml.cXML.org/schemas/cXML/1.2.020/InvoiceDetail.dtd">',
           f'<cXML payloadID="{st["sha256"][:32]}@knos.statement" timestamp="{st["date"]}T00:00:00+00:00" version="1.2.020">', "  <Header>",
           who("From", o["supplier_id"] or st["supplier"]), who("To", o["buyer_id"] or st["buyer"]),
           who("Sender", o["supplier_id"] or st["supplier"]).replace("</Sender>", "<UserAgent>Knos statement export</UserAgent></Sender>"), "  </Header>",
           f'  <Request deploymentMode="{_x(o["deployment"])}">', "    <InvoiceDetailRequest>",
           f'      <InvoiceDetailRequestHeader invoiceID="{_x(st["invoice"])}" purpose="standard" operation="new" invoiceDate="{st["date"]}T00:00:00+00:00">',
           "        <InvoiceDetailHeaderIndicator/>", "        <InvoiceDetailLineIndicator/>",
           f'        <Extrinsic name="knosStatementSha256">{st["sha256"]}</Extrinsic>', "      </InvoiceDetailRequestHeader>"]
    orders: dict[str, list[dict]] = {}
    for m in found:
        orders.setdefault(m["po_number"], []).append(m)
    for po, mine in orders.items():
        ref = (f'<OrderReference orderID="{_x(po)}"><DocumentReference payloadID="{_x(po)}"/></OrderReference>' if po
               else '<MasterAgreementReference><DocumentReference payloadID=""/></MasterAgreementReference>')
        out += ["      <InvoiceDetailOrder>", f"        <InvoiceDetailOrderInfo>{ref}</InvoiceDetailOrderInfo>"]
        for m in mine:
            out += [f'        <InvoiceDetailItem invoiceLineNumber="{m["line"]}" quantity="1">', "          <UnitOfMeasure>EA</UnitOfMeasure>",
                    f"          <UnitPrice>{money(m['amount'])}</UnitPrice>",
                    f'          <InvoiceDetailItemReference lineNumber="{m["line"]}"><Description xml:lang="en">{_x(m["description"])}</Description>'
                    "</InvoiceDetailItemReference>",
                    f"          <SubtotalAmount>{money(m['amount'])}</SubtotalAmount>",
                    *(f'          <Extrinsic name="{name}">{_x(value)}</Extrinsic>' for name, value in (
                        ("knosInvoiceLine", m["invoice_line"]), ("knosDeliverable", m["deliverable"]), ("knosGoodsReceivedNote", m["grn_reference"]),
                        ("knosMatch", m["match"]), ("knosAssurance", m["assurance"]), ("knosSettlement", m["settlement"])) if value),
                    "        </InvoiceDetailItem>"]
        out.append("      </InvoiceDetailOrder>")
    summed = _amount(total, st["scale"])
    out += ["      <InvoiceDetailSummary>", f"        <SubtotalAmount>{money(summed)}</SubtotalAmount>",
            f'        <Tax>{money("0.00")}<Description xml:lang="en">The statement states no tax</Description></Tax>',
            f"        <NetAmount>{money(summed)}</NetAmount>", "      </InvoiceDetailSummary>", "    </InvoiceDetailRequest>", "  </Request>", "</cXML>"]
    return "\n".join(out) + "\n"


def _units(amount: str, scale: int) -> int:
    from . import statement
    return statement.units(amount, scale)


def _amount(value: int, scale: int) -> str:
    from . import statement
    return statement.amount_of(value, scale)


def write_more(fmt: str, st: dict, status: dict | None = None, options: dict | None = None) -> str:
    """The `match` file (every line, CSV) or the `ariba` file (the agreed lines, cXML)."""
    if fmt == "ariba":
        return cxml(st, status, options)
    if fmt != "match":
        raise audit.Refused(f"--format is {', '.join((*STATEMENT_FORMATS, *STATEMENT_MORE))}; {fmt!r} is none of them.")
    return _csv([[TYPE, "version", VERSION, "match", LABEL], MATCH, *([m[c] for c in MATCH] for m in match_of(st, status))])
