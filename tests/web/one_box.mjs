// node tests/web/one_box.mjs <site dir>
//
// The front door's laws of IQ PLAN.md (22 Nov 2026) in headless Chromium, on a local build (scripts/build_site.sh), the
// hosted server and NEAR testnet answered by stand-ins kept in this file:
//   L01  one box: the first screen at 360 by 800 holds exactly one text box, one primary button and at most 3 controls;
//        the sample table, a claim's name, a paper's arXiv link and a pull request's link each show their first answer
//        words within 1 s and the whole answer within 2 s of the press; a question that matches no record answers with
//        the nearest records and a "Prove it" link, never an error; an empty box checks the one example
//   L02  the title, the description and the link preview are one sentence under 125 characters, "Knos is a(n) ... that
//        helps ..."; the first screen counts at most 13 words (its box's hint included) and at most 3 buttons
//   L05  at a 200% root font size, the front door, pricing and status show no horizontal scroll at 320 by 712
//   L11  three live numbers under the first screen, each an <a> to its public record, equal to what the record returned;
//        with the record blocked the slots are empty; the uptime line reads "Up N of M checks in the last 7 days"
//   L20  the front door marks its error, price and consent text data-must-understand
//   L22  after 3 s with no tap a 48 px pointer shows once (never on the next visit); the button carries an arrow; the
//        loop has a pause control; with reduced motion nothing moves; the headline's weight is 400 or less
//   L28  "MIT licensed" and a link to the repository's fork page; no star count when the build read none
// No node, no playwright package or no browser: SKIP (tests/web/overflow.mjs chromiumOrSkip).
import { createServer } from "node:http";
import { readFileSync, existsSync, statSync } from "node:fs";
import { join, extname, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { chromiumOrSkip, TYPES } from "./overflow.mjs";

const here = dirname(fileURLToPath(import.meta.url));
const root = process.argv[2];
if (!root || !existsSync(join(root, "index.html"))) { console.error("usage: node tests/web/one_box.mjs <site dir>"); process.exit(2); }
const EN = JSON.parse(readFileSync(join(here, "../../web/i18n/en.json"), "utf8")).strings;
const CLAIMS = JSON.parse(readFileSync(join(here, "../../near/claims/claims.json"), "utf8")).claims;
const SAMPLE = readFileSync(join(here, "../../near/agents/job/data/limit/sample.csv"), "utf8").replace(/\r\n/g, "\n").replace(/\n+$/, "");
let fails = 0;
const check = (name, cond, detail) => { if (cond) console.log("ok  ", name); else { fails++; console.error("FAIL", name, detail === undefined ? "" : JSON.stringify(detail)); } };

const browser = await chromiumOrSkip();
const server = createServer((req, res) => {
  const path = decodeURIComponent(new URL(req.url, "http://x").pathname);
  const file = path.startsWith("/Knos/") ? join(root, path.slice(6) || "index.html") : null;
  const hit = file && existsSync(file) && statSync(file).isFile() ? file : file && existsSync(join(file, "index.html")) ? join(file, "index.html") : null;
  if (!hit) { res.writeHead(404, { "content-type": "text/html" }); return res.end(readFileSync(join(root, "404.html"))); }
  res.writeHead(200, { "content-type": TYPES[extname(hit)] || "application/octet-stream" }); res.end(readFileSync(hit));
});
await new Promise((r) => server.listen(0, "127.0.0.1", r));
const base = `http://127.0.0.1:${server.address().port}/Knos/`;

// ---- stand-ins --------------------------------------------------------------------------------------------------------
const cors = { "access-control-allow-origin": "*", "content-type": "application/json" };
const TOTALS = { "knos-usdc-1102.testnet": { locked: "40000000", paid: "31500000", refunded: "0", open: "8500000", conserved: true } };
const RECORDS = { "agent-a": { passes: 3, fails: 1, rejected: 0 }, "agent-a2": { passes: 1, fails: 0, rejected: 0 }, "agent-b": { passes: 0, fails: 2, rejected: 1 }, "agent-b2": { passes: 0, fails: 0, rejected: 0 } };
const now = Date.now(), UPTIME = [true, true, false, true].map((up, i) => JSON.stringify({ at: new Date(now - (i + 1) * 36e5).toISOString(), up })).join("\n") + "\n";
const near = (route) => {
  const body = JSON.parse(route.request().postData() || "{}"), p = body.params || {}, args = JSON.parse(Buffer.from(p.args_base64 || "", "base64").toString() || "{}");
  const value = p.method_name === "get_totals" ? TOTALS : p.method_name === "get_agent_record" ? RECORDS[String(args.agent).split(".")[0]] || { passes: 0, fails: 0, rejected: 0 } : null;
  if (value === null) return route.fulfill({ status: 200, headers: cors, body: JSON.stringify({ jsonrpc: "2.0", id: "k", error: { message: "no" } }) });
  return route.fulfill({ status: 200, headers: cors, body: JSON.stringify({ jsonrpc: "2.0", id: "k", result: { result: [...Buffer.from(JSON.stringify(value))] } }) });
};
const runs = [];
let blockedRecord = false;
function hosted(route) {
  const req = route.request(), url = new URL(req.url());
  const reply = (status, body) => route.fulfill({ status, headers: cors, body: JSON.stringify(body) });
  if (req.method() === "OPTIONS") return route.fulfill({ status: 204, headers: { ...cors, "access-control-allow-headers": "content-type", "access-control-allow-methods": "GET, POST" } });
  if (url.pathname === "/api/run") {
    const b = JSON.parse(req.postData() || "{}"); runs.push(b);
    const rows = b.table.split("\n").slice(1).map((l) => Number(l.split(",")[1])), r = rows.findIndex((v) => v <= b.limit) + 1;
    return reply(200, { id: "r1", mode: b.mode, result: r ? `Failed at row ${r}: ${rows[r - 1]} is not above ${b.limit}. ${r - 1} rows passed.` : `Passed: all ${rows.length} rows stay above ${b.limit}.`,
      first_failing_row: r || null, passed: r ? r - 1 : rows.length, unchecked: [], link: "https://knos.onrender.com/r/r1/",
      chart: { points: rows.map((v, i) => [i + 1, v]), fail: r ? [r, rows[r - 1]] : null, limit: b.limit, rule: "above", n: rows.length }, runs_left: null, limits: { max_rows: 100000, max_seconds: 20 } });
  }
  if (url.pathname === "/api/near/claims") return reply(200, { read_at: "2026-11-22T00:00:00Z", claims: Object.fromEntries(CLAIMS.map((c) => [c.name, { last_proof: "job-1", proofs: 2, demand: { behind_usd: 12.5 } }])) });
  if (url.pathname === "/api/near/claim/look") return reply(200, { ok: true, known: false, title: "A paper Knos has not checked", quote: { checker: "a person", price: "not published", time: "not published" } });
  if (url.pathname === "/api/tools") return reply(200, { tools: [] });
  // the door's live numbers come from the Knos server, which reads the jobs contract and the scheduled check's uptime.jsonl
  if (url.pathname === "/api/near/totals" || url.pathname === "/api/uptime") {
    if (blockedRecord) return route.abort();
    if (url.pathname === "/api/uptime") { const ups = UPTIME.trim().split(/\n/).map((l) => JSON.parse(l).up); return reply(200, { days: 7, up: ups.filter(Boolean).length, all: ups.length }); }
    const recs = Object.values(RECORDS);
    return reply(200, { since_upgrade: { contract: "jobs.knos-swarm-1105.testnet", paid_usd: Number(TOTALS["knos-usdc-1102.testnet"].paid) / 1e6,
      jobs_paid: recs.reduce((s, r) => s + r.passes, 0), tried: recs.filter((r) => r.passes + r.fails + r.rejected > 0).length } });
  }
  return reply(404, { error: "no such route" });
}
async function ctxWith({ blockRecord = false, reduced = false, w = 360, h = 800 } = {}) {
  const ctx = await browser.newContext({ viewport: { width: w, height: h }, reducedMotion: reduced ? "reduce" : "no-preference" });
  blockedRecord = blockRecord;
  await ctx.route(/^https:\/\/knos\.onrender\.com\/api\/visit/, (r) => r.abort());
  await ctx.route(/^https:\/\/knos\.onrender\.com\//, hosted);
  await ctx.route(/^https:\/\/rpc\.testnet\./, blockRecord ? (r) => r.abort() : near);
  await ctx.route(/^https:\/\/raw\.githubusercontent\.com\/.*uptime\.jsonl/, blockRecord ? (r) => r.abort() : (r) => r.fulfill({ status: 200, headers: { ...cors, "content-type": "text/plain" }, body: UPTIME }));
  await ctx.route(/^https:\/\/(api\.github\.com|fonts\.)/, (r) => r.abort());
  return ctx;
}

// ---- L02: one sentence ----------------------------------------------------------------------------------------------------
const said = EN.goal.text;
const ctx = await ctxWith();
const page = await ctx.newPage();
await page.goto(base, { waitUntil: "load" });
const head = await page.evaluate(() => ({ title: document.title, desc: document.querySelector('meta[name="description"]').content, og: document.querySelector('meta[property="og:description"]').content }));
check("L02: title, description and link preview are the one sentence", head.title === said && head.desc === said && head.og === said, head);
check("L02: the sentence is under 125 characters, \"Knos is a(n) ... that helps ...\"", said.length < 125 && /^Knos is an? .+ that helps .+/.test(said), said);

// ---- L01 and L02: the first screen ------------------------------------------------------------------------------------------
const first = await page.evaluate(() => {
  const H = innerHeight, W = innerWidth, words = [];
  const shown = (e) => { const r = e.getBoundingClientRect(), cs = getComputedStyle(e); return r.width > 0 && r.height > 0 && r.top < H && r.bottom > 0 && cs.visibility !== "hidden" && !e.closest("[hidden]"); };
  const walk = (n) => {
    if (n.nodeType === 3) { const r = document.createRange(); r.selectNodeContents(n); const b = r.getBoundingClientRect(); if (b.height && b.top < H && b.bottom > 0 && n.textContent.trim()) words.push(n.textContent.trim()); return; }
    if (n.nodeType !== 1 || /^(SCRIPT|STYLE|TEXTAREA|TEMPLATE|NOSCRIPT|OPTION)$/.test(n.tagName)) return;
    const cs = getComputedStyle(n); if (cs.display === "none" || cs.visibility === "hidden") return;
    if (n.tagName === "DETAILS" && !n.open) { const sm = n.querySelector("summary"); if (sm) walk(sm); return; }
    for (const c of n.childNodes) walk(c);
  };
  walk(document.body);
  const boxes = [...document.querySelectorAll("textarea, input:not([type=hidden]):not([type=file])")].filter(shown);
  for (const b of boxes) if (b.placeholder && !b.value) words.push(b.placeholder);
  const controls = [...document.querySelectorAll("a[href], button, input:not([type=hidden]), select, textarea, summary")].filter(shown);
  const h1 = document.querySelector("h1");
  return { text: words.join(" "), boxes: boxes.map((b) => b.id), primary: [...document.querySelectorAll("[data-primary]")].filter(shown).map((b) => b.id),
    controls: controls.map((c) => c.id || c.tagName.toLowerCase() + ":" + c.textContent.trim().slice(0, 20)), buttons: controls.filter((c) => c.tagName === "BUTTON" || c.tagName === "SUMMARY").length,
    h1: h1.textContent.trim(), weight: Number(getComputedStyle(h1).fontWeight), arrow: !!document.querySelector("#try svg path"), scrollX: document.documentElement.scrollWidth - W };
});
const nWords = (first.text.match(/[\p{L}\p{N}$][\p{L}\p{N}'’$%.,-]*/gu) || []).length;
check("L01: the first screen holds exactly one text box and one primary button", first.boxes.length === 1 && first.boxes[0] === "list" && first.primary.length === 1 && first.primary[0] === "try", first);
check("L01: at most 3 controls on the first screen (U3 Rule 1a)", first.controls.length <= 3, first.controls);
check("L02: the first screen counts at most 13 words and at most 3 buttons", nWords <= 13 && first.buttons <= 3, [nWords, first.text, first.buttons]);
check("L01: the headline is the box's label, \"Ask anything about research\"", first.h1 === EN["door.headline"].text, first.h1);
check("L22: the headline's weight is 400 or less; the button carries an arrow", first.weight <= 400 && first.arrow, first);

// ---- L01: what the box answers ----------------------------------------------------------------------------------------------
const answerTimes = async (text, done) => {
  await page.fill("#list", text); await page.dispatchEvent("#list", "input");
  return page.evaluate(({ done }) => new Promise((ok) => {
    const t0 = performance.now(); let firstAt = null;
    const look = () => { const a = document.querySelector("#about"), o = document.getElementById("ask-out");
      const any = (a && !document.getElementById("result").hidden && a.textContent.trim()) || (o && !o.hidden && o.textContent.trim()) || (!document.getElementById("state").hidden && document.getElementById("step").textContent.trim());
      if (any && firstAt === null) firstAt = performance.now() - t0;
      const whole = document.querySelector(done); if (whole && whole.textContent.trim() && whole.offsetParent) { mo.disconnect(); ok({ first: firstAt, whole: performance.now() - t0, text: whole.textContent.trim() }); } };
    const mo = new MutationObserver(look); mo.observe(document.body, { subtree: true, childList: true, characterData: true, attributes: true });
    document.getElementById("try").click(); look();
    setTimeout(() => { mo.disconnect(); ok({ first: firstAt, whole: null, text: "" }); }, 4000);
  }), { done });
};
const t1 = await answerTimes(SAMPLE, "#result:not([hidden]) #about");
check("L01: the sample table answers its first words within 1 s and the whole answer within 2 s", t1.first !== null && t1.first <= 1000 && t1.whole !== null && t1.whole <= 2000 && /^Failed at row \d+/.test(t1.text), t1);
check("L01: a pasted sample table runs the limit check on the sample", runs.length === 1 && runs[0].mode === "sample" && runs[0].column === "capacity_ah" && runs[0].limit === 1.4, runs);
const t2 = await answerTimes("hyperloglog", "#ask-out:not([hidden]) .verdict");
check("L01: a claim's name answers from Knos's records within 1 s, whole within 2 s", t2.first !== null && t2.first <= 1000 && t2.whole !== null && t2.whole <= 2000 && t2.text === EN["ask.holds"].text, t2);
const ax = CLAIMS.find((c) => c.arxiv);
const t3 = await answerTimes(`https://arxiv.org/abs/${ax.arxiv}`, "#ask-out:not([hidden]) .verdict");
check("L01: a paper's arXiv link answers from its claim within 1 s, whole within 2 s", t3.first !== null && t3.first <= 1000 && t3.whole !== null && t3.whole <= 2000 && t3.text === EN["ask.holds"].text, t3);
const t4 = await answerTimes("https://github.com/drexthealpha/Knos/pull/1", "#ask-out:not([hidden]) .verdict");
const prHref = await page.evaluate(() => (document.querySelector("#ask-out a") || {}).href || "");
check("L01: a pull request's link answers within 1 s and leads to its check", t4.whole !== null && t4.whole <= 1000 && t4.text === EN["ask.pr"].text && prHref.includes("check/#check=https://github.com/drexthealpha/Knos/pull/1"), [t4, prHref]);
const t5 = await answerTimes("how do whales sleep in cold water", "#ask-out:not([hidden]) .verdict");
const none = await page.evaluate(() => ({ prove: [...document.querySelectorAll("#ask-out a")].some((a) => a.textContent.trim() === "Prove it" && /prove\//.test(a.href)), near: document.querySelectorAll("#ask-out button.sample").length, err: !document.getElementById("err").hidden }));
check("L01: a question with no record answers with the nearest records and Prove it, never an error", t5.whole !== null && t5.text === EN["ask.none"].text && none.prove && none.near >= 1 && !none.err, [t5, none]);
await page.fill("#list", ""); await page.dispatchEvent("#list", "input");
await page.click("#try");
await page.waitForFunction(() => !document.getElementById("result").hidden, null, { timeout: 4000 }).catch(() => {});
check("L01: an empty box checks the one example, the sample", runs.length === 2 && runs[1].mode === "sample", runs.map((r) => r.mode));

// ---- L20 --------------------------------------------------------------------------------------------------------------
const marked = await page.evaluate(() => [...document.querySelectorAll("[data-must-understand]")].map((e) => e.id));
check("L20: the error, the price and the consent lines are marked data-must-understand", ["err", "pay-line", "pay-what", "optin"].every((id) => marked.includes(id)), marked);

// ---- L11: the live numbers ----------------------------------------------------------------------------------------------
await page.evaluate(() => { document.getElementById("k-more").open = true; document.getElementById("k-live").scrollIntoView(); });
await page.waitForFunction(() => document.getElementById("k-paid").textContent && document.getElementById("k-up").textContent, null, { timeout: 8000 }).catch(() => {});
const live = await page.evaluate(() => ["k-paid", "k-settled", "k-tried"].map((id) => { const a = document.getElementById(id); return { tag: a.tagName, href: a.href, text: a.textContent }; }).concat([{ up: document.getElementById("k-up").textContent }]));
const passes = Object.values(RECORDS).reduce((s, r) => s + r.passes, 0), tried = Object.values(RECORDS).filter((r) => r.passes + r.fails + r.rejected > 0).length;
check("L11: three numbers, each a link to the public record, equal to what the record returned", live.slice(0, 3).every((x) => x.tag === "A" && /^https:\/\/testnet\.nearblocks\.io\//.test(x.href))
  && live[0].text === "31.50 test dollars paid for passed work" && live[1].text === `${passes} pieces of work paid` && live[2].text === `${tried} of Knos's own test helpers tried`, live);
check("L11: the uptime line reads \"Up N of M checks in the last 7 days\"", live[3].up === "Up 3 of 4 checks in the last 7 days", live[3]);
check("L28: \"MIT licensed\" and one link to the repository's fork page; no star count the build did not read", await page.evaluate(() => document.getElementById("k-mit").textContent.includes("MIT licensed")
  && document.getElementById("k-fork").href === "https://github.com/drexthealpha/Knos/fork" && (document.getElementById("k-stars").hidden || /^\d[\d,]* stars?$/.test(document.getElementById("k-stars").textContent))));
const loopBtn = await page.evaluate(() => ({ text: document.getElementById("k-loop-btn").textContent, run: document.getElementById("k-loop").classList.contains("run") }));
check("L22: the loop runs with a pause control (WCAG 2.2.2)", loopBtn.run && loopBtn.text === "Pause", loopBtn);
await ctx.close();

const blocked = await ctxWith({ blockRecord: true });
const bp = await blocked.newPage();
await bp.goto(base, { waitUntil: "load" });
await bp.evaluate(() => { document.getElementById("k-more").open = true; document.getElementById("k-live").scrollIntoView(); });
await bp.waitForTimeout(1500);
const empty = await bp.evaluate(() => ["k-paid", "k-settled", "k-tried", "k-up"].map((id) => document.getElementById(id).textContent));
check("L11: with the record blocked the slots are empty (no placeholder text)", empty.every((t) => t === ""), empty);
await blocked.close();

// ---- L22: the pointer, once --------------------------------------------------------------------------------------------
const pctx = await ctxWith();
const pp = await pctx.newPage();
await pp.goto(base, { waitUntil: "load" });
await pp.waitForTimeout(3500);
const ptr = await pp.evaluate(() => { const p = document.getElementById("k-pointer"); if (!p) return null; const r = p.getBoundingClientRect(); return { w: r.width, h: r.height }; });
check("L22: after 3 s with no tap a 48 px pointer shows", ptr && ptr.w === 48 && ptr.h === 48, ptr);
await pp.reload({ waitUntil: "load" });
await pp.waitForTimeout(3800);
check("L22: the pointer never shows on the next visit", await pp.evaluate(() => !document.getElementById("k-pointer")));
await pctx.close();
const still = await ctxWith({ reduced: true });
const sp = await still.newPage();
await sp.goto(base, { waitUntil: "load" });
await sp.waitForTimeout(3500);
const calm = await sp.evaluate(() => ({ pointer: !!document.getElementById("k-pointer"), loop: document.getElementById("k-loop").classList.contains("run") }));
check("L22: with reduced motion nothing moves (no pointer, no loop)", !calm.pointer && !calm.loop, calm);
await still.close();

// ---- L05: 200% text ---------------------------------------------------------------------------------------------------
const big = await ctxWith({ w: 320, h: 712, blockRecord: true });
for (const rel of ["", "pricing/", "status/", "papers/", "privacy.html"]) {
  const p = await big.newPage();
  await p.goto(base + rel, { waitUntil: "load" });
  await p.addStyleTag({ content: "html { font-size: 200% !important; }" });
  await p.waitForTimeout(150);
  const m = await p.evaluate(() => ({ scrollX: document.documentElement.scrollWidth - innerWidth, body: parseFloat(getComputedStyle(document.body).fontSize) }));
  check(`L05: /${rel} at a 200% root font size: text doubles and nothing scrolls sideways at 320 px`, m.scrollX <= 0 && m.body >= 32, m);
  await p.close();
}
await big.close();

await browser.close(); server.close();
console.log(fails ? `${fails} failed` : "all passed");
process.exit(fails ? 1 : 0);
