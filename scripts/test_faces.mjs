// The browser gates of the three faces (the front door web/, the NEAR app near/web/ and its story, the IRIS page
// iris/web/dashboard.html), as a stranger meets them: a fresh browser context per page, no storage.
//
//   node scripts/test_faces.mjs <base URL of the site, ending in /> <out dir> [the IRIS page's URL]
//
// Per page, at 390 and 1280 px: a screenshot; the words visible before scrolling (first screens: headline, subheadline
// and buttons at most 20 words; every screen at most 40 visible words); the header's visible items (at most 6); no
// paragraph longer than 2 lines at 390 px; the words a first screen never shows; the nav's labels (the same on every
// face); axe-core in light and dark (0 violations). Then the stranger's tasks of F3 that need no key: T-a what Knos does
// (the first screen's headline), T-b reach the NEAR app, T-d open one proof on chain, each with its clicks and seconds.
// Writes <out>/gates.json, <out>/text_limits.txt and the screenshots; exits 1 when any gate fails.
import fs from "node:fs";
import path from "node:path";
import { chromium } from "playwright";

const [base, out = "gates", irisUrl = ""] = process.argv.slice(2);
if (!base) { console.error("usage: node scripts/test_faces.mjs <base URL/> <out dir>"); process.exit(2); }
fs.mkdirSync(out, { recursive: true });
const AXE = fs.readFileSync(path.join("node_modules", "axe-core", "axe.min.js"), "utf8");
const PAGES = [
  { name: "home", url: "", first: true },
  { name: "near", url: "near/", first: true },
  { name: "near-story", url: "near/story/" },
  { name: "iris", url: "iris/", abs: irisUrl },
];
const NAV = ["Home", "NEAR app", "IRIS", "Proof"];
const BANNED = ["valley", "devnet", "solana", "kardashev", "idt", "sibyl", "record line", "n/a", "escrow", "hash", "json"];
const FACE_BANNED = ["n/a", "IDT", "record line"];
const fails = [];
const result = { base, pages: {}, tasks: {} };
const fail = (what) => { fails.push(what); console.log("FAIL", what); };

const browser = await chromium.launch();

async function fresh(width, scheme = "light") {
  const ctx = await browser.newContext({ viewport: { width, height: width < 700 ? 844 : 800 }, colorScheme: scheme, reducedMotion: "no-preference" });
  const page = await ctx.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  return { ctx, page, errors };
}

// what a reader sees before scrolling: the text of visible leaf blocks inside the viewport
const SEEN = () => {
  const vw = innerWidth, vh = innerHeight, words = (t) => (t.match(/[\p{L}\p{N}][\p{L}\p{N}'’.,%$-]*/gu) || []).length;
  const visible = (el) => { const s = getComputedStyle(el); if (s.visibility === "hidden" || s.display === "none" || +s.opacity === 0) return false;
    const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0 && r.bottom > 0 && r.top < vh && r.right > 0 && r.left < vw; };
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  let total = 0; const seen = [];
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    const t = n.textContent.trim(); if (!t) continue;
    const el = n.parentElement; if (!el || el.closest("script,style,noscript,[aria-hidden=true],.k-sr,.sr-only,.visually-hidden")) continue;
    const range = document.createRange(); range.selectNodeContents(n);
    const r = range.getBoundingClientRect(); if (!(r.width > 0 && r.bottom > 0 && r.top < vh && r.left < vw)) continue;
    if (!visible(el)) continue;
    total += words(t); seen.push(t);
  }
  const h1 = document.querySelector("h1"), sub = h1 && (h1.nextElementSibling?.tagName === "P" ? h1.nextElementSibling : null);
  const buttons = [...document.querySelectorAll("main button, main a.k-btn, main [role=button], main input[type=submit]")].filter(visible);
  const lead = (h1 && visible(h1) ? words(h1.innerText) : 0) + (sub && visible(sub) ? words(sub.innerText) : 0) + buttons.reduce((a, b) => a + words(b.innerText || b.value || ""), 0);
  const header = document.querySelector("header");
  const items = header ? [...header.querySelectorAll("a, button, select, input")].filter(visible).length : 0;
  const nav = [...document.querySelectorAll("header nav a, nav[aria-label=Knos] a")].map((a) => a.textContent.trim()).filter(Boolean);
  const long = [...document.querySelectorAll("main p")].filter(visible).filter((p) => {
    const lh = parseFloat(getComputedStyle(p).lineHeight) || 24; return p.getBoundingClientRect().height > lh * 2 + 2; }).map((p) => p.innerText.slice(0, 60));
  return { total, lead, items, nav, long, text: seen.join(" ") };
};

for (const p of PAGES) {
  const at = p.abs || base + p.url;
  const rec = (result.pages[p.name] = { url: at });
  for (const width of [390, 1280]) {
    const { ctx, page, errors } = await fresh(width);
    const r = await page.goto(at, { waitUntil: "networkidle", timeout: 60000 }).catch((e) => ({ status: () => String(e) }));
    await page.waitForTimeout(800);
    const s = await page.evaluate(SEEN);
    await page.screenshot({ path: path.join(out, `${p.name}-${width}.png`) });
    const full = (await page.evaluate(() => document.body.innerText)).toLowerCase();
    rec[width] = { status: r.status(), words_seen: s.total, lead_words: s.lead, header_items: s.items, nav: s.nav, long_paragraphs: s.long, errors, seen: s.text.slice(0, 1200) };
    if (r.status() !== 200) fail(`${p.name} ${width}: HTTP ${r.status()}`);
    if (p.first && s.lead > 20) fail(`${p.name} ${width}: headline, subheadline and buttons are ${s.lead} words (at most 20)`);
    if (s.total > 40) fail(`${p.name} ${width}: ${s.total} words visible before scrolling (at most 40)`);
    if (s.items > 6) fail(`${p.name} ${width}: ${s.items} items in the header (at most 6)`);
    if (width === 390 && s.long.length) fail(`${p.name} 390: ${s.long.length} paragraphs over 2 lines: ${s.long.slice(0, 2).join(" | ")}`);
    if (p.first) for (const w of BANNED) if (new RegExp(`(^|[^a-z])${w.replace("/", "\\/")}([^a-z]|$)`).test(s.text.toLowerCase())) fail(`${p.name} ${width}: the first screen shows "${w}"`);
    for (const w of FACE_BANNED) if (full.includes(w.toLowerCase())) fail(`${p.name} ${width}: the page says "${w}"`);
    if (width === 1280 && JSON.stringify(s.nav) !== JSON.stringify(NAV)) fail(`${p.name}: nav is ${JSON.stringify(s.nav)}, not ${JSON.stringify(NAV)}`);
    if (errors.length) fail(`${p.name} ${width}: page errors ${errors.slice(0, 2).join(" | ")}`);
    await ctx.close();
    for (const scheme of ["light", "dark"]) {
      const a = await fresh(width, scheme);
      await a.page.goto(at, { waitUntil: "networkidle", timeout: 60000 }).catch(() => {});
      await a.page.addScriptTag({ content: AXE });
      const v = await a.page.evaluate(async () => (await window.axe.run(document, { resultTypes: ["violations"] })).violations.map((x) => `${x.id} (${x.nodes.length})`));
      rec[width][`axe_${scheme}`] = v;
      if (v.length) fail(`${p.name} ${width} ${scheme}: axe ${v.join(", ")}`);
      await a.ctx.close();
    }
  }
}

// F3: the stranger's tasks, from the front door, clicks and seconds; the first click must be the right one
async function task(name, width, steps) {
  const { ctx, page } = await fresh(width);
  const t0 = Date.now(); let clicks = 0, ok = false, note = "";
  try {
    await page.goto(base, { waitUntil: "domcontentloaded", timeout: 60000 });
    ok = await steps(page, () => clicks++);
  } catch (e) { note = String(e).slice(0, 160); }
  const secs = Math.round((Date.now() - t0) / 100) / 10;
  await page.screenshot({ path: path.join(out, `task-${name}-${width}.png`) }).catch(() => {});
  result.tasks[`${name}-${width}`] = { ok, clicks, seconds: secs, url: page.url(), note };
  if (!ok || clicks > 3 || secs > 60) fail(`task ${name} ${width}: done ${ok}, ${clicks} clicks, ${secs} s ${note}`);
  await ctx.close();
}
const navClick = async (page, label, count) => {
  const link = page.locator("header nav a", { hasText: label }).first();
  if (!(await link.isVisible())) { await page.locator("#menu").click(); count(); }
  await link.click(); count();
};
for (const width of [390, 1280]) {
  await task("a-what-knos-does", width, async (page) => {
    const h1 = page.locator("h1").first();
    await h1.waitFor({ timeout: 15000 });
    const box = await h1.boundingBox();
    result.tasks.headline = (await h1.innerText()).trim();
    return !!box && box.y < (width < 700 ? 844 : 800);
  });
  await task("b-reach-near-app", width, async (page, count) => {
    await navClick(page, "NEAR app", count);
    await page.waitForLoadState("domcontentloaded");
    return /\/near\/?$/.test(new URL(page.url()).pathname);
  });
  await task("d-open-a-proof-on-chain", width, async (page, count) => {
    await navClick(page, "Proof", count);
    await page.waitForLoadState("domcontentloaded");
    const tx = page.locator('a[href*="explorer"][href*="/tx/"], a[href*="nearblocks"][href*="/txns/"]').first();
    await tx.waitFor({ timeout: 15000 });
    const href = await tx.getAttribute("href");
    result.tasks.proof_link = href;
    count();     // the click on the transaction, followed without leaving the test: the address is what opens
    const r = await page.request.get(href, { timeout: 30000 }).catch(() => null);
    result.tasks.proof_status = r ? r.status() : 0;
    return !!r && (r.status() < 400 || r.status() === 429);   // 429: the explorer is there, and rate limits a runner
  });
}
await browser.close();

const lines = [];
for (const [n, rec] of Object.entries(result.pages))
  for (const w of [390, 1280]) lines.push(`${n} ${w}px: ${rec[w].words_seen} words visible, lead ${rec[w].lead_words}, header items ${rec[w].header_items}, long paragraphs ${rec[w].long_paragraphs.length}`);
fs.writeFileSync(path.join(out, "text_limits.txt"), lines.join("\n") + "\n");
result.fails = fails;
fs.writeFileSync(path.join(out, "gates.json"), JSON.stringify(result, null, 1));
console.log(lines.join("\n"));
console.log(fails.length ? `FAIL gates: ${fails.length}` : "PASS gates: every page and task");
process.exit(fails.length ? 1 : 0);
