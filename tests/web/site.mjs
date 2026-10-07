// node tests/web/site.mjs <site dir> [screenshot.png]
// The built site (scripts/build_site.sh) in headless Chromium against a mocked GitHub API, a mocked Solana devnet RPC
// and a mocked wallet. Every view renders; each flow does what the page says; the transactions the wallet is asked to
// sign are byte for byte the ones sdk/settle builds; a cluster that is not devnet is refused; the numbers shown are
// the numbers in the recorded stats.json samples; the page asks nobody but GitHub and devnet. Needs the `playwright`
// package (tests.yml installs it).
import pw from "playwright";
const { chromium } = pw;
import { createServer } from "node:http";
import { readFileSync, existsSync, readdirSync } from "node:fs";
import { join, extname, dirname } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import * as knos from "../../sdk/settle/index.js";
import * as passkey from "../../sdk/settle/passkey.js";
import { generateKeyPairSync, createHash, createPublicKey, sign as ecSign, verify as ecVerify, randomBytes, ECDH } from "node:crypto";

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
const repos = { "octo/widgets": 5550001, "octo/other": 5550002, "octo/recorded": 1401439243, "octocat/knos-task": 5550003, "octocat/trunky": 5550004, "octo/old": 5550010 };
// the issues GitHub answers for (`/repos/<repo>/issues/<n>`): a pull request is an issue to GitHub's API, with a pull_request member
const issues = { "octo/widgets#7": { title: "Parser crashes on an empty file", state: "open" }, "octo/widgets#8": { title: "Fixed long ago", state: "closed" },
  "octo/widgets#12": { title: "Fixes #7", state: "open", pull_request: { url: "x" } }, "octo/other#3": { title: "<img src=x onerror=alert(1)> and a very long title " + "w".repeat(200), state: "open" },
  "octo/old#1": { title: "In an archived repository", state: "open" } };
const examplePrs = recorded("example_prs").prs;
const firstDeployment = recorded("devnet_first_deployment").transactions;
// A payment of the second deployment that a relay carried: on a 2.1 cluster that is a version 1 transaction, and a cluster
// gives one only to a reader whose maxSupportedTransactionVersion is at least 1 (anything lower is refused with -32015).
const relayed = { signature: "3".repeat(88), version: 1, blockTime: 1_790_000_000, transaction: { message: { accountKeys: [] } },
  meta: { err: null, logMessages: [`Program ${ids.knos_pay} invoke [1]`, "Program log: knos2:paid repo=777000111 issue=31 author=4242 amount=19500000 fee=500000 to=W pr=9",
    `Program ${ids.knos_pay} success`] } };
const index = { date: "2026-10-02", n_prs: 5, agents: {}, prs: [
  { agent: "copilot", repo: "octo/widgets", number: 1, sha: "a".repeat(40), class: "passed", failed_checks: [], phrase: "all tests pass" },
  { agent: "copilot", repo: "octo/widgets", number: 2, sha: "b".repeat(40), class: "failed", failed_checks: ["build (3.12)"], phrase: "tests pass" },
  { agent: "devin", repo: "octo/widgets", number: 4, sha: "f".repeat(40), class: "other", failed_checks: [], phrase: "CI is green" },
  { agent: "codex", repo: "octo/widgets", number: 3, sha: "c".repeat(40), class: "failed", failed_checks: ["lint"], phrase: "<img src=x onerror=alert(1)> green" },
  { agent: "devin", repo: "acme/gadgets", number: 9, sha: "d".repeat(40), class: "other", failed_checks: [], phrase: "CI is green" }] };

// what the server hands out besides the site: the numbers and the index; and a way to change front.js for one page
const served = { stats: recorded("stats_with_data"), index, front: (text) => text, config: (text) => text, settle: (text) => text, extra: {} };   // extra: path -> { type, body }
const types = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json", ".svg": "image/svg+xml", ".yml": "text/plain" };
const server = createServer((req, res) => {
  const path = req.url.split("?")[0];
  const json = (o) => { res.writeHead(200, { "Content-Type": "application/json" }); res.end(JSON.stringify(o)); };
  if (path === "/stats.json") return served.stats === null ? (res.writeHead(404), res.end()) : json(served.stats);
  if (path === "/index.json") return json(served.index);
  if (served.extra[path]) { res.writeHead(200, { "Content-Type": served.extra[path].type }); return res.end(served.extra[path].body); }
  const file = join(root, path === "/" ? "index.html" : path);
  if (!existsSync(file)) { res.writeHead(404); return res.end(); }
  const body = path === "/front.js" ? served.front(readFileSync(file, "utf8")) : path === "/config.js" ? served.config(readFileSync(file, "utf8")) : path === "/settle.js" ? served.settle(readFileSync(file, "utf8")) : readFileSync(file);
  res.writeHead(200, { "Content-Type": types[extname(file)] || "text/plain" }); res.end(body);
}).listen(0);
const base = `http://127.0.0.1:${server.address().port}/`;

// devnet: accounts by address, and a log of every call, the wallet's included
const chain = { accounts: new Map(), lamports: new Map(), calls: [], sent: [], statuses: new Map(), genesis: DEVNET, blockhash: BLOCKHASH, simulate: null, failAfter: null, neverSeen: false, down: null, downFor: null, seq: 0 };
const put = (address, data, owner) => chain.accounts.set(address, { data, owner });
const reset = async () => {
  Object.assign(chain, { calls: [], sent: [], genesis: DEVNET, blockhash: BLOCKHASH, simulate: null, failAfter: null, neverSeen: false, down: null, downFor: null });
  chain.accounts.clear(); chain.lamports.clear(); chain.statuses.clear();
  put(USDC, mintBytes(6), knos.TOKEN);
  put(await knos.ata(WALLET, USDC), tokenBytes({ mint: USDC, owner: WALLET, amount: 100_000_000 }), knos.TOKEN);
  chain.lamports.set(WALLET, 1_500_000_000);
};
// a Version read of knos_pay (instruction 12, simulated: web/version.js) is made whenever the Fund or Pricing view is shown; `called` leaves it out, `calledAll` does not
const calledAll = (method) => chain.calls.filter((c) => c.method === method);
const called = (method) => calledAll(method).filter((c) => !c.version);

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
// What a page does is held here with movement off, so a check never waits for a transition to end; what moves, and
// that it stops for a reader who asked, is held by tests/web/motion.mjs.
// A longer explanation is folded under "More" (details.k-more): the flows here read the page with every one open.
{ const open = browser.newContext.bind(browser);
  browser.newContext = async (o = {}) => { const ctx = await open({ reducedMotion: "reduce", ...o });
    await ctx.addInitScript(() => addEventListener("DOMContentLoaded", () => { for (const d of document.querySelectorAll("details.k-more")) d.open = true; })); return ctx; }; }
const errors = [], strangers = [];
const cors = { "access-control-allow-origin": "*", "access-control-expose-headers": "x-ratelimit-remaining, x-ratelimit-reset" };
let githubReads = 0;
// what GitHub holds for the Status page and for a profile: the relay's log (the open issue labelled knos-relay in
// drexthealpha/Knos and its comments), the canary's repository, and <login>/<login>/.knos/profile.json by login
const hub = { relayIssues: [], relayComments: [], canary: [], profiles: {}, asked: [], down: false, playground: [], playgroundAsked: 0 };

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
    if (p.startsWith("/repos/drexthealpha/Knos/issues") || p.startsWith("/repos/drexthealpha/knos-e2e/") || p.endsWith("/contents/.knos/profile.json")) {
      hub.asked.push(p + u.search);
      if (hub.down) return json({ message: "Server Error" }, 500);
      if (p === "/repos/drexthealpha/Knos/issues") return json(u.searchParams.get("labels") === "knos-relay" && u.searchParams.get("state") === "open" ? hub.relayIssues : []);
      const log = /^\/repos\/drexthealpha\/Knos\/issues\/(\d+)\/comments$/.exec(p);
      if (log) return json(hub.relayIssues.some((i) => i.number === Number(log[1])) ? hub.relayComments.filter((c) => Date.parse(c.updated_at) >= Date.parse(u.searchParams.get("since"))) : []);
      if (p === "/repos/drexthealpha/knos-e2e/issues") return json(hub.canary);
      const profile = /^\/repos\/([^/]+)\/\1\/contents\/\.knos\/profile\.json$/.exec(p);
      if (profile && hub.profiles[profile[1]]) return json({ encoding: "base64", content: Buffer.from(JSON.stringify(hub.profiles[profile[1]])).toString("base64") });
      return json({ message: "Not Found" }, 404);
    }
    if (p === "/repos/drexthealpha/knos-playground/issues") { hub.playgroundAsked++; return json(hub.playground); }
    if (p === "/rate_limit") { githubReads--; return json({ resources: { core: { limit: 60, remaining: 57, reset: 1790003600 } } }); }
    if (p === "/repos/octo/widgets/pulls/12/commits") return json([{ sha: "e".repeat(40) }]);
    const issue = /^\/repos\/([^/]+\/[^/]+)\/issues\/(\d+)$/.exec(p);
    if (issue && issue[1] === "limited/repo") return json({ message: "rate limit" }, 403, { "x-ratelimit-remaining": "0" });
    if (issue) { const got = issues[`${issue[1]}#${issue[2]}`]; return got ? json({ number: Number(issue[2]), ...got }) : json({ message: "Not Found" }, 404); }
    if (repos[p.slice(7)]) return json({ id: repos[p.slice(7)], default_branch: { "octocat/trunky": "trunk" }[p.slice(7)] ?? "main", full_name: p.slice(7), archived: p.slice(7) === "octo/old", private: false });
    if (p === "/repos/octo/widgets/pulls/12") return json({ number: 12, body: "Fixes #7", html_url: "https://github.com/octo/widgets/pull/12", user: { login: "mona" },
      head: { sha: "e".repeat(40) }, base: { repo: { full_name: "octo/widgets", name: "widgets", owner: { login: "octo" }, default_branch: "develop" } } });
    const example = examplePrs.find((x) => p.startsWith(`/repos/${x.repo}/`));
    if (example) {                                                     // the recorded examples of the first screen (tests/web/recorded/example_prs.json)
      if (p === `/repos/${example.repo}/pulls/${example.number}`) return json({ number: example.number, body: example.claim_line, html_url: `https://github.com/${example.repo}/pull/${example.number}`,
        user: { login: example.author }, head: { sha: example.sha }, base: { repo: { full_name: example.repo, name: example.repo.split("/")[1], owner: { login: example.repo.split("/")[0] }, default_branch: "main" } } });
      if (p.endsWith("/check-runs")) return json({ check_runs: Array.from({ length: example.n_check_runs }, (_, i) => ({ name: example.failed_checks[i] ?? `check ${i}`, status: "completed", conclusion: i < example.failed_checks.length ? "failure" : "success" })) });
      if (p.endsWith("/status")) return json({ sha: example.sha, statuses: [] });
    }
    if (p.startsWith("/repositories/")) { const named = Object.entries(repos).find(([, id]) => id === Number(p.slice(14))); return named ? json({ id: Number(p.slice(14)), full_name: named[0] }) : json({ message: "Not Found" }, 404); }
    if (p.endsWith("/check-runs")) return json({ check_runs: [] });
    if (p.endsWith("/status")) return json({ sha: "e".repeat(40), statuses: [] });
    if (p === "/repos/limited/repo") return json({ message: "rate limit" }, 403, { "x-ratelimit-remaining": "0" });
    return json({ message: "Not Found" }, 404);
  });
  await ctx.route("https://api.devnet.solana.com/**", async (route) => {
    const { method, params } = JSON.parse(route.request().postData());
    const version = method === "simulateTransaction" && (() => { try { const [ix, ...more] = readTx(Uint8Array.from(Buffer.from(params[0], "base64"))); return !more.length && ix.program === ids.knos_pay && ix.data.length === 1 && ix.data[0] === 12; } catch { return false; } })();
    chain.calls.push({ method, params, ...(version ? { version } : {}) });
    const reply = (result) => route.fulfill({ status: 200, contentType: "application/json", headers: cors, body: JSON.stringify({ jsonrpc: "2.0", id: 1, result }) });
    const ctxd = (value) => reply({ context: { slot: 100 }, value });
    const info = (a) => (a ? { data: [b64(a.data), "base64"], owner: a.owner, lamports: 2_000_000 } : null);
    if (chain.down) return route.fulfill({ status: 200, contentType: "application/json", headers: cors, body: JSON.stringify({ jsonrpc: "2.0", id: 1, error: { code: -32005, message: chain.down } }) });
    if (method === "getGenesisHash") return reply(chain.genesis);
    if (method === "getSlot") return reply(100);
    if (method === "getBlockTime") return reply(NOW);
    if (method === "getBalance") return ctxd(chain.lamports.get(params[0]) ?? 0);
    if (method === "getAccountInfo") return ctxd(info(chain.accounts.get(params[0])));
    if (method === "getMultipleAccounts") return ctxd(params[0].map((a) => info(chain.accounts.get(a))));
    if (method === "getLatestBlockhash") return ctxd({ blockhash: chain.blockhash, lastValidBlockHeight: 200 });
    if (method === "simulateTransaction") return ctxd({ err: chain.simulate?.err ?? null, logs: chain.simulate?.logs ?? [] });
    if (method === "getSignatureStatuses") return ctxd(params[0].map((s) => chain.statuses.get(s) ?? null));
    if (method === "getTransaction") {
      const t = [...firstDeployment, relayed].find((x) => x.signature === params[0]);
      if (t && (t.version ?? -1) > (params[1]?.maxSupportedTransactionVersion ?? -1)) {
        const message = `Transaction version (${t.version}) is not supported by the requesting client. Please try the request again with the higher supported version`;
        return route.fulfill({ status: 200, contentType: "application/json", headers: cors, body: JSON.stringify({ jsonrpc: "2.0", id: 1, error: { code: -32015, message } }) });
      }
      return reply(t ? { slot: 100, blockTime: t.blockTime, meta: t.meta, transaction: t.transaction, version: t.version ?? "legacy" } : null);
    }
    if (method === "getProgramAccounts") {
      // one program's accounts that cannot be read (a rate limit on the extra query), the rest of devnet answering
      if (chain.downFor && params[0] === chain.downFor.program) return route.fulfill({ status: 200, contentType: "application/json", headers: cors, body: JSON.stringify({ jsonrpc: "2.0", id: 1, error: { code: -32429, message: chain.downFor.message } }) });
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

// the device's passkeys, as a stand-in for navigator.credentials: real P-256 keys made here in Node, so a signature the page carries
// can be checked with the public key alone. It outlives page loads (as a device does), and `cancel` is the person saying no.
const device = { keys: new Map(), creates: 0, gets: [], cancel: false, counter: 0 };
const sha256 = (...parts) => createHash("sha256").update(Buffer.concat(parts.map((p) => Buffer.from(p)))).digest();
const b64url = (buf) => Buffer.from(buf).toString("base64url");

const contexts = [];
async function world({ wallets = [], width = 1100, passkeys = false } = {}) {
  const ctx = await browser.newContext({ viewport: { width, height: 900 } });
  contexts.push(ctx);
  await mock(ctx);
  if (passkeys) {
    await ctx.exposeFunction("deviceCreate", (rpId) => {
      if (device.cancel) return { refused: "NotAllowedError: The operation either timed out or was not allowed." };
      const { publicKey, privateKey } = generateKeyPairSync("ec", { namedCurve: "P-256" }), id = randomBytes(16);
      device.keys.set(id.toString("base64"), { privateKey, publicKey, rpId });
      device.creates++;
      return { id: id.toString("base64"), spki: publicKey.export({ type: "spki", format: "der" }).toString("base64") };
    });
    await ctx.exposeFunction("deviceGet", (id, rpId, challenge) => {
      const have = device.keys.get(id);
      if (device.cancel || !have || have.rpId !== rpId) return { refused: "NotAllowedError: The operation either timed out or was not allowed." };
      const authenticatorData = Buffer.concat([sha256(rpId), Buffer.from([0x05]), Buffer.from(new Uint8Array(new Uint32Array([++device.counter]).buffer).reverse())]);
      const clientDataJSON = Buffer.from(JSON.stringify({ type: "webauthn.get", challenge: b64url(Buffer.from(challenge, "base64")), origin: base.slice(0, -1), crossOrigin: false }));
      const signature = ecSign("sha256", Buffer.concat([authenticatorData, sha256(clientDataJSON)]), { key: have.privateKey, dsaEncoding: "der" });
      device.gets.push({ id, rpId, challenge: Buffer.from(challenge, "base64") });
      return { authenticatorData: authenticatorData.toString("base64"), clientDataJSON: clientDataJSON.toString("base64"), signature: signature.toString("base64") };
    });
    await ctx.addInitScript(() => {
      const bin = (b64) => Uint8Array.from(atob(b64), (c) => c.charCodeAt(0)), text = (u8) => btoa(String.fromCharCode(...u8));
      const refuse = (r) => { const [name, ...msg] = r.refused.split(": "); throw Object.assign(new Error(msg.join(": ")), { name }); };
      Object.defineProperty(navigator, "credentials", { configurable: true, value: {
        create: async ({ publicKey }) => {
          const r = await window.deviceCreate(publicKey.rp.id);
          if (r.refused) refuse(r);
          return { rawId: bin(r.id).buffer, response: { getPublicKey: () => bin(r.spki).buffer } };
        },
        get: async ({ publicKey }) => {
          const id = publicKey.allowCredentials?.[0]?.id;
          const r = await window.deviceGet(id ? text(new Uint8Array(id)) : "", publicKey.rpId, text(new Uint8Array(publicKey.challenge)));
          if (r.refused) refuse(r);
          return { response: { authenticatorData: bin(r.authenticatorData).buffer, clientDataJSON: bin(r.clientDataJSON).buffer, signature: bin(r.signature).buffer } };
        } } });
    });
  }
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
    p.on("console", (m) => { if (m.type() === "error" && !(/Failed to load resource/.test(m.text()) && /api\.github\.com|api\.devnet\.solana\.com|\/stats\.json$|\/missing\.webm$/.test(m.location().url))) errors.push(m.text()); });
    p.on("pageerror", (e) => errors.push(String(e)));
  });
  return ctx;
}
let visits = 0;
// a page is ready when the code of the page its hash names has arrived and run (web/front.js marks the root then: each
// page's code is asked for when the page is first opened, not with the first screen)
const visit = async (page, hash = "") => { await page.goto(`${base}?n=${++visits}${hash}`); await page.waitForFunction(() => document.documentElement.dataset.ready !== undefined); };
// The commit the two workflow files name is read from the files themselves. A test that wants a commit there stamps it into a
// copy of front.js, so it holds for whatever the examples say, before a release and after.
const refs = /(\/\.github\/workflows\/[\w.-]+@)(\$\{\w+\}|[^\s`]+)/g;
const stamp = (to) => (code) => code.replace(refs, (_, head) => head + to);
const COMMIT = "a".repeat(40);
const DOCS = "https://github.com/drexthealpha/Knos/tree/main/docs";
const text = async (page, sel) => (await page.textContent(sel)).replace(/\s+/g, " ");
const gone = async (page, sel) => (await page.$(sel)) === null;
// two words no page may print (a figure of a thousand millions, and the three letters for yearly recurring revenue), spelled from their letters so that this file does not hold them either
const NOT_SAID = [[98, 105, 108, 108, 105, 111, 110], [65, 82, 82]].map((codes) => String.fromCharCode(...codes));
// how far the page runs off the side, at the worst of the widths it must hold (the page is left at the width it had)
const overflow = async (page) => {
  const was = page.viewportSize(), over = [];
  for (const width of [320, 360, 390, 768, 1280]) { await page.setViewportSize({ width, height: was.height }); over.push(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)); }
  await page.setViewportSize(was);
  return Math.max(...over);
};
const dec = (units) => (units / 1e6).toFixed(6).replace(/(\.\d\d\d*?)0+$/, "$1");          // 4875000 -> "4.875", 0 -> "0.00": as the page shows an amount

// ======================================================================================================================
const plain = await world();        // a browser with no wallet in it: everything but "Add money" still works
await reset();

// ---- the front door ----------------------------------------------------------------------------------------------------------
{
  served.front = stamp(COMMIT);                  // so the Protect view hands out its links whatever commit the examples name
  const page = await plain.newPage();
  await visit(page);
  const SHORT = "The neutral meter for AI agent work: neither side keeps the count.";
  const LEAD = "A work order is a task, its budget and the terms that decide whether it is done, fixed before the work starts. A bounty on an issue is the smallest work order. When the work is merged, a workflow run that GitHub signs says whether the terms were met, and a Solana program checks that signature itself before it pays. No person holds the money in between.";
  check("front door renders: the one sentence, then what a work order is", (await text(page, "h1")) === SHORT && (await text(page, "#view-check .lede")) === LEAD);
  check("  the title is a short name, the description is the sentence", (await page.title()) === "Knos: the neutral meter for AI agent work" && SHORT.toLowerCase().startsWith(`${(await page.title()).replace("Knos: ", "").toLowerCase()}:`) && (await page.getAttribute('meta[name="description"]', "content")).startsWith(`${SHORT} `));
  // the brand: one source (web/brand/), drawn in the colour of the text, and nothing of it comes from another host
  {
    const mark = (name) => (readFileSync(join(root, name), "utf8").match(/ d="([^"]+)"/g) || []).join();
    const brand = await page.$eval(".brand .wordmark", (e) => { const s = getComputedStyle(e), b = e.getBoundingClientRect(); return { mask: s.maskImage || s.webkitMaskImage, ink: s.backgroundColor, text: getComputedStyle(e.parentElement).color, w: b.width, h: b.height }; });
    check("the bar shows the wordmark, in the colour of the text, and the link still has its name", /brand\/wordmark\.svg"?\)$/.test(brand.mask) && brand.ink === brand.text && brand.w > 80 && brand.h >= 28 && brand.h <= 44
      && (await page.getAttribute(".brand", "aria-label")) === "Knos home" && (await text(page, ".brand .name")) === "Knos" && (await page.$(".brand img")) === null, brand);
    const got = await page.evaluate(async () => { const one = async (u) => { const r = await fetch(u); return { ok: r.ok, type: r.headers.get("content-type"), size: (await r.arrayBuffer()).byteLength }; };
      return { word: await one("brand/wordmark.svg"), mark: await one("brand/mark.svg"), touch: await one(document.querySelector('link[rel="apple-touch-icon"]').getAttribute("href")) }; });
    check("  the wordmark, the mark and the home-screen icon are files of this site", got.word.ok && got.mark.ok && got.touch.ok && got.word.size < 12000 && got.mark.size < 6000 && got.touch.size > 1000, got);
    const icon = await page.getAttribute('link[rel="icon"]', "href");
    check("  the favicon is the mark: the small copy of it, with no colour of its own but the tab's", icon === "icon.svg" && mark("icon.svg") === mark("brand/mark-small.svg") && mark("icon.svg").length > 500
      && !/fill="(?!currentColor)/.test(readFileSync(join(root, "icon.svg"), "utf8")) && !/<script|href|url\(/i.test(readFileSync(join(root, "icon.svg"), "utf8")));
    const card = await page.getAttribute('meta[property="og:image"]', "content");
    check("  the card of a shared link is this site's own file, 1200 by 630", card === "https://drexthealpha.github.io/Knos/brand/card.png" && existsSync(join(root, "brand", "card.png"))
      && readFileSync(join(root, "brand", "card.png")).readUInt32BE(16) === 1200 && readFileSync(join(root, "brand", "card.png")).readUInt32BE(20) === 630);
    const tags = await page.$$eval("head link[href], head script[src], head meta[content]", (l) => l.map((x) => x.getAttribute("href") || x.getAttribute("src") || "").filter((h) => /^(https?:)?\/\//.test(h)));
    check("  the head asks no other host for anything", tags.length === 0 && strangers.length === 0, [tags, strangers]);
    for (const [scheme, ink] of [["light", "rgb(21, 23, 28)"], ["dark", "rgb(233, 235, 239)"]]) {
      const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 }, colorScheme: scheme }); await mock(ctx);
      const p = await ctx.newPage(); await visit(p);
      check(`  ${scheme}: the wordmark is the ink of that scheme`, (await p.$eval(".brand .wordmark", (e) => getComputedStyle(e).backgroundColor)) === ink);
      for (const width of [320, 339, 340, 360, 390, 768, 1280]) {
        await p.setViewportSize({ width, height: 800 });
        const m = await p.evaluate(() => { const r = (s) => document.querySelector(s).getBoundingClientRect(), b = r(".brand .wordmark"), tools = r(".tools"), s = getComputedStyle(document.querySelector(".brand .wordmark"));
          return { over: document.documentElement.scrollWidth - document.documentElement.clientWidth, gap: tools.top < b.bottom && tools.bottom > b.top ? tools.left - b.right : 999, mask: s.maskImage || s.webkitMaskImage, w: b.width }; });
        check(`  ${scheme} ${width}px: no sideways scroll, the ${width < 340 ? "mark alone" : "wordmark"} clear of the buttons`, m.over <= 1 && m.gap >= 12 && (width < 340 ? /brand\/mark\.svg/ : /brand\/wordmark\.svg/).test(m.mask), m);
      }
      await ctx.close();
    }
    check("  Status, Leaderboard, Pilot and Reproduce are offered, hold nothing until one is opened, and none is shown on the first screen", (await page.$$eval("#status, #index, #pilot, #reproduce", (s) => s.map((x) => `${x.id}:${x.className}:${x.childElementCount}:${getComputedStyle(x).display}`))).join() === "status:mount:0:none,index:mount:0:none,pilot:mount:0:none,reproduce:mount:0:none"
      && (await page.$$eval('nav a[data-mount="status"], nav a[data-mount="index"], nav a[data-mount="pilot"], nav a[data-mount="reproduce"]', (a) => a.length === 4 && a.every((x) => !x.hidden))));
    const asked = await page.evaluate(() => performance.getEntriesByType("resource").map((e) => new URL(e.name).pathname.split("/").pop()).filter((f) => f.endsWith(".js")));
    check("  the first screen asks for the front door's code and no other page's: not the files that read Solana, not the console's", ["front.js", "front_door.js", "motion.js"].every((f) => asked.includes(f))
      && !["app.js", "settle.js", "buyer.js", "console.js", "mounts.js", "pricing.js", "records.js", "statements.js", "palette.js"].some((f) => asked.includes(f)), asked);
    check("  and the Status page has asked GitHub for nothing: it reads when it is opened", hub.asked.length === 0, hub.asked);
  }
  check("only the front view is shown", await page.isVisible("#view-check") && await page.isHidden("#view-protect") && await page.isHidden("#view-network"));
  check("the views are in the menu", (await page.$$eval("nav a:not([data-mount])", (a) => a.map((x) => x.getAttribute("href")))).join() === `#check,#demo,#pricing,${DOCS},#records,#check-a-pull-request,#fund,#claim,#protect,#network,#build`);
  // the bar: five links at most a first visitor needs, the rest one press away under "More"
  {
    const bar = () => page.$$eval("#nav a", (l) => l.filter((a) => a.offsetParent !== null && !a.closest("#more-list")).map((a) => a.textContent));
    const under = () => page.$$eval("#more-list a", (l) => l.filter((a) => a.offsetParent !== null).map((a) => a.textContent));
    check("the bar: six links and More, on one line, and nothing of More shown until it is pressed", (await bar()).join() === "Check,Demo,Console,Leaderboard,Pricing,Docs" && (await page.$$eval("#nav > a", (l) => l.length)) === 6 && (await under()).length === 0 && (await page.getAttribute("#more-button", "aria-expanded")) === "false"
      && await page.$$eval("#nav > a, #more-button", (l) => new Set(l.filter((a) => a.offsetParent !== null).map((a) => Math.round(a.getBoundingClientRect().top / 8))).size === 1), await bar());
    await page.click("#more-button");
    check("  More opens the others, inside the window", (await under()).join() === "Story,For suppliers,Supplier records,Hold a key,Verifier,Playground,Terms,Records,Statement,Invoice from a file,Check a pull request,Fund,Get paid,Protect,Install,Numbers,Status,Pilot,Capabilities,Reproduce,Build" && (await page.getAttribute("#more-button", "aria-expanded")) === "true"
      && await page.$eval("#more-list", (e) => { const r = e.getBoundingClientRect(); return r.left >= 0 && r.right <= document.documentElement.clientWidth; }) && (await overflow(page)) <= 1, await under());
    await page.keyboard.press("Escape");
    check("  Escape closes it and gives the button the focus back", (await under()).length === 0 && await page.evaluate(() => document.activeElement.id === "more-button"));
    await page.click("#more-button"); await page.mouse.click(40, 320);
    check("  a press anywhere else closes it", (await under()).length === 0);
    await page.click("#more-button"); await page.click('#more-list a[href="#records"]');
    await page.waitForSelector("#view-records", { state: "visible" });
    check("  a link of it goes to its page, closes the list, and More is marked as holding the page shown", (await under()).length === 0 && await page.$eval("#more", (e) => e.classList.contains("current")) && (await page.getAttribute("nav a[aria-current=page]", "href")) === "#records");
    await visit(page, "#pricing");
    check("  and is not marked on a page of the bar's own", !(await page.$eval("#more", (e) => e.classList.contains("current"))));
    const phone = await (await world({ width: 390 })).newPage();
    await visit(phone, "");
    await phone.click("#menu");
    const shown = () => phone.$$eval("#nav a", (l) => l.filter((a) => a.offsetParent !== null).length);
    check("  a phone: Menu opens the bar's links and More, and never fifteen at once", (await shown()) === 6 && await phone.isVisible("#more-button") && (await overflow(phone)) <= 1, await shown());
    await phone.click("#more-button");
    check("  and More, inside it, opens the rest", (await shown()) === 27 && (await overflow(phone)) <= 1, await shown());
    await phone.close();
    const bare = await (await browser.newContext({ javaScriptEnabled: false, viewport: { width: 1100, height: 900 } })).newPage();
    await bare.goto(base);
    check("  without scripts: the links of the views are all in the bar, More's too, and its button is not shown", (await bare.$$eval("#nav a", (l) => l.filter((a) => a.offsetParent !== null).map((a) => a.getAttribute("href")))).join() === `#check,#demo,#pricing,${DOCS},#records,#check-a-pull-request,#fund,#claim,#protect,#network,#build` && await bare.isHidden("#more-button"));
    await bare.context().close();
    await visit(page);
  }
  // the first screen: two buttons, the flow in three steps with a payment on devnet, the five things one line each
  check("  one control: a box for an invoice or a repository, its button, and a sample", (await page.$$eval("#front-door textarea, #front-door [data-fd]", (l) => l.map((x) => `${x.dataset.fd || x.id} ${x.textContent.trim()}`))).join() === "fd-in ,run Check,sample Try a sample"
    && await page.isVisible("#front-door [data-fd=run]") && await page.isVisible("#front-door [data-fd=sample]"));
  await page.$eval("#what-is-here", (d) => { d.open = true; });
  check("  the flow is three steps, and the last links the payment on devnet that the third example reads", (await page.$$eval("#view-check .how > li", (l) => l.length)) === 3
    && (await page.getAttribute("#view-check .how a[href*=explorer]", "href")) === `https://explorer.solana.com/tx/${(await import(pathToFileURL(join(root, "config.js")).href)).CONFIG.examples.find((e) => e.id === "paid").input}?cluster=devnet`);
  check("  five things to lead with, one line each at a laptop's width", await page.$$eval("#view-check .lead-with > li", (l) => l.length === 5 && l.every((x) => x.getBoundingClientRect().height < 60)));
  await page.waitForSelector("#demo .kd-go");                  // the round is mounted (web/demo.js); a build without it leaves the mount empty, as here
  await page.evaluate(() => { document.getElementById("demo").innerHTML = ""; });
  await page.waitForSelector("#demo", { state: "hidden" });
  await page.click('#nav > a[href="#demo"]');
  check("  Demo, while the demo's mount is empty, puts the cursor in the box that checks a pull request", await page.evaluate(() => document.activeElement.id === "pr-url") && await page.isHidden("#demo"));
  await page.evaluate(() => { document.activeElement.blur(); document.getElementById("demo").innerHTML = "<p>Filled</p>"; });
  await page.waitForSelector("#demo", { state: "visible" });
  check("  the demo's mount, once filled, is shown in the first screen under the front door, and Demo goes to it", await page.isVisible("#view-check") && await page.$eval("#demo", (d) => d.parentElement.id === "view-check" && d.previousElementSibling.classList.contains("hero")));
  await page.click('#nav > a[href="#demo"]');
  check("    and the cursor stays out of the box", await page.evaluate(() => document.activeElement.id !== "pr-url" && location.hash === "#demo"));
  await page.evaluate(() => { document.getElementById("demo").replaceChildren(); });
  await visit(page);
  const settled = async () => {};          // every page's link is in the menu from the start: a page fills when it is opened
  await settled(); await page.click("#more-button"); await page.click("#go-check");
  check("  Check a pull request, under More, puts the cursor in the box", await page.evaluate(() => document.activeElement.id === "pr-url"));
  // the pages other modules fill: not offered while empty, shown alone at their hash once they hold something
  check("the pages other modules fill are there, and an empty one is not in the menu", (await page.$$eval("nav a[data-mount]", (a) => a.map((x) => x.getAttribute("href")))).join() === "#buy,#index,#story,#supplier,#record,#keyholder,#verifier,#playground,#terms,#invoice-statement,#shadow,#install,#status,#pilot,#capabilities,#reproduce"
    && await page.$$eval("nav a[data-mount]", (a) => a.every((x) => !x.hidden)));
  // every row of the leaderboard links to that supplier's public record (web/supplier_record.js, mounted at #record=<slug>;
  // the build copies docs/records/*.json to records/), and "Supplier records" under More opens the list of them
  await visit(page, "#index"); await page.waitForSelector("#index .index-board tbody tr a.ib-record");
  const recordLinks = await page.$$eval("#index .index-board tbody tr", (tr) => tr.map((r) => [r.dataset.agent, r.querySelector("a.ib-record").getAttribute("href")]));
  check("leaderboard: every row links to its supplier's record, and the build holds each record's file", recordLinks.length >= 4 && recordLinks.every(([agent, href]) => href === `#record=${agent}` && existsSync(join(root, "records", `${agent}.json`))), JSON.stringify(recordLinks));
  await page.click("#index .index-board tbody tr a.ib-record");
  await page.waitForSelector("#record .supplier-record[data-supplier]");
  check("  a press opens the record page: the supplier's name, the rule that it cannot be bought, its dispute link", (await page.evaluate(() => document.body.dataset.page)) === "record"
    && (await text(page, "#record h2")) === `Public record of ${JSON.parse(readFileSync(join(root, "records", `${recordLinks[0][0]}.json`), "utf8")).name}` && (await text(page, '#record [data-sr="rule"]')) === "This record cannot be bought."
    && /^https:\/\/github\.com\/drexthealpha\/Knos\/issues\/new/.test(await page.getAttribute('#record [data-sr="dispute"]', "href")) && await page.isVisible("#record .supplier-record"), await text(page, "#record h2"));
  await visit(page, "#record"); await page.waitForSelector('#record [data-sr="pick"] a');
  check("  Supplier records, with no supplier named, lists every record to pick from", (await page.$$eval('#record [data-sr="pick"] a', (l) => l.map((a) => a.getAttribute("href")))).join() === recordLinks.map((r) => r[1]).join());
  await visit(page, "#capabilities"); await page.waitForSelector("#cap-manifest", { state: "attached" });
  check("capabilities: one link opens what is live, in one page (docs/MANIFEST.md)", (await page.getAttribute("#cap-manifest", "href")) === "https://github.com/drexthealpha/Knos/blob/main/docs/MANIFEST.md" && (await text(page, "#cap-manifest")) === "What is live, in one page"
    && existsSync(join(here, "../../docs/MANIFEST.md")));
  for (const id of ["buy", "install", "capabilities"]) {
    await visit(page, `#${id}`);
    if (id === "capabilities") await page.waitForSelector("#capabilities table", { state: "attached" });      // filled from capabilities.json, once it has loaded
    if (id === "buy" && existsSync(join(here, "..", "..", "web", "buyer.js"))) await page.waitForSelector("#buy-step-1", { state: "attached" });      // filled by web/buyer.js, once it has loaded
    const had = await page.evaluate((i) => document.getElementById(i).childElementCount > 0, id);
    if (!had) check(`  #${id} while empty shows the first screen`, await page.isVisible("#view-check") && await page.isHidden(`#${id}`));
    await page.evaluate((i) => { if (!document.getElementById(i).childElementCount) document.getElementById(i).innerHTML = "<h2>Filled</h2>"; }, id);
    await page.waitForSelector(`#${id}`, { state: "visible" });
    check(`  #${id} once filled is shown alone, with its link in the menu`, await page.isHidden("#view-check") && !(await page.$eval(`nav a[href="#${id}"]`, (a) => a.hidden)) && (await page.getAttribute("nav a[aria-current=page]", "href")) === `#${id}`
      && (await page.$eval("#more", (e) => e.classList.contains("current"))) === (id !== "buy"));
  }
  // what fills them in this build: Install is in the page, Capabilities is the manifest the build copied, Buy is web/buyer.js when there is one
  await visit(page, "");
  await settled(); await page.click("#more-button"); await page.click('#more-list a[href="#install"]');
  await page.waitForSelector("#install-repo", { state: "visible" });
  check("install: Install, under More, lands on the Install page, shown alone, with the box to write a repository in", await page.isVisible("#install") && await page.isHidden("#view-check") && (await page.evaluate(() => document.body.dataset.page)) === "install"
    && (await page.getAttribute("nav a[aria-current=page]", "href")) === "#install" && (await text(page, "#install h2")) === "Install by one pull request");
  await page.fill("#install-repo", "octo/widgets");
  check("  a repository gives the link that opens GitHub's editor there, and the five terms templates are under it", (await page.getAttribute("#install-open", "href")).startsWith("https://github.com/octo/widgets/new/main?filename=.github%2Fworkflows%2Fknos.yml&value=")
    && (await page.$$eval("#install-terms .card", (c) => c.length)) === 5);
  const manifest = JSON.parse(readFileSync(join(root, "capabilities.json"), "utf8"));
  check("capabilities: the build carries the manifest of docs/, byte for byte", readFileSync(join(root, "capabilities.json"), "utf8") === readFileSync(join(here, "..", "..", "docs", "capabilities.json"), "utf8"));
  await visit(page, "#capabilities");
  await page.waitForSelector("#capabilities table.capabilities", { state: "visible" });
  check("capabilities: the page opens on what was exercised on devnet, not on every row", (await page.inputValue("#capabilities .capabilities-stage")) === "exercised" && (await page.$$eval("#capabilities table.capabilities tr[data-stage]", (tr) => tr.every((r) => r.dataset.stage === "exercised") && tr.length)) === manifest.capabilities.filter((c) => c.stage === "exercised").length);
  await page.selectOption("#capabilities .capabilities-stage", "all");
  const capRows = () => page.$$eval("#capabilities table.capabilities tr[data-stage]", (tr) => tr.map((r) => [r.dataset.stage, r.children[0].textContent, r.children[1].textContent]));
  check("capabilities: one row per capability of the manifest, each at its stage, shown alone with its link in the menu", JSON.stringify(await capRows()) === JSON.stringify(manifest.capabilities.map((c) => [c.stage || "none", c.what,
    { none: "not built", implemented: "implemented", tested: "tested locally", deployed: "deployed on devnet", exercised: "exercised on devnet", reproduced: "reproduced by someone else" }[c.stage || "none"]]))
    && await page.isHidden("#view-check") && (await page.getAttribute("nav a[aria-current=page]", "href")) === "#capabilities", JSON.stringify((await capRows()).length));
  await page.selectOption("#capabilities .capabilities-stage", "deployed");
  check("  the filter shows one stage: exactly it, not at least it", JSON.stringify((await capRows()).map((r) => r[1])) === JSON.stringify(manifest.capabilities.filter((c) => c.stage === "deployed").map((c) => c.what)));
  const built014 = ["meter_batch", "meter_seller_claim", "passkey_funder", "gitlab_pay", "single_use_tokens", "fee_tiers", "hermetic_judge", "evidence_bundle", "receipt_mirror", "audit_export", "install_by_pull_request", "terms_templates",
    "badge", "agent_weekly_rates", "x402_knos_order", "upgrade_feed", "load_local_1000", "adapters"];
  // what the release's rehearsal ran on devnet ran on staging programs of its own, never on a public one: it is tested, and
  // its note gives the transaction and says it was a staging rehearsal; the rest is tested with no devnet run at all
  const rehearsed014 = ["meter_batch", "meter_seller_claim", "passkey_funder", "single_use_tokens", "fee_tiers", "x402_knos_order"];
  // ... unless a round at the public ids exercised it since: then its transaction is a public one, and the note keeps the
  // rehearsal as what came before
  const asRound = (c) => c.stage === "exercised" && c.evidence.exercised && (c.evidence.exercised.ids || "public") === "public" && !!c.evidence.deployed
    && (!rehearsed014.includes(c.id) || (/rehearsed on a staging deployment/.test(c.note || "") && /the transaction here is at the public program id/.test(c.note || "")));
  const as014 = (c) => asRound(c) || (c.stage === "tested" && !c.evidence.deployed && !c.evidence.exercised && (rehearsed014.includes(c.id)
    ? c.note.startsWith("Rehearsed on ") && c.note.includes("staging deployment") && c.note.includes("not on the public program ids") && /[1-9A-HJ-NP-Za-km-z]{86,88}/.test(c.note)
    : !/^Rehearsed on /.test(c.note || "")));
  check("  what 0.3.14 built is in it, each tested or exercised at the public ids, the rehearsed ones with their staging transaction in the note, none on a staging id",
    built014.every((id) => { const c = manifest.capabilities.find((x) => x.id === id); return c && as014(c); }),
    built014.filter((id) => { const c = manifest.capabilities.find((x) => x.id === id); return !c || !as014(c); }));
  // the release's rule: nothing is deployed or exercised on a program that is not a public id, at the version devnet runs there
  const pinnedIds = JSON.parse(readFileSync(join(here, "..", "..", "programs-v2", "program_ids.json"), "utf8"));
  const publicIds = { ...Object.fromEntries(Object.entries(pinnedIds).filter(([n]) => n.startsWith("knos_"))),
    upgrade_gate: /declare_id!\("([1-9A-HJ-NP-Za-km-z]{32,44})"\)/.exec(readFileSync(join(here, "..", "..", "examples", "upgrade_gate", "src", "lib.rs"), "utf8"))[1] };
  const onPublic = (c) => {
    const d = c.evidence.deployed, p = d && manifest.programs[d.program];
    return !!p && publicIds[d.program] === d.id && p.id === d.id && p.versions.indexOf(d.version) >= 0 && p.versions.indexOf(d.version) <= p.versions.indexOf(p.on_chain);
  };
  const offPublic = manifest.capabilities.filter((c) => ["deployed", "exercised", "reproduced"].includes(c.stage) && !onPublic(c)).map((c) => c.id);
  check("  no capability is deployed or exercised on a program that is not a public id, and the manifest lists no other program",
    offPublic.length === 0 && Object.entries(manifest.programs).every(([n, p]) => publicIds[n] === p.id) && !Object.keys(manifest.programs).some((n) => n.endsWith("_staging"))
    && manifest.capabilities.filter((c) => c.stage === "deployed").length > 0 && !(await page.textContent("#capabilities")).includes("_staging"), offPublic);
  const buyer = readFileSync(join(root, "buyer.js"), "utf8");
  await visit(page, "#buy");
  await page.waitForTimeout(300);
  // the build copies web/buyer.js itself (the file that fills nothing is written only for a build with none), and the page's own
  // hook (web/app.js) renders it with the page's environment: the four steps and the templates, not a filled-in placeholder
  const ours = join(here, "..", "..", "web", "buyer.js");
  check("buy: the build carries web/buyer.js byte for byte", existsSync(ours) && buyer === readFileSync(ours, "utf8") && /export function renderBuyer\(/.test(buyer));
  await page.waitForSelector("#buy-sentence:not(:empty)", { state: "attached", timeout: 10000 }).catch(() => {});
  check("  the page's own hook renders it: its four parts, its steps (three under Offers), its templates and its one sentence, shown alone with its link in the menu",
    (await page.$$eval("#buy [role=tab]", (t) => t.map((x) => x.textContent))).join() === "Offers,Budgets,Approvals,Invoice" && !!(await page.$("#buy-part-invoice #buy-step-4"))
    && (await Promise.all([1, 2, 3].map((n) => page.isVisible(`#buy-step-${n}`)))).every(Boolean) && (await page.$$eval("#buy-template option", (o) => o.map((x) => x.value))).join() === "bugfix,feature-blackbox,milestone,private-attested"
    && (await text(page, "#buy-sentence")).length > 20 && await page.isVisible('nav a[href="#buy"]') && await page.isHidden("#view-check")
    && (await page.getAttribute("nav a[aria-current=page]", "href")) === "#buy" && !(await page.$("#buy > h2:only-child")),
    await page.evaluate(() => document.getElementById("buy").innerHTML.slice(0, 200)));
  await visit(page, "#pricing");
  check("  and leaving one shows the view asked for", await page.isVisible("#view-pricing") && await page.isHidden("#buy") && (await page.getAttribute("nav a[aria-current=page]", "href")) === "#pricing");
  for (const [hash, view] of [["protect", "protect"], ["fund", "fund"], ["claim", "claim"], ["pricing", "pricing"], ["records", "records"], ["u=alice", "records"], ["r=octo/widgets", "records"], ["rank=earners", "records"], ["network", "network"], ["build", "build"], ["bounty", "fund"], ["money", "fund"], ["numbers", "network"], ["nothing", "check"]]) {
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

// ---- what the first form counts as a claim: the words of scripts/agent_pr_ci.py and `knos check` ----------------------------
{
  const { findClaim } = await import(pathToFileURL(join(root, "front.js")).href);
  const said = (body) => findClaim(body)?.phrase ?? null;
  const boxes = ["- [ ] All tests pass", "* [ ] CI is green", "+ [ ] 801 passed", "1. [ ] tests pass", "2) [ ] all checks pass",
    "> - [ ] tests pass", "  1. - [ ] tests pass"];
  check("claims: an unticked box of any list marker claims nothing, and the same box ticked is a claim",
    boxes.every((b) => said(b) === null && said(b.replace("[ ]", "[x]")) !== null), boxes.map((b) => [b, said(b), said(b.replace("[ ]", "[x]"))]));
  const hedged = ["All tests should pass.", "Please make sure CI is green.", "TODO: make tests pass", "Tests must pass before merging.",
    "The tests do not pass.", "Tests don't pass yet."];
  check("  a hedged, negated or instructional sentence claims nothing", hedged.every((b) => said(b) === null), hedged.map(said));
  check("  the false example's ticked box is a claim", said("- [x] My PR passes all CI/CD checks (e.g., lint, format, unit tests)") === "passes all CI");
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
  check("  the simulation came first, the wallet second", chain.calls.filter((c) => !c.version).map((c) => c.method).filter((m) => m === "simulateTransaction" || m === "wallet:signAndSend").join() === "simulateTransaction,wallet:signAndSend");
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
  check("escrow: the amount, the fee when paid and the state", got.includes("20.00 test USDC") && got.includes("fee when paid: 0.06")
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
    && got.includes("First authenticate GitHub CLI as mona with gh auth login, then send it to an address you choose with knos claim --v1 <address>")
    && (await page.$("#due-v1")) !== null, got);
  const record = await page.$$eval("#due-record dd", (d) => d.map((x) => x.textContent.replace(/\s+/g, " ").trim()));
  check("  its record: payments, funders, total and the dates", record[0] === "3 payments from 2 different funders, 58.50 test USDC in all (" + when(NOW - 30 * 86400) + " to " + when(NOW - 86400) + ")", record);
  check("  faucet money and paying oneself counted apart, never added in", record[1] === "1 payment, 24.38 of the faucet's free test USDC. Counted apart."
    && record[2] === "1 payment, where the funder was the person paid. Counted apart." && got.includes("never added together"));
  check("  the GitHub account's id and that it is all test USDC", got.includes("GitHub account id 4242") && got.includes("All of it is test USDC on devnet"));
  got = await account("quiet");
  check("account: nothing bound, nothing held, nothing paid, said as such", got.includes("No wallet is bound for quiet.") && got.includes("Nothing is held for quiet right now.")
    && got.includes("0 payments from 0 different funders, 0.00 test USDC in all"), got);
  check("  no first-deployment section is added when that account has no due", (await page.$("#due-v1")) === null, got);
  const quietDue = await first.due(5, USDC);
  put(quietDue, dueBytes({ amount: 5_000_000, userId: 5, mint: USDC }), FIRST.pay);
  got = await account("quiet");
  check("account: a first-deployment due with nothing held on the second never says nothing is held", !got.includes("Nothing is held for quiet right now.")
    && got.includes("Nothing is held for quiet on the second deployment.") && got.includes("5.00 test USDC is still held for quiet on the first deployment."), got);
  chain.accounts.delete(quietDue);
  chain.downFor = { program: FIRST.pay, message: "Too many requests for a specific RPC call" };
  got = await account("mona");
  check("account: a first deployment that cannot be read still shows the wallet, the second deployment's holds and the record",
    got.includes("Paid at " + OTHER_WALLET) && got.includes("12.00 test USDC is held for mona until " + when(NOW + 100 * 86400) + ".")
    && got.includes("3 payments from 2 different funders") && (await page.$("#due-v1")) === null, got);
  check("  and says the first deployment could not be read, and why", got.includes("Could not read the first deployment just now (Too many requests for a specific RPC call)"), got);
  got = await account("quiet");
  check("  with nothing held on the second, it does not say nothing is held at all", !got.includes("right now") && got.includes("Nothing is held for quiet on the second deployment.")
    && got.includes("Could not read the first deployment just now"), got);
  chain.downFor = null;
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
    steps.includes("Actions") && steps.includes("knos claim") && steps.includes("Run workflow") && steps.includes("paste your Solana address yourself"), steps);
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
  await page.waitForSelector(`#first-deployment button.copy[data-copy="${FIRST.pay}"]`);
  check("  every address is shown whole, may break anywhere, and has a button that copies it; the button adds no word to the page's text", await page.$$eval("#view-network .mono", (els) => els.filter((e) => /^[1-9A-HJ-NP-Za-km-z]{32,44}$/.test(e.textContent.trim())).every((e) =>
    (e.closest("a") || e).nextElementSibling?.matches(`button.copy[data-copy="${e.textContent.trim()}"]`) && ["anywhere", "break-word"].includes(getComputedStyle(e).overflowWrap) || getComputedStyle(e).wordBreak === "break-all"))
    && (await page.$$eval("#view-network button.copy", (b) => b.length > 3 && b.every((x) => x.textContent === "" && getComputedStyle(x, "::before").content === '"Copy"'))));
  check("  the plan is stated in the words the project uses, as a plan", (await text(page, "#network-programs")).includes("The plan: upgradeable only through a multisig with a public 48-hour delay, until an outside review.") && !/immutable/i.test(await text(page, "#view-network")));
  check("  the explorer links are for devnet", (await page.$$eval("#network-programs a", (a) => a.every((x) => x.getAttribute("href").endsWith("?cluster=devnet")))));

  for (const [what, setup, expected, words, absent = []] of [
    ["upgradeable only by the upgrade multisig's vault, 2 of 3, 48 hours", { oidc: "vault", pay: "vault", up: { threshold: 2, timeLock: 172800 }, guard: { threshold: 2, timeLock: 0 } }, ["multisig", "multisig"],
      ["2 of 3 members must approve, and an approved upgrade waits 48 hours before it can run.", "2 of 3 members must approve; no delay. The guardian can approve or revoke a signing key and pause new funding for at most 7 days."], ["not the 48 hours"]],
    ["a delay that is not the 48 hours said", { oidc: "vault", pay: "vault", up: { threshold: 2, timeLock: 3600 }, guard: { threshold: 1, timeLock: 0 } }, ["multisig", "multisig"], ["waits 1 hour before it can run", "(not the 48 hours stated above)"]],
    ["a program that someone else can upgrade", { oidc: stranger, pay: "vault", up: { threshold: 2, timeLock: 172800 }, guard: { threshold: 2, timeLock: 0 } }, ["other", "multisig"],
      [`upgradeable by ${stranger}, which is not the upgrade multisig of this deployment`]],
    ["a second deployment with no upgrade authority at all", { oidc: null, pay: null, up: { threshold: 2, timeLock: 172800 }, guard: { threshold: 2, timeLock: 0 } }, ["no-authority", "no-authority"], ["no upgrade authority is set on chain", "not the plan stated above"]],
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
  check("numbers: when Solana cannot be read, each card says so and never says 'not on devnet yet'", (await text(page, "#network-programs")).includes("Devnet did not answer (Node is behind by 100 slots)")
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
  await page.waitForSelector("#demo .kd-go");
  // every page is opened once, so that every page's links are in the document (a page's code arrives when it is first opened)
  const PAGES_ALL = ["buy", "install", "capabilities", "status", "index", "pilot", "reproduce", "shadow", "verifier", "playground", "terms", "supplier", "invoice-statement", "story", "keyholder", "record", "protect", "fund", "claim", "pricing", "records", "network", "build"];
  for (const name of PAGES_ALL) { await page.evaluate((h) => { location.hash = h; }, `#${name}`); await page.waitForFunction((n) => document.documentElement.dataset.ready === n, name); }
  await page.waitForSelector("#verifier a", { state: "attached" }); await page.waitForSelector("#terms-list .k-card", { state: "attached" }); await page.waitForSelector("#proc-approvals a", { state: "attached" });
  const hrefs = await page.$$eval("a[href]", (a) => a.map((x) => x.getAttribute("href")));
  const issuerDocs = (await import(pathToFileURL(join(root, "verifier.js")).href)).ISSUERS.map((i) => i.source);
  // the Console's sample approvals name where each was made: a comment in this project's own playground repository, never an account that is somebody else's
  check("links: the Console's sample is in the project's own playground repository", hrefs.some((h) => /^https:\/\/github\.com\/drexthealpha\/knos-playground\/issues\/\d+#issuecomment-\d+$/.test(h)) && !(await page.content()).includes("github.com/acme/"));
  const bad = hrefs.filter((h) => !(h.startsWith("#") ? ["check", "fd-in", "check-a-pull-request", "protect", "fund", "claim", "pricing", "records", "network", "build", "rank", "buy", "install", "capabilities", "status", "index", "pilot", "reproduce", "demo", "shadow", "verifier", "playground", "terms", "supplier", "invoice-statement", "story", "keyholder", "sample", "record"].includes(h.slice(1).split("=")[0])
    : h === TEMPLATE_LINK || h === "https://drexthealpha.github.io/Knos/" || /^https:\/\/explorer\.solana\.com\/(tx\/[1-9A-HJ-NP-Za-km-z]{64,90}|address\/[1-9A-HJ-NP-Za-km-z]{32,44})\?cluster=devnet$/.test(h) || /^https:\/\/github\.com\/drexthealpha\/|^https:\/\/faucet\.circle\.com\/$|^(index|stats|operations|agent_weekly|records)\.json$|^terms\/(?:3\/)?[\w-]+\/\d+\.json$/.test(h) || issuerDocs.includes(h)));
  check("links: every link goes to a view, to the site's own address, to the project's own GitHub, to a transaction or an address on devnet's explorer, to Circle's devnet faucet, to a file of the site or to an issuer's own documentation (the verifier's table)", bad.length === 0, bad);
  check("  a link that opens a new tab does not hand over the page", await page.$$eval('a[target="_blank"]', (a) => a.every((x) => /noopener/.test(x.rel))));
  await page.close();
  hub.playgroundAsked = 0; hub.asked.length = 0;          // this block opened every page, the playground's and Status among them
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
  const phone = await world({ wallets: [["Test Wallet", WALLET]], width: 360, passkeys: true });
  const page = await phone.newPage();
  const WIDTHS = [320, 390, 768, 1280, 360];            // every width the page must hold; 360 last, the one the rest of this block runs at
  const wide = async (what) => {
    for (const width of WIDTHS) {
      await page.setViewportSize({ width, height: 900 });
      const { over, culprits } = await page.evaluate(() => ({ over: document.documentElement.scrollWidth - document.documentElement.clientWidth,
        culprits: [...document.querySelectorAll("body *")].filter((e) => e.offsetParent !== null && (e.getBoundingClientRect().right > document.documentElement.clientWidth + 1
          || (e.scrollWidth > e.clientWidth + 1 && getComputedStyle(e).overflowX === "visible"))).slice(0, 4)
          .map((e) => `<${e.tagName.toLowerCase()}${e.id ? ` id=${e.id}` : ""}${e.className ? ` class=${e.className}` : ""}> ${e.textContent.trim().slice(0, 40)}`) }));
      check(`${width}px: ${what}: nothing runs off the side`, over <= 1, over > 1 ? [over, ...culprits] : "");
    }
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
  await page.click("#pk-create"); await page.waitForSelector("#pk-address:not(:empty)");
  const mine = await text(page, "#pk-address");
  put(await passkey.ata(mine, USDC), tokenBytes({ mint: USDC, owner: mine, amount: 12_500_000 }), knos.TOKEN);
  await page.click("#pk-refresh"); await page.waitForFunction(() => document.getElementById("pk-held")?.textContent.includes("12.50"));
  await page.fill("#pk-amount", "5"); await page.fill("#pk-dest", WALLET); await page.fill("#pk-login", "a-login-of-the-longest-length-github-allows"); await page.click("#pk-sign");
  await page.waitForSelector("#pk-request .status.bad");
  await page.fill("#pk-login", "octocat-with-a-long-name-of-39-chars-aa"); await page.click("#pk-sign");
  await page.waitForSelector("#pk-comment");
  await openAll();
  await wide("get paid, with a passkey wallet, a signed withdrawal and the details open");
  await visit(page, "#network");
  await page.waitForSelector("#programs-now"); await page.waitForSelector("#keys-table"); await page.waitForSelector("#network-recent");
  await wide("numbers, with the keys and the programs");
  await visit(page, "#build");
  await wide("build on it");
  await page.close();
  served.front = (code) => code;
}

// ---- 1. the first screen: the recording, three examples that need one click ---------------------------------------------------------
{
  const agentPrs = JSON.parse(readFileSync(join(here, "../../docs/agent_pr_ci.json"), "utf8")).prs;
  const page = await plain.newPage();
  served.front = stamp(COMMIT);
  await visit(page);
  check("first screen: with no recording in the config the page shows no video and no empty box", await page.isHidden("#film") && await page.$eval("#demo-video", (v) => !v.getAttribute("src")));
  const cfg = await page.evaluate(async () => (await import("/config.js")).CONFIG);
  check("first screen: three example buttons, a true claim, a false claim and a paid task", (await page.$$eval("#examples button", (b) => b.map((x) => x.dataset.example))).join() === "true,false,paid" && cfg.examples.length === 3);

  // where the examples come from: the Index's own list of pull requests, and the recorded transaction
  const asked = (input) => { const m = /github\.com\/([^/]+\/[^/]+)\/pull\/(\d+)/.exec(input); return agentPrs.find((p) => p.repo === m[1] && p.number === Number(m[2])); };
  const [yes, no, paid] = cfg.examples;
  check("  the true example is a pull request of docs/agent_pr_ci.json whose checks passed, and the false one has a failed check", asked(yes.input)?.class === "passed" && asked(no.input)?.class === "failed" && asked(no.input).failed_checks.length > 0);
  const paidTx = firstDeployment.find((t) => t.signature === paid.input);
  check("  the paid example is a transaction of the recorded first deployment, with the escrow's paid line", !!paidTx && paidTx.meta.err === null && paidTx.meta.logMessages.some((l) => /^Program log: knos:paid /.test(l)));
  check("  the recorded pull requests are the ones the page is shown, with what the index says", examplePrs.every((e) => { const x = asked(`https://github.com/${e.repo}/pull/${e.number}`); return x && x.sha === e.sha && x.claim_line === e.claim_line && x.class === e.class; }));

  // one click, a result
  githubReads = 0;
  await page.click('[data-example="true"]');
  await page.waitForSelector("#verdict");
  check("a click on the true example fills the form and answers: claim true", (await page.inputValue("#pr-url")) === yes.input && (await page.getAttribute("#verdict", "data-verdict")) === "claim true" && (await text(page, "#example-says")) === yes.says, await text(page, "#pr-result"));
  await page.click('[data-example="false"]');
  await page.waitForFunction(() => document.getElementById("verdict")?.dataset.verdict === "claim FALSE");
  check("  the false example answers: claim FALSE, with the check that failed", (await text(page, "#pr-result")).includes(asked(no.input).failed_checks[0]) && (await page.inputValue("#pr-url")) === no.input);
  await page.click('[data-example="paid"]');
  await page.waitForFunction(() => document.getElementById("verdict")?.dataset.verdict === "paid");
  const paidText = await text(page, "#pr-result");
  check("  the paid example answers from the transaction: amount, task, payee, fee, link to devnet", paidText.includes("Paid: 9.75 test USDC") && paidText.includes("issue #17 of octo/recorded") && paidText.includes("GitHub user 142920951")
    && paidText.includes("0.25 test USDC") && paidText.includes("first deployment") && (await page.getAttribute('#pr-result a[href*="explorer.solana.com"]', "href")) === `https://explorer.solana.com/tx/${paid.input}?cluster=devnet`, paidText);
  check("  and says the money is test USDC and where the line was read", paidText.includes("test USDC: devnet money is worth nothing") && paidText.includes("escrow's own log line"));

  // the same by hand: a link to the transaction, a transaction that paid nothing, one devnet does not have, another cluster
  await page.fill("#pr-url", `https://explorer.solana.com/tx/${paid.input}?cluster=devnet`);
  await page.click("#pr-check");
  await page.waitForFunction(() => document.getElementById("verdict")?.dataset.verdict === "paid");
  const other = firstDeployment.find((t) => !t.meta.logMessages.some((l) => /knos:paid/.test(l)) && t.meta.err === null);
  await page.fill("#pr-url", other.signature);
  await page.click("#pr-check");
  await page.waitForFunction(() => document.getElementById("verdict")?.dataset.verdict === "not a payment");
  check("a transaction with no payment in it says so", (await text(page, "#pr-result")).includes("no payment line from either escrow program"));
  await page.fill("#pr-url", relayed.signature);
  await page.click("#pr-check");
  await page.waitForFunction(() => document.getElementById("verdict")?.dataset.verdict === "paid" || document.querySelector("#pr-result .status.bad"));
  const relayedText = await text(page, "#pr-result");
  check("a payment a relay carried is a version 1 transaction, and the page reads it", relayedText.includes("Paid: 19.50 test USDC") && relayedText.includes("issue #31 of repository 777000111, pull request #9")
    && relayedText.includes("0.50 test USDC") && relayedText.includes("second deployment"), relayedText);
  check("  every transaction is asked for with version 1", called("getTransaction").length >= 4 && called("getTransaction").every((c) => c.params[1]?.maxSupportedTransactionVersion === 1),
    JSON.stringify(called("getTransaction").map((c) => c.params[1])));
  await page.fill("#pr-url", "5".repeat(88));
  await page.click("#pr-check");
  await page.waitForSelector("#pr-result .status.bad");
  check("a signature devnet does not know is a sentence", (await text(page, "#pr-result")).includes("Devnet has no transaction with that signature"));
  const asks = called("getTransaction").length;
  chain.genesis = MAINNET;
  await page.fill("#pr-url", paid.input);
  await page.click("#pr-check");
  await page.waitForFunction(() => document.querySelector("#pr-result .status.bad")?.textContent.includes("not devnet"));
  check("a cluster that is not devnet is refused before the transaction is asked for", called("getTransaction").length === asks, [asks, called("getTransaction").length]);
  chain.genesis = DEVNET;
  const lines = await page.evaluate(async () => {
    const m = await import("/first.js");
    const log = (...l) => ({ meta: { logMessages: l } });
    return { other: m.paidLines(log("Program Other111 invoke [1]", "Program log: knos:paid repo=1 issue=2 author=3 amount=4 fee=5", "Program Other111 success"), { Pay111: 1 }),
      nested: m.paidLines(log("Program Other111 invoke [1]", "Program Pay111 invoke [2]", "Program log: knos2:paid repo=1 issue=2 author=3 amount=4 fee=5 to=W pr=9", "Program Pay111 success", "Program Other111 success"), { Pay111: 2 }),
      wrong: m.paidLines(log("Program Pay111 invoke [1]", "Program log: knos2:paid repo=1 issue=2 author=3 amount=4 fee=5", "Program Pay111 success"), { Pay111: 1 }) };
  });
  check("only a line the escrow itself printed counts: not another program's, and not the other deployment's prefix", lines.other.length === 0 && lines.wrong.length === 0
    && JSON.stringify(lines.nested) === JSON.stringify([{ deployment: 2, repo: "1", issue: "2", payee: "3", amount: 4, fee: 5, to: "W", pr: "9" }]), JSON.stringify(lines));
  await page.close();

  // the recording: a release asset the config names, hidden when it is absent or the config is not a plain address
  const webm = readFileSync(join(here, "recorded", "blank.webm"));
  served.extra["/demo.webm"] = { type: "video/webm", body: webm };
  served.extra["/poster.svg"] = { type: "image/svg+xml", body: "<svg xmlns='http://www.w3.org/2000/svg' width='4' height='4'/>" };
  const withVideo = async (video) => { served.config = (t) => t.replace("video: null,", `video: ${video},`); const p = await plain.newPage(); await visit(p); return p; };
  let v = await withVideo('{ src: "/demo.webm", poster: "/poster.svg" }');
  await v.waitForSelector("#film:not([hidden])");
  check("recording: a file the config names is shown, with its poster, once the browser has it", (await v.$eval("#demo-video", (e) => e.getAttribute("src") + " " + e.getAttribute("poster"))) === "/demo.webm /poster.svg");
  await v.close();
  v = await withVideo('{ src: "/missing.webm" }');
  await v.waitForFunction(() => document.getElementById("demo-video").error !== null);
  check("  a file that is not there leaves no video on the page", await v.isHidden("#film"));
  await v.close();
  v = await withVideo('{ src: "javascript:alert(1)" }');
  check("  an address that is not a plain https or relative one is not used", await v.isHidden("#film") && await v.$eval("#demo-video", (e) => !e.getAttribute("src")));
  await v.close();
  served.config = (t) => t;
  served.front = (code) => code;
}

// ---- 2. pricing: the price book and two calculators on the programs' own constants -------------------------------------------------
{
  const rust = (file) => Object.fromEntries([...readFileSync(join(here, "../..", file), "utf8").matchAll(/^pub const (\w+): u(?:64|16|32|8|size) = ([\d_]+);/gm)].map((m) => [m[1], Number(m[2].replace(/_/g, ""))]));
  const pay = rust("programs-v2/knos_pay/src/lib.rs"), meter = rust("programs-v2/knos_meter/src/lib.rs");
  const page = await plain.newPage();
  // every fee on the page is the fee of the build that is LIVE (web/fee_live.js asks the program's Version): first with
  // knos_pay 2.2 answering, where the page is this tree's price book; further down with 2.1, the 0.3.14 tiers
  const liveAs = async (version, release) => { chain.simulate = { err: null, logs: [`Program log: knos2:version ${version}`] }; await visit(page, "#pricing");
    await page.waitForFunction((r) => document.getElementById("calc-settle").dataset.fee === r && document.getElementById("bill-live").dataset.fee === r, release); };
  const before = chain.simulate;
  await liveAs(2, "0.3.18");
  check("pricing: with knos_pay 2.2 live the calculator says the fee charged today, from the program, and no line about an upgrade", JSON.stringify(await page.$$eval("#bill-live dt, #bill-live dd", (l) => l.map((e) => e.textContent)))
    === JSON.stringify(["Fee on devnet today", "0.30% of the amount, at least 0.05"]) && (await page.getAttribute("#bill-live", "data-source")) === "chain" && await gone(page, "#calc-next"));
  const c = await page.evaluate(async () => (await import("/price.js")).priceConstants());
  check("pricing: every constant of the fee the page uses is knos_pay's own, by name; the three METER_* are knos_meter's on devnet", c.feeBps === pay.FEE_BPS && c.feeMin === pay.FEE_MIN && c.tiered === false && !("feeMax" in c) && c.minAmount === pay.ORDER_MIN_AMOUNT
    && c.maxAmount === pay.MAX_AMOUNT && c.tip === pay.TIP && c.tipFirst === pay.TIP_FIRST && c.planBpsMin === pay.PLAN_BPS_MIN && c.fee.release === "0.3.18" && c.fee.build === "2.2"
    && c.meterFee === meter.FEE && c.meterPlanMin === meter.PLAN_MIN && c.meterFree === meter.FREE_PER_MONTH, JSON.stringify([c, pay, meter]));
  check("  and says where each came from: exported by sdk/settle, or recorded in price.js", Object.values(c.source).every((x) => x === "exported" || x === "recorded") && Object.keys(c.source).length === 14, JSON.stringify(c.source));
  const book = await page.$$eval("#price-book tbody tr", (tr) => tr.map((r) => [...r.children].map((x) => x.textContent.replace(/\s+/g, " ").trim())));
  const vectors = JSON.parse(readFileSync(join(here, "../data/billing_vectors.json"), "utf8"));
  check("pricing: the price book is the six lines of Price book 3 (tests/data/billing_vectors.json), five columns, in its words", JSON.stringify(book.map((r, n) => (n === 2 ? r.slice(0, 4) : r))) === JSON.stringify(vectors.lines.map((r, n) => (n === 2 ? r.slice(0, 4) : r))) && book[2][4] === await page.evaluate(async (k) => (await import("/price.js")).enforcedNow({ ...k, fee: { ...k.fee, live: true } }), c)
    && book[2][4] === vectors.lines[2][4] && book.length === 6 && book.every((r) => r.length === 5)
    && JSON.stringify(book.map((r) => r[0])) === JSON.stringify(["Check", "Meter", "Acceptance", "Record", "Control", "Pilot"]) && book[2][2] === vectors.lines[2][2] && book[2][2].startsWith("0.30%; by contract 0.20% on monthly value above 1M (the rate never goes below 0.20%") && !/0\.10% above|10M/.test(JSON.stringify(book))
    && book[1][2] === "100,000 a month free per organisation, then 0.002 USD" && JSON.stringify(await page.$$eval("#price-book thead th", (th) => th.map((x) => x.textContent))) === JSON.stringify(vectors.columns), JSON.stringify(book));
  check("  under it: the relayer's tip, and an order's bounds on devnet with a build for real money setting its own cap", (await text(page, "#price-tip")).replace(/\s+/g, " ").trim()
    === "Relayer tip: 0.05, or 0.30 on a payee's first payment, out of the fee. An order holds from 5 to 100,000 test USDC on devnet; a build for real money sets its own cap." && c.minAmount === 5e6 && c.maxAmount === 100_000e6);
  check("  it says what is enforced and what is a contract", (await text(page, "#price-honest")).replace(/\s+/g, " ").includes("The program enforces the Acceptance line at release: 0.30% and the floor.") && (await text(page, "#price-honest")).replace(/\s+/g, " ").includes("contract prices that nothing on chain enforces"));

  const rows = async (sel) => Object.fromEntries(await page.$$eval(`${sel} tr`, (tr) => tr.map((r) => [r.dataset.key, r.children[1].textContent.trim()])));
  const calc = async (amount, rate = "") => { await page.fill("#calc-amount", amount); await page.fill("#calc-rate", rate); return rows("#calc-table"); };
  // fee = max(0.05, 0.30% of the amount), as order_fee in programs-v2/knos_pay/src/lib.rs (tests/web/price.mjs has the edges); a contract
  // rate replaces the one rate; the tip comes out of the fee and is never more than it
  for (const [amount, rate, want] of [["5", "", { funder: "5.05", payee: "5.00", fee: "0.05", tip: "0.05", knos: "0.00" }], ["20", "", { funder: "20.06", payee: "20.00", fee: "0.06", tip: "0.05", knos: "0.01" }],
    ["100", "", { funder: "100.30", payee: "100.00", fee: "0.30", tip: "0.05", knos: "0.25" }], ["500", "", { funder: "501.50", payee: "500.00", fee: "1.50", tip: "0.05", knos: "1.45" }],
    ["100", "0.1", { funder: "100.10", payee: "100.00", fee: "0.10", tip: "0.05", knos: "0.05" }], ["7.5", "", { funder: "7.55", payee: "7.50", fee: "0.05", tip: "0.05", knos: "0.00" }],
    ["5000", "", { funder: "5,015.00", payee: "5,000.00", fee: "15.00", tip: "0.05", knos: "14.95" }], ["50000", "", { funder: "50,150.00", payee: "50,000.00", fee: "150.00", tip: "0.05", knos: "149.95" }],
    ["100000", "", { funder: "100,300.00", payee: "100,000.00", fee: "300.00", tip: "0.05", knos: "299.95" }], ["5000", "0.2", { funder: "5,010.00", payee: "5,000.00", fee: "10.00", tip: "0.05", knos: "9.95" }]]) {
    const got = await calc(amount, rate);
    check(`pricing: ${amount} at ${rate || "the standard rate"}: the funder pays ${want.funder}, the payee gets ${want.payee}, the fee ${want.fee}, the relay's tip ${want.tip}, Knos ${want.knos}`, JSON.stringify(got) === JSON.stringify(want), JSON.stringify(got));
  }
  await calc("5");
  check("  the floor is said when the floor is the fee, and what Knos keeps on a payee's first payment", (await text(page, '#calc-table [data-key="fee"]')).includes("the floor: 0.30% of 5.00 would be 0.015, and the fee is never under 0.05") && (await text(page, '#calc-table [data-key="knos"]')).includes("on a payee's first payment"), await text(page, "#calc-table"));
  for (const [amount, rate, words] of [["4", "", "at least 5.00 test USDC"], ["100001", "", "at most 100,000.00 test USDC on devnet"], ["abc", "", "a number like 20 or 7.5"], ["1.2345678", "", "a number like 20 or 7.5"], ["20", "3", "from 0.10% to 0.30%"], ["20", "0.05", "from 0.10% to 0.30%"], ["20", "x", "from 0.10% to 0.30%"]]) {
    await calc(amount, rate);
    check(`  ${amount} at ${rate || "the standard rate"} is refused in a sentence: ${words}`, (await text(page, "#calc-result")).includes(words) && await gone(page, "#calc-table"), await text(page, "#calc-result"));
  }
  const meterRows = async (n) => { await page.fill("#meter-n", n); return rows("#meter-table"); };
  check("pricing: 250,000 evaluations a month: 100,000 free, 150,000 billable, 300.00 at 0.002 each", JSON.stringify(await meterRows("250000")) === JSON.stringify({ free: "100,000", billable: "150,000", list: "300.00" }), JSON.stringify(await meterRows("250000")));
  check("  99,999 and 100,000 cost nothing, 101,000 costs a thousand evaluations", JSON.stringify([await meterRows("99999"), await meterRows("100000"), await meterRows("101000")]) === JSON.stringify([
    { free: "99,999", billable: "0", list: "0.00" }, { free: "100,000", billable: "0", list: "0.00" }, { free: "100,000", billable: "1,000", list: "2.00" }]));
  check("  a very large month is exact (99,999,999,999 evaluations)", (await meterRows("99,999,999,999")).list === "199,999,800.00", (await meterRows("99,999,999,999")).list);
  await page.fill("#meter-n", "-1");
  check("  anything else is a sentence", (await text(page, "#meter-result")).includes("whole number of evaluations") && await gone(page, "#meter-table"));

  const arithmetic = await text(page, "#arithmetic");
  const worked = await page.$$eval("#fee-worked tbody tr", (tr) => tr.map((r) => [...r.children].map((x) => x.textContent.trim())));
  check("pricing: the fee worked at 100, 5,000 and 100,000: one rate, one step each", JSON.stringify(worked) === JSON.stringify([["100", "0.30% of 100", "0.30"], ["5,000", "0.30% of 5,000", "15"], ["100,000", "0.30% of 100,000", "300"]]), JSON.stringify(worked));
  const pageWords = (await page.evaluate(() => document.querySelector("main").textContent)).replace(/\s+/g, " ");
  check("  nothing on the page says a fee has a maximum of 25, or that an order stops at 500", !/at most 25\b|maximum (?:of )?25\b|at most 500\b|1 to 500\b|capped at 500/.test(arithmetic) && !/at most 25\)|0\.40 test USDC, at most 25|from 1 to 500 test USDC, with/.test(pageWords)
    && pageWords.includes("from 5 to 100,000 test USDC, with at most 6 decimals. A build for real money sets its own cap.") && pageWords.includes("at least 0.05 test USDC and no maximum") && pageWords.includes("the 0.3.14 fee (2.5% of the first 1,000, 1% to 50,000, 0.5% above, at least 0.40 test USDC)"));
  const effective = await page.$$eval("#fee-effective tbody tr", (tr) => tr.map((r) => [...r.children].map((x) => x.textContent.trim())));
  check("pricing: the effective fee before funding: 5 pays 0.05 (1.00%), and from 20 up 0.30%", JSON.stringify(effective) === JSON.stringify([
    ["5", "0.05", "1.00%"], ["20", "0.06", "0.30%"], ["100", "0.30", "0.30%"], ["1,000", "3", "0.30%"], ["5,000", "15", "0.30%"], ["100,000", "300", "0.30%"]]), JSON.stringify(effective));
  check("  and it says what a small order pays, and that the fee on devnet is test money", arithmetic.includes("5 test USDC pays the floor, 0.05: 1.00% of it.") && arithmetic.includes("On devnet the fee is test money: 0 revenue."));
  check("pricing: the page prints no revenue scenario: no table of what a year would take, and no bottom-up figure", await gone(page, `#${NOT_SAID[0]}`) && !new RegExp(`${NOT_SAID[0]}|1,000 million|121,125|bottom-up|\\b${NOT_SAID[1]}\\b`, "i").test(arithmetic), arithmetic.slice(0, 400));

  // THE SAME PAGE WITH knos_pay 2.1 LIVE: every fee is the 0.3.14 one it charges, and one line says the next upgrade's
  await liveAs(1, "0.3.14");
  check("pricing: with knos_pay 2.1 live the calculator says the 0.3.14 fee, and one line: after the next upgrade", JSON.stringify(await page.$$eval("#bill-live dt, #bill-live dd", (l) => l.map((e) => e.textContent)))
    === JSON.stringify(["Fee on devnet today", "2.5% of the first 1,000, 1% to 50,000, 0.5% above, at least 0.40", "After the next upgrade", "0.30% of the amount, at least 0.05"]), await text(page, "#bill-live"));
  for (const [amount, want, next] of [["5", { funder: "5.40", payee: "5.00", fee: "0.40", tip: "0.05", knos: "0.35" }, "0.05"], ["20", { funder: "20.50", payee: "20.00", fee: "0.50", tip: "0.05", knos: "0.45" }, "0.06"],
    ["5000", { funder: "5,065.00", payee: "5,000.00", fee: "65.00", tip: "0.05", knos: "64.95" }, "15.00"], ["100000", { funder: "100,765.00", payee: "100,000.00", fee: "765.00", tip: "0.05", knos: "764.95" }, "300.00"]]) {
    const got = await calc(amount);
    check(`  2.1: ${amount} pays a fee of ${want.fee} today, and ${next} after the next upgrade`, JSON.stringify(got) === JSON.stringify(want) && (await text(page, "#calc-next")) === `After the next upgrade: ${next} on this order.`, JSON.stringify(got) + await text(page, "#calc-next"));
  }
  check("  2.1: the fee worked is the three tiers, and the effective fee is theirs", JSON.stringify(await page.$$eval("#fee-worked tbody tr", (tr) => tr.map((r) => [...r.children].map((x) => x.textContent.trim()))))
    === JSON.stringify([["100", "2.50% of 100", "2.50"], ["5,000", "2.50% of 1,000 + 1.00% of 4,000", "65"], ["100,000", "2.50% of 1,000 + 1.00% of 49,000 + 0.50% of 50,000", "765"]])
    && JSON.stringify((await page.$$eval("#fee-effective tbody tr", (tr) => tr.map((r) => [...r.children].map((x) => x.textContent.trim())))).slice(0, 2)) === JSON.stringify([["5", "0.40", "8.00%"], ["20", "0.50", "2.50%"]]));
  await calc("20", "3");
  check("  2.1: a contract rate is held to that build's bounds", (await text(page, "#calc-result")).includes("from 0.50% to 2.50%"), await text(page, "#calc-result"));
  check("  2.1: what is enforced is said for today and for the next build", (await text(page, "#price-honest")).replace(/\s+/g, " ").includes("Until knos_pay 2.2 is live the program charges the 0.3.14 fee: 2.5% of the first 1,000, 1% to 50,000, 0.5% above, at least 0.40. From 2.2: The program enforces"));
  chain.simulate = before;

  // which fee applies today: asked of the program (instruction 12, simulated), never sent
  const said = async (sim) => { chain.simulate = sim; const before = calledAll("simulateTransaction").length; await visit(page, "#pricing"); await page.waitForFunction(() => !document.getElementById("price-version-now").textContent.includes("reading")); return { words: await text(page, "#price-version-now"), asked: calledAll("simulateTransaction").slice(before) }; };
  let got = await said({ err: { InstructionError: [0, "InvalidInstructionData"] }, logs: [] });
  check("pricing: a program that refuses the Version instruction is 2.0: a task funded now pays the fee that program holds, out of the amount", got.words.includes("the program on devnet is 2.0, older than this price book") && got.words.includes("pays the fee that program holds, out of the amount") && got.words.includes("The prices in this book are those of the next program"), got.words);
  const sentTx = readTx(Uint8Array.from(Buffer.from(got.asked[0].params[0], "base64")));
  check("  what was asked is instruction 12 of knos_pay, simulated and not sent", sentTx.length === 1 && sentTx[0].program === ids.knos_pay && sentTx[0].data.length === 1 && sentTx[0].data[0] === 12 && sentTx[0].accounts.length === 0 && chain.sent.length === 0);
  got = await said({ err: null, logs: ["Program log: knos2:version 1"] });
  check("  a program that logs knos2:version 1 is 2.1: it charges the 0.3.14 fee, and the calculator is said to show the fee charged today", got.words.includes("the program on devnet is 2.1.") && got.words.includes("Fee today: 2.5% of the first 1,000, 1% to 50,000, 0.5% above, at least 0.40 test USDC, paid by the funder on top")
    && got.words.includes("From knos_pay 2.2: 0.30% of the amount, at least 0.05.") && got.words.includes("The calculator below shows the fee it charges today."), got.words);
  got = await said({ err: null, logs: ["Program log: knos2:version 2"] });
  check("  a program that logs knos2:version 2 is 2.2: it takes what the calculator says, the funder paying on top", got.words.includes("the program is 2.2 or later") && got.words.includes("on top of the amount"), got.words);
  got = await said({ err: "BlockhashNotFound", logs: [] });
  check("  any other answer is not guessed at", got.words.includes("could not be read just now"), got.words);
  chain.simulate = null;
  await page.close();
}

// ---- 3. get paid with no wallet: a passkey wallet, its address, its balance, a signed withdrawal ------------------------------------
{
  await reset();
  // the page's module has one thing to give, the page itself: the request's format lives in passkey.js alone (withdrawLine,
  // readWithdrawRequest), and the page keeps no reader or writer of its own
  const claimLib = await import(pathToFileURL(join(root, "claim.js")).href), claimSource = readFileSync(join(root, "claim.js"), "utf8");
  check("passkey: the page's module exports the page and nothing else, and holds no copy of the request's format", Object.keys(claimLib).join() === "initClaim"
    && !/WITHDRAW_PREFIX|parseWithdrawComment|withdrawComment|getBigUint64|setBigUint64/.test(claimSource) && claimSource.includes("passkey.withdrawLine("));
  const N_HALF = passkey.N / 2n;
  const bigOf = (u8) => [...u8].reduce((n, x) => n * 256n + BigInt(x), 0n);
  const stored = (page) => page.evaluate(() => { try { return JSON.parse(localStorage.getItem("knos-passkey")); } catch { return "blocked"; } });
  const walletAccount = (key, nonce) => at(passkey.WALLET_LEN, [0, [1]], [2, key], [40, u64(nonce)]);
  // the signature the page carried, checked with nothing but the public key in it
  const verifies = ({ key, authenticatorData, clientDataJSON, signature }) => {
    const unc = ECDH.convertKey(Buffer.from(key), "prime256v1", undefined, undefined, "uncompressed");
    const pub = createPublicKey({ key: { kty: "EC", crv: "P-256", x: b64url(unc.subarray(1, 33)), y: b64url(unc.subarray(33)) }, format: "jwk" });
    return ecVerify("sha256", Buffer.concat([authenticatorData, sha256(clientDataJSON)]), { key: pub, dsaEncoding: "ieee-p1363" }, Buffer.from(signature));
  };
  const sign = async (page, amount, dest, login = "octocat") => {
    await page.fill("#pk-amount", amount); await page.fill("#pk-dest", dest); await page.fill("#pk-login", login);
    await page.click("#pk-sign");
    await page.waitForSelector("#pk-request .status:not(:has-text('Reading')):not(:has-text('Asking'))");
  };

  const dev = await world({ passkeys: true });
  let page = await dev.newPage();
  githubReads = 0;
  await visit(page, "#claim");
  const creates0 = device.creates;      // the phone check above made one
  const card = await text(page, "#passkey");
  check("passkey: the card is in Get paid, says what a passkey is, that the private key never leaves the device, and that it is test USDC", card.includes("Create a passkey wallet") && card.includes("never leaves the device") && card.includes("test USDC") && await page.isHidden("#pk-wallet"));
  check("  it names the address the page will be served at, as passkeys are bound to it", (await text(page, "#pk-rp")) === "127.0.0.1");
  check("  nothing is made or kept before the button is pressed", device.creates === creates0 && (await stored(page)) === null);

  await page.click("#pk-create");
  await page.waitForSelector("#pk-address:not(:empty)");
  const kept = await stored(page), address = await text(page, "#pk-address");
  const key = Buffer.from(kept.key, "hex"), want = await passkey.wallet(key);
  check("passkey: the address is the PDA of knos_passkey for the passkey's key, computed here independently", device.creates === creates0 + 1 && address === want && key.length === 33, [address, want]);
  check("  its two ways to be named: the pull-request comment with that address, and the claim workflow by hand", (await text(page, "#pk-address-comment")) === `/knos address ${address}` && (await text(page, "#pk-wallet")).includes("run the claim workflow by hand"));
  check("  the id and the public key are kept in localStorage, and nothing else", Object.keys(kept).sort().join() === "credentialId,key" && kept.credentialId === [...device.keys.keys()].at(-1));
  check("  a wallet with no token account is said to hold nothing yet", (await text(page, "#pk-held")).includes("holds no test USDC yet"));
  put(await passkey.ata(address, USDC), tokenBytes({ mint: USDC, owner: address, amount: 12_500_000 }), knos.TOKEN);
  await page.click("#pk-refresh");
  await page.waitForFunction(() => document.getElementById("pk-held")?.textContent.includes("12.50"));
  check("  its balance is read from devnet: 12.50 test USDC, no withdrawals yet", (await text(page, "#pk-held")).includes("Withdrawals so far: 0") && githubReads === 0);
  const exported = await page.inputValue("#pk-export");
  check("  the details can be copied out: the id, the key and the address, as one line", JSON.parse(exported).wallet === address && JSON.parse(exported).key === kept.key && JSON.parse(exported).credentialId === kept.credentialId && !exported.includes("\n"));

  // refusals, in sentences, before the device is asked for anything
  const refused = async (amount, dest, login, words) => {
    const before = device.gets.length;
    await sign(page, amount, dest, login);
    const said = await text(page, "#pk-request");
    check(`  refused with no signature: ${words}`, said.includes(words) && device.gets.length === before && await gone(page, "#pk-comment"), said);
  };
  await refused("", WALLET, "octocat", "a number like 5 or 2.50");
  await refused("0", WALLET, "octocat", "a number like 5 or 2.50");
  await refused("1.2345678", WALLET, "octocat", "a number like 5 or 2.50");
  await refused("5", "not an address", "octocat", "is a Solana address");
  await refused("5", address, "octocat", "this wallet itself");
  await refused("5", WALLET, "", "Your GitHub login");
  await refused("5", WALLET, "bad--login", "Your GitHub login");
  await refused("12.51", WALLET, "octocat", "holds 12.50 test USDC, so 12.51 cannot be withdrawn");
  await refused("5", OTHER_WALLET, "octocat", "has no test USDC token account on devnet");

  // a withdrawal: 5 of the 12.50 to WALLET's token account
  githubReads = 0;
  await sign(page, "5", WALLET, "@octocat");
  await page.waitForSelector("#pk-comment");
  const comment = await page.inputValue("#pk-comment"), req = passkey.readWithdrawRequest(comment), to = await passkey.ata(WALLET, USDC);
  check("passkey: signing shows the request as one line for a comment, says nothing was sent, and sent nothing", comment.startsWith("knos-withdraw: ") && !comment.includes("\n") && (await text(page, "#pk-signed")).includes("Nothing has been sent")
    && chain.sent.length === 0 && called("sendTransaction").length === 0 && githubReads === 0);
  check("  the line says: this key, the test USDC mint, the destination's token account, 5 test USDC, withdrawal number 1", req && Buffer.from(req.key).equals(key) && req.mint === USDC && req.to === to && req.amount === 5_000_000n && req.nonce === 1n, JSON.stringify(req, (_k, v) => (typeof v === "bigint" ? String(v) : v)));
  const asked = device.gets.at(-1), clientData = JSON.parse(Buffer.from(req.clientDataJSON).toString());
  const challenge = Buffer.from(await passkey.challenge(address, USDC, to, 5_000_000, 1));
  check("  what the device signed is the program's challenge for exactly that withdrawal, for this site's address", asked.challenge.equals(challenge) && clientData.challenge === b64url(challenge) && clientData.type === "webauthn.get"
    && Buffer.from(req.authenticatorData).subarray(0, 32).equals(sha256("127.0.0.1")) && (req.authenticatorData[32] & 5) === 5 && asked.rpId === "127.0.0.1");
  check("  the signature verifies with the public key in the line, over authenticatorData and the hash of the client data, with s in the lower half", verifies(req) && bigOf(req.signature.subarray(32)) <= N_HALF);
  const ixs = await passkey.withdrawIxs({ key: req.key, mint: req.mint, to: req.to, amount: req.amount, nonce: req.nonce, assertion: { authenticatorData: req.authenticatorData, clientDataJSON: req.clientDataJSON, signature: req.signature } });
  check("  the line is all a relay needs: it makes the precompile instruction and Withdraw, which names the wallet's own token account and the destination", ixs.length === 2 && ixs[0].program === passkey.SECP256R1
    && ixs[1].program === passkey.PASSKEY && ixs[1].accounts[0].pubkey === address && ixs[1].accounts[1].pubkey === await passkey.ata(address, USDC) && ixs[1].accounts[3].pubkey === to);
  const open = new URL(await page.getAttribute("#pk-open", "href"));
  check("  the button opens GitHub's new-issue page of octocat/knos-claim with the line in the body, in a new tab, and is a link, not a send", open.origin + open.pathname === "https://github.com/octocat/knos-claim/issues/new" && open.searchParams.get("body") === comment
    && (await page.getAttribute("#pk-open", "target")) === "_blank" && (await page.getAttribute("#pk-open", "rel")).includes("noopener"));
  const steps = await text(page, "#pk-request ol");
  check("  each step is stated: post it, who sends it and who pays, check the balance and one withdrawal at a time", steps.includes("Post the line in your repository octocat/knos-claim") && steps.includes("pays the transaction fee") && steps.includes("one withdrawal at a time"));
  check("  the line is not in the page's own address", !page.url().includes("knos-withdraw"));

  // the wallet's account says three withdrawals were made: the next is number 4
  put(address, walletAccount(key, 3), passkey.PASSKEY);
  await page.click("#pk-refresh");
  await page.waitForFunction(() => document.getElementById("pk-held")?.textContent.includes("Withdrawals so far: 3"));
  await sign(page, "2.5", WALLET);
  await page.waitForSelector("#pk-comment");
  const second = passkey.readWithdrawRequest(await page.inputValue("#pk-comment"));
  check("passkey: the withdrawal number is the wallet's own nonce plus one (4 after 3)", second.nonce === 4n && second.amount === 2_500_000n && verifies(second));
  check("  one signed for another amount does not verify as this one: the challenge names the amount and the number", clientData.challenge !== JSON.parse(Buffer.from(second.clientDataJSON).toString()).challenge);

  // faucet money: a bounty funded by comment on devnet pays the escrow's own test mint (knos_pay's faucet mint), not
  // Circle's. The card shows it beside Circle's and withdraws it when the person picks it.
  const FAUCET = await k.faucetMint(), mineFaucet = await passkey.ata(address, FAUCET);
  check("passkey: the faucet mint is another mint than Circle's, and the wallet's account of it another address", FAUCET !== USDC && mineFaucet !== await passkey.ata(address, USDC));
  check("  the mint to withdraw is a choice of the two, Circle's first while only Circle's is held", JSON.stringify(await page.$$eval("#pk-mint option", (os) => os.map((o) => o.value))) === JSON.stringify([USDC, FAUCET])
    && (await page.inputValue("#pk-mint")) === USDC);
  put(mineFaucet, tokenBytes({ mint: FAUCET, owner: address, amount: 3_000_000 }), knos.TOKEN);
  await page.click("#pk-refresh");
  await page.waitForFunction(() => document.getElementById("pk-held")?.textContent.includes("3.00"));
  const both = await text(page, "#pk-held");
  check("  the balance shows both: 12.50 test USDC and 3.00 test USDC from the devnet faucet, each at its own account", both.includes("12.50 test USDC, at") && both.includes("3.00 test USDC from the devnet faucet, at")
    && both.includes(`${mineFaucet.slice(0, 4)}…${mineFaucet.slice(-4)}`) && both.includes("Withdrawals so far: 3"), both);
  check("  and the choice says what each holds; the person's choice is kept across a refresh", (await text(page, "#pk-mint")).includes("3.00") && (await page.inputValue("#pk-mint")) === USDC);
  await page.selectOption("#pk-mint", FAUCET);
  await refused("5", WALLET, "octocat", "holds 3.00 test USDC from the devnet faucet, so 5.00 cannot be withdrawn");
  await refused("2", WALLET, "octocat", "has no token account of the devnet faucet's test USDC");
  check("  the choice stays on the faucet's mint after a refusal", (await page.inputValue("#pk-mint")) === FAUCET);
  const toFaucet = await passkey.ata(WALLET, FAUCET);
  put(toFaucet, tokenBytes({ mint: FAUCET, owner: WALLET, amount: 0 }), knos.TOKEN);
  await sign(page, "2", WALLET);
  await page.waitForSelector("#pk-comment");
  const faucetReq = passkey.readWithdrawRequest(await page.inputValue("#pk-comment")), faucetAsked = device.gets.at(-1);
  check("passkey: a faucet withdrawal names the faucet mint and WALLET's account of it, 2.00, number 4, and the device signed exactly that",
    faucetReq.mint === FAUCET && faucetReq.to === toFaucet && faucetReq.amount === 2_000_000n && faucetReq.nonce === 4n && verifies(faucetReq)
    && faucetAsked.challenge.equals(Buffer.from(await passkey.challenge(address, FAUCET, toFaucet, 2_000_000, 4))) && (await text(page, "#pk-signed")).includes("Nothing has been sent")
    && (await text(page, "#pk-request")).includes("2.00 test USDC from the devnet faucet"));
  const faucetIxs = await passkey.withdrawIxs({ key: faucetReq.key, mint: faucetReq.mint, to: faucetReq.to, amount: faucetReq.amount, nonce: faucetReq.nonce, assertion: { authenticatorData: faucetReq.authenticatorData, clientDataJSON: faucetReq.clientDataJSON, signature: faucetReq.signature } });
  check("  and a relay's Withdraw from it moves the faucet mint out of the wallet's own account of that mint", faucetIxs[1].accounts[1].pubkey === mineFaucet && faucetIxs[1].accounts[3].pubkey === toFaucet);
  await page.selectOption("#pk-mint", USDC);

  // the line's format, both ways, and what is not one
  const round = passkey.readWithdrawRequest(passkey.withdrawLine({ key, mint: USDC, to, amount: 7, nonce: 9, assertion: { authenticatorData: req.authenticatorData, clientDataJSON: req.clientDataJSON, signature: req.signature } }));
  check("passkey: the request's format reads back what was written, and nothing else is read as a request", round.amount === 7n && round.nonce === 9n && round.to === to && Buffer.from(round.signature).equals(Buffer.from(req.signature))
    && ["", "knos-withdraw:", "knos-withdraw: !!!", `${comment}A`, comment.slice(0, -8), "/knos address x", null].every((x) => passkey.readWithdrawRequest(x) === null));

  // a page that comes back finds the passkey this browser kept, and signs with it
  await page.close();
  page = await dev.newPage();
  await visit(page, "#claim");
  await page.waitForSelector("#pk-address:not(:empty)");
  check("passkey: a later visit finds the wallet this browser kept, with no click", (await text(page, "#pk-address")) === address && (await text(page, "#pk-made")).includes("kept is in use"));
  await sign(page, "1", WALLET);
  await page.waitForSelector("#pk-comment");
  check("  and signs with the same passkey", verifies(passkey.readWithdrawRequest(await page.inputValue("#pk-comment"))));
  const keepText = await page.inputValue("#pk-export");
  await page.close();

  // a browser that lets the page keep nothing: the page works, and the details are typed back
  const blocked = await world({ passkeys: true });
  await blocked.addInitScript(() => { Object.defineProperty(window, "localStorage", { configurable: true, get() { throw new DOMException("blocked", "SecurityError"); } }); });
  let bp = await blocked.newPage();
  await visit(bp, "#claim");
  await bp.click("#pk-keep summary");
  await bp.fill("#pk-import", "{ not json");
  await bp.click("#pk-use");
  await bp.waitForSelector("#pk-status .status.bad");
  check("passkey: with no storage the page loads and shows no wallet; details that are not details are a sentence", await bp.isHidden("#pk-wallet") && (await text(bp, "#pk-status")).includes("not a passkey wallet's details"));
  await bp.fill("#pk-import", JSON.stringify({ ...JSON.parse(keepText), wallet: OTHER_WALLET }));
  await bp.click("#pk-use");
  await bp.waitForFunction(() => document.querySelector("#pk-status .status.bad")?.textContent.includes("not a passkey"));
  check("  details whose address is not the key's are refused", await bp.isHidden("#pk-wallet"));
  await bp.fill("#pk-import", keepText);
  await bp.click("#pk-use");
  await bp.waitForSelector("#pk-address:not(:empty)");
  check("  details typed back in give the same wallet", (await text(bp, "#pk-address")) === address && (await text(bp, "#pk-made")).includes("in use"));
  await sign(bp, "1", WALLET);
  await bp.waitForSelector("#pk-comment");
  check("  and sign a withdrawal of it", verifies(passkey.readWithdrawRequest(await bp.inputValue("#pk-comment"))));
  await bp.close();

  // the person says no, or the browser has no passkeys to make
  const fresh = await world({ passkeys: true });
  const fp = await fresh.newPage();
  await visit(fp, "#claim");
  device.cancel = true;
  const made = device.creates;
  await fp.click("#pk-create");
  await fp.waitForSelector("#pk-status .status.bad");
  check("passkey: a device that says no makes nothing, and the page says so", device.creates === made && (await text(fp, "#pk-status")).includes("Nothing was created") && await fp.isHidden("#pk-wallet") && (await stored(fp)) === null);
  device.cancel = false;
  await fp.click("#pk-create");
  await fp.waitForSelector("#pk-address:not(:empty)");
  device.cancel = true;
  put(await passkey.ata(await text(fp, "#pk-address"), USDC), tokenBytes({ mint: USDC, owner: await text(fp, "#pk-address"), amount: 3_000_000 }), knos.TOKEN);
  await fp.click("#pk-refresh");
  await fp.waitForFunction(() => document.getElementById("pk-held")?.textContent.includes("3.00"));
  await sign(fp, "1", WALLET);
  check("  and a signing the person cancels shows no request", (await text(fp, "#pk-request")).includes("cancelled") && (await text(fp, "#pk-request")).includes("nothing was signed") && await gone(fp, "#pk-comment"));
  device.cancel = false;
  chain.genesis = MAINNET;
  await fp.click("#pk-refresh");
  await fp.waitForSelector("#pk-balance .status.bad");
  check("  a cluster that is not devnet is refused before the balance is read", (await text(fp, "#pk-balance")).includes("not devnet"));
  chain.genesis = DEVNET;
  await fp.close();

  // a build of other program ids (a staging deployment): the wallet is the address under ITS knos_passkey, the program a
  // withdrawal goes to, when made and when recalled, and its withdrawal number is read from an account of that program
  const STAGED = unique(97);
  const staged = await world({ passkeys: true });
  await staged.route(`${base}program_ids.json`, (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ...ids, knos_passkey: STAGED }) }));
  const sp = await staged.newPage();
  await visit(sp, "#claim");
  await sp.click("#pk-create");
  await sp.waitForSelector("#pk-address:not(:empty)");
  const sKey = Buffer.from((await stored(sp)).key, "hex"), sAddress = await text(sp, "#pk-address");
  check("passkey: on a build of other program ids the wallet made is the address under that build's knos_passkey", sAddress === await passkey.wallet(sKey, STAGED) && sAddress !== await passkey.wallet(sKey), sAddress);
  put(await passkey.ata(sAddress, USDC), tokenBytes({ mint: USDC, owner: sAddress, amount: 4_000_000 }), knos.TOKEN);
  put(sAddress, walletAccount(sKey, 6), STAGED);
  await sp.close();
  const sp2 = await staged.newPage();
  await visit(sp2, "#claim");
  await sp2.waitForSelector("#pk-address:not(:empty)");
  await sp2.waitForFunction(() => document.getElementById("pk-held")?.textContent.includes("4.00"));
  check("  the wallet this browser kept is recalled at that address, and its withdrawals are read from that program's account", (await text(sp2, "#pk-address")) === sAddress
    && (await text(sp2, "#pk-held")).includes("Withdrawals so far: 6"), [await text(sp2, "#pk-address"), await text(sp2, "#pk-held")]);
  await sp2.close();
  await reset();
}

// ---- 4. records and ranks: the static JSON pages_data.py writes, read from the same origin --------------------------------------------
{
  const files = recorded("pages_data").files, rec = (path) => files[path];
  const serve = (on) => { for (const [path, data] of Object.entries(files)) { if (on) served.extra[`/${path}`] = { type: "application/json", body: JSON.stringify(data) }; else delete served.extra[`/${path}`]; } };
  serve(true);
  await plain.grantPermissions(["clipboard-read", "clipboard-write"], { origin: base.slice(0, -1) });
  const page = await plain.newPage();
  const open = async (hash) => {
    await visit(page, hash);
    // a record this tab has read is drawn at once from what was kept (data-kept) and read again: `open` waits for what the files say now
    await page.waitForFunction(() => !document.querySelector("#rec-result[data-kept]") && (document.querySelector("#rec-card, #rec-rank") || [...document.querySelectorAll("#rec-result .status")].some((x) => !/^Reading/.test(x.textContent))));
  };
  const rows = (sel) => page.$$eval(`${sel} tbody tr`, (tr) => tr.map((r) => [...r.children].map((c) => c.textContent.replace(/\s+/g, " ").trim())));

  await visit(page, "#records");
  await page.waitForSelector("#rec-index a");
  const idx = rec("records.json");
  check("records: the view lists the accounts and repositories of records.json, each a link to its record", JSON.stringify(await page.$$eval("#rec-index li a", (a) => a.map((x) => x.getAttribute("href")))) === JSON.stringify([
    ...idx.accounts.map((x) => `#u=${x}`), ...idx.repositories.map((x) => `#r=${x}`)]) && (await text(page, "#rec-index")).includes(`Accounts with a record (${idx.accounts.length})`),
    JSON.stringify(await page.$$eval("#rec-index li a", (a) => a.map((x) => x.getAttribute("href")))));
  check("  it says what has no file and where the list was read and made", (await text(page, "#rec-index")).includes("0 repositories") && (await text(page, "#rec-index-source")).includes("Read from records.json")
    && (await text(page, "#rec-index-source")).includes("made 2026-09-21 17:00 UTC"));
  check("  the three ranks are linked", JSON.stringify(await page.$$eval("#rec-ranks a", (a) => a.map((x) => x.getAttribute("href")))) === JSON.stringify(["#rank=earners", "#rank=funders", "#rank=agents"]));

  // an account: every number is the file's
  put(await (await knos.v2.client(ids)).rep(601), repBytes({ paid: 2, funders: 1, total: 9_750_000, testPaid: 1, testTotal: 4_875_000, first: Date.UTC(2026, 8, 21, 14, 30) / 1000, last: Date.UTC(2026, 8, 22, 9) / 1000 }), ids.knos_pay);
  await open("#u=alice");
  const alice = rec("u/alice.json"), e = alice.as_earner;
  check("records: an account's record says its paid merges, first and last, distinct funders", (await text(page, "#rec-earned")).startsWith(`${e.paid_merges} paid; first 2026-09-21 14:30 UTC, last 2026-09-21 15:11 UTC. ${e.distinct_funders} distinct funders (${e.distinct_funders_real} with real USDC).`)
    && (await text(page, "#rec-earned")).includes("Refusals at merge: 1."), await text(page, "#rec-earned"));
  const earned = (await rows("#rec-card")).slice(0, 4);
  check("  the amounts are the file's, by kind of money, and the kinds are never added together", JSON.stringify(earned) === JSON.stringify(["real", "test", "self", "own"].map((k) => [{ real: "real USDC", test: "test USDC", self: "paid to the funder's own account", own: "Knos's own accounts" }[k], String(e.amounts[k].count), dec(e.amounts[k].amount)])), JSON.stringify(earned));
  check("  its source line says which file, what it was made from and when", (await text(page, "#rec-source")).includes("Read from u/alice.json") && (await text(page, "#rec-source")).includes(alice.source.summary) && (await page.getAttribute("#rec-source a", "href")) === "u/alice.json");
  await page.waitForSelector("#rec-chain .paid-record");
  check("  the program's own record for that GitHub id is read from devnet and shown with its caveats: paid by others in the headline, test money and self-paid apart", (await text(page, "#rec-chain .record-headline")).trim() === "Paid 2 times by 1 distinct funder: 9.75 test USDC in all, first 2026-09-21, last 2026-09-22."
    && (await text(page, "#rec-chain .record-apart")).includes("1 payment, 4.875 test USDC") && (await text(page, "#rec-chain .record-apart")).includes("0 payments (the program keeps their number, not their amount)")
    && (await page.$$eval("#rec-chain .record-caveats li", (l) => l.map((x) => x.textContent))).join("|").includes("It is not a score of the work.|Distinct funders counts different funders.") && (await text(page, "#rec-chain")).includes("GitHub id 601."), await text(page, "#rec-chain"));
  // a profile over the record is shown only when the account's own file on GitHub asks for one (web/badge.js, readOptIn)
  check("  with no profile file on GitHub the record is the chain's own, by id, and says how to opt in", (await page.getAttribute("#rec-chain .paid-record", "data-profile")) === "chain-only" && (await text(page, "#rec-chain")).includes("This account has not opted in to a profile (the file is not there)")
    && hub.asked.filter((a) => a === "/repos/alice/alice/contents/.knos/profile.json").length === 1, hub.asked);
  hub.profiles.alice = { public_record: true, github_id: 601 };
  await page.evaluate(() => sessionStorage.clear());
  await visit(page, "#u=alice");
  await page.waitForSelector('#rec-chain .paid-record[data-profile="opted-in"]');
  check("  with the file saying \"public_record\": true the profile is shown, and says which file asked for it", (await text(page, "#rec-chain")).includes('Shown because this account opted in: alice/alice/.knos/profile.json says "public_record": true.'));
  hub.profiles.alice = { public_record: true, github_id: 999 };
  await page.evaluate(() => sessionStorage.clear());
  await visit(page, "#u=alice");
  await page.waitForSelector('#rec-chain .paid-record[data-profile="chain-only"]');
  check("  a file that names another account does not count", (await text(page, "#rec-chain")).includes("the file names another account id"));
  delete hub.profiles.alice; hub.asked.length = 0;
  await page.evaluate(() => sessionStorage.clear());
  await visit(page, "#u=alice");
  await page.waitForSelector("#rec-chain .paid-record");
  const badge = rec("badge/u/alice.json");
  check("  the badge is drawn from the badge file, here, with nothing asked of shields.io", (await page.getAttribute("#rec-badge", "aria-label")) === `${badge.label}: ${badge.message}` && (await page.getAttribute("#rec-badge", "data-color")) === badge.color && (await text(page, "#rec-badge")).includes("1 paid"));
  check("  the README line to copy is the one in the record", (await text(page, "#rec-readme")) === alice.badge.readme && alice.badge.readme.startsWith("[![paid through Knos](https://img.shields.io/endpoint?url=") && alice.badge.readme.endsWith("/u/alice.html)"));
  await page.click("#rec-copy");
  await page.waitForFunction(() => document.getElementById("rec-copy").textContent === "Copied");
  check("  Copy puts exactly that line on the clipboard", (await page.evaluate(() => navigator.clipboard.readText())) === alice.badge.readme);
  check("  it links to the same record as a page to share and to the account on GitHub", (await page.getAttribute('#rec-card a[href="u/alice.html"]', "href")) === "u/alice.html" && (await page.getAttribute('#rec-card a[href="https://github.com/alice"]', "rel")).includes("noopener"));
  check("  the lookup box holds the login", (await page.inputValue("#rec-q")) === "alice" && await page.isVisible("#view-records") && (await page.getAttribute("nav a[aria-current=page]", "href")) === "#records");

  // an account that funds: the reliability in words, the merged but unpaid
  await open("#u=funder-one");
  const f1 = rec("u/funder-one.json").as_funder;
  check("records: a funder's record says open now, reliability of real-USDC jobs with its interval, and the review time", (await text(page, "#rec-funder")).includes(`Open now: ${f1.open}.`) && (await text(page, "#rec-funder")).includes(`${(f1.reliability.share * 100).toFixed(1)}% (${f1.reliability.k} of ${f1.reliability.n}; 95% interval ${(f1.reliability.ci95[0] * 100).toFixed(1)}%-${(f1.reliability.ci95[1] * 100).toFixed(1)}%) ended in payment`), await text(page, "#rec-funder"));
  check("  merged but unpaid is listed as a table and says it does not say whose fault", (await text(page, "#rec-card")).includes("not whose fault it was") && (await rows("#rec-card")).some((r) => r.join().includes("octo/widgets") && r.join().includes("2026-09-21")), JSON.stringify(f1.merged_unpaid));

  // a repository
  await open("#r=octo/widgets");
  const repo = rec("r/octo/widgets.json");
  check("records: a repository's record says paid merges and how many people were paid, with its README line", (await text(page, "#rec-earned")).includes(`${repo.as_earner.paid_merges} paid;`) && (await text(page, "#rec-earned")).includes(`${repo.as_earner.payees} people paid`)
    && (await text(page, "#rec-readme")) === repo.badge.readme && (await text(page, "#rec-badge")).startsWith("pays on merge"), await text(page, "#rec-earned"));

  const paidBadge = await import(pathToFileURL(join(root, "badge.js")).href), paidData = { repo: "octo/widgets", count: repo.as_earner.amounts.test.count, other: repo.as_earner.amounts.real.count, money: "test USDC", as_of: repo.generated.slice(0, 10) };
  check("  the paid-on-proof badge is drawn for it: its payments in test money, as of the day the file was made, linked to the repository's page", (await page.getAttribute("#rec-paid a.paid-badge", "href")) === "https://drexthealpha.github.io/Knos/r/octo/widgets.html"
    && (await page.getAttribute("#rec-paid svg", "aria-label")) === `paid on proof: ${paidBadge.badgeMessage(paidData)}` && paidBadge.badgeMessage(paidData) === "1 payment in test USDC, 1 in another token, as of 2026-09-21"
    && (await text(page, "#rec-paid")).includes("Test USDC on Solana devnet: not money.") && (await text(page, "#rec-paid")).includes("is not in the badge"), await page.getAttribute("#rec-paid svg", "aria-label"));
  chain.down = "node is behind";
  await open("#u=carol");
  await page.waitForFunction(() => document.querySelector("#rec-chain")?.textContent.includes("did not answer"));
  check("records: when devnet does not answer, the record says so and shows no number of its own", (await text(page, "#rec-chain")).includes("Solana devnet did not answer just now") && await gone(page, "#rec-chain .paid-record"));
  chain.down = null;

  // nobody: a sentence, with what the site does have, never a made-up zero
  await open("#u=nobody");
  const none = await text(page, "#rec-result");
  check("records: an account with no file says so, what has a file, and that it is not a statement that nothing was paid", none.includes("No record for nobody") && none.includes(`this site has ${idx.accounts.length} accounts with a record`) && none.includes("not that nothing was paid") && await gone(page, "#rec-card"), none);
  await open("#r=octo/unknown");
  check("  the same for a repository", (await text(page, "#rec-result")).includes("No record for octo/unknown") && (await text(page, "#rec-result")).includes(`${idx.repositories.length} repositories with a record`));
  await open("#u=bad..name");
  check("  a name that is not a GitHub login is refused before any file is asked for", (await text(page, "#rec-result")).includes("is not a GitHub login or an owner/name repository"));
  await open("#rank=nothing");
  check("  and a rank that does not exist", (await text(page, "#rec-result")).includes("There is no rank called nothing"));

  // ranks
  await open("#rank=earners");
  const earners = rec("rank/earners.json");
  check("ranks: earners are the file's rows: account (a link to its record), USDC received, paid merges, distinct funders, first, last", JSON.stringify(await rows("#rec-rank")) === JSON.stringify(earners.entries.map((x) => [String(x.rank), x.login ?? `id ${x.github_id}`, dec(x.paid_amount), String(x.paid_merges), String(x.distinct_funders), `${x.first.slice(0, 16).replace("T", " ")} UTC`, `${x.last.slice(0, 16).replace("T", " ")} UTC`])), JSON.stringify(await rows("#rec-rank")));
  check("  it says what is left out: " + Object.entries(earners.left_out).map(([k, v]) => `${v} ${k}`).join(", "), (await text(page, "#rec-rank")).includes(`: ${Object.entries(earners.left_out).map(([k, v]) => `${v} ${k}`).join(", ")} payments left out.`) && (await page.getAttribute('#rec-rank tbody a', "href")) === `#u=${earners.entries[0].login}`);
  await open("#rank=funders");
  const funders = rec("rank/funders.json");
  check("ranks: funders are the file's rows, with reliability and merged but unpaid", (await rows("#rec-rank")).map((r) => r.slice(0, 6).join("|")).join() === funders.entries.map((x) => [x.rank, x.login ?? x.funder, dec(x.paid_amount), x.paid_jobs, x.refunded_jobs, x.open_jobs].join("|")).join()
    && (await rows("#rec-rank")).every((r) => r[6].includes("95% interval") || r[6] === "n/a"));
  await open("#rank=agents");
  const agents = rec("rank/agents.json"), shown = await rows("#rec-rank");
  const pct = (x) => (x === null ? "n/a" : `${(x * 100).toFixed(1)}%`);
  check("ranks: agents are the file's, lowest false-claim rate first, with 95% intervals, in the Index's month", (await text(page, "#rec-rank h3")) === `Agents by false-claim rate, ${agents.month}` && JSON.stringify(shown) === JSON.stringify(agents.entries.map((x) => [String(x.rank), x.name, String(x.repositories), pct(x.false_claim_rate),
    x.ci95 ? `${pct(x.ci95[0])}-${pct(x.ci95[1])}` : "n/a", pct(x.test_or_build_rate), x.test_or_build_ci95 ? `${pct(x.test_or_build_ci95[0])}-${pct(x.test_or_build_ci95[1])}` : "n/a"])), JSON.stringify(shown));
  check("  and says it is GitHub's record of a failed check, not a judgment of why", (await text(page, "#rec-rank")).includes("A failed check is GitHub's record, not a judgment of why"));

  // the lookup box
  await visit(page, "#records");
  for (const [ask, to] of [["alice", "#u=alice"], ["@alice", "#u=alice"], ["https://github.com/alice", "#u=alice"], ["octo/widgets", "#r=octo/widgets"], ["https://github.com/octo/widgets/pulls?q=x", "#r=octo/widgets"], ["github.com/octo/widgets.git", "#r=octo/widgets"]]) {
    const got = await page.evaluate(async (x) => (await import("/records.js")).lookup(x), ask);
    check(`records: the lookup box takes ${ask} to ${to}`, got === to, got);
  }
  await page.fill("#rec-q", "octo/widgets"); await page.click("#rec-go");
  await page.waitForSelector("#rec-card");
  check("  and it opens the record", page.url().endsWith("#r=octo/widgets") && (await text(page, "#rec-card h3")) === "octo/widgets");
  await page.fill("#rec-q", "not a thing/at/all here"); await page.click("#rec-go");
  check("  anything else is a sentence", (await text(page, "#rec-result")).includes("Enter a GitHub login"));
  // the lookup in Get paid links to the public record
  await visit(page, "#claim");
  await page.fill("#due-login", "mona"); await page.click("#due-go"); await page.waitForSelector("#due-public");
  check("records: Get paid's lookup links to the account's public record", (await page.getAttribute("#due-public", "href")) === "#u=mona");
  await page.click("#due-public");
  await page.waitForSelector("#rec-result .status");
  check("  which opens the records view (here: no file for them)", await page.isVisible("#view-records") && (await text(page, "#rec-result")).includes("No record for mona"));

  // a build that measured nothing, a file that is not JSON, a file that did not load
  serve(false);
  await open("#u=alice");
  check("records: a build with nothing measured has no record for anyone and says how many have one (none)", (await text(page, "#rec-result")).includes("No record for alice") && (await text(page, "#rec-result")).includes("this site has 0 accounts with a record"));
  await visit(page, "#records");
  await page.waitForSelector("#rec-index h4");
  check("  and lists no one", (await text(page, "#rec-index")).includes("Accounts with a record (0)") && (await text(page, "#rec-index")).includes("None yet."));
  served.extra["/rank/earners.json"] = { type: "text/html", body: "<html>not json</html>" };
  await open("#rank=earners");
  check("  a file that is not JSON is a sentence, not an error", (await text(page, "#rec-result")).includes("rank/earners.json is not JSON"));
  delete served.extra["/rank/earners.json"];
  await open("#rank=earners");
  check("  a rank file the build has is read as it is: no one ranked yet", (await text(page, "#rec-rank")).includes("Nothing to show yet.") && (await text(page, "#rec-rank")).includes("payments left out"));
  await page.close();

  // a phone: the longest tables stay inside their own box
  serve(true);
  const phone4 = await world({ width: 360 });
  const small = await phone4.newPage();
  for (const hash of ["#records", "#u=alice", "#u=funder-one", "#r=octo/widgets", "#rank=funders", "#rank=agents"]) {
    await visit(small, hash); await small.waitForSelector("#rec-card, #rec-rank, #rec-index a");
    check(`phone: records ${hash}: nothing runs off the side`, (await overflow(small)) <= 1, await overflow(small));
  }
  await small.close();
  serve(false);
}

// ---- 5. statements: an owner's or a seller's month from the records JSON, and a CSV made in the browser -----------------------------
{
  const files = recorded("pages_data").files;
  const serve = (on) => { for (const [path, data] of Object.entries(files)) { if (on) served.extra[`/${path}`] = { type: "application/json", body: JSON.stringify(data) }; else delete served.extra[`/${path}`]; } };
  serve(true);
  const parseCsv = (t) => { const out = []; let row = [], cell = "", q = false; for (let i = 0; i < t.length; i++) { const c = t[i]; if (q) { if (c === '"') { if (t[i + 1] === '"') { cell += '"'; i++; } else q = false; } else cell += c; } else if (c === '"') q = true; else if (c === ",") { row.push(cell); cell = ""; } else if (c === "\n") { row.push(cell); out.push(row); row = []; cell = ""; } else cell += c; } return out; };
  const page = await plain.newPage();
  const open = async (login, role) => {
    await visit(page, `#statement=${login}`);
    await page.waitForFunction(() => document.getElementById("stm-statement") || [...document.querySelectorAll("#stm-result .status")].some((x) => !/^Reading/.test(x.textContent)));
    if (role && (await page.inputValue("#stm-role")) !== role) { await page.selectOption("#stm-role", role); }
  };
  const rows = (sel) => page.$$eval(`${sel} tbody tr`, (tr) => tr.map((r) => [...r.children].map((c) => c.textContent.replace(/\s+/g, " ").trim())));
  const names = { real: "real USDC", test: "test USDC", self: "paid to the funder's own account", own: "Knos's own accounts" };
  githubReads = 0; hub.asked.length = 0;

  await open("alice");
  const st = files["statements/alice.json"];
  check("statements: #statement=login opens the records view with the account's statement for its newest month, as a seller", await page.isVisible("#view-records") && (await page.inputValue("#stm-login")) === "alice" && (await page.inputValue("#stm-role")) === "seller"
    && (await page.inputValue("#stm-month")) === "2026-09" && (await text(page, "#stm-statement h4")) === "alice, 2026-09: paid to this account");
  const want = st.as_seller.filter((r) => r.month === "2026-09");
  check("  every payment of the month is a row: date, task, funder, amount, fee, total, currency, transaction, as the file has them", JSON.stringify(await rows("#stm-table-box")) === JSON.stringify(want.map((r) => [r.date, `${r.repository}#${r.issue}`, r.pull_request ?? "", r.funder, dec(r.amount_units), dec(r.fee_units), dec(r.total_units),
    r.currency + (r.kind === "self" || r.kind === "own" ? ` (${names[r.kind]})` : ""), r.transaction])), JSON.stringify(await rows("#stm-table-box")));
  check("  each task links to its issue on GitHub", (await page.getAttribute("#stm-table-box tbody tr a", "href")) === `https://github.com/${want[0].repository}/issues/${want[0].issue}`);
  const sums = {};
  for (const r of want) { const t = sums[r.kind] ||= [0, 0, 0, 0]; t[0]++; t[1] += r.amount_units; t[2] += r.fee_units; t[3] += r.total_units; }
  check("  the totals are added from those rows, by what each payment is counted as: real, test and Knos's own are three lines, never one", JSON.stringify(await rows("#stm-totals")) === JSON.stringify(["real", "test", "self", "own"].filter((k) => sums[k]).map((k) => [names[k], String(sums[k][0]), dec(sums[k][1]), dec(sums[k][2]), dec(sums[k][3]), want.find((r) => r.kind === k).currency]))
    && (await rows("#stm-totals")).length === 3, JSON.stringify(await rows("#stm-totals")));
  check("  its source line names the file, what it was made from and when", (await text(page, "#stm-source")).includes("Read from statements/alice.json") && (await text(page, "#stm-source")).includes("made 2026-09-21 17:00 UTC") && githubReads === 0);
  await visit(page, "#u=alice");
  await page.waitForSelector("#rec-statement");
  check("  an account's record links to its statements", (await page.getAttribute("#rec-statement", "href")) === "#statement=alice");
  await open("alice");

  // the CSV: made in the browser from the rows on screen
  const download = async () => { const [dl] = await Promise.all([page.waitForEvent("download"), page.click("#stm-csv")]); return { name: dl.suggestedFilename(), text: readFileSync(await dl.path(), "utf8") }; };
  let csv = await download();
  const table = parseCsv(csv.text);
  check("statements: the CSV is named for the account, the statement and the month", csv.name === "knos-statement-alice-seller-2026-09.csv");
  check("  its columns are the file's, its rows the month's payments in order, amounts exactly as the file has them", JSON.stringify(table[0]) === JSON.stringify(st.columns) && table.length === want.length + 1 && csv.text.endsWith("\n")
    && table.slice(1).every((cells, i) => st.columns.every((c, j) => cells[j] === String(want[i][c] ?? ""))), csv.text);
  check("  and adds up: the sum of the amount column in units is the totals' sum, to the unit", table.slice(1).reduce((n, c) => n + Number(c[st.columns.indexOf("amount_units")]), 0) === want.reduce((n, r) => n + r.amount_units, 0));

  // names from GitHub are text, never a formula; a comma or a quote does not move a column
  const hostile = JSON.parse(JSON.stringify(st));
  hostile.as_seller[0].payee = "=HYPERLINK(\"http://x\")"; hostile.as_seller[0].funder = 'a, "b"'; hostile.as_seller[0].repository = "+cmd/x";
  served.extra["/statements/alice.json"] = { type: "application/json", body: JSON.stringify(hostile) };
  await open("alice");
  csv = await download();
  const hrow = parseCsv(csv.text)[1];
  check("statements: a name that starts with = + - @ is quoted so a spreadsheet does not run it, and a comma or a quote stays inside its column", hrow[st.columns.indexOf("payee")] === "'=HYPERLINK(\"http://x\")" && hrow[st.columns.indexOf("funder")] === 'a, "b"'
    && hrow[st.columns.indexOf("repository")] === "'+cmd/x" && hrow.length === st.columns.length, JSON.stringify(hrow));
  check("  and on the page a repository name that is not owner/name is not made a link", (await text(page, "#stm-table-box tbody tr")).includes("repository 10, issue #1") && (await page.$$eval("#stm-table-box tbody tr:first-child a[href*='github.com']", (a) => a.length)) === 0);

  // two months: the newest first, each its own table and its own file
  const two = JSON.parse(JSON.stringify(st));
  two.as_seller[0].month = "2026-08"; two.as_seller[0].date = "2026-08-30"; two.as_seller[0].time = "2026-08-30T10:00:00Z";
  served.extra["/statements/alice.json"] = { type: "application/json", body: JSON.stringify(two) };
  await open("alice");
  check("statements: the months with payments are the choices, newest first", JSON.stringify(await page.$$eval("#stm-month option", (o) => o.map((x) => x.value))) === JSON.stringify(["2026-09", "2026-08"]) && (await rows("#stm-table-box")).length === 2);
  await page.selectOption("#stm-month", "2026-08");
  await page.waitForFunction(() => document.getElementById("stm-statement").dataset.month === "2026-08");
  check("  choosing the other month shows only its payments, and its CSV is named for it", JSON.stringify(await rows("#stm-table-box")) === JSON.stringify([[ "2026-08-30", "octo/widgets#1", "", "funder-one", "4.875", "0.125", "5.00", "USDC", "pay1" ]]) && (await download()).name === "knos-statement-alice-seller-2026-08.csv");
  serve(true);

  // an owner: what an account's money paid out, including a payment to itself, counted apart
  await open("funder-two");
  check("statements: an account that only funded opens as an owner, listing what its money paid out", (await page.inputValue("#stm-role")) === "owner" && (await text(page, "#stm-statement h4")) === "funder-two, 2026-09: paid out by this account"
    && (await rows("#stm-table-box")).length === 1 && (await rows("#stm-table-box"))[0][3] === "carol");
  await open("funder-one", "owner");
  await page.waitForFunction(() => document.getElementById("stm-statement").dataset.role === "owner");
  const f1 = files["statements/funder-one.json"].as_owner;
  check("  an owner's rows are the file's (to alice twice, once to itself), the totals three lines, the payment to itself counted apart", JSON.stringify((await rows("#stm-table-box")).map((r) => [r[1], r[3], r[7]])) === JSON.stringify(f1.map((r) => [`${r.repository}#${r.issue}`, r.payee, r.currency + (r.kind === "self" ? " (paid to the funder's own account)" : "")]))
    && (await rows("#stm-totals")).map((r) => r[0]).join() === "real USDC,test USDC,paid to the funder's own account", JSON.stringify(await rows("#stm-totals")));
  await page.selectOption("#stm-role", "seller");
  check("  the same account as a seller is only the payment to itself", (await rows("#stm-table-box")).length === 1 && (await text(page, "#stm-statement h4")) === "funder-one, 2026-09: paid to this account");
  await open("funder-two");
  await page.selectOption("#stm-role", "seller");
  check("  an account with nothing in a role says so and suggests the other", (await text(page, "#stm-result")).includes("funder-two has no payment as a seller in this site's files. Try owner."));

  // no file, not a login, no data
  await open("nobody");
  check("statements: an account with no file says so, and offers the list", (await text(page, "#stm-result")).includes("no statement file for nobody") && await gone(page, "#stm-csv") && (await page.$$eval("#stm-month option", (o) => o.length)) === 0);
  await page.fill("#stm-login", "bad name"); await page.click("#stm-go");
  check("  a login that is not one is a sentence, nothing asked", (await text(page, "#stm-result")).includes("Enter a GitHub login"));
  await page.fill("#stm-login", "ALICE"); await page.click("#stm-go");
  await page.waitForSelector("#stm-statement");
  check("  a login in other letters finds the account by the name records.json gives", (await page.inputValue("#stm-login")) === "alice");
  serve(false);
  await open("alice");
  check("  a build with nothing measured has none: a sentence", (await text(page, "#stm-result")).includes("no statement file for alice"));
  await page.close();

  serve(true);
  const small = await (await world({ width: 360 })).newPage();
  for (const [login, role] of [["alice", "seller"], ["funder-one", "owner"]]) {
    await visit(small, `#statement=${login}`); await small.waitForSelector("#stm-statement");
    check(`phone: the ${role} statement of ${login}: nothing runs off the side`, (await overflow(small)) <= 1, await overflow(small));
  }
  await small.close();
  serve(false);
  // the one record opened on the way asked GitHub for that account's profile file, and nothing else was asked of it
  check("statements: reading them asked nobody but this site: GitHub was not read", githubReads === hub.asked.length && hub.asked.every((a) => a.endsWith("/contents/.knos/profile.json")), [githubReads, hub.asked]);
}

// ---- 6. a task with no repository: the files of a black-box check, the issue and the comment, as links; nothing is sent --------------------------------
{
  const fixture = recorded("acceptance_bundle");
  const lib = await import(pathToFileURL(join(root, "task.js")).href);
  const accept = readFileSync(join(here, "../../src/knos/accept.py"), "utf8");
  const py = (name) => Number(new RegExp(`^${name} = (\\d+)`, "m").exec(accept)[1]);

  // the pieces, against what the Python side wrote
  check("task: the limits are accept.py's own: MAX_CASES and MAX_INPUT", lib.MAX_PAIRS === py("MAX_CASES") && lib.MAX_INPUT === py("MAX_INPUT") && fixture.limits.MAX_CASES === lib.MAX_PAIRS && fixture.limits.MAX_INPUT === lib.MAX_INPUT);
  const shells = fixture.shell.map((x) => { try { return { command: x.command, argv: lib.shellSplit(x.command) }; } catch { return { command: x.command, error: true }; } });
  check(`task: a command is split as Python's shlex.split reads it, and refused where shlex refuses (${fixture.shell.length} recorded commands)`, JSON.stringify(shells) === JSON.stringify(fixture.shell), JSON.stringify(shells.filter((x, i) => JSON.stringify(x) !== JSON.stringify(fixture.shell[i]))));
  for (const b of fixture.bundles) {
    const got = lib.check({ title: "t", description: "d", amount: "20", command: b.command, login: "octocat", repo: "knos-task", pairs: b.pairs }, { min: 1_000_000, max: 500_000_000 });
    check(`task: ${b.name}: the pairs become the cases accept.norm writes, and the command the argv shlex gives`, got.task && JSON.stringify(got.task.cases) === JSON.stringify(b.cases) && JSON.stringify(got.task.argv) === JSON.stringify(b.argv), got.error ?? JSON.stringify(got.task?.cases));
    const files = lib.bundleFiles(b.issue, b.argv, b.cases);
    check(`  ${b.name}: blackbox.py, cases.json and README.md are byte for byte what accept.bundle writes`, JSON.stringify(files) === JSON.stringify(b.files) && Object.keys(files).join() === "blackbox.py,cases.json,README.md", Object.keys(files).filter((k) => files[k] !== b.files[k]).join());
  }

  // the form
  const page = await plain.newPage();
  const fill = async (v) => {
    for (const [id, value] of Object.entries(v)) await page.fill(`#task-${id}`, value);
  };
  const good = { title: "Slugify a title", description: "Read one line from standard input and print it as a URL slug.", amount: "20", command: "python3 slugify.py", login: "octocat", "repo-name": "knos-task" };
  const pairs = [["Hello, World!", "hello-world"], ["  Spaces  ", "spaces"], ["a--b", "a-b"], ["100%", "100"], ["Ünïcode", "unicode\n\n"]];
  const fillPairs = async (list) => {
    while ((await page.$$eval("#task-pairs .pair", (p) => p.length)) < list.length) await page.click("#task-add");
    for (const [i, [a, b]] of list.entries()) { await page.fill(`#task-in-${i + 1}`, a); await page.fill(`#task-out-${i + 1}`, b); }
  };
  await visit(page, "#fund");
  githubReads = 0;
  check("task: the card is in Fund a task, with five empty pairs, and says it sends nothing", await page.isVisible("#task") && (await page.$$eval("#task-pairs .pair", (p) => p.length)) === 5 && (await text(page, "#task")).includes("It sends nothing"));
  await fill(good); await fillPairs(pairs);
  await page.click("#task-go");
  await page.waitForSelector("#task-made");
  check("task: the steps say that nothing has been sent, and each is stated in order", (await text(page, "#task-made .status")).includes("Nothing has been sent") && (await page.$$eval("#task-steps > li", (l) => l.map((x) => x.id))).join() === "task-step-1,task-step-2,task-step-3,task-step-4" && githubReads === 0);
  const link = async (sel) => new URL(await page.getAttribute(sel, "href"));
  check("  step 1 makes a repository from the template drexthealpha/knos-task, named as asked, public, in the person's own account", (await page.getAttribute("#task-repo-link", "href")) === "https://github.com/new?template_owner=drexthealpha&template_name=knos-task&name=knos-task&visibility=public&owner=@me"
    && (await text(page, "#task-repo-link")).includes("octocat/knos-task from the template drexthealpha/knos-task") && (await page.getAttribute("#task-repo-link", "rel")).includes("noopener"));
  const issue = await link("#task-issue-link"), body = lib.issueBody(lib.check({ ...good, repo: good["repo-name"], pairs: pairs.map(([input, output]) => ({ input, output })) }, { min: 1_000_000, max: 500_000_000 }).task);
  check("  step 2 opens a new issue of octocat/knos-task with the title and the text filled in; the text is the description and how it is accepted", issue.origin + issue.pathname === "https://github.com/octocat/knos-task/issues/new" && issue.searchParams.get("title") === good.title && issue.searchParams.get("body") === body
    && body.startsWith(good.description) && body.includes("python3 slugify.py") && body.includes("5 recorded cases") && body.includes("`Fixes #`") && (await page.inputValue("#task-issue-text")) === body);
  check("  step 4 is the funding comment: /knos fund 20, after the files are committed, from a Balance or a wallet", (await text(page, "#task-fund-comment")) === "/knos fund 20" && (await text(page, "#task-step-4")).includes("after the files are committed") && (await page.getAttribute('#task-step-4 a[href="#money"]', "href")) === "#money");
  check("  and says what it did not do: no reference was run, the cases are public, knos accept init does the check", (await text(page, "#task-made")).includes("did not run a reference") && (await text(page, "#task-made")).includes("a solution can answer exactly them from a table") && (await text(page, "#task-made")).includes("knos accept init"));

  // step 3: the issue's number, the repository's default branch, three new-file links
  await page.fill("#task-number", "abc"); await page.click("#task-files-go");
  check("  step 3: a number that is not one is a sentence, and GitHub is not asked", (await text(page, "#task-files")).includes("The issue's number is digits") && githubReads === 0);
  await page.fill("#task-number", "1"); await page.click("#task-files-go");
  await page.waitForSelector("#task-file-list");
  const expectFiles = lib.bundleFiles(1, ["python3", "slugify.py"], lib.check({ ...good, repo: "knos-task", pairs: pairs.map(([input, output]) => ({ input, output })) }, { min: 1_000_000, max: 500_000_000 }).task.cases);
  check("  step 3: GitHub is asked once, for the repository; each of the three files has a link to a new file on its default branch, with its text in the link", githubReads === 1 && (await page.$$eval("#task-file-list li", (l) => l.map((x) => x.dataset.file))).join() === "blackbox.py,cases.json,README.md");
  for (const name of ["blackbox.py", "cases.json", "README.md"]) {
    const u = new URL(await page.getAttribute(`#task-file-list li[data-file="${name}"] a`, "href"));
    check(`    ${name}: new/main?filename=.knos/acceptance/1/${name}, and the value is the file's text`, u.origin + u.pathname === "https://github.com/octocat/knos-task/new/main" && u.searchParams.get("filename") === `.knos/acceptance/1/${name}` && u.searchParams.get("value") === expectFiles[name]
      && (await page.inputValue(`#task-file-list textarea[data-text="${name}"]`)) === expectFiles[name]);
  }
  check("  every link made here goes to github.com, to a new tab that does not hand over the page", (await page.$$eval("#task-made a[href]", (a) => a.map((x) => [x.getAttribute("href"), x.rel, x.target]))).every(([h, rel, t]) => (/^https:\/\/github\.com\//.test(h) || h === "#money" || h === "#anyissue") && (h.startsWith("#") || (rel.includes("noopener") && t === "_blank"))));
  check("  the check and the cases it names were never sent: no transaction, and nobody asked but GitHub once", chain.sent.length === 0 && called("sendTransaction").length === 0 && githubReads === 1);
  const judged = JSON.parse(expectFiles["cases.json"]);
  check("  the cases are the pairs as the judge compares them: trailing spaces and the blank lines at the ends of an answer dropped, the input kept as typed", judged.cases[1].input === "  Spaces  " && judged.cases[4].output === "unicode" && judged.run.join(" ") === "python3 slugify.py");

  // a repository that is not there yet, another default branch
  await page.fill("#task-number", "1");
  await visit(page, "#fund");
  await fill({ ...good, login: "ghost" }); await fillPairs(pairs);
  await page.click("#task-go"); await page.waitForSelector("#task-made");
  await page.fill("#task-number", "3"); await page.click("#task-files-go");
  await page.waitForSelector("#task-files .status.bad");
  check("task: a repository GitHub does not have says to do step 1 first, and makes no file links", (await text(page, "#task-files")).includes("GitHub has no public repository ghost/knos-task yet: do step 1 first.") && await gone(page, "#task-file-list"));
  await visit(page, "#fund");
  await fill({ ...good, login: "octocat", "repo-name": "trunky" }); await fillPairs(pairs);
  await page.click("#task-go"); await page.waitForSelector("#task-made");
  await page.fill("#task-number", "12"); await page.click("#task-files-go");
  await page.waitForSelector("#task-file-list");
  check("  the default branch is the repository's own (trunk), not assumed", (await link('#task-file-list li[data-file="blackbox.py"] a')).pathname === "/octocat/trunky/new/trunk" && (await text(page, "#task-branch")).includes("default branch is trunk"));

  // a long file does not go in a link
  await visit(page, "#fund");
  await fill(good);
  const long = Array.from({ length: 5 }, (_, i) => [`input number ${i} ${"x".repeat(900)}`, `answer ${i} ${"y".repeat(900)}`]);
  await fillPairs(long);
  await page.click("#task-go"); await page.waitForSelector("#task-made");
  await page.fill("#task-number", "2"); await page.click("#task-files-go");
  await page.waitForSelector("#task-file-list");
  const cases = new URL(await page.getAttribute('#task-file-list li[data-file="cases.json"] a', "href"));
  check("task: a file too long for a link opens an empty new-file page with its name, and says to paste it from the box", cases.searchParams.get("filename") === ".knos/acceptance/2/cases.json" && !cases.searchParams.has("value")
    && (await text(page, '#task-file-list li[data-file="cases.json"]')).includes("too long to carry in a link") && (await page.inputValue('#task-file-list textarea[data-text="cases.json"]')).includes("input number 4")
    && (await page.getAttribute('#task-file-list li[data-file="blackbox.py"] a', "href")).includes("value="));

  // refusals: a sentence each, no steps made
  await visit(page, "#fund");
  const refuse = async (what, change, words, list = pairs) => {
    await visit(page, "#fund");
    await fill({ ...good, ...change.fields }); await fillPairs(list);
    await page.click("#task-go");
    await page.waitForSelector("#task-result .status.bad");
    check(`task: ${what} is refused: ${words}`, (await text(page, "#task-result")).includes(words) && await gone(page, "#task-made"), await text(page, "#task-result"));
  };
  await refuse("no title", { fields: { title: " " } }, "Give the task a title.");
  await refuse("no description", { fields: { description: "" } }, "Describe the task");
  await refuse("an amount that is not a number", { fields: { amount: "twenty" } }, "a number like 20 or 7.5");
  // the bounds are the second deployment's, read from the client: a work order's (what `/knos fund` opens), and beside it the older 2.0 job's own
  const orderBounds = "The amount is from 5 to 100,000 test USDC. A work order holds from 5 to 100,000 test USDC, and `/knos fund` opens a work order. A bounty of the older kind (2.0) takes from 1 to 100,000, where the escrow holds no work orders yet; this page writes the comment for a work order.";
  check("task: the bounds it states are the client's: an order's 5 to 100,000 and a 2.0 job's 1 to 100,000, never the first deployment's 1 to 500",
    knos.v2.ORDER_MIN_AMOUNT === 5_000_000 && knos.v2.MAX_AMOUNT === 100_000_000_000 && knos.v2.MIN_AMOUNT === 1_000_000 && knos.MAX_AMOUNT === 500_000_000
    && !readFileSync(join(root, "task.js"), "utf8").includes("knos.MAX_AMOUNT"));
  await refuse("an amount below the least", { fields: { amount: "0.5" } }, orderBounds);
  await refuse("an amount a 2.0 job takes and an order does not", { fields: { amount: "4.99" } }, orderBounds);
  await refuse("an amount above an order's most", { fields: { amount: "100000.01" } }, orderBounds);
  const lim = { min: knos.v2.ORDER_MIN_AMOUNT, max: knos.v2.MAX_AMOUNT, job: { min: knos.v2.MIN_AMOUNT, max: knos.v2.MAX_AMOUNT } }, five = pairs.map(([input, output]) => ({ input, output }));
  check("  501, which the first deployment refused, and both of an order's bounds are taken", ["501", "5", "100000"].every((amount) => lib.check({ ...good, amount, repo: "knos-task", pairs: five }, lim).task?.units === Number(amount) * 1_000_000));
  await refuse("a command with an open quote", { fields: { command: 'python3 "slug' } }, "not a command line");
  await refuse("no command", { fields: { command: "  " } }, "Name the command");
  await refuse("a login that is not one", { fields: { login: "bad--login" } }, "Your GitHub login");
  await refuse("a repository name that is not one", { fields: { "repo-name": "a/b" } }, "The repository's name");
  await refuse("four pairs", {}, "Give at least 5 pairs", pairs.slice(0, 4));
  await refuse("no pairs", {}, "None is filled in", []);
  await refuse("the same input twice", {}, "has the same input as pair 1", [...pairs.slice(0, 4), [pairs[0][0], "other"]]);
  await refuse("answers that are all empty", {}, "Every answer is empty", pairs.map(([a]) => [a, "  \n"]));
  await refuse("pairs a command that only echoes would pass", {}, "only prints its input back", pairs.map(([a]) => [a, a]));
  await refuse("a control character in an answer", {}, "control character", [...pairs.slice(0, 4), ["x", "a\u0007b"]]);
  await refuse("the text KNOS_TREE", {}, "KNOS_TREE", [...pairs.slice(0, 4), ["KNOS_TREE", "x"]]);
  await refuse("a sixth pair that has an answer but no input", {}, "has no input", [...pairs, ["", "answer"]]);
  check("task: none of the refusals asked anyone: GitHub was read only for the four repositories above", githubReads === 4, githubReads);

  // as many pairs as the judge takes, and no more
  await visit(page, "#fund");
  await page.evaluate(() => { for (let i = 0; i < 195; i++) document.getElementById("task-add").click(); });
  check("task: pairs can be added up to the judge's limit (200)", (await page.$$eval("#task-pairs .pair", (p) => p.length)) === 200);
  await page.click("#task-add");
  check("  and the 201st is refused", (await text(page, "#task-result")).includes("At most 200 pairs") && (await page.$$eval("#task-pairs .pair", (p) => p.length)) === 200);
  await page.close();

  // a phone
  const small = await (await world({ width: 360 })).newPage();
  await visit(small, "#fund");
  for (const [id, value] of Object.entries({ ...good, title: "A title that is long enough to wrap onto several lines on a phone screen without any trouble" })) await small.fill(`#task-${id}`, value);
  for (const [i, [a, b]] of [["x".repeat(120), "y".repeat(120)], ...pairs.slice(1)].entries()) { await small.fill(`#task-in-${i + 1}`, a); await small.fill(`#task-out-${i + 1}`, b); }
  await small.click("#task-go"); await small.waitForSelector("#task-made");
  await small.fill("#task-number", "7"); await small.click("#task-files-go"); await small.waitForSelector("#task-file-list");
  await small.evaluate(() => document.querySelectorAll("#task details").forEach((d) => { d.open = true; }));
  check("phone: the steps of a task, with its files open: nothing runs off the side", (await overflow(small)) <= 1, await overflow(small));
  await small.close();
}

// ---- 7. a banner when an upgrade of either program is waiting: the upgrade multisig's proposals, read from devnet ---------------------------
{
  const rec = recorded("squads_upgrades");
  const lib = await import(pathToFileURL(join(root, "upgrade.js")).href);
  const { createHash: hash } = await import("node:crypto");
  const hexBytes = (h) => Uint8Array.from(Buffer.from(h, "hex"));
  const load = () => { for (const [address, a] of Object.entries(rec.accounts)) put(address, hexBytes(a.data), a.owner); };
  check("upgrade: the recorded accounts were made at the chain's time of these tests, for the multisig this build names", rec.now === NOW && rec.multisig === ids.upgrade_multisig && rec.time_lock === 172800);

  // the reads, on the recorded accounts, against what src/knos/mainnet_check.py read from them
  check("upgrade: the three account discriminators are sha256 of the names, as Anchor makes them", ["Proposal", "VaultTransaction", "ConfigTransaction"].every((n, i) => Object.values(lib.DISCRIMINATORS)[i].join() === [...hash("sha256").update(`account:${n}`).digest().subarray(0, 8)].join()));
  const stub = { findProgramAddress: knos.findProgramAddress, unb58: knos.unb58, b58: knos.b58, SQUADS: knos.SQUADS, LOADER: knos.LOADER, accounts: async (_, list) => list.map((a) => { const x = rec.accounts[a]; return x ? { owner: x.owner, data: hexBytes(x.data), lamports: 1 } : null; }) };
  const ms = knos.readMultisig(hexBytes(rec.accounts[rec.multisig].data));
  const read = await lib.pendingProposals(stub, "rpc", rec.multisig, ms);
  const want = rec.pending.map((p) => ({ index: p.index, status: p.status, approved: p.approved, threshold: p.threshold, kind: p.kind, program: p.program, buffer: p.buffer, executesAt: p.executes_at }));
  check("upgrade: the proposals read from the recorded accounts are the four pending ones mainnet_check.pending_proposals read, newest first, with the executing time", ms.transactionIndex === 5 && ms.staleTransactionIndex === 0 && JSON.stringify(read) === JSON.stringify(want), JSON.stringify(read));
  check("  the proposal and transaction addresses it derives are the ones the Python side derived (every account was found)", read.length === 4 && read.every((p) => p.kind));
  const upgradeTx = hexBytes(rec.accounts[Object.keys(rec.accounts).find((a) => rec.accounts[a].what.startsWith("transaction 4"))].data);
  const kinds = Array.from({ length: upgradeTx.length + 1 }, (_, n) => lib.readTransaction(stub, upgradeTx.subarray(0, n)).kind);
  check("  an account cut short is never read as an upgrade; the whole of it, or all but its last four bytes (the table lookups it does not need), is", kinds.every((k, n) => (n >= upgradeTx.length - 4) === (k === "upgrade")), kinds.join());
  check("  an account of another layout, or none, is other; a proposal that is not one is null", lib.readTransaction(stub, null).kind === "other" && lib.readTransaction(stub, new Uint8Array(200)).kind === "other" && lib.readProposal(new Uint8Array(100)) === null && lib.readProposal(null) === null);
  const proposal = hexBytes(rec.accounts[Object.keys(rec.accounts).find((a) => rec.accounts[a].what.startsWith("proposal 4"))].data);
  check("  a proposal cut short or with an unknown status is null", [10, 48, 49, 55, proposal.length - 9].every((n) => lib.readProposal(proposal.subarray(0, n)) === null) && lib.readProposal(Uint8Array.from(proposal, (b, i) => (i === 48 ? 9 : b))) === null && lib.readProposal(proposal)?.status === "Approved");

  // the page
  const page = await plain.newPage();
  const banner = async (hash) => { await reset(); load(); await visit(page, hash); await page.waitForSelector("#upgrade-banner:not([hidden])"); };
  // the first screen reads no chain: the banner is read with the first page that reads Solana, and stays from then on
  await reset(); load(); await visit(page, ""); await page.waitForTimeout(300);
  check("upgrade: the first screen asks devnet nothing and shows no banner under the bar", await page.isHidden("#upgrade-banner") && called("getMultipleAccounts").length === 0 && called("getAccountInfo").length === 0);
  // what it shows instead: one line from upgrades.json, the file of the site scripts/upgrade_feed.py writes from the multisig
  const built = JSON.parse(readFileSync(join(root, "upgrades.json"), "utf8")), builtPending = built.entries.filter((e) => e.status === "pending");
  await page.waitForSelector("#hero-upgrades:not([hidden])", { timeout: 5000 }).catch(() => {});
  if (builtPending.length) {
    check("  but the pending upgrades in one line, from the site's upgrades.json: the count and two words", await page.isVisible("#hero-upgrades")
      && /^Upgrades (pending|approved)$/.test(await text(page, "#hero-upgrades-line")) && (await page.getAttribute("#hero-upgrades-line", "data-count")) === String(builtPending.length)
      && new RegExp(`^${builtPending.length} program upgrades? (pending|approved, delay over)$`).test(await page.getAttribute("#hero-upgrades-line", "aria-label")), await text(page, "#hero-upgrades-line"));
  } else {
    check("  and with no upgrade pending in the site's upgrades.json, no line either", await page.isHidden("#hero-upgrades"));
  }
  // the line's words, on the feed as it stood with proposals 3 to 6 pending (tests/fixtures/before_round/web/upgrades.json)
  const feed = JSON.parse(readFileSync(join(here, "..", "fixtures", "before_round", "web", "upgrades.json"), "utf8")), feedPending = feed.entries.filter((e) => e.status === "pending");
  const lib0 = await import(pathToFileURL(join(root, "front.js")).href), said = (l) => (l ? `${l.n}|${l.words}|${l.said}` : null);
  check("  the line is true before and after the earliest time one can run: pending before it, approved with the delay over after it, nothing for a file with none pending",
    said(lib0.feedLine(feed, Math.min(...feedPending.map((e) => e.earliest_execution)) - 1)) === "4|Upgrades pending|4 program upgrades pending"
    && said(lib0.feedLine(feed, Math.max(...feedPending.map((e) => e.earliest_execution)))) === "4|Upgrades approved|4 program upgrades approved, delay over"
    && lib0.feedLine({ ...feed, entries: feed.entries.map((e) => ({ ...e, status: "executed" })) }) === null && lib0.feedLine(null) === null
    && said(lib0.feedLine({ entries: [{ ...feedPending[0], squads_status: "Active" }] }, 4e9)) === "1|Upgrades pending|1 program upgrade pending");
  await banner("#fund");
  check("  a page that reads Solana reads the multisig itself, and its banner takes the line's place", await page.isHidden("#hero-upgrades") && (await page.evaluate(() => document.documentElement.dataset.upgrades)) === "chain");
  const paras = await page.$$eval("#upgrade-banner p.upgrade", (p) => p.map((x) => [x.dataset.program, x.dataset.status, x.dataset.index, x.textContent.replace(/\s+/g, " ").trim()]));
  const day = (t) => `${new Date(t * 1000).toISOString().slice(0, 16).replace("T", " ")} UTC`;
  const payUp = rec.pending.find((p) => p.index === 4), oidcUp = rec.pending.find((p) => p.index === 3);
  check("upgrade: the banner shows the two upgrades of Knos's programs, newest first: not the unrelated program's draft, not the multisig's own change, not the one that ran", JSON.stringify(paras.map((p) => p.slice(0, 3))) === JSON.stringify([["knos_pay", "Approved", "4"], ["knos_oidc", "Active", "3"]]), JSON.stringify(paras));
  const short = (a) => `${a.slice(0, 4)}…${a.slice(-4)}`;
  check("  an approved one says the program, the buffer, the votes, and when it can be run, from the chain's clock: 43 h 0 min", paras[0][3] === `An upgrade of knos_pay is pending: it would replace the program's code with the bytes in the buffer ${short(payUp.buffer)}. The multisig has approved it (2 of 2 members); it can be run from ${day(payUp.executes_at)}, in 43 h 0 min.`, paras[0][3]);
  check("  an active one says the votes so far and how long after the last it can run", paras[1][3] === `An upgrade of knos_oidc is pending: it would replace the program's code with the bytes in the buffer ${short(oidcUp.buffer)}. 1 of 2 approvals so far. It can be run 48 hours after the vote that approves it.`, paras[1][3]);
  check("  the buffer links to devnet's explorer", (await page.getAttribute('#upgrade-banner p[data-program="knos_pay"] a', "href")) === `https://explorer.solana.com/address/${payUp.buffer}?cluster=devnet`);
  const security = readFileSync(join(here, "../../docs/SECURITY.md"), "utf8");
  check("  it links to docs/SECURITY.md, section 7 (which is there), in a new tab", (await page.getAttribute("#upgrade-security", "href")) === "https://github.com/drexthealpha/Knos/blob/main/docs/SECURITY.md#7-the-upgrade-authority" && /^## 7\. The upgrade authority$/m.test(security)
    && (await page.getAttribute("#upgrade-security", "rel")).includes("noopener") && (await text(page, "#upgrade-banner")).includes("the delay is there so that it can be seen coming"));
  check("  and nothing was sent: it only read", chain.sent.length === 0 && called("sendTransaction").length === 0 && called("getMultipleAccounts").length === 2 && called("simulateTransaction").length === 0, called("getMultipleAccounts").length);
  for (const hash of ["#fund", "#claim", "#pricing", "#records"]) { await visit(page, hash); await page.waitForSelector("#upgrade-banner:not([hidden])"); }
  check("  it is on every view", await page.isVisible("#upgrade-banner"));

  // what Pricing says of it, when the program still says 2.0
  chain.simulate = { err: { InstructionError: [0, "InvalidInstructionData"] }, logs: [] };
  await visit(page, "#pricing");
  await page.waitForFunction(() => !document.getElementById("price-version-now").textContent.includes("reading"));
  check("upgrade: Pricing says the 2.1 prices wait for it: approved, and the day it can be run", (await text(page, "#price-version-now")).includes(`an upgrade of knos_pay is approved and can be run from ${new Date(payUp.executes_at * 1000).toISOString().slice(0, 10)}`), await text(page, "#price-version-now"));
  chain.simulate = null;

  // a multisig with nothing waiting, no multisig, a void proposal, another program's account, a chain that does not answer: no banner, no error
  const quiet = async (what, prepare) => {
    await reset(); load(); prepare();
    const before = errors.length;
    await visit(page, "#records");
    await page.waitForFunction(() => document.getElementById("pr-form"));
    await page.waitForTimeout(400);
    check(`upgrade: ${what}: no banner`, await page.isHidden("#upgrade-banner") && errors.length === before, errors.slice(before));
  };
  const raw = hexBytes(rec.accounts[rec.multisig].data);
  await quiet("a multisig that has made no proposal", () => put(rec.multisig, Uint8Array.from(raw, (b, i) => (i >= 78 && i < 86 ? 0 : b)), knos.SQUADS));
  await quiet("every proposal void (the stale index is the newest)", () => put(rec.multisig, Uint8Array.from(raw, (b, i) => (i === 86 ? 5 : b)), knos.SQUADS));
  await quiet("no upgrade multisig at all", () => chain.accounts.delete(rec.multisig));
  await quiet("accounts that another program owns", () => { for (const [a, x] of Object.entries(rec.accounts)) if (a !== rec.multisig) put(a, hexBytes(x.data), knos.TOKEN); });
  await quiet("a chain that does not answer", () => { chain.down = "node is behind"; });
  chain.down = null;

  // a phone
  await reset(); load();
  const small = await (await world({ width: 360 })).newPage();
  for (const hash of ["#fund", "#pricing"]) { await visit(small, hash); await small.waitForSelector("#upgrade-banner:not([hidden])"); check(`phone: the banner on ${hash}: nothing runs off the side`, (await overflow(small)) <= 1, await overflow(small)); }
  await small.close(); await page.close();
  await reset();
}

// ---- 8. Fund any issue: the form, its refusals, the terms shown whole, the one adapter, the wallet flow, and what waits for the upgrade ----------------------------
{
  const fa = recorded("fund_any_issue"), rec = recorded("squads_upgrades"), lib = await import(pathToFileURL(join(root, "anyissue.js")).href);
  const hexBytes = (h) => Uint8Array.from(Buffer.from(h, "hex"));
  const sha = (text) => createHash("sha256").update(text).digest("hex");
  const throws = (f) => { try { f(); return null; } catch (e) { return e instanceof lib.Refused ? e.message : `not a Refused: ${e}`; } };
  const front = readFileSync(join(root, "front.js"), "utf8");
  const PIN_REPO = /uses: ([\w.-]+\/[\w.-]+)\/\.github\/workflows\//.exec(front)[1];
  const norm = (o) => JSON.stringify(Object.fromEntries(Object.entries(o).sort(([a], [b]) => (a < b ? -1 : 1))));
  served.front = stamp(COMMIT);

  // -- the terms: what src/knos/terms.py writes for the same boxes (tests/test_fund_any_issue.py), byte for byte
  check("fund any issue: the recorded order is for the wallet, the issue and the pinned workflows these tests use", fa.order.args.funder === WALLET && fa.order.args.funderToken === (await knos.ata(WALLET, USDC)) && fa.order.args.mint === USDC
    && fa.order.args.repoId === repos["octo/widgets"] && fa.order.args.wfRepo === PIN_REPO && fa.order.args.wfSha === COMMIT && fa.order.fee === 500_000);
  for (const c of fa.terms) {
    const checks = lib.listOf(c.checks_text), paths = [...new Set(lib.listOf(c.paths_text).map(lib.glob))], made = lib.termsOf({ checks, paths });
    check(`  terms: ${c.name}: the names and the globs are read as the comment command reads them`, JSON.stringify(checks) === JSON.stringify(c.checks) && JSON.stringify(paths) === JSON.stringify(c.paths), JSON.stringify([checks, paths]));
    check(`  terms: ${c.name}: the canonical bytes, their sha256 and the sentences are Python's`, made.text === c.text && sha(made.bytes) === c.sha256 && Buffer.from(made.bytes).toString("ascii") === c.text
      && (c.checks.length ? JSON.stringify(lib.describeTerms(made.terms)) === JSON.stringify(c.describe) : JSON.stringify(lib.describeTerms(made.terms).slice(1)) === JSON.stringify(c.describe.slice(1))), made.text);
    check(`  terms: ${c.name}: sdk/settle's termsJson writes the same bytes`, Buffer.from(knos.v2.termsJson(made.terms)).equals(Buffer.from(made.bytes)));
  }
  check("  terms: with no check the funder is not 'you': a maintainer's merge alone is the acceptance", lib.describeTerms(lib.termsOf().terms)[0] === "No check is required: the maintainer's merge alone is the acceptance.");
  const refused = (label, f, words) => { const got = throws(f); check(`  terms: ${label}`, got !== null && got.includes(words), got); };
  refused("a check of Knos's own is refused", () => lib.termsOf({ checks: ["knos-check"] }), "is Knos's own job");
  refused("  and its check / claims", () => lib.termsOf({ checks: ["check / claims"] }), "is Knos's own job");
  refused("  and the relay's", () => lib.termsOf({ checks: ["prove-relay / pay"] }), "is Knos's own job");
  refused("a name over 200 characters", () => lib.termsOf({ checks: ["x".repeat(201)] }), "1 to 200 characters on one line");
  refused("a name with a line break", () => lib.termsOf({ checks: ["a\nb"] }), "1 to 200 characters on one line");
  for (const bad of ["../x", "!x", "a\\b", "src/../x", "/"]) refused(`the glob ${JSON.stringify(bad)}`, () => lib.termsOf({ paths: [bad] }), "A path is a glob from the repository's root");
  refused("terms over 600 bytes", () => lib.termsOf({ checks: Array.from({ length: 20 }, (_, i) => `a check with a longer name number ${i}`) }), "at most 600");
  refused("an unclosed bracket", () => lib.listOf("test (ubuntu, 3.12"), "not closed");
  refused("an unclosed quote", () => lib.listOf('"test, lint'), "not closed");

  // -- the issue's address, and every box of the form, in the order the page checks them
  const ref = (o, r, n, kind = "issues") => ({ owner: o, repo: r, number: n, kind });
  const addresses = [["https://github.com/octo/widgets/issues/7", ref("octo", "widgets", 7)], ["github.com/octo/widgets/issues/7?x=1#issuecomment-5", ref("octo", "widgets", 7)], ["  https://www.github.com/octo/widgets/issues/7/  ", ref("octo", "widgets", 7)],
    ["http://github.com/octo/widgets/issues/7", ref("octo", "widgets", 7)], ["octo/widgets/issues/7", ref("octo", "widgets", 7)], ["octo/widgets#7", ref("octo", "widgets", 7)], ["octo/wid.gets-2_x#12", ref("octo", "wid.gets-2_x", 12)],
    ["https://github.com/octo/widgets/pull/12", ref("octo", "widgets", 12, "pull")], ["https://github.com/octo/widgets/pull/12/files", ref("octo", "widgets", 12, "pull")]];
  check("fund any issue: an issue is named by its address, a pull request's address or owner/repo#7 (and a pull request is told apart)", addresses.every(([text, want]) => JSON.stringify(lib.parseIssueUrl(text)) === JSON.stringify(want)), addresses.map(([t]) => JSON.stringify(lib.parseIssueUrl(t))));
  const notAddresses = ["", "octo/widgets", "octo/widgets#0", "octo/widgets#x", "octo/widgets#7 and more", "https://gitlab.com/octo/widgets/issues/7", "https://github.com/octo/issues/7", "https://github.com/octo/widgets/issues/",
    "https://github.com/octo/widgets/issues/1234567890", "javascript:alert(1)", "../widgets#7", "octo/../issues/7", "https://github.com.evil.example/octo/widgets/issues/7"];
  check("  anything else is not an address", notAddresses.every((t) => lib.parseIssueUrl(t) === null), notAddresses.filter((t) => lib.parseIssueUrl(t) !== null));
  const boxes = { issue: "octo/widgets#7", amount: "20", days: "14", checks: "test", paths: "src/**" };
  const sentence = (over) => throws(() => lib.readBoxes({ ...boxes, ...over }));
  const AMOUNT = "Write the amount as a number like 20 or 7.5, with at most six decimals.", DAYS = "The days are a whole number from 1 to 90.";
  for (const [over, words] of [[{ issue: "" }, "Write the issue's address on GitHub: https://github.com/owner/repo/issues/7, or owner/repo#7."], [{ issue: "https://github.com/octo/widgets/pull/12" }, "That is a pull request. Fund the issue it closes: its address ends in /issues/ and a number."],
    [{ amount: "" }, AMOUNT], [{ amount: "1.1234567" }, AMOUNT], [{ amount: "abc" }, AMOUNT], [{ amount: "4.99" }, "An order takes at least 5.00 test USDC."], [{ amount: "100000.000001" }, "An order takes at most 100,000.00 test USDC on devnet."],
    [{ amount: "100001" }, "An order takes at most 100,000.00 test USDC on devnet."], [{ days: "0" }, DAYS], [{ days: "91" }, DAYS], [{ days: "x" }, DAYS], [{ days: "1.5" }, DAYS], [{ days: "" }, DAYS],
    [{ checks: "knos-check" }, `"knos-check" is Knos's own job, and a bounty cannot require it. Name your repository's checks, or leave the box empty.`], [{ paths: "../etc" }, "A path is a glob from the repository's root, like src/** or docs/*.md."]]) {
    check(`  the form: ${JSON.stringify(Object.values(over)[0])} in the ${Object.keys(over)[0]} box is said: ${words.slice(0, 40)}`, sentence(over) === words, sentence(over));
  }
  const good = lib.readBoxes(boxes);
  check("  the form: 5 and 500 are the bounds, 90 days the longest; what is read is the units, the seconds and the terms", lib.readBoxes({ ...boxes, amount: "5" }).amount === 5_000_000 && lib.readBoxes({ ...boxes, amount: "500", days: "90" }).workS === 90 * 86400
    && good.amount === 20_000_000 && good.workS === 14 * 86400 && good.text === fa.order.args.terms && JSON.stringify(good.ref) === JSON.stringify(ref("octo", "widgets", 7)));
  check("  the form: the first wrong box is the one said (the issue before the amount before the days)", sentence({ issue: "x", amount: "x", days: "x" }).startsWith("Write the issue's address") && sentence({ amount: "x", days: "x" }).startsWith("Write the amount"));

  // -- the one adapter, and where it looks
  const log = [], arg = { x: 1 };
  const make = (name) => { const h = { fundOrderWalletIx(a) { log.push([name, this === h, a]); return `ix of ${name}`; } }; return h; };
  const hk = make("k"), hv2 = make("v2"), hmod = Object.assign(make("mod"), { v2: hv2 }), bare = make("bare");
  check("fund any issue: the adapter finds the call on the client first, then on knos.v2, then on the module, calling it as a method with the one object", lib.orderFunding(hmod, hk)(arg) === "ix of k" && lib.orderFunding({ v2: hv2 }, {})(arg) === "ix of v2"
    && lib.orderFunding(bare, null)(arg) === "ix of bare" && JSON.stringify(log.map(([n, own]) => [n, own])) === JSON.stringify([["k", true], ["v2", true], ["bare", true]]) && log.every(([, , a]) => a === arg));
  check("  and says there is none when there is none", lib.orderFunding({}, {}) === null && lib.orderFunding({ v2: {} }, undefined) === null && lib.orderFunding({ fundOrderWalletIx: 5 }, { fundOrderWalletIx: "no" }) === null);
  check("  it and the passkey funder are the only places the page's code names the call (settle.js and passkey.js are the client's own files, copied by the build)", readdirSync(root).filter((f) => f.endsWith(".js")).every((f) => f === "settle.js" || f === "passkey.js" || f === "anyissue.js" || f === "passkey_fund.js" || !readFileSync(join(root, f), "utf8").includes("fundOrderWalletIx")));
  check("  the order's address is the one pay.py derives (scope from the repository id and the issue number), for the first two orders of a wallet", (await lib.orderAddress(knos, ids.knos_pay, repos["octo/widgets"], 7, WALLET, 0)) === fa.order.orders["0"]
    && (await lib.orderAddress(knos, ids.knos_pay, repos["octo/widgets"], 7, WALLET, 1)) === fa.order.orders["1"]);
  check("  the options are 48 bytes of zeros but the NEUTRAL flag, as pay.py opts(flags=F_NEUTRAL) writes them", knos.hex(lib.optionsOf()) === fa.order.args.options && lib.optionsOf().length === 48);
  const pin = lib.workflowPin(front.replaceAll("KNOS_COMMIT_SHA", COMMIT));
  const base = `jobs:\n  a:\n    uses: o/r/.github/workflows/fund.yml@${COMMIT}\n  b:\n    uses: o/r/.github/workflows/prove.yml@${COMMIT}\n`;
  check("  the pinned workflows are read from the file the Protect view hands out: one repository and one full commit, or none", pin.repo === PIN_REPO && /^[0-9a-f]{40}$/.test(pin.sha) && JSON.stringify(lib.workflowPin(base)) === JSON.stringify({ repo: "o/r", sha: COMMIT })
    && lib.workflowPin(base.replace(`prove.yml@${COMMIT}`, "prove.yml@KNOS_COMMIT_SHA")) === null && lib.workflowPin(base.replace(`prove.yml@${COMMIT}`, `prove.yml@${"b".repeat(40)}`)) === null
    && lib.workflowPin(base.replace("b:\n    uses: o/r", "b:\n    uses: p/r")) === null && lib.workflowPin("nothing here") === null && lib.workflowPin(base.replaceAll(COMMIT, "main")) === null);

  // -- whether it can be sent, in words
  const payUp = rec.pending.find((p) => p.index === 4), day = new Date(payUp.executes_at * 1000).toISOString().slice(0, 10);
  const up = { upgrades: [{ name: "knos_pay", status: "Approved", executesAt: payUp.executes_at }] };
  check("fund any issue: Version says 0: available when the upgrade of the day executes", lib.availability({ version: 0, funding: true, up }).words === `Available when the upgrade of ${day} executes. The upgrade multisig has approved it, and it can be run from that day.`
    && lib.availability({ version: 0, funding: true, up }).kind === "upgrade" && !lib.availability({ version: 0, funding: true, up }).ok && !lib.availability({ version: 0, funding: false, up }).ok);
  check("  with no approved upgrade it says there is no date, and why", lib.availability({ version: 0, funding: true, up: { upgrades: [{ name: "knos_pay", status: "Active" }] } }).words === "Available when the upgrade of knos_pay executes. One is pending and not yet approved, so it has no date yet."
    && lib.availability({ version: 0, funding: true, up: { upgrades: [{ name: "knos_oidc", status: "Approved", executesAt: 1 }] } }).words === "Available when the upgrade of knos_pay executes. None is proposed that this page can see, so it has no date."
    && lib.availability({ version: 0, funding: true, up: { upgrades: [], failed: true } }).words === "Available when the upgrade of knos_pay executes. This page could not read the upgrade multisig just now, so it has no date.");
  check("  not told: nothing can be sent; told 2.1 with no call in the client: nothing can be sent, and why; told 2.1 with the call: it can", lib.availability({ version: null, funding: true }).kind === "unread" && !lib.availability({ version: null, funding: true }).ok
    && lib.availability({ version: 1, funding: false }).kind === "client" && lib.availability({ version: 1, funding: true }).ok && lib.availability({ version: 1, funding: true }).words === "The program on devnet is 2.1: it takes this.");

  // -- the page
  const standIn = (code) => code.replace("function client2(ids) {", "function client2(ids) {\n  const k = client2_(ids);\n  k.fundOrderWalletIx = async (args) => window.__fundOrder(args);\n  return k;\n}\nfunction client2_(ids) {");
  const without = (code) => code.replace("function client2(ids) {", "function client2(ids) {\n  const k = client2_(ids);\n  delete k.fundOrderWalletIx;\n  return k;\n}\nfunction client2_(ids) {");
  const builtSettle = readFileSync(join(root, "settle.js"), "utf8");
  check("fund any issue: the two copies of settle.js these tests serve differ from the built one only where the client is made", builtSettle.split("function client2(ids) {").length === 2 && standIn(builtSettle).includes("client2_(ids)") && without(builtSettle).includes("delete k.fundOrderWalletIx"));
  const V1 = { err: null, logs: ["Program log: knos2:version 1"] }, V0 = { err: { InstructionError: [0, "InvalidInstructionData"] }, logs: [] };
  const loadSquads = () => { for (const [address, a] of Object.entries(rec.accounts)) put(address, hexBytes(a.data), a.owner); };
  const available = async (page) => { await page.waitForFunction(() => !document.getElementById("any-available").textContent.includes("Asking devnet")); return text(page, "#any-available"); };
  const fill = async (page, over = {}) => { for (const [id, v] of Object.entries({ "any-issue": "octo/widgets#7", "any-amount": "20", "any-days": "14", "any-checks": "test", "any-paths": "src/**", ...over })) await page.fill(`#${id}`, v); };
  // an issue the tab has read before is shown at once from what was kept (#any-asof says so) and read again: `read` waits for what GitHub says now
  const read = async (page, over = {}) => { await fill(page, over); await page.click("#any-go"); await page.waitForFunction(() => (document.querySelector("#any-facts") && !document.querySelector("#any-asof")) || document.querySelector("#any-result .status.bad")); return text(page, "#any-result"); };
  const idle = () => ({ sent: chain.sent.length, asks: called("simulateTransaction").length, blockhashes: called("getLatestBlockhash").length, signs: called("wallet:signAndSend").length });

  // a browser with no wallet, a client with no such call, a program that says 2.1: the terms are shown, nothing can be sent, and why
  {
    served.settle = without; await reset(); chain.simulate = V1;
    const page = await plain.newPage();
    await visit(page, "#fund");
    check("fund any issue: the card is in the Fund view, with its form, and says what the client lacks", (await available(page)).includes("has no call that builds the funding of an order yet, so nothing can be sent from here") && await page.isVisible("#anyissue"), await available(page));
    check("  the first thing asked of devnet is the version, simulated and not sent", calledAll("simulateTransaction").length === 1 && calledAll("simulateTransaction")[0].version === true && chain.sent.length === 0);
    const before = idle(), reads = githubReads;
    for (const [over, words] of [[{ "any-issue": "" }, "Write the issue's address on GitHub"], [{ "any-amount": "4" }, "An order takes at least 5.00 test USDC."], [{ "any-days": "100" }, "The days are a whole number from 1 to 90."],
      [{ "any-checks": "knos-check" }, "is Knos's own job"], [{ "any-issue": "https://github.com/octo/widgets/pull/12" }, "That is a pull request."]]) {
      const got = await read(page, over);
      check(`  fund any issue: ${JSON.stringify(Object.values(over)[0])} is said in the card: ${words.slice(0, 40)}`, got.includes(words) && await gone(page, "#any-facts"), got);
    }
    check("  a form that is wrong asks GitHub nothing", githubReads === reads);
    for (const [over, words] of [[{ "any-issue": "octo/widgets#8" }, "octo/widgets#8 is closed. Fund an open issue."], [{ "any-issue": "octo/widgets#12" }, "That is a pull request. Fund the issue it closes."], [{ "any-issue": "octo/widgets#99" }, "GitHub has no such public repository, issue or user."],
      [{ "any-issue": "octo/old#1" }, "octo/old is archived: no pull request can be merged in it."], [{ "any-issue": "nobody/nothing#1" }, "GitHub has no such public repository, issue or user."], [{ "any-issue": "limited/repo#1" }, "GitHub's free limit for this network is used up"]]) {
      const got = await read(page, over);
      check(`  fund any issue: GitHub's answer for ${over["any-issue"]} is said: ${words.slice(0, 44)}`, got.includes(words) && await gone(page, "#any-facts"), got);
    }
    githubReads = 0;
    await read(page);
    check("  a good form: two reads of GitHub (the repository and the issue), nothing of Solana", githubReads === 2 && (await text(page, "#any-facts")).length > 100);
    const facts = await text(page, "#any-facts");
    check("  the preview names the issue with its title and a link, the repository's id, and what you pay: the amount and the fee on top", facts.includes("octo/widgets#7: Parser crashes on an empty file") && (await page.getAttribute("#any-issue-link", "href")) === "https://github.com/octo/widgets/issues/7"
      && facts.includes("GitHub repository id 5550001. The order is for this repository's issue number 7.") && facts.includes("20.50 test USDC: 20.00 for the person who does the work, and 0.50 fee on top (2.5% of the first 1,000, 1% from there to 50,000, 0.5% above; at least 0.40, no maximum).") && (await text(page, "#any-pay")) === "20.50", facts);
    check("  the days it has, and what happens when it is unpaid", (await text(page, "#any-time")) === "14 days. Unpaid by then, the order can be sent back to your wallet.");
    check("  the sentences are Python's describe of the same terms", JSON.stringify(await page.$$eval("#any-sentences li", (l) => l.map((x) => x.textContent))) === JSON.stringify(fa.order.describe.map((x) => x.replaceAll("`", "")))
      && (await page.$$("#any-sentences code")).length === 4);
    check("  the terms are the canonical bytes, with their sha256, as Python writes them", (await page.textContent("#any-terms")) === fa.order.args.terms && (await text(page, "#any-hash")) === fa.order.terms_sha256);
    check("  and the workflows that can pay it: the pinned repository and commit, from the file the Protect view hands out", (await text(page, "#any-pin")).includes(`a signed run of the workflows of ${PIN_REPO} at commit ${COMMIT.slice(0, 7)}.`)
      && (await page.getAttribute("#any-pin a:nth-of-type(2)", "href")) === `https://github.com/${PIN_REPO}/commit/${COMMIT}`);
    check("  with no wallet and no call in the client the button to check it is off, and says why", await page.isDisabled("#any-plan") && (await text(page, "#any-why")).includes("has no call that builds the funding of an order yet"));
    check("  nothing was sent, built or simulated for any of this", JSON.stringify(idle()) === JSON.stringify(before) && chain.sent.length === 0);
    await page.fill("#any-amount", "21");
    check("  a box changed, the preview is gone: what is shown is always what was read", await gone(page, "#any-facts") && await page.isHidden("#any-next"));
    const title = await read(page, { "any-issue": "https://github.com/octo/other/issues/3" });
    check("  a title is GitHub's text, shown as text (cut at 150 characters), never as markup", title.includes("<img src=x onerror=alert(1)> and a very long title") && (await page.$$("#any-facts img")).length === 0 && !title.includes("w".repeat(120)));
    const weird = await read(page, { "any-checks": "test (ubuntu, 3.12), `quoted, name`, tést", "any-paths": "./src/**, /docs/" });
    check("  names with commas in brackets or quotes, non-ASCII letters, and paths with a leading ./ or / are read as Python reads them", (await page.textContent("#any-terms")) === lib.termsOf({ checks: ["test (ubuntu, 3.12)", "quoted, name", "tést"], paths: ["src/**", "docs/"] }).text
      && (await page.textContent("#any-terms")).includes("\\u00e9") && weird.includes("test (ubuntu, 3.12) (any source)"), weird);
    await visit(page, "#anyissue=octo/widgets%237");
    check("  #anyissue is the Fund view, the box filled and nothing read (it is not the escrow lookup)", (await page.$$eval(".view", (v) => v.filter((x) => !x.hidden).map((x) => x.id))).join() === "view-fund" && (await page.inputValue("#any-issue")) === "octo/widgets#7"
      && (await page.inputValue("#st-issue")) === "" && called("getProgramAccounts").length === 0 && (await page.getAttribute("nav a[aria-current=page]", "href")) === "#fund");
    await page.close();
  }

  // the program says 2.0: what waits for the upgrade of a day
  {
    served.settle = standIn; await reset(); loadSquads(); chain.simulate = V0;
    const page = await wal.newPage();
    await visit(page, "#fund");
    check("fund any issue: Version says 0 and an upgrade is approved: available when the upgrade of its day executes", (await available(page)) === `Available when the upgrade of ${day} executes. The upgrade multisig has approved it, and it can be run from that day.`, await available(page));
    await read(page);
    await page.click("#any-connect");
    await page.waitForSelector("#any-address");
    check("  the terms are shown and the wallet connects, and still nothing can be sent: the button is off with that sentence", await page.isDisabled("#any-plan") && (await text(page, "#any-why")) === (await text(page, "#any-available")));
    await page.evaluate(() => { window.__fundOrder = () => { throw new Error("must not be called"); }; });
    await page.click("#any-plan", { force: true, timeout: 1000 }).catch(() => {});
    check("  pressing it anyway builds nothing, asks devnet nothing and the wallet nothing", JSON.stringify(idle()) === JSON.stringify({ sent: 0, asks: 0, blockhashes: 0, signs: 0 }) && await gone(page, "#any-send"));
    await page.close();
    await reset(); chain.simulate = V0;
    const none = await wal.newPage();
    await visit(none, "#fund");
    check("  Version says 0 and no upgrade is proposed: it says so, with no date", (await available(none)) === "Available when the upgrade of knos_pay executes. None is proposed that this page can see, so it has no date.", await available(none));
    await none.close();
    await reset(); chain.simulate = { err: "BlockhashNotFound", logs: [] };
    const unsure = await wal.newPage();
    await visit(unsure, "#fund");
    check("  a Version call devnet does not answer plainly is not guessed at", (await available(unsure)).includes("Devnet did not say which knos_pay is live. Nothing can be sent."));
    await unsure.close();
    await reset(); chain.down = "node is behind";
    const down = await wal.newPage();
    await visit(down, "#fund");
    check("  a devnet that does not answer: the same", (await available(down)).includes("Devnet did not say which knos_pay is live"));
    chain.down = null; await down.close();
  }

  // the program says 2.1 and the client has the call: connect, check, see, sign
  {
    served.settle = standIn; await reset(); chain.simulate = V1;
    const page = await wal.newPage();
    const MINE = await knos.ata(WALLET, USDC), ix = (seq) => { const x = fa.order.ix[String(seq)]; return { program: x.program, data: hexBytes(x.data), accounts: x.accounts }; };
    const expect = (seq) => b64(knos.serializeTx([ix(seq)], WALLET, BLOCKHASH));
    await visit(page, "#fund");
    await page.evaluate((ixs) => {
      window.__orderCalls = [];
      window.__fundOrder = async (args) => {
        window.__orderCalls.push({ ...args, terms: new TextDecoder().decode(args.terms), options: [...args.options].map((b) => b.toString(16).padStart(2, "0")).join("") });
        const x = ixs[String(args.seq)];
        return { program: x.program, data: Uint8Array.from(x.data.match(/../g), (h) => parseInt(h, 16)), accounts: x.accounts };
      };
    }, fa.order.ix);
    check("fund any issue: the program says 2.1 and the client has the call: it can be sent", (await available(page)) === "The program on devnet is 2.1: it takes this." && await page.isVisible("#any-available.ok"));
    await read(page);
    check("  with the terms shown but no wallet, the button is off: connect first", await page.isDisabled("#any-plan") && (await text(page, "#any-why")) === "Connect a wallet first.");
    const sims = called("simulateTransaction").length, bh = called("getLatestBlockhash").length;
    await page.click("#any-connect");
    await page.waitForSelector("#any-address");
    check("  connecting here shows in both cards, and the button of both says switch", (await text(page, "#any-address")) === WALLET && (await text(page, "#wallet-address")) === WALLET && (await text(page, "#any-connect")) === "Switch wallet" && (await text(page, "#wallet-connect")) === "Switch wallet");
    check("  now the button works, and still nothing has been sent or asked of the wallet", await page.isEnabled("#any-plan") && (await text(page, "#any-why")) === "" && (await page.evaluate(() => window.__wallet.sent.length)) === 0 && chain.sent.length === 0);
    // the terms are shown and a wallet is connected: the check on devnet runs by itself, once (it signs nothing), and the button stays to check again
    await page.waitForSelector("#any-send, #any-status .status.bad");
    const calls = await page.evaluate(() => window.__orderCalls);
    check("  the client is called once, with exactly the arguments the Python reference was given: the wallet, its token account, the mint, the repository id, the issue number, the amount, the pinned workflows, the terms, merge mode, the seconds, order 0, the options",
      calls.length === 1 && norm(calls[0]) === norm({ ...fa.order.args, seq: 0 }), JSON.stringify(calls));
    check("  devnet simulated exactly the transaction the Python instruction makes, unsigned, on the blockhash it gave, before the wallet was asked", called("simulateTransaction").length === sims + 1 && called("getLatestBlockhash").length === bh + 1
      && called("simulateTransaction").at(-1).params[0] === expect(0) && JSON.stringify(called("simulateTransaction").at(-1).params[1]) === JSON.stringify({ encoding: "base64", sigVerify: false, replaceRecentBlockhash: true, commitment: "confirmed" })
      && chain.sent.length === 0 && (await page.evaluate(() => window.__wallet.sent.length)) === 0);
    const stepsText = await text(page, "#any-steps");
    check("  what you would sign: the order, the amount and the fee, from your token account into the order's own account, with the terms hash", stepsText.startsWith("Fund the order for octo/widgets#7: 20.00 test USDC for the person who does the work and 0.50 fee, 20.50 in all, from your token account into the order's own escrow account.")
      && stepsText.includes(`Its terms hash is ${fa.order.terms_sha256.slice(0, 16)}…`), stepsText);
    const accountLines = await page.$$eval("#any-steps details li", (l) => l.map((x) => x.textContent));
    const flags = (a) => (a.signer ? " (signs)" : "") + (a.writable ? " (changes)" : "");
    check("  and the accounts of the instruction, by their roles, with who signs and what changes", accountLines.length === 9 && accountLines[0] === `the funder (you, signing): ${WALLET} (signs) (changes)` && accountLines[1] === `the order: ${fa.order.orders["0"]} (changes)`
      && accountLines[3] === `your token account: ${MINE} (changes)` && accountLines[4] === `the mint: ${USDC}` && accountLines.every((l, n) => l.endsWith(fa.order.ix["0"].accounts[n].pubkey + flags(fa.order.ix["0"].accounts[n]))), accountLines);
    check("  the order's account has its link on devnet's explorer", (await page.getAttribute('#any-tx a[href*="/address/"]', "href")) === `https://explorer.solana.com/address/${fa.order.orders["0"]}?cluster=devnet`);
    await page.click("#any-send");
    await page.waitForSelector("#any-done, #any-status .status.bad");
    check("  the wallet was handed exactly that transaction, for devnet, from its own address", chain.sent.length === 1 && chain.sent[0].tx === expect(0) && (await page.evaluate(() => window.__wallet.sent[0].chain)) === "solana:devnet"
      && (await page.evaluate(() => window.__wallet.sent[0].account)) === WALLET && (await page.evaluate(() => window.__wallet.sent.length)) === 1);
    check("  the simulation came first, the wallet second", chain.calls.filter((c) => !c.version).map((c) => c.method).filter((m) => m === "simulateTransaction" || m === "wallet:signAndSend").join() === "simulateTransaction,wallet:signAndSend");
    check("  it says done after devnet confirmed, with the transaction and the order's account", (await text(page, "#any-done")).startsWith("Done.") && called("getSignatureStatuses").length >= 1 && (await page.getAttribute("#any-done a", "href")) === `https://explorer.solana.com/tx/${chain.sent[0].signature}?cluster=devnet`
      && (await text(page, "#any-done")).includes(`The order's account is ${fa.order.orders["0"]}.`));

    // a second order for the same issue by the same wallet is order 1, and says so
    put(fa.order.orders["0"], new Uint8Array(512), ids.knos_pay);
    await read(page);
    await page.click("#any-plan");
    await page.waitForSelector("#any-send, #any-status .status.bad");
    const again = await page.evaluate(() => window.__orderCalls.at(-1));
    check("fund any issue: an order of this wallet for this issue is already there: the next one is order 1, said, with its own address", again.seq === 1 && (await text(page, "#any-steps")).includes("(this wallet has funded this issue 1 time before, so this is order 1)")
      && (await text(page, "#any-tx")).includes(`The order's account will be ${fa.order.orders["1"]}.`) && called("simulateTransaction").at(-1).params[0] === expect(1));
    for (let s = 1; s < 8; s++) put(await lib.orderAddress(knos, ids.knos_pay, repos["octo/widgets"], 7, WALLET, s), new Uint8Array(512), ids.knos_pay);
    const calls0 = (await page.evaluate(() => window.__orderCalls)).length;
    await page.click("#any-plan");
    await page.waitForSelector("#any-status .status.bad");
    check("  with eight of them there, it says so and builds nothing", (await text(page, "#any-status")).includes("This wallet has already funded this issue 8 times.") && (await page.evaluate(() => window.__orderCalls)).length === calls0 && await gone(page, "#any-send"));
    chain.accounts.delete(fa.order.orders["0"]);
    for (let s = 1; s < 8; s++) chain.accounts.delete(await lib.orderAddress(knos, ids.knos_pay, repos["octo/widgets"], 7, WALLET, s));

    // what is refused before the wallet is asked
    const sentBefore = chain.sent.length, token = (n) => put(MINE, tokenBytes({ mint: USDC, owner: WALLET, amount: n }), knos.TOKEN);
    token(20_000_000);
    await page.click("#any-plan");
    await page.waitForSelector("#any-status .status.bad");
    check("fund any issue: a wallet with less than the amount and the fee is told what it holds and what is needed", (await text(page, "#any-status")) === "This wallet holds 20.00 test USDC, and 20.50 is needed: the amount and the fee. Circle's devnet faucet gives test USDC.");
    chain.accounts.delete(MINE);
    await page.click("#any-plan");
    await page.waitForSelector("#any-status .status.bad");
    check("  a wallet with no token account holds nothing", (await text(page, "#any-status")).startsWith("This wallet holds 0.00 test USDC, and 20.50 is needed"));
    token(100_000_000);
    chain.simulate = { err: { InstructionError: [0, { Custom: 94 }] }, logs: [] };
    await page.click("#any-plan");
    await page.waitForSelector("#any-status .status.bad");
    check("  devnet's refusal is the program's own words, and nothing is offered to sign", (await text(page, "#any-status")) === knos.v2.ERRORS[94] && await gone(page, "#any-send"), await text(page, "#any-status"));
    chain.simulate = V1;
    chain.genesis = MAINNET;
    const before = idle();
    await page.click("#any-plan");
    await page.waitForSelector("#any-status .status.bad");
    check("  an endpoint that is not devnet: refused before anything is built or simulated", (await text(page, "#any-status")).includes("not devnet, so nothing was sent") && JSON.stringify(idle()) === JSON.stringify(before));
    chain.genesis = DEVNET;
    await page.click("#any-plan");
    await page.waitForSelector("#any-send");
    await page.evaluate(() => { window.__wallet.reject = true; });
    await page.click("#any-send");
    await page.waitForSelector("#any-status .status.bad");
    check("  a wallet that says no: its words, the button works again, and nothing was sent", (await text(page, "#any-status")) === "User rejected the request." && await page.isEnabled("#any-send") && chain.sent.length === sentBefore);
    await page.evaluate(() => { window.__wallet.reject = false; });
    chain.genesis = MAINNET;
    await page.click("#any-send");
    await page.waitForFunction(() => document.getElementById("any-status").textContent.includes("not devnet"));
    check("  an endpoint that stopped being devnet after the check: the wallet is not even asked again", (await text(page, "#any-status")).includes("not devnet, so nothing was sent") && chain.sent.length === sentBefore);
    chain.genesis = DEVNET;
    await page.fill("#any-days", "15");
    check("  a box changed after the check: the transaction on offer is gone", await gone(page, "#any-send") && await gone(page, "#any-steps"));

    // every link the card makes
    await read(page);
    const hrefs = await page.$$eval("#anyissue a[href]", (a) => a.map((x) => x.getAttribute("href")));
    check("  every link of the card goes to GitHub, devnet's explorer or Circle's faucet, none carries the wallet's address to GitHub, and the ones that open a tab do not hand over the page",
      hrefs.every((h) => /^https:\/\/github\.com\/|^https:\/\/explorer\.solana\.com\/(address|tx)\/[1-9A-HJ-NP-Za-km-z]+\?cluster=devnet$|^https:\/\/faucet\.circle\.com\/$/.test(h)) && !hrefs.some((h) => h.startsWith("https://github.com/") && h.includes(WALLET))
      && await page.$$eval('#anyissue a[target="_blank"]', (a) => a.every((x) => /noopener/.test(x.rel))), hrefs);
    await page.close();
  }

  // a phone: the longest content the card can show runs off nowhere
  {
    served.settle = standIn; await reset(); chain.simulate = V1;
    const small = await (await world({ width: 360, wallets: [["Test Wallet", WALLET]] })).newPage();
    await visit(small, "#fund");
    await small.evaluate((ixs) => { window.__fundOrder = async () => { const x = ixs["0"]; return { program: x.program, data: Uint8Array.from(x.data.match(/../g), (h) => parseInt(h, 16)), accounts: x.accounts }; }; }, fa.order.ix);
    await available(small);
    await read(small, { "any-issue": "https://github.com/octo/other/issues/3", "any-checks": "a check with a very long name that has no break in it " + "x".repeat(100) + ", test (ubuntu-latest, python 3.12, with a long matrix)", "any-paths": "src/" + "deeply/".repeat(10) + "**" });
    await small.click("#any-connect");
    await small.waitForSelector("#any-address");
    await small.click("#any-plan");
    await small.waitForSelector("#any-send, #any-status .status.bad");
    check("phone: the card with its longest terms, a connected wallet and the accounts of the transaction: nothing runs off the side", (await overflow(small)) <= 1, await overflow(small));
    await small.close();
  }
  served.settle = (text) => text; chain.simulate = null; await reset();
}

// ---- what a tab has read is shown again at once, and a first-time visitor's path to a funded issue ----------------------------------
{
  // a record seen before: on the page before the site's files or devnet have answered anything, saying how old it is; then what is true now
  const files = recorded("pages_data").files;
  for (const [path, data] of Object.entries(files)) served.extra[`/${path}`] = { type: "application/json", body: JSON.stringify(data) };
  await reset();
  const repAt = await (await knos.v2.client(ids)).rep(601), rep = (paid) => put(repAt, repBytes({ paid, funders: 1, total: 9_750_000, testPaid: 1, testTotal: 4_875_000, first: 1790000000, last: 1790000500 }), ids.knos_pay);
  rep(2);
  const page = await (await world()).newPage();
  await visit(page, "#u=alice");
  await page.waitForSelector("#rec-chain .paid-record");
  check("kept: a record seen for the first time is drawn once, with no note of age", await gone(page, "#rec-asof") && await gone(page, "#rec-chain-asof") && (await text(page, "#rec-chain .record-headline")).trim().startsWith("Paid 2 times"));
  rep(3);                                                               // the chain moves on
  let answered = 0, letGo;
  const gate = new Promise((ok) => { letGo = ok; });
  await page.route(/records\.json|\/u\/alice\.json|\/badge\/|api\.devnet\.solana\.com|program_ids\.json/, async (route) => { await gate; answered++; return route.fallback(); });
  await visit(page, "#u=alice");
  await page.waitForSelector("#rec-asof");
  await page.waitForSelector("#rec-chain .paid-record");
  check("  seen again: the record and the program's own account are on the page before any file or devnet has answered", answered === 0 && (await text(page, "#rec-card h3")) === "alice" && (await text(page, "#rec-chain .record-headline")).trim().startsWith("Paid 2 times"), answered);
  check("  and each says how old it is: \"as of N s ago\"", /^Shown as of \d+ s ago\. Reading it again…$/.test(await text(page, "#rec-asof")) && /^Read from Solana devnet as of \d+ s ago\. Reading it again…$/.test(await text(page, "#rec-chain-asof")), await text(page, "#rec-asof"));
  letGo();
  await page.waitForFunction(() => !document.getElementById("rec-asof") && !document.getElementById("rec-chain-asof"));
  check("  then the files and devnet are read again, and the value that changed on chain replaces the kept one", answered >= 4 && (await text(page, "#rec-chain .record-headline")).trim().startsWith("Paid 3 times") && (await text(page, "#rec-card h3")) === "alice", await text(page, "#rec-chain .record-headline"));
  await page.unroute(/records\.json|\/u\/alice\.json|\/badge\/|api\.devnet\.solana\.com|program_ids\.json/);
  chain.down = "node is behind";
  await visit(page, "#u=alice");
  await page.waitForFunction(() => document.getElementById("rec-chain-asof")?.textContent.includes("did not answer"));
  check("  devnet not answering: the kept account stays, and says it is the record as it was read then", /^Solana devnet did not answer just now\. This is the program's record as it was read as of \d+ s ago\.$/.test(await text(page, "#rec-chain-asof")) && (await text(page, "#rec-chain .record-headline")).trim().startsWith("Paid 3 times"), await text(page, "#rec-chain-asof"));
  chain.down = null;
  await page.close();
  for (const path of Object.keys(files)) delete served.extra[`/${path}`];

  // fund any issue, for someone who has never been here: what they do, counted
  const fa = recorded("fund_any_issue");
  const standIn = (code) => code.replace("function client2(ids) {", "function client2(ids) {\n  const k = client2_(ids);\n  k.fundOrderWalletIx = async (args) => window.__fundOrder(args);\n  return k;\n}\nfunction client2_(ids) {");
  served.settle = standIn; await reset(); chain.simulate = { err: null, logs: ["Program log: knos2:version 1"] };
  const first = await (await world({ wallets: [["Test Wallet", WALLET]] })).newPage();
  await visit(first, "#fund");
  await first.evaluate((ixs) => { window.__fundOrder = async (args) => { const x = ixs[String(args.seq)]; return { program: x.program, data: Uint8Array.from(x.data.match(/../g), (h) => parseInt(h, 16)), accounts: x.accounts }; }; }, fa.order.ix);
  await first.waitForFunction(() => !document.getElementById("any-available").textContent.includes("Asking devnet"));
  let did = 0;
  const act = async (what) => { did++; await what(); }, began = Date.now(), sims = () => chain.calls.filter((c) => c.method === "simulateTransaction" && !c.version).length, sims0 = sims();
  await act(() => first.fill("#any-issue", "octo/widgets#7"));
  await act(() => first.fill("#any-amount", "20"));
  await act(() => first.click("#any-go"));
  await first.waitForSelector("#any-facts");
  check("fund any issue, first visit: with the terms shown and no wallet, devnet has been asked nothing about a transaction", sims() === sims0 && await gone(first, "#any-send"));
  await act(() => first.click("#any-connect"));
  await first.waitForSelector("#any-send");
  check("  connecting the wallet is enough: devnet checked the transaction by itself, once, and what would be signed is on the page", sims() === sims0 + 1 && (await text(first, "#any-steps")).startsWith("Fund the order for octo/widgets#7: 20.00 test USDC") && chain.sent.length === 0);
  await act(() => first.click("#any-send"));
  await first.waitForSelector("#any-done");
  const seconds = (Date.now() - began) / 1000;
  check(`  funded in ${did} things done on the page (two boxes, three buttons) and one approval in the wallet; ${seconds.toFixed(1)} s here against a mocked devnet`, did === 5 && chain.sent.length === 1 && (await text(first, "#any-done")).startsWith("Done."), did);
  check("  nothing was signed before \"Sign in my wallet\" was pressed: one simulation, then the wallet", chain.calls.filter((c) => !c.version).map((c) => c.method).filter((m) => m === "simulateTransaction" || m === "wallet:signAndSend").join() === "simulateTransaction,wallet:signAndSend");

  // the same issue read again in the same tab: shown at once from what was kept, and not fundable until GitHub has answered again
  let ghAnswered = 0, ghGo;
  const ghGate = new Promise((ok) => { ghGo = ok; });
  await first.route("https://api.github.com/**", async (route) => { await ghGate; ghAnswered++; return route.fallback(); });
  await first.fill("#any-amount", "40");
  await first.click("#any-go");
  await first.waitForSelector("#any-asof");
  check("fund any issue, read before: the terms are shown before GitHub answers, with their age", ghAnswered === 0 && /^Shown as of \d+ s ago\. Reading GitHub again before anything can be funded…$/.test(await text(first, "#any-asof")) && (await text(first, "#any-pay")) === "41.00", `${ghAnswered} ${await text(first, "#any-pay")}`);
  check("  and nothing can be checked or signed from what was kept", await first.isHidden("#any-next") && await gone(first, "#any-send"));
  issues["octo/widgets#7"].state = "closed";                                    // and GitHub now says something else
  ghGo();
  await first.waitForSelector("#any-result .status.bad");
  check("  GitHub's answer now takes its place: the issue was closed meanwhile, so nothing is offered", (await text(first, "#any-result")) === "octo/widgets#7 is closed. Fund an open issue." && await gone(first, "#any-facts") && await first.isHidden("#any-next"));
  issues["octo/widgets#7"].state = "open";
  await first.close();
  served.settle = (text) => text; chain.simulate = null; await reset();
}

// ---- 9. Status, Index, Pilot, Reproduce: the pages web/mounts.js fills, each true with nothing read ------------------------------------
{
  const lib = await import(pathToFileURL(join(root, "mounts.js")).href);
  const page = await plain.newPage();
  const iso = (ms) => new Date(ms).toISOString().replace(/\.\d+Z$/, "Z"), bot = { login: "github-actions[bot]" };
  const T = Date.UTC(2026, 9, 5, 12, 0, 0), line = (ago, body, user = bot, edited = ago) => ({ user, created_at: iso(T - ago * 1000), updated_at: iso(T - edited * 1000), body });
  const log = (comments, updated = T - 70_000) => ({ issue: { number: 41, html_url: "https://github.com/drexthealpha/Knos/issues/41", updated_at: iso(updated) }, comments, full: false });
  const day = [
    line(72000, `knos-relay status - - ok at=${iso(T - 70_000)} round=14 tokens=3 waiting=1 oldest=95 retried=2 refused=1`, bot, 70),
    line(18000, "knos-relay pay octo/widgets#12 0123456789abcdef ok sig=5xyz queue=4 workflow=31 wait=9 chain=2 tries=2 note=paid 20 to mona t=46"),
    line(14400, "knos-relay fund octo/widgets#14 fedcba9876543210 ok sig=4abc note=funded t=12"),
    line(10800, "knos-relay pay octo/other#3 - fail this comment cannot carry its token (deadbeef...): the token names another repository"),
    line(600, "knos-relay pay octo/other#3 1111111111111111 ok sig=zzz note=<img src=x onerror=alert(1)> t=1", { login: "mallory" }),       // anyone can comment: not the relay's
  ];
  // the words, from a log and stats.json, with no page
  const v = lib.relayView(log(day), recorded("stats_with_data"), T), fact = (view, name) => view.facts.find((f) => f[0] === name)[1].replace(/<[^>]+>/g, "");
  check("status: the relay, from its log: it ran 70 s ago, one token waits, and the day's count is the relay's own lines only", v.kind === "ok" && v.headline === "The relay ran 70 s ago. 1 token waiting, the oldest for 2 min. In 24 hours: 2 carried, 1 refused, 2 retries."
    && fact(v, "Ran in the last 10 minutes") === "Yes. It last wrote 70 s ago, at 2026-10-05 11:58:50 UTC." && fact(v, "Last round") === "2026-10-05 11:58:50 UTC; it took 14 s and looked at 3 tokens."
    && fact(v, "Tokens waiting") === "1 token, the oldest for 2 min (as of 2026-10-05 11:58:50 UTC)." && fact(v, "Carried in 24 hours") === "2 tokens." && fact(v, "Retries in 24 hours") === "2 (1 on tokens that went through in the end)."
    && fact(v, "Refused in 24 hours").startsWith("1 token.1 × this comment cannot carry its token : the token names another repository"), JSON.stringify([v.headline, v.facts]));
  const m = recorded("stats_with_data").latency.merge_to_paid;
  check("  merge to paid is stats.json's, with its sample size, or said to be missing", (m && m.n ? fact(v, "Merge to paid, measured").includes(`over ${m.n} payment`) : fact(v, "Merge to paid, measured") === "Not in this build's stats.json.")
    && fact(lib.relayView(log(day), null, T), "Merge to paid, measured") === "Not in this build's stats.json.", fact(v, "Merge to paid, measured"));
  const late = lib.relayView(log(day), null, T + 3 * 3600_000);
  check("  a relay that has written nothing for three hours is said to be down, with what to do", late.kind === "bad" && late.headline.startsWith("The relay has written nothing for 3 h: tokens posted now wait until it runs again, or relay them yourself with `knos relay`.")
    && fact(late, "Ran in the last 10 minutes").startsWith("No. It last wrote 3 h ago"), late.headline);
  const old = lib.relayView(log(day.slice(1, 4)), null, T);
  check("  a relay that writes no status line: its last round and its queue are not guessed", fact(old, "Last round") === "The log does not say: this relay writes no status line." && fact(old, "Tokens waiting") === fact(old, "Last round") && old.kind === "bad", JSON.stringify(old.facts));
  const silent = lib.relayView(log([day[4]], T - 30 * 3600_000), null, T);
  check("  a log with no line of the relay's in 24 hours says that, and when the log last changed", silent.kind === "bad" && silent.headline === "The relay has written nothing in its log in the last 24 hours (the log was last changed 2026-10-04 06:00:00 UTC). Tokens posted now wait until it runs again, or relay them yourself with `knos relay`."
    && fact(silent, "Carried in 24 hours") === "0 tokens." && fact(silent, "Refused in 24 hours") === "None.", silent.headline);
  const asked = [];
  const got = await lib.readRelayLog(async (path) => { asked.push(path); return path.includes("/comments") ? (asked.length < 4 ? Array.from({ length: 100 }, () => day[1]) : [day[2]]) : [{ number: 9, pull_request: {} }, { number: 41, html_url: "u", updated_at: "x" }]; }, T + 12_345);
  check("  the log is read as the issue labelled knos-relay and its comments since 24 hours ago, a hundred at a time", JSON.stringify(asked) === JSON.stringify(["/repos/drexthealpha/Knos/issues?labels=knos-relay&state=open&per_page=5",
    "/repos/drexthealpha/Knos/issues/41/comments?since=2026-10-04T12:00:00Z&per_page=100", "/repos/drexthealpha/Knos/issues/41/comments?since=2026-10-04T12:00:00Z&per_page=100&page=2", "/repos/drexthealpha/Knos/issues/41/comments?since=2026-10-04T12:00:00Z&per_page=100&page=3"])
    && got.comments.length === 201 && got.full === false && got.issue.number === 41 && (await lib.readRelayLog(async () => [], T)) === null, JSON.stringify(asked));

  // the page: nothing read until it is opened; then the relay's log and the canary's repository, and nobody else
  const now = Date.now(), live = (ago, body, edited = ago) => ({ user: bot, created_at: iso(now - ago * 1000), updated_at: iso(now - edited * 1000), body });
  hub.relayIssues = [{ number: 41, html_url: "https://github.com/drexthealpha/Knos/issues/41", updated_at: iso(now - 30_000) }];
  hub.relayComments = [live(72000, `knos-relay status - - ok at=${iso(now - 30_000)} round=14 tokens=3 waiting=0 oldest=0 retried=0 refused=1`, 30), live(18000, day[1].body), live(10800, day[3].body),
    live(90000 + 86400, "knos-relay pay octo/old#1 2222222222222222 ok sig=old note=two days ago t=1")];
  hub.canary = []; hub.asked.length = 0;
  await visit(page, "#pricing");
  await page.waitForTimeout(300);
  check("status: no other page asks GitHub for the relay's log or the canary", hub.asked.length === 0, hub.asked);
  await visit(page, "#status");
  await page.waitForSelector("#relay-facts dt");
  await page.waitForFunction(() => !document.getElementById("live-head").textContent.includes("Reading"));
  check("status: opened, it is shown alone under its heading, with its link marked in the bar", (await text(page, "#status > h2")) === "Relay and canary status" && await page.isVisible("#status") && await page.isHidden("#view-check") && (await page.getAttribute("nav a[aria-current=page]", "href")) === "#status");
  check("  the relay: ran in the last 10 minutes, nothing waiting, the day's carried, refused and retried, from the log's own lines", /^The relay ran \d+ s ago\. Nothing is waiting\. In 24 hours: 1 carried, 1 refused, 1 retry\.$/.test((await text(page, "#relay-head")).trim())
    && await page.$eval("#relay-head", (e) => e.classList.contains("ok")) && (await page.$$eval("#relay-facts dt", (l) => l.map((x) => x.textContent))).join("|") === "Ran in the last 10 minutes|Last round|Tokens waiting|Carried in 24 hours|Refused in 24 hours|Retries in 24 hours|Merge to paid, measured"
    && (await text(page, "#relay-facts")).includes("it took 14 s and looked at 3 tokens") && (await text(page, "#relay-facts")).includes("None (as of ") && (await page.getAttribute("#relay-note a", "href")) === "https://github.com/drexthealpha/Knos/issues/41", await text(page, "#relay-status"));
  check("  it asked GitHub three things: the log's issue, its comments of 24 hours, the canary's newest issues", hub.asked.length === 3 && hub.asked[0] === "/repos/drexthealpha/Knos/issues?labels=knos-relay&state=open&per_page=5"
    && /^\/repos\/drexthealpha\/Knos\/issues\/41\/comments\?since=\d{4}-\d\d-\d\dT\d\d:\d\d:00Z&per_page=100$/.test(hub.asked.find((a) => a.includes("/comments")) || "") && hub.asked.some((a) => a.startsWith("/repos/drexthealpha/knos-e2e/issues?state=all")), hub.asked);
  check("  the canary: a repository with no round is said to have none, and nothing is shown as live", (await text(page, "#live-head")).trim() === "The canary has not run: drexthealpha/knos-e2e has no round among its newest issues. Nothing is shown as live." && await gone(page, "#live-line"));
  check("  who answers when it fails is said: the founder alone", (await text(page, "#status-who")).includes("Today the founder alone. There is no support contract, no on-call team and no service-level agreement, and nobody else to call."));
  check("  nothing runs off the side at any width", (await overflow(page)) <= 1, await overflow(page));
  // read again: a log that is gone, then a GitHub that does not answer
  await page.evaluate(() => sessionStorage.clear());
  hub.relayIssues = [];
  await visit(page, "#status");
  await page.waitForFunction(() => document.getElementById("relay-head").textContent.includes("no open issue"));
  check("status: no log issue: that is said, and nothing about the relay", (await text(page, "#relay-head")).trim() === "drexthealpha/Knos has no open issue labelled knos-relay, so the relay's log was not found and nothing is said about the relay." && (await page.$$eval("#relay-facts dt", (l) => l.length)) === 0);
  await page.evaluate(() => sessionStorage.clear());
  hub.down = true;
  await visit(page, "#status");
  await page.waitForFunction(() => document.getElementById("relay-head").textContent.includes("was not read") && document.getElementById("live-head").textContent.includes("was not read"));
  check("status: GitHub does not answer: neither card claims anything, and the canary is not said to have stopped", (await text(page, "#relay-head")).trim() === "The relay's log was not read (GitHub said 500). Nothing is said about the relay."
    && (await text(page, "#live-head")).trim() === "The canary's round was not read (GitHub said 500). None is shown." && (await text(page, "#live-next")).includes("Whether the canary has been running could not be read.") && !(await text(page, "#live-next")).includes("has not been running")
    && await page.isVisible("#relay-again"), [await text(page, "#relay-head"), await text(page, "#live-next")]);
  hub.down = false; hub.relayIssues = [{ number: 41, html_url: "https://github.com/drexthealpha/Knos/issues/41", updated_at: iso(now - 30 * 3600_000) }]; hub.relayComments = [];
  await page.click("#relay-again");
  await page.waitForFunction(() => document.getElementById("relay-head").textContent.includes("last 24 hours"));
  check("  Read it again reads it again: a log with nothing in 24 hours says so", (await text(page, "#relay-head")).startsWith("The relay has written nothing in its log in the last 24 hours (the log was last changed ") && await page.$eval("#relay-head code", (e) => e.textContent === "knos relay"));
  hub.relayIssues = []; hub.asked.length = 0;

  // Index: the weekly table of docs/, as the build copied it
  const weekly = JSON.parse(readFileSync(join(root, "agent_weekly.json"), "utf8"));
  check("index: the build carries docs/agent_weekly.json byte for byte", readFileSync(join(root, "agent_weekly.json"), "utf8") === readFileSync(join(here, "..", "..", "docs", "agent_weekly.json"), "utf8"));
  await visit(page, "#index");
  await page.waitForSelector("#ib-table tbody tr");
  check("index: one row per agent of the file for its latest week, under the page's heading, shown alone", (await text(page, "#index > h2")) === "Agent PR Index" && (await page.$$eval("#ib-table tbody tr", (r) => r.length)) === Object.keys(weekly.agents).length
    && (await text(page, "#ib-title")) === `Agent PR Index, week of ${weekly.latest_week}` && await page.isHidden("#view-check") && (await page.getAttribute("nav a[aria-current=page]", "href")) === "#index" && hub.asked.length === 0);
  check("  it says when the sample was read, what it cannot see, and that nothing was verified through Knos", (await text(page, "#index-source")).startsWith(`Read ${weekly.read}.`) && (await page.$$eval("#index-limits li", (l) => l.length)) === weekly.limits.length
    && (await text(page, "#ib-verified")).includes("Verified: 0 this week."), await text(page, "#index-source"));
  const weeks = await page.$$eval("#ib-week option", (o) => o.map((x) => x.value));
  if (weeks.length > 1) { await page.selectOption("#ib-week", weeks[1]); check("  another week can be picked", (await text(page, "#ib-title")) === `Agent PR Index, week of ${weeks[1]}`); }
  check("  nothing runs off the side at any width", (await overflow(page)) <= 1, await overflow(page));
  served.extra["/agent_weekly.json"] = { type: "application/json", body: JSON.stringify({ agents: {} }) };
  await visit(page, "#index");
  await page.waitForSelector("#index-none");
  check("index: a file with no agent shows no table and says so", await gone(page, "#ib-table") && (await text(page, "#index-none")).includes("so no table is shown"));
  delete served.extra["/agent_weekly.json"];

  // Pilot: the price book's row, the four deliverables, and what is not true yet; no form
  await visit(page, "#pilot");
  await page.waitForSelector("#pilot-deliverables li", { state: "attached" });
  const bookRow = (await import(pathToFileURL(join(root, "price.js")).href)).priceBook((await import(pathToFileURL(join(root, "price.js")).href)).priceConstants()).find((r) => r[0] === "Pilot");
  check("pilot: who it is for, four deliverables, and the price in the price book's own words", (await text(page, "#pilot > h2")) === "The 30-day Pilot" && (await text(page, "#pilot-who")).includes("two or more suppliers")
    && (await page.$$eval("#pilot-deliverables li strong", (l) => l.map((x) => x.textContent))).join("|") === "One reconciled invoice.|A mismatch list.|A statement both sides verify.|Quantified findings."
    && (await text(page, "#pilot-price-words")) === bookRow[2] && bookRow[2].startsWith("2,500 USD, credited against year one") && (await text(page, "#pilot-price dd")) === "one buyer, two suppliers, 30 days, one reconciled invoice");
  check("  it says plainly that nobody has bought it and that there is no legal entity to invoice from", (await text(page, "#pilot-honest")) === "An offer, not a record. Nobody has bought it. Nobody has been asked. No legal entity to invoice from yet."
    && (await text(page, "#pilot-blockers")).includes("Nobody has bought it.") && (await text(page, "#pilot-blockers")).includes("There is no legal entity to invoice from yet.") && (await text(page, "#pilot-blockers")).includes("It has never been run."));
  check("  no form and nothing to type into: the page collects nothing", (await page.$$eval("#pilot form, #pilot input, #pilot textarea, #pilot select, #pilot button:not(.copy)", (l) => l.length)) === 0 && !/customer|pilot is running|signed up/i.test(await text(page, "#pilot")));
  const pilotDoc = readFileSync(join(here, "..", "..", "docs", "PILOT.md"), "utf8").replace(/\s+/g, " ");
  check("  its deliverables are the four of docs/PILOT.md, by name", lib.PILOT_DELIVERABLES.every(([name]) => pilotDoc.includes(`**${name}**`)) && pilotDoc.includes("2,500 USD for one buyer and two suppliers, for 30 days"));
  check("  nothing runs off the side at any width", (await overflow(page)) <= 1, await overflow(page));

  // Reproduce: the three lines, and the count of what the build carries
  check("reproduce: the build lists the reproductions of the repository's folder: none today", JSON.stringify(JSON.parse(readFileSync(join(root, "reproductions.json"), "utf8")))
    === JSON.stringify({ files: readdirSync(join(here, "..", "..", "reproductions")).filter((f) => f.endsWith(".json")).sort() }) && JSON.parse(readFileSync(join(root, "reproductions.json"), "utf8")).files.length === 0);
  await visit(page, "#reproduce");
  await page.waitForSelector("#repro-count");
  const reproDoc = readFileSync(join(here, "..", "..", "docs", "REPRODUCE.md"), "utf8");
  check("reproduce: none yet is said as none yet", (await page.getAttribute("#repro-count", "data-count")) === "0" && (await text(page, "#repro-count")) === "Outside reproductions so far: none yet. No capability is marked as reproduced." && await gone(page, "#repro-files"));
  check("  three lines: the one command of docs/REPRODUCE.md, the fork and run, how to send the result", (await page.$$eval("#repro-lines > li > strong:first-child", (l) => l.map((x) => x.textContent))).join("|") === "The one command.|Fork and run, signed by GitHub.|Send the result."
    && (await text(page, "#repro-command")).trim() === lib.REPRODUCE_COMMAND && reproDoc.includes(`\n${lib.REPRODUCE_COMMAND}\n`) && (await text(page, "#repro-lines")).includes("reproductions/<owner>-<repo>-<run id>.json")
    && (await page.getAttribute('#repro-lines a[href*="knos-reproduce.yml"]', "href")) === "https://github.com/drexthealpha/Knos/blob/main/examples/knos-reproduce.yml" && existsSync(join(here, "..", "..", "examples", "knos-reproduce.yml")));
  check("  shown alone, with More marked as holding it", await page.isHidden("#view-check") && (await page.getAttribute("nav a[aria-current=page]", "href")) === "#reproduce" && await page.$eval("#more", (e) => e.classList.contains("current")) && (await overflow(page)) <= 1);
  served.extra["/reproductions.json"] = { type: "application/json", body: JSON.stringify({ files: ["octo-widgets-123.json", "../evil", "<img src=x onerror=alert(1)>.json"] }) };
  await visit(page, "#reproduce");
  await page.waitForSelector("#repro-files");
  check("reproduce: a build that carries one says one, and links the file; a name that is not a file's is not counted", (await page.getAttribute("#repro-count", "data-count")) === "1" && (await text(page, "#repro-count")) === "1 reproduction from outside Knos is in this build."
    && (await page.$$eval("#repro-files a", (l) => l.map((a) => a.getAttribute("href")))).join() === "reproductions/octo-widgets-123.json");
  delete served.extra["/reproductions.json"];
  check("  a build with no list says that it does not know, never zero", lib.reproductionsOf(null) === null && lib.reproductionsOf({ files: [] }).length === 0);

  // the banner with a whole release pending, the feed the site carries, the statement's new column, and a profile
  const up = await import(pathToFileURL(join(root, "upgrade.js")).href);
  check("upgrade: every program the multisig holds is named, so a proposal for the meter or the passkey wallet is in the banner", JSON.stringify(up.programNames(ids)) === JSON.stringify({ [ids.knos_oidc]: "knos_oidc", [ids.knos_pay]: "knos_pay", [ids.knos_meter]: "knos_meter", [ids.knos_passkey]: "knos_passkey" })
    && JSON.stringify(up.programNames({ knos_pay: "P" })) === JSON.stringify({ P: "knos_pay" }));
  const feed = JSON.parse(readFileSync(join(root, "upgrades.json"), "utf8")), xml = readFileSync(join(root, "upgrades.xml"), "utf8");
  const now78 = feed.entries.find((e) => e.index === 8)?.status;          // pending until proposals 7 and 8 execute (9 October), executed after
  check("upgrade feed: the site's file lists proposals 7 and 8 as one (pending, or executed), 3 to 6 executed and 1 and 2 withdrawn, and the Atom feed says the same", ["pending", "executed"].includes(now78)
    && feed.pending === (now78 === "pending" ? 2 : 0) && JSON.stringify(feed.entries.map((e) => [e.index, e.program, e.status])) === JSON.stringify([[8, "knos_pay", now78], [7, "knos_oidc", now78],
      [6, "knos_passkey", "executed"], [5, "knos_meter", "executed"], [4, "knos_pay", "executed"], [3, "knos_oidc", "executed"], [2, "knos_pay", "replaced"], [1, "knos_oidc", "replaced"]])
    && feed.entries.every((e) => xml.includes(`upgrade proposal ${e.index} is ${e.status}`)) && (xml.match(/<entry>/g) || []).length === 8 && feed.entries.every((e) => e.program_address === ids[e.program]));
  const st = await import(pathToFileURL(join(root, "statements.js")).href);
  const scope = { type: "knos.audit-export", version: 1, program: ids.knos_pay, owner_id: 5001, from: "2026-09-01", to: "2026-09-30", wallets: "", partial: 0 };
  const row = Object.fromEntries(st.AUDIT_COLUMNS.filter((c) => !["seq", "prev"].includes(c)).map((c) => [c, c.endsWith("_units") ? 0 : c === "currency" ? "test USDC" : ""]));
  const withIt = await st.auditExport(scope, [{ ...row, authorised_by: "gh:555000 (spender)" }, { ...row, authorised_by: "wallet:" + WALLET }], "csv"), without = await st.auditExport(scope, [Object.fromEntries(Object.entries(row).filter(([c]) => c !== "authorised_by"))], "csv");
  check("statement: an export says who authorised each order's money, in the column after the commenter; a file written before the column keeps the columns it had", withIt.text.split("\n")[0].split(",").indexOf("authorised_by") === st.AUDIT_COLUMNS.indexOf("commenter_id") + 1
    && withIt.text.split("\n")[1].split(",")[st.AUDIT_COLUMNS.indexOf("authorised_by")] === "gh:555000 (spender)" && withIt.text.split("\n")[2].includes(`wallet:${WALLET}`) && !without.text.includes("authorised_by")
    && without.text.split("\n")[0].split(",").length === st.AUDIT_COLUMNS.length - 1 && withIt.head !== without.head, withIt.text.split("\n")[0]);
  await page.close();
}

// ---- the pages of 0.3.16, mounted: the round on the first screen, Check an invoice, Verify, Playground, Terms, and Status's five states ----
{
  const page = await plain.newPage();
  const demo = JSON.parse(readFileSync(join(root, "demo_data.json"), "utf8"));
  await visit(page);
  await page.waitForSelector("#demo .kd-go");
  check("demo: the round is mounted in the first screen, under the hero, and says which program ids it replays", await page.isVisible("#demo") && await page.isVisible("#view-check") && (await page.$$eval("#demo .k-step", (l) => l.length)) === 6
    && (await text(page, "#demo .kd-mark")).trim() === `A real devnet round, replayed (${demo.ids} program ids, ${demo.date.replace(/^(\d+ \w{3})\w*/, "$1")}).` && ["staging", "public"].includes(demo.ids), await text(page, "#demo .kd-mark"));
  await page.click("#demo .kd-go");
  check("  one press funds the recorded order, and links its transaction", (await text(page, "#demo .kd-say")) === `Funded: ${demo.fund.amount} test USDC held; fee ${demo.fund.fee}, charged under the 0.3.14 fee.` && (await page.getAttribute("#demo .kd-scene a", "href")) === `https://explorer.solana.com/tx/${demo.fund.tx}?cluster=devnet`);
  check("  the front door is above the round once it is mounted", await page.isVisible("#front-door [data-fd=run]") && (await overflow(page)) <= 1);
  for (const from of ['#nav > a[href="#demo"]', "#hero-cue"]) {
    await page.evaluate(() => { document.activeElement.blur(); scrollTo(0, 0); });
    await page.click(from);
    const there = await page.waitForFunction(() => { const top = document.getElementById("demo").getBoundingClientRect().top; return document.activeElement?.classList.contains("kd-go") && top >= 0 && top < innerHeight / 3; }, null, { timeout: 5000 }).then(() => true, () => false);
    check(`  ${from === "#hero-cue" ? "the cue at the foot of the hero" : "Demo in the bar"} brings the round under the bar and puts the focus on its first action`, there && await page.evaluate(() => location.hash === "#demo"),
      await page.evaluate(() => [document.activeElement?.className, document.getElementById("demo").getBoundingClientRect().top]));
  }
  check("  the cue is an arrow with a name, no word of the forty, and stays inside the hero", (await text(page, "#hero-cue")).trim() === "" && (await page.getAttribute("#hero-cue", "aria-label")) === "The demo, below" && await page.evaluate(() => { scrollTo(0, 0); const c = document.getElementById("hero-cue").getBoundingClientRect(), h = document.querySelector(".hero").getBoundingClientRect(), b = document.querySelector(".hero .actions").getBoundingClientRect(); return c.bottom <= h.bottom + 1 && c.top >= b.bottom; }));
  check("  no page but the playground's has asked GitHub for the playground's tasks", hub.playgroundAsked === 0, hub.playgroundAsked);

  // Check an invoice: one line, read from the mocked GitHub; the statement, its one number and its hash
  await visit(page, "#shadow");
  await page.waitForSelector("#shadow textarea");
  check("shadow: shown alone, with its link marked in the bar", await page.isVisible("#shadow") && await page.isHidden("#view-check") && (await page.getAttribute("nav a[aria-current=page]", "href")) === "#shadow");
  const before = githubReads;
  await page.fill("#shadow textarea", "pr,amount,supplier\nhttps://github.com/octo/widgets/pull/12,120.00,acme\nhttps://github.com/octo/nothing/pull/3,80.00,acme\n");
  await page.click('#shadow [data-sh="run"]');
  await page.waitForSelector('#shadow [data-sh="share"]');
  const sh = await page.evaluate(() => ({ share: document.querySelector('#shadow [data-sh="share"]').textContent, of: document.querySelector('#shadow [data-sh="of"]').textContent, hash: document.querySelector('#shadow [data-sh="hash"]').textContent,
    steps: [...document.querySelectorAll('#shadow [data-sh="steps"] li')].map((li) => li.dataset.class), rows: document.querySelectorAll("#shadow .sh-result tbody tr").length, budget: document.querySelector('#shadow [data-sh="budget"]').textContent }));
  check("  two lines checked against GitHub: each gets a class, the share in dispute is one number, the statement has a hash", sh.steps.length === 2 && sh.steps.every(Boolean) && sh.steps[1] === "unreadable" && /^\d+(\.\d+)?%$/.test(sh.share.trim()) && sh.of.includes("200.00 billed")
    && /^sha256 [0-9a-f]{64}$/.test(sh.hash.trim()) && sh.rows === 6 && githubReads > before, JSON.stringify(sh));
  check("  it says the three limits, and runs off no side", (await text(page, "#shadow .sh-result")).includes("A failed check is not proof of bad work.") && (await text(page, "#shadow .sh-result")).includes("Shadow mode changes nothing and holds no money.") && (await overflow(page)) <= 1);

  // Verify: the builders' page, with this build's knos-oidc address and a sample token decoded in the page
  await visit(page, "#verifier");
  await page.waitForSelector("#vf-program");
  const vf = await import(pathToFileURL(join(root, "verifier.js")).href);
  check("verifier: shown alone; the program is this build's knos-oidc; three calls on cards; every issuer of the table", await page.isVisible("#verifier") && await page.isHidden("#view-check") && (await text(page, "#vf-program")).trim() === ids.knos_oidc
    && (await page.$$eval("#vf-calls .k-card[data-tilt]", (l) => l.length)) === vf.CALLS.length && (await text(page, "#vf-sentence")) === vf.SENTENCE && (await text(page, "#vf-who")) === "No outside program reads it yet.");
  await page.click("#vf-sample");
  await page.waitForSelector("#vf-claims tbody tr");
  check("  a sample token is decoded, and said to be decoded, not verified", (await text(page, "#vf-verdict")).trim() === "Decoded, not verified." && (await page.$$eval("#vf-claims tbody tr", (l) => l.length)) > 3 && (await overflow(page)) <= 1);

  // Playground: GitHub is asked when the page is opened, and not before; a funded task and one still waiting
  served.extra["/bounties.json"] = { type: "application/json", body: JSON.stringify({ bounties: [{ repository: "drexthealpha/knos-playground", issue: 4, amount: 5_000_000, decimals: 6, currency: "test USDC" }] }) };
  served.extra["/outsiders.json"] = { type: "application/json", body: JSON.stringify({ measured: true, funders: 0, repositories: 0, payees: 0, funders_in_knos_repositories_faucet: 0, definitions: {} }) };
  hub.playground = [{ number: 4, title: "Count the words", state: "open", user: { login: "someone" } }, { number: 5, title: "Count the lines", state: "open", user: { login: "someone" } }, { number: 6, title: "a pull request", state: "open", pull_request: {} }];
  await visit(page, "#playground");
  await page.waitForSelector("#pg-tasks tbody tr");
  const pg = await import(pathToFileURL(join(root, "playground.js")).href);
  check("playground: opened, it asks GitHub once and lists the open tasks: one funded on devnet, one waiting; a pull request is not a task", hub.playgroundAsked === 1 && await page.isVisible("#playground") && await page.isHidden("#view-check")
    && JSON.stringify(await page.$$eval("#pg-tasks tbody tr", (l) => l.map((r) => [r.dataset.issue, r.dataset.state]))) === JSON.stringify([["5", "opened"], ["4", "funded"]]) && (await text(page, '#pg-tasks tr[data-issue="4"]')).includes("Funded: 5 test USDC")
    && (await page.getAttribute("#pg-fund", "href")) === pg.fundUrl() && (await page.getAttribute("#pg-take", "href")) === "https://github.com/drexthealpha/knos-playground/issues/4");
  check("  the three outside counts are zeros that were counted, never added together", (await page.getAttribute("#pg-counts", "data-measured")) === "true" && (await text(page, "#pg-funders")).trim() === "0 outside funders" && (await text(page, "#pg-counts")).includes("Add none of them together.") && (await overflow(page)) <= 1);
  delete served.extra["/bounties.json"]; delete served.extra["/outsiders.json"]; hub.playground = [];

  // Terms: the registry the build carries, newest version of each template on a card
  const registry = JSON.parse(readFileSync(join(root, "terms", "index.json"), "utf8")), names = [...new Set(registry.templates.map((t) => t.name))];
  await visit(page, "#terms");
  {
    await page.waitForSelector("#terms-list .k-card");
    const cards = await page.$$eval("#terms-list .k-card", (l) => l.map((c) => [c.dataset.template, c.querySelector(".terms-hash").textContent.trim(), c.querySelector("a").getAttribute("href")]));
    check("terms: shown alone; one card per template of the registry, each with its hash and its file", await page.isVisible("#terms") && await page.isHidden("#view-check") && cards.length === names.length
      && cards.every(([name, hash, href]) => registry.templates.some((t) => t.name === name && t.hash === hash && href === `terms/${t.name}/${t.version}.json`) && existsSync(join(root, href))), JSON.stringify(cards));
    const one = registry.templates.find((t) => t.name === cards[0][0] && t.hash === cards[0][1]);
    await page.fill("#terms-paste", one.hash); await page.click("#terms-which");
    await page.waitForFunction(() => document.getElementById("terms-answer").dataset.found === "yes");
    check("  a pasted hash finds its template and version; every published version is in the table", (await text(page, "#terms-answer")).includes(`${one.name} version ${one.version}`) && (await page.$$eval("#terms-versions tbody tr", (l) => l.length)) === registry.templates.length && (await overflow(page)) <= 1);
  }

  // Status: the newest payment the relay carried, in the five states, and the relay's last rounds
  const now = Date.now(), iso = (ms) => new Date(ms).toISOString().replace(/\.\d+Z$/, "Z"), bot = { login: "github-actions[bot]" }, t0 = Math.floor(now / 1000) - 600;
  const said = (ago, body, edited = ago) => ({ user: bot, created_at: iso(now - ago * 1000), updated_at: iso(now - edited * 1000), body });
  hub.relayIssues = [{ number: 41, html_url: "https://github.com/drexthealpha/Knos/issues/41", updated_at: iso(now - 30_000) }];
  hub.relayComments = [said(600, `knos-relay pay octo/widgets#7 ${"ab".repeat(8)} ok sig=${"5".repeat(88)} queue=3 workflow=20 wait=4 chain=6 tries=1 queued_at=${t0} seen_at=${t0 + 3} sent_at=${t0 + 5} confirmed_at=${t0 + 9} note=paid t=12`),
    said(7200, [`knos-relay status - - ok at=${iso(now - 30_000)} round=14 tokens=3 waiting=0 oldest=0 retried=0 refused=0`, `knos-relay round octo/widgets#7 abababab ok order=${unique(77)} state=paid seconds=29 kind=pay`,
      "knos-relay round octo/widgets#9 cdcdcdcd ok order=- state=funded seconds=12 kind=fund"].join("\n"), 30)];
  hub.canary = [];
  await page.evaluate(() => sessionStorage.clear());
  await visit(page, "#status");
  await page.waitForSelector("#relay-latest .k-step");
  const states = await page.$$eval("#relay-latest .k-step", (l) => l.map((li) => [li.dataset.step, li.dataset.state]));
  check("status: the newest payment carried is shown in the five states, each reached one with its time; finalized is not in the relay's log, and is not claimed", JSON.stringify(states) === JSON.stringify([["received", "done"], ["accepted", "done"], ["submitted", "done"], ["confirmed", "done"], ["finalized", "idle"]])
    && (await text(page, '#relay-latest .k-step[data-step="finalized"]')).includes("not in the log") && (await text(page, '#relay-latest .k-step[data-step="confirmed"]')).includes(", 4 s") && (await text(page, "#relay-latest .k-kicker")).includes("octo/widgets#7"), JSON.stringify(states));
  check("  and the relay's last rounds, newest first, each with its state and its seconds", JSON.stringify(await page.$$eval("#relay-rounds-table tbody tr", (l) => l.map((r) => [...r.children].slice(0, 4).map((c) => c.textContent.trim()))))
    === JSON.stringify([["octo/widgets#7", "pay", "paid", "29"], ["octo/widgets#9", "fund", "funded", "12"]]) && (await page.getAttribute("#relay-rounds-table a", "href")) === `https://explorer.solana.com/address/${unique(77)}?cluster=devnet` && (await overflow(page)) <= 1);
  hub.relayIssues = []; hub.relayComments = [];
  await page.evaluate(() => sessionStorage.clear());
  await page.close();
}

// @@END

await browser.close(); server.close();
check("no console errors", errors.length === 0, errors);
check("nothing was asked of anyone but this page, GitHub and devnet", strangers.length === 0, strangers);
