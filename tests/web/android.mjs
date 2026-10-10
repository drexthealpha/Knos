// node tests/web/android.mjs <site dir> [--write [file]]
// The first screen on a cheap Android phone: a build of web/ in headless Chromium at 360 x 740, the processor slowed 4
// times (CDP Emulation.setCPUThrottlingRate) and the network a slow 4G (CDP Network.emulateNetworkConditions: 1.6 Mbps
// down, 750 kbps up, 150 ms round trip), the cache empty on every run. Two figures, each under 3 seconds at the median
// and at the slowest of RUNS runs:
//   first paint     first-contentful-paint, from the navigation's start
//   usable          the first screen answers: front.js has run (the bar's light and dark button is shown) and the
//                   invoice box takes typing
// and one more, measured and written but not yet held to the limit: the first other page opened (the Console, #buy, whose
// code is asked for when it is first opened) drawn, from the tap. --write puts the table in docs/perf.json under "android" (or the file named), the rest of the
// file kept. No `playwright` package or no browser: a failure in CI, a skip elsewhere (tests/web/overflow.mjs, `owed`).
import { createServer } from "node:http";
import { readFileSync, writeFileSync, existsSync } from "node:fs";
import { join, extname, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { cpus } from "node:os";
import { chromiumOrSkip, TYPES } from "./overflow.mjs";

const root = process.argv[2], wr = process.argv.indexOf("--write");
if (!root || !existsSync(join(root, "index.html"))) { console.error("usage: node tests/web/android.mjs <site dir> [--write [file]]"); process.exit(2); }
const out = wr < 0 ? null : process.argv[wr + 1] || join(dirname(fileURLToPath(import.meta.url)), "..", "..", "docs", "perf.json");
const RUNS = 3, LIMIT_MS = 3000, CPU = 4;
const NET = { offline: false, latency: 150, downloadThroughput: Math.round(1.6e6 / 8), uploadThroughput: Math.round(750e3 / 8) };   // bytes a second
const VIEWPORT = { width: 360, height: 740 };
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

const runs = [];
for (let i = 0; i < RUNS; i++) {
  const ctx = await browser.newContext({ viewport: VIEWPORT, deviceScaleFactor: 2, isMobile: true, hasTouch: true });
  await ctx.route("**/*", (route) => (route.request().url().startsWith(base) ? route.continue() : route.abort()));
  const page = await ctx.newPage();
  let bytes = 0;
  page.on("response", async (r) => { bytes += (await r.body().catch(() => Buffer.alloc(0))).length; });
  const cdp = await ctx.newCDPSession(page);
  await cdp.send("Network.enable");
  await cdp.send("Network.setCacheDisabled", { cacheDisabled: true });
  await cdp.send("Network.emulateNetworkConditions", NET);
  await cdp.send("Emulation.setCPUThrottlingRate", { rate: CPU });
  await page.goto(base, { waitUntil: "commit" });
  // the time the first screen first answers, read in the page from the navigation's start
  const usable = await (await page.waitForFunction(() => {
    const box = document.getElementById("fd-in");
    return document.querySelector("#theme:not([hidden])") && box && !box.disabled ? performance.now() : false;
  }, null, { polling: "raf", timeout: 20_000 })).jsonValue();
  const paint = await page.evaluate(() => performance.getEntriesByName("first-contentful-paint")[0]?.startTime ?? null);
  await page.waitForLoadState("networkidle");
  const first = bytes;                                              // what the first screen asked for, before any tap
  // the first other page: the Console (#buy), to its heading drawn and its grey bars gone; its code (web/buyer.js) and data
  // come over the same slow network when it is first opened
  const t0 = await page.evaluate(() => performance.now());
  await page.evaluate(() => { location.hash = "#buy"; });
  const opened = await (await page.waitForFunction((t) => {
    const v = document.getElementById("buy");
    return v && !v.hidden && v.offsetParent !== null && v.querySelector("h2, h1") && !v.querySelector(".k-skeleton") ? performance.now() - t : false;
  }, t0, { polling: "raf", timeout: 20_000 })).jsonValue();
  runs.push({ paint: Math.round(paint), usable: Math.round(usable), console: Math.round(opened), kb: Math.round(first / 1024) });
  console.log(`run ${i + 1}: first paint ${Math.round(paint)} ms, usable ${Math.round(usable)} ms, #buy ${Math.round(opened)} ms, ${Math.round(first / 1024)} KB first screen`);
  await ctx.close();
}
await browser.close(); server.close();

const median = (k) => [...runs].map((r) => r[k]).sort((a, b) => a - b)[Math.floor(runs.length / 2)];
const worst = (k) => Math.max(...runs.map((r) => r[k]));
for (const [k, said] of [["paint", "first contentful paint"], ["usable", "the first screen usable"]])
  check(`android: ${said} under ${LIMIT_MS} ms (median ${median(k)}, slowest ${worst(k)})`, worst(k) < LIMIT_MS, runs);
// measured and written, not held yet: web/buyer.js asks for statements.js and records.js only when it uses them, and
// web/front.js asks for every file #buy names at once (preload), which brought it under the aim here (docs/perf.json); the
// grey bars show at once
console.log(`note: the first other page (#buy) drawn in ${median("console")} ms at the median, ${worst("console")} at the slowest (${LIMIT_MS} is the aim)`);

if (out && !fails) {
  const doc = existsSync(out) ? JSON.parse(readFileSync(out, "utf8")) : {};
  doc.android = {
    what: "tests/web/android.mjs: a build of web/ at 360 x 740, CPU slowed 4x, 1.6 Mbps down, 750 kbps up, 150 ms round trip, cache empty; milliseconds from the navigation's start (first paint, usable) or from the tap (#buy).",
    machine: `${cpus().length} CPUs (${cpus()[0]?.model || "unknown"}), shared`, limit_ms: LIMIT_MS, cpu_slowdown: CPU,
    network: { down_kbps: 1600, up_kbps: 750, rtt_ms: 150 }, viewport: VIEWPORT, runs: runs.length,
    first_contentful_paint_ms: { median: median("paint"), max: worst("paint") }, usable_ms: { median: median("usable"), max: worst("usable") },
    first_other_page_ms: { page: "#buy", median: median("console"), max: worst("console") }, first_screen_kb: median("kb"),
  };
  writeFileSync(out, JSON.stringify(doc, null, 1) + "\n", "utf8");
  console.log(`wrote ${out}`);
}
if (fails) { console.error(`${fails} failed`); process.exit(1); }
console.log("android: all passed");
