// node tests/web/words.mjs <site dir> [--list]
// The word budget, held on every page of a build of web/ in headless Chromium at 1280 by 800:
//   title      a page opens with a heading of 3 to 6 words (8 for the page that names its two readers; the first screen opens with the one sentence instead)
//   under it   at most one line of prose between the heading and the thing itself (a control, a table, a live view)
//   first      what the page says in its first screen, the bar apart (the bar is counted with the site's first screen,
//              tests/web/front_door.mjs): 40 words of prose at most: headings, sentences, list items, links in them.
//              Not counted, because it is the thing itself: a control (a button, a field and its label, the handle of
//              a fold), the cells of a table, code, a figure (.k-num), and the rows of a live view that a module
//              marks data-not-prose (the story's eight steps, a published terms sentence), and an answer the page
//              gives (a status line, a live region): held to twelve words a sentence like everything else
//   statement  no sentence anywhere on the page is longer than 12 words. A fold that is shut (details) is not read
//              until it is opened, and that is where a longer explanation lives; the price book's cells are the
//              price book's own words (SPEC), and a row of data (a table's, a list of facts') is not a sentence
//   record     no page says wallet, hash, pin or token account before the reader asks who keeps the record: those
//              words are for a shut fold, the Records, Verifier and Numbers pages, and the developer's path (Fund, Get
//              paid, Protect, Install, Build), and the part of a page a module marks data-record (the Console's Pay step)
//   folds      every fold a page makes of a longer text (web/front.js foldProse) has a handle that says what is inside
//              it: never "More about this", "More" or nothing, and no one handle repeated over three folds
// --list prints every page's counts. No browser: a failure in CI, a skip elsewhere (tests/web/overflow.mjs).
import { createServer } from "node:http";
import { readFileSync, existsSync } from "node:fs";
import { join, extname } from "node:path";
import { chromiumOrSkip, TYPES, addedPages, answerGitHub, CHECKED } from "./overflow.mjs";

const root = process.argv[2], list = process.argv.includes("--list");
if (!root || !existsSync(join(root, "index.html"))) { console.error("usage: node tests/web/words.mjs <site dir> [--list]"); process.exit(2); }
export const PAGES = ["check", "buy", "index", "pricing", "story", "supplier", "keyholder", "verifier", "playground", "terms", "records", "invoice-statement", "shadow",
  "fund", "claim", "protect", "install", "network", "status", "pilot", "capabilities", "reproduce", "build", "record", CHECKED.slice(1)];
const RECORD_KEEPERS = ["records", "verifier", "network", "fund", "claim", "protect", "install", "build"];
// the front door says more: the outcome, who it is for, the sentence and the number (tests/web/front_door.mjs counts them with the bar)
const FIRST = 40, FIRST_DOOR = 50, STATEMENT = 12;
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
const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 }, reducedMotion: "reduce" });
await ctx.route("**/*", (route) => (route.request().url().startsWith(base) ? route.continue() : answerGitHub(route)));
const page = await ctx.newPage();

for (const name of [...PAGES, ...addedPages(root)]) {
  await page.goto(`${base}?p=${name}#${name}`, { waitUntil: "load" });
  const id = name.split("=")[0];                    // check=acme/app/7: the check of one pull request, on the first screen's view
  await page.waitForFunction((n) => document.documentElement.dataset.ready === n, id);
  if (name !== id) await page.waitForSelector("#check-share [data-share]", { timeout: 10000 });
  // the round under the first screen comes with the reader's first move (web/front.js): its words are counted too
  if (name === "check") { await page.mouse.move(3, 3); await page.waitForSelector("#demo .kd-go"); }
  await page.evaluate(() => document.fonts.ready); await page.waitForTimeout(500);
  const got = await page.evaluate((name) => {
    const WORD = /[A-Za-z0-9][\w'’%.,/-]*/g, words = (t) => (t.match(WORD) || []).filter((w) => /[A-Za-z0-9]/.test(w));
    name = name.split("=")[0];
    const mount = document.getElementById(name);
    const section = name !== "check" && mount && mount.classList.contains("mount") ? mount : document.getElementById(`view-${name}`);
    const drawn = (el) => el.checkVisibility({ visibilityProperty: true, opacityProperty: true }) && el.getClientRects().length > 0;
    const data = "table, dl.facts, pre, code, textarea, select, input, button, label, summary, a.k-btn, a.button, [role=tab], .k-num, .mono, [data-not-prose]";
    // the heading, and what stands between it and the thing itself
    const title = [...section.querySelectorAll("h1, h2")].find(drawn);
    let under = 0, lines = 0;
    for (let el = title?.nextElementSibling; el; el = el.nextElementSibling) {
      if (!drawn(el)) continue;
      if (el.tagName !== "P") break;
      under += 1; lines += Math.round(el.getBoundingClientRect().height / parseFloat(getComputedStyle(el).lineHeight || "24"));
    }
    // the first screen: every text node drawn inside the window, in the page (not the bar)
    const first = [], walk = document.createTreeWalker(document.querySelector("main"), NodeFilter.SHOW_TEXT);
    for (let n = walk.nextNode(); n; n = walk.nextNode()) {
      const el = n.parentElement;
      if (!n.textContent.trim() || el.closest(`script, style, noscript, .status, [role=status], [aria-live], ${data}`) || !drawn(el)) continue;
      const range = document.createRange(); range.selectNodeContents(n);
      const r = range.getBoundingClientRect();
      if (r.width <= 1 || r.bottom <= 0 || r.top >= innerHeight) continue;
      first.push(...words(n.textContent));
    }
    // every statement: the innermost blocks of prose, sentence by sentence
    const BLOCK = "h1, h2, h3, h4, p, li, summary, figcaption, blockquote, dt, dd, label, legend, button, th, td, option, a";
    const long = [], said = [];
    for (const el of section.querySelectorAll(BLOCK)) {
      if (!drawn(el) || el.closest("table, dl.facts, pre, textarea, select, #price-book, [data-not-prose]") || [...el.querySelectorAll(BLOCK)].some((c) => c.tagName !== "A" && drawn(c))) continue;
      if (el.tagName === "A" && el.parentElement.closest(BLOCK)) continue;                     // a link inside a sentence is part of it
      const clone = el.cloneNode(true); for (const x of clone.querySelectorAll("pre, code, .mono, details, table, select, input, textarea")) x.remove();
      const asked = !!el.closest("[data-record]");                                              // where a module says the reader has asked how the money is held (the Console's Pay step)
      for (const t of clone.textContent.split(/(?<=[.!?:])\s+|\n{2,}/)) { const n = words(t).length; if (n && !asked) said.push(t.trim()); if (n > 12) long.push(`${n}: ${t.trim().replace(/\s+/g, " ").slice(0, 140)}`); }
    }
    const banned = [];
    for (const t of said) { const m = /\b(wallets?|hash(es|ed)?|pin(s|ned)?|token accounts?)\b/i.exec(t); if (m) banned.push(`${m[0]}: ${t.replace(/\s+/g, " ").slice(0, 100)}`); }
    // the handle of every fold the page made of a longer text says what is inside it (web/front.js foldLabel), never one word for all
    const handles = [...section.querySelectorAll("details.k-fold > summary")].filter(drawn).map((s) => s.textContent.replace(/\s+/g, " ").trim());
    return { title: title ? title.textContent.trim().replace(/\s+/g, " ") : "", titleWords: title ? words(title.textContent).length : 0, under, lines, first: first.length, firstSaid: first.join(" "), long, banned, handles };
  }, name);
  if (list) console.log(`     ${name}: title ${got.titleWords} "${got.title}", ${got.under} under it (${got.lines} lines), first screen ${got.first}, long ${got.long.length}, record words ${got.banned.length}`);
  // one page names its two readers in its title, "Check every claim yourself (for judges and buyers)": 8 words there
  const titleMost = name === "judges" ? 8 : 6;
  if (id !== "check") check(`${name}: the title is 3 to ${titleMost} words`, got.titleWords >= 3 && got.titleWords <= titleMost, got.title);
  if (id !== "check") check(`${name}: at most one line under the title, then the thing itself`, got.under <= 1 && got.lines <= 1, [got.under, got.lines]);
  const most = id === "check" ? FIRST_DOOR : FIRST;
  check(`${name}: the first screen says ${most} words at most, the bar apart (${got.first})`, got.first <= most, got.firstSaid);
  check(`${name}: no statement is longer than ${STATEMENT} words`, got.long.length === 0, got.long);
  if (!RECORD_KEEPERS.includes(name)) check(`${name}: nothing about a wallet, a hash, a pin or a token account before the reader asks`, got.banned.length === 0, got.banned);
  const vague = got.handles.filter((h) => !h || /^(more( about this)?|details|read more)$/i.test(h) || new Set(got.handles).size < got.handles.length && got.handles.filter((x) => x === h).length > 2);
  check(`${name}: every fold's handle says what is inside it (${got.handles.length} folds)`, vague.length === 0, vague);
  if (list && got.handles.length) console.log(`       folds: ${got.handles.join(" | ")}`);
}
await browser.close(); server.close();
console.log(fails ? `${fails} checks failed` : "words: every page is within the budget");
process.exit(fails ? 1 : 0);
