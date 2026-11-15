// The passkey wallet (0.3.7): no extension, no seed phrase, no SOL from the user.
// A WebAuthn passkey guards a locally generated ed25519 gas key. The key is stored AES-GCM-encrypted in IndexedDB
// under a key derived from the passkey's PRF output when the authenticator supports PRF; otherwise the wrapping key is
// derived from the credential id (bound to the passkey, not secret: a devnet-only throwaway key). Gas (0.01 devnet SOL)
// comes from the Knos API's POST /gas; test USDC from the escrow's devnet faucet (tag 20), signed by the gas key; a
// bounty is a PostBounty (tag 23) in the faucet's mint, amount >= 0.
// (LazorKit's devnet paymaster sponsors LazorKit's own program; a CPI into the Knos escrow is not documented as
// accepted, so this fallback is used.)
import { rpc, PROGRAM } from "./chain.js";

const web3 = () => import("https://cdn.jsdelivr.net/npm/@solana/web3.js@1.98.0/+esm");
const TOKEN = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA";
const ATA = "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL";
const SYSTEM = "11111111111111111111111111111111";
const enc = new TextEncoder();
const SALT = enc.encode("knos-gas-key-v1");
const b64 = { dec: (s) => Uint8Array.from(atob(s), (c) => c.charCodeAt(0)), enc: (u8) => btoa(String.fromCharCode(...u8)) };

// ---- IndexedDB ---------------------------------------------------------------------------------------------------
function db() {
  return new Promise((ok, no) => {
    const r = indexedDB.open("knos-wallet", 1);
    r.onupgradeneeded = () => r.result.createObjectStore("w");
    r.onsuccess = () => ok(r.result); r.onerror = () => no(r.error);
  });
}
async function idb(mode, fn) {
  const d = await db();
  return new Promise((ok, no) => {
    const t = d.transaction("w", mode), q = fn(t.objectStore("w"));
    t.oncomplete = () => ok(q?.result); t.onerror = () => no(t.error);
  });
}
const load = () => idb("readonly", (s) => s.get("wallet"));
const save = (v) => idb("readwrite", (s) => s.put(v, "wallet"));

async function wrapKey(material) {
  const base = await crypto.subtle.importKey("raw", material, "HKDF", false, ["deriveKey"]);
  return crypto.subtle.deriveKey({ name: "HKDF", hash: "SHA-256", salt: SALT, info: enc.encode("knos") }, base,
    { name: "AES-GCM", length: 256 }, false, ["encrypt", "decrypt"]);
}
const prfOut = (cred) => cred.getClientExtensionResults?.()?.prf?.results?.first;

let unlocked = null;   // { kp, pubkey }

export async function exists() { return !!(await load()); }

/** First visit: create the passkey, generate the gas key, store it encrypted. */
export async function create() {
  const { Keypair } = await web3();
  const cred = await navigator.credentials.create({ publicKey: {
    challenge: crypto.getRandomValues(new Uint8Array(32)), rp: { name: "Knos" },
    user: { id: crypto.getRandomValues(new Uint8Array(16)), name: "knos-wallet", displayName: "Knos wallet" },
    pubKeyCredParams: [{ type: "public-key", alg: -7 }, { type: "public-key", alg: -257 }],
    authenticatorSelection: { residentKey: "preferred", userVerification: "preferred" },
    extensions: { prf: { eval: { first: SALT } } } } });
  const id = new Uint8Array(cred.rawId);
  let prf = prfOut(cred), usesPrf = !!prf;
  const kp = Keypair.generate(), iv = crypto.getRandomValues(new Uint8Array(12));
  const key = await wrapKey(prf ? new Uint8Array(prf) : id);
  const ct = new Uint8Array(await crypto.subtle.encrypt({ name: "AES-GCM", iv }, key, kp.secretKey));
  await save({ id: b64.enc(id), iv: b64.enc(iv), ct: b64.enc(ct), prf: usesPrf, pubkey: kp.publicKey.toBase58() });
  unlocked = { kp, pubkey: kp.publicKey.toBase58() };
  return unlocked.pubkey;
}

/** Later visits: the passkey (PRF when available) unwraps the gas key. */
export async function unlock() {
  if (unlocked) return unlocked.pubkey;
  const w = await load();
  if (!w) throw new Error("no wallet on this device yet");
  const { Keypair } = await web3();
  const id = b64.dec(w.id);
  const got = await navigator.credentials.get({ publicKey: { challenge: crypto.getRandomValues(new Uint8Array(32)),
    allowCredentials: [{ type: "public-key", id }], userVerification: "preferred",
    extensions: w.prf ? { prf: { eval: { first: SALT } } } : {} } });
  const prf = prfOut(got);
  const key = await wrapKey(w.prf ? new Uint8Array(prf) : id);
  const sk = new Uint8Array(await crypto.subtle.decrypt({ name: "AES-GCM", iv: b64.dec(w.iv) }, key, b64.dec(w.ct)));
  unlocked = { kp: Keypair.fromSecretKey(sk), pubkey: w.pubkey };
  return unlocked.pubkey;
}

// ---- chain -------------------------------------------------------------------------------------------------------
async function send(ixs) {
  const { Transaction } = await web3();
  const { blockhash } = (await rpc("getLatestBlockhash", [{ commitment: "confirmed" }])).value;
  const tx = new Transaction({ feePayer: unlocked.kp.publicKey, recentBlockhash: blockhash });
  tx.add(...ixs); tx.sign(unlocked.kp);
  const sig = await rpc("sendTransaction", [b64.enc(tx.serialize()), { encoding: "base64", preflightCommitment: "confirmed" }]);
  for (let i = 0; i < 60; i++) {
    const st = (await rpc("getSignatureStatuses", [[sig]])).value[0];
    if (st?.err) throw new Error(`transaction failed: ${JSON.stringify(st.err)}`);
    if (st && ["confirmed", "finalized"].includes(st.confirmationStatus)) return sig;
    await new Promise((r) => setTimeout(r, 500));
  }
  throw new Error("not confirmed in 30 s");
}
const meta = (pubkey, isSigner, isWritable) => ({ pubkey, isSigner, isWritable });
async function account(addr) {
  const got = await rpc("getAccountInfo", [addr.toBase58(), { encoding: "base64", commitment: "confirmed" }]);
  return got.value ? b64.dec(got.value.data[0]) : null;
}
export async function lamports(pk) { return (await rpc("getBalance", [pk || unlocked.pubkey, { commitment: "confirmed" }])).value; }

/** The faucet's mint (from the ["faucet"] PDA) and its registered vault (from ["mint", mint]). */
export async function faucetInfo() {
  const { PublicKey } = await web3();
  const pid = new PublicKey(PROGRAM);
  const faucet = PublicKey.findProgramAddressSync([enc.encode("faucet")], pid)[0];
  const f = await account(faucet);
  if (!f) throw new Error("the devnet faucet is not set up yet (InitFaucetMint)");
  const mint = new PublicKey(f.slice(0, 32)), cap = Number(new DataView(f.buffer, f.byteOffset).getBigUint64(32, true));
  const registry = PublicKey.findProgramAddressSync([enc.encode("mint"), mint.toBytes()], pid)[0];
  const r = await account(registry);
  return { pid, faucet, mint, cap, registry, vault: r ? new PublicKey(r.slice(32, 64)) : null };
}
async function ataOf(owner, mint) {
  const { PublicKey } = await web3();
  return PublicKey.findProgramAddressSync([owner.toBytes(), new PublicKey(TOKEN).toBytes(), mint.toBytes()], new PublicKey(ATA))[0];
}

/** 0.01 devnet SOL for the gas key, from the Knos API. */
export async function gas(apiBase) {
  if ((await lamports()) >= 5_000_000) return "already has gas";
  const r = await fetch(`${apiBase}/gas`, { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ pubkey: unlocked.pubkey }) });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.message || `gas: HTTP ${r.status}`);
  for (let i = 0; i < 40 && (await lamports()) < 5_000_000; i++) await new Promise((ok) => setTimeout(ok, 500));
  return j.signature;
}

/** Test USDC from the faucet (tag 20) into the gas key's token account (created idempotently). */
export async function faucet(units) {
  const { PublicKey, TransactionInstruction } = await web3();
  const f = await faucetInfo(), me = unlocked.kp.publicKey, tok = await ataOf(me, f.mint);
  const drip = PublicKey.findProgramAddressSync([enc.encode("drip"), me.toBytes()], f.pid)[0];
  const createAta = new TransactionInstruction({ programId: new PublicKey(ATA), data: Uint8Array.from([1]), keys: [
    meta(me, true, true), meta(tok, false, true), meta(me, false, false), meta(f.mint, false, false),
    meta(new PublicKey(SYSTEM), false, false), meta(new PublicKey(TOKEN), false, false)] });
  const data = new Uint8Array(9); data[0] = 20;
  new DataView(data.buffer).setBigUint64(1, BigInt(Math.min(units ?? f.cap, f.cap)), true);
  const ix = new TransactionInstruction({ programId: f.pid, data, keys: [meta(me, true, true), meta(f.faucet, false, false),
    meta(f.mint, false, true), meta(tok, false, true), meta(drip, false, true), meta(new PublicKey(TOKEN), false, false),
    meta(new PublicKey(SYSTEM), false, false)] });
  return send([createAta, ix]);
}

export function briefJson(repo, issue) {   // canonical, as sol.bounty_brief_json (sorted keys, no spaces)
  return JSON.stringify({ issue: Number(issue), kind: "github-bounty", repo });
}

/** Fund repo#issue: PostBounty (tag 23) in the faucet's registered mint. Returns { sig, jobId }. */
export async function fundIssue(repo, issue, units, workS = 7 * 86400, reviewS = 86400) {
  if (!/^[\w.-]+\/[\w.-]+$/.test(repo) || !(Number(issue) > 0)) throw new Error("repo as owner/name and an issue number");
  if (!(units >= 0)) throw new Error("amount >= 0");
  const { PublicKey, TransactionInstruction } = await web3();
  const f = await faucetInfo();
  if (!f.vault) throw new Error("the faucet's mint is not registered yet (AddMint)");
  const me = unlocked.kp.publicKey;
  const brief = new Uint8Array(await crypto.subtle.digest("SHA-256", enc.encode(briefJson(repo, issue))));
  const jobId = crypto.getRandomValues(new Uint8Array(32));
  const job = PublicKey.findProgramAddressSync([enc.encode("job"), jobId], f.pid)[0];
  const cfg = PublicKey.findProgramAddressSync([enc.encode("config2")], f.pid)[0];
  const data = new Uint8Array(1 + 32 + 24 + 32 + 32), dv = new DataView(data.buffer);
  data[0] = 23; data.set(jobId, 1);
  dv.setBigUint64(33, BigInt(units), true); dv.setBigInt64(41, BigInt(workS), true); dv.setBigInt64(49, BigInt(reviewS), true);
  data.set(brief, 57);
  const ix = new TransactionInstruction({ programId: f.pid, data, keys: [meta(me, true, true), meta(job, false, true),
    meta(await ataOf(me, f.mint), false, true), meta(f.vault, false, true), meta(cfg, false, false),
    meta(new PublicKey(TOKEN), false, false), meta(new PublicKey(SYSTEM), false, false), meta(f.registry, false, false)] });
  const sig = await send([ix]);
  return { sig, jobId: [...jobId].map((b) => b.toString(16).padStart(2, "0")).join(""), job: job.toBase58() };
}

export const pubkey = () => unlocked?.pubkey || null;
