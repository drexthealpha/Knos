// Q6 test_run_counter, live: while a check runs on /app/, the card shows live counts of Qloo calls, entities and
// seconds; when it ends, the counts equal the server's own call log for that check (GET /api/calls, by the request id the
// page sent). 3 checks of ideas typed into the box.
//
//   node scripts/test_run_counter.mjs [result file]
import { chromium } from "playwright";
import { appendFileSync } from "node:fs";

const APP = "https://knos.onrender.com";
const OUT = process.argv[2] || "";
const IDEAS = ["a sourdough bakery for night owls", "a vintage vinyl record cafe", "a trail running shoe for wide feet"];
const lines = [], fails = [];
const log = (s) => { console.log(s); lines.push(s); if (OUT) appendFileSync(OUT, s + "\n"); };
const ok = (c, what) => { log(`${c ? "ok  " : "FAIL"} ${what}`); if (!c) fails.push(what); return c; };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const COUNT = /Qloo calls (\d+) · entities (\d+)(?: · ([\d.]+) s)?/;

const browser = await chromium.launch();
try {
  for (const idea of IDEAS) {
    const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
    const reqs = [];
    page.on("request", (r) => { if (/\/api\/check/.test(r.url()) && r.method() === "POST") { try { const b = JSON.parse(r.postData() || "{}"); if (b.req) reqs.push(b.req); } catch { /* not JSON */ } } });
    try {
      for (let attempt = 1; ; attempt++) {                        // a page that did not load is loaded once more, before any check
        try { await page.goto(APP + "/app/", { waitUntil: "domcontentloaded", timeout: 90000 }); await page.waitForSelector("#k-q", { timeout: 60000 }); break; }
        catch (e) { if (attempt === 2) throw e; await sleep(20000); }
      }
      await page.fill("#k-q", idea);
      await page.click("#k-go");
      const during = [];
      let picked = false;
      const t0 = Date.now();
      while (Date.now() - t0 < 150000) {                           // read the counter while the check runs
        const s = await page.evaluate(() => ({ busy: document.querySelector("#k-go")?.hasAttribute("aria-busy"), n: document.querySelector("#k-live [data-count]")?.innerText || "",
          which: !!document.querySelector("#k-card [data-which]") }));
        if (s.which && !picked) { picked = true; await page.click('#k-card [data-which] [data-kind="exact"], #k-card [data-which] [data-reading]'); continue; }   // one click, as a reader
        if (s.busy && COUNT.test(s.n)) during.push(s.n);
        if (!s.busy && await page.$("#k-card .k-card [data-without]")) break;
        await sleep(200);
      }
      await sleep(2500);                                            // the last count, read once more after the end
      const final = await page.$eval("#k-live [data-count]", (e) => e.innerText).catch(() => "");
      const m = COUNT.exec(final) || [];
      const logged = ((await (await fetch(APP + "/api/calls")).json()).calls || []).filter((c) => c.req === reqs.at(-1));          // the last check the page ran
      const liveLog = logged.filter((c) => c.origin === "live");
      const ents = liveLog.reduce((a, c) => a + (c.n || 0), 0);
      const shown = during.filter((x) => Number(COUNT.exec(x)[1]) > 0).length;
      ok(shown > 0 && Number(m[1]) === liveLog.length && Number(m[2]) === ents && !!m[3] && liveLog.length > 0,
        `${idea}: ${during.length} counts read while it ran (${shown} above 0, last "${during.at(-1) || ""}"); at the end "${final}"; the server log has ${liveLog.length} live calls carrying ${ents} entities`);
    } catch (e) {
      ok(false, `${idea}: ${e.name}: ${String(e.message).split("\n")[0].slice(0, 120)}`);
    }
    await page.close();
    await sleep(22000);
  }
} finally { await browser.close(); }
log(fails.length ? `FAIL test_run_counter: ${fails.length} of 3 checks failed; first: ${fails[0].slice(0, 160)}`
  : `PASS test_run_counter: 3 of 3 checks show live Qloo calls, entities and seconds while they run, and the last count equals the server log`);
process.exit(fails.length ? 1 : 0);
