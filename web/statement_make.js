// A statement made in the page: knos.statement.from_shadow and knos.statement.approve, byte for byte.
//
//   keeping(get)                  [a reader that writes down what `get` said, the book it writes in] (knos.shadow.keeping)
//   fromShadow(bundle, meta)      the statement of a shadow run. bundle: { invoice: the invoice's text, answers: { path:
//                                 GitHub's answer } }. meta: invoice, supplier, buyer, currency, date, each optional
//   approve(st, status, by, role, on)   the status with one more approval of every agreed line nobody approved yet
//   HANDED, hand(st, status)      web/finance_data.js's: the statement the front door made last, for the Statement page to open
//
// The front door (web/front_door.js) makes its statement here, so what it downloads is the file `knos statement make`
// writes from the same evidence: the same columns, the four ids of src/knos/ids.py, the four line states. The Statement
// page (web/statements.js) opens the same object. tests/web/statement.mjs holds this file to tests/data/statement.
import { parse, read, statement as shadowStatement, recorded, Unread, NOTE } from "./shadow.js";
import { canonicalText, statementDigest, LINE_STATES, STATEMENT_KIND, STATUS_KIND, HANDED, hand } from "./finance_data.js";

export const POLICY_SHADOW = "github-checks-at-merge.v1";
export const SHADOW_NOTE = `${NOTE} GitHub's answers are kept as they were read; GitHub does not sign them.`;

const enc = new TextEncoder();
const hex = (buf) => [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("");
const sha = async (text) => hex(await globalThis.crypto.subtle.digest("SHA-256", enc.encode(text)));
/** ids._id: the prefix and 24 hex characters of a SHA-256 over the tagged, length-prefixed parts. */
async function id(kind, prefix, ...parts) {
  const chunks = [enc.encode(`knos.id.v1\0${kind}\0`)];
  for (const p of parts) { const b = enc.encode(String(p)), n = new Uint8Array(4); new DataView(n.buffer).setUint32(0, b.length); chunks.push(n, b); }
  const all = new Uint8Array(chunks.reduce((a, c) => a + c.length, 0));
  chunks.reduce((at, c) => { all.set(c, at); return at + c.length; }, 0);
  return `${prefix}_${hex(await globalThis.crypto.subtle.digest("SHA-256", all)).slice(0, 24)}`;
}
export const ids = {
  deliverable: (scope, key) => id("deliverable", "dlv", scope, key),
  evaluation: (deliverable, artifact, policy, evaluator, run) => id("evaluation", "evl", deliverable, artifact, policy, evaluator, run),
  invoiceLine: (supplier, invoice, line) => id("invoice_line", "inv", supplier, invoice, line),
  settlement: (deliverable, method, reference) => id("settlement", "stl", deliverable, method, reference),
};

const units = (amount, scale) => {
  if (!amount) return 0n;
  const [whole, part = ""] = amount.replace(/^-/, "").split(".");
  return (amount.startsWith("-") ? -1n : 1n) * BigInt(whole + part.padEnd(scale, "0").slice(0, scale));
};
const amountOf = (value, scale) => {
  const neg = value < 0n, v = neg ? -value : value, base = 10n ** BigInt(scale);
  return `${neg ? "-" : ""}${v / base}.${(v % base).toString().padStart(scale, "0").replace(/0+$/, "").padEnd(2, "0")}`;
};
const DAY = /^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$/;
const day = (text) => { if (!DAY.test(text || "")) throw new Error(`A day is written YYYY-MM-DD; "${text}" is not one.`); return text; };

export function keeping(get) {
  const book = {};
  return [async (path) => {
    try { book[path] = await get(path); } catch (e) { book[path] = { __unread: e instanceof Unread ? e.reason : "no answer" }; throw e; }
    return book[path];
  }, book];
}

export async function fromShadow(bundle, meta = {}) {
  const text = bundle.invoice, invoice = parse(text), [get, used] = keeping(recorded(bundle.answers));
  // knos.shadow.gather, keeping which paths each pull request was read from, in the order they were asked
  const facts = new Map(), paths = new Map();
  for (const ln of invoice.lines) {
    const key = ln.pr.toLowerCase();
    if (!ln.repo || facts.has(key)) continue;
    const asked = [];
    facts.set(key, await read(ln.repo, ln.number, (path) => { asked.push(path); return get(path); }));
    paths.set(key, asked);
  }
  const sh = shadowStatement(invoice, facts);
  const sorted = Object.keys(used).sort((a, b) => (a < b ? -1 : a > b ? 1 : 0));
  const items = { invoice: await sha(text) };
  for (const p of sorted) items[p] = await sha(canonicalText(used[p]));
  const number = meta.invoice || `sha256:${items.invoice.slice(0, 16)}`, lines = [];
  for (const r of sh.lines) {
    const supplier = r.supplier || meta.supplier || sh.supplier, mine = await ids.invoiceLine(supplier, number, r.line);
    const asked = paths.get(r.pr.toLowerCase()) || [];
    const deliverable = r.class === "duplicate" ? lines[r.duplicate_of - 1].deliverable
      : r.issues.length ? await ids.deliverable(`github:${r.issues[0].split("#")[0].toLowerCase()}`, `issue ${r.issues[0].split("#")[1]}`)
      : r.url ? await ids.deliverable(`github:${r.pr.split("#")[0].toLowerCase()}`, `pull ${r.pr.split("#")[1]}`)
      : await ids.deliverable(`invoice:${number}`, mine);
    const judged = r.merged && r.class !== "unreadable";
    const [state, why] = { clean: ["agreed", ""],
      failed: ["disputed", `a check failed when this change was merged: ${r.failed.map((f) => f.name).join(", ")}`],
      not_merged: ["disputed", "the pull request is not merged"],
      duplicate: ["duplicate", `billed twice on this invoice: ${r.why}`],
      unverified: ["insufficient_evidence", `the checks give no verdict: ${r.why}`],
      unreadable: ["insufficient_evidence", `GitHub could not be read for this line: ${r.why}`] }[r.class];
    const link = r.failed.length && r.failed[0].url ? r.failed[0].url : r.url;
    lines.push({ line: r.line, reference: r.pr, supplier, deliverable,
      evaluations: judged ? [await ids.evaluation(deliverable, r.head, POLICY_SHADOW, "github", (await sha(canonicalText(r.checks))).slice(0, 16))] : [],
      invoice_line: mine, settlement: null, state, payment: state === "agreed" ? "payable" : "held", amount: r.amount || "", why, evidence: link,
      evidence_sha256: asked.length ? await sha(asked.map((p) => `${p} ${items[p]}\n`).join("")) : "",
      duplicate_of: r.duplicate_of === null ? "" : `line ${r.duplicate_of}` });
  }
  const merged = sh.lines.filter((r) => r.merged_at).map((r) => r.merged_at.slice(0, 10)).sort();
  const kept = { answers: Object.fromEntries(sorted.map((p) => [p, used[p]])), invoice: text };
  const evidence = { kind: "github-answers", signed: [], sha256: await sha(canonicalText(kept)), items, embedded: kept };
  const scale = 2, priced = lines.every((ln) => ln.amount);
  const sum = (rows) => (priced ? amountOf(rows.reduce((a, ln) => a + units(ln.amount, scale), 0n), scale) : "");
  const totals = { billed: { lines: lines.length, amount: sum(lines) } };
  for (const s of LINE_STATES) { const mine = lines.filter((ln) => ln.state === s); totals[s] = { lines: mine.length, amount: sum(mine) }; }
  const st = { kind: STATEMENT_KIND, version: 1, sha256: "", date: day(meta.date || merged[merged.length - 1] || "1970-01-01"), invoice: number,
    supplier: meta.supplier || sh.supplier, buyer: meta.buyer || "", currency: meta.currency || "", scale, source: "shadow", note: SHADOW_NOTE, prior: [],
    lines, totals, evidence };
  st.sha256 = await statementDigest(st);
  return st;
}

export function approve(st, status, by, role, on) {
  status = status || { kind: STATUS_KIND, version: 1, statement: st.sha256, events: [] };
  if (status.kind !== STATUS_KIND || status.statement !== st.sha256) throw new Error("The status file is another statement's: it names another sha256.");
  if (!String(by).trim() || !String(role).trim()) throw new Error("An approval names who approved and in which role.");
  const done = new Set(status.events.filter((e) => e.type === "approval").flatMap((e) => e.lines));
  const mine = st.lines.filter((ln) => ln.state === "agreed" && !done.has(ln.invoice_line));
  if (!mine.length) throw new Error(done.size ? "There is no agreed line left to approve." : "No line of this statement is agreed, so there is nothing to approve.");
  const event = { type: "approval", scope: "agreed", by: String(by).trim(), role: String(role).trim(), on: day(on), lines: mine.map((ln) => ln.invoice_line),
    amount: amountOf(mine.reduce((a, ln) => a + units(ln.amount, st.scale), 0n), st.scale) };
  return { ...status, events: [...status.events, event] };
}

export { HANDED, hand };
