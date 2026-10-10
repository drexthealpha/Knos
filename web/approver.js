// The approver's screen: one invoice, one row per line, read left to right:
//   Supplier -> Purchase order -> Agreed deliverable -> Acceptance evidence -> Authorised amount -> Exception -> Payment status
// and under it ONE queue of every line that is not agreed, each with its reason in one sentence and the two things an
// approver can do: approve the agreed lines, or send the exception to the supplier as a message that is already written.
//
//   renderApprover(el[, ctx])     the screen in `el`. ctx, all optional: { now } a Date for the approval's day, { rails } a
//                                 module with pain001(statement, payer, status) and, when it draws its own form,
//                                 renderRails(el, { statement, status }) (web/rails.js is asked for when left out),
//                                 { recall } a module with renderRecall(el, rows) (web/recall.js likewise), { time } the
//                                 measured steps instead of approver_time.json. Returns { take, sample, state }.
//   readOrders(text)              the purchase orders a CSV names: { "owner/repo#n": { number, limit } } (limit in hundredths)
//   rowsOf(st, status, orders, receipts)   the rows of a statement, each with its exception (or none) and why
//   uncheckedRows(invoice, orders)         the rows of an invoice no statement covers: every line an exception
//   partsOf(doc), readReceipts(doc)        a receipt's five parts, from the JSON shape below
//   messageOf(row, st)            { subject, body }: the message to the supplier about one exception
//   EXCEPTIONS, WORDS, COLUMNS, PARTS
//
// WHAT IT READS. Files dropped, chosen or pasted, in any order, and nothing else: a statement (`knos statement make`,
// kind knos-statement), its status file (kind knos-statement-status), the invoice (CSV, read by web/shadow.js `parse`,
// the front door's reader; the columns po_number and po_amount, when it has them, name each line's purchase order and
// its limit), and receipts' five parts. The sample is the front door's made-up invoice and its recorded answers
// (web/front_door_sample.js), made into a statement here by web/statement_make.js. This module asks nobody anything:
// no GitHub, no Solana, no host but the site it came from (approver_time.json; rails.js and recall.js when they exist).
//
// THE FIVE EXCEPTIONS. disputed, duplicate and insufficient evidence are the statement's own line states
// (src/knos/ids.py LINE_STATES). replayed is the statement's duplicate whose earlier billing is on ANOTHER statement
// (`duplicate_of` starts "statement "). over the purchase order is worked out HERE, not in the statement: agreed lines
// are added up per purchase order in line order, and a line that takes the sum past the limit the invoice file states is
// held. It is advisory: the statement still calls that line agreed, `knos statement approve` would approve it, and no
// program enforces a purchase order. The approval this page records leaves it out (statement_make.js `approve`, `only`).
//
// A RECEIPT'S FIVE PARTS, as this page reads them (src/knos/receipt.py `parts`; `knos receipt explain` prints them):
//   { "invoice_line": "inv_...", "deliverable": "dlv_...", "reference": "owner/repo#12",       any one names the line
//     "parts": { "identity": P, "execution": P, "acceptance": P, "consequence": P, "assurance": P } }
// P is one sentence, or an object whose `said` (or `line`, `summary`, `text`) is the sentence and whose other fields
// are shown as facts under it. `parts` may also be a list of { "name": "identity", ... }; names may be capitalised.
// What `knos receipt explain --json` writes is read as it is: { "kind": "knos-receipt-parts", "v": 1, "parts": [{ "id",
// "title", "asks", "line", "facts": { ... }, "more": [...] }] }; its line is named by the facts of its parts.
// A file holds one such object, a list of them, or { "receipts": [ ... ] }. A receipt missing a part is not shown.
import { parse, pullOf, cents, money } from "./shadow.js";
import { csvRows, statementLines, statementDigest, statementCsv, statementExport, statementUnits as units, statementAmount as amountOf, canonicalText, sha256Hex,
  STATEMENT_KIND, STATUS_KIND, PAY_WORDS, HANDED } from "./finance_data.js";
import { fromShadow, approve as approveLines, accept as acceptLines } from "./statement_make.js";
import { stepRowHtml, stepStyle } from "./line_steps.js";
import { SAMPLE_INVOICE, SAMPLE_BOOK, SAMPLE_META } from "./front_door_sample.js";

export const EXCEPTIONS = ["disputed", "duplicate", "insufficient_evidence", "over_po", "over_limit", "replayed"];
export const WORDS = { disputed: "disputed", duplicate: "duplicate", insufficient_evidence: "insufficient evidence", over_po: "over the purchase order", over_limit: "over your approval limit",
  replayed: "replayed" };
export const COLUMNS = [["supplier", "Supplier"], ["po", "Authorisation"], ["deliverable", "Agreed deliverable"], ["evidence", "Acceptance evidence"],
  ["amount", "Amount to approve"], ["exception", "Exception"], ["payment", "Payment status"]];
export const PARTS = ["identity", "execution", "acceptance", "consequence", "assurance"];
export const PRIVATE_PATH = "https://github.com/drexthealpha/Knos/blob/main/docs/PRIVATE.md";
// The sample's purchase orders: made up, like its invoice. Both limits cover what is agreed, so the sample can be paid.
export const SAMPLE_ORDERS = "pull_request,po_number,po_amount\nexample-co/storefront#101,PO-1001,1500.00\nexample-co/storefront#102,PO-1001,1500.00\nexample-co/storefront#103,PO-1001,1500.00\n"
  + "example-co/storefront#104,PO-1001,1500.00\nexample-co/storefront#105,PO-1001,1500.00\nexample-co/billing-internal#7,PO-1002,500.00\n";
// the accounting systems a bill-import file is written for (web/finance_data.js statementExport; docs/FINANCE.md)
const SYSTEMS = { quickbooks: "QuickBooks", netsuite: "NetSuite" };
const REMEDY = { disputed: "Send the passing run for this change, or appeal.", duplicate: "Withdraw the line, or name the separate deliverable it is for.",
  replayed: "Withdraw the line: an earlier invoice was agreed for this deliverable.", insufficient_evidence: "Send evidence that this line was accepted.",
  over_po: "Ask for the purchase order to be raised, or bill this line later.", over_limit: "Ask an approver whose limit covers this amount." };
// THE POLICY an approval is made under. An ordinary line meets all three rules and is approved with the others in one
// action; any other line is an exception and is read on its own. The version changes when a rule changes, so a record
// made under version 1 is always read against version 1's rules. `limit` is the approver's own (null: none stated).
export const POLICY = { id: "knos.approval-policy", version: 1, ordinary: ["the statement calls the line agreed", "the agreed lines stay within their purchase order",
  "the line is within the approver's limit"] };
export const RECORD_KIND = "knos-approval-record";
/** An amount as a person reads it: 1500.00 as 1,500.00. Files keep the plain form; only the screen groups the digits. */
export const group = (text) => String(text ?? "").replace(/^(-?)(\d{4,})/, (m, sign, whole) => sign + whole.replace(/\B(?=(\d{3})+(?!\d))/g, ","));

const PO_NAMES = ["po", "po_number", "po_no", "po_reference", "purchase_order"];
const LIMIT_NAMES = ["po_amount", "po_limit", "po_value", "authorised", "authorized", "authorised_amount", "authorized_amount"];
const refOf = (text) => { const n = pullOf(String(text || "")); return n ? `${n.repo}#${n.number}`.toLowerCase() : ""; };

/** The purchase orders a CSV names, by pull request: { "owner/repo#n": { number, limit } }. `limit` is the order's amount
 *  in hundredths (a BigInt), or null when the file gives none. A file with no purchase order column names none. */
export function readOrders(text) {
  const rows = csvRows(String(text || "").replace(/^﻿+/, "")).filter((r) => r.length && !String(r[0]).trim().startsWith("#"));
  if (!rows.length) return {};
  const head = rows[0].map((c) => c.trim().toLowerCase().replace(/[ \t-]+/g, "_")), po = head.findIndex((c) => PO_NAMES.includes(c)), lim = head.findIndex((c) => LIMIT_NAMES.includes(c));
  if (po < 0) return {};
  const out = {};
  for (const r of rows.slice(1)) {
    const ref = r.map(refOf).find(Boolean), number = String(r[po] || "").trim();
    if (!ref || !number) continue;
    let limit = null;
    try { limit = lim >= 0 ? cents(r[lim]) : null; } catch { limit = null; }
    out[ref] = { number, limit };
  }
  return out;
}

/** A receipt's five parts, in order: [{ key, said, facts: [[name, value]] }]; null when one of the five is missing. */
export function partsOf(doc) {
  const given = doc && typeof doc === "object" ? doc.parts || doc : null;
  if (!given || typeof given !== "object") return null;
  const find = (key) => (Array.isArray(given) ? given.find((p) => p && String(p.id || p.name || p.part || p.key || "").toLowerCase() === key) : given[key] ?? given[key[0].toUpperCase() + key.slice(1)]);
  const out = PARTS.map((key) => {
    const p = find(key);
    if (p === undefined || p === null) return null;
    if (typeof p !== "object") return { key, said: String(p), facts: [] };
    const k = ["said", "line", "summary", "text"].find((n) => typeof p[n] === "string");
    // `knos receipt explain --json` (kind knos-receipt-parts): the facts are one object under `facts`, beside the question and the title
    const own = p.facts && typeof p.facts === "object" && !Array.isArray(p.facts) ? Object.entries(p.facts).filter(([, v]) => v !== null && v !== "") : null;
    return { key, said: k ? p[k] : "", facts: (own || Object.entries(p).filter(([n]) => n !== k && !["name", "part", "key", "id", "title", "asks", "more"].includes(n)))
      .map(([n, v]) => [n.replace(/_/g, " "), v !== null && typeof v === "object" ? JSON.stringify(v) : String(v)]) };
  });
  return out.every(Boolean) ? out : null;
}
/** Is this what `knos recall exception --json` (one row) or `knos recall queue --json` (a list of them) prints? Schema knos.recall/1. */
export const isRecall = (d) => { const row = (r) => Boolean(r) && typeof r === "object" && /^knos[.-]recall/.test(String(r.kind || ""));
  return Array.isArray(d) ? d.length > 0 && d.every(row) : Boolean(d) && typeof d === "object" && (row(d) || Array.isArray(d.recall)); };
/** Every receipt a file holds that has its five parts, with what names its line. */
export function readReceipts(doc) {
  const list = Array.isArray(doc) ? doc : doc && Array.isArray(doc.receipts) ? doc.receipts : [doc];
  // the list shape names its line inside the parts: the consequence's facts carry the invoice line and the deliverable
  const fact = (d, name) => { const hit = Array.isArray(d.parts) ? d.parts.map((p) => (p && p.facts && typeof p.facts === "object" ? p.facts[name] : null)).find((v) => v !== null && v !== undefined && v !== "") : null; return hit === undefined || hit === null ? "" : hit; };
  return list.filter((d) => d && typeof d === "object").map((d) => ({ invoice_line: String(d.invoice_line || fact(d, "invoice_line")), deliverable: String(d.deliverable || fact(d, "deliverable")),
    reference: refOf(d.reference || d.pull_request), parts: partsOf(d) })).filter((r) => r.parts);
}

function rowsFrom(lines, scale, orders, receipts, limit = null) {
  const cap_ = limit === null || limit === undefined || limit === "" ? null : units(String(limit), scale);
  const up = 10n ** BigInt(Math.max(0, scale - 2)), used = {};
  return lines.map((ln) => {
    const ref = String(ln.reference || "").toLowerCase(), listed = orders[ref], amount = units(ln.amount, scale);
    const po = listed ? { number: listed.number, limit: listed.limit === null ? null : listed.limit * up, source: "the invoice file", used: 0n }
      : ln.po_reference ? { number: ln.po_reference, limit: null, source: "a goods-received note", used: 0n } : null;
    let kind = ln.state === "agreed" ? null : ln.state === "duplicate" && /^statement /.test(ln.duplicate_of || "") ? "replayed" : ln.state;
    let reason = ln.why ? `${ln.why[0].toUpperCase()}${ln.why.slice(1)}.` : "";
    const next = po ? (used[po.number] || 0n) + amount : 0n;
    if (!kind && po && po.limit !== null && next > po.limit) { kind = "over_po"; reason = `Purchase order ${po.number} allows ${group(amountOf(po.limit, scale))}; agreed lines reach ${group(amountOf(next, scale))}.`; }
    if (!kind && cap_ !== null && amount > cap_) { kind = "over_limit"; reason = `Your approval limit is ${group(amountOf(cap_, scale))}; this line is ${group(amountOf(amount, scale))}.`; }
    if (!kind && po) used[po.number] = next;
    if (po) po.used = used[po.number] || 0n;
    const receipt = receipts.find((r) => (r.invoice_line && r.invoice_line === ln.invoice_line) || (!r.invoice_line && r.deliverable && r.deliverable === ln.deliverable && ln.state !== "duplicate")
      || (!r.invoice_line && !r.deliverable && r.reference && r.reference === ref && ln.state !== "duplicate"));
    return { line: ln.line, id: ln.invoice_line, supplier: ln.supplier || "", reference: ln.reference || "", po, amount: ln.amount || "", authorised: kind ? amountOf(0n, scale) : ln.amount || "",
      kind, reason, approved: ln.approved_by || "", payment: kind === "over_po" || kind === "over_limit" ? "held here" : `${ln.approved_by ? "approved, " : ""}${PAY_WORDS[ln.payment] || ln.payment}`,
      parts: receipt ? receipt.parts : null, ln };
  });
}
// SINGLE SIGN-ON (docs/SELFHOST.md, section 4). Served by the self-host bundle with [sso], each approval and each export
// is written to the audit log: POST /sso/act, with the form token GET /sso/me gives. Sign-in sets the cookie
// knos_signed_in (it holds no secret); without it (the public site, a page opened from disk, a bundle without [sso])
// nothing is sent and nothing changes. `signedIn()` reads that cookie when it is asked.
export function ssoOf(fetchFn, signedIn) {
  let me;                               // the person /sso/me gave, with the form token, until an old token is refused
  async function who() {
    if (typeof fetchFn !== "function" || !signedIn()) return null;
    if (me) return me;
    const r = await fetchFn("/sso/me", { credentials: "same-origin", headers: { Accept: "application/json" } });
    if (r.status === 401) return { out: true };
    const j = r.ok ? await r.json().catch(() => null) : null;
    if (!j || !j.signed_in || typeof j.form !== "string") throw new Error(`sign-in did not answer (${r.status})`);
    me = j;
    return me;
  }
  return {
    /** Writes one audit line; null when sign-in is off here. Throws, in plain words, when the line was not written. */
    async act(action, subject, sha256 = "") {
      const m = await who();
      if (!m) return null;
      if (m.out) throw new Error("sign in again: this was not written to the audit log");
      const r = await fetchFn("/sso/act", { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json", "X-Knos-Form": m.form },
        body: JSON.stringify({ action, subject: String(subject).replace(/[^\x20-\x7e]/g, " ").slice(0, 200), sha256: /^[0-9a-f]{64}$/.test(sha256 || "") ? sha256 : "" }) });
      const j = await r.json().catch(() => ({}));
      if (r.status === 403 && /form token/.test(j.error || "")) me = undefined;     // an old form token: read it again next time
      if (!r.ok) throw new Error(j.error || `the audit log answered ${r.status}`);
      return j.written || true;
    },
  };
}

/** The invoice lines the accounting file bills: approved, and held by no exception here (over the purchase order or
 *  over the approver's limit). A line a status file approved is still held when the purchase order no longer covers it. */
export const billable = (rows) => rows.filter((r) => r.approved && !r.kind).map((r) => r.id);
/** The rows of a statement as they stand with its status file: each line's purchase order, what is authorised, its
 *  exception (one of EXCEPTIONS, or null) and the reason in one sentence. */
export const rowsOf = (st, status = null, orders = {}, receipts = [], limit = null, today = "") => rowsFrom(statementLines(st, status, today), st.scale, orders, receipts, limit);
/** Is this what `knos recall decisions --json` prints: what was accepted, refused or authorised before for each line's
 *  supplier under the same terms (schema knos.recall.decision/1)? A list of rows, each naming its invoice line. */
export const isDecisions = (d) => Array.isArray(d) && d.length > 0 && d.every((r) => r && typeof r === "object" && r.kind === "knos.recall.decision/1" && typeof r.invoice_line === "string");
const APPEAL = "https://github.com/drexthealpha/Knos/blob/main/docs/DISPUTES.md#the-path";
/** The rows of an invoice with no statement: nothing was checked, so nothing is agreed and every line is an exception. */
export const uncheckedRows = (invoice, orders = {}) => rowsFrom(invoice.lines.map((ln) => ({ line: ln.line, reference: ln.pr, supplier: ln.supplier, amount: ln.amount === null ? "" : money(ln.amount),
  state: "insufficient_evidence", why: "no statement covers this line", payment: "held", evaluations: [], evidence: "", evidence_sha256: "", duplicate_of: "", invoice_line: "", deliverable: "",
  assurance: "not evaluated", po_reference: "", approved_by: "" })), 2, orders, []);

/** The message to the supplier about one exception: what is held, why, and what settles it. */
export function messageOf(row, st) {
  const unit = st && st.currency ? ` ${st.currency}` : "", invoice = st ? st.invoice : "", name = row.supplier || (st && st.supplier) || "supplier";
  return { subject: `Invoice ${invoice}, line ${row.line}: ${WORDS[row.kind]}`,
    body: [`To ${name},`, "", `Line ${row.line} of invoice ${invoice}${row.reference ? ` (${row.reference})` : ""}${row.amount ? `, ${group(row.amount)}${unit},` : ""} is not approved.`,
      `It is held as: ${WORDS[row.kind]}.`, `Reason: ${row.reason}`, `What settles it: ${REMEDY[row.kind]}`, "",
      "The agreed lines of this invoice are approved separately; this line does not hold them back.",
      ...(st && st.sha256 ? [`Statement sha256: ${st.sha256}`] : []), ...(row.id ? [`Invoice line: ${row.id}`] : [])].join("\n") };
}

// ---- the approval record ---------------------------------------------------------------------------------------------------
// What an approver can defend later: the policy (its version and the limit), who, when, why, and a snapshot of every line
// approved (its amount, state, evaluations, evidence, purchase order and receipt) with the sha256 of that snapshot. The
// record's own sha256 covers all of it. Dropped back on the page with its statement (and the same invoice file and
// receipts), each line is worked out again and compared: the page says whether the approval still matches its evidence.
const sha = (text) => sha256Hex(text);
async function snapshot(row, scale) {
  const ln = row.ln;
  return { line: row.line, invoice_line: row.id, deliverable: ln.deliverable || "", reference: row.reference, amount: row.amount, state: ln.state || "",
    evaluations: [...(ln.evaluations || [])], evidence_sha256: ln.evidence_sha256 || "", po: row.po ? row.po.number : "",
    po_limit: row.po && row.po.limit !== null ? amountOf(row.po.limit, scale) : "", receipt_sha256: row.parts ? await sha(canonicalText(row.parts)) : "" };
}
export const policyOf = (limit = null) => ({ ...POLICY, limit: limit === null || limit === undefined || limit === "" ? null : String(limit) });
const recordDigest = (rec) => sha(canonicalText({ ...rec, sha256: "" }));
/** The approval record of `rows` (the lines just approved) of statement `st`. who: { by, role, why, on, at, limit }. */
export async function recordOf(st, rows, who) {
  const lines = await Promise.all(rows.map((r) => snapshot(r, st.scale))), policy = policyOf(who.limit);
  const rec = { kind: RECORD_KIND, version: 1, sha256: "", statement: st.sha256, invoice: st.invoice, supplier: st.supplier || "", buyer: st.buyer || "", currency: st.currency || "",
    policy, policy_sha256: await sha(canonicalText(policy)), by: String(who.by).trim(), role: String(who.role).trim(), why: String(who.why || "").trim(), on: who.on, at: who.at,
    amount: amountOf(rows.reduce((a, r) => a + units(r.amount, st.scale), 0n), st.scale), lines, evidence_sha256: await sha(canonicalText(lines)) };
  rec.sha256 = await recordDigest(rec);
  return rec;
}
const FIELD_WORDS = { amount: "amount", state: "state", evaluations: "evaluations", evidence_sha256: "evidence", po: "purchase order", po_limit: "purchase order",
  receipt_sha256: "receipt", deliverable: "deliverable", reference: "deliverable" };
/** Does an approval record still match its evidence? { ok, said, changed: [{ line, what }] }. `st`, `rows`: what the page
 *  holds now (rowsOf with the same invoice file and receipts); without its statement only the record itself is checked. */
export async function checkRecord(rec, st = null, rows = []) {
  if (!rec || rec.kind !== RECORD_KIND) return { ok: false, said: "That is not an approval record.", changed: [] };
  if ((await recordDigest(rec)) !== rec.sha256 || (await sha(canonicalText(rec.policy))) !== rec.policy_sha256 || (await sha(canonicalText(rec.lines))) !== rec.evidence_sha256)
    return { ok: false, said: "This approval record was changed after it was made.", changed: [] };
  if (!st) return { ok: true, partial: true, said: "Record intact. Add its statement to check the evidence.", changed: [] };
  if (st.sha256 !== rec.statement) return { ok: false, said: "This record is for another statement.", changed: [] };
  const changed = [];
  for (const was of rec.lines) {
    const row = rows.find((r) => r.id === was.invoice_line);
    if (!row) { changed.push({ line: was.line, what: ["line"] }); continue; }
    const now = await snapshot(row, st.scale);
    const what = [...new Set(Object.keys(was).filter((k) => canonicalText(was[k]) !== canonicalText(now[k])).map((k) => FIELD_WORDS[k] || k))];
    if (what.length) changed.push({ line: was.line, what });
  }
  return changed.length ? { ok: false, changed, said: `${changed.length === 1 ? "Line" : "Lines"} ${changed.map((c) => c.line).join(", ")} changed since approval: ${[...new Set(changed.flatMap((c) => c.what))].join(", ")}.` }
    : { ok: true, changed, said: `This approval still matches its evidence: ${rec.lines.length} ${rec.lines.length === 1 ? "line" : "lines"}, approved ${rec.on}.` };
}

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const link = (href, text) => (/^https:\/\/github\.com\/[\w.\-/#?=&%]+$/.test(href || "") ? `<a href="${esc(href)}" target="_blank" rel="noopener">${esc(text)}</a>` : esc(text));
const cap = (s) => (s ? s[0].toUpperCase() + s.slice(1) : s);
const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;
const STYLE = `.approver{min-width:0}.approver [hidden]{display:none}.approver .ap-drop{display:block;position:relative;border:1.5px dashed var(--line);border-radius:var(--radius,12px);padding:20px 16px;background:var(--paper-2);cursor:pointer;font-weight:600;transition:border-color var(--dur-1) var(--ease)}
.approver .ap-drop[data-over],.approver .ap-drop:hover{border-color:var(--accent)}.approver .ap-drop:focus-within{outline:2px solid var(--accent);outline-offset:2px}
.approver .ap-drop input{position:absolute;inset:0;width:100%;height:100%;opacity:0;cursor:pointer}
.approver .ap-system{display:inline-flex;gap:6px;align-items:center;font-size:13px;color:var(--ink-2)}.approver textarea{width:100%;min-height:56px;margin:12px 0 0;resize:vertical;box-sizing:border-box}.approver .actions{align-items:center;margin:12px 0}
.ap-sum{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin:16px 0}.ap-sum>div{border:1px solid var(--line);border-radius:var(--radius,12px);padding:12px 14px;background:var(--paper-2);min-width:0;overflow-wrap:anywhere}
.ap-sum .k-kicker{margin:0}.ap-sum .k-num{display:block;font-size:clamp(22px,5vw,34px);font-weight:700;line-height:1.15}
.ap-table table{width:100%;border-collapse:collapse;table-layout:fixed}.ap-table th{text-align:left;font-size:12px;font-weight:600;color:var(--ink-2);padding:6px 9px;vertical-align:bottom}
.ap-table td{padding:2px;border-top:1px solid var(--line);vertical-align:top}.ap-table tr.ap-row>td:first-child{border-left:3px solid var(--ok)}.ap-table tr.ap-row[data-kind]>td:first-child{border-left-color:var(--bad)}
.approver button.ap-cell{display:block;width:100%;min-height:44px;box-sizing:border-box;padding:8px;border:1px solid transparent;border-radius:8px;background:none;color:var(--ink);font:inherit;font-weight:400;text-align:left;box-shadow:none;filter:none;overflow-wrap:anywhere;cursor:pointer;transition:background var(--dur-1) var(--ease),border-color var(--dur-1) var(--ease)}
.approver button.ap-cell:hover{background:var(--paper-2)}.approver button.ap-cell[aria-expanded=true]{border-color:var(--accent);background:var(--paper-2)}.approver button.ap-cell:focus-visible{outline:2px solid var(--accent);outline-offset:1px}
.ap-cell small{display:block;color:var(--ink-2)}.ap-row[data-kind] [data-col=exception] b{color:var(--bad)}.ap-row[data-approved] [data-col=payment] b{color:var(--ok)}
.ap-ev>td{padding:0;border-top:0}.ap-ev>td>div{margin:4px 2px 12px;padding:12px 14px;border:1px solid var(--line);border-radius:var(--radius,12px);background:var(--paper-2);box-shadow:var(--depth-1);animation:ap-in var(--dur-2) var(--ease)}
.ap-ev h4{margin:0 0 6px}.ap-ev dl{margin:6px 0}.ap-ev dd{overflow-wrap:anywhere}.ap-parts{list-style:none;padding:0;margin:0;display:grid;gap:8px}.ap-parts li{border-left:3px solid var(--line);padding:0 0 0 10px}.ap-parts li[data-part=assurance]{border-color:var(--accent)}
@keyframes ap-in{from{opacity:0;translate:0 -4px}}
.approver [data-ap=check]{font-weight:600}.approver [data-ok=yes]{color:var(--ok)}.approver [data-ok=no]{color:var(--bad)}.ap-decide{margin:12px 0}
.ap-queue ol{list-style:none;padding:0;margin:0}.ap-queue li{border-top:1px solid var(--line);padding:12px 0;overflow-wrap:anywhere}.ap-queue li p{margin:0 0 8px}.ap-queue li b{color:var(--bad)}
.ap-msg textarea{min-height:190px;font-size:14px}.ap-sign{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(200px,100%),1fr));gap:12px;align-items:end;margin:12px 0}.ap-sign label{display:grid;gap:4px;font-size:13px;color:var(--ink-2);min-width:0}
.ap-sign input,.ap-pay input{width:100%;box-sizing:border-box}.ap-pay{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(180px,100%),1fr));gap:12px;align-items:end;margin:12px 0}.ap-pay label{display:grid;gap:4px;font-size:13px;color:var(--ink-2);min-width:0}
@media (max-width:860px){.ap-sum{grid-template-columns:minmax(0,1fr)}.ap-table thead{position:absolute;width:1px;height:1px;overflow:hidden;clip-path:inset(50%)}.ap-table table,.ap-table tbody,.ap-table tr,.ap-table td{display:block}
.ap-table tr.ap-row{border:1px solid var(--line);border-left:3px solid var(--ok);border-radius:var(--radius,12px);margin:0 0 12px;padding:4px}.ap-table tr.ap-row[data-kind]{border-left-color:var(--bad)}.ap-table td,.ap-table tr.ap-row>td:first-child{border:0}
.approver button.ap-cell{display:grid;grid-template-columns:minmax(92px,36%) minmax(0,1fr);gap:8px}.approver button.ap-cell::before{content:attr(data-label);font-size:12px;color:var(--ink-2)}}
@media (prefers-reduced-motion:reduce){.ap-ev>td>div{animation:none}.approver .ap-drop,.approver button.ap-cell{transition:none}}`;

/** What one cell opens: [[name, value, href]] and, for the evidence of a line with a receipt, its five parts. */
function evidenceOf(row, key, st, limit = null) {
  const ln = row.ln, scale = st ? st.scale : 2, unit = st && st.currency ? ` ${st.currency}` : "", none = "none on file";
  if (key === "supplier") return { title: "Who billed this line", facts: [["supplier", row.supplier || "not named"], ["invoice", st ? st.invoice : "no statement"], ["buyer", (st && st.buyer) || "not named"], ["statement date", st ? st.date : ""]] };
  const policy = [["policy", `${POLICY.id} version ${POLICY.version}: ${POLICY.ordinary.join("; ")}`], ["approver's limit", limit ? `${group(limit)}${unit}` : "none stated"],
    ["approved by", row.approved || "nobody yet"]];
  if (key === "po") return { title: "What was authorised", facts: [...(row.po ? [["purchase order", row.po.number], ["its limit", row.po.limit === null ? "not stated" : `${group(amountOf(row.po.limit, scale))}${unit}`],
    ["agreed against it", `${group(amountOf(row.po.used, scale))}${unit}`], ["read from", row.po.source], ["who checks the limit", "this page, as advice: no program enforces a purchase order"]]
    : [["purchase order", none], ["how to name one", "add po_number and po_amount columns to the invoice file"]]), ...policy] };
  if (key === "deliverable") return { title: "What was to be delivered", facts: [["named on the invoice", row.reference || "nothing", ln.evidence && /\/pull\/\d+$/.test(ln.evidence) ? ln.evidence : ""], ["deliverable id", ln.deliverable || none],
    ["invoice line id", ln.invoice_line || none], ["billed before", ln.duplicate_of || "no"]] };
  if (key === "evidence") return { title: "Why this line is, or is not, accepted", parts: row.parts,
    facts: [["evaluations", ln.evaluations.length ? ln.evaluations.join(" ") : "none"], ["assurance", ln.assurance || "not evaluated"], ["evidence", ln.evidence || "none", ln.evidence], ["evidence sha256", ln.evidence_sha256 || "none"],
      ...(st ? [["made from", st.source === "shadow" ? "the invoice against GitHub's record, which GitHub does not sign" : st.source === "month" ? "a closed month of the meter" : st.source]] : []),
      ...(row.parts ? [] : [["receipt", "none given for this line: drop its five parts to read them here"]])] };
  if (key === "amount") return { title: "What may be paid", facts: [["billed", row.amount ? `${group(row.amount)}${unit}` : "no amount"], ["authorised", `${group(row.authorised) || "nothing"}${row.authorised ? unit : ""}`],
    ["why", row.kind ? `held: ${WORDS[row.kind]}` : "the line is agreed"], ...(row.po && row.po.limit !== null ? [["purchase order limit", `${group(amountOf(row.po.limit, scale))}${unit}`]] : [])] };
  if (key === "exception") return { title: row.kind ? `Exception: ${WORDS[row.kind]}` : "No exception", facts: row.kind ? [["reason", row.reason], ["what settles it", REMEDY[row.kind]],
    ["decided by", row.kind === "over_po" ? "this page, from the limit the invoice file states" : row.kind === "over_limit" ? "this page, from the limit you typed" : st ? "the statement" : "nothing yet: no statement was given"]] : [["state", "agreed"]] };
  return { title: "What happened to the money", facts: [["payment", row.payment], ["approved by", row.approved || "nobody yet"], ["settlement", ln.settlement || "none recorded"],
    ["how it is paid", "outside this page: a bank file, or the escrow on devnet (test USDC)"]] };
}

/** Draw the approver's screen in `el`. */
export function renderApprover(el, ctx = {}) {
  const doc = el.ownerDocument, win = doc.defaultView;
  if (!doc.getElementById("ap-style")) { const s = doc.createElement("style"); s.id = "ap-style"; s.textContent = STYLE; doc.head.appendChild(s); }
  stepStyle(doc);
  el.classList.add("approver");
  el.innerHTML = `<h2>Approve one invoice</h2>
    <p>Drop the invoice and its statement.</p>
    <form data-ap="in" novalidate>
      <label class="ap-drop" data-ap="drop">Drop files here, or choose them<input type="file" id="ap-file" multiple accept=".csv,.json,.txt,text/csv,application/json,text/plain"></label>
      <textarea id="ap-paste" rows="2" spellcheck="false" autocomplete="off" aria-label="Paste an invoice or a statement" placeholder="Or paste an invoice or a statement"></textarea>
      <p class="actions"><button type="submit" class="k-btn" data-ap="read">Read</button> <button type="button" class="k-btn quiet" data-ap="sample">Try the sample</button>
        <button type="button" class="k-btn quiet" data-ap="last" hidden>Open the last check</button> <button type="button" class="k-btn quiet" data-ap="clear" hidden>Start over</button></p>
    </form>
    <p data-ap="said" role="status" aria-live="polite"></p>
    <p data-ap="check" role="status" aria-live="polite" hidden></p>
    <div data-ap="out" hidden>
      <p data-ap="mark" class="fine" hidden>Sample: a made-up invoice from a made-up supplier.</p>
      <p class="actions" data-ap="go" hidden><button type="button" class="k-btn quiet" data-ap="skip">Go to approval</button></p>
      <div class="ap-sum" data-ap="sum"></div>
      <div class="k-table ap-table" data-ap="table"></div>
      <section class="ap-decide" data-ap="decide" aria-label="Approve">
        <form class="ap-sign" data-ap="sign" novalidate><label>Your name<input type="text" id="ap-by" autocomplete="name" maxlength="120"></label><label>Your role<input type="text" id="ap-role" autocomplete="organization-title" maxlength="120"></label>
          <label>Your limit, if any<input type="text" id="ap-limit" inputmode="decimal" autocomplete="off" maxlength="24" spellcheck="false" placeholder="5,000.00"></label>
          <label>Why, if not the policy<input type="text" id="ap-why" autocomplete="off" maxlength="200"></label>
          <button type="submit" class="k-btn" data-ap="approve" disabled>Approve ordinary lines</button></form>
        <p data-ap="approved" role="status" aria-live="polite"></p>
      </section>
      <section data-ap="files" aria-label="Files" hidden></section>
      <section class="ap-queue" data-ap="queue" aria-label="Exceptions"></section>
      <div data-ap="recall" hidden></div>
    </div>
    <p class="fine" data-ap="account">No account system exists. This screen works signed out.</p>
    <p class="fine">Nothing leaves this browser.</p>
    <p class="fine" data-ap="time" hidden></p>
    <p class="fine"><a href="${PRIVATE_PATH}" target="_blank" rel="noopener">Private repositories: read the private path</a></p>`;
  const $ = (name) => el.querySelector(`[data-ap="${name}"]`), said = (text) => { $("said").textContent = text; };
  const state = { system: "quickbooks", st: null, status: null, invoice: null, orders: {}, receipts: [], sample: false, whole: true, rows: [], open: null, rails: undefined, recall: null, limit: null, record: null, checks: [], decisions: [] };
  let motion = null;
  import("./motion.js").then((m) => { motion = m; }).catch(() => { /* the page is whole without it */ });
  const toast = (text, kind) => { if (motion && motion.toast) motion.toast(text, kind); };
  const today = () => (ctx.now || new Date()).toISOString().slice(0, 10);
  const keep = (text, name, type = "text/csv;charset=utf-8") => {
    const url = URL.createObjectURL(new Blob([text], { type })), a = doc.createElement("a");
    a.href = url; a.download = name; doc.body.append(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(url), 2000);
    toast(`Downloaded ${name}`);
  };
  const fileName = () => `statement-${String(state.st.invoice).replace(/[^\w.-]+/g, "-")}`;
  const sso = ssoOf(ctx.fetch || (typeof fetch === "function" ? fetch.bind(globalThis) : null),
    () => /(?:^|;\s*)knos_signed_in=1(?:;|$)/.test(ctx.cookie !== undefined ? ctx.cookie : doc.cookie || ""));
  const audit = (action, subject, where) => sso.act(action, subject, state.st ? state.st.sha256 : "")
    .catch((e) => { if (where) where.textContent = `${where.textContent} Not in the audit log: ${e.message}.`.trim(); toast("Not in the audit log", "bad"); });

  // ---- drawing ---------------------------------------------------------------------------------------------------------
  // under the payment status: the line's four steps; a line owed to the supplier says so with the appeal; and what memory
  // says was decided before for the same supplier and terms (`knos recall decisions --json`, dropped on the page)
  const afterHtml = (row) => {
    if (!row.ln.steps) return "";
    const before = state.decisions.find((d) => d.invoice_line === row.id);
    return `${stepRowHtml(row.ln.steps)}${row.ln.owed ? `<p class="fine" data-ap="owed"><b>Owed to the supplier.</b> <a href="${APPEAL}" target="_blank" rel="noopener">Supplier: appeal</a></p>` : ""}`
      + (before ? `<p class="fine" data-ap="before">${esc(before.words)}</p>` : "");
  };
  const cellHtml = (row, key) => {
    const text = { supplier: esc(row.supplier || "not named"), po: esc(row.po ? row.po.number : "none on file"), deliverable: esc(row.reference || "none named"),
      evidence: esc(row.parts ? "receipt, five parts" : row.ln.evaluations.length ? `${plural(row.ln.evaluations.length, "evaluation")}, ${row.ln.assurance}` : "none"),
      amount: `<span class="k-num">${esc(group(row.authorised) || "none")}</span>${row.kind && row.amount ? `<small>of <span class="k-num">${esc(group(row.amount))}</span> billed</small>` : ""}`,
      exception: row.kind ? `<b>${esc(WORDS[row.kind])}</b>` : "none", payment: `<b>${esc(row.payment)}</b>` }[key];
    if (key === "po") return `${text}<small>policy ${POLICY.version}${row.po && row.po.limit !== null ? ` · up to <span class="k-num">${esc(group(amountOf(row.po.limit, state.st ? state.st.scale : 2)))}</span>` : ""}${row.approved ? ` · ${esc(row.approved)}` : ""}</small>`;
    return text;
  };
  const panelHtml = (row, key) => {
    const ev = evidenceOf(row, key, state.st, state.limit);
    return `<div data-ev="${key}"><h4>Line ${row.line}: ${esc(ev.title)}</h4>
      ${ev.parts ? `<ol class="ap-parts" data-ap="parts">${ev.parts.map((p) => `<li data-part="${p.key}"><strong>${esc(cap(p.key))}</strong> <span data-not-prose>${esc(p.said)}</span>
        ${p.facts.length ? `<dl class="facts">${p.facts.map(([n, v]) => `<dt>${esc(n)}</dt><dd>${esc(v)}</dd>`).join("")}</dl>` : ""}</li>`).join("")}</ol>` : ""}
      <dl class="facts">${ev.facts.map(([n, v, href]) => `<dt>${esc(n)}</dt><dd>${/^[0-9a-f]{64}$|^(dlv|inv|evl|stl)_/.test(v) ? `<span class="mono">${esc(v)}</span>` : link(href, v)}</dd>`).join("")}</dl>
      <p class="actions"><button type="button" class="k-btn quiet" data-ap="shut">Close</button></p></div>`;
  };
  function shut(focus = false) {
    if (!state.open) return;
    const tr = $("table").querySelector("tr.ap-ev"), b = $("table").querySelector('.ap-cell[aria-expanded="true"]');
    if (tr) tr.remove();
    if (b) { b.setAttribute("aria-expanded", "false"); b.removeAttribute("aria-controls"); if (focus) b.focus(); }
    state.open = null;
  }
  function openCell(line, key, focus = false) {
    const same = state.open && state.open.line === line && state.open.key === key;
    shut();
    if (same) return;
    const row = state.rows.find((r) => r.line === line), tr = $("table").querySelector(`tr.ap-row[data-line="${line}"]`), b = tr && tr.querySelector(`[data-col="${key}"]`);
    if (!row || !b) return;
    const ev = doc.createElement("tr");
    ev.className = "ap-ev"; ev.id = `ap-ev-${line}`;
    ev.innerHTML = `<td colspan="${COLUMNS.length}">${panelHtml(row, key)}</td>`;
    tr.after(ev);
    b.setAttribute("aria-expanded", "true"); b.setAttribute("aria-controls", ev.id);
    state.open = { line, key };
    if (focus) { b.focus(); b.scrollIntoView?.({ block: "center", behavior: motion && !motion.prefersReduced() ? "smooth" : "auto" }); }
  }
  function draw() {
    const { st, rows } = state, scale = st ? st.scale : 2, unit = st && st.currency ? ` ${st.currency}` : "";
    const sum = (list, field) => amountOf(list.reduce((a, r) => a + units(r[field], scale), 0n), scale);
    const agreed = rows.filter((r) => !r.kind), held = rows.filter((r) => r.kind), waiting = agreed.filter((r) => !r.approved), kept = state.open;
    state.open = null;
    $("out").hidden = false; $("mark").hidden = !state.sample; $("clear").hidden = false;
    $("sum").innerHTML = [["Billed", rows, "amount"], ["Policy met", agreed, "amount"], ["Exceptions", held, "amount"]].map(([name, list, field]) => `<div data-sum="${name.toLowerCase().replace(" ", "-")}"><p class="k-kicker">${name}</p>
      <span class="k-num">${esc(group(sum(list, field)))}${esc(unit)}</span><span>${plural(list.length, "line")}</span></div>`).join("");
    $("table").innerHTML = `<table><thead><tr>${COLUMNS.map(([, name]) => `<th scope="col">${name}</th>`).join("")}</tr></thead><tbody>${rows.map((row) => `<tr class="ap-row" data-line="${row.line}"${row.kind ? ` data-kind="${row.kind}"` : ""}${row.approved ? " data-approved" : ""}>
      ${COLUMNS.map(([key, name]) => `<td><button type="button" class="ap-cell" data-col="${key}" data-label="${name}" aria-expanded="false" aria-label="Line ${row.line}, ${name.toLowerCase()}: ${esc(key === "amount" ? group(row.authorised) || "none" : cellHtml(row, key).replace(/<small>.*$/, "").replace(/<[^>]+>/g, ""))}"><span>${cellHtml(row, key)}</span></button>${key === "payment" ? afterHtml(row) : ""}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
    const can = Boolean(st) && state.whole && waiting.length > 0;
    $("sign").hidden = !st; $("go").hidden = !can;
    const go = $("approve");
    go.disabled = !can; go.textContent = waiting.length ? `Approve ${plural(waiting.length, "ordinary line")}` : "No ordinary line waiting";
    $("approved").textContent = !st ? "Add the statement file to approve." : !state.whole ? "Changed after it was made. Do not approve it." : !agreed.length ? "No line is ordinary."
      : !waiting.length ? `Approved ${plural(agreed.length, "line")}. ${plural(held.length, "exception")} stay open.` : "";
    $("queue").innerHTML = `<h3>Exceptions <span class="k-num" data-ap="count">${held.length}</span></h3>
      ${held.length ? `<ol>${held.map((row) => `<li data-line="${row.line}" data-kind="${row.kind}"><p><span class="k-num">Line ${row.line}</span> · <b>${esc(cap(WORDS[row.kind]))}.</b> <span data-ap="reason" data-not-prose>${esc(row.reason)}</span>${row.amount ? ` <span class="k-num">${esc(group(row.amount))}</span>` : ""}</p>
        <p class="actions"><button type="button" class="k-btn quiet" data-ap="open">Open line ${row.line}</button> <button type="button" class="k-btn quiet" data-ap="message" aria-expanded="false">Message the supplier</button></p>
        <div class="ap-msg" data-ap="msg" hidden></div></li>`).join("")}</ol>` : `<p>No exception on this invoice.</p>`}`;
    if (state.recall) drawRecall();            // a redrawn queue keeps what memory says of it
    const files = $("files"); files.hidden = !st;
    if (st) {
      const approvedNow = agreed.some((r) => r.approved);
      // the close: once lines are approved, one press saves the file the accounting system imports (its bills: the approved lines)
      files.innerHTML = `<h3>Files</h3>
        <p class="actions"><button type="button" class="k-btn" data-file="record"${state.record ? "" : " hidden"}>Download approval record</button> <button type="button" class="k-btn" data-file="accounting"${approvedNow ? "" : " disabled"}>Download accounting file</button>
          <label class="ap-system">For <select id="ap-system">${Object.entries(SYSTEMS).map(([k, name]) => `<option value="${k}"${k === state.system ? " selected" : ""}>${name}</option>`).join("")}</select></label></p>
        <p class="actions"><button type="button" class="k-btn quiet" data-file="csv">Download statement</button> <button type="button" class="k-btn quiet" data-file="generic">Download audit file</button></p>
        <div data-ap="pay" hidden><div class="ap-pay"><label>Paying account name<input type="text" id="ap-payer" autocomplete="organization" maxlength="70"></label><label>IBAN<input type="text" id="ap-iban" autocomplete="off" maxlength="34" spellcheck="false"></label>
          <label>BIC<input type="text" id="ap-bic" autocomplete="off" maxlength="11" spellcheck="false"></label><button type="button" class="k-btn" data-file="pain">Download payment file</button></div>
          <p class="fine">No bank has taken this file.</p></div>
        <p data-ap="filed" role="status" aria-live="polite"></p>
        <details class="k-more"><summary>More files</summary><p class="actions"><button type="button" class="k-btn quiet" data-file="status"${approvedNow || state.status ? "" : " disabled"}>Status file</button>
          <button type="button" class="k-btn quiet" data-file="json">Statement file</button></p><p class="fine">File exports, not integrations.</p></details>`;
      if (approvedNow) offerPayment();
    }
    if (kept && rows.some((r) => r.line === kept.line)) openCell(kept.line, kept.key);
  }
  // The payment instruction file is web/rails.js's: pain001(statement, payer, status). Without that module there is no button.
  async function offerPayment() {
    if (state.rails === undefined) state.rails = ctx.rails !== undefined ? ctx.rails : await import("./rails.js").catch(() => null);
    const pay = $("pay");
    if (!pay || !state.rails || typeof state.rails.pain001 !== "function") return;
    // web/rails.js draws its own form (the payer's account and one account a supplier, which a payment file needs) from
    // the statement and the approval this page holds; a module with pain001 alone gets this page's three fields.
    if (typeof state.rails.renderRails === "function") { pay.innerHTML = ""; state.rails.renderRails(pay, { statement: state.st, status: state.status, today: today(), files: false }); }
    pay.hidden = false;
  }
  function refresh() {
    state.rows = state.st ? rowsOf(state.st, state.status, state.orders, state.receipts, state.limit, today()) : state.invoice ? uncheckedRows(state.invoice, state.orders) : [];
    if (!state.rows.length) { $("out").hidden = true; return; }
    draw();
    const held = state.rows.filter((r) => r.kind).length;
    said(!state.st ? `Read ${plural(state.rows.length, "line")}. No statement yet: nothing is checked.` : !state.whole ? "That statement was changed after it was made."
      : `Read ${plural(state.rows.length, "line")}. ${plural(held, "exception")}.`);
  }

  // ---- reading -----------------------------------------------------------------------------------------------------------
  /** Take what was dropped, chosen or pasted: [{ name, text }]. What each is, is read from the file itself. */
  async function take(files) {
    said("Reading."); $("out").setAttribute("aria-busy", "true");
    const unread = [];
    for (const f of files) {
      const text = String(f.text || ""), start = text.replace(/^﻿+/, "").trim().slice(0, 1);
      let doc_ = null;
      if (start === "{" || start === "[") { try { doc_ = JSON.parse(text.replace(/^﻿+/, "")); } catch { unread.push(f.name); continue; } }
      if (doc_ && doc_.kind === STATEMENT_KIND && Array.isArray(doc_.lines)) {
        state.st = doc_; state.sample = false; state.whole = (await statementDigest(doc_)) === doc_.sha256;
        if (state.status && state.status.statement !== doc_.sha256) state.status = null;
        const kept = doc_.evidence && doc_.evidence.embedded && doc_.evidence.embedded.invoice;
        if (typeof kept === "string") state.orders = { ...readOrders(kept), ...state.orders };
      } else if (doc_ && doc_.kind === RECORD_KIND) state.checks.push(doc_);
      else if (doc_ && doc_.kind === STATUS_KIND && Array.isArray(doc_.events)) state.pending = doc_;
      else if (isDecisions(doc_)) state.decisions = doc_;
      else if (isRecall(doc_)) state.recall = Array.isArray(doc_) ? doc_ : Array.isArray(doc_.recall) ? doc_.recall : Array.isArray(doc_.rows) ? doc_.rows : [doc_];
      else if (doc_ && readReceipts(doc_).length) state.receipts = [...readReceipts(doc_), ...state.receipts];
      else {
        try { state.invoice = parse(text); state.orders = { ...state.orders, ...readOrders(text) }; } catch (e) {
          const orders = readOrders(text);
          if (Object.keys(orders).length) state.orders = { ...state.orders, ...orders }; else unread.push(/^line \d+/.test(e.message) ? `${f.name} (${e.message})` : f.name);
        }
      }
    }
    if (state.pending) {            // a status file is its statement's, whichever was read first
      if (state.st && state.pending.statement === state.st.sha256) state.status = state.pending; else if (state.st) unread.push("the status file (another statement's)");
      if (state.st) state.pending = null;
    }
    $("out").removeAttribute("aria-busy");
    refresh();
    if (unread.length) said(`Not read: ${unread.join(", ")}.`);
    else if (!state.rows.length) said(state.checks.length ? `Read ${plural(state.checks.length, "approval record")}.` : "Nothing to show yet. Add an invoice or a statement.");
    await checkRecords();
    drawRecall();
    return state;
  }
  // An approval record dropped back: does it still match its evidence, as the page reads it now?
  async function checkRecords() {
    const box = $("check");
    if (!state.checks.length) { box.hidden = true; return; }
    const got = await Promise.all(state.checks.map((r) => checkRecord(r, state.st, state.rows)));
    box.innerHTML = got.map((g) => `<span data-ok="${g.ok && !g.partial ? "yes" : g.ok ? "partly" : "no"}">${esc(g.said)}</span>`).join("<br>");
    box.hidden = false;
  }
  async function drawRecall() {
    const box = $("recall");
    if (!state.recall || !box) return;
    const mod = ctx.recall !== undefined ? ctx.recall : await import("./recall.js").catch(() => null);
    if (mod && typeof mod.renderRecall === "function") { box.hidden = false; mod.renderRecall(box, state.recall); }
    // what memory says of each exception in the queue: one that ended the same way most times before is labelled and
    // moved up; with no memory nothing is labelled and nothing moves (web/recall.js labelFor)
    const list = $("queue").querySelector("ol");
    if (!mod || typeof mod.labelFor !== "function" || !list) return;
    const items = [...list.children], byLine = new Map(state.rows.map((r) => [String(r.line), r]));
    for (const li of items) {
      li.querySelector("[data-ap=pattern]")?.remove();
      const row = byLine.get(li.dataset.line), label = mod.labelFor(state.recall, li.dataset.kind, row && row.supplier);
      if (!label) continue;
      li.dataset.pattern = "yes";
      li.querySelector("p").insertAdjacentHTML("afterend", `<p data-ap="pattern">${esc(label[0].toUpperCase() + label.slice(1))}.</p>`);
    }
    list.append(...items.filter((li) => li.dataset.pattern), ...items.filter((li) => !li.dataset.pattern));
  }
  function reset() { Object.assign(state, { st: null, status: null, pending: null, invoice: null, orders: {}, receipts: [], sample: false, whole: true, rows: [], open: null, recall: null, record: null, checks: [], decisions: [] }); $("check").hidden = true; }
  async function sample() {
    reset(); said("Reading the sample.");
    state.st = await fromShadow({ invoice: SAMPLE_INVOICE, answers: SAMPLE_BOOK }, SAMPLE_META);
    state.invoice = parse(SAMPLE_INVOICE); state.orders = readOrders(SAMPLE_ORDERS); state.sample = true;
    refresh();
    return state;
  }
  function last() {
    if (!HANDED.st) return;
    reset(); state.st = HANDED.st; state.status = HANDED.status;
    const kept = state.st.evidence && state.st.evidence.embedded && state.st.evidence.embedded.invoice;
    if (typeof kept === "string") state.orders = readOrders(kept);
    refresh();
  }

  // ---- deciding ----------------------------------------------------------------------------------------------------------
  async function approve() {
    const by = doc.getElementById("ap-by"), role = doc.getElementById("ap-role"), why = doc.getElementById("ap-why"), note = $("approved");
    const empty = [by, role].find((i) => !i.value.trim());
    if (empty) { note.textContent = "Type your name and your role."; empty.focus(); return; }
    const mine = state.rows.filter((r) => !r.kind && !r.approved);
    // the approver accepts the lines and authorises their payment: two events, as `knos statement accept` and `approve` record them
    try { state.status = approveLines(state.st, acceptLines(state.st, state.status, by.value, role.value, today(), mine.map((r) => r.id)), by.value, role.value, today(), mine.map((r) => r.id)); } catch (e) { note.textContent = e.message; return; }
    const total = state.status.events[state.status.events.length - 1].amount, now = ctx.now || new Date();
    state.record = await recordOf(state.st, mine, { by: by.value, role: role.value, why: why.value.trim() || "The lines meet the policy: agreed, within order and limit.",
      on: today(), at: now.toISOString(), limit: state.limit });
    refresh();
    const held = state.rows.filter((r) => r.kind).length;
    $("approved").textContent = `Approved ${plural(mine.length, "line")}, ${group(total)}. ${plural(held, "exception")} stay open.`;
    audit("approve", `invoice ${state.st.invoice}: ${plural(mine.length, "line")} approved by ${by.value.trim()}`, $("approved"));
    toast(`Approved ${plural(mine.length, "line")}`);
    (el.querySelector('[data-file="record"]') || $("queue")).focus?.();          // the focus is not left on a button that no longer works
    if (state.sample || state.st === HANDED.st) Object.assign(HANDED, { st: state.st, status: state.status });      // the Statement page opens the same approval
  }
  function message(li) {
    const row = state.rows.find((r) => String(r.line) === li.dataset.line), box = li.querySelector('[data-ap="msg"]'), b = li.querySelector('[data-ap="message"]');
    if (!box.hidden) { box.hidden = true; b.setAttribute("aria-expanded", "false"); return; }
    const m = messageOf(row, state.st), id = `ap-msg-${row.line}`;
    box.innerHTML = `<textarea id="${id}" rows="9" readonly aria-label="Message about line ${row.line}">${esc(`Subject: ${m.subject}\n\n${m.body}`)}</textarea>
      <p class="actions"><button type="button" class="k-btn quiet" data-ap="copy">Copy the message</button> <a class="k-btn quiet" data-ap="mail" href="mailto:?subject=${encodeURIComponent(m.subject)}&amp;body=${encodeURIComponent(m.body)}">Open in mail</a>
        <span data-ap="copied" role="status" aria-live="polite"></span></p>`;
    box.hidden = false; b.setAttribute("aria-expanded", "true"); b.setAttribute("aria-controls", id);
    box.querySelector("textarea").focus();
  }
  async function file(kind) {
    const { st, status } = state, name = fileName(), note = $("filed");
    const save = (text, saved, type) => { keep(text, saved, type); audit("export", `invoice ${st.invoice}: ${saved}`, note); };
    try {
      if (kind === "csv") save(await statementCsv(st, status), `${name}.csv`);
      else if (kind === "json") save(canonicalText(st), `${name}.json`, "application/json");
      else if (kind === "status") save(canonicalText(status), `${name}.status.json`, "application/json");
      else if (kind === "record") save(canonicalText(state.record), `${name}.approval.json`, "application/json");
      else if (kind === "accounting") {
        const fmt = doc.getElementById("ap-system").value, ok = new Set(billable(state.rows));
        if (!ok.size) throw new Error("approve the ordinary lines first");
        const file_ = `${name}-${fmt}.csv`;
        save(await statementExport(fmt, { ...st, lines: st.lines.filter((ln) => ok.has(ln.invoice_line)) }, status), file_);
        if (note) note.textContent = `Approved and exported: ${file_}.`;
        return;
      }
      else if (kind === "pain") {
        const iban = doc.getElementById("ap-iban").value.replace(/\s+/g, "").toUpperCase();
        const payer = { name: doc.getElementById("ap-payer").value.trim(), account: iban, iban, bic: doc.getElementById("ap-bic").value.trim().toUpperCase(), on: today() };
        save(await state.rails.pain001(st, payer, status), `${name}.pain.001.xml`, "application/xml");
      } else save(await statementExport(kind, st, status), `${name}-${kind}.csv`);
      if (note) note.textContent = "";
    } catch (e) { if (note) note.textContent = `Not written: ${e.message}`; toast("Not written", "bad"); }
  }

  // ---- what is pressed ---------------------------------------------------------------------------------------------------
  const texts = (list) => Promise.all([...list].map(async (f) => ({ name: f.name, text: await f.text() })));
  const form = $("in"), drop = $("drop"), box = doc.getElementById("ap-paste"), picker = doc.getElementById("ap-file");
  $("sign").addEventListener("submit", (ev) => { ev.preventDefault(); if (!$("approve").disabled) approve(); });
  form.addEventListener("submit", (ev) => { ev.preventDefault(); if (box.value.trim()) take([{ name: "what was pasted", text: box.value }]).then(() => { box.value = ""; }); else said("Nothing to read. Drop a file, or try the sample."); });
  doc.getElementById("ap-limit").addEventListener("input", (ev) => {
    const text = ev.target.value.replace(/[,\s]/g, "");
    let limit = null;
    if (text) { try { limit = money(cents(text)); } catch { $("approved").textContent = "Write the limit as an amount, like 5,000.00."; return; } }
    state.limit = limit;
    if (state.st || state.invoice) refresh();
  });
  el.addEventListener("change", (ev) => { if (ev.target.id === "ap-system") state.system = ev.target.value; });
  picker.addEventListener("change", async () => { if (picker.files.length) { await take(await texts(picker.files)); picker.value = ""; } });
  for (const name of ["dragenter", "dragover"]) el.addEventListener(name, (ev) => { ev.preventDefault(); drop.dataset.over = ""; });
  for (const name of ["dragleave", "drop"]) el.addEventListener(name, (ev) => { ev.preventDefault(); delete drop.dataset.over; });
  el.addEventListener("drop", async (ev) => { const list = ev.dataTransfer && ev.dataTransfer.files; if (list && list.length) take(await texts(list)); else { const t = ev.dataTransfer && ev.dataTransfer.getData("text"); if (t) take([{ name: "what was dropped", text: t }]); } });
  el.addEventListener("click", (ev) => {
    const cell = ev.target.closest(".ap-cell");
    if (cell) return openCell(Number(cell.closest("tr").dataset.line), cell.dataset.col);
    const kind = ev.target.closest("[data-file]")?.dataset.file;
    if (kind) return file(kind);
    const what = ev.target.closest("[data-ap]")?.dataset.ap, li = ev.target.closest(".ap-queue li");
    if (what === "sample") sample().catch((e) => said(`Not read: ${e.message}`));
    if (what === "last") last();
    if (what === "clear") { reset(); $("out").hidden = true; $("clear").hidden = true; said("Cleared."); picker.focus(); }
    if (what === "shut") shut(true);
    if (what === "skip") { const by = doc.getElementById("ap-by"); by.focus(); by.scrollIntoView?.({ block: "center" }); }
    if (what === "open" && li) openCell(Number(li.dataset.line), "exception", true);
    if (what === "message" && li) message(li);
    if (what === "copy" && li) {
      const text = li.querySelector("textarea").value, note = li.querySelector('[data-ap="copied"]');
      Promise.resolve().then(() => win.navigator.clipboard.writeText(text)).then(() => { note.textContent = "Copied."; }, () => { li.querySelector("textarea").select(); note.textContent = "Select it and copy."; });
    }
  });
  // The table by keyboard: Tab goes through every cell; the arrows move between cells; Escape shuts what is open.
  el.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape" && state.open) { ev.preventDefault(); return shut(true); }
    const cell = ev.target.closest?.(".ap-cell");
    if (!cell || !["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "Home", "End"].includes(ev.key)) return;
    const rows = [...$("table").querySelectorAll("tr.ap-row")], r = rows.indexOf(cell.closest("tr")), cells = (tr) => [...tr.querySelectorAll(".ap-cell")], c = cells(rows[r]).indexOf(cell);
    const to = ev.key === "ArrowLeft" ? [r, c - 1] : ev.key === "ArrowRight" ? [r, c + 1] : ev.key === "ArrowUp" ? [r - 1, c] : ev.key === "ArrowDown" ? [r + 1, c] : ev.key === "Home" ? [r, 0] : [r, COLUMNS.length - 1];
    const next = rows[to[0]] && cells(rows[to[0]])[to[1]];
    if (next) { ev.preventDefault(); next.focus(); }
  });
  const offerLast = () => { $("last").hidden = !HANDED.st; };
  doc.addEventListener("knos:statement", offerLast); offerLast();

  // What a script measured, and nothing else: tests/web/approver.mjs writes approver_time.json; no person was timed.
  const loaded = (ctx.time !== undefined ? Promise.resolve(ctx.time) : fetch(new URL("./approver_time.json", import.meta.url)).then((r) => (r.ok ? r.json() : null)).catch(() => null)).then((t) => {
    if (!t || t.scripted !== true || !Number.isFinite(t.total_ms)) return;
    const line = $("time");
    line.textContent = `Scripted first comparison: ${(t.total_ms / 1000).toFixed(1)} s. No person was timed.`; line.hidden = false;
  });
  return { take, sample, state: () => state, loaded };
}
