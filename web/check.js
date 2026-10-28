// #check: paste a public GitHub pull request, get the Agent PR Index's answer about it in seconds. Everything is read
// in this browser from GitHub's public REST API, with no login: the description (pulls/N), then the check runs and the
// commit statuses at its head commit (and its check suites when neither exists). The rules are the index's own
// (web/check_rules.js, a port of scripts/agent_pr_ci.py held equal to it by tests/test_check_rules.py).
//
// GitHub answers 60 requests an hour to an address with no login (docs.github.com/en/rest/using-the-rest-api/
// rate-limits-for-the-rest-api); one check costs three, so about twenty an hour. When GitHub refuses for that limit the
// page says so and when it resets. Nothing is posted anywhere, and nothing is sent to anyone but api.github.com.
//
// renderCheck(el, ctx): fills el once; ctx.arg is what followed "#check=" (owner/repo/123), checked at once. A later
// #check=… in the address is checked too. Each answer is announced on el as the event "knos:check" (detail: the
// result of readPr), and web/share.js draws its share row under it, in #check-share (emptied at every new run).

import { findClaim, verdict, failedNames, byClass, sentence, parsePr } from "./check_rules.js";

const API = "https://api.github.com";
const LIMIT_S = 10;                     // the promise: an answer, or a reason, inside ten seconds
const escHtml = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

export class RateLimited extends Error {
  constructor(reset) { super("rate limited"); this.reset = reset; }
}
// one reset time, said the same way everywhere: hours and minutes in UTC
export const utc = (d) => `${String(d.getUTCHours()).padStart(2, "0")}:${String(d.getUTCMinutes()).padStart(2, "0")} UTC`;

async function gh(path, signal) {
  const r = await fetch(API + path, { headers: { Accept: "application/vnd.github+json" }, signal });
  // GitHub names its limit in headers it lets a page read (access-control-expose-headers), and in the message
  const limited = r.status === 429 || (r.status === 403 && (r.headers.get("x-ratelimit-remaining") === "0" || r.headers.get("retry-after") ||
    /rate limit/i.test((await r.clone().json().catch(() => ({}))).message || "")));
  if (limited) {
    const reset = Number(r.headers.get("x-ratelimit-reset")) * 1000 || Date.now() + Number(r.headers.get("retry-after") || 60) * 1000;
    throw new RateLimited(new Date(reset));
  }
  if (r.status === 404) throw new Error("GitHub has no such public pull request.");
  if (!r.ok) throw new Error(`GitHub answered ${r.status}. Try again.`);
  return r.json();
}

const kept = new Map();
/** What the index would say of one pull request: { ref, url, title, sha, claim, cls, failed, split, line, merged, merged_at }. */
export async function readPr(ref, signal) {
  const key = `${ref.owner}/${ref.repo}/${ref.number}`.toLowerCase();
  if (kept.has(key)) return kept.get(key);
  const base = `/repos/${encodeURIComponent(ref.owner)}/${encodeURIComponent(ref.repo)}`;
  const pr = await gh(`${base}/pulls/${ref.number}`, signal), sha = pr.head?.sha;
  const runs = [];
  const page = async (n) => { const got = (await gh(`${base}/commits/${sha}/check-runs?per_page=100&page=${n}`, signal)).check_runs || []; runs.push(...got); return got.length; };
  const [first, st] = await Promise.all([page(1), gh(`${base}/commits/${sha}/status`, signal)]);
  for (let n = 2, got = first; got >= 100 && n <= 5; n++) got = await page(n);
  const statuses = st.statuses || [];
  const suites = !runs.length && !statuses.length ? (await gh(`${base}/commits/${sha}/check-suites?per_page=100`, signal)).check_suites || [] : [];
  const v = verdict(runs, statuses, suites), claim = findClaim(pr.body);
  const all = failedNames(runs, statuses);   // every one: the index keeps ten
  const split = byClass(all);
  const out = { ref, url: pr.html_url || `https://github.com/${ref.owner}/${ref.repo}/pull/${ref.number}`, title: pr.title || "",
    sha, claim, cls: v.class, failed: all, split, line: sentence(claim, v.class, split), merged: !!pr.merged_at, merged_at: pr.merged_at };
  if (v.class !== "pending") kept.set(key, out);
  return out;
}

// the newest payout Knos released to an agent (the app's GET /api/agent/payout/latest, which names the work it paid for):
// shown under a passed check when that work is this pull request; the request names no pull request
const norm = (u) => String(u || "").toLowerCase().split(/[?#]/)[0].replace(/\/+$/, "");
async function paidFor(url) {
  try {
    const x = await (await fetch("https://knos.onrender.com/api/agent/payout/latest", { cache: "no-store" })).json();
    return x && x.found && norm(x.result) === norm(url) && /^https:\/\/explorer\.solana\.com\/tx\//.test(x.explorer) ? x : null;
  } catch { return null; }
}

const STEPS = [["read", "Description"], ["checks", "Checks at the head commit"], ["verdict", "Verdict"]];

function answerHtml(r) {
  const tone = r.cls === "failed" && r.claim ? "bad" : r.cls === "passed" ? "ok" : "";
  const row = (name, kind) => `<tr><td>${escHtml(name)}</td><td>${kind}</td></tr>`;
  const table = r.failed.length ? `<div class="k-table"><table id="check-failed"><thead><tr><th scope="col">Failed check</th><th scope="col">Class</th></tr></thead><tbody>
    ${r.split.test.map((n) => row(n, "test, build, lint or type")).join("")}${r.split.other.map((n) => row(n, "other")).join("")}</tbody></table></div>` : "";
  return `<p class="verdict ${tone}" id="check-verdict" data-verdict="${escHtml(r.cls)}">${escHtml(r.line)}</p>
  <dl class="check-facts" data-not-prose style="display:grid;grid-template-columns:minmax(0,max-content) minmax(0,1fr);gap:4px 16px;margin:12px 0">
    <dt>Claimed tests pass</dt><dd style="margin:0" id="check-claimed">${r.claim ? `Yes: <q id="check-quote">${escHtml(r.claim.line)}</q>` : "No"}</dd>
    <dt>Failed: test, build, lint or type</dt><dd style="margin:0" class="k-num" id="check-test">${r.split.test.length}</dd>
    <dt>Failed: other checks</dt><dd style="margin:0" class="k-num" id="check-other">${r.split.other.length}</dd>
  </dl>${table}
  <p class="verdict ${r.cls === "passed" ? "ok" : "bad"}" id="check-money">${r.cls === "passed" ? "Money: releases. GitHub's record matches the claim." : "Money: stays locked. GitHub's record does not show every check passing."}</p>
  <p class="fine"><a href="${escHtml(r.url)}/checks" rel="noopener">Open its checks on GitHub</a></p>`;
}

// the sample: two pull requests of drexthealpha/knos-e2e on one bounty, one Knos paid and one it refused. Each is
// checked as any pull request is; Knos's own comment on it says what it decided, and a paid one names its devnet
// transaction, whose log line is read from devnet itself
export const SAMPLE = [{ owner: "drexthealpha", repo: "knos-e2e", number: 266 }, { owner: "drexthealpha", repo: "knos-e2e", number: 265 }];
const DEVNET = "https://api.devnet.solana.com";
export async function knosSaid(ref, o = { log: true }) {
  const comments = await gh(`/repos/${ref.owner}/${ref.repo}/issues/${ref.number}/comments?per_page=50`).catch(() => []);
  const c = comments.find((x) => /^(<!-- knos-review -->\s*)?Knos: /.test(x.body || ""));
  if (!c) return null;
  const line = c.body.replace(/^<!-- knos-review -->\s*/, "").split("\n")[0].replace(/\[(transaction)\]\([^)]*\)/g, "$1").slice(0, 200);
  const sig = (/explorer\.solana\.com\/tx\/([1-9A-HJ-NP-Za-km-z]{64,90})/.exec(c.body) || [])[1] || null;
  return { line, sig, log: sig && o.log ? await devnetLog(sig, ref.number) : null };
}
// the payment's log line, read from devnet itself: "...:paid ... pr=<number>" in a transaction that succeeded
async function devnetLog(sig, number) {
  const r = await fetch(DEVNET, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ jsonrpc: "2.0", id: 1,
    method: "getTransaction", params: [sig, { encoding: "json", maxSupportedTransactionVersion: 1, commitment: "confirmed" }] }) }).then((x) => x.json()).catch(() => ({}));
  const meta = (r.result || {}).meta || {};
  return meta.err === null ? (meta.logMessages || []).find((l) => new RegExp(`:paid .*\\bpr=${number}\\b`).test(l)) || null : null;
}
// the sample as GitHub showed it, recorded with the site (scripts/check_sample_record.mjs): the page needs GitHub for neither
let recording = null;
export const recorded = () => recording ||= fetch(new URL("./check_sample.json", import.meta.url)).then((r) => r.json()).catch(() => null);
const day = (t) => String(t || "").slice(0, 10);

export async function renderSample(el) {
  el.innerHTML = `<p class="k-fine" role="status">Checking 2 pull requests of drexthealpha/knos-e2e.</p>`;
  const rec = await recorded();
  if (!rec) { el.innerHTML = `<p class="status bad">The recorded sample did not load. Try again.</p>`; return; }
  // drawn at once from the recording; each payment's log line then comes from devnet
  el.innerHTML = `<p class="k-fine" data-recorded="${escHtml(rec.recorded)}">Recorded ${escHtml(day(rec.recorded))} from GitHub.</p>` + SAMPLE.map((ref) => {
    const r = rec.prs[String(ref.number)], said = r && r.said;
    if (!r) return "";
    return `<section class="k-card check-sample" data-sample="${ref.number}"><h3><a href="${escHtml(r.url)}" rel="noopener">${escHtml(`${ref.repo} #${ref.number}`)}</a>: ${escHtml(r.title)}</h3>
  <p class="verdict ${r.cls === "passed" ? "ok" : r.cls === "failed" ? "bad" : ""}" data-verdict="${escHtml(r.cls)}">${escHtml(r.line)}</p>
  ${said ? `<p data-knos>${escHtml(said.line)}</p>` : ""}
  ${said && said.sig ? `<p class="k-fine" data-tx="${escHtml(said.sig)}"><a href="https://explorer.solana.com/tx/${escHtml(said.sig)}?cluster=devnet" target="_blank" rel="noopener">The devnet transaction</a> · <code data-log>reading devnet…</code></p>` : ""}</section>`;
  }).join("");
  for (const ref of SAMPLE) {
    const said = (rec.prs[String(ref.number)] || {}).said, box = said && said.sig && el.querySelector(`[data-sample="${ref.number}"] [data-log]`);
    if (box) devnetLog(said.sig, ref.number).then((log) => { box.textContent = log ? log.replace(/^Program log: /, "") : "devnet did not answer"; });
  }
}

export function renderCheck(el, ctx = {}) {
  el.innerHTML = `<h2>Check an agent's pull request</h2>
  <p class="lede">Paste a public GitHub pull request link.</p>
  <form id="check-form" class="k-card check-form" novalidate>
    <label for="check-url">Pull request</label>
    <input id="check-url" name="check-url" type="text" inputmode="url" autocomplete="off" spellcheck="false"
      placeholder="github.com/owner/repo/pull/123" style="width:100%;max-width:100%;box-sizing:border-box">
    <p class="actions"><button type="submit" class="k-btn" id="check-run">Check</button></p>
  </form>
  <ol class="k-states" id="check-steps" hidden>${STEPS.map(([id, words]) => `<li class="k-step" data-step="${id}" data-state="idle">${words}</li>`).join("")}</ol>
  <div id="check-result" role="status" aria-live="polite"></div>
  <div id="check-share"></div>`;
  const form = el.querySelector("#check-form"), box = el.querySelector("#check-url"), out = el.querySelector("#check-result"), shared = el.querySelector("#check-share");
  const steps = el.querySelector("#check-steps"), step = (id, state) => { const s = steps.querySelector(`[data-step="${id}"]`); if (s) s.dataset.state = state; };
  let run = 0;

  async function check(text) {
    const ref = parsePr(text), mine = ++run, began = globalThis.location?.hash || "";
    shared.innerHTML = "";                  // the last answer's share row goes with it, whatever this run finds
    if (!ref) { out.innerHTML = `<p class="status bad" id="check-error">Paste a link like github.com/owner/repo/pull/123.</p>`; return null; }
    box.value = `https://github.com/${ref.owner}/${ref.repo}/pull/${ref.number}`;
    // the pending state, in this same task: the three steps, the first one live
    steps.hidden = false;
    for (const [id] of STEPS) step(id, "idle");
    step("read", "live");
    out.setAttribute("aria-busy", "true");
    out.innerHTML = `<div class="k-skeleton" data-pending><span class="k-sr">Reading GitHub</span><i></i><i></i></div>`;
    const stop = new AbortController(), late = setTimeout(() => stop.abort(), LIMIT_S * 1000 - 500);
    try {
      const r = await readPr(ref, stop.signal);
      if (mine !== run) return null;
      step("read", "done"); step("checks", r.cls === "failed" ? "bad" : "done"); step("verdict", r.cls === "failed" && r.claim ? "bad" : "done");
      out.innerHTML = answerHtml(r);
      if (r.cls === "passed") paidFor(r.url).then((x) => { if (x && mine === run && el.contains(out)) out.insertAdjacentHTML("beforeend",
        `<p class="fine" id="check-tx">Paid on devnet for this pull request · <a href="${escHtml(x.explorer)}" target="_blank" rel="noopener">${escHtml(x.released || "the transaction")}</a></p>`); });
      el.dispatchEvent(new CustomEvent("knos:check", { bubbles: true, detail: r }));
      // shared only while the address is still a check's and still the one this run began at: a reader who has left
      // #check, or followed another #check= link whose hashchange (a later task) has not reached the page yet, is not
      // sent back to this answer (the share row rewrites the address)
      import("./share.js").then((m) => {
        const now = globalThis.location?.hash || "";
        if (mine === run && el.contains(form) && /^#check=/.test(now) && now === began) m.renderShare(el.querySelector("#check-share"), { verdict: r });
      }).catch(() => {});
      return r;
    } catch (e) {
      if (mine !== run) return null;
      for (const [id, s] of Object.entries({ read: "bad", checks: "idle", verdict: "idle" })) step(id, s);
      const refused = e instanceof RateLimited || e instanceof TypeError;         // GitHub's limit, or no answer from it at all
      out.innerHTML = e instanceof RateLimited
        ? `<p class="status bad" id="check-limit">GitHub's limit for this address resets at ${escHtml(utc(e.reset))}: it answers 60 reads an hour per address.</p>`
        : `<p class="status bad" id="check-error">${escHtml(e.name === "AbortError" ? `GitHub did not answer in ${LIMIT_S} seconds. Try again.` : e instanceof TypeError ? "GitHub did not answer from this browser." : e.message)}</p>`;
      if (refused) {                // the recorded path, labelled: this pull request's recording, else the sample's
        const rec = await recorded(), mineRec = rec && rec.prs[String(ref.number)];
        if (mine !== run) return null;
        if (mineRec && ref.owner === "drexthealpha" && ref.repo === "knos-e2e") {
          out.insertAdjacentHTML("beforeend", `<p class="k-fine" id="check-recorded">Recorded ${escHtml(day(rec.recorded))} from GitHub:</p>` + answerHtml(mineRec));
        } else if (rec) {
          out.insertAdjacentHTML("beforeend", `<p class="k-fine" id="check-recorded">Meanwhile, a recorded check of two pull requests Knos judged:</p><div id="check-recorded-sample"></div>`);
          renderSample(out.querySelector("#check-recorded-sample"));
        }
      }
      return null;
    } finally {
      clearTimeout(late);
      if (mine === run) out.removeAttribute("aria-busy");
    }
  }

  form.addEventListener("submit", (ev) => { ev.preventDefault(); check(box.value); });
  // a pasted link is checked at once: paste, then nothing else to press
  box.addEventListener("paste", (ev) => { const t = ev.clipboardData?.getData("text"); if (parsePr(t)) { ev.preventDefault(); check(t); } });
  const fromHash = () => { const m = /^#check=(.+)$/.exec(globalThis.location?.hash || ""); return m ? decodeURIComponent(m[1]) : ""; };
  globalThis.addEventListener?.("hashchange", () => { const a = fromHash(); if (el.contains(form) && a && parsePr(a)) check(a); });      // until the page empties el
  el.check = check;
  if (ctx.arg && parsePr(ctx.arg)) check(ctx.arg);
  return el;
}
