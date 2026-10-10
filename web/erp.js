// The statement of one invoice as the bill-import file of the approver's accounting system: src/knos/erp.py, in the
// browser. The payable file holds one bill per line whose policy is met and that is not owed to the supplier, its memo
// the line's four steps and assurance level; every other line goes to the held sheet, never to the payable.
// tests/web/erp.mjs holds the bytes equal to the Python's.
import { statementLines, billNumber, day, text, PAY_WORDS, LINE_WORDS, STEPS, STEP_WORDS, OWED_WORDS, DEFAULTS } from "./finance_data.js";

export const XERO = ["ContactName", "InvoiceNumber", "Reference", "InvoiceDate", "DueDate", "Description", "Quantity", "UnitAmount", "AccountCode", "TaxType",
  "InventoryItemCode", "Discount", "Currency"];
export const QUICKBOOKS = ["Bill no.", "Supplier", "Bill Date", "Due Date", "Account", "Line Description", "Line Amount", "Line Tax Code", "Memo"];
export const NETSUITE = ["External ID", "Vendor", "Date", "Reference No.", "Memo", "Expenses : Account", "Expenses : Amount", "Expenses : Memo"];
export const PLAIN = ["bill_no", "invoice", "line", "supplier", "reference", "date", "amount", "currency", "policy", "accepted", "authorised", "settled",
  "assurance", "payment", "invoice_line", "deliverable", "settlement", "statement_sha256"];
export const HELD = ["bill_no", "invoice", "line", "supplier", "reference", "amount", "currency", "held_because", "policy", "accepted", "authorised",
  "settled", "assurance", "invoice_line", "deliverable", "statement_sha256"];
/** erp.TARGETS: the name each system gives its import, its columns and its default date. */
export const TARGETS = {
  xero: { name: "Xero", columns: XERO, date: "DD/MM/YYYY" },
  quickbooks: { name: "QuickBooks Online", columns: QUICKBOOKS, date: "D/M/YYYY" },
  netsuite: { name: "NetSuite", columns: NETSUITE, date: "M/D/YYYY" },
  csv: { name: "Any other (CSV)", columns: PLAIN, date: "YYYY-MM-DD" },
};

// records._cell, then a field as Python's csv module writes it
const cell = (v) => { const t = text(v); return /^[=+\-@\t\r]/.test(t) ? `'${t}` : t; };
const field = (v) => { const t = cell(v); return /[",\n\r]/.test(t) ? `"${t.replace(/"/g, '""')}"` : t; };
const csvOf = (lines) => lines.map((cells) => `${cells.map(field).join(",")}\n`).join("");
const stepText = (x) => { const done = { done: "yes", failed: "no" }[x.state] || "not yet"; return x.said ? `${done}, ${x.said}` : done; };

/** erp.lines: every line with its bill number, four steps in words, memo, and whether it is payable. */
export async function erpLines(st, status = null, today = "") {
  const out = [];
  for (const ln of statementLines(st, status, today)) {
    const steps = Object.fromEntries(ln.steps.map((x) => [x.step, stepText(x)]));
    const payable = ln.state === "agreed" && !ln.owed && Boolean(ln.amount);
    const held = payable ? "" : ln.owed ? `${OWED_WORDS}: the policy is met and the buyer refused it or left it unauthorised; the supplier may appeal`
      : ln.state === "agreed" ? "no amount" : LINE_WORDS[ln.state] + (ln.why ? `: ${ln.why}` : "");
    const memo = [...STEPS.map((s) => `${STEP_WORDS[s]}: ${steps[s]}`), `assurance ${ln.assurance}`, `Knos statement sha256:${st.sha256}`,
      `invoice line ${ln.invoice_line}`, `deliverable ${ln.deliverable}`].join(" | ");
    out.push({ payable, held_because: held, bill_no: await billNumber(ln.deliverable, ln.supplier), invoice: st.invoice, line: ln.line, supplier: ln.supplier,
      reference: ln.reference, date: st.date, amount: ln.amount, currency: st.currency, ...steps, assurance: ln.assurance,
      payment: PAY_WORDS[ln.payment] ?? ln.payment, invoice_line: ln.invoice_line, deliverable: ln.deliverable, settlement: ln.settlement || "",
      statement_sha256: st.sha256, description: `Invoice ${st.invoice} line ${ln.line}: ${ln.reference}`.replace(/[: ]+$/, ""), memo });
  }
  return out;
}

/** erp.write: { payable, held, bills, heldLines } for `to` (xero, quickbooks, netsuite or csv). */
export async function erpWrite(to, st, status = null, options = null, today = "") {
  if (!TARGETS[to]) throw new Error(`--to is ${Object.keys(TARGETS).join(", ")}; "${to}" is none of them.`);
  const o = { ...DEFAULTS, ...(to === "xero" ? { account: "" } : {}), ...Object.fromEntries(Object.entries(options || {}).filter(([, v]) => v)) };
  const found = await erpLines(st, status, today), pay = found.filter((b) => b.payable), when = (b) => day(b.date, o.date_format || TARGETS[to].date);
  const rows = to === "xero" ? pay.map((b) => [b.supplier, b.bill_no, b.invoice_line, when(b), when(b), `${b.description} | ${b.memo}`, 1, b.amount, o.account, o.tax_code, "", "", b.currency])
    : to === "quickbooks" ? pay.map((b) => [b.bill_no, b.supplier, when(b), when(b), o.account, b.description, b.amount, o.tax_code, b.memo])
      : to === "netsuite" ? pay.map((b) => [b.bill_no, b.supplier, when(b), b.bill_no, b.memo, o.account, b.amount, b.description])
        : pay.map((b) => PLAIN.map((c) => (c === "date" ? when(b) : b[c])));
  const held = found.filter((b) => !b.payable);
  return { payable: csvOf([TARGETS[to].columns, ...rows]), held: csvOf([HELD, ...held.map((b) => HELD.map((c) => b[c]))]), bills: pay.length, heldLines: held.length };
}
