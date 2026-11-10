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
// each held screen says what to watch: the step is centred and outlined, with a caption at the foot of the frame
const focus = async (sel, nth, text, ms) => {
  await page.evaluate(([sel, nth, text]) => {
    for (const e of document.querySelectorAll(".rec-on")) { e.classList.remove("rec-on"); e.style.outline = ""; }
    const e = document.querySelectorAll(sel)[nth];
    if (e) { e.scrollIntoView({ block: "center" }); e.classList.add("rec-on"); e.style.outline = "4px solid #2b3bb8"; e.style.outlineOffset = "4px"; }
    let c = document.getElementById("rec-caption");
    if (!c) { c = document.createElement("div"); c.id = "rec-caption"; c.style.cssText = "position:fixed;left:50%;bottom:28px;transform:translateX(-50%);max-width:90%;padding:14px 24px;border-radius:14px;background:#151822;color:#fff;font:600 26px/1.3 system-ui,sans-serif;z-index:99;text-align:center"; document.body.append(c); }
    c.textContent = text;
  }, [sel, nth, text]);
  await page.waitForTimeout(ms);
};
await focus("#steps li", 0, "1. A real paper from 2007, in its own words", 5000);
await focus("#steps li", 1, "2. Two helpers sent code. The check passed one, failed the other", 6000);
await page.screenshot({ path: path.join(out, "2-paid.png") });
await focus("#steps li", 2, "3. The helper whose code works is paid, on NEAR", 5000);
await focus("#product", 0, "4. A small AI wrote the product page. Now buy it", 4000);
const buy = page.locator("#product button");
if (await buy.count()) {
  await buy.click();
  mark("buy");
  await page.locator("#product [role=status]").filter({ hasText: /^Bought|^Not bought/ }).waitFor({ timeout: 60000 });
  mark((await page.locator("#product [role=status]").innerText()).slice(0, 80));
  await focus("#product", 0, "5. Bought with test money. You got the code that passed", 800);
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
