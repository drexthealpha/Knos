// test_motion, live: the motion layer of sweep20 M1.md (its 8 patterns) holds the hard limits. The Pages build's own
// quality.json for this commit: Lighthouse mobile performance 0.90 or more and the other three categories 0.95 or more,
// and axe 0 violations (light and dark), on the front door, /proof/, /demo/, a result page and /app/. Measured here:
// layout shift under 0.05 on those 5 pages at 390 and 1280 px; each pattern present where it belongs; and with
// prefers-reduced-motion, 0 animations or transitions longer than 150 ms while the pages load and are used.
//   node scripts/test_motion.mjs <commit sha under test>
import { chromium } from "playwright";
import { execFileSync } from "node:child_process";
import { appendFileSync } from "node:fs";

const [SHA] = process.argv.slice(2);
const OUT = `${process.env.KNOS_WORLD || `${process.env.KNOS_PRIVATE_DIR || "."}/v0328/world`}/test_motion.txt`;
const SITE = process.env.KNOS_SITE || "https://drexthealpha.github.io/Knos/", API = "https://knos.onrender.com";
const RID = "14d68eb782caff05";
const PAGES = [["landing", SITE], ["proof", `${SITE}proof/`], ["demo", `${SITE}demo/`], ["r", `${API}/r/${RID}`], ["app", `${API}/app/`]];
const lines = []; let fails = 0;
const ok = (c, what) => { lines.push(`${c ? "ok  " : "FAIL"} ${what}`); if (!c) fails++; };
const q = (u) => u + (u.includes("?") ? "&" : "?") + "t=" + Date.now();

const dep = JSON.parse(execFileSync("gh", ["api", "repos/drexthealpha/Knos/deployments?environment=github-pages&per_page=1"], { encoding: "utf8" }))[0];
ok(dep && dep.sha === SHA, `Pages deployed at ${dep && dep.sha.slice(0, 7)} (commit under test ${SHA.slice(0, 7)})`);
// 1. Lighthouse and axe, as the Pages build of this commit measured them
const qj = await (await fetch(q(`${SITE}quality/quality.json`))).json().catch(() => ({}));
ok(qj.commit === SHA, `quality.json is this commit's: ${String(qj.commit || "none").slice(0, 7)}, ${(qj.lighthouse || []).length} Lighthouse runs, ${(qj.axe || []).length} axe runs`);
for (const [page] of PAGES) {
  const m = (qj.lighthouse || []).find((x) => x.page === page && x.form === "mobile") || {}, s = m.scores || {};
  ok(s.performance >= 0.9 && s.accessibility >= 0.95 && s["best-practices"] >= 0.95 && s.seo >= 0.95,
    `Lighthouse mobile ${page}: ${m.error ? `not measured (${m.error.slice(0, 80)})` : `performance ${s.performance}, accessibility ${s.accessibility}, best practices ${s["best-practices"]}, SEO ${s.seo}`}`);
  const ax = (qj.axe || []).filter((x) => x.page === page);
  ok(ax.length === 2 && ax.every((x) => x.violations === 0), `axe ${page}: ${ax.map((x) => `${x.scheme} ${x.error ? "not run" : x.violations}`).join(", ") || "not run"}${ax.some((x) => x.violations) ? ` (${ax.flatMap((x) => (x.ids || []).map((i) => i.id)).join(", ")})` : ""}`);
}
const browser = await chromium.launch();
const errors = [];
// every animation or transition a page starts, with its length (element.animate included)
const WATCH = () => { window.__moves = [];
  const add = (kind, ms, what) => window.__moves.push({ kind, ms, what });
  const orig = Element.prototype.animate;
  Element.prototype.animate = function (k, o) { const d = typeof o === "number" ? o : (o && o.duration) || 0; add("animate", Number(d) + Number((o && o.delay) || 0) * 0, this.className || this.tagName); return orig.call(this, k, o); };
  const css = (ev, prop) => { const st = getComputedStyle(ev.target, ev.pseudoElement || null), ms = parseFloat(st[prop]) * (st[prop].endsWith("ms") ? 1 : 1000);
    add(ev.type, ms, `${ev.target.tagName}.${String(ev.target.className || "").slice(0, 30)}${ev.pseudoElement || ""} ${ev.animationName || ev.propertyName || ""}`); };
  addEventListener("animationstart", (e) => css(e, "animationDuration"), true);
  addEventListener("transitionrun", (e) => css(e, "transitionDuration"), true);
  window.__cls = 0;
  new PerformanceObserver((l) => { for (const e of l.getEntries()) if (!e.hadRecentInput) window.__cls += e.value; }).observe({ type: "layout-shift", buffered: true });
};
try {
  // 2. layout shift on the 5 pages at both widths (no reduced motion: the moves themselves must not shift anything)
  for (const [page, url] of PAGES) for (const width of [390, 1280]) {
    const ctx = await browser.newContext({ viewport: { width, height: 844 } });
    await ctx.addInitScript(WATCH);
    const p = await ctx.newPage();
    p.on("pageerror", (e) => errors.push(`${page} ${width}: ${e.message}`));
    await p.goto(q(url), { waitUntil: "domcontentloaded", timeout: 90000 });
    await p.waitForLoadState("load", { timeout: 60000 }).catch(() => {});
    await p.mouse.wheel(0, 900); await p.waitForTimeout(3500);
    const cls = await p.evaluate(() => Math.round(window.__cls * 10000) / 10000);
    ok(cls < 0.05, `${page} at ${width}: layout shift ${cls}`);
    await ctx.close();
  }
  // 3. the 8 patterns, each where M1 puts it
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  await ctx.addInitScript(WATCH);
  const f = await ctx.newPage();
  f.on("pageerror", (e) => errors.push(`patterns: ${e.message}`));
  await f.goto(q(SITE), { waitUntil: "domcontentloaded", timeout: 90000 });
  const p6 = await f.evaluate(() => [...document.querySelectorAll("style")].some((s) => /@view-transition\{navigation:auto\}/.test(s.textContent)));
  await f.fill("#k-q", "a sleep mask for night shift nurses");
  const w0 = await f.evaluate(() => document.getElementById("k-go").offsetWidth);
  await f.click("#k-go");
  await f.waitForTimeout(150);
  const p1 = await f.evaluate((w) => { const g = document.getElementById("k-go"); return { kept: Math.abs(g.offsetWidth - w) <= 1, spin: !!g.querySelector(".k-spin"), moves: window.__moves.filter((m) => m.kind === "animate").length }; }, w0);
  ok(p1.kept && p1.spin && p1.moves >= 1, `P1 the check button keeps its box (${p1.kept}) and its label hands over to a spinner (${p1.spin}), by element.animate (${p1.moves})`);
  await f.waitForSelector("#k-card > .k-card", { timeout: 45000 }).catch(() => {});
  await f.click('[data-q="a solar powered music festival"]');
  await f.waitForSelector("#k-card [data-sure]", { timeout: 30000 }).catch(() => {});
  await f.click("#k-card [data-sure]").catch(() => {});
  await f.waitForFunction(() => document.querySelector("#k-card > .k-card [data-part=calls-head]"), null, { timeout: 45000 }).catch(() => {});
  const p5 = await f.evaluate(() => getComputedStyle(document.querySelector("#k-card > .k-card .k-verdict")).animationName);
  ok(p5 === "k-rise", `P5 the verdict rises from its mask line: animation ${p5}`);
  await f.click('#k-card [data-view="model"]').catch(() => {});
  await f.waitForTimeout(400);
  const p2 = await f.evaluate(() => { const i = document.querySelector("#k-card .k-switch i"); return i ? { w: i.offsetWidth, moved: window.__moves.some((m) => m.kind === "animate" && m.ms === 320) } : null; });
  ok(p2 && p2.w > 0 && p2.moved, `P2 the switch's indicator rides to the pressed tab: ${JSON.stringify(p2)}`);
  const p4 = await f.evaluate(() => [...document.styleSheets].some((s) => { try { return [...s.cssRules].some((r) => /\.k-cities li:hover::before/.test(r.cssText)); } catch { return false; } }));
  ok(p4, "P4 the accent dot marks the city under the pointer (card.css)");
  ok(p6, "P6 the front door's pages enter by a view transition");
  await ctx.close();
  const pr = await (await browser.newContext({ viewport: { width: 1280, height: 900 } })).newPage();
  await pr.addInitScript(WATCH);
  await pr.goto(q(`${SITE}proof/`), { waitUntil: "domcontentloaded", timeout: 90000 });
  await pr.waitForTimeout(2500);
  const p38 = await pr.evaluate(() => ({ bars: window.__moves.filter((m) => m.kind === "animate" && m.ms === 720).length, quota: document.querySelector("[data-quota-said]")?.textContent || "" }));
  ok(p38.bars >= 2, `P3 the proof bars fill once in view: ${p38.bars} bar moves`);
  ok(/^Qloo's month: /.test(p38.quota), `P8 Qloo's month as a bucket from its two numbers: "${p38.quota}"`);
  const rc = await (await fetch(q(`${API}/receipts/${RID}`))).text();
  ok(/<svg class="k-draw"/.test(rc) && /stroke-dashoffset/.test(rc), "P7 the receipts' check marks draw on");
  // 4. reduced motion: nothing longer than 150 ms while the 5 pages load and are used
  let long = [];
  for (const [page, url] of PAGES) {
    const rctx = await browser.newContext({ viewport: { width: 1280, height: 900 }, reducedMotion: "reduce" });
    await rctx.addInitScript(WATCH);
    const p = await rctx.newPage();
    await p.goto(q(url), { waitUntil: "domcontentloaded", timeout: 90000 });
    await p.waitForLoadState("load", { timeout: 60000 }).catch(() => {});
    await p.mouse.wheel(0, 1200); await p.waitForTimeout(2000);
    if (page === "landing") {
      await p.click('[data-q="a probiotic kombucha brand"]').catch(() => {});
      await p.waitForSelector("#k-card [data-sure]", { timeout: 30000 }).catch(() => {});
      await p.click("#k-card [data-sure]").catch(() => {});
      await p.waitForTimeout(6000);
      await p.click('#k-card [data-view="model"]').catch(() => {});
      await p.waitForTimeout(500);
    }
    const got = await p.evaluate(() => window.__moves.filter((m) => m.ms > 150));
    long = long.concat(got.map((m) => `${page}: ${m.kind} ${Math.round(m.ms)} ms ${m.what}`));
    await rctx.close();
  }
  ok(long.length === 0, `with reduced motion, moves longer than 150 ms: ${long.length}${long.length ? ` (${long.slice(0, 3).join("; ")})` : ""}`);
} catch (e) {
  ok(false, `the browser step stopped: ${String(e.message).split("\n")[0].slice(0, 160)}`);
} finally {
  await browser.close();
}
ok(errors.length === 0, `page errors: ${errors.length}${errors.length ? ` (${errors.slice(0, 2).join("; ").slice(0, 200)})` : ""}`);
lines.push(fails ? `FAIL test_motion: ${fails} check(s) failed` : "PASS test_motion: the 8 patterns present; Lighthouse and axe within limits on 5 pages; layout shift under 0.05; 0 moves over 150 ms with reduced motion");
console.log(lines.join("\n"));
appendFileSync(OUT, lines.join("\n") + "\n");
process.exit(fails ? 1 : 0);
