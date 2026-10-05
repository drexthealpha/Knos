// node tests/web/buyer.mjs <site dir> <fixture dir> [screenshot dir]
// The Buy page (web/buyer.js) in headless Chromium, on a build of the site (scripts/build_site.sh), against a mocked
// GitHub API and a mocked Solana devnet RPC, with Chromium's own virtual authenticator for the passkey (CDP:
// WebAuthn.enable, WebAuthn.addVirtualAuthenticator). The four steps render; each template shows its one sentence
// and what is still trusted; a passkey wallet is made, signs one order, and the line `/knos passkey-fund ...` appears,
// with a signature that verifies under the wallet's key over the challenge the program computes; the order's state
// is read back from the chain's log; the statement's two exports are the bytes `knos audit export` wrote (the fixture
// dir: expected.csv, expected.json, made by tests/test_site_buyer.py); nothing scrolls sideways at 390 px; and the
// page asks nobody but this site, GitHub and devnet. The console's six views (web/console.js) are each drawn from the
// same mocked chain: the fee as an amount and a share with the small-order warning, the organisation's budget and the
// rule that decides, what was billed before, the private case, the orders that need a person, and the receipt's five
// parts with who answers; a meter ledger dropped on the statement gives its three numbers; and a governed order is
// made from an empty page with no YAML and no terminal, its fields and clicks counted and printed. The signed line is written to <fixture dir>/line.txt, for the
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
const chain = { wallet: null, holds: 100_000_000, order: null, calls: [], paid: false, accounts: new Map(), sigs: new Map() };

// ---- an organisation with a budget, and its orders, as devnet and the site's files would hold them ---------------------------------------
// octo (GitHub id 6001) owns octo/widgets. Its Balance: a cap of 500 per order, 300 a day of which 240 is spent today,
// 2,000 in all of which 900 is spent, only for repository 5550001, spendable by ids 4242 and 4243; it holds 1,500.
const ORG = 6001, T = NOW + 40 * 86_400, DAY = Math.floor(T / 86_400), U = 1_000_000;
const addr = (n) => knos.b58(Uint8Array.from({ length: 32 }, (_, i) => (i * 7 + n * 13 + 1) % 256));
const txid = (ch) => ch.repeat(88);
const k2 = knos.v2.client(ids), BAL = addr(1);
const balanceBytes = at(160, [0, [1]], [3, [1]], [8, u64(ORG)], [16, knos.unb58(addr(2))], [48, knos.unb58(knos.USDC_DEVNET)], [80, u64(500 * U)], [96, u64(4242)], [104, u64(4243)], [128, u64(900 * U)]);
const balxBytes = at(152, [0, [1]], [8, u64(300 * U)], [16, u64(2000 * U)], [24, u64(REPO_ID)], [128, u64(DAY)], [136, u64(240 * U)], [144, u64(900 * U)]);
const orderBytes = ({ state = 1, issue = ISSUE, amount, paid = 0, deadline = T + 5 * 86_400, holdUntil = 0, reservedBy = 0, reservedUntil = 0, payee = 0 }) =>
  at(512, [0, [2]], [1, [state]], [3, [1]], [8, u64(REPO_ID)], [16, u64(issue)], [64, u64(amount)], [88, u64(paid)], [96, u64(deadline)], [112, u64(holdUntil)], [128, u64(reservedBy)],
    [136, u64(reservedUntil)], [152, u64(payee)], [168, u64(ORG)], [192, knos.unb58(BAL)], [288, knos.unb58(knos.USDC_DEVNET)]);
const owned = (data) => ({ owner: ids.knos_pay, lamports: 1, data: [b64(data), "base64"] });
chain.accounts.set(BAL, owned(balanceBytes));
chain.accounts.set(await k2.balxPda(BAL), owned(balxBytes));
chain.accounts.set(await k2.baltok(BAL), { owner: knos.TOKEN, lamports: 1, data: [b64(tokenBytes({ mint: knos.USDC_DEVNET, owner: BAL, amount: 1500 * U })), "base64"] });
// the orders: one open for the issue being bought (so it was ordered before), and one of each kind that needs a person
const anyissue = await import(pathToFileURL(join(root, "anyissue.js")));
const O = { live: await anyissue.orderAddress(knos, ids.knos_pay, REPO_ID, ISSUE, BAL, 0), paid: addr(11), held: addr(12), review: addr(13), reverted: addr(14), late: addr(15), stale: addr(16) };
chain.accounts.set(O.live, owned(orderBytes({ amount: 50 * U })));
chain.accounts.set(O.held, owned(orderBytes({ state: 3, issue: 21, amount: 30 * U, holdUntil: T + 5 * 86_400, payee: 777 })));
chain.accounts.set(O.review, owned(orderBytes({ state: 4, issue: 22, amount: 200 * U, paid: 160 * U, holdUntil: T + 10 * 86_400 })));
chain.accounts.set(O.late, owned(orderBytes({ issue: 24, amount: 70 * U, deadline: T - 86_400 })));
chain.accounts.set(O.stale, owned(orderBytes({ issue: 25, amount: 80 * U, reservedBy: 888, reservedUntil: T - 2 * 86_400 })));
chain.sigs.set(O.live, [{ signature: txid("7"), blockTime: T - 3600, err: null }]);
const auditLine = (order, kind, issue, more = {}) => ({ order, kind, issue, repository_id: REPO_ID, owner_id: ORG, date: "2026-10-20", time: `2026-10-20T10:00:${String(issue).padStart(2, "0")}Z`, funded_transaction: txid("5"),
  transaction: txid("6"), private: 0, standing: 0, currency: "test USDC", price_units: 0, paid_units: 0, held_units: 0, refunded_units: 0, reverted_units: 0, pull_request: "", supplier_ids: "", billing_key: "", exception: "", resolved_by: "", ...more });
const orgStatement = { type: "knos.audit-statement", version: 1, owner_id: ORG, months: { "2026-10": { scope: {}, lines: [
  auditLine(O.paid, "paid", ISSUE, { price_units: 50 * U, paid_units: 50 * U, pull_request: 12, supplier_ids: "4242", billing_key: `${O.paid}:${txid("5")}:0`, transaction: txid("8") }),
  auditLine(O.held, "held", 21, { price_units: 30 * U, held_units: 30 * U, supplier_ids: "777", exception: "held: the payee has bound no wallet" }),
  auditLine(O.review, "paid", 22, { price_units: 200 * U, paid_units: 160 * U, held_units: 40 * U, pull_request: 31 }),
  auditLine(O.reverted, "paid", 23, { price_units: 200 * U, paid_units: 160 * U, held_units: 40 * U, pull_request: 32 }),
  auditLine(O.reverted, "reverted", 23, { time: "2026-10-21T10:00:00Z", reverted_units: 40 * U, exception: "reverted inside the warranty", transaction: txid("9") }),
  auditLine(O.late, "open", 24, { price_units: 70 * U, held_units: 70 * U }),
  auditLine(O.stale, "open", 25, { price_units: 80 * U, held_units: 80 * U }) ] } } };
const logs = (lines) => [`Program ${ids.knos_pay} invoke [1]`, ...lines.map((l) => `Program log: ${l}`), `Program ${ids.knos_pay} success`];
const asked = [], refused = [];

async function context(width) {
  const ctx = await browser.newContext({ viewport: { width, height: 900 }, acceptDownloads: true });
  await ctx.grantPermissions(["clipboard-read", "clipboard-write"]).catch(() => {});
  await ctx.addInitScript((ms) => { Date.now = () => ms; }, T * 1000);      // the page's clock is the test's: a day's limit and a deadline do not move
  await ctx.route("**/*", (route) => {          // registered first, so asked last: nothing but this site, GitHub and devnet
    const url = route.request().url();
    asked.push(url);
    if (url.startsWith(base)) return route.continue();
    refused.push(url);
    return route.abort();
  });
  // the site's own files for the organisation: registered after the line above, so asked before it
  await ctx.route(`${base}audit/${ORG}.json`, (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(orgStatement) }));
  await ctx.route(`${base}r/octo/widgets.json`, (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ as_earner: { refusals_at_merge: 2 } }) }));
  await ctx.route("https://api.github.com/**", (route) => {
    const path = new URL(route.request().url()).pathname;
    asked.push(route.request().url());
    const octo = { id: ORG, login: "octo", type: "Organization" };
    const body = path === "/repos/octo/widgets" ? { id: REPO_ID, full_name: "octo/widgets", archived: false, private: false, owner: octo }
      : path === "/repos/octo/vault" ? { id: 5550002, full_name: "octo/vault", archived: false, private: true, owner: octo }
      : path === "/repos/solo/tool" ? { id: 5550003, full_name: "solo/tool", archived: false, private: false, owner: { id: 6002, login: "solo", type: "User" } }
      : path === `/repos/octo/widgets/issues/${ISSUE}` ? { title: "Parser crashes on an empty file", state: "open" } : path === "/users/acme" ? { id: 5001, login: "acme" }
      : path === "/users/octo" ? octo : path === "/users/mallory" ? { id: 999, login: "mallory" } : path === "/users/dana" ? { id: 4242, login: "dana" } : null;
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
    else if (method === "getProgramAccounts") {      // the Balances of one GitHub owner: its id at byte 8
      const want = params[1].filters.find((f) => f.memcmp)?.memcmp;
      result = params[0] === ids.knos_pay && want?.offset === 8 && want.bytes === knos.b58(u64(ORG)) ? [{ pubkey: BAL, account: chain.accounts.get(BAL) }] : [];
    } else if (method === "getMultipleAccounts" && params[0].some((a) => chain.accounts.has(a))) result = { value: params[0].map((a) => chain.accounts.get(a) || null) };
    else if (method === "getSignaturesForAddress" && chain.sigs.has(params[0])) result = chain.sigs.get(params[0]);
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
check("1. the fee is said before anything is signed, as an amount and as a share of the order", /^You pay 256\.7625 test USDC: 250\.50 for whoever does the work, and a fee of 6\.2625 on top, which is 2\.50% of the amount\./.test(await text(page, "#buy-cost"))
  && !(await page.isVisible("#buy-fee-warning")), await text(page, "#buy-cost"));
check("  on the same screen as the amount: the fee, the budget and what was billed before are in the amount's own step", await page.$eval("#buy-step-1", (s) => ["buy-amount", "buy-cost", "buy-fee-warning", "buy-allowed", "buy-before", "buy-private"].every((id) => s.querySelector(`#${id}`))));
for (const [amount, fee, pct] of [["5", "0.40", "8.00%"], ["12", "0.40", "3.33%"], ["19.99", "0.49975", "2.50%"]]) {
  await page.fill("#buy-amount", amount);
  const cost = await text(page, "#buy-cost"), warn = await text(page, "#buy-fee-warning");
  check(`  an order of ${amount} shows the warning: fee ${fee}, ${pct}, never only the headline rate`, (await page.isVisible("#buy-fee-warning")) && cost.includes(`a fee of ${fee} on top, which is ${pct} of the amount`)
    && warn.includes(`This order's fee is ${pct}.`) && /never less than 0\.40 test USDC/.test(warn) && /an order of 5\.00 costs 8\.00%/.test(warn) && /pooled into one order with milestones, or bought at a standing rate/.test(warn), [cost, warn]);
}
await page.fill("#buy-amount", "20");
check("  from 20 up there is no warning, and the share is still said", !(await page.isVisible("#buy-fee-warning")) && /a fee of 0\.50 on top, which is 2\.50% of the amount/.test(await text(page, "#buy-cost")), await text(page, "#buy-cost"));
const feeRows = await page.$$eval("#buy-fee-rows tbody tr", (l) => l.map((r) => [...r.cells].map((c) => c.textContent)));
check("  the fee at five sizes is the price book's: 5 -> 0.40 (8.00%) ... 50,000 -> 515 (1.03%)", JSON.stringify(feeRows) === JSON.stringify([["5.00", "0.40", "8.00%"], ["20.00", "0.50", "2.50%"], ["1,000.00", "25.00", "2.50%"], ["5,000.00", "65.00", "1.30%"], ["50,000.00", "515.00", "1.03%"]]), feeRows);
await page.fill("#buy-amount", "0.5");
check("an amount under the least is said in words, and no sentence is made of it", /An order takes at least 5\.00 test USDC/.test(await text(page, "#buy-sentence")), await text(page, "#buy-sentence"));

// ---- before funding: the budget, what was billed before, the private case -----------------------------------------------------------------------
const part = (page, box, name) => text(page, `${box} [data-part=${name}]`);
const verdict = (page) => page.$eval("#buy-allowed .receipt", (e) => ({ ok: e.dataset.ok, rule: e.dataset.rule, words: e.textContent.trim() }));
await pick(page, "#buy-template", "bugfix");
await page.fill("#buy-amount", "50");
await page.fill("#buy-issue", "https://github.com/octo/widgets/issues/7");
await page.waitForSelector("#buy-allowed .receipt");
check("2. the organisation's budget is read from devnet: cap, left today, left in all, repositories, who may spend",
  (await part(page, "#buy-allowed", "cap")) === "500.00 test USDC" && (await part(page, "#buy-allowed", "day")) === "60.00 test USDC of 300.00" && (await part(page, "#buy-allowed", "total")) === "1,100.00 test USDC of 2,000.00"
  && (await part(page, "#buy-allowed", "repos")) === `only GitHub repository id ${REPO_ID}` && (await part(page, "#buy-allowed", "who")) === `the owner (GitHub id ${ORG}) and GitHub ids 4242, 4243`
  && /octo \(an organisation, GitHub id 6001\)/.test(await text(page, "#buy-allowed")) && /holds 1,500\.00 test USDC/.test(await text(page, "#buy-allowed")), await text(page, "#buy-allowed"));
let said = await verdict(page);
check("  50 with its fee (51.25) passes, and the page says inside which limits", said.ok === "1" && said.rule === "ok" && /51\.25/.test(said.words)
  && (await part(page, "#buy-allowed", "fee")) === "1.25 test USDC, 2.50% of the amount", said);
check("  it was asked of the chain before any comment exists: one getProgramAccounts, and nothing was sent", chain.calls.filter((c) => c.method === "getProgramAccounts").length === 1 && !(await page.$("#buy-line")));
await page.fill("#buy-amount", "250.5");
said = await verdict(page);
check("  an over-budget funding shows the deciding rule: today's limit", said.ok === "0" && said.rule === "day" && (await part(page, "#buy-allowed", "rule")) === "today's limit"
  && /efused/.test(said.words) && /256\.7625/.test(said.words) && /300\.00/.test(said.words) && /60\.00 (test USDC of 300\.00 )?is left/.test(said.words), said);
await page.fill("#buy-amount", "600");
said = await verdict(page);
check("  over the cap: the cap per order decides, before the day's limit", said.ok === "0" && said.rule === "cap" && (await part(page, "#buy-allowed", "rule")) === "the cap per order" && /500\.00/.test(said.words) && /600\.00/.test(said.words), said);
await page.fill("#buy-amount", "50");
await page.fill("#buy-by", "mallory"); await page.dispatchEvent("#buy-by", "change");
await page.waitForFunction(() => document.querySelector("#buy-allowed .receipt")?.dataset.rule === "spender");
said = await verdict(page);
check("  a comment by an account that is not a spender: who may spend decides", said.ok === "0" && /GitHub id 999 is not the owner \((id )?6001\) and is not one of (the|this Balance's) spenders/.test(said.words) && (await part(page, "#buy-allowed", "rule")) === "who may spend", said);
await page.fill("#buy-by", "dana"); await page.dispatchEvent("#buy-by", "change");
await page.waitForFunction(() => document.querySelector("#buy-allowed .receipt")?.dataset.ok === "1");
check("  a listed spender passes", /51\.25/.test((await verdict(page)).words) && /comment by dana \(GitHub id 4242\)/.test(await text(page, "#buy-allowed")), await verdict(page));

const before = await page.$eval("#buy-before .receipt", (e) => ({ billed: e.dataset.billed, orders: e.dataset.orders, words: e.textContent.trim() }));
check("3. billed before: the earlier payment and the open order for the same repository and issue", before.billed === "1" && before.orders === "2"
  && before.words === "Yes. octo/widgets#7 was billed before: 1 payment on 2 orders. Funding again buys the same issue a second time.", before);
const earlier = await page.$$eval("#buy-before-rows li", (l) => l.map((e) => ({ kind: e.dataset.kind, words: e.textContent.replace(/\s+/g, " ").trim(), links: [...e.querySelectorAll("a")].map((a) => a.href) })));
check("  each with its transaction: the payment's and the funding's, and the deliverable (order and milestone)", earlier.length === 2 && earlier[0].kind === "paid" && /paid, 50\.00 test USDC, pull request #12\. Deliverable: order .{6}…, milestone 0\./.test(earlier[0].words)
  && earlier[0].links.includes(`https://explorer.solana.com/tx/${txid("8")}?cluster=devnet`) && earlier[0].links.includes(`https://explorer.solana.com/tx/${txid("5")}?cluster=devnet`)
  && earlier[1].kind === "live" && /On devnet now: funded, not paid yet, 50\.00 test USDC/.test(earlier[1].words) && earlier[1].links.includes(`https://explorer.solana.com/tx/${txid("7")}?cluster=devnet`), earlier);
await page.fill("#buy-issue", "https://github.com/octo/widgets/issues/99"); await page.dispatchEvent("#buy-issue", "change");
await page.waitForFunction(() => document.querySelector("#buy-before .receipt")?.dataset.orders === "0");
check("  an issue nobody ordered: said so, in words", /^No\. No earlier order or payment for octo\/widgets#99 is in the organisation's statement/.test(await text(page, "#buy-before .receipt")), await text(page, "#buy-before .receipt"));
await page.fill("#buy-issue", "solo/tool#3"); await page.dispatchEvent("#buy-issue", "change");
await page.waitForFunction(() => document.querySelector("#buy-allowed .receipt")?.dataset.rule === "no Balance");
check("  an owner with no Balance: no budget governs, and the page says what does", /solo \(a personal account, GitHub id 6002\) has opened no Balance on devnet/.test(await text(page, "#buy-allowed")) && /at most 100\.00 test USDC per comment/.test(await text(page, "#buy-allowed")));

check("4. a public repository and a public template: no private panel", !(await page.isVisible("#buy-private")));
const privateSays = async (why) => { const t = await text(page, "#buy-private"); return (await page.isVisible("#buy-private")) && (await page.$eval("#buy-private", (e) => e.dataset.why)) === why
  && /The supplier cannot settle alone/.test(t) && /only a run of your own workflow, in a repository you control/.test(t) && /The evidence is where you control access/.test(t)
  && /Name an arbiter at funding, if that matters/.test(t) && /arbiter @their-account/.test(t) && /Neither exists today/.test(t); };
await pick(page, "#buy-template", "private-attested");
check("  the template private-attested: what the supplier can and cannot do alone, in the interface", await privateSays("template"), await text(page, "#buy-private"));
await pick(page, "#buy-template", "bugfix");
await page.fill("#buy-issue", "octo/vault#4"); await page.dispatchEvent("#buy-issue", "change");
await page.waitForSelector("#buy-private[data-why=github]");
check("  a repository GitHub says is private: the same panel, whatever the template", await privateSays("github"));
await page.fill("#buy-issue", "octo/gone#4"); await page.dispatchEvent("#buy-issue", "change");
await page.waitForSelector("#buy-private[data-why=hidden]");
check("  a repository GitHub does not show: the panel says it applies if it is private", (await privateSays("hidden")) && /GitHub shows no public repository at that address/.test(await text(page, "#buy-private")));
if (shots) { mkdirSync(shots, { recursive: true }); await page.fill("#buy-issue", "https://github.com/octo/widgets/issues/7"); await page.dispatchEvent("#buy-issue", "change"); await page.fill("#buy-amount", "250.5");
  await page.waitForFunction(() => document.querySelector("#buy-before .receipt")?.dataset.orders === "2"); await (await page.$("#buy-step-1")).screenshot({ path: join(shots, "console-before-funding-1280.png") });
  await pick(page, "#buy-template", "private-attested"); await page.fill("#buy-amount", "12"); await (await page.$("#buy-step-1")).screenshot({ path: join(shots, "console-private-small-1280.png") }); await page.fill("#buy-amount", "50"); }
await page.fill("#buy-by", ""); await page.dispatchEvent("#buy-by", "change");
chain.accounts.delete(O.live); chain.sigs.delete(O.live);          // the passkey below funds this issue: its own order is the first

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
check("  nothing was sent to Solana: the page only read", chain.calls.every((c) => ["getGenesisHash", "getSlot", "getMultipleAccounts", "getAccountInfo", "getProgramAccounts", "getSignaturesForAddress"].includes(c.method)), [...new Set(chain.calls.map((c) => c.method))]);
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
const receipt = await page.$$eval("#buy-receipt > dt", (l) => l.map((e) => [e.textContent, e.nextElementSibling.textContent.trim().replace(/\s+/g, " ")]));
check("6. beside accepted: the receipt's five parts as headings, in order", JSON.stringify(receipt.map((r) => r[0]))
  === JSON.stringify(["What the issuer authenticated", "What the evaluator observed", "Which policy produced the verdict", "Who authorised the money, and under which limit", "What trust remains"]), receipt.map((r) => r[0]));
check("  one line each, from what the chain's log holds: the token, the verdict, the terms, who funded, what is trusted", /GitHub signed a token for one run of the pinned workflow/.test(receipt[0][1]) && /Verdict: accepted, for pull request #12\. Judged by a neutral run/.test(receipt[1][1])
  && /The terms fixed at funding, in 22222222…/.test(receipt[2][1]) && receipt[3][1].startsWith(`The wallet ${chain.wallet.slice(0, 6)}… signed the funding itself, in 22222222…`) && /No organisation's budget was involved/.test(receipt[3][1]) && receipt[4][1].length > 40, receipt);
check("  who answers if this fails: the founder alone, no support contract, said exactly", (await text(page, "#buy-answers")).startsWith("Today the founder alone. There is no support contract, no on-call team and no service-level agreement, and nobody else to call."), await text(page, "#buy-answers"));
if (shots) await (await page.$("#buy-step-4")).screenshot({ path: join(shots, "console-result-1280.png") });

// ---- 5. what needs a person ---------------------------------------------------------------------------------------------------------------------
await page.fill("#buy-exc-scope", "octo/widgets");
await page.click("#buy-exc-form button");
await page.waitForSelector("#buy-exc-rows");
const exc = await page.$$eval("#buy-exc-rows > div", (l) => l.map((e) => ({ kind: e.dataset.kind, ...Object.fromEntries(["what", "action", "who"].map((p) => [p, e.querySelector(`[data-part=${p}]`).textContent.trim()])) })));
const one = (kind) => exc.find((e) => e.kind === kind) || {};
check("5. a repository's orders that need a person: held, in a review window, reverted, past deadline, stale, refused tokens", JSON.stringify(exc.map((e) => e.kind)) === JSON.stringify(["held", "review", "reverted", "refundable", "stale", "refused"])
  && (await text(page, "#buy-exc-count")) === "6 things need a person.", exc.map((e) => e.kind));
check("  each says what happened, the one action that resolves it, and who can take it", exc.every((e) => e.what.length > 30 && e.action.length > 10 && e.who.length > 3), exc);
check("  held: the payee binds a wallet", /the payee \(GitHub id 777\) has bound no wallet\. 30\.00 test USDC waits until/.test(one("held").what) && /^Bind a wallet on the Get paid page/.test(one("held").action) && one("held").who === "the payee", one("held"));
check("  a review window: 40.00 held back, and the revert is the buyer's repository's to run", /40\.00 test USDC held back in the review window, which ends/.test(one("review").what) && /run the revert/.test(one("review").action) && /a signed run of the order's repository/.test(one("review").who), one("review"));
check("  reverted: the money came back; the two parties decide", /40\.00 test USDC went back to the funder/.test(one("reverted").what) && one("reverted").who === "the buyer and the supplier", one("reverted"));
check("  past its deadline: anyone sends the refund", /Past its deadline .* and unpaid: 70\.00 test USDC can go back/.test(one("refundable").what) && /^Send the refund/.test(one("refundable").action) && one("refundable").who === "anyone", one("refundable"));
check("  reserved and stale: who reserved it, and when it ran out", /Reserved by GitHub id 888, and the reservation ran out/.test(one("stale").what) && one("stale").who === "the buyer", one("stale"));
check("  refused tokens, from the site's file of the repository", /^2 tokens were refused by the relay at a merge/.test(one("refused").what) && one("refused").who === "the supplier", one("refused"));
check("  the order that was paid the plain way is not in the list, and the source is said", !(await text(page, "#buy-exc-rows")).includes(O.paid.slice(0, 6)) && /From 7 lines of the site's statement of GitHub id 6001 and the 6 order accounts read from devnet/.test(await text(page, "#buy-exc-source")), await text(page, "#buy-exc-source"));
if (shots) await (await page.$("#buy-exc-card")).screenshot({ path: join(shots, "console-exceptions-1280.png") });
await page.fill("#buy-exc-scope", "acme");
await page.click("#buy-exc-form button");
await page.waitForFunction(() => /GitHub id 5001/.test(document.getElementById("buy-exc-source")?.textContent || ""));
const acme = await page.$$eval("#buy-exc-rows > div", (l) => l.map((e) => e.dataset.kind));
check("  an organisation, from its statement alone: the revert and the arbiter's ruling are named", acme.includes("reverted") && acme.includes("challenged"), acme);
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
// one order of the month as four linked objects, on one screen, and the files a finance system imports
{
  const fd = await import(pathToFileURL(join(root, "finance_data.js")).href), con = await import(pathToFileURL(join(root, "console.js")).href);
  const cards = await page.$$eval("#ost-objects [data-object]", (l) => l.map((c) => ({ key: c.dataset.object, card: c.classList.contains("k-card"), tilt: c.hasAttribute("data-tilt"), head: c.querySelector(".k-kicker").childNodes[0].textContent.trim(),
    labels: [...c.querySelectorAll("dl.facts > dt")].map((d) => d.textContent), top: Math.round(c.getBoundingClientRect().top) })));
  check("the four linked objects of the chosen order are on one screen: Authorisation, Acceptance, Commercial record, Settlement status, each a card of six labelled values at most",
    cards.map((c) => c.head).join("|") === "Authorisation|Acceptance|Commercial record|Settlement status" && cards.map((c) => c.key).join() === fd.OBJECTS.join() && cards.every((c) => c.card && c.tilt && c.labels.length >= 3 && c.labels.length <= 6)
    && cards[0].labels.join("|") === "Buyer|Supplier|Scope|Budget|Approved by|Second approver" && cards[1].labels.join("|") === "Verdict|Artifact|Policy|Policy version|Evaluator|Evidence"
    && cards[2].labels.join("|") === "Billable deliverable|Amount|Fee|Invoice line|Dispute|Credit", JSON.stringify(cards));
  const WORDS = ["paid outside Knos", "payable", "held", "refunded", "devnet demonstration"];
  const options = await page.$$eval("#ost-order option", (l) => l.map((o) => o.textContent));
  const chips = [];
  for (let n = 0; n < options.length; n++) {
    await pick(page, "#ost-order", String(n));
    chips.push(await page.$eval("#ost-objects .k-objects", (e) => [e.dataset.chip, e.querySelector('[data-object="settlement"] .pill').textContent, e.querySelectorAll("[data-object]").length, e.querySelector("[data-object-trust]").textContent.trim().length > 20,
      e.querySelector("[data-object-said]").textContent.trim().length > 10]));
  }
  check("  every order of the month has its four, a status chip in the settlement words, what remains trusted under Acceptance, and the status said in a sentence",
    options.length >= 3 && chips.every(([chip, shown, n, trust, said]) => WORDS.includes(chip) && shown === chip && n === 4 && trust && said) && options.every((o, n) => o.endsWith(`: ${chips[n][0]}`)), JSON.stringify([options, chips]));
  check("  a payment on devnet is a demonstration in test money, never called paid", chips.some(([chip]) => chip === "devnet demonstration") && !chips.some(([chip]) => /^paid$|paid on/.test(chip)) && Object.values(con.CHIP).every((w) => WORDS.includes(w))
    && Object.keys(con.CHIP).sort().join() === [...fd.SETTLEMENTS].sort().join());
  const offered = await page.$$eval("#ost-exports [data-export]", (l) => l.map((b) => [b.dataset.export, b.textContent, b.nextElementSibling?.dataset.unverified === b.dataset.export ? b.nextElementSibling.textContent : ""]));
  check("  five files for a finance system: the generic one, then NetSuite, SAP, Coupa and QuickBooks, each of those four marked best effort, unverified (docs/FINANCE.md)",
    offered.map((o) => o[0]).sort().join() === "coupa,generic,netsuite,quickbooks,sap" && offered[0][0] === "generic" && offered.every(([fmt, , mark]) => (fmt === "generic" ? mark === "" : mark === "best effort, unverified"))
    && Object.entries(fd.FORMATS).every(([fmt, f]) => f.unverified === (fmt !== "generic")) && /best effort|unverified/i.test(readFileSync(new URL("../../docs/FINANCE.md", import.meta.url), "utf8")), JSON.stringify(offered));
  const shownHead = await text(page, "#ost-head");
  for (const fmt of ["generic", "netsuite"]) {
    const [download] = await Promise.all([page.waitForEvent("download"), page.click(`#ost-exports [data-export="${fmt}"]`)]);
    const got = readFileSync(await download.path(), "utf8");
    check(`  the ${fmt} file is made in the page from the rows on screen${fmt === "generic" ? ", and carries the statement and its head" : ""}`, download.suggestedFilename() === `knos-audit-5001-2026-09-${fmt}.csv`
      && (fmt === "generic" ? got.startsWith("knos.finance-export,version,1,generic\n") && fd.statementOf(got).head === shownHead : got.startsWith("External ID,Vendor,Date,")), got.slice(0, 160));
  }
  check("  nothing of it runs off the side", (await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)) <= 1);
}
// 7. a meter ledger dropped onto the statement: its three numbers, and the exports stay what they were
const evalLine = (order, artifact, milestone, accepted) => JSON.stringify({ accepted, artifact: artifact.repeat(40), buyer: 5001, id: createHash("sha256").update(`${order}${artifact}${milestone}`).digest("hex"), milestone, order: order.repeat(64), policy: "c".repeat(64), rate: 2000000, seller: 555000 });
const evals = [evalLine("a", "1", 0, 1), evalLine("a", "2", 0, 1), evalLine("a", "3", 1, 1), evalLine("b", "4", 0, 0), evalLine("b", "5", 0, 0)];
const ledger = [JSON.stringify({ batch: { accepted: 3, buyer: 5001, count: 5, month: 202609, root: "0".repeat(64), seller: 555000, seq: 0, value: 6000000 } }), ...evals, evals[0], ""].join("\n");
const meterOf = () => page.$$eval("#ost-meter-numbers [data-meter]", (l) => Object.fromEntries(l.map((e) => [e.dataset.meter, e.querySelector("strong").textContent])));
await page.evaluate((body) => { const dt = new DataTransfer(); dt.items.add(new File([body], "ledger-2026-09.jsonl", { type: "application/x-ndjson" }));
  document.getElementById("buy-statement-box").dispatchEvent(new DragEvent("drop", { dataTransfer: dt, bubbles: true, cancelable: true })); }, ledger);
await page.waitForSelector("#ost-meter-numbers");
check("7. a meter ledger dropped on the statement: evaluations 5, accepted outcomes 2, rejected 2 (the same evidence twice is one evaluation; two artifacts of one deliverable are one outcome)",
  JSON.stringify(await meterOf()) === JSON.stringify({ evaluations: "5", accepted_outcomes: "2", rejected: "2" }) && !(await page.$("#ost-meter-problems")) && !/differ/.test(await text(page, "#ost-meter-note")), await meterOf());
const fixed = [ledger.trim(), JSON.stringify({ correction: { batch: "202609.0", by: 5001, id: JSON.parse(evals[3]).id, kind: "verdict", accepted: 1 } }), JSON.stringify({ correction: { batch: "202609.0", by: 5001, id: JSON.parse(evals[4]).id, kind: "withdrawn" } }), "not json"].join("\n");
await page.setInputFiles("#ost-meter-file", { name: "fixed.jsonl", mimeType: "text/plain", buffer: Buffer.from(fixed) });
await page.waitForSelector("#ost-meter-numbers[data-file='fixed.jsonl']");
check("  corrections are applied as the ledger applies them: a verdict replaced, an evaluation withdrawn; a line that is not JSON is named", JSON.stringify(await meterOf()) === JSON.stringify({ evaluations: "4", accepted_outcomes: "3", rejected: "0" })
  && /2 corrections/.test(await text(page, "#ost-meter-note")) && /differ by 1/.test(await text(page, "#ost-meter-note")) && /Line 10 is not JSON/.test(await text(page, "#ost-meter-problems")), [await meterOf(), await text(page, "#ost-meter-note")]);
check("  the statement's head is the same after the ledger was read", (await text(page, "#ost-head")) === head);
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
if (shots) { await page.screenshot({ path: join(shots, "buyer-1280.png"), fullPage: true }); await (await page.$("#buy-statement")).screenshot({ path: join(shots, "console-statement-meter-1280.png") }); }
// every console view on the page at once: the small-order warning, the private panel, the budget, what was billed, the exceptions, the receipt, the meter
await pick(page, "#buy-template", "private-attested");
await page.fill("#buy-amount", "12");
await page.fill("#buy-exc-scope", "octo/widgets");
await page.click("#buy-exc-form button");
await page.waitForFunction(() => /GitHub id 6001/.test(document.getElementById("buy-exc-source")?.textContent || ""));
check("the six views are on the page together", (await Promise.all(["#buy-fee-warning", "#buy-allowed .receipt", "#buy-before .receipt", "#buy-private", "#buy-exc-rows", "#buy-receipt", "#buy-answers", "#ost-meter-numbers"].map((s) => page.isVisible(s)))).every(Boolean));
for (const width of [390, 320]) {
  await page.setViewportSize({ width, height: 800 });
  await page.evaluate(() => document.querySelectorAll("details").forEach((d) => { d.open = true; }));
  await page.waitForTimeout(150);
  const { over, culprits } = await measure(page);
  check(`the page does not scroll sideways at ${width} px, with a signed line, an order and a statement on it`, over <= 1, { over, culprits });
  if (shots && width === 390) { await page.screenshot({ path: join(shots, "buyer-390.png"), fullPage: true }); await page.screenshot({ path: join(shots, "buyer-390-top.png") }); }
  if (shots) for (const [name, sel] of [["before-funding", "#buy-step-1"], ["exceptions", "#buy-exc-card"], ["result", "#buy-step-4"]]) await (await page.$(sel)).screenshot({ path: join(shots, `console-${name}-${width}.png`) });
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
// the issue's budget and earlier orders are drawn above the button a moment after the box is filled: wait for them, so the press does not land while the page is still moving
await third.page.waitForFunction(() => { const t = document.getElementById("buy-before").textContent.trim(); return !/^Write the issue above|^Reading/.test(t); }, null, { timeout: 15000 }).catch(() => {});
await third.page.click("#buy-pk-create");
await third.page.waitForSelector("#buy-pk-made").catch(async (e) => { console.error("DEBUG status:", await third.page.textContent("#buy-pk-status"), "| errors:", JSON.stringify(third.errors), "| focus:", await third.page.evaluate(() => document.hasFocus())); throw e; });
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

// ---- a governed order from an empty page: no YAML, no terminal; the fields and the clicks are counted --------------------------------------------
// "Governed": funded by comment from the organisation's Balance, after the page said the budget lets it through and that
// the issue was not billed before. The count is of what the operator does on this page; the last act is on GitHub.
chain.accounts.set(O.live, owned(orderBytes({ amount: 50 * U })));
const gov = await context(1280);
await gov.route("https://github.com/**", (route) => route.fulfill({ status: 200, contentType: "text/html", body: "<title>the issue</title>" }));
const fifth = await open(gov), g = fifth.page, did = { fields: 0, clicks: 0 }, started = Date.now();
const fillIn = async (sel, value) => { did.fields++; await g.fill(sel, value); await g.dispatchEvent(sel, "change"); };
const choose = async (sel, value) => { did.fields++; await g.selectOption(sel, value); };
await fillIn("#buy-issue", "https://github.com/octo/widgets/issues/99");
await choose("#buy-template", "milestone");
await fillIn("#buy-amount", "40");
await g.waitForFunction(() => document.querySelector("#buy-allowed .receipt")?.dataset.ok === "1" && document.querySelector("#buy-before .receipt")?.dataset.orders === "0");
check("a governed order: the budget passes and nothing was billed before, said before the comment exists", /41\.00/.test(await text(g, "#buy-allowed .receipt")) && /^No\./.test(await text(g, "#buy-before .receipt")));
did.clicks++; await g.click("#buy-comment-copy");
const copied = await g.evaluate(() => navigator.clipboard.readText());
check("  one click copies the comment that funds it under the template's terms", copied === "/knos fund 40 checks: unit holdback 20 warranty 30 days 30" && copied === (await text(g, "#buy-comment")), copied);
did.clicks++;
const [popup] = await Promise.all([gov.waitForEvent("page"), g.click("#buy-comment-open")]);
check("  the next click opens the issue on GitHub, where the line is pasted", popup.url() === "https://github.com/octo/widgets/issues/99", popup.url());
const pathText = await g.$$eval("#buy-step-1, #buy-step-2, #buy-step-3", (l) => l.map((e) => e.innerText).join("\n"));
check("  the path asks for no YAML and no terminal: steps 1 to 3 name neither, and show no command to run in a shell", !/ya?ml|terminal|command line|\bshell\b/i.test(pathText) && !/\bknos [a-z]/.test(pathText.replace(/\/knos /g, "")), pathText.match(/.{0,40}(ya?ml|terminal|command line|\bshell\b|\bknos [a-z]).{0,40}/i)?.[0]);
check(`  it took ${did.fields} fields and ${did.clicks} clicks on the page`, did.fields === 3 && did.clicks === 2, did);
console.log(`GOVERNED ORDER: ${did.fields} fields, ${did.clicks} clicks on the page; then one paste and one click on GitHub`);
check("  no script error on that path", fifth.errors.length === 0, fifth.errors);
if (shots) await (await g.$("#buy-step-3")).screenshot({ path: join(shots, "console-governed-pay-1280.png") });
await gov.close();

// a build that has web/controls_data.js: its explainFunding and its fee table are what the page shows
const ruled = await context(1280);
await ruled.route(`${base}controls_data.js`, (route) => route.fulfill({ status: 200, contentType: "text/javascript", body: `
  export const explainFunding = ({ balance, balx, repoId, amount, byId }) => ({ ok: false, rule: "a rule of the file", sentence: "Said by the build's own rules for " + amount + " in " + repoId + ".", fee: 1250000, effectivePct: "2.50" });
  export const feeTable = () => [{ amount: 5000000, fee: 400000, total: 5400000, effectivePct: "8.00" }];` }));
const sixth = await open(ruled);
await sixth.page.fill("#buy-issue", "octo/widgets#7"); await sixth.page.dispatchEvent("#buy-issue", "change");
await sixth.page.waitForSelector("#buy-allowed .receipt");
check("a build with controls_data.js: its explainFunding decides what the budget panel says, and its table is the fee table", (await text(sixth.page, "#buy-allowed .receipt")) === `Said by the build's own rules for 50000000 in ${REPO_ID}.`
  && (await text(sixth.page, "#buy-allowed [data-part=rule]")) === "a rule of the file" && (await text(sixth.page, "#buy-allowed [data-part=fee]")) === "1.25 test USDC, 2.50% of the amount"
  && JSON.stringify(await sixth.page.$$eval("#buy-fee-rows tbody tr", (l) => l.map((r) => [...r.cells].map((c) => c.textContent)))) === JSON.stringify([["5.00", "0.40", "8.00%"]]), await text(sixth.page, "#buy-allowed"));
await ruled.close();

await browser.close(); server.close();
console.log(process.exitCode ? "the Buy page FAILED" : "the Buy page holds");
