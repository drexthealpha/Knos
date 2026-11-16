// node tests/web/tool.mjs <site dir>      the front door's first tool on a build of the site, the hosted server mocked
// node tests/web/tool.mjs --live          the same first steps on the published front door against the live server
//
// Round 13 (v0328 research ROUND13-ITEMS.md and R13 SPEC.md). On a build served as GitHub Pages serves it (under /Knos/),
// in headless Chromium at 360 by 800 with no stored state, the hosted server answered by a stand-in that keeps the API
// contract of SPEC.md (POST /api/run, POST /api/pay, GET /api/tools; the 402, 413 and 408 answers):
//   A  the first screen holds 40 words or fewer and none of the PLAIN-WORDS rule's words, one h1, and the box and "Try it"
//      whole with no scroll; "Try it" shows a first change within 200 ms (SPEC: U1 R2 and R3) and then a line that starts
//      "About " and the line "Exact count: 12"; "Use my data" empties the box and puts the cursor in it; 5 lines with 3
//      different items read "Exact count: 3"; "Copy link" reads "Copied" within 400 ms
//   A6 a slow run shows a moving sign, the step and Stop from 1 s; Stop stops it and keeps the list in the box
//   C  own-data runs until the free runs end; the pay screen's strings are the ones docs/data/pricing.json gives; "Pay with
//      test money", its confirm step, a second press that records nothing twice, "20 runs left", and one more run
//   errors: the server's 413 message and a server that does not answer, each 12 words or more with the list kept
// Every run the page sends carries the test marker (D2). No `playwright` package or no browser: SKIP (tests/web/overflow.mjs).
import { createServer } from "node:http";
import { readFileSync, existsSync, statSync } from "node:fs";
import { join, extname, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { chromiumOrSkip, TYPES } from "./overflow.mjs";

const here = dirname(fileURLToPath(import.meta.url));
const LIVE = process.argv[2] === "--live";
const root = LIVE ? null : process.argv[2];
if (!LIVE && (!root || !existsSync(join(root, "index.html")))) { console.error("usage: node tests/web/tool.mjs <site dir> | --live"); process.exit(2); }
const pricing = JSON.parse(readFileSync(join(here, "../../docs/data/pricing.json"), "utf8")).numbers;
const N = Object.fromEntries(Object.entries(pricing).map(([k, v]) => [k, v.value]));
// the PLAIN-WORDS rule of ROUND13-ITEMS.md: none of these on a front, tool, result, price or status screen outside a closed How it works fold
export const PLAIN = ["tx", "hash", "testnet", "devnet", "mainnet", "proof", "prove", "verify", "contract", "token", "wallet", "agent", "job", "oracle", "LMSR", "NEAR", "Solana", "IRIS", "MCP", "API", "JSON"];
const plainHit = (text) => PLAIN.filter((w) => new RegExp(`\\b${w}s?\\b`, "i").test(text));
let fails = 0;
const check = (name, cond, detail) => { if (cond) console.log("ok  ", name); else { fails++; console.error("FAIL", name, detail === undefined ? "" : JSON.stringify(detail)); } };
const words = (s) => (String(s).match(/[A-Za-z0-9$][\w'’$%.,-]*/g) || []).length;

const browser = await chromiumOrSkip();
let server = null, base = "https://drexthealpha.github.io/Knos/";
if (!LIVE) {
  server = createServer((req, res) => {
    const path = decodeURIComponent(new URL(req.url, "http://x").pathname);
    const file = path.startsWith("/Knos/") ? join(root, path.slice(6) || "index.html") : null;
    const hit = file && existsSync(file) && statSync(file).isFile() ? file : file && existsSync(join(file, "index.html")) ? join(file, "index.html") : null;
    if (!hit) { res.writeHead(404, { "content-type": "text/html" }); return res.end(readFileSync(join(root, "404.html"))); }
    res.writeHead(200, { "content-type": TYPES[extname(hit)] || "application/octet-stream" }); res.end(readFileSync(hit));
  });
  await new Promise((r) => server.listen(0, "127.0.0.1", r));
  base = `http://127.0.0.1:${server.address().port}/Knos/`;
}

// ---- the stand-in for the hosted server: the contract of SPEC.md --------------------------------------------------------
const SAMPLE = ["apple", "banana", "cherry", "apple", "grape", "lemon", "banana", "mango", "orange", "pear", "apple", "plum", "kiwi", "cherry", "lime", "grape", "mango", "peach", "banana", "lemon"].join("\n");
const LIMITS = { max_lines: 100000, max_seconds: 10 };
function standIn() {
  const s = { runs: [], pays: [], presses: new Set(), left: new Map(), delay: 0, fail: null, unmarked: 0 };
  s.handle = async (route) => {
    const req = route.request(), url = new URL(req.url()), cors = { "access-control-allow-origin": "*", "content-type": "application/json" };
    const reply = (status, body) => route.fulfill({ status, headers: cors, body: JSON.stringify(body) });
    if (req.method() === "OPTIONS") return route.fulfill({ status: 204, headers: { ...cors, "access-control-allow-headers": "content-type", "access-control-allow-methods": "GET, POST" } });
    if (url.pathname === "/api/tools") return reply(200, { tools: [{ id: "count-distinct", title: "Count the different items in a list", sample: SAMPLE }] });
    const body = JSON.parse(req.postData() || "{}");
    if (url.pathname === "/api/run") {
      s.runs.push(body);
      if (body.test !== true) s.unmarked++;
      if (s.fail === "down") return route.abort("connectionfailed");
      if (s.delay) await new Promise((r) => setTimeout(r, s.delay));
      if (s.fail === "413") return reply(413, { error: `Your list is too long for me to count here. The limit is ${LIMITS.max_lines.toLocaleString("en-US")} lines. Try a shorter list.` });
      const lines = String(body.input).split("\n").map((x) => x.trim()).filter(Boolean), n = new Set(lines).size;
      let left = null, free = null, paid = null;
      if (body.mode === "own") {
        const had = s.left.has(body.browser) ? s.left.get(body.browser) : { free: N.free_runs_per_day, paid: 0 };
        if (had.free + had.paid <= 0) return reply(402, { pay: { headline: `${N.pack_runs} more runs for $${N.pack_price} in test money`, line: "Today this is test money. Nothing is charged.", runs: N.pack_runs, price: `$${N.pack_price}` } });
        if (had.free > 0) had.free--; else had.paid--;
        s.left.set(body.browser, had); free = had.free; paid = had.paid; left = free + paid;
      }
      const id = `r${s.runs.length}`;
      return reply(200, { result: `About ${n} different items`, exact: n, shown_by: "Checked by a test that counted 30,000 different visitors to within 10%.", link: `https://knos.onrender.com/r/${id}/`, runs_left: left, free_left: free, paid_left: paid, limits: LIMITS });
    }
    if (url.pathname === "/api/pay") {
      s.pays.push(body);
      if (!/^[A-Za-z0-9_-]{8,64}$/.test(body.press || "")) return reply(400, { error: "A test payment needs a press id of 8 to 64 letters, digits, dashes or underscores." });
      if (!s.presses.has(body.press)) { s.presses.add(body.press); const had = s.left.get(body.browser) || { free: 0, paid: 0 }; had.paid += N.pack_runs; s.left.set(body.browser, had); }
      return reply(200, { runs_left: N.pack_runs, recorded: "test" });
    }
    return reply(404, { error: "no such route" });
  };
  return s;
}

const ctx = await browser.newContext({ viewport: { width: 360, height: 800 } });   // a new context: no stored state
if (!LIVE) await ctx.grantPermissions(["clipboard-read", "clipboard-write"], { origin: new URL(base).origin });
const s = standIn();
await ctx.route(/^https:\/\/knos\.onrender\.com\/api\/(tools|run|pay)/, LIVE ? (r) => r.continue() : s.handle);
await ctx.route(/^https:\/\/(knos\.onrender\.com\/api\/(near|visit)|rpc\.testnet)/, (r) => r.abort());   // the question box below and the visit events: not this test
const page = await ctx.newPage();
await page.goto(base, { waitUntil: "load" });

// ---- A: the first screen ------------------------------------------------------------------------------------------------
const first = await page.evaluate(() => {
  const H = innerHeight, out = [];
  const walk = (n) => {
    if (n.nodeType === 3) { const r = document.createRange(); r.selectNodeContents(n); const b = r.getBoundingClientRect(); if (b.height && b.top < H && b.bottom > 0 && n.textContent.trim()) out.push(n.textContent.trim()); return; }
    if (n.nodeType !== 1 || /^(SCRIPT|STYLE|TEXTAREA|NOSCRIPT)$/.test(n.tagName)) return;
    const cs = getComputedStyle(n); if (cs.display === "none" || cs.visibility === "hidden") return;
    if (n.tagName === "DETAILS" && !n.open) { const sm = n.querySelector("summary"); if (sm) walk(sm); return; }
    for (const c of n.childNodes) walk(c);
  };
  walk(document.body);
  const box = document.getElementById("list").getBoundingClientRect(), go = document.getElementById("try").getBoundingClientRect();
  return { text: out.join(" "), h1: [...document.querySelectorAll("h1")].map((h) => h.textContent.trim()), title: document.getElementById("t-title").textContent.trim(),
    label: document.getElementById("list-label").textContent.trim(), boxBottom: box.bottom, goBottom: go.bottom, goW: go.width, goH: go.height, H,
    lines: document.getElementById("list").value.split("\n"), scrollX: document.documentElement.scrollWidth - innerWidth,
    font: parseFloat(getComputedStyle(document.body).fontSize) };
});
check("A: the first screen is 40 words or fewer (the box's sample is the input, not words of the screen)", words(first.text) <= 40, [words(first.text), first.text]);
check("A: the first screen has none of the PLAIN-WORDS rule's words", plainHit(first.text).length === 0, plainHit(first.text));
check("A: one h1, the headline, and the tool's title under it", first.h1.length === 1 && first.h1[0] === "What can you do with Knos?" && first.title === "Count the different items in a list", first);
check("A: the box is labelled Sample list and holds 20 lines with 12 different items", first.label === "Sample list" && first.lines.length === 20 && new Set(first.lines).size === 12, first.lines);
check("A: the box and Try it are whole on the first screen, no scroll", first.boxBottom <= first.H && first.goBottom <= first.H && first.scrollX <= 0, first);
check("A: Try it is the main action, 48 px tall at least and 300 px wide at least; body text 18 px", first.goH >= 48 && first.goW >= 300 && first.font >= 18, first);

// a first change within 200 ms of a press: the first mutation of the page after the click
const firstChange = (sel) => page.evaluate((sel) => new Promise((done) => {
  const t0 = performance.now(), mo = new MutationObserver(() => { mo.disconnect(); done(performance.now() - t0); });
  mo.observe(document.body, { subtree: true, childList: true, characterData: true, attributes: true });
  document.querySelector(sel).click();
  setTimeout(() => { mo.disconnect(); done(9999); }, 2000);
}), sel);
const ms = await firstChange("#try");
check("A6: Try it shows a first change within 200 ms", ms <= 200, Math.round(ms));
await page.waitForFunction(() => !document.getElementById("result").hidden || !document.getElementById("err").hidden, null, { timeout: LIVE ? 90000 : 10000 });
const sample = await page.evaluate(() => ({ about: document.getElementById("about").textContent, exact: document.getElementById("exact").textContent, err: document.getElementById("err-text").textContent }));
check("A: the sample's result starts with \"About \"", sample.about.startsWith("About "), sample);
check("A: the sample's exact count is 12", sample.exact === "Exact count: 12", sample);
if (LIVE) { console.log(fails ? `${fails} failed` : "all passed"); await browser.close(); process.exit(fails ? 1 : 0); }
check("D2: the run carries the test marker and no browser id before the counting question is answered", s.runs.length === 1 && s.runs[0].test === true && s.runs[0].mode === "sample" && s.runs[0].browser === "", s.runs);
const shownLine = await page.evaluate(() => document.getElementById("shown").textContent);
check("A5: the test that showed it works, in one plain line outside the fold", shownLine === "Checked by a test that counted 30,000 different visitors to within 10%.", shownLine);
const optin = await page.evaluate(() => ({ text: document.getElementById("optin").textContent.trim(), shown: !document.getElementById("optin").hidden }));
check("D2: the counting question is asked once, below the result", optin.shown && optin.text === "Count my visits to help improve Knos? Yes No", optin);
await page.click("#optin-yes");

// ---- B4: Copy link ------------------------------------------------------------------------------------------------------
const copyMs = await page.evaluate(() => new Promise((done) => { const b = document.getElementById("copy"), t0 = performance.now();
  const mo = new MutationObserver(() => { if (b.textContent === "Copied") { mo.disconnect(); done(performance.now() - t0); } });
  mo.observe(b, { childList: true, characterData: true, subtree: true }); b.click(); setTimeout(() => done(9999), 2000); }));
const copied = await page.evaluate(() => navigator.clipboard.readText().catch(() => ""));
check("B4: Copy link reads Copied within 400 ms and the link is on the clipboard", copyMs <= 400 && copied === "https://knos.onrender.com/r/r1/", [Math.round(copyMs), copied]);

// ---- A4: Use my data ----------------------------------------------------------------------------------------------------
await page.click("#mine");
const mineState = await page.evaluate(() => ({ value: document.getElementById("list").value, focused: document.activeElement === document.getElementById("list"),
  limits: document.getElementById("limits").textContent, label: document.getElementById("list-label").textContent }));
check("A4: Use my data empties the box and puts the cursor in it", mineState.value === "" && mineState.focused, mineState);
check("A4: the screen states the two limits as numbers", mineState.limits === "Up to 100,000 lines. A run stops after 10 seconds.", mineState);
await page.keyboard.type("red\nblue\ngreen\nred\nblue");
const runOwn = async () => { await page.click("#try"); await page.waitForFunction(() => document.getElementById("state").dataset.state !== "working", null, { timeout: 10000 }); };
await runOwn();
const own = await page.evaluate(() => ({ exact: document.getElementById("exact").textContent, left: document.getElementById("left").textContent, priv: !document.getElementById("private").hidden }));
check("A: 5 lines with 3 different items read Exact count: 3", own.exact === "Exact count: 3", own);
check("C3: after an own-data run the screen says how many free runs are left today", own.left === `${N.free_runs_per_day - 1} free runs left today`, own);
check("B1: an own-data result says only people with its link can see it", own.priv, own);
check("D2: after Yes, the own-data run carries a browser id and the test marker", s.runs[1].mode === "own" && /^[0-9a-f]{24}$/.test(s.runs[1].browser) && s.runs[1].test === true, s.runs[1]);

// ---- C: until the free runs end, then the pay screen -------------------------------------------------------------------
for (let i = 1; i < N.free_runs_per_day; i++) await runOwn();
const last = await page.evaluate(() => document.getElementById("left").textContent);
check("C3: the last free run says 0 free runs left today", last === "0 free runs left today", last);
await runOwn();
const payScreen = await page.evaluate(() => ({ shown: !document.getElementById("pay").hidden, h: document.getElementById("pay-h").textContent, line: document.getElementById("pay-line").textContent,
  primary: [...document.querySelectorAll("#pay .go")].filter((b) => b.offsetParent).map((b) => b.textContent), no: !!document.getElementById("pay-no").offsetParent,
  box: !!document.getElementById("list").offsetParent }));
check("C4: the pay screen's headline is the pack from docs/data/pricing.json", payScreen.shown && payScreen.h === `${N.pack_runs} more runs for $${N.pack_price} in test money`, payScreen);
check("C4: one line says it is test money and nothing is charged", payScreen.line === "Today this is test money. Nothing is charged.", payScreen);
check("C4: one main control, Pay with test money, and a Not now", payScreen.primary.join("|") === "Pay with test money" && payScreen.no && !payScreen.box, payScreen);
await page.click("#pay-go");
const confirm = await page.evaluate(() => ({ what: document.getElementById("pay-what").textContent, primary: [...document.querySelectorAll("#pay .go")].filter((b) => b.offsetParent).map((b) => b.textContent) }));
check("C4: a confirm step says in one sentence what will happen", confirm.what === `This records a $${N.pack_price} test payment for ${N.pack_runs} more runs. Nothing is charged.` && confirm.primary.join("|") === "Yes, record it", confirm);
await page.evaluate(() => { const b = document.getElementById("pay-yes"); b.click(); b.click(); });   // a second press at once
await page.waitForFunction(() => document.getElementById("pay").hidden, null, { timeout: 10000 });
const after = await page.evaluate(() => ({ step: document.getElementById("step").textContent, box: !!document.getElementById("list").offsetParent }));
check("C4: a second press records nothing twice", s.pays.length === 1 && s.presses.size === 1, s.pays);
check("C4: back to the tool with 20 runs left", after.step === `${N.pack_runs} runs left` && after.box, after);
await runOwn();
const paidRun = await page.evaluate(() => ({ exact: document.getElementById("exact").textContent, left: document.getElementById("left").textContent }));
check("C4: one more run after the test payment", paidRun.exact === "Exact count: 3" && paidRun.left === `${N.pack_runs - 1} runs left`, paidRun);

// ---- A6: a slow run, and Stop ------------------------------------------------------------------------------------------
s.delay = 4000;
await page.click("#try");
await page.waitForTimeout(1300);
const slow = await page.evaluate(() => ({ spin: !document.getElementById("spin").hidden, stop: !!document.getElementById("stop").offsetParent, step: document.getElementById("step").textContent,
  live: document.getElementById("state").getAttribute("aria-live"), stopBox: document.getElementById("stop").getBoundingClientRect() }));
check("A6: from 1 s a moving sign, the step with its seconds, and Stop", slow.spin && slow.stop && /^Sending your list to Knos, 1 s$/.test(slow.step) && slow.live === "polite", slow);
check("A6: Stop is 44 by 44 px at least", slow.stopBox.width >= 44 && slow.stopBox.height >= 44, slow.stopBox);
await page.click("#stop");
const stopped = await page.evaluate(() => ({ err: document.getElementById("err-text").textContent, value: document.getElementById("list").value, working: document.getElementById("state").dataset.state }));
check("A6: Stop stops the run and keeps the list in the box", /stopped/.test(stopped.err) && stopped.value === "red\nblue\ngreen\nred\nblue" && stopped.working === "idle", stopped);
s.delay = 0;

// ---- errors: over a limit, and no answer --------------------------------------------------------------------------------
s.fail = "413";
await runOwn();
const big = await page.evaluate(() => ({ err: document.getElementById("err-text").textContent, next: document.getElementById("err-next").textContent, value: document.getElementById("list").value }));
check("A4: over a limit, the server's message, 12 words or more, a next step, and the list kept", words(big.err) >= 12 && /limit is 100,000 lines/.test(big.err) && big.next === "Try a shorter list" && big.value.length > 0, big);
s.fail = "down";
await runOwn();
const down = await page.evaluate(() => ({ err: document.getElementById("err-text").textContent, next: document.getElementById("err-next").textContent }));
check("errors: a server that does not answer gets a first-person line of 12 words or more and Try again", words(down.err) >= 12 && /^I could not reach/.test(down.err) && down.next === "Try again", down);
s.fail = null;
check("D2: every run the page sent carried the test marker", s.unmarked === 0, s.unmarked);

await browser.close(); server.close();
console.log(fails ? `${fails} failed` : "all passed");
process.exit(fails ? 1 : 0);
