// node tests/web/seo.mjs <site dir> [screenshot dir]
// The pages a search engine indexes besides the first screen (web/faq.html, web/check/index.html), on a build of web/
// (scripts/build_site.sh), in headless Chromium. They are held to the site's rules as the app's pages are
// (tests/web/words.mjs, tests/web/overflow.mjs), which measure # routes of index.html and so cannot reach these:
//   words     at 1280 by 800: a title of 3 to 6 words, at most one line between it and the thing itself, 40 words of
//             prose at most on the first screen, no sentence over 12 words (every fold opened), nothing about a wallet,
//             a hash, a pin or a token account, and every fold's handle saying what is inside it
//   width     no sideways scroll at 320, 360, 390, 768 and 1280 px, light and dark, every fold open
//   requests  opened bare, a page asks no host but its own; the check page, opened at #check=acme/app/7, asks
//             api.github.com alone (the recorded answers of tests/data/front_verdict.json) and draws the verdict and
//             its share row, as the first screen's check does
//   stamp     one canonical address, one h1, and "Last updated" with the build's date
// With a screenshot dir, each page is saved at 390 and 1280 px (light; the FAQ with its first question open).
// No `playwright` package or no browser: a failure in CI, a skip elsewhere (tests/web/overflow.mjs chromiumOrSkip).
import { createServer } from "node:http";
import { readFileSync, existsSync, mkdirSync } from "node:fs";
import { join, extname } from "node:path";
import { chromiumOrSkip, TYPES, WIDTHS, measure, answerGitHub } from "./overflow.mjs";

export const STATIC = ["faq.html", "check/"];
const root = process.argv[2], shots = process.argv[3];
if (!root || !existsSync(join(root, "faq.html"))) { console.error("usage: node tests/web/seo.mjs <site dir> [screenshot dir]"); process.exit(2); }
let fails = 0;
const check = (name, cond, detail) => { if (cond) console.log("ok  ", name); else { fails++; console.error("FAIL", name, detail === undefined ? "" : JSON.stringify(detail)); } };

const browser = await chromiumOrSkip();
const server = createServer((req, res) => {
  const path = join(root, decodeURIComponent(new URL(req.url, "http://x").pathname).replace(/\/$/, "/index.html"));
  if (!path.startsWith(root) || !existsSync(path)) { res.writeHead(404); return res.end(); }
  res.writeHead(200, { "content-type": TYPES[extname(path)] || "application/octet-stream" }); res.end(readFileSync(path));
});
await new Promise((r) => server.listen(0, "127.0.0.1", r));
const base = `http://127.0.0.1:${server.address().port}/`;

// a context that refuses every host but the site's own (GitHub answers only where a test asks it to), and lists them
async function context(options, github = false) {
  const ctx = await browser.newContext(options), asked = [];
  await ctx.route("**/*", (route) => {
    const url = route.request().url();
    if (url.startsWith(base)) return route.continue();
    asked.push(new URL(url).host);
    return github ? answerGitHub(route) : route.abort();
  });
  return { ctx, asked };
}

const read = (page) => page.evaluate(() => {
  const WORD = /[A-Za-z0-9][\w'’%.,/-]*/g, words = (t) => (t.match(WORD) || []).filter((w) => /[A-Za-z0-9]/.test(w));
  const section = document.querySelector("main > section");
  const drawn = (el) => el.checkVisibility({ visibilityProperty: true, opacityProperty: true }) && el.getClientRects().length > 0;
  const data = "table, dl.facts, pre, code, textarea, select, input, button, label, summary, a.k-btn, a.button, [role=tab], .k-num, .mono, [data-not-prose]";
  const title = [...section.querySelectorAll("h1, h2")].find(drawn);
  let under = 0, lines = 0;
  for (let el = title?.nextElementSibling; el; el = el.nextElementSibling) {
    if (!drawn(el)) continue;
    if (el.tagName !== "P") break;
    under += 1; lines += Math.round(el.getBoundingClientRect().height / parseFloat(getComputedStyle(el).lineHeight || "24"));
  }
  const first = [], walk = document.createTreeWalker(document.querySelector("main"), NodeFilter.SHOW_TEXT);
  for (let n = walk.nextNode(); n; n = walk.nextNode()) {
    const el = n.parentElement;
    if (!n.textContent.trim() || el.closest(`script, style, noscript, .status, [role=status], [aria-live], ${data}`) || !drawn(el)) continue;
    const range = document.createRange(); range.selectNodeContents(n);
    const r = range.getBoundingClientRect();
    if (r.width <= 1 || r.bottom <= 0 || r.top >= innerHeight) continue;
    first.push(...words(n.textContent));
  }
  // every statement, with every fold opened: the innermost blocks of prose, sentence by sentence
  const shut = [...section.querySelectorAll("details:not([open])")]; shut.forEach((d) => { d.open = true; });
  const BLOCK = "h1, h2, h3, h4, p, li, summary, figcaption, blockquote, dt, dd, label, legend, button, th, td, option, a";
  const long = [], banned = [];
  for (const el of section.querySelectorAll(BLOCK)) {
    if (!drawn(el) || el.closest("table, dl.facts, pre, textarea, select, [data-not-prose]") || [...el.querySelectorAll(BLOCK)].some((c) => c.tagName !== "A" && drawn(c))) continue;
    if (el.tagName === "A" && el.parentElement.closest(BLOCK)) continue;
    const clone = el.cloneNode(true); for (const x of clone.querySelectorAll("pre, code, .mono, details, table, select, input, textarea")) x.remove();
    for (const t of clone.textContent.split(/(?<=[.!?:])\s+|\n{2,}/)) {
      const n = words(t).length;
      if (n > 12) long.push(`${n}: ${t.trim().replace(/\s+/g, " ").slice(0, 140)}`);
      const m = /\b(wallets?|hash(es|ed)?|pin(s|ned)?|token accounts?)\b/i.exec(t); if (m) banned.push(`${m[0]}: ${t.trim().slice(0, 100)}`);
    }
  }
  shut.forEach((d) => { d.open = false; });
  const handles = [...section.querySelectorAll("details > summary")].map((s) => s.textContent.replace(/\s+/g, " ").trim());
  const updated = document.querySelector("#updated time");
  return { title: title ? title.textContent.trim() : "", titleWords: title ? words(title.textContent).length : 0, under, lines, first: first.length, firstSaid: first.join(" "),
    long, banned, handles, h1: document.querySelectorAll("h1").length, canonical: [...document.querySelectorAll('link[rel="canonical"]')].map((l) => l.href),
    updated: updated ? [updated.dateTime, updated.textContent] : null };
});

// words, the stamp, and what the page asks for, at 1280 by 800 as tests/web/words.mjs measures
{
  const { ctx, asked } = await context({ viewport: { width: 1280, height: 800 }, reducedMotion: "reduce" });
  const page = await ctx.newPage();
  for (const name of STATIC) {
    await page.goto(base + name, { waitUntil: "load" });
    if (name === "check/") await page.waitForSelector("#check-form");
    await page.evaluate(() => document.fonts.ready); await page.waitForTimeout(150);
    const got = await read(page);
    check(`${name}: the title is 3 to 6 words`, got.titleWords >= 3 && got.titleWords <= 6, got.title);
    check(`${name}: at most one line under the title, then the thing itself`, got.under <= 1 && got.lines <= 1, [got.under, got.lines]);
    check(`${name}: the first screen says 40 words at most (${got.first})`, got.first <= 40, got.firstSaid);
    check(`${name}: no statement is longer than 12 words, every fold open`, got.long.length === 0, got.long);
    check(`${name}: nothing about a wallet, a hash, a pin or a token account`, got.banned.length === 0, got.banned);
    check(`${name}: every fold's handle says what is inside it`, got.handles.every((h) => h && !/^(more( about this)?|details|read more)$/i.test(h)) && new Set(got.handles).size === got.handles.length, got.handles);
    check(`${name}: one h1 and one canonical address of its own`, got.h1 === 1 && got.canonical.length === 1 && got.canonical[0] === `https://drexthealpha.github.io/Knos/${name}`, got.canonical);
    check(`${name}: "Last updated" says the build's date`, !!got.updated && /^\d{4}-\d{2}-\d{2}$/.test(got.updated[0]) && got.updated[0] === got.updated[1], got.updated);
  }
  check("opened bare, neither page asks any host but the site's own", asked.length === 0, asked);
  await ctx.close();
}

// the check page draws the first screen's check: a verdict, then its share row, reading GitHub alone
{
  const { ctx, asked } = await context({ viewport: { width: 390, height: 800 }, reducedMotion: "reduce" }, true);
  const page = await ctx.newPage();
  await page.goto(`${base}check/#check=acme/app/7`, { waitUntil: "load" });
  const drawn = await page.waitForSelector("#check-share [data-share]", { timeout: 10000 }).then(() => true).catch(() => false);
  const verdict = await page.textContent("#check-verdict").catch(() => "");
  check("check/#check=acme/app/7: a verdict and its share row, as on the first screen", drawn && !!verdict.trim(), verdict);
  check("  and it asked api.github.com alone", asked.length > 0 && asked.every((h) => h === "api.github.com"), [...new Set(asked)]);
  const { over } = await measure(page);
  check("  and the answer does not scroll sideways at 390 px", over <= 1, over);
  if (shots) { mkdirSync(shots, { recursive: true }); await page.screenshot({ path: join(shots, "check-answer-390.png"), fullPage: true }); }
  await ctx.close();
}

// no sideways scroll, every fold open, at every width in both schemes; screenshots at 390 and 1280
for (const scheme of ["light", "dark"]) {
  const { ctx } = await context({ colorScheme: scheme, viewport: { width: 1280, height: 800 } });
  const page = await ctx.newPage();
  for (const width of WIDTHS) {
    await page.setViewportSize({ width, height: 800 });
    for (const name of STATIC) {
      await page.goto("about:blank"); await page.goto(base + name, { waitUntil: "load" });
      await page.evaluate(() => document.fonts.ready); await page.waitForTimeout(100);
      if (shots && scheme === "light" && (width === 390 || width === 1280)) {
        const file = name.replace(/\W+/g, "-").replace(/-$/, "");
        if (name === "faq.html") await page.evaluate(() => { document.querySelector("details").open = true; });
        await page.screenshot({ path: join(shots, `${file}-${width}.png`) });
        await page.screenshot({ path: join(shots, `${file}-${width}-full.png`), fullPage: true });
      }
      await page.evaluate(() => document.querySelectorAll("details").forEach((d) => { d.open = true; }));
      const { over, culprits } = await measure(page);
      check(`${scheme} ${width}px ${name}: no sideways scroll`, over <= 1, culprits);
    }
  }
  await ctx.close();
}
await browser.close(); server.close();
console.log(fails ? `${fails} checks failed` : "seo: every page holds");
process.exit(fails ? 1 : 0);
