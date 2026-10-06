// node tests/web/keyholder.mjs [web dir]
// The Hold a key page (web/keyholder.js). First with no browser, on node's own WebCrypto: the key the page makes is an
// Ed25519 keypair in the form of a Solana keypair file (seed, then public key), its address is the public key in base58,
// the seed alone gives the same public key back, and the request it writes carries the public key and never a number
// of the file. Then in headless Chromium, on web/ as it stands: outside key holders today: 0; a key is made in the page,
// its file is downloaded once and the page forgets it; a browser with no Ed25519 says so and opens the command; a
// pasted public key works too; the request link is the prefilled issue; no statement is over 12 words; nothing runs off
// the side from 320 to 1280 px; and nobody is asked but this site. No `playwright` package or no browser: says so after
// the first part and exits 0.
import { createServer } from "node:http";
import { createRequire } from "node:module";
import { readFileSync, existsSync } from "node:fs";
import { join, extname, dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { webcrypto } from "node:crypto";

const root = resolve(process.argv[2] ?? join(dirname(fileURLToPath(import.meta.url)), "..", "..", "web"));
if (!existsSync(join(root, "keyholder.js"))) { console.error("usage: node tests/web/keyholder.mjs [web dir]"); process.exit(2); }
const check = (name, cond, detail) => { if (!cond) { console.error("FAIL", name, detail === undefined ? "" : JSON.stringify(detail)); process.exitCode = 1; } else console.log("ok  ", name); };
const kh = await import(pathToFileURL(join(root, "keyholder.js")));
const subtle = webcrypto.subtle;

// the seed 07 x 32 and its address, as @solana/web3.js gives it (scripts/governance.test.mjs uses the same key)
const SEED = new Uint8Array(32).fill(7), ADDRESS = "GmaDrppBC7P5ARKV8g3djiwP89vz1jLK23V2GBjuAEGB";
const PKCS8 = Uint8Array.from([0x30, 0x2e, 0x02, 0x01, 0x00, 0x30, 0x05, 0x06, 0x03, 0x2b, 0x65, 0x70, 0x04, 0x22, 0x04, 0x20]);   // RFC 8410: what precedes the seed
const publicOf = async (seed) => {
  const priv = await subtle.importKey("pkcs8", Uint8Array.from([...PKCS8, ...seed]), { name: "Ed25519" }, true, ["sign"]);
  const jwk = await subtle.exportKey("jwk", priv);
  return Uint8Array.from(Buffer.from(jwk.x, "base64url"));
};
check("base58 writes an address as Solana does", kh.base58(await publicOf(SEED)) === ADDRESS && kh.base58(new Uint8Array(32)) === "1".repeat(32));
check("this WebCrypto can make the key", await kh.canMakeKey(subtle));
const made = await kh.makeKey(subtle), again = await kh.makeKey(subtle);
check("a key file is 64 numbers from 0 to 255: the seed, then the public key", made.file.length === 64 && made.file.every((n) => Number.isInteger(n) && n >= 0 && n <= 255));
check("its address is the public half in base58", kh.base58(made.file.slice(32)) === made.address && kh.looksLikeAddress(made.address));
check("the seed in the file gives that public key back", kh.base58(await publicOf(made.file.slice(0, 32))) === made.address);
check("two keys are two keys", made.address !== again.address);
check("no WebCrypto, or one with no Ed25519, is told apart", !(await kh.canMakeKey(null)) && !(await kh.canMakeKey({ generateKey: async () => { throw new Error("NotSupportedError"); } })));
const url = new URL(kh.issueUrl(kh.REPO, { address: made.address, name: "a handle", reach: "by e-mail" })), body = url.searchParams.get("body");
check("the request is a new issue of the repository, titled and filled in", url.origin + url.pathname === "https://github.com/drexthealpha/Knos/issues/new" && url.searchParams.get("title") === "Key holder request"
  && url.searchParams.get("template") === "key_holder.md" && body.includes(made.address) && body.includes("a handle") && body.includes("by e-mail"));
check("it carries nothing of the private half", !body.includes(JSON.stringify(made.file).slice(1, 40)) && !/\d+,\d+,\d+/.test(body));
const template = join(root, "..", ".github", "ISSUE_TEMPLATE", "key_holder.md");
if (existsSync(template)) {
  const t = readFileSync(template, "utf8");
  check("the issue template has the same title and asks for the same three things", t.includes(`title: ${kh.ISSUE_TITLE}`) && ["Public key", "Name or handle", "How to reach me"].every((w) => t.includes(w) && body.includes(w)));
}
const source = readFileSync(join(root, "keyholder.js"), "utf8"), code = source.split("\n").filter((l) => !l.trimStart().startsWith("//")).join("\n");
check("the module asks this site for one file and has no way to send", code.match(/fetchFn\(/g).length === 1 && code.includes('fetchFn("keyholders.json"')
  && !/method\s*:|\.send\(|XMLHttpRequest|sendBeacon|WebSocket|localStorage|sessionStorage|indexedDB|document\.cookie/.test(code) && !/^import /m.test(code));
check("the only hosts named are GitHub's, for links a person follows", [...new Set([...code.matchAll(/https?:\/\/([\w.-]+)/g)].map((m) => m[1]))].join() === "github.com");

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
const html = (ctx) => `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Hold a key</title>
<link rel="stylesheet" href="app.css"></head><body><main id="keyholder"></main>
<script type="module">import { renderKeyholder } from "./keyholder.js"; await renderKeyholder(document.getElementById("keyholder"), ${ctx}); document.body.dataset.ready = "1";</script></body></html>`;
const NO_ED = `{ subtle: { generateKey: async () => { throw new DOMException("Unrecognized name.", "NotSupportedError"); } } }`;
const server = createServer((req, res) => {
  const name = decodeURIComponent(new URL(req.url, "http://x").pathname);
  if (name === "/keyholder.html") { res.writeHead(200, { "content-type": "text/html" }); return res.end(html("{}")); }
  if (name === "/keyholder_old.html") { res.writeHead(200, { "content-type": "text/html" }); return res.end(html(NO_ED)); }
  const path = join(root, name);
  if (!path.startsWith(root) || !existsSync(path)) { res.writeHead(404); return res.end(); }
  res.writeHead(200, { "content-type": TYPES[extname(path)] || "application/octet-stream" }); res.end(readFileSync(path));
});
await new Promise((r) => server.listen(0, "127.0.0.1", r));
const base = `http://localhost:${server.address().port}/`;
const refused = [], asked = [];

async function open(width, file = "keyholder.html") {
  const ctx = await browser.newContext({ viewport: { width, height: 900 }, acceptDownloads: true });
  await ctx.route("**/*", (route) => { const u = route.request().url(); if (u.startsWith(base) || u.startsWith("data:") || u.startsWith("blob:")) { asked.push(`${route.request().method()} ${u.slice(base.length)}`); return route.continue(); } refused.push(u); return route.abort(); });
  const page = await ctx.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  await page.goto(`${base}${file}`);
  await page.waitForSelector("body[data-ready]");
  return { ctx, page, errors };
}
const text = (page, name) => page.textContent(`[data-kh="${name}"]`);
const stateOf = (page, name) => page.getAttribute(`[data-kh="${name}"]`, "data-state");

{
  const { ctx, page, errors } = await open(1280);
  check("page: outside key holders today: 0", (await text(page, "count")) === "Outside key holders today: 0");
  check("page: nothing can be saved or asked before there is a key", await page.isDisabled('[data-kh="save"]') && (await page.getAttribute('[data-kh="ask"]', "href")) === null && (await stateOf(page, "s1")) === "live");
  await page.click('[data-kh="make"]');
  await page.waitForFunction(() => document.querySelector('[data-kh="address"]').textContent.startsWith("Public key: "));
  const address = (await text(page, "address")).slice("Public key: ".length);
  check("page: the public key is shown as an address", kh.looksLikeAddress(address), address);
  const [download] = await Promise.all([page.waitForEvent("download"), page.click('[data-kh="save"]')]);
  const file = JSON.parse(readFileSync(await download.path(), "utf8"));
  check("page: the file saved is a Solana keypair file of that key", download.suggestedFilename() === "knos-member.json" && file.length === 64 && kh.base58(file.slice(32)) === address
    && kh.base58(await publicOf(file.slice(0, 32))) === address);
  check("page: the page forgets the private key once it is saved", await page.isDisabled('[data-kh="save"]') && (await text(page, "said")) === "Saved. This page has forgotten the private key." && (await stateOf(page, "s3")) === "live");
  await page.fill('[data-kh="name"]', "a handle");
  await page.fill('[data-kh="reach"]', "by e-mail");
  const href = await page.getAttribute('[data-kh="ask"]', "href");
  check("page: the request is the prefilled issue, with the public key and no more of the key", href === kh.issueUrl(kh.REPO, { address, name: "a handle", reach: "by e-mail" }) && !href.includes(encodeURIComponent(JSON.stringify(file.slice(0, 8)).slice(1, -1))));
  const over = await page.$$eval("#keyholder p, #keyholder li:not(.k-step), #keyholder h2, #keyholder h3, #keyholder summary, #keyholder button, #keyholder a, #keyholder label", (els) =>
    els.flatMap((e) => [...e.childNodes].filter((n) => n.nodeType === 3).map((n) => n.textContent).join(" ").split(/(?<=[.:])\s+/)).map((s) => s.trim()).filter((s) => s.split(/\s+/).filter(Boolean).length > 12));
  check("page: no statement is over 12 words", over.length === 0, over);
  check("page: no error", errors.length === 0, errors);
  await ctx.close();
}
{
  const { ctx, page } = await open(390, "keyholder_old.html");
  await page.click('[data-kh="make"]');
  await page.waitForFunction(() => document.querySelector('[data-kh="said"]').textContent.includes("cannot"));
  await page.waitForSelector("#keyholder details:has(> pre) pre", { state: "visible" });      // the block opens over 240 ms: wait for it, do not sample it
  const old = { said: await text(page, "said"), how: await text(page, "how"), open: await page.$eval("#keyholder details:has(> pre)", (d) => d.open), shown: await page.isVisible("#keyholder details:has(> pre) pre"),
    pre: await page.textContent("#keyholder details pre"), s1: await stateOf(page, "s1"), save: await page.isDisabled('[data-kh="save"]') };
  check("old browser: says it cannot make the key, names what can, and opens the command", old.said === "This browser cannot make the key. Use the command below."
    && old.how === `Needs ${kh.NEEDS}.` && old.open && old.shown && old.pre.includes("solana-keygen new --outfile knos-member.json") && old.s1 === "bad" && old.save, old);
  await page.fill('[data-kh="paste"]', "not a key");
  check("old browser: something that is not a public key is not taken", (await page.getAttribute('[data-kh="ask"]', "href")) === null && (await text(page, "said")).startsWith("Paste the public key"));
  await page.fill('[data-kh="paste"]', ADDRESS);
  check("old browser: a pasted public key goes into the request, and there is no file to save", (await page.getAttribute('[data-kh="ask"]', "href")) === kh.issueUrl(kh.REPO, { address: ADDRESS })
    && await page.isDisabled('[data-kh="save"]') && (await stateOf(page, "s3")) === "live");
  await ctx.close();
}
for (const width of [320, 390, 768, 1280]) {
  const { ctx, page } = await open(width);
  await page.click('[data-kh="make"]');
  await page.waitForFunction(() => document.querySelector('[data-kh="address"]').textContent.length > 20);
  await page.evaluate(() => { document.querySelector("#keyholder details").open = true; });
  const wide = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  check(`page: nothing runs off the side at ${width} px`, wide <= 0, wide);
  await ctx.close();
}
check("nobody was asked but this site, and only with GET", refused.length === 0 && asked.every((a) => a.startsWith("GET ")), { refused, asked: asked.filter((a) => !a.startsWith("GET ")) });
check("the one file read is keyholders.json", asked.some((a) => a === "GET keyholders.json"));
await browser.close();
server.close();
console.log(process.exitCode ? "FAILED" : "all passed");
