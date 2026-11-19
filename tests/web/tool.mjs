// node tests/web/tool.mjs <site dir>      the front door's first tool on a build of the site, the hosted server mocked
// node tests/web/tool.mjs --live          the same first steps on the published front door against the live server
//
// Round 13 (v0328 research ROUND13-ITEMS.md part A, R13 SPEC.md and SPEC2.md). On a build served as GitHub Pages serves
// it (under /Knos/), in headless Chromium at 360 by 800 with no stored state, the hosted server answered by a stand-in
// that keeps the API contract and the program's interface of SPEC2.md (POST /api/run, POST /api/pay, GET /api/tools; the
// 402, 413 and 408 answers):
//   A  "Proved by": the first screen holds 40 words or fewer and none of the PLAIN-WORDS rule's words; "Check my data" shows a
//      first change within 200 ms (SPEC: U1 R2 and R3) and a sentence that starts "Failed at row " or "Passed: all ";
//      "Use my data" shows "Choose a file", "Which column?" and the limit, in that order; file 2 of A8 given as a file,
//      its column picked, "must stay above" and its limit set, "Check my data" reads "Failed at row 37"; "Copy link" reads
//      "Copied" within 400 ms
//   A6 a slow run shows a moving sign, the step and Stop from 1 s; Stop stops it and keeps the file in the box
//   C  own-data runs until the free runs end; the pay screen's strings are the ones docs/data/pricing.json gives; "Pay with
//      test money", its confirm step, a second press that records nothing twice, "20 runs left", and one more run
//   errors: the server's 413 message and a server that does not answer, each 12 words or more with the file kept
// Every run the page sends carries the test marker (D2). No `playwright` package or no browser: SKIP (tests/web/overflow.mjs).
import { createServer } from "node:http";
import { readFileSync, existsSync, statSync, mkdtempSync, writeFileSync, rmSync, cpSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { join, extname, dirname, resolve } from "node:path";
import { tmpdir } from "node:os";
import { fileURLToPath } from "node:url";
import { chromiumOrSkip, TYPES } from "./overflow.mjs";

const here = dirname(fileURLToPath(import.meta.url));
const LIVE = process.argv[2] === "--live";
const given = LIVE ? null : process.argv[2];
if (!LIVE && (!given || !existsSync(join(given, "index.html")))) { console.error("usage: node tests/web/tool.mjs <site dir> | --live"); process.exit(2); }
// a build made for the earlier one-page app (KNOS_SPA_AT_ROOT=1, as the web job builds it) has that app at its root: the
// front door is composed here on a copy, as scripts/build_site.sh composes the published site (scripts/site_pages.py)
let root = given, made = null;
if (!LIVE && !readFileSync(join(given, "index.html"), "utf8").includes('id="list"')) {
  made = mkdtempSync(join(tmpdir(), "knos-door-")); root = resolve(made, "site");
  cpSync(given, root, { recursive: true });
  execFileSync(process.env.PYTHON || "python3", [join(here, "..", "..", "scripts", "site_pages.py"), root], { stdio: "ignore" });
}
const pricing = JSON.parse(readFileSync(join(here, "../../docs/data/pricing.json"), "utf8")).numbers;
const N = Object.fromEntries(Object.entries(pricing).map(([k, v]) => [k, v.value]));
// the PLAIN-WORDS rule of ROUND13-ITEMS.md: none of these on a front, tool, result, price or status screen outside a closed How it works fold
export const PLAIN = ["tx", "hash", "testnet", "devnet", "mainnet", "proof", "prove", "verify", "contract", "token", "wallet", "agent", "job", "oracle", "LMSR", "NEAR", "Solana", "IRIS", "MCP", "API", "JSON"];
const plainHit = (text) => PLAIN.filter((w) => new RegExp(`\\b${w}s?\\b`, "i").test(text));
let fails = 0;
const check = (name, cond, detail) => { if (cond) console.log("ok  ", name); else { fails++; console.error("FAIL", name, detail === undefined ? "" : JSON.stringify(detail)); } };
const words = (s) => (String(s).match(/[A-Za-z0-9$][\w'’$%.,-]*/g) || []).length;

// file 2 of A8: the job's case2.csv (column reading_v, limit 2.5) when it is there, else the same file built here
const LIMIT_DIR = join(here, "../../near/agents/job/data/limit");
const FILE2 = existsSync(join(LIMIT_DIR, "case2.csv"))
  ? { text: readFileSync(join(LIMIT_DIR, "case2.csv"), "utf8"), column: "reading_v", limit: "2.5" }
  : { text: "cycle,capacity_ah\n" + Array.from({ length: 100 }, (_, i) => `${i + 1},${i + 1 === 37 ? 1.38 : i + 1 < 37 ? (1.9 - (i + 1) * 0.004).toFixed(3) : 1.6}`).join("\n") + "\n", column: "capacity_ah", limit: "1.4" };
const browser = await chromiumOrSkip();
const tmp = mkdtempSync(join(tmpdir(), "knos-tool-"));
const FILE2_PATH = join(tmp, "file2.csv");
writeFileSync(FILE2_PATH, FILE2.text);
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

// ---- the stand-in for the hosted server: test_limit3.py's interface, kept only in this test -------------------------------------
const LIMITS = { max_rows: 100000, max_seconds: 20 };
// a cell Python's float() reads (NaN, inf and -inf too, so a first row holding one is data); a checked value is a finite one
const reads = (s) => { const t = String(s).trim(); return t !== "" && (/^[+-]?(nan|inf|infinity)$/i.test(t) || !Number.isNaN(Number(t))); };
const isNum = (s) => { const t = String(s).trim(); return t !== "" && Number.isFinite(Number(t)); };
const rowsSaid = (u) => u.length === 1 ? `Row ${u[0]} has no number, so I did not check it.`
  : `Rows ${(u.length > 5 ? u.slice(0, 5) : u.slice(0, -1)).join(", ")} and ${u.length > 5 ? `${u.length - 5} more` : u[u.length - 1]} have no number, so I did not check them.`;
function standInCheck(table, column, rule, limit) {
  const rows = table.split(/\r?\n/).filter((l) => l.trim()).map((l) => l.split(","));
  const head = rows[0].some((c) => !reads(c));
  const names = head ? rows[0].map((c) => c.trim()) : rows[0].map((_, i) => `column ${i + 1}`);
  const at = names.indexOf(column), data = head ? rows.slice(1) : rows, lim = String(limit);
  let p = 0, first = null, fail = null; const values = [], unchecked = [];
  for (let r = 1; r <= data.length; r++) {
    const cell = (data[r - 1][at] || "").trim();
    if (!isNum(cell)) { unchecked.push(r); continue; }
    const v = Number(cell); values.push(v);
    if (rule === "above" ? v <= limit : v >= limit) { if (!first) { first = [r, cell]; fail = [values.length, v]; } } else p++;
  }
  const said = !values.length ? ["I cannot check: no row has a number."]
    : first ? [`Failed at row ${first[0]}: ${first[1]} is not ${rule} ${lim}.`, `${p} row${p === 1 ? "" : "s"} passed.`]
    : [p === 1 ? `Passed: all 1 row stays ${rule} ${lim}.` : `Passed: all ${p} rows stay ${rule} ${lim}.`];
  if (values.length && unchecked.length) said.push(rowsSaid(unchecked));
  return { result: said.join(" "), first_failing_row: first ? first[0] : null, passed: p, unchecked, values, fail };
}
let SAMPLE = null;
function standIn() {
  const s = { runs: [], pays: [], presses: new Set(), left: new Map(), delay: 0, fail: null, unmarked: 0 };
  s.handle = async (route) => {
    const req = route.request(), url = new URL(req.url()), cors = { "access-control-allow-origin": "*", "content-type": "application/json" };
    const reply = (status, body) => route.fulfill({ status, headers: cors, body: JSON.stringify(body) });
    if (req.method() === "OPTIONS") return route.fulfill({ status: 204, headers: { ...cors, "access-control-allow-headers": "content-type", "access-control-allow-methods": "GET, POST" } });
    if (url.pathname === "/api/tools") return reply(200, { tools: [{ id: "limit-check", title: "Check a test file against a limit", sample: SAMPLE }] });
    const body = JSON.parse(req.postData() || "{}");
    if (url.pathname === "/api/run") {
      s.runs.push(body);
      if (body.test !== true) s.unmarked++;
      if (s.fail === "down") return route.abort("connectionfailed");
      if (s.delay) await new Promise((r) => setTimeout(r, s.delay));
      if (s.fail === "413") return reply(413, { error: `Your file is too big. The limit is ${LIMITS.max_rows.toLocaleString("en-US")} rows. I kept your file in the box; try a shorter one.` });
      const got = standInCheck(body.table, body.column, body.rule, body.limit);
      let left = null, free = null, paid = null;
      const mode = body.table === SAMPLE ? "sample" : "own";
      if (mode === "own") {
        const had = s.left.has(body.browser) ? s.left.get(body.browser) : { free: N.free_runs_per_day, paid: 0 };
        if (had.free + had.paid <= 0) return reply(402, { pay: { headline: `${N.pack_runs} more runs for $${N.pack_price} in test money`, line: "Today this is test money. Nothing is charged.", runs: N.pack_runs, price: `$${N.pack_price}` } });
        if (had.free > 0) had.free--; else had.paid--;
        s.left.set(body.browser, had); free = had.free; paid = had.paid; left = free + paid;
      }
      const id = `r${s.runs.length}`;
      return reply(200, { id, mode, result: got.result, first_failing_row: got.first_failing_row, passed: got.passed, unchecked: got.unchecked,
        shown_by: "Checked by a test of 14 cases with known answers.", link: `https://knos.onrender.com/r/${id}/`,
        chart: { points: got.values.map((v, i) => [i + 1, v]), fail: got.fail, limit: body.limit, rule: body.rule, n: got.values.length },
        runs_left: left, free_left: free, paid_left: paid, limits: LIMITS });
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
SAMPLE = await page.evaluate(() => document.getElementById("list").defaultValue);

// ---- A: the first screen ------------------------------------------------------------------------------------------------
const first = await page.evaluate(() => {
  const H = innerHeight, out = [];
  const walk = (n) => {
    if (n.nodeType === 3) { const r = document.createRange(); r.selectNodeContents(n); const b = r.getBoundingClientRect(); if (b.height && b.top < H && b.bottom > 0 && n.textContent.trim()) out.push(n.textContent.trim()); return; }
    if (n.nodeType !== 1 || /^(SCRIPT|STYLE|TEXTAREA|NOSCRIPT|OPTION)$/.test(n.tagName)) return;
    const cs = getComputedStyle(n); if (cs.display === "none" || cs.visibility === "hidden") return;
    if (n.tagName === "SELECT") { out.push(n.options[n.selectedIndex].textContent.trim()); return; }   // a closed list shows its chosen line
    if (n.tagName === "DETAILS" && !n.open) { const sm = n.querySelector("summary"); if (sm) walk(sm); return; }
    for (const c of n.childNodes) walk(c);
  };
  walk(document.body);
  const box = document.getElementById("list").getBoundingClientRect(), go = document.getElementById("try").getBoundingClientRect();
  return { text: out.join(" "), h1: [...document.querySelectorAll("h1")].map((h) => h.textContent.trim()), title: document.getElementById("t-title").textContent.trim(),
    label: document.getElementById("list-label").textContent.trim(), boxBottom: box.bottom, goBottom: go.bottom, goW: go.width, goH: go.height, H,
    lines: document.getElementById("list").value.split("\n"), column: document.getElementById("colname").textContent, rule: document.getElementById("rule").selectedOptions[0].textContent,
    limit: document.getElementById("limit").value, scrollX: document.documentElement.scrollWidth - innerWidth, font: parseFloat(getComputedStyle(document.body).fontSize) };
});
check("A: the first screen is 40 words or fewer (the box's sample is the input, not words of the screen)", words(first.text) <= 40, [words(first.text), first.text]);
check("A: the first screen has none of the PLAIN-WORDS rule's words", plainHit(first.text).length === 0, plainHit(first.text));
check("A: one h1, the headline, and the tool's title under it", first.h1.length === 1 && first.h1[0] === "What can you do with Knos?" && first.title === "Check a test file against a limit", first);
check("A2: the sample is loaded and labelled, two columns cycle and capacity_ah", /^Sample: (NASA|made-up) battery test$/.test(first.label) && first.lines[0] === "cycle,capacity_ah" && first.lines.length > 100, [first.label, first.lines.slice(0, 2)]);
// F1B: the rule line says the sample's column in plain words; capacity_ah, the file's own name, is the box's and the fold's
check("A2: the limit is filled in: charge held must stay above 1.4", first.column === "charge held" && !/capacity_ah/.test(first.text) && first.rule === "must stay above" && first.limit === "1.4", first);
check("A: the box and Check my data are whole on the first screen, no scroll", first.boxBottom <= first.H && first.goBottom <= first.H && first.scrollX <= 0, first);
check("A: Check my data is the main action, 48 px tall at least and 300 px wide at least; body text 18 px", first.goH >= 48 && first.goW >= 300 && first.font >= 18, first);

// a first change within 200 ms of a press: the first mutation of the page after the click
const firstChange = (sel) => page.evaluate((sel) => new Promise((done) => {
  const t0 = performance.now(), mo = new MutationObserver(() => { mo.disconnect(); done(performance.now() - t0); });
  mo.observe(document.body, { subtree: true, childList: true, characterData: true, attributes: true });
  document.querySelector(sel).click();
  setTimeout(() => { mo.disconnect(); done(9999); }, 2000);
}), sel);
const ms = await firstChange("#try");
check("A6: Check my data shows a first change within 200 ms", ms <= 200, Math.round(ms));
await page.waitForFunction(() => !document.getElementById("result").hidden || !document.getElementById("err").hidden, null, { timeout: LIVE ? 90000 : 10000 });
const sample = await page.evaluate(() => ({ about: document.getElementById("about").textContent, err: document.getElementById("err-text").textContent,
  chart: !!document.querySelector("#chart svg polyline"), ring: !!document.querySelector("#chart svg circle") }));
check("A: the sample's result is a sentence that starts with \"Failed at row \" or \"Passed: all \"", /^(Failed at row |Passed: all )/.test(sample.about), sample);
check("A2: under the sentence, one chart: the values as a line, the first failing row marked", sample.chart && sample.ring === sample.about.startsWith("Failed"), sample);
if (LIVE) { console.log(fails ? `${fails} failed` : "all passed"); await browser.close(); process.exit(fails ? 1 : 0); }
check("D2: the run carries the test marker and no browser id before the counting question is answered", s.runs.length === 1 && s.runs[0].test === true && s.runs[0].mode === "sample" && s.runs[0].browser === "" && s.runs[0].column === "capacity_ah" && s.runs[0].limit === 1.4, s.runs);
const shownLine = await page.evaluate(() => document.getElementById("shown").textContent);
check("A5: the test that showed it works, in one plain line outside the fold", shownLine === "Checked by a test of 14 cases with known answers.", shownLine);
const fold = await page.evaluate(() => [...document.querySelectorAll("#how li")].map((li) => li.textContent.trim()));
check("A5: the fold holds, in order, the sample's source, its column by the file's name (F1B), what it does not do, your file, the test, the price, who built it",
  fold.length === 7 && /^The sample is /.test(fold[0]) && fold[1] === "The sample's column capacity_ah holds the battery's capacity in amp hours." && /does not judge whether the limit is the right one/.test(fold[2]) && /^Your file goes/.test(fold[3]) && /^The test that showed it works/.test(fold[4]) && /test money/.test(fold[5]) && /^Who built it/.test(fold[6]), fold);
const optin = await page.evaluate(() => ({ text: document.getElementById("optin").textContent.trim(), shown: !document.getElementById("optin").hidden }));
check("D2: the counting question is asked once, below the result", optin.shown && optin.text === "Count my visits to help improve Knos? Yes No", optin);
await page.click("#optin-yes");

// ---- B4: Copy link ------------------------------------------------------------------------------------------------------
const copyMs = await page.evaluate(() => new Promise((done) => { const b = document.getElementById("copy"), t0 = performance.now();
  const mo = new MutationObserver(() => { if (b.textContent === "Copied") { mo.disconnect(); done(performance.now() - t0); } });
  mo.observe(b, { childList: true, characterData: true, subtree: true }); b.click(); setTimeout(() => done(9999), 2000); }));
const copied = await page.evaluate(() => navigator.clipboard.readText().catch(() => ""));
check("B4: Copy link reads Copied within 400 ms and the link is on the clipboard", copyMs <= 400 && copied === "https://knos.onrender.com/r/r1/", [Math.round(copyMs), copied]);

// ---- A3: Use my data, with file 2 of A8 ---------------------------------------------------------------------------------
await page.click("#mine");
const mineState = await page.evaluate(() => {
  const vis = (id) => !!document.getElementById(id).offsetParent;
  const order = ["file", "col", "limit"].map((id) => document.getElementById(id).getBoundingClientRect().top);
  return { value: document.getElementById("list").value, file: vis("file"), col: vis("col"), limit: document.getElementById("limit").value,
    labels: [...document.querySelectorAll("#form label")].filter((l) => l.offsetParent).map((l) => l.textContent.trim()), ordered: order[0] < order[1] && order[1] <= order[2],
    limits: document.getElementById("limits").textContent };
});
check("A3: Use my data shows Choose a file, Which column? and the limit, in that order, each field with a visible label (U3.md:165)", mineState.file && mineState.col && mineState.ordered && mineState.labels.join("|") === "Choose a file|Or paste a table|Which column?|The rule|The limit" && mineState.value === "", mineState);
check("A4: the screen states the two limits as numbers", mineState.limits === "Up to 100,000 rows. A run stops after 20 seconds.", mineState);
await page.setInputFiles("#file", FILE2_PATH);
await page.waitForFunction(() => document.getElementById("col").options.length > 1, null, { timeout: 5000 });
await page.selectOption("#col", FILE2.column);
await page.selectOption("#rule", "above");
await page.fill("#limit", FILE2.limit);
const runOwn = async () => { await page.click("#try"); await page.waitForFunction(() => document.getElementById("state").dataset.state !== "working", null, { timeout: 10000 }); };
await runOwn();
const own = await page.evaluate(() => ({ about: document.getElementById("about").textContent, left: document.getElementById("left").textContent, priv: !document.getElementById("private").hidden,
  ring: document.querySelector("#chart svg text") ? document.querySelector("#chart svg text").textContent : "" }));
check("A: file 2 of A8 reads \"Failed at row 37\"", own.about.startsWith("Failed at row 37: ") && own.about.endsWith(" 98 rows passed.") && own.ring === "Row 37", own);
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
const paidRun = await page.evaluate(() => ({ about: document.getElementById("about").textContent, left: document.getElementById("left").textContent }));
check("C4: one more run after the test payment", paidRun.about.startsWith("Failed at row 37: ") && paidRun.left === `${N.pack_runs - 1} runs left`, paidRun);

// ---- A6: a slow run, and Stop ------------------------------------------------------------------------------------------
s.delay = 4000;
// after a verdict the box is empty (UX/U6.md line 33) and Check my data checks the same table again, putting it back in the box
const kept = await page.evaluate(() => document.getElementById("list").value) || FILE2.text.replace(/\r\n/g, "\n");
await page.click("#try");
await page.waitForTimeout(1300);
const slow = await page.evaluate(() => ({ spin: !document.getElementById("spin").hidden, stop: !!document.getElementById("stop").offsetParent, step: document.getElementById("step").textContent,
  live: document.getElementById("state").getAttribute("aria-live"), stopBox: document.getElementById("stop").getBoundingClientRect() }));
check("A6: from 1 s a moving sign, the step with its seconds, and Stop", slow.spin && slow.stop && /^Sending your file to Knos, 1 s$/.test(slow.step) && slow.live === "polite", slow);
check("A6: Stop is 44 by 44 px at least", slow.stopBox.width >= 44 && slow.stopBox.height >= 44, slow.stopBox);
await page.click("#stop");
const stopped = await page.evaluate(() => ({ err: document.getElementById("err-text").textContent, value: document.getElementById("list").value, working: document.getElementById("state").dataset.state }));
check("A6: Stop stops the run and keeps the file in the box", /stopped/.test(stopped.err) && stopped.value === kept && stopped.working === "idle", stopped);
s.delay = 0;

// ---- errors: over a limit, and no answer --------------------------------------------------------------------------------
s.fail = "413";
await runOwn();
const big = await page.evaluate(() => ({ err: document.getElementById("err-text").textContent, next: document.getElementById("err-next").textContent, value: document.getElementById("list").value }));
check("A4: over a limit, \"Your file is too big. The limit is <n> rows.\", 12 words or more, a next step, and the file kept", words(big.err) >= 12 && /^Your file is too big\. The limit is 100,000 rows\./.test(big.err) && big.next === "Try a smaller file" && big.value.length > 0, big);
s.fail = "down";
await runOwn();
const down = await page.evaluate(() => ({ err: document.getElementById("err-text").textContent, next: document.getElementById("err-next").textContent }));
check("errors: a server that does not answer gets a first-person line of 12 words or more and Try again", words(down.err) >= 12 && /^I could not reach/.test(down.err) && down.next === "Try again", down);
s.fail = null;
// F1B: no row has a number: under "I cannot check", the reason names the rows (the answer's unchecked list)
await page.fill("#list", "cycle,reading\n1,NaN\n2,NaN\n3,NaN"); await page.dispatchEvent("#list", "input");
await page.selectOption("#col", "reading"); await page.fill("#limit", "1.4");
await runOwn();
const none = await page.evaluate(() => ({ about: document.getElementById("about").textContent, reason: document.getElementById("reason").textContent, shown: !document.getElementById("reason").hidden }));
check("F1B: no row has a number: the reason names rows 1, 2 and 3", none.about === "I cannot check: no row has a number." && none.shown && none.reason === "Rows 1, 2 and 3 have no number in reading.", none);
check("D2: every run the page sent carried the test marker", s.unmarked === 0, s.unmarked);

await browser.close(); server.close(); rmSync(tmp, { recursive: true, force: true }); if (made) rmSync(made, { recursive: true, force: true });
console.log(fails ? `${fails} failed` : "all passed");
process.exit(fails ? 1 : 0);
