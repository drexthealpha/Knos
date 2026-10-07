// node tests/web/demo.mjs <site dir> [folder for screenshots]
// The first screen's round (web/demo.js) in headless Chromium, on a page that holds nothing but the site's stylesheet and
// <div id="demo">. The six steps are reached with the keyboard alone, one key a step; each statement is 12 words or fewer; the
// rejected claim, the accepted fix, the token that pays nothing the second time and the disputed month carry their labels (the words of src/knos/ids.py); only recorded counts are shown; the figures are those of demo_data.json; a reader
// who asked for reduced motion gets no animation at all; nothing is asked of any other host; nothing scrolls sideways at
// 320 and 390 px; and the module mounts when web/motion.js is not there. Needs the `playwright` package.
import { createServer } from "node:http";
import { readFileSync, existsSync, mkdirSync } from "node:fs";
import { join, extname, normalize } from "node:path";

const root = process.argv[2], shots = process.argv[3] || "";
if (!root || !existsSync(join(root, "demo.js"))) { console.error("usage: node tests/web/demo.mjs <site dir> [shots dir]"); process.exit(2); }
let chromium;
try { ({ chromium } = (await import("playwright")).default); } catch { console.log("SKIP the playwright package is not installed"); process.exit(0); }
const check = (name, cond, detail) => { if (!cond) { console.error("FAIL", name, detail === undefined ? "" : JSON.stringify(detail)); process.exitCode = 1; } else console.log("ok  ", name); };
const data = JSON.parse(readFileSync(join(root, "demo_data.json"), "utf8"));
const STEPS = ["Fund", "A claim", "Fixed", "Paid", "Replay", "Both sides"];
const ACTS = ["Post the comment", "Check the claim", "Push the fix", "Pay", "Send the same token again", "Compare the two counts"];
const READ = [false, true, false, false, false, true];          // the steps that show something to read before their action
const words = (s) => s.trim().split(/\s+/).filter((w) => /[\p{L}\p{N}]/u.test(w)).length;

const TYPES = { ".html": "text/html", ".js": "text/javascript", ".mjs": "text/javascript", ".css": "text/css", ".json": "application/json", ".svg": "image/svg+xml",
  ".woff2": "font/woff2", ".png": "image/png" };
const PAGE = (offline) => `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>demo</title><link rel="stylesheet" href="app.css"></head><body><main><div id="demo" hidden></div></main>
<script type="module">import { renderDemo } from "./demo.js";
window.__demo = await renderDemo(document.getElementById("demo"), ${offline ? "{ online: () => false }" : "{}"}); window.__mounted = true;</script></body></html>`;
let withMotion = true;
const server = createServer((req, res) => {
  const path = decodeURIComponent(new URL(req.url, "http://x").pathname);
  if (path === "/__demo.html" || path === "/__demo_offline.html") { res.writeHead(200, { "content-type": "text/html" }); return res.end(PAGE(path.includes("offline"))); }
  const file = join(root, normalize(path).replace(/^([/\\])+/, ""));
  if ((path === "/motion.js" && !withMotion) || !file.startsWith(root) || !existsSync(file) || extname(file) === "") { res.writeHead(404); return res.end("no"); }
  res.writeHead(200, { "content-type": TYPES[extname(file)] || "application/octet-stream" });
  res.end(readFileSync(file));
});
await new Promise((r) => server.listen(0, "127.0.0.1", r));
const origin = `http://127.0.0.1:${server.address().port}`;

let browser;
try { browser = await chromium.launch(); } catch (e) { console.log(`SKIP Chromium does not start here (${String(e.message).split("\n")[0]})`); server.close(); process.exit(0); }
if (shots) mkdirSync(shots, { recursive: true });

// what the page says, each statement by itself: the state line, the small lines, the line about the sources
const read = (page) => page.evaluate(() => {
  const el = document.getElementById("demo"), text = (s) => [...el.querySelectorAll(s)].map((n) => n.textContent.replace(/\s+/g, " ").trim()).filter(Boolean);
  return { say: el.querySelector(".kd-say").textContent, mark: el.querySelector(".kd-mark")?.textContent || "", lines: [...text(".kd-say"), ...text(".kd-fine"), ...text(".kd-src"), ...text(".k-kicker"), ...text(".kd-go"), ...text(".kd-quote")],
    step: [...el.querySelectorAll(".k-step")].findIndex((b) => b.getAttribute("aria-current") === "step"), states: [...el.querySelectorAll(".k-step")].map((b) => b.dataset.state),
    badges: text(".kd-scene .kd-badge"), scene: el.querySelector(".kd-scene").textContent.replace(/\s+/g, " "), go: el.querySelector(".kd-go").textContent,
    focus: document.activeElement?.className || document.activeElement?.id || "", sideways: document.documentElement.scrollWidth - document.documentElement.clientWidth,
    running: document.getAnimations().length, animated: window.__animated, links: [...el.querySelectorAll(".kd-scene a")].map((a) => a.href) };
});

async function open(width, { reduce = false, motion = true, offline = false } = {}) {
  withMotion = motion;
  const context = await browser.newContext({ viewport: { width, height: 900 }, reducedMotion: reduce ? "reduce" : "no-preference" });
  const page = await context.newPage(), asked = [], errors = [];
  page.on("request", (r) => asked.push(r.url()));
  page.on("pageerror", (e) => errors.push(String(e)));
  await page.addInitScript(() => { window.__animated = 0; const a = Element.prototype.animate; Element.prototype.animate = function (...x) { window.__animated += 1; return a.apply(this, x); }; });
  await page.goto(`${origin}/${offline ? "__demo_offline" : "__demo"}.html`);
  await page.waitForFunction(() => window.__mounted === true);
  return { page, context, asked, errors };
}

// The whole round with keys only: Tab to the comment box, Enter posts it, then Enter acts and Enter moves on.
async function round(label, width, opts = {}) {
  const { page, context, asked, errors } = await open(width, opts);
  const tag = `${label} ${width}`;
  const first = await read(page);
  check(`${tag}: mounted on step 1, nothing done, nothing moving`, first.step === 0 && first.states.join() === "live,idle,idle,idle,idle,idle" && first.animated === 0 && first.running === 0, first);
  check(`${tag}: the state line is announced politely`, await page.evaluate(() => { const s = document.querySelector("#demo .kd-say"); return s.getAttribute("aria-live") === "polite"; }));
  check(`${tag}: the comment box holds the recorded comment`, await page.evaluate(() => document.getElementById("kd-comment").value) === data.fund.comment);
  for (let n = 0; n < 12 && (await page.evaluate(() => document.activeElement?.id)) !== "kd-comment"; n += 1) await page.keyboard.press("Tab");
  check(`${tag}: Tab reaches the comment box`, (await page.evaluate(() => document.activeElement?.id)) === "kd-comment");
  const seen = [];
  let last = first;
  for (let i = 0; i < STEPS.length; i += 1) {
    // a step that shows something to read is reached first ("Next"); every other step is done by the one key that names it
    const waits = i === 0 || READ[i], before = waits ? await read(page) : last;
    if (waits) check(`${tag}: step ${i + 1} is ${STEPS[i]}, with its action on the button`, before.step === i && before.states[i] === "live" && before.go === ACTS[i], [before.states, before.go]);
    else check(`${tag}: the button names step ${i + 1}'s action before it is reached`, before.go === ACTS[i] && before.step === i - 1, before.go);
    await page.keyboard.press(i % 2 ? " " : "Enter");                  // the one action of the step, by Enter or by Space
    if (i === 3) await page.waitForFunction((to) => document.querySelector("#demo .kd-secs").textContent === to, String(data.paid.seconds));   // the counter stops there
    const after = last = await read(page);
    seen.push({ before, after });
    for (const s of [...before.lines, ...after.lines]) check(`${tag}: step ${i + 1}: "${s.slice(0, 40)}" is 12 words or fewer`, words(s) <= 12, [words(s), s]);
    check(`${tag}: step ${i + 1} changed on one key`, after.step === i && after.states[i] === ([1, 4].includes(i) ? "bad" : "done") /* a disputed month is no refusal: step 6 does not take the refused look */ && after.say !== before.say, after);
    check(`${tag}: step ${i + 1} does not scroll sideways`, before.sideways <= 0 && after.sideways <= 0, [before.sideways, after.sideways]);
    check(`${tag}: step ${i + 1} keeps the focus on the one button`, after.focus.includes("kd-go"), after.focus);
    if (opts.reduce) check(`${tag}: step ${i + 1} moves nothing`, after.running === 0 && after.animated === 0, [after.running, after.animated]);
    if (shots && opts.shot) await page.locator("#demo").screenshot({ path: join(shots, `demo-${width}-${i + 1}-${STEPS[i].toLowerCase().replace(/\s+/g, "-")}.png`), animations: "disabled" });
    if (i < STEPS.length - 1 && READ[i + 1]) { check(`${tag}: step ${i + 1} offers the next, which is read first`, after.go === `Next: ${STEPS[i + 1]}`, after.go); await page.keyboard.press("Enter"); }
  }
  check(`${tag}: the whole round took one key a step, and one more before each of the two steps that are read`, true);
  check(`${tag}: the demo says what it is: a replay of a round, at the program ids it ran on`, first.mark === `A real ${data.cluster} round, replayed (${data.ids} program ids, ${data.date.replace(/^(\d+ \w{3})\w*/, "$1")}).` && ["staging", "public"].includes(data.ids), first.mark);
  const [fund, claim, fixed, paid, replay, both] = seen.map((s) => s.after);
  check(`${tag}: the order is the recorded one`, fund.scene.includes(`${data.fund.order.slice(0, 4)}…${data.fund.order.slice(-4)}`) && fund.say.includes(data.fund.amount) && fund.say.includes(`fee ${data.fund.fee}, charged under the 0.3.14 fee`) && fund.scene.includes(`fee ${data.fund.fee}, charged under the 0.3.14 fee`), fund.scene);
  check(`${tag}: the claim is rejected and the failed check is named`, claim.badges.includes("rejected") && claim.badges.includes("failed") && claim.say === "Rejected: test_mixed failed."
    && claim.scene.includes(data.claim.check.split(".").pop()) && seen[1].before.scene.includes(data.claim.says), claim);
  check(`${tag}: the fix is accepted and signed with the three claims`, fixed.badges.includes("accepted") && fixed.say.startsWith("Accepted: ") && fixed.badges.filter((b) => b === "passes").length === 3 && data.fixed.claims.every((c) => fixed.scene.includes(c.name) && fixed.scene.includes(c.is)), fixed.scene);
  check(`${tag}: paid, and the wait is the measured one`, paid.badges.includes("Paid") && paid.say.includes(`${data.paid.seconds} seconds`) && paid.scene.includes(`${data.paid.payments} payments`), paid);
  check(`${tag}: the explorer is ${opts.offline ? "not offered with no network" : "offered"}`, opts.offline ? paid.links.length === 0 : paid.links.length === 1 && paid.links[0] === `https://explorer.solana.com/tx/${data.paid.tx}?cluster=devnet`, paid.links);
  check(`${tag}: the token sent again is refused: a token works once, with the error that was recorded, and is not called single-use`, replay.badges.includes("Refused") && replay.say === `Refused: a token works once. Error ${data.replay.error}.`
    && data.replay.error === data.replay.single_use_error && replay.scene.includes(data.replay.means) && !/single.use/i.test(replay.scene + replay.say) && seen[4].before.go === "Send the same token again", replay);
  const n = (v) => String(v).replace(/\B(?=(\d{3})+$)/g, ",");
  // the counts the chain holds: apart (the staging rehearsal: disputed, by how many) or the same (the public round: agreed, no "+0")
  const agreed = Number(data.count.apart) === 0;
  check(`${tag}: the two counts are the recorded ones from the start, never compared before; the action compares them`, seen[5].before.badges.includes("not compared") && !seen[5].before.badges.includes("equal")
    && (agreed ? seen[5].before.scene.split(n(data.count.buyer)).length === 3
      : seen[5].before.scene.split(n(data.count.seller)).length === 2 && seen[5].before.scene.split(n(data.count.buyer)).length === 2)
    && both.scene.includes(n(data.count.buyer)) && both.scene.includes(n(data.count.seller))
    && (agreed ? both.badges.includes("agreed") && !both.badges.includes("disputed") && !both.scene.includes("+0") && both.say === `Agreed: both counted ${n(data.count.buyer)}.`
      : both.badges.includes("disputed") && both.scene.includes(`+${data.count.apart}`)), [seen[5].before.scene, both.scene]);
  if (!opts.offline) check(`${tag}: each count links the transactions that wrote it`, [...data.count.buyer_tx, ...data.count.seller_tx].every((t) => both.links.some((l) => l.includes(t))), both.links);
  check(`${tag}: the last step ends, it does not go on`, both.go === "Start over" && both.step === 5);
  if (!opts.reduce) check(`${tag}: a state change moved something`, both.animated > 0, both.animated);
  // the arrows move between steps, Escape starts over
  await page.keyboard.press("ArrowLeft");
  check(`${tag}: the left arrow goes back a step`, (await read(page)).step === 4);
  await page.keyboard.press("ArrowRight"); await page.keyboard.press("ArrowRight");
  check(`${tag}: the right arrow stops at the last step`, (await read(page)).step === 5);
  await page.keyboard.press("Escape");
  const fresh = await read(page);
  check(`${tag}: Escape starts over`, fresh.step === 0 && fresh.states.join() === "live,idle,idle,idle,idle,idle" && fresh.say === first.say, fresh.states);
  const paidCount = await page.evaluate(async () => { for (let i = 0; i < 3; i += 1) document.querySelector("#demo [data-step='3']").click(); document.querySelector("#demo .kd-go").click(); return document.querySelector("#demo .kd-secs").dataset.to; });
  check(`${tag}: the counter ends at the measured seconds`, paidCount === String(data.paid.seconds), paidCount);
  await page.waitForFunction((to) => document.querySelector("#demo .kd-secs")?.textContent === to, String(data.paid.seconds));
  // what is tied to the scroll (a section not yet scrolled to) is not something running: only the clock's animations count
  await page.waitForFunction(() => document.getAnimations().filter((a) => a.timeline === document.timeline).length === 0 && !document.querySelector(".kd-token, body > .kd-raven"));
  check(`${tag}: nothing loops: every movement ends`, true);
  const said = await page.evaluate(() => { for (const b of document.querySelectorAll("#demo .k-step")) b.click(); return document.getElementById("demo").textContent + [...document.querySelectorAll("#demo [aria-label]")].map((e) => e.getAttribute("aria-label")).join(" "); });
  check(`${tag}: no caption says refused, passed, failed verdict or pending: a verdict is one of the four words`, !/refus|unverified|pending/i.test(said), said.match(/.{0,20}(refus|unverified|pending).{0,20}/i));
  check(`${tag}: no page error`, errors.length === 0, errors);
  const foreign = asked.filter((u) => !u.startsWith(origin));
  check(`${tag}: no request leaves the site`, foreign.length === 0, foreign);
  check(`${tag}: motion.js was ${opts.motion === false ? "absent" : "asked for"}`, asked.some((u) => u.endsWith("/motion.js")));
  await context.close();
}

const hasMotion = existsSync(join(root, "motion.js"));
await round("no motion.js", 1280, { motion: false, shot: true });
await round("no motion.js", 390, { motion: false, shot: true });
await round("no motion.js", 320, { motion: false });
await round("reduced motion", 390, { motion: false, reduce: true });
await round("no network", 390, { motion: false, offline: true });
if (hasMotion) { await round("with motion.js", 1280); await round("with motion.js, reduced", 390, { reduce: true }); }
else console.log("note  web/motion.js is not in this build: only the fallback ran");

await browser.close();
server.close();
if (!process.exitCode) console.log("the demo holds");
