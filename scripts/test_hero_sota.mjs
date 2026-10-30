// H1 test_hero_sota, live (Playwright Chromium): the front door (Pages) and /app/ (Render) at 390 and 1280, light and
// dark. Pass here: the first screen shows a finished real result (a verdict in the hero card, inside the viewport); a
// new result's top is in the viewport within 400 ms of it being drawn; CLS under 0.05; 0 page errors; under reduced
// motion 0 animation frames over 150 ms. Lighthouse (performance 0.95+, accessibility 1.0 on CI's pages) is read from
// the push-triggered lighthouse run of the same commit (CI is the judge of performance) and appended by the caller.
//
//   node scripts/test_hero_sota.mjs [result file]
import { chromium } from "playwright";
import { appendFileSync } from "node:fs";

const PAGES = [["front door", "https://drexthealpha.github.io/Knos/"], ["/app/", "https://knos.onrender.com/app/"]];
const OUT = process.argv[2] || "";
const lines = [], fails = [];
const log = (s) => { console.log(s); lines.push(s); };
const ok = (c, what) => { log(`${c ? "ok  " : "FAIL"} ${what}`); if (!c) fails.push(what); return c; };
const VERDICT = /Wanted|Open for pre-orders|Not yet|Not enough evidence/;

const browser = await chromium.launch();
try {
  for (const [name, url] of PAGES) {
    for (const width of [390, 1280]) {
      for (const scheme of ["light", "dark"]) {
        const ctx = await browser.newContext({ viewport: { width, height: width === 390 ? 844 : 800 }, colorScheme: scheme });
        const page = await ctx.newPage();
        const errors = [];
        page.on("pageerror", (e) => errors.push(e.message));
        await page.addInitScript(() => {
          window.__cls = 0;
          new PerformanceObserver((l) => { for (const e of l.getEntries()) if (!e.hadRecentInput) window.__cls += e.value; }).observe({ type: "layout-shift", buffered: true });
        });
        await page.goto(url + "?t=" + Date.now(), { waitUntil: "networkidle", timeout: 120000 }).catch(() => null);
        await page.waitForTimeout(2500);
        const first = await page.evaluate((vh) => {
          const c = document.querySelector("#k-card .k-card, #k-card article, .k-hero [data-past], .k-hero article");
          if (!c) return { found: false };
          const r = c.getBoundingClientRect();
          return { found: true, text: (c.innerText || "").slice(0, 200), top: Math.round(r.top), inView: r.top < vh && r.bottom > 0 };
        }, width === 390 ? 844 : 800);
        ok(first.found && first.inView && VERDICT.test(first.text || ""), `${name} ${width} ${scheme}: first screen ${first.found ? `"${(first.text || "").split("\n")[0].slice(0, 60)}" at y=${first.top}` : "shows no result"}`);
        const cls = await page.evaluate(() => window.__cls);
        ok(cls < 0.05, `${name} ${width} ${scheme}: CLS ${cls.toFixed(3)}`);
        if (scheme === "light") {        // a new result: pressed chip, time from the card drawn to its top in view
          const chip = await page.$("button.k-chip[data-q]");
          if (chip) {
            await chip.click();
            const t = await page.waitForFunction(() => {
              const c = document.querySelector("#k-card .k-card:not([data-past]):not([data-confirm]), #k-card [data-which]");
              if (!c) return false;
              window.__drawn = window.__drawn || performance.now();
              const r = c.getBoundingClientRect();
              return r.top >= 0 && r.top < innerHeight ? performance.now() - window.__drawn : false;
            }, null, { timeout: 120000, polling: 20 }).then((h) => h.jsonValue()).catch(() => null);
            ok(t !== null && t <= 400, `${name} ${width}: a new result's top in view ${t === null ? "never" : `${Math.round(t)} ms`} after it was drawn`);
          }
        }
        ok(errors.length === 0, `${name} ${width} ${scheme}: ${errors.length} page errors${errors.length ? ": " + errors[0].slice(0, 100) : ""}`);
        await ctx.close();
      }
    }
    // reduced motion: no animation frame over 150 ms
    const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 }, reducedMotion: "reduce" });
    const page = await ctx.newPage();
    await page.goto(url + "?t=" + Date.now(), { waitUntil: "networkidle", timeout: 120000 }).catch(() => null);
    const long = await page.evaluate(() => new Promise((res) => {
      const anims = document.getAnimations().filter((a) => {
        const t = a.effect && a.effect.getTiming ? a.effect.getTiming() : {};
        return a.playState === "running" && (Number(t.duration) || 0) > 150;
      });
      res(anims.length);
    }));
    ok(long === 0, `${name} reduced motion: ${long} running animations longer than 150 ms`);
    await ctx.close();
  }
} finally { await browser.close(); }
log(fails.length ? `FAIL test_hero_sota: ${fails.length} of ${lines.length} checks failed; first: ${fails[0].slice(0, 140)}`
  : `PASS test_hero_sota: ${lines.length} of ${lines.length} checks on 2 pages x 2 widths x 2 schemes (Lighthouse from CI below)`);
if (OUT) appendFileSync(OUT, `\n${new Date().toISOString()}\n` + lines.join("\n") + "\n");
process.exit(fails.length ? 1 : 0);
