// A recording of one live /near/ run from its public URL, for near/web/knos-near.mp4: a fresh browser at 1280x800 opens
// the first screen, asks "Will it work?" of the sample paper, orders the proof, and stays on each step long enough to
// read it, with a caption saying what to watch: the cap, the answer, the receipt, reuse, the counters and the one call
// for agents. It writes the times each step showed and 3 screenshots.
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
    c.style.display = text ? "" : "none";   // no caption while a step runs, so none covers it
  }, [sel, nth, text]);
  await page.waitForTimeout(ms);
};
await page.goto(url, { waitUntil: "load", timeout: 120000 });
await page.locator("#go:not([disabled])").waitFor({ timeout: 60000 });
await page.evaluate(() => scrollTo(0, 0));
await page.waitForTimeout(1500);                       // the one page settles its first paint
mark("open");
await page.screenshot({ path: path.join(out, "1-first.png") });
await page.waitForTimeout(1000);                       // the question, its answer and what checking costs
await focus(null, 0, "Why does good research take 17 years to reach people?", 1500);
await focus("#ask", 0, "An R&D lead pastes a paper link and asks: will it work?", 1500);
await page.locator("#go").click();
mark("click");
await page.locator("#look .offer button").waitFor({ timeout: 60000 });
mark("claim shown");
await focus("#look .answer", 0, "The one rule: the first proof pays what you put behind the claim", 2000);
await focus("#claim-amount", 0, "The buyer puts 10 test USDC behind the claim", 1500);
await page.screenshot({ path: path.join(out, "2-claim.png") });
await focus("#look .card", 1, "The paper's own claim, word for word", 1500);
await page.locator("#look .offer button").click();
mark("order");
await focus(null, 0, "Two agents ran it against the locked test; NEAR records and pays each step", 0);
await page.locator(".receipt-card").waitFor({ timeout: 120000 });
mark("receipt");
await focus("#steps li", 2, "Agents work against a locked test; the cap blocks an over-budget step", 2500);
await focus("#steps li", 3, "The answer: the paper's number beside the one measured now", 2000);
await page.locator("#steps li").nth(4).locator("button").click();
await page.locator("#steps li").nth(4).locator("[role=status]").filter({ hasText: /^Counted|^Not counted/ }).waitFor({ timeout: 30000 });
await focus("#steps li", 4, "The code you got, at work: 100,000 visitors counted in 1.5 kilobytes", 2000);
await focus(".receipt-card", 0, "The receipt on NEAR testnet: your 10 test USDC, split between agent A and Knos", 2500);
await focus(".receipt-card .log", 0, "What each step cost, each with its record", 1500);
await page.locator(".receipt-card button").click();
mark("again");
await page.locator(".receipt-card [role=status]").filter({ hasText: /^Free|Not run/ }).waitFor({ timeout: 60000 });
await focus(".receipt-card [role=status]", 0, "The same claim again: free, the first proof reused", 2500);
await page.screenshot({ path: path.join(out, "3-got.png") });
await focus(".facts .counters", 0, "Live counters, read from NEAR", 1500);
await focus(".facts .snip", 0, "One call runs it all for an agent", 2000);
mark("end");
const video = page.video();
await ctx.close();
fs.renameSync(await video.path(), path.join(out, "run.webm"));
fs.writeFileSync(path.join(out, "marks.json"), JSON.stringify(marks, null, 1));
console.log(JSON.stringify(marks));
await browser.close();
