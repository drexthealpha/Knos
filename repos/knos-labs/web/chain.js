// The Knos escrow on Solana devnet, read and written from the browser with no Knos server: job accounts come from
// getProgramAccounts, transactions are built here (the same layouts as src/knos/jobs/sol.py) and signed by the wallet.
// The API (relay + Actions) is optional: its current URL is a devnet memo `knos-api:<url>` signed by POINTER.
export const RPC = "https://api.devnet.solana.com";
export const PROGRAM = "GwmbMFvyHHwHug5em9dv26oXz2zTgXKGsNdrBxPayRPq";
export const POINTER = "q6F1zDrYM1skVMyfFLsvgbxALDouZQURheFhr5dT4xY";
export const FEED_BUYER = "3AwCofxMiRBChGA4BWdEqGKxgREErrrRYf3fqjhP7HzM";   // Knos's own task feed buys from this key
const TOKEN = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA";
const ATA = "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL";
const SYSTEM = "11111111111111111111111111111111";
const MEMO = "MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr";
export const STATES = ["none", "open", "claimed", "delivered", "released", "refunded"];
const B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz";

export function b58(bytes) {
  let n = 0n;
  for (const b of bytes) n = n * 256n + BigInt(b);
  let out = "";
  while (n > 0n) { out = B58[Number(n % 58n)] + out; n /= 58n; }
  for (const b of bytes) { if (b !== 0) break; out = "1" + out; }
  return out;
}
export function unb58(s) {
  let n = 0n;
  for (const c of s) n = n * 58n + BigInt(B58.indexOf(c));
  const out = [];
  while (n > 0n) { out.unshift(Number(n % 256n)); n /= 256n; }
  for (const c of s) { if (c !== "1") break; out.unshift(0); }
  return Uint8Array.from(out);
}
const hex = (u8) => [...u8].map((b) => b.toString(16).padStart(2, "0")).join("");

export async function rpc(method, params) {
  const r = await fetch(RPC, { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ jsonrpc: "2.0", id: 1, method, params }) });
  const j = await r.json();
  if (j.error) throw new Error(j.error.message || "RPC error");
  return j.result;
}

const u64 = (dv, o) => Number(dv.getBigUint64(o, true));
const i64 = (dv, o) => Number(dv.getBigInt64(o, true));

// Job account (src/knos/jobs/sol.py): state buyer worker amount deadline review brief result verifier proof stake
// (225 bytes, 0.3.5); 0.3.4 jobs are 217 bytes (no stake); jobs posted before 0.3.4 are 153 (no verifier, no proof).
// Since 0.3.5 every settlement closes the job account, so settled jobs are no longer listed.
export const JOB_LEN = 225, V034_JOB_LEN = 217, LEGACY_JOB_LEN = 153;
const zero = (u8) => u8.every((b) => b === 0);
export function parseJob(address, raw) {
  const dv = new DataView(raw.buffer, raw.byteOffset, raw.byteLength);
  const worker = raw.slice(33, 65), result = raw.slice(121, 153);
  const full = raw.length >= V034_JOB_LEN, verifier = full ? raw.slice(153, 185) : null, proof = full ? raw.slice(185, 217) : null;
  return { address, state: STATES[raw[0]] || "none", buyer: b58(raw.slice(1, 33)),
    worker: zero(worker) ? null : b58(worker), amount: u64(dv, 65) / 1e6, deadline: i64(dv, 73),
    review: i64(dv, 81), brief: hex(raw.slice(89, 121)), result: zero(result) ? null : hex(result),
    verifier: verifier && !zero(verifier) ? b58(verifier) : null, proof: proof && !zero(proof) ? hex(proof) : null,
    stake: raw.length >= JOB_LEN ? u64(dv, 217) / 1e6 : 0 };
}

export async function jobs() {
  const sized = (n) => rpc("getProgramAccounts", [PROGRAM, { encoding: "base64", filters: [{ dataSize: n }] }]);
  const got = (await Promise.all([sized(JOB_LEN), sized(V034_JOB_LEN), sized(LEGACY_JOB_LEN)])).flat();
  return got.map((a) => parseJob(a.pubkey, Uint8Array.from(atob(a.account.data[0]), (c) => c.charCodeAt(0))));
}

// The network and every agent's record, from job accounts only (the same rules as src/knos/jobs/stats.py).
export function network(all) {
  const part = (js) => ({ jobs: js.length, paid: js.filter((j) => j.state === "released").length,
    paidUsdc: js.filter((j) => j.state === "released").reduce((s, j) => s + j.amount * 0.95, 0),
    escrowUsdc: js.filter((j) => ["open", "claimed", "delivered"].includes(j.state)).reduce((s, j) => s + j.amount, 0) });
  const feed = all.filter((j) => j.buyer === FEED_BUYER), outside = all.filter((j) => j.buyer !== FEED_BUYER);
  return { all: part(all), feed: part(feed), outside: part(outside),
    agents: new Set(all.filter((j) => j.worker).map((j) => j.worker)).size,
    buyers: new Set(all.map((j) => j.buyer)).size, outsideBuyers: new Set(outside.map((j) => j.buyer)).size };
}
export function agents(all, now = Date.now() / 1000) {
  const rows = new Map();
  for (const j of all) {
    if (!j.worker) continue;
    const r = rows.get(j.worker) || { agent: j.worker, paid: 0, rejected: 0, expired: 0, active: 0, earned: 0 };
    if (j.state === "released") { r.paid++; r.earned += j.amount * 0.95; }
    else if (j.state === "refunded") j.result ? r.rejected++ : r.expired++;
    else if (j.state === "claimed" && j.deadline < now) r.expired++;
    else r.active++;
    rows.set(j.worker, r);
  }
  return [...rows.values()].map((r) => ({ ...r, acceptance: r.paid + r.rejected + r.expired
    ? r.paid / (r.paid + r.rejected + r.expired) : null })).sort((a, b) => b.paid - a.paid);
}

// The API pointer: the newest `knos-api:<url>` memo signed by POINTER.
export async function apiUrl() {
  const sigs = await rpc("getSignaturesForAddress", [POINTER, { limit: 10 }]);
  for (const s of sigs) {
    if (s.err) continue;
    const tx = await rpc("getTransaction", [s.signature, { encoding: "json", maxSupportedTransactionVersion: 0 }]);
    const m = tx && tx.transaction.message;
    if (!m || m.accountKeys[0] !== POINTER || !tx.transaction.signatures.length) continue;   // signed by the pointer
    for (const ix of m.instructions) {
      if (m.accountKeys[ix.programIdIndex] !== MEMO) continue;
      const text = new TextDecoder().decode(unb58(ix.data));
      if (text.startsWith("knos-api:https://")) return text.slice(9);
    }
  }
  return null;
}

// ---- transactions, built here ------------------------------------------------------------------------------------
let web3P;
const web3 = () => (web3P ||= import("https://cdn.jsdelivr.net/npm/@solana/web3.js@1.98.0/+esm"));

// Config PDA ["config2"]: admin mint fee_token fee_bps(u16) min_fee(u64) min_amount(u64) max_amount(u64) paused(u8) bump
export async function config() {
  const { PublicKey } = await web3();
  const [cfg] = PublicKey.findProgramAddressSync([new TextEncoder().encode("config2")], new PublicKey(PROGRAM));
  const got = await rpc("getAccountInfo", [cfg.toBase58(), { encoding: "base64" }]);
  const raw = Uint8Array.from(atob(got.value.data[0]), (c) => c.charCodeAt(0));
  const dv = new DataView(raw.buffer, raw.byteOffset, raw.byteLength);
  return { address: cfg, mint: new PublicKey(raw.slice(32, 64)), feeToken: new PublicKey(raw.slice(64, 96)),
    feeBps: dv.getUint16(96, true), minFee: u64(dv, 98), minAmount: u64(dv, 106), maxAmount: u64(dv, 114),
    paused: raw[122] !== 0 };
}

async function pdas(jobId) {
  const { PublicKey } = await web3();
  const pid = new PublicKey(PROGRAM), enc = new TextEncoder();
  return { pid, job: PublicKey.findProgramAddressSync([enc.encode("job"), jobId], pid)[0],
    vaultAuth: PublicKey.findProgramAddressSync([enc.encode("vault")], pid)[0] };
}
async function ata(owner, mint) {
  const { PublicKey } = await web3();
  return PublicKey.findProgramAddressSync([owner.toBytes(), new PublicKey(TOKEN).toBytes(), mint.toBytes()],
    new PublicKey(ATA))[0];
}

async function serialize(ixs, payer) {
  const { Transaction } = await web3();
  const { blockhash } = await rpc("getLatestBlockhash", [{ commitment: "confirmed" }]).then((r) => r.value);
  const tx = new Transaction({ feePayer: payer, recentBlockhash: blockhash });
  tx.add(...ixs);
  return tx.serialize({ requireAllSignatures: false, verifySignatures: false });
}

/** The post transaction (src/knos/jobs/sol.py `post`): the price into the program's vault, the brief's hash on chain,
 * and optionally a verifier (base58) who may release the delivered work on proof. */
export async function postTx(buyerB58, jobId, units, briefHash, workS = 3600, reviewS = 86400, verifierB58 = null) {
  const { PublicKey, TransactionInstruction } = await web3();
  const buyer = new PublicKey(buyerB58), cfg = await config(), p = await pdas(jobId);
  if (cfg.paused) throw new Error("The escrow is paused for new jobs right now; existing jobs still settle.");
  if (units < cfg.minAmount) throw new Error(`The minimum job is ${cfg.minAmount / 1e6} USDC.`);
  if (cfg.maxAmount && units > cfg.maxAmount) throw new Error(`Jobs are capped at ${cfg.maxAmount / 1e6} USDC for now.`);
  const data = new Uint8Array(1 + 32 + 24 + 32 + 32), dv = new DataView(data.buffer);
  data[0] = 1; data.set(jobId, 1);
  dv.setBigUint64(33, BigInt(units), true); dv.setBigInt64(41, BigInt(workS), true); dv.setBigInt64(49, BigInt(reviewS), true);
  data.set(briefHash, 57);
  if (verifierB58) data.set(new PublicKey(verifierB58).toBytes(), 89);
  const keys = [[buyer, true, true], [p.job, false, true], [await ata(buyer, cfg.mint), false, true],
    [await ata(p.vaultAuth, cfg.mint), false, true], [cfg.address, false, false], [new PublicKey(TOKEN), false, false],
    [new PublicKey(SYSTEM), false, false]].map(([pubkey, isSigner, isWritable]) => ({ pubkey, isSigner, isWritable }));
  return serialize([new TransactionInstruction({ programId: p.pid, keys, data })], buyer);
}

/** sha256 over a repo's acceptance bundle .knos/acceptance/<issue>/ at `ref`, read from the public GitHub API: sorted
 * relative paths, each "path\0sha256(content)\n" (src/knos/jobs/prove.py `checks_hash`). Returns 32 bytes. */
export async function checksHash(repo, ref, issue) {
  const dir = `.knos/acceptance/${issue}/`;
  const tree = await fetch(`https://api.github.com/repos/${repo}/git/trees/${encodeURIComponent(ref)}?recursive=1`)
    .then((r) => { if (!r.ok) throw new Error(`GitHub: ${repo}@${ref} not readable (${r.status})`); return r.json(); });
  const files = tree.tree.filter((t) => t.type === "blob" && t.path.startsWith(dir)).map((t) => t.path).sort();
  if (!files.length) throw new Error(`${repo} has no ${dir} on ${ref}: write the acceptance tests first.`);
  const hexOf = (u8) => [...u8].map((b) => b.toString(16).padStart(2, "0")).join("");
  const dig = async (u8) => new Uint8Array(await crypto.subtle.digest("SHA-256", u8));
  let lines = "";
  const rel = files.map((f) => f.slice(dir.length)).sort();
  for (const f of rel) {
    const body = await fetch(`https://raw.githubusercontent.com/${repo}/${encodeURIComponent(ref)}/${dir}${f}`)
      .then((r) => { if (!r.ok) throw new Error(`GitHub: cannot read ${dir}${f}`); return r.arrayBuffer(); });
    lines += `${f}\0${hexOf(await dig(new Uint8Array(body)))}\n`;
  }
  return dig(new TextEncoder().encode(lines));
}

/** PostGithub (19, src/knos/jobs/sol.py `post_github`): the price into the vault in the config mint, paid when a
 * GitHub Actions token from Knos's prove.yml for `repo` at `ref` (e.g. refs/heads/main) proves the checks passed. */
export async function postGithubTx(buyerB58, jobId, units, briefHash, repo, ref, checks, stake = false,
                                   workS = 7 * 86400, reviewS = 86400) {
  const { PublicKey, TransactionInstruction } = await web3();
  const buyer = new PublicKey(buyerB58), cfg = await config(), p = await pdas(jobId);
  if (cfg.paused) throw new Error("The escrow is paused for new jobs right now; existing jobs still settle.");
  if (units && units < cfg.minAmount) throw new Error(`The minimum job is ${cfg.minAmount / 1e6} USDC.`);
  if (cfg.maxAmount && units > cfg.maxAmount) throw new Error(`Jobs are capped at ${cfg.maxAmount / 1e6} USDC for now.`);
  const dig = async (s) => new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(s)));
  const data = new Uint8Array(1 + 32 + 24 + 32 * 4 + 1), dv = new DataView(data.buffer);   // 186 bytes
  data[0] = 19; data.set(jobId, 1);
  dv.setBigUint64(33, BigInt(units), true); dv.setBigInt64(41, BigInt(workS), true); dv.setBigInt64(49, BigInt(reviewS), true);
  data.set(briefHash, 57); data.set(await dig(repo), 89); data.set(await dig(ref), 121); data.set(checks, 153);
  data[185] = stake ? 1 : 0;
  const keys = [[buyer, true, true], [p.job, false, true], [await ata(buyer, cfg.mint), false, true],
    [await ata(p.vaultAuth, cfg.mint), false, true], [cfg.address, false, false], [new PublicKey(TOKEN), false, false],
    [new PublicKey(SYSTEM), false, false]].map(([pubkey, isSigner, isWritable]) => ({ pubkey, isSigner, isWritable }));
  return serialize([new TransactionInstruction({ programId: p.pid, keys, data })], buyer);
}

/** Accept (pays the worker 95%, the fee 5%) or reject (refund) a delivered job, signed by its buyer. */
export async function settleTx(buyerB58, job, jobId, verb) {
  const { PublicKey, TransactionInstruction } = await web3();
  const buyer = new PublicKey(buyerB58), cfg = await config(), p = await pdas(jobId);
  const vault = await ata(p.vaultAuth, cfg.mint), m = (pubkey, s, w) => ({ pubkey, isSigner: s, isWritable: w });
  if (verb === "accept") {
    const worker = new PublicKey(job.worker), wtok = await ata(worker, cfg.mint);
    const create = new TransactionInstruction({ programId: new PublicKey(ATA), data: Uint8Array.from([1]), keys: [
      m(buyer, true, true), m(wtok, false, true), m(worker, false, false), m(cfg.mint, false, false),
      m(new PublicKey(SYSTEM), false, false), m(new PublicKey(TOKEN), false, false)] });
    const ix = new TransactionInstruction({ programId: p.pid, data: Uint8Array.from([4]), keys: [
      m(buyer, true, true), m(p.job, false, true), m(vault, false, true), m(p.vaultAuth, false, false),
      m(wtok, false, true), m(cfg.feeToken, false, true), m(cfg.address, false, false), m(new PublicKey(TOKEN), false, false),
      m(buyer, true, true)] });   // 0.3.5: the job closes; its rent goes back to the buyer
    return serialize([create, ix], buyer);
  }
  // Reject: refused by the escrow on a job that names a verifier (only the verifier or the deadline settles it).
  const ix = new TransactionInstruction({ programId: p.pid, data: Uint8Array.from([6]), keys: [
    m(buyer, true, true), m(p.job, false, true), m(vault, false, true), m(p.vaultAuth, false, false),
    m(await ata(buyer, cfg.mint), false, true), m(new PublicKey(TOKEN), false, false)] });
  return serialize([ix], buyer);
}

export async function jobAddress(jobId) {
  return (await pdas(jobId)).job.toBase58();
}
