// test_forecast_ledger_v2 (F1), live: /forecasts/ lists every recorded idea with its three forecasts (Knos's read from
// the app's server), its NAICS code, the grading date and its source; 0 placebo picks equal Knos's; the rows' sha256
// recomputed in the browser matches the plan's, and the plan's own sha256 on the page matches the committed file.
//
//   node scripts/test_forecast_ledger_v2.mjs [result dir]
import { chromium } from "playwright";
import { appendFileSync, readFileSync } from "node:fs";
import { createHash } from "node:crypto";

const SITE = "https://drexthealpha.github.io/Knos/", API = "https://knos.onrender.com";
const DIR = process.argv[2] || "C:/Users/zulab/knos-v1-private/v0328/world";
const lines = [], fails = [];
const ok = (c, w) => { lines.push(`${c ? "ok  " : "FAIL"} ${w}`); console.log(lines.at(-1)); if (!c) fails.push(w); };
const plan = readFileSync(new URL("../docs/reference/forecast_plan_v2.md", import.meta.url));
const planSha = createHash("sha256").update(plan).digest("hex");
const rows = (await fetch(`${API}/api/forecasts`).then((r) => r.json())).rows || [];
ok(rows.length === 7, `the app holds ${rows.length} forecast rows`);
ok(rows.filter((r) => r.placebo && r.knos && r.placebo.fips === r.knos.fips).length === 0, `0 placebo picks equal Knos's (${rows.filter((r) => r.graded).length} graded, ${rows.filter((r) => !r.graded).map((r) => r.idea).join(", ")} outside US data)`);
const browser = await chromium.launch();
const errors = [];
try {
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto(SITE + "forecasts/?t=" + Date.now(), { waitUntil: "load", timeout: 90000 });
  await page.waitForFunction(() => document.getElementById("f-match")?.dataset.match, null, { timeout: 60000 }).catch(() => {});
  const got = await page.evaluate(() => ({ match: document.getElementById("f-match")?.dataset.match, plan: document.getElementById("f-plan")?.textContent,
    rows: [...document.querySelectorAll("tbody tr")].map((tr) => [...tr.children].map((td) => td.textContent.trim())), links: [...document.querySelectorAll("tbody a")].map((a) => a.href) }));
  ok(got.match === "true", "the rows' sha256, recomputed in the browser, matches the plan's");
  ok(got.plan === planSha, `the plan's sha256 on the page (${String(got.plan).slice(0, 12)}) is the committed file's (${planSha.slice(0, 12)})`);
  const full = got.rows.filter((c) => c[2] && c[2] !== "read from the app" && c[3] && c[4] && /^\d{6}/.test(c[1]) && c[5] && c[6]);
  ok(got.rows.length === 7 && full.length === 7, `${full.length} of ${got.rows.length} rows with 3 forecasts, NAICS, grading date and source: ${got.rows.map((c) => `${c[0]}: ${c[2]} / ${c[3]} / ${c[4]}, ${c[1].slice(0, 6)}, ${c[5]}`).join("; ")}`);
  for (const href of got.links) { const r = await fetch(href).catch(() => null); ok(r && r.status === 200, `source ${href.slice(-32)}: HTTP ${r ? r.status : "no answer"}`); }
} finally { await browser.close(); }
ok(errors.length === 0, `${errors.length} page errors`);
const line = fails.length ? `FAIL test_forecast_ledger_v2: ${fails.length} check(s) failed` : `PASS test_forecast_ledger_v2: 7 ideas with 3 forecasts each, NAICS, graded 2 Dec 2026 from QCEW, 0 placebo picks equal Knos's, the plan's sha256 matches the page`;
lines.push(line); console.log(line);
appendFileSync(`${DIR}/test_forecast_ledger_v2.txt`, lines.join("\n") + "\n");
process.exit(fails.length ? 1 : 0);
