// The bank's payment file as the site writes it (web/rails.js): node tests/web/rails.mjs [--no-browser]
// tests/data/rails/vectors.json was written by the Python (tests/test_statement_rails.py holds it equal to knos.rails).
// The site's function must give the same bytes from the same statement, status and payer. Then, in headless Chromium,
// the view: a statement in, the same file out, no sideways scroll from 320 to 1280 px, nobody asked but the page's own
// server, no statement longer than twelve words. No `playwright` package or no browser: that part says SKIP.
import { createServer } from "node:http";
import { readFileSync, existsSync } from "node:fs";
import { join, dirname, extname, normalize } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = dirname(fileURLToPath(import.meta.url)), web = join(here, "../../web");
const rails = await import(pathToFileURL(join(web, "rails.js")).href);
const vectors = JSON.parse(readFileSync(join(here, "../data/rails/vectors.json"), "utf8"));
let failed = 0;
const ok = (what, cond, detail) => { if (!cond) failed++; console.log(`${cond ? "ok  " : "FAIL"} ${what}${cond || detail === undefined ? "" : `: ${JSON.stringify(detail)}`}`); };
const same = (what, got, want) => {
  const a = typeof got === "string" ? got : JSON.stringify(got), b = typeof want === "string" ? want : JSON.stringify(want);
  let i = 0; while (i < a.length && a[i] === b[i]) i++;
  ok(what, a === b, a === b ? undefined : { at: i, got: a.slice(Math.max(0, i - 40), i + 80), want: b.slice(Math.max(0, i - 40), i + 80) });
};
const refused = (fn) => { try { fn(); return ""; } catch (e) { return e.message; } };

same("SHA-256 of nothing", rails.sha256(new Uint8Array(0)), "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855");
same("SHA-256 across two blocks", rails.sha256(new TextEncoder().encode("a".repeat(119))), "31eba51c313a5c08226adf18d4a359cfdfd8d2e816b13f4af952f7ea6584dcfb");
for (const v of vectors) {
  same(`${v.name}: the transfers`, rails.transfers(v.statement, v.status), v.transfers);
  same(`${v.name}: the message id`, rails.messageId(v.statement, v.transfers), v.message);
  same(`${v.name}: the file, byte for byte`, rails.pain001(v.statement, v.payer, v.status), v.xml);
  same(`${v.name}: the status may ride in the payer`, rails.pain001(v.statement, { ...v.payer, status: v.status }), v.xml);
}
const v = vectors[0];
ok("nobody approved: nothing is instructed", refused(() => rails.pain001(v.statement, v.payer, null)).includes("agreed, approved and still payable"));
ok("an IBAN with wrong check digits is refused", refused(() => rails.pain001(v.statement, { ...v.payer, account: "DE89370400440532013001" }, v.status)).includes("check digits are wrong"));
ok("a supplier with no account is named", refused(() => rails.pain001(v.statement, { ...v.payer, payees: {} }, v.status)).includes("No bank account is given for Acme Agents"));
ok("test money is never paid by bank", refused(() => rails.transfers({ ...v.statement, currency: "test USDC" }, { ...v.status, statement: v.statement.sha256 })).includes("Test money is paid on devnet"));
ok("another statement's status is refused", refused(() => rails.transfers(v.statement, { ...v.status, statement: "x" })).includes("another statement's"));
ok("a name is cut to what a bank's file takes", rails.text("  Ünïcode & <tags>\n", 140) === ".n.code . .tags.");

if (!process.argv.includes("--no-browser")) {
  let chromium;
  try { ({ chromium } = (await import("playwright")).default); } catch (e) { console.log(`SKIP the playwright package is not installed (${e.code || e.message})`); }
  let browser;
  if (chromium) { try { browser = await chromium.launch(); } catch (e) { console.log(`SKIP no browser for playwright here (${String(e.message).split("\n")[0]})`); } }
  if (browser) {
    const TYPES = { ".js": "text/javascript", ".css": "text/css", ".json": "application/json", ".woff2": "font/woff2", ".svg": "image/svg+xml" };
    const PAGE = `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Pay by bank</title>
<link rel="stylesheet" href="/app.css"></head><body><main id="page"></main>
<script type="module">import { renderRails } from "/rails.js";
const v = (await (await fetch("/golden/vectors.json")).json())[0];
window.view = renderRails(document.getElementById("page"), { today: v.payer.on });
window.vector = v; window.ready = true;</script></body></html>`;
    const server = createServer((req, res) => {
      const path = normalize(decodeURIComponent(req.url.split("?")[0])).replace(/^([/\\])+/, "");
      if (!path) { res.writeHead(200, { "content-type": "text/html" }); return res.end(PAGE); }
      const file = path.startsWith("golden/") ? join(here, "../data/rails", path.slice(7)) : join(web, path);
      if (!existsSync(file)) { res.writeHead(404); return res.end(); }
      res.writeHead(200, { "content-type": TYPES[extname(file)] || "application/octet-stream" });
      res.end(readFileSync(file));
    });
    await new Promise((r) => server.listen(0, "127.0.0.1", r));
    const origin = `http://127.0.0.1:${server.address().port}`;
    try {
      for (const width of [320, 768, 1280]) {
        const page = await browser.newPage({ viewport: { width, height: 900 } });
        const asked = [];
        page.on("request", (r) => { if (!r.url().startsWith(origin)) asked.push(r.url()); });
        await page.goto(origin + "/");
        await page.waitForFunction("window.ready === true");
        ok(`${width}px: with no statement it says what to do`, (await page.textContent("[data-rails-said]")) === "Choose a statement.");
        await page.evaluate(() => window.view.open(window.vector.statement, window.vector.status));
        ok(`${width}px: one transfer is ready`, (await page.textContent("[data-rails-said]")) === "1 transfer ready.");
        ok(`${width}px: the amount and its lines are shown`, JSON.stringify(await page.$$eval("tbody td", (tds) => tds.slice(0, 3).map((td) => td.textContent.trim()))) === JSON.stringify(["Acme Agents", "160.00 USD", "2"]));
        await page.fill('input[name="name"]', v.payer.name);
        await page.fill('input[name="account"]', "DE89370400440532013001");
        await page.fill('input[name="payee0"]', v.payer.payees["Acme Agents"].account);
        const said = await page.evaluate(() => { document.querySelector('button[type="submit"]').click(); return document.querySelector("[data-rails-said]").textContent; });
        ok(`${width}px: a wrong IBAN is said in the same turn, and no file is made`, said.includes("check digits are wrong") && !(await page.evaluate(() => document.getElementById("page").dataset.railsFile)), said);
        await page.fill('input[name="account"]', v.payer.account);
        const [download] = await Promise.all([page.waitForEvent("download"), page.click('button[type="submit"]')]);
        ok(`${width}px: the file is saved under its message id`, download.suggestedFilename() === `${v.message}.pain001.xml`);
        const made = await page.evaluate(() => document.getElementById("page").dataset.railsFile);
        const want = rails.pain001(v.statement, { name: v.payer.name, account: v.payer.account, on: v.payer.on, payees: { "Acme Agents": { name: "Acme Agents", account: v.payer.payees["Acme Agents"].account } } }, v.status);
        same(`${width}px: the file the view made is the function's`, made, want);
        ok(`${width}px: nothing runs off the side`, await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth));
        const long = await page.evaluate(() => [...document.querySelectorAll(".rails p, .rails h2, .rails label, .rails button, .rails th")].map((e) => (e.childElementCount && e.tagName !== "P" ? [...e.childNodes].filter((n) => n.nodeType === 3).map((n) => n.textContent).join(" ") : e.textContent).trim()).filter((t) => t.split(/\s+/).length > 12));
        ok(`${width}px: no statement is longer than twelve words`, long.length === 0, long);
        ok(`${width}px: nobody is asked but the page's own server`, asked.length === 0, asked);
        await page.close();
      }
    } finally { await browser.close(); server.close(); }
  }
}
console.log(failed ? `${failed} failed` : "all passed");
process.exit(failed ? 1 : 0);
