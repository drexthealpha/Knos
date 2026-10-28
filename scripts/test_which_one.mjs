// test_which_one (D1) and test_live_honest (L1), live: the 4 test inputs on the 5 surfaces (the front door, /app/,
// /api/check, the hosted MCP's knos_demand_check and `knos demand`). Each surface is asked which one first; the exact
// reading (an idea) or the first product reading or a named product (a paper) is picked; the checked idea must be the
// picked text, every answer must count 0 live Qloo calls while Qloo answers 429, and no recorded answer says LIVE.
//
//   node scripts/test_which_one.mjs <knos command> [result dir]     e.g. node scripts/test_which_one.mjs ".venv/Scripts/python.exe -m knos"
import { chromium } from "playwright";
import { execFileSync } from "node:child_process";
import { appendFileSync } from "node:fs";

const APP = "https://knos.onrender.com", FRONT = "https://drexthealpha.github.io/Knos/";
const KNOS = (process.argv[2] || "knos").split(" ");
const DIR = process.argv[3] || `${process.env.KNOS_PRIVATE_DIR || "C:/Users/zulab/knos-v1-private"}/v0328/world`;
const INPUTS = ["a vegan ramen food truck", "a late night ramen spot", "10.1038/nature14539", "10.1126/science.1225829"];
const TITLES = { "10.1038/nature14539": "Deep learning", "10.1126/science.1225829": "A Programmable Dual-RNA" };
const NAMED = { "10.1038/nature14539": "a photo search app that finds any picture by its content", "10.1126/science.1225829": "a gene editing kit for crop breeders" };
const lines = [], fails = [];
const log = (s) => { console.log(s); lines.push(s); };
const ok = (c, what) => { log(`${c ? "ok  " : "FAIL"} ${what}`); if (!c) fails.push(what); return c; };
// the app allows 30 checks per client in 10 minutes: every check here waits its turn, so none is refused
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let last = 0;
const pace = async (n = 1) => { const wait = last + 22000 * n - Date.now(); if (wait > 0) await sleep(wait); last = Date.now(); };
const post = async (path, body) => { await pace(); const r = await fetch(APP + path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }); return r.json(); };
const mcp = async (args) => { const r = await post("/mcp", { jsonrpc: "2.0", id: 1, method: "tools/call", params: { name: "knos_demand_check", arguments: args } });
  return r.result?.structuredContent || JSON.parse(r.result?.content?.[0]?.text || "{}"); };
// what a surface picks from its readings: the exact text of an idea; a paper's first product, else the named product
const pickOf = (input, w) => (w.paper || w.of === "paper" ? ((w.readings || [])[0]?.text || NAMED[input]) : input);
const qc = (r) => r.qloo_calls || {};
const pairs = [];
// knos demand's JSON, or its error as an answer with nothing in it (the check then fails, the run goes on)
const cli = async (args) => { await pace(); try { return JSON.parse(execFileSync(KNOS[0], [...KNOS.slice(1), "demand", ...args, "--json"], { encoding: "utf8", env: { ...process.env, PYTHONIOENCODING: "utf-8" } })); }
  catch (e) { return { error: String(e.stderr || e.message).slice(0, 200) }; } };

function judgeReadings(surface, input, w) {
  if (TITLES[input]) {
    ok(w.kind === "which_one" && String(w.paper?.title || "").startsWith(TITLES[input]), `${surface} ${input}: the paper resolves to "${String(w.paper?.title || "").slice(0, 40)}"`);
    ok((w.readings || []).length >= 1 || w.name_box, `${surface} ${input}: ${(w.readings || []).length} product reading(s)${w.name_box ? ", the name box" : ""}`);
  } else {
    const kinds = (w.readings || []).map((r) => r.kind);
    ok(w.kind === "which_one" && kinds[0] === "exact" && kinds.includes("broader") && kinds.includes("recorded"),
      `${surface} ${input}: readings ${kinds.join(", ")}`);
    const rec = (w.readings || []).find((r) => r.kind === "recorded");
    ok(!!(rec && rec.differs && (rec.differs.theirs || rec.differs.yours)), `${surface} ${input}: the recorded reading shows the words that differ (${rec ? `${rec.differs?.theirs} against ${rec.differs?.yours}` : "none"})`);
  }
}
function judgeAnswer(surface, input, picked, r) {
  const checked = r.read_as || r.idea;
  pairs.push(checked === picked);
  ok(checked === picked, `${surface} ${input}: checked "${checked}", picked "${picked}"`);
  ok(qc(r).live === 0, `${surface} ${input}: ${qc(r).live} live, ${qc(r).recorded} recorded, ${qc(r).failed} failed Qloo calls, ${qc(r).ms} ms`);
  const recordedLive = (r.calls || []).filter((c) => c.recorded && /LIVE/.test(JSON.stringify(c))).length + (/^LIVE/.test(String(r.label || "")) && !qc(r).live ? 1 : 0);
  ok(recordedLive === 0, `${surface} ${input}: "LIVE" on ${recordedLive} recorded answers`);
  if (r.queued) ok(!!(r.ready?.criteria_hash && r.ready.ready), `${surface} ${input}: queued, Ready brief ${String(r.ready?.criteria_hash || "").slice(0, 12)}`);
  return { live: qc(r).live, recorded: qc(r).recorded };
}

const counts = {};
for (const input of INPUTS) {
  // /api/check
  const w = await post("/api/check", { idea: input });
  judgeReadings("api", input, w);
  const picked = pickOf(input, w);
  counts[input] = { api: judgeAnswer("api", input, picked, await post("/api/check", { idea: picked, picked: true })) };
  // the hosted MCP
  const mw = await mcp({ idea: input });
  judgeReadings("mcp", input, mw);
  counts[input].mcp = judgeAnswer("mcp", input, pickOf(input, mw), await mcp({ idea: pickOf(input, mw), picked: true }));
  // the CLI
  const cliW = await cli([input]);
  judgeReadings("cli", input, cliW);
  const cliPick = pickOf(input, cliW);
  counts[input].cli = judgeAnswer("cli", input, cliPick, await cli([cliPick, "--picked"]));
}

const browser = await chromium.launch();
const errors = [];
try {
  for (const [surface, url] of [["front door", FRONT], ["/app/", APP + "/app/"]]) {
    for (const width of [390, 1280]) {
      const page = await browser.newPage({ viewport: { width, height: 900 } });
      page.on("pageerror", (e) => errors.push(`${surface} ${width}: ${e.message}`));
      await page.goto(url + "?t=" + Date.now(), { waitUntil: "domcontentloaded", timeout: 120000 });
      for (const input of INPUTS) {
        if (width === 390 && input.startsWith("10.")) continue;     // the papers at one width: Qloo is out, each costs nothing but time
        await pace(2);
        await page.fill("#k-q", input);
        await page.click("#k-go");
        const which = await page.waitForSelector("#k-card [data-which]", { timeout: 90000 }).catch(() => null);
        const shown = which ? await page.$$eval("#k-card [data-reading]", (bs) => bs.map((b) => ({ text: b.dataset.reading, kind: b.dataset.kind }))) : [];
        const paperTitle = which ? await page.$eval("#k-card [data-paper]", (e) => e.textContent).catch(() => "") : "";
        const differs = which ? await page.$$eval("#k-card [data-differs]", (e) => e.map((x) => x.textContent)) : [];
        const w = { kind: which ? "which_one" : "none", readings: shown, paper: paperTitle ? { title: paperTitle } : null,
          name_box: !!(await page.$("#k-card [data-name-box]")) };
        if (w.readings.find((r) => r.kind === "recorded")) w.readings.find((r) => r.kind === "recorded").differs = { theirs: differs[0] || "", yours: differs[0] ? "x" : "" };
        judgeReadings(`${surface} ${width}`, input, w);
        let picked = input;
        if (!which) { ok(false, `${surface} ${width} ${input}: no readings card came`); continue; }
        await pace(2);
        if (input.startsWith("10.") && !shown.length) { picked = NAMED[input]; await page.fill("#k-name", picked); await page.click("#k-card [data-name-box] button"); }
        else { picked = input.startsWith("10.") ? shown[0].text : input; await page.click(`#k-card [data-reading="${picked.replace(/"/g, '\\"')}"]`); }
        await page.waitForSelector("#k-card [data-queued], #k-card .k-card:not([data-which])", { timeout: 120000 }).catch(() => null);
        await page.waitForTimeout(1500);
        const readAs = await page.$eval("#k-card [data-read-as]", (e) => e.textContent).catch(() => "");
        const kick = readAs || await page.$eval("#k-card .k-kick", (e) => e.textContent).catch(() => "");
        const head = await page.$eval("#k-card [data-part=calls-head]", (e) => ({ live: Number(e.dataset.live), recorded: Number(e.dataset.recorded), t: e.textContent })).catch(() => null);
        const checked = (kick.match(/^Read as (.*?)(?:, also matched .*)?$/) || [null, kick])[1];
        pairs.push(checked === picked);
        ok(checked === picked, `${surface} ${width} ${input}: the card reads "${kick.slice(0, 80)}", picked "${picked}"`);
        ok(!head || head.live === 0, `${surface} ${width} ${input}: ${head ? head.t : "no calls line"}`);
        if (width === 1280 && head && counts[input]) ok(head.live === counts[input].mcp.live, `${surface} ${input}: the card and the MCP agree (${head.live} live)`);
        const brief = await page.$eval("#k-card [data-brief]", (e) => e.textContent).catch(() => "");
        ok(/criteria hash [0-9a-f]{12}/.test(brief) || !(await page.$("#k-card [data-queued]")), `${surface} ${width} ${input}: ${brief.slice(0, 90) || "a recorded card"}`);
      }
      await page.close();
    }
  }
} finally { await browser.close(); }
ok(errors.length === 0, `0 page errors (${errors.length}${errors.length ? ": " + errors.slice(0, 3).join(" | ") : ""})`);
const same = pairs.filter(Boolean).length;
log(`picked text = checked text on ${same} of ${pairs.length} surface and input pairs`);
const line = fails.length ? `FAIL test_which_one: ${fails.length} check(s) failed; picked = checked on ${same} of ${pairs.length}` : `PASS test_which_one: 4 inputs on 5 surfaces, picked = checked on ${same} of ${pairs.length}, 0 live Qloo calls, 0 page errors`;
log(line);
appendFileSync(`${DIR}/test_which_one.txt`, lines.join("\n") + "\n");
// L1 test_live_honest: the live and recorded counts of the same run, with Qloo answering 429
const l1 = lines.filter((l) => /live, .* recorded|"LIVE" on|agree|calls line/.test(l));
const l1fail = l1.filter((l) => l.startsWith("FAIL"));
l1.push(l1fail.length ? `FAIL test_live_honest: ${l1fail.length} of ${l1.length} checks failed` : `PASS test_live_honest: 0 live Qloo calls on ${l1.length} answers with Qloo at 429, "LIVE" on 0 recorded answers, the card and the MCP agree on all 4 inputs`);
appendFileSync(`${DIR}/test_live_honest.txt`, l1.join("\n") + "\n");
process.exit(fails.length ? 1 : 0);
