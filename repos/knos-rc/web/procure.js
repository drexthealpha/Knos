// Procurement as data: a rate card, a standing offer, a budget envelope and an approval policy, each a small file in
// the buyer's repository (.knos/procurement/), read and judged here exactly as the command line does it. Pure
// functions: nothing here reads the page or the network. It is src/knos/controls.py (the three files) and
// src/knos/approvals.py (the policy, authority and the chain) again, sentence for sentence;
// tests/data/procure_cases.json holds both to one answer and tests/web/procure.mjs runs it in node.
//
// The files are a small, fixed part of YAML: `key: value`, nested keys, `- item` lists, `[a, b]` lists, "quoted
// text", whole numbers, true, false, null and `#` comments. Dates and amounts with a decimal point stay text.
// Amounts in a file are whole units as people write them (50, "12.5"); every function answers in millionths.
import { orderFee, priceConstants } from "./price.js";

export const PROCUREMENT = ".knos/procurement";
export const FILES = Object.freeze({ "rate-card": "rate-cards", "standing-offer": "offers", "budget-envelope": "envelopes" });
export const PERIODS = Object.freeze({ week: 7, month: 30, quarter: 90 });
export const ROLES = Object.freeze(["requester", "approver", "finance", "auditor"]);
export const SIGNING = Object.freeze(["approver", "finance"]);
export const REOPENED = Object.freeze({ same: "Reopened work is the same deliverable: it is not billed again.", new: "Reopened work is a new deliverable: it needs a new approval." });
const UNIT = 1_000_000, MAX_RETRIES = 20, DAYS = 14;
const DATE = /^[0-9]{4}-[0-9]{2}-[0-9]{2}$/, SLUG = /^[a-z0-9][a-z0-9-]{0,62}$/, LOGIN = /^[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}$/, HEX64 = /^[0-9a-f]{64}$/;
const KEY = /^([A-Za-z_][A-Za-z0-9_]*):(?: +(.*))?$/, INT = /^-?(?:0|[1-9][0-9]{0,14})$/, BARE = /^[A-Za-z_@/][A-Za-z0-9_./@-]*(?: [A-Za-z0-9_./@-]+)*$/;
// 400000 -> "0.40", 5000000000 -> "5,000.00" (knos.controls.money): at least two decimals, no zeros past them
export function money(units) {
  const whole = Math.floor(units / UNIT), frac = String(units % UNIT).padStart(6, "0").replace(/0+$/, "").padEnd(2, "0");
  return `${String(whole).replace(/\B(?=(\d{3})+$)/g, ",")}.${frac}`;
}
const isMap = (v) => v !== null && typeof v === "object" && !Array.isArray(v);
const has = (o, k) => Object.prototype.hasOwnProperty.call(o, k);
const is = (re, v) => typeof v === "string" && re.test(v);
const lower = (v) => String(v).toLowerCase();
const strip = (s) => s.replace(/^ +| +$/g, "");

// ---- the files ----------------------------------------------------------------------------------------------------------
/** What a file that is not that part of YAML throws; the message names the line. */
export class Unread extends Error {}

function uncomment(line) {
  let quoted = false;
  for (let i = 0; i < line.length; i++) {
    const ch = line[i];
    if (ch === '"' && (i === 0 || line[i - 1] !== "\\")) quoted = !quoted;
    else if (ch === "#" && !quoted && (i === 0 || line[i - 1] === " ")) return line.slice(0, i);
  }
  return line;
}
function items(inner) {
  const out = []; let quoted = false, start = 0;
  for (let i = 0; i < inner.length; i++) {
    const ch = inner[i];
    if (ch === '"' && (i === 0 || inner[i - 1] !== "\\")) quoted = !quoted;
    else if (ch === "," && !quoted) { out.push(inner.slice(start, i)); start = i + 1; }
  }
  return [...out, inner.slice(start)];
}
function scalar(text, n) {
  const s = text.trim();
  if (s === "" || s === "null" || s === "~") return null;
  if (s[0] === '"') {
    let got = null;
    try { got = JSON.parse(s); } catch { got = null; }
    if (typeof got !== "string") throw new Unread(`Line ${n}: the quoted text does not end where the line does.`);
    return got;
  }
  if (s[0] === "[") {
    if (!s.endsWith("]")) throw new Unread(`Line ${n}: a list in brackets ends on its own line.`);
    const inner = s.slice(1, -1).trim();
    return inner ? items(inner).map((p) => scalar(p, n)) : [];
  }
  if ("{|>&*!'%`".includes(s[0])) throw new Unread(`Line ${n}: these files use plain keys, lists and values only; \`${s[0]}\` starts something else.`);
  if (s === "true" || s === "false") return s === "true";
  return INT.test(s) ? Number(s) : s;
}
function map(rows, i, indent) {
  const out = {};
  while (i < rows.length && rows[i][0] === indent && !rows[i][1].startsWith("- ")) {
    const [, s, n] = rows[i], m = KEY.exec(s);
    if (!m) throw new Unread(`Line ${n}: expected \`key: value\`.`);
    const key = m[1], rest = m[2];
    if (has(out, key)) throw new Unread(`Line ${n}: \`${key}\` is written twice.`);
    i += 1;
    if (rest) out[key] = scalar(rest, n);
    else if (i < rows.length && (rows[i][0] > indent || (rows[i][0] === indent && rows[i][1].startsWith("- ")))) [out[key], i] = block(rows, i);
    else out[key] = null;
  }
  return [out, i];
}
function block(rows, i) {
  const indent = rows[i][0];
  if (!rows[i][1].startsWith("- ")) return map(rows, i, indent);
  const out = [];
  while (i < rows.length && rows[i][0] === indent && rows[i][1].startsWith("- ")) {
    const [, s, n] = rows[i], body = s.slice(2).replace(/^ +/, "");
    if (KEY.test(body)) {
      const inner = indent + s.length - body.length;
      rows[i] = [inner, body, n];
      let item; [item, i] = map(rows, i, inner);
      out.push(item);
    } else { out.push(scalar(body, n)); i += 1; }
  }
  return [out, i];
}
/** One procurement file as data, or Unread with the line that is not the part of YAML these files are written in. */
export function readYaml(text) {
  const rows = [];
  String(text).replace(/\r\n/g, "\n").split("\n").forEach((raw, k) => {
    const line = uncomment(raw).replace(/ +$/, "");
    if (line.includes("\t")) throw new Unread(`Line ${k + 1}: indent with spaces, not tabs.`);
    if (strip(line) === "" || strip(line) === "---") return;
    rows.push([line.length - line.replace(/^ +/, "").length, strip(line), k + 1]);
  });
  if (!rows.length) throw new Unread("The file is empty.");
  const [value, i] = block(rows, 0);
  if (i !== rows.length) throw new Unread(`Line ${rows[i][2]}: the indentation matches nothing above it.`);
  return value;
}
const quote = (s) => JSON.stringify(s).replace(/[\u007f-￿]/g, (c) => `\\u${c.charCodeAt(0).toString(16).padStart(4, "0")}`);
function plain(v) {
  if (v === null || v === undefined) return "null";
  if (typeof v === "boolean") return v ? "true" : "false";
  if (typeof v === "number") return String(v);
  const s = String(v);
  return DATE.test(s) || (BARE.test(s) && !["true", "false", "null"].includes(s)) ? s : quote(s);
}
/** The file readYaml reads back to `doc`: keys in the order given, a list of values on one line. */
export function dumpYaml(doc, indent = 0) {
  const out = [], pad = " ".repeat(indent);
  for (const [k, v] of Object.entries(doc)) {
    if (isMap(v)) out.push(`${pad}${k}:`, dumpYaml(v, indent + 2).slice(0, -1));
    else if (Array.isArray(v) && v.length && v.every(isMap)) {
      out.push(`${pad}${k}:`);
      for (const item of v) { const [first, ...rest] = dumpYaml(item, indent + 4).slice(0, -1).split("\n"); out.push(`${pad}  - ${strip(first)}`, ...rest); }
    } else if (Array.isArray(v)) out.push(`${pad}${k}: [${v.map(plain).join(", ")}]`);
    else out.push(`${pad}${k}: ${plain(v)}`);
  }
  return `${out.join("\n")}\n`;
}

/** Whole units as a file writes them (50, "12.5") in millionths, or null when it is not an amount. */
export function unitsOf(v) {
  const m = (typeof v === "string" || (typeof v === "number" && Number.isInteger(v))) ? /^([0-9]{1,9})(?:\.([0-9]{1,6}))?$/.exec(String(v)) : null;
  return m ? Number(m[1]) * UNIT + Number((m[2] || "").padEnd(6, "0")) : null;
}
/** A date written 2026-10-01 as a day number (days since 1970-01-01), or null when it is not a date. */
export function dayOf(v) {
  if (!is(DATE, v)) return null;
  const [y, m, d] = v.split("-").map(Number), t = new Date(Date.UTC(y, m - 1, d));
  if (y < 1) return null;
  if (y < 100) t.setUTCFullYear(y);
  return t.getUTCFullYear() === y && t.getUTCMonth() === m - 1 && t.getUTCDate() === d ? Math.round(t.getTime() / 86_400_000) : null;
}
/** Millionths as a file writes them: 20, 12.5 (knos.commands.amount). */
export const typed = (units) => { const part = units % UNIT; return `${Math.trunc(units / UNIT)}${part ? `.${String(part).padStart(6, "0").replace(/0+$/, "")}` : ""}`; };

function head(doc, kind, what, fields) {
  if (!isMap(doc)) return [`${what[0].toUpperCase()}${what.slice(1)} is a list of \`key: value\` lines, and this is not.`];
  const out = Object.keys(doc).filter((k) => !fields.includes(k)).map((k) => `\`${k}\` is not a field of ${what}.`);
  if (doc.version !== 1) out.push("`version` must be 1.");
  if (doc.kind !== kind) out.push(`\`kind\` must be ${kind}.`);
  if (fields.includes("name") && !is(SLUG, doc.name)) out.push("`name` is lower-case letters, digits and hyphens, like eng-2026q4.");
  if (fields.includes("currency") && doc.currency !== "test USDC") out.push("`currency` must be test USDC: this is devnet.");
  return out;
}
function span(doc, a, b) {
  const da = dayOf(doc[a]), db = dayOf(doc[b]);
  const out = [[a, da], [b, db]].filter(([, d]) => d === null).map(([k]) => `\`${k}\` is a date like 2026-10-01.`);
  if (da !== null && db !== null && da > db) out.push(`\`${a}\` is after \`${b}\`.`);
  return out;
}
const CARD_FIELDS = ["version", "kind", "name", "currency", "valid_from", "valid_to", "outcomes"], OUTCOME_FIELDS = ["name", "price", "unit", "terms", "terms_hash"];
const OFFER_FIELDS = ["version", "kind", "name", "rate_card", "outcome", "suppliers", "cap", "period", "starts", "ends", "envelope", "requested_by", "retries", "reopened"];
const ENVELOPE_FIELDS = ["version", "kind", "name", "owner", "cost_centre", "currency", "period_from", "period_to", "limit", "committed", "spent", "held", "left", "as_of"];
const POLICY_FIELDS = ["version", "kind", "currency", "self_approval_limit", "roles", "thresholds"], HOLDER_FIELDS = ["account", "from", "until", "limit"], TIER_FIELDS = ["up_to", "approvers", "finance"];

/** What is wrong with a rate card, in sentences ([]: nothing). `published`: { terms template: its hash }, when known. */
export function cardProblems(doc, published = null, c = priceConstants()) {
  const out = head(doc, "rate-card", "a rate card", CARD_FIELDS);
  if (!isMap(doc)) return out;
  out.push(...span(doc, "valid_from", "valid_to"));
  const rows = doc.outcomes;
  if (!Array.isArray(rows) || !rows.length || !rows.every(isMap)) return [...out, "`outcomes` lists at least one outcome, each with a name, a price, a unit and its terms."];
  const seen = new Set();
  rows.forEach((r, k) => {
    const name = r.name, me = is(SLUG, name) ? `Outcome \`${name}\`` : `Outcome ${k + 1}`;
    out.push(...Object.keys(r).filter((f) => !OUTCOME_FIELDS.includes(f)).map((f) => `${me}: \`${f}\` is not a field of an outcome.`));
    if (!is(SLUG, name)) out.push(`${me}: \`name\` is lower-case letters, digits and hyphens.`);
    else if (seen.has(name)) out.push(`${me} is listed twice.`);
    seen.add(name);
    const price = unitsOf(r.price);
    if (!price) out.push(`${me}: \`price\` is an amount above zero, like 50 or 12.5.`);
    else if (price < c.minAmount || price > c.maxAmount) out.push(`${me}: devnet pays between ${money(c.minAmount)} and ${money(c.maxAmount)} for one outcome.`);
    if (typeof r.unit !== "string" || !(r.unit.length > 0 && r.unit.length <= 60)) out.push(`${me}: \`unit\` says what is counted, like accepted pull request.`);
    if (!is(SLUG, r.terms) || !is(HEX64, r.terms_hash)) out.push(`${me}: \`terms\` names a template of terms/, and \`terms_hash\` is its 64 hex characters.`);
    else if (published !== null && !has(published, r.terms)) out.push(`${me}: terms/ has no template \`${r.terms}\`.`);
    else if (published !== null && published[r.terms] !== r.terms_hash) out.push(`${me}: \`terms_hash\` is not the published hash of \`${r.terms}\`.`);
  });
  return out;
}
export const outcomeOf = (card, name) => (card.outcomes || []).find((r) => isMap(r) && r.name === name) || null;

/** What is wrong with a standing offer ([]: nothing). `card`: the rate card it names, already found sound. */
export function offerProblems(doc, card = null, c = priceConstants()) {
  const out = head(doc, "standing-offer", "a standing offer", OFFER_FIELDS);
  if (!isMap(doc)) return out;
  out.push(...span(doc, "starts", "ends"));
  const who = doc.suppliers;
  if (who !== "anyone" && !(Array.isArray(who) && who.length && who.every((w) => is(LOGIN, w)) && new Set(who.map(lower)).size === who.length))
    out.push("`suppliers` is anyone, or a list of forge accounts, each once.");
  const cap = unitsOf(doc.cap);
  if (!cap) out.push("`cap` is an amount above zero: the most one supplier is paid in one period.");
  else if (cap > c.maxAmount) out.push(`\`cap\` is over ${money(c.maxAmount)}, the most devnet holds in one order.`);
  if (typeof doc.period !== "string" || !has(PERIODS, doc.period)) out.push("`period` is week, month or quarter.");
  for (const k of ["rate_card", "envelope"]) if (!is(SLUG, doc[k])) out.push(`\`${k}\` is the name of a file beside this one.`);
  if (!is(SLUG, doc.outcome)) out.push("`outcome` names one outcome of the rate card.");
  if (!is(LOGIN, doc.requested_by)) out.push("`requested_by` is the forge account of whoever asks for this.");
  if (typeof doc.retries !== "number" || !(doc.retries >= 1 && doc.retries <= MAX_RETRIES)) out.push(`\`retries\` is how many evaluations one deliverable may take: 1 to ${MAX_RETRIES}.`);
  if (typeof doc.reopened !== "string" || !has(REOPENED, doc.reopened)) out.push("`reopened` is same (not billed again) or new (a new deliverable).");
  if (card !== null && !out.length) {
    const row = outcomeOf(card, doc.outcome);
    if (doc.rate_card !== card.name) out.push(`The offer names rate card \`${doc.rate_card}\`, and this card is \`${card.name}\`.`);
    else if (row === null) out.push(`Rate card \`${card.name}\` has no outcome \`${doc.outcome}\`.`);
    else {
      if (cap < (unitsOf(row.price) || 0)) out.push(`The cap of ${money(cap)} is less than one \`${row.name}\` at ${money(unitsOf(row.price) || 0)}.`);
      if ((dayOf(doc.starts) || 0) < (dayOf(card.valid_from) || 0) || (dayOf(doc.ends) || 0) > (dayOf(card.valid_to) || 0))
        out.push(`The offer runs outside the rate card, which is valid ${card.valid_from} to ${card.valid_to}.`);
    }
  }
  return out;
}

/** An envelope's five amounts in millionths: { limit, committed, spent, held, left }. Left is never typed: it is the limit less the three. */
export function envelopeState(doc) {
  const [limit, committed, spent, held] = ["limit", "committed", "spent", "held"].map((k) => unitsOf(has(doc, k) ? doc[k] : 0) || 0);
  return { limit, committed, spent, held, left: limit - committed - spent - held };
}
/** What is wrong with a budget envelope ([]: nothing). */
export function envelopeProblems(doc) {
  const out = head(doc, "budget-envelope", "a budget envelope", ENVELOPE_FIELDS);
  if (!isMap(doc)) return out;
  out.push(...span(doc, "period_from", "period_to"));
  if (!is(LOGIN, doc.owner)) out.push("`owner` is the forge account of whoever answers for this budget.");
  if (typeof doc.cost_centre !== "string" || !(doc.cost_centre.length > 0 && doc.cost_centre.length <= 40)) out.push("`cost_centre` is your own code for it, like ENG-410.");
  if (!unitsOf(doc.limit)) out.push("`limit` is an amount above zero.");
  const bad = ["committed", "spent", "held"].filter((k) => has(doc, k) && unitsOf(doc[k]) === null);
  out.push(...bad.map((k) => `\`${k}\` is an amount, like 0 or 250.5.`));
  if (has(doc, "as_of") && dayOf(doc.as_of) === null) out.push("`as_of` is a date like 2026-10-01.");
  if (!bad.length && unitsOf(doc.limit)) {
    const s = envelopeState(doc);
    if (s.left < 0) out.push(`The envelope is over its limit by ${money(-s.left)}.`);
    else if (has(doc, "left") && unitsOf(doc.left) !== s.left) out.push(`\`left\` says ${doc.left}, and the limit less committed, spent and held is ${money(s.left)}.`);
  }
  return out;
}

/** How many periods a sound offer spans: the nearest whole number, at least one (a quarter is three months). */
export function periodsOf(offer) {
  const days = (dayOf(offer.ends) || 0) - (dayOf(offer.starts) || 0) + 1, one = PERIODS[offer.period];
  return Math.max(1, Math.floor((days + Math.floor(one / 2)) / one));
}
/** What opening a sound offer promises, in millionths: { suppliers, periods, cap, fee, value, leaves }. The cap is one
 *  supplier's for one period; `value` is caps alone (what an approval is asked for), `leaves` adds the fees (what an envelope counts). */
export function commitment(offer, c = priceConstants()) {
  const cap = unitsOf(offer.cap) || 0, suppliers = offer.suppliers === "anyone" ? 1 : offer.suppliers.length, periods = periodsOf(offer), fee = orderFee(cap, c.feeBps, c);
  return { suppliers, periods, cap, fee, value: cap * suppliers * periods, leaves: (cap + fee) * suppliers * periods };
}
/** Whether `leaves` more (amount and fee, millionths) fits a sound envelope, before anything starts: { ok, over, before,
 *  after, sentence }. Over the limit it is refused with the amount it is over by, and `after` stays `before`. */
export function fit(envelope, leaves) {
  const before = envelopeState(envelope), after = { ...before, committed: before.committed + leaves, left: before.left - leaves };
  const over = Math.max(0, -after.left), name = envelope.name;
  if (over) return { ok: false, over, before, after: before, sentence: `Refused: this is ${money(over)} over envelope \`${name}\`. ${money(Math.max(before.left, 0))} of ${money(before.limit)} is left.` };
  return { ok: true, over: 0, before, after, sentence: `Fits: ${money(leaves)} is committed, and ${money(after.left)} stays in envelope \`${name}\`.` };
}
/** One supplier's share of a sound offer in the shape of a template's `parts` (web/buyer_templates.json): the outcome's
 *  price is the rate, the cap the budget, the period the days; checks and paths are the cited terms template's. */
export function offerParts(offer, card, supplier, template) {
  const row = outcomeOf(card, offer.outcome) || {};
  return { ...template, kind: "offer", vendor: supplier, rate: typed(unitsOf(row.price) || 0), amount: typed(unitsOf(offer.cap) || 0), holdback: 0, warranty: 0, days: PERIODS[offer.period] };
}
/** The comment that funds one supplier's cap for one period on devnet (web/buyer.js commentOf writes the same line). */
export function offerComment(offer, card, supplier, template, defaultDays = DAYS) {
  const p = offerParts(offer, card, supplier, template);
  return [`/knos offer @${p.vendor} rate ${p.rate} budget ${p.amount}`, p.checks.length ? `checks: ${p.checks.join(", ")}` : "", p.paths.length ? `paths: ${p.paths.join(", ")}` : "",
    Number(p.days) !== defaultDays ? `days ${p.days}` : ""].filter(Boolean).join(" ");
}

// ---- the policy, authority, and the chain -----------------------------------------------------------------------------------
export const holders = (policy, role) => { const rows = isMap(policy.roles) ? policy.roles[role] : null; return Array.isArray(rows) ? rows.filter(isMap) : []; };

/** What is wrong with an approval policy, in sentences ([]: nothing). */
export function policyProblems(doc) {
  const out = head(doc, "approval-policy", "an approval policy", POLICY_FIELDS);
  if (!isMap(doc)) return out;
  if (unitsOf(has(doc, "self_approval_limit") ? doc.self_approval_limit : 0) === null) out.push("`self_approval_limit` is an amount; 0 means nobody approves their own request.");
  const roles = doc.roles;
  if (!isMap(roles) || !Object.keys(roles).length) return [...out, "`roles` names who holds each role: requester, approver, finance, auditor."];
  for (const [role, rows] of Object.entries(roles)) {
    if (!ROLES.includes(role)) { out.push(`\`${role}\` is not a role: the roles are requester, approver, finance and auditor.`); continue; }
    if (!Array.isArray(rows) || !rows.every(isMap)) { out.push(`Role \`${role}\` is a list of holders, each with an \`account\`.`); continue; }
    rows.forEach((h, k) => {
      const me = is(LOGIN, h.account) ? `Role \`${role}\`, @${h.account}` : `Role \`${role}\`, holder ${k + 1}`;
      out.push(...Object.keys(h).filter((f) => !HOLDER_FIELDS.includes(f)).map((f) => `${me}: \`${f}\` is not a field of a holder.`));
      if (!is(LOGIN, h.account)) out.push(`${me}: \`account\` is a forge account, like octocat.`);
      const days = ["from", "until"].filter((f) => has(h, f)).map((f) => [f, dayOf(h[f])]);
      out.push(...days.filter(([, d]) => d === null).map(([f]) => `${me}: \`${f}\` is a date like 2026-10-01.`));
      if (days.length === 2 && days.every(([, d]) => d !== null) && days[0][1] > days[1][1]) out.push(`${me}: \`from\` is after \`until\`.`);
      if (has(h, "limit") && (!SIGNING.includes(role) || !unitsOf(h.limit))) out.push(`${me}: \`limit\` is an amount above zero, for an approver or finance only.`);
    });
  }
  const tiers = doc.thresholds;
  if (!Array.isArray(tiers) || !tiers.length || !tiers.every(isMap)) return [...out, "`thresholds` lists at least one step, each with `approvers` and, but for the last, `up_to`."];
  let last = 0;
  tiers.forEach((t, k) => {
    const n = k + 1;
    out.push(...Object.keys(t).filter((f) => !TIER_FIELDS.includes(f)).map((f) => `Threshold ${n}: \`${f}\` is not a field of a threshold.`));
    const top = has(t, "up_to") ? unitsOf(t.up_to) : null;
    if (n < tiers.length && (!top || top <= last)) out.push(`Threshold ${n}: \`up_to\` is an amount above the step before it.`);
    if (n === tiers.length && has(t, "up_to")) out.push("The last threshold has no `up_to`: it covers every amount above.");
    last = top || last;
    for (const [role, least] of [["approvers", 1], ["finance", 0]]) {
      const need = has(t, role) ? t[role] : 0;
      if (typeof need !== "number" || !(need >= least && need <= 5)) out.push(`Threshold ${n}: \`${role}\` is a whole number from ${least} to 5.`);
      else if (need > new Set(holders(doc, role === "approvers" ? "approver" : role).map((h) => lower(h.account))).size) out.push(`Threshold ${n} asks for ${need} of \`${role}\`, and the policy names fewer.`);
    }
  });
  return out;
}
/** What a sound policy asks for `amount` (millionths): { approver, finance, up_to } (up_to null: the last step). */
export function tierOf(policy, amount) {
  for (const t of policy.thresholds) {
    const top = has(t, "up_to") ? unitsOf(t.up_to) : null;
    if (top === null || amount <= top) return { approver: Number(t.approvers || 0), finance: Number(t.finance || 0), up_to: top };
  }
  return { approver: 0, finance: 0, up_to: null };
}
const term = (h) => (has(h, "from") && has(h, "until") ? `from ${h.from} to ${h.until}` : has(h, "from") ? `from ${h.from}` : has(h, "until") ? `until ${h.until}` : "with no end date");
/** A holder's authority in a few words: "approver from 2026-01-01 to 2026-12-31, up to 25,000.00". */
export const authorityWords = (role, h) => `${role} ${term(h)}${has(h, "limit") ? `, up to ${money(unitsOf(h.limit) || 0)}` : ""}`;
/** [the holder's entry in force on the day `on`, ""] or [null, why not: one sentence]. */
export function heldOn(policy, account, role, on) {
  const mine = holders(policy, role).filter((h) => lower(h.account) === lower(account)), day = dayOf(on) || 0;
  if (!mine.length) return [null, `Refused: @${account} does not hold the ${role} role in this policy.`];
  for (const h of mine) if ((dayOf(h.from) || -1e9) <= day && day <= (dayOf(h.until) || 1e9)) return [h, ""];
  const ended = mine.filter((h) => has(h, "until") && (dayOf(h.until) || 0) < day);
  if (ended.length) return [null, `Refused: @${account}'s ${role} role ended ${ended.map((h) => h.until).sort().pop()}, before this approval of ${on}.`];
  return [null, `Refused: @${account}'s ${role} role starts ${mine.map((h) => h.from).sort()[0]}, after this approval of ${on}.`];
}
/** Did `approver` have the authority to approve `amount` (millionths) of `requester`'s request on the day `on`, in
 *  `role` (approver or finance)? { ok, role, authority, sentence }; a refusal's sentence says which rule refused. */
export function check(policy, { approver, requester, amount, on, role = "approver" }) {
  const no = (sentence) => ({ ok: false, role, authority: "", sentence });
  if (!SIGNING.includes(role)) return no(`Refused: the ${role} role approves nothing; an approver or finance does.`);
  const [h, why] = heldOn(policy, approver, role, on);
  if (h === null) return no(why);
  const own = unitsOf(has(policy, "self_approval_limit") ? policy.self_approval_limit : 0) || 0;
  if (lower(approver) === lower(requester) && amount > own) return no(`Refused: @${approver} asked for this, and nobody approves their own request${own ? ` above ${money(own)}.` : "."}`);
  if (has(h, "limit") && amount > (unitsOf(h.limit) || 0)) return no(`Refused: ${money(amount)} is over @${approver}'s own limit of ${money(unitsOf(h.limit) || 0)}.`);
  const words = authorityWords(role, h);
  return { ok: true, role, authority: words, sentence: `Fine: @${approver} is ${words}.` };
}
/** Where one request stands: { subject, amount, need, counted, refused, waiting, met, sentence }. Every event of the
 *  subject is judged again for its own day; an account counts once; `waiting` names who could still sign on the day `on`. */
export function chain(policy, { subject, requester, amount, events, on }) {
  const tier = tierOf(policy, amount), counted = [], refused = [], got = { approver: 0, finance: 0 };
  if (heldOn(policy, requester, "requester", on)[0] === null) refused.push({ approver: requester, role: "requester", sentence: `Refused: @${requester} does not hold the requester role on ${on}.` });
  for (const e of events) {
    if (e.subject !== subject) continue;
    const who = String(e.approver ?? ""), role = String(e.role ?? "approver"), at = String(e.at ?? "").slice(0, 10);
    let said = check(policy, { approver: who, requester, amount, on: at, role });
    if (said.ok && counted.some((c) => lower(c.approver) === lower(who))) said = { ...said, ok: false, sentence: `Refused: @${who} already approved this, and one person counts once.` };
    const theirs = unitsOf(e.amount ?? "");
    if (said.ok && theirs !== null && theirs !== amount) said = { ...said, ok: false, sentence: `Refused: @${who} approved ${money(theirs || 0)}, and the request is now ${money(amount)}.` };
    if (said.ok) { counted.push({ approver: who, role, at: String(e.at ?? ""), authority: said.authority, source: (e.source || {}).url || "" }); got[role] += 1; }
    else refused.push({ approver: who, role, sentence: said.sentence });
  }
  const waiting = [];
  for (const role of SIGNING) {
    const short = tier[role] - got[role];
    if (short > 0) waiting.push({ role, count: short, who: [...new Set(holders(policy, role).filter((h) => !counted.some((c) => lower(c.approver) === lower(h.account))
      && check(policy, { approver: String(h.account), requester, amount, on, role }).ok).map((h) => String(h.account)))].sort((a, b) => (lower(a) < lower(b) ? -1 : lower(a) > lower(b) ? 1 : 0)) });
  }
  const met = !waiting.length && !refused.some((r) => r.role === "requester");
  const names = { approver: (n) => `${n} approver${n !== 1 ? "s" : ""}`, finance: () => "finance" };
  const need = SIGNING.filter((r) => tier[r]).map((r) => names[r](tier[r])).join(" and ");
  const sentence = met ? `Approved: ${need} signed, as ${money(amount)} needs.` : !waiting.length ? refused[0].sentence
    : `Waits for ${waiting.map((w) => names[w.role](w.count)).join(" and ")}: ${money(amount)} needs ${need}.`;
  return { subject, amount, need: { approver: tier.approver, finance: tier.finance }, counted, refused, waiting, met, sentence };
}
/** [subject, role asked for or null] of the first `/knos approve ...` line of a comment, or null when it has none. */
export function readComment(body) {
  const m = /^\/knos approve +(\S+)(?: +as +(approver|finance))? *$/m.exec(String(body).replace(/\r\n/g, "\n"));
  return m && /^[A-Za-z0-9][A-Za-z0-9_:./#-]{0,119}$/.test(m[1]) ? [m[1], m[2] || null] : null;
}
/** The line an approver posts on the forge. */
export const commentLine = (subject, role = "approver") => `/knos approve ${subject}${role === "finance" ? " as finance" : ""}`;
/** The events of an approvals log: one JSON object a line; a line that is not one is skipped. */
export function readLog(text) {
  const out = [];
  for (const line of String(text).split(/\r?\n/)) { let e = null; try { e = line.trim() ? JSON.parse(line) : null; } catch { e = null; } if (isMap(e) && e.type === "knos.approval") out.push(e); }
  return out;
}
