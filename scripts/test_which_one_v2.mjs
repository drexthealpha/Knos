// D2 test_which_one_v2, live: the 4 shared test inputs and the 20 of INPUTS.txt on the 5 surfaces (the front door at
// 1280, /app/ at 390, /api/check, the hosted MCP's knos_demand_check and `knos demand`), 120 pairs. Each surface is
// asked which one first; the exact reading (an idea) or the first product the paper enables is picked; the checked
// idea must be the picked text. Also: 0 recorded readings sharing fewer than 2 content words, no paper reading for a
// plain idea, "a game cafe" checked as a place, both DOIs resolved to their real titles, 0 page errors.
//
//   node scripts/test_which_one_v2.mjs <INPUTS.txt> <knos command> [result file]
import { chromium } from "playwright";
import { execFileSync } from "node:child_process";
import { appendFileSync, readFileSync } from "node:fs";

const APP = "https://knos.onrender.com", FRONT = "https://drexthealpha.github.io/Knos/";
const MORE = readFileSync(process.argv[2], "utf8").split(/\r?\n/).map((s) => s.trim()).filter(Boolean);
const KNOS = (process.argv[3] || "knos").split(" ");
const OUT = process.argv[4] || "";
const INPUTS = ["a vegan ramen food truck", "a late night ramen spot", "10.1038/nature14539", "10.1126/science.1225829", ...MORE];
const TITLES = { "10.1038/nature14539": "Deep learning", "10.1126/science.1225829": "A Programmable Dual-RNA" };
const NAMED = { "10.1038/nature14539": "a photo search app that finds any picture by its content", "10.1126/science.1225829": "a gene editing kit for crop breeders" };
const NO_PAPER = ["a cold brew coffee brand for night shift nurses", "oat milk soft serve for night markets",
  "a board game cafe with vegan snacks for students", "a vegan meal kit for students, like HelloFresh"];
const lines = [], fails = [];
const log = (s) => { console.log(s); lines.push(s); if (process.argv[4]) appendFileSync(process.argv[4], s + "\n"); };   // each line kept at once
const ok = (c, what) => { log(`${c ? "ok  " : "FAIL"} ${what}`); if (!c) fails.push(what); return c; };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let last = 0;
const pace = async (n = 1) => { const wait = last + 22000 * n - Date.now(); if (wait > 0) await sleep(wait); last = Date.now(); };
const post = async (path, body) => { await pace(); const r = await fetch(APP + path, { method: "POST", headers: { "Content-Type": "application/json", "User-Agent": "knos-d2-test" }, body: JSON.stringify(body) }); return r.json(); };
const mcp = async (args) => { const r = await post("/mcp", { jsonrpc: "2.0", id: 1, method: "tools/call", params: { name: "knos_demand_check", arguments: args } });
  return r.result?.structuredContent || JSON.parse(r.result?.content?.[0]?.text || "{}"); };
const cli = async (args) => { await pace(); try { return JSON.parse(execFileSync(KNOS[0], [...KNOS.slice(1), "demand", ...args, "--json"], { encoding: "utf8", env: { ...process.env, PYTHONIOENCODING: "utf-8" } })); }
  catch (e) { return { error: String(e.stderr || e.message).slice(0, 200) }; } };
// what a person picks: the exact text of an idea; a paper's first product reading, else the product they name
const pickOf = (input, w) => (w.paper || w.of === "paper" ? ((w.readings || []).find((r) => r.kind === "product")?.text || NAMED[input] || input) : input);
const pairs = [];

function judgeReadings(surface, input, w) {
  const rs = w.readings || [];
  if (TITLES[input]) {
    ok(w.kind === "which_one" && String(w.paper?.title || "").startsWith(TITLES[input]), `${surface} ${input}: the paper resolves to "${String(w.paper?.title || "").slice(0, 50)}"`);
    return;
  }
  const isPaper = !!(w.paper || w.of === "paper");
  if (NO_PAPER.includes(input)) ok(!isPaper, `${surface} ${input.slice(0, 50)}: ${isPaper ? "read as a paper" : "0 paper readings"}`);
  if (w.kind === "which_one") {
    ok(rs[0]?.kind === "exact" && rs[0]?.text === input, `${surface} ${input.slice(0, 50)}: the exact reading first (${rs.map((r) => r.kind).join(", ")})`);
    const thin = rs.filter((r) => r.kind === "recorded" && typeof r.shared === "number" && r.shared < 2);
    ok(thin.length === 0, `${surface} ${input.slice(0, 50)}: ${thin.length} recorded readings sharing fewer than 2 content words`);
  }
}

function judgeAnswer(surface, input, picked, r) {
  const checked = r.read_as || r.idea || r.report?.idea;
  pairs.push(checked === picked);
  ok(checked === picked, `${surface} ${input.slice(0, 50)}: checked "${String(checked).slice(0, 60)}", picked "${picked.slice(0, 60)}"`);
  if (input === "a game cafe" && r.product_type) ok(r.product_type === "urn:entity:place", `${surface} a game cafe: checked as ${r.product_type}`);
}

for (const input of INPUTS) {
  try {
  const w = await post("/api/check", { idea: input });
  judgeReadings("api", input, w);
  const picked = pickOf(input, w);
  judgeAnswer("api", input, picked, await post("/api/check", { idea: picked, picked: true, stage: "verdict" }));
  const mw = await mcp({ idea: input });
  judgeReadings("mcp", input, mw);
  const mPick = pickOf(input, mw);
  judgeAnswer("mcp", input, mPick, await mcp({ idea: mPick, picked: true }));
  const cw = await cli([input]);
  judgeReadings("cli", input, cw);
  const cPick = pickOf(input, cw);
  judgeAnswer("cli", input, cPick, await cli([cPick, "--picked"]));
  } catch (e) { pairs.push(false); ok(false, `api/mcp/cli ${input.slice(0, 50)}: ${e.name}: ${String(e.message).slice(0, 120)}`); }
}

const browser = await chromium.launch();
const errors = [];
try {
  for (const [surface, url, width] of [["front door", FRONT, 1280], ["/app/", APP + "/app/", 390]]) {
    const page = await browser.newPage({ viewport: { width, height: 900 } });
    page.on("pageerror", (e) => errors.push(`${surface} ${width}: ${e.message}`));
    await page.goto(url + "?t=" + Date.now(), { waitUntil: "domcontentloaded", timeout: 120000 });
    for (const input of INPUTS) {
      try {
      await pace(2);
      await page.fill("#k-q", input);
      await page.click("#k-go");
      const which = await page.waitForSelector("#k-card [data-which]", { timeout: 90000 }).catch(() => null);
      const shown = which ? await page.$$eval("#k-card [data-reading]", (bs) => bs.map((b) => ({ text: b.dataset.reading, kind: b.dataset.kind }))) : [];
      const paperTitle = which ? await page.$eval("#k-card [data-paper]", (e) => e.textContent).catch(() => "") : "";
      judgeReadings(`${surface} ${width}`, input, { kind: which ? "which_one" : "none", readings: shown, paper: paperTitle ? { title: paperTitle } : null });
      if (!which) { ok(false, `${surface} ${width} ${input.slice(0, 50)}: no readings card came`); continue; }
      let picked = input;
      const prod = shown.find((r) => r.kind === "product");
      if (TITLES[input] && !prod) { picked = NAMED[input]; await page.fill("#k-name", picked); await page.click("#k-card [data-name-box] button"); }
      else { picked = TITLES[input] ? prod.text : input; await page.click(`#k-card [data-reading="${picked.replace(/"/g, '\\"')}"]`); }
      await page.waitForSelector("#k-card [data-queued], #k-card .k-card:not([data-which])", { timeout: 120000 }).catch(() => null);
      await page.waitForTimeout(1500);
      const readAs = await page.$eval("#k-card [data-read-as]", (e) => e.textContent).catch(() => "");
      const kick = readAs || await page.$eval("#k-card .k-kick", (e) => e.textContent).catch(() => "");
      const checked = (kick.match(/^Read as (.*?)(?:, also matched .*)?$/) || [null, kick])[1];
      pairs.push(checked === picked);
      ok(checked === picked, `${surface} ${width} ${input.slice(0, 50)}: the card reads "${kick.slice(0, 70)}", picked "${picked.slice(0, 50)}"`);
      } catch (e) { pairs.push(false); ok(false, `${surface} ${width} ${input.slice(0, 50)}: ${e.name}: ${String(e.message).slice(0, 120)}`); }
    }
    await page.close();
  }
} finally { await browser.close(); }
ok(errors.length === 0, `0 page errors (${errors.length}${errors.length ? ": " + errors.slice(0, 3).join(" | ") : ""})`);
const same = pairs.filter(Boolean).length;
log(`picked text = checked text on ${same} of ${pairs.length} surface and input pairs`);
log(fails.length ? `FAIL test_which_one_v2: ${fails.length} check(s) failed; picked = checked on ${same} of ${pairs.length}; first: ${fails[0].slice(0, 140)}`
  : `PASS test_which_one_v2: ${INPUTS.length} inputs on 5 surfaces, picked = checked on ${same} of ${pairs.length}, 0 thin readings, 0 page errors`);
process.exit(fails.length ? 1 : 0);
