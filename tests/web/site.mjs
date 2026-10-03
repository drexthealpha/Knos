// node tests/web/site.mjs <site dir> [screenshot.png]
// The built site (scripts/build_site.sh) in headless Chromium against a mocked GitHub API, a mocked Solana devnet RPC
// and a mocked wallet. Every view renders; each flow does what the page says; the transactions the wallet is asked to
// sign are byte for byte the ones sdk/settle builds; a cluster that is not devnet is refused; the numbers shown are
// the numbers in the recorded stats.json samples; the page asks nobody but GitHub and devnet. Needs the `playwright`
// package (tests.yml installs it).
import pw from "playwright";
const { chromium } = pw;
import { createServer } from "node:http";
import { readFileSync, existsSync } from "node:fs";
import { join, extname, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import * as knos from "../../sdk/settle/index.js";

const root = process.argv[2];
const here = dirname(fileURLToPath(import.meta.url));
const recorded = (name) => JSON.parse(readFileSync(join(here, "recorded", `${name}.json`), "utf8"));
const check = (name, cond, detail) => { if (!cond) { console.error("FAIL", name, detail === undefined ? "" : detail); process.exitCode = 1; } else console.log("ok  ", name); };

// ---- bytes: the accounts of the two programs, as the chain would hold them (layouts: sdk/settle readers, idl/) ------------
const DEVNET = "EtWTRABZaYq6iMfeYKouRu166VU2xqa1wcaWoxPkrZBG", MAINNET = "5eykt4UsFv8P8NJdTREpY1vzqKqZKvdpKuc147dw2N9d";
const A58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz";
const fromB58 = (s) => { let n = 0n; for (const c of s) n = n * 58n + BigInt(A58.indexOf(c)); const out = []; for (; n > 0n; n >>= 8n) out.unshift(Number(n & 255n)); for (const c of s) { if (c !== "1") break; out.unshift(0); } return Uint8Array.from(out); };
const u32 = (n) => { const b = new Uint8Array(4); new DataView(b.buffer).setUint32(0, n, true); return b; };
const u64 = (n) => { const b = new Uint8Array(8); new DataView(b.buffer).setBigUint64(0, BigInt(n), true); return b; };
const i64 = (n) => { const b = new Uint8Array(8); new DataView(b.buffer).setBigInt64(0, BigInt(n), true); return b; };
const at = (size, ...fields) => { const out = new Uint8Array(size); for (const [offset, bytes] of fields) out.set(bytes, offset); return out; };
const addr = (b) => knos.unb58(b);
const b64 = (u8) => Buffer.from(u8).toString("base64");
const ascii = (s) => new TextEncoder().encode(s);
const balanceBytes = ({ ownerId, authority, mint, cap = 0, spenders = [], spent = 0, faucet = false }) => at(160, [0, [1, 0, faucet ? 1 : 0]], [8, u64(ownerId)],
  [16, addr(authority)], [48, addr(mint)], [80, u64(cap)], [96, Uint8Array.from([0, 1, 2, 3].flatMap((i) => [...u64(spenders[i] || 0)]))], [128, u64(spent)]);
const jobBytes = ({ state = 1, fromBalance = true, faucet = false, token22 = false, mode = 0, repoId, issue, amount, deadline, holdUntil = 0, payeeId = 0, funderId = 0,
  ownerId = 0, source, mint, terms = "ab".repeat(32) }) => at(320, [0, [state, mode, fromBalance ? 1 : 0]], [6, [token22 ? 1 : 0, faucet ? 1 : 0]], [8, u64(repoId)], [16, u64(issue)],
  [24, u64(amount)], [32, i64(deadline)], [48, i64(holdUntil)], [56, u64(payeeId)], [64, u64(funderId)], [80, u64(ownerId)], [88, addr(source)], [120, addr(source)],
  [152, addr(source)], [184, addr(mint)], [216, knos.unhex(terms)], [280, ascii("c".repeat(40))]);
const bindBytes = ({ userId, wallet, iat }) => at(56, [0, [1]], [8, u64(userId)], [16, addr(wallet)], [48, i64(iat)]);
const dueBytes = ({ amount, userId, mint }) => at(48, [0, u64(amount)], [8, u64(userId)], [16, addr(mint)]);
const repBytes = ({ paid = 0, funders = 0, total = 0, testPaid = 0, selfPaid = 0, testTotal = 0, first = 0, last = 0 }) => at(64, [0, u32(paid)], [4, u32(funders)], [8, u64(total)],
  [16, u32(testPaid)], [20, u32(selfPaid)], [32, u64(testTotal)], [40, i64(first)], [48, i64(last)]);
const keyBytes = ({ issuer = 0, limbs = 64, state = 1, flags = 5, activeAt, expiresAt, seed = 1 }) => at(40 + 8 * limbs, [0, [state, issuer, limbs]], [8, i64(activeAt)],
  [16, i64(expiresAt)], [24, [flags]], [40, Uint8Array.from({ length: 4 * limbs }, (_, i) => (i * 7 + seed) % 251 + 1)]);
const mintBytes = (decimals) => at(82, [36, u64(0)], [44, [decimals]], [45, [1]]);
const tokenBytes = ({ mint, owner, amount }) => at(165, [0, addr(mint)], [32, addr(owner)], [64, u64(amount)], [108, [1]]);
const MULTISIG = Uint8Array.from([224, 116, 121, 186, 68, 161, 79, 236]);
const multisigBytes = ({ threshold, timeLock, members }) => at(100 + 33 * members.length, [0, MULTISIG], [72, Uint8Array.of(threshold & 255, threshold >> 8)], [74, u32(timeLock)],
  [96, u32(members.length)], ...members.map((m, i) => [100 + 33 * i, addr(m)]));
const programDataBytes = (authority) => at(45, [0, [3]], [12, authority ? [1] : [0]], ...(authority ? [[13, addr(authority)]] : []));
const when = (t) => `${new Date(t * 1000).toISOString().slice(0, 16).replace("T", " ")} UTC`;
const unique = (n) => knos.b58(Uint8Array.from({ length: 32 }, (_, i) => (n * 31 + i * 5) % 256));

// ---- the world the page sees ----------------------------------------------------------------------------------------------
const ids = JSON.parse(readFileSync(join(root, "program_ids.json"), "utf8"));
const k = knos.v2.client(ids);
const FIRST = { oidc: "vpWym9azbPU5f2PH2a6n8c4RfmsyUeW2dMuWr1DSHcE", pay: "9UzPFbh2A4e4sEPgngKG523FfYLnQ3qPfFVfFTTAdfDi" };   // the first deployment, as history
// the only link of the page to a GitHub page outside drexthealpha's: "Use this template", with nothing of the reader's in it
const TEMPLATE_LINK = "https://github.com/new?template_owner=drexthealpha&template_name=knos-claim&name=knos-claim&visibility=public&owner=@me";
const WALLET = unique(1), OTHER_WALLET = unique(2), USDC = knos.USDC_DEVNET, MINT22 = unique(3), BLOCKHASH = unique(4), BLOCKHASH2 = unique(5), NOW = 1790000000;
const users = { mona: { id: 4242, type: "User" }, octocat: { id: 583231, type: "User" }, "octo-org": { id: 7000001, type: "Organization" }, carol: { id: 99, type: "User" },
  quiet: { id: 5, type: "User" }, xss: { id: 666, type: "User", login: "<img src=x onerror=alert(1)>" } };
const repos = { "octo/widgets": 5550001, "octo/other": 5550002 };
const index = { date: "2026-10-02", n_prs: 5, agents: {}, prs: [
  { agent: "copilot", repo: "octo/widgets", number: 1, sha: "a".repeat(40), class: "passed", failed_checks: [], phrase: "all tests pass" },
  { agent: "copilot", repo: "octo/widgets", number: 2, sha: "b".repeat(40), class: "failed", failed_checks: ["build (3.12)"], phrase: "tests pass" },
  { agent: "devin", repo: "octo/widgets", number: 4, sha: "f".repeat(40), class: "other", failed_checks: [], phrase: "CI is green" },
  { agent: "codex", repo: "octo/widgets", number: 3, sha: "c".repeat(40), class: "failed", failed_checks: ["lint"], phrase: "<img src=x onerror=alert(1)> green" },
  { agent: "devin", repo: "acme/gadgets", number: 9, sha: "d".repeat(40), class: "other", failed_checks: [], phrase: "CI is green" }] };

// what the server hands out besides the site: the numbers and the index; and a way to change front.js for one page
const served = { stats: recorded("stats_with_data"), index, front: (text) => text };
const types = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json", ".svg": "image/svg+xml", ".yml": "text/plain" };
const server = createServer((req, res) => {
  const path = req.url.split("?")[0];
  const json = (o) => { res.writeHead(200, { "Content-Type": "application/json" }); res.end(JSON.stringify(o)); };
  if (path === "/stats.json") return served.stats === null ? (res.writeHead(404), res.end()) : json(served.stats);
  if (path === "/index.json") return json(served.index);
  const file = join(root, path === "/" ? "index.html" : path);
  if (!existsSync(file)) { res.writeHead(404); return res.end(); }
  const body = path === "/front.js" ? served.front(readFileSync(file, "utf8")) : readFileSync(file);
  res.writeHead(200, { "Content-Type": types[extname(file)] || "text/plain" }); res.end(body);
}).listen(0);
const base = `http://127.0.0.1:${server.address().port}/`;

// devnet: accounts by address, and a log of every call, the wallet's included
const chain = { accounts: new Map(), lamports: new Map(), calls: [], sent: [], statuses: new Map(), genesis: DEVNET, blockhash: BLOCKHASH, simulate: null, failAfter: null, neverSeen: false, down: null, seq: 0 };
const put = (address, data, owner) => chain.accounts.set(address, { data, owner });
const reset = async () => {
  Object.assign(chain, { calls: [], sent: [], genesis: DEVNET, blockhash: BLOCKHASH, simulate: null, failAfter: null, neverSeen: false, down: null });
  chain.accounts.clear(); chain.lamports.clear(); chain.statuses.clear();
  put(USDC, mintBytes(6), knos.TOKEN);
  put(await knos.ata(WALLET, USDC), tokenBytes({ mint: USDC, owner: WALLET, amount: 100_000_000 }), knos.TOKEN);
  chain.lamports.set(WALLET, 1_500_000_000);
};
const called = (method) => chain.calls.filter((c) => c.method === method);

// a transaction the wallet was handed: its instructions { program, accounts, data }
function readTx(tx) {
  let o = 0;
  const vec = () => { let n = 0, shift = 0; for (;;) { const b = tx[o++]; n |= (b & 127) << shift; if (!(b & 128)) return n; shift += 7; } };
  o = 1 + 64 * tx[0] + 3;
  const keys = Array.from({ length: vec() }, () => { const key = knos.b58(tx.slice(o, o + 32)); o += 32; return key; });
  o += 32;
  return Array.from({ length: vec() }, () => {
    const program = keys[tx[o++]], accounts = Array.from({ length: vec() }, () => keys[tx[o++]]), n = vec(), data = tx.slice(o, o + n);
    o += n;
    return { program, accounts, data };
  });
}

// What the chain does with the transactions this page sends: a Balance opened, money moved, the list changed.
function apply(tx) {
  const dv = (u8) => new DataView(u8.buffer, u8.byteOffset, u8.length);
  const token = (address) => { const a = chain.accounts.get(address); return a && { a, amount: Number(dv(a.data).getBigUint64(64, true)) }; };
  const setAmount = (address, v) => { new DataView(chain.accounts.get(address).data.buffer).setBigUint64(64, BigInt(v), true); };
  for (const ix of readTx(tx)) {
    const d = ix.data;
    if (ix.program === ids.knos_pay && d[0] === 0) {          // OpenBalance(owner id, cap, four spenders)
      const [authority, balance, baltok, mint] = ix.accounts, r = dv(d), owner = Number(r.getBigUint64(1, true));
      put(balance, balanceBytes({ ownerId: owner, authority, mint, cap: Number(r.getBigUint64(9, true)),
        spenders: [0, 1, 2, 3].map((i) => Number(r.getBigUint64(17 + 8 * i, true))).filter(Boolean) }), ids.knos_pay);
      put(baltok, tokenBytes({ mint, owner: balance, amount: 0 }), ix.accounts[5]);
    } else if (ix.program === ids.knos_pay && d[0] === 1) {   // SetBalance(cap, four spenders)
      const raw = chain.accounts.get(ix.accounts[1]).data;
      raw.set(d.slice(1, 9), 80); raw.set(d.slice(9, 41), 96);
    } else if (ix.program === ids.knos_pay && d[0] === 2) {   // Withdraw(amount): 0 is everything
      const [, , baltok, dest] = ix.accounts, have = token(baltok).amount, take = Number(dv(d).getBigUint64(1, true)) || have;
      setAmount(baltok, have - take); setAmount(dest, token(dest).amount + take);
    } else if (ix.program === knos.ATA_PROGRAM) {             // CreateIdempotent
      const [, account, owner, mint] = ix.accounts;
      if (!chain.accounts.has(account)) put(account, tokenBytes({ mint, owner, amount: 0 }), ix.accounts[5]);
    } else if ((ix.program === knos.TOKEN || ix.program === knos.TOKEN_2022) && d[0] === 12) {    // TransferChecked
      const [source, , dest] = ix.accounts, amount = Number(dv(d).getBigUint64(1, true));
      setAmount(source, token(source).amount - amount); setAmount(dest, token(dest).amount + amount);
    }
  }
}

// ---- the page's three outside worlds -----------------------------------------------------------------------------------------
const browser = await chromium.launch();
const errors = [], strangers = [];
const cors = { "access-control-allow-origin": "*", "access-control-expose-headers": "x-ratelimit-remaining, x-ratelimit-reset" };
let githubReads = 0;

async function mock(ctx) {
  await ctx.route("**/*", (route) => {          // registered first, so asked last: nothing but this page, GitHub and devnet
    const u = new URL(route.request().url());
    if (u.origin === new URL(base).origin) return route.continue();
    strangers.push(u.href); return route.abort();
  });
  await ctx.route("https://api.github.com/**", (route) => {
    githubReads++;
    const u = new URL(route.request().url()), p = u.pathname;
    const json = (o, status = 200, headers = {}) => route.fulfill({ status, contentType: "application/json", headers: { ...cors, ...headers }, body: JSON.stringify(o) });
    const user = (login) => Object.entries(users).find(([name]) => name.toLowerCase() === login.toLowerCase());
    if (p.startsWith("/users/")) { const got = user(decodeURIComponent(p.slice(7))); return got ? json({ id: got[1].id, login: got[1].login ?? got[0], type: got[1].type }) : json({ message: "Not Found" }, 404); }
    if (p.startsWith("/user/")) { const got = Object.entries(users).find(([, v]) => v.id === Number(p.slice(6))); return got ? json({ id: got[1].id, login: got[1].login ?? got[0] }) : json({ message: "Not Found" }, 404); }
    if (repos[p.slice(7)]) return json({ id: repos[p.slice(7)], default_branch: "main", full_name: p.slice(7) });
    if (p === "/repos/octo/widgets/pulls/12") return json({ number: 12, body: "Fixes #7", html_url: "https://github.com/octo/widgets/pull/12", user: { login: "mona" },
      head: { sha: "e".repeat(40) }, base: { repo: { full_name: "octo/widgets", name: "widgets", owner: { login: "octo" }, default_branch: "develop" } } });
    if (p.endsWith("/check-runs")) return json({ check_runs: [] });
    if (p.endsWith("/status")) return json({ sha: "e".repeat(40), statuses: [] });
    if (p === "/repos/limited/repo") return json({ message: "rate limit" }, 403, { "x-ratelimit-remaining": "0" });
    return json({ message: "Not Found" }, 404);
  });
  await ctx.route("https://api.devnet.solana.com/**", async (route) => {
    const { method, params } = JSON.parse(route.request().postData());
    chain.calls.push({ method, params });
    const reply = (result) => route.fulfill({ status: 200, contentType: "application/json", headers: cors, body: JSON.stringify({ jsonrpc: "2.0", id: 1, result }) });
    const ctxd = (value) => reply({ context: { slot: 100 }, value });
    const info = (a) => (a ? { data: [b64(a.data), "base64"], owner: a.owner, lamports: 2_000_000 } : null);
    if (chain.down) return route.fulfill({ status: 200, contentType: "application/json", headers: cors, body: JSON.stringify({ jsonrpc: "2.0", id: 1, error: { code: -32005, message: chain.down } }) });
    if (method === "getGenesisHash") return reply(chain.genesis);
    if (method === "getSlot") return reply(100);
    if (method === "getBlockTime") return reply(NOW);
    if (method === "getBalance") return ctxd(chain.lamports.get(params[0]) ?? 0);
    if (method === "getAccountInfo") return ctxd(info(chain.accounts.get(params[0])));
    if (method === "getLatestBlockhash") return ctxd({ blockhash: chain.blockhash, lastValidBlockHeight: 200 });
    if (method === "simulateTransaction") return ctxd({ err: chain.simulate?.err ?? null, logs: chain.simulate?.logs ?? [] });
    if (method === "getSignatureStatuses") return ctxd(params[0].map((s) => chain.statuses.get(s) ?? null));
    if (method === "getProgramAccounts") {
      const filters = params[1].filters, size = filters[0].dataSize, memcmp = filters[1]?.memcmp, want = memcmp && fromB58(memcmp.bytes);
      return reply([...chain.accounts].filter(([, a]) => a.owner === params[0] && a.data.length === size
        && (!memcmp || want.every((b, i) => a.data[memcmp.offset + i] === b))).map(([pubkey, a]) => ({ pubkey, account: info(a) })));
    }
    return route.fulfill({ status: 200, contentType: "application/json", headers: cors, body: JSON.stringify({ jsonrpc: "2.0", id: 1, error: { code: -32601, message: `no ${method}` } }) });
  });
}

// the wallet: registered the way the Wallet Standard says; what it is handed goes to the mocked chain, which signs for it
const walletScript = (list) => `(() => {
  window.__wallets = {};
  for (const [name, address] of ${JSON.stringify(list)}) {
    const w = window.__wallets[name] = { sent: [], connects: 0, reject: false };
    const account = w.account = { address, publicKey: new Uint8Array(32), chains: ["solana:mainnet", "solana:devnet"], features: [] };
    const wallet = { version: "1.0.0", name, icon: "data:image/svg+xml;base64,PHN2Zy8+", chains: ["solana:mainnet", "solana:devnet"], accounts: [],
      features: { "standard:connect": { version: "1.0.0", connect: async () => { w.connects++; return { accounts: [account] }; } },
        "solana:signAndSendTransaction": { version: "1.0.0", supportedTransactionVersions: ["legacy"], signAndSendTransaction: async (input) => {
          const tx = btoa(String.fromCharCode(...input.transaction));
          w.sent.push({ chain: input.chain, account: input.account.address, tx });
          if (w.reject) throw new Error("User rejected the request.");
          return [{ signature: Uint8Array.from(await window.walletSigns(tx)) }];
        } } } };
    const register = (api) => api.register(wallet);
    window.addEventListener("wallet-standard:app-ready", (ev) => register(ev.detail));
    window.dispatchEvent(new CustomEvent("wallet-standard:register-wallet", { detail: register }));
  }
  window.__wallet = window.__wallets[${JSON.stringify(list[0]?.[0] ?? "")}];
})();`;

const contexts = [];
async function world({ wallets = [], width = 1100 } = {}) {
  const ctx = await browser.newContext({ viewport: { width, height: 900 } });
  contexts.push(ctx);
  await mock(ctx);
  if (wallets.length) {
    await ctx.exposeFunction("walletSigns", (tx) => {          // the chain takes the transaction and answers with its signature
      const bytes = Uint8Array.from(Buffer.from(tx, "base64"));
      chain.calls.push({ method: "wallet:signAndSend" });
      apply(bytes);
      const signature = knos.b58(Uint8Array.from({ length: 64 }, (_, i) => (++chain.seq * 17 + i * 3) % 256 || 1));
      chain.sent.push({ tx, signature });
      if (!chain.neverSeen) chain.statuses.set(signature, { confirmationStatus: "confirmed", err: chain.failAfter ?? null });
      return [...fromB58(signature)];
    });
    await ctx.addInitScript(walletScript(wallets));
  }
  ctx.on("page", (p) => {
    p.on("console", (m) => { if (m.type() === "error" && !(/Failed to load resource/.test(m.text()) && /api\.github\.com|api\.devnet\.solana\.com|\/stats\.json$/.test(m.location().url))) errors.push(m.text()); });
    p.on("pageerror", (e) => errors.push(String(e)));
  });
  return ctx;
}
let visits = 0;
const visit = async (page, hash = "") => { await page.goto(`${base}?n=${++visits}${hash}`); };
// The commit the two workflow files name is read from the files themselves. A test that wants a commit there stamps it into a
// copy of front.js, so it holds for whatever the examples say, before a release and after.
const refs = /(\/\.github\/workflows\/[\w.-]+@)(\$\{\w+\}|[^\s`]+)/g;
const stamp = (to) => (code) => code.replace(refs, (_, head) => head + to);
const COMMIT = "a".repeat(40);
const text = async (page, sel) => (await page.textContent(sel)).replace(/\s+/g, " ");
const gone = async (page, sel) => (await page.$(sel)) === null;

// ======================================================================================================================
const plain = await world();        // a browser with no wallet in it: everything but "Add money" still works
await reset();

// ---- the front door ----------------------------------------------------------------------------------------------------------
{
  served.front = stamp(COMMIT);                  // so the Protect view hands out its links whatever commit the examples name
  const page = await plain.newPage();
  await visit(page);
  const SHORT = "Bounties that pay when the pull request is merged with the checks you named passing. Attested by a GitHub-signed workflow run, verified on Solana.";
  const LONG = "A pinned workflow reads the merge and the check results from GitHub. GitHub signs that workflow run. A Solana program verifies the signature itself and pays the author in the same minute. Nobody holds the money in between, and nobody decides after the fact.";
  check("front door renders: the short line, then the long one", (await text(page, "h1")) === SHORT && (await text(page, "#view-check .lede")) === LONG);
  check("  the title and description say the short line too", (await page.title()).includes(SHORT) && (await page.getAttribute('meta[name="description"]', "content")).startsWith(SHORT));
  check("only the front view is shown", await page.isVisible("#view-check") && await page.isHidden("#view-protect") && await page.isHidden("#view-network"));
  check("the six views are in the menu", (await page.$$eval("nav a", (a) => a.map((x) => x.getAttribute("href")))).join() === "#check,#protect,#fund,#claim,#network,#build");
  for (const [hash, view] of [["protect", "protect"], ["fund", "fund"], ["claim", "claim"], ["network", "network"], ["build", "build"], ["bounty", "fund"], ["money", "fund"], ["numbers", "network"], ["nothing", "check"]]) {
    await visit(page, `#${hash}`);
    const shown = await page.$$eval(".view", (v) => v.filter((x) => !x.hidden).map((x) => x.id));
    check(`#${hash} shows the ${view} view alone`, shown.join() === `view-${view}` && (await page.getAttribute("nav a[aria-current=page]", "href")) === `#${view}`, shown);
  }

  // a repository's own record in the Agent PR Index: the same box, no request but index.json
  await visit(page);
  for (const ask of ["octo/widgets", "OCTO/Widgets", "https://github.com/octo/widgets/", "github.com/octo/widgets.git", "https://github.com/octo/widgets/pulls?q=x"]) {
    githubReads = 0;
    await page.fill("#pr-url", ask);
    await page.click("#pr-check");
    await page.waitForSelector("#repo-record");
    const rec = await text(page, "#repo-record");
    check(`repository record for ${ask}`, rec.includes("4 agent pull requests") && rec.includes("tests pass, 2 had a failing check") && rec.includes("octo/widgets"));
    check(`  ${ask}: no GitHub request, only index.json`, githubReads === 0);
  }
  const rec = await text(page, "#repo-record");
  check("record: per agent", rec.includes("copilot") && rec.includes("1 of 2") && rec.includes("codex") && rec.includes("1 of 1"));
  check("record: each pull request links to GitHub", (await page.getAttribute('#repo-record a[href$="/pull/2"]', "href")) === "https://github.com/octo/widgets/pull/2" && rec.includes("build (3.12)"));
  check("record: index text is escaped, not run", (await page.$("#repo-record img")) === null && rec.includes("<img src=x"));
  await page.fill("#pr-url", "octo/unknown");
  await page.click("#pr-check");
  await page.waitForSelector("#repo-record");
  const none = await text(page, "#repo-record");
  check("record: none says so and offers the single-PR check", none.includes("No agent pull requests") && none.includes("octo/unknown") && none.includes("pull request link"));
  githubReads = 0;
  await page.fill("#pr-url", "https://github.com/octo/widgets/pull/12");
  await page.click("#pr-check");
  await page.waitForSelector("#verdict");
  check("a pull request link is still the single-PR check", githubReads > 0 && (await text(page, "#verdict")).includes("No tests-pass claim") && (await page.$("#repo-record")) === null);
  check("the result offers to protect that repository, at its default branch", (await page.getAttribute("#check-protect", "href")) === "#protect=octo%2Fwidgets%40develop");
  check("the result says the fee and that it applies only when someone is paid", (await text(page, "#pr-result")).includes("Fee: 2.5%, only when someone is paid"));
  await page.click("#check-protect");
  await page.waitForSelector("#protect-open");
  check("  and the link opens the Protect view with that repository and branch", await page.isVisible("#view-protect") && (await page.inputValue("#protect-repo")) === "octo/widgets"
    && (await page.inputValue("#protect-branch")) === "develop" && (await page.textContent("#protect-result")).includes("octo/widgets"));
  await visit(page);
  await page.fill("#pr-url", "not a thing");
  await page.click("#pr-check");
  await page.waitForSelector("#pr-result .status.bad");
  check("anything else is refused in a sentence", (await text(page, "#pr-result")).includes("owner/repo"));
  await page.fill("#pr-url", "limited/repo#1");
  await page.close();

  const again = await plain.newPage();
  served.index = { ...index, prs: "not a list" };                 // an index that is not the shape it should be: a sentence, no error
  await visit(again);
  await again.fill("#pr-url", "octo/widgets");
  await again.click("#pr-check");
  await again.waitForSelector("#repo-record");
  check("record: an index without a list of pull requests says none", (await text(again, "#repo-record")).includes("No agent pull requests"));
  served.index = index;
  await again.close();
  served.front = (code) => code;
}

// ---- protect a repository: the files, and the gate on the commit they name ---------------------------------------------------
{
  const page = await plain.newPage();
  const files = () => page.evaluate(async () => {
    const m = await import("/front.js");
    return { WORKFLOW: m.WORKFLOW, CHECK_WORKFLOW: m.CHECK_WORKFLOW, pinned: m.pinned(m.WORKFLOW) && m.pinned(m.CHECK_WORKFLOW),
      pins: [...m.pinsOf(m.WORKFLOW), ...m.pinsOf(m.CHECK_WORKFLOW)] };
  });
  const prefilled = (href) => { const u = new URL(href); return { origin: u.origin, path: u.pathname, file: u.searchParams.get("filename"), value: u.searchParams.get("value") }; };
  const pinsIn = (value) => [...value.matchAll(/^[ \t]*uses:[ \t]*\S+@(\S+)[ \t]*$/gm)].map((m) => m[1]);
  const go = async (repo, branch = "") => { await page.fill("#protect-repo", repo); await page.fill("#protect-branch", branch); await page.click("#protect-go"); };

  served.front = stamp(COMMIT);
  await visit(page, "#protect");
  const f = await files();
  check("protect: every workflow the two files call is named by a full commit", f.pins.length >= 2 && f.pins.every((p) => p.ref === COMMIT) && f.pinned, f.pins);
  await go("octo/widgets", "main");
  const one = prefilled(await page.getAttribute("#protect-open", "href")), two = prefilled(await page.getAttribute("#protect-check", "href"));
  check("protect: knos.yml, prefilled on the branch, is the file the page holds", one.origin === "https://github.com" && one.path === "/octo/widgets/new/main"
    && one.file === ".github/workflows/knos.yml" && one.value === f.WORKFLOW);
  check("protect: knos-check.yml is the second, optional file", two.path === "/octo/widgets/new/main" && two.file === ".github/workflows/knos-check.yml" && two.value === f.CHECK_WORKFLOW);
  check("protect: every workflow a handed-out file calls is named by a full commit", [one.value, two.value].every((v) => pinsIn(v).length > 0 && pinsIn(v).every((r) => /^[0-9a-f]{40}$/.test(r))));
  check("protect: a link to a new ruleset, for the check to be required", (await page.getAttribute("#protect-rules", "href")) === "https://github.com/octo/widgets/settings/rules/new?target=branch&enforcement=active");
  check("protect: the files can be copied instead, exactly as they are handed out", (await page.$$eval("#protect-copy pre", (p) => p.map((x) => x.textContent))).join("\n--\n") === [f.WORKFLOW, f.CHECK_WORKFLOW].join("\n--\n")
    && (await text(page, "#protect-copy summary")) === "Copy the files instead");
  const facts = await text(page, "#workflow-facts");
  check("protect: the page says what the files call, read from the files", [...new Set(f.pins.map((p) => p.file))].every((file) => facts.includes(file)) && facts.includes(COMMIT.slice(0, 7)) && !facts.includes("placeholder"), facts);
  check("protect: knos.yml's commit link goes to that commit of the repository it names", (await page.$$eval("#workflow-facts a", (a) => a.map((x) => x.getAttribute("href")))).every((h) => /^https:\/\/github\.com\/[\w.-]+\/[\w.-]+\/commit\/a{40}$/.test(h)));
  await go("https://github.com/octo/widgets.git", "develop");
  check("protect: a github.com address and another branch", prefilled(await page.getAttribute("#protect-open", "href")).path === "/octo/widgets/new/develop");
  await go("octo/widgets", "");
  check("protect: no branch means main", prefilled(await page.getAttribute("#protect-open", "href")).path === "/octo/widgets/new/main");
  for (const bad of ["octo", "a/b/c", "octo/wid gets", "<b>/x", ""]) {
    await go(bad);
    check(`protect: ${JSON.stringify(bad)} is refused in a sentence`, (await text(page, "#protect-result")).includes("Enter the repository as owner/repo.") && await gone(page, "#protect-open"));
  }
  await visit(page, "#protect=octo%2Fwidgets%40develop");
  await page.waitForSelector("#protect-open");
  check("protect: a link made by the check opens it filled in", (await page.inputValue("#protect-repo")) === "octo/widgets" && prefilled(await page.getAttribute("#protect-open", "href")).path === "/octo/widgets/new/develop");

  // a placeholder, a branch or a tag where a commit should be: the page hands out nothing, and says so
  const placeholder = stamp("KNOS_WORKFLOWS_SHA");
  let n = 0;
  for (const [what, front] of [["a placeholder that no release has replaced", placeholder], ["one branch name among full commits", (code) => code.replace(refs, (_, head) => head + (n++ === 0 ? "main" : COMMIT))],
    ["a tag", stamp("v1.0.0")], ["a short commit", stamp("a".repeat(39))]]) {
    served.front = front; n = 0;
    await visit(page, "#protect");
    const g = await files();
    await go("octo/widgets", "main");
    check(`protect: ${what}: nothing is handed out`, !g.pinned && await gone(page, "#protect-open") && await gone(page, "#protect-check") && await gone(page, "#protect-rules"));
    check(`  ${what}: the page says why and shows the files to read`, (await text(page, "#protect-result")).includes("no published workflow commit")
      && (await text(page, "#protect-copy summary")) === "Read the files" && (await page.$$eval("#protect-copy pre", (p) => p.length)) === 2);
  }
  served.front = placeholder;
  await visit(page, "#protect");
  check("protect: a placeholder is said on the page, as a placeholder", (await text(page, "#workflow-facts")).includes("placeholder"));

  // the page as built: whatever it hands out, it hands out only when its own gate holds
  served.front = (code) => code;
  await visit(page, "#protect");
  const built = await files();
  await go("octo/widgets", "main");
  check("protect: as built, links are offered exactly when every called workflow is named by a full commit", (await page.$("#protect-open") !== null) === built.pinned && built.pinned === built.pins.every((p) => /^[0-9a-f]{40}$/.test(p.ref)), built.pins);
  await page.close();
}

// ---- fund a task ---------------------------------------------------------------------------------------------------------------
{
  const page = await plain.newPage();
  await visit(page, "#fund");
  check("fund: the comment to write", (await text(page, "#fund-comment")).trim() === "/knos fund 20 checks: test");
  await page.waitForFunction(() => document.getElementById("fund-latency").textContent.includes("median"));
  check("fund: how long a comment took is the measured time, from stats.json", (await text(page, "#fund-latency")).replace(/\s+/g, " ").includes("the median is 4 min and the slowest 5 min, over 3 funded tasks"), await text(page, "#fund-latency"));
  for (const [what, stats] of [["nothing measured", recorded("stats_empty")], ["no stats.json", null]]) {
    served.stats = stats;
    await visit(page, "#fund");
    await page.waitForLoadState("networkidle");
    check(`fund: with ${what} the page promises no time`, (await text(page, "#fund-latency")).includes("see Numbers") && !(await text(page, "#view-fund")).includes("median"));
  }
  served.stats = recorded("stats_with_data");
  await page.close();
}

// ---- add money: a Balance, opened and filled from a wallet ---------------------------------------------------------------------
const wal = await world({ wallets: [["Test Wallet", WALLET]] });
const BAL = await k.balance(7000001, WALLET, USDC), BALTOK = await k.baltok(BAL), MINE = await knos.ata(WALLET, USDC);
{
  const page = await plain.newPage();
  await visit(page, "#fund");
  await page.click("#wallet-connect");
  check("add money: with no wallet in the browser, it says to install one", (await text(page, "#wallet-status")).includes("No Solana wallet found"));
  await page.fill("#owner-login", "octo-org");
  await page.click("#owner-go");
  check("  and nothing is looked up before a wallet is connected", (await text(page, "#owner-result")).includes("Connect a wallet first."));
  check("  the rest of the page needs no wallet: the escrow lookup answers", await (async () => { await page.fill("#st-issue", "octo/widgets#7"); await page.click("#st-go"); await page.waitForSelector("#st-result p"); return true; })());
  await page.close();
}
{
  await reset();
  const page = await wal.newPage();
  const sentByWallet = () => page.evaluate(() => window.__wallet.sent.length);
  const clear = () => page.evaluate(() => { document.getElementById("money-status").innerHTML = ""; });
  // what the page asks the wallet to sign, built here from the same inputs by sdk/settle (checked against the Python client's bytes)
  const expect = (ixs, hash = BLOCKHASH) => b64(knos.serializeTx(ixs, WALLET, hash));
  const attempt = async (button, fields = {}) => {
    for (const [id, v] of Object.entries(fields)) await page.fill(`#${id}`, v);
    await clear();
    await page.click(`#${button}`);
    await page.waitForSelector("#money-status .status.bad, #money-steps");
  };
  const steps = () => page.$$eval("#money-steps > li", (l) => l.map((x) => x.firstChild.textContent.trim()));
  const problem = async () => (await text(page, "#money-status")).trim();
  const sign = async () => { await clear(); await page.click("#money-send"); await page.waitForSelector("#money-done, #money-status .status.bad"); };
  const facts = () => page.$$eval("#balance-facts dd", (d) => d.map((x) => x.textContent.trim()));
  const lookup = async (login, mint = null) => {
    if (mint) { await page.click("#owner-form summary"); await page.fill("#money-mint", mint); }
    await page.fill("#owner-login", login);
    await page.evaluate(() => { document.getElementById("balance-state").innerHTML = ""; document.getElementById("owner-result").innerHTML = ""; });
    await page.click("#owner-go");
    await page.waitForSelector("#money-form, #owner-result .status.bad");
  };
  await visit(page, "#fund");

  // a wallet that cannot sign for devnet, and a cluster that is not devnet, are refused before anything is built
  await page.evaluate(() => { window.__wallet.account.chains = ["solana:mainnet"]; });
  await page.click("#wallet-connect");
  await page.waitForSelector("#wallet-status .status.bad");
  check("add money: a wallet whose account is not on devnet is refused, with what to do", (await text(page, "#wallet-status")).includes("Test Wallet has no devnet account to share. Set it to devnet and connect again.") && await gone(page, "#wallet-address"));
  await page.evaluate(() => { window.__wallet.account.chains = ["solana:mainnet", "solana:devnet"]; });
  chain.genesis = MAINNET;
  await page.click("#wallet-connect");
  await page.waitForSelector("#wallet-status .status.bad");
  check("add money: an endpoint that is not devnet is refused when the wallet connects", (await text(page, "#wallet-status")).includes("not devnet, so nothing was sent") && await gone(page, "#wallet-address"));
  await lookup("octo-org");
  check("  and then nothing can be looked up", (await text(page, "#owner-result")).includes("Connect a wallet first.") && called("getLatestBlockhash").length === 0);
  chain.genesis = DEVNET;
  await page.click("#wallet-connect");
  await page.waitForSelector("#wallet-address");
  check("add money: connected, with the address the wallet shared, on devnet", (await text(page, "#wallet-address")) === WALLET && (await text(page, "#wallet-status")).includes("Solana devnet")
    && (await text(page, "#wallet-connect")) === "Switch wallet" && called("getGenesisHash").length >= 2);

  // the owner and the mint
  await lookup("nobody-at-all");
  check("add money: an owner GitHub does not know is said so", (await text(page, "#owner-result")).includes("GitHub has no such public repository, issue or user."));
  await lookup("not a login!");
  check("  a login with odd characters is refused in a sentence", (await text(page, "#owner-result")).includes("Enter a GitHub login."));
  await lookup("octo-org");
  const first = await text(page, "#balance-state");
  check("add money: no Balance yet, for the GitHub owner with its id and kind", first.includes("No Balance yet for octo-org (GitHub id 7000001, organization)"), first);
  check("  the wallet's own test USDC and SOL are shown", first.includes("This wallet holds 100.00 test USDC and 1.500 SOL"));
  check("  the button says open; there is nothing to withdraw yet", (await text(page, "#money-add")) === "Open the Balance" && await gone(page, "#money-withdraw") && await gone(page, "#money-set"));

  // what is refused before a transaction is built
  const refusals = [[{ "money-amount": "abc" }, "Write how much to add as a number like 20 or 2.5, with at most 6 decimals."],
    [{ "money-amount": "1.1234567" }, "at most 6 decimals"], [{ "money-amount": "20", "money-cap": "x" }, "The cap is a number like 5 or 2.5, or blank for none."],
    [{ "money-cap": "", "money-spenders": "mona, octocat, carol, quiet, xss" }, "A Balance lists at most four people besides its owner."],
    [{ "money-spenders": "nobody-at-all" }, "GitHub has no such public repository, issue or user."],
    [{ "money-amount": "500", "money-spenders": "" }, "This wallet holds 100.00 test USDC, and 500.00 is to go in. Circle's devnet faucet gives test USDC."]];
  for (const [fields, words] of refusals) {
    await attempt("money-add", fields);
    check(`add money: refused in words: ${words.slice(0, 48)}`, (await problem()).includes(words), await problem());
  }
  check("  nothing was simulated, signed or sent for any of them", called("simulateTransaction").length === 0 && (await sentByWallet()) === 0 && chain.sent.length === 0);

  // an endpoint that stops being devnet after the wallet connected: neither a preview nor a lookup goes on
  chain.genesis = MAINNET;
  await attempt("money-add", { "money-amount": "20", "money-cap": "", "money-spenders": "" });
  check("add money: a preview refuses an endpoint that is not devnet: nothing is built or simulated", (await problem()).includes("not devnet, so nothing was sent")
    && called("simulateTransaction").length === 0 && called("getLatestBlockhash").length === 0);
  await lookup("octo-org");
  check("  and a lookup refuses it too", (await text(page, "#owner-result")).includes("not devnet, so nothing was sent") && await gone(page, "#money-form"));
  chain.genesis = DEVNET;
  await lookup("octo-org");

  // open the Balance and put money in, in one transaction
  await attempt("money-add", { "money-amount": "20", "money-cap": "5", "money-spenders": "mona, octocat" });
  const open = [await k.openBalanceIx({ authority: WALLET, ownerId: 7000001, mint: USDC, cap: 5_000_000, spenders: [4242, 583231] }), knos.transferCheckedIx(MINE, USDC, BALTOK, WALLET, 20_000_000, 6)];
  check("add money: the preview says what each instruction does", (await steps()).join(" | ") === "Open a Balance for GitHub owner 7000001: no task may take more than 5.00; GitHub ids 4242, 583231 may spend it by comment, besides the owner. | "
    + "Move 20.00 test USDC from your token account into the Balance's token account.", await steps());
  check("  and lists every account of each, with who signs and what changes", (await page.$$eval("#money-steps details", (d) => d.map((x) => x.textContent)))[0].includes(`authority: ${WALLET} (signs) (changes)`)
    && (await text(page, "#money-steps")).includes(`balance: ${BAL} (changes)`) && (await text(page, "#money-steps")).includes("knos-pay: OpenBalance"));
  const sim = called("simulateTransaction");
  check("  devnet simulated exactly that transaction, without signatures, before the wallet was asked", sim.length === 1 && sim[0].params[0] === expect(open)
    && JSON.stringify(sim[0].params[1]) === JSON.stringify({ encoding: "base64", sigVerify: false, replaceRecentBlockhash: true, commitment: "confirmed" }) && chain.sent.length === 0);
  await sign();
  check("add money: the wallet was handed exactly that transaction, for devnet, from its own address", chain.sent.length === 1 && chain.sent[0].tx === expect(open)
    && (await page.evaluate(() => window.__wallet.sent[0].chain)) === "solana:devnet" && (await page.evaluate(() => window.__wallet.sent[0].account)) === WALLET);
  check("  the simulation came first, the wallet second", chain.calls.map((c) => c.method).filter((m) => m === "simulateTransaction" || m === "wallet:signAndSend").join() === "simulateTransaction,wallet:signAndSend");
  check("  the page waits for devnet to confirm, then says done with a link to the transaction", (await text(page, "#money-done")).startsWith("Done.") && called("getSignatureStatuses").length >= 1
    && (await page.getAttribute("#money-done a", "href")) === `https://explorer.solana.com/tx/${chain.sent[0].signature}?cluster=devnet`);
  check("  the Balance is read back: what it holds, its cap, who may spend it, what it has spent", (await facts()).slice(0, 4).join(" | ") === "20.00 test USDC | at most 5.00 | the owner and mona, octocat | 0.00", await facts());
  check("  the Balance and its token account are linked on the explorer", (await page.$$eval("#balance-facts dd a", (a) => a.map((x) => x.getAttribute("href")))).join()
    === `https://explorer.solana.com/address/${BAL}?cluster=devnet,https://explorer.solana.com/address/${BALTOK}?cluster=devnet`);
  check("  the wallet line shows what is left", (await text(page, "#balance-state")).includes("This wallet holds 80.00 test USDC"));

  // add more
  await attempt("money-add", { "money-amount": "5" });
  check("add money: adding is one token transfer", (await steps()).join() === "Move 5.00 test USDC from your token account into the Balance's token account.");
  await sign();
  check("  that exact transfer was sent, and the Balance holds 25.00", chain.sent.at(-1).tx === expect([knos.transferCheckedIx(MINE, USDC, BALTOK, WALLET, 5_000_000, 6)]) && (await text(page, "#balance-amount")) === "25.00");
  await attempt("money-add", { "money-amount": "" });
  check("  an empty amount is not an addition", (await problem()).includes("Write how much to add"));

  // who may spend it, and the cap
  await attempt("money-set", { "money-cap": "10", "money-spenders": "mona" });
  check("add money: changing the list says what it changes", (await steps()).join() === "Change who may spend the Balance and its cap: no task may take more than 10.00; GitHub ids 4242, besides the owner.");
  await sign();
  check("  SetBalance with that cap and that list was sent; it reads back", chain.sent.at(-1).tx === expect([k.setBalanceIx({ authority: WALLET, balance: BAL, cap: 10_000_000, spenders: [4242] })])
    && (await facts()).slice(0, 3).join(" | ") === "25.00 test USDC | at most 10.00 | the owner and mona");
  await attempt("money-set", { "money-cap": "", "money-spenders": "" });
  await sign();
  check("  a blank cap is no cap, a blank list is the owner only", (await facts()).slice(0, 3).join(" | ") === "25.00 test USDC | any amount (no cap) | the owner only");

  // take money back
  await attempt("money-withdraw", { "money-out": "50" });
  check("add money: more than the Balance holds cannot be taken back", (await problem()).includes("The Balance holds 25.00, so that much cannot be taken back."));
  await attempt("money-withdraw", { "money-out": "7" });
  check("  an amount: the preview names it", (await steps()).join() === "Move 7.00 out of the Balance into your own token account.");
  await sign();
  check("  that Withdraw went to the wallet's own token account; 18.00 is left", chain.sent.at(-1).tx === expect([await k.withdrawIx({ authority: WALLET, balance: BAL, mint: USDC, amount: 7_000_000 })])
    && (await text(page, "#balance-amount")) === "18.00" && (await text(page, "#balance-state")).includes("This wallet holds 82.00 test USDC"));
  await attempt("money-withdraw", { "money-out": "" });
  check("  blank takes everything", (await steps()).join() === "Move everything out of the Balance into your own token account.");
  await sign();
  check("  Withdraw with amount 0 was sent; the Balance is empty; the wallet has its 100.00 back", chain.sent.at(-1).tx === expect([await k.withdrawIx({ authority: WALLET, balance: BAL, mint: USDC, amount: 0 })])
    && (await text(page, "#balance-amount")) === "0.00" && (await text(page, "#balance-state")).includes("This wallet holds 100.00 test USDC"));
  await attempt("money-withdraw");
  check("  with nothing left it says so", (await problem()).includes("The Balance holds nothing to take back."));

  // what can go wrong between the preview and the chain
  await attempt("money-add", { "money-amount": "1" });
  chain.simulate = { err: { InstructionError: [1, { Custom: 94 }] } };
  await attempt("money-add");
  check("add money: devnet's refusal in the program's words", (await problem()) === knos.v2.ERRORS[94] && await gone(page, "#money-steps"), await problem());
  for (const [err, logs, words] of [["AccountNotFound", [], "This wallet has no SOL on devnet"], ["InsufficientFundsForRent", [], "This wallet needs more devnet SOL"],
    [{ InstructionError: [0, "InvalidAccountData"] }, ["Program log: Error: bad account"], "Devnet would refuse it"]]) {
    chain.simulate = { err, logs };
    await attempt("money-add");
    check(`  and in plain words: ${words}`, (await problem()).includes(words) && (words !== "Devnet would refuse it" || (await problem()).includes("Program log: Error: bad account")), await problem());
  }
  chain.simulate = null;
  const before = chain.sent.length;
  await attempt("money-add");
  await page.evaluate(() => { window.__wallet.reject = true; });
  await sign();
  check("add money: a wallet that says no: its words, and the button works again", (await problem()) === "User rejected the request." && await page.isEnabled("#money-send") && chain.sent.length === before);
  await page.evaluate(() => { window.__wallet.reject = false; });
  const asked = await sentByWallet();
  chain.genesis = MAINNET;
  await sign();
  check("add money: an endpoint that stopped being devnet after the preview: the wallet is not even asked", (await problem()).includes("not devnet, so nothing was sent") && (await sentByWallet()) === asked && chain.sent.length === before);
  chain.genesis = DEVNET;
  chain.blockhash = BLOCKHASH2;
  await sign();
  check("  the blockhash is asked again when the wallet is, so a slow reader never signs an old one", chain.sent.at(-1).tx === expect([knos.transferCheckedIx(MINE, USDC, BALTOK, WALLET, 1_000_000, 6)], BLOCKHASH2) && (await text(page, "#money-done")).startsWith("Done."));
  chain.blockhash = BLOCKHASH;
  chain.failAfter = { InstructionError: [1, { Custom: 92 }] };
  await attempt("money-add", { "money-amount": "1" });
  await sign();
  check("  a transaction that devnet then fails is said in the program's words, not as done", (await problem()) === knos.v2.ERRORS[92] && await gone(page, "#money-done"), await problem());
  chain.failAfter = null;

  // a Balance whose people GitHub cannot name, and a token that is not test USDC
  const carol = await k.balance(99, WALLET, USDC);
  put(carol, balanceBytes({ ownerId: 99, authority: WALLET, mint: USDC, cap: 2_500_000, spenders: [4242, 99999], spent: 1_000_000 }), ids.knos_pay);
  put(await k.baltok(carol), tokenBytes({ mint: USDC, owner: carol, amount: 3_000_000 }), knos.TOKEN);
  await lookup("carol");
  check("add money: a Balance read from the chain: holds, cap, people, spent", (await facts()).slice(0, 4).join(" | ") === "3.00 test USDC | at most 2.50 | the owner and mona, GitHub id 99999 | 1.00", await facts());
  check("  a person GitHub cannot name is shown by id; saving would replace the whole list, and says so", (await text(page, "#money-form")).includes("Saving replaces the whole list.") && (await page.inputValue("#money-spenders")) === "");
  const more = [[MINT22, 9, knos.TOKEN_2022]];
  for (const [mint, decimals, program] of more) {
    put(mint, mintBytes(decimals), program);
    put(await knos.ata(WALLET, mint, program), tokenBytes({ mint, owner: WALLET, amount: 5_000_000_000 }), program);
  }
  await lookup("octo-org", MINT22);
  const bal22 = await k.balance(7000001, WALLET, MINT22), tok22 = await k.baltok(bal22), mine22 = await knos.ata(WALLET, MINT22, knos.TOKEN_2022);
  check("add money: another token: it is named as a test token, with its own decimals", (await text(page, "#balance-state")).includes("of the test token") && (await text(page, "#balance-state")).includes("This wallet holds 5.00"));
  await attempt("money-add", { "money-amount": "1.5", "money-cap": "", "money-spenders": "" });
  await sign();
  check("  Token-2022 is used for the Balance, the transfer and the decimals", chain.sent.at(-1).tx === expect([await k.openBalanceIx({ authority: WALLET, ownerId: 7000001, mint: MINT22, cap: 0, spenders: [], tokenProgram: knos.TOKEN_2022 }),
    knos.transferCheckedIx(mine22, MINT22, tok22, WALLET, 1_500_000_000, 9, knos.TOKEN_2022)]) && (await text(page, "#balance-amount")) === "1.50");
  put(unique(78), new Uint8Array(82), knos.SYSTEM);
  for (const [what, mint, words] of [["text that is not an address", "hello", "That is not a Solana address. Use the mint's address."], ["an account the token programs do not own", unique(78), "That address is not a token mint on devnet."],
    ["an address nothing is at", unique(77), "That address is not a token mint on devnet."]]) {
    await page.fill("#money-mint", mint);
    await lookup("octo-org");
    check(`  ${what} is refused`, (await text(page, "#owner-result")).includes(words), await text(page, "#owner-result"));
  }
  await page.close();
}
{
  // the money in a wallet with no token account yet: taking money back creates it first, in the same transaction
  await reset();
  put(BAL, balanceBytes({ ownerId: 7000001, authority: WALLET, mint: USDC, cap: 0, spenders: [] }), ids.knos_pay);
  put(BALTOK, tokenBytes({ mint: USDC, owner: BAL, amount: 9_000_000 }), knos.TOKEN);
  chain.accounts.delete(MINE);
  const page = await wal.newPage();
  await visit(page, "#fund");
  await page.click("#wallet-connect"); await page.waitForSelector("#wallet-address");
  await page.fill("#owner-login", "octo-org"); await page.click("#owner-go"); await page.waitForSelector("#money-form");
  check("add money: a wallet with no token account is told so", (await text(page, "#balance-state")).includes("no test USDC token account yet"));
  await page.fill("#money-amount", "1"); await page.click("#money-add");
  await page.waitForSelector("#money-status .status.bad");
  check("  putting money in says it holds none, and where to get some", (await text(page, "#money-status")).includes("This wallet holds 0.00 test USDC, and 1.00 is to go in. Circle's devnet faucet gives test USDC."));
  await page.click("#money-withdraw");
  await page.waitForSelector("#money-steps");
  check("  taking money back creates the token account first", (await page.$$eval("#money-steps > li", (l) => l.map((x) => x.firstChild.textContent.trim()))).join(" | ")
    === "Create your token account for this mint, unless you have one. You pay its small deposit. | Move everything out of the Balance into your own token account.");
  await page.click("#money-send");
  await page.waitForSelector("#money-done");
  check("  and sends both, in that order", chain.sent[0].tx === b64(knos.serializeTx([await knos.createAtaIx(WALLET, WALLET, USDC), await k.withdrawIx({ authority: WALLET, balance: BAL, mint: USDC, amount: 0 })], WALLET, BLOCKHASH))
    && (await text(page, "#balance-state")).includes("This wallet holds 9.00 test USDC"));
  await page.close();

  // a wallet that says it is on devnet and a network that never shows the transaction: the page says nothing happened, in a minute
  await reset();
  put(BAL, balanceBytes({ ownerId: 7000001, authority: WALLET, mint: USDC }), ids.knos_pay);
  put(BALTOK, tokenBytes({ mint: USDC, owner: BAL, amount: 0 }), knos.TOKEN);
  put(MINE, tokenBytes({ mint: USDC, owner: WALLET, amount: 100_000_000 }), knos.TOKEN);
  chain.neverSeen = true;
  const slow = await wal.newPage();
  await slow.clock.install();
  await visit(slow, "#fund");
  await slow.click("#wallet-connect"); await slow.waitForSelector("#wallet-address");
  await slow.fill("#owner-login", "octo-org"); await slow.click("#owner-go"); await slow.waitForSelector("#money-form");
  await slow.fill("#money-amount", "2"); await slow.click("#money-add"); await slow.waitForSelector("#money-send");
  await slow.click("#money-send");
  for (let i = 0; i < 120 && !(await slow.textContent("#money-status")).includes("did not show"); i++) { await slow.clock.fastForward(2000); await slow.waitForTimeout(20); }
  const said = await slow.textContent("#money-status");
  check("add money: a transaction devnet never shows is said not to have happened, with the reason it may be on another network",
    said.includes("Devnet did not show the transaction within a minute") && said.includes("other networks refuse a devnet transaction") && await gone(slow, "#money-done"), said);
  chain.neverSeen = false;
  await slow.close();
}
{
  // two wallets in the browser: the person picks
  await reset();
  const two = await world({ wallets: [["Test Wallet", WALLET], ["Other Wallet", OTHER_WALLET]] });
  const page = await two.newPage();
  await visit(page, "#fund");
  await page.click("#wallet-connect");
  await page.waitForSelector("[data-wallet]");
  check("add money: with two wallets it asks which", (await page.$$eval("[data-wallet]", (b) => b.map((x) => x.textContent))).join() === "Test Wallet,Other Wallet");
  await page.click('[data-wallet="1"]');
  await page.waitForSelector("#wallet-address");
  check("  and connects the one picked", (await text(page, "#wallet-address")) === OTHER_WALLET);
  await page.close();
}

// ---- what is in escrow for an issue, what is held for an account, binding a wallet ---------------------------------------------
{
  await reset();
  const page = await plain.newPage();
  const settled = (sel) => page.waitForFunction((s) => { const t = document.querySelector(s).textContent; return t.trim() && !t.includes("Reading GitHub and Solana"); }, sel);
  const ask = async (issue) => {
    await page.fill("#st-issue", issue);
    await page.evaluate(() => { document.getElementById("st-result").innerHTML = ""; });
    await page.click("#st-go");
    await settled("#st-result");
    return text(page, "#st-result");
  };
  const OWNER_BAL = await k.balance(424242, OTHER_WALLET, USDC), FAUCET_BAL = await k.faucetBalance(7000001), FAUCET_MINT = await k.faucetMint();
  const jobAt = async (issue, source, fields, repoId = 5550001) => {
    const address = await k.job(repoId, issue, source);
    put(address, jobBytes({ repoId, issue, source, mint: USDC, ...fields }), ids.knos_pay);
    return address;
  };
  const J7 = await jobAt(7, OWNER_BAL, { amount: 20_000_000, deadline: NOW + 14 * 86400, ownerId: 424242, funderId: 583231 });
  const J8 = await jobAt(8, WALLET, { state: 3, fromBalance: false, amount: 12_000_000, deadline: NOW - 100, holdUntil: NOW + 100 * 86400, payeeId: 4242 });
  await jobAt(9, FAUCET_BAL, { faucet: true, mint: FAUCET_MINT, ownerId: 7000001, funderId: 583231, amount: 3_000_000, deadline: NOW + 5 * 3600 });
  await jobAt(10, OWNER_BAL, { amount: 1_000_000, deadline: NOW - 100, ownerId: 424242, funderId: 583231 });
  await jobAt(11, WALLET, { state: 3, fromBalance: false, amount: 4_500_000, deadline: NOW - 100, holdUntil: NOW + 5 * 86400, payeeId: 99 });
  await jobAt(7, OWNER_BAL, { amount: 7_000_000, deadline: NOW + 86400, ownerId: 424242, funderId: 583231 }, 5550002);       // another repository's issue 7
  put(await k.bind(4242), bindBytes({ userId: 4242, wallet: OTHER_WALLET, iat: NOW - 86400 }), ids.knos_pay);
  put(await k.rep(4242), repBytes({ paid: 3, funders: 2, total: 58_500_000, testPaid: 1, selfPaid: 1, testTotal: 24_375_000, first: NOW - 30 * 86400, last: NOW - 86400 }), ids.knos_pay);
  const first = knos.client({ knos_oidc: FIRST.oidc, knos_pay: FIRST.pay });
  put(await first.due(4242, USDC), dueBytes({ amount: 4_875_000, userId: 4242, mint: USDC }), FIRST.pay);

  await visit(page, "#fund");
  let got = await ask("octo/widgets#7");
  check("escrow: the amount, the fee when paid and the state", got.includes("20.00 test USDC") && got.includes("fee when paid: 0.50")
    && got.includes("open: paid when a maintainer merges the pull request that closes the issue"), got);
  check("  who funded it: the Balance of the owner, and the person who commented", got.includes("the Balance of GitHub owner 424242, by GitHub user 583231"));
  check("  when it goes back if nobody is paid", got.includes("goes back to where it came from in 336 h"));
  check("  the terms' hash, and the account on the explorer", got.includes("ab".repeat(32)) && (await page.getAttribute("#st-result a", "href")) === `https://explorer.solana.com/address/${J7}?cluster=devnet`);
  check("  only this repository's issue 7, not another's", got.split("In escrow").length === 2 && !got.includes("7.00 test USDC"));
  got = await ask("https://github.com/octo/widgets/issues/7");
  check("escrow: the issue's web address is as good as owner/repo#7", got.includes("20.00 test USDC"));
  got = await ask("octo/widgets#8");
  check("escrow: a held job names the person it waits for and until when", got.includes("held for GitHub user mona until " + when(NOW + 100 * 86400)) && got.includes("it goes back to the funder")
    && got.includes(`wallet ${WALLET}`) && got.includes("12.00 test USDC"), got);
  got = await ask("octo/widgets#9");
  check("escrow: faucet money is said to be faucet money", got.includes("free faucet money") && got.includes("3.00 test USDC") && got.includes("in 5 h"), got);
  got = await ask("octo/widgets#10");
  check("escrow: an open job past its deadline can be sent back by anyone", got.includes("now (anyone may send it)"));
  await jobAt(13, OWNER_BAL, { mode: 1, amount: 5_000_000, deadline: NOW + 86400, ownerId: 424242, funderId: 583231 });
  got = await ask("octo/widgets#13");
  check("escrow: a job paid without a merge says so, and that its check is black-box", got.includes("open: paid without a merge, when its black-box check passes") && !got.includes("any test"), got);
  got = await ask("octo/widgets#12");
  check("escrow: nothing there says so, and who funds it, and how", got.includes("Nothing is in escrow for octo/widgets#12.") && got.includes("/knos fund 20"));
  check("  a sentence for something that is not an issue", (await ask("hello")).includes("Enter the issue as owner/repo#7."));
  check("  a sentence for a repository GitHub does not have", (await ask("octo/nothing#1")).includes("GitHub has no such public repository, issue or user."));
  check("  a sentence for GitHub's rate limit", (await ask("limited/repo#1")).includes("GitHub's free limit for this network is used up"));
  await visit(page, "#fund=" + encodeURIComponent("octo/widgets#7"));
  await settled("#st-result");
  check("escrow: a link to one issue reads it on arrival", (await page.inputValue("#st-issue")) === "octo/widgets#7" && (await text(page, "#st-result")).includes("20.00 test USDC"));

  // an account: the wallet it bound, what is held for it, its record on Solana
  const account = async (login) => {
    await page.fill("#due-login", login);
    await page.evaluate(() => { document.getElementById("due-result").innerHTML = ""; });
    await page.click("#due-go");
    await settled("#due-result");
    return text(page, "#due-result");
  };
  await visit(page, "#claim");
  got = await account("mona");
  check("account: the wallet it bound", (await text(page, "#due-bound")).startsWith(`Paid at ${OTHER_WALLET}`) && got.includes("Bound " + when(NOW - 86400) + ". Every task now pays this wallet."), got);
  check("  what is held for it, until when, and that it can be sent now", got.includes("12.00 test USDC is held for mona until " + when(NOW + 100 * 86400) + ".")
    && got.includes("A wallet is bound, so it can be sent there now: comment /knos settle on the merged pull request."));
  check("  first deployment: its separate held amount and v1 claim command", got.includes("4.88 test USDC is still held for mona on the first deployment.")
    && got.includes("knos claim --v1 <address>") && (await page.$("#due-v1")) !== null, got);
  const record = await page.$$eval("#due-record dd", (d) => d.map((x) => x.textContent.replace(/\s+/g, " ").trim()));
  check("  its record: payments, funders, total and the dates", record[0] === "3 payments from 2 different funders, 58.50 test USDC in all (" + when(NOW - 30 * 86400) + " to " + when(NOW - 86400) + ")", record);
  check("  faucet money and paying oneself counted apart, never added in", record[1] === "1 payment, 24.38 of the faucet's free test USDC. Counted apart."
    && record[2] === "1 payment, where the funder was the person paid. Counted apart." && got.includes("never added together"));
  check("  the GitHub account's id and that it is all test USDC", got.includes("GitHub account id 4242") && got.includes("All of it is test USDC on devnet"));
  got = await account("quiet");
  check("account: nothing bound, nothing held, nothing paid, said as such", got.includes("No wallet is bound for quiet.") && got.includes("Nothing is held for quiet right now.")
    && got.includes("0 payments from 0 different funders, 0.00 test USDC in all"), got);
  check("  no first-deployment section is added when that account has no due", (await page.$("#due-v1")) === null, got);
  got = await account("carol");
  check("account: held with no wallet bound says to bind one, before when, and where it goes after", got.includes("4.50 test USDC is held for carol until " + when(NOW + 5 * 86400))
    && got.includes("Bind a wallet before then and it can be sent there. After that date it goes back to the funder.") && got.includes("No wallet is bound for carol."), got);
  got = await account("xss");
  check("account: what GitHub says a login is, is text, never markup", (await page.$("#due-result img")) === null && got.includes("<img src=x onerror=alert(1)>"));
  check("  a login GitHub does not know", (await account("nobody-at-all")).includes("GitHub has no such public repository, issue or user."));
  check("  odd characters are refused", (await account("a b")).includes("Enter a GitHub login."));
  await visit(page, "#claim=mona");
  await settled("#due-result");
  check("account: a link to one account reads it on arrival", (await page.inputValue("#due-login")) === "mona" && (await text(page, "#due-result")).includes("Paid at " + OTHER_WALLET));

  // bind a wallet once, by hand: a plain template link with no address in it, then the Actions tab, or `knos claim`
  const steps = await text(page, "#bind-steps");
  const template = await page.getAttribute("#bind-template", "href");
  check("bind: the one link is GitHub's new-repository page, from the template, named knos-claim, public, in the account, with no address in it",
    template === TEMPLATE_LINK && !/description|address/i.test(template), template);
  check("  it opens in a new tab without handing over the page", (await page.getAttribute("#bind-template", "target")) === "_blank" && (await page.getAttribute("#bind-template", "rel")) === "noopener");
  check("  the second step is the Actions tab, 'knos claim', 'Run workflow', and pasting the address yourself",
    steps.includes("Actions") && steps.includes("knos claim") && steps.includes("Run workflow") && steps.includes("paste your Solana address into the box yourself"), steps);
  const claimText = await text(page, "#view-claim");
  check("  the terminal does both steps with `knos claim`, and the page says why an address is never put in a link",
    claimText.includes("knos claim YOUR_SOLANA_ADDRESS") && claimText.includes("an address carried in a link could be someone else's"), claimText);
  check("  nothing on the page prefills a repository: no form to enter an address, no link that carries one, no first-run binding",
    (await page.$("#bind-form")) === null && (await page.$("#bind-address")) === null
    && (await page.$$eval("#view-claim a", (a) => a.every((x) => !/description=|address=/.test(x.href)))) && !/as its description|first run asks|Prefill/.test(claimText), claimText);
  check("  the app has no function that makes such a link", await page.evaluate(async () => !("bindUrl" in await import("/app.js"))));

  // an amount, as the page reads it
  const read = (...args) => page.evaluate(async (a) => { const { units } = await import("/app.js"); return a.map(([t, d]) => units(t, d)); }, args);
  const got2 = await read(["20"], ["0.5"], ["1.234567"], ["1.2345678"], [" 7 "], ["0"], ["1.5", 9], ["5.1", 0], ["5", 0], ["abc"], [""], ["-1"], ["1e3"], [".5"], ["1."], ["9007199254"], ["9007199255"], ["99999999999999999999"]);
  check("amounts: digits, at most the mint's decimals, and nothing that cannot be sent exactly", JSON.stringify(got2)
    === JSON.stringify([20_000_000, 500_000, 1_234_567, null, 7_000_000, 0, 1_500_000_000, null, 5, null, null, null, null, null, null, 9_007_199_254_000_000, null, null]), got2);
  await page.close();
}

// ---- the numbers, the issuers' keys, and who can change the programs ----------------------------------------------------------
{
  const fmt = (u) => (u / 1e6).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const took = (s) => (s == null ? "n/a" : s < 120 ? `${s} s` : s < 7200 ? `${Math.round(s / 60)} min` : `${Math.round(s / 3600)} h`);
  const cells = (page, sel) => page.$$eval(`${sel} tr`, (tr) => tr.map((r) => [...r.children].map((c) => c.textContent.replace(/\s+/g, " ").trim())));
  const blocks = (page) => page.$$eval("#network-stats .stats", (b) => b.map((x) => [...x.querySelectorAll(".stat")].map((s) => [s.querySelector("b").textContent, s.querySelector("span").textContent])));
  const upgradeVault = ids.upgrade_authority, stranger = unique(50);
  check("numbers: the upgrade authority the ids name is the vault of the upgrade multisig", (await knos.squadsVault(ids.upgrade_multisig)) === upgradeVault);

  // devnet as it is: the first deployment's two programs with no upgrade authority; the second not deployed yet
  const deploy = async ({ oidc = "missing", pay = "missing", up = null, guard = null, first = [null, null], keys = [] } = {}) => {
    await reset();
    const authority = (a) => (a === "vault" ? upgradeVault : a);
    for (const [program, a] of [[ids.knos_oidc, oidc], [ids.knos_pay, pay], [FIRST.oidc, first[0]], [FIRST.pay, first[1]]]) {
      if (a !== "missing") put(await knos.programData(program), programDataBytes(authority(a)), knos.LOADER);
    }
    if (up) put(ids.upgrade_multisig, multisigBytes({ ...up, members: [unique(11), unique(12), unique(13)] }), knos.SQUADS);
    if (guard) put(ids.guardian_multisig, multisigBytes({ ...guard, members: [unique(14), unique(15), unique(16)] }), knos.SQUADS);
    keys.forEach((key, i) => put(unique(100 + i), keyBytes(key), ids.knos_oidc));
  };
  const loaded = async (page) => { await page.waitForSelector("#programs-now, #network-programs .status.bad"); await page.waitForSelector("#first-now, #first-deployment .status.bad"); await page.waitForSelector("#keys-table, #keys-none, #network-keys .status.bad"); await page.waitForSelector("#network-stats .stat, #network-stats .status"); };
  const states = (page, sel) => page.$$eval(`${sel} [data-state]`, (e) => e.map((x) => x.dataset.state));

  const page = await plain.newPage();
  served.stats = recorded("stats_with_data");
  await deploy();
  await visit(page, "#network");
  await loaded(page);
  const [outside, both] = await blocks(page);
  check("numbers: outside use, from stats.json: paid, funded, funders, people paid, repositories, repeat funders, money", JSON.stringify(outside)
    === JSON.stringify([["3", "tasks paid"], ["6", "tasks funded"], ["2", "funders"], ["2", "people paid"], ["3", "repositories"], ["1", "funders who funded again"], ["63.38", "test USDC paid out"], ["1.63", "test USDC in fees"]]), outside);
  check("  everything else is kept apart, one row each, and never added to outside use", JSON.stringify(await cells(page, "#network-kinds")) === JSON.stringify([
    ["", "Funded", "Paid", "Funders", "People paid", "Test USDC paid out"], ["Outside use", "6", "3", "2", "2", "63.38"], ["Knos's own accounts", "13", "8", "2", "2", "95.55"],
    ["Paid to themselves", "2", "2", "2", "2", "13.65"], ["Free faucet money", "2", "1", "1", "1", "24.38"]]), await cells(page, "#network-kinds"));
  check("  the funnel, with the way the installs were counted", JSON.stringify(await page.$$eval("#network-funnel li", (l) => l.map((x) => x.textContent.replace(/\s+/g, " ").trim()))) === JSON.stringify([
    "Repositories with the workflow: 3 (GitHub code search: public repositories whose workflow files call Knos's)", "Of those, repositories that funded a task: 2",
    "Repositories that funded a task, not Knos's own: 6", "Outside tasks completed: 3", "Funders who funded again after a payment: 1"]), await page.$$eval("#network-funnel li", (l) => l.map((x) => x.textContent)));
  check("  how long it took: count, median, 90th percentile, slowest; the relay's part apart", JSON.stringify(await cells(page, "#network-latency")) === JSON.stringify([
    ["", "Count", "Median", "90th percentile", "Slowest"], ["Comment to funded", "3", "4 min", "5 min", "5 min"], ["Merge to paid", "4", "61 s", "10 min", "10 min"],
    ["Funded to paid", "14", "3 min", "2 h", "2 h"], ["The relay's part, funding", "3", "9 s", "12 s", "12 s"], ["The relay's part, paying", "4", "6 s", "14 s", "14 s"]]), await cells(page, "#network-latency"));
  check("  the two deployments, and what is open and held now", JSON.stringify(both) === JSON.stringify([["8 of 12", "second deployment: paid of funded"], ["6 of 11", "first deployment: paid of funded"],
    ["2", "open now (20.00 test USDC)"], ["1", "held for people with no wallet (12.00)"], ["1", "refunded unpaid"], ["1", "wallets bound"], ["4", "Balances opened from a wallet"], ["0", "withdrawals"]]), both);
  const recent = recorded("stats_with_data").recent;
  check("  every latest payment: kind, amount, task, who was paid, how long, which deployment", JSON.stringify((await cells(page, "#network-recent")).slice(1))
    === JSON.stringify(recent.map((p) => [p.kind, fmt(p.amount), `repository ${p.repo}, issue #${p.issue}`, `GitHub user ${p.payee}`, took(p.seconds), p.deployment === 1 ? "first" : "second"])));
  check("  and each amount links to its transaction on devnet", JSON.stringify(await page.$$eval("#network-recent tr td:nth-child(2) a", (a) => a.map((x) => x.getAttribute("href"))))
    === JSON.stringify(recent.map((p) => `https://explorer.solana.com/tx/${p.tx}?cluster=devnet`)));
  check("  the note says when and by what it was counted", (await text(page, "#network-note")) === "Counted 2026-10-03 04:00 UTC by scripts/network_stats.py from the transaction history of both escrow programs.");

  // the programs: what Solana says now
  check("numbers: a second deployment that is not on devnet yet is said so, not guessed", JSON.stringify(await states(page, "#programs-now")) === JSON.stringify(["missing", "missing"])
    && (await text(page, "#multisigs-now")).split("not on devnet yet").length === 3 && (await text(page, "#keys-none")).includes("not on devnet yet, so it holds no keys"));
  check("  the first deployment's programs, from the page's own addresses, read as having no upgrade authority", JSON.stringify(await states(page, "#first-now")) === JSON.stringify(["immutable", "immutable"])
    && (await text(page, "#first-deployment")).includes(FIRST.oidc) && (await text(page, "#first-deployment")).includes(FIRST.pay));
  check("  the plan is stated in the words the project uses, as a plan", (await text(page, "#network-programs")).includes("The plan: upgradeable only through a multisig with a public 48-hour delay, until an outside review; then made immutable."));
  check("  the explorer links are for devnet", (await page.$$eval("#network-programs a", (a) => a.every((x) => x.getAttribute("href").endsWith("?cluster=devnet")))));

  for (const [what, setup, expected, words, absent = []] of [
    ["upgradeable only by the upgrade multisig's vault, 2 of 3, 48 hours", { oidc: "vault", pay: "vault", up: { threshold: 2, timeLock: 172800 }, guard: { threshold: 2, timeLock: 0 } }, ["multisig", "multisig"],
      ["2 of 3 members must approve, and an approved upgrade waits 48 hours before it can run.", "2 of 3 members must approve; no delay. The guardian can approve or revoke a signing key and pause new funding for at most 7 days."], ["not the 48 hours"]],
    ["a delay that is not the 48 hours said", { oidc: "vault", pay: "vault", up: { threshold: 2, timeLock: 3600 }, guard: { threshold: 1, timeLock: 0 } }, ["multisig", "multisig"], ["waits 1 hour before it can run", "(not the 48 hours stated above)"]],
    ["a program that someone else can upgrade", { oidc: stranger, pay: "vault", up: { threshold: 2, timeLock: 172800 }, guard: { threshold: 2, timeLock: 0 } }, ["other", "multisig"],
      [`upgradeable by ${stranger}, which is not the upgrade multisig of this deployment`]],
    ["a second deployment made immutable after its review", { oidc: null, pay: null, up: { threshold: 2, timeLock: 172800 }, guard: { threshold: 2, timeLock: 0 } }, ["immutable", "immutable"], ["no upgrade authority is set"]],
    ["one program deployed and the other not", { oidc: "vault", pay: "missing" }, ["multisig", "missing"], ["not on devnet yet"]]]) {
    await deploy(setup);
    await visit(page, "#network");
    await loaded(page);
    const said = await text(page, "#network-programs");
    check(`numbers: ${what}`, JSON.stringify(await states(page, "#programs-now")) === JSON.stringify(expected) && words.every((w) => said.includes(w)) && absent.every((w) => !said.includes(w)), said);
  }
  await deploy({ first: [stranger, null] });
  await visit(page, "#network");
  await loaded(page);
  check("numbers: a first-deployment program that someone can upgrade is said so, in red", JSON.stringify(await states(page, "#first-now")) === JSON.stringify(["other", "immutable"]) && (await text(page, "#first-now")).includes(`upgradeable by ${stranger}`));
  check("numbers: nothing on the page promises that nobody can change the second deployment", !/\b(nobody can change|no one can change|can never be changed|cannot be changed)\b/i.test(await text(page, "#view-network")));

  // the issuers' signing keys, from the chain's own clock
  const day = 86400;
  const keyList = [["usable genesis", { flags: 5, activeAt: NOW - 100 * day, expiresAt: NOW + 20 * day, seed: 1 }, `usable until ${when(NOW + 20 * day)}`, "built in"],
    ["attested and approved", { flags: 1, activeAt: NOW - 2 * day, expiresAt: NOW + 25 * day, seed: 2 }, `usable until ${when(NOW + 25 * day)}`, "attested"],
    ["revoked", { flags: 3, activeAt: NOW - 9 * day, expiresAt: NOW + 21 * day, seed: 3 }, "revoked for good", "attested"],
    ["expired", { flags: 1, activeAt: NOW - 40 * day, expiresAt: NOW - 3600, seed: 4 }, `expired ${when(NOW - 3600)}`, "attested"],
    ["GitLab, waiting for the guardian", { issuer: 1, limbs: 128, flags: 0, activeAt: NOW + day, expiresAt: NOW + 31 * day, seed: 5 }, "waiting for the guardian's approval", "attested"],
    ["approved but not yet active", { flags: 1, activeAt: NOW + 3600, expiresAt: NOW + 30 * day, seed: 6 }, `usable from ${when(NOW + 3600)}`, "attested"],
    ["registered, not ready", { state: 0, flags: 1, activeAt: NOW - day, expiresAt: NOW + 29 * day, seed: 7 }, "registered, not ready", "attested"]];
  await deploy({ oidc: "vault", pay: "vault", up: { threshold: 2, timeLock: 172800 }, guard: { threshold: 2, timeLock: 0 }, keys: keyList.map(([, key]) => key) });
  await visit(page, "#network");
  await loaded(page);
  const hashes = await Promise.all(keyList.map(async ([, key], i) => (await knos.v2.keyAccountHash(chain.accounts.get(unique(100 + i)).data)).slice(0, 12)));
  const shown = await page.$$eval("#keys-table tr", (tr) => tr.slice(1).map((r) => [...r.children].map((c) => c.textContent.trim())));
  const want = keyList.map(([, key, label, how], i) => [key.issuer === 1 ? "GitLab" : "GitHub", `${(key.limbs || 64) * 32} bits`, hashes[i], how, label, when(key.expiresAt)])
    .sort((a, b) => (a[0] === b[0] ? a[5].localeCompare(b[5]) : a[0].localeCompare(b[0])));
  check("keys: every signing key on chain, by issuer then expiry: size, start of its hash, how it got in, whether it works now, when it expires", JSON.stringify(shown) === JSON.stringify(want), shown);
  check("  the clock is the chain's, and the page says when it read", (await text(page, "#network-keys")).includes(`at ${when(NOW)}`));
  check("  the sentence says a key nobody attests again stops working", (await text(page, "#network-keys")).includes("a key that nobody attests again stops working then"));
  await deploy({ oidc: "vault", pay: "vault" });
  await visit(page, "#network");
  await loaded(page);
  check("keys: a deployed knos-oidc with no key says so", (await text(page, "#keys-none")) === "No signing key is on chain yet.");

  // the chain cannot be read: that is said, never turned into "not deployed"
  await deploy({ oidc: "vault", pay: "vault", up: { threshold: 2, timeLock: 172800 }, guard: { threshold: 2, timeLock: 0 } });
  chain.down = "Node is behind by 100 slots";
  await visit(page, "#network");
  await page.waitForFunction(() => document.querySelectorAll("#network-programs .status.bad, #network-keys .status.bad, #first-deployment .status.bad").length === 3);
  check("numbers: when Solana cannot be read, each card says so and never says 'not on devnet yet'", (await text(page, "#network-programs")).includes("Could not read Solana devnet just now (Node is behind by 100 slots)")
    && !(await text(page, "#view-network")).includes("not on devnet yet") && (await text(page, "#network-stats")).includes("tasks paid"));
  chain.down = null;

  // the three recorded samples, and files that are not what they should be
  for (const [name, sample, rows, both2] of [["empty", recorded("stats_empty"), [["Outside use", "0", "0", "0", "0", "0.00"], ["Knos's own accounts", "0", "0", "0", "0", "0.00"]], ["0 of 0", "0 of 0"]],
    ["first deployment only", recorded("stats_first_deployment"), [["Outside use", "0", "0", "0", "0", "0.00"], ["Knos's own accounts", "11", "6", "1", "1", "62.40"]], ["0 of 0", "6 of 11"]]]) {
    served.stats = sample;
    await deploy();
    await visit(page, "#network");
    await loaded(page);
    const [, secondRow, thirdRow] = await cells(page, "#network-kinds");
    check(`numbers (${name}): a zero is shown as a zero, outside use apart from Knos's own`, JSON.stringify([secondRow, thirdRow]) === JSON.stringify(rows), [secondRow, thirdRow]);
    check(`  (${name}): the deployments' rows`, JSON.stringify((await blocks(page))[1].slice(0, 2).map((x) => x[0])) === JSON.stringify(both2));
    if (name === "empty") {
      check("  (empty): nothing measured says not measured, never a made-up time", (await text(page, "#network-funnel")).includes("Repositories with the workflow: not measured")
        && JSON.stringify((await cells(page, "#network-latency")).slice(1).map((r) => r.slice(1))) === JSON.stringify(Array(5).fill(["0", "n/a", "n/a", "n/a"])) && await gone(page, "#network-recent"));
    }
  }
  served.stats = { ...recorded("stats_with_data"), error: "<img src=x onerror=alert(1)> GitHub was not asked", recent: [{ ...recorded("stats_with_data").recent[0], kind: "<b>own</b>", tx: "<i>no</i>" }] };
  await visit(page, "#network");
  await loaded(page);
  check("numbers: text in stats.json is text, never markup", await page.$("#view-network img") === null && await page.$("#network-recent b") === null && (await text(page, "#network-note")).includes("Not everything could be read: <img src=x"));
  for (const [what, sample, words] of [["a file with no counts", { error: "no history <b>yet</b>" }, "no history <b>yet</b>"], ["no file", null, "The numbers are built with the site; none here yet."], ["a list", [], "The numbers are built with the site; none here yet."]]) {
    served.stats = sample;
    await visit(page, "#network");
    await page.waitForSelector("#network-stats .status");
    check(`numbers: ${what}: a sentence, no error`, (await text(page, "#network-stats")).includes(words) && await gone(page, "#network-stats b"));
  }
  served.stats = recorded("stats_with_data");
  await page.close();
}

// ---- links ------------------------------------------------------------------------------------------------------------------------
{
  const page = await plain.newPage();
  await visit(page);
  const hrefs = await page.$$eval("a[href]", (a) => a.map((x) => x.getAttribute("href")));
  const bad = hrefs.filter((h) => !(h.startsWith("#") ? ["check", "protect", "fund", "claim", "network", "build"].includes(h.slice(1))
    : h === TEMPLATE_LINK || /^https:\/\/github\.com\/drexthealpha\/|^https:\/\/faucet\.circle\.com\/$|^(index|stats)\.json$/.test(h)));
  check("links: every link goes to a view, to the project's own GitHub, to Circle's devnet faucet or to a file of the site", bad.length === 0, bad);
  check("  a link that opens a new tab does not hand over the page", await page.$$eval('a[target="_blank"]', (a) => a.every((x) => /noopener/.test(x.rel))));
  await page.close();
}

// ---- a phone: nothing runs off the side of the screen in any view, with the longest content each can show ----------------------------
{
  await reset();
  const day = 86400, OWNER_BAL = await k.balance(424242, OTHER_WALLET, USDC);
  put(await k.job(5550001, 7, OWNER_BAL), jobBytes({ repoId: 5550001, issue: 7, source: OWNER_BAL, mint: USDC, amount: 20_000_000, deadline: NOW + 14 * day, ownerId: 424242, funderId: 583231 }), ids.knos_pay);
  put(await k.bind(4242), bindBytes({ userId: 4242, wallet: OTHER_WALLET, iat: NOW - day }), ids.knos_pay);
  put(await k.rep(4242), repBytes({ paid: 3, funders: 2, total: 58_500_000, first: NOW - 30 * day, last: NOW - day }), ids.knos_pay);
  for (const [program, a] of [[ids.knos_oidc, ids.upgrade_authority], [ids.knos_pay, ids.upgrade_authority], [FIRST.oidc, null], [FIRST.pay, null]]) put(await knos.programData(program), programDataBytes(a), knos.LOADER);
  put(ids.upgrade_multisig, multisigBytes({ threshold: 2, timeLock: 172800, members: [unique(11), unique(12), unique(13)] }), knos.SQUADS);
  put(ids.guardian_multisig, multisigBytes({ threshold: 2, timeLock: 0, members: [unique(14), unique(15), unique(16)] }), knos.SQUADS);
  put(unique(100), keyBytes({ flags: 5, activeAt: NOW - 100 * day, expiresAt: NOW + 20 * day }), ids.knos_oidc);
  put(unique(101), keyBytes({ issuer: 1, limbs: 128, flags: 0, activeAt: NOW + day, expiresAt: NOW + 31 * day, seed: 5 }), ids.knos_oidc);
  served.front = stamp(COMMIT);
  const phone = await world({ wallets: [["Test Wallet", WALLET]], width: 360 });
  const page = await phone.newPage();
  const wide = async (what) => {
    const { over, culprits } = await page.evaluate(() => ({ over: document.documentElement.scrollWidth - document.documentElement.clientWidth,
      culprits: [...document.querySelectorAll("body *")].filter((e) => e.offsetParent !== null && (e.getBoundingClientRect().right > document.documentElement.clientWidth + 1
        || (e.scrollWidth > e.clientWidth + 1 && getComputedStyle(e).overflowX === "visible"))).slice(0, 4)
        .map((e) => `<${e.tagName.toLowerCase()}${e.id ? ` id=${e.id}` : ""}${e.className ? ` class=${e.className}` : ""}> ${e.textContent.trim().slice(0, 40)}`) }));
    check(`phone: ${what}: nothing runs off the side`, over <= 1, over > 1 ? [over, ...culprits] : "");
  };
  const openAll = () => page.evaluate(() => document.querySelectorAll("details").forEach((d) => { d.open = true; }));

  await visit(page);
  await page.fill("#pr-url", "https://github.com/octo/widgets/pull/12"); await page.click("#pr-check"); await page.waitForSelector("#verdict");
  await wide("check a pull request, with a result");
  await page.fill("#pr-url", "octo/widgets"); await page.click("#pr-check"); await page.waitForSelector("#repo-record");
  await wide("  and with a repository's record");
  await visit(page, "#protect");
  await page.fill("#protect-repo", "octo/widgets"); await page.click("#protect-go"); await page.waitForSelector("#protect-open");
  await openAll();
  await wide("protect a repository, with the files open");
  await visit(page, "#fund");
  await page.click("#wallet-connect"); await page.waitForSelector("#wallet-address");
  await page.fill("#owner-login", "octo-org"); await page.click("#owner-go"); await page.waitForSelector("#money-form");
  await page.fill("#money-amount", "3"); await page.fill("#money-spenders", "mona, octocat, carol, quiet"); await page.click("#money-add"); await page.waitForSelector("#money-send");
  await openAll();
  await page.fill("#st-issue", "octo/widgets#7"); await page.click("#st-go"); await page.waitForSelector("#st-result dl");
  await wide("fund a task, with a wallet connected, a preview and an escrow");
  if (process.argv[3]) await page.screenshot({ path: process.argv[3], fullPage: true });
  await visit(page, "#claim");
  await page.fill("#due-login", "mona"); await page.click("#due-go"); await page.waitForSelector("#due-record");
  await wide("get paid, with an account and the two steps to bind a wallet");
  await visit(page, "#network");
  await page.waitForSelector("#programs-now"); await page.waitForSelector("#keys-table"); await page.waitForSelector("#network-recent");
  await wide("numbers, with the keys and the programs");
  await visit(page, "#build");
  await wide("build on it");
  await page.close();
  served.front = (code) => code;
}

// @@END

await browser.close(); server.close();
check("no console errors", errors.length === 0, errors);
check("nothing was asked of anyone but this page, GitHub and devnet", strangers.length === 0, strangers);
