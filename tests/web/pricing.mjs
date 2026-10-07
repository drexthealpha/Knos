// The pricing calculator in a browser (web/pricing.js, renderPricing): node tests/web/pricing.mjs
// web/ as it stands, in headless Chromium, with an empty settle.js (so every constant is the recorded one). It opens on
// the worked customer of tests/data/billing_vectors.json, which src/knos/billing.py is held to (tests/test_billing.py);
// every year of that file whose month is a whole number of cents is typed into the five inputs and the invoice lines
// must show the same numbers; the Acceptance line's three rates move with the month's value; a slider moves the lines
// at once; every statement is twelve words at most; nothing runs off the side from 320 to 1280 px; and nobody is asked
// but the page's own server. No `playwright` package or no browser: SKIP, with why.
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
const lines = (p) => p.$$eval("#bill-table tbody tr", (rows) => Object.fromEntries(rows.map((r) => [r.dataset.line, { amount: r.children[1].textContent, say: r.children[2].textContent, off: r.dataset.off || "" }])));
const tiers = (p) => p.$$eval("#bill-tiers .bill-tier", (rows) => rows.map((r) => ({ name: r.children[0].textContent, of: r.querySelector(".k-num").textContent, width: r.querySelector("i").style.width, on: r.dataset.on })));
const statements = (p) => p.evaluate(() => [...document.querySelectorAll(".bill p, .bill label, .bill th, .bill td, .bill option, .bill .bill-tier span:first-child")]
  .filter((e) => e.matches("option") || e.offsetParent !== null).flatMap((e) => (e.matches("option") ? e.textContent : e.innerText).split(/(?<=[.!?])\s+|\n+/)).map((t) => t.trim()).filter(Boolean));
const wordy = (list) => list.filter((t) => t.split(/\s+/).filter((w) => /[\p{L}\p{N}]/u.test(w)).length > 12);
const cents = (text) => Math.round(Number(text.replace(/,/g, "")) * 100);
const monthOf = (y) => { const c = cents(y.accepted); return c % 12 === 0 ? (c / 12 / 100).toFixed(2) : null; };      // null: the year is not twelve whole-cent months
const type = async (p, y) => {
  await p.selectOption("#bill-plan", y.plan);
  await p.fill("#bill-evaluations", String(y.evaluations)); await p.fill("#bill-accepted", monthOf(y)); await p.fill("#bill-onchain", String(y.on_chain_percent)); await p.fill("#bill-lookups", String(y.lookups));
};

{
  const { ctx, p, strangers, errors } = await visit(1280);
  // it opens on the worked customer, already drawn
  const first = await lines(p), worked = vectors.years[0];
  ok("it opens on the worked customer: Business, 110,000 evaluations a month, 833,333.33 accepted a month, none on chain", JSON.stringify([await p.inputValue("#bill-plan"), await p.inputValue("#bill-evaluations"), await p.inputValue("#bill-accepted"), await p.inputValue("#bill-onchain"), await p.inputValue("#bill-lookups")]) === JSON.stringify(["business", "110,000", "833,333.33", "0", "0"]));
  ok("  Control 100,000, Meter 240, Acceptance 30,000, 130,240 in all", JSON.stringify([first.control.amount, first.meter.amount, first.acceptance.amount, first.onchain.amount, first.rebate.amount, first.records.amount, first.total.amount])
    === JSON.stringify([worked.out.control, worked.out.meter, worked.out.acceptance, worked.out.paid_on_chain, worked.out.rebate, worked.out.records, worked.out.total]) && first.total.amount === "130,240.00", first);
  ok("  there is no Verify line, no Settle line, no greater-of line and no supplier line", ["verify", "settle", "usage", "suppliers"].every((k) => !(k in first)) && !/Verify|Settle|greater|capped/i.test(await p.innerText("#bill")));
  ok("  two sentences under it: The rated party never pays. Connecting a supplier costs nothing.", (await p.textContent("#bill-pays")) === "The rated party never pays." && (await p.textContent("#bill-connect")) === "Connecting a supplier costs nothing.");
  ok("  fees on devnet are test money: 0 revenue", first.devnet.say === "test money: 0 revenue" && first.devnet.amount === "");
  ok("  and the benefit a buyer should demand is three to one", (await p.textContent("#bill-benefit")) === `Demand a benefit of 3 to 1: ${worked.out.benefit_to_demand} a year.`);
  const opened = await tiers(p);
  ok("  the month's 833,333.33 is all in the first rate", JSON.stringify(opened.map((t) => [t.name, t.of, t.on])) === JSON.stringify([["0.30% to 1M", "833,333.33", "yes"], ["0.20% above 1M", "0.00", "no"], ["0.10% above 10M", "0.00", "no"]]) && opened[0].width === "100%", opened);
  let typed = 0;
  for (const y of vectors.years) {
    if (monthOf(y.in) === null) continue;
    typed++;
    await type(p, y.in);
    const got = await lines(p), o = y.out;
    ok(`a year: ${y.name}`, JSON.stringify([got.control.amount, got.meter.amount, got.acceptance.amount, got.onchain.amount, got.rebate.amount.replace("-", ""), got.records.amount, got.total.amount])
      === JSON.stringify([o.control, o.meter, o.acceptance, o.paid_on_chain, o.rebate, o.records, o.total]), got);
  }
  ok("  most years of the file are typed", typed >= 7, typed);
  // the Acceptance line shows its marginal tiers moving
  await type(p, { plan: "business", evaluations: 110000, accepted: "240000000.00", on_chain_percent: 0, lookups: 0 });
  const moved = await tiers(p);
  ok("the tiers move: 20 million in a month is 1M at 0.30%, 9M at 0.20%, 10M at 0.10%", JSON.stringify(moved.map((t) => [t.of, t.width, t.on])) === JSON.stringify([["1,000,000.00", "5%", "yes"], ["9,000,000.00", "45%", "yes"], ["10,000,000.00", "50%", "yes"]]) && (await lines(p)).acceptance.amount === "372,000.00", moved);
  ok("  a bar's width is animated, a state change and nothing else", await p.$eval("#bill-tiers i", (i) => getComputedStyle(i).transitionProperty.includes("width") && parseFloat(getComputedStyle(i).transitionDuration) > 0));
  await p.selectOption("#bill-plan", "none");
  ok("  with no contract all of it pays 0.30%", JSON.stringify((await tiers(p)).map((t) => t.of)) === JSON.stringify(["20,000,000.00", "0.00", "0.00"]) && (await lines(p)).acceptance.amount === "720,000.00" && (await lines(p)).rebate.say === "needs a contract");
  // a slider moves the lines at once, and the box beside it holds the same number
  await p.selectOption("#bill-plan", "business"); await p.fill("#bill-accepted", "833,333.33");
  const started = Date.now();
  await p.$eval("#bill-evaluations-range", (r) => { r.value = "1000000"; r.dispatchEvent(new Event("input", { bubbles: true })); });
  const slid = await lines(p);
  ok("a slider moves the lines at once: at 1,000,000 evaluations Meter is 21,600 and both lines are charged", slid.meter.amount === "21,600.00" && slid.acceptance.amount === "30,000.00" && slid.total.amount === "151,600.00" && (await p.inputValue("#bill-evaluations")) === "1,000,000" && Date.now() - started < 300, slid);
  await p.fill("#bill-onchain", "100");
  const chained = await lines(p);
  ok("  all of it released on chain: nothing on the invoice for it, and the fee paid there is shown", (await p.inputValue("#bill-onchain-range")) === "100" && chained.acceptance.amount === "0.00" && chained.acceptance.off === "yes" && chained.onchain.amount === "30,000.00" && chained.onchain.say === "at release; never charged again" && chained.total.amount === "121,600.00", chained);
  await p.selectOption("#bill-plan", "enterprise");
  ok("Enterprise says it is from a price and not deliverable yet", (await lines(p)).control.say === "from; not deliverable yet");
  await p.fill("#bill-accepted", "ten million");
  ok("what cannot be read is said in a sentence, and the lines stay", (await p.textContent("#bill-said")).trim() === "Write accepted value as dollars, like 833,333.33." && (await lines(p)).total.amount !== "");
  await p.fill("#bill-accepted", "833,333.33");
  ok("every statement is twelve words at most", wordy(await statements(p)).length === 0, wordy(await statements(p)));
  ok("nobody but the page's own server is asked", strangers.length === 0, strangers);
  ok("no error on the page", errors.length === 0, errors);
  await ctx.close();
}
for (const width of [320, 390, 768]) {
  const { ctx, p, errors } = await visit(width, width === 320);
  await type(p, vectors.years.find((y) => y.in.plan === "enterprise").in);      // the widest numbers of the file
  ok(`${width}px: nothing runs off the side`, (await measure(p)).over <= 0, await measure(p));
  if (width === 320) ok("with reduced motion asked for, no line and no bar has a transition", await p.$eval('[data-line="meter"] td', (td) => parseFloat(getComputedStyle(td).transitionDuration) === 0) && await p.$eval("#bill-tiers i", (i) => parseFloat(getComputedStyle(i).transitionDuration) === 0));
  if (process.env.KNOS_PRICING_SHOTS) await p.screenshot({ path: join(process.env.KNOS_PRICING_SHOTS, `pricing-${width}.png`), fullPage: true });
  ok(`${width}px: no error on the page`, errors.length === 0, errors);
  await ctx.close();
}
await browser.close(); server.close();
console.log(failed ? `${failed} failed` : "all passed");
process.exit(failed ? 1 : 0);
