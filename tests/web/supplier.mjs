// The supplier's page (web/supplier.js), with no browser: node tests/web/supplier.mjs
// Its rules are held to the Python's (src/knos/preflight.py): tests/data/supplier_cases.json was written by it
// (tests/test_site_supplier.py checks the file against it). Then, with `page`, the control in headless Chromium.
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const { readTerms, termsLink, termsInComments, classify, rules, tree, search, matches, SAMPLES, LABELS, CLASSES, PROGRAMS } =
  await import(pathToFileURL(join(here, "../../web/supplier.js")).href);
const { cases } = JSON.parse(readFileSync(join(here, "../data/supplier_cases.json"), "utf8"));
const refusals = JSON.parse(readFileSync(join(here, "../../web/refusals.json"), "utf8")).rows;

let failed = 0;
const same = (what, got, want) => { const ok = JSON.stringify(got) === JSON.stringify(want); if (!ok) failed++; console.log(`${ok ? "ok  " : "FAIL"} ${what}${ok ? "" : `: got ${JSON.stringify(got)}, want ${JSON.stringify(want)}`}`); };

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
same("three classes, each with a label of three words at most", CLASSES.map((c) => LABELS[c].split(" ").length <= 3), [true, true, true]);

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
    await p.fill("#sp-in", "not terms"); await p.click("[data-sp=run]");
    ok(`${width}px: what is not terms is said`, (await p.innerText("[data-sp=said]")) === "That is not JSON.");
    ok(`${width}px: every statement is twelve words at most`, wordy(await statements(p)).length === 0, wordy(await statements(p)));
    ok(`${width}px: the filled page does not scroll sideways`, (await measure(p)).over <= 0, await measure(p));
    ok(`${width}px: nobody but this page and api.github.com is asked`, strangers.length === 0, strangers);
    ok(`${width}px: no error on the page`, errors.length === 0, errors);
    await ctx.close();
  }
  await browser.close(); server.close();
}
if (process.argv[2] === "page") await page();
console.log(failed ? `${failed} failed` : "all passed");
process.exit(failed ? 1 : 0);
