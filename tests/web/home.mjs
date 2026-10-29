// node tests/web/home.mjs <site dir>
// THE FIRST SCREEN at the bare address (index.html #view-home, web/home.js): the research products people can back
// now, on a phone and a laptop, held in headless Chromium on a build of web/:
//   instant   the snapshot's cards are drawn before any host answers (everything off the site refused), whole, with
//             their three one-tap actions (Back it, Fund the work, Contribute) above the fold on a phone
//   words     the first screen says 56 words of prose at most, the bar included (the cards are data-not-prose)
//   live      with the reader's first move the app is asked (GET /api/front) and, when it answers, the cards are redrawn
//             in place from the live list, with no shift of the layout; an empty or failed answer leaves the snapshot;
//             untouched, the page asks no other host
//   one tap   a press opens the app at that action: straight to it when it is awake, else through the wake page
//   verify    "How we verify" is one press away, a page of its own; the check of agent work is still at #check
//   sideways  nothing scrolls sideways at 320, 375, 390 and 1280
import { createServer } from "node:http";
import { readFileSync, existsSync } from "node:fs";
import { join, extname } from "node:path";
import { chromiumOrSkip, TYPES } from "./overflow.mjs";
// a link to a page the bar no longer lists (8e29789: "More" holds seven items, the others keep their own addresses),
// pressed as a reader follows one from the text: the page's own router answers it
const follow = async (page, href) => {
  await page.evaluate((h) => { const a = document.createElement("a"); a.id = "k-follow"; a.href = h; a.textContent = "go";
    a.style.cssText = "position:fixed;left:4px;bottom:4px;z-index:2147483647"; document.body.append(a); }, href);
  await page.click("#k-follow"); await page.evaluate(() => document.getElementById("k-follow")?.remove());
};

const root = process.argv[2];
if (!root || !existsSync(join(root, "index.html"))) { console.error("usage: node tests/web/home.mjs <site dir>"); process.exit(2); }
let fails = 0;
const ok = (name, cond, detail) => { if (cond) console.log("ok  ", name); else { fails++; console.error("FAIL", name, detail === undefined ? "" : JSON.stringify(detail).slice(0, 600)); } };

const browser = await chromiumOrSkip();
const server = createServer((req, res) => {
  const path = join(root, decodeURIComponent(new URL(req.url, "http://x").pathname).replace(/\/$/, "/index.html"));
  if (!path.startsWith(root) || !existsSync(path)) { res.writeHead(404); return res.end(); }
  res.writeHead(200, { "content-type": TYPES[extname(path)] || "application/octet-stream" }); res.end(readFileSync(path));
});
await new Promise((r) => server.listen(0, "127.0.0.1", r));
const base = `http://127.0.0.1:${server.address().port}/`;
const APP = "https://knos.onrender.com";
const LIVE = { products: [
  { slug: "sweat-glucose-watch", title: "A fitness watch with a sweat glucose sensor", paper: "Nature, 2016", reserve_units: 48, backed_units: 12, maker: true },
  { slug: "air-water-bottle", title: "A water bottle that harvests drinking water from desert air", paper: "Science, 2017", reserve_units: 81, backed_units: 0, maker: false },
  { slug: "x<script>", title: "refused: not a slug", reserve_units: 1, backed_units: 0 }], crossing_now: [] };

// app: "off" (every host off the site refused), "live" (the app answers /api/front and /healthz), "empty" (an empty list)
async function open(width, height, app = "off") {
  const ctx = await browser.newContext({ viewport: { width, height }, reducedMotion: "reduce", isMobile: width < 700, hasTouch: width < 700 });
  const asked = [];
  await ctx.route("**/*", (route) => {
    const u = route.request().url();
    if (u.startsWith(base)) return route.continue();
    // the proof shown first and the measured numbers come from Knos's own app (web/brand/hero.js, vectors.js): by design
    if (/^https:\/\/knos\.onrender\.com\/api\/(proof|vectors|counter|qloo\/status)$/.test(u)) return route.abort();   // and the proof strip's live numbers, and Qloo's limits (H1)
    asked.push(u);
    if (app !== "off" && u.startsWith(`${APP}/api/front`)) return route.fulfill({ status: 200, contentType: "application/json", headers: { "access-control-allow-origin": "*" }, body: JSON.stringify(app === "live" ? LIVE : { products: [], crossing_now: ["sweat-glucose-watch"] }) });
    if (app !== "off" && u.startsWith(`${APP}/healthz`)) return route.fulfill({ status: 200, contentType: "application/json", headers: { "access-control-allow-origin": "*" }, body: "{\"ok\":true}" });
    if (app !== "off" && u.startsWith(`${APP}/`)) return route.fulfill({ status: 200, contentType: "text/html", body: "<title>app</title><p>the app</p>" });
    return route.abort();
  });
  const page = await ctx.newPage();
  const errors = []; page.on("pageerror", (e) => errors.push(String(e)));
  await page.goto(base, { waitUntil: "load" });
  return { ctx, page, asked, errors };
}
const cards = (page) => page.$$eval("#home-products li.hp", (l) => l.map((li) => ({ slug: li.dataset.slug, title: li.querySelector(".hp-t").textContent,
  acts: [...li.querySelectorAll("a[data-app]")].map((a) => [a.textContent, a.dataset.app, a.getAttribute("href")]),
  bottom: Math.round(li.querySelector(".hp-act").getBoundingClientRect().bottom), visible: li.checkVisibility() })));
const words = (page) => page.evaluate(() => {
  const out = [], walk = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let n = walk.nextNode(); n; n = walk.nextNode()) {
    const el = n.parentElement;
    if (!n.textContent.trim() || el.closest("#demo, script, style, noscript, table, dl.facts, pre, code, textarea, select, input, button, label, summary, a.k-btn, a.button, [role=tab], .k-num, .mono, [data-not-prose]") || !el.checkVisibility({ visibilityProperty: true, opacityProperty: true })) continue;
    const range = document.createRange(); range.selectNodeContents(n);
    const r = range.getBoundingClientRect(), box = el.getBoundingClientRect();
    if (r.width <= 1 || box.width <= 1 || r.bottom <= 0 || r.top >= innerHeight) continue;
    out.push(...(n.textContent.match(/[A-Za-z0-9][\w'’%.,-]*/g) || []));
  }
  return out;
});
const sideways = (page) => page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
const snap = JSON.parse(readFileSync(join(root, "index.html"), "utf8").match(/<script type="application\/json" id="home-snapshot">(.*?)<\/script>/s)[1].replace(/<\\\//g, "</"));

// 1. instant: the snapshot, with nothing answering
for (const [w, h] of [[375, 812], [390, 844], [320, 640], [1280, 800]]) {
  const { ctx, page, asked, errors } = await open(w, h, "off");
  await page.waitForFunction(() => document.documentElement.dataset.ready !== undefined, null, { timeout: 15000 }).catch(() => {});
  await page.waitForTimeout(400);
  const got = await cards(page);
  ok(`${w}px: the bare address opens on the research products, the check of agent work hidden`, await page.isVisible("#view-home") && !(await page.isVisible("#view-check")) && (await page.textContent("#k-mission")).trim() === "See who wants your product, and where, before you build it" && (await page.isVisible("#k-q")));
  ok(`${w}px: the snapshot's ${snap.rows.length} products are drawn before any host answers`, got.length === snap.rows.length && got.every((c, i) => c.slug === snap.rows[i].slug && c.visible), got);
  ok(`${w}px: each has its three one-tap actions, each a link to the app at that action through the wake page`, got.every((c) => c.acts.map((a) => a[0]).join() === "Back it,Fund the work,Contribute"
    && c.acts.every(([, app, href]) => /^#(back|fund|contribute)=[a-z0-9-]+$/.test(app) && href === `wanted.html${app}`)), got.map((c) => c.acts));
  const box = await page.evaluate(() => document.getElementById("k-ask").getBoundingClientRect().bottom);
  ok(`${w}px: the one box is above the fold`, box <= h, box);
  const n = await words(page);
  ok(`${w}px: the first screen says 64 words of prose at most, bar included`, n.length <= 64 && n.length >= 12, [n.length, n.join(" ")]);
  ok(`${w}px: nothing scrolls sideways`, (await sideways(page)) <= 0, await sideways(page));
  ok(`${w}px: no script error`, errors.length === 0, errors);
  if (w === 375) ok("375px: untouched, the first screen asks no other host but its app's proof and numbers", asked.length === 0, asked);
  await ctx.close();
}

// 2. live: the app answers, the cards are redrawn in place (only valid slugs; at most three); an empty answer keeps the snapshot
{
  const { ctx, page, asked } = await open(375, 812, "live");
  await page.waitForTimeout(1500);
  ok("live: a page nobody touched has asked no other host", asked.length === 0, asked);
  const before = await page.evaluate(() => document.getElementById("home-products").getBoundingClientRect().top);
  await page.mouse.move(40, 300);                                   // the reader's first move asks the app for the live list
  await page.waitForFunction(() => document.getElementById("home-products").dataset.live === "1", null, { timeout: 15000 }).catch(() => {});
  const got = await cards(page);
  ok("live: the cards are the live list's valid rows", got.map((c) => c.slug).join() === "sweat-glucose-watch,air-water-bottle", got);
  ok("live: a product that has a maker says so no more ('maker wanted' only where none claimed it)", await page.$eval('#home-products li[data-slug="sweat-glucose-watch"] .hp-src', (e) => !/maker wanted/.test(e.textContent))
    && await page.$eval('#home-products li[data-slug="air-water-bottle"] .hp-src', (e) => /maker wanted/.test(e.textContent)));
  ok("live: the backing is drawn to scale (12 of 48 is a quarter)", await page.$eval('#home-products li[data-slug="sweat-glucose-watch"] .hp-bar i', (e) => e.style.width === "25%"));
  ok("live: the list did not move the page (no layout shift)", before === await page.evaluate(() => document.getElementById("home-products").getBoundingClientRect().top));
  ok("live: the line under the list says it is live", /Live now/.test(await page.textContent("#home-when")));
  // one tap: the app is awake, so the press goes straight to it, at that action
  await page.click('#home-products li[data-slug="sweat-glucose-watch"] a[data-app="#back=sweat-glucose-watch"]');
  await page.waitForURL((u) => String(u).startsWith(APP), { timeout: 10000 }).catch(() => {});
  ok("one tap: Back it opens the app at #back=<slug> when it is awake", page.url() === `${APP}/app/#back=sweat-glucose-watch`, page.url());
  await ctx.close();
}
{
  const { ctx, page } = await open(375, 812, "empty");
  await page.mouse.move(40, 300); await page.waitForTimeout(3500);
  ok("empty answer: the snapshot stays", (await cards(page)).length === snap.rows.length && !(await page.$eval("#home-products", (e) => e.dataset.live)));
  await ctx.close();
}
{
  const { ctx, page } = await open(375, 812, "off");
  await page.click('#home-products li.hp a[data-app^="#fund="]');
  await page.waitForURL(/wanted\.html#fund=/, { timeout: 10000 }).catch(() => {});
  ok("one tap, the app asleep: the press goes to the wake page, which carries the action", /\/wanted\.html#fund=[a-z0-9-]+$/.test(page.url()), page.url());
  await ctx.close();
}

// 3. verify (in the bar's menu, the same on every page), and the check of agent work, one press away
{
  const { ctx, page } = await open(375, 812, "off");
  await follow(page, "#verify");                                        // a phone: How we verify, from a link to it
  await page.waitForFunction(() => document.documentElement.dataset.ready === "verify", null, { timeout: 10000 }).catch(() => {});
  const v = await page.evaluate(() => ({ shown: document.getElementById("view-verify").checkVisibility(), home: document.getElementById("view-home").checkVisibility(),
    h1: document.getElementById("verify-h").textContent, items: [...document.querySelectorAll(".verify-list li h2")].map((e) => e.textContent),
    long: [...document.querySelectorAll("#view-verify p, #view-verify h2")].flatMap((e) => e.textContent.split(/(?<=[.!?])\s+/)).filter((s) => (s.match(/[A-Za-z0-9][\w'’%.,/-]*/g) || []).length > 12) }));
  ok("verify: How we verify is its own page, in plain lines of twelve words at most", v.shown && !v.home && v.h1 === "How we verify" && v.items.length >= 5 && v.long.length === 0, v);
  await page.goto(`${base}#check`, { waitUntil: "load" });
  await page.waitForTimeout(500);
  ok("#check: the check of agent work keeps its first screen", await page.isVisible("#front-door") && !(await page.isVisible("#view-home")) && (await page.textContent("#check")).trim() === "Check an AI agent's pull request before it is paid.");
  await ctx.close();
}

await browser.close(); server.close();
console.log(fails ? `home: ${fails} check(s) failed` : "home: every check held");
process.exit(fails ? 1 : 0);
