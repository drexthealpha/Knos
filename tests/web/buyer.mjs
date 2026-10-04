// node tests/web/buyer.mjs <site dir> <fixture dir> [screenshot dir]
// The Buy page (web/buyer.js) in headless Chromium, on a build of the site (scripts/build_site.sh), against a mocked
// GitHub API and a mocked Solana devnet RPC, with Chromium's own virtual authenticator for the passkey (CDP:
// WebAuthn.enable, WebAuthn.addVirtualAuthenticator). The four steps render; each template shows its one sentence
// and what is still trusted; a passkey wallet is made, signs one order, and the line `/knos passkey-fund ...` appears,
// with a signature that verifies under the wallet's key over the challenge the program computes; the order's state
// is read back from the chain's log; the statement's two exports are the bytes `knos audit export` wrote (the fixture
// dir: expected.csv, expected.json, made by tests/test_site_buyer.py); nothing scrolls sideways at 390 px; and the
// page asks nobody but this site, GitHub and devnet. The signed line is written to <fixture dir>/line.txt, for the
// Python side to send to the programs. No `playwright` package or no browser: says so and exits 0 (a skip).
import { createServer } from "node:http";
import { createRequire } from "node:module";
import { createHash, createPublicKey, verify as ecVerify, ECDH } from "node:crypto";
import { readFileSync, writeFileSync, existsSync, mkdirSync } from "node:fs";
import { join, extname } from "node:path";
import { pathToFileURL } from "node:url";
import { measure } from "./overflow.mjs";

const [root, fixtures, shots] = process.argv.slice(2);
if (!root || !fixtures || !existsSync(join(root, "index.html"))) { console.error("usage: node tests/web/buyer.mjs <site dir> <fixture dir> [screenshot dir]"); process.exit(2); }
const skip = (why) => { console.log(`SKIP ${why}`); process.exit(0); };
const check = (name, cond, detail) => { if (!cond) { console.error("FAIL", name, detail === undefined ? "" : detail); process.exitCode = 1; } else console.log("ok  ", name); };

let pw;
try { pw = await import("playwright"); } catch {
  const paths = (process.env.NODE_PATH || "").split(":").filter(Boolean);
  try { const req = createRequire(import.meta.url); pw = req(req.resolve("playwright", { paths })); } catch { skip("the playwright package is not installed"); }
}
const { chromium } = pw.default || pw;
let browser;
try { browser = await chromium.launch(); } catch (e) { skip(`no Chromium to start: ${String(e.message).split("\n")[0]}`); }

// the site's own modules, as the page loads them: what the page signs is checked with the same code a relay's reader is tested against
const knos = await import(pathToFileURL(join(root, "settle.js")));
const fund = await import(pathToFileURL(join(root, "passkey_fund.js")));
const buyer = await import(pathToFileURL(join(root, "buyer.js")));
const ids = JSON.parse(readFileSync(join(root, "program_ids.json"), "utf8"));
const book = JSON.parse(readFileSync(join(root, "buyer_templates.json"), "utf8"));
const byName = Object.fromEntries(book.templates.map((t) => [t.name, t]));

const TYPES = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json", ".svg": "image/svg+xml", ".woff2": "font/woff2" };
const server = createServer((req, res) => {
  const path = join(root, decodeURIComponent(new URL(req.url, "http://x").pathname).replace(/\/$/, "/index.html"));
  if (!path.startsWith(root) || !existsSync(path)) { res.writeHead(404); return res.end(); }
  res.writeHead(200, { "content-type": TYPES[extname(path)] || "application/octet-stream" }); res.end(readFileSync(path));
});
await new Promise((r) => server.listen(0, "127.0.0.1", r));
const base = `http://localhost:${server.address().port}/`;      // a passkey needs a name, not an IP number: localhost is one

// ---- the world the page sees -----------------------------------------------------------------------------------------------------------
const DEVNET = "EtWTRABZaYq6iMfeYKouRu166VU2xqa1wcaWoxPkrZBG", REPO_ID = 5550001, ISSUE = 7, SLOT = 1000, NOW = 1790000000;
const u64 = (n) => { const b = new Uint8Array(8); new DataView(b.buffer).setBigUint64(0, BigInt(n), true); return b; };
const at = (size, ...fields) => { const out = new Uint8Array(size); for (const [offset, bytes] of fields) out.set(bytes, offset); return out; };
const b64 = (u8) => Buffer.from(u8).toString("base64");
const tokenBytes = ({ mint, owner, amount }) => at(165, [0, knos.unb58(mint)], [32, knos.unb58(owner)], [64, u64(amount)], [108, [1]]);
const SIG = { fund: "2".repeat(88), pay: "3".repeat(88) };
const chain = { wallet: null, holds: 100_000_000, order: null, calls: [], paid: false };
const logs = (lines) => [`Program ${ids.knos_pay} invoke [1]`, ...lines.map((l) => `Program log: ${l}`), `Program ${ids.knos_pay} success`];
const asked = [], refused = [];

async function context(width) {
  const ctx = await browser.newContext({ viewport: { width, height: 900 }, acceptDownloads: true });
  await ctx.grantPermissions(["clipboard-read", "clipboard-write"]).catch(() => {});
  await ctx.route("**/*", (route) => {          // registered first, so asked last: nothing but this site, GitHub and devnet
    const url = route.request().url();
    asked.push(url);
    if (url.startsWith(base)) return route.continue();
    refused.push(url);
    return route.abort();
  });
  await ctx.route("https://api.github.com/**", (route) => {
    const path = new URL(route.request().url()).pathname;
    asked.push(route.request().url());
    const body = path === "/repos/octo/widgets" ? { id: REPO_ID, full_name: "octo/widgets", archived: false }
      : path === `/repos/octo/widgets/issues/${ISSUE}` ? { title: "Parser crashes on an empty file", state: "open" } : path === "/users/acme" ? { id: 5001, login: "acme" } : null;
    return route.fulfill({ status: body ? 200 : 404, contentType: "application/json", headers: { "access-control-allow-origin": "*" }, body: JSON.stringify(body || { message: "Not Found" }) });
  });
  await ctx.route("https://api.devnet.solana.com/**", async (route) => {
    const req = route.request();
    asked.push(req.url());
    if (req.method() === "OPTIONS") return route.fulfill({ status: 204, headers: { "access-control-allow-origin": "*", "access-control-allow-headers": "*" } });
    const { method, params } = JSON.parse(req.postData());
    chain.calls.push({ method, params });
    let result;
    if (method === "getGenesisHash") result = DEVNET;
    else if (method === "getSlot") result = SLOT;
    else if (method === "getMultipleAccounts") {
      // [the wallet, its token account]: the wallet is not open yet and holds test USDC; the orders of the issue: none yet
      result = { value: params[0].length === 2 ? [null, { owner: knos.TOKEN, lamports: 2039280, data: [b64(tokenBytes({ mint: knos.USDC_DEVNET, owner: params[0][0], amount: chain.holds })), "base64"] }]
        : params[0].map(() => null) };
    } else if (method === "getAccountInfo") result = { value: null };                 // the order was paid in full and closed
    else if (method === "getSignaturesForAddress") result = chain.paid ? [{ signature: SIG.pay, blockTime: NOW + 3600, err: null }, { signature: SIG.fund, blockTime: NOW, err: null }] : [];
    else if (method === "getTransaction") {
      const o = chain.order;
      result = params[0] === SIG.fund ? { blockTime: NOW, meta: { err: null, logMessages: logs([`knos3:funded order=${o} repo=${REPO_ID} issue=${ISSUE} seq=0 amount=50000000 fee=1250000 mode=0 by=0 source=${chain.wallet} flags=4 deadline=${NOW + 14 * 86400}`, "knos3:terms {}"]) } }
        : { blockTime: NOW + 3600, meta: { err: null, logMessages: logs([`knos3:paid order=${o} pr=12 payee=4242 amount=50000000 to=${chain.wallet}`, `knos3:settled order=${o} paid=50000000 of=50000000 fee=950000 tip=300000 judge=1`]) } };
    } else return route.fulfill({ status: 200, contentType: "application/json", headers: { "access-control-allow-origin": "*" }, body: JSON.stringify({ jsonrpc: "2.0", id: 1, error: { message: `the test's devnet has no ${method}` } }) });
    return route.fulfill({ status: 200, contentType: "application/json", headers: { "access-control-allow-origin": "*" }, body: JSON.stringify({ jsonrpc: "2.0", id: 1, result }) });
  });
  return ctx;
}

async function open(ctx) {
  const page = await ctx.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  await page.goto(`${base}#buy`, { waitUntil: "load" });
  // the page's own hook calls renderBuyer; until it is there (and after: it draws once), the test calls it the same way
  await page.evaluate(async () => { const m = await import("./buyer.js"); await m.renderBuyer(document.getElementById("buy"), {}); window.dispatchEvent(new HashChangeEvent("hashchange")); });
  await page.waitForSelector("#buy-sentence:not(:empty)");
  await page.evaluate(() => document.fonts.ready);
  return { page, errors };
}
const text = (page, sel) => page.$eval(sel, (e) => e.textContent.trim().replace(/\s+/g, " "));
const pick = async (page, sel, value) => { await page.selectOption(sel, value); };

// ---- the four steps, the templates ---------------------------------------------------------------------------------------------------------
const ctx = await context(1280);
const { page, errors } = await open(ctx);
check("the Buy page is shown alone at #buy, and its menu link is offered", await page.isVisible("#buy") && (await page.evaluate(() => document.body.dataset.page)) === "buy");
const heads = await page.$$eval("#buy section[id^=buy-step-] > h3", (l) => l.map((h) => h.textContent.trim()));
check("four plain steps on one screen", JSON.stringify(heads) === JSON.stringify(["What are you buying?", "When is it accepted?", "Pay", "What happened"]), heads);
check("  each step is visible", (await Promise.all([1, 2, 3, 4].map((n) => page.isVisible(`#buy-step-${n}`)))).every(Boolean));
const offered = await page.$$eval("#buy-template option", (l) => l.map((o) => o.value));
check("one issue: the four templates that fund one", JSON.stringify(offered) === JSON.stringify(["bugfix", "feature-blackbox", "milestone", "private-attested"]), offered);
for (const name of offered) {
  await pick(page, "#buy-template", name);
  const t = byName[name];
  check(`template ${name}: its ONE sentence, as knos terms show says it`, (await text(page, "#buy-sentence")) === `${t.sentence.replace(/`/g, "")}.`, await text(page, "#buy-sentence"));
  check(`  the comment that funds it is the template's own`, (await text(page, "#buy-comment")) === t.comment, await text(page, "#buy-comment"));
  check(`  it says how it is judged (${t.assurance}) and what is still trusted`, (await text(page, "#buy-mode")) === `judged ${t.assurance}`
    && JSON.stringify(await page.$$eval("#buy-trusted li", (l) => l.map((e) => e.textContent))) === JSON.stringify(t.trusted));
  check(`  a passkey ${t.passkey ? "can" : "cannot"} fund it, and the page says so`, (await page.isVisible("#buy-pk")) === t.passkey && (t.passkey || (await text(page, "#buy-pk-why")).includes(t.passkey_why_not)));
}
check("the three ways of judging are named, with what each was measured to stop", JSON.stringify(await page.$$eval("#buy-modes dt", (l) => l.map((e) => e.textContent.replace(" (this template)", "")))) === JSON.stringify(["in-process", "black-box", "hermetic"]));
await pick(page, "#buy-kind", "rate");
check("a rate per accepted pull request: the vendor is asked for", (await page.isVisible("#buy-vendor")) && /vendor's GitHub account/.test(await text(page, "#buy-sentence")), await text(page, "#buy-sentence"));
await page.fill("#buy-vendor", "octocat");
check("  its sentence and its comment are the standing offer's", (await text(page, "#buy-sentence")) === `${byName["standing-rate"].sentence.replace(/`/g, "")}.`
  && (await text(page, "#buy-comment")) === byName["standing-rate"].comment, [await text(page, "#buy-sentence"), await text(page, "#buy-comment")]);
check("card and bank: one honest line", (await text(page, "#buy-card")) === "Not available: it needs a licensed on-ramp partner, and Knos has none. Nothing here takes a card.");
check("the exception paths say who can trigger each", (await page.$$eval("#buy-exceptions dt", (l) => l.length)) === 4 && /Anyone can send it once the deadline has passed/.test(await text(page, "#buy-exceptions"))
  && /\/knos cancel/.test(await text(page, "#buy-exceptions")) && /inside the warranty window/.test(await text(page, "#buy-exceptions")));

// the buyer's own numbers go into the sentence and the comment
await pick(page, "#buy-kind", "issue");
await pick(page, "#buy-template", "milestone");
await page.fill("#buy-amount", "250.5"); await page.fill("#buy-days", "21"); await page.fill("#buy-checks", "build, e2e"); await page.fill("#buy-paths", "app/**");
check("the buyer's own amount, days, checks and paths are in the sentence",
  (await text(page, "#buy-sentence")) === "Pays 250.5 test USDC when checks build, e2e pass on a merge that only touches app/; 20% of it waits 30 days and goes back if the change is reverted; refund after 21 days.", await text(page, "#buy-sentence"));
check("  and in the comment", (await text(page, "#buy-comment")) === "/knos fund 250.5 checks: build, e2e paths: app/** holdback 20 warranty 30 days 21", await text(page, "#buy-comment"));
check("  the fee is said before anything is signed", /^You pay 256\.7625 test USDC: 250\.50 for whoever does the work, and a fee of 6\.2625 on top\./.test(await text(page, "#buy-cost")), await text(page, "#buy-cost"));
await page.fill("#buy-amount", "0.5");
check("an amount under the least is said in words, and no sentence is made of it", /An order takes at least 5\.00 test USDC/.test(await text(page, "#buy-sentence")), await text(page, "#buy-sentence"));

// ---- the passkey: Chromium's virtual authenticator ---------------------------------------------------------------------------------------------
const cdp = await ctx.newCDPSession(page);
await cdp.send("WebAuthn.enable");
const { authenticatorId } = await cdp.send("WebAuthn.addVirtualAuthenticator", { options: { protocol: "ctap2", transport: "internal", hasResidentKey: true, hasUserVerification: true, isUserVerified: true, automaticPresenceSimulation: true } });
await pick(page, "#buy-template", "bugfix");
await page.fill("#buy-issue", "https://github.com/octo/widgets/issues/7");
await page.click("#buy-pk-create");
await page.waitForSelector("#buy-pk-made");
chain.wallet = await text(page, "#buy-pk-address");
const made = await cdp.send("WebAuthn.getCredentials", { authenticatorId });
check("a passkey wallet is made: one credential on the authenticator, an address on the page", made.credentials.length === 1 && knos.isAddress(chain.wallet), chain.wallet);
check("  its test USDC is read from devnet, and the faucet path is a link, not a request", (await text(page, "#buy-pk-balance")) === "100.00 test USDC"
  && (await page.$eval("#buy-pk-faucet a", (a) => a.href)) === "https://faucet.circle.com/", await text(page, "#buy-pk-balance"));
const kept = await page.evaluate(() => JSON.parse(localStorage.getItem("knos-passkey")));
check("  the browser keeps its id and public key, as the Get paid page does, and nothing secret", Object.keys(kept).sort().join() === "credentialId,key" && /^0[23][0-9a-f]{64}$/.test(kept.key), kept);

chain.holds = 10_000_000;
await page.click("#buy-pk-refresh");
await page.waitForFunction(() => document.getElementById("buy-pk-balance").textContent.startsWith("10.00"));
await page.click("#buy-pk-sign");
await page.waitForSelector("#buy-pk-result .status.bad");
check("a wallet that holds less than the amount and the fee signs nothing", /The wallet holds 10\.00 test USDC, and 51\.25 is needed.*Nothing was signed\./.test(await text(page, "#buy-pk-result")) && !(await page.$("#buy-line")), await text(page, "#buy-pk-result"));
chain.holds = 100_000_000;
await page.click("#buy-pk-sign");
await page.waitForSelector("#buy-signed");
const line = await page.$eval("#buy-line", (e) => e.value);
check("the virtual passkey signs, and the one comment line appears", /^\/knos passkey-fund [A-Za-z0-9_-]{300,6000}$/.test(line), line.slice(0, 60));
const intent = JSON.parse(Buffer.from(line.split(" ")[2], "base64url").toString("utf8"));
chain.order = intent.order;
const data = Buffer.from(intent.data, "base64url"), terms = '{"accept":"","checks":[{"app":-1,"name":"lint"},{"app":-1,"name":"unit"}],"deny":[".github/**",".knos/**"],"mode":"merge","paths":["src/**","tests/**"],"reserve":0,"v":1}';
check("  the intent is for this order: the issue, the amount, the terms of step 2, the wallet's first nonce, about an hour of slots",
  intent.v === 1 && intent.amount === 50_000_000 && intent.nonce === 1 && intent.expirySlot === SLOT + buyer.SLOTS && intent.wallet === chain.wallet && intent.mint === knos.USDC_DEVNET
  && intent.program === ids.knos_passkey && intent.pay === ids.knos_pay && data[0] === 15 && Number(data.readBigUInt64LE(1)) === ISSUE && Number(data.readBigUInt64LE(9)) === REPO_ID
  && Number(data.readBigUInt64LE(17)) === 50_000_000 && data.subarray(158).toString() === terms && intent.order === (await text(page, "#buy-signed-order")), intent);
check("  the terms hash shown is the hash of those bytes", (await text(page, "#buy-signed-terms")) === createHash("sha256").update(terms).digest("hex"));
const cdj = Buffer.from(intent.clientDataJSON, "base64url"), auth = Buffer.from(intent.authenticatorData, "base64url"), client = JSON.parse(cdj.toString());
const challenge = await fund.fundChallenge(ids.knos_pay, intent.mint, new Uint8Array(data), intent.expirySlot, intent.nonce);
check("  the passkey signed the challenge the program computes, at this site", client.type === "webauthn.get" && client.challenge === Buffer.from(challenge).toString("base64url") && client.origin === base.slice(0, -1)
  && auth.subarray(0, 32).equals(createHash("sha256").update("localhost").digest()) && (auth[32] & 1) === 1, client);
const point = ECDH.convertKey(Buffer.from(intent.key, "hex"), "prime256v1", undefined, undefined, "uncompressed");
const spki = createPublicKey({ key: Buffer.concat([Buffer.from("3059301306072a8648ce3d020106082a8648ce3d030107034200", "hex"), point]), format: "der", type: "spki" });
const message = Buffer.concat([auth, createHash("sha256").update(cdj).digest()]), sig = Buffer.from(intent.signature, "base64url");
check("  the signature verifies under the wallet's key, with s in the lower half", sig.length === 64 && ecVerify("sha256", message, { key: spki, dsaEncoding: "ieee-p1363" }, sig)
  && BigInt(`0x${sig.subarray(32).toString("hex")}`) <= 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551n / 2n);
check("  the button opens the issue on GitHub, and the page says to paste the line", (await page.$eval("#buy-open", (a) => a.href)) === "https://github.com/octo/widgets/issues/7"
  && /paste it in the comment box/.test(await text(page, "#buy-pk-result")));
check("  nothing was sent to Solana: the page only read", chain.calls.every((c) => ["getGenesisHash", "getSlot", "getMultipleAccounts", "getAccountInfo"].includes(c.method)), [...new Set(chain.calls.map((c) => c.method))]);
writeFileSync(join(fixtures, "line.txt"), line);
await page.fill("#buy-amount", "60");
check("changing the order after signing takes the signed line away", !(await page.$("#buy-line")));
await page.fill("#buy-amount", "50");

// ---- what happened ----------------------------------------------------------------------------------------------------------------------------
check("the order's address is carried to step 4", (await page.$eval("#buy-order", (e) => e.value)) === intent.order);
await page.click("#buy-order-form button");
await page.waitForSelector("#buy-state");
check("an order the relay has not carried yet is said so", (await page.$eval("#buy-state", (e) => e.dataset.state)) === "none" && /the relay has not carried it yet/.test(await text(page, "#buy-state-words")));
chain.paid = true;
await page.click("#buy-order-form button");
await page.waitForSelector("#buy-state[data-state=paid]");
check("a paid order: its state from the chain's log, and the states it went through", (await text(page, "#buy-state")) === "Paid"
  && JSON.stringify(await page.$$eval("#buy-states li[data-reached='1']", (l) => l.map((e) => e.textContent.replace(" (now)", "")))) === JSON.stringify(["funded", "accepted", "paid"])
  && (await page.$$eval("#buy-states li", (l) => l.length)) === 6, await text(page, "#buy-states"));
check("  the receipt's four parts, in order", JSON.stringify(await page.$$eval("#buy-receipt > dt", (l) => l.map((e) => e.textContent)))
  === JSON.stringify(["What the issuer authenticated", "What the evaluator observed", "Which policy produced the verdict", "What trust remains"]) && /pull request #12/.test(await text(page, "#buy-receipt")));
check("  what the program logged, each line with its transaction", (await page.$$eval("#buy-events li a", (l) => l.map((a) => a.href))).every((h) => h.startsWith("https://explorer.solana.com/tx/")) && /paid 50\.00 to GitHub id 4242 for pull request #12/.test(await text(page, "#buy-events")), await text(page, "#buy-events"));

// ---- the statement: the bytes of `knos audit export` -------------------------------------------------------------------------------------------
await page.fill("#ost-owner", "acme");
await page.click("#ost-form button");
await page.waitForSelector("#ost-statement");
check("the newest month is shown first, and every month with a line is offered", JSON.stringify(await page.$$eval("#ost-month option", (l) => l.map((o) => o.value))) === JSON.stringify(["2026-10", "2026-09"])
  && (await page.$eval("#ost-statement", (e) => e.dataset.month)) === "2026-10");
await pick(page, "#ost-month", "2026-09");
await page.waitForSelector("#ost-statement[data-month='2026-09']");
const expected = { csv: readFileSync(join(fixtures, "expected.csv")), json: readFileSync(join(fixtures, "expected.json")) };
const head = JSON.parse(expected.json).head, rowsCount = JSON.parse(expected.json).rows_count;
check("the organisation's month: every line, the totals, the head both sides compare", (await page.$eval("#ost-statement", (e) => e.dataset.month)) === "2026-09"
  && (await page.$$eval("#ost-table tbody tr", (l) => l.length)) === rowsCount && (await text(page, "#ost-head")) === head && (await page.$$eval("#ost-totals tbody tr", (l) => l.length)) === 1, await text(page, "#ost-head"));
check("  a line says how the other party recomputes it", (await text(page, "#ost-recompute")).includes("knos audit export --owner 5001 --from 2026-09-01 --to 2026-09-30 --format csv"));
for (const fmt of ["csv", "json"]) {
  const [download] = await Promise.all([page.waitForEvent("download"), page.click(`#ost-${fmt}`)]);
  const got = readFileSync(await download.path());
  check(`  Export ${fmt.toUpperCase()} is byte for byte what knos audit export --format ${fmt} wrote (${got.length} bytes)`, got.equals(expected[fmt]) && download.suggestedFilename() === `knos-audit-5001-2026-09.${fmt}`, got.toString().slice(0, 200));
}
const users = asked.filter((u) => u.includes("/users/")).length;
await page.fill("#ost-owner", "5001");
await page.click("#ost-form button");
await page.waitForSelector("#ost-statement[data-month='2026-10']");
await pick(page, "#ost-month", "2026-09");
await page.waitForSelector("#ost-statement[data-month='2026-09']");
check("  the numeric id opens the same statement, with nothing asked of GitHub", (await text(page, "#ost-head")) === head && asked.filter((u) => u.includes("/users/")).length === users);

// ---- the width, and who was asked ----------------------------------------------------------------------------------------------------------------
if (shots) { mkdirSync(shots, { recursive: true }); await page.screenshot({ path: join(shots, "buyer-1280.png"), fullPage: true }); }
for (const width of [390, 320]) {
  await page.setViewportSize({ width, height: 800 });
  await page.evaluate(() => document.querySelectorAll("details").forEach((d) => { d.open = true; }));
  await page.waitForTimeout(150);
  const { over, culprits } = await measure(page);
  check(`the page does not scroll sideways at ${width} px, with a signed line, an order and a statement on it`, over <= 1, { over, culprits });
  if (shots && width === 390) { await page.screenshot({ path: join(shots, "buyer-390.png"), fullPage: true }); await page.screenshot({ path: join(shots, "buyer-390-top.png") }); }
}
const hosts = [...new Set(asked.map((u) => new URL(u).host))].sort();
check("no third-party request: only this site, GitHub's API and devnet's RPC were asked", refused.length === 0 && JSON.stringify(hosts) === JSON.stringify(["api.devnet.solana.com", "api.github.com", new URL(base).host].sort()), { refused, hosts });
check("no script error on the page", errors.length === 0, errors);
await ctx.close();

// a browser that kept the wallet uses it again; and the first look at 390 px, before anything is typed
const again = await context(390);
await again.addInitScript((saved) => { localStorage.setItem("knos-passkey", saved); }, JSON.stringify(kept));
const second = await open(again);
await second.page.waitForSelector("#buy-pk-made");
check("the passkey wallet a browser kept is reused, at the same address", (await text(second.page, "#buy-pk-address")) === chain.wallet && /this browser kept is in use/.test(await text(second.page, "#buy-pk-made")));
const first = await measure(second.page);
check("the page as it opens does not scroll sideways at 390 px", first.over <= 1, first);
if (shots) await second.page.screenshot({ path: join(shots, "buyer-390-open.png"), fullPage: true });
await again.close();

// a build of other program ids (a staging deployment): the wallet shown is the one passkey_fund.js signs for, the address
// under THAT build's knos_passkey, when it is made and when a browser recalls it
const STAGED = knos.b58(Uint8Array.from({ length: 32 }, (_, i) => (i * 11 + 7) % 256));
const passkeyLib = await import(pathToFileURL(join(root, "passkey.js")));
const stagedIds = async (c) => { await c.route(`${base}program_ids.json`, (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ...ids, knos_passkey: STAGED }) })); return c; };
const made3 = await stagedIds(await context(1280));
const third = await open(made3);
const cdp3 = await made3.newCDPSession(third.page);
await cdp3.send("WebAuthn.enable");
await cdp3.send("WebAuthn.addVirtualAuthenticator", { options: { protocol: "ctap2", transport: "internal", hasResidentKey: true, hasUserVerification: true, isUserVerified: true, automaticPresenceSimulation: true } });
await pick(third.page, "#buy-template", "bugfix");
await third.page.fill("#buy-issue", "https://github.com/octo/widgets/issues/7");
await third.page.click("#buy-pk-create");
await third.page.waitForSelector("#buy-pk-made");
const kept3 = await third.page.evaluate(() => JSON.parse(localStorage.getItem("knos-passkey")));
const staged3 = await passkeyLib.wallet(Buffer.from(kept3.key, "hex"), STAGED);
check("on a build of other program ids, the wallet made is the address under that build's knos_passkey", (await text(third.page, "#buy-pk-address")) === staged3
  && staged3 !== await passkeyLib.wallet(Buffer.from(kept3.key, "hex")), [await text(third.page, "#buy-pk-address"), staged3]);
await made3.close();
const recalled3 = await stagedIds(await context(1280));
await recalled3.addInitScript((saved) => { localStorage.setItem("knos-passkey", saved); }, JSON.stringify(kept));
const fourth = await open(recalled3);
await fourth.page.waitForSelector("#buy-pk-made");
const staged4 = await passkeyLib.wallet(Buffer.from(kept.key, "hex"), STAGED);
check("  and the wallet a browser kept is recalled at that address", (await text(fourth.page, "#buy-pk-address")) === staged4 && staged4 !== chain.wallet, [await text(fourth.page, "#buy-pk-address"), staged4]);
await recalled3.close();

await browser.close(); server.close();
console.log(process.exitCode ? "the Buy page FAILED" : "the Buy page holds");
