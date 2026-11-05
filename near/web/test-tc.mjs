// F3 T-c, the stranger's walk (spec S1): fund one testnet milestone and release it with its proof, then fund one with
// a one-minute deadline and refund it once the deadline passes. A fresh browser, the page only, one page at a time.
//   node near/web/test-tc.mjs <app URL, e.g. http://127.0.0.1:8790/> <out dir>
// Chain time and the deadline wait are logged apart from the stranger's own seconds. Writes <out>/tc-walk.json.
import fs from "node:fs";
import path from "node:path";
import { chromium } from "playwright";

const [app, out = "tc-walk", only = ""] = process.argv.slice(2);   // only: run just the step of that name
fs.mkdirSync(out, { recursive: true });
const browser = await chromium.launch();
const result = { app, steps: [] };
let fails = 0;

async function step(name, width, run) {
  if (only && name !== only) return;
  const ctx = await browser.newContext({ viewport: { width, height: width < 700 ? 844 : 800 } });
  const page = await ctx.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  let clicks = 0, wait = 0, ok = false, note = "";
  const t0 = Date.now();
  const click = async (loc) => { clicks++; await loc.click(); };
  const waitFor = async (fn, ms) => { const w0 = Date.now(); await fn(ms); wait += Date.now() - w0; };
  try { ok = await run(page, click, waitFor, (n) => { note = n; }); } catch (e) { note = String(e).slice(0, 300); }
  const secs = (Date.now() - t0) / 1000, own = Math.round((secs - wait / 1000) * 10) / 10;
  await page.screenshot({ path: path.join(out, `${name}-${width}.png`) });
  const row = { name, width, ok, clicks, seconds_total: Math.round(secs * 10) / 10, seconds_without_waits: own, seconds_waiting: Math.round(wait / 100) / 10, note, errors };
  result.steps.push(row);
  const pass = ok && clicks <= 3 && own <= 60 && !errors.length;
  if (!pass) fails++;
  console.log(pass ? "ok  " : "FAIL", JSON.stringify(row));
  await ctx.close();
}

const said = (page) => page.locator("#busy-text").innerText();
const done = (page, label) => (ms) => page.locator("#busy-text", { hasText: new RegExp(`^${label}: (done|refused)`) }).waitFor({ timeout: ms });
const firstRow = (page) => page.locator("#rows tr").first();

await step("tc-fund-release", 1280, async (page, click, waitFor, say) => {
  await page.goto(app, { waitUntil: "domcontentloaded", timeout: 90000 });
  await page.locator("#t-ms").scrollIntoViewIfNeeded();
  await click(page.getByRole("button", { name: "Fund" }));
  await waitFor(done(page, "Fund"), 240000);
  const funded = await said(page);
  const id = (await firstRow(page).locator(".id").innerText()).trim();
  await click(firstRow(page).getByRole("button", { name: "Send proof" }));
  await waitFor(done(page, "Proof"), 240000);
  const row = await firstRow(page).innerText();
  const links = await firstRow(page).locator("a").evaluateAll((as) => as.map((a) => [a.textContent, a.href]));
  result.release = { id, funded, said: await said(page), row, links };
  say(`${id}: ${await said(page)}`);
  return /Fund: done/.test(funded) && /Proof: done/.test(await said(page)) && /released|paid/i.test(row);
});

await step("tc-fund-refund", 1280, async (page, click, waitFor, say) => {
  await page.goto(app, { waitUntil: "domcontentloaded", timeout: 90000 });
  await page.locator("#t-ms").scrollIntoViewIfNeeded();
  await page.locator("#minutes").fill("1");
  await click(page.getByRole("button", { name: "Fund" }));
  await waitFor(done(page, "Fund"), 240000);
  const id = (await firstRow(page).locator(".id").innerText()).trim();
  // the deadline: the table redraws itself when it passes, and Refund shows
  await waitFor((ms) => firstRow(page).getByRole("button", { name: "Refund" }).waitFor({ timeout: ms }), 180000);
  await click(firstRow(page).getByRole("button", { name: "Refund" }));
  await waitFor(done(page, "Refund"), 240000);
  const row = await firstRow(page).innerText();
  const links = await firstRow(page).locator("a").evaluateAll((as) => as.map((a) => [a.textContent, a.href]));
  result.refund = { id, said: await said(page), row, links };
  say(`${id}: ${await said(page)}`);
  return /Refund: done/.test(await said(page)) && /refund/i.test(row);
});

fs.writeFileSync(path.join(out, only ? `tc-walk-${only}.json` : "tc-walk.json"), JSON.stringify(result, null, 1));
await browser.close();
process.exit(fails ? 1 : 0);
