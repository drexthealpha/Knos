// The front door: the ten-second check first. One pull request pasted alone (a link, or owner/repo#123) goes to the
// check of that one pull request, web/check.js at #check=owner/repo/123 (checkHref): a pasted link is checked as it
// lands, so landing, paste and post are three presses at most (tests/web/front_door.mjs counts them). Anything else the
// box takes as before: a supplier's invoice (CSV, or lines of pull request links) or the name of a public repository,
// and the answer is drawn in place: the supplier's count beside
// the neutral count, then every line in one of four groups, each line with its four steps (policy satisfied, parties
// accepted, payment authorised, settled: web/line_steps.js). A line whose checks passed is "policy met", never
// "agreed": nobody accepted or authorised it until someone does, here or in the statement. Left unauthorised more than
// ACCEPT_DAYS after the statement's day, it is owed to the supplier, with the supplier's appeal one click away.
// No install, no login, nothing sent to Knos.
//
//   renderFrontDoor(el[, env])    the control in `el` (index.html: <form id="front-door">) and its result
//   prOf(text), checkHref(pr)     one pull request and nothing else in the box, and the hash of its check
//   LINE_STATES, LINE_WORDS       src/knos/ids.py's, mirrored (tests/web/front_door.mjs holds the two together)
//   stateOf(row)                  which of the four a statement line of web/shadow.js is
//   answers(row, pull)            the seven things an approver asks of one line, each in a few words
//   invoiceLineId(supplier, invoice, line)   ids.invoice_line, byte for byte
//
// What reads GitHub and what judges a line is web/shadow.js, unchanged: this file only groups and draws. The sample is
// web/front_door_sample.js (a made-up invoice with its recorded answers), so it works with no network.
import { parse, pullOf, gather, statement, recorded, githubReader, Unread, ANONYMOUS_AN_HOUR, LINE_COSTS } from "./shadow.js";
import { SAMPLE_INVOICE, SAMPLE_BOOK, SAMPLE_META } from "./front_door_sample.js";
import { stepRowHtml, shadowSteps, markSteps, stepStyle } from "./line_steps.js";
// web/install.js is the Install page's code (its workflow file and the terms templates, 15 KB). The box needs it only
// to make a checked invoice's Install link, so it is asked for then, never with the first screen (tests/web/perf.mjs:
// the first screen's weight, and the files it must not ask for).
const install = () => import("./install.js");
// owner/repo or owner/repo@branch, read as web/install.js's parseRepo reads it (that file imports nothing, so it keeps
// its own copy; tests/web/front_door.mjs holds the two to one answer). Read here, at once: a press is answered in the
// same task, its pending state first.
const REPO = /^(?:https:\/\/github\.com\/)?([A-Za-z0-9](?:-?[A-Za-z0-9]){0,38})\/([A-Za-z0-9._-]{1,100}?)(?:\.git)?\/?(?:@([A-Za-z0-9._\/-]{1,200}))?$/;
export function repoOf(text) {
  const m = REPO.exec(String(text || "").trim());
  return m && m[2] !== "." && m[2] !== ".." ? { owner: m[1], repo: m[2], branch: m[3] || "main" } : null;
}

export const LINE_STATES = ["agreed", "disputed", "duplicate", "insufficient_evidence"];
export const LINE_WORDS = { agreed: "policy met", disputed: "disputed", duplicate: "duplicate", insufficient_evidence: "insufficient evidence" };
export const ACCEPT_DAYS = 30;            // knos.statement.ACCEPT_DAYS: the acceptance window when none is given
export const APPEAL = "https://github.com/drexthealpha/Knos/blob/main/docs/reference/DISPUTES.md#the-path";
const daysBetween = (a, b) => Math.round((Date.parse(`${b}T00:00:00Z`) - Date.parse(`${a}T00:00:00Z`)) / 86400000);
/** Is a line owed to the supplier on `today`: its policy met, nobody authorised it, and the window after `since` has passed? */
export const isOwed = (row, since, today, decided = null) => row.class === "clean" && !decided && Boolean(since) && daysBetween(since, today) > ACCEPT_DAYS;
const STATE_OF = { clean: "agreed", failed: "disputed", not_merged: "disputed", duplicate: "duplicate", unverified: "insufficient_evidence", unreadable: "insufficient_evidence" };
export const stateOf = (row) => STATE_OF[row.class] || "insufficient_evidence";

// The seven columns, in the order an approver asks: what did we authorize, what was delivered, which requirements
// passed, was it billed before, who approved it, what is owed, and what explains the decision later.
export const COLUMNS = [["authorized", "Authorized"], ["delivered", "Delivered"], ["passed", "Passed"], ["billed_before", "Billed before"],
  ["approved_by", "Approved by"], ["owed", "Owed"], ["evidence", "Evidence"]];
export const REPO_LINES = 10;              // a named repository: its latest merged pull requests, this many at most
const API = "https://api.github.com";
export const FEEDBACK = "https://github.com/drexthealpha/Knos/issues/new?labels=shadow-feedback&title=" + encodeURIComponent("What the check missed")
  + "&body=" + encodeURIComponent("1. What was wrong in the result?\n\n\n2. Would you use this on a real invoice?\n\n\n3. What would you pay for it?\n\n");

const hex = (buf) => [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("");
const sha256 = async (bytes) => hex(await globalThis.crypto.subtle.digest("SHA-256", bytes));
/** ids.invoice_line(supplier, invoice, line): "inv_" and 24 hex characters of a SHA-256 over the tagged parts. */
export async function invoiceLineId(supplier, invoice, line) {
  const enc = new TextEncoder(), parts = [enc.encode("knos.id.v1\0invoice_line\0")];
  for (const p of [supplier, invoice, line]) { const b = enc.encode(String(p)), n = new Uint8Array(4); new DataView(n.buffer).setUint32(0, b.length); parts.push(n, b); }
  const all = new Uint8Array(parts.reduce((a, p) => a + p.length, 0));
  parts.reduce((at, p) => { all.set(p, at); return at + p.length; }, 0);
  return `inv_${(await sha256(all)).slice(0, 24)}`;
}

/** What the box holds: { repo: { owner, repo, branch } } for one repository's name, else { invoice } (throws as parse does). */
export function reading(text) {
  const t = String(text || "").trim();
  if (!/[\n,;\t]/.test(t) && !pullOf(t)) { const at = repoOf(t); if (at) return { repo: at }; }
  return { invoice: parse(text) };
}

/** One pull request and nothing else in the box: { owner, repo, number }; null for anything else (an invoice, a name). */
export function prOf(text) {
  const t = String(text || "").trim(), p = /[\n,;\t]/.test(t) ? null : pullOf(t);
  if (!p) return null;
  const [owner, repo] = p.repo.split("/");
  return { owner, repo, number: p.number };
}
/** Where one pull request is checked: the #check view (web/check.js), which reads the pull request from its hash. */
export const checkHref = (pr) => `#check=${pr.owner}/${pr.repo}/${pr.number}`;

/** A named repository as an invoice: its latest merged pull requests, one line each, no amounts. `known`: each pull
 *  request as the listing gave it, so that it is not asked for again. */
export async function repoInvoice(at, get) {
  const repo = `${at.owner}/${at.repo}`, got = await get(`repos/${repo}/pulls?state=closed&sort=updated&direction=desc&per_page=50`);
  const merged = (Array.isArray(got) ? got : []).filter((p) => p && p.merged_at && Number.isInteger(p.number)).slice(0, REPO_LINES);
  return { invoice: { lines: merged.map((p, i) => ({ line: i + 1, pr: `${repo}#${p.number}`, repo, number: p.number, amount: null, supplier: "" })) },
    known: new Map(merged.map((p) => [`repos/${repo}/pulls/${p.number}`, p])) };
}

/** The seven answers for one line: { key: { text, href } }. `pull`: GitHub's own record of it, when it was read.
 *  `owed`: the line is owed to the supplier (isOwed); `decided`: { by, on } when it was accepted and authorised here. */
export function answers(row, pull = null, owed = false, decided = null) {
  const state = stateOf(row), home = row.pr.split("#")[0], by = pull && pull.merged_by && pull.merged_by.login, same = row.class === "duplicate" && row.merged === null;
  const unread = row.class === "unreadable" ? "not read" : same ? `see line ${row.duplicate_of}` : "";
  const passed = row.checks.filter((c) => c.state === "passed").length;
  const issue = row.issues[0], num = issue ? issue.split("#")[1] : "";
  return {
    authorized: unread ? { text: unread } : issue ? { text: `issue #${num}${row.issues.length > 1 ? ` and ${row.issues.length - 1} more` : ""}`, href: `https://github.com/${issue.split("#")[0]}/issues/${num}` } : { text: "no issue named" },
    delivered: unread ? { text: unread } : row.merged ? { text: `merged ${row.merged_at.slice(0, 10)}${by ? ` by ${by}` : ""}`, href: row.merge_commit ? `https://github.com/${home}/commit/${row.merge_commit}` : "" } : { text: "not merged" },
    passed: unread ? { text: unread } : !row.merged ? { text: "nothing ran" } : row.failed.length ? { text: `failed: ${row.failed.map((f) => f.name).join(", ")}`, href: row.failed[0].url }
      : row.checks.length ? { text: `${passed} of ${row.checks.length} checks` } : { text: "no check ran" },
    billed_before: { text: row.duplicate_of ? `yes, line ${row.duplicate_of}` : "no" },
    approved_by: { text: decided && state === "agreed" ? `${decided.by}, ${decided.on}` : "nobody yet" },
    owed: { text: state === "agreed" ? `${row.amount ?? "1 change"}${decided ? ", authorised" : owed ? ", to the supplier" : " once authorised"}` : state === "disputed" ? "nothing: disputed" : state === "duplicate" ? "nothing: billed twice" : "undecided" },
    evidence: row.url ? { text: "pull request", href: row.url } : { text: "none" },
  };
}
const WHY = { failed: "A check failed at merge.", not_merged: "Never merged.", unverified: "Checks gave no verdict.", unreadable: "GitHub gave no answer." };
const whyOf = (row) => (row.class === "duplicate" ? `${row.why[0].toUpperCase()}${row.why.slice(1)}.` : row.why === "not found or private" ? "Not found, or private."
  : row.why === "rate limit" ? "GitHub's hourly limit reached." : row.why === "no pull request named" ? "No pull request named." : WHY[row.class] || "");

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const link = (href, text) => (/^https:\/\/github\.com\//.test(href || "") ? `<a href="${esc(href)}" target="_blank" rel="noopener">${esc(text)}</a>` : esc(text));
const cap = (s) => s[0].toUpperCase() + s.slice(1);
const STYLE = `.fd textarea{min-height:64px;font-size:15px;resize:vertical}.fd .actions{align-items:center;margin:12px 0 0}.fd-result{grid-column:1/-1;order:2;min-width:0;margin:24px 0 8px;scroll-margin-top:80px}
.fd-counts{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;margin:0 0 16px}.fd-counts>div{border:1px solid var(--line);border-radius:var(--radius,12px);padding:12px 14px;background:var(--paper-2);min-width:0}
.fd-counts .k-kicker{margin:0}.fd-big{display:block;font-size:clamp(40px,11vw,80px);line-height:1;font-weight:700}.fd-counts span{overflow-wrap:anywhere}
.fd-counts [data-fd=ours]{color:var(--ok)}.fd-pending,.fd-group ol{list-style:none;padding:0;margin:0}.fd-pending li{padding:4px 0;color:var(--ink-2);overflow-wrap:anywhere}
.fd-groups{display:grid;gap:12px}.fd-group{border-left:3px solid var(--line);padding:2px 0 2px 12px;min-width:0}.fd-group h3{margin:0 0 4px;display:flex;gap:8px;align-items:baseline}
.fd-group[data-group=agreed]{border-color:var(--ok)}.fd-group[data-group=disputed],.fd-group[data-group=duplicate]{border-color:var(--bad)}
.fd-group[data-empty]{opacity:.55}.fd-line{padding:10px 0;border-top:1px solid var(--line);overflow-wrap:anywhere}.fd-line p{margin:0 0 6px}.fd-line .fd-why{color:var(--ink-2)}
.fd-line dl{display:grid;grid-template-columns:repeat(auto-fit,minmax(118px,1fr));gap:6px 12px;margin:0}.fd-line dt{font-size:12px;color:var(--ink-2)}.fd-line dd{margin:0}
.fd-line[data-approved]{background:color-mix(in srgb,var(--ok) 9%,transparent);transition:background var(--dur-2) var(--ease)}
.fd-line[data-owed]{border-left:3px solid var(--accent);padding-left:9px}.fd-owed{margin:6px 0 0;font-weight:600}
.hero:has(>#front-result:not([hidden])) .hero-board{display:none}
.fd-under{display:flex;flex-wrap:wrap;gap:12px 16px;align-items:center;margin:16px 0 8px}.fd-result [hidden]{display:none}`;

/** Draw the front door. `el`: the form (or an empty element, which is given one). env, all optional: { out } where the
 *  result goes, { fetch } to read GitHub with, { get } a reader instead of GitHub, { now } a Date for the approval,
 *  { elsewhere(text, out) } what the page answers itself (true when it did: a transaction, a repository's record). */
export function renderFrontDoor(el, env = {}) {
  const doc = el.ownerDocument, fetchFn = env.fetch || ((...a) => globalThis.fetch(...a));
  if (!doc.getElementById("fd-style")) { const s = doc.createElement("style"); s.id = "fd-style"; s.textContent = STYLE; doc.head.appendChild(s); }
  stepStyle(doc);
  if (!el.querySelector("textarea")) {
    el.classList.add("fd");
    el.innerHTML = `<textarea id="fd-in" rows="2" spellcheck="false" autocomplete="off" aria-label="An agent's pull request link, an invoice, or a repository name (owner/repo)" placeholder="Paste an agent's pull request"></textarea>
      <p class="actions"><button type="submit" class="k-btn" data-fd="run">Check</button> <button type="button" class="k-btn quiet" data-fd="sample">Try a sample invoice</button></p>`;
  }
  let out = env.out || doc.getElementById("front-result");
  if (!out) { out = doc.createElement("div"); out.id = "front-result"; el.after(out); }
  out.classList.add("fd-result");
  const box = el.querySelector("textarea"), $ = (name) => out.querySelector(`[data-fd="${name}"]`);
  const budget = { remaining: null, limit: ANONYMOUS_AN_HOUR, reset: null, asked: 0, spent: false };
  let busy = false, last = null, motion = null, checking = null, again = false, meter = null;
  import("./motion.js").then((m) => { motion = m; }).catch(() => { /* the page is whole without it */ });

  const frame = (said, theirs) => {
    out.hidden = false; delete out.dataset.done;
    out.innerHTML = `<p data-fd="mark" class="fine" hidden>Sample: a made-up invoice from a made-up supplier.</p>
      <p data-fd="said" role="status" aria-live="polite">${esc(said)}</p>
      <div class="fd-counts" data-fd="counts" hidden><div><p class="k-kicker" data-fd="theirs-name">${esc(theirs)}</p><span class="k-num fd-big" data-fd="theirs">0</span><span data-fd="theirs-sum"></span></div>
        <div><p class="k-kicker">Count both sides agree on</p><span class="k-num fd-big" data-fd="ours">0</span><span data-fd="ours-sum">lines whose checks passed so far</span></div></div>
      <ol class="fd-pending" data-fd="pending"></ol>
      <div class="fd-groups" data-fd="groups" hidden>${LINE_STATES.map((s) => `<section class="fd-group" data-group="${s}" data-empty><h3><span>${esc(cap(LINE_WORDS[s]))}</span> <span class="k-num" data-count>0</span></h3><ol></ol></section>`).join("")}</div>
      <div data-fd="after" hidden>
        <p class="fd-under"><button type="button" class="k-btn" data-fd="approve">Accept and authorise</button>
          <button type="button" class="k-btn quiet" data-fd="csv">Download CSV</button>
          <a data-fd="statement" href="#invoice-statement">Open the statement</a></p>
        <p data-fd="approved" role="status" aria-live="polite"></p>
        <p class="fd-under"><a data-fd="install" href="#install">Install the meter</a> <a data-fd="feedback" href="${esc(FEEDBACK)}" target="_blank" rel="noopener">Tell us what it missed</a></p>
        <div data-fd="terms" hidden></div>
        <p class="fine">A failed check is not proof of bad work.</p>
        <p class="fine">Nothing left this page but pull request names.</p>
      </div>`;
    const cue = doc.getElementById("hero-cue"); if (cue) cue.hidden = true;
    // the answer is brought into the window, so the lines are seen as they sort (a reader who asked for no movement gets it at once)
    out.scrollIntoView?.({ block: "nearest", behavior: motion && !motion.prefersReduced() ? "smooth" : "auto" });
  };
  const lineHtml = (row, pull, owed = false) => {
    const a = answers(row, pull, owed), why = whyOf(row);
    return `<p><span class="k-num">Line ${row.line}</span> · ${row.url ? link(row.url, row.pr) : esc(row.pr || "no pull request")}${row.amount ? ` · <span class="k-num">${esc(row.amount)}</span>` : ""}</p>
      ${why ? `<p class="fd-why">${esc(why)}</p>` : ""}
      ${stepRowHtml(shadowSteps(row))}
      <dl>${COLUMNS.map(([key, name]) => `<div><dt>${esc(name)}</dt><dd data-col="${key}">${link(a[key].href, a[key].text)}</dd></div>`).join("")}</dl>
      ${owed ? owedHtml() : ""}`;
  };
  const owedHtml = () => `<p class="fd-owed" data-fd-owed>Owed to the supplier: checks passed, nobody approved it in ${ACCEPT_DAYS} days. <a href="${APPEAL}" target="_blank" rel="noopener">Supplier: appeal</a></p>`;

  async function run(sample = false, counting = false) {
    const pr = sample ? null : prOf(box.value);      // one pull request: its own check, on its own page (env.go: a test's)
    if (pr) { (env.go || ((to) => { globalThis.location.hash = to; }))(checkHref(pr)); return; }
    // one line that the page around the box answers itself (env.elsewhere, web/front.js): a transaction, or a repository
    // named alone (its record; data-fd="count" then counts its merged pull requests here). Without it, as before.
    const one = box.value.trim();
    if (!sample && !counting && !busy && env.elsewhere && one && !/[\n,;\t]/.test(one) && await env.elsewhere(one, out)) return;
    if (busy) { again = !sample && box.value !== checking; return; }     // asked while a check runs: what the box holds now is checked next, when it is not what is being checked
    checking = sample ? null : box.value; again = false;
    let what;
    try { what = sample ? { invoice: parse(SAMPLE_INVOICE) } : reading(box.value); } catch (e) {
      frame(/^line \d+/.test(e.message) ? `Not read: ${e.message}.` : "Not read: paste pull request links, or type owner/repo.", ""); return;
    }
    busy = true; last = null; meter = null; budget.spent = false;
    const repo = what.repo ? `${what.repo.owner}/${what.repo.repo}` : "";
    frame(repo ? `Reading ${repo}.` : `Checking ${what.invoice.lines.length} ${what.invoice.lines.length === 1 ? "line" : "lines"}.`, repo ? "Merged there" : "Supplier's count");      // the pending state, before anything is asked
    $("mark").hidden = !sample;
    const finish = (said) => { busy = false; $("said").textContent = said; if (again && box.value !== checking) setTimeout(run, 0); again = false; };
    let get = env.get || (sample ? recorded(SAMPLE_BOOK) : null), invoice = what.invoice;
    if (!get) {
      try {
        const rate = await fetchFn(`${API}/rate_limit`, { headers: { Accept: "application/vnd.github+json" } });      // asking for the budget does not spend it
        const core = rate.ok ? ((await rate.json()).resources || {}).core : null;
        if (core && Number.isInteger(core.remaining)) Object.assign(budget, { remaining: core.remaining, limit: core.limit ?? budget.limit, reset: core.reset ?? null });
      } catch { /* unknown: GitHub's own headers say it with the first answer */ }
      get = githubReader(fetchFn, budget);
    }
    if (what.repo) {
      let listed;
      try { listed = await repoInvoice(what.repo, get); } catch (e) {
        const why = e instanceof Unread ? e.reason : "no answer";
        return finish(why === "rate limit" ? "GitHub's hourly limit reached. Try again in an hour." : why === "not found or private" ? "Not read: that repository is private, or not there." : "GitHub gave no answer. Try again.");
      }
      if (!listed.invoice.lines.length) return finish("No merged pull request found there.");
      invoice = listed.invoice;
      const reader = get;
      get = async (path) => {
        if (!listed.known.has(path)) return reader(path);
        if (budget.spent || (budget.remaining !== null && budget.remaining < LINE_COSTS - 1)) { budget.spent = true; throw new Unread("rate limit"); }
        return listed.known.get(path);
      };
      $("said").textContent = `Checking ${invoice.lines.length} merged pull requests.`;
    }
    const priced = invoice.lines.every((ln) => ln.amount !== null), rows = [], pulls = new Map();
    $("counts").hidden = false; $("groups").hidden = false;
    $("theirs-sum").textContent = repo ? "merged pull requests" : "lines billed";
    $("pending").innerHTML = invoice.lines.map((ln) => `<li class="fd-line" data-line="${ln.line}" data-state="pending"><span class="k-num">Line ${ln.line}</span> · ${esc(ln.pr || "no pull request")}</li>`).join("");
    // a figure counts up to its new value (motion.js countTo); with no motion it is simply written
    const count = (el, n) => { if (motion && motion.countTo) motion.countTo(el, n, { digits: 0 }); else el.textContent = String(n); };
    count($("theirs"), invoice.lines.length);
    const tally = () => {
      const agreed = rows.filter((r) => stateOf(r) === "agreed");      // policy met: the checks passed, and nothing more
      count($("ours"), agreed.length);
      for (const s of LINE_STATES) { const g = out.querySelector(`[data-group="${s}"]`), n = rows.filter((r) => stateOf(r) === s).length; count(g.querySelector("[data-count]"), n); g.toggleAttribute("data-empty", n === 0); }
    };
    // each line sorts into its group as its answer arrives: it slides from the list to its place there (motion.js sort)
    let moving = Promise.resolve();
    const place = (row, pull) => {
      moving = moving.then(async () => {
        const li = $("pending").querySelector(`[data-line="${row.line}"]`), group = out.querySelector(`[data-group="${stateOf(row)}"]`);
        if (!li || !group) return;
        li.dataset.class = row.class; rows.push(row); tally();
        if (motion && motion.sort) { const landed = motion.sort(li, group.querySelector("ol"), { state: stateOf(row) }); li.innerHTML = lineHtml(row, pull); await landed; }
        else { li.dataset.state = stateOf(row); li.innerHTML = lineHtml(row, pull); group.querySelector("ol").append(li); }
      });
    };
    // what GitHub said is written down as it is read: the statement is made from the invoice and these answers, and from nothing else
    const book = {}, asked = get;
    get = async (path) => { try { return (book[path] = await asked(path)); } catch (e) { book[path] = { __unread: e instanceof Unread ? e.reason : "no answer" }; throw e; } };
    const facts = await gather(invoice, get, (ln, got, all) => {
      const row = statement({ lines: invoice.lines.slice(0, ln.line) }, all).lines[ln.line - 1];
      pulls.set(ln.line, got && got.pull); place(row, got && got.pull);
    });
    await moving;
    const st = statement(invoice, facts), agreed = st.lines.filter((r) => stateOf(r) === "agreed"), left = st.lines.length - agreed.length;
    if (priced && st.amounts) {
      $("theirs-sum").textContent = `lines, ${st.amounts.billed} billed`;
      $("ours-sum").textContent = `lines whose checks passed, ${st.amounts.clean}`;
    } else $("ours-sum").textContent = agreed.length === 1 ? "line whose checks passed" : "lines whose checks passed";
    // OWED: the statement's day is the last merge (knos.statement.from_shadow); a line whose policy is met and that nobody
    // authorised within the window after it is owed to the supplier, and says so beside the supplier's appeal
    const merged = st.lines.map((r) => r.merged_at).filter(Boolean).map((t) => t.slice(0, 10)).sort(), since = merged[merged.length - 1] || "";
    const today = (env.now || new Date()).toISOString().slice(0, 10), owed = agreed.filter((r) => isOwed(r, since, today));
    for (const r of owed) {
      const li = out.querySelector(`.fd-line[data-line="${r.line}"]`);
      if (!li) continue;
      li.dataset.owed = "1"; li.querySelector('[data-col="owed"]').textContent = answers(r, null, true).owed.text;
      li.insertAdjacentHTML("beforeend", owedHtml());
    }
    const at = repo ? what.repo : sample ? null : (() => {      // an invoice: the repository most of its lines name, on the branch GitHub says is its default
      const seen = {}; for (const ln of invoice.lines) if (ln.repo) seen[ln.repo.toLowerCase()] = [(seen[ln.repo.toLowerCase()] || [0])[0] + 1, ln];
      const top = Object.values(seen).sort((a, b) => b[0] - a[0])[0];
      if (!top) return null;
      const branch = ((((facts.get(top[1].pr.toLowerCase()) || {}).pull || {}).base || {}).repo || {}).default_branch;
      return { ...repoOf(top[1].repo), ...(typeof branch === "string" && /^[\w./-]{1,200}$/.test(branch) ? { branch } : {}) };
    })();
    const inst = at && at.owner ? await install().catch(() => null) : null;      // the Install link's file and its maker
    const href = inst && inst.pinnedFile(inst.INSTALL_WORKFLOW) ? inst.installLink(at) : null;
    if (href) Object.assign($("install"), { href, target: "_blank", rel: "noopener" });
    meter = at && at.owner ? { repo: `${at.owner}/${at.repo}`, branch: at.branch, href } : null;
    $("approve").disabled = agreed.length === 0;
    $("after").hidden = false;
    const text = repo ? `${invoice.lines.map((ln) => ln.pr).join("\n")}\n` : sample ? SAMPLE_INVOICE : box.value;
    last = { st, pulls, approved: "", status: null, made: null, bundle: { invoice: text, answers: book }, meta: sample ? SAMPLE_META : {} };
    made().catch(() => {});                 // the statement itself, made beside the page's own count and handed to the Statement page
    out.dataset.done = "1";
    finish(budget.spent ? "GitHub's hourly limit reached. Unread lines stay insufficient evidence." : `Checked ${st.lines.length} ${st.lines.length === 1 ? "line" : "lines"}. ${left} ${left === 1 ? "exception" : "exceptions"}.`
      + (owed.length ? ` ${owed.length} owed to the supplier.` : ""));
  }

  // THE STATEMENT: what `knos statement make` writes from the same invoice and the same answers (web/statement_make.js,
  // held to tests/data/statement byte for byte): the four ids of every line, one of the four states, its evidence and
  // its hash. Approve and Download work on it, and the Statement page opens the same object.
  const made = () => { const mine = last; return (mine.made ||= import("./statement_make.js").then(async (m) => { const st = await m.fromShadow(mine.bundle, mine.meta); if (last === mine) m.hand(st, mine.status); return st; })); };
  const say = (text, kind) => { if (motion && motion.toast) motion.toast(text, kind); };

  async function approve() {
    if (!last || last.approved) return;
    const mine = last, day = (env.now || new Date()).toISOString().slice(0, 10), lines = [...out.querySelectorAll('.fd-line[data-state="agreed"]')];
    mine.approved = `you, ${day}`;
    const decided = { by: "you", on: day };
    // two steps move, and only those: parties accepted, then payment authorised. Policy met was already so; settled is not.
    for (const li of lines) {
      const row = mine.st.lines.find((r) => String(r.line) === li.dataset.line);
      li.dataset.approved = day; li.removeAttribute("data-owed"); li.querySelector("[data-fd-owed]")?.remove();
      li.querySelector('[data-col="approved_by"]').textContent = mine.approved;
      if (row) { li.querySelector('[data-col="owed"]').textContent = answers(row, null, false, decided).owed.text; markSteps(li, shadowSteps(row, decided)); }
    }
    const left = mine.st.lines.length - lines.length;
    $("approved").textContent = `Accepted and approved: ${lines.length} ${lines.length === 1 ? "line" : "lines"}. Still open: ${left} ${left === 1 ? "exception" : "exceptions"}. Nothing is paid yet.`;
    if (doc.activeElement === $("approve")) $("csv").focus();          // the focus is not left on a button that no longer works
    $("approve").disabled = true;
    say(`Authorised ${lines.length} ${lines.length === 1 ? "line" : "lines"}`);
    // two events beside the statement, as `knos statement accept` and `knos statement approve` record them: who, and the day
    const m = await import("./statement_make.js"), st = await made();
    mine.status = m.approve(st, m.accept(st, mine.status, "you", "approver", day), "you", "approver", day);
    if (last === mine) m.hand(st, mine.status);
  }

  async function download() {
    if (!last) return;
    const mine = last, [{ statementCsv }, st] = await Promise.all([import("./finance_data.js"), made()]);
    const name = `statement-${String(st.invoice).replace(/[^\w.-]+/g, "-")}.csv`;
    const url = URL.createObjectURL(new Blob([await statementCsv(st, mine.status)], { type: "text/csv;charset=utf-8" })), a = doc.createElement("a");
    a.href = url; a.download = name; doc.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000);
    say(`Downloaded ${name}`);
  }

  el.addEventListener("submit", (ev) => { ev.preventDefault(); run(); });
  el.querySelector('[data-fd="sample"]').addEventListener("click", (ev) => { ev.preventDefault(); box.value = SAMPLE_INVOICE; run(true); });
  // Enter in the box checks what is in it, whatever it holds (a pasted invoice has many lines: Enter used to add one more
  // there and check nothing); Shift+Enter is the new line. An Enter that ends an input method's composition is not one.
  box.addEventListener("keydown", (ev) => { if (ev.key === "Enter" && !ev.shiftKey && !ev.isComposing && ev.keyCode !== 229) { ev.preventDefault(); run(); } });
  box.addEventListener("paste", () => setTimeout(() => { if (box.value.includes("\n") || prOf(box.value)) run(); }, 0));      // a pasted invoice, or one pasted pull request, is checked as it lands
  out.addEventListener("click", (ev) => {
    const what = ev.target.closest("[data-fd]")?.dataset.fd;
    // INSTALL THE METER, for a repository that was named: its terms are proposed from its own checks, in place
    // (web/propose_view.js, asked for now), and the workflow file is one link in what is drawn. The sample names no
    // repository of the reader's, so there the link stays a link to the Install page.
    if (what === "install" && meter && !ev.ctrlKey && !ev.metaKey && !ev.shiftKey) {
      ev.preventDefault();
      const mine = meter, box = $("terms");
      import("./propose_view.js").then((m) => m.renderProposal(box, mine.repo, { branch: mine.branch, install: mine.href, propose: env.propose, proposeEnv: env.proposeEnv }))
        .then(() => box.scrollIntoView?.({ block: "nearest", behavior: motion && !motion.prefersReduced() ? "smooth" : "auto" })).catch(() => { box.hidden = false; box.textContent = "Not read. Try again."; });
    }
    if (what === "count") { ev.preventDefault(); run(false, true); }
    if (what === "approve") approve().catch(() => { $("approved").textContent = "Not recorded. Try again."; });
    if (what === "csv") download().catch(() => { $("approved").textContent = "Download failed. Try again."; say("Download failed", "bad"); });
  });
  return { run, statement: () => (last ? made().then((st) => ({ st, status: last.status })) : Promise.resolve(null)) };
}
