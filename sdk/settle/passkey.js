// Knos passkey wallet, in JavaScript: a wallet whose only key is a WebAuthn passkey (knos-passkey, programs-v2).
// One file, no dependency, nothing imported: it runs as is in a browser and in Node 20+. Everything but `create`
// and `sign` is a pure function; those two take the browser's navigator.credentials (or a stand-in).
// The Python client (src/knos/settle/v2/passkey.py) is the authority; sdk/settle/passkey.test.mjs checks this file
// against the bytes it built (sdk/settle/passkey.fixtures.json, from scripts/passkey_fixtures.py), which
// tests/test_passkey_chain.py runs on chain.
//
//   import * as passkey from "./passkey.js";
//   const made = await passkey.create({ rpId: location.hostname, rpName: "Knos", userName: "octocat" });
//   made.wallet                         // the address to be paid at; keep made.credentialId and made.key
//   // later, to withdraw `amount` of `mint` to the token account `to` (passkey.ata(owner, mint) for a wallet address):
//   const nonce = (passkey.readWallet(accountBytes)?.nonce ?? 0) + 1;
//   const challenge = await passkey.challenge(made.wallet, mint, to, amount, nonce);
//   const assertion = await passkey.sign(challenge, { rpId: location.hostname, credentialId: made.credentialId });
//   const ixs = [await passkey.openIx(payer, made.key),                 // only while the wallet account does not exist
//                await passkey.createAtaIx(payer, owner, mint),          // only while `to` does not exist
//                ...await passkey.withdrawIxs({ key: made.key, mint, to, amount, nonce, assertion })];
//   // anyone may be `payer` and send them: the two instructions of withdrawIxs stay adjacent, in that order.
//
// An instruction is { program, data: Uint8Array, accounts: [{ pubkey, signer, writable }] } with base58 addresses,
// as in index.js, whose serializeTx takes them.

export const PASSKEY = "FQPX9i5kQxLYKZyyPgM2fVK9am3w1LSk1Cuoer1sSY85";      // knos_passkey in program_ids.json
export const SECP256R1 = "Secp256r1SigVerify1111111111111111111111111";    // Solana's P-256 precompile (SIMD-0075)
export const INSTRUCTIONS = "Sysvar1nstructions1111111111111111111111111";
export const TOKEN = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA";
export const TOKEN_2022 = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb";
export const ATA_PROGRAM = "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL";
export const SYSTEM = "11111111111111111111111111111111";
export const WALLET_LEN = 48;
export const N = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551n;   // the order of P-256
export const ERRORS = {
  110: "a wrong account in the instruction",
  111: "that is not a compressed P-256 public key (33 bytes starting with 02 or 03)",
  112: "that account is not a passkey wallet; open it first",
  113: "the instruction right before Withdraw must be the secp256r1 check of this passkey's signature, with everything in its own data",
  114: "the signature is another passkey's, not this wallet's",
  115: "the signed message is not this authenticator data followed by the hash of this client data",
  116: "the authenticator did not report that a person was present; sign again and confirm on the device",
  117: "the client data is not that of a passkey signature (type webauthn.get, with a challenge)",
  118: "the passkey signed for another withdrawal: the wallet, the mint, the destination, the amount or the nonce differs; sign again for this one",
  119: "the nonce is not the wallet's nonce plus one: this withdrawal was sent already, or another came first; read the wallet and sign again",
  120: "this mint cannot be withdrawn: it is not a mint of the token program passed, or it is a Token-2022 mint with an extension the program does not accept",
  121: "the signature's s is in the upper half; send n - s instead, as this client's builders do",
  122: "the source is not a token account of this mint owned by the wallet, or it is the destination",
};

// ---- bytes and addresses (as in index.js) ----------------------------------------------------------------------------
const B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz";
const enc = new TextEncoder();
const bytes = (x) => (x instanceof Uint8Array ? x : ArrayBuffer.isView(x) ? new Uint8Array(x.buffer, x.byteOffset, x.byteLength) : new Uint8Array(x));
const cat = (...parts) => {
  const out = new Uint8Array(parts.reduce((n, p) => n + p.length, 0));
  let o = 0;
  for (const p of parts) { out.set(p, o); o += p.length; }
  return out;
};
const u64 = (v) => { const b = new Uint8Array(8); new DataView(b.buffer).setBigUint64(0, BigInt(v), true); return b; };
const u16 = (v) => Uint8Array.of(v & 255, (v >> 8) & 255);
const big = (b) => b.reduce((n, x) => n * 256n + BigInt(x), 0n);
const be32 = (n) => Uint8Array.from({ length: 32 }, (_, i) => Number((n >> BigInt(8 * (31 - i))) & 255n));
const meta = (pubkey, signer, writable) => ({ pubkey, signer, writable });

export function b58(raw) {
  let n = big(raw), out = "";
  while (n > 0n) { out = B58[Number(n % 58n)] + out; n /= 58n; }
  for (const b of raw) { if (b !== 0) break; out = "1" + out; }
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
const key32 = (k) => (typeof k === "string" ? unb58(k) : k);
export const sha256 = async (b) => new Uint8Array(await globalThis.crypto.subtle.digest("SHA-256", b));
export const b64url = (raw) => btoa(String.fromCharCode(...raw)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");

// A program address is a sha256 that is not a point on ed25519: y is the low 255 bits, and the point exists iff
// (y^2 - 1) / (d y^2 + 1) is a square mod p.
const P = 2n ** 255n - 19n;
const D = 37095705934669439343138083508754565189542113879843219016388785533085940283555n;
const mod = (a) => ((a % P) + P) % P;
function pow(b, e) {
  let r = 1n;
  b = mod(b);
  while (e > 0n) { if (e & 1n) r = mod(r * b); b = mod(b * b); e >>= 1n; }
  return r;
}
function onCurve(h) {
  let y = 0n;
  for (let i = 31; i >= 0; i--) y = (y << 8n) | BigInt(h[i]);
  y &= (1n << 255n) - 1n;
  if (y >= P) return false;
  const x2 = mod(mod(y * y - 1n) * pow(mod(D * y * y + 1n), P - 2n));
  return x2 === 0n || pow(x2, (P - 1n) / 2n) === 1n;
}
export async function findProgramAddress(seeds, program) {
  const tail = cat(key32(program), enc.encode("ProgramDerivedAddress"));
  for (let bump = 255; bump >= 0; bump--) {
    const h = await sha256(cat(...seeds, Uint8Array.of(bump), tail));
    if (!onCurve(h)) return [b58(h), bump];
  }
  throw new Error("no program address");
}

/** The owner's associated token account of a mint: where a wallet address is paid, and what `to` is for one. */
export const ata = async (owner, mint, tokenProgram = TOKEN) =>
  (await findProgramAddress([key32(owner), key32(tokenProgram), key32(mint)], ATA_PROGRAM))[0];
/** Creates the owner's associated token account if it does not exist (idempotent); the payer pays its rent. */
export async function createAtaIx(payer, owner, mint, tokenProgram = TOKEN) {
  return { program: ATA_PROGRAM, data: Uint8Array.of(1), accounts: [meta(payer, true, true), meta(await ata(owner, mint, tokenProgram), false, true),
    meta(owner, false, false), meta(mint, false, false), meta(SYSTEM, false, false), meta(tokenProgram, false, false)] };
}

// ---- the public key ---------------------------------------------------------------------------------------------------
const SPKI = Uint8Array.from("3059301306072a8648ce3d020106082a8648ce3d030107034200".match(/../g), (h) => parseInt(h, 16));

/** A P-256 public key as the program stores it: 33 bytes, 02 or 03 (y even or odd), then x. Takes that form, the
 *  65-byte point (04, x, y) and the 91-byte SubjectPublicKeyInfo that response.getPublicKey() returns. */
export function compressed(publicKey) {
  let k = bytes(publicKey);
  if (k.length === 91 && SPKI.every((b, i) => k[i] === b)) k = k.subarray(SPKI.length);
  if (k.length === 65 && k[0] === 4) k = cat(Uint8Array.of(2 + (k[64] & 1)), k.subarray(1, 33));
  if (k.length !== 33 || (k[0] !== 2 && k[0] !== 3)) {
    throw new Error("not a P-256 public key: give its 33-byte compressed form, its 65-byte point, or the 91 bytes of getPublicKey()");
  }
  return Uint8Array.from(k);
}

// The little of CBOR an attestation uses: integers, byte and text strings, arrays, maps. Returns [value, next offset].
function cbor(b, at = 0) {
  const major = b[at] >> 5, info = b[at] & 31;
  let n = info, o = at + 1;
  if (info >= 24 && info <= 27) { const len = 1 << (info - 24); n = Number(big(b.subarray(o, o + len))); o += len; } else if (info > 27) throw new Error("not the CBOR of an attestation");
  if (major === 0) return [n, o];
  if (major === 1) return [-1 - n, o];
  if (major === 2) return [b.subarray(o, o + n), o + n];
  if (major === 3) return [new TextDecoder().decode(b.subarray(o, o + n)), o + n];
  if (major === 4) { const out = []; for (let i = 0; i < n; i++) { let v; [v, o] = cbor(b, o); out.push(v); } return [out, o]; }
  if (major === 5) { const out = new Map(); for (let i = 0; i < n; i++) { let k, v; [k, o] = cbor(b, o); [v, o] = cbor(b, o); out.set(k, v); } return [out, o]; }
  if (major === 7 && info < 24) return [info === 21, o];
  throw new Error("not the CBOR of an attestation");
}

/** The passkey's compressed public key from the authenticator data of a registration (the attested credential data:
 *  rpIdHash [32], flags, signCount [4], aaguid [16], id length u16 BE, id, then the key as COSE: EC2, ES256, P-256). */
export function keyFromAuthenticatorData(authenticatorData) {
  const a = bytes(authenticatorData);
  if (a.length < 55 || !(a[32] & 0x40)) throw new Error("this authenticator data carries no public key: it is not a registration's");
  const [cose] = cbor(a, 55 + ((a[53] << 8) | a[54]));
  if (!(cose instanceof Map) || cose.get(1) !== 2 || cose.get(3) !== -7 || cose.get(-1) !== 1 || cose.get(-2)?.length !== 32 || cose.get(-3)?.length !== 32) {
    throw new Error("the passkey is not a P-256 (ES256) key; create it with createOptions");
  }
  return compressed(cat(Uint8Array.of(4), cose.get(-2), cose.get(-3)));
}

/** The compressed public key of a passkey just created: from the credential navigator.credentials.create returned
 *  (or its response): getPublicKey() where the browser has it, else the attestation's authenticator data. */
export function publicKeyOf(credential) {
  const r = credential.response || credential;
  if (typeof r.getPublicKey === "function" && r.getPublicKey()) return compressed(r.getPublicKey());
  if (typeof r.getAuthenticatorData === "function") return keyFromAuthenticatorData(r.getAuthenticatorData());
  const [att] = cbor(bytes(r.attestationObject));
  return keyFromAuthenticatorData(att.get("authData"));
}

// ---- the wallet -------------------------------------------------------------------------------------------------------
/** The address of a passkey's wallet: ["pk", sha256(compressed public key)]. */
export const wallet = async (publicKey, program = PASSKEY) =>
  (await findProgramAddress([enc.encode("pk"), await sha256(compressed(publicKey))], program))[0];

/** The 32 bytes the passkey signs as its WebAuthn challenge to withdraw `amount` of `mint` to the token account `to`,
 *  as the wallet's withdrawal number `nonce`: sha256("knos-passkey" || wallet || mint || to || amount LE || nonce LE). */
export const challenge = (walletAddress, mint, to, amount, nonce) =>
  sha256(cat(enc.encode("knos-passkey"), key32(walletAddress), key32(mint), key32(to), u64(amount), u64(nonce)));

/** A wallet account's bytes: { key, nonce }; null when the wallet is not open yet (its next nonce is then 1). */
export function readWallet(raw) {
  if (!raw || raw.length !== WALLET_LEN || raw[0] !== 1) return null;
  const nonce = new DataView(raw.buffer, raw.byteOffset).getBigUint64(40, true);
  return { key: Uint8Array.from(raw.subarray(2, 35)), nonce: nonce <= 9007199254740991n ? Number(nonce) : nonce };
}

/** A P-256 signature as the precompile takes it: r then s, 32 bytes each, s in the lower half of the order. Takes
 *  that form or the ASN.1 DER a browser returns. (r, n - s) verifies whenever (r, s) does. */
export function rawSignature(signature) {
  let sig = bytes(signature);
  if (sig.length !== 64) {
    const rEnd = 4 + sig[3];
    if (sig[0] !== 0x30 || sig[1] !== sig.length - 2 || sig[2] !== 2 || sig[rEnd] !== 2 || rEnd + 2 + sig[rEnd + 1] !== sig.length) {
      throw new Error("not a P-256 signature: give r and s (64 bytes) or the DER a browser returns");
    }
    const r = big(sig.subarray(4, rEnd)), s = big(sig.subarray(rEnd + 2));
    if (r >> 256n || s >> 256n) throw new Error("not a P-256 signature: r or s is out of range");
    sig = cat(be32(r), be32(s));
  }
  const r = big(sig.subarray(0, 32)), s = big(sig.subarray(32));
  if (r <= 0n || r >= N || s <= 0n || s >= N) throw new Error("not a P-256 signature: r or s is out of range");
  return cat(sig.subarray(0, 32), be32(s > N / 2n ? N - s : s));
}

// ---- instructions -----------------------------------------------------------------------------------------------------
/** Open: creates the wallet's account (anyone pays its rent). A wallet that is open already is left as it is. */
export async function openIx(payer, publicKey, program = PASSKEY) {
  const k = compressed(publicKey);
  return { program, data: cat(Uint8Array.of(0), k), accounts: [meta(payer, true, true), meta(await wallet(k, program), false, true), meta(SYSTEM, false, false)] };
}

/** The precompile instruction that verifies one P-256 signature over `message`, everything in its own data: count 1,
 *  padding, seven u16 LE (signature offset, 0xFFFF, key offset, 0xFFFF, message offset, message length, 0xFFFF), then
 *  the key, the signature, the message. */
export function secp256r1Ix(publicKey, signature, message) {
  const k = compressed(publicKey), sig = rawSignature(signature), m = bytes(message);
  const offsets = [16 + 33, 0xFFFF, 16, 0xFFFF, 16 + 33 + 64, m.length, 0xFFFF];
  return { program: SECP256R1, data: cat(Uint8Array.of(1, 0), ...offsets.map(u16), k, sig, m), accounts: [] };
}

/** The two instructions of a withdrawal, from a WebAuthn assertion ({ authenticatorData, clientDataJSON, signature },
 *  as `sign` returns or as the response of navigator.credentials.get carries them): the precompile over
 *  authenticatorData || sha256(clientDataJSON), then Withdraw. Keep them adjacent and in this order.
 *  `to`: the destination token account. `from`: the wallet's token account to spend (default: its associated one). */
export async function withdrawIxs({ key, mint, to, amount, nonce, assertion, tokenProgram = TOKEN, from = null, program = PASSKEY }) {
  const a = assertion.response || assertion;
  const clientData = bytes(a.clientDataJSON), w = await wallet(key, program);
  const withdraw = { program, data: cat(Uint8Array.of(1), u64(amount), u64(nonce), clientData),
    accounts: [meta(w, false, true), meta(from || await ata(w, mint, tokenProgram), false, true), meta(mint, false, false), meta(to, false, true),
      meta(tokenProgram, false, false), meta(INSTRUCTIONS, false, false)] };
  return [secp256r1Ix(key, a.signature, cat(bytes(a.authenticatorData), await sha256(clientData))), withdraw];
}

// ---- the withdrawal request: the one line a relay reads ---------------------------------------------------------------
// A person with no SOL does not send the two instructions: a relay does, from one line of text posted where it looks
// (a comment in the person's own repository named knos-claim). The line is `knos-withdraw: ` and the base64 (standard
// alphabet, padded) of, in this order:
//   key[33] (the passkey's compressed public key), mint[32], to[32] (the destination token account, as the challenge
//   names it), amount u64 LE, nonce u64 LE, authenticatorData (u16 LE length, bytes), clientDataJSON (u16 LE length,
//   bytes), signature[64] (r then s, s in the lower half: what the secp256r1 precompile takes).
// It is exactly what withdrawIxs needs. The Python relay reads and writes the same bytes
// (knos.settle.v2.passkey.request, read_request), and passkey.fixtures.json holds both to one `request`.
export const WITHDRAW_PREFIX = "knos-withdraw:";

/** The base64 text of a withdrawal request, from what `withdrawIxs` takes. */
export function withdrawRequest({ key, mint, to, amount, nonce, assertion }) {
  const a = assertion.response || assertion, auth = bytes(a.authenticatorData), client = bytes(a.clientDataJSON);
  const raw = cat(compressed(key), unb58(mint), unb58(to), u64(amount), u64(nonce), u16(auth.length), auth, u16(client.length), client,
    rawSignature(a.signature));
  return btoa(String.fromCharCode(...raw));
}

/** The whole line: `knos-withdraw: <withdrawRequest(...)>`. */
export const withdrawLine = (request) => `${WITHDRAW_PREFIX} ${withdrawRequest(request)}`;

/** A request read back, from its text or its whole line: { key, mint, to, amount, nonce, authenticatorData,
 *  clientDataJSON, signature } (amount and nonce as BigInt); null for anything else. */
export function readWithdrawRequest(text) {
  let t = String(text ?? "").trim();
  if (t.startsWith(WITHDRAW_PREFIX)) t = t.slice(WITHDRAW_PREFIX.length).trim();
  try {
    const raw = Uint8Array.from(atob(t.replace(/-/g, "+").replace(/_/g, "/")), (c) => c.charCodeAt(0));
    let o = 0;
    const take = (n) => { if (o + n > raw.length) throw new Error("short"); const x = raw.slice(o, o + n); o += n; return x; };
    const num = () => new DataView(take(8).buffer).getBigUint64(0, true);
    const sized = () => take(new DataView(take(2).buffer).getUint16(0, true));
    const key = compressed(take(33)), mint = b58(take(32)), to = b58(take(32)), amount = num(), nonce = num();
    const authenticatorData = sized(), clientDataJSON = sized(), signature = rawSignature(take(64));
    return o === raw.length ? { key, mint, to, amount, nonce, authenticatorData, clientDataJSON, signature } : null;
  } catch { return null; }
}

// ---- the browser ------------------------------------------------------------------------------------------------------
/** What to pass to navigator.credentials.create for a passkey this program can verify: ES256 (P-256) only. */
export function createOptions({ rpId, rpName = rpId, userName, userId = globalThis.crypto.getRandomValues(new Uint8Array(16)) }) {
  return { publicKey: { rp: { id: rpId, name: rpName }, user: { id: userId, name: userName, displayName: userName },
    challenge: globalThis.crypto.getRandomValues(new Uint8Array(32)), pubKeyCredParams: [{ type: "public-key", alg: -7 }],
    authenticatorSelection: { residentKey: "preferred", userVerification: "preferred" }, attestation: "none" } };
}

/** Creates a passkey and says where its wallet is: { credentialId, key (compressed), wallet (address) }. The key is
 *  only shown now: keep it with the credential id (the wallet's account also holds it once opened). */
export async function create(options, credentials = globalThis.navigator?.credentials) {
  if (!credentials) throw new Error("this browser has no passkeys (navigator.credentials); use a current browser over https");
  const credential = await credentials.create(createOptions(options));
  const key = publicKeyOf(credential);
  return { credentialId: bytes(credential.rawId), key, wallet: await wallet(key) };
}

/** Asks the passkey to sign `challenge` (32 bytes, from `challenge`): { authenticatorData, clientDataJSON, signature }. */
export async function sign(challengeBytes, { rpId, credentialId = null }, credentials = globalThis.navigator?.credentials) {
  if (!credentials) throw new Error("this browser has no passkeys (navigator.credentials); use a current browser over https");
  const publicKey = { challenge: challengeBytes, rpId, userVerification: "preferred",
    ...(credentialId ? { allowCredentials: [{ type: "public-key", id: credentialId }] } : {}) };
  const { response } = await credentials.get({ publicKey });
  return { authenticatorData: bytes(response.authenticatorData), clientDataJSON: bytes(response.clientDataJSON), signature: bytes(response.signature) };
}
