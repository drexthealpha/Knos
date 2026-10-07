// The finance view's data, as pure functions: a statement of version 2 (src/knos/audit.py), each deliverable as four
// linked objects (audit.record), and the files a finance system imports (src/knos/exports.py). Nothing here touches the
// page or the network. Every function is the Python's, line for line where it matters: tests/web/finance.mjs holds the
// bytes equal to tests/data/finance, which tests/test_exports.py holds equal to the Python.
//
//   auditExport(scope, lines, fmt)            { text, rows, head }: what `knos audit export --format csv|json` prints
//   recordsOf(rows, refs, receipts, approvals)  the four objects of every deliverable (authorisation, acceptance,
//                                             commercial, settlement); record(rows, ref, receipt, approval) is one
//   exportAs(fmt, scope, rows, head, refs, options)   netsuite | sap | coupa | quickbooks | generic, as text
//   readRefs(text)                            a buyer's refs file (order,ref,paid_outside,dispute)
//
// `lines` are the lines of audit/<owner id>.json (scripts/audit_statements.py); `rows` are lines with seq and prev.

export const TYPE = "knos.audit-export", VERSION = 3;
export const COLUMNS_V1 = ["seq", "date", "time", "kind", "order", "funded_transaction", "owner_id", "funder", "commenter_id", "authorised_by", "repository_id",
  "issue", "private", "standing", "mode", "price_units", "price", "funder_fee_units", "currency", "terms_hash", "pull_request", "artifact",
  "supplier_ids", "wallets", "judge", "evaluator", "verdict", "paid_units", "paid", "held_units", "refunded_units", "reverted_units",
  "fee_units", "fee", "transaction", "billing_key", "billed_before", "exception", "resolved_by", "prev"];
const ADDED = { kind: ["record"], funder: ["source"], terms_hash: ["terms_version"], wallets: ["paid_each"], held_units: ["held_until"] };
export const COLUMNS_V2 = COLUMNS_V1.flatMap((c) => [c, ...(ADDED[c] || [])]);
// version 3 (src/knos/audit.py): the verdict in one of the four words, and the four ids, each after the column it explains
const ADDED3 = { verdict: ["outcome"], billing_key: ["deliverable_id", "evaluation_id", "invoice_line_id", "settlement_id"] };
export const COLUMNS = COLUMNS_V2.flatMap((c) => [c, ...(ADDED3[c] || [])]);
export const COLUMNS_OF = { 1: COLUMNS_V1, 2: COLUMNS_V2, 3: COLUMNS };
export const SUMS = ["paid_units", "fee_units", "refunded_units", "reverted_units"];
export const OBJECTS = ["authorisation", "acceptance", "commercial", "settlement"];
export const SETTLEMENTS = ["paid on devnet (test money)", "held", "refunded", "reverted", "payable", "paid outside Knos"];
const [PAID, HELD, REFUNDED, REVERTED, PAYABLE, OUTSIDE] = SETTLEMENTS;
const TEST = "test USDC";
export const SAID = {
  NO_SECOND: "One account funded this by comment, within the Balance's limits. No second person approved: Knos has no approval step of its own.",
  ONE_WALLET: "One wallet signed the funding. If that wallet is a multisig's vault, the multisig's threshold is the approval, and `knos audit show` reads it from the chain.",
  FAUCET: "Test money from the devnet faucet, which any commenter in the owner's repositories may spend. Nobody approved it, and nothing real was spent.",
  NO_LIMITS: "The log lines do not carry a Balance's limits. The acceptance receipt of the paying transaction has them as they were at funding (`knos receipt`), and `knos budget show` reads today's.",
  NO_EVALUATORS: "The log line names the program's rule, not the accounts. The acceptance receipt names each evaluator's owner and starter, and whether either is the buyer's or the seller's.",
};
export const explorer = (tx) => `https://explorer.solana.com/tx/${tx}?cluster=devnet`;

// ---- text, JSON and CSV exactly as the Python writes them ---------------------------------------------------------------------------------
/** audit._text: every value as text (None is "", True is "1"). */
export const text = (v) => (v === null || v === undefined ? "" : typeof v === "boolean" ? String(Number(v)) : String(v));
const quoted = (s) => JSON.stringify(s).replace(/[\u0080-\uffff]/g, (c) => `\\u${c.charCodeAt(0).toString(16).padStart(4, "0")}`);
/** json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=True). */
export function canonical(doc) {
  if (doc === null || doc === undefined) return "null";
  if (typeof doc === "string") return quoted(doc);
  if (typeof doc !== "object") return String(doc);
  if (Array.isArray(doc)) return `[${doc.map(canonical).join(",")}]`;
  return `{${Object.keys(doc).sort().map((k) => `${quoted(k)}:${canonical(doc[k])}`).join(",")}}`;
}
export async function sha256Hex(s) {
  const got = await globalThis.crypto.subtle.digest("SHA-256", new TextEncoder().encode(s));
  return [...new Uint8Array(got)].map((b) => b.toString(16).padStart(2, "0")).join("");
}
const textRow = (r) => Object.fromEntries(Object.entries(r).map(([k, v]) => [k, text(v)]));
/** audit._hash: sha256 of the canonical JSON of a row (or of the scope), every value as text. */
export const auditHash = (doc) => sha256Hex(canonical(textRow(doc)));
// records._cell, then a field as Python's csv module writes it
const cell = (v) => { const t = text(v); return /^[=+\-@\t\r]/.test(t) ? `'${t}` : t; };
const field = (v) => { const t = cell(v); return /[",\n\r]/.test(t) ? `"${t.replace(/"/g, '""')}"` : t; };
const csvOf = (lines) => lines.map((cells) => `${cells.map(field).join(",")}\n`).join("");
/** A CSV as Python's csv.reader reads it: quoted fields, doubled quotes, \n or \r\n between lines. */
export function csvRows(s) {
  const out = []; let row = [], cur = "", inside = false, any = false;
  for (let i = 0; i < s.length; i++) {
    const c = s[i];
    if (inside) { if (c === '"') { if (s[i + 1] === '"') { cur += '"'; i++; } else inside = false; } else cur += c; continue; }
    if (c === '"') { inside = true; any = true; } else if (c === ",") { row.push(cur); cur = ""; any = true; } else if (c === "\n" || c === "\r") {
      if (c === "\r" && s[i + 1] === "\n") i++;
      if (any || cur) row.push(cur);
      out.push(row); row = []; cur = ""; any = false;
    } else cur += c;
  }
  if (any || cur) { row.push(cur); out.push(row); }
  return out;
}

// ---- the statement: audit.chained, totals, write ------------------------------------------------------------------------------------------
/** The columns of a file of this scope's version. A version 1 file written before `authorised_by` existed (0.3.14) has lines
 *  without it, and keeps the columns it was written for, so its bytes and its head stay the ones printed then. */
export function columnsOf(scope, lines = []) {
  const got = COLUMNS_OF[Number(scope?.version)];
  if (!got) throw new Error(`This audit export says it is of version ${scope?.version}; this page reads versions ${Object.keys(COLUMNS_OF).join(", ")}.`);
  return Number(scope.version) === 1 && lines.some((r) => r.authorised_by === undefined) ? got.filter((c) => c !== "authorised_by") : got;
}
/** audit.chained: { rows, head }. The head of an empty export is its scope's hash. */
export async function chained(lines, scope) {
  let prev = await auditHash(scope);
  const rows = [], columns = columnsOf(scope, lines);
  for (const [n, r] of lines.entries()) {
    const all = { ...r, seq: n + 1, prev }, row = Object.fromEntries(columns.map((c) => [c, all[c] ?? ""]));
    rows.push(row);
    prev = await auditHash(row);
  }
  return { rows, head: prev };
}
/** audit.totals: per currency (never added across mints), how many lines and the sum of each money column; currencies in order. */
export function totals(rows) {
  const out = {};
  for (const r of rows) {
    const t = (out[text(r.currency)] ||= { lines: 0, ...Object.fromEntries(SUMS.map((c) => [c, 0])) });
    t.lines++;
    for (const c of SUMS) t[c] += Number(r[c] || 0);
  }
  return Object.fromEntries(Object.keys(out).sort().map((k) => [k, out[k]]));
}
/** audit.write: the file, "csv" or "json". A version 2 file names its version; a version 1 scope is written as version 1 was. */
export function auditWrite(scope, rows, head, fmt = "csv") {
  const sums = totals(rows), columns = columnsOf(scope, rows), version = Number(scope.version);
  if (fmt === "json") return `${canonical({ scope, columns, rows, totals: sums, head, rows_count: rows.length, ...(version > 1 ? { version } : {}) })}\n`;
  if (fmt !== "csv") throw new Error(`--format is csv or json; "${fmt}" is neither.`);
  return csvOf([...(version > 1 ? [[TYPE, "version", version]] : []), columns, ...rows.map((r) => columns.map((c) => text(r[c]))),
    ...Object.entries(sums).map(([cur, t]) => ["total", cur, t.lines, ...SUMS.map((c) => t[c])]), ["head", head, rows.length, canonical(scope)]]);
}
/** audit.export, from the lines: { text, rows, head }. */
export async function auditExport(scope, lines, fmt = "csv") {
  const { rows, head } = await chained(lines, scope);
  return { text: auditWrite(scope, rows, head, fmt), rows, head };
}
/** What is wrong with a statement's rows, in words (audit.verify without the file's own totals): [] when every hash and the head hold. */
export async function verifyRows(scope, rows, head) {
  const said = [], seen = new Set();
  let prev = await auditHash(scope);
  for (const [i, raw] of rows.entries()) {
    const r = textRow(raw), n = i + 1;
    if (r.seq !== String(n)) said.push(`Row ${n} is numbered ${r.seq}: a row was removed, added or moved before it.`);
    if (r.prev !== prev) said.push(`Row ${n} does not follow the row before it (its \`prev\` is not that row's hash): row ${n - 1 || "scope"} was edited or removed, or this row was moved.`);
    if (r.billing_key && (seen.has(r.billing_key) || r.billed_before !== "0")) said.push(`Row ${n} bills ${r.billing_key} a second time.`);
    seen.add(r.billing_key);
    prev = await auditHash(r);
  }
  if (prev !== head) said.push("The head does not match the last row: the last row was edited or removed, or rows were added after it.");
  return said;
}

// ---- the four linked objects: audit.record ------------------------------------------------------------------------------------------------
/** audit.deliverable_of: order:funded transaction:milestone. */
export function deliverableOf(row) {
  if (text(row.billing_key)) return text(row.billing_key);
  const milestone = text(row.standing) === "1" ? text(row.pull_request) || "-" : "0";
  return `${text(row.order)}:${text(row.funded_transaction)}:${milestone}`;
}
/** audit.deliverables: the rows by deliverable, in the file's order (a Map). */
export function deliverables(rows) {
  const out = new Map();
  for (const r of rows) { const k = deliverableOf(r); if (!out.has(k)) out.set(k, []); out.get(k).push(textRow(r)); }
  return out;
}
export const REF_COLUMNS = ["order", "ref", "paid_outside", "dispute"];
/** audit.read_refs: { order or deliverable: { order, ref, paid_outside, dispute } }. Throws, in words, for another file. */
export function readRefs(s) {
  const got = csvRows(s), head = got[0] || [];
  if (!got.length || head[0] !== "order" || head[1] !== "ref" || head.some((c) => !REF_COLUMNS.includes(c))) {
    throw new Error("A refs file is a CSV whose first line is order,ref,paid_outside,dispute (the last two may be left out).");
  }
  const out = {};
  got.slice(1).forEach((cells, i) => {
    if (!cells.some((c) => c.trim())) return;
    const row = { ...Object.fromEntries(REF_COLUMNS.map((c) => [c, ""])), ...Object.fromEntries(head.slice(0, cells.length).map((c, n) => [c, cells[n].trim()])) };
    if (!row.order || cells.length > head.length) throw new Error(`Line ${i + 2} of the refs file names no order, or has more cells than the first line has columns.`);
    out[row.order] = row;
  });
  return out;
}
export const refOf = (refs, deliverable) => (refs || {})[deliverable] || (refs || {})[deliverable.split(":")[0]] || null;

/** records.units_text: 19500000 as "19.500000". */
export function unitsText(units) {
  const n = BigInt(units), a = n < 0n ? -n : n;
  return `${n < 0n ? "-" : ""}${a / 1000000n}.${String(a % 1000000n).padStart(6, "0")}`;
}
const money = (units, cur) => (cur === TEST ? unitsText(units) : "");
const unitsOf = (units, cur) => (cur === TEST ? `${unitsText(units)} ${cur}` : `${units} units of ${cur}`);

function each(rows) {
  const out = new Map();
  for (const r of rows) {
    const ids = r.supplier_ids ? r.supplier_ids.split(";") : [], tos = r.wallets.split(";"), share = (r.paid_each ?? "").split(";");
    ids.forEach((who, n) => {
      if (!out.has(who)) out.set(who, { github_id: who, wallet: "", units: 0 });
      const e = out.get(who);
      e.wallet = e.wallet || (n < tos.length ? tos[n] : "");
      if (r.kind === "paid" || r.kind === "released") e.units += n < share.length && share[n] ? Number(share[n]) : ids.length === 1 ? Number(r.paid_units) : 0;
    });
  }
  return [...out.values()];
}

/** audit.record: one deliverable as four linked objects, from its rows of a statement. `ref`: the buyer's refs line;
 *  `receipt`: the acceptance receipt of its paying transaction (version 3); `approval`: who approved when a Squads vault funded. */
export function record(given, ref = null, receipt = null, approval = null) {
  const rows = given.map(textRow), first = rows[0], last = rows[rows.length - 1], cur = first.currency;
  const total = (col, kinds) => rows.reduce((n, r) => n + (!kinds || kinds.includes(r.kind) ? Number(r[col] || 0) : 0), 0);
  const paid = total("paid_units", ["paid", "released"]), refunded = total("refunded_units"), reverted = total("reverted_units");
  const still = Number(last.held_units || 0), waiting = last.kind === "held";
  const accepted = rows.some((r) => r.verdict === "accepted" && ["paid", "released", "held"].includes(r.kind));
  const amount = paid + (waiting ? still : 0), outside = ref?.paid_outside || "";
  const at = first.authorised_by.indexOf(" ("), funder = at < 0 ? first.authorised_by : first.authorised_by.slice(0, at);
  const role = (at < 0 ? "" : first.authorised_by.slice(at + 2).replace(/\)+$/, "")) || "wallet";
  let said;
  if (approval) {
    const k = Number(approval.threshold), n = approval.members.length, who = approval.approved;
    said = k >= 2 ? `A Squads vault funded this: ${k} of its ${n} members had to approve${who === null || who === undefined ? "" : `, and ${who.length} did`}. This is the two-person approval Knos has today. It is the multisig's own rule, not a workflow inside Knos.`
      : `A Squads vault funded this, and its threshold is 1 of ${n}: one member alone could approve. That is not a two-person approval.`;
  } else said = { wallet: SAID.ONE_WALLET, faucet: SAID.FAUCET }[role] || SAID.NO_SECOND;
  const c3 = receipt?.version === 3 ? receipt.commercial_authorisation || null : null, seen = c3 ? receipt.evaluator_observed || null : null;
  const judged = rows.filter((r) => r.judge);
  const evaluators = seen
    ? seen.evaluators.map((e) => Object.fromEntries(["kind", "repository_id", "owner_id", "actor_id", "runner", "independent_of_buyer", "independent_of_seller"].map((k) => [k, e[k] ?? null])))
    : judged.slice(0, 1).map((r) => ({ kind: r.judge, rule: r.evaluator, independent_of_buyer: r.judge === "repository" ? false : null, independent_of_seller: null }));
  const evidence = [], linked = new Set();
  for (const [what, tx] of [["funded", first.funded_transaction], ...rows.map((r) => [r.kind, r.transaction])]) {
    if (tx && !linked.has(tx)) { linked.add(tx); evidence.push({ what, transaction: tx, link: explorer(tx) }); }
  }
  const ruling = rows.find((r) => r.exception.includes("arbiter ruling"));
  const dispute = ref?.dispute ? `open, as the refs file says: ${ref.dispute}` : ruling ? `ruled by the arbiter the order named (line ${ruling.seq}, ${ruling.transaction})` : null;
  const back = rows.find((r) => r.kind === "reverted") || (paid ? rows.find((r) => r.kind === "refunded") : undefined) || null;
  const correction = back === null ? null : {
    kind: back.kind === "reverted" ? "credit" : "refund", units: Number(back[`${back.kind}_units`]), line: Number(back.seq || 0), transaction: back.transaction,
    said: back.kind === "reverted" ? "Reverted inside the review window: what the order still held went back to the funder. What was already paid stays paid."
      : "The rest of the order went back to the funder after a part was paid.",
  };
  const until = last.held_until ? ` until ${last.held_until}` : "";
  let status, why;
  if (reverted) [status, why] = [REVERTED, `${unitsOf(reverted, cur)} went back to the funder on ${back ? back.date : last.date}; ${unitsOf(paid, cur)} stays paid.`];
  else if (outside) [status, why] = [OUTSIDE, `The buyer says it paid outside Knos: ${outside}.${paid ? " The chain also shows a payment on devnet: check that it was not paid twice." : ""}`];
  else if (waiting) [status, why] = [PAYABLE, `Accepted, and ${unitsOf(still, cur)} is owed. Held for the supplier's wallet${until}: the supplier binds a wallet, then anyone settles.`];
  else if (paid) [status, why] = [PAID, `${unitsOf(paid, cur)} reached the supplier on ${rows.find((r) => r.kind === "paid" || r.kind === "released").date}.${still ? ` ${unitsOf(still, cur)} is held back in a review window${until}.` : ""}`];
  else if (refunded) [status, why] = [REFUNDED, `${unitsOf(refunded, cur)} went back to the funder on ${last.date}. Nothing was accepted.`];
  else [status, why] = [HELD, `Funded, and nothing is accepted yet. The escrow holds ${unitsOf(still, cur)}${until}.`];
  const id = deliverableOf(first), fee = total("fee_units");
  const artifact = [...rows].reverse().find((r) => r.artifact && r.kind !== "reverted")?.artifact || null;
  return {
    id, record: first.record || "order",
    authorisation: {
      buyer: { owner_id: first.owner_id, funder: first.funder, login: c3?.funder?.login ?? null },
      supplier: each(rows),
      scope: { repository_id: first.repository_id, issue: first.issue, deliverable: id, private: first.private === "1" },
      budget: { kind: role === "wallet" ? "wallet" : role === "faucet" ? "faucet Balance" : "Balance",
        address: first.source || (funder.startsWith("wallet:") ? funder.slice(7) : null), limits_at_funding: c3 ? c3.limit : null,
        said: c3 ? null : role === "wallet" ? "A wallet has no limits of Knos's: it spends what it holds." : SAID.NO_LIMITS },
      approved_by: { funder, role, two_person: Boolean(approval && Number(approval.threshold) >= 2), multisig: approval || null, said },
    },
    acceptance: { accepted, artifact, policy: { terms_hash: first.terms_hash || null, version: first.terms_version || null, mode: first.mode }, evaluators,
      independence: seen ? seen.independence : evaluators.length ? SAID.NO_EVALUATORS : null, evidence, verdict: last.verdict },
    commercial: { deliverable: id, amount_units: amount, amount: money(amount, cur), price_units: Number(first.price_units || 0), fee_units: fee, fee: money(fee, cur),
      currency: cur, invoice_ref: ref?.ref || null, billed_before: rows.some((r) => r.billed_before === "1"), dispute, correction, lines: rows.map((r) => Number(r.seq || 0)) },
    settlement: { status, said: why, paid_units: paid, held_units: still, refunded_units: refunded, reverted_units: reverted, held_until: last.held_until || null,
      paid_outside: outside || null },
  };
}

/** audit.records_of: every deliverable of a statement, in the order each first appears. */
export function recordsOf(rows, refs = null, receipts = null, approvals = null) {
  const out = [];
  for (const [key, mine] of deliverables(rows)) {
    const paying = mine.find((r) => (receipts || {})[r.transaction]);
    out.push(record(mine, refOf(refs, key), paying ? receipts[paying.transaction] : null, (approvals || {})[mine[0].funded_transaction] || null));
  }
  return out;
}

// ---- the files a finance system imports: knos.exports ---------------------------------------------------------------------------------------
export const EXPORT_TYPE = "knos.finance-export", EXPORT_VERSION = 1, UNVERIFIED = "best effort, unverified";
export const FORMATS = {
  netsuite: { name: "NetSuite: CSV Import, Vendor Bill", extension: "csv", date: "M/D/YYYY", source: "https://docs.oracle.com/en/cloud/saas/netsuite/ns-online-help/section_N427250.html", unverified: true },
  sap: { name: "SAP S/4HANA: Import Supplier Invoices (app F3041)", extension: "csv", date: "YYYYMMDD", source: "https://userapps.support.sap.com/sap/support/knowledge/en/3782347", unverified: true },
  coupa: { name: "Coupa: flat file (CSV) import, Invoices", extension: "csv", date: "YYYY-MM-DD", source: "https://compass.coupa.com/en-us/products/product-documentation/integration-technical-documentation/coupa-core-flat-files-(csv)/flat-file-(csv)-import/invoices-import", unverified: true },
  quickbooks: { name: "QuickBooks Online: import bills", extension: "csv", date: "D/M/YYYY", source: "https://quickbooks.intuit.com/learn-support/en-ca/help-article/import-transactions/import-bills-quickbooks-online/L4Q6QWsRw_CA_en_CA", unverified: true },
  generic: { name: "Knos: generic finance export", extension: "csv", date: "YYYY-MM-DD", source: "docs/FINANCE.md", unverified: false },
};
export const DEFAULTS = { account: "Accepted agent work", entity: "", tax_code: "", date_format: "" };
const NETSUITE = ["External ID", "Vendor", "Date", "Reference No.", "Memo", "Expenses : Account", "Expenses : Amount", "Expenses : Memo"];
const QUICKBOOKS = ["Bill no.", "Supplier", "Bill Date", "Due Date", "Account", "Line Description", "Line Amount", "Line Tax Code", "Memo"];
const COUPA_INVOICE = ["Invoice", "Invoice Number", "Supplier Name", "Supplier Number", "Status", "Invoice Date", "Submit For Approval?", "Handling Amount",
  "Misc Amount", "Shipping Amount", "Line Level Taxation", "Tax Amount", "Tax Rate", "Tax Code", "Tax Rate Type", "Supplier Note", "Payment Terms", "Shipping Terms",
  "Requester Email", "Requester Name", "Requester Lookup Name", "Chart of Accounts", "Currency", "Contract Number"];
const COUPA_LINE = ["Invoice Line", "Invoice Number", "Supplier Name", "Supplier Number", "Line Number", "Description", "Price", "Quantity", "UOM", "PO Number", "Account Name", "Billing Notes"];
const SAP = ["Invoice ID", "Company Code", "Transaction", "Invoicing Party", "Reference", "Document Date", "Posting Date", "Document Type", "Document Header Text",
  "Document Currency", "Gross Invoice Amount", "G/L Account", "Item Text", "Debit/Credit", "Amount", "Tax Code", "Assignment"];
export const GENERIC = ["bill_no", "deliverable", "record", "date", "supplier", "supplier_wallet", "repository_id", "issue", "artifact", "amount", "amount_units",
  "currency", "fee_units", "status", "invoice_ref", "billed_before", "dispute", "correction", "terms_hash", "terms_version", "evaluator", "authorised_by", "receipt", "statement_head"];
const ISO = { [TEST]: "USD" };

/** exports.decimal: 19500000 as "19.50", 404999 as "0.404999": two to six places, never rounded. */
export function decimal(units) {
  const n = BigInt(units), part = String(n % 1000000n).padStart(6, "0").replace(/0+$/, "");
  return `${n / 1000000n}.${part.padEnd(2, "0")}`;
}
/** exports.day: a day (2026-09-03) in a product's format: YYYY, MM, DD, and M and D without the leading zero. */
export function day(date, fmt) {
  const [y, m, d] = date.split("-"), tokens = [["YYYY", y], ["MM", m], ["DD", d], ["M", String(Number(m))], ["D", String(Number(d))]];
  let out = "";
  for (let at = 0; at < fmt.length;) {
    const hit = tokens.find(([t]) => fmt.startsWith(t, at));
    if (hit) { out += hit[1]; at += hit[0].length; } else { out += fmt[at]; at++; }
  }
  return out;
}
export const billNumber = async (deliverable, supplier) => `KNOS-${(await sha256Hex(`${deliverable}|${supplier}`)).slice(0, 11).toUpperCase()}`;

/** exports.bills: one object per accepted deliverable per supplier, in the statement's order. */
export async function bills(scope, rows, head, refs = null) {
  const out = [];
  for (const rec of recordsOf(rows, refs)) {
    const { authorisation: a, acceptance: c, commercial: m, settlement: s } = rec;
    if (!c.accepted) continue;
    const first = rows.find((r) => deliverableOf(r) === rec.id && text(r.verdict) === "accepted");
    const tx = c.evidence.find((e) => e.what === "paid" || e.what === "held")?.transaction || "";
    for (const sup of a.supplier) {
      const units = sup.units || (a.supplier.length === 1 ? m.amount_units : 0);
      if (!units) continue;
      const vendor = `gh:${sup.github_id}`, test = m.currency === TEST && s.status !== OUTSIDE;
      const where = a.scope.private ? "a private order" : `repository ${a.scope.repository_id} issue ${a.scope.issue}`;
      out.push({
        bill_no: await billNumber(rec.id, vendor), deliverable: rec.id, record: rec.record, date: text(first.date), supplier: vendor, supplier_wallet: sup.wallet,
        repository_id: a.scope.repository_id, issue: a.scope.issue, artifact: c.artifact || "", amount: decimal(units), amount_units: units, currency: m.currency,
        iso: ISO[m.currency] || "", fee_units: m.fee_units, status: s.status, invoice_ref: m.invoice_ref || "", billed_before: Number(m.billed_before), dispute: m.dispute || "",
        correction: m.correction ? `${m.correction.kind} ${m.correction.units}` : "", terms_hash: c.policy.terms_hash || "", terms_version: c.policy.version || "",
        evaluator: c.evaluators.map((e) => e.kind).join(";"), authorised_by: `${a.approved_by.funder} (${a.approved_by.role})`, receipt: tx ? explorer(tx) : "", transaction: tx,
        statement_head: head, description: `Accepted deliverable: ${where}${c.artifact ? `, ${c.artifact}` : ""}`,
        memo: [test ? "TEST MONEY (devnet test USDC): not a payable" : "", s.status, `Knos statement sha256:${head}`, tx ? `receipt ${explorer(tx)}` : "", `deliverable ${rec.id}`,
          m.invoice_ref ? `ref ${m.invoice_ref}` : ""].filter(Boolean).join(" | "),
      });
    }
  }
  return out;
}

/** exports.write: the file of one format, as text. `rows`: the statement's rows with seq and prev. */
export async function exportAs(fmt, scope, given, head, refs = null, options = null) {
  if (!FORMATS[fmt]) throw new Error(`--format is csv, json, ${Object.keys(FORMATS).join(", ")}; "${fmt}" is none of them.`);
  const o = { ...DEFAULTS, ...Object.fromEntries(Object.entries(options || {}).filter(([, v]) => v)) };
  const rows = given.map(textRow), found = await bills(scope, rows, head, refs), when = (b) => day(b.date, o.date_format || FORMATS[fmt].date);
  if (fmt === "netsuite") return csvOf([NETSUITE, ...found.map((b) => [b.bill_no, b.supplier, when(b), b.bill_no, b.memo, o.account, b.amount, b.description])]);
  if (fmt === "quickbooks") return csvOf([QUICKBOOKS, ...found.map((b) => [b.bill_no, b.supplier, when(b), when(b), o.account, b.description, b.amount, o.tax_code, b.memo])]);
  if (fmt === "coupa") {
    return csvOf([COUPA_INVOICE, COUPA_LINE, ...found.flatMap((b) => [
      ["Invoice", b.bill_no, b.supplier, b.supplier, "draft", when(b), "No", "", "", "", "No", "", "", "", "", b.memo, "", "", "", "", "", o.entity, b.iso, ""],
      ["Invoice Line", b.bill_no, b.supplier, b.supplier, 1, b.description, b.amount, 1, "EA", b.invoice_ref, o.account, `Knos ${head}`]])]);
  }
  if (fmt === "sap") {
    return csvOf([SAP, ...found.map((b) => [b.bill_no, o.entity, 1, b.supplier, b.bill_no, when(b), when(b), "KR", `Knos ${head.slice(0, 20)}`, b.iso, b.amount, o.account,
      `Knos ${head.slice(0, 16)} tx ${b.transaction.slice(0, 24)}`, "S", b.amount, o.tax_code, b.invoice_ref.slice(0, 18)])]);
  }
  const sums = totals(rows);
  return csvOf([[EXPORT_TYPE, "version", EXPORT_VERSION, "generic"], GENERIC, ...found.map((b) => GENERIC.map((c) => b[c])),
    ...rows.map((r) => ["statement", r.seq, canonical(r)]), ...Object.entries(sums).map(([cur, t]) => ["total", cur, t.lines, ...SUMS.map((c) => t[c])]),
    ["head", head, rows.length, canonical(scope)]]);
}

/** exports.statement_of: the statement a generic file carries, as { scope, rows, head, text } (text: the audit CSV). */
export function statementOf(s) {
  const got = csvRows(s);
  if (!got.length || got[0].join(",") !== `${EXPORT_TYPE},version,${EXPORT_VERSION},generic`) throw new Error("This is not a generic finance export of this version: its first line does not say so.");
  const tail = got.find((c) => c[0] === "head" && c.length === 4);
  if (!tail) throw new Error("This generic finance export has no statement at its end: it was cut short or edited.");
  const scope = JSON.parse(tail[3]), rows = got.filter((c) => c[0] === "statement" && c.length === 3).map((c) => JSON.parse(c[2].startsWith("'") ? c[2].slice(1) : c[2]));
  return { scope, rows, head: tail[1], text: auditWrite(scope, rows, tail[1], "csv") };
}

// ---- the statement of one invoice: knos.statement and knos.exports.write_statement ----------------------------------------------------------
// A statement (kind knos-statement) is made by `knos statement make`; this page reads one, checks its own sha256, and
// writes the same CSV and the same export files as the Python, byte for byte (tests/web/statement.mjs, against
// tests/data/statement). It does not make the PDF: the browser prints the same cells (web/statements.js).
export const STATEMENT_KIND = "knos-statement", STATUS_KIND = "knos-statement-status", LABEL = "file export, not an integration";
export const LINE_STATES = ["agreed", "disputed", "duplicate", "insufficient_evidence"];
export const LINE_WORDS = { agreed: "agreed", disputed: "disputed", duplicate: "duplicate", insufficient_evidence: "insufficient evidence" };
export const PAY_WORDS = { payable: "payable", paid_outside: "paid outside Knos", held: "held", refunded: "refunded", devnet_demonstration: "devnet demonstration" };
export const STATEMENT_HEAD = ["line", "reference", "supplier", "state", "amount", "why", "deliverable", "evaluations", "invoice_line", "settlement", "payment", "evidence",
  "evidence_sha256", "duplicate_of", "assurance", "po_reference", "grn_reference"];
export const NOT_EVALUATED = "not evaluated", GRN_KIND = "knos-grn";
const NO_ORDER = { shadow: "no purchase order on record: a shadow run reads the invoice and GitHub, not the order; give the payment's receipt (--receipt)",
  month: "no purchase order on record: a closed month names each order by its deliverable, not its terms or approver; give the payment's receipt (--receipt)",
  events: "no purchase order on record: the log of events does not carry the order's terms or approver; give the payment's receipt (--receipt)" };
export const STATEMENT_FORMATS = ["quickbooks", "netsuite", "generic"];
const STATEMENT_GENERIC = ["bill_no", "line", "state", "payment", "date", "supplier", "reference", "amount", "currency", "why", "deliverable", "evaluations", "invoice_line",
  "settlement", "evidence", "evidence_sha256", "duplicate_of", "statement_sha256", "po_reference", "grn_reference", "assurance"];

/** The statement the front door made last (web/front_door.js, through web/statement_make.js), for the Statement page
 *  (web/statements.js) to open: hand(st, status) keeps it and says so; the page opens it now, or when it is first drawn. */
export const HANDED = { st: null, status: null };
export function hand(st, status = null) {
  Object.assign(HANDED, { st, status });
  if (typeof document !== "undefined") document.dispatchEvent(new CustomEvent("knos:statement"));
}
/** statement.canonical: JSON with sorted keys, no spaces, characters as they are (ensure_ascii=False), one final newline. */
export function canonicalText(doc) {
  const walk = (d) => (d === null || d === undefined ? "null" : typeof d !== "object" ? JSON.stringify(d)
    : Array.isArray(d) ? `[${d.map(walk).join(",")}]` : `{${Object.keys(d).sort().map((k) => `${JSON.stringify(k)}:${walk(d[k])}`).join(",")}}`);
  return `${walk(doc)}\n`;
}
/** statement.digest: the statement's own sha256, of its canonical bytes with the sha256 field empty. */
export const statementDigest = (st) => sha256Hex(canonicalText({ ...st, sha256: "" }));
const stUnits = (amount, scale) => {
  if (!amount) return 0n;
  const [whole, part = ""] = amount.replace(/^-/, "").split(".");
  return (amount.startsWith("-") ? -1n : 1n) * BigInt(whole + part.padEnd(scale, "0").slice(0, scale));
};
const stAmount = (value, scale) => {
  const neg = value < 0n, v = neg ? -value : value, base = 10n ** BigInt(scale);
  return `${neg ? "-" : ""}${v / base}.${(v % base).toString().padStart(scale, "0").replace(/0+$/, "").padEnd(2, "0")}`;
};
const eventsOf = (st, status) => {
  if (!status) return [];
  if (status.kind !== STATUS_KIND || status.statement !== st.sha256) throw new Error("The status file is another statement's: it names another sha256.");
  return status.events;
};
/** statement.grn_reference: the first evaluation's id as a note's; empty for a line nothing evaluated. */
export const grnReference = (ln) => (ln.evaluations.length ? `grn_${ln.evaluations[0].split("_").slice(1).join("_")}` : "");
/** statement.lines_now: the lines with the last settlement recorded for each, who approved it, and its assurance level,
 *  purchase order and goods-received note (computed: the recorded note's level, else reported, else "not evaluated"). */
export function statementLines(st, status = null) {
  const events = eventsOf(st, status);
  return st.lines.map((ln) => {
    const paid = events.filter((e) => e.type === "settlement" && e.line === ln.invoice_line), last = paid[paid.length - 1];
    const ok = events.find((e) => e.type === "approval" && e.lines.includes(ln.invoice_line));
    const noted = events.filter((e) => e.type === "grn" && e.line === ln.invoice_line).map((e) => e.grn), note = noted[noted.length - 1];
    ln = { ...ln, assurance: note ? note.receipt_of_goods.assurance : ln.evaluations.length ? "reported" : NOT_EVALUATED,
      po_reference: note && note.purchase_order ? note.purchase_order.number : "", grn_reference: grnReference(ln) };
    return { ...ln, settlement: last ? last.settlement : null, payment: last ? last.state : ln.payment, approved_by: ok ? `${ok.by} (${ok.role}) on ${ok.on}` : "" };
  });
}
/** statement.grn_said: a goods-received note's result in one sentence. */
export const grnSaid = (note) => (note.match ? "match" : `mismatch: ${note.mismatches.join("; ")}`);
/** statement.grn with no receipt at hand: the note recorded for the line as it was recorded, or one with no purchase
 *  order (which never matches). The three legs: purchase_order, receipt_of_goods, invoice_line. */
export function statementGrn(st, status, line) {
  const events = eventsOf(st, status), ln = statementLines(st, status).find((x) => x.invoice_line === line);
  if (!ln) throw new Error(`No line of this statement has the id ${line}. The ids are in the invoice_line column.`);
  const kept = events.filter((e) => e.type === "grn" && e.line === line);
  if (kept.length) return { ...kept[kept.length - 1].grn, recorded: kept[kept.length - 1].on };
  const wrong = [NO_ORDER[st.source]];
  if (!ln.evaluations.length) wrong.push("no receipt of goods: no evaluation of this line is on record");
  if (ln.state !== "agreed") wrong.push(`the invoice line is ${LINE_WORDS[ln.state]}${ln.why ? `: ${ln.why}` : ""}`);
  const goods = { reference: ln.grn_reference, verdict: ln.evaluations.length && ln.state === "agreed" ? "accepted" : "none",
    evaluator: { shadow: "GitHub's checks at the merged commit", month: "the meter, as both ledgers recorded it", events: "the log of events" }[st.source],
    controllers: [], assurance: ln.assurance, trusted: ln.evaluations.length ? [st.note] : [], declared_related: [], evidence: ln.evidence, receipt_sha256: null };
  return { kind: GRN_KIND, version: 1, statement: st.sha256, reference: goods.reference, purchase_order: null, receipt_of_goods: goods,
    invoice_line: { id: ln.invoice_line, line: ln.line, reference: ln.reference, supplier: ln.supplier, amount: ln.amount, currency: st.currency, state: ln.state, payment: ln.payment },
    match: false, mismatches: wrong, recorded: null };
}
/** statement.answers: what whoever approves the invoice asks, answered in order: [[question, answer]]. */
export function statementAnswers(st, status = null) {
  const now = statementLines(st, status), scale = st.scale, priced = Boolean(st.totals.billed.amount), unit = st.currency ? ` ${st.currency}` : "";
  const said = (rows) => `${rows.length} ${rows.length === 1 ? "line" : "lines"}${priced ? `, ${stAmount(rows.reduce((a, r) => a + stUnits(r.amount, scale), 0n), scale)}${unit}` : ""}`;
  const of = (state) => now.filter((r) => r.state === state);
  const approvals = eventsOf(st, status).filter((e) => e.type === "approval"), agreed = of("agreed"), waiting = agreed.filter((r) => !r.approved_by);
  const paid = now.filter((r) => r.payment === "paid_outside" || r.payment === "devnet_demonstration"), wrongly = paid.filter((r) => r.state !== "agreed");
  let approved = approvals.map((e) => `${e.lines.length} agreed ${e.lines.length === 1 ? "line" : "lines"}${priced ? `, ${e.amount}${unit}` : ""} by ${e.by} (${e.role}) on ${e.on}, role as stated`).join("; ") || "nobody yet";
  if (approvals.length && waiting.length) approved += `; ${waiting.length} agreed not yet approved`;
  const twice = of("duplicate");
  return [
    ["Authorised", st.source === "shadow" ? "not known here: a shadow run reads the invoice and GitHub, not the order"
      : `${new Set(now.map((r) => r.deliverable)).size} deliverables, each a milestone of an order both ledgers name`],
    ["Billed", `${said(now)} on invoice ${st.invoice}${st.supplier ? ` from ${st.supplier}` : ""}`],
    ["Delivered", `${now.filter((r) => r.evaluations.length).length} of ${now.length} lines name work that was evaluated`],
    ["Passed", `${said(agreed)} agreed`],
    ["Already billed", said(twice) + (twice.length ? `: ${twice.map((r) => `line ${r.line} (${r.duplicate_of})`).join("; ")}` : "")],
    ["Approved", approved],
    ["Disputed", `${said(of("disputed"))}, open`],
    ["Insufficient evidence", `${said(of("insufficient_evidence"))}, open`],
    ["Credited", `${said(now.filter((r) => r.payment === "refunded"))} refunded${wrongly.length ? `; ${said(wrongly)} paid though not agreed, to be credited or settled` : ""}`],
    ["Paid", said(paid) + (paid.length ? ` (${[...new Set(paid.map((r) => PAY_WORDS[r.payment]))].sort().join(", ")})` : "")],
    ["Owed", `${said(agreed.filter((r) => r.payment === "payable"))} payable`],
  ];
}
/** statement.cells: everything the CSV and the printed page say, as text. `statusHash`: sha256 of the status file's canonical text. */
export async function statementCells(st, status = null) {
  const ev = st.evidence, events = eventsOf(st, status);
  const top = [["invoice", st.invoice], ["date", st.date], ["supplier", st.supplier], ["buyer", st.buyer], ["currency", st.currency],
    ["made from", { shadow: "a shadow run: the invoice against GitHub's record", month: "a closed month of the meter" }[st.source]],
    ["evidence sha256", ev.sha256],
    ["evidence", `${ev.embedded !== null && ev.embedded !== undefined ? "inside the statement" : "in a file beside the statement"}; ${ev.signed.length ? `signed through GitHub by the ${ev.signed.join(" and the ")}` : "not signed"}`],
    ["status sha256", events.length ? await sha256Hex(canonicalText(status)) : "none recorded"]];
  const rows = statementLines(st, status).map((r) => [String(r.line), r.reference, r.supplier, LINE_WORDS[r.state], r.amount, r.why, r.deliverable, r.evaluations.join(" "),
    r.invoice_line, r.settlement || "", PAY_WORDS[r.payment], r.evidence, r.evidence_sha256, r.duplicate_of, r.assurance, r.po_reference, r.grn_reference]);
  const totals = ["billed", ...LINE_STATES].map((name) => [name === "billed" ? name : LINE_WORDS[name], String(st.totals[name].lines), st.totals[name].amount]);
  const recorded = events.map((e) => (e.type === "approval" ? ["approval", e.on, `${e.by} (${e.role})`, `${e.lines.length} agreed lines`, e.amount]
    : e.type === "grn" ? ["goods-received note", e.on, e.line, grnSaid(e.grn), e.grn.reference]
    : ["settlement", e.on, e.line, `${PAY_WORDS[e.state]} by ${e.method}, reference ${e.reference}`, e.settlement]));
  return { top, head: [...STATEMENT_HEAD], rows, totals, answers: statementAnswers(st, status), events: recorded };
}
// statement._cell: a quote before text a spreadsheet would run as a formula (never before a plain number), then RFC 4180 quoting
const stCell = (v) => { let t = v === null || v === undefined ? "" : String(v); if (!/^-?\d+(\.\d+)?$/.test(t) && /^[=+\-@]/.test(t)) t = `'${t}`; return /[",\r\n]/.test(t) ? `"${t.replace(/"/g, '""')}"` : t; };
/** statement.as_csv: the statement's CSV, the bytes `knos statement make` writes. */
export async function statementCsv(st, status = null) {
  const c = await statementCells(st, status);
  const out = [[STATEMENT_KIND, String(st.version), st.sha256], ...c.top, c.head, ...c.rows, ...c.totals.map((t) => ["total", ...t]), ...c.answers.map((a) => ["answer", ...a]),
    ...c.events, ["note", st.note]];
  return out.map((row) => `${row.map(stCell).join(",")}\n`).join("");
}
/** exports.write_statement: the file an accounting system imports. Agreed lines only are bills; the generic file lists every line. */
export async function statementExport(fmt, st, status = null, options = null) {
  if (!STATEMENT_FORMATS.includes(fmt)) throw new Error(`--format is ${STATEMENT_FORMATS.join(", ")}; "${fmt}" is none of them.`);
  const o = { ...DEFAULTS, ...Object.fromEntries(Object.entries(options || {}).filter(([, v]) => v)) }, found = [];
  for (const ln of statementLines(st, status)) {
    const words = LINE_WORDS[ln.state], paid = PAY_WORDS[ln.payment];
    found.push({ bill: ln.state === "agreed", bill_no: await billNumber(ln.deliverable, ln.supplier), line: ln.line, state: words, payment: paid, date: st.date, supplier: ln.supplier,
      reference: ln.reference, amount: ln.amount, currency: st.currency, why: ln.why, deliverable: ln.deliverable, evaluations: ln.evaluations.join(" "), invoice_line: ln.invoice_line,
      settlement: ln.settlement || "", evidence: ln.evidence, evidence_sha256: ln.evidence_sha256, duplicate_of: ln.duplicate_of, statement_sha256: st.sha256,
      po_reference: ln.po_reference, grn_reference: ln.grn_reference, assurance: ln.assurance,
      description: `Invoice ${st.invoice} line ${ln.line}: ${ln.reference}`.replace(/[: ]+$/, ""),
      memo: [`${words}, ${paid}`, `Knos statement sha256:${st.sha256}`, `deliverable ${ln.deliverable}`, `invoice line ${ln.invoice_line}`, ...ln.evaluations.map((e) => `evaluation ${e}`),
        ln.settlement ? `settlement ${ln.settlement}` : "", ln.po_reference ? `PO ${ln.po_reference}` : "", ln.grn_reference ? `GRN ${ln.grn_reference}` : "",
        `assurance ${ln.assurance}`].filter(Boolean).join(" | ") });
  }
  const billed = found.filter((b) => b.bill && b.amount), when = (b) => day(b.date, o.date_format || FORMATS[fmt].date);
  if (fmt === "netsuite") return csvOf([NETSUITE, ...billed.map((b) => [b.bill_no, b.supplier, when(b), b.bill_no, b.memo, o.account, b.amount, b.description])]);
  if (fmt === "quickbooks") return csvOf([QUICKBOOKS, ...billed.map((b) => [b.bill_no, b.supplier, when(b), when(b), o.account, b.description, b.amount, o.tax_code, b.memo])]);
  return csvOf([[EXPORT_TYPE, "version", EXPORT_VERSION, "statement", LABEL], STATEMENT_GENERIC, ...found.map((b) => STATEMENT_GENERIC.map((c) => b[c]))]);
}
