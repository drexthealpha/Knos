// node sdk/settle/test.mjs
// The JavaScript client against the fixtures the Python client wrote: every address, audience, fee, instruction,
// account reader and transaction must match byte for byte, for both deployments. Then what the client adds for a
// browser: the wallets it can ask, with stand-ins for each kind. Exit 1 on the first mismatch.
import { existsSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { format } from "node:util";
import * as knos from "./index.js";

const here = dirname(fileURLToPath(import.meta.url));
const fx = JSON.parse(readFileSync(join(here, "fixtures.json"), "utf8"));
const i = fx.inputs, k = knos.client(fx.programs);
let n = 0;

function same(name, got, want) {
  n++;
  const text = (v) => JSON.stringify(v, (_k, x) => (typeof x === "bigint" ? `${x}n` : x));
  if (text(got) !== text(want)) {
    console.error(`MISMATCH ${name}\n  got  ${text(got)}\n  want ${text(want)}`);
    process.exit(1);
  }
}
const plain = (ix) => ({ program: ix.program, data: knos.hex(ix.data),
  accounts: ix.accounts.map((a) => ({ pubkey: a.pubkey, signer: a.signer, writable: a.writable })) });
const throws = async (name, f) => { let threw = false; try { await f(); } catch { threw = true; } same(name, threw, true); };

// ==== the first deployment ==========================================================================================
// base58 and the curve check
same("b58 round trip", knos.b58(knos.unb58(i.funder)), i.funder);
same("system program", knos.b58(new Uint8Array(32)), knos.SYSTEM);

// addresses
same("auth", await k.auth(), fx.addresses.auth);
same("vault", await k.vault(i.mint), fx.addresses["vault(mint)"]);
same("faucet mint", await k.faucetMint(), fx.addresses.faucet_mint);
same("job (own)", await k.job(i.repo_id, i.issue), fx.addresses["job(repo, issue) own"]);
same("job (wallet)", await k.job(i.repo_id, i.issue, i.funder), fx.addresses["job(repo, issue, funder)"]);
same("due", await k.due(i.author_id, i.mint), fx.addresses["due(author, mint)"]);
same("rep", await k.rep(i.author_id), fx.addresses["rep(author)"]);
same("rate", await k.rate(i.repo_id), fx.addresses["rate(repo)"]);
same("ata", await knos.ata(i.address, i.mint), fx.addresses["ata(address, mint)"]);
same("fee account", await knos.ata(knos.FEE_OWNER, i.mint), fx.addresses["fee_account(mint)"]);

// audiences, the repository hash, fees
same("fund merge", knos.fundAudience(i.issue, i.amount), fx.audiences["fund merge"]);
same("fund tests", knos.fundAudience(i.issue, i.amount, knos.TESTS, i.checks, 14 * 86400, 86400), fx.audiences["fund tests"]);
same("pay merge", knos.payAudience(i.repo_id, i.issue, i.author_id, "a".repeat(40)), fx.audiences["pay merge"]);
same("pay tests", knos.payAudience(i.repo_id, i.issue, i.author_id, "a".repeat(40), i.checks, knos.TESTS), fx.audiences["pay tests"]);
same("veto", knos.vetoAudience(i.repo_id, i.issue), fx.audiences.veto);
same("claim", knos.claimAudience(i.address), fx.audiences.claim);
same("wf repo hash", knos.hex(await knos.wfRepoHash(i.wf_repo)), fx.wf_repo_hash);
for (const [amount, fee] of Object.entries(fx.fees)) same(`fee of ${amount}`, knos.feeOf(Number(amount)), fee);

// instructions
const base = { funder: i.funder, funderToken: i.funder_token, mint: i.mint, repoId: i.repo_id, issue: i.issue,
  amount: i.amount, wfRepo: i.wf_repo, wfSha: i.wf_sha };
same("fund merge ix", plain(await k.fundIx(base)), fx.instructions["pay.fund merge"]);
same("fund tests ix", plain(await k.fundIx({ ...base, mode: knos.TESTS, checksHex: i.checks, workS: 7 * 86400, reviewS: 86400 })),
  fx.instructions["pay.fund tests"]);
same("veto ix", plain(k.vetoIx(i.funder, fx.addresses["job(repo, issue, funder)"])), fx.instructions["pay.veto (wallet)"]);
same("create ata ix", plain(await knos.createAtaIx(i.relayer, i.address, i.mint)), fx.instructions.create_ata);

// the verifier's instructions (the same five in both deployments), at the first deployment's address
const tid1 = knos.unhex(i.token_id), n1 = BigInt(i.n2048);
same("token id is 32 bytes", (await knos.tokenId(i.jwt)).length, 32);
same("v1 token account", await k.oidc.tokenPda(i.payer, tid1), fx.addresses["token(payer, token_id)"]);
same("v1 key account", await k.oidc.keyPda(knos.GITHUB, n1), fx.addresses["key(github, n2048)"]);
same("v1 rotate audience", await knos.rotateAudience(knos.GITHUB, n1), fx.audiences.rotate);
const w1 = await k.oidc.writeIxs(i.payer, tid1, i.jwt);
same("v1 write, first chunk", plain(w1[0]), fx.instructions["oidc.write (first chunk)"]);
same("v1 write, last chunk", plain(w1.at(-1)), fx.instructions["oidc.write (last chunk)"]);
same("v1 step", plain(await k.oidc.stepIx(i.payer, tid1, fx.addresses["key(github, n2048)"], 8)), fx.instructions["oidc.step"]);
same("v1 close", plain(await k.oidc.closeIx(i.payer, tid1)), fx.instructions["oidc.close"]);
same("v1 register key", plain(await k.oidc.registerKeyIx(i.payer, knos.GITHUB, n1)), fx.instructions["oidc.register_key"]);
same("v1 register key, attested", plain(await k.oidc.registerKeyIx(i.payer, knos.GITHUB, n1, i.token_account)), fx.instructions["oidc.register_key (attested)"]);
same("v1 key params", plain(await k.oidc.keyParamsIx(i.payer, knos.GITHUB, n1)), fx.instructions["oidc.key_params"]);

// account layouts
const job = new Uint8Array(256);
const dv = new DataView(job.buffer);
job[0] = 2; job[1] = 1; job[2] = 1;
dv.setBigUint64(8, BigInt(i.repo_id), true); dv.setBigUint64(16, BigInt(i.issue), true); dv.setBigUint64(24, BigInt(i.amount), true);
dv.setBigInt64(48, 1790000000n, true); dv.setBigUint64(56, BigInt(i.author_id), true);
job.set(knos.unb58(i.funder), 88); job.set(knos.unb58(i.mint), 120); job.set(new TextEncoder().encode(i.wf_sha), 216);
const parsed = knos.parseJob(job);
same("job layout", [parsed.state, parsed.mode, parsed.tokenFunded, parsed.repoId, parsed.issue, parsed.amount, parsed.payAfter,
  parsed.authorId, parsed.funder, parsed.mint, parsed.wfSha], ["proven", 1, true, i.repo_id, i.issue, i.amount, 1790000000,
  i.author_id, i.funder, i.mint, i.wf_sha]);
same("job of the wrong size", knos.parseJob(new Uint8Array(255)), null);
const due = new Uint8Array(48);
new DataView(due.buffer).setBigUint64(0, 4875000n, true); new DataView(due.buffer).setBigUint64(8, BigInt(i.author_id), true);
due.set(knos.unb58(i.mint), 16);
same("due layout", knos.parseDue(due), { amount: 4875000, userId: i.author_id, mint: i.mint });
const pd = new Uint8Array(60); pd[0] = 3;
same("immutable program", knos.upgradeAuthority(pd), null);
pd[12] = 1; pd.set(knos.unb58(i.funder), 13);
same("upgradeable program", knos.upgradeAuthority(pd), i.funder);
same("not a program-data account", knos.upgradeAuthority(new Uint8Array(60)), undefined);
same("no account at all", knos.upgradeAuthority(null), undefined);

// the transaction a wallet signs: header, the payer first, then the accounts of each kind in the order of their bytes
const tx = knos.serializeTx([await knos.createAtaIx(i.funder, i.funder, i.mint), await k.fundIx(base)], i.funder, i.mint);
same("tx: one empty signature", [tx[0], knos.hex(tx.slice(1, 65))], [1, "00".repeat(64)]);
same("tx: header", [...tx.slice(65, 68)], [1, 0, 6]);
same("tx: accounts", tx[68], 11);
same("tx: payer first", knos.b58(tx.slice(69, 101)), i.funder);
if (process.argv[2]) writeFileSync(process.argv[2], Buffer.from(tx));
const first = n;

// ==== the second deployment =========================================================================================
const s = fx.second, j = s.inputs, v2 = knos.v2, k2 = v2.client(s.programs);
const tid = knos.unhex(j.token_id), n2048 = BigInt(j.n2048), n4096 = BigInt(j.n4096);
const terms = v2.termsJson(j.terms), termsTests = v2.termsJson(j.terms_tests);
const th = knos.hex(await v2.termsHash(terms)), thTests = knos.hex(await v2.termsHash(termsTests));

// constants, error words, issuers
for (const [name, want] of Object.entries(s.constants)) same(`constant ${name}`, name in v2 ? v2[name] : knos[name], want);
same("the words for every error code", Object.fromEntries(Object.entries(v2.ERRORS).map(([c, w]) => [String(c), w])), s.errors);
same("what a refusal means", v2.errorWords({ InstructionError: [1, { Custom: 93 }] }), s.errors["93"]);
same("an error that is not the program's has no words", [v2.errorWords({ InstructionError: [0, "InvalidArgument"] }), v2.errorWords(null)], [null, null]);
for (const id of Object.keys(s.issuers)) same(`issuer ${id}`, { issuer: knos.ISSUERS[id], jwks: knos.JWKS[id] }, s.issuers[id]);

// addresses
const bal = await k2.balance(j.owner_id, j.authority, j.mint), bal22 = await k2.balance(j.owner_id, j.authority, j.mint22);
const faucetBal = await k2.faucetBalance(j.owner_id);
const jobBal = await k2.job(j.repo_id, j.issue, bal), jobWallet = await k2.job(j.repo_id, j.issue, j.funder);
const key2048 = await k2.oidc.keyPda(knos.GITHUB, n2048), key4096 = await k2.oidc.keyPda(knos.GITLAB, n4096);
const orderTerms = v2.termsJson(j.order_terms), oth = knos.hex(await v2.termsHash(orderTerms)), saltBytes = knos.unhex(j.salt);
const scope = await v2.scopeOf(j.repo_id, j.issue), scopePrivate = await v2.scopeOf(j.repo_id, j.issue, saltBytes);
const orderW = await k2.orderPda(scope, j.funder, 0), orderB = await k2.orderPda(scope, bal, 3), orderP = await k2.orderPda(scopePrivate, j.funder, 1);
const verifiedToken = knos.unhex(s.accounts["token (verified)"].data);
const addresses = {
  "order(scope, wallet, seq 0)": orderW, "order(scope, balance, seq 3)": orderB, "order(private scope, wallet, seq 1)": orderP,
  "ov(order)": await k2.ovPda(orderW), "balx(balance)": await k2.balxPda(bal), "plan(owner)": await k2.planPda(j.owner_id),
  "used(jwt)": await k2.usedPda(j.jwt), "used(token account data)": await k2.usedPda(verifiedToken), "used(signature hash)": await k2.usedPda(await v2.sigHash(j.jwt)),
  "key(issuer url, n2048)": await k2.oidc.keyPda(j.url, n2048), "key(private, n2048)": await k2.oidc.keyPda(j.url, n2048, j.authority), "iss(url)": await k2.oidc.issPda(j.url),
  "hb(order)": await k2.hbPda(orderW), "done(order, pr 40)": await k2.donePda(orderB, 40), "assign(order, payee)": await k2.assignPda(orderW, j.payee_id),
  auth: await k2.auth(), "vault(mint)": await k2.vault(j.mint), faucet_mint: await k2.faucetMint(), "balance(owner, authority, mint)": bal,
  "faucet_balance(owner)": faucetBal, "baltok(balance)": await k2.baltok(bal), "job(repo, issue, balance)": jobBal,
  "job(repo, issue, funder)": jobWallet, "bind(payee)": await k2.bind(j.payee_id), "rep(payee)": await k2.rep(j.payee_id),
  "pair(payee, owner id)": await k2.pair(j.payee_id, j.owner_id), "pair(payee, funder)": await k2.pair(j.payee_id, j.funder),
  "rate(repo)": await k2.rate(j.repo_id), pause: await k2.pause(), "ata(address, mint)": await knos.ata(j.address, j.mint),
  "ata(address, mint22) token-2022": await knos.ata(j.address, j.mint22, knos.TOKEN_2022), "fee_account(mint)": await knos.ata(knos.FEE_OWNER, j.mint),
  "token(payer, token_id)": await k2.oidc.tokenPda(j.payer, tid), "key(github, n2048)": key2048, "key(gitlab, n4096)": key4096,
};
same("second: every address has a check", Object.keys(addresses).sort(), Object.keys(s.addresses).sort());
for (const [name, got] of Object.entries(addresses)) same(`second address ${name}`, got, s.addresses[name]);
same("the two deployments derive different addresses", (await k.auth()) !== (await k2.auth()), true);

// terms, hashes, fees
same("terms json", new TextDecoder().decode(terms), s.terms.json);
same("terms hash", th, s.terms.hash);
same("terms json, with characters outside ASCII", new TextDecoder().decode(termsTests), s.terms["json tests"]);
same("terms hash, tests mode", thTests, s.terms["hash tests"]);
same("terms json: every character that is written as an escape", new TextDecoder().decode(v2.termsJson(s.terms.odd)), s.terms["json odd"]);
same("terms in another key order give the same bytes", knos.hex(v2.termsJson(Object.fromEntries(Object.entries(j.terms).reverse()))), knos.hex(terms));
await throws("terms over 600 bytes are refused", () => v2.termsJson({ ...j.terms, paths: Array(60).fill("a-long-glob/**") }));
same("hashes", { wf_repo_hash: knos.hex(await v2.wfRepoHash(j.wf_repo)), "funder_key(wallet)": knos.hex(await v2.funderKey(j.funder)),
  "funder_key(owner id)": knos.hex(await v2.funderKey(j.owner_id)), "token_id(jwt)": knos.hex(await knos.tokenId(j.jwt)),
  "key_hash(n2048)": knos.hex(await knos.keyHash(n2048)), "key_hash(n4096)": knos.hex(await knos.keyHash(n4096)),
  "scope(repo, issue)": knos.hex(scope), "scope(repo, issue, salt)": knos.hex(scopePrivate), "sig_hash(jwt)": knos.hex(await v2.sigHash(j.jwt)),
  "sig_hash(token account data)": knos.hex(await v2.sigHash(verifiedToken)), "issuer_hash(url)": knos.hex(await knos.issuerHash(j.url)), "order terms": oth,
  "private_fund_terms(scope, terms)": knos.hex(await v2.privateFundTerms(scopePrivate, oth)) }, s.hashes);
same("a private order's fund terms from bytes and from hex are the same", knos.hex(await v2.privateFundTerms(knos.hex(scopePrivate), knos.unhex(oth))), s.hashes["private_fund_terms(scope, terms)"]);
for (const [amount, fee] of Object.entries(s.fees)) same(`second: fee of ${amount}`, v2.feeOf(Number(amount)), fee);

// audiences
const fundAud = v2.fundAudience(j.issue, j.amount, v2.MERGE, th, bal);
const payAud = v2.payAudience(j.repo_id, j.issue, j.payee_id, j.head_sha, th, v2.MERGE, j.address);
const payAudNone = v2.payAudience(j.repo_id, j.issue, j.payee_id, j.head_sha, thTests, v2.TESTS);
const bound = v2.readBind(knos.unhex(s.accounts.bind.data));
const opts = (name) => ({ none: v2.opts(), "merge, reserve 7": v2.opts({ flags: v2.F_NEUTRAL, reserveDays: 7 }),
  everything: v2.opts({ flags: v2.F_NEUTRAL | v2.F_STANDING, holdbackBps: 5000, warrantyDays: 90, killBps: 2000, reserveDays: 30, rate: 2_500_000, arbiterId: 9_001,
    judgeRepoId: 70_000_001, salted: true }), private: v2.opts({ flags: v2.F_PRIVATE | v2.F_NEUTRAL, salted: true, judgeRepoId: 70_000_001 }) })[name];
const one = [[j.payee_id, 10_000, j.address]], many = [[j.payee_id, 6_000, j.address], [j.maintainer_id, 3_000, null], [9, 1_000, j.wallet]];
const audiences = {
  "order fund": v2.orderFundAudience(j.issue, j.amount, v2.MERGE, oth, bal, 14 * 86400, 3, opts("merge, reserve 7")),
  "order fund, no options": v2.orderFundAudience(j.issue, j.amount, v2.TESTS, oth, bal),
  "order pay, one payee": v2.orderPayAudience(orderW, j.head, oth, v2.MERGE, 12, one),
  "order pay, three payees": v2.orderPayAudience(orderB, j.head, oth, v2.TESTS, 40, many),
  "payees_of(one)": v2.payeesOf(v2.orderPayAudience(orderW, j.head, oth, v2.MERGE, 12, one)),
  "payees_of(three)": v2.payeesOf(v2.orderPayAudience(orderB, j.head, oth, v2.TESTS, 40, many)), "payees_text(three)": v2.payeesText(many),
  "order_destination(bind, address)": v2.orderDestination(bound, j.address), "order_destination(bind, no address)": v2.orderDestination(bound, null),
  "order_destination(no bind, address)": v2.orderDestination(null, j.address), "order_destination(no bind, no address)": v2.orderDestination(null, null),
  "rotate (issuer url)": await knos.rotateAudience(j.url, n2048),
  "order fund, private": v2.orderFundAudience(0, j.amount, v2.MERGE, knos.hex(await v2.privateFundTerms(scopePrivate, oth)), bal, 14 * 86400, 3, opts("private")),
  "rule, three payees": v2.ruleAudience(orderB, many), "org bind": v2.orgBindAudience(j.wallet), take: v2.takeAudience(orderW, j.payee_id, 7),
  cancel: v2.cancelAudience(orderB), revert: v2.revertAudience(orderB, j.head), "payees_of(rule)": v2.payeesOf(v2.ruleAudience(orderB, many)),
  fund: fundAud, "fund tests, 30 days": v2.fundAudience(j.issue, j.amount, v2.TESTS, thTests, faucetBal, 30 * 86400),
  "pay to an address": payAud, "pay, no address": payAudNone, bind: v2.bindAudience(j.wallet),
  rotate: await knos.rotateAudience(knos.GITHUB, n2048), "rotate 4096": await knos.rotateAudience(knos.GITLAB, n4096),
  "named_balance(fund)": v2.namedBalance(fundAud), "destination(bind, pay to an address)": v2.destination(bound, payAud),
  "destination(no bind, pay to an address)": v2.destination(null, payAud), "destination(no bind, pay, no address)": v2.destination(null, payAudNone),
};
same("second: every audience has a check", Object.keys(audiences).sort(), Object.keys(s.audiences).sort());
for (const [name, got] of Object.entries(audiences)) same(`second audience ${name}`, got, s.audiences[name]);

// the verifier's arithmetic and its reading of a key set
same("step plan", { 2048: knos.stepPlan(2048), 4096: knos.stepPlan(4096) }, s.oidc.step_plan);
same("key params: three moduli", Object.keys(s.oidc.key_params).length, 3);
for (const [nn, want] of Object.entries(s.oidc.key_params)) {
  const p = knos.keyParams(BigInt(nn));
  same(`key params of ${nn.slice(0, 6)}...${nn.slice(-7)}`, { n0inv: p.n0inv, r2: knos.hex(p.r2) }, want);
}
same("jwks keys", knos.jwksKeys(s.oidc.jwks).map(([kid, nn]) => [kid, "0x" + nn.toString(16)]), s.oidc.jwks_keys);
await throws("a 1024-bit modulus is refused", () => knos.modulusBytes(1n << 1023n));
await throws("a token over 8192 bytes is refused", () => k2.oidc.writeIxs(j.payer, tid, "x".repeat(8193)));

// accounts: what each reader makes of the bytes
const snake = (o) => (o && typeof o === "object" && !Array.isArray(o)
  ? Object.fromEntries(Object.entries(o).map(([name, v]) => [name.replace(/[A-Z]/g, (c) => "_" + c.toLowerCase()), v])) : o);
const readers = {
  job: (raw) => { const got = v2.readJob(raw); if (got) delete got.funder; return snake(got); },
  balance: (raw) => snake(v2.readBalance(raw)), bind: (raw) => snake(v2.readBind(raw)), rep: (raw) => snake(v2.readRep(raw)),
  pause: v2.readPause, rate: v2.readRate,
  order: (raw) => { const got = v2.readOrder(raw); if (got) { delete got.funder; delete got.tokenProgram; delete got.faucet; } return snake(got); },
  balx: (raw) => snake(v2.readBalx(raw)), plan: (raw) => snake(v2.readPlan(raw)), iss: v2.readIss,
  holdback: v2.readHoldback, assign: (raw) => v2.readAssign(raw), marker: v2.readMarker,
  token: (raw) => { const t = knos.readToken(raw); return t && { stage: t.stage, issuer: t.issuer, done: t.done, exp: t.exp, key: t.key, payer: t.payer, payload: knos.hex(t.payload) }; },
};
for (const [name, a] of Object.entries({ ...s.accounts, ...s["order accounts"] })) same(`account ${name}`, readers[a.reader](a.data === null ? null : knos.unhex(a.data)), a.read);
const oW = v2.readOrder(knos.unhex(s["order accounts"]["order (open, from a wallet, public)"].data));
const oB = v2.readOrder(knos.unhex(s["order accounts"]["order (warranty, from a Balance, standing, token-2022)"].data));
const oP = v2.readOrder(knos.unhex(s["order accounts"]["order (held, private)"].data));
same("an order says whose money it is and which token program holds it", [oW.funder, oB.funder, oB.tokenProgram, oW.tokenProgram, oB.faucet, oP.state, oB.state],
  [j.funder, j.owner_id, knos.TOKEN_2022, knos.TOKEN, false, "held", "warranty"]);
const orderOf = (name) => v2.readOrder(knos.unhex(s["order accounts"][name].data));
const oK = orderOf("order (open, cancelled while reserved)"), oH = orderOf("order (warranty, a holdback, from a wallet)"), oHb = orderOf("order (open, a holdback, from a Balance)");
const hbOne = v2.readHoldback(knos.unhex(s["order accounts"]["holdback (one payee)"].data)), hbThree = v2.readHoldback(knos.unhex(s["order accounts"]["holdback (three payees)"].data));
same("what a refund owes a taker first, for every order", Object.fromEntries(Object.keys(s["kill fees"]).map((name) => [name, v2.killFee(orderOf(name))])), s["kill fees"]);
same("a kill fee is a tenth of this order's amount, and never more than what is left of it", [v2.killFee(oK), v2.killFee({ ...oK, paid: oK.amount - 5 }), v2.killFee({ ...oK, cancelAt: 0 })],
  [2_000_000, 5, 0]);
{
  const assigned = knos.unhex(s["order accounts"].assign.data), earlier = Uint8Array.from(assigned);
  new DataView(earlier.buffer).setBigInt64(80, BigInt(j.now - 1), true);
  same("where a payee of an order is paid: its assignee, else the token's address, else its bound wallet", {
    assigned: v2.payeeWallet(assigned, oW, bound, j.address), "assigned for an earlier order at this address": v2.payeeWallet(earlier, oW, bound, null),
    "no assignment, an address": v2.payeeWallet(null, oW, bound, j.address), "no assignment, no address, no bind": v2.payeeWallet(null, oW, null, null) }, s["payee wallets"]);
  same("an assignment is read with or without its order", [v2.readAssign(assigned), v2.readAssign(assigned, oW), v2.readAssign(earlier, oW)], [j.dest_token, j.dest_token, null]);
}
same("a Balance with a side account says so", v2.readBalance(knos.unhex(s["order accounts"]["balance (with a side account)"].data)).hasX, true);
const jBal = v2.readJob(knos.unhex(s.accounts["job (open, from a Balance)"].data));
const jWallet = v2.readJob(knos.unhex(s.accounts["job (held, from a wallet, Token-2022, tests mode)"].data));
same("a Balance's job is funded by its GitHub owner; a wallet's by the wallet", [jBal.funder, jWallet.funder], [j.owner_id, j.funder]);
const verified = knos.readToken(knos.unhex(s.accounts["token (verified)"].data));
same("a verified token's claims", [verified.verified, verified.claims().aud, verified.claims().actor_id], [true, fundAud, String(j.maintainer_id)]);
same("a token still being verified shows no claims", knos.readToken(knos.unhex(s.accounts["token (stepping)"].data)).payload.length, 0);

// keys: what the header says and whether a token signed with the key would verify now
for (const [name, c] of Object.entries(s.keys)) {
  const key = v2.readKey(c.data === null ? null : knos.unhex(c.data));
  same(`key ${name}: header`, snake(key), c.read);
  same(`key ${name}: usable`, v2.keyUsable(key, c.now), c.usable);
}
for (const [name, c] of Object.entries(s["order keys"])) {
  const key = v2.readKey(c.data === null ? null : knos.unhex(c.data));
  same(`key ${name}: header`, snake(key), c.read);
  same(`key ${name}: usable`, v2.keyUsable(key, c.now), c.usable);
}
for (const [name, c] of Object.entries(s["token issuers"])) same(`token issuer: ${name}`, v2.tokenIssuer(knos.unhex(c.data)), c.read);
same("a key account names its key by the hash of its modulus", await v2.keyAccountHash(knos.unhex(s.keys["ready, genesis"].data)), s.hashes["key_hash(n2048)"]);
same("a time outside the years a date can name", v2.keyUsable({ state: 1, genesis: true, activeAt: 4e14, expiresAt: 5e14 }, 0)[1],
  "this signing key is new: it can be used from time 400000000000000. Try again then.");

// instructions
const w = await k2.oidc.writeIxs(j.payer, tid, j.jwt);
const walletTok = await knos.ata(j.authority, j.mint), walletTok22 = await knos.ata(j.authority, j.mint22, knos.TOKEN_2022);
const open = await k2.openBalanceIx({ authority: j.authority, ownerId: j.owner_id, mint: j.mint, cap: j.cap, spenders: j.spenders });
const transfer = knos.transferCheckedIx(walletTok, j.mint, await k2.baltok(bal), j.authority, j.amount, 6);
const payArgs = { relayer: j.relayer, payToken: j.token_account, key: j.key };
const instructions = {
  "oidc.write (first chunk)": w[0], "oidc.write (last chunk)": w.at(-1),
  "oidc.step": await k2.oidc.stepIx(j.payer, tid, key2048, 8),
  "oidc.close": await k2.oidc.closeIx(j.payer, tid),
  "oidc.register_key": await k2.oidc.registerKeyIx(j.payer, knos.GITHUB, n2048),
  "oidc.register_key (attested, 4096)": await k2.oidc.registerKeyIx(j.payer, knos.GITLAB, n4096, j.attest),
  "oidc.key_params": await k2.oidc.keyParamsIx(j.payer, knos.GITHUB, n2048),
  "oidc.key_params (4096)": await k2.oidc.keyParamsIx(j.payer, knos.GITLAB, n4096),
  "oidc.refresh": await k2.oidc.refreshIx(j.payer, knos.GITHUB, n2048, j.attest),
  "oidc.approve": await k2.oidc.approveIx(s.programs.guardian, knos.GITLAB, n4096),
  "oidc.revoke": await k2.oidc.revokeIx(s.programs.guardian, knos.GITHUB, n2048),
  "pay.open_balance": await k2.openBalanceIx({ authority: j.authority, ownerId: j.owner_id, mint: j.mint }),
  "pay.open_balance (cap, spenders)": open,
  "pay.open_balance (token-2022, four spenders)": await k2.openBalanceIx({ authority: j.authority, ownerId: j.owner_id, mint: j.mint22,
    spenders: [1, 2, 3, 2n ** 64n - 1n], tokenProgram: knos.TOKEN_2022 }),
  "pay.set_balance": k2.setBalanceIx({ authority: j.authority, balance: bal, cap: j.cap, spenders: j.spenders }),
  "pay.set_balance (no cap, nobody)": k2.setBalanceIx({ authority: j.authority, balance: bal }),
  "pay.withdraw (everything)": await k2.withdrawIx({ authority: j.authority, balance: bal, mint: j.mint }),
  "pay.withdraw (amount, token account)": await k2.withdrawIx({ authority: j.authority, balance: bal, mint: j.mint, amount: j.amount, destToken: j.dest_token }),
  "pay.withdraw (token-2022)": await k2.withdrawIx({ authority: j.authority, balance: bal22, mint: j.mint22, tokenProgram: knos.TOKEN_2022 }),
  "pay.fund_balance": await k2.fundBalanceIx({ relayer: j.relayer, fundToken: j.token_account, key: j.key, balance: bal, mint: j.mint,
    repoId: j.repo_id, issue: j.issue, terms, used: j.jwt }),
  "pay.fund_balance (with its side account)": await k2.fundBalanceIx({ relayer: j.relayer, fundToken: j.token_account, key: j.key, balance: bal, mint: j.mint,
    repoId: j.repo_id, issue: j.issue, terms, balx: true, used: await v2.sigHash(j.jwt) }),
  "pay.fund_balance (faucet)": await k2.fundBalanceIx({ relayer: j.relayer, fundToken: j.token_account, key: j.key, balance: faucetBal,
    mint: await k2.faucetMint(), repoId: j.repo_id, issue: j.issue, terms: s.terms.json, used: verifiedToken }),
  "pay.fund_wallet merge": await k2.fundWalletIx({ funder: j.funder, funderToken: j.funder_token, mint: j.mint, repoId: j.repo_id, issue: j.issue,
    amount: j.amount, wfRepo: j.wf_repo, wfSha: j.wf_sha, terms }),
  "pay.fund_wallet tests (token-2022)": await k2.fundWalletIx({ funder: j.funder, funderToken: j.funder_token, mint: j.mint22, repoId: j.repo_id,
    issue: j.issue, amount: j.amount, wfRepo: j.wf_repo, wfSha: j.wf_sha, terms: termsTests, mode: v2.TESTS, workS: 7 * 86400, tokenProgram: knos.TOKEN_2022 }),
  "pay.pay (a Balance's job, to a wallet)": await k2.payIx({ ...payArgs, job: jobBal, j: jBal, payeeId: j.payee_id, wallet: j.wallet, used: j.jwt }),
  "pay.pay (a Balance's job, held)": await k2.payIx({ ...payArgs, job: jobBal, j: jBal, payeeId: j.payee_id, wallet: null, used: await v2.sigHash(j.jwt) }),
  "pay.pay (a wallet's job, token account)": await k2.payIx({ ...payArgs, job: jobWallet, j: jWallet, payeeId: j.payee_id, wallet: j.wallet, destToken: j.dest_token,
    used: j.attest }),
  "pay.pay (the marker of a token account's data)": await k2.payIx({ ...payArgs, job: jobBal, j: jBal, payeeId: j.payee_id, wallet: j.wallet,
    used: knos.unhex(s.accounts["token (verified)"].data) }),
  "pay.settle": await k2.settleIx({ relayer: j.relayer, job: jobWallet, j: jWallet, wallet: j.wallet }),
  "pay.refund (a Balance's job)": await k2.refundIx({ relayer: j.relayer, job: jobBal, j: jBal }),
  "pay.refund (a wallet's job)": await k2.refundIx({ relayer: j.relayer, job: jobWallet, j: jWallet }),
  "pay.refund (a wallet's job, token account)": await k2.refundIx({ relayer: j.relayer, job: jobWallet, j: jWallet, refundToken: j.dest_token }),
  "pay.bind": await k2.bindIx({ relayer: j.relayer, bindToken: j.token_account, key: j.key, userId: j.payee_id, used: j.jwt }),
  "pay.pause": await k2.pauseIx({ guardian: s.programs.guardian, payer: j.payer, seconds: 3 * 86400 }),
  "pay.pause (lift)": await k2.pauseIx({ guardian: s.programs.guardian, payer: j.payer, seconds: 0 }),
  "pay.init_faucet": await k2.initFaucetIx({ payer: j.payer }),
  "pay.faucet_open": await k2.faucetOpenIx({ relayer: j.relayer, fundToken: j.token_account, key: j.key, ownerId: j.owner_id, repoId: j.repo_id, used: verifiedToken }),
  create_ata: await knos.createAtaIx(j.relayer, j.address, j.mint),
  "create_ata (token-2022)": await knos.createAtaIx(j.relayer, j.address, j.mint22, knos.TOKEN_2022),
  "token.transfer_checked": transfer,
};
same("second: every instruction has a check", Object.keys(instructions).sort(), Object.keys(s.instructions).sort());
for (const [name, ix] of Object.entries(instructions)) same(`second instruction ${name}`, plain(ix), s.instructions[name]);
await throws("a fifth spender is refused", () => k2.openBalanceIx({ authority: j.authority, ownerId: j.owner_id, mint: j.mint, spenders: [1, 2, 3, 4, 5] }));
await throws("a workflow commit that is not a full sha is refused", () => k2.fundWalletIx({ funder: j.funder, funderToken: j.funder_token, mint: j.mint,
  repoId: j.repo_id, issue: j.issue, amount: j.amount, wfRepo: j.wf_repo, wfSha: "main", terms }));

// what an instruction is, read back from its bytes: every knos-pay instruction under the IDL's names
for (const [name, ix] of Object.entries(instructions).filter(([name]) => name.startsWith("pay."))) {
  const e = k2.explain(ix), [want, names] = v2.PAY_IXS.find((x) => x[2] === ix.data[0]);
  same(`explain ${name}`, [e.program, e.address, e.name, e.accounts.map((a) => a.name), e.accounts.map((a) => a.pubkey)],
    ["knos-pay", s.programs.knos_pay, want, names.slice(0, ix.accounts.length), ix.accounts.map((a) => a.pubkey)]);
}
same("explain: open a balance", k2.explain(open).args, { ownerId: j.owner_id, cap: j.cap, spenders: j.spenders });
same("explain: set who may spend", k2.explain(instructions["pay.set_balance (no cap, nobody)"]).args, { cap: 0, spenders: [] });
same("explain: take an amount back", k2.explain(instructions["pay.withdraw (amount, token account)"]).args, { amount: j.amount });
same("explain: a wallet funds a job", k2.explain(instructions["pay.fund_wallet merge"]).args, { repoId: j.repo_id, issue: j.issue, amount: j.amount,
  workS: 14 * 86400, mode: 0, wfRepoHash: s.hashes.wf_repo_hash, wfSha: j.wf_sha, terms: s.terms.json });
same("explain: a comment funds a job", k2.explain(instructions["pay.fund_balance"]).args, { terms: s.terms.json });
same("explain: pause", k2.explain(instructions["pay.pause"]).args, { seconds: 3 * 86400 });
const moved = k2.explain(transfer);
same("explain: a transfer", [moved.program, moved.name, moved.args, moved.accounts.map((a) => a.name)],
  ["SPL Token", "TransferChecked", { amount: j.amount, decimals: 6 }, ["source", "mint", "destination", "owner"]]);
same("explain: a token account", [k2.explain(instructions.create_ata).name, k2.explain(instructions["create_ata (token-2022)"]).accounts[5].pubkey],
  ["CreateIdempotent", knos.TOKEN_2022]);
same("explain: anything else is unknown, with its bytes", [k2.explain(w[0]).program, k2.explain(w[0]).name, k2.explain(w[0]).args.data.slice(0, 4)],
  ["knos-oidc", "unknown", "00c0"]);
const idlPath = join(here, "..", "..", "idl", "knos_pay_v2.json");
if (existsSync(idlPath)) {      // in the repository: the names are the IDL's (the npm package does not carry it)
  const idl = JSON.parse(readFileSync(idlPath, "utf8"));
  same("the instruction table is the IDL's", v2.PAY_IXS.map(([name, names]) => [name, names]), idl.instructions.map((x) => [x.name, x.accounts.map((a) => a.name)]));
  same("the instruction tags are the IDL's", v2.PAY_IXS.map((x) => x[2]), idl.instructions.map((x) => x.discriminant.value));
}

// transactions: the unsigned legacy transaction as the Solana SDK serialises the same instructions
const b64 = (u8) => Buffer.from(u8).toString("base64");
const create = await knos.createAtaIx(j.authority, j.authority, j.mint);
const transactions = {
  "open a balance": [[open], j.authority],
  "open a balance and put money in": [[open, transfer], j.authority],
  "add money": [[transfer], j.authority],
  "add money (token-2022, 9 decimals)": [[knos.transferCheckedIx(walletTok22, j.mint22, await k2.baltok(bal22), j.authority, 3_000_000_000, 9, knos.TOKEN_2022)], j.authority],
  "set who may spend": [[instructions["pay.set_balance"]], j.authority],
  "take everything back": [[create, instructions["pay.withdraw (everything)"]], j.authority],
  "take an amount back": [[create, await k2.withdrawIx({ authority: j.authority, balance: bal, mint: j.mint, amount: j.amount })], j.authority],
  "a wallet funds a job": [[await k2.fundWalletIx({ funder: j.funder, funderToken: await knos.ata(j.funder, j.mint), mint: j.mint, repoId: j.repo_id,
    issue: j.issue, amount: j.amount, wfRepo: j.wf_repo, wfSha: j.wf_sha, terms })], j.funder],
};
same("second: every transaction has a check", Object.keys(transactions).sort(), Object.keys(s.transactions).sort());
for (const [name, [ixs, payer]] of Object.entries(transactions)) {
  const want = s.transactions[name];
  same(`transaction ${name}: instructions`, ixs.map(plain), want.instructions);
  same(`transaction ${name}: message`, knos.hex(knos.serializeMessage(ixs, payer, j.blockhash)), want.message);
  const bytes = knos.serializeTx(ixs, payer, j.blockhash);
  same(`transaction ${name}: bytes`, b64(bytes), want.transaction);
  same(`transaction ${name}: the message inside it`, knos.hex(knos.messageOf(bytes)), want.message);
  same(`transaction ${name}: fits in a packet`, bytes.length <= 1232, true);
}


// ==== work orders (2.1) =============================================================================================
for (const [amount, fee] of Object.entries(s["fees (decimals)"])) { const [a, d] = amount.split("/").map(Number); same(`second: fee of ${amount}`, v2.feeOf(a, d), fee); }
for (const [name, fee] of Object.entries(s["order fees"])) { const [a, bps, d] = name.split("/").map(Number); same(`order fee ${name}`, v2.orderFee(a, bps, d), fee); }
for (const [name, want] of Object.entries(s.units)) { const [m, d] = name.split("/").map(Number); same(`units ${name}`, v2.units(m, d), want); }
same("units saturate at the largest amount a token account holds", v2.units(10n ** 13n, 18), 2n ** 64n - 1n);
same("the fee of an order has no maximum: 25 on the first 1,000, 490 on the next 49,000, 0.5% of what lies above", [v2.orderFee(1_000_000_000), v2.orderFee(50_000_000_000),
  v2.orderFee(v2.MAX_AMOUNT), v2.orderFee(10n ** 12n)], [25_000_000, 515_000_000, 765_000_000, 5_265_000_000]);
same("a plan lowers the first tier's rate only", v2.orderFee(2_000_000_000, 100) - v2.orderFee(2_000_000_000), 10_000_000 - 25_000_000);
for (const [name, c] of Object.entries(s.spent)) same(`a token is used up: ${name}`, v2.spent(c.data === null ? null : knos.unhex(c.data)), c.want);
for (const name of ["bindIx", "bindOrgIx", "reserveIx", "faucetOpenIx"]) {
  await throws(`${name} without the token's marker is refused here, as the program would refuse it`, () => k2[name]({ relayer: j.relayer, key: j.key, order: j.address, userId: 1, orgId: 1, ownerId: 1, repoId: 1 }));
}
await throws("a cancel token without its marker is refused", () => k2.cancelIx({ signer: j.relayer, order: j.address, cancelToken: j.token_account, key: j.key }));
const plansIn = { "no plan": null, "a plan in force": v2.readPlan(knos.unhex(s["order accounts"].plan.data)) };
{
  const p = (over) => ({ ...plansIn["a plan in force"], ...over });
  const got = { "no plan": v2.planBps(null, j.now), "a plan in force": v2.planBps(plansIn["a plan in force"], j.now), "an expired plan": v2.planBps(p({ expires: j.now - 1 }), j.now),
    "a rate below the floor": v2.planBps(p({ feeBps: 10 }), j.now), "a rate above the cap": v2.planBps(p({ feeBps: 900 }), j.now), "expires this second": v2.planBps(p({ expires: j.now }), j.now) };
  same("the fee rate of an owner's orders: a plan while it lasts, within 50 to 250", got, s["plan bps"]);
}
for (const [name, want] of Object.entries(s.opts)) same(`opts ${name}`, knos.hex(opts(name)), want);
same("opts are 48 bytes", opts("everything").length, v2.OPTS_LEN);

const orderIxs = {};
{
  const bal22 = await k2.balance(j.owner_id, j.authority, j.mint22), erpt = () => ({ relayer: j.relayer, fundToken: j.token_account, key: j.key, ownerId: j.owner_id, repoId: j.repo_id, issue: j.issue, terms: orderTerms });
  const payees = (named) => named.map(([id, wallet, dest]) => [id, wallet ? j[wallet] : null, ...(dest ? [j[dest]] : [])]);
  const four = payees(j.four_payees);
  const orderK = await k2.orderPda(scope, j.funder, 2), orderH = await k2.orderPda(scope, j.funder, 5), orderHb = await k2.orderPda(scope, bal, 6);
  const fundW = { funder: j.funder, funderToken: j.funder_token, mint: j.mint, repoId: j.repo_id, issue: j.issue, amount: j.amount, wfRepo: j.wf_repo, wfSha: j.wf_sha, terms: orderTerms };
  Object.assign(orderIxs, {
    "pay.version": k2.versionIx(),
    "pay.set_balance_x": await k2.setBalanceXIx({ authority: j.authority, balance: bal, dayLimit: 50_000_000, totalLimit: 500_000_000, repos: [j.repo_id, 7], wfSha: j.wf_sha }),
    "pay.set_balance_x (no limits)": await k2.setBalanceXIx({ authority: j.authority, balance: bal }),
    "pay.set_balance_x (eight repositories)": await k2.setBalanceXIx({ authority: j.authority, balance: bal, dayLimit: 1, totalLimit: 2, repos: [1, 2, 3, 4, 5, 6, 7, 2n ** 64n - 1n], wfSha: "d".repeat(40) }),
    "pay.set_plan": await k2.setPlanIx({ feeOwner: knos.FEE_OWNER, payer: j.payer, ownerId: j.owner_id, feeBps: 100, expires: j.now + 90 * 86400 }),
    "pay.fund_order_wallet": await k2.fundOrderWalletIx(fundW),
    "pay.fund_order_wallet (tests, options, seq, token-2022)": await k2.fundOrderWalletIx({ ...fundW, mint: j.mint22, mode: v2.TESTS, workS: 7 * 86400, seq: 4,
      options: opts("everything"), tokenProgram: knos.TOKEN_2022 }),
    "pay.fund_order_wallet (private)": await k2.fundOrderWalletIx({ ...fundW, repoId: 0, issue: 0, terms: knos.unhex(oth), seq: 1, options: opts("private"), scope: scopePrivate }),
    "pay.fund_order_balance": await k2.fundOrderBalanceIx({ ...erpt(), balance: bal, mint: j.mint, used: j.jwt, seq: 3 }),
    "pay.fund_order_balance (token-2022, marker given)": await k2.fundOrderBalanceIx({ ...erpt(), balance: bal22, mint: j.mint22, used: j.attest, seq: 0, tokenProgram: knos.TOKEN_2022 }),
    "pay.pay_order (one payee, a bound wallet)": await k2.payOrderIx({ relayer: j.relayer, payToken: j.token_account, key: j.key, order: orderW, o: oW, payees: [[j.payee_id, j.wallet]], used: j.jwt }),
    "pay.pay_order (one payee, held)": await k2.payOrderIx({ relayer: j.relayer, payToken: j.token_account, key: j.key, order: orderW, o: oW, payees: [[j.payee_id, null]], used: j.attest }),
    "pay.pay_order (four payees, a tip account, a token account)": await k2.payOrderIx({ relayer: j.relayer, payToken: j.token_account, key: j.key, order: orderB, o: oB,
      payees: four, tipToken: j.dest_token, used: j.jwt }),
    "pay.fund_order_balance (private)": await k2.fundPrivateOrderBalanceIx({ relayer: j.relayer, fundToken: j.token_account, key: j.key, balance: bal, mint: j.mint,
      ownerId: j.owner_id, scope: scopePrivate, termsHash: oth, used: j.jwt, seq: 3 }),
    "pay.bind_org": await k2.bindOrgIx({ relayer: j.relayer, bindToken: j.token_account, key: j.key, orgId: j.owner_id, used: j.jwt }),
    "pay.pay_order (a holdback: its record)": await k2.payOrderIx({ relayer: j.relayer, payToken: j.token_account, key: j.key, order: orderHb, o: oHb,
      payees: [[j.payee_id, j.wallet], [j.maintainer_id, j.address]], used: j.jwt }),
    "pay.pay_order (a standing order: the pull request's marker)": await k2.payOrderIx({ relayer: j.relayer, payToken: j.token_account, key: j.key, order: orderB, o: oB,
      payees: [[j.payee_id, j.wallet]], pr: 40, used: j.jwt }),
    "pay.release (one payee)": await k2.releaseIx({ relayer: j.relayer, order: orderH, o: oH, hb: hbOne }),
    "pay.release (three payees, a tip account, token-2022)": await k2.releaseIx({ relayer: j.relayer, order: orderB, o: oB, hb: hbThree, tipToken: j.dest_token }),
    "pay.revert (a wallet's order)": await k2.revertIx({ relayer: j.relayer, revertToken: j.token_account, key: j.key, order: orderH, o: oH, hb: hbOne, used: j.jwt }),
    "pay.revert (a Balance's order)": await k2.revertIx({ relayer: j.relayer, revertToken: j.token_account, key: j.key, order: orderB, o: oB, hb: hbThree, used: j.jwt }),
    "pay.revert (token account)": await k2.revertIx({ relayer: j.relayer, revertToken: j.token_account, key: j.key, order: orderH, o: oH, hb: hbOne, refundToken: j.dest_token, used: j.jwt }),
    "pay.reserve": await k2.reserveIx({ relayer: j.relayer, takeToken: j.token_account, key: j.key, order: orderW, used: j.jwt }),
    "pay.cancel (a wallet's order)": await k2.cancelIx({ signer: j.funder, order: orderW }),
    "pay.cancel (a Balance's order, a token)": await k2.cancelIx({ signer: j.relayer, order: orderB, cancelToken: j.token_account, key: j.key, used: j.jwt }),
    "pay.assign": await k2.assignIx({ signer: j.wallet, order: orderW, payeeId: j.payee_id, to: j.dest_token }),
    "pay.close_marker (used)": k2.closeMarkerIx({ marker: await k2.usedPda(j.jwt), rentTo: j.relayer }),
    "pay.close_marker (done)": k2.closeMarkerIx({ marker: await k2.donePda(orderB, 40), rentTo: j.relayer, order: orderB }),
    "pay.refund_order (a kill fee, to the taker)": await k2.refundOrderIx({ relayer: j.relayer, order: orderK, o: oK, killToken: j.dest_token }),
    "pay.refund_order (a kill fee, held for the taker)": await k2.refundOrderIx({ relayer: j.relayer, order: orderK, o: oK }),
    "pay.settle_order": await k2.settleOrderIx({ relayer: j.relayer, order: orderP, o: oP, wallet: j.wallet }),
    "pay.settle_order (token account, tip account)": await k2.settleOrderIx({ relayer: j.relayer, order: orderP, o: oP, wallet: j.wallet, destToken: j.dest_token, tipToken: j.token_account }),
    "pay.refund_order (a wallet's order)": await k2.refundOrderIx({ relayer: j.relayer, order: orderW, o: oW }),
    "pay.refund_order (a Balance's order)": await k2.refundOrderIx({ relayer: j.relayer, order: orderB, o: oB }),
    "pay.refund_order (token account)": await k2.refundOrderIx({ relayer: j.relayer, order: orderW, o: oW, refundToken: j.dest_token }),
    "pay.top_up (a wallet's order)": await k2.topUpIx({ signer: j.funder, order: orderW, o: oW, add: 5_000_000 }),
    "pay.top_up (a Balance's order)": await k2.topUpIx({ signer: j.authority, order: orderB, o: oB, add: 5_000_000_000 }),
    "pay.top_up (token account)": await k2.topUpIx({ signer: j.funder, order: orderW, o: oW, add: 1, fromToken: j.dest_token }),
    "oidc.register_key (attested, with its key)": await k2.oidc.registerKeyIx(j.payer, knos.GITLAB, n4096, j.attest, j.key),
    "oidc.register_key (no attestation, a key given)": await k2.oidc.registerKeyIx(j.payer, knos.GITHUB, n2048, null, j.key),
    "oidc.register_issuer_key": await k2.oidc.registerIssuerKeyIx(j.payer, j.url, n2048, j.attest, j.key),
    "oidc.register_private_key": await k2.oidc.registerPrivateKeyIx(j.authority, j.url, n4096),
    "oidc.key_params (issuer URL)": await k2.oidc.keyParamsIx(j.payer, j.url, n2048),
    "oidc.key_params (private)": await k2.oidc.keyParamsIx(j.payer, j.url, n2048, j.authority),
    "oidc.refresh (with its key)": await k2.oidc.refreshIx(j.payer, knos.GITHUB, n2048, j.attest, j.key),
    "oidc.refresh (issuer URL)": await k2.oidc.refreshIx(j.payer, j.url, n2048, j.attest, j.key),
    "oidc.approve (issuer URL)": await k2.oidc.approveIx(s.programs.guardian, j.url, n2048),
    "oidc.revoke (private)": await k2.oidc.revokeIx(j.authority, j.url, n2048, j.authority),
  });
}
same("order: every instruction has a check", Object.keys(orderIxs).sort(), Object.keys(s["order instructions"]).sort());
for (const [name, got] of Object.entries(orderIxs)) same(`order instruction ${name}`, plain(got), s["order instructions"][name]);
await throws("a fifth payee needs no check here: nine repositories are refused", () => k2.setBalanceXIx({ authority: j.authority, balance: bal, repos: [1, 2, 3, 4, 5, 6, 7, 8, 9] }));
await throws("a pay token with no marker is refused in words", () => k2.payIx({ ...payArgs, job: jobBal, j: jBal, payeeId: j.payee_id, wallet: j.wallet }));
await throws("an issuer URL that is not https is refused", () => k2.oidc.registerPrivateKeyIx(j.authority, "http://token.example.com", n2048));
await throws("an issuer URL of 201 bytes is refused", () => k2.oidc.registerPrivateKeyIx(j.authority, "https://" + "a".repeat(193), n2048));
await throws("an order's workflow commit must be a full sha", () => k2.fundOrderWalletIx({ funder: j.funder, funderToken: j.funder_token, mint: j.mint, repoId: j.repo_id, issue: j.issue,
  amount: j.amount, wfRepo: j.wf_repo, wfSha: "abc", terms: orderTerms }));

// every order instruction, read back from its bytes. The names are the table's (the IDL's) where an instruction has
// one list of accounts; a payment's are written out here: fourteen (the last is the token's marker), five for each payee, each payee's assignment,
// then the marker or the record; a release's: thirteen, then a wallet and its token account for each recorded payee.
const perPayee = ["bind", "wallet", "destToken", "rep", "pair"];
const paid = (payees, last) => [...v2.PAY_IXS[17][1].slice(0, 14), ...Array(payees).fill(perPayee).flat(), ...Array(payees).fill("assign"), ...last];
const written = { "pay.pay_order (one payee, a bound wallet)": paid(1, []), "pay.pay_order (one payee, held)": paid(1, []),
  "pay.pay_order (four payees, a tip account, a token account)": paid(4, ["doneOrHb"]), "pay.pay_order (a holdback: its record)": paid(2, ["doneOrHb"]),
  "pay.pay_order (a standing order: the pull request's marker)": paid(1, ["doneOrHb"]),
  "pay.release (three payees, a tip account, token-2022)": [...v2.PAY_IXS[18][1], "wallet", "destToken", "wallet", "destToken"] };
for (const [name, ix] of Object.entries(orderIxs).filter(([name]) => name.startsWith("pay."))) {
  const e = k2.explain(ix), [want, names] = v2.PAY_IXS.find((x) => x[2] === ix.data[0]);
  const expect = written[name] ?? names.slice(0, ix.accounts.length);
  same(`explain ${name}: an account, a name`, expect.length, ix.accounts.length);
  same(`explain ${name}`, [e.program, e.name, e.accounts.map((a) => a.name), e.accounts.map((a) => a.pubkey)], ["knos-pay", want, expect, ix.accounts.map((a) => a.pubkey)]);
}
same("the table is in the order of the tags, with none missing", v2.PAY_IXS.map((x) => x[2]), v2.PAY_IXS.map((_x, at) => at));
same("explain: a private order from a Balance shows its scope and the hash of its terms", k2.explain(orderIxs["pay.fund_order_balance (private)"]).args,
  { scope: knos.hex(scopePrivate), terms: oth });
same("explain: an assignment", k2.explain(orderIxs["pay.assign"]).args, { payeeId: j.payee_id, to: j.dest_token });
same("explain: the taker's accounts of a refund", k2.explain(orderIxs["pay.refund_order (a kill fee, to the taker)"]).accounts.slice(8).map((a) => [a.name, a.pubkey, a.writable]),
  [["takerBind", await k2.bind(j.maintainer_id), false], ["killToken", j.dest_token, true]]);
same("a refund with no kill fee due names no taker", orderIxs["pay.refund_order (a wallet's order)"].accounts.length, 8);
same("explain: a wallet funds an order", k2.explain(orderIxs["pay.fund_order_wallet"]).args, { issue: j.issue, repoId: j.repo_id, amount: j.amount, mode: 0, workS: 14 * 86400, seq: 0,
  options: knos.hex(v2.opts()), wfRepoHash: s.hashes.wf_repo_hash, wfSha: j.wf_sha, terms: s["order terms"].json });
same("explain: a private order shows its scope and the hash of its terms", k2.explain(orderIxs["pay.fund_order_wallet (private)"]).args,
  { issue: 0, repoId: 0, amount: j.amount, mode: 0, workS: 14 * 86400, seq: 1, options: knos.hex(opts("private")), wfRepoHash: s.hashes.wf_repo_hash, wfSha: j.wf_sha, scope: knos.hex(scopePrivate), terms: oth });
same("explain: a side account", k2.explain(orderIxs["pay.set_balance_x"]).args, { dayLimit: 50_000_000, totalLimit: 500_000_000, repos: [j.repo_id, 7], wfSha: j.wf_sha });
same("explain: no side account limits", k2.explain(orderIxs["pay.set_balance_x (no limits)"]).args, { dayLimit: 0, totalLimit: 0, repos: [], wfSha: "" });
same("explain: a plan", k2.explain(orderIxs["pay.set_plan"]).args, { ownerId: j.owner_id, feeBps: 100, expires: j.now + 90 * 86400 });
same("explain: a top up", k2.explain(orderIxs["pay.top_up (a wallet's order)"]).args, { add: 5_000_000 });
same("explain: a comment funds an order", k2.explain(orderIxs["pay.fund_order_balance"]).args, { terms: s["order terms"].json });
same("explain: the version call", [k2.explain(orderIxs["pay.version"]).name, k2.explain(orderIxs["pay.version"]).accounts], ["Version", []]);

// the transaction a wallet signs to fund an order, and the same in a v1 transaction
{
  const fund = await k2.fundOrderWalletIx({ funder: j.funder, funderToken: await knos.ata(j.funder, j.mint), mint: j.mint, repoId: j.repo_id, issue: j.issue, amount: j.amount,
    wfRepo: j.wf_repo, wfSha: j.wf_sha, terms: orderTerms });
  const named = { "a wallet funds an order": [[fund], j.funder], "a wallet funds an order, with its token account": [[await knos.createAtaIx(j.funder, j.funder, j.mint),
    await k2.fundOrderWalletIx({ funder: j.funder, funderToken: await knos.ata(j.funder, j.mint), mint: j.mint, repoId: j.repo_id, issue: j.issue, amount: j.amount,
      wfRepo: j.wf_repo, wfSha: j.wf_sha, terms: orderTerms })], j.funder] };
  for (const [name, [ixs, payer]] of Object.entries(named)) {
    const want = s["order transactions"][name], bytes = knos.serializeTx(ixs, payer, j.blockhash);
    same(`transaction ${name}: instructions`, ixs.map(plain), want.instructions);
    same(`transaction ${name}: bytes`, b64(bytes), want.transaction);
    same(`transaction ${name}: the message inside it`, knos.hex(knos.messageOf(bytes)), want.message);
    same(`transaction ${name}: fits in a packet`, bytes.length <= 1232, true);
  }
}

// ==== knos-meter ======================================================================================================
const M = s.meter, m = knos.meter, mk = m.client(s.programs.knos_meter), mi = M.inputs;
for (const [name, want] of Object.entries(M.constants)) same(`meter constant ${name}`, m[name], want);
same("the words for every meter error code", Object.fromEntries(Object.entries(m.ERRORS).map(([c, w]) => [String(c), w])), M.errors);
same("the meter's address is the one the programs file names", mk.program, s.programs.knos_meter);
const mintAuth = j.authority;
const credits = await mk.creditsPda(j.owner_id, mintAuth, j.mint), credits22 = await mk.creditsPda(j.owner_id, mintAuth, j.mint22);
const meterBytes = (name) => knos.unhex(M.accounts[name].data);
const c = m.readCredits(meterBytes("credits")), c22 = m.readCredits(meterBytes("credits (token-2022)"));
const aud = m.evalAudience(j.owner_id, j.maintainer_id, mi.order, mi.artifact, mi.policy, 0, 1, 2_000_000);
const audRejected = m.evalAudience(j.owner_id, j.maintainer_id, mi.order, "b".repeat(40), mi.policy, 3, 0, 5);
const ev = m.parseAudience(aud), evRejected = m.parseAudience(audRejected);
const evKey = await m.evalKey(ev.order, ev.artifact, ev.policy, ev.milestone), evKeyRejected = await m.evalKey(evRejected.order, evRejected.artifact, evRejected.policy, evRejected.milestone);
const mAddresses = { auth: await mk.auth(), "credits(owner, authority, mint)": credits, "credits(owner, authority, mint22)": credits22, "crtok(credits)": await mk.crtokPda(credits),
  "plan(owner)": await mk.planPda(j.owner_id), "mark(buyer, key)": await mk.markPda(j.owner_id, evKey), "month(buyer, seller, month)": await mk.monthPda(j.owner_id, j.maintainer_id, 202610),
  "ledger(buyer, seller, month)": await mk.ledgerPda(j.owner_id, j.maintainer_id, 202610), "ledger(buyer, seller, month, claim)": await mk.ledgerPda(j.owner_id, j.maintainer_id, 202610, true) };
same("meter: every address has a check", Object.keys(mAddresses).sort(), Object.keys(M.addresses).sort());
for (const [name, got] of Object.entries(mAddresses)) same(`meter address ${name}`, got, M.addresses[name]);
same("meter: audiences", { eval: aud, "eval, rejected": audRejected, "parse(eval)": snake(ev), "parse(rejected)": snake(evRejected) }, M.audiences);
same("a mark is named by the hash of the four things that make an evaluation", { eval_key: knos.hex(evKey), "eval_key (rejected)": knos.hex(evKeyRejected) }, M.hashes);
await throws("an evaluation of a 31-byte work order is refused", () => m.evalAudience(1, 2, "ab".repeat(31), mi.artifact, mi.policy, 0, 1, 1));
await throws("an evaluation of a 39-character commit is refused", () => m.evalAudience(1, 2, mi.order, "a".repeat(39), mi.policy, 0, 1, 1));
await throws("a milestone of 2^32 is refused", () => m.evalAudience(1, 2, mi.order, mi.artifact, mi.policy, 2 ** 32, 1, 1));
await throws("an audience that is not an evaluation is refused", async () => m.parseAudience("knos3:fund:1"));
same("the evaluation of bytes and of hex are the same", m.evalAudience(1, 2, knos.unhex(mi.order), mi.artifact, knos.unhex(mi.policy), 0, true, 1), m.evalAudience(1, 2, mi.order, mi.artifact, mi.policy, 0, 1, 1));
same("months, UTC, from the chain's clock", Object.fromEntries(Object.entries(M.when).map(([name, t]) => [name, m.yyyymm(t)])), M.yyyymm);
same("the first second of the next month", Object.fromEntries(Object.entries(M.when).map(([name, t]) => [name, m.nextMonth(t)])), M.next_month);
same("from when a mark can be closed", Object.fromEntries(Object.entries(M.when).map(([name, t]) => [name, m.closeAfter(t)])), M.close_after);
{
  const marks = M.closable.marks.map(([address, mark]) => [address, { ...mark, closeAfter: mark.close_after }]);
  same("the marks CloseMark takes at a time: none before, all but the one from before CloseMark after",
    Object.fromEntries(Object.keys(M.closable.want).map((t) => [t, m.closable(marks, Number(t))])), M.closable.want);
}
// past 2^53 an amount is a BigInt here and a JSON number in the fixtures: both as the same digits
const digits = (o) => Object.fromEntries(Object.entries(o).map(([name, v]) => [name, BigInt(v).toString()]));
same("fees in a mint's smallest units", digits(Object.fromEntries(Object.keys(M.fee_units).map((name) => [name, m.feeUnits(...name.split("/").map(Number))]))), digits(M.fee_units));
const mPlans = { "no plan, nothing used": m.readPlan(null), "a plan, past the free ones": m.readPlan(meterBytes("plan")),
  "a plan, expired": { ...m.readPlan(meterBytes("plan")), expiry: j.now - 1 }, "a plan, last month's count": { ...m.readPlan(meterBytes("plan")), month: 202609 },
  "inside the free ones": { tier: 0, month: 202610, ownerId: j.owner_id, rate: 0, expiry: 0, used: 9_999 }, "the first one paid for": { tier: 0, month: 202610, ownerId: j.owner_id, rate: 0, expiry: 0, used: 10_000 } };
same("the meter's plans", Object.fromEntries(Object.entries(mPlans).map(([name, p]) => [name, snake(p)])), Object.fromEntries(Object.entries(M.plans).map(([name, p]) => [name, p])));
same("what the next evaluation costs", Object.fromEntries(Object.entries(mPlans).map(([name, p]) => [name, m.quote(p, 6, j.now)])), M.quote);
same("the rate in force", Object.fromEntries(Object.entries(mPlans).map(([name, p]) => [name, m.rateAt(p, j.now)])), M.rate_at);
same("the count of a month", Object.fromEntries(Object.entries(mPlans).map(([name, p]) => [name, m.usedIn(p, 202610)])), M.used_in);
const meterIxs = {
  open_credits: await mk.openCreditsIx({ authority: j.authority, ownerId: j.owner_id, mint: j.mint, wfRepo: j.wf_repo, wfSha: j.wf_sha }),
  "open_credits (token-2022)": await mk.openCreditsIx({ authority: j.authority, ownerId: j.owner_id, mint: j.mint22, wfRepo: j.wf_repo, wfSha: j.wf_sha, tokenProgram: knos.TOKEN_2022 }),
  deposit: await mk.depositIx({ source: walletTok, owner: j.authority, credits, mint: j.mint, amount: j.amount, decimals: 6 }),
  "deposit (token-2022)": await mk.depositIx({ source: walletTok22, owner: j.authority, credits: credits22, mint: j.mint22, amount: 3_000_000_000, decimals: 9, tokenProgram: knos.TOKEN_2022 }),
  "withdraw_credits (everything)": await mk.withdrawCreditsIx({ authority: j.authority, credits, mint: j.mint }),
  "withdraw_credits (amount, token account)": await mk.withdrawCreditsIx({ authority: j.authority, credits, mint: j.mint, amount: j.amount, destToken: j.dest_token }),
  "withdraw_credits (token-2022)": await mk.withdrawCreditsIx({ authority: j.authority, credits: credits22, mint: j.mint22, tokenProgram: knos.TOKEN_2022 }),
  set_plan: await mk.setPlanIx({ feeOwner: knos.FEE_OWNER, payer: j.payer, ownerId: j.owner_id, tier: 2, rate: 20_000, expiry: j.now + 90 * 86400 }),
  "record (a fee token account given)": await mk.recordIx({ relayer: j.relayer, token: j.token_account, key: j.key, credits, c, audience: aud, now: j.now, feeToken: j.dest_token }),
  "record (token-2022, the fee owner's own)": await mk.recordIx({ relayer: j.relayer, token: j.token_account, key: j.key, credits: credits22, c: c22, audience: audRejected, now: j.now + 40 * 86400 }),
  close_mark: mk.closeMarkIx({ payer: j.relayer, mark: await mk.markPda(j.owner_id, evKey) }),
  "record_batch (a fee token account given)": await mk.recordBatchIx({ relayer: j.relayer, token: j.token_account, key: j.key, credits, c, audience: M.batch.audience, feeToken: j.dest_token }),
  "record_batch (token-2022, the fee owner's own)": await mk.recordBatchIx({ relayer: j.relayer, token: j.token_account, key: j.key, credits: credits22, c: c22, audience: M.batch.audience }),
  claim_batch: await mk.claimBatchIx({ relayer: j.relayer, token: j.token_account, key: j.key, audience: M.batch["claim audience"] }),
  version: mk.versionIx(),
};
// the batch mode (1.1): the root both sides compute, the audiences, the ledger's running hash and its account
{
  const B = M.batch, root = (n) => m.merkleRoot(B.keys.slice(0, n));
  for (const [n, want] of Object.entries(B.roots)) same(`the Merkle root of ${n} evaluation keys (RFC 6962)`, knos.hex(await root(Number(n))), want);
  same("the root of bytes and of hex are the same", knos.hex(await m.merkleRoot(B.keys.map(knos.unhex))), B.roots["5"]);
  await throws("keys out of order have no root", () => m.merkleRoot([B.keys[1], B.keys[0]]));
  await throws("a key given twice has no root", () => m.merkleRoot([B.keys[0], B.keys[0]]));
  await throws("no keys, no root", () => m.merkleRoot([]));
  same("a batch's audience", m.batchAudience(j.owner_id, j.maintainer_id, 202610, 3, 5, 4, 8_000_000, B.roots["5"]), B.audience);
  same("the seller's claim of it", m.batchAudience(j.owner_id, j.maintainer_id, 202610, 0, 5, 5, 10_000_000, knos.unhex(B.roots["5"]), "claim"), B["claim audience"]);
  same("a batch's audience, read back", m.parseBatch(B.audience), { claim: false, buyerId: j.owner_id, sellerId: j.maintainer_id, month: 202610, seq: 3, count: 5, accepted: 4,
    value: 8_000_000, root: B.roots["5"] });
  await throws("an evaluation's audience is not a batch's", async () => m.parseBatch(aud));
  await throws("a batch is the buyer's or the seller's, nothing else", async () => m.batchAudience(1, 2, 202610, 0, 1, 1, 1, B.roots["1"], "other"));
  await throws("the buyer's count is not sent as a claim", () => mk.claimBatchIx({ relayer: j.relayer, token: j.token_account, key: j.key, audience: B.audience }));
  await throws("a claim is not sent as the buyer's count", () => mk.recordBatchIx({ relayer: j.relayer, token: j.token_account, key: j.key, credits, c, audience: B["claim audience"] }));
  const first = await m.chainHash(new Uint8Array(32), B.roots["3"], 0, 3, 3, 6_000_000), second = await m.chainHash(first, B.roots["5"], 1, 5, 4, 8_000_000);
  same("a ledger's running hash, batch after batch", [knos.hex(first), knos.hex(second)], Object.values(B.chain));
  for (const [name, a] of Object.entries(M.ledgers)) same(`meter ${name}`, snake(m.readLedger(a.data === null ? null : knos.unhex(a.data))), a.read);
  same("the ledger's hash is the one recomputed from its batches", m.readLedger(knos.unhex(M.ledgers.ledger.data)).chain, knos.hex(second));
}
same("meter: every instruction has a check", Object.keys(meterIxs).sort(), Object.keys(M.instructions).sort());
for (const [name, got] of Object.entries(meterIxs)) same(`meter instruction ${name}`, plain(got), M.instructions[name]);
await throws("credits pin a full commit", () => mk.openCreditsIx({ authority: j.authority, ownerId: j.owner_id, mint: j.mint, wfRepo: j.wf_repo, wfSha: "main" }));
const mReaders = { credits: m.readCredits, plan: m.readPlan, mark: m.readMark, month: (raw) => m.readMonth(raw, j.owner_id, j.maintainer_id, 202610) };
for (const [name, a] of Object.entries(M.accounts)) same(`meter account ${name}`, snake(mReaders[a.reader](a.data === null ? null : knos.unhex(a.data))), a.read);
same("a deposit is a plain transfer to the credits' token account", [meterIxs.deposit.program, k2.explain(meterIxs.deposit).name], [knos.TOKEN, "TransferChecked"]);
same("parse_eval", Object.fromEntries(Object.keys(M.parse_eval).map((line) => [line, m.parseEval(line)])), M.parse_eval);
same("what a program itself logged", [knos.said(M.said.logs, M.said.program), knos.said(M.said.logs)], [M.said.want, M["said"]["want (everyone)"]]);
{
  const st = M.statement;
  const asked = [], history = async function* (address, most) { asked.push(address); yield* Object.keys(st.logs).slice(0, most); };
  const got = await m.statement({ history, logs: (sig) => st.logs[sig] }, st.buyer, st.seller, st.month, st.program);
  same("a statement recomputed from the meter's logs: duplicates, forged lines, other sellers and months do not count", snake(got), st.want);
  same("it asked for the transactions of the month's account", asked, [await mk.monthPda(st.buyer, st.seller, st.month)]);
}

// ==== the v1 transaction (SIMD-0385) ==================================================================================
{
  const four = j.four_payees.map(([id, wallet, dest]) => [id, wallet ? j[wallet] : null, ...(dest ? [j[dest]] : [])]);
  const orderBal = await k2.orderPda(scope, bal, 3);
  const oBal = v2.readOrder(knos.unhex(s["order accounts"]["order (open, from a wallet, public)"].data));
  const oFor = { ...oBal, fromBalance: true, source: bal, refundTo: await k2.baltok(bal), rentTo: j.relayer, mint: j.mint, funder: j.owner_id };
  const payFour = await k2.payOrderIx({ relayer: j.relayer, payToken: j.token_account, key: j.key, order: orderBal, o: oFor, payees: four, used: j.jwt });
  const fund = await k2.fundOrderWalletIx({ funder: j.funder, funderToken: await knos.ata(j.funder, j.mint), mint: j.mint, repoId: j.repo_id, issue: j.issue, amount: j.amount,
    wfRepo: j.wf_repo, wfSha: j.wf_sha, terms: orderTerms });
  const cases = {
    "four payees, a compute limit": [[payFour], j.relayer], "a wallet funds an order, every setting": [[fund], j.funder],
    "open a balance and put money in": [[open, transfer], j.authority],
    "a token-2022 payee list and a heap": [[await knos.createAtaIx(j.relayer, j.address, j.mint22, knos.TOKEN_2022), payFour], j.relayer],
  };
  const camel = (cfg) => ({ computeUnitLimit: cfg.compute_unit_limit, priorityFee: cfg.priority_fee, loadedAccountsDataSizeLimit: cfg.loaded_accounts_data_size_limit, heapSize: cfg.heap_size });
  same("v1: every transaction has a check", Object.keys(cases).sort(), Object.keys(s.v1.cases).sort());
  for (const [name, [ixs, payer]] of Object.entries(cases)) {
    const want = s.v1.cases[name], config = Object.fromEntries(Object.entries(camel(want.config)).filter(([, v]) => v !== undefined));
    same(`v1 ${name}: payer and instructions`, [payer, ixs.map(plain)], [want.payer, want.instructions]);
    const message = knos.serializeMessageV1(ixs, payer, j.blockhash, config), bytes = knos.serializeTxV1(ixs, payer, j.blockhash, config);
    same(`v1 ${name}: message`, knos.hex(message), want.message);
    same(`v1 ${name}: bytes`, b64(bytes), want.transaction);
    same(`v1 ${name}: size`, bytes.length, want.size);
    same(`v1 ${name}: the message inside it`, knos.hex(knos.messageOfV1(bytes)), want.message);
    same(`v1 ${name}: starts with 0x81`, message[0], s.v1.limits.V1_PREFIX);
  }
  same("v1: a payment to four new payees does not fit a legacy transaction and fits a v1 one",
    [knos.serializeTx([await knos.createAtaIx(j.relayer, j.address, j.mint22, knos.TOKEN_2022), payFour], j.relayer, j.blockhash).length > 1232, s.v1.cases["a token-2022 payee list and a heap"].size <= knos.V1_MAX_SIZE], [true, true]);
  same("v1: the limits", [knos.V1_MAX_SIZE, knos.V1_PREFIX], [s.v1.limits.MAX_TRANSACTION_SIZE, s.v1.limits.V1_PREFIX]);
  await throws("v1: no compute limit is refused (an unset one is zero units)", async () => knos.serializeTxV1([fund], j.funder, j.blockhash, {}));
  await throws("v1: a heap outside 32 KiB to 256 KiB is refused", async () => knos.serializeTxV1([fund], j.funder, j.blockhash, { computeUnitLimit: 1, heapSize: 1024 }));
  await throws("v1: more than 4,096 bytes are refused", async () => knos.serializeTxV1([{ ...fund, data: new Uint8Array(4100) }], j.funder, j.blockhash, { computeUnitLimit: 1 }));
  await throws("v1: more than 64 accounts are refused", async () => knos.serializeTxV1([{ program: knos.SYSTEM, data: new Uint8Array(0),
    accounts: Array.from({ length: 70 }, (_x, at) => ({ pubkey: knos.b58(Uint8Array.from({ length: 32 }, () => at + 1)), signer: false, writable: false })) }], j.funder, j.blockhash, { computeUnitLimit: 1 }));
}

// ==== what a browser adds ============================================================================================
same("addresses: 32 bytes, written one way", [knos.isAddress(j.wallet), knos.isAddress(knos.SYSTEM), knos.isAddress("1" + j.wallet),
  knos.isAddress("0x" + "ab".repeat(20)), knos.isAddress(j.wallet.slice(0, 31)), knos.isAddress(null)], [true, false, false, false, false, false]);

// SPL Token accounts
const mintAccount = new Uint8Array(82);
new DataView(mintAccount.buffer).setUint32(0, 1, true); mintAccount.set(knos.unb58(j.authority), 4);
new DataView(mintAccount.buffer).setBigUint64(36, 1_000_000_000_000n, true); mintAccount[44] = 6; mintAccount[45] = 1;
same("a mint", knos.readMint(mintAccount), { decimals: 6, supply: 1_000_000_000_000, mintAuthority: j.authority });
const tokenAccount = new Uint8Array(165);
tokenAccount.set(knos.unb58(j.mint), 0); tokenAccount.set(knos.unb58(j.wallet), 32); new DataView(tokenAccount.buffer).setBigUint64(64, 19_500_000n, true);
same("a token account", knos.readTokenAccount(tokenAccount), { mint: j.mint, owner: j.wallet, amount: 19_500_000 });
same("neither", [knos.readMint(new Uint8Array(81)), knos.readTokenAccount(null)], [null, null]);

// Squads: the vault of a multisig, and two multisig accounts of other people's as devnet returned them on 2 Oct 2026
// (2 of 3 members, an approved transaction waits 172,800 seconds; one names a rent collector, one does not)
same("the upgrade authority is vault 0 of the upgrade multisig", await knos.squadsVault(s.programs.upgrade_multisig), s.programs.upgrade_authority);
same("the guardian is vault 0 of the guardian multisig", await knos.squadsVault(s.programs.guardian_multisig), s.programs.guardian);
same("the multisig program", knos.SQUADS, s.programs.squads_program);
const recorded = [       // [address, account data, what a reader written apart from this client found in it, its vault 0]
  ["K3u623LwUfpiQNuTXgmWW6Q9mgqh94pFm7nEn7W99Xb",
    "4HR5ukShT+xNivujmtQm1Okq4LPGr5F9K9R6wnKMB40nBPWTUnJizQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAgAAowIAAAAAAAAAAAAAAAAAAAAAAAD8AwAAAFzX7Eqr3t/I9YmHAqNrbcQe5JG6oK0xuBJ+nuwfbv6XB6bGmWv4e9OsNIDl0EP50hgIhsHAwu1desJP3hHAWoN/B/E0PpnjG0Aha16GrzQ3JGOeSgYlL3JAUdC1aZvDb2i5BwAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
    { createKey: "6DhJyjCMs4pRkTvy1Dig6zd9enRpWNTJE6FLvif5AsMN", configAuthority: knos.SYSTEM, threshold: 2, timeLock: 172800, transactionIndex: 0,
      staleTransactionIndex: 0, rentCollector: null, members: ["7FRUMUKVu63e78hw1dNL4dMH1hYYDxASqUqVRpVq7Y1C",
        "CE2KZgRhHaEJRwVqMWiFfmUkgU9veAhY3VrU8Vqc8xNz", "HEZTi6du87sv9jdgzbtFJmfLVtUxqzRPxYvxX7MWcssN"].map((key) => ({ key, permissions: 7 })) },
    "C57XKxbywVVTSvJhskMRKWW8X978yeWhq4ZSJkEsVCGn"],
  ["3fw9nvFdzWc5WWYEFkDrMmyzRaoiuWzdMQohQjfyyDWH",
    "4HR5ukShT+zeTFOY+Knj2hv/ktfmAqTtGwF9DpxI7RCJol6xju8KzwAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAgAAowIAAAAAAAAAAAAAAAAAAAAAAAEUK252ngj3hv377tTD/e6S/z97nizjtHAXQsw8P8tqT/wDAAAARufEo6Wjv9wFFwh5GPPVqmqD+95HTf8pw5IUdPKj7IcHXHs3n5Lq8AUtUI3pZWmSQ7rQbB00SmU0LPBtoQUq8aIHy+sHmYsw5qefkZtWhsqNJAL022dZegpNrw0bY8FNgmYH",
    { createKey: "Fxm1j2bZzxvvw6NkWfQjKh1WuXkEgfPdFRtbfiYmy8jp", configAuthority: knos.SYSTEM, threshold: 2, timeLock: 172800, transactionIndex: 0,
      staleTransactionIndex: 0, rentCollector: "2MjZmdfqem7K4dej76hrXGVEixPVhrFkLCC2oNQZranr", members: ["5mnWuy7EcUvz7yzy1ftvp3bCXnUUhE273YAAuSsN7ZB4",
        "7E1Uy463eTennkhNS2febLu4XFPt1kvk3xmufJFSDbBf", "Ej1dCSoxxjBRUC9LfhoUcXg7TA93BWaE9seCgpeTscCm"].map((key) => ({ key, permissions: 7 })) },
    "Ei2YVhRhRsJXHAnfFqmkkdgRj5LQdCmy1B4iqG4t1ELZ"],
];
for (const [address, data, want, vault] of recorded) {
  same(`a multisig on devnet, ${address.slice(0, 6)}: members, threshold, delay`, knos.readMultisig(Uint8Array.from(Buffer.from(data, "base64"))), want);
  same(`a multisig on devnet, ${address.slice(0, 6)}: its vault`, await knos.squadsVault(address), vault);
}
const tag = knos.hex(new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode("account:Multisig"))).slice(0, 8));
same("a multisig account starts with Anchor's tag for it", tag, "e07479ba44a14fec");
const ms = new Uint8Array(231);         // the layout of a 2-of-3 multisig with a 48-hour time lock and a rent collector
ms.set(knos.unhex(tag), 0); ms.set(knos.unb58(j.payer), 8); new DataView(ms.buffer).setUint16(72, 2, true);
new DataView(ms.buffer).setUint32(74, 172800, true); new DataView(ms.buffer).setBigUint64(78, 5n, true); ms[94] = 1; ms.set(knos.unb58(j.rent_to), 95);
ms[127] = 254; new DataView(ms.buffer).setUint32(128, 3, true);
[j.funder, j.relayer, j.address].forEach((m, at) => { ms.set(knos.unb58(m), 132 + 33 * at); ms[164 + 33 * at] = 7; });
same("a multisig: threshold, delay, members", knos.readMultisig(ms), { createKey: j.payer, configAuthority: knos.SYSTEM, threshold: 2, timeLock: 172800,
  transactionIndex: 5, staleTransactionIndex: 0, rentCollector: j.rent_to, members: [j.funder, j.relayer, j.address].map((m) => ({ key: m, permissions: 7 })) });
ms[94] = 0; ms.copyWithin(96, 128, 231);      // no rent collector: the members follow one byte sooner
same("a multisig without a rent collector", [knos.readMultisig(ms).rentCollector, knos.readMultisig(ms).members.length, knos.readMultisig(ms).members[2].key], [null, 3, j.address]);
same("not a multisig", [knos.readMultisig(new Uint8Array(231)), knos.readMultisig(null), knos.readMultisig(ms.slice(0, 120))], [null, null, null]);

// wallets: a stand-in for each kind, in a window of our own
class Window extends EventTarget { CustomEvent = CustomEvent; }
const signature = Uint8Array.from({ length: 64 }, (_x, at) => at + 1);
function standardWallet(name, log, { wallet = ["solana:mainnet", "solana:devnet"], shared = ["solana:devnet", "solana:mainnet"] } = {}) {
  const account = { address: j.authority, publicKey: knos.unb58(j.authority), chains: shared, features: ["solana:signAndSendTransaction"] };
  return { version: "1.0.0", name, icon: "data:image/svg+xml,", chains: wallet, accounts: [],
    features: { "standard:connect": { version: "1.0.0", connect: async () => ({ accounts: [account] }) },
      "solana:signAndSendTransaction": { version: "1.0.0", supportedTransactionVersions: ["legacy", 0],
        signAndSendTransaction: async (...inputs) => { log.push(...inputs); return inputs.map(() => ({ signature })); } } } };
}
// what a wallet does to register (the Wallet Standard's registerWallet): announce itself, and listen for the app
function registerWallet(win, wallet) {
  const callback = ({ register }) => register(wallet);
  win.dispatchEvent(new CustomEvent("wallet-standard:register-wallet", { detail: callback }));
  win.addEventListener("wallet-standard:app-ready", ({ detail: api }) => callback(api));
}
const [, [openIxs, openPayer]] = Object.entries(transactions)[0];
const openTx = knos.serializeTx(openIxs, openPayer, j.blockhash);

same("no window, no wallets", knos.wallets(undefined), []);
{
  const win = new Window(), log = [];
  registerWallet(win, standardWallet("Early", log));                 // the wallet loaded before the page's script
  same("a window with one wallet", knos.wallets(win).map((x) => [x.name, x.kind]), [["Early", "standard"]]);
  registerWallet(win, standardWallet("Late", log));                  // and one that loaded after
  registerWallet(win, { name: "Other chain", chains: ["bip122:000000000019d6689c085ae165831e93"], features: { "standard:connect": {} } });
  registerWallet(win, { name: "Cannot send", chains: ["solana:devnet"], features: { "standard:connect": {}, "solana:signTransaction": {} } });
  const found = knos.wallets(win);
  same("wallets that can sign and send on Solana, in the order they registered", found.map((x) => x.name), ["Early", "Late"]);
  same("a wallet connects to an address", await found[1].connect(), j.authority);
  same("a wallet signs and sends: the signature, as Solana writes it", await found[1].signAndSend(openTx, "solana:devnet"), knos.b58(signature));
  same("what the wallet was handed", [log.length, log[0].chain, log[0].account.address, b64(log[0].transaction)],
    [1, "solana:devnet", j.authority, s.transactions["open a balance"].transaction]);
  same("signing connects first when nobody did", await found[0].signAndSend(openTx), knos.b58(signature));
  registerWallet(win, standardWallet("Mainnet only", log, { wallet: ["solana:mainnet"], shared: ["solana:mainnet"] }));
  registerWallet(win, standardWallet("Account on mainnet", log, { shared: ["solana:mainnet"] }));
  registerWallet(win, standardWallet("Account with no list", log, { shared: undefined }));
  const [, , mainnetOnly, otherAccount, unlisted] = knos.wallets(win);
  await throws("a wallet that does not offer devnet is refused for devnet, in words", () => mainnetOnly.connect("solana:devnet"));
  await throws("so is a wallet whose account is not on devnet", () => otherAccount.connect("solana:devnet"));
  same("each is as good as it says for the chain it does offer", [await mainnetOnly.connect("solana:mainnet"), await otherAccount.connect("solana:mainnet")], [j.authority, j.authority]);
  same("an account that lists no chains is taken as it is", await unlisted.connect("solana:devnet"), j.authority);
  try { await mainnetOnly.connect("solana:devnet"); } catch (e) { same("the refusal says what to do", e.message, "Mainnet only has no devnet account to share. Set it to devnet and connect again."); }
}
{
  const win = new Window(), asked = [];
  win.phantom = { solana: { isPhantom: true, publicKey: null,
    connect: async () => ({ publicKey: { toString: () => j.authority } }),
    request: async (r) => { asked.push(r); return { signature: knos.b58(signature), publicKey: j.authority }; } } };
  const [phantom, ...others] = knos.wallets(win);
  same("Phantom's own provider is used when it did not register", [phantom.name, phantom.kind, others.length], ["Phantom", "phantom", 0]);
  same("Phantom connects", await phantom.connect(), j.authority);
  same("Phantom signs and sends", await phantom.signAndSend(openTx), knos.b58(signature));
  same("Phantom is asked with the message in base58", [asked[0].method, knos.hex(knos.unb58(asked[0].params.message, knos.messageOf(openTx).length))],
    ["signAndSendTransaction", s.transactions["open a balance"].message]);
  registerWallet(win, standardWallet("Phantom", []));
  same("a wallet that registered is not listed twice", knos.wallets(win).map((x) => x.kind), ["standard"]);
}
{
  const win = new Window(), sent = [];
  win.solana = { isPhantom: true, connect: async () => ({ publicKey: j.wallet }), request: async () => ({ signature }) };
  win.solflare = { isSolflare: true, publicKey: null,
    async connect() { this.publicKey = { toString: () => j.authority }; return true; },
    async signAndSendTransaction(t) { sent.push(t.version, b64(t.serialize({ verifySignatures: false, requireAllSignatures: false })), knos.hex(t.serializeMessage())); return knos.b58(signature); } };
  const [phantom, solflare] = knos.wallets(win);
  same("Phantom under its older name, then Solflare", [phantom.kind, solflare.name, solflare.kind], ["phantom", "Solflare", "solflare"]);
  same("an address given as text, a signature given as bytes", [await phantom.connect(), await phantom.signAndSend(openTx)], [j.wallet, knos.b58(signature)]);
  same("Solflare connects", await solflare.connect(), j.authority);
  same("Solflare signs and sends", await solflare.signAndSend(openTx), knos.b58(signature));
  same("Solflare is handed a legacy transaction that serialises to the same bytes", sent,
    [undefined, s.transactions["open a balance"].transaction, s.transactions["open a balance"].message]);
}

// JSON-RPC: what is asked and what comes back, with a stand-in for fetch
{
  const asked = [], filters = [], real = globalThis.fetch;
  const answers = { getAccountInfo: (p) => ({ value: p[0] === j.mint ? { owner: knos.TOKEN, lamports: 1461600, data: [b64(mintAccount), "base64"] } : null }),
    getProgramAccounts: () => [{ pubkey: bal, account: { data: [s.accounts.balance.data ? b64(knos.unhex(s.accounts.balance.data)) : "", "base64"] } }],
    getMultipleAccounts: (p) => ({ value: p[0].map((a) => (a === j.mint ? { owner: knos.TOKEN, lamports: 1461600, data: [b64(mintAccount), "base64"] } : null)) }),
    getSlot: () => 500, getBlockTime: (p) => (p[0] === 500 ? null : 1790000000 + p[0]),
    getSignatureStatuses: (p) => ({ value: [p[0][0] === "pending" ? null : p[0][0] === "failed" ? { err: { InstructionError: [0, { Custom: 98 }] }, confirmationStatus: "confirmed" }
      : { err: null, confirmationStatus: "confirmed" }] }) };
  globalThis.fetch = async (url, init) => {
    const body = JSON.parse(init.body);
    asked.push([url, body.method]);
    return { json: async () => (body.method in answers ? { jsonrpc: "2.0", id: 1, result: answers[body.method](body.params) } : { error: { message: "no such method" } }) };
  };
  try {
    same("an account's bytes", knos.readMint(await knos.account("rpc", j.mint)).decimals, 6);
    same("an account that does not exist", [await knos.account("rpc", j.wallet), await knos.accountInfo("rpc", j.wallet)], [null, null]);
    same("an account's owner", (await knos.accountInfo("rpc", j.mint)).owner, knos.TOKEN);
    const several = await knos.accounts("rpc", [j.wallet, j.mint]);
    same("several accounts, in the order asked", [several[0], several[1].owner, knos.readMint(several[1].data).decimals], [null, knos.TOKEN, 6]);
    same("the chain's clock is a block's time, the newest that has one", await knos.chainTime("rpc"), 1790000499);
    const got = await knos.programAccounts("rpc", s.programs.knos_pay, v2.BALANCE_LEN, 8, knos.u64le(j.owner_id));
    same("a program's accounts", [got.length, got[0].address, v2.readBalance(got[0].data).ownerId], [1, bal, j.owner_id]);
    // the marks a relayer paid for: one request, filtered by a mark's length and by the payer it names; what is not a mark is left out
    answers.getProgramAccounts = (p) => { filters.push(p[1].filters); return [M.accounts.mark, M.accounts["mark (rejected)"], M.accounts.credits].map((a, at) => ({ pubkey: [bal, bal22, jobBal][at], account: { data: [b64(knos.unhex(a.data)), "base64"] } })); };
    const mine = await knos.meter.client(s.programs.knos_meter).marksOf("rpc", j.relayer);
    same("the marks a relayer paid for", [mine.map(([address]) => address), mine.map(([, mark]) => mark.payer), filters],
      [[bal, bal22], [j.relayer, j.relayer], [[{ dataSize: 88 }, { memcmp: { offset: 48, bytes: j.relayer } }]]]);
    same("a confirmed transaction", await knos.confirmed("rpc", "landed", 3, async () => {}), { ok: true, err: null });
    same("a refused transaction, in the program's words", v2.errorWords((await knos.confirmed("rpc", "failed", 3, async () => {})).err), s.errors["98"]);
    same("a transaction nobody saw", await knos.confirmed("rpc", "pending", 3, async () => {}), null);
    await throws("an RPC error is an error", () => knos.rpc("rpc", "nope", []));
    same("each call went to the endpoint", [asked.length > 6, asked.every(([url]) => url === "rpc")], [true, true]);
    // a public endpoint's rate limit says nothing about the request: HTTP 429 (its body not even JSON), then an error of
    // code 429 in a body, are waited out (1 s, then 2 s) and the call is asked again; a limit that never ends is an error
    const served = globalThis.fetch, limits = [{ status: 429, json: async () => { throw new SyntaxError("not JSON"); } },
      { status: 200, json: async () => ({ jsonrpc: "2.0", id: 1, error: { code: 429, message: "Too many requests for a specific RPC call" } }) }];
    let tries = 0;
    const t0 = Date.now();
    globalThis.fetch = async (url, init) => (tries++ < limits.length ? limits[tries - 1] : served(url, init));
    same("a rate limit is waited out and the call asked again", [await knos.rpc("rpc", "getSlot", []), tries, Date.now() - t0 >= 2900], [500, 3, true]);
    tries = 0;
    globalThis.fetch = async () => { tries++; return { status: 429, json: async () => ({ jsonrpc: "2.0", id: 1, error: { code: 429, message: "Too Many Requests" } }) }; };
    await throws("a rate limit that does not end is an error, after five tries", () => knos.rpc("rpc", "getSlot", []));
    same("  five tries", tries, 5);
  } finally { globalThis.fetch = real; }
}

// ==== the README's two examples, as pasted, with a fake wallet and a fake network ====================================
{
  const readme = readFileSync(join(here, "README.md"), "utf8");
  const example = (heading) => /```js\n([\s\S]*?)```/.exec(readme.slice(readme.indexOf(`## ${heading}`)))[1];
  const fund = example("Fund an order from a wallet in the browser"), read = example("Read an account's record");
  same("the first example is 20 lines at most", fund.trimEnd().split("\n").length <= 20, true);
  same("the first deployment is mentioned once", readme.match(/first deployment/gi).length, 1);
  same("the README's program ids are the second deployment's", [fund, read].map((code) => [s.programs.knos_oidc, s.programs.knos_pay].every((id) => code.includes(id))), [true, true]);
  const pinned = /prove\.yml@([0-9a-f]{40})/.exec(readFileSync(join(here, "../../examples/knos-workflow.yml"), "utf8"))[1];
  same("the workflows the example pins are the ones the example workflow calls", fund.includes(`wfSha: "${pinned}"`), true);

  const repoId = 1353152983, userId = 142920951, win = new Window(), sent = [], lines = [];
  registerWallet(win, standardWallet("Fake", sent));
  const answers = { getLatestBlockhash: () => ({ value: { blockhash: j.blockhash, lastValidBlockHeight: 1 } }),
    getSignatureStatuses: () => ({ value: [{ err: null, confirmationStatus: "confirmed" }] }),
    getAccountInfo: async ([address]) => ({ value: address === await k2.rep(userId) ? { owner: s.programs.knos_pay, lamports: 1, data: [b64(knos.unhex(s.accounts.rep.data)), "base64"] } : null }) };
  const github = { "https://api.github.com/repos/drexthealpha/Knos": { id: repoId }, "https://api.github.com/users/drexthealpha": { id: userId } };
  const [real, log] = [globalThis.fetch, console.log], file = join(here, ".readme-example.mjs");
  globalThis.window = win;
  globalThis.fetch = async (url, init) => {
    if (url in github) return { json: async () => github[url] };
    const body = JSON.parse(init.body);
    return { json: async () => ({ jsonrpc: "2.0", id: 1, result: await answers[body.method](body.params) }) };
  };
  console.log = (...what) => lines.push(format(...what));
  try {
    for (const [at, code] of [fund, read].entries()) {
      writeFileSync(file, code);                       // inside the package, so that "knos-settle" is this very package
      await import(`${pathToFileURL(file)}?${at}`);
    }
  } finally { globalThis.fetch = real; console.log = log; delete globalThis.window; rmSync(file, { force: true }); }
  const want = await k2.fundOrderWalletIx({ funder: j.authority, funderToken: await knos.ata(j.authority, knos.USDC_DEVNET), mint: knos.USDC_DEVNET, repoId, issue: 7,
    amount: 25_000_000, terms: v2.termsJson(j.terms), wfRepo: j.wf_repo, wfSha: pinned });
  same("the wallet was asked once, on devnet, for the transaction the client builds", [sent.length, sent[0].chain, b64(sent[0].transaction)],
    [1, "solana:devnet", b64(knos.serializeTx([want], j.authority, j.blockhash))]);
  same("the first example says what happened", lines[0], "{ ok: true, err: null } - paid 25 test USDC and a fee of 0.625 on top");
  same("the second example prints the record", lines[1], "3 payments from 2 funders, 58.5 test USDC");
}

// ==== every export has a declaration (index.d.ts) =======================================================================
{
  const declarations = (file) => readFileSync(join(here, file), "utf8").replace(/\/\*[\s\S]*?\*\//g, "").replace(/\/\/.*$/gm, "");
  const dts = declarations("index.d.ts");
  // the members of `export interface name { ... }`: split at the `;` that sit outside every bracket
  const members = (name) => {
    const open = dts.indexOf("{", dts.search(new RegExp(`export interface ${name}\\b`)));
    let depth = 0, from = open + 1, parts = [];
    for (let at = open; at < dts.length; at++) {
      const c = dts[at];
      if ("{([".includes(c)) depth++;
      else if ("})]".includes(c) && --depth === 0) { parts.push(dts.slice(from, at)); break; }
      else if (c === ";" && depth === 1) { parts.push(dts.slice(from, at)); from = at + 1; }
    }
    return parts.map((p) => /^\s*(?:readonly\s+)?(\w+)\??\s*[(:<]/.exec(p)?.[1]).filter(Boolean);
  };
  const values = new Set(), declared = new Set();
  for (const [, kind, name] of dts.matchAll(/^export (?:declare )?(?:async )?(function|const|let|class|interface|type|enum)\s+(\w+)/gm)) {
    declared.add(name);
    if (!["interface", "type"].includes(kind)) values.add(name);
  }
  for (const [, list] of dts.matchAll(/^export \{([^}]*)\}/gm)) for (const part of list.split(",")) values.add(part.trim().split(/\s+as\s+/).pop());
  const missing = (what, have, want) => same(`${what}: declared and exported are the same names`,
    { undeclared: have.filter((x) => !want.includes(x)).sort(), stale: want.filter((x) => !have.includes(x)).sort() }, { undeclared: [], stale: [] });
  missing("index.js", Object.keys(knos), [...values]);
  const agentDts = declarations("agent.d.ts"), agentValues = [...agentDts.matchAll(/^export (?:declare )?(?:async )?(?:function|const|let|class)\s+(\w+)/gm)].map((m) => m[1]);
  missing("agent.js", Object.keys(await import("./agent.js")), agentValues);
  missing("knos.v2", Object.keys(knos.v2), members("V2"));
  missing("knos.meter", Object.keys(knos.meter), members("Meter"));
  missing("client(ids)", Object.keys(k), members("Client1"));
  missing("v2.client(ids)", Object.keys(k2), members("V2Client"));
  missing("verifier(program)", Object.keys(knos.verifier(knos.SYSTEM)), members("Verifier"));
  missing("meter.client(program)", Object.keys(mk), members("MeterClient"));
  same("every declaration of a value has a type that is declared", declared.has("Instruction") && declared.has("Order") && declared.has("Wallet"), true);
}

// the terms an agent reads: the fields knos.terms writes, `image` (the hermetic judge's) among them, and nothing else;
// `auto` and `quorum` are options in the order's flags and never keys of the terms
{
  const { parseTerms } = await import("./agent.js");
  const base = { accept: "ab".repeat(32), checks: [{ app: 15368, name: "test" }], deny: [], mode: "tests", paths: [], reserve: 7, v: 1 };
  const image = "docker.io/library/python@sha256:" + "c".repeat(64), text = (t) => JSON.stringify(t);
  same("terms an agent reads: the seven fields", parseTerms(text(base)), base);
  same("terms an agent reads: with the hermetic judge's image", parseTerms(text({ ...base, image }))?.image, image);
  same("terms an agent reads: with a policy and a vendor", parseTerms(text({ ...base, policy: "0f".repeat(32), vendor: 77 }))?.vendor, 77);
  same("terms an agent reads: refused", [{ ...base, image: "python:3.12" }, { ...base, mode: "merge", accept: "", image }, { ...base, auto: true },
    { ...base, quorum: 2 }, { ...base, policy: "x" }, { ...base, vendor: 0 }].map((t) => parseTerms(text(t))), [null, null, null, null, null, null]);
}

// the passkey wallet's helper and the agent calls have their own files and their own checks
await import("./passkey.test.mjs");
await import("./agent.test.mjs");

console.log(`sdk/settle: ${n} checks match the Python client (${first} for the first deployment, ${n - first} for the second and the browser)`);
