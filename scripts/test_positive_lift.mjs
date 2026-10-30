// S3 test_positive_lift, live: on the 6 front-door chips (/app/, 1280 px) the card lists the audiences with lift above zero
// first, at least 2 per chip, read from live Qloo calls (the server's call log, by the request id the page sent), with
// one plain line saying what lift means; a card whose audiences Qloo moved alike says so in words.
//
//   node scripts/test_positive_lift.mjs [result file]
import { chromium } from "playwright";
import { appendFileSync } from "node:fs";

const APP = "https://knos.onrender.com";
const OUT = process.argv[2] || "";
const CHIPS = ["a solar powered music festival", "an AI recipe planner for families", "a crypto podcast for beginners",
  "a quantum physics book for kids", "a probiotic kombucha brand", "a recycled ocean plastic swimwear brand"];
const lines = [], fails = [];
const log = (s) => { console.log(s); lines.push(s); if (OUT) appendFileSync(OUT, s + "\n"); };
const ok = (c, what) => { log(`${c ? "ok  " : "FAIL"} ${what}`); if (!c) fails.push(what); return c; };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const isLift = (c) => Object.keys(c.params || {}).some((k) => k.startsWith("signal.demographics.audiences")) && !/\/v2\/audiences/.test(c.call);

const browser = await chromium.launch();
let good = 0;
try {
  for (const idea of CHIPS) {
    const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
    const reqs = [];
    page.on("request", (r) => { if (/\/api\/check/.test(r.url()) && r.method() === "POST") { try { const b = JSON.parse(r.postData() || "{}"); if (b.req) reqs.push(b.req); } catch { /* not JSON */ } } });
    try {
      for (let attempt = 1; ; attempt++) {                        // a page that did not load is loaded once more, before any check
        try { await page.goto(`${APP}/app/?q=${encodeURIComponent(idea)}`, { waitUntil: "domcontentloaded", timeout: 90000 }); break; }
        catch (e) { if (attempt === 2) throw e; await sleep(20000); }
      }
      await page.waitForFunction(() => document.querySelector("#k-card .k-card [data-part=lifts]") && !document.querySelector("#k-go")?.hasAttribute("aria-busy"), null, { timeout: 150000 });
      await sleep(1500);
      const card = await page.evaluate(() => ({
        lifts: [...document.querySelectorAll("#k-card .k-card [data-part=lifts] [data-lift]")].map((li) => ({ lift: Number(li.dataset.lift), name: li.querySelector("span")?.innerText || "" })),
        means: document.querySelector("#k-card .k-card [data-lift-means]")?.innerText || "",
        none: document.querySelector("#k-card .k-card [data-lift-none]")?.innerText || "",
      }));
      const logged = ((await (await fetch(APP + "/api/calls")).json()).calls || []).filter((c) => reqs.includes(c.req) && isLift(c) && c.origin === "live");
      const up = card.lifts.filter((a) => a.lift > 0);
      const firstUp = card.lifts.findIndex((a) => !(a.lift > 0));
      const ordered = firstUp === -1 || card.lifts.slice(firstUp).every((a) => !(a.lift > 0));
      const pass = up.length >= 2 && ordered && !!card.means && logged.length >= 2;
      if (pass) good++;
      ok(pass, `${idea}: ${up.length} audiences above zero (${up.slice(0, 3).map((a) => `${a.name} +${a.lift.toFixed(4)}`).join(", ") || "none"}), listed first ${ordered}; ${logged.length} live audience lift calls; line: "${(card.means || card.none).slice(0, 70)}"`);
    } catch (e) {
      ok(false, `${idea}: ${e.name}: ${String(e.message).split("\n")[0].slice(0, 120)}`);
    }
    await page.close();
    await sleep(8000);
  }
} finally { await browser.close(); }
log(fails.length ? `FAIL test_positive_lift: ${good} of 6 chips list 2+ audiences above zero first from live calls; first: ${fails[0].slice(0, 160)}`
  : `PASS test_positive_lift: 6 of 6 chips list 2+ audiences above zero first, from live Qloo calls, with one line saying what lift means`);
process.exit(fails.length ? 1 : 0);
