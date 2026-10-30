// S1 test_always_warm: .github/workflows/live-window.yml is timer-only, asks for the front door, /app/ and /api/proof
// every 10 minutes, and turns itself off from 6 Nov 2026 06:00 UTC; GitHub shows a scheduled run of it that succeeded;
// 3 first visits at 390 px (each a fresh browser) show the live card in view within 5 s.
//
//   node scripts/test_always_warm.mjs [result file]
import { chromium } from "playwright";
import { appendFileSync, readFileSync } from "node:fs";
import { execFileSync } from "node:child_process";

const FRONT = "https://drexthealpha.github.io/Knos/";
const OUT = process.argv[2] || "";
const lines = [], fails = [];
const log = (s) => { console.log(s); lines.push(s); if (OUT) appendFileSync(OUT, s + "\n"); };
const ok = (c, what) => { log(`${c ? "ok  " : "FAIL"} ${what}`); if (!c) fails.push(what); return c; };
const VERDICT = /Wanted|Open for pre-orders|Not yet|Not enough evidence/;

const wf = readFileSync(new URL("../.github/workflows/live-window.yml", import.meta.url), "utf8");
const on = wf.slice(wf.indexOf("\non:"), wf.indexOf("\npermissions:"));
ok(/schedule:/.test(on) && !/workflow_dispatch|push:|pull_request/.test(on) && /cron: "\*\/10 \* \* \* \*"/.test(on),
  "live-window.yml runs on its timer only, every 10 minutes");
ok(["https://drexthealpha.github.io/Knos/", "https://knos.onrender.com/app/", "https://knos.onrender.com/api/proof"].every((u) => wf.includes(u)),
  "it asks for the front door, /app/ and /api/proof");
ok(/2026-11-06T06:00:00Z/.test(wf) && /gh workflow disable live-window\.yml/.test(wf), "from 6 Nov 06:00 UTC it turns itself off");
try {
  const runs = JSON.parse(execFileSync("gh", ["run", "list", "--workflow", "live-window.yml", "--event", "schedule", "-L", "20", "--json", "status,conclusion,createdAt,databaseId"], { encoding: "utf8", timeout: 120000 }));
  const good = runs.filter((r) => r.conclusion === "success" || r.status === "in_progress");     // a run asks for up to 6 hours
  ok(good.length >= 1, `GitHub ran it on its timer: ${good.length} of ${runs.length} scheduled runs asking or done${good[0] ? `, the latest ${good[0].createdAt} (run ${good[0].databaseId}, ${good[0].status})` : ""}`);
} catch (e) {
  ok(false, `GitHub runs: ${String(e.message).split("\n")[0].slice(0, 120)}`);
}

const browser = await chromium.launch();
try {
  for (let visit = 1; visit <= 3; visit++) {
    const ctx = await browser.newContext({ viewport: { width: 390, height: 844 } });      // a first visit: nothing cached
    const page = await ctx.newPage();
    try {
      const t0 = Date.now();
      await page.goto(FRONT + "?v=" + Date.now(), { waitUntil: "domcontentloaded", timeout: 60000 });
      const seen = await page.waitForFunction((re) => {
        const c = document.querySelector("#k-card .k-card, #k-card article");
        if (!c) return false;
        const r = c.getBoundingClientRect();
        return new RegExp(re).test(c.innerText || "") && r.top < innerHeight && r.bottom > 0;
      }, VERDICT.source, { timeout: Math.max(1, 5000 - (Date.now() - t0)), polling: 50 }).then(() => Date.now() - t0).catch(() => null);
      ok(seen !== null && seen <= 5000, `first visit ${visit} at 390 px: the live card in view ${seen === null ? "not within 5 s" : `after ${(seen / 1000).toFixed(1)} s`}`);
    } catch (e) {
      ok(false, `first visit ${visit}: ${e.name}: ${String(e.message).split("\n")[0].slice(0, 120)}`);
    }
    await ctx.close();
  }
} finally { await browser.close(); }
log(fails.length ? `FAIL test_always_warm: ${fails.length} of ${lines.length} checks failed; first: ${fails[0].slice(0, 160)}`
  : `PASS test_always_warm: ${lines.length} of ${lines.length} checks: timer-only workflow every 10 minutes to 6 Nov 06:00 UTC, run by GitHub, 3 first visits with the live card in view within 5 s`);
process.exit(fails.length ? 1 : 0);
