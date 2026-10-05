// Shadow mode as the site computes it (web/shadow.js), with no browser: node tests/web/shadow.mjs
// Every case of tests/data/shadow_cases.json was answered by the Python (src/knos/shadow.py; tests/test_shadow.py
// checks the file against it). The site's functions must write the same bytes from the same invoice and the same
// answers from GitHub: the statement's JSON, its CSV and its sha256. Then the reader: what it asks, of whom, and
// that it stops when GitHub's budget is spent.
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const { parse, gather, statement, canonical, digest, asCsv, recorded, githubReader, cents, money, NOTE, LABELS, CLASSES, SAMPLE, LINE_COSTS } =
  await import(pathToFileURL(join(here, "../../web/shadow.js")).href);
const { book, cases } = JSON.parse(readFileSync(join(here, "../data/shadow_cases.json"), "utf8"));

let failed = 0;
const same = (what, got, want) => { const ok = JSON.stringify(got) === JSON.stringify(want); if (!ok) failed++; console.log(`${ok ? "ok  " : "FAIL"} ${what}${ok ? "" : `: got ${JSON.stringify(got)}, want ${JSON.stringify(want)}`}`); };

for (const c of cases) {
  const invoice = parse(c.invoice), st = statement(invoice, await gather(invoice, recorded(book)));
  same(`${c.name}: the statement's bytes`, canonical(st), c.json);
  same(`${c.name}: the CSV`, asCsv(st), c.csv);
  same(`${c.name}: the sha256`, await digest(st), c.sha256);
}
same("the note is the Python's, in every statement", JSON.parse(cases[0].json).note, NOTE);
same("amounts", ["1,200.50", "1.200,50", "$1200", "12,5", "USD 3", "-4.00", ""].map((t) => { const v = cents(t); return v === null ? null : money(v); }),
  ["1200.50", "1200.50", "1200.00", "12.50", "3.00", "-4.00", null]);
same("an amount is never guessed", ["0.125", "1,2,3", "twelve"].map((t) => { try { cents(t); return "read"; } catch { return "refused"; } }), ["refused", "refused", "refused"]);
same("a line whose amount cannot be read is named", (() => { try { parse("pr,amount\nacme/app#1,1\nacme/app#2,0.125\n"); } catch (e) { return e.message; } })(), "line 2: the amount 0.125 could not be read");
same("every class has a label of four words at most", CLASSES.map((c) => LABELS[c].split(" ").length <= 4), CLASSES.map(() => true));
same("the sample is examples/shadow/sample.csv", SAMPLE, readFileSync(join(here, "../../examples/shadow/sample.csv"), "utf8"));

// the reader: GitHub's public API with no login, GET only, nothing of the invoice in what it sends
const asked = [];
const answer = (path, left, calm) => {
  const got = Object.prototype.hasOwnProperty.call(book, path) ? book[path] : { __unread: "not found or private" };
  const head = new Headers({ "x-ratelimit-remaining": String(left), "x-ratelimit-limit": "60", "x-ratelimit-reset": "2000" });
  if (got.__unread === "rate limit" && !calm) return new Response("{}", { status: 403, headers: { ...Object.fromEntries(head), "x-ratelimit-remaining": "0" } });
  if (got.__unread) return new Response("{}", { status: got.__unread === "no answer" ? 502 : 404, headers: head });
  return new Response(JSON.stringify(got), { status: 200, headers: head });
};
// `calm`: GitHub never says its limit is spent (the recorded "rate limit" line is then one it does not have)
const web = (start, calm = false) => { let left = start; return async (url, init = {}) => { asked.push({ url, init }); left = Math.max(0, left - 1); return answer(url.slice("https://api.github.com/".length), left, calm); }; };

const main = parse(cases[0].invoice), budget = { remaining: null, limit: 60, reset: null, asked: 0, spent: false };
const live = statement(main, await gather(main, githubReader(web(600, true), budget)));
const offline = JSON.parse(cases[0].json);
same("read over HTTP, the classes are the recording's", live.lines.map((r) => r.class), offline.lines.map((r) => r.class));
same("and so is every line but the one whose reason differs", canonical(live.lines.filter((r) => r.line !== 7)), canonical(offline.lines.filter((r) => r.line !== 7)));
same("only api.github.com is asked, with GET and no body", asked.every((a) => a.url.startsWith("https://api.github.com/repos/") && !a.init.method && !a.init.body), true);
same("no login is sent", asked.every((a) => Object.keys(a.init.headers).join() === "Accept"), true);
same("nothing of the invoice but the pull request's name is in an address", asked.some((a) => /Acme%20Agents|Acme Agents|100\.00|1720|retainer/.test(a.url)), false);
same("a pull request billed twice is asked for once", asked.filter((a) => a.url.endsWith("/repos/acme/app/pulls/1") || a.url.endsWith("/repos/ACME/App/pulls/1")).length, 1);
same("the budget is GitHub's own count", [budget.asked, budget.remaining], [asked.length, 600 - asked.length]);

// a budget too small for the invoice: the lines it covers are judged, the rest are "rate limit", and nothing more is asked
asked.length = 0;
const small = { remaining: 11, limit: 60, reset: 2000, asked: 0, spent: false };
const part = statement(main, await gather(main, githubReader(web(11), small)));
same("with eleven requests left, the first lines are judged", part.lines.slice(0, 3).map((r) => r.class), ["clean", "failed", "not_merged"]);
same("and the rest could not be read: rate limit", [...new Set(part.lines.slice(5).filter((r) => r.pr.includes("#")).map((r) => r.why))], ["rate limit"]);
same(`a line is not started with fewer than ${LINE_COSTS} requests left`, [small.spent, asked.length <= 11, small.remaining >= 0], [true, true, true]);
same("unread lines are counted apart, never in dispute", [part.complete, part.counts.unreadable, part.disputed.lines, part.amounts.unreadable], [false, 7, 4, "1130.50"]);

// ---- the page, in headless Chromium: node tests/web/shadow.mjs page -------------------------------------------------------
// web/ is served as it is, with one page that holds nothing but the control. GitHub is the recording, over HTTP.
// No `playwright` package or no browser: says so and exits 0 (tests/test_site_shadow.py reports that as a skip).
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

  const root = join(here, "../../web"), TYPES = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json", ".svg": "image/svg+xml", ".woff2": "font/woff2" };
  const HOLDER = `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Shadow mode</title>
    <link rel="stylesheet" href="app.css"></head><body><main><div id="shadow"></div></main>
    <script type="module">import { renderShadow } from "./shadow.js"; renderShadow(document.getElementById("shadow")); window.drawn = true;</script></body></html>`;
  const server = createServer((req, res) => {
    const path = decodeURIComponent(new URL(req.url, "http://x").pathname), file = join(root, path);
    if (path === "/shadow_page.html") { res.writeHead(200, { "content-type": "text/html" }); return res.end(HOLDER); }
    if (!file.startsWith(root) || !existsSync(file) || !extname(file)) { res.writeHead(404); return res.end(); }
    res.writeHead(200, { "content-type": TYPES[extname(file)] || "application/octet-stream" }); res.end(readFileSync(file));
  });
  await new Promise((r) => server.listen(0, "127.0.0.1", r));
  const base = `http://127.0.0.1:${server.address().port}/`;
  const ok = (what, cond, detail) => { if (!cond) failed++; console.log(`${cond ? "ok  " : "FAIL"} ${what}${cond || detail === undefined ? "" : `: ${JSON.stringify(detail)}`}`); };
  const http = cases.find((c) => c.name.includes("over HTTP")), want = JSON.parse(http.json);

  // one visit: `left` is what GitHub says remains this hour
  async function visit(width, left) {
    const ctx = await browser.newContext({ viewport: { width, height: 800 }, acceptDownloads: true }), sent = [], strangers = [], errors = [];
    const cors = { "access-control-allow-origin": "*", "access-control-expose-headers": "x-ratelimit-remaining, x-ratelimit-limit, x-ratelimit-reset, retry-after" };
    await ctx.route("**/*", (route) => {            // registered first, so asked last: nothing but this page and GitHub's API
      const u = new URL(route.request().url());
      if (u.origin === new URL(base).origin || u.protocol === "blob:") return route.continue();
      strangers.push(u.href); return route.abort();
    });
    await ctx.route("https://api.github.com/**", (route) => {
      const q = route.request(), u = new URL(q.url()), path = (u.pathname + u.search).slice(1);
      sent.push({ method: q.method(), path, body: q.postData(), headers: q.headers() });
      const head = (n) => ({ ...cors, "x-ratelimit-remaining": String(n), "x-ratelimit-limit": "60", "x-ratelimit-reset": "2000000000" });
      if (path === "rate_limit") return route.fulfill({ status: 200, contentType: "application/json", headers: head(left), body: JSON.stringify({ resources: { core: { limit: 60, remaining: left, reset: 2000000000 } } }) });
      left = Math.max(0, left - 1);
      const got = Object.prototype.hasOwnProperty.call(book, path) ? book[path] : { __unread: "not found or private" };
      if (got.__unread) return route.fulfill({ status: got.__unread === "no answer" ? 502 : 404, contentType: "application/json", headers: head(left), body: "{}" });
      return route.fulfill({ status: 200, contentType: "application/json", headers: head(left), body: JSON.stringify(got) });
    });
    const p = await ctx.newPage();
    p.on("pageerror", (e) => errors.push(String(e)));
    p.on("console", (m) => { if (m.type() === "error" && !/motion\.js|^https:\/\/api\.github\.com\//.test(m.location().url || "")) errors.push(m.text()); });   // not errors: GitHub's own 404 for a line, and motion.js, another module's, which the page is complete without
    await p.goto(`${base}shadow_page.html`);
    await p.waitForFunction(() => window.drawn === true);
    return { ctx, p, sent, strangers, errors };
  }
  // every statement on the page: a sentence of an element that holds words of its own
  const statements = (p) => p.evaluate(() => [...document.querySelectorAll(".shadow h2, .shadow p, .shadow label, .shadow button, .shadow li, .shadow th, .shadow td")]
    .filter((e) => e.offsetParent !== null && !e.matches(".sh-hash")).flatMap((e) => e.innerText.split(/(?<=[.!?])\s+|\n+/)).map((t) => t.trim()).filter(Boolean));
  const wordy = (list) => list.filter((t) => t.split(/\s+/).filter((w) => /[\p{L}\p{N}]/u.test(w)).length > 12);
  const save = async (p, what) => { const [d] = await Promise.all([p.waitForEvent("download"), p.click(`[data-sh="${what}"]`)]); return [d.suggestedFilename(), readFileSync(await d.path(), "utf8")]; };

  for (const width of [390, 320]) {
    const { ctx, p, sent, strangers, errors } = await visit(width, 60);
    ok(`${width}px: nothing is asked of GitHub before anyone asks`, sent.length === 0, sent);
    ok(`${width}px: the empty control does not scroll sideways`, (await measure(p)).over <= 0, await measure(p));
    ok(`${width}px: every label is twelve words at most`, wordy(await statements(p)).length === 0, wordy(await statements(p)));
    await p.fill(".shadow textarea", http.invoice);
    await p.click('[data-sh="run"]');
    await p.waitForSelector('[data-sh="hash"]');
    const steps = await p.$$eval(".shadow .k-step", (els) => els.map((e) => [e.dataset.state, e.dataset.class]));
    ok(`${width}px: a row per line, each in a state of its own`, JSON.stringify(steps.map((s) => s[1])) === JSON.stringify(want.lines.map((r) => r.class)) && steps.every((s) => ["done", "bad", "idle"].includes(s[0])), steps);
    ok(`${width}px: the disputed share is the one big number`, await p.textContent('[data-sh="share"]') === want.disputed.share && await p.textContent('[data-sh="of"]') === `${want.disputed.amount} of ${want.amounts.billed} billed`);
    ok(`${width}px: the sha256 is the Python's`, (await p.textContent('[data-sh="hash"]')) === `sha256 ${http.sha256}`, await p.textContent('[data-sh="hash"]'));
    ok(`${width}px: the downloaded JSON is the Python's bytes`, JSON.stringify(await save(p, "json")) === JSON.stringify(["statement.json", http.json]));
    ok(`${width}px: the downloaded CSV is the Python's bytes`, JSON.stringify(await save(p, "csv")) === JSON.stringify(["statement.csv", http.csv]));
    ok(`${width}px: the budget is shown`, /^Budget: \d+ of 60 requests left this hour\.$/.test(await p.textContent('[data-sh="budget"]')), await p.textContent('[data-sh="budget"]'));
    ok(`${width}px: a failed check links its run, and no address is a script`, await p.$$eval(".sh-lines a", (as) => as.length > 3 && as.every((a) => a.href.startsWith("https://github.com/"))));
    const said = await statements(p);
    ok(`${width}px: the three plain sentences are on the page`, ["A failed check is not proof of bad work.", "A green check is not proof of good work.", "Shadow mode changes nothing and holds no money."].every((t) => said.includes(t)), said);
    ok(`${width}px: every statement is twelve words at most`, wordy(said).length === 0, wordy(said));
    ok(`${width}px: the statement does not scroll sideways`, (await measure(p)).over <= 0, await measure(p));
    if (process.env.KNOS_SHADOW_SHOTS) await p.screenshot({ path: join(process.env.KNOS_SHADOW_SHOTS, `shadow-${width}.png`), fullPage: true });     // for someone who wants to look
    // the invoice goes nowhere: GitHub is read with GET, no body and no login, and is told nothing but which pull request
    ok(`${width}px: only GETs with no body and no login reach GitHub`, sent.every((s) => s.method === "GET" && !s.body && !s.headers.authorization && !s.headers.cookie), sent.filter((s) => s.method !== "GET"));
    ok(`${width}px: nothing of the invoice but the pull requests' names is sent`, !sent.some((s) => /Acme(%20| )Agents|retainer|1\.015|250,00/i.test(s.path)));
    ok(`${width}px: nobody but this page and api.github.com is asked`, strangers.length === 0, strangers);
    ok(`${width}px: no error on the page`, errors.length === 0, errors);
    await ctx.close();
  }

  // the sample, with five requests left this hour: it is marked as a sample, stops cleanly, and offers the command line
  const { ctx, p, sent, errors } = await visit(390, 5);
  await p.click('[data-sh="sample"]');
  await p.waitForSelector('[data-sh="hash"]');
  ok("the sample is marked: assembled by Knos, nobody's invoice, illustrative amounts", await p.textContent('[data-sh="mark"]') === "Sample assembled by Knos. Not anyone's invoice. Amounts are illustrative.");
  ok("the box holds examples/shadow/sample.csv", await p.inputValue(".shadow textarea") === SAMPLE);
  ok("with the budget spent it stops and offers the command line", /^Budget spent\. Run knos shadow invoice\.csv for more\.$/.test((await p.innerText('[data-sh="said"]')).trim()), await p.innerText('[data-sh="said"]'));
  ok("no more was asked than GitHub had left", sent.filter((s) => s.path !== "rate_limit").length <= 5, sent.map((s) => s.path));
  ok("lines it could not read are idle, never judged", (await p.$$eval(".shadow .k-step", (els) => els.map((e) => `${e.dataset.state} ${e.dataset.class}`))).slice(-3).every((s) => s === "idle unreadable"));
  ok("and the statement says they are counted apart", (await p.textContent('[data-sh="partial"]')) === "Unread lines are counted apart, never guessed.");
  ok("every statement is twelve words at most", wordy(await statements(p)).length === 0, wordy(await statements(p)));
  ok("no error on the page", errors.length === 0, errors);
  await ctx.close();
  await browser.close(); server.close();
}

if (process.argv[2] === "page") await page();
console.log(failed ? `${failed} failed` : "all passed");
process.exit(failed ? 1 : 0);
