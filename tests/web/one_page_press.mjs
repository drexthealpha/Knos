// node tests/web/one_page_press.mjs <site dir>
// The goal's 400 ms rule on the one page (https://drexthealpha.github.io/Knos/), at 390 px on a CPU slowed 4 times, as
// tests/web/front_door.mjs slows it: every press shows a visible change within 400 ms of the input, and while a press
// waits on the network past 400 ms, the page keeps moving (a clock, a counter or a running animation) at least every
// 400 ms until the answer is drawn. The network is mocked: the hosted app answers each call after 900 ms with a fixed
// answer, so the waits are real and the same on every machine. Pressed: every button and summary the page shows when it
// loads, then the proof flow's own controls in order (the sample paper, another paper and "Prove the sample paper
// instead", the order, "Count them with your code", "Prove the same claim again").
// The site the web job builds keeps the app at index.html (KNOS_SPA_AT_ROOT=1); the one page is then composed here from
// that build, as scripts/build_site.sh composes it for the published site.
import { createServer } from "node:http";
import { readFileSync, existsSync, mkdtempSync, cpSync, rmSync, renameSync } from "node:fs";
import { join, extname, dirname, resolve } from "node:path";
import { tmpdir } from "node:os";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { chromiumOrSkip, TYPES } from "./overflow.mjs";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const given = process.argv[2];
if (!given || !existsSync(join(given, "index.html"))) { console.error("usage: node tests/web/one_page_press.mjs <site dir>"); process.exit(2); }
let root = resolve(given), made = null;
if (!readFileSync(join(given, "index.html"), "utf8").includes('id="near-flow"')) {
  made = mkdtempSync(join(tmpdir(), "one-page-")); root = resolve(made, "site");
  cpSync(given, root, { recursive: true });
  rmSync(join(root, "index.html")); renameSync(join(root, "home.html"), join(root, "index.html"));
  execFileSync(process.env.PYTHON || "python3", [join(ROOT, "scripts", "one_page.py"), root], { stdio: "inherit" });
}
const LIMIT = 400, DELAY = 900, WIDTH = 390, HEIGHT = 844;
let fails = 0;
const check = (name, cond, detail) => { if (cond) console.log("ok  ", name); else { fails++; console.error("FAIL", name, detail === undefined ? "" : JSON.stringify(detail)); } };

const SAMPLE = "https://doi.org/10.46298/dmtcs.3545";
const ANSWERS = {
  "/api/near/claim/look": (b) => (String(b.url || "").includes("dmtcs.3545")
    ? { ok: true, known: true, paper: "HyperLogLog", authors: "Flajolet and others, 2007", doi: SAMPLE, quote: "a typical accuracy of 2% while using a memory of only 1.5 kilobytes", amount_default: 10, amount_max: 100, ready: true, job_id: "job-1" }
    : { ok: true, known: false, title: "Another paper", quote: { checker: "a person who reruns it", price: "$330 to $763", time: "weeks", source: "https://example.org/" } }),
  "/api/near/claim/prove": () => ({ ok: true, ran_before_s: 300, job_id: "job-1", market: { id: "m-1" },
    attempts: [{ agent: "agent-a", passed: true, reason: "Passed" }, { agent: "agent-b", passed: false, reason: "Failed" }],
    verdict: { holds: true, paper: "2% typical error", measured: "1.2% error" } }),
  "/api/near/claim/cap": () => ({ ok: true, refused: true, tried_units: 2, cap_units: 1, url: "https://example.org/tx" }),
  "/api/near/claim/finish": () => ({ pay: { ok: true }, settle: { ok: true, settled: true, url: "https://example.org/tx" },
    receipt: { job: "job-1", buyer_usd: 10, agent_usd: 0.2, knos_usd: 9.8, agent_pay_url: "https://example.org/a", fee_url: "https://example.org/f", log: { rows: [] } } }),
  "/api/near/claim/reuse": () => ({ ok: true, reused: "job-1", saved: { first_answer_seconds: 9 }, first_url: "https://example.org/tx" }),
  "/api/near/claim/try": () => ({ ok: true, counted: 98935, visitors: 100000, off_pct: 1.1, bytes: 1364, seconds: 2.4 }),
};
const browser = await chromiumOrSkip();
const server = createServer((req, res) => {
  const path = join(root, decodeURIComponent(new URL(req.url, "http://x").pathname).replace(/\/$/, "/index.html"));
  if (!path.startsWith(root) || !existsSync(path)) { res.writeHead(404); return res.end(); }
  res.writeHead(200, { "content-type": TYPES[extname(path)] || "application/octet-stream" }); res.end(readFileSync(path));
});
await new Promise((r) => server.listen(0, "127.0.0.1", r));
const base = `http://127.0.0.1:${server.address().port}/`;

async function open() {
  const ctx = await browser.newContext({ viewport: { width: WIDTH, height: HEIGHT }, colorScheme: "light", reducedMotion: "no-preference" });
  await ctx.route("**/*", async (route) => {
    const req = route.request(), u = new URL(req.url());
    if (req.url().startsWith(base)) return route.continue();
    if (u.hostname === "knos.onrender.com") {
      await new Promise((r) => setTimeout(r, DELAY));
      let body = {}; try { body = JSON.parse(req.postData() || "{}"); } catch { /* not JSON */ }
      const f = ANSWERS[u.pathname];
      return route.fulfill({ status: 200, contentType: "application/json", headers: { "access-control-allow-origin": "*" },
        body: JSON.stringify(f ? f(body) : { ok: false, why: "not part of this test" }) });
    }
    return route.abort();
  });
  await ctx.addInitScript(() => {
    // what the page's own clock sees: when each press began, every change to the page, and every call it waits on
    window.__t = { marks: [], calls: [], press: null };
    const mark = () => window.__t.marks.push(performance.now());
    new MutationObserver(mark).observe(document, { subtree: true, childList: true, attributes: true, characterData: true });
    setInterval(() => { if (document.getAnimations().some((a) => a.playState === "running")) mark(); }, 50);
    for (const t of ["pointerdown", "mousedown", "keydown"]) addEventListener(t, (ev) => { if (window.__t.armed) { window.__t.press = ev.timeStamp; window.__t.armed = false; } }, { capture: true });
    const f = window.fetch;
    window.fetch = function (input, init) {
      const url = String(input && input.url || input), c = { url, start: performance.now(), end: null };
      if (!url.startsWith(location.origin)) window.__t.calls.push(c);
      const done = () => { c.end = performance.now(); };
      const p = f.apply(this, arguments); p.then(done, done); return p;
    };
  });
  const page = await ctx.newPage();
  const cdp = await ctx.newCDPSession(page);
  await page.goto(base, { waitUntil: "load" });
  await page.waitForTimeout(2500);                          // the first reads (counters, the latest test run) are answered
  await cdp.send("Emulation.setCPUThrottlingRate", { rate: 4 });
  return { ctx, page };
}

// press, then: the first change after the input, drawn; and the longest still stretch while a call it made was waiting
async function press(page, locator, name) {
  await locator.scrollIntoViewIfNeeded().catch(() => {});
  await page.evaluate(() => { window.__t.armed = true; window.__t.press = null; window.__t.marks = []; window.__t.since = window.__t.calls.length; });
  await locator.click({ timeout: 5000 });
  const settle = Date.now();
  for (;;) {                                                  // until every call it made is answered and the page is still for 1.5 s
    await page.waitForTimeout(300);
    const s = await page.evaluate(() => ({ open: window.__t.calls.slice(window.__t.since).some((c) => c.end === null),
      quiet: performance.now() - Math.max(0, ...window.__t.marks.filter((m) => m <= performance.now())) }));
    if ((!s.open && s.quiet > 1500) || Date.now() - settle > 40000) break;
  }
  const r = await page.evaluate((limit) => {
    const t = window.__t, p = t.press;
    const first = t.marks.filter((m) => m >= p).sort((a, b) => a - b)[0];
    const own = /\/api\/near\/claim\/(counters|plain)$|\/api\/near\/(tests|live|totals)$|\/api\/qloo\/status$/;   // the page's own background reads, not a press's
    let still = 0, call = "";
    for (const c of t.calls.slice(t.since)) {
      if (own.test(c.url) || c.end === null || c.end - c.start <= limit) continue;
      const pts = [c.start, ...t.marks.filter((m) => m > c.start && m < c.end), c.end].sort((a, b) => a - b);
      for (let i = 1; i < pts.length; i++) if (pts[i] - pts[i - 1] > still && pts[i] > c.start + limit) { still = pts[i] - pts[i - 1]; call = c.url; }
    }
    return { first: first === undefined ? null : Math.round(first - p), still: Math.round(still), call };
  }, LIMIT);
  check(`${name}: a visible change ${r.first} ms after the press (at most ${LIMIT})`, r.first !== null && r.first <= LIMIT, r);
  check(`${name}: while it waits, still for at most ${r.still} ms at a time (at most ${LIMIT})`, r.still <= LIMIT, r);
}

// every control the page shows when it loads, then every control inside its folded parts once they are opened
// (summaries are pressed in the first pass, so the second presses only what the folds hold)
const controls = ([k, opened]) => {
  if (opened) for (const d of document.querySelectorAll("details")) d.open = true;
  const seen = (x) => { const b = x.getBoundingClientRect(); return b.width > 0 && b.height > 0 && getComputedStyle(x).visibility !== "hidden" && !x.disabled; };
  const all = [...document.querySelectorAll(opened ? "button, input[type=submit]" : "button, summary, input[type=submit]")].filter(seen);
  if (k < 0) return all.length;
  if (!all[k]) return false; all[k].dataset.press = String(k); return true;
};
for (const opened of [false, true]) {
  const { ctx, page } = await open();
  const n = await page.evaluate(controls, [-1, opened]);
  await ctx.close();
  check(`the page shows ${n} controls to press ${opened ? "with its folded parts open" : "when it loads"}`, n > 0, n);
  for (let i = 0; i < n; i++) {
    const { ctx: c, page: p } = await open();
    if (!(await p.evaluate(controls, [i, opened]).catch(() => false))) { await c.close(); continue; }
    const e = p.locator(`[data-press="${i}"]`);
    const name = (await e.evaluate((x) => (x.getAttribute("aria-label") || x.textContent || x.id || x.tagName).trim().replace(/\s+/g, " ").slice(0, 50))) || `control ${i}`;
    await press(p, e, `press "${name}"${opened ? " (folds open)" : ""}`);
    await c.close();
  }
}

// the proof flow, in order
{
  const { ctx, page } = await open();
  await press(page, page.locator("#go"), 'the sample paper, "Will it work?"');
  await press(page, page.locator("#look .offer button"), '"Prove it with 10 test USDC"');
  await press(page, page.getByRole("button", { name: "Count them with your code" }), '"Count them with your code"');
  await press(page, page.getByRole("button", { name: "Prove the same claim again" }), '"Prove the same claim again"');
  await ctx.close();
}
{
  const { ctx, page } = await open();
  await page.fill("#paper", "https://arxiv.org/abs/1706.03762");
  await press(page, page.locator("#go"), 'another paper, "Will it work?"');
  await press(page, page.getByRole("button", { name: "Prove the sample paper instead" }), '"Prove the sample paper instead"');
  await ctx.close();
}

await browser.close(); server.close();
if (made) rmSync(made, { recursive: true, force: true });
if (fails) { console.error(`${fails} failed`); process.exit(1); }
console.log("every press answered within 400 ms");
