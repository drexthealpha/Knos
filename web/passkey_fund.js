// Fund a work order with nothing but a passkey: the passkey wallet (knos_passkey, a program-derived address holding
// test USDC) signs for one FundOrderWallet of knos_pay, and a relayer sends it and pays the transaction fee. The
// funder needs no SOL and no wallet app. This file signs and sends nothing to Solana: it returns the signed intent,
// and the one line of text a relayer picks up.
//
//   import { passkeyFundIntent, intentComment } from "./passkey_fund.js";
//   const intent = await passkeyFundIntent({
//     terms: { repoId, issue, wfRepo: "owner/name", wfSha, terms: { accept: "", checks: [...], mode: "merge", v: 2 } },
//     amount: 20_000_000,                 // what the payees receive, in the mint's smallest units; knos_pay's fee comes on top
//     expirySlot,                         // the last slot in which the intent can be sent
//     wallet: { key, credentialId },      // the passkey wallet's details, as claim.js keeps them
//   });
//   intentComment(intent)                 // "/knos passkey-fund <base64url>"
//
// What the passkey signs (the program's lib.rs says the same): the WebAuthn challenge is
//   sha256("knos-passkey:fund" || knos_pay id || mint || the FundOrderWallet instruction data || expiry slot LE || nonce LE)
// so the assertion funds the one order those bytes describe, in that mint, once, and in no slot after expirySlot. The
// instruction data comes from the one builder the site already has (settle.js, fundOrderWalletIx), with the wallet
// as the funder. The fee is knos_pay's own and is not computed here: the program logs what left the wallet.
import * as knos from "./settle.js";
import * as passkey from "./passkey.js";

const RPC = "https://api.devnet.solana.com";
const DOMAIN = new TextEncoder().encode("knos-passkey:fund");
export const COMMENT = "/knos passkey-fund";
// A wallet that holds none asks the faucet (docs/FAUCET.md; the rules are knos.faucet's): one line, posted on the faucet issue.
export const FAUCET_ISSUE = "https://github.com/drexthealpha/knos-playground/issues?q=is%3Aissue+is%3Aopen+label%3Afaucet";
export const FAUCET_AMOUNT = 20_000_000;
/** The line that asks the faucet for test USDC to `address`: `/knos faucet <address>`. */
export const faucetComment = (address) => `/knos faucet ${address}`;

const u64 = (v) => { const b = new Uint8Array(8); new DataView(b.buffer).setBigUint64(0, BigInt(v), true); return b; };
const cat = (...parts) => { const out = new Uint8Array(parts.reduce((n, p) => n + p.length, 0)); let o = 0; for (const p of parts) { out.set(p, o); o += p.length; } return out; };
const whole = (v, name) => { if (!Number.isSafeInteger(v) || v <= 0) throw new Error(`${name} must be a whole number above zero`); return v; };
const keyOf = (k) => passkey.compressed(typeof k === "string" ? Uint8Array.from(k.match(/../g) || [], (h) => parseInt(h, 16)) : k);

/** The 32 bytes the passkey signs to fund the order `data` describes (the FundOrderWallet instruction data). */
export const fundChallenge = (pay, mint, data, expirySlot, nonce) =>
  passkey.sha256(cat(DOMAIN, passkey.unb58(pay), passkey.unb58(mint), data, u64(expirySlot), u64(nonce)));

/** Asks the passkey to sign for one order and returns everything a relayer needs, as one JSON object:
 *  { v, program, pay, key, wallet, mint, tokenProgram, order, amount, data, expirySlot, nonce, authenticatorData,
 *    clientDataJSON, signature }; bytes are base64url, the key is hex, addresses are base58.
 *  terms: { repoId, issue, wfRepo, wfSha, terms, mode?, workS?, seq?, options?, scope?, mint?, tokenProgram? }: what
 *    fundOrderWalletIx takes; `terms.terms` is the terms object, or its JSON as text or bytes. mint: Circle's devnet USDC
 *    unless named.
 *  amount: what the payees receive, in the mint's smallest units. expirySlot: the last slot the intent is good in.
 *  wallet: { key, credentialId?, nonce? }: the passkey's public key and credential id; nonce is the wallet's nonce as
 *    last read, and is read from the chain when it is not given.
 *  env: what a page may replace: { rpc, ids, rpId, credentials }. */
export async function passkeyFundIntent({ terms, amount, expirySlot, wallet }, env = {}) {
  if (!terms || !wallet || !wallet.key) throw new Error("the terms of the order and the passkey wallet's details are both needed");
  whole(amount, "the amount");
  whole(expirySlot, "the expiry slot");
  const rpc = env.rpc || RPC;
  const ids = env.ids || await fetch("program_ids.json").then((r) => { if (!r.ok) throw new Error("program_ids.json is missing from this build"); return r.json(); });
  const key = keyOf(wallet.key), program = ids.knos_passkey, address = await passkey.wallet(key, program);
  const mint = terms.mint || knos.USDC_DEVNET, tokenProgram = terms.tokenProgram || knos.TOKEN;
  const body = terms.terms instanceof Uint8Array || typeof terms.terms === "string" ? terms.terms : knos.v2.termsJson(terms.terms);
  const ix = await knos.v2.client(ids).fundOrderWalletIx({ funder: address, funderToken: await passkey.ata(address, mint, tokenProgram), mint,
    repoId: terms.repoId, issue: terms.issue, amount, wfRepo: terms.wfRepo, wfSha: terms.wfSha, terms: body, mode: terms.mode ?? knos.MERGE,
    workS: terms.workS ?? 14 * 86400, seq: terms.seq ?? 0, options: terms.options ?? null, scope: terms.scope ?? null, tokenProgram });
  let last = wallet.nonce;
  if (!Number.isSafeInteger(last)) {
    const opened = await knos.accountInfo(rpc, address);
    if (opened && opened.owner !== program) throw new Error("that address is not a passkey wallet of this program. Nothing was signed.");
    last = Number((opened && passkey.readWallet(opened.data)?.nonce) ?? 0);
  }
  const nonce = last + 1;
  const rpId = env.rpId || globalThis.location?.hostname;
  const a = await passkey.sign(await fundChallenge(ids.knos_pay, mint, ix.data, expirySlot, nonce), { rpId, credentialId: wallet.credentialId || null },
    env.credentials || globalThis.navigator?.credentials);
  return { v: 1, program, pay: ids.knos_pay, key: [...key].map((b) => b.toString(16).padStart(2, "0")).join(""), wallet: address, mint, tokenProgram,
    order: ix.accounts[1].pubkey, amount, data: passkey.b64url(ix.data), expirySlot, nonce, authenticatorData: passkey.b64url(a.authenticatorData),
    clientDataJSON: passkey.b64url(a.clientDataJSON), signature: passkey.b64url(passkey.rawSignature(a.signature)) };
}

/** The one line a relayer picks up: `/knos passkey-fund <base64url of the intent's JSON>`. */
export function intentComment(intent) {
  return `${COMMENT} ${passkey.b64url(new TextEncoder().encode(JSON.stringify(intent)))}`;
}
