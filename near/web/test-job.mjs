// The stranger's walk of the NEAR app (spec S1): a fresh browser, no storage, only the page.
//   node near/web/test-job.mjs <app URL, e.g. http://127.0.0.1:8790/> <blank page URL with the button> <out dir>
// U3: post a job; two agents take it; only the passing one is paid (clicks, seconds, the transactions).
// U4: agent B's two guardrails, each refused on chain with its transaction.
// U5: a blank page of another origin embeds the button with one script tag; it shows a 1Click dry quote, then pays the
// bid on testnet. Screenshots at 390 and 1280 px. Writes <out>/near-walk.json; exits 1 when a step fails.
import fs from "node:fs";
import path from "node:path";
import { chromium } from "playwright";

const [app, blank, out = "near-walk"] = process.argv.slice(2);
fs.mkdirSync(out, { recursive: true });
const browser = await chromium.launch();
const result = { app, blank, steps: [] };
let fails = 0;

async function step(name, width, run, limit = 3) {
  const ctx = await browser.newContext({ viewport: { width, height: width < 700 ? 844 : 800 } });
  const page = await ctx.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  let clicks = 0, wait = 0, ok = false, note = "";
  const t0 = Date.now();
  const click = async (loc) => { clicks++; await loc.click(); };
  const waitFor = async (fn, ms) => { const w0 = Date.now(); await fn(ms); wait += Date.now() - w0; };   // chain time, logged apart
  try { ok = await run(page, click, waitFor, (n) => { note = n; }); } catch (e) { note = String(e).slice(0, 300); }
  const secs = (Date.now() - t0) / 1000, own = Math.round((secs - wait / 1000) * 10) / 10;
  await page.screenshot({ path: path.join(out, `${name}-${width}.png`), fullPage: false });
  const row = { name, width, ok, clicks, seconds_total: Math.round(secs * 10) / 10, seconds_without_chain: own, seconds_on_chain: Math.round(wait / 100) / 10, note, errors };
  result.steps.push(row);
  const pass = ok && clicks <= limit && own <= 60 && !errors.length;
  if (!pass) fails++;
  console.log(pass ? "ok  " : "FAIL", JSON.stringify(row));
  await ctx.close();
  return row;
}

// U3 at 1280 (the transactions are real; one job), then the first screen at 390
await step("u3-post-a-job", 1280, async (page, click, waitFor, say) => {
  await page.goto(app, { waitUntil: "domcontentloaded" });
  await click(page.getByRole("button", { name: "Post a job" }));
  await waitFor((ms) => page.locator("#busy-text", { hasText: /^Paid:|The run stopped|Not posted/ }).waitFor({ timeout: ms }), 300000);
  const said = await page.locator("#busy-text").innerText();
  await page.locator("#t-job").scrollIntoViewIfNeeded();
  const rows = await page.locator("#agents tr").allInnerTexts();
  const links = await page.locator("#jobline a, #agents a").evaluateAll((as) => as.map((a) => [a.textContent, a.href]));
  result.u3 = { said, rows, links };
  say(said);
  return /^Paid:/.test(said) && rows.some((r) => /agent-a[\s\S]*passed[\s\S]*1000/.test(r)) && rows.some((r) => /agent-b[\s\S]*failed[\s\S]*\b0\b/.test(r));
});
await step("near-first-screen", 390, async (page) => { await page.goto(app, { waitUntil: "domcontentloaded" }); return true; }, 0);

// U4
await step("u4-guardrails", 1280, async (page, click, waitFor, say) => {
  await page.goto(app, { waitUntil: "domcontentloaded" });
  await page.locator("#t-guard").scrollIntoViewIfNeeded();
  await click(page.getByRole("button", { name: "Try both" }));
  await waitFor((ms) => page.locator("#guards li").nth(1).waitFor({ timeout: ms }), 300000);
  const items = await page.locator("#guards li").allInnerTexts();
  const links = await page.locator("#guards a").evaluateAll((as) => as.map((a) => a.href));
  result.u4 = { items, links };
  say(items.join(" | "));
  return items.length === 2 && items.every((t) => t.startsWith("refused")) && links.length === 2;
});

// U5: the blank page of another origin
for (const width of [1280, 390]) {
  await step(`u5-pay-with-any-wallet`, width, async (page, click, waitFor, say) => {
    await page.goto(blank, { waitUntil: "networkidle" });
    const btn = page.getByRole("button", { name: "Pay with any wallet" });
    await click(btn);
    const outLoc = page.locator("[data-out]");
    await waitFor((ms) => outLoc.filter({ hasText: /arrives as|No quote|did not answer/ }).waitFor({ timeout: ms }), 60000);
    const quote = await outLoc.innerText();
    let paid = "";
    if (width === 1280 && /arrives as/.test(quote)) {
      await click(page.getByRole("button", { name: /^Pay \d+ test units/ }));
      await waitFor((ms) => outLoc.filter({ hasText: /test units on testnet|Not paid/ }).waitFor({ timeout: ms }), 300000);
      paid = await outLoc.innerText();
      result.u5 = { quote, paid, tx: await page.locator("[data-out] a").getAttribute("href").catch(() => "") };
    }
    say(quote + (paid ? " | " + paid : ""));
    return /arrives as/.test(quote) && (width !== 1280 || /^Paid [0-9]+ test units on testnet/.test(paid));
  });
}
await browser.close();
fs.writeFileSync(path.join(out, "near-walk.json"), JSON.stringify(result, null, 1));
console.log(fails ? `FAIL near walk: ${fails} step(s)` : "PASS near walk: every step");
process.exit(fails ? 1 : 0);
