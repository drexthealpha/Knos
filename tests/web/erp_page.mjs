// "Download for your accounting system" on the Statement page (web/statements.js, web/erp.js), in headless Chromium on
// web/ as it stands: node tests/web/erp_page.mjs. September's statement is opened with its last line refused by the
// buyer; for each system the control downloads the payable file (the system's own header, line 1 only) and the held
// sheet (the disputed, owed, duplicate and unevidenced lines), and says both counts in twelve words or fewer. Nothing
// runs off the side from 320 to 1280 px; nobody is asked but the page's own server. No `playwright` or no browser: SKIP.
import { createServer } from "node:http";
import { readFileSync, existsSync } from "node:fs";
import { join, dirname, extname, normalize } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url)), web = join(here, "../../web"), data = join(here, "../data");
let chromium;
try { ({ chromium } = (await import("playwright")).default); } catch (e) { console.log(`SKIP the playwright package is not installed (${e.code || e.message})`); process.exit(0); }
let failed = 0;
const ok = (what, cond, detail) => { if (!cond) failed++; console.log(`${cond ? "ok  " : "FAIL"} ${what}${cond || detail === undefined ? "" : `: ${JSON.stringify(detail)}`}`); };
const TYPES = { ".js": "text/javascript", ".css": "text/css", ".json": "application/json", ".html": "text/html", ".woff2": "font/woff2", ".svg": "image/svg+xml" };
const PAGE = `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Statement</title>
<link rel="stylesheet" href="/app.css"></head><body><main id="page"></main>
<script type="module">import { renderStatements } from "/statements.js";
const file = async (path) => (await fetch("/" + path)).json();
window.openStatement = renderStatements(document.getElementById("page"), { file, now: new Date("2026-10-05T12:00:00Z") });
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
const HEAD = {
  xero: "ContactName,InvoiceNumber,Reference,InvoiceDate,DueDate,Description,Quantity,UnitAmount,AccountCode,TaxType,InventoryItemCode,Discount,Currency",
  quickbooks: "Bill no.,Supplier,Bill Date,Due Date,Account,Line Description,Line Amount,Line Tax Code,Memo",
  netsuite: "External ID,Vendor,Date,Reference No.,Memo,Expenses : Account,Expenses : Amount,Expenses : Memo",
  csv: "bill_no,invoice,line,supplier,reference,date,amount,currency,policy,accepted,authorised,settled,assurance,payment,invoice_line,deliverable,settlement,statement_sha256",
};
const st = JSON.parse(readFileSync(join(data, "statement/sept.json"), "utf8"));
const [first, refusedLine] = [st.lines[0].invoice_line, st.lines[4].invoice_line];
let browser;
try { browser = await chromium.launch(); } catch (e) { console.log(`SKIP no browser for playwright here (${String(e.message).split("\n")[0]})`); server.close(); process.exit(0); }
try {
  for (const width of [320, 768, 1280]) {
    const page = await browser.newPage({ viewport: { width, height: 900 }, acceptDownloads: true });
    const asked = [], errors = [];
    page.on("request", (r) => { if (!r.url().startsWith(origin)) asked.push(r.url()); });
    page.on("pageerror", (e) => errors.push(e.message));
    await page.goto(origin);
    await page.waitForFunction(() => window.ready === true);
    await page.evaluate(async () => { const j = async (n) => (await fetch(`/golden/${n}`)).json(); await window.openStatement(await j("statement/sept.json"), await j("erp/sept.refused.status.json")); });
    await page.waitForSelector("#aps-erp-go");
    const label = (await page.textContent("#aps-erp-go")).trim();
    ok(`${width}px: one control, named for the approver`, label === "Download for your accounting system" && (await page.$$("#aps-erp button")).length === 1, label);
    const names = [];
    for (const to of Object.keys(HEAD)) {
      await page.selectOption("#aps-erp-to", to);
      const files = [];
      page.on("download", (d) => files.push(d));
      await page.click("#aps-erp-go");
      await page.waitForFunction(() => document.getElementById("aps-erp-said").textContent.length > 0);
      while (files.length < 2) await page.waitForEvent("download");
      page.removeAllListeners("download");
      const got = {};
      for (const d of files) got[d.suggestedFilename()] = readFileSync(await d.path(), "utf8");
      // named as `knos statement export --to` names them (<statement>.<to>.csv, the held sheet beside it)
      const payable = got[`statement-INV-2026-09.${to}.csv`], held = got[`statement-INV-2026-09.${to}.held.csv`];
      names.push(...Object.keys(got));
      ok(`${width}px ${to}: the payable file has the system's header`, payable && payable.split("\n")[0] === HEAD[to], Object.keys(got));
      ok(`${width}px ${to}: one bill, line 1; the refused line is never in it`, payable && payable.split("\n").length === 3 && payable.includes(to === "csv" || to === "xero" ? first : "KNOS-") && !payable.includes(refusedLine));
      ok(`${width}px ${to}: the held sheet has the four other lines`, held && held.trim().split("\n").length === 5 && held.includes(refusedLine) && held.includes("owed to the supplier"));
      const said = await page.textContent("#aps-erp-said");
      ok(`${width}px ${to}: it says both counts in twelve words or fewer`, said === "1 bill; 4 held lines on a separate sheet." && said.split(/\s+/).length <= 12, said);
      await page.evaluate(() => { document.getElementById("aps-erp-said").textContent = ""; });
    }
    // the buttons above it (QuickBooks file, NetSuite file, Every line: exports.write_statement) save other bytes: never
    // under the same name. Their names are read as the page hands them to the browser: the `download` of the link it clicks.
    const above = await page.evaluate(async () => {
      const got = [], real = HTMLAnchorElement.prototype.click;
      HTMLAnchorElement.prototype.click = function () { if (this.download) got.push(this.download); };
      try {
        for (const b of document.querySelectorAll("[data-aps-export]")) {
          const had = got.length;
          b.click();
          for (let t = 0; got.length === had && t < 200; t++) await new Promise((r) => setTimeout(r, 25));
        }
      } finally { HTMLAnchorElement.prototype.click = real; }
      return got;
    });
    ok(`${width}px: no two downloads of the page share a name`, new Set([...above, ...names]).size === above.length + names.length && above.length === 3 && names.length === 8, [above, names, errors]);
    ok(`${width}px: nothing runs off the side`, await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth), await page.evaluate(() => [document.documentElement.scrollWidth, document.documentElement.clientWidth]));
    ok(`${width}px: nobody is asked but the page's own server`, asked.length === 0, asked);
    await page.close();
  }
} finally { await browser.close(); server.close(); }
console.log(failed ? `${failed} failed` : "all passed");
process.exit(failed ? 1 : 0);
