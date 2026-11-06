// The stranger on the live /near/ page (spec S1): a fresh browser, the public URL only. Reads the first screen, clicks
// Post a job once, follows the live testnet run to the payment. Screenshots at each step, clicks and seconds.
//   node near/web/test-live.mjs <url, e.g. https://drexthealpha.github.io/Knos/near/> <out dir>
import fs from "node:fs";
import path from "node:path";
import { chromium } from "playwright";

const [url = "https://drexthealpha.github.io/Knos/near/", out = "near-live"] = process.argv.slice(2);
fs.mkdirSync(out, { recursive: true });
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
const errors = [];
page.on("pageerror", (e) => errors.push(String(e).slice(0, 200)));
const t0 = Date.now(), steps = [];
const shot = async (name, note) => { await page.screenshot({ path: path.join(out, `${name}.png`) }); steps.push({ name, s: Math.round((Date.now() - t0) / 100) / 10, note }); };
await page.goto(url, { waitUntil: "domcontentloaded", timeout: 120000 });
await page.locator("#busy-text").filter({ hasText: /Live on NEAR testnet|Last run shown/ }).waitFor({ timeout: 120000 });
await shot("1-first-screen", await page.locator("#busy-text").innerText());
const btn = page.getByRole("button", { name: "Post a job" });
const enabled = await btn.isEnabled();
let clicks = 0;
if (enabled) { await btn.click(); clicks++; }
await shot("2-clicked", await page.locator("#busy-text").innerText());
let said = "";
for (let i = 0; i < 100; i++) {
  await page.waitForTimeout(3000);
  said = await page.locator("#busy-text").innerText();
  if (/^Paid:|^Replay:|^The run stopped/.test(said)) break;
  if (i === 10) await shot("3-running", said);
}
await page.locator("#t-job").scrollIntoViewIfNeeded().catch(() => {});
await shot("4-paid", said);
const rows = await page.locator("#agents tr").allInnerTexts().catch(() => []);
const links = await page.locator("#jobline a, #agents a").evaluateAll((as) => as.map((a) => [a.textContent, a.href])).catch(() => []);
const result = { url, enabled, clicks, said, rows, links, steps, errors, seconds: Math.round((Date.now() - t0) / 100) / 10 };
fs.writeFileSync(path.join(out, "near-live.json"), JSON.stringify(result, null, 1));
console.log(JSON.stringify({ enabled, clicks, said, seconds: result.seconds, rows, errors }));
await browser.close();
