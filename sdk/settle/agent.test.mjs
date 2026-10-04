// node sdk/settle/agent.test.mjs   (sdk/settle/test.mjs runs it too)
// agent.js against recorded RPC: agent.recorded.json is what a public RPC would answer about a small history that the
// second deployment's test builds ran in LiteSVM (scripts/record_settle_agent.py): the accounts of the escrow, the
// meter and the token program, the transactions that named them with the programs' own log lines, and the signatures
// that named each address. A stand-in node answers from it, with the same filters a node applies; the expectations in
// the file come from the Python client and the programs' logs. Exit 1 on the first mismatch.
import { readFileSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import * as knos from "./index.js";
import * as agent from "./agent.js";

const here = dirname(fileURLToPath(import.meta.url));
const world = JSON.parse(readFileSync(join(here, "agent.recorded.json"), "utf8"));
const fx = JSON.parse(readFileSync(join(here, "fixtures.json"), "utf8"));
const want = world.expect, mint = world.mints.usdc;
let n = 0;
function same(name, got, expected) {
  n++;
  const text = (v) => JSON.stringify(v, (_k, x) => (typeof x === "bigint" ? `${x}n` : x));
  if (text(got) !== text(expected)) { console.error(`MISMATCH ${name}\n  got  ${text(got)}\n  want ${text(expected)}`); process.exit(1); }
}
const throws = async (name, f, words) => {
  let said = null;
  try { await f(); } catch (e) { said = e.message; }
  same(name, said !== null && (!words || said.includes(words)), true);
};

// ---- a node that answers from the recording, the way a node does ---------------------------------------------------------
const B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz";
function unbase58(text) {                              // any length; each leading "1" is a zero byte: not the client's decoder
  let big = 0n;
  for (const ch of text) big = big * 58n + BigInt(B58.indexOf(ch));
  const digits = big.toString(16), body = big === 0n ? [] : [...Buffer.from(digits.length % 2 ? `0${digits}` : digits, "hex")];
  return Buffer.from([...new Array(text.length - text.replace(/^1+/, "").length).fill(0), ...body]);
}

function node(w, { calls = [], drop = new Set() } = {}) {
  const info = (a) => (a ? { owner: a.owner, lamports: a.lamports, data: [a.data, "base64"] } : null);
  const matches = (a, f) => ("dataSize" in f ? Buffer.from(a.data, "base64").length === f.dataSize
    : Buffer.from(a.data, "base64").subarray(f.memcmp.offset, f.memcmp.offset + unbase58(f.memcmp.bytes).length).equals(unbase58(f.memcmp.bytes)));
  const methods = {
    getAccountInfo: ([address]) => ({ value: info(w.accounts[address]) }),
    getMultipleAccounts: ([addresses]) => ({ value: addresses.map((address) => info(w.accounts[address])) }),
    getProgramAccounts: ([program, { filters = [] }]) => Object.entries(w.accounts)
      .filter(([, a]) => a.owner === program && filters.every((f) => matches(a, f))).map(([pubkey, a]) => ({ pubkey, account: info(a) })),
    getSignaturesForAddress: ([address, { limit = 1000, before = null } = {}]) => {
      const all = w.signatures[address] ?? [], from = before ? all.indexOf(before) + 1 : 0;
      return all.slice(from, from + limit).map((signature) => ({ signature, slot: 1, err: null, blockTime: w.transactions[signature].blockTime }));
    },
    getTransaction: ([signature, { maxSupportedTransactionVersion: most = -1 } = {}]) => {
      // what a relay sends to a 2.1 cluster is a version 1 transaction, and a cluster gives one only to a reader that names that version
      if (most < 1) throw new Error("Transaction version (1) is not supported by the requesting client. Please try the request again with the higher supported version");
      const t = drop.has(signature) ? null : w.transactions[signature];
      return t ? { blockTime: t.blockTime, meta: { err: null, logMessages: t.logs }, transaction: { message: { accountKeys: t.keys } } } : null;
    },
    getSlot: () => w.clock.slot, getBlockTime: () => w.clock.time,
  };
  return async (_url, init) => {
    const body = JSON.parse(init.body);
    calls.push(body.method);
    if (!(body.method in methods)) return { json: async () => ({ error: { message: `${body.method}: a public RPC read this node does not have` } }) };
    let answer;
    try { answer = { result: methods[body.method](body.params) }; } catch (why) { answer = { error: { code: -32015, message: why.message } }; }
    return { json: async () => ({ jsonrpc: "2.0", id: 1, ...answer }) };
  };
}

const real = globalThis.fetch, calls = [];
globalThis.fetch = node(world, { calls });
const programs = world.programs, connection = { url: "rpc", programs, names: { [mint]: "test USDC" } };
const camel = (o) => Object.fromEntries(Object.entries(o).map(([k, v]) => [k.replace(/_(\w)/g, (_m, c) => c.toUpperCase()), v]).sort(([a], [b]) => (a < b ? -1 : 1)));   // the recording's keys are sorted

try {
  // a staging deployment, named by the same variable the Python client reads: only program addresses, each a real address
  const staging = join(here, ".staging-ids.test.json"), other = "11111111111111111111111111111112";
  try {
    writeFileSync(staging, JSON.stringify({ knos_pay: other, fee_owner: "ignored: not a program", staging: "a test" }));
    same("no variable: the pinned deployment", await agent.deployment({}), agent.DEPLOYMENT);
    same("KNOS_PROGRAM_IDS replaces the programs it names and nothing else", await agent.deployment({ KNOS_PROGRAM_IDS: staging }),
         { ...agent.DEPLOYMENT, knos_pay: other });
    writeFileSync(staging, JSON.stringify({ knos_pay: "not an address" }));
    await throws("a staging file with a wrong address is refused", () => agent.deployment({ KNOS_PROGRAM_IDS: staging }), "knos_pay is not an address");
    await throws("a staging file that is missing is refused in plain words", () => agent.deployment({ KNOS_PROGRAM_IDS: staging + ".none" }), "Unset it to use the pinned deployment");
  } finally { rmSync(staging, { force: true }); }
  same("the default programs are the second deployment's", [agent.DEPLOYMENT.knos_pay, agent.DEPLOYMENT.knos_meter, agent.DEPLOYMENT.knos_oidc],
    [fx.second.programs.knos_pay, fx.second.programs.knos_meter, fx.second.programs.knos_oidc]);

  // ==== terms, in words: the Python client's sentences ===========================================================================
  for (const [name, words] of Object.entries(want.terms_words)) same(`terms in words: ${name}`, agent.describe(JSON.parse(want.terms_json[name])), words);
  same("terms that name no checks", agent.describe({ accept: "", checks: [], deny: [], mode: "merge", paths: [], reserve: 0, v: 1 }),
    ["It names no checks: a maintainer's merge alone is the acceptance.", "Nobody can reserve it: the first accepted pull request is paid."]);
  same("one day is not days", agent.describe({ accept: "", checks: [], deny: [], mode: "merge", paths: ["a/**"], reserve: 1, v: 1 }).slice(1),
    ["The pull request may only change files matching `a/**`.", "`/knos take` reserves the issue for 1 day."]);

  // ==== quote ===================================================================================================================
  const q = await agent.quote(connection, want.issue.repo, want.issue.issue);
  const byAddress = Object.fromEntries(q.items.map((i) => [i.address, i]));
  same("every order and job on the issue, and nothing else", Object.keys(byAddress).sort(), [...want.orders.map((o) => o.address), want.job.address].sort());
  same("the issue and the chain's clock", [q.repoId, q.issue, q.at], [want.issue.repo, want.issue.issue, want.now]);
  same("the biggest offer first", q.items.map((i) => i.address), [want.orders[1].address, want.orders[0].address, want.job.address]);
  for (const o of want.orders) {
    const got = byAddress[o.address];
    same(`order ${o.address}: state, mode, money, deadline`, [got.kind, got.state, got.mode, got.mint, got.decimals, got.amount, got.fee, got.paid, got.authorReceives, got.deadline, got.expired, got.payable],
      ["order", o.state, o.mode === 0 ? "merge" : "tests", o.mint, o.decimals, o.amount, o.fee, o.paid, o.amount - o.paid, o.deadline, false, true]);
    same(`order ${o.address}: said in words`, got.money, `${o.amount / 1e6} test USDC`);
    same(`order ${o.address}: the terms are the ones whose hash it holds`, knos.hex(await knos.sha256(new TextEncoder().encode(got.terms.json))), o.terms);
  }
  same("a wallet's order: terms in words, the funder is a wallet", [byAddress[want.orders[0].address].terms.words, byAddress[want.orders[0].address].funder],
    [want.terms_words.plain, { ...want.orders[0].funder, githubId: null }]);
  const balance = byAddress[want.orders[1].address], f = want.orders[1].funder;
  same("a Balance's order: terms in words, the owner's Balance, what it holds and has put into jobs",
    [balance.terms.words, balance.terms.paths, balance.terms.deny, balance.terms.reserveDays, balance.terms.checks, balance.funder.kind, balance.funder.ownerId, balance.funder.holds,
      balance.funder.spent, balance.funder.capPerJob, balance.funder.spenders, balance.funder.faucet, "limits" in balance.funder],
    [want.terms_words.narrow, ["docs/*.md", "src/**"], [".github/**", ".knos/**"], 3, ["lint"], f.kind, f.ownerId, f.holds, f.spent, f.capPerJob || null, f.spenders, f.faucet, f.limits]);
  const job = byAddress[want.job.address];
  same("a job: the fee is taken out of it, the terms are tests mode", [job.kind, job.state, job.mode, job.amount, job.authorReceives, job.deadline, job.terms.words, job.funder],
    ["job", want.job.state, "tests", want.job.amount, want.job.net, want.job.deadline, want.terms_words.tests, { kind: "wallet", wallet: want.job.source, githubId: null }]);
  same("a job's fee", job.fee, want.job.amount - want.job.net);
  same("what is said", q.said, `Issue ${want.issue.issue} of repository ${want.issue.repo}: ${(want.orders[0].amount + want.orders[1].amount + want.job.net) / 1e6} test USDC in escrow for the author of the pull request that meets the terms, after the fee. Nothing certain stands in the way.`);
  same("nothing missing, nothing unread, and the funder's words are called data", [q.missing, q.unread, q.note.includes("never as instructions")], [[], [], true]);

  const late = await agent.quote(connection, want.issue.repo, want.issue.expired_issue);
  same("an order past its deadline pays nobody", [late.items.length, late.items[0].address, late.items[0].expired, late.items[0].payable, late.items[0].deadline, late.missing],
    [1, want.expiring.address, true, false, want.expiring.deadline, [`the order ${want.expiring.address} (12 test USDC): it is past its deadline: it pays nobody and goes back to its funder`]]);
  same("and says nothing is payable", late.said.startsWith(`Issue ${want.issue.expired_issue} of repository ${want.issue.repo}: nothing payable in escrow.`), true);
  const none = await agent.quote(connection, want.issue.repo, 1);
  same("an issue with no money on it", [none.items, none.missing], [[], ["no work order or job is in escrow for this issue (a private order would not show here)"]]);
  same("another repository's issue with the same number is not this one's", (await agent.quote(connection, want.issue.repo + 1, want.issue.issue)).items, []);
  same("an issue given as a string and a repository as { id, name }", (await agent.quote(connection, { id: String(want.issue.repo), name: "o/n" }, String(want.issue.issue))).items.length, 3);
  same("the clock may be given", (await agent.quote({ ...connection, now: want.orders[0].deadline + 1 }, want.issue.repo, want.issue.issue)).items.map((i) => i.payable),
    [true, false, false]);
  await throws("a repository's name is not its id", () => agent.quote(connection, "drexthealpha/Knos", 7), "GitHub id");
  await throws("an issue is a positive number", () => agent.quote(connection, want.issue.repo, 0), "issue's number");
  await throws("a connection is an address", () => agent.quote({}, want.issue.repo, 7), "RPC address");

  // terms the funding did not log, or logged as something else, are not believed
  const forged = structuredClone(world);
  for (const t of Object.values(forged.transactions)) t.logs = t.logs.map((line) => (line.includes("knos3:terms ") ? line.replace('"reserve":7', '"reserve":9') : line));
  globalThis.fetch = node(forged);
  const doubted = await agent.quote(connection, want.issue.repo, want.issue.issue);
  same("terms whose hash is not the account's are not read", [doubted.items.find((i) => i.address === want.orders[0].address).terms, doubted.unread],
    [null, [`the terms of the order ${want.orders[0].address}`]]);
  const lone = structuredClone(world);
  for (const t of Object.values(lone.transactions)) t.logs = t.logs.filter((line) => !line.includes("knos2:terms "));
  globalThis.fetch = node(lone);
  same("a job whose terms line is gone is quoted, and the terms are unread", [(await agent.quote(connection, want.issue.repo, want.issue.issue)).unread],
    [[`the terms of the job ${want.job.address}`]]);
  globalThis.fetch = node(world, { calls });

  // ==== eligible ==================================================================================================================
  const e = await agent.eligible(connection, { id: want.issue.repo, name: "drexthealpha/Knos" }, want.issue.issue, 12);
  same("eligible says it is server-side work, and does not guess", [e.decided, e.eligible, e.serverSide], [false, null, true]);
  same("it points to `knos attest` for each order that could pay, not for the job", e.attest.map((a) => a.command),
    [want.orders[1], want.orders[0]].map((o) => `knos attest --repository drexthealpha/Knos --pull 12 --order ${o.address} --kind pay`));
  same("and says what the chain does say", [e.said.includes("decided on a server"), e.said.includes("`knos attest`"), e.said.endsWith("On the chain, 3 offers could pay: 30 test USDC, 20 test USDC, 14.625 test USDC."),
    e.orders.length], [true, true, true, 3]);
  const bare = await agent.eligible(connection, want.issue.repo, want.issue.expired_issue);
  same("without the repository's name or a pull request the command has placeholders, and nothing could pay", [bare.attest, bare.said.endsWith("On the chain, nothing could pay now.")], [[], true]);
  same("placeholders", (await agent.eligible(connection, want.issue.repo, want.issue.issue)).attest[0].command.startsWith("knos attest --repository OWNER/REPO --pull PULL_NUMBER --order "), true);

  // ==== statement =================================================================================================================
  const st = want.statement, month = "2026-10";
  const s = await agent.statement(connection, st.seller, month);
  const buyers = Object.keys(st.meter_accounts).sort((a, b) => a - b);
  same("each buyer's month: the account, recomputed from the meter's logs, and agreeing",
    s.meter.buyers.map((b) => [b.buyerId, b.evaluations, b.accepted, b.rejected, b.value, b.fees, camel(b.recomputed), b.agrees]),
    buyers.map((b) => { const a = camel(st.meter_accounts[b]); return [a.buyerId, a.evaluations, a.accepted, a.rejected, a.value, a.fees, camel(st.meter[b]), true]; }));
  same("the sums over buyers", [s.meter.evaluations, s.meter.accepted, s.meter.rejected, s.meter.value, s.meter.fees],
    ["evaluations", "accepted", "rejected", "value", "fees"].map((k) => buyers.reduce((a, b) => a + st.meter_accounts[b][k], 0)));
  same("the payments the escrow logged to the seller that month, oldest first, from its own lines", s.escrow.payments.map((p) => [p.signature, `knos3:paid order=${p.order} pr=${p.pull} payee=${s.seller} amount=${p.amount} to=${p.to}`]),
    st.escrow.map((x) => [x.signature, x.line]));
  same("the payment's time is its transaction's", s.escrow.payments.map((p) => p.at), st.escrow.map((x) => world.transactions[x.signature].blockTime));
  same("what was paid in all, and that the whole history was read", [s.escrow.paid, s.escrow.complete, s.escrow.unread, s.escrow.scanned > 0], [st.escrow.reduce((a, x) => a + Number(/amount=(\d+)/.exec(x.line)[1]), 0), true, 0, true]);
  same("the month, as words and as times", [s.month, s.seller, s.from, s.to], [month, st.seller, Date.UTC(2026, 9, 1) / 1000, Date.UTC(2026, 10, 1) / 1000]);
  same("said in words", s.said, `Seller ${st.seller}, ${month}: 4 billable evaluations (3 accepted, 1 rejected) across 2 buyers, and 2 payments from the escrow.`);
  same("nothing to note but the units", s.notes, ["Amounts are in the smallest units of the mint, as the programs logged them: USDC has six decimals."]);
  same("the month as a number", (await agent.statement(connection, st.seller, 202610)).escrow.payments.length, 2);

  const before = await agent.statement(connection, st.seller, "2026-09");
  same("the month before: only what happened then", [before.meter.buyers.map((b) => [b.buyerId, b.evaluations, b.accepted, b.rejected, b.value, b.fees, b.agrees]),
    before.escrow.payments.map((p) => `knos3:paid order=${p.order} pr=${p.pull} payee=${before.seller} amount=${p.amount} to=${p.to}`)],
    [[[camel(st.september).buyerId, st.september.evaluations, st.september.accepted, st.september.rejected, st.september.value, st.september.fees, true]], st.september_escrow]);
  const none2 = await agent.statement(connection, st.seller, "2026-08");
  same("a month before there was anything", [none2.meter.buyers, none2.escrow.payments, none2.escrow.complete, none2.meter.evaluations], [[], [], true, 0]);
  same("a seller nobody paid", (await agent.statement(connection, 1, month)).escrow.payments, []);
  const short = await agent.statement(connection, st.seller, month, { most: 2 });
  same("a history read only in part says so, and what it did read is a lower bound", [short.escrow.complete, short.escrow.scanned, short.notes.some((x) => x.startsWith("Only the newest 2 transactions"))], [false, 2, true]);
  await throws("a month is written 2026-10", () => agent.statement(connection, st.seller, "October"), "2026-10");
  await throws("a seller is a GitHub id", () => agent.statement(connection, "me", month), "seller's GitHub id");

  // a node whose history is cut short cannot make the account's count smaller
  const cut = structuredClone(world), account = await knos.meter.client(programs.knos_meter).monthPda(buyers[0], st.seller, want.month);
  delete cut.signatures[account];
  globalThis.fetch = node(cut);
  const doubt = await agent.statement(connection, st.seller, month);
  same("a month account the node has no history for: the account is the count, and the difference is said", [doubt.meter.buyers[0].evaluations, doubt.meter.buyers[0].recomputed.evaluations, doubt.meter.buyers[0].agrees, doubt.notes[0]],
    [st.meter_accounts[buyers[0]].evaluations, 0, false, `For buyer ${buyers[0]} the meter's log in this node's history differs from its month account: the node's history is cut short, and the account is the count.`]);
  const lost = new Set(world.signatures[programs.knos_pay].filter((sig) => world.transactions[sig].logs.some((line) => line.includes("knos3:paid"))));
  globalThis.fetch = node(world, { drop: lost });
  const unread = await agent.statement(connection, st.seller, month);
  same("transactions the node will not give are counted, never guessed", [unread.escrow.unread, unread.escrow.payments.length, unread.notes.some((x) => x.includes("lower bound"))], [st.escrow.length, 0, true]);
  globalThis.fetch = node(world, { calls });

  // ==== public RPC reads and nothing else ===========================================================================================
  same("only reads were asked of the node", [...new Set(calls)].sort(), ["getBlockTime", "getMultipleAccounts", "getProgramAccounts", "getSignaturesForAddress", "getSlot", "getTransaction"]);
  same("none of them sends or simulates", calls.some((m) => /send|simulate|request/i.test(m)), false);

  // ==== the README's example, as pasted, against a chain with nothing on it =====================================================
  const readme = readFileSync(join(here, "README.md"), "utf8"), block = /```js\n(import \{ quote[\s\S]*?)```/.exec(readme.slice(readme.indexOf("## Three calls")))[1];
  const empty = { clock: world.clock, accounts: {}, signatures: {}, transactions: {} }, printed = [], log = console.log, file = join(here, ".readme-agent.mjs");
  globalThis.fetch = node(empty);
  console.log = (...what) => printed.push(what.join(" "));
  try { writeFileSync(file, block); await import(pathToFileURL(file).href); } finally { console.log = log; rmSync(file, { force: true }); }
  same("the README's agent example runs as pasted and prints three answers", [printed.length, printed[0].startsWith("Issue 7 of repository 1353152983: nothing payable in escrow."),
    printed[1].includes("`knos attest`"), printed[2]], [3, true, true, "Seller 142920951, 2026-10: 0 billable evaluations (0 accepted, 0 rejected) across 0 buyers, and 0 payments from the escrow."]);
  const ids = JSON.parse(readFileSync(join(here, "../../src/knos/settle/v2/program_ids.json"), "utf8"));
  same("its repository and seller are ids the programs file names", [ids.attest_repo_ids.includes(1353152983), ids.attest_owner_id], [true, 142920951]);
} finally { globalThis.fetch = real; }

console.log(`sdk/settle/agent: ${n} checks against recorded RPC (${Object.keys(world.accounts).length} accounts, ${Object.keys(world.transactions).length} transactions)`);
