// S6 test_gates, live: GitHub's API shows the repository public with its licence detected; the front door, /app/ and
// one result page answer 200 in a fresh browser with no sign-in asked; Qloo's own month counter has 80,000 calls left.
//
//   node scripts/test_gates.mjs [result file]
import { chromium } from "playwright";
import { appendFileSync } from "node:fs";
import { execFileSync } from "node:child_process";

const OUT = process.argv[2] || "";
const lines = [], fails = [];
const log = (s) => { console.log(s); lines.push(s); if (OUT) appendFileSync(OUT, s + "\n"); };
const ok = (c, what) => { log(`${c ? "ok  " : "FAIL"} ${what}`); if (!c) fails.push(what); return c; };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const again = async (f) => { try { return await f(); } catch { await sleep(30000); return await f(); } };

try {
  const repo = JSON.parse(execFileSync("gh", ["api", "repos/drexthealpha/Knos"], { encoding: "utf8", timeout: 120000 }));
  ok(repo.private === false && repo.visibility === "public" && !!(repo.license && repo.license.spdx_id && repo.license.spdx_id !== "NOASSERTION"),
    `GitHub: drexthealpha/Knos is ${repo.visibility}, licence ${repo.license ? repo.license.spdx_id : "none"} detected`);
} catch (e) {
  ok(false, `GitHub API: ${String(e.message).split("\n")[0].slice(0, 120)}`);
}
const proof = await again(async () => (await fetch("https://knos.onrender.com/api/proof")).json());
const h = ((proof.proof || {}).hash || (proof.sample || {}).hash || "").slice(0, 16);
const pages = [["front door", "https://drexthealpha.github.io/Knos/"], ["/app/", "https://knos.onrender.com/app/"], ["one result", `https://knos.onrender.com/r/${h}`]];
const browser = await chromium.launch();
try {
  for (const [name, url] of pages) {
    const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });     // fresh: no cookie, no storage
    const page = await ctx.newPage();
    try {
      const r = await again(() => page.goto(url, { waitUntil: "domcontentloaded", timeout: 90000 }));
      await sleep(2500);
      const seen = await page.evaluate(() => ({
        text: document.body.innerText.slice(0, 4000),
        password: !!document.querySelector('input[type="password"]'),
        dialog: [...document.querySelectorAll("dialog[open], [role=dialog]")].filter((d) => d.offsetParent !== null).map((d) => d.innerText.slice(0, 60)),
      }));
      const asks = /sign in to (continue|see|use)|log in to (continue|see|use)|create an account to/i.test(seen.text) || seen.password || seen.dialog.some((d) => /sign|log in/i.test(d));
      ok(r && r.status() === 200 && !asks, `${name} ${url}: HTTP ${r ? r.status() : "none"}, ${asks ? "asks for a sign-in" : "no sign-in asked"}, ${seen.text.length} characters shown`);
    } catch (e) {
      ok(false, `${name}: ${e.name}: ${String(e.message).split("\n")[0].slice(0, 120)}`);
    }
    await ctx.close();
  }
} finally { await browser.close(); }
const st = await again(async () => (await fetch("https://knos.onrender.com/api/qloo/status")).json());
const left = Number(st.month_left);
ok(left >= 80000, `Qloo's month counter: ${left} calls left of ${st.month_limit}, resets ${st.month_reset}`);
log(fails.length ? `FAIL test_gates: ${fails.length} of ${lines.length} checks failed; first: ${fails[0].slice(0, 160)}`
  : `PASS test_gates: ${lines.length} of ${lines.length} checks: the repository public with its licence, 3 pages open with no sign-in, ${left} Qloo calls left`);
process.exit(fails.length ? 1 : 0);
