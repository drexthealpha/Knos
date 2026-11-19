// node tests/web/test_h3_budget.mjs <site dir>
// Round 13, H3 e: cheap phones and slow networks, on the four screens (the front door, the tool page, the result page
// and the pricing page; tests/web/test_h3_common.mjs serves them, the site gzip-compressed as GitHub Pages serves it,
// the server's pages as the server sends them, uncompressed). The numbers are the "Automatic check:" lines of
// LAWS/UX/U7.md and the D9 thresholds (LAWS/DISTRIBUTION/D9.md Annex C, findings 16 and 21):
//   U7 R23  at 360 x 800, network 5 Mbps down, 1 Mbps up, 100 ms, CPU slowed 6 times: every byte until load at most
//           300 KiB, of it script at most 100 KiB and fonts at most 50 KiB, in each shipped language; largest contentful
//           paint at most 2.5 s; the main action usable within 3 s
//   U7 R22  CPU slowed 6 times: total blocking time during load under 600 ms; the compressed script of the first screen
//           (its inline scripts counted, gzip-compressed, with the script files) within the R23 cap; every press shows a
//           visible change within 400 ms with the CPU slowed 6 times, as R22 sets it (the project's 200 ms rule, SPEC.md,
//           is held at the CPU slowed 4 times by tests/web/front_door_budget.mjs and at full speed by tests/web/tool.mjs;
//           a press over 200 ms here is printed, over 400 ms it fails)
//   D9      a core of 50 to 200 kB (Ola, finding 16: "a no-install web path under about 200 kB"): the first load of each
//           screen at most 200 kB
//   U7 R21  with script switched off, the result page still shows the result sentence (H3 e), and the tool page its
//           sample and its button
import { gzipSync } from "node:zlib";
import { chromiumOrSkip } from "./overflow.mjs";
import { serveScreens, LANGS } from "./test_h3_common.mjs";

const KIB = 1024, TOTAL = 300 * KIB, SCRIPT = 100 * KIB, FONTS = 50 * KIB, CORE = 200 * 1000, LCP = 2500, USABLE = 3000, TBT = 600, PRESS_LAW = 400, PRESS_FAIL = 200;
let fails = 0;
const check = (name, cond, detail) => { if (cond) console.log("ok  ", name); else { fails++; console.error("FAIL", name, detail === undefined ? "" : JSON.stringify(detail).slice(0, 500)); } };
const browser = await chromiumOrSkip();
const S = await serveScreens(process.argv[2]);

async function load(lang, url, opts = {}) {
  const ctx = await browser.newContext({ viewport: { width: 360, height: 800 }, locale: lang, hasTouch: true, javaScriptEnabled: opts.js !== false });
  await S.route(ctx);
  await ctx.addInitScript(() => {
    window.__v = { lcp: 0, long: [], marks: [], press: null };
    try { new PerformanceObserver((l) => { for (const e of l.getEntries()) window.__v.lcp = e.startTime; }).observe({ type: "largest-contentful-paint", buffered: true }); } catch { /* none */ }
    try { new PerformanceObserver((l) => { for (const e of l.getEntries()) window.__v.long.push([e.startTime, e.duration]); }).observe({ type: "longtask", buffered: true }); } catch { /* none */ }
    new MutationObserver(() => window.__v.marks.push(performance.now())).observe(document, { subtree: true, childList: true, attributes: true, characterData: true });
    for (const t of ["pointerdown", "mousedown", "keydown"]) addEventListener(t, (ev) => { if (window.__v.armed) { window.__v.press = ev.timeStamp; window.__v.armed = false; } }, { capture: true });
  });
  const page = await ctx.newPage();
  const cdp = await ctx.newCDPSession(page);
  await cdp.send("Network.enable");
  await cdp.send("Network.emulateNetworkConditions", { offline: false, latency: 100, downloadThroughput: 5e6 / 8, uploadThroughput: 1e6 / 8 });
  await cdp.send("Emulation.setCPUThrottlingRate", { rate: 6 });
  const bytes = { all: 0, script: 0, font: 0 }, types = new Map();
  cdp.on("Network.responseReceived", (e) => types.set(e.requestId, e.type));
  let loaded = false;
  cdp.on("Network.loadingFinished", (e) => { if (loaded) return; const t = types.get(e.requestId); bytes.all += e.encodedDataLength; if (t === "Script") bytes.script += e.encodedDataLength; if (t === "Font") bytes.font += e.encodedDataLength; });
  const t0 = Date.now();
  await page.goto(url, { waitUntil: "load" });
  loaded = true;
  const loadMs = Date.now() - t0;
  return { ctx, page, bytes, loadMs };
}

const SCREENS = Object.entries(S.screens);
// one load of each screen first, measured by nothing: a browser started cold is not a slow page
for (const [, url] of SCREENS) { const w = await load("en", url); await w.page.waitForTimeout(500); await w.ctx.close(); }
for (const [screen, url] of SCREENS) {
  for (const lang of LANGS) {
    const at = `${lang} ${screen}:`;
    const { ctx, page, bytes, loadMs } = await load(lang, url);
    if (lang !== "en" && (screen === "door" || screen === "price")) await page.waitForFunction((l) => document.documentElement.lang === l, lang, { timeout: 15000 }).catch(() => {});
    await page.waitForTimeout(800);
    const inline = await page.evaluate(() => [...document.scripts].filter((s) => !s.src && s.type !== "application/json").map((s) => s.textContent).join("\n"));
    const inlineGz = gzipSync(Buffer.from(inline)).length;
    const v = await page.evaluate(() => ({ lcp: Math.round(window.__v.lcp), tbt: Math.round(window.__v.long.filter(([s]) => s < performance.timing.loadEventEnd - performance.timing.navigationStart + 1000).reduce((n, [, d]) => n + Math.max(0, d - 50), 0)) }));
    const script = bytes.script + inlineGz;
    check(`${at} first load ${(bytes.all / KIB).toFixed(1)} KiB, at most 300 KiB (U7 R23)`, bytes.all <= TOTAL, bytes);
    check(`${at} first load at most 200 kB, a core as D9 finding 16 sets it`, bytes.all <= CORE, bytes.all);
    check(`${at} script ${(script / KIB).toFixed(1)} KiB compressed (inline ${(inlineGz / KIB).toFixed(1)} KiB), at most 100 KiB (U7 R22, R23)`, script <= SCRIPT, { files: bytes.script, inlineGz });
    check(`${at} fonts ${(bytes.font / KIB).toFixed(1)} KiB, at most 50 KiB (U7 R23)`, bytes.font <= FONTS, bytes.font);
    if (lang === "en" || lang === "ar" || lang === "hi") {
      check(`${at} largest contentful paint ${v.lcp} ms, at most 2.5 s (U7 R23, 5 Mbps, CPU 6x)`, v.lcp > 0 && v.lcp <= LCP, v);
      check(`${at} the main action usable ${loadMs} ms after the request, within 3 s (U7 R23)`, loadMs <= USABLE, loadMs);
      check(`${at} total blocking time ${v.tbt} ms during load, under 600 ms (U7 R22, CPU 6x)`, v.tbt < TBT, v);
    }
    if ((lang === "en" || lang === "ar") && screen !== "price") {
      await page.evaluate(() => { window.__v.armed = true; window.__v.press = null; });
      await page.tap(screen === "door" ? "#try" : "#go");
      await page.waitForTimeout(600);
      const ms = await page.evaluate(() => { const p = window.__v.press, m = window.__v.marks.find((t) => t > p); return p == null || m == null ? null : Math.round(m - p); });
      check(`${at} Check my data shows a visible change in ${ms} ms with the CPU slowed 6 times (U7 R22: 400 ms; SPEC: over 200 ms fails)`, ms != null && ms <= PRESS_LAW, ms);
      if (ms != null && ms > PRESS_FAIL) console.log(`note ${at} the press took ${ms} ms, over SPEC's 200 ms at full speed, with the CPU slowed 6 times`);
    }
    if (screen === "price" && (lang === "en" || lang === "ar")) {
      await page.evaluate(() => { window.__v.armed = true; window.__v.press = null; });
      await page.tap("details.how summary");
      await page.waitForTimeout(400);
      const ms = await page.evaluate(() => { const p = window.__v.press, m = window.__v.marks.find((t) => t > p); return p == null || m == null ? null : Math.round(m - p); });
      check(`${at} How it works opens with a visible change in ${ms} ms, within 400 ms (U7 R22, CPU 6x)`, ms != null && ms <= PRESS_LAW, ms);
    }
    await ctx.close();
  }
}

// U7 R21 and H3 e: scripts switched off
for (const lang of ["en", "ar"]) {
  const r = await load(lang, S.screens.result, { js: false });
  const shown = await r.page.evaluate(() => { const p = document.querySelector("#about"); return p ? p.textContent.trim() : ""; });
  check(`${lang}: with scripts blocked the result page shows the result sentence ("${shown.slice(0, 50)}")`, lang === "en" ? /^Failed at row 136: /.test(shown) : shown.length > 20 && /136/.test(shown), shown);
  await r.ctx.close();
  const t = await load(lang, S.screens.tool, { js: false });
  // G5: the box is offered empty, the sample shown in it as its example; sent untouched, the form checks that sample
  const tool = await t.page.evaluate(() => { const l = document.getElementById("list"), f = document.querySelector('#tool input[name="sample"]'); return { box: (l.value || l.placeholder).split("\n")[0], sample: l.value ? "1" : (f ? f.value : ""), go: !!document.getElementById("go") && !!document.getElementById("go").offsetParent }; });
  // F1B: the example's header says the sample's column in plain words, in the page's language (tool.sample_column)
  const plainCol = { en: "battery capacity", ar: "سعة البطارية" }[lang];
  check(`${lang}: with scripts blocked the tool page shows its sample and its button`, tool.box === `cycle,${plainCol}` && tool.sample === "1" && tool.go, tool);
  await t.ctx.close();
}

await browser.close(); S.close();
console.log(fails ? `${fails} failed` : "all passed");
process.exit(fails ? 1 : 0);
