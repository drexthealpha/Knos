// Q2 test_phone_first_screen, live: the front door at 390 px, light and dark, shows the live Qloo card within 15 s and
// has 0 elements wider than the viewport; Lighthouse (mobile) performance 0.90+ and accessibility 1.0 on the front door
// and /app/, read from the reports of the push-triggered lighthouse run of the commit under test.
//
//   node scripts/test_phone_first_screen.mjs <commit sha> [result file]
import { chromium } from "playwright";
import { appendFileSync, mkdtempSync, readdirSync, readFileSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { tmpdir } from "node:os";
import { join } from "node:path";

const FRONT = "https://drexthealpha.github.io/Knos/";
const SHA = process.argv[2] || "";
const OUT = process.argv[3] || "";
const lines = [], fails = [];
const log = (s) => { console.log(s); lines.push(s); if (OUT) appendFileSync(OUT, s + "\n"); };
const ok = (c, what) => { log(`${c ? "ok  " : "FAIL"} ${what}`); if (!c) fails.push(what); return c; };
const VERDICT = /Wanted|Open for pre-orders|Not yet|Not enough evidence/;

const browser = await chromium.launch();
try {
  for (const scheme of ["light", "dark"]) {
    const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, colorScheme: scheme });
    const page = await ctx.newPage();
    try {
      const t0 = Date.now();
      await page.goto(FRONT + "?t=" + Date.now(), { waitUntil: "domcontentloaded", timeout: 60000 });
      const seen = await page.waitForFunction((re) => {
        const c = document.querySelector("#k-card .k-card, #k-card article");
        if (!c) return false;
        const r = c.getBoundingClientRect();
        return new RegExp(re).test(c.innerText || "") && r.top < innerHeight && r.bottom > 0;
      }, VERDICT.source, { timeout: 15000, polling: 100 }).then(() => Date.now() - t0).catch(() => null);
      ok(seen !== null, `390 ${scheme}: the live Qloo card in view ${seen === null ? "not within 15 s" : `after ${(seen / 1000).toFixed(1)} s`}`);
      const wide = await page.evaluate(() => [...document.querySelectorAll("body *")].filter((e) => {
        const r = e.getBoundingClientRect(), s = getComputedStyle(e);
        return r.width > 0 && s.visibility !== "hidden" && (r.right > innerWidth + 1 || r.left < -1) && !e.closest("[hidden], .k-sr, .sr-only");
      }).map((e) => `${e.tagName.toLowerCase()}${e.id ? "#" + e.id : ""}${e.className && typeof e.className === "string" ? "." + e.className.split(" ")[0] : ""}`));
      const scroll = await page.evaluate(() => document.documentElement.scrollWidth - innerWidth);
      ok(wide.length === 0 && scroll <= 0, `390 ${scheme}: ${wide.length} elements wider than the viewport, page scrolls ${Math.max(0, scroll)} px sideways${wide.length ? " (" + wide.slice(0, 3).join(", ") + ")" : ""}`);
    } catch (e) {
      ok(false, `390 ${scheme}: ${e.name}: ${String(e.message).split("\n")[0].slice(0, 120)}`);
    }
    await ctx.close();
  }
} finally { await browser.close(); }

// Lighthouse: the reports the push-triggered lighthouse run of this commit kept (apps/wanted/lighthouserc.js, mobile)
try {
  const gh = (args) => execFileSync("gh", args, { encoding: "utf8", timeout: 300000 });
  const runs = JSON.parse(gh(["run", "list", "--workflow", "lighthouse.yml", "--event", "push", "--commit", SHA, "--json", "databaseId,conclusion,headSha"]));
  const run = runs.find((r) => r.headSha === SHA);
  if (!run) throw new Error(`no push-triggered lighthouse run for ${SHA.slice(0, 7)}`);
  const dir = mkdtempSync(join(tmpdir(), "q2-lh-"));
  gh(["run", "download", String(run.databaseId), "-n", "lighthouse", "-D", dir]);
  const want = { "front door": "http://127.0.0.1:8081/", "/app/": "http://127.0.0.1:8080/app/" };   // the page each report asked for
  const got = {};
  for (const f of readdirSync(dir).filter((x) => /^lhr-.*\.json$/.test(x))) {
    const d = JSON.parse(readFileSync(join(dir, f), "utf8"));
    for (const [name, url] of Object.entries(want)) if (d.requestedUrl === url) got[name] = d.categories;
  }
  for (const name of Object.keys(want)) {
    const c = got[name];
    const perf = c?.performance?.score, a11y = c?.accessibility?.score;
    ok(perf >= 0.9 && a11y === 1, `Lighthouse ${name} (run ${run.databaseId}, mobile): performance ${perf ?? "not measured"}, accessibility ${a11y ?? "not measured"}`);
  }
} catch (e) {
  ok(false, `Lighthouse: ${String(e.message).split("\n")[0].slice(0, 160)}`);
}
log(fails.length ? `FAIL test_phone_first_screen: ${fails.length} of ${lines.length} checks failed; first: ${fails[0].slice(0, 140)}`
  : `PASS test_phone_first_screen: ${lines.length} of ${lines.length} checks: the live card within 15 s at 390 px in both themes, 0 elements wider than the viewport, Lighthouse performance 0.90+ and accessibility 1.0 on both pages`);
process.exit(fails.length ? 1 : 0);
