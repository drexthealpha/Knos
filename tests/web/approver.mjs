// The approver's screen (web/approver.js), with no browser: node tests/web/approver.mjs
// Its rows are held to the statements of tests/data/statement (which `knos statement make` wrote). Then, with `page`,
// the screen in headless Chromium: a first invoice comparison as someone new would make it (open, drop two files, read
// the result, open one exception, approve), each step timed; the sample; the five exceptions; a receipt's five parts
// in place; the keyboard alone; 320 to 1280 px; twelve words a statement; no movement when none is asked for; nobody
// asked but the page's own host. `page --write` writes what the script measured to web/approver_time.json, which the
// page states: a script's time, not a person's.
import { readFileSync, writeFileSync, existsSync } from "node:fs";
import { join, dirname, extname } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = dirname(fileURLToPath(import.meta.url)), web = join(here, "../../web"), data = join(here, "../data/statement");
const mod = (name) => import(pathToFileURL(join(web, name)).href);
const { readOrders, rowsOf, uncheckedRows, partsOf, readReceipts, messageOf, EXCEPTIONS, WORDS, COLUMNS, PARTS, SAMPLE_ORDERS } = await mod("approver.js");
const { fromShadow, approve } = await mod("statement_make.js");
const { parse } = await mod("shadow.js");
const { SAMPLE_INVOICE, SAMPLE_BOOK, SAMPLE_META } = await mod("front_door_sample.js");
const read = (name) => readFileSync(join(data, name), "utf8"), json = (name) => JSON.parse(read(name));
const sept = json("sept.json"), septStatus = json("sept.status.json"), october = json("october.json"), front = json("front_door.json");
const TIME = join(web, "approver_time.json");
// an invoice file for the September statement that names a purchase order of 120.00: lines 1 and 5 are agreed (100.00, 60.00)
const INVOICE = "pull_request,amount,supplier,po_number,po_amount\nacme/app#1,100.00,Acme Agents,PO-7,120.00\nacme/app#2,250.00,Acme Agents,PO-7,120.00\nacme/app#3,80.00,Acme Agents,PO-7,120.00\n"
  + "acme/app#1,100.00,Acme Agents,PO-7,120.00\nacme/app#4,60.00,Acme Agents,PO-7,120.00\n";
const RECEIPT = { invoice_line: sept.lines[0].invoice_line, parts: { Identity: { said: "GitHub signed run 21 of acme/app.", issuer: "https://token.actions.githubusercontent.com", workflow: "knos.yml" },
  Execution: "The agreed evaluator ran on the merged commit.", Acceptance: { line: "The agreed check, test, passed.", terms_sha256: "ab".repeat(32) },
  Consequence: "100.00 became payable to Acme Agents.", Assurance: { said: "Reported: the workflow file decides what it reads.", level: "reported" } } };

let failed = 0;
const same = (what, got, want) => { const ok = JSON.stringify(got) === JSON.stringify(want); if (!ok) failed++; console.log(`${ok ? "ok  " : "FAIL"} ${what}${ok ? "" : `: got ${JSON.stringify(got)}, want ${JSON.stringify(want)}`}`); };
const kinds = (rows) => rows.map((r) => r.kind);

same("seven columns, in the order an approver reads", COLUMNS.map((c) => c[1]), ["Supplier", "Purchase order", "Agreed deliverable", "Acceptance evidence", "Authorised amount", "Exception", "Payment status"]);
same("five exceptions, each with its words", EXCEPTIONS.map((k) => WORDS[k]), ["disputed", "duplicate", "insufficient evidence", "over the purchase order", "replayed"]);
same("a purchase order column is read by pull request", JSON.stringify(readOrders(INVOICE), (k, v) => (typeof v === "bigint" ? String(v) : v)), JSON.stringify({ "acme/app#1": { number: "PO-7", limit: "12000" },
  "acme/app#2": { number: "PO-7", limit: "12000" }, "acme/app#3": { number: "PO-7", limit: "12000" }, "acme/app#4": { number: "PO-7", limit: "12000" } }));
same("an invoice with no purchase order column names none", readOrders(SAMPLE_INVOICE), {});
same("September with no purchase order: the statement's own states", kinds(rowsOf(sept)), [null, "disputed", "insufficient_evidence", "duplicate", null]);
const over = rowsOf(sept, null, readOrders(INVOICE));
same("September against a purchase order of 120.00: the line that passes it is held", kinds(over), [null, "disputed", "insufficient_evidence", "duplicate", "over_po"]);
same("the held line says the limit and what was reached, and nothing is authorised", [over[4].reason, over[4].authorised, over[4].payment, over[0].authorised],
  ["Purchase order PO-7 allows 120.00; agreed lines reach 160.00.", "0.00", "held here", "100.00"]);
same("a line billed on an earlier statement is replayed", [kinds(rowsOf(october)), rowsOf(october)[0].reason], [["replayed", null], "Already billed: invoice INV-2026-09 line 1 agreed this deliverable on 2026-09-30."]);
same("with its status file a line says who approved and how it was paid", rowsOf(sept, septStatus).map((r) => r.payment),
  ["approved, paid outside Knos", "held", "held", "held", "approved, devnet demonstration"]);
const sample = await fromShadow({ invoice: SAMPLE_INVOICE, answers: SAMPLE_BOOK }, SAMPLE_META);
same("the sample is the front door's statement", sample.sha256, front.sha256);
same("the sample: two agreed lines inside their purchase orders, five exceptions", kinds(rowsOf(sample, null, readOrders(SAMPLE_ORDERS))), [null, "disputed", "disputed", "duplicate", null, "duplicate", "insufficient_evidence"]);
same("an invoice with no statement: nothing is checked, every line is an exception", uncheckedRows(parse(INVOICE), readOrders(INVOICE)).map((r) => [r.kind, r.reason, r.authorised])[0],
  ["insufficient_evidence", "No statement covers this line.", "0.00"]);
// the approval: every agreed line as `knos statement approve` records it, or the ones the approver did not hold back
same("an approval of every agreed line is the Python's", Object.entries(approve(sept, null, "Dana Reyes", "finance controller", "2026-10-01").events[0]).sort(), Object.entries(septStatus.events[0]).sort());
const part = approve(sept, null, "Dana Reyes", "finance controller", "2026-10-01", over.filter((r) => !r.kind).map((r) => r.id)).events[0];
same("an approval that holds the line over its purchase order names one line and its amount", [part.lines, part.amount], [[sept.lines[0].invoice_line], "100.00"]);
same("a receipt's five parts, in order, from sentences or objects", partsOf(RECEIPT).map((p) => [p.key, p.said, p.facts.length]),
  [["identity", "GitHub signed run 21 of acme/app.", 2], ["execution", "The agreed evaluator ran on the merged commit.", 0], ["acceptance", "The agreed check, test, passed.", 1],
    ["consequence", "100.00 became payable to Acme Agents.", 0], ["assurance", "Reported: the workflow file decides what it reads.", 1]]);
same("the five parts as a list", partsOf({ parts: PARTS.map((name) => ({ name, said: `${name}.` })) }).map((p) => p.said), PARTS.map((n) => `${n}.`));
{ // the shape the command line writes (src/knos/receipt.py `parts`; tests/data/receipt_parts.json holds 21 of them)
  const cases = JSON.parse(readFileSync(join(here, "../data/receipt_parts.json"), "utf8")).cases, first = cases[0].parts, got = partsOf(first);
  same("the parts `knos receipt explain --json` writes: every case reads in five parts, each its own line", cases.map((c) => (partsOf(c.parts) || []).map((p) => p.said).join("|")), cases.map((c) => c.parts.parts.map((p) => p.line).join("|")));
  same("  its facts are the part's own facts, and its line is named by them", [got.map((p) => p.key), got[0].facts.some(([n, v]) => n === "issuer" && v === first.parts[0].facts.issuer), got[0].facts.some(([n]) => ["asks", "more", "title", "id"].includes(n)),
    readReceipts(first)[0].invoice_line, readReceipts(first)[0].deliverable], [PARTS, true, false, first.parts[3].facts.invoice_line, first.parts[3].facts.deliverable]);
}
same("a receipt missing a part is not shown", [partsOf({ parts: { identity: "x" } }), readReceipts({ receipts: [RECEIPT, { parts: { identity: "x" } }] }).length], [null, 1]);
same("a receipt is its line's", rowsOf(sept, null, {}, readReceipts(RECEIPT)).map((r) => Boolean(r.parts)), [true, false, false, false, false]);
const m = messageOf(over[1], sept);
same("the message to the supplier says the line, the reason and what settles it", [m.subject, m.body.split("\n").slice(0, 6)], ["Invoice INV-2026-09, line 2: disputed",
  ["To Acme Agents,", "", "Line 2 of invoice INV-2026-09 (acme/app#2), 250.00 USD, is not approved.", "It is held as: disputed.", "Reason: A check failed when this change was merged: test.",
    "What settles it: Send the passing run for this change, or appeal."]]);
same("every exception has a message", EXCEPTIONS.map((kind) => messageOf({ ...over[1], kind }, sept).body.includes("What settles it: undefined")), [false, false, false, false, false]);
if (existsSync(TIME)) {
  const t = JSON.parse(readFileSync(TIME, "utf8"));
  same("the time the page states is a script's, of five steps, under ten minutes", [t.scripted, t.steps.map((s) => s.step), t.total_ms < 600_000 && t.total_ms === t.steps.reduce((a, s) => a + s.ms, 0)],
    [true, ["open the page", "drop the invoice and the statement", "read the result", "open one exception", "approve the agreed lines"], true]);
}

// ---- the page, in headless Chromium: node tests/web/approver.mjs page [--write] ------------------------------------------
async function page() {
  const { createServer } = await import("node:http");
  const { createRequire } = await import("node:module");
  const { measure } = await import("./overflow.mjs");
  const skip = (why) => { console.log(`SKIP ${why}`); process.exit(0); };
  let pw;
  try { pw = await import("playwright"); } catch {
    const paths = (process.env.NODE_PATH || "").split(":").filter(Boolean);
    try { const req = createRequire(import.meta.url); pw = req(req.resolve("playwright", { paths })); } catch { skip("the playwright package is not installed"); }
  }
  const { chromium } = pw.default || pw;
  let browser;
  try { browser = await chromium.launch(); } catch (e) { skip(`no Chromium to start: ${String(e.message).split("\n")[0]}`); }
  const TYPES = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json", ".svg": "image/svg+xml", ".woff2": "font/woff2" };
  // ?rails gives the page a payment module that says what it was handed; ?norails says there is none; neither: web/rails.js is asked for
  const HOLDER = `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Approve</title>
    <link rel="stylesheet" href="app.css"></head><body><main><section id="approve"></section></main>
    <script type="module">import { renderApprover } from "./approver.js"; const q = new URLSearchParams(location.search);
      const rails = q.has("rails") ? { pain001: (st, payer, status) => "<pain>" + [st.sha256, payer.name, payer.iban, payer.bic, status.events[0].lines.length].join("|") + "</pain>" } : q.has("norails") ? null : undefined;
      window.ap = renderApprover(document.getElementById("approve"), { now: new Date("2026-10-07T12:00:00Z"), ...(rails === undefined ? {} : { rails }) }); await window.ap.loaded; window.drawn = true;</script></body></html>`;
  const server = createServer((req, res) => {
    const path = decodeURIComponent(new URL(req.url, "http://x").pathname), file = join(web, path);
    if (path === "/approver_page.html") { res.writeHead(200, { "content-type": "text/html" }); return res.end(HOLDER); }
    if (!file.startsWith(web) || !existsSync(file) || !extname(file)) { res.writeHead(404); return res.end(); }
    res.writeHead(200, { "content-type": TYPES[extname(file)] || "application/octet-stream" }); res.end(readFileSync(file));
  });
  await new Promise((r) => server.listen(0, "127.0.0.1", r));
  const base = `http://127.0.0.1:${server.address().port}/`;
  const ok = (what, cond, detail) => { if (!cond) failed++; console.log(`${cond ? "ok  " : "FAIL"} ${what}${cond || detail === undefined ? "" : `: ${JSON.stringify(detail)}`}`); };
  // every statement the page makes itself: what is not a control's cell of data, a quoted reason or a fact
  const statements = (p) => p.evaluate(() => [...document.querySelectorAll(".approver h2, .approver h3, .approver h4, .approver p, .approver label, .approver button:not(.ap-cell), .approver summary, .approver th, .approver a")]
    .filter((e) => e.offsetParent !== null && !e.closest("dl, textarea")).flatMap((e) => { const c = e.cloneNode(true); for (const x of c.querySelectorAll("[data-not-prose], .k-num, input, textarea")) x.remove(); return c.innerText.split(/(?<=[.!?:])\s+|\n+/); })
    .map((t) => t.trim()).filter(Boolean));
  const wordy = (list) => list.filter((t) => t.split(/\s+/).filter((w) => /[\p{L}\p{N}]/u.test(w)).length > 12);
  const open = async (width, query = "?norails", more = {}) => {
    const ctx = await browser.newContext({ viewport: { width, height: 800 }, acceptDownloads: true, ...more }), seen = { strangers: [], errors: [], asked: [] };
    await ctx.route("**/*", (route) => { const u = route.request().url(); seen.asked.push(u); if (u.startsWith(base)) return route.continue(); seen.strangers.push(u); return route.abort(); });
    const p = await ctx.newPage();
    p.on("pageerror", (e) => seen.errors.push(String(e)));
    p.on("console", (msg) => { if (msg.type() === "error" && !/approver_time\.json|rails\.js|motion\.js/.test(msg.location().url || "")) seen.errors.push(msg.text()); });
    const t0 = Date.now();
    await p.goto(`${base}approver_page.html${query}`);
    await p.waitForFunction(() => window.drawn === true);
    return { ctx, p, seen, opened: Date.now() - t0 };
  };
  const dropFiles = (p, files) => p.evaluate((files) => {
    const dt = new DataTransfer();
    for (const [name, text] of files) dt.items.add(new File([text], name, { type: name.endsWith(".json") ? "application/json" : "text/csv" }));
    document.querySelector("[data-ap=drop]").dispatchEvent(new DragEvent("drop", { bubbles: true, cancelable: true, dataTransfer: dt }));
  }, files);
  const downloaded = async (p, press) => { const [d] = await Promise.all([p.waitForEvent("download"), press()]); return { name: d.suggestedFilename(), text: readFileSync(await d.path(), "utf8") }; };
  const said = (p, name = "said") => p.innerText(`[data-ap=${name}]`);

  // ---- 1. a first invoice comparison, as someone new makes it, timed step by step -------------------------------------------
  {
    const { ctx, p, seen, opened } = await open(1280, "?rails"), steps = [{ step: "open the page", ms: opened }];
    const timed = async (step, fn) => { const t = Date.now(); await fn(); steps.push({ step, ms: Date.now() - t }); };
    ok("the empty screen says there is no account and that it works signed out", (await said(p, "account")) === "No account system exists. This screen works signed out.");
    if (existsSync(TIME)) ok("the screen states the time the script measured, and that no person was timed", (await said(p, "time")) === `Scripted first comparison: ${(JSON.parse(readFileSync(TIME, "utf8")).total_ms / 1000).toFixed(1)} s. No person was timed.`, await said(p, "time"));
    ok("the private path is one link", (await p.getAttribute(".approver a[href*='PRIVATE.md']", "href")) === "https://github.com/drexthealpha/Knos/blob/main/docs/PRIVATE.md");
    await timed("drop the invoice and the statement", async () => { await dropFiles(p, [["invoice.csv", INVOICE], ["sept.json", read("sept.json")]]); await p.waitForSelector("tr.ap-row[data-line='5']"); });
    let got;
    await timed("read the result", async () => {
      got = await p.evaluate(() => ({ said: document.querySelector("[data-ap=said]").textContent, head: [...document.querySelectorAll(".ap-table th")].map((e) => e.textContent),
        sums: [...document.querySelectorAll("[data-sum]")].map((e) => e.innerText.replace(/\s+/g, " ").trim()), rows: [...document.querySelectorAll("tr.ap-row")].map((tr) => [...tr.querySelectorAll(".ap-cell")].map((c) => c.innerText.replace(/\s+/g, " ").trim())),
        queue: [...document.querySelectorAll(".ap-queue li")].map((li) => li.querySelector("p").innerText.replace(/\s+/g, " ").trim()) }));
    });
    ok("the result says how many lines and how many exceptions", got.said === "Read 5 lines. 4 exceptions.", got.said);
    ok("one row a line, read left to right in the seven columns", JSON.stringify(got.head) === JSON.stringify(COLUMNS.map((c) => c[1])) && got.rows.length === 5 && got.rows.every((r) => r.length === 7), got.head);
    ok("an agreed line: supplier, order, deliverable, evidence, amount, no exception, payable", JSON.stringify(got.rows[0]) === JSON.stringify(["Acme Agents", "PO-7", "acme/app#1", "1 evaluation, reported", "100.00", "none", "payable"]), got.rows[0]);
    ok("a line over its purchase order: nothing authorised, held here", JSON.stringify(got.rows[4]) === JSON.stringify(["Acme Agents", "PO-7", "acme/app#4", "1 evaluation, reported", "0.00 of 60.00 billed", "over the purchase order", "held here"]), got.rows[4]);
    ok("billed, authorised and exceptions are added up", JSON.stringify(got.sums) === JSON.stringify(["Billed 590.00 USD 5 lines", "Authorised 100.00 USD 1 line", "Exceptions 490.00 USD 4 lines"]), got.sums);
    ok("one queue: every line that is not agreed, each with its reason in one sentence", JSON.stringify(got.queue) === JSON.stringify(["Line 2 · Disputed. A check failed when this change was merged: test. 250.00",
      "Line 3 · Insufficient evidence. The checks give no verdict: no check ran. 80.00", "Line 4 · Duplicate. Billed twice on this invoice: same pull request as line 1. 100.00",
      "Line 5 · Over the purchase order. Purchase order PO-7 allows 120.00; agreed lines reach 160.00. 60.00"]), got.queue);
    await timed("open one exception", async () => { await p.click(".ap-queue li[data-line='2'] [data-ap=open]"); await p.waitForSelector("tr.ap-ev [data-ev=exception]"); });
    ok("an exception opens in place, under its row, with what settles it", (await p.evaluate(() => document.querySelector("tr.ap-ev").previousElementSibling.dataset.line)) === "2"
      && (await p.innerText("tr.ap-ev")).includes("Send the passing run for this change, or appeal."), await p.innerText("tr.ap-ev"));
    await p.click("[data-ap=approve]");
    ok("an approval names who approved and in which role", (await said(p, "approved")) === "Type your name and your role." && (await p.evaluate(() => document.activeElement.id)) === "ap-by");
    await timed("approve the agreed lines", async () => { await p.fill("#ap-by", "Dana Reyes"); await p.fill("#ap-role", "finance controller"); await p.click("[data-ap=approve]"); await p.waitForSelector("tr.ap-row[data-approved]"); });
    ok("approving says what was approved and what stays open", (await said(p, "approved")) === "Approved 1 line, 100.00. 4 exceptions stay open.", await said(p, "approved"));
    ok("the approved line says so, and the exceptions are still held", JSON.stringify(await p.evaluate(() => [...document.querySelectorAll("tr.ap-row [data-col=payment]")].map((c) => c.innerText))) === JSON.stringify(["approved, payable", "held", "held", "held", "held here"]));
    ok("nothing is left to approve", await p.isDisabled("[data-ap=approve]"));
    const total = steps.reduce((a, s) => a + s.ms, 0);
    ok(`a first comparison by script: ${total} ms, under ten minutes, with no command line`, total < 600_000, steps);
    if (process.argv.includes("--write")) writeFileSync(TIME, `${JSON.stringify({ scripted: true, by: "tests/web/approver.mjs page --write", what: "headless Chromium at 1280 px on the build machine: a script's time, not a person's; nobody was observed",
      steps, total_ms: total }, null, 1)}\n`);
    // the signed-off statement, the approval beside it, the payment file and the audit export
    const status = JSON.parse((await downloaded(p, async () => { await p.click("details.k-more summary"); await p.click("[data-file=status]"); })).text);
    ok("the approval record is the statement's status file: one approval, the held line left out", status.kind === "knos-statement-status" && status.statement === sept.sha256
      && JSON.stringify(status.events) === JSON.stringify([{ amount: "100.00", by: "Dana Reyes", lines: [sept.lines[0].invoice_line], on: "2026-10-07", role: "finance controller", scope: "agreed", type: "approval" }]), status);
    const csv = await downloaded(p, () => p.click("[data-file=csv]"));
    ok("the statement downloaded carries the approval", csv.name === "statement-INV-2026-09.csv" && csv.text.startsWith(`knos-statement,1,${sept.sha256}\n`) && csv.text.includes("approval,2026-10-07,Dana Reyes (finance controller),1 agreed lines,100.00\n"), csv.text.slice(0, 200));
    const audit = await downloaded(p, () => p.click("[data-file=generic]"));
    ok("the audit export is one click: every line, with its ids", audit.name === "statement-INV-2026-09-generic.csv" && audit.text.split("\n").length === 8 && audit.text.includes(sept.lines[1].invoice_line), audit.text.slice(0, 120));
    ok("with a payment module the payment file is offered after approval", await p.isVisible("[data-file=pain]"));
    await p.fill("#ap-payer", "Northwind Ltd"); await p.fill("#ap-iban", "gb33 bukb 2020 1555 5555 55"); await p.fill("#ap-bic", "bukbgb22");
    const pain = await downloaded(p, () => p.click("[data-file=pain]"));
    ok("the payment file is the module's, handed the statement, the payer and the approval", pain.name === "statement-INV-2026-09.pain.001.xml" && pain.text === `<pain>${sept.sha256}|Northwind Ltd|GB33BUKB20201555555555|BUKBGB22|1</pain>`, pain);
    ok("nobody but this page's own host was asked", seen.strangers.length === 0, seen.strangers);
    ok("no error on the page", seen.errors.length === 0, seen.errors);
    await ctx.close();
  }

  // ---- 2. the sample, a receipt, the replayed line, at every width ----------------------------------------------------------
  for (const width of [1280, 768, 390, 320]) {
    const { ctx, p, seen } = await open(width);
    ok(`${width}px: the empty screen does not scroll sideways`, (await measure(p)).over <= 0, await measure(p));
    // the answer within 300 ms, or a pending state at once: the press itself writes "Reading the sample." before anything is worked out
    const pending = await p.evaluate(() => { document.querySelector("[data-ap=sample]").click(); return document.querySelector("[data-ap=said]").textContent; });
    await p.waitForSelector("tr.ap-row[data-line='7']");
    ok(`${width}px: the sample shows a pending state at once`, pending === "Reading the sample.", pending);
    ok(`${width}px: the sample says it is a sample`, (await p.innerText("[data-ap=mark]")) === "Sample: a made-up invoice from a made-up supplier." && (await said(p)) === "Read 7 lines. 5 exceptions.", await said(p));
    ok(`${width}px: seven rows, five in the queue, each cell a control with its column's name`, (await p.locator("tr.ap-row").count()) === 7 && (await p.locator(".ap-queue li").count()) === 5
      && (await p.getAttribute("tr.ap-row[data-line='1'] [data-col=po]", "aria-label")) === "Line 1, purchase order: PO-1001");
    await p.click("tr.ap-row[data-line='1'] [data-col=evidence]");
    ok(`${width}px: evidence opens in place and says no receipt was given`, (await p.getAttribute("tr.ap-row[data-line='1'] [data-col=evidence]", "aria-expanded")) === "true"
      && (await p.innerText("tr.ap-ev")).includes("none given for this line") && (await p.innerText("tr.ap-ev")).includes("which GitHub does not sign"));
    await p.click("tr.ap-row[data-line='1'] [data-col=evidence]");
    ok(`${width}px: the same cell shuts it`, (await p.locator("tr.ap-ev").count()) === 0);
    await p.click(".ap-queue li[data-line='7'] [data-ap=message]");
    const msg = await p.inputValue("#ap-msg-7");
    ok(`${width}px: the exception goes to the supplier as a message already written`, msg.startsWith("Subject: Invoice sha256:fb61f3411e72ffea, line 7: insufficient evidence\n\nTo Example Agents Ltd (made up),")
      && msg.includes("Reason: GitHub could not be read for this line: not found or private.") && (await p.getAttribute(".ap-queue li[data-line='7'] [data-ap=mail]", "href")).startsWith("mailto:?subject=Invoice%20sha256"), msg);
    ok(`${width}px: without a payment module no payment file is offered`, !(await p.isVisible("[data-ap=pay]")));
    ok(`${width}px: every statement is twelve words at most`, wordy(await statements(p)).length === 0, wordy(await statements(p)));
    ok(`${width}px: the words wallet, hash, pin and token account are not said`, !/\b(wallets?|hash(es|ed)?|pin(s|ned)?|token accounts?)\b/i.test(await p.innerText(".approver")));
    ok(`${width}px: the filled screen does not scroll sideways`, (await measure(p)).over <= 0, await measure(p));
    // September with its receipt, then October: a line billed on an earlier statement is replayed
    await p.click("[data-ap=clear]");
    await dropFiles(p, [["sept.status.json", read("sept.status.json")], ["sept.json", read("sept.json")], ["receipt.json", JSON.stringify(RECEIPT)]]);
    await p.waitForSelector("tr.ap-row[data-approved]");
    ok(`${width}px: a status file read before its statement is still its statement's`, (await p.innerText("tr.ap-row[data-line='1'] [data-col=payment]")) === "approved, paid outside Knos");
    ok(`${width}px: a line with a receipt says so`, (await p.innerText("tr.ap-row[data-line='1'] [data-col=evidence]")) === "receipt, five parts");
    await p.click("tr.ap-row[data-line='1'] [data-col=evidence]");
    ok(`${width}px: the receipt reads in its five parts, in place`, JSON.stringify(await p.evaluate(() => [...document.querySelectorAll("tr.ap-ev [data-ap=parts] > li")].map((li) => `${li.dataset.part}: ${li.querySelector("span").textContent}`)))
      === JSON.stringify(["identity: GitHub signed run 21 of acme/app.", "execution: The agreed evaluator ran on the merged commit.", "acceptance: The agreed check, test, passed.", "consequence: 100.00 became payable to Acme Agents.",
        "assurance: Reported: the workflow file decides what it reads."]));
    ok(`${width}px: the open receipt does not scroll sideways`, (await measure(p)).over <= 0, await measure(p));
    await p.setInputFiles("#ap-file", [{ name: "october.json", mimeType: "application/json", buffer: Buffer.from(read("october.json")) }]);
    await p.waitForFunction(() => document.querySelectorAll("tr.ap-row").length === 2);
    ok(`${width}px: a file chosen is read like one dropped, and a replayed line is named`, (await p.innerText("tr.ap-row[data-line='1'] [data-col=exception]")) === "replayed"
      && (await p.innerText(".ap-queue li[data-line='1'] [data-ap=reason]")) === "Already billed: invoice INV-2026-09 line 1 agreed this deliverable on 2026-09-30.");
    const changed = { ...sept, invoice: "INV-9999" };
    await dropFiles(p, [["changed.json", JSON.stringify(changed)]]);
    await p.waitForFunction(() => document.querySelector("[data-ap=said]").textContent.includes("changed"));
    ok(`${width}px: a statement changed after it was made cannot be approved`, (await said(p)) === "That statement was changed after it was made." && await p.isDisabled("[data-ap=approve]"));
    await p.click("[data-ap=clear]");
    await p.fill("#ap-paste", INVOICE); await p.click("[data-ap=read]");
    await p.waitForSelector("tr.ap-row[data-line='5']");
    ok(`${width}px: an invoice alone is read and nothing is called agreed`, (await said(p)) === "Read 5 lines. No statement yet: nothing is checked." && (await p.locator(".ap-queue li").count()) === 5
      && (await said(p, "approved")) === "Add the statement file to approve.", await said(p));
    await p.fill("#ap-paste", "acme/app#1,a lot\n"); await p.click("[data-ap=read]");
    await p.waitForFunction(() => document.querySelector("[data-ap=said]").textContent.startsWith("Not read"));
    ok(`${width}px: what cannot be read is said`, (await said(p)) === "Not read: what was pasted (line 1: the amount a lot could not be read).", await said(p));
    ok(`${width}px: nobody but this page's own host was asked`, seen.strangers.length === 0, seen.strangers);
    ok(`${width}px: no error on the page`, seen.errors.length === 0, seen.errors);
    await ctx.close();
  }

  // ---- 3. the keyboard alone, with no movement asked for --------------------------------------------------------------------
  {
    const { ctx, p, seen } = await open(1280, "?norails", { reducedMotion: "reduce" });
    const at = () => p.evaluate(() => { const e = document.activeElement; return e.dataset.col ? `${e.closest("tr").dataset.line}:${e.dataset.col}` : e.dataset.ap || e.dataset.file || e.id || e.tagName; });
    const tabTo = async (want, most = 60) => { for (let i = 0; i < most; i++) { await p.keyboard.press("Tab"); if ((await at()) === want) return true; } return false; };
    ok("keys: Tab reaches the file chooser first, then the sample", (await tabTo("ap-file", 3)) && (await tabTo("sample", 4)));
    await p.keyboard.press("Enter");
    await p.waitForSelector("tr.ap-row[data-line='7']");
    ok("keys: Tab reaches the first cell of the first row", await tabTo("1:supplier", 6));
    await p.keyboard.press("ArrowRight"); await p.keyboard.press("ArrowRight"); await p.keyboard.press("ArrowDown");
    ok("keys: the arrows move between cells", (await at()) === "2:deliverable", await at());
    await p.keyboard.press("End"); await p.keyboard.press("ArrowLeft");
    ok("keys: End and Left reach the exception", (await at()) === "2:exception", await at());
    await p.keyboard.press("Enter");
    ok("keys: Enter opens the cell's evidence", (await p.locator("tr.ap-ev [data-ev=exception]").count()) === 1);
    ok("no movement asked for: the evidence appears with none", (await p.evaluate(() => getComputedStyle(document.querySelector("tr.ap-ev > td > div")).animationName)) === "none");
    await p.keyboard.press("Escape");
    ok("keys: Escape shuts it and the focus stays on the cell", (await p.locator("tr.ap-ev").count()) === 0 && (await at()) === "2:exception", await at());
    ok("keys: Tab reaches the name, the role and Approve", (await tabTo("ap-by")) && (await p.keyboard.type("Dana Reyes"), await tabTo("ap-role", 1)) && (await p.keyboard.type("controller"), await tabTo("approve", 1)));
    await p.keyboard.press("Enter");
    await p.waitForSelector("tr.ap-row[data-approved]");
    ok("keys: Enter approves, and the focus moves to the statement's download", (await said(p, "approved")) === "Approved 2 lines, 650.00. 5 exceptions stay open." && (await at()) === "csv", [await said(p, "approved"), await at()]);
    ok("keys: every control on the screen can be reached and shows where the focus is", await p.evaluate(() => [...document.querySelectorAll(".approver button, .approver a, .approver input, .approver textarea, .approver summary")]
      .filter((e) => e.offsetParent !== null && !e.disabled).every((e) => e.tabIndex >= 0)));
    ok("no error on the page", seen.errors.length === 0 && seen.strangers.length === 0, seen);
    await ctx.close();
  }

  // ---- 4. a build with no payment module: the page asks its own host for it once and offers nothing ----------------------------
  {
    const { ctx, p, seen } = await open(1280, "");
    await p.click("[data-ap=sample]"); await p.waitForSelector("tr.ap-row[data-line='7']");
    await p.fill("#ap-by", "Dana Reyes"); await p.fill("#ap-role", "controller"); await p.click("[data-ap=approve]");
    await p.waitForSelector("tr.ap-row[data-approved]");
    if (existsSync(join(web, "recall.js"))) {       // what `knos recall exception --json` prints, dropped on the page, is drawn by web/recall.js
      const row = { kind: "knos.recall/1", terms: "ab".repeat(32), reason: "disputed", supplier: "", seen: 3, endings: { accepted_on_appeal: 2, corrected_and_passed: 0, refused: 1 }, most_often: "accepted_on_appeal",
        seconds: { median: 7200, fastest: 60, slowest: 86400, timed: 3 }, evidence: ["evl_1"], open: 0, said: "Seen 3 times: 2 accepted on appeal, 1 refused.", words: "2 accepted on appeal, 1 refused", cases: [], terms_text_kept: true, memory: true };
      await dropFiles(p, [["recall.json", JSON.stringify(row)]]); await p.waitForSelector("[data-ap=recall]:not([hidden]) .rc-row");
      ok("a recall row dropped on the page is drawn in the queue's place for it", (await p.$$eval("[data-ap=recall] .rc-row", (x) => x.length)) === 1 && seen.errors.length === 0, seen.errors);
      await dropFiles(p, [["queue.json", JSON.stringify([row, { ...row, reason: "duplicate" }])]]); await p.waitForFunction(() => document.querySelectorAll("[data-ap=recall] .rc-row").length === 2);
      ok("a list of them (`knos recall queue --json`) is drawn row by row", true);
    }
    if (!existsSync(join(web, "rails.js"))) {
      await p.waitForFunction(() => performance.getEntriesByType("resource").some((r) => r.name.endsWith("/rails.js")));
      ok("no web/rails.js in this tree: the payment file is not offered, and nothing breaks", !(await p.isVisible("[data-ap=pay]")) && seen.errors.length === 0 && seen.strangers.length === 0, seen);
    } else {
      await p.waitForSelector("[data-ap=pay]:not([hidden])");
      // web/rails.js draws the form itself (a payment file needs each supplier's account): the page hands it the statement and the approval
      // web/rails.js draws the form itself (a payment file needs each supplier's account): the page hands it the statement and the approval
      await p.waitForSelector("[data-ap=pay] [data-rails-said]");
      // the sample states its currency (USD): approved, its two agreed lines make one transfer, and the bank file is saved
      await p.waitForSelector("[data-ap=pay] [data-rails-form]");
      ok("web/rails.js is in this tree: it is shown after approval, and the sample, in USD, gets one transfer of its two agreed lines",
        (await p.innerText("[data-ap=pay] [data-rails-said]")) === "1 transfer ready." && !(await p.isVisible("[data-ap=pay] [data-rails-files]")) && (await p.innerText("[data-ap=pay] [data-rails-form] td.k-num")).startsWith("650.00 USD"));
      await p.fill("[data-ap=pay] input[name=name]", "Example Buyer (made up)"); await p.fill("[data-ap=pay] input[name=account]", "GB33BUKB20201555555555");
      for (const box of await p.$$("[data-ap=pay] input[name^=payee]")) await box.fill("DE89370400440532013000");
      const sampled = await downloaded(p, () => p.click("[data-ap=pay] [data-rails-form] button[type=submit]"));
      ok("  the sample's bank file: a pain.001 of 650.00 USD to the made-up supplier", /\.pain001\.xml$/.test(sampled.name) && sampled.text.includes('<InstdAmt Ccy="USD">650.00</InstdAmt>')
        && sampled.text.includes("<Nm>Example Agents Ltd (made up)</Nm>") && (await p.innerText("[data-ap=pay] [data-rails-said]")) === "Saved. Upload it to your bank.", [sampled.name, sampled.text.slice(0, 300)]);
      // a statement that states no currency gets its reason and no form: the sample's own, made with no currency
      const plain = await fromShadow({ invoice: SAMPLE_INVOICE, answers: SAMPLE_BOOK }, {});
      await p.reload(); await p.waitForFunction(() => window.drawn);
      await dropFiles(p, [["invoice.csv", SAMPLE_INVOICE], ["front_door.json", JSON.stringify(plain)]]); await p.waitForSelector("tr.ap-row[data-line='7']");
      await p.fill("#ap-by", "Dana Reyes"); await p.fill("#ap-role", "controller"); await p.click("[data-ap=approve]");
      await p.waitForSelector("[data-ap=pay] [data-rails-said]:not(:empty)");
      ok("  a statement with no currency: its reason, and no file", (await p.innerText("[data-ap=pay] [data-rails-said]")) === "A bank moves a currency with a three-letter code; this statement states no currency. Test money is paid on devnet (--rail usdc), never by bank."
        && !(await p.$("[data-ap=pay] [data-rails-form]")), await p.innerText("[data-ap=pay] [data-rails-said]"));
      await p.reload(); await p.waitForFunction(() => window.drawn);
      await dropFiles(p, [["invoice.csv", INVOICE], ["sept.json", read("sept.json")]]); await p.waitForSelector("tr.ap-row[data-line='5']");
      await p.fill("#ap-by", "Dana Reyes"); await p.fill("#ap-role", "controller"); await p.click("[data-ap=approve]");
      await p.waitForSelector("[data-ap=pay] [data-rails-form]");
      await p.fill("[data-ap=pay] input[name=name]", "Northwind Ltd"); await p.fill("[data-ap=pay] input[name=account]", "GB33BUKB20201555555555");
      for (const box of await p.$$("[data-ap=pay] input[name^=payee]")) await box.fill("DE89370400440532013000");
      const pain = await downloaded(p, () => p.click("[data-ap=pay] [data-rails-form] button[type=submit]"));
      ok("a statement in a currency: the file it writes is a pain.001 naming the payer and the day of the approval", /\.pain001\.xml$/.test(pain.name) && pain.text.includes("<Nm>Northwind Ltd</Nm>") && pain.text.includes("<IBAN>GB33BUKB20201555555555</IBAN>")
        && pain.text.includes("<Dt>2026-10-07</Dt>") && pain.text.includes("pain.001.001.09") && seen.errors.length === 0, [pain.name, pain.text.slice(0, 300), seen.errors]);
    }
    await ctx.close();
  }
  await browser.close(); server.close();
}
if (process.argv[2] === "page") await page();
console.log(failed ? `${failed} failed` : "all passed");
process.exit(failed ? 1 : 0);
