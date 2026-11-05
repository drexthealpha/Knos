// F2 test_motion_showpiece: one page, the live front door at 1280 px. Scrolls the film (#k-film) to 0, 20, 40, 60, 80
// and 100 percent of its run and saves the viewport at each; records CLS (layout shifts without input), LCP and page
// errors; then checks that 390 px and reduced motion get the still (no canvas drawn).
//   node scripts/test_film_frames.mjs <site URL> <out dir>
import fs from "node:fs";
import path from "node:path";
import { chromium } from "playwright";

const [site = "https://drexthealpha.github.io/Knos/", out = "film-frames"] = process.argv.slice(2);
fs.mkdirSync(out, { recursive: true });
const browser = await chromium.launch({ args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"] });
const result = { site, frames: [], errors: [] };
const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 } });
await ctx.addInitScript(() => {
  window.__cls = 0; window.__lcp = 0;
  new PerformanceObserver((l) => { for (const e of l.getEntries()) if (!e.hadRecentInput) window.__cls += e.value; }).observe({ type: "layout-shift", buffered: true });
  new PerformanceObserver((l) => { for (const e of l.getEntries()) window.__lcp = e.startTime; }).observe({ type: "largest-contentful-paint", buffered: true });
});
const page = await ctx.newPage();
page.on("pageerror", (e) => result.errors.push(String(e).slice(0, 200)));
await page.goto(site + "?f=" + Date.now(), { waitUntil: "load", timeout: 120000 });
result.lcp_ms = Math.round(await page.evaluate(() => window.__lcp));
const film = page.locator("#k-film");
await film.scrollIntoViewIfNeeded();
await page.waitForFunction(() => document.getElementById("k-film")?.dataset.ready === "1", null, { timeout: 60000 }).catch(() => {});
result.ready = await page.evaluate(() => document.getElementById("k-film")?.dataset.ready === "1");
for (const pct of [0, 20, 40, 60, 80, 100]) {
  await page.evaluate((p) => {
    const f = document.getElementById("k-film"), top = f.getBoundingClientRect().top + scrollY;
    scrollTo(0, top + (f.offsetHeight - innerHeight) * p / 100);
  }, pct);
  await page.waitForTimeout(1800);         // the springs settle
  const file = path.join(out, `film-${String(pct).padStart(3, "0")}.png`);
  await page.screenshot({ path: file });
  const label = await page.evaluate(() => [...document.querySelectorAll("#k-film [data-stage][data-on], #k-film .k-film-stage, #k-film [aria-current]")].map((e) => e.textContent.trim()).join(" | "));
  result.frames.push({ pct, file, label });
}
result.cls = Math.round((await page.evaluate(() => window.__cls)) * 1000) / 1000;
await ctx.close();
for (const [name, opts] of [["phone", { viewport: { width: 390, height: 844 } }], ["reduced", { viewport: { width: 1280, height: 800 }, reducedMotion: "reduce" }]]) {
  const c = await browser.newContext(opts), p = await c.newPage();
  await p.goto(site + "?f=" + Date.now(), { waitUntil: "load", timeout: 120000 });
  await p.locator("#k-film").scrollIntoViewIfNeeded();
  await p.waitForTimeout(2500);
  result[name] = await p.evaluate(() => ({ ready: document.getElementById("k-film")?.dataset.ready || null, still: !!document.querySelector("#k-film .k-film-still, #k-film img, #k-film ol") }));
  await p.screenshot({ path: path.join(out, `film-${name}.png`) });
  await c.close();
}
await browser.close();
fs.writeFileSync(path.join(out, "film-frames.json"), JSON.stringify(result, null, 1));
console.log(JSON.stringify(result, null, 1));
