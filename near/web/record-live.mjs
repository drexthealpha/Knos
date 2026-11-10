// A recording of one live /near/ run from its public URL, for near/web/knos-near.mp4: a fresh browser at 1280x800 opens
// the first screen, asks "Will it work?" of the sample paper, orders the proof, and stays on each step long enough to
// read it, with a caption saying what to watch. It writes the times each step showed and 3 screenshots.
//   node near/web/record-live.mjs <url> <out dir>   -> <out>/run.webm, <out>/marks.json, <out>/1-first.png, 2-claim.png, 3-got.png
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
// each held screen says what to watch: the part is centred and outlined, with a caption at the foot of the frame
const focus = async (sel, nth, text, ms) => {
  await page.evaluate(([sel, nth, text]) => {
    for (const e of document.querySelectorAll(".rec-on")) { e.classList.remove("rec-on"); e.style.outline = ""; }
    const e = sel ? document.querySelectorAll(sel)[nth] : null;
    if (e) { e.scrollIntoView({ block: "center" }); e.classList.add("rec-on"); e.style.outline = "4px solid #2b3bb8"; e.style.outlineOffset = "4px"; }
    let c = document.getElementById("rec-caption");
    if (!c) { c = document.createElement("div"); c.id = "rec-caption"; c.style.cssText = "position:fixed;left:50%;bottom:28px;transform:translateX(-50%);max-width:90%;padding:14px 24px;border-radius:14px;background:#151822;color:#fff;font:600 26px/1.3 system-ui,sans-serif;z-index:99;text-align:center"; document.body.append(c); }
    c.textContent = text;
  }, [sel, nth, text]);
  await page.waitForTimeout(ms);
};
await page.goto(url, { waitUntil: "load", timeout: 120000 });
await page.locator("#go:not([disabled])").waitFor({ timeout: 60000 });
mark("open");
await page.screenshot({ path: path.join(out, "1-first.png") });
await page.waitForTimeout(2500);                       // line 1 and the 17 years
await focus("#ask", 0, "An R&D lead pastes a paper link and asks: will it work?", 3500);
await page.locator("#go").click();
mark("click");
await page.locator("#look button").waitFor({ timeout: 60000 });
mark("claim shown");
await focus("#look .answer", 0, "Not proven yet, and one offer: prove it for $500", 3500);
await focus("#look .card", 1, "The paper's own claim, word for word", 3500);
await page.screenshot({ path: path.join(out, "2-claim.png") });
await focus("#look .card", 2, "In plain words, written by a small AI", 3000);
await focus("#look .odds", 0, "The odds it holds, kept on NEAR until a proof settles them", 3000);
await focus("#look .answer", 0, "Order the proof: answer in under a minute", 2500);
await page.locator("#look .offer button").click();
mark("order");
await focus(null, 0, "Ordered. Watch each step and the clock", 300);
await page.locator("#prove").filter({ hasText: /now read (Yes|No)|not settled/ }).waitFor({ timeout: 90000 });
mark("settled");
await focus("#steps li", 0, "1. The test is locked before anyone works", 3000);
await focus("#steps li", 1, "2. Two agents rerun the result: one passes, one fails", 4000);
await focus("#steps li", 2, "3. The paper's number beside the one measured now", 4500);
await focus("#steps li", 3, "You got the verified code. The odds on NEAR now read Yes, for good", 1000);
await page.screenshot({ path: path.join(out, "3-got.png") });
await page.waitForTimeout(4000);
mark("end");
const video = page.video();
await ctx.close();
fs.renameSync(await video.path(), path.join(out, "run.webm"));
fs.writeFileSync(path.join(out, "marks.json"), JSON.stringify(marks, null, 1));
console.log(JSON.stringify(marks));
await browser.close();
