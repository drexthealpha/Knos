// Knos settle, in JavaScript: addresses, audiences, instructions and account layouts of knos-oidc and knos-pay, the
// unsigned transaction a wallet signs, and the call that asks an injected wallet to sign and send it.
// No dependency: it runs as is in a browser (the Knos web app loads this file) and in Node 20+.
// The Python client (src/knos/settle) is the authority; sdk/settle/test.mjs checks this file against the
// byte-exact fixtures it wrote (sdk/settle/fixtures.json).
//
// The second deployment (programs-v2; upgradeable only through a multisig with a public 48-hour delay, until an
// outside review; then made immutable) is under `v2`:
//
//   import * as knos from "./index.js";
//   const k = knos.v2.client(ids);                                      // ids: src/knos/settle/v2/program_ids.json
//   const balance = await k.balance(ownerId, wallet, mint);             // a wallet's Balance for one GitHub owner
//   const state = knos.v2.readBalance(await knos.account(RPC, balance));
//   const ix = await k.openBalanceIx({ authority: wallet, ownerId, mint, cap, spenders });
//   const tx = knos.serializeTx([ix], wallet, recentBlockhash);         // unsigned legacy transaction
//   const [w] = knos.wallets();                                         // Wallet Standard, then Phantom, then Solflare
//   await w.connect(); const signature = await w.signAndSend(tx, "solana:devnet");
//
// A work order (knos-pay 2.1) is funded from a wallet in one instruction, `k.fundOrderWalletIx`; the Python names
// in camelCase are here (fund_order_wallet_ix -> fundOrderWalletIx), the PDAs as `k.orderPda`, the pure functions and
// readers under `v2` (v2.readOrder, v2.orderFee), the meter under `meter`, and the 4,096-byte v1 transaction beside
// the legacy one (serializeTxV1). The embeddable reads for an agent platform are in agent.js.
//
// The first deployment (programs/, immutable; jobs funded there finish there) keeps the names it had:
//
//   const k1 = knos.client({ knos_oidc: "...", knos_pay: "..." });      // src/knos/settle/program_ids.json
//   const job = knos.parseJob(await knos.account(RPC, await k1.job(repoId, issue)));

export const TOKEN = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA";
export const TOKEN_2022 = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb";
export const ATA_PROGRAM = "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL";
export const SYSTEM = "11111111111111111111111111111111";
export const LOADER = "BPFLoaderUpgradeab1e11111111111111111111111";
export const SQUADS = "SQDS4ep65T869zMMBKyuUq6aD6EgTu8psMjkvj52pCf";      // Squads v4, the multisig program
export const FEE_OWNER = "4G3cznCnwCUPBCZwzKiLupjdgB5pSoCcGWNGuFv4TYFo";   // receives fees, nothing else
export const USDC_DEVNET = "4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU";  // Circle's devnet USDC
export const USDC_MAINNET = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v";  // Circle's USDC on mainnet
export const MERGE = 0, TESTS = 1;
export const FEE_BPS = 250, FEE_MIN = 50_000, MIN_AMOUNT = 1_000_000, MAX_AMOUNT = 500_000_000;      // the first deployment's
export const JOB_LEN = 256, DUE_LEN = 48, REP_LEN = 32;                    // the first deployment's accounts

// ---- bytes ---------------------------------------------------------------------------------------------------------
const B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz";
const enc = new TextEncoder();

export function b58(bytes) {
  let n = 0n;
  for (const b of bytes) n = n * 256n + BigInt(b);
  let out = "";
  while (n > 0n) { out = B58[Number(n % 58n)] + out; n /= 58n; }
  for (const b of bytes) { if (b !== 0) break; out = "1" + out; }
  return out;
}

export function unb58(s, size = 32) {
  let n = 0n;
  for (const c of s) {
    const i = B58.indexOf(c);
    if (i < 0) throw new Error(`not base58: ${s}`);
    n = n * 58n + BigInt(i);
  }
  const out = new Uint8Array(size);
  for (let i = size - 1; i >= 0; i--) { out[i] = Number(n & 255n); n >>= 8n; }
  if (n > 0n) throw new Error(`longer than ${size} bytes: ${s}`);
  return out;
}

/** A Solana address: base58 that decodes to exactly 32 bytes, written the one way those bytes are written. */
export function isAddress(s) {
  if (typeof s !== "string" || s.length < 32 || s.length > 44 || [...s].some((c) => !B58.includes(c))) return false;
  try { const raw = unb58(s); return raw.some((b) => b !== 0) && b58(raw) === s; } catch { return false; }
}

export const hex = (u8) => [...u8].map((b) => b.toString(16).padStart(2, "0")).join("");
export const unhex = (s) => Uint8Array.from(s.match(/../g) || [], (h) => parseInt(h, 16));
const key = (k) => (typeof k === "string" ? unb58(k) : k);
const u64 = (v) => { const b = new Uint8Array(8); new DataView(b.buffer).setBigUint64(0, BigInt(v), true); return b; };
const i64 = (v) => { const b = new Uint8Array(8); new DataView(b.buffer).setBigInt64(0, BigInt(v), true); return b; };
const u32 = (v) => { const b = new Uint8Array(4); new DataView(b.buffer).setUint32(0, Number(v), true); return b; };
const u16 = (v) => Uint8Array.of(v & 255, (v >> 8) & 255);
const cat = (...parts) => {
  const out = new Uint8Array(parts.reduce((n, p) => n + p.length, 0));
  let o = 0;
  for (const p of parts) { out.set(p, o); o += p.length; }
  return out;
};
const view = (raw) => new DataView(raw.buffer, raw.byteOffset, raw.byteLength);
// A 64-bit field as a number; as a BigInt when it is too large to be one exactly (ids and amounts never are).
const num = (big) => (big >= -9007199254740991n && big <= 9007199254740991n ? Number(big) : big);
const ascii = (raw) => [...raw].map((b) => (b < 128 ? String.fromCharCode(b) : String.fromCharCode(0xfffd))).join("");

export async function sha256(bytes) {
  return new Uint8Array(await globalThis.crypto.subtle.digest("SHA-256", bytes));
}

// ---- program addresses ---------------------------------------------------------------------------------------------
// A program address is a sha256 that is NOT a point on ed25519. The curve check: y is the low 255 bits; the point
// exists iff (y^2 - 1) / (d y^2 + 1) is a square mod p.
const P = 2n ** 255n - 19n;
const D = 37095705934669439343138083508754565189542113879843219016388785533085940283555n;
const mod = (a) => ((a % P) + P) % P;
function pow(b, e) {
  let r = 1n;
  b = mod(b);
  while (e > 0n) { if (e & 1n) r = mod(r * b); b = mod(b * b); e >>= 1n; }
  return r;
}
export function onCurve(bytes) {
  let y = 0n;
  for (let i = 31; i >= 0; i--) y = (y << 8n) | BigInt(bytes[i]);
  y &= (1n << 255n) - 1n;
  if (y >= P) return false;
  const u = mod(y * y - 1n), v = mod(D * y * y + 1n);
  const x2 = mod(u * pow(v, P - 2n));
  return x2 === 0n || pow(x2, (P - 1n) / 2n) === 1n;
}

export async function findProgramAddress(seeds, program) {
  const tail = cat(key(program), enc.encode("ProgramDerivedAddress"));
  for (let bump = 255; bump >= 0; bump--) {
    const h = await sha256(cat(...seeds, Uint8Array.of(bump), tail));
    if (!onCurve(h)) return [b58(h), bump];
  }
  throw new Error("no program address");
}

/** The owner's associated token account of a mint (`tokenProgram`: TOKEN, or TOKEN_2022 for a Token-2022 mint). */
export const ata = async (owner, mint, tokenProgram = TOKEN) =>
  (await findProgramAddress([key(owner), key(tokenProgram), key(mint)], ATA_PROGRAM))[0];
export const programData = async (program) => (await findProgramAddress([key(program)], LOADER))[0];

// ---- the first deployment: audiences, fees, account layouts ---------------------------------------------------------
const ZERO = "0".repeat(64);
export const fundAudience = (issue, amount, mode = MERGE, checksHex = ZERO, workS = 14 * 86400, reviewS = 0) =>
  `knos:fund:${issue}:${amount}:${mode}:${checksHex}:${workS}:${reviewS}`;
export const payAudience = (repoId, issue, authorId, headSha, checksHex = ZERO, mode = MERGE) =>
  `knos:pay:${repoId}:${issue}:${authorId}:${headSha}:${checksHex}:${mode}`;
export const vetoAudience = (repoId, issue) => `knos:veto:${repoId}:${issue}`;
export const claimAudience = (address) => `knos:claim:${address}`;

/** The fee on a payment: 2.5%, at least 0.05, never more than the amount. The same in both deployments. */
export function feeOf(amount) {
  const a = BigInt(amount);
  const pct = (a * BigInt(FEE_BPS)) / 10000n;
  const fee = pct > BigInt(FEE_MIN) ? pct : BigInt(FEE_MIN);
  return Number(fee < a ? fee : a);
}

/** sha256 of "owner/name": the repository whose prove.yml and fund.yml a job pins. */
export const wfRepoHash = (repository) => sha256(enc.encode(repository));

const STATES = { 1: "open", 2: "proven" };

export function parseJob(raw) {
  if (!raw || raw.length !== JOB_LEN) return null;
  const dv = view(raw);
  const u = (o) => Number(dv.getBigUint64(o, true)), i = (o) => Number(dv.getBigInt64(o, true));
  return { state: STATES[raw[0]] || "?", mode: raw[1], tokenFunded: raw[2] === 1, repoId: u(8), issue: u(16), amount: u(24),
    deadline: i(32), review: i(40), payAfter: i(48), authorId: u(56), funderId: u(64), notBefore: i(72),
    vetoes: dv.getUint32(80, true), funder: b58(raw.slice(88, 120)), mint: b58(raw.slice(120, 152)),
    checks: hex(raw.slice(152, 184)), wfRepoHash: hex(raw.slice(184, 216)), wfSha: new TextDecoder().decode(raw.slice(216, 256)) };
}

export function parseDue(raw) {
  if (!raw || raw.length !== DUE_LEN) return null;
  const dv = view(raw);
  return { amount: Number(dv.getBigUint64(0, true)), userId: Number(dv.getBigUint64(8, true)), mint: b58(raw.slice(16, 48)) };
}

export function parseRep(raw) {
  if (!raw || raw.length !== REP_LEN) return { paidJobs: 0, totalPaid: 0, repositories: 0 };
  const dv = view(raw);
  return { paidJobs: dv.getUint32(0, true), totalPaid: Number(dv.getBigUint64(8, true)), repositories: dv.getUint32(16, true) };
}

// ---- who can change a program ---------------------------------------------------------------------------------------
/** The upgrade authority in a program-data account: an address, null when the program is immutable, undefined when
 *  the bytes are not a program-data account (the program is not deployed). */
export function upgradeAuthority(programDataBytes) {
  if (!programDataBytes || programDataBytes.length < 45 || programDataBytes[0] !== 3) return undefined;
  return programDataBytes[12] === 1 ? b58(programDataBytes.slice(13, 45)) : null;
}

/** A Squads multisig's vault: the address that signs what the multisig approved (index 0 unless it made more). */
export const squadsVault = async (multisig, index = 0) =>
  (await findProgramAddress([enc.encode("multisig"), key(multisig), enc.encode("vault"), Uint8Array.of(index)], SQUADS))[0];

const MULTISIG = [224, 116, 121, 186, 68, 161, 79, 236];     // sha256("account:Multisig")[0..8], Anchor's account tag

/** A Squads v4 multisig account: how many of its members must approve, and how long an approved transaction waits
 *  before it can run (`timeLock`, seconds). null for any other account. */
export function readMultisig(raw) {
  if (!raw || raw.length < 100 || MULTISIG.some((b, i) => raw[i] !== b)) return null;
  const dv = view(raw);
  let o = 94;
  const rentCollector = raw[o] === 1 ? b58(raw.slice(o + 1, o + 33)) : null;
  o += raw[o] === 1 ? 33 : 1;
  const count = dv.getUint32(o + 1, true);
  if (o + 5 + 33 * count > raw.length) return null;
  const members = [];
  for (let m = 0; m < count; m++) members.push({ key: b58(raw.slice(o + 5 + 33 * m, o + 37 + 33 * m)), permissions: raw[o + 37 + 33 * m] });
  return { createKey: b58(raw.slice(8, 40)), configAuthority: b58(raw.slice(40, 72)), threshold: dv.getUint16(72, true),
    timeLock: dv.getUint32(74, true), transactionIndex: num(dv.getBigUint64(78, true)),
    staleTransactionIndex: num(dv.getBigUint64(86, true)), rentCollector, members };
}

// ---- knos-oidc: the verifier (both deployments send it the same Write, Step, Close, RegisterKey and KeyParams) -------
export const GITHUB = 0, GITLAB = 1;
export const ISSUERS = { [GITHUB]: "https://token.actions.githubusercontent.com", [GITLAB]: "https://gitlab.com" };
export const JWKS = { [GITHUB]: "https://token.actions.githubusercontent.com/.well-known/jwks", [GITLAB]: "https://gitlab.com/oauth/discovery/keys" };
export const MAX_JWT = 8192;
export const LATE = 3600;       // a token is accepted up to an hour past its exp (each instruction has its own replay guard)
export const T_JWT = 626;       // where the token's bytes start in its account
export const CHUNK = 880;       // token bytes per Write instruction (one per transaction)

/** The URL of an issuer and a modulus, as RegisterIssuerKey and RegisterPrivateKey carry them. */
function urlAndModulus(url, n) {
  const u = enc.encode(url);
  if (!(u.length > 8 && u.length <= MAX_ISS) || !url.startsWith("https://")) throw new Error(`an issuer URL starts with https:// and has at most ${MAX_ISS} bytes`);
  return cat(Uint8Array.of(u.length), u, modulusBytes(n));
}

const bytesOf = (jwt) => (typeof jwt === "string" ? enc.encode(jwt) : jwt);

/** What names a token on chain: sha256 of its bytes. */
export const tokenId = (jwt) => sha256(bytesOf(jwt));

/** An RSA modulus (a BigInt) as 256 or 512 big-endian bytes. */
export function modulusBytes(n) {
  let bits = 0;
  for (let v = BigInt(n); v > 0n; v >>= 1n) bits++;
  const k = Math.ceil(bits / 8);
  if (k !== 256 && k !== 512) throw new Error("only 2048- and 4096-bit RSA keys are supported");
  const out = new Uint8Array(k);
  let v = BigInt(n);
  for (let i = k - 1; i >= 0; i--) { out[i] = Number(v & 255n); v >>= 8n; }
  return out;
}

export const keyHash = (n) => sha256(modulusBytes(n));

/** { n0inv, r2 }: -n^-1 mod 2^32 and R^2 mod n (R = 2^bits), which KeyParams takes and checks on chain. */
export function keyParams(n) {
  n = BigInt(n);
  const k = modulusBytes(n).length, W = 1n << 32n;
  let inv = n % W;                                      // Newton's iteration: each round doubles the correct bits
  for (let i = 0; i < 5; i++) inv = (inv * (2n + W - ((n * inv) % W))) % W;
  let r2 = 1n, b = 2n % n;
  for (let e = BigInt(16 * k); e > 0n; e >>= 1n) { if (e & 1n) r2 = (r2 * b) % n; b = (b * b) % n; }
  const out = new Uint8Array(k);
  for (let i = k - 1; i >= 0; i--) { out[i] = Number(r2 & 255n); r2 >>= 8n; }
  return { n0inv: Number((W - inv) % W), r2: out };
}

/** Squarings per Step transaction, 16 in all, so that every transaction stays under the 1,400,000 compute units a
 *  transaction can have, for a token of any size up to MAX_JWT. */
export const stepPlan = (bits) => (bits === 2048 ? [8, 8] : [2, 3, 3, 3, 4, 1]);

/** What names an issuer on chain: sha256 of its URL, exactly as the issuer writes it in `iss`. */
export const issuerHash = (url) => sha256(enc.encode(url));

/** The audience the pinned rotate workflow asks GitHub to sign for a key it found in the issuer's JWKS. `issuer` is
 *  GitHub (0), GitLab (1), or any other RS256 issuer's URL. */
export const rotateAudience = async (issuer, n) => (typeof issuer === "string"
  ? `knos-oidc:ikey:${hex(await issuerHash(issuer))}:${hex(await keyHash(n))}` : `knos-oidc:key:${issuer}:${hex(await keyHash(n))}`);

function unb64url(s) {
  const b = atob(s.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - (s.length % 4)) % 4));
  return Uint8Array.from(b, (c) => c.charCodeAt(0));
}

/** [kid, modulus] for each RS256 key with exponent 65537 in a JWKS document. */
export function jwksKeys(jwks) {
  const out = [];
  for (const k of jwks.keys || []) {
    if (k.kty !== "RSA" || k.e !== "AQAB" || (k.alg ?? "RS256") !== "RS256") continue;
    out.push([k.kid ?? "", BigInt("0x" + (hex(unb64url(k.n)) || "0"))]);
  }
  return out;
}

/** A token account: { stage (0 writing, 1 stepping, 2 verified), issuer, done, exp, key, payer, payload, verified,
 *  claims() }. `payload` is the decoded claims (JSON bytes), only when verified. null for anything shorter. */
export function readToken(raw) {
  if (!raw || raw.length < T_JWT) return null;
  const dv = view(raw);
  const off = dv.getUint16(6, true), len = dv.getUint16(8, true);
  const payload = raw[0] === 2 ? raw.slice(off, off + len) : new Uint8Array(0);
  return { stage: raw[0], issuer: raw[1], done: raw[2], exp: num(dv.getBigInt64(10, true)), key: b58(raw.slice(18, 50)),
    payer: b58(raw.slice(50, 82)), payload, verified: raw[0] === 2, claims: () => JSON.parse(new TextDecoder().decode(payload)) };
}

const meta = (pubkey, signer, writable) => ({ pubkey, signer, writable });

/** The verifier at one program id: its addresses and instructions. `tid` is tokenId(jwt); `n` a modulus (BigInt). */
export function verifier(program) {
  const o = {
    program,
    tokenPda: async (payer, tid) => (await findProgramAddress([enc.encode("tok"), key(payer), tid], program))[0],
    /** The key account of GitHub (0) or GitLab (1), of any other issuer named by its URL, or (with `registrant`) the
     *  private key that wallet registered for that URL. */
    async keyPda(issuer, n, registrant = null) {
      const seeds = registrant ? [enc.encode("pkey"), key(registrant), await issuerHash(String(issuer))]
        : typeof issuer === "string" ? [enc.encode("ikey"), await issuerHash(issuer)] : [enc.encode("key"), Uint8Array.of(issuer)];
      return (await findProgramAddress([...seeds, await keyHash(n)], program))[0];
    },
    /** The account that holds an issuer's URL, created with its first key. */
    issPda: async (url) => (await findProgramAddress([enc.encode("iss"), await issuerHash(url)], program))[0],
    /** The token into its account: one instruction per CHUNK bytes, each in a transaction of its own. */
    async writeIxs(payer, tid, jwt) {
      const raw = bytesOf(jwt);
      if (!raw.length || raw.length > MAX_JWT) throw new Error(`token is ${raw.length} bytes; the verifier takes up to ${MAX_JWT}`);
      const accounts = [meta(payer, true, true), meta(await o.tokenPda(payer, tid), false, true), meta(SYSTEM, false, false)];
      const out = [];
      for (let off = 0; off < raw.length; off += CHUNK) {
        out.push({ program, data: cat(Uint8Array.of(0), tid, u16(raw.length), u16(off), raw.slice(off, off + CHUNK)), accounts });
      }
      return out;
    },
    stepIx: async (payer, tid, keyAccount, squarings) => ({ program, data: cat(Uint8Array.of(1), tid, Uint8Array.of(squarings)),
      accounts: [meta(payer, true, false), meta(await o.tokenPda(payer, tid), false, true), meta(keyAccount, false, false)] }),
    closeIx: async (payer, tid) => ({ program, data: cat(Uint8Array.of(2), tid),
      accounts: [meta(payer, true, true), meta(await o.tokenPda(payer, tid), false, true)] }),
    /** A genesis key needs no `attest`. Any other needs a verified token account whose audience is
     *  rotateAudience(issuer, n), from the pinned rotate workflow run in the attester's repository, and `attestKey`:
     *  the key account that verified that token (readToken(its data).key), usable now. The program refuses an
     *  attested registration sent without it. */
    async registerKeyIx(payer, issuer, n, attest = null, attestKey = null) {
      const accounts = [meta(payer, true, true), meta(await o.keyPda(issuer, n), false, true), meta(SYSTEM, false, false)];
      if (attest) accounts.push(meta(attest, false, false));
      if (attest && attestKey) accounts.push(meta(attestKey, false, false));
      return { program, data: cat(Uint8Array.of(3, issuer), modulusBytes(n)), accounts };
    },
    /** A key of any RS256 issuer, named by the issuer's URL. `attest`: a VERIFIED token account whose audience is
     *  rotateAudience(url, n), from the attester's run of the pinned rotate workflow; `attestKey`: the key account that
     *  verified it. The key waits KEY_DELAY and the guardian, like any attested key. */
    async registerIssuerKeyIx(payer, url, n, attest, attestKey) {
      return { program, data: cat(Uint8Array.of(8), urlAndModulus(url, n)), accounts: [meta(payer, true, true), meta(await o.keyPda(url, n), false, true),
        meta(await o.issPda(url), false, true), meta(SYSTEM, false, false), meta(attest, false, false), meta(attestKey, false, false)] };
    },
    /** A private key: the wallet `registrant` says that `n` is a key of the issuer at `url`, and nobody checks it.
     *  Usable at once (after KeyParams) for KEY_TTL; sent again by the same wallet it renews the key. Every token it
     *  verifies carries the wallet's address, and a consumer accepts it only from a wallet it trusts for that purpose. */
    async registerPrivateKeyIx(registrant, url, n) {
      return { program, data: cat(Uint8Array.of(9), urlAndModulus(url, n)),
        accounts: [meta(registrant, true, true), meta(await o.keyPda(url, n, registrant), false, true), meta(SYSTEM, false, false)] };
    },
    async keyParamsIx(payer, issuer, n, registrant = null) {
      const { n0inv, r2 } = keyParams(n);
      return { program, data: cat(Uint8Array.of(4), u32(n0inv), r2), accounts: [meta(payer, true, false), meta(await o.keyPda(issuer, n, registrant), false, true)] };
    },
    // -- the second deployment only: how a key lives --
    /** The key's expiry becomes now + KEY_TTL if that is later. `attest` and `attestKey` as for registerKeyIx (the
     *  program refuses a Refresh sent without `attestKey`). Anyone may send it. */
    refreshIx: async (payer, issuer, n, attest, attestKey = null) => ({ program, data: Uint8Array.of(5),
      accounts: [meta(payer, true, false), meta(await o.keyPda(issuer, n), false, true), meta(attest, false, false),
        ...(attestKey ? [meta(attestKey, false, false)] : [])] }),
    approveIx: async (guardian, issuer, n) => ({ program, data: Uint8Array.of(6),
      accounts: [meta(guardian, true, false), meta(await o.keyPda(issuer, n), false, true)] }),
    /** For ever: no instruction undoes it, and the same modulus cannot be registered for that issuer again. The
     *  signer is the guardian, or for a private key (`registrant`) the wallet that registered it. */
    revokeIx: async (guardian, issuer, n, registrant = null) => ({ program, data: Uint8Array.of(7),
      accounts: [meta(guardian, true, false), meta(await o.keyPda(issuer, n, registrant), false, true)] }),
  };
  return o;
}

// ---- a client bound to the first deployment's program ids ----------------------------------------------------------
export function client(ids) {
  const PAY = ids.knos_pay;
  const pda = async (...seeds) => (await findProgramAddress(seeds, PAY))[0];
  const k = {
    ids,
    oidc: verifier(ids.knos_oidc),
    auth: () => pda(enc.encode("auth")),
    vault: (mint) => pda(enc.encode("vault"), key(mint)),
    faucetMint: () => pda(enc.encode("mint")),
    /** A job's address. `funder` is the wallet that funded it; omit it for the repository's own token-funded bounty. */
    job: (repoId, issue, funder = null) => pda(enc.encode("job"), u64(repoId), u64(issue), funder ? key(funder) : new Uint8Array(32)),
    due: (userId, mint) => pda(enc.encode("due"), u64(userId), key(mint)),
    rep: (userId) => pda(enc.encode("rep"), u64(userId)),
    rate: (repoId) => pda(enc.encode("rate"), u64(repoId)),

    /** A wallet funds a bounty on any issue of a repository that runs Knos's workflow at commit `wfSha`. */
    async fundIx({ funder, funderToken, mint, repoId, issue, amount, wfRepo, wfSha, mode = MERGE, checksHex = ZERO,
      workS = 14 * 86400, reviewS = 0 }) {
      if (!/^[0-9a-f]{40}$/.test(wfSha)) throw new Error("wfSha must be a full commit sha");
      const data = cat(Uint8Array.of(0), u64(repoId), u64(issue), u64(amount), i64(workS), i64(reviewS), Uint8Array.of(mode),
        unhex(checksHex), await wfRepoHash(wfRepo), enc.encode(wfSha));
      return { program: PAY, data, accounts: [meta(funder, true, true), meta(await k.job(repoId, issue, funder), false, true),
        meta(funderToken, false, true), meta(await k.vault(mint), false, true), meta(mint, false, false),
        meta(await k.auth(), false, false), meta(TOKEN, false, false), meta(SYSTEM, false, false)] };
    },

    /** The funding wallet takes back a tests-mode payment during its review window. */
    vetoIx: (wallet, job) => ({ program: PAY, data: Uint8Array.of(4), accounts: [meta(wallet, true, false), meta(job, false, true)] }),
  };
  return k;
}

// ---- SPL Token ------------------------------------------------------------------------------------------------------
/** Creates the owner's associated token account if it does not exist (idempotent). */
export async function createAtaIx(payer, owner, mint, tokenProgram = TOKEN) {
  return { program: ATA_PROGRAM, data: Uint8Array.of(1), accounts: [meta(payer, true, true), meta(await ata(owner, mint, tokenProgram), false, true),
    meta(owner, false, false), meta(mint, false, false), meta(SYSTEM, false, false), meta(tokenProgram, false, false)] };
}

/** A plain token transfer that names the mint and its decimals (TransferChecked). This is how money is added to a
 *  Balance: `dest` is the Balance's token account. `owner` signs for `source`. */
export const transferCheckedIx = (source, mint, dest, owner, amount, decimals, tokenProgram = TOKEN) => ({ program: tokenProgram,
  data: cat(Uint8Array.of(12), u64(amount), Uint8Array.of(decimals)),
  accounts: [meta(source, false, true), meta(mint, false, false), meta(dest, false, true), meta(owner, true, false)] });

/** A mint account's decimals, supply and mint authority (the fixed fields SPL Token and Token-2022 share). */
export function readMint(raw) {
  if (!raw || raw.length < 82) return null;
  const dv = view(raw);
  return { decimals: raw[44], supply: num(dv.getBigUint64(36, true)), mintAuthority: dv.getUint32(0, true) === 1 ? b58(raw.slice(4, 36)) : null };
}

/** A token account's mint, owner and amount (smallest units). */
export function readTokenAccount(raw) {
  if (!raw || raw.length < 165) return null;
  return { mint: b58(raw.slice(0, 32)), owner: b58(raw.slice(32, 64)), amount: num(view(raw).getBigUint64(64, true)) };
}

// ---- the second deployment (programs-v2): knos.settle.v2.pay and knos.settle.v2.oidc ------------------------------
const HOLD = 180 * 86_400, MAX_TERMS = 600, KEY_DELAY = 86_400, KEY_TTL = 30 * 86_400, K_HDR = 40;
const KEY_TAIL = 64, OTHER = 2, PRIVATE = 3, PRIVATE_FLAG = 8, MAX_ISS = 200, T_IHASH = 114;   // keys of other issuers, and private ones
const COUNTED = Object.freeze([USDC_DEVNET, USDC_MAINNET]);     // the record counts real money only in these mints
// work orders (2.1). Amounts are millionths of one whole unit of the mint: `units` gives the mint's smallest units.
const BALX_LEN = 152, PLAN_LEN = 24, ORDER_LEN = 512, OPTS_LEN = 48;
const MAX_AMOUNT2 = 100_000_000_000;         // 100,000.00 per job and per order on devnet; a build for real money decides its own cap
const ORDER_FEE_MIN = 400_000, ORDER_MIN_AMOUNT = 5_000_000, TIP = 50_000, TIP_FIRST = 300_000, PLAN_BPS_MIN = 50;
// an order's fee is marginal: FEE_BPS (or a Plan's rate) of the first FEE_TIER_1, FEE_BPS_2 up to FEE_TIER_2, FEE_BPS_3 above; no cap
const FEE_TIER_1 = 1_000_000_000, FEE_TIER_2 = 50_000_000_000, FEE_BPS_2 = 100, FEE_BPS_3 = 50;
const MAX_HOLDBACK_BPS = 5000, MAX_WARRANTY_DAYS = 90, MAX_KILL_BPS = 2000, MAX_PAYEES = 4;
const F_FAUCET = 1, F_PRIVATE = 2, F_NEUTRAL = 4, F_STANDING = 8, F_TOKEN2022 = 16;
// what an order can promise (order_terms.rs): the record of a holdback, the two markers, an assignment
const HB_LEN = 240, DONE_LEN = 65, AS_LEN = 88, USED_LEN = 41;
const NOTICE = 7 * 86_400;                  // a cancelled order still takes a pay token for this long
const USED_KEEP = 300 + 3600 + 3600 + 3600; // a used marker can be closed this long after it was made
// The instructions that take a token (tag: the index of the token account). Each takes the token's marker (usedPda).
// MINTED: a marker's first byte after the devnet faucet took the token; the funding that follows still takes it.
const TOKEN_AT = Object.freeze({ 3: 1, 5: 1, 8: 1, 11: 1, 16: 1, 17: 1, 19: 1, 20: 1, 21: 2, 25: 1 });
const MINTED = 2;
const STATES2 = { 1: "open", 3: "held", 4: "warranty" };
const ERRORS = {
  76: "the key that signed this token is not active on chain yet: it waits for its delay and the guardian's approval; try again after that",
  77: "the key that signed this token has expired on chain; run the rotate workflow and send Refresh for the key, then relay the token again while it is fresh",
  78: "the key that signed this token was revoked on chain, so the token can do nothing; run the workflow again for a token signed by another key",
  80: "a wrong account, or a missing signature",
  81: "the amount, the work time, the mode, the workflow commit, the terms or the pause length is outside what is allowed",
  82: "this issue already has a job from this funder, or the account is not a job",
  83: "too early or too late: the job is not in the state this needs",
  84: "the token is not verified, not GitHub's, expired, or its times are not GitHub's; a new run gives a new one",
  85: "the token's claims do not allow this: the event, the runner, the repository or its owner, or a re-run instead of a first run",
  86: "the token is not from the workflow this needs",
  87: "the token's audience does not match",
  88: "wrong destination, fee or refund account, or the payee has not bound a wallet yet",
  89: "only on a devnet build",
  90: "the faucet gives test USDC once per repository per minute, in the order GitHub issued the tokens; wait a minute and comment again",
  91: "this token is not newer than the last one used here, and a token works once; comment again for a new one",
  92: "this comment cannot spend that balance: only its repository owner and the spenders its wallet listed can",
  93: "more than that balance allows for one job",
  94: "the balance does not hold that much; add money to it or fund less",
  95: "this mint cannot be used: it is not a mint of the token program passed, or it can block or tax a transfer",
  96: "new funding is paused; payments, refunds, withdrawals and binds go on",
  97: "only the guardian can pause",
  98: "the balance exists already, is not a balance, or the signer is not the wallet that opened it",
  99: "a faucet balance holds test USDC and cannot be withdrawn",
  100: "more than this balance may spend in one day or in total; its wallet can raise the limit, or fund less",
  101: "this order exists already (use another seq), or the account is not an order",
  102: "only the fee owner sets a plan, with a rate of 50 to 250 basis points and an expiry in the future",
  103: "this order is both standing and has a holdback, and such an order is never paid: its money goes back to its funder at the deadline; fund a new one that is standing or has a holdback, not both",
};

function sorted(value) {
  if (Array.isArray(value)) return value.map(sorted);
  if (value && typeof value === "object") return Object.fromEntries(Object.keys(value).sort().map((name) => [name, sorted(value[name])]));
  return value;
}

/** The canonical JSON of a job's terms, as bytes: keys sorted, no spaces, ASCII (anything else written as an escape,
 *  the way Python's json writes it). This is what the funding instruction carries and logs, and what termsHash hashes. */
function termsJson(terms) {
  const json = JSON.stringify(sorted(terms));
  let text = "";
  for (let i = 0; i < json.length; i++) {
    const code = json.charCodeAt(i);
    text += code < 127 ? json[i] : "\\u" + code.toString(16).padStart(4, "0");
  }
  if (text.length > MAX_TERMS) throw new Error(`the terms are ${text.length} bytes; a job takes at most ${MAX_TERMS}`);
  return enc.encode(text);
}

/** sha256 of the terms JSON bytes: what a job stores and what the fund and pay audiences carry. */
const termsHash = (terms) => sha256(bytesOf(terms));

/** A funder as the record counts it: the funding wallet (an address), or the GitHub owner id of a Balance. */
const funderKey = async (funder) => (typeof funder === "string" ? unb58(funder) : sha256(cat(enc.encode("gh"), u64(funder))));

/** `termsHex` is hex(termsHash(...)). `balance` is the Balance this comment spends: the funder's workflow chooses
 *  it, and the program spends no other with this token. */
const fundAudience2 = (issue, amount, mode, termsHex, balance, workS = 14 * 86400) =>
  `knos2:fund:${issue}:${amount}:${mode}:${termsHex}:${workS}:${balance}`;
/** The Balance a fund audience names. */
const namedBalance = (audience) => audience.split(":").at(-1);
/** `address`: where the payee asked to be paid in the pull request, or null (the job is then held for them unless
 *  they have bound a wallet). */
const payAudience2 = (repoId, issue, payeeId, headSha, termsHex, mode, address = null) =>
  `knos2:pay:${repoId}:${issue}:${payeeId}:${headSha}:${termsHex}:${mode}:${address ?? "-"}`;
const bindAudience = (address) => `knos2:bind:${address}`;

/** Where the program will pay a pay token: the payee's bound wallet, else the address the audience carries, else
 *  null (the job is held for the payee). `bind` is readBind of the account at k.bind(payee id). */
function destination(bind, audience) {
  if (bind) return bind.wallet;
  const address = audience.split(":").at(-1);
  return address === "-" ? null : address;
}

/** A job: one bounty on one issue. `funder` is who the record counts as its funder: the Balance's GitHub owner id,
 *  or the funding wallet. null for anything that is not a job account. */
function readJob(raw) {
  if (!raw || raw.length !== 320) return null;
  const dv = view(raw);
  const u = (o) => num(dv.getBigUint64(o, true)), i = (o) => num(dv.getBigInt64(o, true));
  const j = { state: STATES2[raw[0]] || "?", mode: raw[1], fromBalance: raw[2] === 1, tokenProgram: raw[6] === 1 ? TOKEN_2022 : TOKEN,
    faucet: raw[7] === 1, repoId: u(8), issue: u(16), amount: u(24), deadline: i(32), holdUntil: i(48), payeeId: u(56), funderId: u(64),
    notBefore: i(72), ownerId: u(80), source: b58(raw.slice(88, 120)), refundTo: b58(raw.slice(120, 152)), rentTo: b58(raw.slice(152, 184)),
    mint: b58(raw.slice(184, 216)), terms: hex(raw.slice(216, 248)), wfRepoHash: hex(raw.slice(248, 280)), wfSha: ascii(raw.slice(280, 320)) };
  j.funder = j.fromBalance ? j.ownerId : j.source;
  return j;
}

/** A Balance: money a wallet (`authority`) set aside for the repositories of one GitHub owner. `capPerJob` 0: no cap.
 *  `spenders`: the GitHub ids that may spend it by comment, besides the owner. `spent`: everything it ever put into jobs.
 *  `hasX`: it has a side account (balxPda) that every funding from it must pass. */
function readBalance(raw) {
  if (!raw || raw.length !== 160 || raw[0] !== 1) return null;
  const dv = view(raw);
  const spenders = [0, 1, 2, 3].map((s) => num(dv.getBigUint64(96 + 8 * s, true))).filter((s) => s);
  return { faucet: raw[2] === 1, ownerId: num(dv.getBigUint64(8, true)), authority: b58(raw.slice(16, 48)), mint: b58(raw.slice(48, 80)),
    capPerJob: num(dv.getBigUint64(80, true)), lastIat: num(dv.getBigInt64(88, true)), spenders, spent: num(dv.getBigUint64(128, true)),
    hasX: raw[3] === 1 };
}

/** The wallet a GitHub user is paid at. */
function readBind(raw) {
  if (!raw || raw.length !== 56 || raw[0] !== 1) return null;
  const dv = view(raw);
  return { userId: num(dv.getBigUint64(8, true)), wallet: b58(raw.slice(16, 48)), iat: num(dv.getBigInt64(48, true)) };
}

/** A GitHub user's public record. `paid`, `funders`, `total`: payments from someone else that were not faucet money,
 *  the distinct funders among them, and what they put in the wallet. `testPaid`, `testTotal`: payments in the
 *  faucet's test USDC. `selfPaid`: payments whose funder was the payee. `first`, `last`: times of the first and the
 *  latest payment counted in `paid` (0: none yet). */
function readRep(raw) {
  if (!raw || raw.length !== 64) return { paid: 0, funders: 0, total: 0, testPaid: 0, selfPaid: 0, testTotal: 0, first: 0, last: 0 };
  const dv = view(raw);
  return { paid: dv.getUint32(0, true), funders: dv.getUint32(4, true), total: num(dv.getBigUint64(8, true)), testPaid: dv.getUint32(16, true),
    selfPaid: dv.getUint32(20, true), testTotal: num(dv.getBigUint64(32, true)), first: num(dv.getBigInt64(40, true)),
    last: num(dv.getBigInt64(48, true)) };
}


// ---- work orders (knos-pay 2.1): pure functions -----------------------------------------------------------------------
/** `micro` millionths of one whole unit of a mint with `decimals` decimals, in the mint's smallest units. */
function units(micro, decimals = 6) {
  const v = (BigInt(micro) * 10n ** BigInt(decimals)) / 1_000_000n;
  return num(v < 2n ** 64n - 1n ? v : 2n ** 64n - 1n);
}

/** The fee of a job (2.0), taken out of its amount: 2.5%, at least 0.05 of a whole unit, never more than the amount. */
function feeOf2(amount, decimals = 6) {
  const a = BigInt(amount), pct = (a * BigInt(FEE_BPS)) / 10000n, floor = BigInt(units(FEE_MIN, decimals));
  const fee = pct > floor ? pct : floor;
  return num(fee < a ? fee : a);
}

/** The fee of an order (2.1), which its funder pays on top of the amount, exactly as the program computes it (lib.rs
 *  order_fee): `bps` (FEE_BPS, or the owner's Plan) of the first 1,000 whole units, 1% of what lies between 1,000 and
 *  50,000, 0.5% of what lies above, each part rounded down; at least 0.40; no maximum. */
function orderFee(amount, bps = FEE_BPS, decimals = 6) {
  const a = BigInt(amount), t1 = BigInt(units(FEE_TIER_1, decimals)), t2 = BigInt(units(FEE_TIER_2, decimals));
  const first = a < t1 ? a : t1, second = (a < t2 ? a : t2) - first, third = a - first - second;
  const fee = (first * BigInt(bps)) / 10000n + (second * BigInt(FEE_BPS_2)) / 10000n + (third * BigInt(FEE_BPS_3)) / 10000n;
  const floor = BigInt(units(ORDER_FEE_MIN, decimals));
  return num(fee > floor ? fee : floor);
}

const fromHex = (v) => (typeof v === "string" ? unhex(v) : v);

/** An order's scope. Public: sha256("knos3:scope" || repo id || issue). Private (`salt`, 32 bytes, kept off chain):
 *  sha256(salt || repo id || issue); the order then stores no repository and no issue. */
const scopeOf = (repoId, issue, salt = null) => sha256(cat(salt ? fromHex(salt) : enc.encode("knos3:scope"), u64(repoId), u64(issue)));

/** sha256 of a token's signature bytes: what names its single-use marker. `token`: the JWT as GitHub gave it, or the
 *  data of its token account in the verifier (the signature stays there as the token carried it). */
function sigHash(token) {
  let part;
  if (typeof token === "string") part = token.slice(token.lastIndexOf(".") + 1);
  else {
    const jwt = ascii(token.slice(T_JWT, T_JWT + view(token).getUint16(4, true)));
    part = jwt.slice(jwt.lastIndexOf(".") + 1);
  }
  return sha256(unb64url(part));
}

/** The 48 bytes a funder fixes beside the amount and the terms. `flags`: F_PRIVATE, F_NEUTRAL, F_STANDING. */
function opts({ flags = 0, holdbackBps = 0, warrantyDays = 0, killBps = 0, reserveDays = 0, rate = 0, arbiterId = 0, judgeRepoId = 0, salted = false } = {}) {
  return cat(Uint8Array.of(flags), u16(holdbackBps), u16(warrantyDays), u16(killBps), Uint8Array.of(reserveDays), u64(rate), u64(arbiterId),
    u64(judgeRepoId), Uint8Array.of(salted ? 1 : 0), new Uint8Array(15));
}

/** What fund.yml asks GitHub to sign to fund an order from a Balance. `termsHex` is hex(termsHash(...)); `options` is opts(...). */
const orderFundAudience = (issue, amount, mode, termsHex, balance, workS = 14 * 86400, seq = 0, options = null) =>
  `knos3:fund:${issue}:${amount}:${mode}:${termsHex}:${workS}:${balance}:${seq}:${hex(options ?? opts())}`;

/** `payees`: 1..=4 of [GitHub id, basis points, address or null]; the basis points add up to 10000. */
const payeesText = (payees) => payees.map(([id, bps, address]) => `${id}.${bps}.${address ?? "-"}`).join(",");

/** What a judge's workflow asks GitHub to sign to pay an order. `payees` as payeesText takes them. */
const orderPayAudience = (order, headSha, termsHex, mode, pr, payees) => `knos3:pay:${order}:${headSha}:${termsHex}:${mode}:${pr}:${payeesText(payees)}`;

/** The payees a pay audience of an order names: [GitHub id, basis points, address or null], in its order. */
const payeesOf = (audience) => audience.split(":").at(-1).split(",").map((entry) => {
  const [id, bps, address] = entry.split(".");
  return [num(BigInt(id)), Number(bps), address === "-" ? null : address];
});

/** Where the program pays one payee of an order: the address the token carries for it, else its bound wallet, else
 *  null (a single payee: the order is held for it; one of several: the payment is refused). `bind` is readBind's. */
const orderDestination = (bind, address) => address ?? bind?.wallet ?? null;

/** What the fund audience of a PRIVATE order carries where a public one carries its terms hash: sha256(scope || terms
 *  hash) (bytes or hex each). GitHub's signature then fixes both, and the audience names neither the repository nor the
 *  issue: pass issue 0 to orderFundAudience. */
const privateFundTerms = (scope, termsHash) => sha256(cat(fromHex(scope), fromHex(termsHash)));

/** What attest.yml asks GitHub to sign when the arbiter an order named decides it: who is paid, and in what shares.
 *  `payees` as payeesText takes them; the arbiter cannot be one. The ruling is relayed with payOrderIx, like any pay token. */
const ruleAudience = (order, payees) => `knos3:rule:${order}:${payeesText(payees)}`;
/** What the pinned claim workflow asks GitHub to sign when a member starts it by hand in an ORGANISATION's repository
 *  named knos-claim: the organisation is paid at `address`. (A person binds with bindAudience.) */
const orgBindAudience = (address) => `knos3:bind:${address}`;
/** What the taker's own run asks GitHub to sign to reserve an order for `takerId` for `days` (at most the order's reserveDays):
 *  the order's repository answering his comment (fund.yml) or his pull request (prove.yml), or, for a NEUTRAL order,
 *  attest.yml he started by hand in a repository of his. The token's actor must be `takerId`. */
const takeAudience = (order, takerId, days) => `knos3:take:${order}:${takerId}:${days}`;
/** What the order's own repository asks GitHub to sign (fund.yml answering a comment, or prove.yml) to cancel an order
 *  funded from a Balance. The token's actor must be the commenter who funded it or the Balance's owner. */
const cancelAudience = (order) => `knos3:cancel:${order}`;
/** What a judge of the order (a, b or c; not the arbiter) asks GitHub to sign when the accepted change was reverted
 *  inside the warranty. */
const revertAudience = (order, headSha) => `knos3:revert:${order}:${headSha}`;

/** The record of a holdback (the account at k.hbPda(order)): { payer (who paid its rent and gets it back), until (the
 *  end of the warranty), payees: [GitHub id, wallet, amount] each }. null for anything else. */
function readHoldback(raw) {
  if (!raw || raw.length !== HB_LEN || raw[0] !== 1) return null;
  const dv = view(raw), payees = [];
  for (let n = 0, o = 48; n < raw[2]; n++, o += 48) payees.push([num(dv.getBigUint64(o, true)), b58(raw.slice(o + 8, o + 40)), num(dv.getBigUint64(o + 40, true))]);
  return { payer: b58(raw.slice(8, 40)), until: num(dv.getBigInt64(40, true)), payees };
}

/** The assignee in the account at k.assignPda(order, payee id). With `o` (the order as it is now): null too when the
 *  assignment was made for an earlier order at the same address, which the program ignores. */
function readAssign(raw, o = null) {
  if (!raw || raw.length !== AS_LEN || raw[0] !== 1 || (o && num(view(raw).getBigInt64(80, true)) !== o.notBefore)) return null;
  return b58(raw.slice(48, 80));
}

/** Where the program pays one payee of an order: its assignee (`assign`: the data of the account at k.assignPda), else
 *  as orderDestination says. */
const payeeWallet = (assign, o, bind, address) => readAssign(assign, o) ?? orderDestination(bind, address);

/** A marker: [who paid its rent, the time after which a used marker can be closed] or, for the marker of a pull request
 *  a standing order paid, [who paid its rent, its order]. null for anything else. */
function readMarker(raw) {
  if (raw && raw.length === USED_LEN) return [b58(raw.slice(1, 33)), num(view(raw).getBigInt64(33, true))];
  if (raw && raw.length === DONE_LEN) return [b58(raw.slice(1, 33)), b58(raw.slice(33, 65))];
  return null;
}

/** Whether a token is used up, from the data of its marker (usedPda): no funding, and nothing else, takes it again.
 *  A marker the devnet faucet made (MINTED) is not: the one funding that follows the faucet still takes the token. */
const spent = (marker) => !!(marker && marker.length) && marker[0] !== MINTED;

/** What a refund owes the taker first: killBps of the amount (at most what is left of it), when an open order was
 *  cancelled while reserved. `o` is readOrder's. */
function killFee(o) {
  if (o.state !== "open" || !o.killBps || !o.cancelAt || !o.reservedBy || o.cancelAt > o.reservedUntil) return 0;
  const fee = (BigInt(o.amount) * BigInt(o.killBps)) / 10000n, left = BigInt(o.amount) - BigInt(o.paid);
  return num(fee < left ? fee : left);
}

/** An order: one work order, its money alone in its own token account. `funder` is who the record counts as its funder:
 *  the Balance's GitHub owner id, or the funding wallet. null for anything that is not an order account. */
function readOrder(raw) {
  if (!raw || raw.length !== ORDER_LEN || raw[0] !== 2) return null;
  const dv = view(raw), u = (o) => num(dv.getBigUint64(o, true)), i = (o) => num(dv.getBigInt64(o, true));
  const a = (o) => b58(raw.slice(o, o + 32));
  const o = { state: STATES2[raw[1]] || "?", mode: raw[2], fromBalance: raw[3] === 1, flags: raw[4], decimals: raw[6], reserveDays: raw[7],
    repoId: u(8), issue: u(16), scope: hex(raw.slice(24, 56)), seq: dv.getUint32(56, true), holdbackBps: dv.getUint16(60, true), killBps: dv.getUint16(62, true),
    amount: u(64), fee: u(72), rate: u(80), paid: u(88), deadline: i(96), notBefore: i(104), holdUntil: i(112), warrantyS: i(120), reservedBy: u(128),
    reservedUntil: i(136), cancelAt: i(144), payeeId: u(152), funderId: u(160), ownerId: u(168), arbiterId: u(176), judgeRepoId: u(184),
    source: a(192), refundTo: a(224), rentTo: a(256), mint: a(288), terms: hex(raw.slice(320, 352)), wfRepoHash: hex(raw.slice(352, 384)),
    wfSha: ascii(raw.slice(384, 424)), feeBps: dv.getUint16(424, true) };
  o.tokenProgram = o.flags & F_TOKEN2022 ? TOKEN_2022 : TOKEN;
  o.faucet = !!(o.flags & F_FAUCET);
  o.funder = o.fromBalance ? o.ownerId : o.source;
  return o;
}

/** A Balance's side account: what it may spend a day and in all, which repositories and which workflows commit may
 *  spend it, and the running counters. `repos`: empty means any repository of the owner; `wfSha`: "" means any. */
function readBalx(raw) {
  if (!raw || raw.length !== BALX_LEN || raw[0] !== 1) return null;
  const dv = view(raw), u = (o) => num(dv.getBigUint64(o, true));
  const sha = raw.slice(88, 128);
  return { dayLimit: u(8), totalLimit: u(16), repos: [0, 1, 2, 3, 4, 5, 6, 7].map((k) => u(24 + 8 * k)).filter((r) => r),
    wfSha: sha.every((b) => b === 0) ? "" : ascii(sha), day: num(dv.getBigInt64(128, true)), daySpent: u(136), totalSpent: u(144) };
}

/** The fee rate FEE_OWNER set for one owner's orders, until `expires`. null for anything that is not a plan. */
function readPlan(raw) {
  if (!raw || raw.length !== PLAN_LEN || raw[0] !== 1) return null;
  const dv = view(raw);
  return { feeBps: dv.getUint16(2, true), ownerId: num(dv.getBigUint64(8, true)), expires: num(dv.getBigInt64(16, true)) };
}

/** The fee rate of an owner's orders now: its Plan's while it lasts, FEE_BPS otherwise. */
const planBps = (plan, now) => (plan && now < plan.expires ? Math.min(Math.max(plan.feeBps, PLAN_BPS_MIN), FEE_BPS) : FEE_BPS);

/** The time until which new funding is refused (0: not paused, or never was). */
const readPause = (raw) => (raw && raw.length === 8 ? num(view(raw).getBigInt64(0, true)) : 0);

/** [when the devnet faucet last served a repository, that fund token's iat]; [0, 0] when it never did. */
const readRate = (raw) => (raw && raw.length === 16 ? [num(view(raw).getBigInt64(0, true)), num(view(raw).getBigInt64(8, true))] : [0, 0]);

/** A key account's header: { state (1: ready), issuer, bits, activeAt, expiresAt, approved, revoked, genesis, issuerHash,
 *  private, registrant }. A key of an issuer that is not GitHub (0) or GitLab (1) carries sha256 of the issuer's URL
 *  (`issuerHash`, hex), and a private one the wallet that registered it (`registrant`). null for anything that is not
 *  a key account of the second deployment. */
function readKey(raw) {
  if (!raw || raw.length < K_HDR || (raw[2] !== 64 && raw[2] !== 128) || raw.length !== K_HDR + 8 * raw[2] + (raw[1] >= OTHER ? KEY_TAIL : 0)) return null;
  const dv = view(raw), flags = raw[24], tail = K_HDR + 8 * raw[2];
  return { state: raw[0], issuer: raw[1], bits: 32 * raw[2], activeAt: num(dv.getBigInt64(8, true)), expiresAt: num(dv.getBigInt64(16, true)),
    approved: !!(flags & 1), revoked: !!(flags & 2), genesis: !!(flags & 4), issuerHash: raw[1] >= OTHER ? hex(raw.slice(tail, tail + 32)) : null,
    private: !!(flags & PRIVATE_FLAG), registrant: flags & PRIVATE_FLAG && raw[1] === PRIVATE ? b58(raw.slice(tail + 32, tail + 64)) : null };
}

/** For a VERIFIED token account of an issuer that is not GitHub (0) or GitLab (1): [sha256 of the issuer's URL (hex),
 *  the wallet that registered the key when it is a private one, else null]. null for any other account. */
function tokenIssuer(raw) {
  if (!raw || raw.length < T_JWT || raw[0] !== 2 || raw[1] < OTHER) return null;
  const who = raw.slice(T_IHASH + 32, T_IHASH + 64);
  return [hex(raw.slice(T_IHASH, T_IHASH + 32)), who.some((b) => b) ? b58(who) : null];
}

/** The URL in an issuer account (the one a key of that issuer's first registration made); null for anything else. */
function readIss(raw) {
  if (!raw || raw.length < 4 || raw[0] !== 3 || raw.length !== 4 + raw[3]) return null;
  return new TextDecoder().decode(raw.slice(4));
}

/** sha256 of the modulus a key account holds, as hex: what names the key (the account stores it as 32-bit limbs,
 *  lowest first). */
async function keyAccountHash(raw) {
  const size = 4 * raw[2];
  return hex(await sha256(raw.slice(K_HDR, K_HDR + size).reverse()));
}

const pad = (v) => String(v).padStart(2, "0");
function when(t) {
  if (!(t >= -62135596800 && t <= 253402300799)) return `time ${t}`;    // the years a date can name: 1 to 9999
  const d = new Date(t * 1000);
  return `${String(d.getUTCFullYear()).padStart(4, "0")}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())} ${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())} UTC`;
}

/** [whether Step accepts this key at `now` (the chain's clock), and if not, why and what to do]. `k` is readKey's. */
function keyUsable(k, now) {
  if (!k) return [false, "this signing key is not on chain yet. Send RegisterKey with an attestation from the rotate workflow."];
  if (k.state !== 1) return [false, "this signing key is registered but not ready. Send KeyParams for it (anyone can)."];
  if (k.revoked) return [false, "the guardian revoked this signing key. It cannot be used again."];
  if (!(k.genesis || k.approved || k.private)) {
    const wait = now < k.activeAt ? ` Its ${KEY_DELAY / 3600}-hour wait ends ${when(k.activeAt)}.` : "";
    return [false, `this signing key is new and the guardian has not approved it yet.${wait} Try again after the approval.`];
  }
  if (now < k.activeAt) return [false, `this signing key is new: it can be used from ${when(k.activeAt)}. Try again then.`];
  if (now >= k.expiresAt) {
    return [false, `this signing key expired ${when(k.expiresAt)}: nothing attested it for ${KEY_TTL / 86_400} days. `
      + "Run the rotate workflow and send Refresh with its token."];
  }
  return [true, ""];
}

// the accounts of each knos-pay instruction, in order, under the names idl/knos_pay_v2.json gives them
const PAYOUT = ["job", "bind", "destToken", "rep", "pair", "vault", "feeToken", "auth", "rentTo", "mint", "tokenProgram", "systemProgram"];
// a PayOrder's and a SettleOrder's accounts: what every payment shares, (PayOrder) the token's marker, then five for
// each payee, then each payee's assignment, then (PayOrder) a standing order's marker or a holdback's record
const ORDER_COMMON = ["order", "ov", "tipToken", "feeToken", "auth", "rentTo", "mint", "tokenProgram", "systemProgram", "ataProgram"];
const PER_PAYEE = ["bind", "wallet", "destToken", "rep", "pair"];
const HB_COMMON = ["auth", "rentTo", "hbPayer", "mint", "tokenProgram"];
// [name, accounts, tag], in the order of the tags, which is the IDL's. An instruction that pays several payees lists
// the first payee's accounts: accountNames gives every account of one instruction its name.
const PAY_IXS = [
  ["OpenBalance", ["authority", "balance", "baltok", "mint", "auth", "tokenProgram", "systemProgram"], 0],
  ["SetBalance", ["authority", "balance"], 1],
  ["Withdraw", ["authority", "balance", "baltok", "destToken", "mint", "auth", "tokenProgram"], 2],
  ["FundBalance", ["relayer", "fundToken", "key", "balance", "baltok", "job", "vault", "mint", "auth", "tokenProgram", "systemProgram", "pause", "used", "balx"], 3],
  ["FundWallet", ["funder", "job", "funderToken", "vault", "mint", "auth", "tokenProgram", "systemProgram", "pause"], 4],
  ["Pay", ["relayer", "payToken", "key", ...PAYOUT, "used"], 5],
  ["Settle", ["relayer", ...PAYOUT], 6],
  ["Refund", ["relayer", "job", "vault", "refundToken", "auth", "rentTo", "mint", "tokenProgram"], 7],
  ["Bind", ["relayer", "bindToken", "key", "bind", "systemProgram", "used"], 8],
  ["Pause", ["guardian", "payer", "pause", "systemProgram"], 9],
  ["InitFaucet", ["payer", "mint", "auth", "tokenProgram", "systemProgram"], 10],
  ["FaucetOpen", ["relayer", "fundToken", "key", "balance", "baltok", "mint", "auth", "tokenProgram", "systemProgram", "rate", "used"], 11],
  ["Version", [], 12],
  ["SetBalanceX", ["authority", "balance", "balx", "systemProgram"], 13],
  ["SetPlan", ["feeOwner", "payer", "plan", "systemProgram"], 14],
  ["FundOrderWallet", ["funder", "order", "ov", "funderToken", "mint", "auth", "tokenProgram", "systemProgram", "pause"], 15],
  ["FundOrderBalance", ["relayer", "fundToken", "key", "balance", "baltok", "balx", "plan", "order", "ov", "used", "mint", "auth", "tokenProgram", "systemProgram", "pause"], 16],
  ["PayOrder", ["relayer", "payToken", "key", ...ORDER_COMMON, "used", ...PER_PAYEE, "assign", "doneOrHb"], 17],
  ["Release", ["relayer", "order", "ov", "hb", "tipToken", "feeToken", ...HB_COMMON, "systemProgram", "ataProgram", "wallet", "destToken"], 18],
  ["Revert", ["relayer", "revertToken", "key", "order", "ov", "hb", "refundToken", ...HB_COMMON, "systemProgram", "used"], 19],
  ["Reserve", ["relayer", "takeToken", "key", "order", "systemProgram", "used"], 20],
  ["Cancel", ["signer", "order", "cancelToken", "key", "systemProgram", "used"], 21],
  ["RefundOrder", ["relayer", "order", "ov", "refundToken", "auth", "rentTo", "mint", "tokenProgram", "takerBind", "killToken"], 22],
  ["TopUp", ["signer", "order", "ov", "fromToken", "balance", "mint", "auth", "tokenProgram", "pause"], 23],
  ["Assign", ["signer", "order", "bind", "assign", "systemProgram"], 24],
  ["BindOrg", ["relayer", "bindToken", "key", "bind", "systemProgram", "used"], 25],
  ["SettleOrder", ["relayer", ...ORDER_COMMON, ...PER_PAYEE, "assign"], 26],
  ["CloseMarker", ["marker", "rentTo", "order"], 27],
];

/** The name of each of the `count` accounts of one knos-pay instruction, in order. PayOrder: its fourteen, five for each
 *  payee, then each payee's assignment, then the marker or the record when there is one. Release: its thirteen, then a
 *  wallet and its token account for each recorded payee. Every other instruction: the IDL's names as they stand. */
function accountNames(name, count) {
  const names = PAY_IXS.find((x) => x[0] === name)[1];
  if (name === "PayOrder") {
    const payees = Math.floor((count - 14) / 6), last = (count - 14) % 6;
    if (payees < 1 || last > 1) return names.slice(0, count);
    return [...names.slice(0, 14), ...Array(payees).fill(PER_PAYEE).flat(), ...Array(payees).fill("assign"), ...(last ? ["doneOrHb"] : [])];
  }
  if (name === "Release") return Array.from({ length: count }, (_x, at) => (at < 13 ? names[at] : ["wallet", "destToken"][(at - 13) % 2]));
  return names.slice(0, count);
}

/** What a FundOrderWallet carries, read back from its bytes: issue, repository, amount, mode, work seconds, seq, the 48
 *  option bytes (hex), the pinned workflows, then the terms JSON (a public order) or the scope and the terms hash (private). */
function orderArgs(d, dv) {
  const u = (o) => num(dv.getBigUint64(o, true)), flags = d[38], priv = !!(flags & F_PRIVATE);
  return { issue: u(1), repoId: u(9), amount: u(17), mode: d[25], workS: num(dv.getBigInt64(26, true)), seq: dv.getUint32(34, true), options: hex(d.slice(38, 86)),
    wfRepoHash: hex(d.slice(86, 118)), wfSha: ascii(d.slice(118, 158)),
    ...(priv ? { scope: hex(d.slice(158, 190)), terms: hex(d.slice(190)) } : { terms: ascii(d.slice(158)) }) };
}

function limits(cap, spenders) {
  const ids = [...spenders];
  if (ids.length > 4) throw new Error("a balance has at most 4 spenders");
  while (ids.length < 4) ids.push(0);
  return cat(u64(cap), ...ids.map(u64));
}

/** A client bound to the second deployment's ids (src/knos/settle/v2/program_ids.json). Every address and
 *  instruction is derived, nothing is fetched. Ids and amounts are numbers or BigInts; addresses are base58. */
function client2(ids) {
  const PAY = ids.knos_pay;
  const pda = async (...seeds) => (await findProgramAddress(seeds, PAY))[0];
  const tag = (s) => enc.encode(s);
  // a marker given as an address is used as it is; a JWT or a token account's data is turned into one
  const marker = async (used) => {
    if (used == null) throw new Error("a token that works once needs its marker: pass `used` (the JWT, the token account's data, or usedPda's address); every instruction that takes a token makes it");
    return typeof used === "string" && isAddress(used) ? used : k.usedPda(used);
  };
  const k = {
    ids,
    oidc: verifier(ids.knos_oidc),
    /** The owner of every vault and of every Balance's token account. Only the program signs for it. */
    auth: () => pda(tag("auth")),
    vault: (mint) => pda(tag("vault"), key(mint)),
    /** The Balance a wallet (`authority`) opened for the repositories of the GitHub owner `ownerId`, in one mint. */
    balance: (ownerId, authority, mint) => pda(tag("bal"), u64(ownerId), key(authority), key(mint)),
    /** The devnet test-USDC mint (SPL Token, 6 decimals); its mint authority is the program. */
    faucetMint: () => pda(tag("mint")),
    /** The devnet faucet's Balance of a GitHub owner: test USDC that fund tokens of that owner's repositories spend. */
    faucetBalance: async (ownerId) => k.balance(ownerId, await k.auth(), await k.faucetMint()),
    /** A Balance's token account. Add money to a Balance with a plain token transfer to this address. */
    baltok: (balance) => pda(tag("baltok"), key(balance)),
    /** A job's address. `source` is the Balance it is funded from, or the funding wallet. */
    job: (repoId, issue, source) => pda(tag("job"), u64(repoId), u64(issue), key(source)),
    bind: (userId) => pda(tag("bind"), u64(userId)),
    rep: (userId) => pda(tag("rep"), u64(userId)),
    /** Exists once this funder (a wallet's address, or the GitHub owner id of a Balance) has paid this payee. */
    pair: async (payeeId, funder) => pda(tag("pair"), u64(payeeId), await funderKey(funder)),
    rate: (repoId) => pda(tag("rate"), u64(repoId)),
    pause: () => pda(tag("pause")),
    /** A work order: `scope` is scopeOf(...) (bytes or hex), `source` the Balance it is funded from or the funding
     *  wallet, `seq` the funder's own counter, so one source can fund an issue more than once. */
    orderPda: async (scope, source, seq = 0) => pda(tag("ord"), fromHex(scope), key(source), u32(seq)),
    /** The token account that holds one order's money and nothing else. */
    ovPda: (order) => pda(tag("ov"), key(order)),
    /** A Balance's side account: limits per day and in total, the repositories and the workflows commit that may spend it. */
    balxPda: (balance) => pda(tag("balx"), key(balance)),
    planPda: (ownerId) => pda(tag("plan"), u64(ownerId)),
    /** Where the holdback of an order in warranty goes. */
    hbPda: (order) => pda(tag("hb"), key(order)),
    /** Exists once a standing order has paid this pull request. */
    donePda: (order, pr) => pda(tag("done"), key(order), u64(pr)),
    /** The wallet an order pays for this payee instead of the payee's own. */
    assignPda: (order, payeeId) => pda(tag("as"), key(order), u64(payeeId)),
    /** The single-use marker of a token: every instruction that takes a token makes it, and refuses the token once it
     *  is there. `token`: the JWT, the data of its token account, or the 32 bytes sigHash gave. */
    async usedPda(token) {
      return pda(tag("used"), token instanceof Uint8Array && token.length === 32 ? token : await sigHash(token));
    },

    /** Opens `authority`'s Balance for the repositories of the GitHub owner `ownerId`. `cap`: the most one job may
     *  take (0: no cap). `spenders`: up to 4 GitHub ids that may spend it by comment, besides the owner. */
    async openBalanceIx({ authority, ownerId, mint, cap = 0, spenders = [], tokenProgram = TOKEN }) {
      const balance = await k.balance(ownerId, authority, mint);
      return { program: PAY, data: cat(Uint8Array.of(0), u64(ownerId), limits(cap, spenders)),
        accounts: [meta(authority, true, true), meta(balance, false, true), meta(await k.baltok(balance), false, true), meta(mint, false, false),
          meta(await k.auth(), false, false), meta(tokenProgram, false, false), meta(SYSTEM, false, false)] };
    },
    setBalanceIx: ({ authority, balance, cap = 0, spenders = [] }) => ({ program: PAY, data: cat(Uint8Array.of(1), limits(cap, spenders)),
      accounts: [meta(authority, true, false), meta(balance, false, true)] }),
    /** Unspent money back to the wallet that opened the Balance. `amount` 0: everything. `destToken`: a token account
     *  of that wallet (default: its associated token account). */
    async withdrawIx({ authority, balance, mint, amount = 0, destToken = null, tokenProgram = TOKEN }) {
      return { program: PAY, data: cat(Uint8Array.of(2), u64(amount)),
        accounts: [meta(authority, true, false), meta(balance, false, false), meta(await k.baltok(balance), false, true),
          meta(destToken ?? await ata(authority, mint, tokenProgram), false, true), meta(mint, false, false), meta(await k.auth(), false, false),
          meta(tokenProgram, false, false)] };
    },
    /** Funds the job a fund token describes from the Balance its audience names. `key` is the verifier's account of
     *  the key that verified the token. `terms` is the terms JSON (bytes, or the text) whose hash the audience carries.
     *  `balx: true` adds the Balance's side account as a 14th account: the program requires it once the Balance has
     *  one (readBalance(...).hasX). `used`: the token's single-use marker, as payIx takes it (the 13th account). */
    async fundBalanceIx({ relayer, fundToken, key: keyAccount, balance, mint, repoId, issue, terms, used, tokenProgram = TOKEN, balx = false }) {
      return { program: PAY, data: cat(Uint8Array.of(3), bytesOf(terms)),
        accounts: [meta(relayer, true, true), meta(fundToken, false, false), meta(keyAccount, false, false), meta(balance, false, true),
          meta(await k.baltok(balance), false, true), meta(await k.job(repoId, issue, balance), false, true), meta(await k.vault(mint), false, true),
          meta(mint, false, false), meta(await k.auth(), false, false), meta(tokenProgram, false, false), meta(SYSTEM, false, false),
          meta(await k.pause(), false, false), meta(await marker(used), false, true), ...(balx ? [meta(await k.balxPda(balance), false, true)] : [])] };
    },
    /** A wallet funds a job with its own money. `wfRepo` ("owner/name") and `wfSha` pin the prove.yml that can prove it. */
    async fundWalletIx({ funder, funderToken, mint, repoId, issue, amount, wfRepo, wfSha, terms, mode = MERGE, workS = 14 * 86400,
      tokenProgram = TOKEN }) {
      if (!/^[0-9a-f]{40}$/.test(wfSha)) throw new Error("wfSha must be a full commit sha");
      const data = cat(Uint8Array.of(4), u64(repoId), u64(issue), u64(amount), i64(workS), Uint8Array.of(mode), await wfRepoHash(wfRepo),
        enc.encode(wfSha), bytesOf(terms));
      return { program: PAY, data, accounts: [meta(funder, true, true), meta(await k.job(repoId, issue, funder), false, true),
        meta(funderToken, false, true), meta(await k.vault(mint), false, true), meta(mint, false, false), meta(await k.auth(), false, false),
        meta(tokenProgram, false, false), meta(SYSTEM, false, false), meta(await k.pause(), false, false)] };
    },
    async payoutAccounts(job, j, payeeId, wallet, destToken) {
      const vault = await k.vault(j.mint);
      // a job that will be held names no destination: the vault stands in, and the program does not touch it
      const dest = destToken ?? (wallet ? await ata(wallet, j.mint, j.tokenProgram) : vault);
      return [meta(job, false, true), meta(await k.bind(payeeId), false, false), meta(dest, false, true), meta(await k.rep(payeeId), false, true),
        meta(await k.pair(payeeId, j.funder), false, true), meta(vault, false, true), meta(await ata(FEE_OWNER, j.mint, j.tokenProgram), false, true),
        meta(await k.auth(), false, false), meta(j.rentTo, false, true), meta(j.mint, false, false), meta(j.tokenProgram, false, false),
        meta(SYSTEM, false, false)];
    },
    /** `j` is readJob of `job`. `wallet` is destination(readBind(...), audience): the program pays a token account of
     *  that wallet (default: its associated token account; create it and FEE_OWNER's first), or holds the job when
     *  it is null. `used`: the token's single-use marker (usedPda), or what usedPda takes (the JWT, or the token
     *  account's data): a pay token pays, or holds, exactly one job. */
    async payIx({ relayer, payToken, key: keyAccount, job, j, payeeId, wallet, destToken = null, used }) {
      return { program: PAY, data: Uint8Array.of(5), accounts: [meta(relayer, true, true), meta(payToken, false, false), meta(keyAccount, false, false),
        ...await k.payoutAccounts(job, j, payeeId, wallet, destToken), meta(await marker(used), false, true)] };
    },
    /** Pays a held job once its payee has bound a wallet: `wallet` is readBind(k.bind(j.payeeId)).wallet. */
    settleIx: async ({ relayer, job, j, wallet, destToken = null }) => ({ program: PAY, data: Uint8Array.of(6),
      accounts: [meta(relayer, true, true), ...await k.payoutAccounts(job, j, j.payeeId, wallet, destToken)] }),
    /** An open job past its deadline, or a held job past its hold: the money back to the Balance it came from, or to
     *  a token account of the funding wallet (default: its associated token account). */
    async refundIx({ relayer, job, j, refundToken = null }) {
      const dest = refundToken ?? (j.fromBalance ? j.refundTo : await ata(j.refundTo, j.mint, j.tokenProgram));
      return { program: PAY, data: Uint8Array.of(7), accounts: [meta(relayer, true, true), meta(job, false, true), meta(await k.vault(j.mint), false, true),
        meta(dest, false, true), meta(await k.auth(), false, false), meta(j.rentTo, false, true), meta(j.mint, false, false),
        meta(j.tokenProgram, false, false)] };
    },
    /** `userId` is the token's actor_id. `used`: the token's single-use marker, as payIx takes it. */
    bindIx: async ({ relayer, bindToken, key: keyAccount, userId, used }) => ({ program: PAY, data: Uint8Array.of(8),
      accounts: [meta(relayer, true, true), meta(bindToken, false, false), meta(keyAccount, false, false), meta(await k.bind(userId), false, true),
        meta(SYSTEM, false, false), meta(await marker(used), false, true)] }),
    /** The guardian refuses new funding for `seconds` (at most 7 days) from now; 0 lifts the pause. */
    pauseIx: async ({ guardian, payer, seconds }) => ({ program: PAY, data: cat(Uint8Array.of(9), u32(seconds)),
      accounts: [meta(guardian, true, false), meta(payer, true, true), meta(await k.pause(), false, true), meta(SYSTEM, false, false)] }),
    initFaucetIx: async ({ payer }) => ({ program: PAY, data: Uint8Array.of(10), accounts: [meta(payer, true, true),
      meta(await k.faucetMint(), false, true), meta(await k.auth(), false, false), meta(TOKEN, false, false), meta(SYSTEM, false, false)] }),
    /** Devnet: mints the fund token's amount of test USDC into the faucet Balance of the token's repository owner,
     *  which the token's audience must name. Send fundBalanceIx on that Balance after it, in the same transaction.
     *  `used`: the token's marker, as payIx takes it: the faucet marks the token as minted on, and the funding that
     *  follows is the one instruction that still takes it. */
    async faucetOpenIx({ relayer, fundToken, key: keyAccount, ownerId, repoId, used }) {
      const balance = await k.faucetBalance(ownerId);
      return { program: PAY, data: Uint8Array.of(11), accounts: [meta(relayer, true, true), meta(fundToken, false, false), meta(keyAccount, false, false),
        meta(balance, false, true), meta(await k.baltok(balance), false, true), meta(await k.faucetMint(), false, true),
        meta(await k.auth(), false, false), meta(TOKEN, false, false), meta(SYSTEM, false, false), meta(await k.rate(repoId), false, true),
        meta(await marker(used), false, true)] };
    },

    // ---- work orders (2.1) ----
    /** The 2.1 build logs `knos2:version 1` when this is simulated; a 2.0 build refuses the instruction. */
    versionIx: () => ({ program: PAY, data: Uint8Array.of(12), accounts: [] }),
    /** The wallet that opened a Balance sets its side account. Limits are in the mint's smallest units (0: none);
     *  `repos`: up to 8 repository ids (none: any repository of the owner); `wfSha`: 40 hex characters, or "" for any. */
    async setBalanceXIx({ authority, balance, dayLimit = 0, totalLimit = 0, repos = [], wfSha = "" }) {
      const ids = [...repos];
      if (ids.length > 8) throw new Error("a balance lists at most 8 repositories");
      while (ids.length < 8) ids.push(0);
      return { program: PAY, data: cat(Uint8Array.of(13), u64(dayLimit), u64(totalLimit), ...ids.map(u64), wfSha ? enc.encode(wfSha) : new Uint8Array(40)),
        accounts: [meta(authority, true, true), meta(balance, false, true), meta(await k.balxPda(balance), false, true), meta(SYSTEM, false, false)] };
    },
    /** FEE_OWNER sets the fee rate (50..=250 basis points) of the orders of one repository owner until `expires`. */
    async setPlanIx({ feeOwner, payer, ownerId, feeBps, expires }) {
      return { program: PAY, data: cat(Uint8Array.of(14), u64(ownerId), u16(feeBps), i64(expires)),
        accounts: [meta(feeOwner, true, false), meta(payer, true, true), meta(await k.planPda(ownerId), false, true), meta(SYSTEM, false, false)] };
    },
    /** A wallet funds an order for an issue of any public repository: `amount` for the payees plus orderFee(amount) on
     *  top, from `funderToken`. `terms` is the terms JSON (bytes, or the text). A private order: `options` with F_PRIVATE
     *  and salted, `scope` = scopeOf(repoId, issue, salt), `repoId` and `issue` 0, and `terms` the 32-byte termsHash. */
    async fundOrderWalletIx({ funder, funderToken, mint, repoId, issue, amount, wfRepo, wfSha, terms, mode = MERGE, workS = 14 * 86400, seq = 0,
      options = null, scope = null, tokenProgram = TOKEN }) {
      if (!/^[0-9a-f]{40}$/.test(wfSha)) throw new Error("wfSha must be a full commit sha");
      const o = options ?? opts(), own = scope ? fromHex(scope) : await scopeOf(repoId, issue), order = await k.orderPda(own, funder, seq);
      const data = cat(Uint8Array.of(15), u64(issue), u64(repoId), u64(amount), Uint8Array.of(mode), i64(workS), u32(seq), o, await wfRepoHash(wfRepo),
        enc.encode(wfSha), scope ? fromHex(scope) : new Uint8Array(0), bytesOf(terms));
      return { program: PAY, data, accounts: [meta(funder, true, true), meta(order, false, true), meta(await k.ovPda(order), false, true),
        meta(funderToken, false, true), meta(mint, false, false), meta(await k.auth(), false, false), meta(tokenProgram, false, false),
        meta(SYSTEM, false, false), meta(await k.pause(), false, false)] };
    },
    /** Funds the order a fund token (knos3:fund) describes from the Balance its audience names. `mint` and `ownerId` are
     *  the Balance's; `repoId`, `issue` and `seq` are the token's; `terms` is the terms JSON whose hash the audience
     *  carries; `used` is the token's single-use marker, as payIx takes it. */
    async fundOrderBalanceIx({ relayer, fundToken, key: keyAccount, balance, mint, ownerId, repoId, issue, terms, used, seq = 0, tokenProgram = TOKEN }) {
      const order = await k.orderPda(await scopeOf(repoId, issue), balance, seq);
      return { program: PAY, data: cat(Uint8Array.of(16), bytesOf(terms)),
        accounts: [meta(relayer, true, true), meta(fundToken, false, false), meta(keyAccount, false, false), meta(balance, false, true),
          meta(await k.baltok(balance), false, true), meta(await k.balxPda(balance), false, true), meta(await k.planPda(ownerId), false, false),
          meta(order, false, true), meta(await k.ovPda(order), false, true), meta(await marker(used), false, true), meta(mint, false, false),
          meta(await k.auth(), false, false), meta(tokenProgram, false, false), meta(SYSTEM, false, false), meta(await k.pause(), false, false)] };
    },
    async orderCommon(relayer, order, o, tipToken) {
      const tp = o.tokenProgram;
      return [meta(order, false, true), meta(await k.ovPda(order), false, true), meta(tipToken ?? await ata(relayer, o.mint, tp), false, true),
        meta(await ata(FEE_OWNER, o.mint, tp), false, true), meta(await k.auth(), false, false), meta(o.rentTo, false, true), meta(o.mint, false, false),
        meta(tp, false, false), meta(SYSTEM, false, false), meta(ATA_PROGRAM, false, false)];
    },
    async payeeAccounts(o, payeeId, wallet, destToken) {
      // a payee the order will be held for names no wallet: the system program stands in, and the program does not read it
      const w = wallet ?? SYSTEM;
      return [meta(await k.bind(payeeId), false, false), meta(w, false, false), meta(destToken ?? await ata(w, o.mint, o.tokenProgram), false, true),
        meta(await k.rep(payeeId), false, true), meta(await k.pair(payeeId, o.funder), false, true)];
    },
    /** `o` is readOrder of `order`. `payees`: for each payee of the audience, in its order, [GitHub id, wallet] or
     *  [GitHub id, wallet, destToken]; `wallet` is orderDestination(readBind(...), the address the audience carries).
     *  The program pays each a token account of its wallet (default: its associated token account, which the program
     *  creates when it does not exist, at the relayer's cost and for a larger tip). `tipToken`: a token account of the
     *  relayer for the tip (default: its associated token account; it must exist, as FEE_OWNER's must). A payee who
     *  assigned this order's payment is paid at its assignee: pass payeeWallet(...) as its wallet. `pr`: the pull request
     *  the audience names (a STANDING order marks it). The token may be any judge's of the order, or its arbiter's ruling.
     *  `used`: the token's single-use marker, as payIx takes it: a pay token (or a ruling) pays, or holds, once; it comes
     *  before the payees' accounts. */
    async payOrderIx({ relayer, payToken, key: keyAccount, order, o, payees, used, tipToken = null, pr = 0 }) {
      const per = [];
      for (const [id, wallet, dest = null] of payees) per.push(...await k.payeeAccounts(o, id, wallet, dest));
      return { program: PAY, data: Uint8Array.of(17), accounts: [meta(relayer, true, true), meta(payToken, false, false), meta(keyAccount, false, false),
        ...await k.orderCommon(relayer, order, o, tipToken), meta(await marker(used), false, true), ...per, ...await k.termsAccounts(order, o, payees.map((p) => p[0]), pr)] };
    },
    /** What PayOrder takes after its payees: each payee's assignment (it need not exist, but cannot be left out), then
     *  a standing order's marker of the pull request, or the record of a holdback. */
    async termsAccounts(order, o, payeeIds, pr) {
      const out = [];
      for (const id of payeeIds) out.push(meta(await k.assignPda(order, id), false, false));
      if (o.flags & F_STANDING) out.push(meta(await k.donePda(order, pr), false, true));
      else if (o.holdbackBps) out.push(meta(await k.hbPda(order), false, true));
      return out;
    },
    /** Pays a held order once its payee has bound a wallet: `wallet` is readBind(k.bind(o.payeeId)).wallet, or the
     *  wallet the payee assigned this order's payment to (payeeWallet). */
    async settleOrderIx({ relayer, order, o, wallet, destToken = null, tipToken = null }) {
      return { program: PAY, data: Uint8Array.of(26), accounts: [meta(relayer, true, true), ...await k.orderCommon(relayer, order, o, tipToken),
        ...await k.payeeAccounts(o, o.payeeId, wallet, destToken), meta(await k.assignPda(order, o.payeeId), false, false)] };
    },
    /** An open order past its deadline, or a held one past its hold: everything it holds back to the Balance it came
     *  from, or to a token account of the funding wallet (default: its associated token account). When a kill fee is
     *  due (killFee(o) > 0), `killToken` is a token account of the taker's bound wallet and the fee is sent there first;
     *  with none (or a taker with no wallet) the fee stays held for him in the order, and the rest goes back now. */
    async refundOrderIx({ relayer, order, o, refundToken = null, killToken = null }) {
      const dest = refundToken ?? (o.fromBalance ? o.refundTo : await ata(o.refundTo, o.mint, o.tokenProgram));
      const kill = killFee(o) ? [meta(await k.bind(o.reservedBy), false, false), killToken ? meta(killToken, false, true) : meta(SYSTEM, false, false)] : [];
      return { program: PAY, data: Uint8Array.of(22), accounts: [meta(relayer, true, true), meta(order, false, true), meta(await k.ovPda(order), false, true),
        meta(dest, false, true), meta(await k.auth(), false, false), meta(o.rentTo, false, true), meta(o.mint, false, false), meta(o.tokenProgram, false, false),
        ...kill] };
    },
    /** Adds `add` to an open order's amount (the fee on it comes on top) from where its money came. A wallet's order:
     *  the funding wallet signs and `fromToken` is a token account of it (default: its associated token account). A
     *  Balance's order: the wallet that opened the Balance signs and the Balance's token account pays. */
    async topUpIx({ signer, order, o, add, fromToken = null }) {
      const src = fromToken ?? (o.fromBalance ? o.refundTo : await ata(o.source, o.mint, o.tokenProgram));
      return { program: PAY, data: cat(Uint8Array.of(23), u64(add)), accounts: [meta(signer, true, true), meta(order, false, true),
        meta(await k.ovPda(order), false, true), meta(src, false, true), meta(o.source, false, false), meta(o.mint, false, false),
        meta(await k.auth(), false, false), meta(o.tokenProgram, false, false), meta(await k.pause(), false, false)] };
    },

    // ---- the judges and the terms of an order (2.1) ----
    /** Funds a PRIVATE order from a Balance: fundOrderBalanceIx's accounts, and as data the order's scope
     *  (scopeOf(repoId, issue, salt)) and its 32-byte terms hash (bytes or hex each). The fund token is from fund.yml in
     *  the order's judge repository, with issue 0 and privateFundTerms(scope, termsHash) as its terms. */
    async fundPrivateOrderBalanceIx({ relayer, fundToken, key: keyAccount, balance, mint, ownerId, scope, termsHash: hash, used, seq = 0, tokenProgram = TOKEN }) {
      const order = await k.orderPda(scope, balance, seq);
      return { program: PAY, data: cat(Uint8Array.of(16), fromHex(scope), fromHex(hash)),
        accounts: [meta(relayer, true, true), meta(fundToken, false, false), meta(keyAccount, false, false), meta(balance, false, true),
          meta(await k.baltok(balance), false, true), meta(await k.balxPda(balance), false, true), meta(await k.planPda(ownerId), false, false),
          meta(order, false, true), meta(await k.ovPda(order), false, true), meta(await marker(used), false, true), meta(mint, false, false),
          meta(await k.auth(), false, false), meta(tokenProgram, false, false), meta(SYSTEM, false, false), meta(await k.pause(), false, false)] };
    },
    /** Binds an organisation's wallet. `orgId` is the token's repository_owner_id; the Bind is the account a person's
     *  is, k.bind(orgId): a payee id that is an organisation is then paid like any other. `used`: the token's marker. */
    bindOrgIx: async ({ relayer, bindToken, key: keyAccount, orgId, used }) => ({ program: PAY, data: Uint8Array.of(25),
      accounts: [meta(relayer, true, true), meta(bindToken, false, false), meta(keyAccount, false, false), meta(await k.bind(orgId), false, true),
        meta(SYSTEM, false, false), meta(await marker(used), false, true)] }),
    /** After the warranty, anyone: the holdback to the recorded wallets (their associated token accounts, created when
     *  missing), the tip to the relayer, the rest of the fee to FEE_OWNER. `hb` is readHoldback of k.hbPda(order). */
    async releaseIx({ relayer, order, o, hb, tipToken = null }) {
      const c = await k.orderCommon(relayer, order, o, tipToken), per = [];     // order ov tip fee auth rentTo mint tokenProgram system ataProgram
      for (const [, wallet] of hb.payees) per.push(meta(wallet, false, false), meta(await ata(wallet, o.mint, o.tokenProgram), false, true));
      return { program: PAY, data: Uint8Array.of(18), accounts: [meta(relayer, true, true), c[0], c[1], meta(await k.hbPda(order), false, true), c[2], c[3], c[4],
        c[5], meta(hb.payer, false, true), ...c.slice(6), ...per] };
    },
    /** Inside the warranty, on a revert token of one of the order's judges, a, b or c (revertAudience): everything the order
     *  holds back to its funder. `hb` is readHoldback of k.hbPda(order). `used`: the token's marker, as payIx takes it;
     *  the relayer pays its rent. */
    async revertIx({ relayer, revertToken, key: keyAccount, order, o, hb, used, refundToken = null }) {
      const dest = refundToken ?? (o.fromBalance ? o.refundTo : await ata(o.refundTo, o.mint, o.tokenProgram));
      return { program: PAY, data: Uint8Array.of(19), accounts: [meta(relayer, true, true), meta(revertToken, false, false), meta(keyAccount, false, false),
        meta(order, false, true), meta(await k.ovPda(order), false, true), meta(await k.hbPda(order), false, true), meta(dest, false, true),
        meta(await k.auth(), false, false), meta(o.rentTo, false, true), meta(hb.payer, false, true), meta(o.mint, false, false),
        meta(o.tokenProgram, false, false), meta(SYSTEM, false, false), meta(await marker(used), false, true)] };
    },
    /** Reserves an order for the taker a take token names (takeAudience). `used`: the token's marker, as payIx takes
     *  it; the relayer pays its rent. */
    reserveIx: async ({ relayer, takeToken, key: keyAccount, order, used }) => ({ program: PAY, data: Uint8Array.of(20),
      accounts: [meta(relayer, true, true), meta(takeToken, false, false), meta(keyAccount, false, false), meta(order, false, true),
        meta(SYSTEM, false, false), meta(await marker(used), false, true)] }),
    /** Gives notice: the deadline becomes min(deadline, now + NOTICE). A wallet's order: `signer` is the funding wallet.
     *  A Balance's order: anyone signs, `cancelToken` (with its `key`) carries cancelAudience(order), and `used` is that
     *  token's marker, as payIx takes it; the signer pays its rent. */
    async cancelIx({ signer, order, cancelToken = null, key: keyAccount = null, used = null }) {
      if (cancelToken && !keyAccount) throw new Error("a cancel token is read with its key: pass `key` too");
      const tok = cancelToken ? [meta(cancelToken, false, false), meta(keyAccount, false, false), meta(SYSTEM, false, false), meta(await marker(used), false, true)] : [];
      return { program: PAY, data: Uint8Array.of(21), accounts: [meta(signer, true, true), meta(order, false, true), ...tok] };
    },
    /** This order's payment for `payeeId` goes to the wallet `to`. `signer`: the payee's bound wallet the first time, the
     *  current assignee after that. */
    assignIx: async ({ signer, order, payeeId, to }) => ({ program: PAY, data: cat(Uint8Array.of(24), u64(payeeId), key(to)),
      accounts: [meta(signer, true, true), meta(order, false, false), meta(await k.bind(payeeId), false, false),
        meta(await k.assignPda(order, payeeId), false, true), meta(SYSTEM, false, false)] }),
    /** Closes a used marker (usedPda) once its time has passed, or the marker of a pull request (donePda) once its
     *  `order` is closed. `rentTo`: who paid the marker's rent (readMarker(...)[0]); it gets the rent back. */
    closeMarkerIx: ({ marker: account, rentTo, order = null }) => ({ program: PAY, data: Uint8Array.of(27),
      accounts: [meta(account, false, true), meta(rentTo, false, true), meta(order ?? SYSTEM, false, false)] }),

    /** What an instruction is, read back from its own bytes, for a person to check before signing: { program (a
     *  name), address, name, args, accounts: [{ name, pubkey, signer, writable }] }. Amounts are in the mint's
     *  smallest units. Knows knos-pay, a token transfer and the creation of a token account; anything else comes
     *  back named "unknown" with its data in hex. */
    explain(ix) {
      const d = ix.data, dv = view(d);
      const named = (names) => ix.accounts.map((a, i) => ({ name: names[i] ?? `account ${i}`, ...a }));
      const u = (o) => num(dv.getBigUint64(o, true));
      const four = (o) => [0, 1, 2, 3].map((s) => u(o + 8 * s)).filter((s) => s);
      const out = (program, name, args, names) => ({ program, address: ix.program, name, args, accounts: named(names) });
      const known = ix.program === PAY && d.length ? PAY_IXS.find((x) => x[2] === d[0]) : null;
      if (known) {
        const [name] = known;
        // a private order's funding carries its scope and the hash of its terms where a public one carries the terms (printable ASCII)
        const hidden = d.length === 65 && d.slice(1).some((b) => b < 0x20 || b > 0x7e);
        const args = name === "OpenBalance" ? { ownerId: u(1), cap: u(9), spenders: four(17) }
          : name === "SetBalance" ? { cap: u(1), spenders: four(9) }
          : name === "Withdraw" ? { amount: u(1) }
          : name === "FundBalance" ? { terms: ascii(d.slice(1)) }
          : name === "FundWallet" ? { repoId: u(1), issue: u(9), amount: u(17), workS: num(dv.getBigInt64(25, true)), mode: d[33],
            wfRepoHash: hex(d.slice(34, 66)), wfSha: ascii(d.slice(66, 106)), terms: ascii(d.slice(106)) }
          : name === "Pause" ? { seconds: dv.getUint32(1, true) }
          : name === "SetBalanceX" ? { dayLimit: u(1), totalLimit: u(9), repos: [0, 1, 2, 3, 4, 5, 6, 7].map((r) => u(17 + 8 * r)).filter((r) => r),
            wfSha: d.slice(81, 121).every((b) => !b) ? "" : ascii(d.slice(81, 121)) }
          : name === "SetPlan" ? { ownerId: u(1), feeBps: dv.getUint16(9, true), expires: num(dv.getBigInt64(11, true)) }
          : name === "FundOrderWallet" ? orderArgs(d, dv)
          : name === "FundOrderBalance" ? (hidden ? { scope: hex(d.slice(1, 33)), terms: hex(d.slice(33)) } : { terms: ascii(d.slice(1)) })
          : name === "Assign" ? { payeeId: u(1), to: b58(d.slice(9, 41)) }
          : name === "TopUp" ? { add: u(1) } : {};
        return out("knos-pay", name, args, accountNames(name, ix.accounts.length));
      }
      if ((ix.program === TOKEN || ix.program === TOKEN_2022) && d[0] === 12 && d.length === 10) {
        return out(ix.program === TOKEN ? "SPL Token" : "Token-2022", "TransferChecked", { amount: u(1), decimals: d[9] }, ["source", "mint", "destination", "owner"]);
      }
      if (ix.program === ATA_PROGRAM && d.length === 1 && d[0] === 1) {
        return out("Associated Token Account", "CreateIdempotent", {}, ["payer", "account", "owner", "mint", "systemProgram", "tokenProgram"]);
      }
      return out(ix.program === ids.knos_oidc ? "knos-oidc" : ix.program, "unknown", { data: hex(d) }, []);
    },
  };
  return k;
}

/** What a failed transaction's error means, in words, when knos-pay refused it: `err` as the cluster reports it
 *  ({ InstructionError: [index, { Custom: 93 }] }). null when it is not one of the program's own codes. */
function errorWords(err) {
  const custom = err?.InstructionError?.[1]?.Custom;
  return custom in ERRORS ? ERRORS[custom] : null;
}

export const v2 = Object.freeze({
  MERGE, TESTS, FEE_BPS, FEE_MIN, MIN_AMOUNT, MAX_AMOUNT: MAX_AMOUNT2, FAUCET_CAP: 100_000_000, MIN_WORK: 60, MAX_WORK: 90 * 86_400, HOLD, PAUSE_MAX: 7 * 86_400,
  FUND_PERIOD: 60, CLOCK_SLACK: 30, MAX_TERMS, TOKEN_AHEAD: 300, TOKEN_LIFE: 3600, JOB_LEN: 320, BALANCE_LEN: 160, BIND_LEN: 56, REP_LEN: 64,
  KEY_DELAY, KEY_TTL, K_HDR, KEY_TAIL, OTHER, PRIVATE, PRIVATE_FLAG, MAX_ISS, T_IHASH, ERRORS, PAY_IXS,
  BALX_LEN, PLAN_LEN, ORDER_LEN, OPTS_LEN, ORDER_FEE_MIN, FEE_TIER_1, FEE_TIER_2, FEE_BPS_2, FEE_BPS_3, ORDER_MIN_AMOUNT, TIP, TIP_FIRST, PLAN_BPS_MIN, MAX_HOLDBACK_BPS, MAX_WARRANTY_DAYS,
  MAX_KILL_BPS, MAX_PAYEES, F_FAUCET, F_PRIVATE, F_NEUTRAL, F_STANDING, F_TOKEN2022, COUNTED, HB_LEN, DONE_LEN, AS_LEN, USED_LEN, NOTICE, USED_KEEP, TOKEN_AT, MINTED,
  units, feeOf: feeOf2, termsJson, termsHash, wfRepoHash, funderKey, fundAudience: fundAudience2, namedBalance, payAudience: payAudience2, bindAudience, destination,
  orderFee, scopeOf, sigHash, opts, orderFundAudience, payeesText, orderPayAudience, payeesOf, orderDestination, planBps,
  privateFundTerms, ruleAudience, orgBindAudience, takeAudience, cancelAudience, revertAudience, payeeWallet, killFee, accountNames,
  readJob, readBalance, readBind, readRep, readPause, readRate, readOrder, readBalx, readPlan, readKey, tokenIssuer, readIss, keyAccountHash, keyUsable,
  readHoldback, readAssign, readMarker, spent, errorWords, client: client2,
});


// ---- the lines a program logged ---------------------------------------------------------------------------------------
const LOG = "Program log: ";
/** The lines programs logged in one transaction, without the "Program log: " the runtime puts before them; with
 *  `program`, only what that program itself logged. A program can log any text, so who is speaking is read from the
 *  runtime's own lines ("Program <id> invoke [depth]", "... success", "... failed: ..."), which no program can write. */
export function said(logs, program = null) {
  const out = [], stack = [];
  for (const line of logs || []) {
    const called = /^Program (\w+) invoke \[(\d+)\]$/.exec(line);
    if (called) stack.splice(Number(called[2]) - 1, stack.length, called[1]);
    else if (/^Program (\w+) (?:success|failed)/.test(line)) stack.pop();
    else if (line.startsWith(LOG) && (program === null || stack.at(-1) === program)) out.push(line.slice(LOG.length));
  }
  return out;
}

// ---- knos-meter (programs-v2/knos_meter): acceptance without escrow ---------------------------------------------------
const MICRO = 1_000_000, M_FEE = 50_000, M_PLAN_MIN = 20_000, FREE_PER_MONTH = 10_000, MIN_DECIMALS = 2, MAX_DECIMALS = 18;
const M_EXTENSIONS = Object.freeze([3, 4, 10, 18, 19, 20, 21, 22, 23, 25]);     // the only Token-2022 extensions a mint of credits may carry
const CREDITS_LEN = 168, M_PLAN_LEN = 40, MARK_LEN = 88, MONTH_LEN = 64;
const MARK_LEN_1 = 48;          // a mark written before CloseMark existed: no payer, it stays
const MARK_PAYER = 48;          // where a mark keeps the relayer that paid its rent (marksOf filters on it)
const MARK_GRACE = 7200;        // the longest life the meter takes of a token, and the hour the verifier allows past its expiry
const M_WORKFLOWS = Object.freeze(["attest.yml", "prove.yml"]), EVAL = "knosm:eval ", CLOSED = "knosm:closed ";
const LEDGER_LEN = 96, MAX_BATCH = 100_000;     // the batch mode (1.1): one Ledger account for a month, no account per evaluation
const M_ERRORS = {
  61: "the token's claims are not a JSON object", 62: "a claim the meter reads appears twice in the token", 63: "a claim the meter reads is missing from the token",
  76: ERRORS[76], 77: ERRORS[77],
  78: "the key that signed this token was revoked on chain, so the token counts nothing; run the workflow again for a token signed by another key",
  110: "a wrong account, or a missing signature",
  111: "the owner id, the workflow commit, the rate or the tier is outside what is allowed",
  112: "this is not a credits account, or the signer is not the wallet that opened it",
  113: "the token is not verified, not GitHub's, expired, or its times are not GitHub's; a new run gives a new one",
  114: "the token's claims do not allow this: the runner is not GitHub's, or this is a re-run; start a new run",
  115: "the token is not from attest.yml or prove.yml at the commit these credits pin; send OpenCredits again to pin another commit",
  116: "the token's audience is not a knosm:eval audience",
  117: "the run was not in a repository of the buyer its audience names, or these credits were prepaid for another owner",
  118: "the credits do not hold that much; add money with a transfer to the credits' token account and send this again",
  119: "this mint cannot be used: it is not Circle's USDC, not a mint of the token program passed, has fewer than 2 or more than 18 decimals, or carries an extension that is not on the list",
  120: "the fee account is not a token account of the credits' mint owned by the fee owner, or the destination is not the withdrawing wallet's",
  121: "only the fee owner sets a plan",
  122: "the key that signed this token is a private key, or of a kind the meter does not know: it counts nothing here",
  123: "this is not a mark that can be closed, or the signer is not the relayer that paid its rent; sign with the wallet the mark names",
  124: "this mark cannot be closed yet; send this again after the time the mark names (two hours into the month after the one it was counted in)",
  125: "this batch's seq is not the ledger's next one: the token was already taken, or an earlier batch is missing; read next_seq from the ledger account and send that batch",
  126: "a batch holds 1 to 100,000 evaluations, no more accepted than counted, for this month or the last one",
};

/** A rate (millionths of a whole unit) in the smallest units of a mint with these decimals, rounded down. */
const feeUnits = (rate, decimals) => num((BigInt(rate) * 10n ** BigInt(decimals)) / BigInt(MICRO));

/** The UTC calendar month of a unix time, as the program computes it from the chain's clock: 202610. */
function yyyymm(t) {
  const d = new Date(Math.max(Number(t), 0) * 1000);
  return d.getUTCFullYear() * 100 + d.getUTCMonth() + 1;
}

/** The first second of the UTC calendar month after the one `t` is in. */
function nextMonth(t) {
  const d = new Date(Math.max(Number(t), 0) * 1000);
  return Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + 1, 1) / 1000;
}

/** From when a mark recorded at `t` can be closed: its month has closed and no token issued in it is accepted. */
const closeAfter = (t) => nextMonth(t) + MARK_GRACE;

const hex32 = (v, what) => {
  const raw = fromHex(v);
  if (raw.length !== 32) throw new Error(`${what} is 32 bytes`);
  return raw;
};

/** What attest.yml or prove.yml asks GitHub to sign for one evaluation. `order` and `policy` are 32 bytes (bytes or hex:
 *  the work order and the policy it was judged under); `artifact` is a commit (40 hex characters); `verdict` 1 accepted,
 *  0 rejected; `rate` is what the seller bills for this outcome when it is accepted, in the smallest units of whatever
 *  the two settle in. */
function evalAudience(buyerId, sellerId, order, artifact, policy, milestone, verdict, rate) {
  const bad = fromHex(order).length !== 32 || fromHex(policy).length !== 32 || artifact.length !== 40 || !(milestone >= 0 && milestone < 2 ** 32);
  if (bad) throw new Error("an evaluation names a 32-byte work order, a 40-character commit, a 32-byte policy and a milestone below 2^32");
  return `knosm:eval:${buyerId}:${sellerId}:${hex(fromHex(order))}:${artifact}:${hex(fromHex(policy))}:${milestone}:${verdict ? 1 : 0}:${rate}`;
}

/** The fields of a knosm:eval audience: { buyerId, sellerId, order (hex), artifact, policy (hex), milestone, accepted, rate }. */
function parseAudience(audience) {
  const p = audience.split(":");
  if (p.length !== 10 || p[0] !== "knosm" || p[1] !== "eval" || (p[8] !== "0" && p[8] !== "1")) throw new Error("this is not a knosm:eval audience");
  return { buyerId: num(BigInt(p[2])), sellerId: num(BigInt(p[3])), order: p[4], artifact: p[5], policy: p[6], milestone: Number(p[7]), accepted: p[8] === "1",
    rate: num(BigInt(p[9])) };
}

/** What makes an evaluation billable once (with the buyer): sha256(work order || artifact || policy || milestone u32). */
const evalKey = (order, artifact, policy, milestone) => sha256(cat(fromHex(order), enc.encode(artifact), fromHex(policy), u32(milestone)));

/** Credits: money a wallet prepaid for the evaluations of one GitHub owner (the buyer), and the workflows that may spend it. */
function readCredits(raw) {
  if (!raw || raw.length !== CREDITS_LEN || raw[0] !== 1) return null;
  const dv = view(raw), u = (o) => num(dv.getBigUint64(o, true));
  return { tokenProgram: raw[2] === 1 ? TOKEN_2022 : TOKEN, decimals: raw[3], ownerId: u(8), authority: b58(raw.slice(16, 48)), mint: b58(raw.slice(48, 80)),
    spent: u(80), evaluations: u(88), wfRepoHash: hex(raw.slice(96, 128)), wfSha: ascii(raw.slice(128, 168)) };
}

/** The account at planPda(owner id); an owner with no account has no plan and has used nothing. */
function readMeterPlan(raw) {
  if (!raw || raw.length !== M_PLAN_LEN || raw[0] !== 1) return { tier: 0, month: 0, ownerId: 0, rate: 0, expiry: 0, used: 0 };
  const dv = view(raw);
  return { tier: raw[2], month: dv.getUint32(4, true), ownerId: num(dv.getBigUint64(8, true)), rate: num(dv.getBigUint64(16, true)),
    expiry: num(dv.getBigInt64(24, true)), used: num(dv.getBigUint64(32, true)) };
}

/** What a billable evaluation past the free ones costs at `now`, in millionths of a whole unit. */
const rateAt = (plan, now) => (plan.rate && now < plan.expiry ? plan.rate : M_FEE);
const usedIn = (plan, month) => (plan.month === month ? plan.used : 0);

/** null: this evaluation was never billed, or its mark was closed after its month. `payer`: the relayer that paid the
 *  mark's rent, the only one that closes it; `closeAfter`: the chain time from which it can. Both null for a mark
 *  written before CloseMark existed: it stays. */
function readMark(raw) {
  const now = raw && raw.length === MARK_LEN && raw[0] === 2, old = raw && raw.length === MARK_LEN_1 && raw[0] === 1;
  if (!now && !old) return null;
  const dv = view(raw), u = (o) => num(dv.getBigUint64(o, true));
  return { accepted: raw[1] === 1, month: dv.getUint32(4, true), buyerId: u(8), sellerId: u(16), time: num(dv.getBigInt64(24, true)), rate: u(32), fee: u(40),
    payer: now ? b58(raw.slice(MARK_PAYER, MARK_PAYER + 32)) : null, closeAfter: now ? num(dv.getBigInt64(80, true)) : null };
}

/** The marks of marksOf that CloseMark takes at `now` (the chain's clock): their addresses. `marks`: [address, mark]. */
const closable = (marks, now) => marks.filter(([, mark]) => mark.closeAfter !== null && now >= mark.closeAfter).map(([address]) => address);

/** One buyer, one seller, one month: billable evaluations, how many were accepted and rejected, the declared value (the
 *  sum of `rate` over the accepted) and what they cost in credits. Zeros when nothing was recorded. */
function readMonth(raw, buyerId = 0, sellerId = 0, month = 0) {
  if (!raw || raw.length !== MONTH_LEN || raw[0] !== 1) return { buyerId, sellerId, month, evaluations: 0, accepted: 0, rejected: 0, value: 0, fees: 0 };
  const dv = view(raw), u = (o) => num(dv.getBigUint64(o, true));
  return { buyerId: u(8), sellerId: u(16), month: dv.getUint32(4, true), evaluations: u(24), accepted: u(32), rejected: u(40), value: u(48), fees: u(56) };
}

// ---- the batch mode (knos-meter 1.1): one signed token counts a whole batch; the Ledger keeps totals and a running hash ----
/** What the buyer's run (`kind` "batch") or the seller's (`kind` "claim") asks GitHub to sign for one batch: the month
 *  (yyyymm), the ledger's next seq, how many evaluations, how many of them accepted, their declared value, and the
 *  Merkle root of their keys (32 bytes, or hex; merkleRoot gives it). */
function batchAudience(buyerId, sellerId, month, seq, count, accepted, value, root, kind = "batch") {
  if (kind !== "batch" && kind !== "claim") throw new Error("a batch is the buyer's (\"batch\") or the seller's own count (\"claim\")");
  return `knosm:${kind}:${buyerId}:${sellerId}:${month}:${seq}:${count}:${accepted}:${value}:${hex(hex32(root, "a batch's root"))}`;
}

/** The fields of a knosm:batch or knosm:claim audience: { claim, buyerId, sellerId, month, seq, count, accepted, value, root (hex) }. */
function parseBatch(audience) {
  const p = audience.split(":");
  if (p.length !== 10 || p[0] !== "knosm" || (p[1] !== "batch" && p[1] !== "claim") || !/^[0-9a-f]{64}$/.test(p[9])) throw new Error("this is not a knosm:batch or knosm:claim audience");
  const n = (at) => num(BigInt(p[at]));
  return { claim: p[1] === "claim", buyerId: n(2), sellerId: n(3), month: Number(p[4]), seq: n(5), count: n(6), accepted: n(7), value: n(8), root: p[9] };
}

/** The root both sides compute for one batch and the program stores: RFC 6962 over the evaluation keys (evalKey's
 *  bytes, or hex), sorted ascending, none repeated: a leaf is sha256(0x00 || key), a node sha256(0x01 || left || right). */
async function merkleRoot(keys) {
  const ids = keys.map((id) => hex32(id, "an evaluation key")), ordered = ids.every((id, at) => !at || hex(ids[at - 1]) < hex(id));
  if (!ids.length || !ordered) throw new Error("a batch's keys are sorted ascending, none repeated, and there is at least one");
  const tree = async (leaves) => {
    if (leaves.length === 1) return sha256(cat(Uint8Array.of(0), leaves[0]));
    let half = 1;
    while (half * 2 < leaves.length) half *= 2;       // the largest power of two below the number of leaves
    return sha256(cat(Uint8Array.of(1), await tree(leaves.slice(0, half)), await tree(leaves.slice(half))));
  };
  return tree(ids);
}

/** A ledger's running hash after one more batch: sha256(before || root || seq || count || accepted || value), the four
 *  numbers as u64 LE. A new ledger starts from 32 zero bytes. Recompute it over every batch of an off-chain ledger and
 *  compare with readLedger(...).chain. */
const chainHash = (before, root, seq, count, accepted, value) =>
  sha256(cat(hex32(before, "a ledger's hash"), hex32(root, "a batch's root"), u64(seq), u64(count), u64(accepted), u64(value)));

/** The Ledger of one buyer, one seller and one month (ledgerPda): { claim (false: the buyer's count, which is billed;
 *  true: the seller's own), month, buyerId, sellerId, nextSeq, evaluations, accepted, value, fees, chain (hex) }. null
 *  when no batch was recorded. A buyer's ledger and a seller's that differ are two different counts of the same month. */
function readLedger(raw) {
  if (!raw || raw.length !== LEDGER_LEN || raw[0] !== 1) return null;
  const dv = view(raw), u = (o) => num(dv.getBigUint64(o, true));
  return { claim: raw[2] === 1, month: dv.getUint32(4, true), buyerId: u(8), sellerId: u(16), nextSeq: u(24), evaluations: u(32), accepted: u(40), value: u(48),
    fees: u(56), chain: hex(raw.slice(64, 96)) };
}

/** What the next billable evaluation of this owner costs at `now`, in the mint's smallest units. */
const meterQuote = (plan, decimals, now) => (usedIn(plan, yyyymm(now)) < FREE_PER_MONTH ? 0 : feeUnits(rateAt(plan, now), decimals));

/** The fields of a `knosm:eval` log line (strings); null for any other line. */
function parseEval(line) {
  if (!line.startsWith(EVAL)) return null;
  return Object.fromEntries(line.slice(EVAL.length).split(" ").filter((part) => part.includes("=")).map((part) => [part.slice(0, part.indexOf("=")), part.slice(part.indexOf("=") + 1)]));
}

/** The month of one buyer and one seller, recomputed from the program's own log lines: every transaction that named
 *  the month's account is read (`ledger.history`, `ledger.logs`: an array or an async iterable of signatures; the
 *  lines of one transaction), and only what the meter itself logged in it counts. It equals readMonth of the account
 *  while the cluster still has the transactions; a difference means the node's history is cut short, and the account is
 *  the count. `program`: the meter's address. */
async function meterStatement(ledger, buyerId, sellerId, month, program, most = 100_000) {
  const out = { buyerId, sellerId, month, evaluations: 0, accepted: 0, rejected: 0, value: 0, fees: 0 }, seen = new Set();
  for await (const sig of await ledger.history(await meterClient(program).monthPda(buyerId, sellerId, month), most)) {
    for (const line of said(await ledger.logs(sig), program)) {
      const e = parseEval(line);
      if (!e || e.buyer !== String(buyerId) || e.seller !== String(sellerId) || e.month !== String(month)) continue;
      const id = [e.order, e.artifact, e.policy, e.milestone].join(" ");
      if (seen.has(id)) continue;      // the program bills an evaluation once; a node that repeats a row does not make two
      seen.add(id);
      const ok = e.verdict === "1";
      out.evaluations += 1; out.accepted += ok ? 1 : 0; out.rejected += ok ? 0 : 1;
      out.value += ok ? Number(e.rate) : 0; out.fees += Number(e.fee);
    }
  }
  return out;
}

/** The meter at one program id (src/knos/settle/v2/program_ids.json: knos_meter): its addresses and instructions. */
function meterClient(program) {
  const pda = async (...seeds) => (await findProgramAddress(seeds, program))[0];
  const tag = (s) => enc.encode(s);
  const k = {
    program,
    /** The owner of every credits token account. Only the program signs for it. */
    auth: () => pda(tag("auth")),
    /** The credits a wallet (`authority`) prepaid for the evaluations of the GitHub owner `ownerId`, in one mint. */
    creditsPda: (ownerId, authority, mint) => pda(tag("cr"), u64(ownerId), key(authority), key(mint)),
    /** A credits account's token account. Add money with a plain token transfer to this address (depositIx). */
    crtokPda: (credits) => pda(tag("crtok"), key(credits)),
    /** An owner's rate under a contract and its count of billable evaluations this month. */
    planPda: (ownerId) => pda(tag("plan"), u64(ownerId)),
    /** Exists once this evaluation of this buyer was billed. `evalKey` is evalKey(...)'s bytes (or hex). */
    markPda: (buyerId, evalKey) => pda(tag("k"), u64(buyerId), fromHex(evalKey)),
    /** The count of one buyer and one seller in one month (`month` is yyyymm, as yyyymm(unix time) gives it). */
    monthPda: (buyerId, sellerId, month) => pda(tag("m"), u64(buyerId), u64(sellerId), u32(month)),

    /** Opens `authority`'s credits for the evaluations of the GitHub owner `ownerId` (the buyer), and pins the workflows
     *  whose runs may spend them: attest.yml and prove.yml of the repository `wfRepo` ("owner/name") at the commit
     *  `wfSha`. Sent again by the same wallet, it only sets a new pin. */
    async openCreditsIx({ authority, ownerId, mint, wfRepo, wfSha, tokenProgram = TOKEN }) {
      if (wfSha.length !== 40) throw new Error("the workflows are pinned by a full commit: 40 hex characters");
      const credits = await k.creditsPda(ownerId, authority, mint);
      return { program, data: cat(Uint8Array.of(0), u64(ownerId), await wfRepoHash(wfRepo), enc.encode(wfSha)),
        accounts: [meta(authority, true, true), meta(credits, false, true), meta(await k.crtokPda(credits), false, true), meta(mint, false, false),
          meta(await k.auth(), false, false), meta(tokenProgram, false, false), meta(SYSTEM, false, false)] };
    },
    /** Adds money to credits: a plain TransferChecked of the token program, from `source` (a token account `owner` signs
     *  for) to the credits' token account. The meter is not called. */
    async depositIx({ source, owner, credits, mint, amount, decimals, tokenProgram = TOKEN }) {
      return transferCheckedIx(source, mint, await k.crtokPda(credits), owner, amount, decimals, tokenProgram);
    },
    /** Unspent credits back to the wallet that opened them. `amount` 0: everything. */
    async withdrawCreditsIx({ authority, credits, mint, amount = 0, destToken = null, tokenProgram = TOKEN }) {
      return { program, data: cat(Uint8Array.of(1), u64(amount)),
        accounts: [meta(authority, true, false), meta(credits, false, false), meta(await k.crtokPda(credits), false, true),
          meta(destToken ?? await ata(authority, mint, tokenProgram), false, true), meta(mint, false, false), meta(await k.auth(), false, false),
          meta(tokenProgram, false, false)] };
    },
    /** FEE_OWNER sets one owner's rate (millionths of a whole unit, 20000..=50000) until `expiry` (unix time). */
    async setPlanIx({ feeOwner, payer, ownerId, tier, rate, expiry }) {
      return { program, data: cat(Uint8Array.of(2), u64(ownerId), Uint8Array.of(tier), u64(rate), i64(expiry)),
        accounts: [meta(feeOwner, true, false), meta(payer, true, true), meta(await k.planPda(ownerId), false, true), meta(SYSTEM, false, false)] };
    },
    /** Records the evaluation a verified token describes. `key` is the verifier's account of the key that verified it;
     *  `c` is readCredits of `credits`; `audience` is the token's; `now` is the chain's clock (chainTime), which decides
     *  the month. `feeToken`: a token account of the credits' mint owned by FEE_OWNER (default: its associated token
     *  account; create it with createAtaIx before the first evaluation that costs something). */
    async recordIx({ relayer, token, key: keyAccount, credits, c, audience, now, feeToken = null }) {
      const e = parseAudience(audience);
      return { program, data: Uint8Array.of(3), accounts: [meta(relayer, true, true), meta(token, false, false), meta(keyAccount, false, false),
        meta(credits, false, true), meta(await k.crtokPda(credits), false, true), meta(await k.planPda(e.buyerId), false, true),
        meta(await k.markPda(e.buyerId, await evalKey(e.order, e.artifact, e.policy, e.milestone)), false, true),
        meta(await k.monthPda(e.buyerId, e.sellerId, yyyymm(now)), false, true), meta(feeToken ?? await ata(FEE_OWNER, c.mint, c.tokenProgram), false, true),
        meta(c.mint, false, false), meta(await k.auth(), false, false), meta(c.tokenProgram, false, false), meta(SYSTEM, false, false)] };
    },
    /** The batch ledger of one buyer and one seller in one month: the buyer's count, or (`claim`) the seller's own. */
    ledgerPda: (buyerId, sellerId, month, claim = false) => pda(tag(claim ? "lc" : "l"), u64(buyerId), u64(sellerId), u32(month)),
    /** Records the batch a verified token describes (batchAudience): no account per evaluation, the totals and the
     *  running hash go to the buyer's Ledger. The token is taken once: its seq must be the ledger's nextSeq (error
     *  125). The fee is count x rate beyond the month's free ones, from `credits`, refused whole when they cannot pay.
     *  `c` is readCredits of `credits`; `feeToken` as recordIx takes it. */
    async recordBatchIx({ relayer, token, key: keyAccount, credits, c, audience, feeToken = null }) {
      const b = parseBatch(audience);
      if (b.claim) throw new Error("a knosm:claim audience is the seller's own count: send it with claimBatchIx");
      return { program, data: Uint8Array.of(5), accounts: [meta(relayer, true, true), meta(token, false, false), meta(keyAccount, false, false),
        meta(credits, false, true), meta(await k.crtokPda(credits), false, true), meta(await k.planPda(b.buyerId), false, true),
        meta(await k.ledgerPda(b.buyerId, b.sellerId, b.month), false, true), meta(feeToken ?? await ata(FEE_OWNER, c.mint, c.tokenProgram), false, true),
        meta(c.mint, false, false), meta(await k.auth(), false, false), meta(c.tokenProgram, false, false), meta(SYSTEM, false, false)] };
    },
    /** The seller's own count of a batch, from a token of a repository the seller owns (batchAudience with "claim"):
     *  the same shape, in the seller's Ledger (ledgerPda(..., true)). No fee and no credits. */
    async claimBatchIx({ relayer, token, key: keyAccount, audience }) {
      const b = parseBatch(audience);
      if (!b.claim) throw new Error("a knosm:batch audience is the buyer's count: send it with recordBatchIx");
      return { program, data: Uint8Array.of(6), accounts: [meta(relayer, true, true), meta(token, false, false), meta(keyAccount, false, false),
        meta(await k.ledgerPda(b.buyerId, b.sellerId, b.month, true), false, true), meta(SYSTEM, false, false)] };
    },
    /** The 1.1 build logs its version when this is simulated; a 1.0 build refuses the instruction. */
    versionIx: () => ({ program, data: Uint8Array.of(7), accounts: [] }),
    /** The relayer that paid a mark's rent takes all of it back and the mark is gone. `payer` signs and is the wallet
     *  the mark names; `mark` is markPda(buyer id, key) or an address from marksOf. Refused before the mark's
     *  closeAfter (error 124). Several fit in one transaction: one signature closes them all. */
    closeMarkIx: ({ payer, mark }) => ({ program, data: Uint8Array.of(4), accounts: [meta(payer, true, true), meta(mark, false, true)] }),
    /** Every mark whose rent `payer` put up: [address, mark], from one getProgramAccounts of the RPC endpoint `url`,
     *  filtered by length and payer. */
    async marksOf(url, payer) {
      const found = await programAccounts(url, program, MARK_LEN, MARK_PAYER, key(payer));
      return found.map(({ address, data }) => [address, readMark(data)]).filter(([, mark]) => mark);
    },
  };
  return k;
}

export const meter = Object.freeze({
  MICRO, FEE: M_FEE, PLAN_MIN: M_PLAN_MIN, FREE_PER_MONTH, MIN_DECIMALS, MAX_DECIMALS, EXTENSIONS: M_EXTENSIONS, CREDITS_LEN, PLAN_LEN: M_PLAN_LEN, MARK_LEN, MONTH_LEN,
  MARK_LEN_1, MARK_PAYER, MARK_GRACE, CLOSED, LEDGER_LEN, MAX_BATCH, batchAudience, parseBatch, merkleRoot, chainHash, readLedger, WORKFLOWS: M_WORKFLOWS, EVAL, ERRORS: M_ERRORS, feeUnits, yyyymm, nextMonth, closeAfter, closable, evalAudience, parseAudience, evalKey, readCredits, readPlan: readMeterPlan, rateAt, usedIn,
  readMark, readMonth, quote: meterQuote, parseEval, statement: meterStatement, client: meterClient,
});

// ---- an unsigned legacy transaction, for a wallet to sign and send -------------------------------------------------
function shortvec(n) {
  const out = [];
  for (;;) { const b = n & 0x7f; n >>= 7; if (n) out.push(b | 0x80); else { out.push(b); return Uint8Array.from(out); } }
}

function byBytes(a, b) {
  for (let i = 0; i < 32; i++) if (a.raw[i] !== b.raw[i]) return a.raw[i] - b.raw[i];
  return 0;
}

/** Every account of a set of instructions once: the fee payer first, then the other signers, then the rest; in each
 *  group the writable ones first, in the order of their bytes, as the Solana SDK compiles it. */
function compileAccounts(ixs, payer) {
  const seen = new Map();     // pubkey -> { signer, writable }
  const note = (pubkey, signer, writable) => {
    const have = seen.get(pubkey) || { raw: key(pubkey), signer: false, writable: false };
    seen.set(pubkey, { raw: have.raw, signer: have.signer || signer, writable: have.writable || writable });
  };
  for (const ix of ixs) {
    note(ix.program, false, false);
    for (const a of ix.accounts) note(a.pubkey, a.signer, a.writable);
  }
  seen.delete(payer);
  const rest = [...seen.entries()].map(([pubkey, v]) => ({ pubkey, ...v })).sort(byBytes);
  const group = (signer, writable) => rest.filter((a) => a.signer === signer && a.writable === writable);
  const keys = [{ pubkey: payer, raw: key(payer), signer: true, writable: true }, ...group(true, true), ...group(true, false),
    ...group(false, true), ...group(false, false)];
  const count = (f) => keys.filter(f).length;
  const header = Uint8Array.of(count((a) => a.signer), count((a) => a.signer && !a.writable), count((a) => !a.signer && !a.writable));
  return { keys, names: keys.map((a) => a.pubkey), header };
}

/** The legacy message of a transaction: the header, every account once, the recent blockhash, and the instructions by index. */
export function serializeMessage(ixs, payer, recentBlockhash) {
  const { keys, names, header } = compileAccounts(ixs, payer);
  if (keys.length > 255) throw new Error("too many accounts for one transaction");
  const body = ixs.map((ix) => cat(Uint8Array.of(names.indexOf(ix.program)), shortvec(ix.accounts.length),
    Uint8Array.from(ix.accounts.map((a) => names.indexOf(a.pubkey))), shortvec(ix.data.length), ix.data));
  return cat(header, shortvec(keys.length), ...keys.map((a) => a.raw), key(recentBlockhash), shortvec(ixs.length), ...body);
}

/** The unsigned transaction: one empty signature for each signer, then the message. At most 1232 bytes fit. */
export function serializeTx(ixs, payer, recentBlockhash) {
  const message = serializeMessage(ixs, payer, recentBlockhash);
  return cat(shortvec(message[0]), new Uint8Array(64 * message[0]), message);
}

/** The message inside a transaction serializeTx made (the part that is signed). */
export function messageOf(tx) {
  const signatures = tx[0];        // one byte: a transaction never has 128 signers
  return tx.slice(1 + 64 * signatures);
}

// ---- wallets: ask an injected wallet to sign and send ---------------------------------------------------------------
const registries = new WeakMap();     // window -> the wallets that registered through the Wallet Standard

// The Wallet Standard's handshake, both ways round: a wallet announces itself with a "register-wallet" event whose
// detail is a function that takes our { register }, and listens for our "app-ready" event, whose detail is that
// same { register }. So a wallet is found whether it loaded before this page's script or after.
function standardWallets(win) {
  if (!registries.has(win)) {
    const found = [];
    registries.set(win, found);
    const api = Object.freeze({ register: (...list) => { for (const w of list) if (!found.includes(w)) found.push(w); return () => {}; } });
    try {
      win.addEventListener("wallet-standard:register-wallet", (ev) => ev.detail(api));
      win.dispatchEvent(new win.CustomEvent("wallet-standard:app-ready", { detail: api }));
    } catch { /* no events here: not a browser window */ }
  }
  return registries.get(win).filter((w) => (w.chains || []).some((c) => c.startsWith("solana:"))
    && w.features?.["standard:connect"] && w.features?.["solana:signAndSendTransaction"]);
}

const text = (v) => (typeof v === "string" ? v : v?.toBase58 ? v.toBase58() : String(v));
const signatureOf = (got) => {
  const s = got?.signature ?? got;
  return typeof s === "string" ? s : b58(s);
};

/** The wallets this page can ask, in the order it prefers them: every wallet that registered through the Wallet
 *  Standard and can sign and send on Solana, then Phantom's and Solflare's own injected providers when they did not
 *  register that way. Each is { name, kind, connect(), signAndSend(tx, chain) }:
 *
 *    connect()                 asks the wallet for an account; resolves to its address
 *    signAndSend(tx, chain)    `tx` is serializeTx's bytes; the wallet shows it, signs and sends it; resolves to the
 *                              transaction's signature (base58). `chain`: "solana:devnet" or "solana:mainnet". An
 *                              injected provider sends to the network the wallet itself is set to.
 *
 *  Call it once when the page loads (wallets that load later are then heard) and again when the person asks to connect. */
export function wallets(win = globalThis.window) {
  if (!win) return [];
  const out = standardWallets(win).map((w) => {
    let account = null;
    return { name: w.name, kind: "standard", icon: w.icon,
      async connect(chain = "solana:devnet") {
        const got = await w.features["standard:connect"].connect();
        const accounts = got?.accounts?.length ? got.accounts : w.accounts || [];
        if (!accounts.length) throw new Error(`${w.name} shared no account.`);
        // a wallet or an account that lists its chains and not this one cannot sign for it: said now, not after a prompt
        const net = chain.replace("solana:", "");
        account = (w.chains || []).includes(chain) ? accounts.find((a) => !a.chains?.length || a.chains.includes(chain)) : null;
        if (!account) throw new Error(`${w.name} has no ${net} account to share. Set it to ${net} and connect again.`);
        return account.address;
      },
      async signAndSend(tx, chain = "solana:devnet") {
        if (!account) await this.connect(chain);
        const [got] = await w.features["solana:signAndSendTransaction"].signAndSendTransaction({ account, transaction: tx, chain });
        return signatureOf(got);
      } };
  });
  const has = (name) => out.some((w) => w.name.toLowerCase().includes(name));
  const phantom = win.phantom?.solana?.isPhantom ? win.phantom.solana : win.solana?.isPhantom ? win.solana : null;
  if (phantom && !has("phantom")) {
    out.push({ name: "Phantom", kind: "phantom",
      connect: async () => text((await phantom.connect())?.publicKey ?? phantom.publicKey),
      // Phantom's own request takes the message in base58 and needs no transaction object
      signAndSend: async (tx) => signatureOf(await phantom.request({ method: "signAndSendTransaction", params: { message: b58(messageOf(tx)) } })) });
  }
  const solflare = win.solflare?.isSolflare ? win.solflare : null;
  if (solflare && !has("solflare")) {
    out.push({ name: "Solflare", kind: "solflare",
      async connect() { await solflare.connect(); return text(solflare.publicKey); },
      // Solflare's provider serialises what it is given: an object that answers serialize() with the wire bytes
      signAndSend: async (tx) => signatureOf(await solflare.signAndSendTransaction({ serialize: () => tx, serializeMessage: () => messageOf(tx),
        signatures: [] })) });
  }
  return out;
}

// ---- JSON-RPC ------------------------------------------------------------------------------------------------------
export async function rpc(url, method, params) {
  // A public endpoint rate-limits: HTTP 429, or an error of code 429 in the body. That says nothing about the request
  // (it was not served), so it is waited out and asked again, as the Python client's chain.call does; anything else is
  // the answer. Without this a client that has just sent a transaction can stop before it knows the transaction landed.
  for (const wait of [1000, 2000, 4000, 8000, null]) {
    const r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ jsonrpc: "2.0", id: 1, method, params }) });
    const j = r.status === 429 ? await r.json().catch(() => ({ error: { code: 429, message: "Too Many Requests" } })) : await r.json();
    if ((r.status === 429 || j?.error?.code === 429) && wait !== null) { await new Promise((ok) => setTimeout(ok, wait)); continue; }
    if (j.error) throw new Error(j.error.message || "RPC error");
    return j.result;
  }
}

const fromB64 = (s) => Uint8Array.from(atob(s), (c) => c.charCodeAt(0));

/** An account's data, or null when it does not exist. */
export async function account(url, address) {
  const got = await rpc(url, "getAccountInfo", [address, { encoding: "base64", commitment: "confirmed" }]);
  return got.value ? fromB64(got.value.data[0]) : null;
}

/** An account's { owner, data, lamports }, or null when it does not exist. */
export async function accountInfo(url, address) {
  const got = await rpc(url, "getAccountInfo", [address, { encoding: "base64", commitment: "confirmed" }]);
  return got.value ? { owner: got.value.owner, data: fromB64(got.value.data[0]), lamports: got.value.lamports } : null;
}

/** Several accounts in one call: [{ owner, data, lamports } or null], in the order asked. */
export async function accounts(url, addresses) {
  const got = await rpc(url, "getMultipleAccounts", [addresses, { encoding: "base64", commitment: "confirmed" }]);
  return got.value.map((v) => (v ? { owner: v.owner, data: fromB64(v.data[0]), lamports: v.lamports } : null));
}

/** The chain's clock: the time of the latest confirmed block (what the programs see), never the local clock. */
export async function chainTime(url) {
  const slot = await rpc(url, "getSlot", [{ commitment: "confirmed" }]);
  for (const s of [slot, slot - 1, slot - 2]) {
    const t = await rpc(url, "getBlockTime", [s]).catch(() => null);
    if (t) return t;
  }
  throw new Error("the cluster gave no block time");
}

/** Every account of `program` with this size whose bytes at `offset` equal `bytes`: [{ address, data }]. */
export async function programAccounts(url, program, size, offset = null, bytes = null) {
  const filters = [{ dataSize: size }];
  if (bytes) filters.push({ memcmp: { offset, bytes: b58(bytes) } });
  const got = await rpc(url, "getProgramAccounts", [program, { encoding: "base64", commitment: "confirmed", filters }]);
  return (got || []).map((x) => ({ address: x.pubkey, data: fromB64(x.account.data[0]) }));
}

/** Waits until the cluster has confirmed a transaction: { ok, err } (err as the cluster reports it), or null when
 *  it was not seen within `seconds`. */
export async function confirmed(url, signature, seconds = 60, pause = (ms) => new Promise((r) => setTimeout(r, ms))) {
  for (let waited = 0; waited < seconds * 1000; waited += 1500) {
    const got = (await rpc(url, "getSignatureStatuses", [[signature], { searchTransactionHistory: true }])).value[0];
    if (got && (got.err || got.confirmationStatus === "confirmed" || got.confirmationStatus === "finalized")) return { ok: !got.err, err: got.err || null };
    await pause(1500);
  }
  return null;
}

export { u64 as u64le };

// ---- the v1 transaction (SIMD-0385) -----------------------------------------------------------------------------------
// Up to 4,096 bytes (a legacy transaction takes 1,232), at most 64 accounts, 12 signers and 64 instructions, no
// lookup tables. The compute budget is part of the message, so no compute budget instruction is sent.
export const V1_PREFIX = 0x81, V1_MAX_SIZE = 4096, V1_MAX_ACCOUNTS = 64, V1_MAX_SIGNATURES = 12, V1_MAX_INSTRUCTIONS = 64;
export const V1_HEAP = { min: 32_768, max: 262_144 };

/** The v1 message of a transaction: 0x81, the header, which settings follow, the recent blockhash, the numbers of
 *  instructions and accounts, the accounts (ordered as the legacy message orders them), the settings, each
 *  instruction's header (program, number of accounts, length of data), then each instruction's account indexes and data.
 *  `config`: { computeUnitLimit (required: an unset limit is zero units), priorityFee (micro-lamports), loadedAccountsDataSizeLimit,
 *  heapSize } */
export function serializeMessageV1(ixs, payer, recentBlockhash, config = {}) {
  const { computeUnitLimit, priorityFee, loadedAccountsDataSizeLimit, heapSize } = config;
  if (!(computeUnitLimit > 0)) throw new Error("a v1 transaction carries its own compute limit: pass config.computeUnitLimit (an unset limit is zero units)");
  if (heapSize !== undefined && !(heapSize >= V1_HEAP.min && heapSize <= V1_HEAP.max)) throw new Error(`the heap is ${V1_HEAP.min} to ${V1_HEAP.max} bytes`);
  const { keys, names, header } = compileAccounts(ixs, payer);
  if (keys.length > V1_MAX_ACCOUNTS) throw new Error(`a v1 transaction names at most ${V1_MAX_ACCOUNTS} accounts; this one names ${keys.length}`);
  if (header[0] > V1_MAX_SIGNATURES) throw new Error(`a v1 transaction has at most ${V1_MAX_SIGNATURES} signers`);
  if (ixs.length > V1_MAX_INSTRUCTIONS) throw new Error(`a v1 transaction has at most ${V1_MAX_INSTRUCTIONS} instructions`);
  const mask = (priorityFee !== undefined ? 3 : 0) | 4 | (loadedAccountsDataSizeLimit !== undefined ? 8 : 0) | (heapSize !== undefined ? 16 : 0);
  const values = cat(...(priorityFee !== undefined ? [u64(priorityFee)] : []), u32(computeUnitLimit),
    ...(loadedAccountsDataSizeLimit !== undefined ? [u32(loadedAccountsDataSizeLimit)] : []), ...(heapSize !== undefined ? [u32(heapSize)] : []));
  for (const ix of ixs) if (ix.data.length > 0xffff || ix.accounts.length > 255) throw new Error("an instruction of a v1 transaction has at most 255 accounts and 65,535 bytes of data");
  const heads = ixs.map((ix) => cat(Uint8Array.of(names.indexOf(ix.program), ix.accounts.length), Uint8Array.of(ix.data.length & 255, ix.data.length >> 8)));
  const bodies = ixs.map((ix) => cat(Uint8Array.from(ix.accounts.map((a) => names.indexOf(a.pubkey))), ix.data));
  return cat(Uint8Array.of(V1_PREFIX), header, u32(mask), key(recentBlockhash), Uint8Array.of(ixs.length, keys.length), ...keys.map((a) => a.raw), values, ...heads, ...bodies);
}

/** The unsigned v1 transaction: the message, then one empty signature for each signer. At most 4,096 bytes fit. */
export function serializeTxV1(ixs, payer, recentBlockhash, config = {}) {
  const message = serializeMessageV1(ixs, payer, recentBlockhash, config);
  const tx = cat(message, new Uint8Array(64 * message[1]));
  if (tx.length > V1_MAX_SIZE) throw new Error(`the transaction is ${tx.length} bytes; a v1 transaction takes at most ${V1_MAX_SIZE}`);
  return tx;
}

/** The message inside a transaction serializeTxV1 made (the part that is signed). */
export const messageOfV1 = (tx) => tx.slice(0, tx.length - 64 * tx[1]);
