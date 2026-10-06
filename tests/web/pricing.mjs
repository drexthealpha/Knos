// The pricing calculator in a browser (web/pricing.js, renderPricing): node tests/web/pricing.mjs
// web/ as it stands, in headless Chromium, with an empty settle.js (so every constant is the recorded one). Every year
// of tests/data/billing_vectors.json, which src/knos/billing.py is held to (tests/test_billing.py), is typed into the
// four inputs and the invoice lines must show the same numbers; the greater of Meter and Verify is visibly the one
// charged; a slider moves the lines at once; every statement is twelve words at most; nothing runs off the side from
// 320 to 1280 px; and nobody is asked but the page's own server. No `playwright` package or no browser: SKIP, with why.
import { readFileSync, existsSync } from "node:fs";
import { createServer } from "node:http";
import { createRequire } from "node:module";
import { join, dirname, extname } from "node:path";
import { fileURLToPath } from "node:url";
import { measure } from "./overflow.mjs";

const here = dirname(fileURLToPath(import.meta.url)), root = join(here, "../../web");
const vectors = JSON.parse(readFileSync(join(here, "../data/billing_vectors.json"), "utf8"));
const skip = (why) => { console.log(`SKIP ${why}`); process.exit(0); };
let pw;
try { pw = await import("playwright"); } catch {
  const paths = (process.env.NODE_PATH || "").split(":").filter(Boolean);
  try { const req = createRequire(import.meta.url); pw = req(req.resolve("playwright", { paths })); } catch { skip("the playwright package is not installed"); }
}
const { chromium } = pw.default || pw;
let browser;
try { browser = await chromium.launch(); } catch (e) { skip(`no Chromium to start: ${String(e.message).split("\n")[0]}`); }

const TYPES = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json", ".svg": "image/svg+xml", ".woff2": "font/woff2" };
const HOLDER = `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Pricing</title>
  <link rel="stylesheet" href="app.css"></head><body><main><div class="k-card" id="bill"></div></main>
  <script type="module">import { renderPricing } from "./pricing.js"; renderPricing(document.getElementById("bill")); window.drawn = true;</script></body></html>`;
const server = createServer((req, res) => {
  const path = decodeURIComponent(new URL(req.url, "http://x").pathname), file = join(root, path);
  if (path === "/pricing_page.html") { res.writeHead(200, { "content-type": "text/html" }); return res.end(HOLDER); }
  if (path === "/settle.js") { res.writeHead(200, { "content-type": "text/javascript" }); return res.end("export {};\n"); }      // only the built site has it
  if (!file.startsWith(root) || !existsSync(file) || !extname(file)) { res.writeHead(404); return res.end(); }
  res.writeHead(200, { "content-type": TYPES[extname(file)] || "application/octet-stream" }); res.end(readFileSync(file));
});
await new Promise((r) => server.listen(0, "127.0.0.1", r));
const base = `http://127.0.0.1:${server.address().port}/`;
let failed = 0;
const ok = (what, cond, detail) => { if (!cond) failed++; console.log(`${cond ? "ok  " : "FAIL"} ${what}${cond || detail === undefined ? "" : `: ${JSON.stringify(detail)}`}`); };

async function visit(width, reduced = false) {
  const ctx = await browser.newContext({ viewport: { width, height: 900 }, reducedMotion: reduced ? "reduce" : "no-preference" }), strangers = [], errors = [];
  await ctx.route("**/*", (route) => { const u = new URL(route.request().url()); if (u.origin === new URL(base).origin) return route.continue(); strangers.push(u.href); return route.abort(); });
  const p = await ctx.newPage();
  p.on("pageerror", (e) => errors.push(String(e)));
  await p.goto(`${base}pricing_page.html`);
  await p.waitForFunction(() => window.drawn === true);
  return { ctx, p, strangers, errors };
}
const lines = (p) => p.$$eval("#bill-table tbody tr", (rows) => Object.fromEntries(rows.map((r) => [r.dataset.line, { amount: r.children[1].textContent, say: r.children[2].textContent, charged: r.dataset.charged || "" }])));
const statements = (p) => p.evaluate(() => [...document.querySelectorAll(".bill p, .bill label, .bill th, .bill td, .bill option")]
  .filter((e) => e.matches("option") || e.offsetParent !== null).flatMap((e) => (e.matches("option") ? e.textContent : e.innerText).split(/(?<=[.!?])\s+|\n+/)).map((t) => t.trim()).filter(Boolean));
const wordy = (list) => list.filter((t) => t.split(/\s+/).filter((w) => /[\p{L}\p{N}]/u.test(w)).length > 12);
const type = async (p, y) => {
  await p.selectOption("#bill-plan", y.plan);
  await p.fill("#bill-evaluations", String(y.evaluations)); await p.fill("#bill-accepted", y.accepted); await p.fill("#bill-suppliers", String(y.suppliers));
};

{
  const { ctx, p, strangers, errors } = await visit(1280);
  // it opens on the worked example, already drawn
  const first = await lines(p), worked = vectors.years[0];
  ok("it opens on the worked example: Business, 110,000 evaluations a month, 10 million a year", JSON.stringify([await p.inputValue("#bill-plan"), await p.inputValue("#bill-evaluations"), await p.inputValue("#bill-accepted"), await p.inputValue("#bill-suppliers")]) === JSON.stringify(["business", "110,000", "10,000,000", "5"]));
  ok("  Control 80,000, Meter 24,000, Verify 50,000, 130,000 in all", JSON.stringify([first.control.amount, first.meter.amount, first.verify.amount, first.usage.amount, first.total.amount]) === JSON.stringify([worked.out.control, worked.out.meter, worked.out.verify, worked.out.usage, worked.out.total]), first);
  ok("  the greater-of line visibly chooses: Verify is charged, Meter is struck out", first.verify.charged === "yes" && first.meter.charged === "no" && first.verify.say === "charged" && first.meter.say === "not charged" && first.usage.say === "Verify, never Meter too"
    && await p.$eval('[data-line="meter"] td.k-num', (td) => getComputedStyle(td).textDecorationLine === "line-through" && Number(getComputedStyle(td).opacity) < 1)
    && await p.$eval('[data-line="verify"] td.k-num', (td) => getComputedStyle(td).textDecorationLine === "none"), first);
  ok("  one sentence under it: The rated party never pays.", (await p.textContent("#bill-pays")) === "The rated party never pays.");
  ok("  devnet settlement is test money: 0 revenue", first.settle.say === "test money: 0 revenue" && first.settle.amount === "");
  ok("  and the benefit a buyer should demand is three to one", (await p.textContent("#bill-benefit")) === `Demand a benefit of 3 to 1: ${worked.out.benefit_to_demand} a year.`);
  for (const y of vectors.years) {
    await type(p, y.in);
    const got = await lines(p), o = y.out;
    ok(`a year: ${y.name}`, JSON.stringify([got.control.amount, got.meter.amount, got.verify.amount, got.usage.amount, got.suppliers.amount, got.total.amount, await p.$eval("#bill-table tbody", (b) => b.dataset.chosen)])
      === JSON.stringify([o.control, o.meter, o.verify, o.usage, o.supplier_connections, o.total, o.chosen]) && got[o.chosen].charged === "yes" && got[o.chosen === "meter" ? "verify" : "meter"].charged === "no", got);
  }
  // a slider moves the lines at once, and the box beside it holds the same number
  await type(p, vectors.years[0].in);
  const started = Date.now();
  await p.$eval("#bill-evaluations-range", (r) => { r.value = "1000000"; r.dispatchEvent(new Event("input", { bubbles: true })); });
  const moved = await lines(p);
  ok("a slider moves the lines at once: at 1,000,000 evaluations Meter is the greater, 237,600", moved.meter.amount === "237,600.00" && moved.meter.charged === "yes" && moved.verify.charged === "no" && moved.total.amount === "317,600.00" && (await p.inputValue("#bill-evaluations")) === "1,000,000" && Date.now() - started < 300, moved);
  await p.fill("#bill-suppliers", "12");
  ok("  and a box moves its slider", (await p.inputValue("#bill-suppliers-range")) === "12" && (await lines(p)).suppliers.amount === "35,000.00");
  await p.selectOption("#bill-plan", "enterprise");
  ok("Enterprise says it is from a price and not deliverable yet", (await lines(p)).control.say === "from; not deliverable yet");
  await p.fill("#bill-accepted", "ten million");
  ok("what cannot be read is said in a sentence, and the lines stay", (await p.textContent("#bill-said")).trim() === "Write accepted value as dollars, like 10,000,000." && (await lines(p)).total.amount !== "");
  await p.fill("#bill-accepted", "10,000,000");
  ok("every statement is twelve words at most", wordy(await statements(p)).length === 0, wordy(await statements(p)));
  ok("nobody but the page's own server is asked", strangers.length === 0, strangers);
  ok("no error on the page", errors.length === 0, errors);
  await ctx.close();
}
for (const width of [320, 390, 768]) {
  const { ctx, p, errors } = await visit(width, width === 320);
  await type(p, vectors.years.find((y) => y.in.plan === "enterprise").in);      // the widest numbers of the file
  ok(`${width}px: nothing runs off the side`, (await measure(p)).over <= 0, await measure(p));
  if (width === 320) ok("with reduced motion asked for, no line has a transition", await p.$eval('[data-line="meter"] td', (td) => parseFloat(getComputedStyle(td).transitionDuration) === 0));
  if (process.env.KNOS_PRICING_SHOTS) await p.screenshot({ path: join(process.env.KNOS_PRICING_SHOTS, `pricing-${width}.png`), fullPage: true });
  ok(`${width}px: no error on the page`, errors.length === 0, errors);
  await ctx.close();
}
await browser.close(); server.close();
console.log(failed ? `${failed} failed` : "all passed");
process.exit(failed ? 1 : 0);
