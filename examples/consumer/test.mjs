// node --test examples/consumer/test.mjs: the consumer against a recorded order (fixtures/order_paid.json), offline.
// Each test changes one thing the receipt, the status file or the cluster says, and the decision must name it.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { b58decode, decideReceipt, decideStatus, knosId, liveRpc, logsOf, main, milestoneOf, orderScope, recordedRpc, schemaErrors } from "./consumer.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
const FIXTURE = join(HERE, "fixtures", "order_paid.json");
const fresh = () => JSON.parse(readFileSync(FIXTURE, "utf8"));
const PAY = "5y7iWJ1VAMJjnnWbbdo2a2PsWJEwTExSNpzrvQSEnS8k";

async function decide(edit = () => {}) {
  const f = fresh();
  edit(f);
  return decideReceipt(f.receipt, recordedRpc(f.rpc));
}
const paying = (f) => f.rpc[`getTransaction ${f.receipt.transaction.signature}`];
const fundingTx = (f) => f.rpc[`getTransaction ${f.receipt.commercial_authorisation.funded}`];
const no = (d, text) => assert.ok(!d.paid && d.disagrees.some((x) => x.includes(text)), `${text} not in ${JSON.stringify(d.disagrees)}`);

test("the recorded order is paid, by its transaction, under its terms hash", async () => {
  const f = fresh(), d = await decide();
  assert.equal(d.paid, true, JSON.stringify(d.disagrees));
  assert.equal(d.transaction, f.receipt.transaction.signature);
  assert.equal(d.terms_hash, f.receipt.policy.terms_hash);
  assert.deepEqual(d.disagrees, []);
});

test("a receipt that names another wallet, amount, fee or terms hash is not shown paid", async () => {
  no(await decide((f) => { f.receipt.payees[0].to = f.receipt.order; }), "knos_pay logged");
  no(await decide((f) => { f.receipt.amounts.tip = "1"; }), "the receipt says paid");
  no(await decide((f) => { f.receipt.policy.terms_hash = "0".repeat(64); }), "fixed terms");
  no(await decide((f) => { f.receipt.transaction.slot += 1; }), "the receipt says slot");
  no(await decide((f) => { f.receipt.ids.settlement = "stl_" + "0".repeat(24); }), "the receipt's ids");
});

test("a receipt that does not fit its published schema is refused before the chain is asked", async () => {
  let asked = 0;
  const f = fresh();
  f.receipt.extra = 1;
  const d = await decideReceipt(f.receipt, async () => { asked++; return null; });
  assert.equal(asked, 0);
  no(d, "extra is not a field of this version");
  f.receipt = { ...fresh().receipt, version: 3 };
  no(await decideReceipt(f.receipt, recordedRpc(f.rpc)), "receipt version 3 is not read here");
});

test("a receipt that names another program than the IDL's knos_pay is refused", async () => {
  no(await decide((f) => { f.receipt.program = "11111111111111111111111111111111"; }), "knos_pay in the IDL is");
});

test("a transaction the cluster does not have finalized, or that failed, pays nothing", async () => {
  no(await decide((f) => { delete f.rpc[`getTransaction ${f.receipt.transaction.signature}`]; }), "no finalized transaction");
  no(await decide((f) => { paying(f).meta.err = { InstructionError: [1, { Custom: 91 }] }; }), "failed on chain");
});

test("a payment line printed by another program is not knos_pay's word", async () => {
  // the same lines, moved into a frame of a program the payment called: they no longer count
  const d = await decide((f) => {
    const logs = paying(f).meta.logMessages, at = logs.findIndex((l) => l.includes("knos3:paid"));
    logs.splice(at, 0, "Program Evi1111111111111111111111111111111111111 invoke [2]");
    logs.splice(at + 3, 0, "Program Evi1111111111111111111111111111111111111 success");
  });
  no(d, "paid nobody");
  const plain = fresh(), tx = paying(plain);
  assert.equal(logsOf(tx, PAY).lines.filter((l) => l.startsWith("knos3:paid")).length, 1);
  assert.equal(logsOf(tx, "Evi1111111111111111111111111111111111111").lines.length, 0);
});

test("a truncated log decides nothing", async () => {
  no(await decide((f) => { paying(f).meta.logMessages.push("Log truncated"); }), "truncated");
});

test("token balances, when the cluster gives them, must show the payee received the amount", async () => {
  const withBalances = (got) => (f) => {
    const { mint } = f.receipt.amounts, owner = f.receipt.payees[0].to;
    paying(f).meta.preTokenBalances = [];
    paying(f).meta.postTokenBalances = [{ accountIndex: 0, mint, owner, uiTokenAmount: { amount: got } }];
  };
  const good = await decide(withBalances("20000000"));
  assert.equal(good.paid, true, JSON.stringify(good.disagrees));
  no(await decide(withBalances("19000000")), "received 19000000");
});

test("a private order's terms hash is read from the funding instruction", async () => {
  const d = await decide((f) => {
    const tx = fundingTx(f), logs = tx.meta.logMessages;
    tx.meta.logMessages = logs.filter((l) => !l.includes("knos3:terms")).map((l) => l.replace(/ flags=0 /, " flags=2 "));
    const keys = tx.transaction.message.accountKeys, ix = tx.transaction.message.instructions.find((i) => keys[i.programIdIndex] === PAY);
    const data = b58decode(ix.data), hash = Buffer.from(f.receipt.policy.terms_hash, "hex");
    const changed = Buffer.concat([Buffer.from(data.slice(0, 1)), Buffer.from([64, 0, 0, 0]), Buffer.alloc(32, 7), hash]);
    ix.data = b58encode(changed);
  });
  assert.equal(d.paid, true, JSON.stringify(d.disagrees));
  assert.ok(d.agrees.some((x) => x.includes("a private order")));
});

test("the status file's payments on chain are decided line by line", async () => {
  const f = fresh(), rpc = recordedRpc(f.rpc);
  const d = await decideStatus(f.status, rpc);
  assert.equal(d.paid, true, JSON.stringify(d));
  assert.equal(d.lines[0].order, f.receipt.order);
  assert.equal(d.lines[0].terms_hash, f.receipt.policy.terms_hash);
  const other = structuredClone(f.status);
  other.events[0].deliverable = knosId("deliverable", "ab".repeat(32), 0);
  const bad = await decideStatus(other, rpc);
  assert.equal(bad.paid, false);
  assert.ok(bad.lines[0].disagrees.some((x) => x.includes("is not of order")));
});

test("the ids follow the published vectors (conformance/vectors/ids.v1.json)", () => {
  const vectors = JSON.parse(readFileSync(join(HERE, "..", "..", "conformance", "vectors", "ids.v1.json"), "utf8")).cases;
  const run = { "ids.deliverable": (i) => knosId("deliverable", i.scope, i.key), "ids.settlement": (i) => knosId("settlement", i.deliverable, i.method, i.reference),
    "ids.order_scope": (i) => orderScope(i.order) };
  const cases = vectors.filter((c) => c.op in run && c.expect.output);
  assert.ok(cases.length >= 3 && cases.some((c) => c.op === "ids.order_scope"));
  for (const c of cases) assert.equal(run[c.op](c.input), c.expect.output, c.id);
});

// -- what devnet answers: transactions of version 1 (what the relay sends) and 0 (address lookup tables) ---------------
const BUDGET = "ComputeBudget111111111111111111111111111111";

/** `tx` as a cluster gives a version 1 transaction (SIMD-0385): its limits in the message, no compute budget instruction. */
function asVersion1(tx) {
  const m = tx.transaction.message, keys = m.accountKeys;
  m.instructions = m.instructions.filter((ix) => keys[ix.programIdIndex] !== BUDGET);
  m.transactionConfig = { computeUnitLimit: 1400000, heapSize: null, loadedAccountsDataSizeLimit: 67108864, priorityFee: null };
  m.header = { numRequiredSignatures: 1, numReadonlySignedAccounts: 0, numReadonlyUnsignedAccounts: 3 };
  tx.meta.logMessages = tx.meta.logMessages.filter((l) => !l.startsWith(`Program ${BUDGET} `));
  tx.version = 1;
}

/** `tx` as a cluster gives a version 0 transaction that loads `address` from an address lookup table. */
function asVersion0(tx, address) {
  const m = tx.transaction.message, before = [...m.accountKeys];
  m.accountKeys = before.filter((k) => k !== address);
  const after = [...m.accountKeys, address], at = (i) => after.indexOf(before[i]);
  for (const ix of [...m.instructions, ...(tx.meta.innerInstructions || []).flatMap((x) => x.instructions)]) {
    ix.programIdIndex = at(ix.programIdIndex);
    ix.accounts = ix.accounts.map(at);
  }
  m.addressTableLookups = [{ accountKey: "4Nd1mBQtrMJVYVfKf2PJy9NZUZdTAsp7D4xWLs4gDB4T", writableIndexes: [0], readonlyIndexes: [] }];
  tx.meta.loadedAddresses = { writable: [address], readonly: [] };
  tx.version = 0;
}

test("a payment sent as a version 1 transaction, as the relay sends it, is read; asked with version 0, the cluster refuses", async () => {
  const d = await decide((f) => { asVersion1(paying(f)); asVersion1(fundingTx(f)); });
  assert.equal(d.paid, true, JSON.stringify(d.disagrees));
  const f = fresh();
  asVersion1(paying(f));
  const sig = f.receipt.transaction.signature, rpc = recordedRpc(f.rpc);
  await assert.rejects(rpc("getTransaction", [sig, { encoding: "json", maxSupportedTransactionVersion: 0 }]), /Transaction version \(1\) is not supported/);
  await assert.rejects(rpc("getTransaction", [sig, { encoding: "json" }]), /maxSupportedTransactionVersion/);
  const s = await decideStatus(f.status, rpc);
  assert.equal(s.paid, true, JSON.stringify(s));
});

test("a version 0 transaction whose order comes from an address lookup table is read", async () => {
  const d = await decide((f) => {
    asVersion0(paying(f), f.receipt.order);
    assert.ok(!paying(f).transaction.message.accountKeys.includes(f.receipt.order));
  });
  assert.equal(d.paid, true, JSON.stringify(d.disagrees));
  no(await decide((f) => { asVersion0(paying(f), f.receipt.order); paying(f).meta.loadedAddresses.writable = [f.receipt.payees[0].to]; }), "paid nobody");
});

test("a status line named by the audit export's billing key (a witnessed statement's) is the order's deliverable", async () => {
  const f = fresh(), order = f.receipt.order, funded = f.receipt.commercial_authorisation.funded, ev = f.status.events[0];
  ev.deliverable = knosId("deliverable", `${order}:${funded}`, 0);
  ev.settlement = knosId("settlement", ev.deliverable, "chain", ev.reference);
  const d = await decideStatus(f.status, recordedRpc(f.rpc));
  assert.equal(d.paid, true, JSON.stringify(d));
  assert.ok(d.lines[0].agrees.some((x) => x.includes(`milestone 0 of that order, named by its billing key (the order and its funding ${funded})`)));
  // the same key with another funding transaction is another order's: not this one
  ev.deliverable = knosId("deliverable", `${order}:${f.receipt.transaction.signature}`, 0);
  ev.settlement = knosId("settlement", ev.deliverable, "chain", ev.reference);
  const bad = await decideStatus(f.status, recordedRpc(f.rpc));
  assert.ok(!bad.paid && bad.lines[0].disagrees.some((x) => x.includes("is not of order")));
});

test("a standing order's deliverable is its pull request, as the payment logged it", () => {
  const order = "5vTDcEUuQhkxbntCzyJjYZc4kvsKbqEmyDoe9r8o9Pq3", funded = "5zsTQHHcqHDm7dZYAvFdhVG1CzWKDnXGsRdbvtkCM3GqSRjYiR4yhxgcwAJpahjbUUZsHPec53r1b6aAJ1vETu5B";
  assert.deepEqual(milestoneOf(knosId("deliverable", orderScope(order), 1574), order, funded, [1574]), { milestone: 1574, by: "the order" });
  assert.equal(milestoneOf(knosId("deliverable", orderScope(order), 1574), order, funded, []), null);
  assert.equal(milestoneOf(knosId("deliverable", `${order}:${funded}`, 1574), order, funded, [1574]).milestone, 1574);
  assert.equal(milestoneOf(knosId("deliverable", `${order}:${funded}`, 0), order, undefined, []), null);
});

test("a busy endpoint (HTTP 429) is asked again, then reported", async () => {
  const answers = (statuses) => {
    let n = 0;
    return async () => { const status = statuses[Math.min(n++, statuses.length - 1)];
      return { status, json: async () => (status === 429 ? { jsonrpc: "2.0", error: { code: 429, message: "Too many requests" } } : { jsonrpc: "2.0", result: "ok" }) }; };
  };
  assert.equal(await liveRpc("http://rpc.invalid", 1000, { fetchFn: answers([429, 429, 200]), waits: [0, 0, 0] })("getSlot", []), "ok");
  await assert.rejects(liveRpc("http://rpc.invalid", 1000, { fetchFn: answers([429]), waits: [0, 0] })("getSlot", []), /getSlot: Too many requests/);
});

test("the schema keywords are read as JSON Schema reads them", () => {
  const s = { type: "object", required: ["a"], additionalProperties: false, properties: { a: { oneOf: [{ type: "null" }, { type: "string", pattern: "^x+$" }] } } };
  assert.deepEqual(schemaErrors(s, { a: "xx" }), []);
  assert.deepEqual(schemaErrors(s, { a: null }), []);
  assert.equal(schemaErrors(s, { a: "y" }).length, 1);
  assert.equal(schemaErrors(s, {}).length, 1);
});

test("the command: exit 0 when paid, 1 when not, 2 when used wrongly", async () => {
  const [code, text] = await main(["receipt", join(HERE, "fixtures", "receipt.json"), "--recorded", FIXTURE]);
  assert.equal(code, 0, text);
  assert.match(text, /^PAID: order /);
  const [code2, json] = await main(["status", join(HERE, "fixtures", "status.json"), "--recorded", FIXTURE, "--json"]);
  assert.equal(code2, 0, json);
  assert.equal(JSON.parse(json).lines.length, 1);
  assert.equal((await main(["receipt", FIXTURE, "--recorded", FIXTURE]))[0], 1);
  assert.equal((await main(["receipt"]))[0], 2);
});

function b58encode(bytes) {
  const A = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz";
  let n = BigInt("0x" + (Buffer.from(bytes).toString("hex") || "0")), out = "";
  while (n > 0n) { out = A[Number(n % 58n)] + out; n /= 58n; }
  for (const b of bytes) { if (b !== 0) break; out = "1" + out; }
  return out;
}
