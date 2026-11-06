// A recording of one live /near/ run, for near-submit/demo.mp4: a fresh browser at 1280x720 records the page from its
// public URL through one click on Post a job to the payment, and writes the times each step showed (for captions).
//   node near/web/record-live.mjs <url> <out dir>      -> <out>/run.webm and <out>/marks.json
import fs from "node:fs";
import path from "node:path";
import { chromium } from "playwright";

const [url = "https://drexthealpha.github.io/Knos/near/", out = "near-video"] = process.argv.slice(2);
fs.mkdirSync(out, { recursive: true });
const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1280, height: 720 }, recordVideo: { dir: out, size: { width: 1280, height: 720 } } });
const page = await ctx.newPage();
const t0 = Date.now(), marks = [];
const mark = (what) => marks.push({ what, t: (Date.now() - t0) / 1000 });
await page.goto(url, { waitUntil: "domcontentloaded", timeout: 120000 });
await page.locator("#busy-text").filter({ hasText: /Live on NEAR testnet/ }).waitFor({ timeout: 120000 });
mark("open");
await page.waitForTimeout(2500);
await page.getByRole("button", { name: "Post a job" }).click();
mark("click");
let last = "";
for (let i = 0; i < 120; i++) {
  await page.waitForTimeout(1000);
  const s = await page.locator("#busy-text").innerText();
  if (s !== last) { last = s; mark(s.slice(0, 80)); }
  if (/^Paid:|^Replay:|^The run stopped/.test(s)) break;
}
mark("done");
await page.waitForTimeout(1500);
await page.locator("#t-job").scrollIntoViewIfNeeded();
await page.waitForTimeout(4000);
mark("job shown");
const video = page.video();
await ctx.close();
fs.renameSync(await video.path(), path.join(out, "run.webm"));
fs.writeFileSync(path.join(out, "marks.json"), JSON.stringify(marks, null, 1));
console.log(JSON.stringify(marks));
await browser.close();
