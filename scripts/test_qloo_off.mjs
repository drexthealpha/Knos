// Q5 test_qloo_off, live: every result card has one switch that shows the model-alone answer beside the Qloo answer,
// on the 6 front-door chips and 1 DOI (its paper reading), on /app/ at 1280 px. Pass: one Model alone switch per card,
// and pressing it shows the model's own launch city in the same table as Knos's.
//
//   node scripts/test_qloo_off.mjs [result file]
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
      await page.goto(APP + "?q=" + encodeURIComponent(idea), { waitUntil: "domcontentloaded", timeout: 120000 });
      if (idea === DOI) {                                          // the paper: its product reading, as a reader picks it
        await page.waitForSelector('#k-card [data-which] [data-reading]', { timeout: 120000 });
        await page.click('#k-card [data-which] [data-kind="product"], #k-card [data-which] [data-reading]:not([data-kind="exact"])');
      }
      await page.waitForSelector("#k-card .k-card [data-without]", { timeout: 150000 });
      await sleep(1500);
      const switches = await page.$$eval('#k-card .k-card .k-switch [data-view="model"]', (b) => b.length);
      await page.click('#k-card .k-card .k-switch [data-view="model"]', { timeout: 10000 });
      await sleep(400);
      const seen = await page.evaluate(() => {
        const k = document.querySelector("#k-card .k-card"), p = k && k.querySelector("[data-model-panel]");
        const m = p && p.querySelector('[data-row="city"] [data-model]'), q = p && p.querySelector('[data-row="city"] [data-knos]');
        return { open: !!p && !p.hidden, model: m ? m.innerText.trim() : "", knos: q ? q.innerText.trim() : "", idea: k?.querySelector(".k-kick")?.innerText || "" };
      });
      const pass = switches === 1 && seen.open && !!seen.model && !!seen.knos;
      if (pass) good++;
      ok(pass, `${idea}${idea === DOI ? ` (read as "${seen.idea.split("·")[0].trim()}")` : ""}: ${switches} Model alone switch, panel ${seen.open ? "open" : "shut"}; Knos with Qloo "${seen.knos}" beside the model alone "${seen.model}"`);
    } catch (e) {
      ok(false, `${idea}: ${e.name}: ${String(e.message).split("\n")[0].slice(0, 120)}`);
    }
    await page.close();
    await sleep(22000);
  }
} finally { await browser.close(); }
log(fails.length ? `FAIL test_qloo_off: ${good} of 7 cards show the model alone beside Qloo; first: ${fails[0].slice(0, 160)}`
  : `PASS test_qloo_off: 7 of 7 cards (6 chips and 1 DOI) have one switch that shows the model-alone answer beside the Qloo answer`);
process.exit(fails.length ? 1 : 0);
