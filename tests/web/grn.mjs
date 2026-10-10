// The goods-received note on the Statement page (web/statements.js), in headless Chromium on web/ as it stands:
// node tests/web/grn.mjs. The sample statement is opened; each line shows its assurance level, and its three legs
// (purchase order, receipt of goods, invoice line) side by side with "match" or "mismatch"; a recorded note shows its
// purchase order; no statement is longer than twelve words; nothing runs off the side from 320 to 1280 px; nobody is
// asked but the page's own server. No `playwright` package or no browser: SKIP, with the reason.
import { createServer } from "node:http";
import { readFileSync, existsSync } from "node:fs";
import { join, dirname, extname, normalize } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url)), web = join(here, "../../web"), data = join(here, "../data/statement");
let chromium;
try { ({ chromium } = (await import("playwright")).default); } catch (e) { console.log(`SKIP the playwright package is not installed (${e.code || e.message})`); process.exit(0); }
let failed = 0;
const ok = (what, cond, detail) => { if (!cond) failed++; console.log(`${cond ? "ok  " : "FAIL"} ${what}${cond || detail === undefined ? "" : `: ${JSON.stringify(detail)}`}`); };
const TYPES = { ".js": "text/javascript", ".css": "text/css", ".json": "application/json", ".html": "text/html", ".woff2": "font/woff2", ".svg": "image/svg+xml" };
const PAGE = `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Statement</title>
<link rel="stylesheet" href="/app.css"></head><body><main id="page"></main>
<script type="module">import { renderStatements } from "/statements.js";
const file = async (path) => (await fetch("/" + path)).json();
window.openStatement = renderStatements(document.getElementById("page"), { file });
window.ready = true;</script></body></html>`;
const server = createServer((req, res) => {
  const path = normalize(decodeURIComponent(req.url.split("?")[0])).replace(/^([/\\])+/, "");
  if (!path) { res.writeHead(200, { "content-type": "text/html" }); return res.end(PAGE); }
  const built = { "settle.js": "../sdk/settle/index.js", "passkey.js": "../sdk/settle/passkey.js", "program_ids.json": "../src/knos/settle/v2/program_ids.json" };   // what scripts/build_site.sh copies in
  const file = path.startsWith("golden/") ? join(data, path.slice(7)) : join(web, built[path] || path);
  if (!existsSync(file)) { res.writeHead(404); return res.end(); }
  res.writeHead(200, { "content-type": TYPES[extname(file)] || "application/octet-stream" });
  res.end(readFileSync(file));
});
await new Promise((r) => server.listen(0, "127.0.0.1", r));
const origin = `http://127.0.0.1:${server.address().port}`;
let browser;
try { browser = await chromium.launch(); } catch (e) { console.log(`SKIP no browser for playwright here (${String(e.message).split("\n")[0]})`); server.close(); process.exit(0); }
try {
  for (const width of [320, 768, 1280]) {
    const page = await browser.newPage({ viewport: { width, height: 900 } });
    const asked = [];
    page.on("request", (r) => { if (!r.url().startsWith(origin)) asked.push(r.url()); });
    await page.goto(origin);
    await page.waitForFunction(() => window.ready === true);
    // timed in the page, from the click event to the first thing drawn in #aps-result: Playwright's own checks before a
    // click and its round trips are not the page's time (several browsers share the runner's cores under pytest -n auto)
    await page.evaluate(() => {
      const out = document.getElementById("aps-result");
      window.answered = {};
      document.addEventListener("click", (e) => { if (e.target.closest("#aps-sample")) window.answered.click ??= performance.now(); }, { capture: true });
      new MutationObserver((_, o) => { if (window.answered.click !== undefined && out.firstElementChild) { window.answered.drawn = performance.now(); o.disconnect(); } })
        .observe(out, { childList: true, subtree: true });
    });
    await page.click("#aps-sample");
    await page.waitForSelector("#aps-result > *");                        // the pending state, or the statement itself
    const took = await page.evaluate(() => window.answered.drawn - window.answered.click);
    ok(`${width}px: the click is answered within 300 ms`, took < 300, Math.round(took));
    await page.waitForSelector("#aps-statement");
    const head = await page.$$eval("#aps-lines th", (x) => x.map((e) => e.textContent.trim()));
    ok(`${width}px: the lines have an assurance column`, head.includes("assurance"), head);
    const at = head.indexOf("assurance");
    const levels = await page.$$eval("#aps-lines tbody tr", (rows, n) => rows.map((r) => r.children[n].textContent.trim()), at);
    ok(`${width}px: every line says its level`, JSON.stringify(levels) === JSON.stringify(["not signed", "not signed", "not signed", "not evaluated", "not signed"]), levels);     // `knos assurance`'s words: a shadow statement is not signed
    await page.click("#aps-grn > summary");
    const notes = await page.$$eval("#aps-grn .k-grn", (x) => x.map((s) => ({ match: s.dataset.match, legs: [...s.querySelectorAll("[data-grn-leg]")].map((c) => c.dataset.grnLeg),
      tops: [...s.querySelectorAll("[data-grn-leg]")].map((c) => Math.round(c.getBoundingClientRect().top)), said: s.querySelector(".k-state").textContent })));
    ok(`${width}px: one note a line, three legs each`, notes.length === 5 && notes.every((n) => n.legs.join() === "order,goods,invoice"), notes);
    ok(`${width}px: with no order on record every note says mismatch`, notes.every((n) => n.match === "0" && n.said === "mismatch"), notes);
    if (width >= 768) ok(`${width}px: the three legs are side by side`, notes.every((n) => new Set(n.tops).size === 1), notes[0]);
    const long = await page.$$eval("#aps-grn p, #aps-grn summary, #aps-grn li", (x) => x.filter((e) => !e.closest("details:not([open])")).map((e) => e.textContent.trim()).filter((t) => t.split(/\s+/).length > 12));
    ok(`${width}px: no statement of a note is longer than twelve words`, long.length === 0, long);
    ok(`${width}px: nothing runs off the side`, await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth), await page.evaluate(() => [document.documentElement.scrollWidth, document.documentElement.clientWidth]));
    // a recorded note: the same statement with the status file `knos statement grn --record` wrote
    await page.evaluate(async () => { const j = async (n) => (await fetch(`/golden/${n}`)).json(); await window.openStatement(await j("sept.json"), await j("sept.grn.status.json")); });
    await page.click("#aps-grn > summary");
    const last = await page.$eval("#aps-grn .k-grn:last-of-type", (s) => ({ match: s.dataset.match, order: s.querySelector('[data-grn-leg="order"]').textContent, goods: s.querySelector('[data-grn-leg="goods"]').textContent }));
    ok(`${width}px: a recorded note matches and names its order and level`, last.match === "1" && last.order.includes("PO-2026-0932") && last.goods.includes("re-executed"), last);
    const level = await page.$$eval("#aps-lines tbody tr", (rows, n) => rows[4].children[n].textContent.trim(), at);
    ok(`${width}px: the line then says the receipt's assurance, as knos assurance does`, level === "re-executed (workflow identity proved on chain)", level);
    ok(`${width}px: nothing runs off the side with a recorded note`, await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth));
    ok(`${width}px: nobody is asked but the page's own server`, asked.length === 0, asked);
    await page.close();
  }
} finally { await browser.close(); server.close(); }
console.log(failed ? `${failed} failed` : "all passed");
process.exit(failed ? 1 : 0);
