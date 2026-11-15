// @knos/escrow: instruction builders and the job decoder for the Knos escrow program on Solana
// (programs/knos_escrow; IDL in programs/knos_escrow/idl.json). A native program: one-byte instruction tags,
// packed little-endian layouts, no account discriminators.
//
// No runtime dependencies. Pass @solana/web3.js's PublicKey (or anything with the same static
// findProgramAddressSync(seeds, programId) and instance toBytes()) to createEscrow. Builders return
// { programId, keys: [{ pubkey, isSigner, isWritable }], data } - the shape `new TransactionInstruction(...)` takes.
//
//   import { PublicKey, TransactionInstruction } from "@solana/web3.js";
//   import { createEscrow } from "@knos/escrow";
//   const escrow = createEscrow({ PublicKey });
//   const ix = new TransactionInstruction(escrow.claim({ worker, jobId, workerToken, vaultToken }));

export const DEVNET_PROGRAM_ID = "GwmbMFvyHHwHug5em9dv26oXz2zTgXKGsNdrBxPayRPq";
export const TOKEN_PROGRAM_ID = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA";
export const SYSTEM_PROGRAM_ID = "11111111111111111111111111111111";
export const JOB_LEN = 225;
export const V034_JOB_LEN = 217;
export const LEGACY_JOB_LEN = 153;
export const CONFIG_LEN = 124;
export const STATES = ["none", "open", "claimed", "delivered", "released", "refunded"];

// Tag and account metas [name, signer, writable] per instruction; test.mjs checks this table against idl.json.
const PAYOUT = (who, whoW) => [[who, true, whoW], ["job", false, true], ["vault_token", false, true],
  ["vault_authority", false, false], ["worker_token", false, true], ["fee_token", false, true],
  ["config", false, false], ["token_program", false, false], ["buyer", false, true]];
const REFUNDISH = [["buyer", true, true], ["job", false, true], ["vault_token", false, true],
  ["vault_authority", false, false], ["buyer_token", false, true], ["token_program", false, false]];
export const LAYOUT = {
  post: [1, [["buyer", true, true], ["job", false, true], ["buyer_token", false, true], ["vault_token", false, true],
    ["config", false, false], ["token_program", false, false], ["system_program", false, false]]],
  claim: [2, [["worker", true, false], ["job", false, true], ["worker_token", false, true],
    ["vault_token", false, true], ["config", false, false], ["token_program", false, false]]],
  deliver: [3, [["worker", true, false], ["job", false, true], ["worker_token", false, true],
    ["vault_token", false, true], ["vault_authority", false, false], ["token_program", false, false]]],
  accept: [4, PAYOUT("buyer_signer", true)],
  release: [5, PAYOUT("anyone", false)],
  reject: [6, REFUNDISH],
  refund: [7, REFUNDISH],
  verify_release: [11, PAYOUT("verifier", false)],
  verify_reject: [12, [["verifier", true, false], ["job", false, true], ["vault_token", false, true],
    ["vault_authority", false, false], ["buyer_token", false, true], ["token_program", false, false],
    ["buyer", false, true]]],
  settle: [13, [["anyone", true, false], ["job", false, true], ["vault_token", false, true],
    ["vault_authority", false, false], ["worker_token", false, true], ["fee_token", false, true],
    ["buyer_token", false, true], ["buyer", false, true], ["config", false, false], ["token_program", false, false]]],
};

const enc = new TextEncoder();
const bytesOf = (k) => (k instanceof Uint8Array ? k : k.toBytes());
const same = (a, b) => { const x = bytesOf(a), y = bytesOf(b); return x.length === y.length && x.every((v, i) => v === y[i]); };
const toData = (u8) => (globalThis.Buffer ? globalThis.Buffer.from(u8) : u8);

function b32(v, what) {
  const b = typeof v === "string" ? Uint8Array.from(v.match(/../g).map((h) => parseInt(h, 16))) : Uint8Array.from(v);
  if (b.length !== 32) throw new Error(`${what} is 32 bytes`);
  return b;
}
function u64le(v) { const b = new Uint8Array(8); new DataView(b.buffer).setBigUint64(0, BigInt(v), true); return b; }
function i64le(v) { const b = new Uint8Array(8); new DataView(b.buffer).setBigInt64(0, BigInt(v), true); return b; }
function concat(...parts) {
  const out = new Uint8Array(parts.reduce((n, p) => n + p.length, 0));
  let o = 0; for (const p of parts) { out.set(p, o); o += p.length; }
  return out;
}

export function createEscrow({ PublicKey, programId = DEVNET_PROGRAM_ID }) {
  const pid = typeof programId === "string" ? new PublicKey(programId) : programId;
  const token = new PublicKey(TOKEN_PROGRAM_ID);
  const system = new PublicKey(SYSTEM_PROGRAM_ID);
  const pda = (...seeds) => PublicKey.findProgramAddressSync(seeds, pid)[0];
  const config = pda(enc.encode("config2"));
  const vault = pda(enc.encode("vault"));
  const jobPda = (jobId) => pda(enc.encode("job"), b32(jobId, "job id"));

  function build(name, accounts, data) {
    const [tag, metas] = LAYOUT[name];
    const keys = metas.map(([n, isSigner, isWritable]) => {
      if (!accounts[n]) throw new Error(`${name}: missing account ${n}`);
      return { pubkey: accounts[n], isSigner, isWritable };
    });
    // The same key twice (the buyer signing and taking the rent): every occurrence carries the union of flags.
    for (const k of keys) for (const o of keys) if (same(k.pubkey, o.pubkey)) {
      k.isSigner ||= o.isSigner; k.isWritable ||= o.isWritable;
    }
    return { programId: pid, keys, data: toData(concat(Uint8Array.of(tag), data || new Uint8Array())) };
  }
  const common = { config, vault_authority: vault, token_program: token, system_program: system };
  const payout = (name, who, a, data) => build(name, { ...common, [who[0]]: who[1], job: jobPda(a.jobId),
    vault_token: a.vaultToken, worker_token: a.workerToken, fee_token: a.feeToken, buyer: a.buyer }, data);
  const refundish = (name, a) => build(name, { ...common, buyer: a.buyer, job: jobPda(a.jobId),
    vault_token: a.vaultToken, buyer_token: a.buyerToken });

  return {
    programId: pid,
    pdas: { config, vault, job: jobPda },
    /** Post a job; `verifier` optional (omitted = none: only the buyer or the deadline settles it). */
    post: (a) => build("post", { ...common, buyer: a.buyer, job: jobPda(a.jobId), buyer_token: a.buyerToken,
      vault_token: a.vaultToken }, concat(b32(a.jobId, "job id"), u64le(a.amount), i64le(a.work), i64le(a.review),
      b32(a.brief, "brief hash"), a.verifier ? bytesOf(a.verifier) : new Uint8Array(32))),
    claim: (a) => build("claim", { ...common, worker: a.worker, job: jobPda(a.jobId), worker_token: a.workerToken,
      vault_token: a.vaultToken }),
    deliver: (a) => build("deliver", { ...common, worker: a.worker, job: jobPda(a.jobId),
      worker_token: a.workerToken, vault_token: a.vaultToken }, b32(a.result, "result hash")),
    accept: (a) => payout("accept", ["buyer_signer", a.buyer], a),
    release: (a) => payout("release", ["anyone", a.anyone], a),
    verifyRelease: (a) => payout("verify_release", ["verifier", a.verifier], a,
      concat(b32(a.resultHash, "result hash"), b32(a.proofRoot, "proof root"))),
    reject: (a) => refundish("reject", a),
    refund: (a) => refundish("refund", a),
    verifyReject: (a) => build("verify_reject", { ...common, verifier: a.verifier, job: jobPda(a.jobId),
      vault_token: a.vaultToken, buyer_token: a.buyerToken, buyer: a.buyer }, b32(a.proofRoot, "proof root")),
    /** The deadline crank (tag 13), by anyone. For an unclaimed job pass any token account as workerToken. */
    settle: (a) => build("settle", { ...common, anyone: a.signer, job: jobPda(a.jobId), vault_token: a.vaultToken,
      worker_token: a.workerToken, fee_token: a.feeToken, buyer_token: a.buyerToken, buyer: a.buyer }),
  };
}

/** Decode a job account (225 bytes; 217-byte 0.3.4 and 153-byte older jobs too). Keys come back as PublicKey when
 *  one is passed, else as 32-byte Uint8Arrays; zero worker/verifier/result/proof come back null. */
export function decodeJob(buffer, PublicKey) {
  const d = Uint8Array.from(buffer);
  if (![JOB_LEN, V034_JOB_LEN, LEGACY_JOB_LEN].includes(d.length)) throw new Error("not a knos_escrow job account");
  const v = new DataView(d.buffer);
  const raw = (o) => d.slice(o, o + 32);
  const zero = (b) => b.every((x) => x === 0);
  const key = (o) => (zero(raw(o)) ? null : PublicKey ? new PublicKey(raw(o)) : raw(o));
  const full = d.length >= V034_JOB_LEN;
  return {
    state: STATES[d[0]] || "unknown",
    buyer: PublicKey ? new PublicKey(raw(1)) : raw(1),
    worker: key(33),
    amount: v.getBigUint64(65, true),
    deadline: v.getBigInt64(73, true),
    review: v.getBigInt64(81, true),
    brief: raw(89),
    result: zero(raw(121)) ? null : raw(121),
    verifier: full ? key(153) : null,
    proof: full && !zero(raw(185)) ? raw(185) : null,
    stake: d.length === JOB_LEN ? v.getBigUint64(217, true) : 0n,
  };
}
