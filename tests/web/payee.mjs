// node tests/web/payee.mjs [screenshot dir]
// The payee page (web/payee.js) in headless Chromium, served from web/ with the SDK's two modules where the build puts
// them (settle.js, passkey.js), against a mocked GitHub API and a mocked devnet RPC, with Chromium's own virtual
// authenticator for the passkey (CDP: WebAuthn.enable, WebAuthn.addVirtualAuthenticator). It checks: what is held is
// read by payee id from held jobs and held orders (a job less its fee, an order what it has not paid); a passkey is made
// in one press and its address is the knos_passkey address of its key; the one link is GitHub's filled-in
// new-repository form while <login>/knos-claim does not exist, and the claim workflow's page once it does; Check reads
// the Bind account; by keyboard, a login that does not exist brings the box back with the login in it and the cursor
// there, and the right one moves the focus to the answer, which is said aloud; the clicks table says 13 before and 8 now; no statement is longer than twelve words; no sideways
// scroll from 320 to 1280 px; nobody is asked but the page's host, api.github.com and devnet. No `playwright` package
// or no browser: says SKIP and exits 0.
import { createServer } from "node:http";
import { createRequire } from "node:module";
import { readFileSync, existsSync, mkdirSync } from "node:fs";
import { join, dirname, extname, normalize } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = dirname(fileURLToPath(import.meta.url)), repo = join(here, "../.."), web = join(repo, "web");
const shots = process.argv[2];
const skip = (why) => { console.log(`SKIP ${why}`); process.exit(0); };
let failed = 0;
const ok = (what, cond, detail) => { if (!cond) failed++; console.log(`${cond ? "ok  " : "FAIL"} ${what}${cond || detail === undefined ? "" : `: ${JSON.stringify(detail)}`}`); };

const passkey = await import(pathToFileURL(join(repo, "sdk/settle/passkey.js")).href);
const ids = JSON.parse(readFileSync(join(repo, "src/knos/settle/v2/program_ids.json"), "utf8"));
const SOURCES = { "settle.js": join(repo, "sdk/settle/index.js"), "passkey.js": join(repo, "sdk/settle/passkey.js"),
  "program_ids.json": join(repo, "src/knos/settle/v2/program_ids.json") };

let pw;
try { pw = await import("playwright"); } catch {
  const paths = (process.env.NODE_PATH || "").split(":").filter(Boolean);
  try { const req = createRequire(import.meta.url); pw = req(req.resolve("playwright", { paths })); } catch { skip("the playwright package is not installed"); }
}
const { chromium } = pw.default || pw;
let browser;
try { browser = await chromium.launch(); } catch (e) { skip(`no Chromium to start: ${String(e.message).split("\n")[0]}`); }

const TYPES = { ".js": "text/javascript", ".css": "text/css", ".json": "application/json", ".woff2": "font/woff2", ".svg": "image/svg+xml" };
const PAGE = `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Payee</title><link rel="stylesheet" href="/app.css"></head><body><main id="page" class="view"></main>
<script type="module">import { renderPayee } from "/payee.js";
window.view = renderPayee(document.getElementById("page"), { arg: location.hash.split("=")[1] || "" }); window.ready = true;</script></body></html>`;
const server = createServer((req, res) => {
  const path = normalize(decodeURIComponent(req.url.split("?")[0])).replace(/^([/\\])+/, "");
  if (!path) { res.writeHead(200, { "content-type": "text/html" }); return res.end(PAGE); }
  const file = SOURCES[path] || join(web, path);
  if (!file.startsWith(repo) || !existsSync(file)) { res.writeHead(404); return res.end(); }
  res.writeHead(200, { "content-type": TYPES[extname(file)] || "application/octet-stream" }); res.end(readFileSync(file));
});
await new Promise((r) => server.listen(0, "127.0.0.1", r));
const origin = `http://localhost:${server.address().port}`;      // a passkey needs a name, not an IP number

// ---- the world the page sees ------------------------------------------------------------------------------------------
const ID = 583231, LOGIN = "octo", MINT = "4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU";
const u64 = (n) => { const b = new Uint8Array(8); new DataView(b.buffer).setBigUint64(0, BigInt(n), true); return b; };
const at = (size, ...fields) => { const out = new Uint8Array(size); for (const [offset, bytes] of fields) out.set(bytes, offset); return out; };
const b64 = (u8) => Buffer.from(u8).toString("base64");
const job = (state, amount, payee) => at(320, [0, [state]], [24, u64(amount)], [56, u64(payee)], [184, passkey.unb58(MINT)]);
const order = (state, amount, paid, payee) => at(512, [0, [2, state]], [64, u64(amount)], [88, u64(paid)], [152, u64(payee)], [288, passkey.unb58(MINT)]);
const ACCOUNTS = {
  320: [["Job1111111111111111111111111111111111111111", job(3, 5_000_000, ID)], ["Job2222222222222222222222222222222222222222", job(1, 9_000_000, ID)]],
  512: [["Ord1111111111111111111111111111111111111111", order(3, 10_000_000, 2_500_000, ID)], ["Ord2222222222222222222222222222222222222222", order(4, 7_000_000, 0, ID)]],
};
const world = { repo: false, bound: null, asked: [] };

async function route(page) {
  page.on("request", (r) => { if (!r.url().startsWith(origin)) world.asked.push(new URL(r.url()).host); });
  await page.route("https://api.github.com/**", (r) => {
    const p = new URL(r.request().url()).pathname;
    if (p === `/users/${LOGIN}`) return r.fulfill({ json: { login: LOGIN, id: ID } });
    if (p === `/repos/${LOGIN}/knos-claim`) return world.repo ? r.fulfill({ json: { full_name: `${LOGIN}/knos-claim` } }) : r.fulfill({ status: 404, json: { message: "Not Found" } });
    return r.fulfill({ status: 404, json: {} });
  });
  await page.route("https://api.devnet.solana.com/**", (r) => {
    const { method, params } = JSON.parse(r.request().postData());
    if (method === "getProgramAccounts") {
      const [program, { filters }] = params, size = filters[0].dataSize, m = filters[1].memcmp;
      const want = b64(passkey.unb58(m.bytes, 8));
      const hit = program === ids.knos_pay ? (ACCOUNTS[size] || []).filter(([, d]) => b64(d.subarray(m.offset, m.offset + 8)) === want) : [];
      return r.fulfill({ json: { jsonrpc: "2.0", id: 1, result: hit.map(([pubkey, d]) => ({ pubkey, account: { data: [b64(d), "base64"], owner: program, lamports: 1 } })) } });
    }
    if (method === "getAccountInfo") {
      const value = world.bound ? { data: [b64(at(56, [0, [1]], [8, u64(ID)], [16, passkey.unb58(world.bound)])), "base64"], owner: ids.knos_pay, lamports: 1 } : null;
      return r.fulfill({ json: { jsonrpc: "2.0", id: 1, result: { context: { slot: 1 }, value } } });
    }
    return r.fulfill({ json: { jsonrpc: "2.0", id: 1, error: { code: -32601, message: method } } });
  });
}
const longest = (page) => page.$$eval("#page p, #page li > span, #page label, #page summary", (ns) => ns.map((n) => {
  const t = [...n.childNodes].filter((c) => c.nodeType === 3 || !["BUTTON", "A"].includes(c.nodeName)).map((c) => c.textContent).join(" ");
  return t.replace(/[A-HJ-NP-Za-km-z1-9]{32,44}/g, "X").trim().split(/\s+/).filter(Boolean).length;
}).reduce((a, b) => Math.max(a, b), 0));

try {
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const page = await ctx.newPage();
  await route(page);
  const cdp = await ctx.newCDPSession(page);
  await cdp.send("WebAuthn.enable");
  const { authenticatorId } = await cdp.send("WebAuthn.addVirtualAuthenticator", { options: { protocol: "ctap2", transport: "internal",
    hasResidentKey: true, hasUserVerification: true, isUserVerified: true, automaticPresenceSimulation: true } });
  await page.goto(`${origin}/#payee=${LOGIN}`);
  await page.waitForSelector("[data-py-amount]");
  // a held job of 5.00 pays 5.00 less the 0.05 floor; a held order of 10.00 that paid 2.50 has 7.50 left; open and warranty states are not held
  ok("held: a job less its fee and an order's unpaid part, by payee id", (await page.textContent("[data-py-amount]")) === "12.45", await page.textContent("[data-py-held]"));
  ok("no link before a passkey", (await page.$("#py-go")) === null);
  const t0 = Date.now();
  await page.click("#py-make");
  await page.waitForSelector("[data-py-address]");
  ok("the passkey is made in one press", Date.now() - t0 < 10_000, Date.now() - t0);
  const address = (await page.textContent("[data-py-address]")).trim();
  const made = await cdp.send("WebAuthn.getCredentials", { authenticatorId });
  const kept = await page.evaluate(() => JSON.parse(localStorage.getItem("knos-passkey")));
  ok("one credential; the address is knos_passkey's for its key", made.credentials.length === 1
    && address === await passkey.wallet(passkey.compressed(Uint8Array.from(Buffer.from(kept.key, "hex"))), ids.knos_passkey), address);
  ok("kept as the Get paid page keeps it: id and public key only", Object.keys(kept).sort().join() === "credentialId,key");
  const href = await page.$eval("#py-go", (a) => a.href);
  ok("with no knos-claim yet, the link is GitHub's filled-in form", href === `https://github.com/new?template_owner=drexthealpha&template_name=knos-claim&owner=${LOGIN}&name=knos-claim&visibility=public`, href);
  await page.click("#py-check");
  await page.waitForFunction(() => /Not bound|Bound/.test(document.querySelector("[data-py-done]").textContent));
  ok("Check before the run: not bound", (await page.textContent("[data-py-done]")).startsWith("Not bound yet"));
  world.bound = address;
  await page.click("#py-check");
  await page.waitForSelector("[data-py-bound]");
  ok("Check after the run: bound to this passkey", (await page.textContent("[data-py-bound]")) === address && (await page.$eval("#py-done", (n) => n.dataset.state)) === "done");
  const table = await page.$$eval("[data-py-clicks] th", (th) => th.map((n) => n.textContent));
  ok("the clicks: 13 before, 8 now", JSON.stringify(table) === JSON.stringify(["Before: 13", "Now: 8"]), table);
  ok("no statement is longer than twelve words", (await longest(page)) <= 12, await longest(page));

  // a second visit: the repository exists and the passkey is kept, so the link is the workflow's page at once
  world.repo = true; world.bound = null;
  const again = await ctx.newPage();
  await route(again);
  await again.goto(`${origin}/#payee=${LOGIN}`);
  await again.waitForSelector("#py-go");
  ok("kept passkey, existing repository: the link is the claim workflow's page", (await again.$eval("#py-go", (a) => a.href)) === `https://github.com/${LOGIN}/knos-claim/actions/workflows/knos-claim.yml`
    && (await again.textContent("[data-py-address]")).trim() === address);

  // by keyboard, with no login in the link: a login typed wrong is said, and the box comes back with it, the cursor in
  // it, so it can be corrected (it used to stay hidden: the page had to be loaded again); the right login moves the
  // focus to the answer, and the next Tab is the passkey
  {
    const fresh = await browser.newContext({ viewport: { width: 390, height: 900 } }), typed = await fresh.newPage();
    await route(typed);
    await typed.goto(`${origin}/#payee`);
    await typed.waitForFunction(() => window.ready === true);
    await typed.focus("#py-login");
    await typed.keyboard.type(`${LOGIN}-typo`);
    await typed.keyboard.press("Enter");
    await typed.waitForFunction(() => /No GitHub account/.test(document.querySelector("[data-py-held]").textContent));
    const asked = await typed.evaluate(() => ({ shown: getComputedStyle(document.querySelector("#py-who")).display !== "none",
      value: document.querySelector("#py-login").value, focus: document.activeElement.id, said: document.querySelector("[data-py-held]").getAttribute("aria-live") }));
    ok("keyboard: a login that does not exist is said aloud, and the box comes back with it, the cursor in it",
      asked.shown && asked.value === `${LOGIN}-typo` && asked.focus === "py-login" && asked.said === "polite", asked);
    await typed.keyboard.press("Control+A");
    await typed.keyboard.type(LOGIN);
    await typed.keyboard.press("Enter");
    await typed.waitForSelector("[data-py-amount]");
    const found = await typed.evaluate(() => ({ hidden: getComputedStyle(document.querySelector("#py-who")).display === "none",
      focus: document.activeElement.matches("[data-py-held]"), amount: document.querySelector("[data-py-amount]").textContent }));
    await typed.keyboard.press("Tab");
    found.next = await typed.evaluate(() => document.activeElement.id);
    ok("keyboard: the right login shows what is held, the focus on the answer, and Tab goes on to Make a passkey",
      found.hidden && found.focus && found.amount === "12.45" && found.next === "py-make", found);
    await fresh.close();
  }

  for (const width of [320, 390, 768, 1280]) {
    await again.setViewportSize({ width, height: 900 });
    const wide = await again.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    ok(`${width}px: no sideways scroll`, wide <= 0, wide);
    if (shots && (width === 390 || width === 1280)) { mkdirSync(shots, { recursive: true }); await again.screenshot({ path: join(shots, `payee-${width}.png`), fullPage: true }); }
  }
  const hosts = [...new Set(world.asked)].sort();
  ok("nobody asked but this host, api.github.com and devnet", hosts.every((h) => ["api.devnet.solana.com", "api.github.com"].includes(h)), hosts);
} finally {
  await browser.close();
  server.close();
}
console.log(failed ? `${failed} failed` : "all passed");
process.exit(failed ? 1 : 0);
