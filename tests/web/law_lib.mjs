// The set-up the law checks share (tests/web/law_checks.mjs, tests/web/section12.mjs); run by itself it does nothing.
//
// The five screens as built locally: the site that scripts/build_site.sh builds, with the front door, pricing/ and
// status/ composed on a copy by scripts/site_pages.py (as tests/web/tool.mjs and front_door_budget.mjs compose it), served
// under /Knos/; and the Knos app (apps/wanted, tests/web/law_app.py) for /t/limit-check/ and /r/<id>/, behind the same
// local address. Calls the front door makes to https://knos.onrender.com go to that local app; every other address
// outside is refused. No `playwright` package or no browser: SKIP outside CI, a failure in CI (tests/web/overflow.mjs).
import { createServer, request as httpRequest } from "node:http";
import { readFileSync, readdirSync, existsSync, statSync, mkdtempSync, cpSync, rmSync } from "node:fs";
import { spawn, execFileSync } from "node:child_process";
import { join, extname, dirname, resolve } from "node:path";
import { tmpdir } from "node:os";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";
import { AsyncLocalStorage } from "node:async_hooks";
import { chromiumOrSkip, TYPES } from "./overflow.mjs";

export const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");
export const SCREENS = ["door", "tool", "result", "price", "status"];
export const RUN_SCREENS = ["door", "tool", "result"];
// ROUND13-ITEMS H3 a, L09: a browser locale for every locale file of web/i18n (the first ten, then the rest by code),
// Chinese by its region (zh-Hans as zh-CN, zh-Hant as zh-TW)
const FIRST = ["en", "ar", "hi", "es", "fr", "pt", "zh-Hans", "id", "sw", "ru"];
const FILES = readdirSync(join(ROOT, "web", "i18n")).filter((f) => f.endsWith(".json")).map((f) => f.slice(0, -5));
export const LOCALES = [...FIRST.filter((c) => FILES.includes(c)), ...FILES.filter((c) => !FIRST.includes(c)).sort()]
  .map((c) => ({ "zh-Hans": "zh-CN", "zh-Hant": "zh-TW" })[c] || c);
export const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
// Pages that only read what a screen shows load side by side (KNOS_LAW_PAGES at once, 4 by default); a measure of time
// runs alone (excl): it waits for the others to close and nothing else opens until it is done.
const als = new AsyncLocalStorage();
const MAX_PAGES = Number(process.env.KNOS_LAW_PAGES || 4);
let active = 0, exclusive = false;
export async function excl(f) {
  if (als.getStore()) return f();
  while (exclusive) await sleep(25);
  exclusive = true;
  while (active > 0) await sleep(25);
  try { return await als.run({ excl: true }, f); } finally { exclusive = false; }
}
export const WORD = /[\p{L}\p{N}][\p{L}\p{N}\p{M}'’$%.,-]*/gu;
export const words = (s) => (String(s || "").match(WORD) || []).length;

// ---- contrast (WCAG 2.2 relative luminance) -----------------------------------------------------------------------------
export function rgb(s) { const m = String(s).match(/rgba?\(([^)]+)\)/); if (!m) return null; const p = m[1].split(/[ ,/]+/).filter(Boolean).map(Number); return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 }; }
export function lum(c) { const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; }; return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b); }
export function ratio(a, b) { const x = lum(a), y = lum(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); }

function axeSource() {
  const tries = [process.env.KNOS_AXE];
  try { tries.push(createRequire(join(ROOT, "x.js")).resolve("axe-core/axe.min.js", { paths: [ROOT, ...(process.env.NODE_PATH || "").split(/[:;]/).filter(Boolean)] })); } catch { /* not installed */ }
  for (const f of tries) if (f && existsSync(f)) return readFileSync(f, "utf8");
  return null;
}

export async function setup(given) {
  if (!given || !existsSync(join(given, "index.html"))) { console.error("usage: node tests/web/<law_checks|section12>.mjs <site dir>"); process.exit(2); }
  const T0 = Date.now(), dbg = (m) => { if (process.env.KNOS_LAW_DEBUG) console.error(`setup ${((Date.now() - T0) / 1000).toFixed(1)} s: ${m}`); };
  const browser = await chromiumOrSkip(); dbg("browser");
  const PY = process.env.PYTHON || "python3";
  const made = mkdtempSync(join(tmpdir(), "knos-law-")), root = resolve(made, "site");
  cpSync(given, root, { recursive: true });
  try { execFileSync(PY, [join(ROOT, "scripts", "site_pages.py"), root], { stdio: ["ignore", "ignore", "pipe"] }); } catch (e) { throw new Error("scripts/site_pages.py failed: " + String(e.stderr || e.message).slice(-1500)); } dbg("site composed");

  // the app, run locally (tests/web/law_app.py): its port is the first line it prints
  const app = spawn(PY, [join(ROOT, "tests", "web", "law_app.py")], { cwd: ROOT, stdio: ["pipe", "pipe", "pipe"] });
  let appErr = "";
  app.stderr.on("data", (d) => { appErr = (appErr + d).slice(-4000); });
  let out = "";
  app.stdout.on("data", (d) => { out += d; });
  const appPort = await new Promise((ok, no) => {
    const t = setTimeout(() => no(new Error("the app did not start in 60 s: " + appErr)), 60000);
    const look = () => { const m = out.match(/port (\d+)/); if (m) { clearTimeout(t); ok(Number(m[1])); } };
    app.stdout.on("data", look); look();
    app.on("exit", (c) => { clearTimeout(t); no(new Error(`the app stopped (${c}): ${appErr}`)); });
  });
  for (let i = 0; i < 50 && !/program [^\n]+\n/.test(out); i++) await sleep(100);
  dbg("app on " + appPort);
  const program = ((out.match(/program ([^\n]+)/) || [])[1] || "unknown").trim();

  const server = createServer((req, res) => {
    const u = new URL(req.url, "http://x");
    if (u.pathname === "/Knos") { res.writeHead(301, { location: "/Knos/" }); return res.end(); }
    if (u.pathname.startsWith("/Knos/")) {
      const path = decodeURIComponent(u.pathname);
      const file = join(root, path.slice(6) || "index.html");
      const hit = file.startsWith(root) && existsSync(file) && statSync(file).isFile() ? file : existsSync(join(file, "index.html")) ? join(file, "index.html") : null;
      if (!hit) { res.writeHead(404, { "content-type": "text/html" }); return res.end(readFileSync(join(root, "404.html"))); }
      res.writeHead(200, { "content-type": TYPES[extname(hit)] || (extname(hit) === ".png" ? "image/png" : extname(hit) === ".ico" ? "image/x-icon" : "application/octet-stream") });
      return res.end(readFileSync(hit));
    }
    const p = httpRequest({ host: "127.0.0.1", port: appPort, path: req.url, method: req.method, headers: req.headers }, (r) => { res.writeHead(r.statusCode, r.headers); r.pipe(res); });
    p.on("error", () => { if (!res.headersSent) res.writeHead(502); res.end(); });
    req.pipe(p);
  });
  await new Promise((r) => server.listen(0, "127.0.0.1", r));
  const ORIGIN = `http://127.0.0.1:${server.address().port}`;

  // one result of the sample, and one of an own file, made through the app's own /api/run (with the test marker)
  const runApi = async (body) => { const r = await fetch(ORIGIN + "/api/run", { method: "POST", headers: { "content-type": "application/json", "x-knos-test": "1" }, body: JSON.stringify({ id: "limit-check", test: true, ...body }) }); return { status: r.status, body: await r.json().catch(() => ({})) }; };
  const SAMPLE = readFileSync(join(ROOT, "near", "agents", "job", "data", "limit", "sample.csv"), "utf8").replace(/\r\n/g, "\n").replace(/\n+$/, "");
  const sampleRun = await runApi({ table: SAMPLE, column: "capacity_ah", rule: "above", limit: 1.4, mode: "sample", browser: "" });
  if (sampleRun.status !== 200) throw new Error(`the app's /api/run answered ${sampleRun.status}: ${JSON.stringify(sampleRun.body)}`);
  dbg("sample run");
  const rid = new URL(sampleRun.body.link).pathname.split("/")[2];
  const URLS = { door: `${ORIGIN}/Knos/`, tool: `${ORIGIN}/t/limit-check/?test=1`, result: `${ORIGIN}/r/${rid}/?test=1`, price: `${ORIGIN}/Knos/pricing/`, status: `${ORIGIN}/Knos/status/` };

  const contexts = new Set();
  async function context(o = {}) {
    const mine = !!als.getStore();
    if (!mine) { while (exclusive || active >= MAX_PAGES) await sleep(25); active++; }
    let ctx;
    try { ctx = await browser.newContext({ viewport: { width: o.w || 390, height: o.h || 844 }, colorScheme: o.scheme || "light", locale: o.locale || "en-US",
      hasTouch: !!o.touch, reducedMotion: o.reduced ? "reduce" : "no-preference", forcedColors: o.forced ? "active" : "none", javaScriptEnabled: o.js !== false,
      deviceScaleFactor: o.dsf || 1, extraHTTPHeaders: o.headers || undefined, storageState: o.storage || undefined });
    } catch (e) { if (!mine) active--; throw e; }
    contexts.add(ctx); ctx.on("close", () => { contexts.delete(ctx); if (!mine) active--; });
    ctx.law = { delay: o.delay || 0, fail: o.fail || null, payDelay: o.payDelay || 0, requests: [], blockJs: !!o.blockJs, blockFonts: !!o.blockFonts };
    await ctx.route("**/*", async (route) => {
      const req = route.request(); let u; try { u = new URL(req.url()); } catch { return route.abort(); }
      const local = u.origin === ORIGIN, hosted = u.hostname === "knos.onrender.com";
      ctx.law.requests.push({ url: req.url(), type: req.resourceType(), method: req.method() });
      if (!local && !hosted) return route.abort();
      if (ctx.law.blockJs && (req.resourceType() === "script" || /\.m?js(\?|$)/.test(u.pathname))) return route.abort();
      if (ctx.law.blockFonts && (req.resourceType() === "font" || /\.(woff2?|ttf|otf)(\?|$)/.test(u.pathname))) return route.abort();
      const cors = { "access-control-allow-origin": "*", "access-control-allow-headers": "content-type, x-knos-test", "access-control-allow-methods": "GET, POST, OPTIONS" };
      if (hosted && req.method() === "OPTIONS") return route.fulfill({ status: 204, headers: cors });
      if (u.pathname === "/api/run" && req.method() === "POST") {
        if (ctx.law.fail === "down") return route.abort("connectionfailed");
        if (ctx.law.delay) await sleep(ctx.law.delay);
        if (ctx.law.fail === "408") return route.fulfill({ status: 408, headers: { ...cors, "content-type": "application/json" }, body: JSON.stringify({ error: "This took too long and was stopped. Try a smaller file. I stopped it after 20 seconds and kept your file in the box." }) });
      }
      if (u.pathname === "/api/pay" && req.method() === "POST" && ctx.law.payDelay) await sleep(ctx.law.payDelay);
      if (u.pathname === "/api/pay" && req.method() === "POST" && ctx.law.payFail) return route.fulfill({ status: 500, headers: { ...cors, "content-type": "application/json" }, body: JSON.stringify({ error: "I could not record the test payment just now. Nothing was charged. Press Try again." }) });
      if (local) return route.continue().catch(() => {});
      const resp = await route.fetch({ url: ORIGIN + u.pathname + u.search }).catch(() => null);
      if (!resp) return route.abort().catch(() => {});
      return route.fulfill({ response: resp, headers: { ...resp.headers(), ...cors } }).catch(() => {});
    });
    return ctx;
  }
  // a screen, loaded in a context of its own; o.cpu slows the CPU, o.net = [down kbps, up kbps, latency ms]
  async function open(screen, o = {}) {
    const ctx = await context(o);
    if (o.init) for (const f of [].concat(o.init)) await ctx.addInitScript(f);
    const page = await ctx.newPage();
    page.law = { errors: [], console: [] };
    page.on("pageerror", (e) => page.law.errors.push(String(e.message || e)));
    page.on("console", (m) => { if (m.type() === "error") page.law.console.push(m.text()); });
    if (o.cpu || o.net) {
      const cdp = await ctx.newCDPSession(page);
      if (o.cpu) await cdp.send("Emulation.setCPUThrottlingRate", { rate: o.cpu });
      if (o.net) { await cdp.send("Network.enable"); await cdp.send("Network.emulateNetworkConditions", { offline: false, downloadThroughput: o.net[0] * 1024 / 8, uploadThroughput: o.net[1] * 1024 / 8, latency: o.net[2] }); }
      if (o.fontScale) await cdp.send("Page.setFontSizes", { fontSizes: { standard: 16 * o.fontScale, fixed: 13 * o.fontScale } });
    } else if (o.fontScale) { const cdp = await ctx.newCDPSession(page); await cdp.send("Page.setFontSizes", { fontSizes: { standard: 16 * o.fontScale, fixed: 13 * o.fontScale } }); }
    const url = screen in URLS ? URLS[screen] : screen;
    page.law.response = await page.goto(url, { waitUntil: "load", timeout: 60000 }).catch((e) => { page.law.errors.push("goto: " + e.message); return null; });
    if (o.settle !== 0) await page.waitForTimeout(o.settle || 300);
    return page;
  }
  const AXE = axeSource();
  async function axe(page, opts) {
    if (!AXE) return { error: "axe-core is not installed (npm install axe-core@4.10.2, or KNOS_AXE=<path to axe.min.js>)" };
    if (!(await page.evaluate(() => !!window.axe).catch(() => false))) await page.addScriptTag({ content: AXE });
    return page.evaluate(async (opts) => {
      const r = await window.axe.run(document, opts);
      return { violations: r.violations.map((v) => ({ id: v.id, n: v.nodes.length, at: v.nodes.slice(0, 3).map((x) => x.target.join(" ")).join(", "), why: (v.nodes[0] && v.nodes[0].failureSummary || "").split("\n").slice(1, 2).join("").trim().slice(0, 140) })),
        ran: [...r.passes, ...r.violations, ...r.incomplete, ...r.inapplicable].map((x) => x.id) };
    }, opts);
  }
  async function closeAll() { for (const c of [...contexts]) await c.close().catch(() => {}); }
  async function close() {
    for (const c of [...contexts]) await c.close().catch(() => {});
    await browser.close().catch(() => {});
    server.close();
    try { app.stdin.end(); } catch { /* gone */ }
    await new Promise((r) => { const t = setTimeout(() => { try { app.kill(); } catch { /* gone */ } r(); }, 3000); app.on("exit", () => { clearTimeout(t); r(); }); });
    rmSync(made, { recursive: true, force: true });
  }
  return { browser, ORIGIN, URLS, root, rid, closeAll, sample: sampleRun.body, SAMPLE, program, runApi, context, open, axe, close, hasAxe: !!AXE };
}

// ---- in-page measures ---------------------------------------------------------------------------------------------------
// the controls a person can press, each tagged data-law-i; returns what each one is
export const TAG_CONTROLS = () => {
  const sel = "a[href], button, input:not([type=hidden]), textarea, select, summary, [role=button], [role=tab], [role=switch], [onclick]";
  const vis = (el) => { const r = el.getBoundingClientRect(); if (!r.width || !r.height) return false; if (el.checkVisibility && !el.checkVisibility({ visibilityProperty: true, contentVisibilityAuto: true })) return false; const d = el.closest("details:not([open])"); if (d && !(d.querySelector(":scope > summary") || { contains: () => false }).contains(el)) return false; for (let e = el; e; e = e.parentElement) { const cs = getComputedStyle(e); if (cs.display === "none" || cs.visibility === "hidden") return false; } return true; };
  const list = [...document.querySelectorAll(sel)].filter(vis);
  list.forEach((el, i) => el.setAttribute("data-law-i", String(i)));
  return list.map((el) => ({ tag: el.tagName.toLowerCase(), type: (el.getAttribute("type") || "").toLowerCase(), name: (el.getAttribute("aria-label") || el.textContent || el.value || el.id || "").replace(/\s+/g, " ").trim().slice(0, 40),
    href: el.tagName === "A" ? el.href : "", target: el.getAttribute("target") || "", disabled: !!el.disabled, sameDoc: el.tagName === "A" && el.href.split("#")[0] === location.href.split("#")[0] }));
};
// arm a timer: from the press (pointer, touch or key) to the frame after the next DOM change, focus, scroll or hash change
export const ARM = () => {
  window.__law = { t0: null, done: undefined, ev: [] };
  const L = window.__law;
  try { sessionStorage.removeItem("lawDone"); } catch { /* none */ }
  const start = (ev) => { if (L.t0 === null) { L.t0 = ev.timeStamp; try { sessionStorage.setItem("lawT0", String(performance.timeOrigin + ev.timeStamp)); } catch { /* none */ } } };
  for (const t of ["pointerdown", "touchstart", "mousedown", "keydown"]) addEventListener(t, start, { capture: true, once: false });
  const end = () => { if (L.t0 === null || L.done !== undefined || L.pending) return; L.pending = true; requestAnimationFrame(() => { L.done = performance.now() - L.t0; try { sessionStorage.setItem("lawDone", String(L.done)); } catch { /* none */ } }); };
  new MutationObserver((ms) => { if (ms.some((m) => !(m.type === "attributes" && m.attributeName === "data-law-i"))) end(); }).observe(document, { subtree: true, childList: true, attributes: true, characterData: true });
  addEventListener("focusin", end, true); addEventListener("scroll", end, true); addEventListener("hashchange", end);
  try { new PerformanceObserver((l) => { for (const e of l.getEntries()) L.ev.push({ name: e.name, d: e.duration, at: e.startTime }); }).observe({ type: "event", durationThreshold: 16, buffered: false }); } catch { /* no event timing */ }
};

// press control i of a screen and measure; o.touch taps; the page is reloaded first by the caller
export async function measurePress(page, i, info, o = {}) {
  const base = { name: `${info.tag}${info.type ? "[" + info.type + "]" : ""} "${info.name}"` };
  if (info.disabled) return { ...base, skipped: "disabled" };
  if (info.tag === "a" && info.href && (new URL(info.href).origin !== new URL(page.url()).origin || info.target === "_blank")) return { ...base, skipped: "a link to another site or a new tab" };
  const sel = `[data-law-i="${i}"]`;
  if (info.tag === "input" && info.type === "file") {
    const t0 = Date.now();
    const got = await Promise.all([page.waitForEvent("filechooser", { timeout: 3000 }).then(() => Date.now() - t0).catch(() => Infinity), page.click(sel, { timeout: 3000 }).catch(() => null)]);
    return { ...base, ms: got[0], how: "file chooser" };
  }
  await page.evaluate(ARM);
  const url0 = page.url();
  let navigated = false; const onNav = (f) => { if (f === page.mainFrame()) navigated = true; }; page.on("framenavigated", onNav);
  let clicked = true;
  try { if (o.touch) await page.tap(sel, { timeout: 3000, noWaitAfter: true }); else await page.click(sel, { timeout: 3000, noWaitAfter: true }); } catch (e) { clicked = /Execution context|navigat|Target closed/.test(String(e.message)); if (!clicked) return { ...base, ms: Infinity, how: "could not be pressed: " + String(e.message).split("\n")[0].slice(0, 80) }; }
  try {
    await page.waitForFunction(() => window.__law && window.__law.done !== undefined, null, { timeout: 3000, polling: 16 });
    const r = await page.evaluate(() => ({ ms: window.__law.done, ev: Math.max(0, ...window.__law.ev.map((e) => e.d)) }));
    page.off("framenavigated", onNav);
    return { ...base, ms: r.ms, ev: r.ev, how: "same page" };
  } catch {
    {
      // a page that sends on to another (an older address) is followed to the page that stays
      let r = null;
      for (let k = 0; k < 4 && r === null; k++) {
        await page.waitForLoadState("load", { timeout: 15000 }).catch(() => {});
        await page.waitForFunction(() => performance.getEntriesByType("paint").length > 0, null, { timeout: 3000 }).catch(() => {});
        r = await page.evaluate(() => { const t0 = Number(sessionStorage.getItem("lawT0")); const p = performance.getEntriesByName("first-contentful-paint")[0] || performance.getEntriesByType("paint")[0]; const nav = performance.getEntriesByType("navigation")[0];
        const at = p ? p.startTime : nav ? nav.domContentLoadedEventEnd : null; return t0 && at !== null && performance.timeOrigin > t0 - 5 ? performance.timeOrigin + at - t0 : null; }).catch(() => null);
      }
      page.off("framenavigated", onNav);
      // a change the pressed page showed before the next page took over (a link's pressed look) is the first visible change
      const before = await page.evaluate(() => { const d = sessionStorage.getItem("lawDone"); return d === null ? null : Number(d); }).catch(() => null);
      if ((navigated || page.url() !== url0) && before !== null && (r === null || before < r)) return { ...base, ms: before, how: "new page, pressed look first" };
      if ((navigated || page.url() !== url0) && r !== null) return { ...base, ms: r, how: "new page" };
      if (navigated || page.url() !== url0) return { ...base, ms: Infinity, how: "new page, no paint time" };
    }
    return { ...base, ms: Infinity, how: "no visible change within 3 s" };
  }
}

// every control of a screen pressed once, each on a freshly loaded screen
export async function pressAll(env, screens, o = {}) {
  const out = [];
  for (const s of screens) {
    const page = await env.open(s, o);
    const infos = await page.evaluate(TAG_CONTROLS);
    for (let i = 0; i < infos.length; i++) {
      let r = null;
      for (let attempt = 0; attempt < 2 && !r; attempt++) {
        try {
          let at = i;
          if (i > 0 || attempt > 0) {
            await page.evaluate(() => { try { localStorage.clear(); sessionStorage.clear(); } catch { /* none */ } }).catch(() => {});
            await page.goto(env.URLS[s] || s, { waitUntil: "load" }); await page.waitForTimeout(o.cpu ? 400 : 150);
            const now = await page.evaluate(TAG_CONTROLS);
            const same = (x) => x && x.tag === infos[i].tag && x.name === infos[i].name && x.href === infos[i].href;
            if (!same(now[i])) at = now.findIndex(same);
            if (at < 0) { r = { name: `${infos[i].tag} "${infos[i].name}"`, skipped: "not on the screen after a fresh load" }; break; }
          }
          r = await measurePress(page, at, infos[i], o);
        } catch (e) {
          if (attempt === 1) r = { name: `${infos[i].tag} "${infos[i].name}"`, ms: Infinity, how: "not measured: " + String(e.message).split("\n")[0].slice(0, 80) };
          await page.waitForLoadState("load").catch(() => {});
        }
      }
      out.push({ screen: s, ...r });
      if (process.env.KNOS_LAW_DEBUG) console.error(`press ${s} ${i + 1}/${infos.length} ${r.name} ${r.ms === undefined ? r.skipped : Math.round(r.ms)} ${r.how || ""}`);
    }
    await page.context().close();
  }
  return out;
}

// what a screen shows, measured once it has loaded, at the top of the page
export const SURVEY = () => {
  scrollTo(0, 0);
  const H = innerHeight, W = innerWidth, de = document.documentElement;
  const WORD = /[\p{L}\p{N}][\p{L}\p{N}\p{M}'’$%.,-]*/gu, wc = (s) => (String(s).match(WORD) || []).length;
  const visible = (el) => { const r = el.getBoundingClientRect(); if (!r.width || !r.height) return false; if (el.checkVisibility && !el.checkVisibility({ visibilityProperty: true, contentVisibilityAuto: true })) return false; const dd = el.closest("details:not([open])"); if (dd && !(dd.querySelector(":scope > summary") || { contains: () => false }).contains(el)) return false; for (let e = el; e; e = e.parentElement) { const cs = getComputedStyle(e); if (cs.display === "none" || cs.visibility === "hidden") return false; } return true; };
  const box = (el) => { if (!el) return null; const r = el.getBoundingClientRect(); return { x: r.left, y: r.top, w: r.width, h: r.height, b: r.bottom, r: r.right }; };
  const texts = [];
  const walk = (n, user) => {
    if (n.nodeType === 3) { const t = n.textContent.replace(/\s+/g, " ").trim(); if (!t) return; const rg = document.createRange(); rg.selectNodeContents(n); const b = rg.getBoundingClientRect(); if (!b.width && !b.height) return;
      texts.push({ t, node: n, el: n.parentElement, top: b.top, bottom: b.bottom, fs: parseFloat(getComputedStyle(n.parentElement).fontSize), user }); return; }
    if (n.nodeType !== 1 || /^(SCRIPT|STYLE|NOSCRIPT|TEMPLATE|TEXTAREA|OPTION|svg)$/i.test(n.tagName)) return;
    const cs = getComputedStyle(n); if (cs.display === "none" || cs.visibility === "hidden") return;
    const u = user || n.hasAttribute("data-user-content");
    if (n.tagName === "DETAILS" && !n.open) { const s = n.querySelector(":scope > summary"); if (s) walk(s, u); return; }
    if (n.tagName === "SELECT") { const o = n.selectedOptions[0], b = n.getBoundingClientRect(); if (o && b.width) texts.push({ t: o.textContent.trim(), node: n, el: n, top: b.top, bottom: b.bottom, fs: parseFloat(cs.fontSize), user: u }); return; }
    for (const c of n.childNodes) walk(c, u);
  };
  walk(document.body, false);
  const own = texts.filter((x) => !x.user);
  const ta = [...document.querySelectorAll("textarea")].find(visible) || null;
  const input = document.querySelector("[data-main-input]") || ta || [...document.querySelectorAll("input:not([type=hidden]):not([type=file]):not([type=checkbox]):not([type=radio])")].find(visible) || null;
  const dmain = document.querySelector("[data-main-action]");
  const prims = [...document.querySelectorAll("[data-primary]")].filter(visible);
  const goEl = document.getElementById("try") || document.getElementById("go") || [...document.querySelectorAll("button.primary, button.go, .go, a.btn, .btn, button")].find(visible) || null;
  const before = (el) => el ? own.filter((x) => x.node.compareDocumentPosition(el) & Node.DOCUMENT_POSITION_FOLLOWING && !(x.node.nodeType === 1 && x.node === el)) : [];
  const sum = (a) => a.reduce((s, x) => s + wc(x.t), 0);
  const ib = input ? input.getBoundingClientRect() : null;
  const ctlSel = "a[href], button, input:not([type=hidden]), textarea, select, summary, [role=button], [role=tab], [role=switch], [onclick]";
  const controls = [...document.querySelectorAll(ctlSel)].filter(visible).map((el) => {
    const r = el.getBoundingClientRect(), block = el.closest("p, li, td, dd, span.inline");
    const inline = el.tagName === "A" && !!block && block.textContent.trim().length > el.textContent.trim().length + 3 && getComputedStyle(el).display.startsWith("inline");
    return { tag: el.tagName.toLowerCase(), type: el.getAttribute("type") || "", id: el.id, name: (el.getAttribute("aria-label") || el.textContent || el.value || "").replace(/\s+/g, " ").trim().slice(0, 30),
      x: r.left, y: r.top, w: r.width, h: r.height, inline, primary: el.hasAttribute("data-primary") || /\b(primary|go)\b/.test(el.className || ""), fixed: false };
  });
  const lists = [...document.querySelectorAll("ol, ul, nav")].filter(visible).map((l) => ({ tag: l.tagName.toLowerCase(), n: l.tagName === "NAV" ? l.querySelectorAll(":scope > a, :scope > ul > li, :scope > ol > li").length : l.querySelectorAll(":scope > li").length, id: l.id || l.className || "" }));
  const heads = [...document.querySelectorAll("h1, h2, h3, h4, h5, h6")].filter(visible);
  const sections = heads.map((h, i) => { const next = heads[i + 1]; const inside = own.filter((x) => (h.compareDocumentPosition(x.node) & Node.DOCUMENT_POSITION_FOLLOWING) && !h.contains(x.node) && (!next || (x.node.compareDocumentPosition(next) & Node.DOCUMENT_POSITION_FOLLOWING))); return { h: h.textContent.trim().slice(0, 60), hw: wc(h.textContent), words: sum(inside) }; });
  const paras = [...document.querySelectorAll("p, li")].filter(visible).slice(0, 80).map((p) => {
    const tops = new Map(); const tw = document.createTreeWalker(p, NodeFilter.SHOW_TEXT);
    for (let n = tw.nextNode(); n; n = tw.nextNode()) { const re = /\S+/g; let m; while ((m = re.exec(n.textContent))) { const rg = document.createRange(); rg.setStart(n, m.index); rg.setEnd(n, m.index + m[0].length); const rr = rg.getClientRects()[0]; if (!rr) continue; const k = Math.round(rr.top); tops.set(k, (tops.get(k) || 0) + m[0].length + 1); } }
    const cs = getComputedStyle(p), fs = parseFloat(cs.fontSize), lh = cs.lineHeight === "normal" ? 1.2 * fs : parseFloat(cs.lineHeight);
    const lens = [...tops.values()].map((v) => v - 1);
    return { tag: p.tagName.toLowerCase(), text: p.textContent.replace(/\s+/g, " ").trim().slice(0, 50), chars: p.textContent.trim().length, lines: lens.length, longest: Math.max(0, ...lens), lh: lh / fs, fs, align: cs.textAlign, dir: cs.direction, ls: cs.letterSpacing, cjk: /[぀-ヿ一-鿿가-힯]/.test(p.textContent) };
  });
  const sizeOf = (sel) => [...document.querySelectorAll(sel)].filter(visible).map((el) => ({ tag: el.tagName.toLowerCase(), fs: parseFloat(getComputedStyle(el).fontSize), t: (el.textContent || el.value || el.placeholder || "").trim().slice(0, 30) }));
  const firstBlocks = [...document.querySelectorAll("body *")].filter((el) => { const r = el.getBoundingClientRect(); if (!r.width || r.top >= H || r.bottom <= 0 || !visible(el)) return false; const cs = getComputedStyle(el);
    return (cs.backgroundColor !== "rgba(0, 0, 0, 0)" && cs.backgroundColor !== "transparent") || parseFloat(cs.borderTopWidth) > 0 || el.tagName === "IMG" || el.tagName === "svg" || cs.backgroundImage !== "none"; }).length;
  const meta = document.querySelector('meta[name="viewport"]');
  const bgOf = (el) => { for (let e = el; e; e = e.parentElement) { const c = getComputedStyle(e).backgroundColor; if (c && c !== "rgba(0, 0, 0, 0)" && c !== "transparent") return c; } return "rgb(255, 255, 255)"; };
  return {
    H, W, url: location.href, scrollW: de.scrollWidth, clientW: de.clientWidth, scrollH: de.scrollHeight,
    blocks: (() => { const m = new Map(); for (const x of own) { const b = x.el.closest("p, li, td, th, h1, h2, h3, h4, h5, h6, label, button, summary, dt, dd, figcaption, a, option, legend") || x.el; m.set(b, (m.has(b) ? m.get(b) + " " : "") + x.t); } return [...m.values()]; })(),
    words: sum(own), wordsFirst: sum(own.filter((x) => x.top < H)), wordsBelow: sum(own.filter((x) => x.top >= H)),
    wordsAboveInput: ib ? sum(own.filter((x) => x.bottom <= ib.top)) : null, wordsBeforeMainDom: dmain ? sum(before(dmain)) : ta ? sum(before(ta)) : null,
    wordsBeforeGo: goEl ? sum(before(goEl)) : null, text: own.map((x) => x.t).join(" "), firstText: own.filter((x) => x.top < H).map((x) => x.t).join(" "),
    dmain: box(dmain), prim: box(prims[0] || null), primCount: prims.length, primaryStyled: controls.filter((c) => c.primary).length,
    input: box(input), inputTag: input ? input.tagName.toLowerCase() + (input.id ? "#" + input.id : "") : null, ta: box(ta),
    go: box(goEl), goName: goEl ? (goEl.textContent || "").trim().slice(0, 30) : null, goIcon: !!(goEl && goEl.querySelector("svg, img")),
    h1: [...document.querySelectorAll("h1")].filter(visible).map((h) => ({ t: h.textContent.replace(/\s+/g, " ").trim(), ...box(h) })),
    heads: heads.map((h) => h.textContent.replace(/\s+/g, " ").trim()), buttons: [...document.querySelectorAll("button, [role=button]")].filter(visible).map((b) => (b.textContent || "").replace(/\s+/g, " ").trim()),
    controls, lists, sections, paras,
    sizes: sizeOf("p, li, label, textarea, input:not([type=hidden]), button, select"), minText: Math.min(...own.map((x) => x.fs)), smallTexts: own.filter((x) => x.fs < 12).map((x) => x.t.slice(0, 30)).slice(0, 5),
    firstBlocks, viewport: meta ? meta.getAttribute("content") : null, lang: de.getAttribute("lang"), dir: de.getAttribute("dir") || getComputedStyle(de).direction, cdir: getComputedStyle(de).direction,
    bodyBg: bgOf(document.body), broken: [...document.images].filter((i) => i.complete && i.naturalWidth === 0).map((i) => i.src.slice(-40)),
    checked: [...document.querySelectorAll("input[type=checkbox]:checked, input[type=radio]:checked, [aria-checked=true], [aria-pressed=true]")].map((e) => e.id || e.name || e.outerHTML.slice(0, 60))
      .concat([...document.querySelectorAll("select")].filter((s) => s.selectedIndex >= 0 && s.options[s.selectedIndex] && s.options[s.selectedIndex].value !== "" && !s.options[s.selectedIndex].disabled).map((s) => (s.id || s.name || "select") + "=" + s.value)),
    clipped: [...document.querySelectorAll("body *")].filter((el) => { if (!visible(el) || !el.textContent.trim() || el.tagName === "TEXTAREA") return false; const cs = getComputedStyle(el); const bb = el.getBoundingClientRect(); if (bb.width <= 1 || bb.height <= 1 || (cs.clip && cs.clip !== "auto") || /inset\(50%\)/.test(cs.clipPath)) return false; const hid = (v) => v === "hidden" || v === "clip";
      return (hid(cs.overflowX) && el.scrollWidth > el.clientWidth + 1) || (hid(cs.overflowY) && el.scrollHeight > el.clientHeight + 1) || (cs.textOverflow === "ellipsis" && el.scrollWidth > el.clientWidth + 1); }).map((el) => el.tagName.toLowerCase() + (el.id ? "#" + el.id : "")).slice(0, 6),
    sticks: [...document.querySelectorAll("body *")].filter((el) => { const r = el.getBoundingClientRect(); return visible(el) && (r.right > W + 1 || r.left < -1) && getComputedStyle(el).position !== "fixed"; }).map((el) => el.tagName.toLowerCase() + (el.id ? "#" + el.id : el.className ? "." + String(el.className).split(" ")[0] : "")).slice(0, 6),
    marked: Object.fromEntries(["data-main-action", "data-primary", "data-starter", "data-next-step", "data-followup", "data-verdict", "data-answer", "data-evidence", "data-status", "data-state", "data-must-understand", "data-language-switcher", "data-voice-input", "data-voice-output", "data-audio", "data-recap", "data-options", "data-mirror", "data-no-mirror", "data-proof", "data-ai-notice", "data-uncertain", "data-reason", "data-quote", "data-claim", "data-correction", "data-destructive", "data-alt-for", "data-user-content"].map((a) => [a, document.querySelectorAll(`[${a}]`).length])),
    contrastBg: bgOf(input || document.body),
  };
};

// the tool's own-file form: "Check my data" once on the sample, then "Use my data" (the result screen has that button already)
export const OWN_TABLE = "cycle,reading\n1,3.2\n2,3.1\n3,2.9\n4,2.7";
export const settled = (p) => p.waitForFunction(() => document.getElementById("out") && document.getElementById("out").dataset.state !== "working", null, { timeout: 15000 }).catch(() => {});
export const isResult = (p) => p.waitForFunction(() => [...document.querySelectorAll("#out .big, #out p")].some((e) => /^(Failed at row |Passed: all )/.test(e.textContent.trim())), null, { timeout: 15000 }).then(() => true).catch(() => false);
export async function ownForm(p, screen) {
  if (screen === "tool") { await p.click("#go"); await isResult(p); }
  await p.click("button:has-text('Use my data')", { timeout: 5000 });
}
// own-file runs until the free runs of the day are used up and the pay screen shows; true when it shows
export async function toPay(p) {
  await p.evaluate(() => { try { localStorage.setItem("knos-count", "yes"); localStorage.setItem("knos-browser", Array.from(crypto.getRandomValues(new Uint8Array(12)), (x) => x.toString(16).padStart(2, "0")).join("")); } catch { /* none */ } });
  for (let i = 0; i < 12; i++) {
    if (await p.evaluate(() => !document.getElementById("pay").hidden)) return true;
    if (!(await p.evaluate(() => !!document.querySelector("#own") && !document.querySelector("#own").hidden))) await p.click("button:has-text('Use my data')", { timeout: 3000 }).catch(() => {});
    await p.fill("#list", OWN_TABLE + "\n" + (5 + i) + ",2.5"); await p.waitForTimeout(50); await p.selectOption("#col", "reading").catch(() => {}); await p.fill("#limit", "2");
    await p.click("#go", { timeout: 5000 }).catch(() => {}); await settled(p); await p.waitForTimeout(100);
  }
  return p.evaluate(() => !document.getElementById("pay").hidden);
}
