// Shadow mode in the browser: paste or drop an invoice that bills per merged change, and see which billed changes had a
// failed check when they were merged. The invoice never leaves the page: it is read here, and the only host asked for
// anything is api.github.com, with no login (60 requests an hour, a budget the page shows and stops at).
//
//   renderShadow(el[, env])       the control: a box for the invoice, a row per line as it is checked, then the statement
//   parse(text)                   an invoice (CSV or JSON) as lines
//   gather(invoice, get)          what GitHub says about each pull request it names (`get(path)` reads one path)
//   statement(invoice, facts)     the statement; canonical(st) its bytes as text, digest(st) their sha256, asCsv(st)
//
// This is src/knos/shadow.py, function for function: the same invoice and the same answers from GitHub give the same
// bytes and so the same sha256 (tests/web/shadow.mjs, against tests/data/shadow_cases.json, which the Python wrote).
// What claims passing tests is the Agent PR Index's reading, the copy in front.js. Nothing is written to GitHub,
// nothing is paid, nothing is held.
import { findClaim } from "./front.js";

export const KIND = "knos-shadow-statement", VERSION = 1;
export const NOTE = "A failed check at merge is not proof the work is bad, and a green check is not proof it is good. " +
  "Shadow mode changes nothing and holds no money.";
export const CLASSES = ["clean", "failed", "unverified", "not_merged", "duplicate", "unreadable"];
export const DISPUTED = ["failed", "not_merged", "duplicate"];
export const LABELS = { clean: "verified clean", failed: "failed check at merge", unverified: "no verdict from checks",
  not_merged: "not merged", duplicate: "billed twice", unreadable: "could not be read" };
const ALIASES = { pr: ["pr", "pull_request", "url", "change"], amount: ["amount", "price", "total"], supplier: ["supplier", "vendor"] };
const API = "https://api.github.com";
export const ANONYMOUS_AN_HOUR = 60;      // what GitHub answers without a login
export const LINE_COSTS = 4;              // requests one line can need: the pull request, its check runs, its statuses, its commits

// examples/shadow/sample.csv, word for word (tests/test_shadow.py holds the two together)
export const SAMPLE = `# A sample assembled by Knos from public pull requests listed in docs/agent_pr_ci.json. Not anyone's invoice.
# The amounts are illustrative: nobody billed them. The lines were chosen to show both outcomes: this is not a rate.
pr,amount,supplier
https://github.com/stackql/stackql/pull/783,90.00,Sample assembled by Knos
zcaudate-xyz/foundation-base#454,120.00,Sample assembled by Knos
https://github.com/usestrix/strix/pull/753,60.00,Sample assembled by Knos
brainy-bots/arcane#260,100.00,Sample assembled by Knos
JPL-Devin/atlas#24,80.00,Sample assembled by Knos
finos-labs/dtcch-2026-compliledger#45,75.00,Sample assembled by Knos
`;

// ---- the invoice ------------------------------------------------------------------------------------------------------
const BLANK = " \t\r\n\u00a0\ufeff";
const trim = (s) => { let a = 0, b = s.length; while (a < b && BLANK.includes(s[a])) a++; while (b > a && BLANK.includes(s[b - 1])) b--; return s.slice(a, b); };
const count = (s, c) => s.split(c).length - 1;

function cells(text) {
  if (text.startsWith("\ufeff")) text = text.slice(1);
  const first = text.split("\n").find((l) => !trim(l).startsWith("#")) ?? "";
  const sep = count(first, ";") > count(first, ",") ? ";" : count(first, "\t") > count(first, ",") ? "\t" : ",";
  const rows = [];
  let row = [], cell = "", quoted = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (quoted) {
      if (c === '"' && text[i + 1] === '"') { cell += '"'; i++; } else if (c === '"') quoted = false; else cell += c;
    } else if (c === '"' && !trim(cell)) { cell = ""; quoted = true; } else if (c === sep) { row.push(cell); cell = ""; } else if (c === "\n") { row.push(cell); rows.push(row); row = []; cell = ""; } else if (c !== "\r") cell += c;
  }
  rows.push([...row, cell]);
  return rows.map((r) => r.map(trim)).filter((r) => r.some((c) => c) && !r[0].startsWith("#"));
}

function column(name) {
  const key = trim(name).toLowerCase().replace(/[ \t-]+/g, "_");
  return Object.keys(ALIASES).find((col) => ALIASES[col].includes(key)) || "";
}

export function pullOf(text) {
  const m = /github\.com\/([\w.-]+)\/([\w.-]+)\/pull\/(\d{1,10})/i.exec(text || "") || /^([\w.-]+)\/([\w.-]+)#(\d{1,10})$/.exec(trim(text || ""));
  return m ? { repo: `${m[1]}/${m[2]}`, number: Number(m[3]) } : null;
}

/** An amount in hundredths, as a BigInt; null for an empty cell; throws for anything that is not an amount. */
export function cents(text) {
  const t = (text || "").replace(/[^0-9.,-]/g, "");
  if (!t) { if (trim(text || "")) throw new Error(text); return null; }
  const m = /^(-?)([1-9]\d{0,2}(?:[.,]\d{3})+|\d+)(?:[.,](\d{1,2}))?$/.exec(t);
  if (!m) throw new Error(text);
  const value = BigInt(m[2].replace(/[.,]/g, "")) * 100n + BigInt(((m[3] || "") + "00").slice(0, 2));
  return m[1] ? -value : value;
}

export const money = (v) => `${v < 0n ? "-" : ""}${(v < 0n ? -v : v) / 100n}.${String((v < 0n ? -v : v) % 100n).padStart(2, "0")}`;

const textOf = (v) => (v === null || v === undefined || typeof v === "boolean" || typeof v === "object" ? "" : String(v));

export function parse(text) {
  const start = trim(text).slice(0, 1), table = [];
  if (start === "[" || start === "{") {
    const got = JSON.parse(text.replace(/^\ufeff+/, ""));
    const items = Array.isArray(got) ? got : got && got.lines;
    if (!Array.isArray(items)) throw new Error("the invoice's JSON holds no list of lines");
    for (const item of items) {
      const row = { pr: "", amount: "", supplier: "" };
      if (item && typeof item === "object" && !Array.isArray(item)) {
        for (const [name, value] of Object.entries(item)) { const col = column(String(name)); if (col && !row[col]) row[col] = trim(textOf(value)); }
      } else row.pr = trim(textOf(item));
      table.push(row);
    }
  } else {
    let rows = cells(text), head = rows.length ? rows[0].map(column) : [];
    if (head.includes("pr")) rows = rows.slice(1); else head = ["pr", "amount", "supplier"];
    for (const r of rows) {
      const row = { pr: "", amount: "", supplier: "" };
      head.forEach((col, i) => { if (col && i < r.length && !row[col]) row[col] = r[i]; });
      table.push(row);
    }
  }
  const lines = table.map((row, i) => {
    const named = pullOf(row.pr);
    let amount;
    try { amount = cents(row.amount); } catch { throw new Error(`line ${i + 1}: the amount ${row.amount} could not be read`); }
    return { line: i + 1, pr: named ? `${named.repo}#${named.number}` : row.pr, repo: named ? named.repo : "", number: named ? named.number : 0, amount, supplier: row.supplier };
  });
  if (!lines.length) throw new Error("the invoice names no line");
  return { lines };
}

// ---- GitHub, read only ----------------------------------------------------------------------------------------------------
export class Unread extends Error { constructor(reason) { super(reason); this.reason = reason; } }

/** A reader over answers written down earlier: { path: answer }, or { path: { __unread: reason } }. No network. */
export const recorded = (book) => async (path) => {
  if (!Object.prototype.hasOwnProperty.call(book, path)) throw new Unread("not in the recording");
  const got = book[path];
  if (got && typeof got === "object" && !Array.isArray(got) && "__unread" in got) throw new Unread(String(got.__unread));
  return got;
};

/** GitHub's public API with no login. `budget` is kept as GitHub reports it ({ remaining, limit, reset, asked, spent });
 *  when a line could not be finished with what is left, nothing more is asked: the rest is "rate limit". */
export function githubReader(fetchFn, budget, changed = () => {}) {
  return async (path) => {
    if (budget.spent || (/\/pulls\/\d+$/.test(path) && budget.remaining !== null && budget.remaining < LINE_COSTS)) { budget.spent = true; changed(); throw new Unread("rate limit"); }
    let r;
    try { r = await fetchFn(`${API}/${path}`, { headers: { Accept: "application/vnd.github+json" } }); } catch { throw new Unread("no answer"); }
    budget.asked++;
    const left = r.headers.get("x-ratelimit-remaining"), limit = r.headers.get("x-ratelimit-limit"), reset = r.headers.get("x-ratelimit-reset");
    if (left !== null && /^\d+$/.test(left)) budget.remaining = Number(left); else if (budget.remaining !== null && budget.remaining > 0) budget.remaining--;
    if (limit !== null && /^\d+$/.test(limit)) budget.limit = Number(limit);
    if (reset !== null && /^\d+$/.test(reset)) budget.reset = Number(reset);
    changed();
    if (r.ok) { try { return await r.json(); } catch { throw new Unread("no answer"); } }
    if (r.status === 429 || (r.status === 403 && (left === "0" || r.headers.get("retry-after")))) { budget.spent = true; changed(); throw new Unread("rate limit"); }
    throw new Unread(r.status === 404 ? "not found or private" : r.status === 401 || r.status === 403 ? "refused" : "no answer");
  };
}

// every row of a paged listing, 100 a page; null when it could not be read or was cut short (knos.terms.pages)
async function pages(path, get, key, cap = 10) {
  const rows = [], sep = path.includes("?") ? "&" : "?";
  try {
    for (let page = 1; page <= cap; page++) {
      const got = await get(`${path}${sep}per_page=100&page=${page}`);
      const batch = key && got && typeof got === "object" && !Array.isArray(got) ? got[key] : got;
      if (!Array.isArray(batch)) return null;
      rows.push(...batch);
      if (batch.length < 100) return rows;
      const total = got && !Array.isArray(got) ? got.total_count : null;
      if (Number.isInteger(total) && rows.length >= total) return rows;
    }
  } catch { return null; }
  return null;
}

export async function read(repo, number, get) {
  const facts = { pull: null, runs: null, statuses: null, commits: null, unread: "" }, why = [];
  const got = async (path) => { try { return await get(path); } catch (e) { why.push(e instanceof Unread ? e.reason : "no answer"); throw e; } };
  let pull;
  try { pull = await got(`repos/${repo}/pulls/${number}`); } catch { facts.unread = why[0]; return facts; }
  if (!pull || typeof pull !== "object" || Array.isArray(pull)) { facts.unread = "no answer"; return facts; }
  facts.pull = pull;
  const head = String((pull.head || {}).sha || "");
  if (!pull.merged_at) return facts;
  if (!head) { facts.unread = "no answer"; return facts; }
  facts.runs = await pages(`repos/${repo}/commits/${head}/check-runs`, got, "check_runs");
  facts.statuses = await pages(`repos/${repo}/commits/${head}/status`, got, "statuses");
  if (facts.runs !== null && facts.statuses !== null && !findClaim(pull.body)) {
    facts.commits = await pages(`repos/${repo}/pulls/${number}/commits`, got, null, 3);
    if (facts.commits === null) facts.unread = why.length ? why[0] : "cut short";
  }
  if (facts.runs === null || facts.statuses === null) facts.unread = why.length ? why[0] : "cut short";
  return facts;
}

/** `read` for every pull request the invoice names, once each: a Map from "owner/repo#n" in lower case to its facts.
 *  `before(line)` and `each(line, facts)` are called around every line, for a progress display. */
export async function gather(invoice, get, each, before) {
  const facts = new Map();
  for (const ln of invoice.lines) {
    const key = ln.pr.toLowerCase();
    if (before) before(ln);
    if (ln.repo && !facts.has(key)) facts.set(key, await read(ln.repo, ln.number, get));
    if (each) each(ln, facts.get(key), facts);
  }
  return facts;
}

// ---- which issue a pull request closes (knos.closing: closed_by, closing_issues) -------------------------------------------
const LINE_ENDS = /\r\n|[\n\r\v\f\x1c\x1d\x1e\x85\u2028\u2029]/;
const KEYWORD = /(?<![\w-])(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?):?[ \t]+(?:([\w.-]{1,100}\/[\w.-]{1,100}))?#(\d{1,10})\b/gi;

function prose(body) {
  const text = (body || "").slice(0, 200_000), out = [];
  for (let i = 0; ;) {
    const a = text.indexOf("<!--", i);
    if (a < 0) { out.push(text.slice(i)); break; }
    out.push(text.slice(i, a) + " ");
    const b = text.indexOf("-->", a + 4);
    if (b < 0) break;
    i = b + 3;
  }
  const lines = [];
  let fenced = false;
  for (const line of out.join("").split(LINE_ENDS)) {
    const t = line.trimStart();
    if (t.startsWith("```") || t.startsWith("~~~")) fenced = !fenced; else if (!fenced) lines.push(line.replace(/`[^`]*`/g, " "));
  }
  return lines.join("\n");
}

export function closedBy(pull) {
  const base = pull.base || {}, repo = base.repo || {}, name = String(repo.full_name || ""), out = [];
  if (base.ref && repo.default_branch && base.ref !== repo.default_branch) return out;
  for (const m of prose(pull.body || "").matchAll(KEYWORD)) {
    const n = Number(m[2]);
    if ((!m[1] || m[1].toLowerCase() === name.toLowerCase()) && n && !out.includes(n)) out.push(n);
  }
  return out;
}

// ---- the statement ----------------------------------------------------------------------------------------------------------
const AGENT_RUN_RE = /^(copilot|claude|claude[-_ ]?(code|review|code[-_ ]review|pr[-_ ]review)|codex|devin)$/i;   // the agent's own session, not project CI
const FAIL = new Set(["failure", "timed_out", "startup_failure"]), OK = new Set(["success", "neutral", "skipped"]);
const order = (a, b) => (a < b ? -1 : a > b ? 1 : 0);

export function checksOf(runs, statuses) {
  const out = [];
  let own = 0;
  for (const r of runs) {
    const name = String(r.name || "?");
    if (AGENT_RUN_RE.test(name.trim())) { own++; continue; }
    const done = r.status === "completed", concl = String(r.conclusion || "");
    const state = FAIL.has(concl) ? "failed" : !done ? "pending" : concl === "success" ? "passed" : OK.has(concl) ? "skipped" : "other";
    out.push({ name, kind: "run", conclusion: done || concl ? concl : String(r.status || ""), state, url: String(r.html_url || r.details_url || "") });
  }
  for (const s of statuses) {
    const said = String(s.state || "");
    const state = said === "failure" || said === "error" ? "failed" : said === "pending" ? "pending" : said === "success" ? "passed" : "other";
    out.push({ name: String(s.context || "?"), kind: "status", conclusion: said, state, url: String(s.target_url || "") });
  }
  return [out.sort((a, b) => order(a.name, b.name) || order(a.kind, b.kind) || order(a.url, b.url)), own];
}

export function verdict(checks) {
  const states = checks.map((c) => c.state);
  if (states.includes("failed")) return ["failed", ""];
  if (!checks.length) return ["unverified", "no check ran"];
  if (states.includes("pending")) return ["unverified", "a check has not finished"];
  if (states.includes("other")) return ["unverified", "a check ended without a verdict"];
  if (!states.includes("passed")) return ["unverified", "no check passed"];
  return ["clean", ""];
}

export function statement(invoice, facts) {
  const rows = [], firstPull = new Map(), firstIssue = new Map();
  for (const ln of invoice.lines) {
    const row = { line: ln.line, pr: ln.pr, url: ln.repo ? `https://github.com/${ln.repo}/pull/${ln.number}` : "", amount: ln.amount === null ? null : money(ln.amount),
      supplier: ln.supplier, class: "unreadable", why: "", merged: null, merged_at: "", merge_commit: "", head: "", claimed: "", issues: [], checks: [], failed: [],
      agent_runs: 0, duplicate_of: null };
    rows.push(row);
    const key = ln.pr.toLowerCase(), got = facts.get(key);
    if (!ln.repo) row.why = "no pull request named";
    else if (firstPull.has(key)) Object.assign(row, { class: "duplicate", duplicate_of: firstPull.get(key), why: `same pull request as line ${firstPull.get(key)}` });
    else if (!got || got.unread || got.pull === null) { firstPull.set(key, ln.line); row.why = (got && got.unread) || "no answer"; } else {
      firstPull.set(key, ln.line);
      const pull = got.pull;
      Object.assign(row, { merged: !!pull.merged_at, merged_at: String(pull.merged_at || ""), head: String((pull.head || {}).sha || "") });
      if (!row.merged) { row.class = "not_merged"; continue; }
      row.merge_commit = String(pull.merge_commit_sha || "");
      const home = String(((pull.base || {}).repo || {}).full_name || ln.repo);
      row.issues = closedBy(pull).map((n) => `${home}#${n}`);
      const messages = (got.commits || []).map((c) => String(((c || {}).commit || {}).message || ""));
      row.claimed = findClaim(pull.body) ? "description" : messages.some((m) => findClaim(m)) ? "commit" : "";
      [row.checks, row.agent_runs] = checksOf(got.runs, got.statuses);
      row.failed = row.checks.filter((c) => c.state === "failed").map((c) => ({ name: c.name, url: c.url }));
      const twice = row.issues.find((i) => firstIssue.has(i.toLowerCase()));
      if (twice) { const at = firstIssue.get(twice.toLowerCase()); Object.assign(row, { class: "duplicate", duplicate_of: at, why: `closes ${twice}, as line ${at} does` }); continue; }
      for (const i of row.issues) firstIssue.set(i.toLowerCase(), ln.line);
      [row.class, row.why] = verdict(row.checks);
    }
  }
  const priced = invoice.lines.every((ln) => ln.amount !== null);
  const billed = priced ? invoice.lines.reduce((a, ln) => a + ln.amount, 0n) : 0n, byAmount = priced && billed > 0n;
  const counts = {}, sums = {};
  for (const c of CLASSES) {
    counts[c] = rows.filter((r) => r.class === c).length;
    if (byAmount) sums[c] = invoice.lines.reduce((a, ln, i) => (rows[i].class === c ? a + ln.amount : a), 0n);
  }
  const lines = DISPUTED.reduce((a, c) => a + counts[c], 0);
  const part = byAmount ? DISPUTED.reduce((a, c) => a + sums[c], 0n) : BigInt(lines), whole = byAmount ? billed : BigInt(rows.length);
  let share = (2n * part * 10000n + whole) / (2n * whole);
  if (share < 0n) share = 0n;
  const names = [...new Set(rows.map((r) => r.supplier).filter(Boolean))];
  return { kind: KIND, version: VERSION, note: NOTE, supplier: names.length === 1 ? names[0] : "", basis: byAmount ? "amount" : "lines", lines_billed: rows.length, counts,
    amounts: byAmount ? { billed: money(billed), ...Object.fromEntries(CLASSES.map((c) => [c, money(sums[c])])) } : null,
    disputed: { lines, amount: byAmount ? money(part) : null, share_bp: Number(share), share: `${share / 100n}.${String(share % 100n).padStart(2, "0")}%` },
    complete: counts.unreadable === 0, lines: rows };
}

const canon = (v) => (v === null ? "null" : Array.isArray(v) ? `[${v.map(canon).join(",")}]`
  : typeof v === "object" ? `{${Object.keys(v).sort().map((k) => `${JSON.stringify(k)}:${canon(v[k])}`).join(",")}}` : JSON.stringify(v));
/** The statement's bytes, as text: JSON with sorted keys and no spaces, one final newline. */
export const canonical = (st) => `${canon(st)}\n`;

/** The sha256 of the statement's bytes: what `sha256sum statement.json` prints. */
export async function digest(st) {
  const hash = await globalThis.crypto.subtle.digest("SHA-256", new TextEncoder().encode(canonical(st)));
  return [...new Uint8Array(hash)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

const CSV_HEAD = ["line", "pull_request", "url", "supplier", "amount", "class", "why", "merged_at", "merge_commit", "last_commit", "claimed_passing", "failed_checks",
  "failed_check_links", "duplicate_of"];
function cell(value, words = false) {
  let t = value === null || value === undefined ? "" : String(value);
  if (words && "=+-@".includes(t.slice(0, 1)) && t) t = `'${t}`;
  return /[,"\r\n]/.test(t) ? `"${t.replace(/"/g, '""')}"` : t;
}
export function asCsv(st) {
  const out = [CSV_HEAD.join(",")];
  for (const r of st.lines) {
    out.push([cell(r.line), cell(r.pr, true), cell(r.url), cell(r.supplier, true), cell(r.amount), cell(r.class), cell(r.why, true), cell(r.merged_at), cell(r.merge_commit),
      cell(r.head), cell(r.claimed), cell(r.failed.map((f) => f.name).join(" | "), true), cell(r.failed.map((f) => f.url).join(" | "), true), cell(r.duplicate_of)].join(","));
  }
  return `${out.join("\n")}\n`;
}

// ---- the control --------------------------------------------------------------------------------------------------------------
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const link = (url, text) => (/^https:\/\//.test(url) ? `<a href="${esc(url)}" target="_blank" rel="noopener">${esc(text)}</a>` : esc(text));
const STATE = { clean: "done", unverified: "idle", failed: "bad", not_merged: "bad", duplicate: "bad", unreadable: "idle" };
const STYLE = `.shadow textarea{min-height:132px;font-size:13px}.shadow .sh-row{display:flex;flex-wrap:wrap;gap:8px;align-items:center}
.shadow .sh-big{font-size:clamp(44px,15vw,104px);line-height:1;margin:4px 0;font-weight:700;font-variant-numeric:tabular-nums}.shadow .sh-steps{list-style:none;padding:0;margin:12px 0}
.shadow .sh-steps li{overflow-wrap:anywhere;padding-bottom:10px}.shadow .sh-steps li[data-state=bad]{color:var(--bad)}.shadow .sh-steps li[data-state=done]{color:var(--ok)}
.shadow .sh-steps li[data-state=live]{font-weight:600}.shadow table{border-collapse:collapse}.shadow td,.shadow th{padding:4px 12px 4px 0;text-align:left}
.shadow td.k-num{text-align:right}.shadow .sh-hash,.shadow .sh-lines li,.shadow code{overflow-wrap:anywhere;word-break:break-word}.shadow .sh-drop{outline:2px dashed var(--accent)}
.shadow input[type=file]{position:absolute;width:1px;height:1px;opacity:0}`;

/** The statement as the page shows it: the disputed share as the one number, the counts, the lines that are not clean. */
export function statementHtml(st, hash) {
  const byAmount = st.basis === "amount", d = st.disputed;
  const rows = CLASSES.map((c) => `<tr data-class="${c}"><th scope="row">${esc(LABELS[c])}</th><td class="k-num">${st.counts[c]}</td>${byAmount ? `<td class="k-num">${esc(st.amounts[c])}</td>` : ""}</tr>`).join("");
  const lines = st.lines.filter((r) => r.class !== "clean").map((r) => `<li data-class="${r.class}"><span class="k-num">${r.line}</span> · ${r.url ? link(r.url, r.pr) : esc(r.pr || "no pull request")} · ${
    r.class === "failed" ? `failed: ${r.failed.map((f) => link(f.url, f.name)).join(", ")}` : esc(LABELS[r.class])}${r.class !== "failed" && r.why ? `: ${esc(r.why)}` : ""}</li>`).join("");
  return `<div class="sh-result k-reveal">
    <p class="k-kicker">Lines to question</p>
    <p class="sh-big k-num" data-sh="share">${esc(d.share)}</p>
    <p data-sh="of">${byAmount ? `${esc(d.amount)} of ${esc(st.amounts.billed)} billed` : `${d.lines} of ${st.lines_billed} lines billed`}</p>
    <div class="k-table"><table><thead><tr><th scope="col">Outcome</th><th scope="col">Lines</th>${byAmount ? `<th scope="col">Amount</th>` : ""}</tr></thead><tbody>${rows}</tbody></table></div>
    ${lines ? `<ul class="sh-lines">${lines}</ul>` : ""}
    ${st.complete ? "" : `<p data-sh="partial">Unread lines are counted apart, never guessed.</p>`}
    <p class="fine">A failed check is not proof of bad work.</p>
    <p class="fine">A green check is not proof of good work.</p>
    <p class="fine">This check changes nothing and holds no money.</p>
    <p class="fine mono sh-hash" data-sh="hash">sha256 ${esc(hash)}</p>
    <p class="sh-row"><button type="button" class="k-btn" data-sh="json">Download statement (JSON)</button>
      <button type="button" class="k-btn quiet" data-sh="csv">Download statement (CSV)</button></p>
  </div>`;
}

/** Draw shadow mode into `el`. `env` (all optional): { fetch } to read GitHub with, { sample } the sample invoice's text. */
export function renderShadow(el, env = {}) {
  const doc = el.ownerDocument, fetchFn = env.fetch || ((...a) => globalThis.fetch(...a)), sample = env.sample ?? SAMPLE;
  if (!doc.getElementById("shadow-style")) { const s = doc.createElement("style"); s.id = "shadow-style"; s.textContent = STYLE; doc.head.appendChild(s); }
  el.innerHTML = `<section class="shadow k-card">
    <p class="k-kicker">Read-only check</p>
    <h2>Check an invoice against GitHub</h2>
    <label for="shadow-in">Paste or drop the invoice (CSV)</label>
    <textarea id="shadow-in" rows="6" spellcheck="false" autocomplete="off" placeholder="pr,amount,supplier"></textarea>
    <p class="sh-row"><button type="button" class="k-btn" data-sh="run">Check invoice</button>
      <button type="button" class="k-btn quiet" data-sh="sample">Try with a sample</button>
      <label class="k-btn quiet" data-sh="pick">Choose a file<input type="file" accept=".csv,.json,text/csv,application/json"></label></p>
    <p class="fine">Stays in this page. Reads api.github.com only.</p>
    <p class="fine" data-sh="budget">GitHub allows ${ANONYMOUS_AN_HOUR} requests an hour without login.</p>
    <p class="fine" data-sh="mark"></p>
    <p data-sh="said" role="status" aria-live="polite"></p>
    <ol class="sh-steps" data-sh="steps"></ol>
    <div data-sh="out"></div>
  </section>`;
  const $ = (name) => el.querySelector(`[data-sh="${name}"]`), box = el.querySelector("textarea"), budget = { remaining: null, limit: ANONYMOUS_AN_HOUR, reset: null, asked: 0, spent: false };
  let busy = false, last = null;
  const showBudget = () => { $("budget").textContent = budget.remaining === null ? `GitHub allows ${ANONYMOUS_AN_HOUR} requests an hour without login.` : `GitHub lets this page make ${budget.remaining} more requests this hour (of ${budget.limit}).`; };
  const save = (name, text, type) => {
    const url = URL.createObjectURL(new Blob([text], { type })), a = doc.createElement("a");
    a.href = url; a.download = name; doc.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  };

  async function run() {
    if (busy) return;
    let invoice;
    $("out").innerHTML = ""; $("steps").innerHTML = ""; last = null;
    try { invoice = parse(box.value); } catch (e) { $("said").textContent = /^line \d+|^the invoice/.test(e.message) ? `Not read: ${e.message}.` : "Not read: paste a CSV that names pull requests."; return; }
    busy = true; budget.spent = false; $("run").disabled = true;
    $("said").textContent = `Checking ${invoice.lines.length} lines.`;
    $("steps").innerHTML = invoice.lines.map((ln) => `<li class="k-step" data-state="idle" data-line="${ln.line}"><span class="k-num">Line ${ln.line}</span> · ${esc(ln.pr || "no pull request")} <span data-said></span></li>`).join("");
    const step = (ln) => $("steps").querySelector(`[data-line="${ln.line}"]`);
    try {
      const rate = await fetchFn(`${API}/rate_limit`, { headers: { Accept: "application/vnd.github+json" } });   // asking for the budget does not spend it
      const core = rate.ok ? ((await rate.json()).resources || {}).core : null;
      if (core && Number.isInteger(core.remaining)) Object.assign(budget, { remaining: core.remaining, limit: core.limit ?? budget.limit, reset: core.reset ?? null });
    } catch { /* unknown: GitHub's own headers say it with the first answer */ }
    showBudget();
    const get = env.get || githubReader(fetchFn, budget, showBudget);
    const facts = await gather(invoice, get, (ln, _f, all) => {
      const row = statement({ lines: invoice.lines.slice(0, ln.line) }, all).lines[ln.line - 1], li = step(ln);
      li.dataset.state = STATE[row.class]; li.dataset.class = row.class;
      li.querySelector("[data-said]").textContent = `· ${LABELS[row.class]}`;
    }, (ln) => { step(ln).dataset.state = "live"; });
    const st = statement(invoice, facts), hash = await digest(st);
    last = { st, hash };
    $("out").innerHTML = statementHtml(st, hash);
    $("said").innerHTML = budget.spent ? `GitHub's hourly limit is used up. To check more lines, run <code>knos shadow invoice.csv</code> on your computer.` : `Checked ${invoice.lines.length} lines.`;
    busy = false; $("run").disabled = false;
    try { const motion = await import("./motion.js"); if (motion.reveal) motion.reveal(el); } catch { /* the page is complete without it */ }
  }

  $("run").addEventListener("click", run);
  $("sample").addEventListener("click", () => { box.value = sample; $("mark").textContent = "Sample assembled by Knos. Not anyone's invoice. Amounts are illustrative."; run(); });
  box.addEventListener("input", () => { $("mark").textContent = ""; });
  const take = async (file) => { if (file) { box.value = await file.text(); $("mark").textContent = ""; $("said").textContent = "Read in this page. Not uploaded."; } };
  el.querySelector("input[type=file]").addEventListener("change", (e) => take(e.target.files[0]));
  box.addEventListener("dragover", (e) => { e.preventDefault(); box.classList.add("sh-drop"); });
  box.addEventListener("dragleave", () => box.classList.remove("sh-drop"));
  box.addEventListener("drop", (e) => { e.preventDefault(); box.classList.remove("sh-drop"); take(e.dataTransfer.files[0]); });
  $("out").addEventListener("click", (e) => {
    const what = e.target.closest("[data-sh]")?.dataset.sh;
    if (!last) return;
    if (what === "json") save("statement.json", canonical(last.st), "application/json");
    if (what === "csv") save("statement.csv", asCsv(last.st), "text/csv;charset=utf-8");
  });
  return { run };
}
