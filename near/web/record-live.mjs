// A recording of one live run from the public site, for near/web/knos-near.mp4: a fresh browser at 1280x800 opens the
// front door, tries the sample (answered on that screen), goes on to the Prove page and orders the proof, then shows the
// claims with their two markets, the browser's own check of a locked test against NEAR, and the one call for agents;
// each screen holds long enough to read, with a caption saying what to watch. It writes the times each step showed and
// 3 screenshots.
//   node near/web/record-live.mjs <url> <out dir>   -> <out>/run.webm, <out>/marks.json, <out>/1-first.png, 2-claim.png, 3-got.png
import fs from "node:fs";
import path from "node:path";
import { chromium } from "playwright";

const [url = "https://drexthealpha.github.io/Knos/", out = "near-video"] = process.argv.slice(2);
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
    if (!c) { c = document.createElement("div"); c.id = "rec-caption"; c.style.cssText = "position:fixed;left:50%;bottom:28px;transform:translateX(-50%);max-width:90%;padding:14px 24px;border-radius:14px;background:#151822;color:#fff;font:600 22px/1.3 system-ui,sans-serif;z-index:99;text-align:center"; document.body.append(c); }
    c.textContent = text;
    c.style.display = text ? "" : "none";   // no caption while a step runs, so none covers it
  }, [sel, nth, text]);
  await page.waitForTimeout(ms);
};
// the one call for agents, run for real while the page is recorded; its answer is shown at the end
const flow = fetch("https://knos.onrender.com/api/near/claim/flow", { method: "POST", headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ url: "https://doi.org/10.46298/dmtcs.3545", amount: 10 }) }).then((r) => r.json()).catch((e) => ({ ok: false, why: String(e) }));
const site = url.replace(/[^/]*$/, "");
await page.goto(url, { waitUntil: "load", timeout: 120000 });
await page.locator("#sample:not([disabled])").waitFor({ timeout: 60000 });
await page.waitForTimeout(1500);                       // the front door settles its first paint
await page.screenshot({ path: path.join(out, "1-first.png") });
mark("open");                                          // the video starts here: a caption on every screen, none held over 3 s
await focus(".q", 0, "A good result waits 17 years in a paper before people use it", 2500);
await focus("h1", 0, "Ask Knos anything about research", 1500);
await page.locator("#sample").click();
await page.locator("#out .verdict").waitFor({ timeout: 60000 });
await focus("#out", 0, "The answer at once: what is proved, by which locked test", 2000);
await page.locator("#out a.next").click();
await page.locator("#ask").waitFor({ timeout: 60000 });
await page.waitForFunction(() => !/reading/.test((document.querySelector(".facts .counters") || {}).textContent || ""), null, { timeout: 30000 }).catch(() => {});   // the counters read before they are filmed
mark("click");
await page.locator("#look .offer button").waitFor({ timeout: 60000 });
mark("claim shown");
await focus("#look .answer", 0, "The one rule: the first proof pays what you put behind the claim", 1500);
await focus("#claim-amount", 0, "The buyer puts 10 test USDC behind the claim", 1000);
await page.screenshot({ path: path.join(out, "2-claim.png") });
await focus("#look .card", 1, "The paper's own claim, word for word", 1000);
await page.locator("#look .offer button").click();
mark("order");
await focus(null, 0, "Now prove it live: two agents race a test locked on NEAR", 0);
await page.locator(".receipt-card").waitFor({ timeout: 120000 });
mark("receipt");
await focus("#steps li", 2, "Agent B tries to overspend; NEAR refuses it", 2500);
await focus("#steps li", 3, "It holds: the paper's number beside the one measured now", 2000);
await focus("#steps li", 4, "", 0);                  // the count runs in view, its own clock ticking, no caption over it
await page.locator("#steps li").nth(4).locator("button").click();
mark("count");
await page.locator("#steps li").nth(4).locator("[role=status]").filter({ hasText: /^There were|^Not counted/ }).waitFor({ timeout: 30000 });
mark("counted");
await focus("#steps li", 4, "The code you got, at work: 100,000 visitors counted in 1.5 kilobytes", 1500);
await focus(".receipt-card", 0, "The money moves: 90% to the agent whose code passed, 10% to Knos", 2500);
await focus(".receipt-card .log", 0, "What each step cost, each with its record", 1000);
await page.locator(".receipt-card button").click();
mark("again");
await page.locator(".receipt-card [role=status]").filter({ hasText: /^Free|Not run/ }).waitFor({ timeout: 60000 });
await focus(".receipt-card [role=status]", 0, "The same claim again: free, the first proof reused", 2000);
await page.screenshot({ path: path.join(out, "3-got.png") });
await focus(".facts .counters", 0, "Live counters, read from NEAR", 1500);
await focus("#t-why", 0, "Why Knos: the middleman it removes, and why a lab could not do this", 2000);
await page.goto(site + "claims/", { waitUntil: "load" });
await page.waitForFunction(() => ![...document.querySelectorAll("#claims td")].some((td) => td.textContent === "reading"), null, { timeout: 60000 });
await focus("#claims", 0, "Four claims from real papers, each with two markets on NEAR: will it hold, will 100 test USDC back it", 2500);
await page.goto(site + "claim/jump-hash/", { waitUntil: "load" });
await page.locator("#verify").click();
await page.locator("#verdict").filter({ hasText: /VERIFIED|Not checked/ }).waitFor({ timeout: 60000 });
await focus("#verdict", 0, "Your browser checks the locked test against the hash NEAR locked: VERIFIED", 2000);
await page.locator("#tamper").click();
await focus("#verdict", 0, "Change one byte of the test: NOT VERIFIED", 2000);
await page.goto(site + "agents/", { waitUntil: "load" });
await focus("pre", 0, "One call runs it all for an agent", 1000);
const answer = await flow;
await page.evaluate((x) => {
  const pre = document.createElement("pre"); pre.id = "rec-flow";
  pre.style.cssText = "margin:8px 0;padding:12px;border-radius:10px;background:#151822;color:#e8e8e8;font:13px/1.5 ui-monospace,monospace;white-space:pre-wrap";
  const r = x.receipt || {};
  pre.textContent = JSON.stringify({ verdict: { holds: (x.verdict || {}).holds }, cap: { refused: (x.cap || {}).refused }, paid: x.paid, settled: x.settled,
    receipt: { buyer_usd: r.buyer_usd, agent_usd: r.agent_usd, knos_usd: r.knos_usd } }, null, 1);
  document.querySelector("pre").after(pre);
}, answer);
await focus("#rec-flow", 0, "Part of the answer that call returned during this recording", 2000);
mark("end");                                           // the video ends on the agent call's answer
const video = page.video();
await ctx.close();
fs.renameSync(await video.path(), path.join(out, "run.webm"));
fs.writeFileSync(path.join(out, "marks.json"), JSON.stringify(marks, null, 1));
console.log(JSON.stringify(marks));
await browser.close();
