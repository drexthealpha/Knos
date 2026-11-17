// node tests/web/launch.mjs <site dir>
// What a stranger meets on launch day when something is missing, on a build of web/ served as GitHub Pages serves it
// (under /Knos/, and any address the site does not have answered with 404.html and the status 404):
//   404        a missing address, however deep, gets the site's own page: the product's one header, the front door as its
//              one button, the vision line labelled as the goal, the claims and the prices
//   privacy    the privacy and terms page draws, and no page sets a cookie
//   data       when stats.json does not load, the pages that read it say so in one line with a Reload button; when no
//              data file loads, every page that reads one says so, and no page is blank or shows a stack; once the
//              file loads again, Reload brings the page back without the line
// Nothing outside the site is asked but GitHub's API and devnet, which the pages read by design: every request outside is
// refused, and one to any other host fails the run.
// No `playwright` package or no browser: a failure in CI, a skip elsewhere (tests/web/overflow.mjs, `owed`).
import { createServer } from "node:http";
import { readFileSync, existsSync, statSync } from "node:fs";
import { join, extname } from "node:path";
import { chromiumOrSkip, measure, PAGES, addedPages, TYPES } from "./overflow.mjs";

const root = process.argv[2];
if (!root || !existsSync(join(root, "index.html"))) { console.error("usage: node tests/web/launch.mjs <site dir>"); process.exit(2); }
let fails = 0;
const check = (name, cond, detail) => { if (cond) console.log("ok  ", name); else { fails++; console.error("FAIL", name, detail === undefined ? "" : JSON.stringify(detail)); } };
const STACK = /\bat \S+ \(\S+:\d+:\d+\)|\.m?js:\d+|TypeError|ReferenceError|SyntaxError|\[object Object\]|\bundefined\b|\bNaN\b/;
const WORD = /[A-Za-z0-9][\w'’%.,/#-]*/g;

const browser = await chromiumOrSkip();
const PREFIX = "/Knos/";
const server = createServer((req, res) => {
  const path = decodeURIComponent(new URL(req.url, "http://x").pathname);
  const file = path.startsWith(PREFIX) ? join(root, path.slice(PREFIX.length) || "index.html") : null;
  const hit = file && file.startsWith(root) && existsSync(file) && statSync(file).isFile() ? file : null;
  if (!hit) { res.writeHead(404, { "content-type": "text/html" }); return res.end(readFileSync(join(root, "404.html"))); }   // as Pages does
  res.writeHead(200, { "content-type": TYPES[extname(hit)] || "application/octet-stream" }); res.end(readFileSync(hit));
});
await new Promise((r) => server.listen(0, "127.0.0.1", r));
const origin = `http://127.0.0.1:${server.address().port}`, base = origin + PREFIX;
// and what the product pages read by design: the hosted server's NEAR answers and the visit events, NEAR testnet's public
// RPCs, the uptime log on the gh-pages branch
const PRODUCT = /^https:\/\/knos\.onrender\.com\/api\/(near\/[\w/]+|visits?|tools|run|pay)$|^https:\/\/(rpc\.testnet\.fastnear\.com|rpc\.testnet\.near\.org)\/?$|^https:\/\/raw\.githubusercontent\.com\/drexthealpha\/Knos\/gh-pages\/uptime\.jsonl$/;
const outside = [];
const ASKED = /^https:\/\/(api\.github\.com|api\.devnet\.solana\.com|devnet\.rpcpool\.com)\/|^https:\/\/knos\.onrender\.com\/api\/(front|proof|vectors|counter|qloo\/status)$/;     // what the pages read by design, refused here: GitHub, devnet (and its second free RPC, web/netfacts.js, once the first is refused), and the app's list of research products (web/home.js, on a reader's first move at the bare address)
// block: a test of the request's path inside the site; a request it matches fails as a dropped connection would
const world = async (block = () => false, o = {}) => {
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 }, ...o });
  await ctx.route("**/*", (route) => {
    const url = route.request().url();
    if (!url.startsWith(origin)) { if (!ASKED.test(url) && !PRODUCT.test(url.split("?")[0])) outside.push(url); return route.abort(); }
    return block(url.slice(base.length).split("?")[0]) ? route.abort("connectionfailed") : route.continue();
  });
  return ctx;
};

// ---- 404 -----------------------------------------------------------------------------------------------------------------------
{
  const ctx = await world();
  for (const [width, height] of [[320, 640], [390, 844], [1280, 800]]) {
    const page = await ctx.newPage();
    await page.setViewportSize({ width, height });
    const answer = await page.goto(base + "no/such/page/at/all", { waitUntil: "load" });
    check(`404: a missing address answers 404 at ${width}`, answer.status() === 404, answer.status());
    const seen = await page.evaluate(() => ({
      h1: document.querySelector("h1")?.textContent.trim(),
      nav: [...document.querySelectorAll("#kh nav a")].map((a) => a.textContent.trim()),
      logo: document.querySelector("#kh .logo")?.href,
      go: document.querySelector("main a.go")?.href, goal: document.querySelector("main .goal")?.textContent.trim(),
      links: [...document.querySelectorAll("#lost-links a")].map((a) => [a.textContent.trim(), a.href]), mainLinks: document.querySelectorAll("main a").length,
      words: [...document.querySelectorAll("h1, li, footer span")].map((e) => e.textContent.trim()),
      goTop: document.querySelector("main a.go")?.getBoundingClientRect().bottom,
    }));
    check(`404: the product's one header at ${width}`, seen.logo === base && seen.nav.join("|") === "Claims|Papers|Builders|Labs|Code checker", seen);
    check(`404: says the page is missing and offers the front door first at ${width}`, seen.h1 === "No page lives here" && seen.go === base && seen.goTop <= height, seen);
    check(`404: the vision line is labelled as the goal at ${width}`, /^The goal: /.test(seen.goal || ""), seen.goal);
    check(`404: one control back to the front door, no other link in the page (R13 WALK 1) at ${width}`, seen.links.length === 0 && seen.mainLinks === 1, seen);
    const long = seen.words.filter((t) => (t.match(WORD) || []).length > 12);
    check(`404: no statement over 12 words at ${width}`, long.length === 0, long);
    const over = await measure(page);
    check(`404: no sideways scroll at ${width}`, over.over <= 0, over);
    await page.close();
  }
  await ctx.close();
}

// ---- privacy and terms; no cookie anywhere ------------------------------------------------------------------------------------
// the published build (scripts/site_pages.py: the front door at the root, the privacy page written by site_product.py) or
// the earlier one-page app at the root (KNOS_SPA_AT_ROOT=1, its own privacy page of short <li> lines and its # pages)
const SPA = /src="front\.js"/.test(readFileSync(join(root, "index.html"), "utf-8"));
{
  const ctx = await world(), page = await ctx.newPage();
  const answer = await page.goto(base + "privacy.html", { waitUntil: "load" });
  if (SPA) {
    const lines = await page.evaluate(() => [...document.querySelectorAll("main li")].map((li) => li.textContent.trim()));
    check("privacy: the page draws, every line a short statement", answer.status() === 200 && lines.length >= 10 && lines.every((t) => (t.match(WORD) || []).length <= 12), lines);
  } else {
    const seen = await page.evaluate(() => ({ h1: document.querySelector("h1")?.textContent.trim(), h2: [...document.querySelectorAll("main h2")].map((h) => h.textContent.trim()) }));
    check("privacy: the page draws, with its three parts", answer.status() === 200 && seen.h1 === "Privacy and terms" && seen.h2.join("|") === "This site|The server|Terms", seen);
  }
  for (const where of SPA ? ["", "#pricing", "#fund", "#records"] : ["", "claims/", "pricing/", "status/"]) { await page.goto(base + where, { waitUntil: "load" }); await page.waitForTimeout(300); }
  check("privacy: no page sets a cookie", (await ctx.cookies()).length === 0 && (await page.evaluate(() => document.cookie)) === "", await ctx.cookies());
  await ctx.close();
}

if (SPA) {
// ---- a data file that does not load ---------------------------------------------------------------------------------------------
const pages = [...PAGES, ...addedPages(root).map((n) => `#${n}`)];
const look = async (ctx, hash) => {
  const page = await ctx.newPage(), asked = new Set(), errors = [];
  page.on("request", (r) => { const u = r.url(); if (u.startsWith(base) && /\.json(\?|$)/.test(u)) asked.add(u.slice(base.length).split("?")[0]); });
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto(base + hash, { waitUntil: "load" });
  await page.waitForSelector("#theme:not([hidden])");
  await page.waitForTimeout(900);                                 // the reads a page makes when it is opened have failed by now
  const seen = await page.evaluate(() => {
    const shown = [...document.querySelectorAll("main > section")].filter((s) => !s.hidden && s.offsetParent !== null);
    const line = document.querySelector("#k-retry");
    return { text: shown.map((s) => s.innerText).join("\n"), line: line?.checkVisibility() ? line.querySelector("span").textContent.trim() : null,
      button: !!document.querySelector("#k-retry button") };
  });
  return { page, asked, errors, ...seen };
};

{
  const ctx = await world((path) => path === "stats.json");
  const said = [];
  for (const hash of ["#fund", "#network", "#status"]) {
    const v = await look(ctx, hash);
    said.push([hash, v.line]);
    check(`data: ${hash} reads stats.json and, when it does not load, says so in one line with a Reload button`,
      v.asked.has("stats.json") && v.line === "Try again: stats.json did not load." && v.button, { asked: [...v.asked], line: v.line });
    check(`data: ${hash} is not blank and shows no stack`, v.text.trim().length > 40 && !STACK.test(v.text), v.text.slice(0, 200));
    await v.page.close();
  }
  await ctx.close();
}

{
  const ctx = await world((path) => path.endsWith(".json"));
  const bad = [], errors = [];
  for (const hash of pages) {
    const v = await look(ctx, hash);
    if (v.errors.length) errors.push([hash, v.errors]);
    if (!v.text.trim().length) bad.push([hash, "blank"]);
    else if (STACK.test(v.text)) bad.push([hash, v.text.match(STACK)[0]]);
    else if (v.asked.size && !(v.line && /^Try again: .+ did not load\./.test(v.line) && v.button)) bad.push([hash, "no retry line", [...v.asked]]);
    await v.page.close();
  }
  check(`data: with no data file loading, each of ${pages.length} pages says so in one line, none blank, none with a stack`, bad.length === 0, bad);
  if (errors.length) console.log(`note: errors a page threw (not shown on the page): ${JSON.stringify(errors)}`);
  await ctx.close();
}

{
  let down = true;
  const ctx = await world((path) => down && path === "stats.json");
  const v = await look(ctx, "#network");
  check("data: the line is there while stats.json does not load", !!v.line);
  down = false;
  await Promise.all([v.page.waitForEvent("load"), v.page.click("#k-retry button")]);
  await v.page.waitForSelector("#theme:not([hidden])"); await v.page.waitForTimeout(600);
  check("data: Reload, once the file loads, brings the page back without the line", (await v.page.$("#k-retry")) === null && v.page.url().endsWith("#network"));
  await ctx.close();
}

} else console.log("note: the data-file checks drive the one-page app's # pages; this build has the product pages at the root");

check("nothing outside the site was asked", outside.length === 0, [...new Set(outside)].slice(0, 5));
await browser.close(); server.close();
if (fails) { console.error(`${fails} failed`); process.exit(1); }
console.log("launch: all passed");
