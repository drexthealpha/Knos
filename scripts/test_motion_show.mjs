// test_motion_show (M1), live: the crossing as one shape under the box on the front door. Playwright records its five
// states in order within 6 s, each state's number equals the live record's (the latest real verdict and its hash from
// /api/proof, the crossing's 10 pre-orders, the paid signature of the step below), layout shift under 0.05, Lighthouse
// mobile on the front door as the Pages build of this commit measured it (performance 0.90 or more, accessibility 0.95
// or more), no animation frame over 150 ms with reduced motion, 0 page errors, and the motion items of sweep 4.3 to
// 4.11 listed, each with applied yes or no.
//
//   node scripts/test_motion_show.mjs <commit sha> <items file> [result dir]
import { chromium } from "playwright";
import { appendFileSync, readFileSync } from "node:fs";

const SITE = "https://drexthealpha.github.io/Knos/", API = "https://knos.onrender.com";
const SHA = process.argv[2], ITEMS = process.argv[3], DIR = process.argv[4] || "C:/Users/zulab/knos-v1-private/v0328/world";
const lines = [], fails = [];
const ok = (c, w) => { lines.push(`${c ? "ok  " : "FAIL"} ${w}`); console.log(lines.at(-1)); if (!c) fails.push(w); };
const qj = await fetch(`${SITE}quality/quality.json?t=${Date.now()}`).then((r) => r.json()).catch(() => ({}));
const lh = (qj.lighthouse || []).find((x) => x.page === "landing" && x.form === "mobile") || {}, s = lh.scores || {};
ok(qj.commit === SHA, `quality.json is this commit's (${String(qj.commit || "none").slice(0, 7)})`);
ok(s.performance >= 0.9 && s.accessibility >= 0.95, `Lighthouse mobile front door: performance ${s.performance}, accessibility ${s.accessibility}`);
const proof = await fetch(`${API}/api/proof`).then((r) => r.json());
const pr = proof.sample || proof.proof || proof;
const browser = await chromium.launch();
const errors = [];
try {
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  await ctx.addInitScript(() => { window.__cls = 0; new PerformanceObserver((l) => { for (const e of l.getEntries()) if (!e.hadRecentInput) window.__cls += e.value; }).observe({ type: "layout-shift", buffered: true }); });
  const page = await ctx.newPage();
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto(SITE + "?t=" + Date.now(), { waitUntil: "load", timeout: 90000 });
  // the states as they come, sampled every 40 ms from the moment the shape starts
  await page.waitForFunction(() => document.getElementById("k-shape")?.dataset.ready === "1" || document.getElementById("k-shape")?.dataset.state !== "4", null, { timeout: 60000 }).catch(() => {});
  const seen = await page.evaluate(async () => { const f = document.getElementById("k-shape"), out = [], t0 = performance.now();
    while (performance.now() - t0 < 6500) { const st = f.dataset.state, n = f.querySelector("[data-num]").textContent; if (!out.length || out.at(-1).st !== st) out.push({ st, n, t: Math.round(performance.now() - t0) }); await new Promise((r) => setTimeout(r, 40)); }
    return out; });
  const order = seen.map((x) => x.st).join(",");
  ok(/0,1,2,3,4$/.test(order) && seen.at(-1).t <= 6000 + (seen.find((x) => x.st === "0")?.t || 0), `5 states in order: ${seen.map((x) => `${x.st}@${x.t}ms "${x.n}"`).join(", ")}`);
  const n = Object.fromEntries(seen.map((x) => [x.st, x.n]));
  const verdict = String(pr.decision?.verdict || "").replace("_", " ").toLowerCase(), hash = String(pr.ready?.criteria_hash || pr.criteria_hash || pr.hash || "").slice(0, 8);
  const sig = (await page.$eval("#k-paid a", (a) => a.href).catch(() => "")).match(/tx\/([1-9A-HJ-NP-Za-km-z]{8})/)?.[1] || "";
  const crossing = await fetch(`${SITE}crossing/7b4ed16b8c2903dc/facts.json`).then((r) => r.json()).catch(() => ({}));
  const held = `${(crossing.orders || []).length} pre-orders`;
  ok(n["1"] === verdict && n["2"] === hash && n["3"] === held && n["4"] === sig,
    `numbers: verdict "${n["1"]}" = "${verdict}", hash "${n["2"]}" = "${hash}", held "${n["3"]}" = "${held}", signature "${n["4"]}" = "${sig}"`);
  const cls = await page.evaluate(() => window.__cls);
  ok(cls < 0.05, `layout shift ${cls.toFixed(4)}`);
  // reduced motion: the last frame, nothing that moves for more than 150 ms
  const red = await browser.newContext({ viewport: { width: 390, height: 844 }, reducedMotion: "reduce" });
  const rp = await red.newPage();
  rp.on("pageerror", (e) => errors.push("reduced: " + e.message));
  await rp.goto(SITE + "?t=" + Date.now(), { waitUntil: "load", timeout: 90000 });
  await rp.waitForTimeout(4000);
  const long = await rp.evaluate(() => document.getAnimations().filter((a) => { const t = a.effect?.getTiming?.(); return t && Number(t.duration) > 150; }).length);
  const last = await rp.$eval("#k-shape", (f) => f.dataset.state);
  ok(long === 0 && last === "4", `reduced motion: ${long} animations over 150 ms, the shape rests at state ${last}`);
} finally { await browser.close(); }
ok(errors.length === 0, `${errors.length} page errors${errors.length ? ": " + errors.slice(0, 2).join(" | ") : ""}`);
const items = readFileSync(ITEMS, "utf8").trim().split(/\r?\n/);
lines.push(`motion items of sweep 4.3 to 4.11, each with applied yes or no (${items.filter((l) => /applied yes/.test(l)).length} yes, ${items.filter((l) => /applied no/.test(l)).length} no):`, ...items.map((l) => "  " + l));
const line = fails.length ? `FAIL test_motion_show: ${fails.length} check(s) failed` : `PASS test_motion_show: 5 states in order within 6 s with the live record's numbers, layout shift under 0.05, Lighthouse ${s.performance}/${s.accessibility}, 0 long moves with reduced motion, 0 page errors`;
lines.push(line); console.log(line);
appendFileSync(`${DIR}/test_motion_show.txt`, lines.join("\n") + "\n");
process.exit(fails.length ? 1 : 0);
