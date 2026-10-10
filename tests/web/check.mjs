// node tests/web/check.mjs
// #check (web/check.js) in headless Chromium, served from web/, against GitHub's REST API answered from recorded pull
// requests of docs/agent_pr_ci.json (their claim line as the description; their failed checks, other conclusions and
// counts as the head commit's check runs and statuses; tests/test_check_rules.py rebuilds them the same way). It checks:
//   android    at 360 x 740, the processor slowed 4 times and a slow 4G (as tests/web/android.mjs), a #check=… link gives
//              its first verdict in under 10 s from the navigation's start, each GitHub answer 150 ms late
//   answer     "Claimed tests pass" with the matched line quoted, failed checks by class, the verdict in one line
//   paste      a pasted link is checked with no press at all; a later #check=… in the address is checked too
//   pending    the steps and the grey bars are on the screen in the same task as the press
//   limits     GitHub's refusal for its hourly limit says 60 an hour and when it resets; a missing PR says so
//   words      no statement over twelve words, the title 3 to 6; nothing says wallet, hash, pin or token account
//   width      no sideways scroll from 320 to 1280 px; nobody is asked but the page's host and api.github.com
// No `playwright` package or no browser: says SKIP and exits 0 (tests/web/overflow.mjs, `chromiumOrSkip`).
import { createServer } from "node:http";
import { readFileSync, existsSync } from "node:fs";
import { join, dirname, extname, normalize } from "node:path";
import { fileURLToPath } from "node:url";
import { chromiumOrSkip, TYPES } from "./overflow.mjs";

const here = dirname(fileURLToPath(import.meta.url)), repo = join(here, "../.."), web = join(repo, "web");
let failed = 0;
const ok = (what, cond, detail) => { if (!cond) failed++; console.log(`${cond ? "ok  " : "FAIL"} ${what}${cond || detail === undefined ? "" : `: ${JSON.stringify(detail)}`}`); };

// ---- what GitHub answers: rebuilt from the recorded scan ---------------------------------------------------------------
const recorded = JSON.parse(readFileSync(join(repo, "docs/agent_pr_ci.json"), "utf8")).prs;
const find = (r, n) => recorded.find((p) => p.repo === r && p.number === n);
function github(rec) {
  const failedNames = rec.failed_checks || [], n = rec.n_check_runs || 0;
  const runs = failedNames.slice(0, n).map((name) => ({ name, status: "completed", conclusion: "failure" }));
  for (const c of rec.other_conclusions || []) if (c !== "failure" && runs.length < n) runs.push({ name: `job ${c}`, status: "completed", conclusion: c });
  while (runs.length < n) runs.push({ name: `job ${runs.length}`, status: "completed", conclusion: "success" });
  for (let i = 0; i < (rec.n_agent_runs_excluded || 0); i++) runs.push({ name: "Copilot", status: "completed", conclusion: "success" });
  const statuses = failedNames.slice(n).map((context) => ({ context, state: "failure" }));
  while (statuses.length < (rec.n_statuses || 0)) statuses.push({ context: `status ${statuses.length}`, state: "success" });
  return { pr: { number: rec.number, title: `Pull request ${rec.number}`, body: rec.claim_line, merged_at: rec.merged ? "2026-09-01T00:00:00Z" : null,
    html_url: `https://github.com/${rec.repo}/pull/${rec.number}`, head: { sha: rec.sha }, user: { login: rec.author } }, runs, statuses };
}
const CASES = { failed: find("BerriAI/litellm", 34321), passed: find("usestrix/strix", 753), other: find("spaja86/AI-IQ-SUPER-PLATFORMA", 877) };
const ANSWERS = new Map();
for (const rec of Object.values(CASES)) {
  const g = github(rec), base = `/repos/${rec.repo}`;
  ANSWERS.set(`${base}/pulls/${rec.number}`, g.pr);
  for (let p = 1; p <= 5; p++) ANSWERS.set(`${base}/commits/${rec.sha}/check-runs?per_page=100&page=${p}`, { total_count: g.runs.length, check_runs: g.runs.slice((p - 1) * 100, p * 100) });
  ANSWERS.set(`${base}/commits/${rec.sha}/status`, { sha: rec.sha, statuses: g.statuses });
  ANSWERS.set(`${base}/commits/${rec.sha}/check-suites?per_page=100`, { check_suites: [] });
}
const RESET = 1_791_000_000;    // a fixed time for the refusal's x-ratelimit-reset

const PAGE = `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Check</title><link rel="stylesheet" href="/app.css"></head><body><main><section id="check"></section></main>
<script type="module">import { renderCheck } from "/check.js";
const m = /^#check=(.+)$/.exec(location.hash);
renderCheck(document.getElementById("check"), { arg: m ? decodeURIComponent(m[1]) : "" }); window.ready = true;</script></body></html>`;
const server = createServer((req, res) => {
  const path = normalize(decodeURIComponent(req.url.split("?")[0])).replace(/^([/\\])+/, "");
  if (!path) { res.writeHead(200, { "content-type": "text/html" }); return res.end(PAGE); }
  const file = join(web, path);
  if (!file.startsWith(web) || !existsSync(file)) { res.writeHead(404); return res.end(); }
  res.writeHead(200, { "content-type": TYPES[extname(file)] || "application/octet-stream" }); res.end(readFileSync(file));
});
await new Promise((r) => server.listen(0, "127.0.0.1", r));
const origin = `http://127.0.0.1:${server.address().port}`;

const browser = await chromiumOrSkip();
const hosts = new Set();
async function open(options = {}, late = 0) {
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 }, ...options });
  await ctx.route("**/*", async (route) => {
    const url = new URL(route.request().url());
    hosts.add(url.host);
    if (url.origin === origin) return route.continue();
    if (url.host !== "api.github.com") return route.abort();
    if (late) await new Promise((r) => setTimeout(r, late));
    const path = url.pathname + url.search;
    if (path.includes("/limited/")) return route.fulfill({ status: 403, headers: { "x-ratelimit-remaining": "0", "x-ratelimit-reset": String(RESET), "content-type": "application/json", "access-control-allow-origin": "*", "access-control-expose-headers": "X-RateLimit-Remaining, X-RateLimit-Reset, Retry-After" }, body: '{"message":"API rate limit exceeded"}' });
    const got = ANSWERS.get(path);
    return got ? route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(got) }) : route.fulfill({ status: 404, contentType: "application/json", body: '{"message":"Not Found"}' });
  });
  return ctx;
}
const verdictOf = (page) => page.waitForSelector("#check-verdict", { timeout: 15_000 }).then(() => page.evaluate(() => ({
  line: document.getElementById("check-verdict").textContent, quote: document.getElementById("check-quote")?.textContent ?? null,
  claimed: document.getElementById("check-claimed").textContent, test: Number(document.getElementById("check-test").textContent),
  other: Number(document.getElementById("check-other").textContent) })));

// ---- android: the first verdict from a link -----------------------------------------------------------------------------
{
  const ctx = await open({ viewport: { width: 360, height: 740 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true }, 150);
  const page = await ctx.newPage(), cdp = await ctx.newCDPSession(page);
  await cdp.send("Network.enable");
  await cdp.send("Network.setCacheDisabled", { cacheDisabled: true });
  await cdp.send("Network.emulateNetworkConditions", { offline: false, latency: 150, downloadThroughput: Math.round(1.6e6 / 8), uploadThroughput: Math.round(750e3 / 8) });
  await cdp.send("Emulation.setCPUThrottlingRate", { rate: 4 });
  await page.goto(`${origin}/#check=BerriAI/litellm/34321`, { waitUntil: "commit" });
  const ms = await (await page.waitForFunction(() => document.getElementById("check-verdict") && performance.now(), null, { polling: "raf", timeout: 20_000 })).jsonValue();
  ok(`android: first verdict in ${Math.round(ms)} ms from the link (under 10000)`, ms < 10_000, ms);
  const v = await verdictOf(page);
  ok("answer: a claim, quoted", v.claimed.startsWith("Yes") && v.quote === CASES.failed.claim_line, v);
  ok("answer: one test or build check failed, no other", v.test === 1 && v.other === 0, v);
  ok("answer: the verdict in one line", v.line === "Claims tests pass; a test or build check failed.", v.line);
  ok("answer: the failed check is named in the table", (await page.textContent("#check-failed")).includes("All Other Providers / Run tests"));
  ok("android 360px: no sideways scroll", await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
  await ctx.close();
}

// ---- paste, the address, pending, limits ------------------------------------------------------------------------------
{
  const ctx = await open({ reducedMotion: "reduce" });
  const page = await ctx.newPage();
  await page.goto(`${origin}/`);
  await page.waitForFunction(() => window.ready);
  await page.evaluate(() => { const dt = new DataTransfer(); dt.setData("text", "https://github.com/usestrix/strix/pull/753"); document.getElementById("check-url").dispatchEvent(new ClipboardEvent("paste", { clipboardData: dt, bubbles: true, cancelable: true })); });
  let v = await verdictOf(page);
  ok("paste: checked with no press", v.line === "Claims tests pass; every check passed." && v.test === 0 && v.other === 0, v);

  await page.evaluate(() => { location.hash = "#check=spaja86/AI-IQ-SUPER-PLATFORMA/877"; });
  await page.waitForFunction(() => /test nothing/.test(document.getElementById("check-verdict")?.textContent || ""));
  v = await verdictOf(page);
  ok("address: a later #check= link is checked; deploys count as other", v.test === 0 && v.other === 3 && v.line === "Claims tests pass; only checks that test nothing failed.", v);

  const pending = await page.evaluate(() => {
    document.getElementById("check-url").value = "https://github.com/someone/limited/pull/1";
    document.getElementById("check-run").click();
    return { live: document.querySelector('[data-step="read"]').dataset.state, bars: !!document.querySelector("#check-result .k-skeleton"), busy: document.getElementById("check-result").getAttribute("aria-busy") };
  });
  ok("pending: shown in the same task as the press", pending.live === "live" && pending.bars && pending.busy === "true", pending);
  await page.waitForSelector("#check-limit");
  const limit = await page.textContent("#check-limit");
  ok("limits: GitHub's hourly limit is said, with its reset", /^Wait until .+: GitHub answers 60 reads an hour per address\.$/.test(limit), limit);

  await page.fill("#check-url", "github.com/nobody/nothing/pull/9");
  await page.click("#check-run");
  await page.waitForFunction(() => /no such public pull request/.test(document.getElementById("check-error")?.textContent || ""));
  ok("limits: a missing pull request is said", true);
  await page.fill("#check-url", "not a link");
  await page.click("#check-run");
  ok("limits: a line that is no link asks for one", /like github\.com\/owner\/repo\/pull\/123/.test(await page.textContent("#check-error")));

  // words: the page with an answer on it
  await page.fill("#check-url", "BerriAI/litellm#34321");
  await page.click("#check-run");
  await verdictOf(page);
  const words = await page.evaluate(() => {
    const said = [...document.querySelectorAll("#check h2, #check p, #check dt, #check dd, #check li, #check label, #check button, #check th")].map((e) => {
      const c = e.cloneNode(true); for (const q of c.querySelectorAll("q, td")) q.remove(); return c.textContent.replace(/\s+/g, " ").trim(); });
    return { title: document.querySelector("#check h2").textContent, long: said.flatMap((t) => t.split(/(?<=[.!?])\s+/)).filter((t) => t.split(" ").length > 12), all: said.join(" ") };
  });
  ok("words: no statement over twelve words", words.long.length === 0, words.long);
  ok("words: a title of 3 to 6 words", words.title.split(" ").length >= 3 && words.title.split(" ").length <= 6, words.title);
  ok("words: nothing says wallet, hash, pin or token account", !/\b(wallets?|hash(es)?|pins?|token accounts?)\b/i.test(words.all), words.all);

  for (const width of [320, 360, 390, 768, 1280]) {
    await page.setViewportSize({ width, height: 800 });
    const over = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    ok(`width ${width}px: no sideways scroll`, over <= 0, over);
  }
  await ctx.close();
}
ok("hosts: only the page's own and api.github.com", [...hosts].every((h) => h === new URL(origin).host || h === "api.github.com"), [...hosts]);

await browser.close(); server.close();
console.log(failed ? `${failed} failed` : "all passed");
process.exit(failed ? 1 : 0);
