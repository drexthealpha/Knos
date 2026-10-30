// R2 test_rival_gaps, live: every rival-gap item of the CHAMPION16 spec, each with its own check and number.
// The answers come from the hosted app (/api/check with the picked reading; past the visitor cap the private cache
// answers, labelled); the page items run in Playwright Chromium at 1280 on the front door and /app/.
//
//   node scripts/test_rival_gaps.mjs <INPUTS.txt> <S1-S4 map file> [result file]
import { chromium } from "playwright";
import { appendFileSync, readFileSync } from "node:fs";

const APP = "https://knos.onrender.com", FRONT = "https://drexthealpha.github.io/Knos/";
const MORE = readFileSync(process.argv[2], "utf8").split(/\r?\n/).map((s) => s.trim()).filter(Boolean);
const MAP = process.argv[3] ? readFileSync(process.argv[3], "utf8") : "";
const OUT = process.argv[4] || "";
const INPUTS = ["a vegan ramen food truck", "a late night ramen spot", "10.1038/nature14539", "10.1126/science.1225829", ...MORE];
const CHIPS = ["a solar powered music festival", "an AI recipe planner for families", "a crypto podcast for beginners",
  "a quantum physics book for kids", "a probiotic kombucha brand", "a recycled ocean plastic swimwear brand"];
const lines = [], fails = [];
const log = (s) => { console.log(s); lines.push(s); if (OUT) appendFileSync(OUT, s + "\n"); };
const ok = (c, what) => { log(`${c ? "ok  " : "FAIL"} ${what}`); if (!c) fails.push(what); return c; };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const again = async (f) => { try { return await f(); } catch (e) { await sleep(30000); return await f(); } };
let last = 0;
const pace = async () => { const w = last + 22000 - Date.now(); if (w > 0) await sleep(w); last = Date.now(); };
const get = (p) => again(async () => (await fetch(APP + p, { headers: { "User-Agent": "knos-r2-test" } })).json());
const post = async (p, b) => { await pace(); return again(async () => (await fetch(APP + p, { method: "POST", headers: { "Content-Type": "application/json", "User-Agent": "knos-r2-test" }, body: JSON.stringify(b) })).json()); };
const words = (s) => new Set(String(s).toLowerCase().match(/[a-z0-9]+/g) || []);

// the answers: each input's which-one step, then the reading a person picks, checked
const cards = {};
let against = 0, untyped = 0;
for (const input of [...INPUTS, ...CHIPS]) {
  try {
    const w = await post("/api/check", { idea: input });
    for (const r of w.readings || []) { if (/ against /.test(r.text || "")) against++; if (!r.kind) untyped++; }
    const picked = w.kind !== "which_one" ? input : (w.of === "paper" ? ((w.readings || []).find((r) => r.kind === "product")?.text || input) : input);
    cards[input] = await post("/api/check", { idea: picked, picked: true });
  } catch (e) { cards[input] = { error: `${e.name}: ${e.message}` }; }
}
const all = Object.entries(cards);
// 1. readings show their type, 0 debug strings
ok(against === 0 && untyped === 0, `1 readings: ${against} options containing " against ", ${untyped} without a type`);
// 2. one card, one story: a launch line only on Open; header and footer counts equal
const launchBad = all.filter(([, r]) => (r.decision || {}).verdict !== "OPEN" && /Launch in|pre-orders? from/.test(JSON.stringify(r.story || {}))).length;
const countBad = all.filter(([, r]) => { const q = r.qloo_calls || {}; return (r.calls || []).length !== (q.total ?? (r.calls || []).length); }).length;
ok(launchBad === 0 && countBad === 0, `2 one story: ${launchBad} cards with a launch line beside a non-Open verdict, ${countBad} count mismatches`);
// 3. papers reach Qloo
for (const doi of ["10.1038/nature14539", "10.1126/science.1225829"]) {
  const r = cards[doi] || {};
  const v = (r.decision || {}).verdict, live = (r.qloo_calls || {}).live || 0, http400 = (r.calls || []).filter((c) => /HTTP 400/.test(String(c.error || ""))).length;
  ok(["OPEN", "REFUSE"].includes(v) && live >= 3 && http400 === 0, `3 ${doi}: ${v}, ${live} live Qloo calls, ${http400} HTTP 400 lines`);
}
// 5. a refusal is never a dead end; 6. the decision first; 11. say what was used; 14. things a buyer acts on
let refusals = 0, deadEnds = 0, noStory = 0, noUsed = 0, badUsed = 0, opens = 0, dlBad = 0;
for (const [input, r] of all) {
  const s = r.story || {}, v = (r.decision || {}).verdict;
  if (!s.sentence || !(s.tiles || []).length) noStory++;
  const u = s.used || {};
  if (!u.line) noUsed++;
  const own = words(input);
  if ([...(u.used || []), ...(u.not_in_qloo || [])].some((w) => ![...own].some((x) => x.startsWith(w.slice(0, 4))))) badUsed++;
  if (v === "REFUSE") { refusals++; if (!(s.reruns || []).length || !(s.rejected || []).length) deadEnds++; }
  if (v === "OPEN") {
    opens++;
    const d = (s.downloads || []).map((x) => x.kind).join(",");
    if (d !== "preorder,outreach,refund.ics") { dlBad++; continue; }
    const pre = await again(async () => (await fetch(APP + `/api/card/preorder?hash=${r.hash}`)).text());
    const t = (r.decision || {}).target_units;
    if (!pre.includes(String(t))) dlBad++;
  }
}
ok(deadEnds === 0, `5 refusals: ${refusals - deadEnds} of ${refusals} offer a rerun and list what was rejected`);
ok(noStory === 0, `6 decision first: ${all.length - noStory} of ${all.length} answers lead with a sentence and tiles`);
ok(noUsed === 0 && badUsed === 0, `11 used line: ${all.length - noUsed} of ${all.length} carry it; ${badUsed} list a word that is not the input's`);
ok(dlBad === 0, `14 Open cards: ${opens - dlBad} of ${opens} offer the 3 downloads, built from the card's own numbers`);
// 8. the public counter; 13. the model state; 9. feedback
const counter = await get("/api/counter");
ok(["checks_today", "checks_week", "preorders_held", "preorders_released", "checks_by_others"].every((k) => k in counter),
  `8 counter: today ${counter.checks_today}, this week ${counter.checks_week}, held ${counter.preorders_held}, released ${counter.preorders_released}, by others ${counter.checks_by_others}`);
const status = await get("/api/status");
ok(["on", "off"].includes(status.model) && !/sk-ant|ANTHROPIC_API_KEY=/.test(JSON.stringify(status)), `13 model: /api/status says "${status.model}", no key text`);
const anyHash = (all.find(([, r]) => r.hash) || [])[1]?.hash;
const fb = anyHash ? await post("/api/feedback", { hash: anyHash, useful: true, note: "r2 test" }) : {};
const counter2 = await get("/api/counter");
ok(fb.saved && counter2.feedback_yes >= 1, `9 feedback: saved ${fb.saved}, yes ${counter2.feedback_yes}, no ${counter2.feedback_no}`);
const ask = anyHash ? await post("/api/ask", { hash: anyHash, question: "where first?" }) : {};
ok(status.model === "on" || /model key/.test(String(ask.refused || "")), `15 ask: with the model "${status.model}", the answer is "${String(ask.refused || ask.answer || "").slice(0, 60)}"`);
// 12. the six chips live today
const today = new Date().toISOString().slice(0, 10);
const chipsLive = CHIPS.filter((c) => (cards[c]?.calls || []).some((x) => x.live || String(x.at || "").startsWith(today))).length;
ok(chipsLive === 6, `12 chips: ${chipsLive} of 6 cards carry Qloo answers from today (${today})`);
// the page items
const browser = await chromium.launch();
const errors = [];
try {
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  page.on("pageerror", (e) => errors.push(e.message));
  await again(() => page.goto(FRONT + "?t=" + Date.now(), { waitUntil: "networkidle", timeout: 120000 }));
  const strip = await page.$$eval(".k-strip a, .k-strip [data-cell], [data-proof-strip] a", (a) => a.length).catch(() => 0);
  const firstText = await page.evaluate(() => document.body.innerText.slice(0, 2500));
  ok(strip >= 4 && !/0\.19.{0,40}0\.41/.test(firstText), `4 proof strip: ${strip} cells; the 0.19 line ${/0\.19/.test(firstText) ? "on" : "off"} the first screen`);
  const how = await again(async () => (await fetch(FRONT + "how-we-test.html")).text());
  ok(/0\.19/.test(how), `4 the 0.19 result is on How we test Knos: ${/0\.19/.test(how)}`);
  await page.click("button.k-chip[data-q]");
  await page.waitForSelector("#k-card .k-card:not([data-confirm])", { timeout: 120000 }).catch(() => null);
  let clicks = 0;
  for (let i = 0; i < 2; i++) for (const v of ["without", "with", "model"]) {
    const b = await page.$(`.k-switch [data-view="${v}"]`);
    if (b) { await b.click().catch(() => null); clicks++; await page.waitForTimeout(300); }
  }
  ok(clicks >= 6, `2 the Without Qloo, With Qloo and Model alone buttons: ${clicks} of 6 clicks answered`);
  const start = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  start.on("pageerror", (e) => errors.push(e.message));
  await again(() => start.goto(FRONT + "start/?t=" + Date.now(), { waitUntil: "networkidle", timeout: 120000 }));
  const states = await start.$$eval("[data-state-run], [data-try-state]", (b) => b.length).catch(() => 0);
  const cap = /3,000|day cap|resets 00:00 UTC/.test(await start.evaluate(() => document.body.innerText));
  ok(states >= 4 && cap, `10 Start: ${states} one-click states, the day cap line ${cap ? "shown" : "missing"}`);
} finally { await browser.close(); }
ok(errors.length === 0, `0 page errors (${errors.length}${errors.length ? ": " + errors[0].slice(0, 100) : ""})`);
// 7. the work streams while it runs: typed ideas answer in one request; the job steps stream only a paper's crossing
log("note 7: the call rows stream through /api/cross job steps for a paper's crossing; a typed idea's check is one request");
// 16. every S1 to S4 TOP 10 item, mapped
const mapped = (MAP.match(/^- /gm) || []).length;
const unruled = MAP.split("\n").filter((l) => /not built:/.test(l) && !/by the rule/.test(l)).length;
ok(mapped >= 40 && unruled === 0, `16 S1 to S4: ${mapped} TOP 10 items listed; ${unruled} left unbuilt without a rule that stops them`);
if (OUT && MAP) appendFileSync(OUT, MAP + "\n");
log(fails.length ? `FAIL test_rival_gaps: ${fails.length} of ${lines.length - 1} checks failed; first: ${fails[0].slice(0, 140)}`
  : `PASS test_rival_gaps: ${lines.length - 1} checks`);
process.exit(fails.length ? 1 : 0);
