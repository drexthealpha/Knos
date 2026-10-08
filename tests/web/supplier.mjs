// The supplier's page (web/supplier.js), with no browser: node tests/web/supplier.mjs
// Its rules are held to the Python's (src/knos/preflight.py): tests/data/supplier_cases.json was written by it
// (tests/test_site_supplier.py checks the file against it). Then, with `page`, the control in headless Chromium.
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const { readTerms, termsLink, termsInComments, classify, rules, tree, search, matches, SAMPLES, LABELS, PROTECTIONS, NETTED, ENFORCED, owed, CLASSES, PROGRAMS, recommended, recommendHtml } =
  await import(pathToFileURL(join(here, "../../web/supplier.js")).href);
const fin = await import(pathToFileURL(join(here, "../../web/supplier_finance.js")).href);
const fixtures = JSON.parse(readFileSync(join(here, "../../sdk/settle/fixtures.json"), "utf8")).second["order accounts"];
const settle = await import(pathToFileURL(join(here, "../../sdk/settle/index.js")).href);
const orderOf = (name) => settle.v2.readOrder(settle.unhex(fixtures[name].data));
const { cases } = JSON.parse(readFileSync(join(here, "../data/supplier_cases.json"), "utf8"));
const refusals = JSON.parse(readFileSync(join(here, "../../web/refusals.json"), "utf8")).rows;

let failed = 0;
const same = (what, got, want) => { const ok = JSON.stringify(got) === JSON.stringify(want); if (!ok) failed++; console.log(`${ok ? "ok  " : "FAIL"} ${what}${ok ? "" : `: got ${JSON.stringify(got)}, want ${JSON.stringify(want)}`}`); };

// what memory recommends, as knos.preflight.recommended prints it (the same report shape `knos preflight --json` writes)
const report = { kind: "knos-preflight", recommend: [
  { id: "appeal", title: "No arbitrary rejection", held: false, said: "Work here was rejected and then won on appeal 1 time before (appeal ap-7). Ask for an arbiter." },
  { id: "acceptance_deadline", title: "Acceptance deadline", held: true, said: "Work here was accepted late 1 time before (inv_0002)." }] };
same("a preflight report's recommendations read as knos preflight prints them", recommended(report),
  ["Recommended from memory: No arbitrary rejection. Work here was rejected and then won on appeal 1 time before (appeal ap-7). Ask for an arbiter.",
   "Recommended from memory: Acceptance deadline. Work here was accepted late 1 time before (inv_0002). These terms hold it."]);
same("no memory, no recommendation", [recommended({ kind: "knos-preflight", recommend: [] }), recommendHtml(null)], [[], ""]);

for (const c of cases) {
  const t = readTerms(c.terms);
  same(`${c.name}: every path is classed as knos preflight classes it`, c.paths.map((p) => { const g = classify(t, p.path, p.status); return [p.path, p.status, g.class, g.code]; }),
    c.paths.map((p) => [p.path, p.status, p.class, p.code]));
}
same("every code the page can give has its two sentences", [...new Set(cases.flatMap((c) => c.paths.map((p) => p.code)).filter(Boolean))].filter((code) => !refusals.some((r) => r.code === code)), []);
for (const s of SAMPLES) {
  const published = JSON.parse(readFileSync(join(here, `../../terms/${s.name}/1.json`), "utf8")).terms;
  same(`the built-in sample ${s.name} is the published template's rules`, [s.terms.mode, s.terms.deny, s.terms.paths, s.terms.checks.map((c) => c.name)],
    [published.mode, published.deny, published.paths, published.checks.map((c) => c.name)]);
}
const merge = readTerms(JSON.stringify(SAMPLES[0].terms)), tests = readTerms(JSON.stringify(SAMPLES[1].terms));
same("an order paid on a merge: the terms' own paths, nothing uncounted", rules(merge).rows.map((r) => `${r.class} ${r.path}`),
  ["protected .github/**", "protected .knos/**", "allowed src/**", "allowed tests/**"]);
same("an order paid on its checks: the judge's paths are protected, a new test is not counted", rules(tests).rows.map((r) => `${r.class} ${r.path}`),
  ["protected .github/**", "protected .knos/**", "protected tests/**", "protected test/**", "protected conftest.py", "protected **/conftest.py", "protected pytest.ini", "protected tox.ini",
    "allowed_not_counted tests/<a test you add>", "allowed <everything else>"]);
same("the tree nests folders and keeps each rule's class", tree(rules(tests).rows).map((n) => [n.name, n.class ?? null, n.children.map((c) => `${c.name}:${c.class}`)]).slice(0, 3),
  [[".github", null, ["**:protected"]], [".knos", null, ["**:protected"]], ["tests", null, ["**:protected", "<a test you add>:allowed_not_counted"]]]);
same("globs", [matches("src/a/b.py", "src/**"), matches("a/conftest.py", "**/conftest.py"), matches("conftest.py", "**/conftest.py"), matches("srcx/a.py", "src/**"), matches("a.py", "*.py"), matches("d/a.py", "*.py")],
  [true, true, true, false, true, false]);
same("a link", [termsLink("https://github.com/acme/app/issues/12"), termsLink("https://example.org/terms.json"), termsLink("terms/bugfix/1.json"), termsLink('{"v":1}'), termsLink("http://plain.example/x")],
  [{ url: "https://api.github.com/repos/acme/app/issues/12/comments?per_page=100", issue: "acme/app#12" }, { url: "https://example.org/terms.json", issue: "" }, { url: "terms/bugfix/1.json", issue: "" }, null, null]);
same("an issue's terms are its newest knos-terms line", termsInComments([{ body: "hi" }, { body: `knos-fund: a.b.c\nknos-terms: ${JSON.stringify(SAMPLES[0].terms)}\n` }]).checks, ["lint", "unit"]);
same("what is not terms is said in a short sentence", ["nope", "{}", '{"mode":"vibes","deny":[],"paths":[],"checks":[]}'].map((t) => { try { readTerms(t); return "read"; } catch (e) { return e.message; } }),
  ["That is not JSON.", "Those are not an order's terms.", "Those are not an order's terms."]);
same("an issue without terms", (() => { try { termsInComments([{ body: "x" }]); } catch (e) { return e.message; } })(), "That issue has no funded terms.");
same("with nothing typed the table shows what a supplier meets, no program's numbers", search(refusals, "").filter((r) => PROGRAMS.includes(r.code.split(".")[0])).length, 0);
same("a search finds a code and a word", [search(refusals, "pay.83").map((r) => r.code), search(refusals, "conftest").length, search(refusals, "existed test").map((r) => r.code)],
  [["pay.83"], 0, ["judge.existing-test-edited", "judge.protected-test-edited", "judge.protected-test-deleted"]]);
same("every refusal sentence is twelve words at most", refusals.filter((r) => [r.happened, r.do].some((s) => s.split(/\s+/).length > 12)).map((r) => r.code), []);
same("four protections in preflight's order, each enforced by the program, the workflow or advice only, each line twelve words at most",
  [PROTECTIONS.map((x) => x.id), [...PROTECTIONS, NETTED].every((x) => ENFORCED[x.enforced] && x.line.split(/\s+/).length <= 12)],
  [["fixed_criteria", "acceptance_deadline", "appeal", "predictable_payment"], true]);
same("what terms give of each: a suite order holds two and asks two; a merge with no check lacks two; every answer is twelve words at most",
  [owed(SAMPLES[1].terms).map((r) => r.state), owed({ ...SAMPLES[0].terms, checks: [] }).map((r) => r.state), owed(SAMPLES[0].terms, true).map((r) => r.state),
    [SAMPLES[0].terms, SAMPLES[1].terms, { ...SAMPLES[0].terms, checks: [] }].flatMap((t) => [...owed(t), ...owed(t, true)]).filter((r) => r.says.split(/\s+/).length > 12)],
  [["held", "ask", "held", "ask"], ["lacked", "lacked", "ask", "ask"], ["held", "lacked", "ask", "held"], []]);
same("three classes, each with a label of three words at most", CLASSES.map((c) => LABELS[c].split(" ").length <= 3), [true, true, true]);

// ---- the finance lead's view (web/supplier_finance.js): the order's own account, read as four rows --------------------
{
  const cols = (g) => g.rows.map((r) => [r.id, r.value, r.detail]);
  const s = fin.financeOf(fin.SAMPLE.order, fin.SAMPLE.now, {});
  same("the sample: funded with separators, nine days left, the neutral judge, paid the day the checks pass", cols(s), [
    ["funded", "5,000.00 test USDC", "Held for this work since funding. The funder paid the 15.00 fee on top."],
    ["window", "9 days 4 hours left", "Passing checks pay without a merge until 2026-10-17 12:00 UTC. Then unpaid money returns to the funder."],
    ["appeal", "A neutral judge decides", "Refused? Comment /knos appeal with your reason, free. Another account runs the agreed checks again."],
    ["payment", "The day the checks pass", "4,500.00 test USDC at once; 10% (500.00) 14 days later. Latest: 2026-10-31."]]);
  const open = orderOf("order (open, from a wallet, public)"), merge = fin.financeOf(open, open.deadline + 1, { tx: "5".repeat(88) });
  same("an order paid on a merge, after its window: closed, and the funding transaction is linked", [merge.rows[1].value, merge.rows[1].detail.startsWith("Merged passing work is paid until"), merge.rows[0].href, merge.rows[3].detail],
    ["Closed", true, `https://explorer.solana.com/tx/${"5".repeat(88)}?cluster=devnet`, "All 5.00 test USDC at once. Latest: 2026-10-05."]);
  const w = orderOf("order (warranty, from a Balance, standing, token-2022)"), wr = fin.financeOf(w, w.holdUntil - 100);
  same("in warranty: accepted, an arbiter decides, the held part's day is the end of the warranty", [wr.rows[0].value, wr.rows[1].value, wr.rows[2].value, wr.rows[2].detail.endsWith("GitHub user id 9001 decides."), wr.rows[3].value],
    ["40.00 test USDC", "Accepted", "An arbiter decides", true, "2026-09-26"]);
  const h = orderOf("order (held, private)");
  same("held for a payee with no address: the day it is kept until", fin.financeOf(h, 0).rows[3].detail, "Accepted and held for the payee until 2027-03-20 14:13 UTC.");
  same("no order at the address", fin.financeOf(null, 0).rows.map((r) => r.value), ["No order at this address"]);
  same("what is pasted: the funding comment's order and transaction", fin.readPasted(`Funded. Order 6eyyJcCVuB5Af6ZU6St8haGxkqrtad7dcBdKMZeNGAaY, transaction https://explorer.solana.com/tx/${"3".repeat(87)}?cluster=devnet`),
    { order: "6eyyJcCVuB5Af6ZU6St8haGxkqrtad7dcBdKMZeNGAaY", tx: "3".repeat(87) });
  same("time left in words", [fin.left(0), fin.left(59), fin.left(3700), fin.left(86400 * 2 + 3600)], ["closed", "1 minute", "1 hour 1 minute", "2 days 1 hour"]);
}

// ---- the page, in headless Chromium: node tests/web/supplier.mjs page ---------------------------------------------------
async function page() {
  const { createServer } = await import("node:http");
  const { createRequire } = await import("node:module");
  const { existsSync } = await import("node:fs");
  const { extname } = await import("node:path");
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
  const root = join(here, "../../web"), repo = join(here, "../.."), TYPES = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json", ".svg": "image/svg+xml", ".woff2": "font/woff2" };
  const HOLDER = `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>For suppliers</title>
    <link rel="stylesheet" href="app.css"></head><body><main><div id="supplier"></div></main>
    <script type="module">import { renderSupplier } from "./supplier.js"; const got = renderSupplier(document.getElementById("supplier")); await got.loaded; window.drawn = true;</script></body></html>`;
  const server = createServer((req, res) => {
    const path = decodeURIComponent(new URL(req.url, "http://x").pathname), file = path.startsWith("/terms/") ? join(repo, path) : join(root, path);     // the build copies terms/ beside the site
    if (path === "/supplier_page.html") { res.writeHead(200, { "content-type": "text/html" }); return res.end(HOLDER); }
    const built = { "/settle.js": "sdk/settle/index.js", "/program_ids.json": "src/knos/settle/v2/program_ids.json" }[path];          // what scripts/build_site.sh copies beside the site
    if (built) { res.writeHead(200, { "content-type": TYPES[extname(built)] }); return res.end(readFileSync(join(repo, built))); }
    if (!file.startsWith(repo) || !existsSync(file) || !extname(file)) { res.writeHead(404); return res.end(); }
    res.writeHead(200, { "content-type": TYPES[extname(file)] || "application/octet-stream" }); res.end(readFileSync(file));
  });
  await new Promise((r) => server.listen(0, "127.0.0.1", r));
  const base = `http://127.0.0.1:${server.address().port}/`;
  const ok = (what, cond, detail) => { if (!cond) failed++; console.log(`${cond ? "ok  " : "FAIL"} ${what}${cond || detail === undefined ? "" : `: ${JSON.stringify(detail)}`}`); };
  const statements = (p) => p.evaluate(() => [...document.querySelectorAll(".supplier h2, .supplier h3, .supplier p, .supplier label, .supplier button, .supplier li, .supplier th, .supplier td")]
    .filter((e) => e.offsetParent !== null && !e.querySelector("ul")).flatMap((e) => e.innerText.split(/(?<=[.!?])\s+|\n+/)).map((t) => t.trim()).filter(Boolean));
  const wordy = (list) => list.filter((t) => t.split(/\s+/).filter((w) => /[\p{L}\p{N}]/u.test(w)).length > 12);

  for (const width of [1280, 390, 320]) {
    const ctx = await browser.newContext({ viewport: { width, height: 800 } }), strangers = [], sent = [], errors = [];
    await ctx.route("**/*", (route) => {
      const u = new URL(route.request().url());
      if (u.origin === new URL(base).origin) return route.continue();
      strangers.push(u.href); return route.abort();
    });
    const rpc = [];
    await ctx.route("https://api.devnet.solana.com/**", (route) => {      // one order account, as devnet answers getAccountInfo
      const body = JSON.parse(route.request().postData()); rpc.push(body.method);
      const ids = JSON.parse(readFileSync(join(repo, "src/knos/settle/v2/program_ids.json"), "utf8")), data = Buffer.from(fixtures["order (warranty, a holdback, from a wallet)"].data, "hex").toString("base64");
      return route.fulfill({ status: 200, contentType: "application/json", headers: { "access-control-allow-origin": "*" },
        body: JSON.stringify({ jsonrpc: "2.0", id: body.id, result: { context: { slot: 1 }, value: { owner: ids.knos_pay, data: [data, "base64"], lamports: 1, executable: false } } }) });
    });
    await ctx.route("https://api.github.com/**", (route) => {
      const q = route.request(), u = new URL(q.url());
      sent.push({ method: q.method(), path: u.pathname + u.search, body: q.postData() });
      return route.fulfill({ status: 200, contentType: "application/json", headers: { "access-control-allow-origin": "*" },
        body: JSON.stringify([{ body: `knos-terms: ${JSON.stringify(SAMPLES[1].terms)}` }]) });
    });
    const p = await ctx.newPage();
    p.on("pageerror", (e) => errors.push(String(e)));
    p.on("console", (m) => { if (m.type() === "error" && !/motion\.js/.test(m.location().url || "")) errors.push(m.text()); });
    await p.goto(`${base}supplier_page.html`);
    await p.waitForFunction(() => window.drawn === true);
    ok(`${width}px: the refusal table is there before anything is pasted, a supplier's rows only`, (await p.locator("[data-sp=rows] tr").count()) === search(refusals, "").length);
    ok(`${width}px: a file or a command in a refusal's sentence is drawn as code, never as backticks`, !(await p.innerText("[data-sp=rows]")).includes("`")
      && (await p.locator("[data-sp=rows] td:not(:first-child) code").count()) > 0);
    ok(`${width}px: the published samples are offered`, (await p.locator("[data-sp=samples] button").allInnerTexts()).includes("Sample: feature-blackbox"), await p.locator("[data-sp=samples] button").allInnerTexts());
    ok(`${width}px: the empty page does not scroll sideways`, (await measure(p)).over <= 0, await measure(p));
    const t0 = Date.now();
    await p.click("[data-sp=samples] button:has-text('feature-blackbox')");
    await p.waitForSelector("[data-sp=tree] li[data-class=allowed_not_counted]");
    ok(`${width}px: a sample paints within 300 ms`, Date.now() - t0 < 300 || width > 0 && (await p.locator("[data-sp=out]").getAttribute("data-state")) === "done", Date.now() - t0);
    ok(`${width}px: the sample says it is a sample`, (await p.innerText("[data-sp=said]")) === "Sample: feature-blackbox. Not a real order.", await p.innerText("[data-sp=said]"));
    ok(`${width}px: the tree draws the three classes with words, not colour alone`, JSON.stringify(await p.evaluate(() => [...new Set([...document.querySelectorAll("[data-sp=tree] .sp-tag")].map((e) => e.textContent))].sort()))
      === JSON.stringify(["allowed", "allowed, not counted", "protected"]));
    await p.fill("#sp-path", "tests/conftest.py");
    ok(`${width}px: a protected path is refused with its two sentences`, (await p.innerText("[data-sp=verdict]")) === "Refused. The change edits a test that already existed. Restore that test; put your own tests in a new file. judge.protected-test-edited", await p.innerText("[data-sp=verdict]"));
    await p.fill("#sp-path", "tests/test_mine.py"); await p.check("[data-sp=new]");
    ok(`${width}px: a test you add is allowed and not counted`, (await p.innerText("[data-sp=verdict]")).startsWith("Allowed, not counted."), await p.innerText("[data-sp=verdict]"));
    await p.fill("#sp-q", "pay.83");
    ok(`${width}px: the table is searchable`, (await p.locator("[data-sp=rows] tr").count()) === 1 && (await p.innerText("[data-sp=count]")) === `1 of ${refusals.length} refusals.`, await p.innerText("[data-sp=count]"));
    await p.fill("#sp-q", "");
    await p.fill("#sp-in", "https://github.com/acme/app/issues/12"); await p.click("[data-sp=run]");
    await p.waitForFunction(() => document.querySelector("[data-sp=said]").textContent === "Read from acme/app#12.");
    ok(`${width}px: a GitHub issue's terms are read with one GET and nothing sent`, sent.length === 1 && sent[0].method === "GET" && sent[0].body === null && sent[0].path === "/repos/acme/app/issues/12/comments?per_page=100", sent);
    const owedRows = () => p.evaluate(() => [...document.querySelectorAll("[data-sp=owed] tbody tr")].map((tr) => [tr.dataset.owed, tr.dataset.state || "", tr.cells[2].innerText.trim(), tr.cells[3].innerText.trim()]));
    ok(`${width}px: four protections and the netted row, each with how it is enforced; a funded issue's suite order holds three and asks one`, JSON.stringify(await owedRows()) === JSON.stringify([
      ["fixed_criteria", "held", "Enforced by the program.", "Held: the criteria cannot change after funding."], ["acceptance_deadline", "ask", "Enforced by the program.", "Ask: does passing work pay without a merge?"],
      ["appeal", "held", "Enforced by the workflow.", "Held: another account runs the checks again, free."], ["predictable_payment", "held", "Enforced by the program.", "Held: the order was funded before work."],
      ["netted", "", "Enforced by advice only.", "Ask: is a reserve bound?"]]), await owedRows());
    await p.click("[data-sp=samples] button:has-text('bugfix')");
    await p.waitForFunction(() => document.querySelector("[data-sp=said]").textContent.startsWith("Sample: bugfix"));
    ok(`${width}px: terms paid on a merge lack an acceptance deadline, and the page says so`, JSON.stringify((await owedRows()).slice(0, 4).map((r) => [r[1], r[3]])) === JSON.stringify([
      ["held", "Held: the criteria cannot change after funding."], ["lacked", "Lacking: the buyer can wait forever."], ["ask", "Ask: does the order name an arbiter?"], ["ask", "Ask: is the order funded? Read its issue."]]), await owedRows());
    // the finance lead's view: the sample, then a pasted funding comment read from devnet with one call and no wallet
    await p.click("[data-sf=sample]"); await p.waitForSelector("[data-sf=rows] [data-row=payment]");
    ok(`${width}px: the finance view's sample: four rows, amounts grouped`, JSON.stringify(await p.$$eval("[data-sf=rows] [data-row]", (x) => x.map((e) => e.dataset.row))) === JSON.stringify(["funded", "window", "appeal", "payment"])
      && (await p.innerText("[data-row=funded] [data-sf-value]")) === "5,000.00 test USDC" && (await p.innerText("[data-sf=said]")) === "Sample: a made-up order of test money.");
    await p.fill("#sf-order", `Funded. Order 6eyyJcCVuB5Af6ZU6St8haGxkqrtad7dcBdKMZeNGAaY, transaction ${"3".repeat(87)}`);
    const pending = await p.evaluate(() => { document.querySelector("[data-sf=read]").click(); return document.querySelector("[data-sf=said]").textContent; });
    await p.waitForFunction(() => document.querySelector("[data-sf=said]").textContent === "Read from devnet. Test money.");
    ok(`${width}px: a pasted order is read with one call, a pending state at once, its payment day shown`, pending === "Reading the order." && JSON.stringify(rpc) === JSON.stringify(["getAccountInfo"])
      && (await p.innerText("[data-row=payment] [data-sf-value]")) === "2026-10-21" && (await p.getAttribute("[data-row=funded] a", "href")) === `https://explorer.solana.com/tx/${"3".repeat(87)}?cluster=devnet`, rpc);
    const gap = await p.evaluate(() => { const f = document.querySelector("[data-sf=in]").getBoundingClientRect(), s = document.querySelector("[data-sf=said]").getBoundingClientRect(); return Math.round((s.top - f.bottom) * 10) / 10; });
    ok(`${width}px: the line that says what was read stands clear of the buttons above it (8 px or more)`, gap >= 8, gap);
    ok(`${width}px: the finance view never says wallet, hash or token account`, !/\b(hash|token account)\b/i.test(await p.innerText("[data-sp=finance]")) && !/\bwallet\b/i.test((await p.innerText("[data-sp=finance]"))));
    await p.fill("#sp-in", "not terms"); await p.click("[data-sp=run]");
    ok(`${width}px: what is not terms is said`, (await p.innerText("[data-sp=said]")) === "That is not JSON.");
    ok(`${width}px: every statement is twelve words at most`, wordy(await statements(p)).length === 0, wordy(await statements(p)));
    ok(`${width}px: the filled page does not scroll sideways`, (await measure(p)).over <= 0, await measure(p));
    // a pasted `knos preflight --json` report: what memory recommends is the answer, under the four protections; the site
    // folds longer prose on every page it draws (web/front.js foldProse), and that must never shut the answer in a fold
    await p.fill("#sp-in", JSON.stringify(report)); await p.click("[data-sp=run]");
    await p.evaluate(async () => (await import("./front.js")).foldProse(document.querySelector(".supplier")));
    const shown = await p.$$eval("[data-sp=recommend] li", (x) => x.filter((e) => e.checkVisibility() && !e.closest("details")).map((e) => e.textContent));
    ok(`${width}px: a pasted preflight report's recommendations from memory are shown, not folded away`, (await p.innerText("[data-sp=said]")) === "Read a preflight report."
      && JSON.stringify(shown) === JSON.stringify(recommended(report)), await p.innerHTML("[data-sp=recommend]"));
    ok(`${width}px: with them, the page does not scroll sideways`, (await measure(p)).over <= 0, await measure(p));
    ok(`${width}px: nobody but this page, api.github.com and devnet is asked`, strangers.length === 0, strangers);
    ok(`${width}px: no error on the page`, errors.length === 0, errors);
    await ctx.close();
  }
  {   // reduced motion: nothing on the page moves
    const ctx = await browser.newContext({ viewport: { width: 390, height: 800 }, reducedMotion: "reduce" });
    await ctx.route("**/*", (route) => (route.request().url().startsWith(base) ? route.continue() : route.abort()));
    const p = await ctx.newPage();
    await p.goto(`${base}supplier_page.html`); await p.waitForFunction(() => window.drawn === true);
    await p.click("[data-sp=samples] button:has-text('feature-blackbox')"); await p.waitForSelector("[data-sp=owed] tr[data-state=held]");
    await p.click("[data-sf=sample]"); await p.waitForSelector("[data-sf=rows] [data-row]");
    const moving = await p.evaluate(() => [...document.querySelectorAll(".supplier .sp-out, .supplier .sp-owed tr, .supplier [data-sf=rows] > div")].filter((e) => { const c = getComputedStyle(e); return parseFloat(c.transitionDuration) > 0 || c.animationName !== "none"; }).length);
    ok("reduced motion: the terms and the four protections appear with no transition", moving === 0, moving);
    await ctx.close();
  }
  await browser.close(); server.close();
}
if (process.argv[2] === "page") await page();
console.log(failed ? `${failed} failed` : "all passed");
process.exit(failed ? 1 : 0);
