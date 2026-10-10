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
  <p class="fine"><a href="${escHtml(r.url)}/checks" rel="noopener">Open its checks on GitHub</a></p>`;
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
    const ref = parsePr(text), mine = ++run;
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
      el.dispatchEvent(new CustomEvent("knos:check", { bubbles: true, detail: r }));
      // shared only while the address is still a check's: a reader who has left #check is not sent back to it
      import("./share.js").then((m) => { if (mine === run && el.contains(form) && /^#check=/.test(globalThis.location?.hash || "")) m.renderShare(el.querySelector("#check-share"), { verdict: r }); }).catch(() => {});
      return r;
    } catch (e) {
      if (mine !== run) return null;
      for (const [id, s] of Object.entries({ read: "bad", checks: "idle", verdict: "idle" })) step(id, s);
      const at = e instanceof RateLimited ? e.reset.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "";
      out.innerHTML = e instanceof RateLimited
        ? `<p class="status bad" id="check-limit">Wait until ${escHtml(at)}: GitHub answers 60 reads an hour per address.</p>`
        : `<p class="status bad" id="check-error">${escHtml(e.name === "AbortError" ? `GitHub did not answer in ${LIMIT_S} seconds. Try again.` : e.message)}</p>`;
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
