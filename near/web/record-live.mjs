// A recording of one live /near/ run from its public URL, for near/web/knos-near.mp4: a fresh browser at 1280x800 opens
// the first screen, presses the one button, and stays on each step long enough to read it: the paper, the two tries,
// the payment, the product page the small AI wrote, then Buy. It writes the times each step showed and 3 screenshots.
//   node near/web/record-live.mjs <url> <out dir>   -> <out>/run.webm, <out>/marks.json, <out>/1-first.png, 2-paid.png, 3-bought.png
import fs from "node:fs";
import path from "node:path";
import { chromium } from "playwright";

const [url = "https://drexthealpha.github.io/Knos/near/", out = "near-video"] = process.argv.slice(2);
fs.mkdirSync(out, { recursive: true });
const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 }, colorScheme: "light", recordVideo: { dir: out, size: { width: 1280, height: 800 } } });
const page = await ctx.newPage();
const t0 = Date.now(), marks = [];
const mark = (what) => marks.push({ what, t: +((Date.now() - t0) / 1000).toFixed(1) });
await page.goto(url, { waitUntil: "load", timeout: 120000 });
await page.locator("#go:not([disabled])").waitFor({ timeout: 60000 });
mark("open");
await page.screenshot({ path: path.join(out, "1-first.png") });
await page.waitForTimeout(7000);                       // line 1 and the 17 years, long enough to read
await page.locator("#go").click();
mark("click");
let seen = 0;
for (let i = 0; i < 240; i++) {
  await page.waitForTimeout(250);
  const n = await page.locator("#steps li").count();
  if (n !== seen) { seen = n; mark(`step ${n}: ${(await page.locator("#steps li h3").last().innerText()).slice(0, 60)}`); }
  if (await page.locator("#product:not([hidden]), #steps li.stop").count()) break;
}
mark("product");
await page.locator("#steps li").nth(0).scrollIntoViewIfNeeded();
await page.waitForTimeout(6000);                       // the paper's own sentence
await page.locator("#steps li").nth(1).scrollIntoViewIfNeeded();
await page.waitForTimeout(6000);                       // the two tries and the check
await page.locator("#steps li").nth(2).scrollIntoViewIfNeeded();
await page.screenshot({ path: path.join(out, "2-paid.png") });
await page.waitForTimeout(4000);                       // paid
await page.locator("#product").scrollIntoViewIfNeeded();
await page.waitForTimeout(5000);                       // the product page
const buy = page.locator("#product button");
if (await buy.count()) {
  await buy.click();
  mark("buy");
  await page.locator("#product [role=status]").filter({ hasText: /^Bought|^Not bought/ }).waitFor({ timeout: 60000 });
  mark((await page.locator("#product [role=status]").innerText()).slice(0, 80));
  await page.locator("#product").scrollIntoViewIfNeeded();
  await page.waitForTimeout(800);
  await page.screenshot({ path: path.join(out, "3-bought.png") });
  await page.waitForTimeout(7000);                     // bought, what you got, where to try it
}
mark("end");
const video = page.video();
await ctx.close();
fs.renameSync(await video.path(), path.join(out, "run.webm"));
fs.writeFileSync(path.join(out, "marks.json"), JSON.stringify(marks, null, 1));
console.log(JSON.stringify(marks));
await browser.close();
