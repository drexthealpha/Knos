// node tests/web/terms.mjs <site dir>
// The Terms page (web/terms.js) on a folder that holds web/ and the registry terms/ as the site serves them. First
// with no browser: the page's own canonical form and sha256 give, for every published version, the bytes and the hash
// the registry file carries (which scripts/terms_registry.py made with knos.terms), whatever order the fields and
// lists arrive in. Then in headless Chromium: one card a template with its sentence, what it trusts and its hash;
// "Cite in a contract" copies the contract sentence and "Fund with this" the comment; the box names the published
// template of a pasted hash or terms JSON and says so when there is none; no statement is over 12 words; nothing
// scrolls sideways from 320 to 1280 px; and the page asks nobody but this site. No `playwright` package or no
// browser: says so after the first part and exits 0.
import { createServer } from "node:http";
import { createRequire } from "node:module";
import { readFileSync, existsSync } from "node:fs";
import { join, extname } from "node:path";
import { pathToFileURL } from "node:url";

const [root] = process.argv.slice(2);
if (!root || !existsSync(join(root, "terms.js")) || !existsSync(join(root, "terms", "index.json"))) { console.error("usage: node tests/web/terms.mjs <site dir>"); process.exit(2); }
const check = (name, cond, detail) => { if (!cond) { console.error("FAIL", name, detail === undefined ? "" : JSON.stringify(detail)); process.exitCode = 1; } else console.log("ok  ", name); };

const page0 = await import(pathToFileURL(join(root, "terms.js")));
const index = JSON.parse(readFileSync(join(root, "terms", "index.json"), "utf8"));
const files = index.templates.map((t) => JSON.parse(readFileSync(join(root, page0.fileOf(t)), "utf8")));
const backwards = (v) => (Array.isArray(v) ? [...v].reverse().map(backwards).concat(v.slice(0, 1).map(backwards))
  : v && typeof v === "object" ? Object.fromEntries(Object.entries(v).reverse().map(([k, x]) => [k, backwards(x)])) : v);
check("the registry lists templates", index.templates.length >= 5 && index.standard === page0.STANDARD, index.templates.length);
check("the page's canonical form is each published file's bytes", files.every((f) => page0.canonicalTerms(f.terms) === f.terms_json));
check("...whatever order the fields and lists arrive in, and with repeats", files.every((f) => page0.canonicalTerms(backwards(f.terms)) === f.terms_json));
const hashes = await Promise.all(files.map((f) => page0.sha256Hex(page0.canonicalTerms(f.terms))));
check("the page's sha256 of them is the hash the index lists", hashes.every((h, i) => h === index.templates[i].hash && h === files[i].terms_hash), hashes);
check("the contract sentence is the one the file carries", index.templates.every((t, i) => page0.citeSentence(t) === files[i].cite));
check("non-ASCII is written \\uXXXX as Python's json writes it", page0.canonicalTerms({ ...files[0].terms, paths: ["src/é😀/**"] }).includes('"src/\\u00e9\\ud83d\\ude00/**"'));
let refusedShape = ""; try { page0.canonicalTerms({ ...files[0].terms, extra: 1 }); } catch (e) { refusedShape = e.message; }
check("an object with another field is not terms", refusedShape.startsWith("Terms have exactly these fields"), refusedShape);
check("a hash nobody published matches nothing", page0.published(index, "0".repeat(64)).length === 0);

const skip = (why) => { console.log(`SKIP the browser part: ${why}`); process.exit(process.exitCode || 0); };
let pw;
try { pw = await import("playwright"); } catch {
  const paths = (process.env.NODE_PATH || "").split(":").filter(Boolean);
  try { const req = createRequire(import.meta.url); pw = req(req.resolve("playwright", { paths })); } catch { skip("the playwright package is not installed"); }
}
const { chromium } = pw.default || pw;
let browser;
try { browser = await chromium.launch(); } catch (e) { skip(`no Chromium to start: ${String(e.message).split("\n")[0]}`); }

const TYPES = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json", ".svg": "image/svg+xml", ".woff2": "font/woff2" };
const HTML = `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Terms</title>
<link rel="stylesheet" href="app.css"></head><body><main id="terms"></main>
<script type="module">import { renderTerms } from "./terms.js"; await renderTerms(document.getElementById("terms")); document.body.dataset.ready = "1";</script></body></html>`;
let withRegistry = true;
const server = createServer((req, res) => {
  const name = decodeURIComponent(new URL(req.url, "http://x").pathname);
  if (name === "/terms.html") { res.writeHead(200, { "content-type": "text/html" }); return res.end(HTML); }
  const path = join(root, name);
  if (!path.startsWith(root) || !existsSync(path) || (!withRegistry && name.startsWith("/terms/"))) { res.writeHead(404); return res.end(); }
  res.writeHead(200, { "content-type": TYPES[extname(path)] || "application/octet-stream" }); res.end(readFileSync(path));
});
await new Promise((r) => server.listen(0, "127.0.0.1", r));
const base = `http://localhost:${server.address().port}/`;
const refused = [];

async function open(width) {
  const ctx = await browser.newContext({ viewport: { width, height: 900 } });
  await ctx.grantPermissions(["clipboard-read", "clipboard-write"]).catch(() => {});
  await ctx.route("**/*", (route) => { const url = route.request().url(); if (url.startsWith(base) || url.startsWith("data:")) return route.continue(); refused.push(url); return route.abort(); });
  const page = await ctx.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  await page.goto(`${base}terms.html`);
  await page.waitForSelector("body[data-ready]");
  return { ctx, page, errors };
}

const names = [...new Set(index.templates.map((t) => t.name))], newest = page0.newest(index);
{
  const { ctx, page, errors } = await open(1280);
  check("one card a template, in the registry's order", JSON.stringify(await page.$$eval("[data-template]", (els) => els.map((e) => e.dataset.template))) === JSON.stringify(names));
  const cards = await page.$$eval("[data-template]", (els) => els.map((e) => ({ kicker: e.querySelector(".k-kicker").textContent, sentence: e.querySelector(".terms-sentence").textContent,
    trust: e.querySelector(".terms-trust").textContent, hash: e.querySelector(".terms-hash").textContent, card: e.classList.contains("k-card") })));
  check("each shows its version, its one sentence and its hash, on a .k-card", cards.every((c, i) => c.card && c.kicker === `Version ${newest[i].version}` && c.sentence === `${newest[i].sentence.replace(/`/g, "")}.` && c.hash === newest[i].hash), cards);
  check("each says what it trusts: the judge and the quorum", cards.every((c, i) => c.trust === page0.trustOf(newest[i]) && /^Judge: (a maintainer's merge|in-process|black-box|hermetic)\. Quorum: [123]\.$/.test(c.trust)), cards.map((c) => c.trust));
  const blackbox = newest.findIndex((t) => t.name === "feature-blackbox");
  check("the black-box template says black-box, a merge template says a merge", cards[blackbox].trust.startsWith("Judge: black-box") && cards[0].trust.startsWith("Judge: a maintainer's merge"));
  const clip = () => page.evaluate(() => navigator.clipboard.readText()).catch(() => null);
  const first = page.locator("[data-template]").first();
  await first.locator('button[data-copy="cite"]').click();
  await page.waitForFunction(() => document.querySelector('button[data-copy="cite"]').textContent === "Sentence copied");
  const cited = await first.locator(".terms-copied").textContent(), want = `Acceptance is governed by Knos Terms 1, template ${newest[0].name} version ${newest[0].version}, sha256 ${newest[0].hash}`;
  const onClip = await clip();
  check("Cite in a contract copies the contract sentence and leaves it in view", cited === want && (onClip === null || onClip === want), [cited, onClip]);
  await first.locator('button[data-copy="fund"]').click();
  await page.waitForFunction(() => document.querySelector('button[data-copy="fund"]').textContent === "Comment copied");
  check("Fund with this copies the comment to post", await first.locator(".terms-copied").textContent() === newest[0].comment && newest[0].comment.startsWith("/knos "), newest[0].comment);
  await first.locator('button[data-copy="hash"]').click();
  await page.waitForFunction(() => document.querySelector('button[data-copy="hash"]').textContent === "Hash copied");
  check("Copy hash copies the hash", await first.locator(".terms-copied").textContent() === newest[0].hash);

  const ask = async (text) => {
    await page.fill("#terms-paste", text);
    await page.evaluate(() => { document.getElementById("terms-answer").dataset.found = "wait"; });
    await page.click("#terms-which");
    await page.waitForFunction(() => document.getElementById("terms-answer").dataset.found !== "wait");
    return page.$eval("#terms-answer", (e) => [e.dataset.found, e.textContent]);
  };
  const some = files[1], row = index.templates[1];
  check("a pasted hash is named: template and version", JSON.stringify(await ask(`  ${row.hash.toUpperCase()}\n`)) === JSON.stringify(["yes", `${row.name} version ${row.version}. Open the file`]));
  check("a pasted terms JSON is named, with other spacing and order", (await ask(JSON.stringify(backwards(some.terms), null, 2)))[1].startsWith(`${row.name} version ${row.version}.`));
  check("the published file itself is named", (await ask(JSON.stringify(some)))[0] === "yes");
  const other = await ask(JSON.stringify({ ...some.terms, reserve: some.terms.reserve + 1 }));
  check("terms nobody published: not a published template, with their hash", other[0] === "no" && /^Not a published template\. sha256 [0-9a-f]{64}$/.test(other[1]) && !other[1].includes(row.hash), other);
  check("a hash nobody published: not a published template", (await ask("ab".repeat(32)))[0] === "no");
  check("text that is neither is said to be neither", JSON.stringify(await ask("pay me")) === JSON.stringify(["error", "Neither a sha256 nor JSON."]));
  check("the version table lists every version, in a .k-table", await page.$$eval("#terms-versions .k-table tbody tr", (r) => r.length) === index.templates.length);

  // the 12-word budget: every statement the page itself makes (a template's own sentence and the answers are data)
  const said = await page.$$eval("#terms h2, #terms h3, #terms p:not(.terms-sentence):not(.terms-hash), #terms button, #terms th, #terms label", (els) => els.map((e) => e.textContent.trim().replace(/\s+/g, " ")));
  const long = said.filter((s) => s.split(" ").filter(Boolean).length > 12);
  check("no statement of the page is over 12 words", long.length === 0 && said.length > 10, long);
  check("the page raised no error", errors.length === 0, errors);
  await ctx.close();
}
for (const width of [320, 390, 768, 1280]) {
  const { ctx, page } = await open(width);
  await page.locator('button[data-copy="cite"]').first().click();
  await page.fill("#terms-paste", index.templates[0].hash);
  await page.click("#terms-which");
  await page.waitForFunction(() => document.getElementById("terms-answer").dataset.found === "yes");
  const [scroll, client] = await page.evaluate(() => [document.documentElement.scrollWidth, document.documentElement.clientWidth]);
  check(`nothing scrolls sideways at ${width} px`, scroll <= client, [scroll, client]);
  await ctx.close();
}
{
  withRegistry = false;
  const { ctx, page } = await open(390);
  check("a build with no registry says so and shows no template", await page.$eval("#terms-none", (e) => e.textContent) === "This build holds no terms registry." && (await page.$$("[data-template]")).length === 0);
  await ctx.close();
}
check("the page asked nobody but this site", refused.length === 0, refused);
await browser.close();
server.close();
console.log(process.exitCode ? "the Terms page FAILED" : "the Terms page holds");
