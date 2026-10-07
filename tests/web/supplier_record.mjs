// The supplier's record page (web/supplier_record.js) and the first screen's strip (web/index_board.js renderBoardStrip).
//   node tests/web/supplier_record.mjs          the strings, with no browser
//   node tests/web/supplier_record.mjs page     the page in headless Chromium, at three widths and under reduced motion
import { readFileSync, existsSync } from "node:fs";
import { join, dirname, extname } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = dirname(fileURLToPath(import.meta.url)), repo = join(here, "../.."), web = join(repo, "web");
const at = (f) => pathToFileURL(join(web, f)).href;
const { boardStripHtml, stripRows, stripWords, STRIP_WORDS, boardOf, weeksOf } = await import(at("index_board.js"));
const { recordBadge, recordBadgeSvg } = await import(at("badge.js"));
const weekly = JSON.parse(readFileSync(join(repo, "docs/agent_weekly.json"), "utf8")), feed = JSON.parse(readFileSync(join(repo, "docs/index.json"), "utf8"));
const record = (slug) => JSON.parse(readFileSync(join(repo, `docs/records/${slug}.json`), "utf8"));

let failed = 0;
const ok = (what, cond, detail) => { if (!cond) failed++; console.log(`${cond ? "ok  " : "FAIL"} ${what}${cond || detail === undefined ? "" : `: ${JSON.stringify(detail)}`}`); };
const words = (t) => t.split(/\s+/).filter((w) => /[\p{L}\p{N}]/u.test(w));

// ---- the strip ----------------------------------------------------------------------------------------------------------
const strip = boardStripHtml({ weekly }), top = boardOf(weekly, weeksOf(weekly)[0]).rows.filter((r) => r.rank != null);
ok(`the strip says under ${STRIP_WORDS} words, labels and figures counted (${stripWords(strip)})`, stripWords(strip) < STRIP_WORDS, stripWords(strip));
ok("the strip is the same from the series and from the feed", strip === boardStripHtml({ feed }));
ok("the strip shows the placed agents by place, four at most", JSON.stringify(stripRows({ weekly }).rows.map((r) => r.agent)) === JSON.stringify(top.slice(0, 4).map((r) => r.agent)));
ok("every row of the strip has its sample beside the bar and its interval on it", top.slice(0, 4).every((r) => strip.includes(`${r.failed_at_merge} of ${r.merged}</span>`) && strip.includes(`left:${(r.ci95[0] * 100).toFixed(1)}%`)));
ok("the strip links to the board and to each agent's record", strip.includes('href="#index">See the board</a>') && top.slice(0, 4).every((r) => strip.includes(`href="#record=${r.agent}"`)));
ok("the strip's bars move only where motion is welcome", /@media \(prefers-reduced-motion: no-preference\)\{[^@]*\.bs-anim/.test(strip) && !/animation:|infinite/.test(strip));
ok("with nothing read the strip draws nothing", boardStripHtml({}) === "" && boardStripHtml({ rows: 2, weekly }).split("<li").length === 3);

// ---- the record's strings -------------------------------------------------------------------------------------------------
const { recordHtml, evidenceRows, slugIn, slugOf, TILES, INSTALL, SCHEMA } = await import(at("supplier_record.js"));
const codex = record("codex");
const SETTLED = { ...codex, supplier: "vendor-x", name: "Vendor X", public: null, orders: { ...codex.orders, sample: 4, period: { from: "2026-07", to: "2026-09", unit: "month" },
  counts: { ...codex.orders.counts,
    accepted: { n: 2, from: "events", evidence: [{ deliverable: "dlv_a1", event: "acc_1", line: 1, line_sha256: "aa", evidence: "tx:sig1", month: 202607, source: "record" }, { deliverable: "dlv_a2", event: "acc_2", line: 3, line_sha256: "bb", evidence: "tx:sig2", month: 202608, source: "record" }] },
    rejected: { n: 1, from: "events", evidence: [{ deliverable: "dlv_a3", event: "evl_3", line: 4, line_sha256: "cc", evidence: "tx:sig3", month: 202608, source: "record" }] },
    overturned: { n: 1, from: "memory", evidence: [{ repository: "acme/app", pull_request: 6, url: "https://github.com/acme/app/pull/6", appeal: "ap1" }] },
    reverted: { n: 1, from: "events", evidence: [{ deliverable: "dlv_a4", event: "acc_4", line: 6, line_sha256: "dd", evidence: "tx:sig4", month: 202609, source: "record", correction: "cor_1", reason: "reverted in warranty" }] } } } };
ok("the address names the record", slugIn("#record=codex") === "codex" && slugIn("#record=Claude%20Code") === "claude-code" && slugIn("#index") === "" && slugOf(" A/b ") === "a-b");
ok("a committed record is this schema", codex.schema === SCHEMA && codex.supplier === "codex");
const html = recordHtml(codex), settled = recordHtml(SETTLED);
ok("six tiles, one per count shown", TILES.length === 6 && TILES.every((k) => html.includes(`data-count="${k}"`)));
ok("the page says the record cannot be bought, offers the dispute and the file", html.includes("This record cannot be bought.") && html.includes(`href="${codex.links.dispute.replace(/&/g, "&amp;")}"`) && html.includes('href="records/codex.json"'));
ok("the public row is labelled as public pull requests and keeps its interval", html.includes("From public pull requests, not Knos orders") && html.includes(`${codex.public.failed_at_merge} of ${codex.public.sample} merged`) && html.includes("sr-whisker"));
ok("a record with no Knos order says so", html.includes("Holds no Knos order yet.") && evidenceRows(codex).length === 0);
ok("every count's evidence is a row", evidenceRows(SETTLED).length === 5 && evidenceRows(SETTLED).filter((r) => r.url).length === 1 && settled.includes("line 6: tx:sig4"));
ok("the page shows the badge the command writes and the one line that installs", html.includes(recordBadgeSvg(codex).trim()) && html.includes(INSTALL) && recordBadge(SETTLED).message === "2 accepted, 1 reverted, sample 4, 2026-07 to 2026-09");
const prose = (h) => h.replace(/<(svg|pre|table|code)[\s\S]*?<\/\1>/g, " ").replace(/<[^>]*>/g, "\n").split(/(?<=[.!?:])\s+|\n+/).map((t) => t.trim()).filter(Boolean);
ok("every statement of the page is twelve words at most", [html, settled].every((h) => prose(h).every((t) => words(t).length <= 12)), [html, settled].flatMap(prose).filter((t) => words(t).length > 12));
ok("nothing about a wallet, a hash, a pin or a token account", ![html, settled].flatMap(prose).some((t) => /\b(wallets?|hash(es|ed)?|pin(s|ned)?|token accounts?)\b/i.test(t)));
ok("the module names no host but GitHub's pages", [...readFileSync(join(web, "supplier_record.js"), "utf8").matchAll(/https:\/\/([A-Za-z0-9.-]+)/g)].every((m) => ["github.com", "raw.githubusercontent.com"].includes(m[1])));

// ---- the page, in headless Chromium ----------------------------------------------------------------------------------------
async function page() {
  const { createServer } = await import("node:http");
  const { chromiumOrSkip, measure, TYPES } = await import("./overflow.mjs");
  const browser = await chromiumOrSkip();
  const HOLDER = `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Record</title>
    <link rel="stylesheet" href="app.css"></head><body><main><div id="strip"></div><div id="record"></div></main>
    <script type="module">import { renderSupplierRecord } from "./supplier_record.js"; import { renderBoardStrip } from "./index_board.js";
      const feed = await (await fetch("agent_index.json")).json(); renderBoardStrip(document.getElementById("strip"), { feed });
      // the page's own clock, not the test's: when the record's file had arrived, when it was drawn, and whether the place said it was
      // waiting (aria-busy) from the first instant and at every change until then. A test process's seconds are the machine's load.
      const el = document.getElementById("record"), paint = window.paint = { said: false, blank: 0, file: null, drawn: null };
      new MutationObserver(() => { if (!el.hasAttribute("aria-busy") && !el.firstElementChild) paint.blank += 1; }).observe(el, { attributes: true, childList: true });
      window.kit = renderSupplierRecord(el); paint.said = el.getAttribute("aria-busy") === "true";
      await window.kit.loaded; paint.drawn = performance.now();
      paint.file = (performance.getEntriesByType("resource").find((e) => new URL(e.name).pathname.startsWith("/records/")) || {}).responseEnd ?? null;
      window.drawn = true;</script></body></html>`;
  const server = createServer((req, res) => {
    const path = decodeURIComponent(new URL(req.url, "http://x").pathname);
    if (path === "/record_page.html") { res.writeHead(200, { "content-type": "text/html" }); return res.end(HOLDER); }
    if (path === "/records/vendor-x.json") { res.writeHead(200, { "content-type": "application/json" }); return res.end(JSON.stringify(SETTLED)); }
    const file = path === "/agent_index.json" ? join(repo, "docs/index.json") : path.startsWith("/records/") ? join(repo, "docs", path) : join(web, path);       // what scripts/build_site.sh puts beside the site
    if (!file.startsWith(repo) || !existsSync(file) || !extname(file)) { res.writeHead(404); return res.end(); }
    res.writeHead(200, { "content-type": TYPES[extname(file)] || "application/octet-stream" }); res.end(readFileSync(file));
  });
  await new Promise((r) => server.listen(0, "127.0.0.1", r));
  const base = `http://127.0.0.1:${server.address().port}/`;
  const tiles = (p) => p.evaluate(() => Object.fromEntries([...document.querySelectorAll(".sr-tile")].map((t) => [t.dataset.count, t.querySelector("strong").textContent])));
  for (const [width, reducedMotion] of [[1280, "no-preference"], [390, "reduce"], [320, "no-preference"]]) {
    const ctx = await browser.newContext({ viewport: { width, height: 800 }, reducedMotion }), strangers = [], errors = [];
    await ctx.route("**/*", (route) => (route.request().url().startsWith(base) ? route.continue() : (strangers.push(route.request().url()), route.abort())));
    const p = await ctx.newPage();
    p.on("pageerror", (e) => errors.push(String(e)));
    await p.goto(`${base}record_page.html#record=vendor-x`);
    await p.waitForFunction(() => window.drawn === true);
    const first = await tiles(p), paint = await p.evaluate(() => window.paint);
    await p.waitForFunction(() => document.querySelector(".sr-tile[data-count=accepted] strong").textContent === "2");
    ok(`${width}px: the tiles end on the record's counts`, JSON.stringify(await tiles(p)) === JSON.stringify({ accepted: "2", rejected: "1", insufficient_evidence: "0", disputed: "0", overturned: "1", reverted: "1" }), await tiles(p));
    if (reducedMotion === "reduce") {
      ok(`${width}px: under reduced motion the counts are there at once and the strip does not move`, first.accepted === "2" && first.reverted === "1" && await p.evaluate(() => !document.querySelector(".board-strip").classList.contains("bs-anim")), first);
    } else if (width === 1280) {
      await p.evaluate(() => { location.hash = "#record=codex"; });
      await p.waitForFunction(() => document.querySelector(".supplier-record")?.dataset.supplier === "codex");
      await p.evaluate(() => { location.hash = "#record=vendor-x"; });
      await p.waitForFunction(() => document.querySelector(".supplier-record")?.dataset.supplier === "vendor-x");
      const seen = await p.evaluate(() => new Promise((done) => { const got = new Set(), el = document.querySelector(".sr-tile[data-count=accepted] strong"); const tick = () => { got.add(el.textContent); if (el.textContent === "2" && got.size > 1 || performance.now() > 4000) return done([...got]); requestAnimationFrame(tick); }; window.kit.show("vendor-x").then(tick); }));
      ok(`${width}px: a tile counts up to its number and ends on it exactly`, seen[seen.length - 1] === "2", seen);
      ok(`${width}px: the strip's bars grow in once`, await p.evaluate(() => document.querySelector(".board-strip").classList.contains("in")));
    }
    ok(`${width}px: the first paint is within 300 ms of the files, or pending is said`, paint.drawn !== null && ((paint.file !== null && paint.drawn - paint.file < 300) || (paint.said && paint.blank === 0)), paint);
    ok(`${width}px: the evidence list has a row for every piece of evidence`, (await p.locator("[data-sr=evidence] tbody tr").count()) === 5);
    ok(`${width}px: the record cannot be bought, and can be disputed`, (await p.innerText("[data-sr=rule]")) === "This record cannot be bought." && (await p.getAttribute("[data-sr=dispute]", "href")).includes("issues/new?template=dispute-index-row.yml"));
    ok(`${width}px: one line of limits`, (await p.locator("[data-sr=limits]").count()) === 1 && (await p.innerText("[data-sr=limits]")).startsWith("Counts with samples, never a score."));
    ok(`${width}px: the settled record does not scroll sideways`, (await measure(p)).over <= 0, await measure(p));
    await p.evaluate(() => { location.hash = "#record=codex"; });
    await p.waitForFunction(() => document.querySelector(".supplier-record")?.dataset.supplier === "codex");
    ok(`${width}px: an agent of the index shows its row with the interval as a whisker`, (await p.innerText("[data-sr=sample]")) === `${codex.public.failed_at_merge} of ${codex.public.sample} merged` && (await p.locator(".sr-whisker").count()) === 1
      && (await p.innerText("[data-sr=ci]")).includes("95% interval"));
    ok(`${width}px: it says no Knos order is on record`, (await p.innerText("[data-sr=orders-sample]")).includes("Holds no Knos order yet."));
    const said = await p.evaluate(() => [...document.querySelectorAll(".supplier-record h2, .supplier-record h3, .supplier-record p, .supplier-record button, .supplier-record a.k-btn, .supplier-record .sr-tile span")]
      .filter((e) => e.offsetParent !== null).flatMap((e) => e.innerText.split(/(?<=[.!?:])\s+|\n+/)).map((t) => t.trim()).filter(Boolean));
    ok(`${width}px: every statement is twelve words at most`, said.every((t) => words(t).length <= 12), said.filter((t) => words(t).length > 12));
    ok(`${width}px: the title is 3 to 6 words`, [3, 4, 5, 6].includes(words(await p.innerText(".supplier-record h2")).length));
    ok(`${width}px: the index's record does not scroll sideways`, (await measure(p)).over <= 0, await measure(p));
    await p.click("[data-sr=copy]");
    await p.waitForFunction(() => document.querySelector("[data-sr=copy]")?.textContent === "Copied" || !!document.querySelector(".supplier-record textarea"));
    ok(`${width}px: the badge's Markdown is copied, or shown to copy`, true);
    await p.evaluate(() => { location.hash = "#record=nobody-here"; });
    await p.waitForFunction(() => document.querySelector("[data-sr=said]")?.textContent === "Holds no record named nobody-here.");
    ok(`${width}px: an unknown name offers the records there are`, (await p.locator("[data-sr=pick] a").count()) === feed.weeks[0].rows.length);
    ok(`${width}px: the strip is on the page with a bar and a sample per row`, (await p.locator(".board-strip li").count()) === 4 && (await p.locator(".board-strip .bs-whisker").count()) === 4);
    ok(`${width}px: the strip says under ${STRIP_WORDS} words`, words(await p.innerText(".board-strip")).length < STRIP_WORDS, words(await p.innerText(".board-strip")).length);
    ok(`${width}px: nobody but this page is asked`, strangers.length === 0, strangers);
    ok(`${width}px: no error on the page`, errors.length === 0, errors);
    await ctx.close();
  }
  await browser.close(); server.close();
}
if (process.argv[2] === "page") await page();
console.log(failed ? `${failed} failed` : "all passed");
process.exit(failed ? 1 : 0);
