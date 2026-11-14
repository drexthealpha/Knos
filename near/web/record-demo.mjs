// The NEAR demo video (near/web/knos-near.mp4), recorded from one real order on the live site: a fresh browser at
// 1280x720 opens the front door, orders a proof of one live claim, waits for its four steps and its receipt, then reads
// the order's transactions from NEAR testnet on the site's own transaction page (the explorer shows a bot check to a
// fresh browser) and ends on one card. Every caption is at most 8 words, 36 px tall, and says only what the page shows:
// when agent A ran its fixed program, the caption says so. It writes each page's video and the times to cut.
//   node near/web/record-demo.mjs <out dir>   -> <out>/a.webm (the order), <out>/b.webm (NEAR and the card), <out>/cuts.json
import fs from "node:fs";
import path from "node:path";
import { chromium } from "playwright";

const out = process.argv[2] || "near-demo";
const SITE = "https://drexthealpha.github.io/Knos/";
const REFUSED = "FShgZgDA6pUwY3KxJ4yi76CDBGX8F1oiihR5NN97BFgw";   // W3: a payout to a lookalike of agent-a2, refused by the jobs contract
fs.mkdirSync(out, { recursive: true });
const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1280, height: 720 }, colorScheme: "light", recordVideo: { dir: out, size: { width: 1280, height: 720 } } });
const cuts = [];
// a caption at the foot of the frame, and an outline on the part it names; "" hides the caption
const say = async (page, text, sel, nth = 0) => {
  if (text.split(/\s+/).filter(Boolean).length > 8) throw new Error("caption over 8 words: " + text);
  await page.evaluate(([text, sel, nth]) => {
    for (const e of document.querySelectorAll(".rec-on")) { e.classList.remove("rec-on"); e.style.outline = ""; }
    const e = sel ? document.querySelectorAll(sel)[nth] : null;
    if (e) { e.scrollIntoView({ block: "center" }); e.classList.add("rec-on"); e.style.outline = "4px solid #2b3bb8"; e.style.outlineOffset = "4px"; }
    let c = document.getElementById("rec-caption");
    if (!c) { c = document.createElement("div"); c.id = "rec-caption"; c.style.cssText = "position:fixed;left:50%;bottom:24px;transform:translateX(-50%);max-width:92%;padding:14px 28px;border-radius:16px;background:#151822;color:#fff;font:700 36px/1.25 system-ui,sans-serif;z-index:2147483647;text-align:center;box-shadow:0 6px 24px rgba(0,0,0,.25)"; document.body.append(c); }
    c.textContent = text; c.style.display = text ? "" : "none";
  }, [text, sel, nth]);
};
const clock = (t0) => () => +((Date.now() - t0) / 1000).toFixed(2);

// ---- page A: the order -----------------------------------------------------------------------------------------
const a = await ctx.newPage(); const ta = clock(Date.now());
await a.goto(SITE, { waitUntil: "load", timeout: 120000 });
await a.locator("#sample:not([disabled])").waitFor({ timeout: 60000 });
await a.waitForTimeout(1200);
await say(a, "Good research waits 17 years to reach people", "h1");
let s = ta(); await a.waitForTimeout(3600); cuts.push({ f: "a", from: s, to: ta(), what: "problem" });
await say(a, "Pick one paper's claim: HyperLogLog", "#sample");
s = ta(); await a.waitForTimeout(900);
await a.locator("#sample").click();
await a.locator("#out .verdict").waitFor({ timeout: 60000 });
await say(a, "Its test is locked by its hash", "#out");
await a.waitForTimeout(1800); cuts.push({ f: "a", from: s, to: ta(), what: "claim and hash" });
await a.locator("#out a.next").click();
await a.locator("#look .offer button").waitFor({ timeout: 90000 });
await a.waitForTimeout(800);
await say(a, "One press orders a proof: 10 test USDC", "#look .offer button");
s = ta(); await a.waitForTimeout(1600);
await a.locator("#look .offer button").click();
const tOrder = ta();
await a.locator("#steps li").first().waitFor({ timeout: 60000 });
await say(a, "", null);
await a.waitForTimeout(1200); cuts.push({ f: "a", from: s, to: ta(), what: "the press" });
// the steps run on their own; the cut skips the wait and keeps each step once it shows
await a.locator("#steps li").nth(1).filter({ hasText: /Agent A's code/ }).waitFor({ timeout: 180000 }).catch(() => {});
const writer = await a.locator("#steps li").nth(1).innerText().catch(() => "");
const model = /code was written by/.test(writer);
const priv = /private: its attestation and the answer's signature verified/.test(writer);
await say(a, model ? "A private model on NEAR AI wrote it" : "This run: agent A's fixed program, no model", "#steps li", 1);
s = ta(); await a.waitForTimeout(2600);
if (model) { await say(a, priv ? "Its TEE attestation and signature: verified" : "Its attestation: not verified this time", "#steps li", 1); await a.waitForTimeout(2400); }
cuts.push({ f: "a", from: s, to: ta(), what: model ? "the private model" : "the fixed program" });
const fourth = a.locator("#steps li").nth(3);
await fourth.waitFor({ timeout: 180000 });
const answerText = await fourth.innerText().catch(() => "");
const holds = /Yes, the claim holds/.test(answerText);
await say(a, "A reviewer model may only reject it", "#steps li .vs tr", 3);
s = ta(); await a.waitForTimeout(2600);
await say(a, holds ? "The locked test passed: yes, it holds" : "The page's answer this time", "#steps li", 3);
await a.waitForTimeout(2600); cuts.push({ f: "a", from: s, to: ta(), what: "reviewer and the test" });
await a.locator(".receipt-card").waitFor({ timeout: 180000 });
await a.waitForTimeout(800);
await say(a, "Receipt: 9 to the agent, 1 to Knos", ".receipt-card");
s = ta(); await a.waitForTimeout(3600); cuts.push({ f: "a", from: s, to: ta(), what: "receipt" });
const links = await a.evaluate(() => [...document.querySelectorAll(".receipt-card a, #steps a")].map((x) => ({ text: x.closest("tr, p, li")?.innerText.slice(0, 120) || x.textContent, href: x.href })).filter((x) => /tx\/\?h=/.test(x.href)));
const hashOf = (re) => { const l = links.find((x) => re.test(x.text)); return l ? new URL(l.href).searchParams.get("h") : null; };
const jobTx = hashOf(/job and its locked test posted|locked test posted/i) || (links[0] && new URL(links[0].href).searchParams.get("h"));
const splitTx = hashOf(/held it with the job|in one transaction|the split|release/i);
const summary = { order_at_s: tOrder, model, private: priv, holds, writer: writer.slice(0, 400), job_tx: jobTx, split_tx: splitTx, links };
await say(a, "", null);
await a.close();

// ---- page B: the same order on NEAR, then the card --------------------------------------------------------------
const b = await ctx.newPage(); const tb = clock(Date.now());
const tx = async (h, caption, ms) => {
  await b.goto(SITE + "tx/?h=" + h, { waitUntil: "load" });
  await b.waitForFunction(() => !/Reading it/.test(document.getElementById("verdict").textContent), null, { timeout: 60000 });
  await say(b, caption, "#moved li") ;
  const t = tb(); await b.waitForTimeout(ms); cuts.push({ f: "b", from: t, to: tb(), what: caption });
};
if (jobTx) await tx(jobTx, "The locked test's job, read from NEAR", 3200);
if (splitTx) await tx(splitTx, "The contract paid: 90% agent, 10% Knos", 4600);
await tx(REFUSED, "Refused: a payout to a lookalike account", 3600);
await b.setContent(`<body style="margin:0;height:100vh;display:grid;place-items:center;background:#151822;color:#fff;font-family:system-ui,sans-serif;text-align:center">
  <div><p style="font:700 52px/1.25 system-ui;max-width:1100px;margin:0 auto 40px">Knos turns any research into a product people use, in days, not years.</p>
  <p style="font:500 34px/1.5 ui-monospace,monospace;margin:0">drexthealpha.github.io/Knos</p><p style="font:500 34px/1.5 ui-monospace,monospace;margin:0">github.com/drexthealpha/Knos</p></div></body>`);
let t = tb(); await b.waitForTimeout(4300); cuts.push({ f: "b", from: t, to: tb(), what: "card" });
const va = a.video(), vb = b.video();
await b.close(); await ctx.close();
fs.renameSync(await va.path(), path.join(out, "a.webm"));
fs.renameSync(await vb.path(), path.join(out, "b.webm"));
fs.writeFileSync(path.join(out, "cuts.json"), JSON.stringify({ summary, cuts }, null, 1));
console.log(JSON.stringify({ model, private: priv, holds, job_tx: jobTx, split_tx: splitTx, cuts: cuts.map((c) => c.what + " " + (c.to - c.from).toFixed(1) + "s") }));
await browser.close();
