// node tests/web/demo.mjs <site dir> [folder for screenshots]
// The round under the first screen (web/demo.js) in headless Chromium, on a page that holds nothing but the site's
// stylesheet and <div id="demo">. ONE transaction in SEVEN beats: agree, fails, passes, same statement, replay, pay,
// verify. Every beat is reached with the keyboard alone, one key a beat (and one more before a beat that is read
// first); each statement is 12 words or fewer; a verdict and a line's state are the words of src/knos/ids.py; the
// figures are those of demo_data.json and every beat says what is recorded and what is computed here; the root both
// panes show is the sha256 this script computes of statement_sample.json, and the file's own; a changed amount is
// not verified; the bank file is offered only where the build has web/rails.js (here: a stand-in handed to the
// module); a reader who asked for reduced motion gets no animation at all; nothing is asked of any other host;
// nothing scrolls sideways at 320 and 390 px; and the module mounts when web/motion.js is not there.
import { createServer } from "node:http";
import { readFileSync, existsSync, mkdirSync } from "node:fs";
import { join, extname, normalize } from "node:path";
import { createHash } from "node:crypto";

const root = process.argv[2], shots = process.argv[3] || "";
if (!root || !existsSync(join(root, "demo.js"))) { console.error("usage: node tests/web/demo.mjs <site dir> [shots dir]"); process.exit(2); }
let chromium;
try { ({ chromium } = (await import("playwright")).default); } catch { console.log("SKIP the playwright package is not installed"); process.exit(0); }
const check = (name, cond, detail) => { if (!cond) { console.error("FAIL", name, detail === undefined ? "" : JSON.stringify(detail)); process.exitCode = 1; } else console.log("ok  ", name); };
const data = JSON.parse(readFileSync(join(root, "demo_data.json"), "utf8"));
const STEPS = ["Agree", "Fails", "Passes", "Statement", "Replay", "Pay", "Verify"];
const ACTS = ["Agree and fund", "Check the submission", "Push the correction", "Compute both statements", "Send the same token again", `Pay in ${data.money}`, "Verify the export"];
const READ = [false, true, false, true, false, true, true];          // the beats that show something to read before their action
const BAD = [1, 4];                                                    // the two refusals: the rejected submission, the token sent again
const WHY = "Money is released with no custodian, and the count is anchored where neither side can alter it.";
// the sample statement's root, computed here as src/knos/statement.py does: canonical JSON, the sha256 field empty
const sample = JSON.parse(readFileSync(join(root, "statement_sample.json"), "utf8"));
const canon = (d) => (d === null ? "null" : typeof d !== "object" ? JSON.stringify(d) : Array.isArray(d) ? `[${d.map(canon).join(",")}]` : `{${Object.keys(d).sort().map((k) => `${JSON.stringify(k)}:${canon(d[k])}`).join(",")}}`);
const ROOT = createHash("sha256").update(`${canon({ ...sample, sha256: "" })}\n`).digest("hex");
const shown = (r) => `${r.slice(0, 12)}…${r.slice(-6)}`;
const words = (s) => s.trim().split(/\s+/).filter((w) => /[\p{L}\p{N}]/u.test(w)).length;

const TYPES = { ".html": "text/html", ".js": "text/javascript", ".mjs": "text/javascript", ".css": "text/css", ".json": "application/json", ".svg": "image/svg+xml",
  ".woff2": "font/woff2", ".png": "image/png" };
const PAGE = (offline, bank = false) => `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>demo</title><link rel="stylesheet" href="app.css"></head><body><main><div id="demo" hidden></div></main>
<script type="module">import { renderDemo } from "./demo.js";
window.__demo = await renderDemo(document.getElementById("demo"), ${offline ? "{ online: () => false }" : bank ? "{ pain001: (st, payer) => `<Document><Nm>${payer.name}</Nm>${st.lines.filter((l) => l.state === 'agreed').map((l) => `<Amt>${l.amount}</Amt>`).join('')}</Document>` }" : "{}"}); window.__mounted = true;</script></body></html>`;
let withMotion = true;
const server = createServer((req, res) => {
  const path = decodeURIComponent(new URL(req.url, "http://x").pathname);
  if (/^\/__demo(_offline|_bank)?\.html$/.test(path)) { res.writeHead(200, { "content-type": "text/html" }); return res.end(PAGE(path.includes("offline"), path.includes("bank"))); }
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
  return { say: el.querySelector(".kd-say").textContent, mark: el.querySelector(".kd-mark")?.textContent || "", lines: [...text(".kd-say"), ...text(".kd-fine"), ...text(".kd-src"), ...text(".k-kicker"), ...text(".kd-go"), ...text(".kd-alt"), ...text(".kd-quote"), ...text(".kd-terms dd"), ...text(".kd-reason"), ...text(".kd-why summary")],
    prov: el.querySelector(".kd-prov")?.textContent || "", roots: [...el.querySelectorAll(".kd-root")].map((r) => [r.textContent, r.title, r.dataset.s]), alt: el.querySelector(".kd-alt").hidden ? "" : el.querySelector(".kd-alt").textContent,
    busy: el.querySelector(".kd-scene").getAttribute("aria-busy") === "true", terms: text(".kd-terms dt, .kd-terms dd"), why: el.querySelector(".kd-why p")?.textContent || "", whyOpen: !!el.querySelector(".kd-why")?.open,
    step: [...el.querySelectorAll(".k-step")].findIndex((b) => b.getAttribute("aria-current") === "step"), states: [...el.querySelectorAll(".k-step")].map((b) => b.dataset.state),
    badges: text(".kd-scene .kd-badge"), scene: el.querySelector(".kd-scene").textContent.replace(/\s+/g, " "), go: el.querySelector(".kd-go").textContent,
    focus: document.activeElement?.className || document.activeElement?.id || "", sideways: document.documentElement.scrollWidth - document.documentElement.clientWidth,
    running: document.getAnimations().length, animated: window.__animated, links: [...el.querySelectorAll(".kd-scene a")].map((a) => a.href) };
});

async function open(width, { reduce = false, motion = true, offline = false, bank = false } = {}) {
  withMotion = motion;
  const context = await browser.newContext({ viewport: { width, height: 900 }, reducedMotion: reduce ? "reduce" : "no-preference" });
  const page = await context.newPage(), asked = [], errors = [];
  page.on("request", (r) => asked.push(r.url()));
  page.on("pageerror", (e) => errors.push(String(e)));
  await page.addInitScript(() => { window.__animated = 0; const a = Element.prototype.animate; Element.prototype.animate = function (...x) { window.__animated += 1; return a.apply(this, x); }; });
  await page.goto(`${origin}/${offline ? "__demo_offline" : bank ? "__demo_bank" : "__demo"}.html`);
  await page.waitForFunction(() => window.__mounted === true);
  return { page, context, asked, errors };
}

// The whole round with keys only: Tab to the comment box, Enter agrees and funds, then Enter acts and Enter moves on.
const settled = (page) => page.waitForFunction(() => document.querySelector("#demo .kd-scene").getAttribute("aria-busy") !== "true");
async function round(label, width, opts = {}) {
  const { page, context, asked, errors } = await open(width, opts);
  const tag = `${label} ${width}`, idle = STEPS.map((_, i) => (i ? "idle" : "live")).join();
  const first = await read(page);
  check(`${tag}: mounted on beat 1 of seven, nothing done, nothing moving`, first.step === 0 && first.states.join() === idle && first.states.length === 7 && first.animated === 0 && first.running === 0, first);
  check(`${tag}: the state line is announced politely`, await page.evaluate(() => { const s = document.querySelector("#demo .kd-say"); return s.getAttribute("aria-live") === "polite"; }));
  check(`${tag}: the four terms are on the table before anything is funded: price, acceptance, deadline, remedy`, first.terms.join("|") === `Price|${data.agree.price} ${data.money}|Acceptance|Named checks pass at merge|Deadline|${data.agree.days} days|Remedy|Unproven: the money goes back`
    && data.agree.price === data.fund.amount && /goes back at the deadline$/.test(data.agree.remedy), first.terms);
  check(`${tag}: the comment box holds the recorded comment`, await page.evaluate(() => document.getElementById("kd-comment").value) === data.fund.comment);
  check(`${tag}: the statement is not asked for before the reader acts`, !asked.some((u) => u.endsWith("/statement_sample.json")), asked);
  for (let n = 0; n < 12 && (await page.evaluate(() => document.activeElement?.id)) !== "kd-comment"; n += 1) await page.keyboard.press("Tab");
  check(`${tag}: Tab reaches the comment box`, (await page.evaluate(() => document.activeElement?.id)) === "kd-comment");
  const seen = [];
  let last = first;
  for (let i = 0; i < STEPS.length; i += 1) {
    // a beat that shows something to read is reached first ("Next"); every other beat is done by the one key that names it
    const waits = i === 0 || READ[i], before = waits ? await read(page) : last;
    if (waits) check(`${tag}: beat ${i + 1} is ${STEPS[i]}, with its action on the button`, before.step === i && before.states[i] === "live" && before.go === ACTS[i], [before.states, before.go]);
    else check(`${tag}: the button names beat ${i + 1}'s action before it is reached`, before.go === ACTS[i] && before.step === i - 1, before.go);
    await page.keyboard.press(i % 2 ? " " : "Enter");                  // the one action of the beat, by Enter or by Space
    await settled(page);
    if (i === 5) await page.waitForFunction((to) => document.querySelector("#demo .kd-secs").textContent === to, String(data.paid.seconds));   // the counter stops there
    const after = last = await read(page);
    seen.push({ before, after });
    for (const s of [...before.lines, ...after.lines]) check(`${tag}: beat ${i + 1}: "${s.slice(0, 40)}" is 12 words or fewer`, words(s) <= 12, [words(s), s]);
    check(`${tag}: beat ${i + 1} changed on one key`, after.step === i && after.states[i] === (BAD.includes(i) ? "bad" : "done") && after.say !== before.say, after);
    check(`${tag}: beat ${i + 1} says what is recorded and what is computed`, /^(Recorded|Counts recorded|Token recorded|Payment recorded|The sample statement)/.test(after.prov) && (!waits || after.prov === before.prov), after.prov);
    check(`${tag}: beat ${i + 1} does not scroll sideways`, before.sideways <= 0 && after.sideways <= 0, [before.sideways, after.sideways]);
    check(`${tag}: beat ${i + 1} keeps the focus on the one button`, after.focus.includes("kd-go"), after.focus);
    if (opts.reduce) check(`${tag}: beat ${i + 1} moves nothing`, after.running === 0 && after.animated === 0, [after.running, after.animated]);
    if (shots && opts.shot) await page.locator("#demo").screenshot({ path: join(shots, `demo-${width}-${i + 1}-${STEPS[i].toLowerCase().replace(/\s+/g, "-")}.png`), animations: "disabled" });
    if (i < STEPS.length - 1 && READ[i + 1]) { check(`${tag}: beat ${i + 1} offers the next, which is read first`, after.go === `Next: ${STEPS[i + 1]}`, after.go); await page.keyboard.press("Enter"); }
  }
  check(`${tag}: the whole round took one key a beat, and one more before each of the four beats that are read`, true);
  check(`${tag}: the demo says what it is: a replay of a round, at the program ids it ran on`, first.mark === `A real ${data.cluster} round, replayed (${data.ids} program ids, ${data.date.replace(/^(\d+ \w{3})\w*/, "$1")}).` && ["staging", "public"].includes(data.ids), first.mark);
  const [fund, claim, fixed, both, replay, paid, verify] = seen.map((s) => s.after);
  check(`${tag}: 1 agree: the order is the recorded one`, fund.scene.includes(`${data.fund.order.slice(0, 4)}…${data.fund.order.slice(-4)}`) && fund.say === `Agreed and funded: ${data.fund.amount} ${data.money} held.` && fund.badges.includes("funded") && fund.scene.includes(`fee ${data.fund.fee}, charged under the 0.3.14 fee`), fund.scene);
  check(`${tag}: 2 fails: the submission is rejected, the failed check is named and the judge's reason is given word for word`, claim.badges.includes("rejected") && claim.badges.includes("failed") && claim.say === "Rejected: test_mixed failed."
    && claim.scene.includes(data.claim.check.split(".").pop()) && claim.scene.includes(`${data.claim.reason}: test_mixed`) && data.claim.reason === "acceptance checks not passed" && seen[1].before.scene.includes(data.claim.says), claim);
  check(`${tag}: 3 passes: the correction is accepted and signed with the three claims`, fixed.badges.includes("accepted") && fixed.say.startsWith("Accepted: ") && fixed.badges.filter((b) => b === "passes").length === 3 && data.fixed.claims.every((c) => fixed.scene.includes(c.name) && fixed.scene.includes(c.is)), fixed.scene);
  const n = (v) => String(v).replace(/\B(?=(\d{3})+$)/g, ",");
  // the counts the chain holds: apart (the staging rehearsal: disputed, by how many) or the same (the public round: agreed, no "+0")
  const agreed = Number(data.count.apart) === 0;
  check(`${tag}: 4 same statement: the two counts are the recorded ones, not compared and no root shown before the action`, seen[3].before.badges.includes("not compared") && seen[3].before.roots.length === 2 && seen[3].before.roots.every((r) => r[0] === "not computed")
    && both.scene.includes(n(data.count.buyer)) && both.scene.includes(n(data.count.seller))
    && (agreed ? both.badges.includes("agreed") && !both.badges.includes("disputed") && !both.scene.includes("+0") && both.say === `Agreed: both counted ${n(data.count.buyer)}. One root.`
      : both.badges.includes("disputed") && both.scene.includes(`+${data.count.apart}`)), [seen[3].before.scene, both.scene]);
  check(`${tag}:   two panes, one root: each pane computed the sha256 this script computes, which is the file's own`, both.roots.length === 2 && both.roots.every((r) => r[1] === ROOT && r[0] === shown(ROOT) && r[2] === "ok") && ROOT === sample.sha256
    && both.badges.includes("same root") && asked.some((u) => u.endsWith("/statement_sample.json")), both.roots);
  if (!opts.offline) check(`${tag}:   each count links the transactions that wrote it`, [...data.count.buyer_tx, ...data.count.seller_tx].every((t) => both.links.some((l) => l.includes(t))), both.links);
  const dup = sample.lines.find((l) => l.state === "duplicate");
  check(`${tag}: 5 replay: the token sent again is refused: a token works once, with the error that was recorded, and is not called single-use`, replay.badges.includes("Refused") && replay.say === `Refused: a token works once. Error ${data.replay.error}.`
    && data.replay.error === data.replay.single_use_error && replay.scene.includes(data.replay.means) && !/single.use/i.test(replay.scene + replay.say), replay);
  check(`${tag}:   and the line billed twice is a duplicate, owed once, in the statement's own words`, replay.badges.includes("duplicate") && replay.scene.includes(`Invoice line ${dup.line}`) && replay.scene.includes(dup.amount) && replay.scene.includes(`${dup.why.split(":")[0].replace(/^./, (c) => c.toUpperCase())}: owed once.`) && replay.scene.includes("Fund token, sent again"), replay.scene);
  check(`${tag}: 6 pay: paid, and the wait is the measured one`, paid.badges.includes("Paid") && paid.say === `Paid ${data.paid.amount} ${data.money}. Median wait: ${data.paid.seconds} seconds.` && paid.scene.includes(`${data.paid.payments} payments`), paid);
  check(`${tag}:   the explorer is ${opts.offline ? "not offered with no network" : "offered"}`, opts.offline ? paid.links.length === 0 : paid.links.length === 1 && paid.links[0] === `https://explorer.solana.com/tx/${data.paid.tx}?cluster=devnet`, paid.links);
  check(`${tag}:   why a chain is answered where the money moves, in the one line, behind a fold the reader opens`, paid.why === WHY && !paid.whyOpen && seen.every((s, k) => k === 5 || !s.after.why), paid.why);
  const offered = Boolean(opts.bank) || data.bank_file === true;        // a build that holds web/rails.js offers the file in every round
  check(`${tag}:   a bank file is ${offered ? "offered beside the payment" : "not offered: this build has no web/rails.js"}`, offered ? seen[5].before.alt === "Write a bank file instead" : seen[5].before.alt === "" && data.bank_file === false, seen[5].before.alt);
  check(`${tag}: 7 verify: the export's root is derived again and its totals added again, and both match`, verify.say === "Verified: root and totals match the export." && verify.roots.length === 1 && verify.roots[0][1] === ROOT && verify.roots[0][2] === "ok"
    && verify.badges.filter((b) => b === "matches").length === 2 && seen[6].before.badges.filter((b) => b === "not checked").length === 2 && verify.alt === "Change one amount", verify);
  check(`${tag}: the last beat ends, it does not go on`, verify.go === "Start over" && verify.step === 6);
  if (!opts.reduce) check(`${tag}: a state change moved something`, verify.animated > 0, verify.animated);
  // one amount changed in the export: the root is another, the totals no longer add up, and the page says not verified
  await page.keyboard.press("Tab");
  check(`${tag}: Tab reaches the second action of the last beat`, (await read(page)).focus.includes("kd-alt"));
  await page.keyboard.press("Enter");
  const changed = await read(page);
  check(`${tag}:   one amount changed: not verified, another root, both checks differ`, changed.say === "Not verified: the changed file has another root." && changed.roots[0][1] !== ROOT && /^[0-9a-f]{64}$/.test(changed.roots[0][1]) && changed.roots[0][2] === "bad"
    && changed.badges.filter((b) => b === "differs").length === 2 && changed.badges.includes("one amount changed") && changed.alt === "Put the amount back" && changed.focus.includes("kd-alt"), changed);
  await page.keyboard.press("Enter");
  check(`${tag}:   put back: verified again`, (await read(page)).say === verify.say);
  if (opts.bank) {
    await page.evaluate(() => document.querySelector("#demo [data-step='5']").click());
    await page.click("#demo .kd-alt");
    const bank = await read(page), file = await page.evaluate(async () => { const a = document.querySelector("#demo .kd-bank a"); return { name: a.getAttribute("download"), text: await (await fetch(a.href)).text() }; });
    check(`${tag}:   the bank file is written in the browser from the agreed lines, and the page says no bank has taken it`, bank.badges.includes("Bank file written") && file.name === `pain001-${sample.invoice}.xml`
      && file.text === `<Document><Nm>${sample.buyer}</Nm>${sample.lines.filter((l) => l.state === "agreed").map((l) => `<Amt>${l.amount}</Amt>`).join("")}</Document>` && bank.scene.includes("No bank has taken this file.") && bank.alt === "", [bank.scene, file]);
    await page.evaluate(() => document.querySelector("#demo [data-step='6']").click());
  } else if (data.bank_file === true) {       // the build's own web/rails.js: the sample's agreed lines, approved by the demonstration, as a pain.001 that names nobody's accounts
    await page.evaluate(() => document.querySelector("#demo [data-step='5']").click());
    await page.click("#demo .kd-alt");
    const bank = await read(page), file = await page.evaluate(async () => { const a = document.querySelector("#demo .kd-bank a"); return a ? { name: a.getAttribute("download"), text: await (await fetch(a.href)).text() } : null; });
    const agreed = sample.lines.filter((l) => l.state === "agreed"), sum = (agreed.reduce((n, l) => n + Math.round(parseFloat(l.amount) * 100), 0) / 100).toFixed(2);
    check(`${tag}:   the build's own bank file is a pain.001 of the agreed lines, and the page says no bank has taken it`, Boolean(file) && bank.badges.includes("Bank file written") && file.name === `pain001-${sample.invoice}.xml`
      && file.text.includes("urn:iso:std:iso:20022:tech:xsd:pain.001.001.09") && file.text.includes(`<CtrlSum>${sum}</CtrlSum>`) && file.text.includes(`<Nm>${sample.buyer}</Nm>`)
      && agreed.every((l) => file.text.includes(l.invoice_line)) && bank.scene.includes("No bank has taken this file.") && bank.alt === "", [bank.scene, file && file.text.slice(0, 400)]);
    await page.evaluate(() => document.querySelector("#demo [data-step='6']").click());
  }
  // the arrows move between beats, Escape starts over
  await page.evaluate(() => document.querySelector("#demo .kd-go").focus());
  await page.keyboard.press("ArrowLeft");
  check(`${tag}: the left arrow goes back a beat`, (await read(page)).step === 5);
  await page.keyboard.press("ArrowRight"); await page.keyboard.press("ArrowRight");
  check(`${tag}: the right arrow stops at the last beat`, (await read(page)).step === 6);
  await page.keyboard.press("Escape");
  const fresh = await read(page);
  check(`${tag}: Escape starts over`, fresh.step === 0 && fresh.states.join() === idle && fresh.say === first.say, fresh.states);
  const paidCount = await page.evaluate(async () => { for (let i = 0; i < 3; i += 1) document.querySelector("#demo [data-step='5']").click(); document.querySelector("#demo .kd-go").click(); return document.querySelector("#demo .kd-secs").dataset.to; });
  check(`${tag}: the counter ends at the measured seconds`, paidCount === String(data.paid.seconds), paidCount);
  await page.waitForFunction((to) => document.querySelector("#demo .kd-secs")?.textContent === to, String(data.paid.seconds));
  // what is tied to the scroll (a section not yet scrolled to) is not something running: only the clock's animations count
  await page.waitForFunction(() => document.getAnimations().filter((a) => a.timeline === document.timeline).length === 0 && !document.querySelector(".kd-token, body > .kd-raven"));
  check(`${tag}: nothing loops: every movement ends`, true);
  const said = await page.evaluate(() => { for (const b of document.querySelectorAll("#demo .k-step")) b.click(); return document.getElementById("demo").textContent + [...document.querySelectorAll("#demo [aria-label]")].map((e) => e.getAttribute("aria-label")).join(" "); });
  check(`${tag}: no caption says refused, unverified or pending where a verdict stands: a verdict is one of the four words`, !/refus|unverified|pending/i.test(said), said.match(/.{0,20}(refus|unverified|pending).{0,20}/i));
  check(`${tag}: no page error`, errors.length === 0, errors);
  const foreign = asked.filter((u) => !u.startsWith(origin) && !u.startsWith(`blob:${origin}/`));          // the bank file it wrote itself is read back from the page's own memory
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
await round("with a bank file", 390, { motion: false, bank: true });
if (hasMotion) { await round("with motion.js", 1280); await round("with motion.js, reduced", 390, { reduce: true }); }
else console.log("note  web/motion.js is not in this build: only the fallback ran");

await browser.close();
server.close();
if (!process.exitCode) console.log("the demo holds");
