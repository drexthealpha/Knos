// node tests/web/front_door_budget.mjs <site dir>
// The front door's numbers (Round 7, S1), on a 390 x 844 phone with the CPU slowed 4 times, in light and dark:
// the first screen holds one plain line, the paste box in the middle of the screen, one primary button and the sample,
// whose answer appears on that same screen; the page is at most 3 screens tall and at most 150 words; body text is at
// least 16 px; every touch target is at least 44 px (a link inside a sentence is exempt, as WCAG 2.2 2.5.8 exempts it);
// text contrast meets WCAG 2.2 AA (4.5:1, or 3:1 for large text); every press shows a visible change within 100 ms
// (a slower one is reported, and over 200 ms fails); LCP is at most 2.5 s and CLS at most 0.1.
// The hosted app is mocked: each call answers after 900 ms. The front door is composed here from the site the web job
// builds, as scripts/build_site.sh composes the published site (scripts/site_pages.py).
import { createServer } from "node:http";
import { readFileSync, existsSync, mkdtempSync, cpSync, rmSync } from "node:fs";
import { join, extname, dirname, resolve } from "node:path";
import { tmpdir } from "node:os";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { chromiumOrSkip, TYPES } from "./overflow.mjs";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const given = process.argv[2];
if (!given || !existsSync(join(given, "index.html"))) { console.error("usage: node tests/web/front_door_budget.mjs <site dir>"); process.exit(2); }
const made = mkdtempSync(join(tmpdir(), "front-door-")), root = resolve(made, "site");
cpSync(given, root, { recursive: true });
execFileSync(process.env.PYTHON || "python3", [join(ROOT, "scripts", "site_pages.py"), root], { stdio: "inherit" });

const W = 390, H = 844, DELAY = 900;
const MAX_WORDS = 150, MAX_SCREENS = 3, MIN_TEXT = 16, MIN_TARGET = 44, PRESS_GOOD = 100, PRESS_FAIL = 200, LCP = 2500, CLS = 0.1;
let fails = 0;
const check = (name, cond, detail) => { if (cond) console.log("ok  ", name); else { fails++; console.error("FAIL", name, detail === undefined ? "" : JSON.stringify(detail)); } };

const SAMPLE = "https://doi.org/10.46298/dmtcs.3545";
const ANSWERS = {
  "/api/near/claim/look": (b) => (String(b.url || "").includes("dmtcs.3545")
    ? { ok: true, known: true, paper: "HyperLogLog: the analysis of a near-optimal cardinality estimation algorithm", authors: "Flajolet, Fusy, Gandouet and Meunier, 2007",
        doi: SAMPLE, paper_number: "2% typical error, 1.5 kilobytes of memory", last: { holds: true, job: "job-1", record: "https://example.org/record" } }
    : { ok: true, known: false, title: "Another paper", quote: { checker: "a person who reruns it", price: "$330 to $763", time: "weeks", source: "https://example.org/" } }),
  "/api/near/claim/counters": () => ({ proofs: 231, usd: 4278, lost_usd: 0 }),
};
const browser = await chromiumOrSkip();
const server = createServer((req, res) => {
  const path = join(root, decodeURIComponent(new URL(req.url, "http://x").pathname).replace(/\/$/, "/index.html"));
  if (!path.startsWith(root) || !existsSync(path)) { res.writeHead(404); return res.end(); }
  res.writeHead(200, { "content-type": TYPES[extname(path)] || "application/octet-stream" }); res.end(readFileSync(path));
});
await new Promise((r) => server.listen(0, "127.0.0.1", r));
const base = `http://127.0.0.1:${server.address().port}/`;

async function open(scheme) {
  const ctx = await browser.newContext({ viewport: { width: W, height: H }, colorScheme: scheme, hasTouch: true });
  await ctx.route("**/*", async (route) => {
    const req = route.request(), u = new URL(req.url());
    if (req.url().startsWith(base)) return route.continue();
    if (u.hostname === "knos.onrender.com") {
      await new Promise((r) => setTimeout(r, DELAY));
      let body = {}; try { body = JSON.parse(req.postData() || "{}"); } catch { /* not JSON */ }
      const f = ANSWERS[u.pathname];
      return route.fulfill({ status: 200, contentType: "application/json", headers: { "access-control-allow-origin": "*" }, body: JSON.stringify(f ? f(body) : { ok: false }) });
    }
    return route.abort();
  });
  await ctx.addInitScript(() => {
    window.__v = { lcp: 0, cls: 0, marks: [], press: null };
    new PerformanceObserver((l) => { for (const e of l.getEntries()) window.__v.lcp = e.startTime; }).observe({ type: "largest-contentful-paint", buffered: true });
    new PerformanceObserver((l) => { for (const e of l.getEntries()) if (!e.hadRecentInput) window.__v.cls += e.value; }).observe({ type: "layout-shift", buffered: true });
    new MutationObserver(() => window.__v.marks.push(performance.now())).observe(document, { subtree: true, childList: true, attributes: true, characterData: true });
    for (const t of ["pointerdown", "mousedown", "keydown"]) addEventListener(t, (ev) => { if (window.__v.armed) { window.__v.press = ev.timeStamp; window.__v.armed = false; } }, { capture: true });
  });
  const page = await ctx.newPage();
  const cdp = await ctx.newCDPSession(page);
  await cdp.send("Emulation.setCPUThrottlingRate", { rate: 4 });
  await page.goto(base, { waitUntil: "load" });
  await page.waitForLoadState("networkidle");   // a visitor presses once the page has settled
  await page.waitForTimeout(DELAY + 600);
  return { ctx, page };
}

async function press(page, sel) {
  await page.evaluate(() => { window.__v.armed = true; window.__v.press = null; });
  await page.tap(sel);
  await page.waitForTimeout(400);
  return page.evaluate(() => { const p = window.__v.press; const m = window.__v.marks.find((t) => t > p); return p == null || m == null ? null : Math.round(m - p); });
}

// one load first, measured by nothing: a browser started cold is not a slow page
{ const w = await open("light"); await w.ctx.close(); }
for (const scheme of ["light", "dark"]) {
  const { ctx, page } = await open(scheme);
  const at = `${scheme}, 390 px:`;
  const m = await page.evaluate(({ MIN_TEXT }) => {
    const vis = (e) => { const r = e.getBoundingClientRect(), s = getComputedStyle(e); return r.width > 0 && r.height > 0 && s.visibility !== "hidden" && s.display !== "none"; };
    const box = (s) => { const e = document.querySelector(s); if (!e) return null; const r = e.getBoundingClientRect(); return { top: r.top, bottom: r.bottom, mid: (r.top + r.bottom) / 2 }; };
    const words = document.body.innerText.split(/\s+/).filter((w) => /[\p{L}\p{N}]/u.test(w)).length;
    const texts = [...document.querySelectorAll("body *")].filter((e) => vis(e) && [...e.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim()) && !e.closest(".sr"));
    const small = texts.filter((e) => parseFloat(getComputedStyle(e).fontSize) < MIN_TEXT).map((e) => `${e.tagName} ${e.textContent.trim().slice(0, 30)} ${getComputedStyle(e).fontSize}`);
    const inline = (a) => a.tagName === "A" && a.parentElement && a.parentElement.tagName === "P" && a.parentElement.textContent.trim().length > a.textContent.trim().length + 8;
    const tiny = [...document.querySelectorAll("a, button, input, textarea, select, summary")].filter((e) => vis(e) && !inline(e)).filter((e) => { const r = e.getBoundingClientRect(); return r.height < 44 || r.width < 44; })
      .map((e) => `${e.tagName} ${(e.textContent || e.id).trim().slice(0, 30)} ${Math.round(e.getBoundingClientRect().width)}x${Math.round(e.getBoundingClientRect().height)}`);
    // WCAG contrast of each text element against the first opaque background behind it
    const rgb = (c) => { const m = c.match(/[\d.]+/g); return m ? m.map(Number) : [0, 0, 0, 0]; };
    const lum = ([r, g, b]) => { const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; }; return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b); };
    const bg = (e) => { for (let n = e; n; n = n.parentElement) { const c = rgb(getComputedStyle(n).backgroundColor); if (c.length < 4 || c[3] > 0.5) if (c.length < 4 || c[3] > 0) return c; } return [255, 255, 255]; };
    const low = texts.map((e) => { const s = getComputedStyle(e), fg = rgb(s.color), b = bg(e), L1 = lum(fg), L2 = lum(b);
      const ratio = (Math.max(L1, L2) + 0.05) / (Math.min(L1, L2) + 0.05), px = parseFloat(s.fontSize), large = px >= 24 || (px >= 18.66 && +s.fontWeight >= 700);
      return { t: e.textContent.trim().slice(0, 30), ratio: Math.round(ratio * 100) / 100, need: large ? 3 : 4.5 }; }).filter((x) => x.ratio < x.need);
    const mk = document.querySelector(".kh .mark"), mb = mk && mk.getBoundingClientRect(), mc = mk && rgb(getComputedStyle(mk).backgroundColor), pg = bg(document.body);
    const markRatio = mk ? (Math.max(lum(mc), lum(pg)) + 0.05) / (Math.min(lum(mc), lum(pg)) + 0.05) : 0;
    const mark = { w: mb ? Math.round(mb.width) : 0, h: mb ? Math.round(mb.height) : 0, ratio: Math.round(markRatio * 10) / 10, masked: mk ? /mark\.svg/.test(getComputedStyle(mk).maskImage || getComputedStyle(mk).webkitMaskImage) : false };
    return { mark, words, height: document.documentElement.scrollHeight, wide: document.documentElement.scrollWidth, small, tiny, low,
      h1: box("h1"), input: box("#paper"), go: box("#go"), sample: box("#sample"),
      primaries: [...document.querySelectorAll(".door button.go, .door .go")].filter(vis).length };
  }, { MIN_TEXT });
  check(`${at} the Knos logo mark shows in the header (drawn in the text colour, 3:1 against the page)`, m.mark.w >= 20 && m.mark.h >= 20 && m.mark.masked && m.mark.ratio >= 3, m.mark);
  check(`${at} one plain line on the first screen`, m.h1 && m.h1.top >= 0 && m.h1.bottom <= H, m.h1);
  check(`${at} the paste box in the middle of the first screen (its centre between 25% and 75% of 844 px)`, m.input && m.input.mid >= H * 0.25 && m.input.mid <= H * 0.75, m.input);
  check(`${at} one primary button, on the first screen`, m.primaries === 1 && m.go && m.go.bottom <= H, { primaries: m.primaries, go: m.go });
  check(`${at} the sample on the first screen`, m.sample && m.sample.bottom <= H, m.sample);
  check(`${at} at most ${MAX_SCREENS} screens tall (${m.height} px)`, m.height <= MAX_SCREENS * H, m.height);
  check(`${at} no sideways scroll`, m.wide <= W, m.wide);
  check(`${at} at most ${MAX_WORDS} words (${m.words})`, m.words <= MAX_WORDS, m.words);
  check(`${at} body text at least ${MIN_TEXT} px`, m.small.length === 0, m.small);
  check(`${at} touch targets at least ${MIN_TARGET} px`, m.tiny.length === 0, m.tiny);
  check(`${at} text contrast WCAG 2.2 AA`, m.low.length === 0, m.low);
  const v = await page.evaluate(() => ({ lcp: Math.round(window.__v.lcp), cls: Math.round(window.__v.cls * 1000) / 1000 }));
  check(`${at} LCP at most ${LCP} ms (${v.lcp} ms, CPU slowed 4 times)`, v.lcp > 0 && v.lcp <= LCP, v);
  check(`${at} CLS at most ${CLS} (${v.cls})`, v.cls <= CLS, v);
  // the sample: one press, its answer on this same screen
  const t1 = await press(page, "#sample");
  check(`${at} "Try the sample": a visible change within ${PRESS_FAIL} ms (${t1} ms; ${t1 != null && t1 <= PRESS_GOOD ? "within" : "over"} ${PRESS_GOOD} ms)`, t1 != null && t1 <= PRESS_FAIL, t1);
  await page.waitForSelector("#out .verdict", { timeout: 10000 });
  const ans = await page.evaluate(() => { const r = document.querySelector("#out").getBoundingClientRect(), v = document.querySelector("#out .verdict"); return { text: v.textContent, top: Math.round(v.getBoundingClientRect().top), bottom: Math.round(v.getBoundingClientRect().bottom), scrollY }; });
  check(`${at} the sample's answer on the same first screen ("${ans.text}")`, ans.scrollY === 0 && ans.top >= 0 && ans.bottom <= H && /holds/.test(ans.text), ans);
  // the paste box and its button: another paper's answer
  await page.fill("#paper", "https://doi.org/10.1000/another");
  const t2 = await press(page, "#go");
  check(`${at} "Check it": a visible change within ${PRESS_FAIL} ms (${t2} ms; ${t2 != null && t2 <= PRESS_GOOD ? "within" : "over"} ${PRESS_GOOD} ms)`, t2 != null && t2 <= PRESS_FAIL, t2);
  await page.waitForFunction(() => /cannot prove/.test(document.querySelector("#out .verdict")?.textContent || ""), null, { timeout: 10000 });
  check(`${at} another paper says Knos cannot prove it yet`, true);
  await ctx.close();
}
await browser.close(); server.close(); rmSync(made, { recursive: true, force: true });
if (fails) { console.error(`${fails} check(s) failed`); process.exit(1); }
console.log("the front door keeps every S1 number");
