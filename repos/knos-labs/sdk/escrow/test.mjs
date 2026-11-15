// Offline: the builders' encodings equal the Python builders' (fixtures.json from scripts/escrow_fixtures.py) byte for
// byte, and the account table equals programs/knos_escrow/idl.json. Run: node --test sdk/escrow/
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createEscrow, decodeJob, LAYOUT, JOB_LEN, CONFIG_LEN } from "./index.js";

const here = new URL(".", import.meta.url);
const fx = JSON.parse(readFileSync(new URL("fixtures.json", here), "utf8"));
const idl = JSON.parse(readFileSync(new URL("../../programs/knos_escrow/idl.json", here), "utf8"));

// A minimal PublicKey: base58 in and out; PDAs come from the fixture (derived by solders), keyed by their seeds.
const ALPHA = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz";
const b58decode = (s) => {
  let n = 0n; for (const c of s) n = n * 58n + BigInt(ALPHA.indexOf(c));
  const out = new Uint8Array(32); for (let i = 31; i >= 0; i--) { out[i] = Number(n & 255n); n >>= 8n; }
  return out;
};
const b58encode = (b) => {
  let n = 0n; for (const x of b) n = n * 256n + BigInt(x);
  let s = ""; while (n > 0n) { s = ALPHA[Number(n % 58n)] + s; n /= 58n; }
  for (const x of b) { if (x !== 0) break; s = "1" + s; }
  return s;
};
const hex = (b) => Buffer.from(b).toString("hex");
class FakeKey {
  constructor(v) { this.b = typeof v === "string" ? b58decode(v) : Uint8Array.from(v); }
  toBytes() { return this.b; }
  toBase58() { return b58encode(this.b); }
  static findProgramAddressSync(seeds, pid) {
    assert.equal(pid.toBase58(), fx.program_id);
    const label = new TextDecoder().decode(seeds[0]);
    if (label === "job") { assert.equal(hex(seeds[1]), fx.bytes32.job_id); return [new FakeKey(fx.pdas.job), 255]; }
    return [new FakeKey(fx.pdas[label]), 255];
  }
}

const K = Object.fromEntries(Object.entries(fx.keys).map(([n, v]) => [n, new FakeKey(v)]));
const H = fx.bytes32;
const { amount, work, review } = fx.numbers;
const escrow = createEscrow({ PublicKey: FakeKey, programId: fx.program_id });
const common = { jobId: H.job_id, vaultToken: K.vault_token, workerToken: K.worker_token, feeToken: K.fee_token,
  buyerToken: K.buyer_token, buyer: K.buyer };
const BUILD = {
  post: (o) => escrow.post({ buyer: K.buyer, jobId: H.job_id, amount, work, review, brief: H.brief,
    buyerToken: K.buyer_token, vaultToken: K.vault_token, verifier: o.verifier ? K[o.verifier] : undefined }),
  claim: () => escrow.claim({ worker: K.worker, ...common }),
  deliver: () => escrow.deliver({ worker: K.worker, result: H.result, ...common }),
  accept: () => escrow.accept(common),
  release: () => escrow.release({ anyone: K.anyone, ...common }),
  verify_release: () => escrow.verifyRelease({ verifier: K.verifier, resultHash: H.result, proofRoot: H.proof, ...common }),
  reject: () => escrow.reject(common),
  refund: () => escrow.refund(common),
  verify_reject: () => escrow.verifyReject({ verifier: K.verifier, proofRoot: H.proof, ...common }),
  settle: (o) => escrow.settle({ signer: K[o.signer], ...common }),
};

for (const want of fx.instructions) {
  test(`${want.name} ${JSON.stringify(want.options)} matches the Python builder`, () => {
    const ix = BUILD[want.name](want.options);
    assert.equal(ix.programId.toBase58(), fx.program_id);
    assert.equal(hex(ix.data), want.data);
    assert.deepEqual(ix.keys.map((k) => ({ pubkey: k.pubkey.toBase58(), signer: k.isSigner, writable: k.isWritable })),
      want.accounts);
  });
}

test("every builder has a fixture", () => {
  assert.deepEqual(new Set(fx.instructions.map((i) => i.name)), new Set(Object.keys(BUILD)));
});

test("LAYOUT equals idl.json (tags, account names, signer and writable)", () => {
  for (const [name, [tag, metas]] of Object.entries(LAYOUT)) {
    const entry = idl.instructions.find((i) => i.name === name);
    assert.ok(entry, name);
    assert.deepEqual(entry.discriminator, [tag]);
    assert.deepEqual(entry.accounts.map((a) => [a.name, !!a.signer, !!a.writable]), metas, name);
  }
  const size = (t) => (typeof t === "string" ? { u8: 1, u16: 2, u64: 8, i64: 8, pubkey: 32 }[t] : t.array[1]);
  const len = (n) => idl.types.find((t) => t.name === n).type.fields.reduce((s, f) => s + size(f.type), 0);
  assert.equal(len("Job"), JOB_LEN);
  assert.equal(len("Config2"), CONFIG_LEN);
});

test("decodeJob reads what sol.parse_job reads", () => {
  const j = decodeJob(Buffer.from(fx.job.hex, "hex"), FakeKey);
  const w = fx.job;
  assert.equal(j.state, w.state);
  assert.equal(j.buyer.toBase58(), w.buyer);
  assert.equal(j.worker.toBase58(), w.worker);
  assert.equal(j.verifier.toBase58(), w.verifier);
  assert.equal(j.amount, BigInt(w.amount));
  assert.equal(j.deadline, BigInt(w.deadline));
  assert.equal(j.review, BigInt(w.review));
  assert.equal(j.stake, BigInt(w.stake));
  assert.equal(hex(j.brief), w.brief);
  assert.equal(hex(j.result), w.result);
  assert.equal(hex(j.proof), w.proof);
  assert.throws(() => decodeJob(new Uint8Array(100)));
  const legacy = decodeJob(Buffer.from(fx.job.hex, "hex").subarray(0, 153));
  assert.equal(legacy.verifier, null);
  assert.equal(legacy.stake, 0n);
});
