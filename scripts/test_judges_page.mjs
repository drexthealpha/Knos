// J2 test_judges_page, live: /judges/ is linked from the front door's first screen; it reads in under 3 minutes (under
// 600 words), shows a status line with Qloo and Solana devnet read from the app at load, one button that runs a live
// check, the Qloo-off comparison and the locked result with its link; it loads at 390 and 1280 px with no sign-in;
// Lighthouse accessibility 1.0 from the push-triggered lighthouse run of the commit under test.
//
//   node scripts/test_judges_page.mjs <commit sha> [result file]
import { chromium } from "playwright";
import { appendFileSync, mkdtempSync, readdirSync, readFileSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { tmpdir } from "node:os";
import { join } from "node:path";

const FRONT = "https://drexthealpha.github.io/Knos/", PAGE = FRONT + "judges/";
const SHA = process.argv[2] || "", OUT = process.argv[3] || "";
const lines = [], fails = [];
const log = (s) => { console.log(s); lines.push(s); if (OUT) appendFileSync(OUT, s + "\n"); };
const ok = (c, what) => { log(`${c ? "ok  " : "FAIL"} ${what}`); if (!c) fails.push(what); return c; };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const browser = await chromium.launch();
try {
  const f = await browser.newPage({ viewport: { width: 1280, height: 800 } });
  await f.goto(FRONT + "?t=" + Date.now(), { waitUntil: "domcontentloaded", timeout: 90000 });
  const link = await f.evaluate(() => { const a = document.querySelector('a[href$="/judges/"]'); if (!a) return null; const r = a.getBoundingClientRect(); return { text: a.innerText, inView: r.top >= 0 && r.bottom <= innerHeight }; });
  ok(!!link && link.inView, `front door first screen links /judges/: ${link ? `"${link.text}", in view ${link.inView}` : "no link"}`);
  await f.close();
  for (const width of [390, 1280]) {
    const ctx = await browser.newContext({ viewport: { width, height: width === 390 ? 844 : 800 } });
    const p = await ctx.newPage();
    try {
      const r = await p.goto(PAGE + "?t=" + Date.now(), { waitUntil: "domcontentloaded", timeout: 90000 });
      await p.waitForFunction(() => !/reading/.test(document.getElementById("qloo")?.innerText || "reading") && !/reading/.test(document.getElementById("sol")?.innerText || "reading"), null, { timeout: 30000 }).catch(() => null);
      await sleep(500);
      const s = await p.evaluate(() => ({
        words: document.querySelector("main").innerText.split(/\s+/).filter(Boolean).length,
        qloo: document.getElementById("qloo")?.innerText || "", sol: document.getElementById("sol")?.innerText || "",
        button: [...document.querySelectorAll("button")].filter((b) => /live check/i.test(b.innerText)).length,
        off: !!document.querySelector('a[href*="qloo=off"]') && /Without Qloo/.test(document.body.innerText) && /Model alone/.test(document.body.innerText),
        locked: /\+0\.033 \[\+0\.007, \+0\.067\]/.test(document.body.innerText) && !!document.querySelector('a[href$="how-we-test.html"]'),
        what: /valley of death/.test(document.body.innerText), signin: !!document.querySelector('input[type="password"]') || /sign in to/i.test(document.body.innerText),
        wide: document.documentElement.scrollWidth - innerWidth,
      }));
      ok(r.status() === 200 && !s.signin && s.wide <= 0, `${width} px: HTTP ${r.status()}, no sign-in ${!s.signin}, sideways scroll ${Math.max(0, s.wide)} px`);
      ok(s.words < 600 && s.what, `${width} px: ${s.words} words to read (under 3 minutes at 200 a minute), says what Knos does ${s.what}`);
      ok(/live|not/.test(s.qloo) && /live|not/.test(s.sol) && !/reading/.test(s.qloo + s.sol), `${width} px: status read at load: Qloo "${s.qloo}", Solana devnet "${s.sol}"`);
      ok(s.button === 1 && s.off && s.locked, `${width} px: ${s.button} live check button, the Qloo-off comparison ${s.off}, the locked result with its link ${s.locked}`);
    } catch (e) {
      ok(false, `${width} px: ${e.name}: ${String(e.message).split("\n")[0].slice(0, 120)}`);
    }
    await ctx.close();
  }
} finally { await browser.close(); }
try {
  const gh = (a) => execFileSync("gh", a, { encoding: "utf8", timeout: 300000 });
  const run = JSON.parse(gh(["run", "list", "--workflow", "lighthouse.yml", "--event", "push", "--commit", SHA, "--json", "databaseId,headSha"])).find((r) => r.headSha === SHA);
  if (!run) throw new Error(`no push-triggered lighthouse run for ${SHA.slice(0, 7)}`);
  const dir = mkdtempSync(join(tmpdir(), "j2-lh-"));
  gh(["run", "download", String(run.databaseId), "-n", "lighthouse", "-D", dir]);
  const scores = readdirSync(dir).filter((x) => /^lhr-.*\.json$/.test(x)).map((x) => JSON.parse(readFileSync(join(dir, x), "utf8")))
    .filter((d) => d.requestedUrl === "http://127.0.0.1:8081/judges/").map((d) => d.categories.accessibility.score);
  ok(scores.length > 0 && Math.max(...scores) === 1, `Lighthouse accessibility of /judges/ (run ${run.databaseId}, mobile, best of ${scores.length}): ${scores.join(", ") || "not measured"}`);
} catch (e) {
  ok(false, `Lighthouse: ${String(e.message).split("\n")[0].slice(0, 140)}`);
}
log(fails.length ? `FAIL test_judges_page: ${fails.length} of ${lines.length} checks failed; first: ${fails[0].slice(0, 160)}`
  : `PASS test_judges_page: ${lines.length} of ${lines.length} checks: linked from the first screen, under 3 minutes to read, the status read live, one live check, the Qloo-off comparison, the locked result, both widths, accessibility 1.0`);
process.exit(fails.length ? 1 : 0);
