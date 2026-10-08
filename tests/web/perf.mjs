// node tests/web/perf.mjs <site dir> [--write [file]]
// How fast the page answers, measured on a build of web/ in headless Chromium:
//   answer    each primary interaction, from the input's own timestamp to the first frame painted with the new state
//             (or with its pending state: a page that is leaving dims at once), 20 runs each, a run being the best of three
//             presses so that a shared machine's bursts are not counted, the 95th percentile under 300 ms: open a view, run the sample
//             invoice (where the first screen has #front-door), open the command palette, switch light and dark.
//             A change of page is held twice: to its pending state, and to the new page itself drawn. A page whose code
//             is not there yet (each page's code is asked for when it is first opened) shows its grey bars at once,
//             and that first opening is held to 200 ms
//   weight    the JavaScript and CSS the first screen asks for before anything is pressed, in bytes as served
//             (unminified, uncompressed): under the budgets below; the palette is not among them
//   place     layout shift after the first paint: 0.05 at most, at a laptop's width and a phone's
//   width     no sideways scroll from 320 to 1280, the palette shut and open
// --write puts the table in docs/perf.json (or the file named): the figures of the machine it ran on, which it names.
// No browser: a failure in CI, a skip elsewhere (tests/web/overflow.mjs, `owed`).
import { createServer } from "node:http";
import { readFileSync, writeFileSync, existsSync } from "node:fs";
import { join, extname, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { cpus } from "node:os";
import { chromiumOrSkip, measure, TYPES } from "./overflow.mjs";

const root = process.argv[2], wr = process.argv.indexOf("--write");
if (!root || !existsSync(join(root, "index.html"))) { console.error("usage: node tests/web/perf.mjs <site dir> [--write [file]]"); process.exit(2); }
const out = wr < 0 ? null : process.argv[wr + 1] || join(dirname(fileURLToPath(import.meta.url)), "..", "..", "docs", "perf.json");
const RUNS = 20, LIMIT_MS = 300, FIRST_OPEN_MS = 200, SHIFT = 0.05, WIDTHS = [320, 360, 390, 480, 768, 1024, 1280];
const BUDGET = { js: 183_000, css: 60_000 };                        // bytes the first screen may ask for: what was measured (166,013 of script once the round below the fold came with the reader's first move, and 59,914) and a tenth more; today's are in docs/perf.json
let fails = 0;
const check = (name, cond, detail) => { if (cond) console.log("ok  ", name); else { fails++; console.error("FAIL", name, detail === undefined ? "" : JSON.stringify(detail)); } };

const browser = await chromiumOrSkip();
const server = createServer((req, res) => {
  const path = join(root, decodeURIComponent(new URL(req.url, "http://x").pathname).replace(/\/$/, "/index.html"));
  if (!path.startsWith(root) || !existsSync(path)) { res.writeHead(404); return res.end(); }
  res.writeHead(200, { "content-type": TYPES[extname(path)] || "application/octet-stream" }); res.end(readFileSync(path));
});
await new Promise((r) => server.listen(0, "127.0.0.1", r));
const base = `http://127.0.0.1:${server.address().port}/`;
const world = async (o = {}) => {
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 }, colorScheme: "dark", ...o });
  await ctx.route("**/*", (route) => (route.request().url().startsWith(base) ? route.continue() : route.abort()));
  // armed before an input: resolves with the milliseconds from that input's timestamp to the frame that shows `done`
  await ctx.addInitScript(() => {
    window.__answer = (types, done) => new Promise((res) => {
      let t0;
      window.__armed = true;                                        // the listeners below are on: the test may press now
      for (const t of types) addEventListener(t, (ev) => { t0 ??= ev.timeStamp; }, { capture: true, once: true });
      const tick = () => {
        if (t0 === undefined || !done()) return requestAnimationFrame(tick);
        const ch = new MessageChannel();                            // a task after this frame's callbacks: the frame is drawn
        ch.port1.onmessage = () => { window.__armed = false; res(performance.now() - t0); }; ch.port2.postMessage(0);
      };
      requestAnimationFrame(tick);
    });
    window.__shift = 0;
    try { new PerformanceObserver((l) => { for (const e of l.getEntries()) if (!e.hadRecentInput) window.__shift += e.value; }).observe({ type: "layout-shift", buffered: true }); } catch { window.__shift = -1; }
  });
  return ctx;
};
const ready = (page) => page.waitForSelector("#theme:not([hidden])");
const p = (list, q) => { const s = [...list].sort((a, b) => a - b); return Math.round(s[Math.min(s.length - 1, Math.ceil(q * s.length) - 1)] * 10) / 10; };

// ---- weight and place --------------------------------------------------------------------------------------------------------
const weight = { js: 0, css: 0, files: [] };
const shifts = {};
for (const [width, height] of [[1280, 800], [390, 844]]) {
  const ctx = await world({ viewport: { width, height } });
  const page = await ctx.newPage();
  if (width === 1280) page.on("response", async (r) => {
    const ext = extname(new URL(r.url()).pathname);
    if (ext !== ".js" && ext !== ".css") return;
    const n = (await r.body().catch(() => Buffer.alloc(0))).length;
    weight[ext.slice(1)] += n; weight.files.push([r.url().replace(base, ""), n]);
  });
  await page.goto(base, { waitUntil: "networkidle" }); await ready(page);
  await page.evaluate(() => document.fonts.ready);
  await page.waitForTimeout(1200);                                  // every late answer of the page's own files has landed
  shifts[width] = Math.round((await page.evaluate(() => window.__shift)) * 10000) / 10000;
  check(`place: at ${width} the layout shifts ${shifts[width]} after the first paint (${SHIFT} at most)`, shifts[width] >= 0 && shifts[width] <= SHIFT, shifts[width]);
  await ctx.close();
}
weight.files.sort((a, b) => b[1] - a[1]);
check(`weight: the first screen asks for ${weight.js} bytes of JavaScript (under ${BUDGET.js})`, weight.js > 0 && weight.js < BUDGET.js, weight.files.slice(0, 6));
check(`weight: and ${weight.css} bytes of CSS (under ${BUDGET.css})`, weight.css > 0 && weight.css < BUDGET.css);
check("weight: the palette is not asked for until it is opened", !weight.files.some(([f]) => f === "palette.js"), weight.files.map(([f]) => f));
check("weight: nor the files that read Solana, nor the round below the first screen, nor any other page's code", !weight.files.some(([f]) => ["app.js", "settle.js", "demo.js", "buyer.js", "console.js", "mounts.js", "pricing.js", "records.js", "statements.js", "finance_data.js"].includes(f)), weight.files.map(([f]) => f));

// ---- answer ------------------------------------------------------------------------------------------------------------------
const table = {};
{
  const ctx = await world();
  const page = await ctx.newPage();
  await page.goto(base, { waitUntil: "load" }); await ready(page);
  const errors = []; page.on("pageerror", (e) => errors.push(e.message));
  const time = async (name, arm, act, reset, told = false, presses = 3, limit = LIMIT_MS) => {
    const took = [];
    for (let i = 0; i < RUNS; i += 1) {
      let best = Infinity;                                          // a run is the best of three presses: a neighbour's burst on a shared machine is not the page's time
      for (let k = 0; k < (told ? 1 : presses); k += 1) {             // what is only told is one press a run
        const answered = page.evaluate(arm);
        await page.waitForFunction(() => window.__armed === true);  // a key press is faster than the arming: wait for it, or the press is missed and nothing answers
        await act(); best = Math.min(best, await answered);
        if (reset) await reset();
      }
      took.push(best);
    }
    table[name] = { runs: RUNS, p50_ms: p(took, 0.5), p95_ms: p(took, 0.95), max_ms: p(took, 1) };
    if (told) { table[name].held_to_limit = false; return console.log(`     ${name}: p95 ${table[name].p95_ms} ms over ${RUNS} runs (told, not held to the limit)`); }
    if (limit !== LIMIT_MS) table[name].limit_ms = limit;
    check(`answer: ${name}: p95 ${table[name].p95_ms} ms over ${RUNS} runs (under ${limit})`, table[name].p95_ms < limit, table[name]);
  };

  await time("open a view", () => window.__answer(["click"], () => "morph" in document.documentElement.dataset || !document.getElementById("view-pricing").hidden),
    () => page.click('#nav a[href="#pricing"]'),
    async () => { await page.waitForFunction(() => !document.getElementById("view-pricing").hidden && document.getElementById("view-check").hidden && !("morph" in document.documentElement.dataset));
      await page.evaluate(() => { location.hash = "#check"; }); await page.waitForFunction(() => !document.getElementById("view-check").hidden); });

  // the press is answered by the pending state (above); the new page itself is held to the same limit: the page is
  // swapped in the task of the press, and only the heading and the mark are pictured for the crossing (web/motion.js)
  await time("open a view: the new page drawn", () => window.__answer(["click"], () => !document.getElementById("view-pricing").hidden),
    () => page.click('#nav a[href="#pricing"]'),
    async () => { await page.waitForFunction(() => !("morph" in document.documentElement.dataset)); await page.evaluate(() => { location.hash = "#check"; }); await page.waitForFunction(() => !document.getElementById("view-check").hidden); });

  // a page whose code has not been asked for yet: its section is shown at once, with grey bars until the code has run.
  // Held to FIRST_OPEN_MS: in 0.3.19 this was 299.6 ms against 300, the press waiting for a picture of the page it
  // left (a view transition) and for the new page's code to be read; now the bars are drawn in the task of the press
  // and the code is asked for after that frame (web/front.js: `painted`, and no crossing on a first opening)
  if (await page.$('#nav a[href="#buy"]')) await time("open a page for the first time", () => window.__answer(["click"], () => { const b = document.getElementById("buy"); return b.checkVisibility() && b.childElementCount > 0; }),
    () => page.click('#nav a[href="#buy"]'),
    async () => { await page.goto(base, { waitUntil: "load" }); await ready(page); await page.waitForSelector('#nav a[href="#buy"]', { state: "visible" }); }, false, 1, FIRST_OPEN_MS);

  if (await page.$("#front-door")) {
    // the answer is whatever the front door draws first: the lines, or its pending state
    const act = await page.evaluate(() => ["sample", "run"].find((k) => document.querySelector(`#front-door [data-fd="${k}"]`)?.checkVisibility()));
    if (act) await time("run the sample invoice", () => { let changed = false; const seen = new MutationObserver(() => { changed = true; });       // the answer is drawn in the form or in the result beside it (#front-result)
      for (const el of [document.getElementById("front-door"), document.getElementById("front-result")]) if (el) seen.observe(el, { subtree: true, childList: true, attributes: true, characterData: true });
      return window.__answer(["click"], () => changed); },
      () => page.click(`#front-door [data-fd="${act}"]`),
      async () => { await page.reload({ waitUntil: "load" }); await ready(page); await page.waitForSelector(`#front-door [data-fd="${act}"]`, { state: "visible" }); },
      false, 1);        // one press a run: each press needs the page loaded again, and sixty loads are minutes on a small machine
    else check("answer: the front door offers its sample or its run button", false);
  } else console.log("ok   answer: this build has no #front-door; the sample invoice is not timed");

  await page.focus("#theme");
  await time("open the palette", () => window.__answer(["keydown"], () => !!document.querySelector("dialog.k-pal[open] li")),
    () => page.keyboard.press("Control+k"),
    async () => { await page.keyboard.press("Escape"); await page.waitForFunction(() => !document.querySelector("dialog.k-pal").open); });

  await time("switch light and dark", () => { const was = getComputedStyle(document.body).backgroundColor; return window.__answer(["click"], () => getComputedStyle(document.body).backgroundColor !== was); },
    () => page.click("#theme"));
  check("answer: no page error", errors.length === 0, errors);
  await ctx.close();
}

// ---- width -------------------------------------------------------------------------------------------------------------------
{
  const ctx = await world({ reducedMotion: "reduce" });
  const page = await ctx.newPage();
  const wide = [];
  for (const width of WIDTHS) {
    await page.setViewportSize({ width, height: 800 });
    await page.goto(base, { waitUntil: "load" }); await ready(page);
    const shut = await measure(page);
    await page.keyboard.press("Control+k"); await page.waitForSelector("dialog.k-pal[open] li");
    const box = await page.evaluate(() => { const r = document.querySelector("dialog.k-pal").getBoundingClientRect(); return r.left >= 0 && r.right <= document.documentElement.clientWidth; });
    const open = await measure(page);
    if (shut.over > 0 || open.over > 0 || !box) wide.push([width, shut, open, box]);
    await page.keyboard.press("Escape");
  }
  check(`width: no sideways scroll at ${WIDTHS.join(", ")}, the palette shut and open`, wide.length === 0, wide);
  await ctx.close();
}

await browser.close(); server.close();
if (out && !fails) {
  const doc = { what: "tests/web/perf.mjs on a build of web/ in headless Chromium. Input to next paint (the new state, or its pending state), in milliseconds, 20 runs, each the best of three presses; bytes as served, unminified and uncompressed.",
    machine: `${cpus().length} CPUs (${cpus()[0]?.model || "unknown"}), shared`, limit_ms: LIMIT_MS, interactions: table,
    first_screen_bytes: { js: weight.js, css: weight.css, budget: BUDGET, files: weight.files.length }, layout_shift: { limit: SHIFT, at_1280: shifts[1280], at_390: shifts[390] }, widths_without_sideways_scroll: WIDTHS };
  writeFileSync(out, JSON.stringify(doc, null, 1) + "\n", "utf8");
  console.log(`wrote ${out}`);
}
console.log(fails ? `${fails} checks failed` : "perf: every check held");
process.exit(fails ? 1 : 0);
