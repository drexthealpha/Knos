// Statements: what an account was paid, or paid out, in one month, as a table and a CSV built in this browser.
// Read from statements/<login>.json (scripts/pages_data.py): one row per payment, in the mint's six decimals. The months,
// the table and the totals are worked out here from those rows; nothing is asked of anyone but this site, and the CSV is
// made from the rows on screen, in the browser, not fetched.
import { jsonFile, tableHtml, sourceHtml, isLogin, KIND_WORDS } from "./records.js";
import { show } from "./price.js";

const ROLES = { seller: ["as_seller", "Seller: what the account was paid"], owner: ["as_owner", "Owner: what the account's money paid out"] };
const KINDS = Object.keys(KIND_WORDS);

// months with at least one payment, newest first
export const monthsOf = (rows) => [...new Set(rows.map((r) => r.month))].sort().reverse();
export const inMonth = (rows, month) => rows.filter((r) => r.month === month);

// the totals of the rows given, by what each payment is counted as: real, test, self, own are never added together
export function totals(rows) {
  const out = {};
  for (const r of rows) {
    const t = (out[r.kind] ||= { kind: r.kind, currency: r.currency, payments: 0, amount_units: 0, fee_units: 0, total_units: 0 });
    t.payments++; t.amount_units += r.amount_units; t.fee_units += r.fee_units; t.total_units += r.total_units;
  }
  return KINDS.filter((k) => out[k]).map((k) => out[k]);
}

// A spreadsheet runs a cell that starts with = + - @ as a formula: text from GitHub gets a quote in front of one
// (as src/knos/records.py does for its receipts). Fields with a comma, quote or line break are quoted, as RFC 4180 says.
const safe = (v) => { const t = v === null || v === undefined ? "" : String(v); return typeof v === "string" && /^[=+\-@\t\r]/.test(t) ? `'${t}` : t; };
const field = (v) => { const t = safe(v); return /[",\n\r]/.test(t) ? `"${t.replace(/"/g, '""')}"` : t; };
export const csvOf = (columns, rows) => `${columns.join(",")}\n${rows.map((r) => columns.map((c) => field(r[c])).join(",")).join("\n")}${rows.length ? "\n" : ""}`;

export function initStatements(ctx) {
  const { $, esc, EXPLORER } = ctx;
  let loaded = null;           // { login, file }
  const say = (html, kind = "") => { $("stm-result").innerHTML = `<p class="status ${kind}">${html}</p>`; };
  const rolesRows = () => loaded.file[ROLES[$("stm-role").value][0]] || [];

  function months() {
    const have = monthsOf(rolesRows()), box = $("stm-month");
    box.innerHTML = have.map((m) => `<option value="${esc(m)}">${esc(m)}</option>`).join("");
    box.disabled = !have.length;
  }

  function render() {
    const rows = rolesRows(), month = $("stm-month").value, role = $("stm-role").value, login = loaded.login;
    if (!rows.length) { say(`${esc(login)} has no payment as ${role === "seller" ? "a seller" : "an owner"} in this site's files. ${role === "seller" ? "Try owner" : "Try seller"}.`); return; }
    const mine = inMonth(rows, month), seller = role === "seller", other = seller ? "funder" : "payee";
    const repo = (r) => (r.repository && /^[\w.-]+\/[\w.-]+$/.test(r.repository) ? `<a href="https://github.com/${esc(r.repository)}/issues/${esc(r.issue)}" target="_blank" rel="noopener">${esc(r.repository)}#${esc(r.issue)}</a>` : esc(`repository ${r.repository_id}, issue #${r.issue}`));
    const tx = (r) => (/^[1-9A-HJ-NP-Za-km-z]{60,90}$/.test(r.transaction || "") ? `<a href="${esc(EXPLORER("tx", r.transaction))}" target="_blank" rel="noopener">${esc(r.transaction.slice(0, 8))}…</a>` : esc(r.transaction || ""));
    const sum = totals(mine).map((t) => [esc(`${KIND_WORDS[t.kind]}`), esc(t.payments), esc(show(t.amount_units)), esc(show(t.fee_units)), esc(show(t.total_units)), esc(t.currency)]);
    $("stm-result").innerHTML = `<div id="stm-statement" data-role="${esc(role)}" data-month="${esc(month)}">
      <h4>${esc(login)}, ${esc(month)}: ${seller ? "paid to this account" : "paid out by this account"}</h4>
      <p class="fine">UTC days of the month, from the escrows' log lines on Solana devnet as the file lists them. ${seller ? "Amount is what reached the account; fee is what the escrow kept; total is what left escrow." : "Amount is what reached the people who did the work; fee is what the escrow kept; total is what left escrow."}</p>
      <div id="stm-table-box">${tableHtml(esc, ["date", "task", "pull request", other, "amount", "fee", "total", "currency", "transaction"], mine.map((r) => [esc(r.date), repo(r), esc(r.pull_request ?? ""), esc(seller ? r.funder ?? "" : r.payee ?? `id ${r.payee_id}`),
        esc(show(r.amount_units)), esc(show(r.fee_units)), esc(show(r.total_units)), esc(r.currency + (r.kind === "self" || r.kind === "own" ? ` (${KIND_WORDS[r.kind]})` : "")), tx(r)]))}</div>
      <h4>Totals</h4>
      <div id="stm-totals">${tableHtml(esc, ["counted as", "payments", seller ? "received" : "to the payees", "fees", "total out of escrow", "currency"], sum)}</div>
      <p><button type="button" id="stm-csv" class="ghost small"${mine.length ? "" : " disabled"}>Download the CSV</button> <span class="fine">Made here, from these rows, in your browser.</span></p>
      ${sourceHtml(esc, loaded.file, `statements/${loaded.login}.json`, "stm-source")}</div>`;
    const csv = $("stm-csv");
    csv.onclick = () => {
      const blob = new Blob([csvOf(loaded.file.columns, mine)], { type: "text/csv;charset=utf-8" }), url = URL.createObjectURL(blob), a = document.createElement("a");
      a.href = url; a.download = `knos-statement-${login}-${role}-${month}.csv`;
      document.body.append(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 2000);
    };
  }

  async function open(asked) {
    if (!isLogin(asked)) return say("Enter a GitHub login: letters, digits and single hyphens.", "bad");
    say(`Reading records.json…`);
    try {
      const index = await jsonFile("records.json").catch(() => null);
      const login = index ? index.accounts.find((x) => x.toLowerCase() === asked.toLowerCase()) : asked;
      const file = login ? await jsonFile(`statements/${login}.json`) : null;
      if (!file) { loaded = null; $("stm-month").innerHTML = ""; $("stm-month").disabled = true; say(`This site has no statement file for ${esc(asked)}. Only an account that was paid or funded a task, and that GitHub named, has one. <a href="#records">Everyone with a record</a>.`); return; }
      loaded = { login, file };
      $("stm-login").value = login;
      if (!(file.as_seller || []).length && (file.as_owner || []).length) $("stm-role").value = "owner";
      months();
      render();
    } catch (e) { say(esc(e.message), "bad"); }
  }

  $("stm-role").innerHTML = Object.entries(ROLES).map(([k, [, words]]) => `<option value="${k}">${esc(words)}</option>`).join("");
  $("stm-form").onsubmit = (ev) => { ev.preventDefault(); open($("stm-login").value.trim().replace(/^@/, "")); };
  $("stm-role").onchange = () => { if (loaded) { months(); render(); } };
  $("stm-month").onchange = () => { if (loaded) render(); };
  return (login) => { if (login) { $("stm-login").value = login; open(login); } $("statements").scrollIntoView?.(); };
}


// ---- the order statement: an organisation's month of work orders, as `knos audit export` writes it ----------------------------------
// audit/<owner id>.json (scripts/audit_statements.py) holds, per month, the scope and the lines of src/knos/audit.py. What follows
// is audit.py's `chained`, `totals` and `write` again, so "Export CSV" and "Export JSON" are byte for byte what
// `knos audit export --owner <id> --from <first day> --to <last day>` prints (tests/test_site_buyer.py holds them equal), and the
// head is the hash both parties compare. Nothing is fetched to export: the file is made here from the rows on screen.
//
// `authorised_by` is who authorised the order's money, as src/knos/controls.py authority_of words it: "gh:555000 (spender)",
// "gh:424242 (owner)", "gh:<id> (faucet)" or "wallet:<address>". The lines of audit/<owner id>.json carry it once the Python
// that wrote them does; a file whose lines have no such member was written before the column, and is exported with the
// columns it was written for (auditColumns), so its bytes and its head stay the ones `knos audit export` printed then.
export const AUTHORISED = "authorised_by";
export const AUDIT_COLUMNS = ["seq", "date", "time", "kind", "order", "funded_transaction", "owner_id", "funder", "commenter_id", AUTHORISED, "repository_id", "issue",
  "private", "standing", "mode", "price_units", "price", "funder_fee_units", "currency", "terms_hash", "pull_request", "artifact",
  "supplier_ids", "wallets", "judge", "evaluator", "verdict", "paid_units", "paid", "held_units", "refunded_units", "reverted_units",
  "fee_units", "fee", "transaction", "billing_key", "billed_before", "exception", "resolved_by", "prev"];
/** The columns of an export of these lines (or rows): all of them, or without `authorised_by` for a file written before it. */
export const auditColumns = (lines) => (lines.some((r) => r[AUTHORISED] === undefined) ? AUDIT_COLUMNS.filter((c) => c !== AUTHORISED) : AUDIT_COLUMNS);
export const AUDIT_SUMS = ["paid_units", "fee_units", "refunded_units", "reverted_units"];
// audit._text: every value as text (None is "", True is "1")
const auditText = (v) => (v === null || v === undefined ? "" : typeof v === "boolean" ? String(Number(v)) : String(v));
// json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
const asciiJson = (v) => JSON.stringify(v).replace(/[\u007f-￿]/g, (ch) => `\\u${ch.charCodeAt(0).toString(16).padStart(4, "0")}`);
export function canonical(v) {
  if (Array.isArray(v)) return `[${v.map(canonical).join(",")}]`;
  if (v && typeof v === "object") return `{${Object.keys(v).sort().map((k) => `${asciiJson(k)}:${canonical(v[k])}`).join(",")}}`;
  return asciiJson(v);
}
const sha256Hex = async (text) => [...new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text)))].map((b) => b.toString(16).padStart(2, "0")).join("");
/** audit._hash: sha256 of the canonical JSON of a row (or of the scope), every value as text. */
export const auditHash = (doc) => sha256Hex(canonical(Object.fromEntries(Object.entries(doc).map(([k, v]) => [k, auditText(v)]))));

/** audit.chained: { rows, head }: the lines numbered, each carrying the hash of the row before; the head of an empty export is its scope's hash. */
export async function auditChained(lines, scope) {
  let prev = await auditHash(scope);
  const rows = [], columns = auditColumns(lines);
  for (const [n, r] of lines.entries()) {
    const full = { ...r, seq: n + 1, prev }, row = Object.fromEntries(columns.map((c) => [c, full[c]]));
    rows.push(row);
    prev = await auditHash(row);
  }
  return { rows, head: prev };
}

/** audit.totals: per currency (never added across mints), how many lines and the sum of each money column; currencies in order. */
export function auditTotals(rows) {
  const out = {};
  for (const r of rows) {
    const t = (out[auditText(r.currency)] ||= { lines: 0, ...Object.fromEntries(AUDIT_SUMS.map((c) => [c, 0])) });
    t.lines++;
    for (const c of AUDIT_SUMS) t[c] += Number(r[c] || 0);
  }
  return Object.fromEntries(Object.keys(out).sort().map((k) => [k, out[k]]));
}

const csvCell = (t) => (/[",\n\r]/.test(t) ? `"${t.replace(/"/g, '""')}"` : t);                    // csv.writer, as Python quotes
const formulaSafe = (t) => (/^[=+\-@\t\r]/.test(t) ? `'${t}` : t);                                 // records._cell
/** audit.write: the file, "csv" or "json". */
export function auditWrite(scope, rows, head, fmt) {
  const sums = auditTotals(rows), columns = auditColumns(rows);
  if (fmt === "json") return `${canonical({ scope, columns, rows, totals: sums, head, rows_count: rows.length })}\n`;
  if (fmt !== "csv") throw new Error(`the format is csv or json; ${fmt} is neither`);
  const line = (cells) => `${cells.map((c) => csvCell(String(c))).join(",")}\n`;
  return line(columns) + rows.map((r) => line(columns.map((c) => formulaSafe(auditText(r[c]))))).join("")
    + Object.entries(sums).map(([cur, t]) => line(["total", cur, t.lines, ...AUDIT_SUMS.map((c) => t[c])])).join("")
    + line(["head", head, rows.length, canonical(scope)]);
}

/** audit.export, from the lines: { text, rows, head }. */
export async function auditExport(scope, lines, fmt = "csv") {
  const { rows, head } = await auditChained(lines, scope);
  return { text: auditWrite(scope, rows, head, fmt), rows, head };
}

// ---- the meter's three numbers, from a ledger file dropped onto the page ---------------------------------------------------------------
// A meter ledger (src/knos/ledger.py, docs/METER.md) is JSON Lines: a batch's header line {"batch": {...}}, then its
// evaluations, one line each: {"accepted": 1 or 0, "artifact", "buyer", "deliverable", "id", "milestone", "order", "policy",
// "rate", "seller"}, then its corrections: {"correction": {"batch", "by", "id", "kind": duplicate | verdict | withdrawn, "accepted"}}.
// The three numbers are ledger.py's Numbers, by its names: `evaluations` (each id once: the same evidence sent again is
// not another; a withdrawn one is not counted), `accepted_outcomes` (deliverables, order and milestone, with an accepted
// evaluation: one each, however many artifacts carried it) and `rejected` (evaluations whose verdict, after any verdict
// correction, is 0). ledger.py gives them per month; this gives them for the whole file, which is one month when the
// file is. The file is read in this browser and sent nowhere.
/** { evaluations, accepted_outcomes, rejected, accepted, batches, anchored, corrections, problems: [words] } of a ledger file's text. */
export function meterNumbers(text) {
  const ids = new Map(), problems = [], fixes = [];
  let batches = 0, anchored = 0;
  for (const [n, raw] of String(text).split(/\r?\n/).entries()) {
    if (!raw.trim()) continue;
    let o;
    try { o = JSON.parse(raw); } catch { problems.push(`Line ${n + 1} is not JSON.`); continue; }
    if (o && typeof o.batch === "object" && o.batch) { batches++; anchored += Number(o.batch.count) || 0; continue; }
    if (o && typeof o.correction === "object" && o.correction) { fixes.push(o.correction); continue; }
    if (!o || (o.accepted !== 0 && o.accepted !== 1) || typeof o.order !== "string" || !Number.isSafeInteger(o.milestone)) { problems.push(`Line ${n + 1} is not an evaluation: it needs accepted (1 or 0), order and milestone.`); continue; }
    const id = typeof o.id === "string" && o.id ? o.id : `${o.order}:${o.artifact}:${o.policy}:${o.milestone}`;
    if (!ids.has(id)) ids.set(id, { accepted: o.accepted, deliverable: typeof o.deliverable === "string" && o.deliverable ? o.deliverable : `${o.order}:${o.milestone}` });   // sent twice: one evaluation
  }
  for (const f of fixes) {                              // a duplicate is already counted once; a withdrawn one is not counted; a verdict is replaced
    if (f.kind === "withdrawn") ids.delete(f.id);
    else if (f.kind === "verdict" && ids.has(f.id) && (f.accepted === 0 || f.accepted === 1)) ids.get(f.id).accepted = f.accepted;
  }
  const all = [...ids.values()], accepted = all.filter((e) => e.accepted).length;
  return { evaluations: all.length, accepted_outcomes: new Set(all.filter((e) => e.accepted).map((e) => e.deliverable)).size, rejected: all.length - accepted, accepted,
    batches, anchored, corrections: fixes.length, problems };
}

const STATE_WORDS = { paid: "paid", released: "holdback released", kill: "kill fee paid", refunded: "refunded", reverted: "reverted", open: "funded, open", held: "accepted, held" };
const escHtml = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const explorer = (kind, id) => `https://explorer.solana.com/${kind}/${id}?cluster=devnet`;

/** The order statement, drawn into `el`: an organisation (its GitHub id, or its login, which GitHub turns into the id), a month,
 *  every line, the totals, and the two exports. env: { file(path) -> JSON or null, gh(path) -> JSON, EXPLORER(kind, id) }. */
export function renderOrderStatement(el, env = {}) {
  const doc = el.ownerDocument, esc = escHtml, EXPLORER = env.EXPLORER || explorer, file = env.file || jsonFile;
  const gh = env.gh || (async (path) => { const r = await fetch(`https://api.github.com${path}`, { headers: { Accept: "application/vnd.github+json" } }); if (!r.ok) throw new Error(r.status === 404 ? "GitHub has no such account." : `GitHub said ${r.status}`); return r.json(); });
  el.innerHTML = `<form id="ost-form"><label for="ost-owner">The organisation: its GitHub name, or its numeric id</label>
      <div class="row"><input id="ost-owner" autocomplete="off" placeholder="acme" spellcheck="false">
      <select id="ost-month" aria-label="Month" disabled></select></div>
      <button type="submit">Show the statement</button></form>
    <div id="ost-result" role="status" aria-live="polite"></div>
    <div id="ost-meter"><h4>The meter's count, beside the money</h4>
      <label for="ost-meter-file">Drop a meter ledger file anywhere on this card, or choose one. It is read in this browser and sent nowhere.</label>
      <input type="file" id="ost-meter-file" accept=".jsonl,.json,.txt,.ndjson">
      <div id="ost-meter-result" role="status" aria-live="polite"></div></div>`;
  const $ = (id) => doc.getElementById(id), out = $("ost-result");
  const say = (html, kind = "") => { out.innerHTML = `<p class="status ${kind}">${html}</p>`; };
  let loaded = null;                                    // { id, name, file }
  // the meter's three numbers: a file dropped on the card, or chosen. The exports above are not touched by it.
  async function meter(f) {
    const box = $("ost-meter-result");
    if (!f) return;
    if (f.size > 64 * 1024 * 1024) { box.innerHTML = `<p class="status bad">That file is over 64 MB: too large to read here.</p>`; return; }
    const m = meterNumbers(await f.text());
    box.innerHTML = m.evaluations || m.batches ? `<dl class="facts" id="ost-meter-numbers" data-file="${esc(f.name)}">
        <dt>Evaluations</dt><dd data-meter="evaluations"><strong>${esc(m.evaluations.toLocaleString("en-US"))}</strong> <span class="fine">billable: each acceptance policy run once on one artifact for one deliverable</span></dd>
        <dt>Accepted outcomes</dt><dd data-meter="accepted_outcomes"><strong>${esc(m.accepted_outcomes.toLocaleString("en-US"))}</strong> <span class="fine">deliverables that passed: one each, however the work was split</span></dd>
        <dt>Rejected</dt><dd data-meter="rejected"><strong>${esc(m.rejected.toLocaleString("en-US"))}</strong> <span class="fine">evaluations that did not pass; they are billable too</span></dd></dl>
      <p class="fine" id="ost-meter-note">From ${esc(f.name)}: ${esc(m.batches)} batch${m.batches === 1 ? "" : "es"} whose headers anchored ${esc(m.anchored)} evaluation${m.anchored === 1 ? "" : "s"}, ${esc(m.corrections)} correction${m.corrections === 1 ? "" : "s"}, ${esc(m.accepted)} accepted evaluation${m.accepted === 1 ? "" : "s"}.
        ${m.batches && m.anchored !== m.evaluations ? `The headers and the count differ by ${esc(Math.abs(m.anchored - m.evaluations))}: repeats and withdrawals are counted once or not at all here, or lines are missing from the file. <code>knos meter verify</code> says which.` : ""}
        The statement above and its exports are unchanged by this file.</p>
      ${m.problems.length ? `<ul class="plain" id="ost-meter-problems">${m.problems.slice(0, 5).map((p) => `<li class="status bad">${esc(p)}</li>`).join("")}</ul>` : ""}`
      : `<p class="status bad" id="ost-meter-none">${esc(f.name)} holds no evaluation: a meter ledger is JSON Lines, a batch header and then one line per evaluation. ${esc(m.problems[0] || "")}</p>`;
  }
  $("ost-meter-file").onchange = (ev) => meter(ev.target.files?.[0]).catch((e) => { $("ost-meter-result").innerHTML = `<p class="status bad">${esc(e.message)}</p>`; });
  const card = el.closest("section") || el;
  card.addEventListener("dragover", (ev) => { ev.preventDefault(); });
  card.addEventListener("drop", (ev) => { ev.preventDefault(); meter(ev.dataTransfer?.files?.[0]).catch(() => {}); });
  const save = (text, name, type) => {
    const url = URL.createObjectURL(new Blob([text], { type })), a = doc.createElement("a");
    a.href = url; a.download = name; doc.body.append(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 2000);
  };

  async function render() {
    const month = $("ost-month").value, m = loaded.file.months[month];
    if (!m) return say("Pick a month.");
    const { rows, head } = await auditChained(m.lines, m.scope), sums = auditTotals(rows), s = m.scope;
    const tx = (t) => (/^[1-9A-HJ-NP-Za-km-z]{60,90}$/.test(t || "") ? `<a href="${esc(EXPLORER("tx", t))}" target="_blank" rel="noopener">${esc(t.slice(0, 8))}…</a>` : esc(t || ""));
    const order = (a) => (/^[1-9A-HJ-NP-Za-km-z]{32,44}$/.test(a || "") ? `<a class="mono" href="${esc(EXPLORER("address", a))}" target="_blank" rel="noopener">${esc(a.slice(0, 6))}…</a>` : esc(a || ""));
    const what = (r) => (r.private ? "a private order" : `repository ${r.repository_id}, issue #${r.issue}${r.pull_request ? `, pull request #${r.pull_request}` : ""}`);
    const money = (u) => (u ? show(Number(u)) : "");
    const back = (r) => money(Number(r.refunded_units) + Number(r.reverted_units));
    const said = rows.length > 0 && auditColumns(rows).includes(AUTHORISED);       // who authorised each order's money, when the file says
    const command = `knos audit export --owner ${s.owner_id} --from ${s.from} --to ${s.to} --format csv`;
    out.innerHTML = `<div id="ost-statement" data-owner="${esc(s.owner_id)}" data-month="${esc(month)}">
      <h4>${esc(loaded.name)}, ${esc(month)}: every work order</h4>
      <p class="fine">One line per payment, refund, revert, or order still open at the end of ${esc(s.to)} (UTC), from the escrow's own log lines on Solana devnet. The fee is paid by the funder on top of the amount.${s.partial ? " The cluster did not give the whole history when this file was made: it is partial, and its head is not one to compare." : ""}</p>
      <div id="ost-table">${tableHtml(esc, ["date", "order", "what was bought", ...(said ? ["authorised by"] : []), "amount", "state", "paid", "fee", "sent back", "held", "currency", "transaction"],
        rows.map((r) => [esc(r.date), order(r.order), esc(what(r)), ...(said ? [esc(r[AUTHORISED])] : []), esc(money(r.price_units)), esc(STATE_WORDS[r.kind] || r.kind) + (r.exception ? `<br><span class="fine">${esc(r.exception)}</span>` : ""),
          esc(money(r.paid_units)), esc(money(r.fee_units)), esc(back(r)), esc(money(r.held_units)), esc(r.currency), tx(r.transaction)]))}</div>
      <h4>Totals</h4>
      <div id="ost-totals">${tableHtml(esc, ["currency", "lines", "paid", "fees", "refunded", "reverted"],
        Object.entries(sums).map(([cur, t]) => [esc(cur), esc(t.lines), esc(show(t.paid_units)), esc(show(t.fee_units)), esc(show(t.refunded_units)), esc(show(t.reverted_units))]))}</div>
      <p><button type="button" id="ost-csv" class="ghost small">Export CSV</button> <button type="button" id="ost-json" class="ghost small">Export JSON</button>
        <span class="fine">Made here, in your browser, from these rows.</span></p>
      <p class="fine" id="ost-recompute">How the other party recomputes it: <code>${esc(command)}</code> reads the same period from the chain and prints the same bytes as Export CSV
        (<code>--format json</code> for Export JSON). Compare one hash, the head: <span class="mono" id="ost-head">${esc(head)}</span>. <code>knos audit verify &lt;file&gt;</code>
        checks every row's hash, the totals and the head of a file someone sent you. Test USDC on devnet: not an invoice for real money.</p></div>`;
    const name = `knos-audit-${s.owner_id}-${month}`;
    $("ost-csv").onclick = () => save(auditWrite(s, rows, head, "csv"), `${name}.csv`, "text/csv;charset=utf-8");
    $("ost-json").onclick = () => save(auditWrite(s, rows, head, "json"), `${name}.json`, "application/json");
  }

  async function open(asked) {
    const t = asked.trim().replace(/^@/, "");
    if (!/^\d{1,15}$/.test(t) && !isLogin(t)) return say("Write the organisation's GitHub name (letters, digits and single hyphens) or its numeric id.", "bad");
    say("Reading…");
    try {
      const id = /^\d+$/.test(t) ? Number(t) : (await gh(`/users/${t}`)).id;
      if (!Number.isSafeInteger(id) || id < 1) throw new Error("GitHub did not give that account an id.");
      const got = await file(`audit/${id}.json`);
      const months = got && got.type === "knos.audit-statement" ? Object.keys(got.months || {}).sort().reverse() : [];
      if (!months.length) { loaded = null; $("ost-month").innerHTML = ""; $("ost-month").disabled = true; return say(`This site has no order statement for ${esc(t)} (GitHub id ${esc(id)}): none of its money has funded a work order that this site's files list. <code>knos audit export --owner ${esc(id)}</code> reads the chain itself.`); }
      loaded = { id, name: t, file: got };
      $("ost-month").innerHTML = months.map((m) => `<option value="${esc(m)}">${esc(m)}</option>`).join("");
      $("ost-month").disabled = false;
      await render();
    } catch (e) { say(esc(e.message), "bad"); }
  }
  $("ost-form").onsubmit = (ev) => { ev.preventDefault(); open($("ost-owner").value); };
  $("ost-month").onchange = () => { if (loaded) render().catch((e) => say(esc(e.message), "bad")); };
  return open;
}
