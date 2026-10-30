// S4 test_proof_on_card, live: every result card on /app/ carries one line with the locked result (ahead of Qloo
// popularity alone, +0.033 [+0.007, +0.067]; a tie with population; the model alone ahead twice) linking to How we test
// Knos, on the 6 front-door chips and 1 DOI (its paper reading).
//
//   node scripts/test_proof_on_card.mjs [result file]
import { chromium } from "playwright";
import { appendFileSync } from "node:fs";

const APP = "https://knos.onrender.com/app/";
const OUT = process.argv[2] || "";
const CHIPS = ["a solar powered music festival", "an AI recipe planner for families", "a crypto podcast for beginners",
  "a quantum physics book for kids", "a probiotic kombucha brand", "a recycled ocean plastic swimwear brand"];
const DOI = "10.1126/science.1225829";
const lines = [], fails = [];
const log = (s) => { console.log(s); lines.push(s); if (OUT) appendFileSync(OUT, s + "\n"); };
const ok = (c, what) => { log(`${c ? "ok  " : "FAIL"} ${what}`); if (!c) fails.push(what); return c; };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const browser = await chromium.launch();
let good = 0;
try {
  for (const idea of [...CHIPS, DOI]) {
    const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
    try {
      for (let attempt = 1; ; attempt++) {
        try { await page.goto(APP + "?q=" + encodeURIComponent(idea), { waitUntil: "domcontentloaded", timeout: 90000 }); break; }
        catch (e) { if (attempt === 2) throw e; await sleep(20000); }
      }
      if (idea === DOI) {
        await page.waitForSelector("#k-card [data-which] [data-reading]", { timeout: 120000 });
        await page.click('#k-card [data-which] [data-kind="product"], #k-card [data-which] [data-reading]:not([data-kind="exact"])');
      }
      await page.waitForSelector("#k-card .k-card [data-proof-line]", { timeout: 150000 });
      const p = await page.evaluate(() => {
        const all = [...document.querySelectorAll("#k-card .k-card [data-proof-line]")];
        const el = all[0];
        return { n: all.length, text: el ? el.innerText : "", href: el?.querySelector("a")?.href || "" };
      });
      const pass = p.n === 1 && /\+0\.033 \[\+0\.007, \+0\.067\]/.test(p.text) && /popularity alone/.test(p.text) && /ties population/.test(p.text)
        && /model alone beat it twice/.test(p.text) && /how-we-test\.html$/.test(p.href);
      if (pass) good++;
      ok(pass, `${idea}: ${p.n} proof line, "${p.text.slice(0, 150)}", linking to ${p.href}`);
    } catch (e) {
      ok(false, `${idea}: ${e.name}: ${String(e.message).split("\n")[0].slice(0, 120)}`);
    }
    await page.close();
    await sleep(8000);
  }
} finally { await browser.close(); }
log(fails.length ? `FAIL test_proof_on_card: ${good} of 7 cards carry the locked result; first: ${fails[0].slice(0, 160)}`
  : `PASS test_proof_on_card: 7 of 7 cards (6 chips and 1 DOI) carry one line with the locked result, linking to How we test Knos`);
process.exit(fails.length ? 1 : 0);
