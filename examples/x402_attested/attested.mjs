// x402 "knos-order": a PROPOSED payment scheme, not part of x402. The payment requirement is a Knos work order: the client
// puts the amount in escrow (FundOrderWallet), the server delivers, and the escrow pays the seller when a GitHub-signed
// acceptance arrives (PayOrder), or returns everything to the client after the deadline (RefundOrder). docs/X402.md is
// the specification; this file is both roles' logic, with no dependency but Node and sdk/settle (which has none).
import { ata, b58, findProgramAddress, hex, sha256, unb58, unhex } from "../../sdk/settle/index.js";

export const SCHEME = "knos-order";     // lower case with a hyphen, as x402 names its own (exact, upto, batch-settlement)
export const X402_VERSION = 2;
export const DEVNET = "solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1";     // x402's network id of Solana devnet (CAIP-2)
export const KNOS_PAY = "5y7iWJ1VAMJjnnWbbdo2a2PsWJEwTExSNpzrvQSEnS8k";
export const TOKEN = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA";
export const SYSTEM = "11111111111111111111111111111111";
const enc = new TextEncoder();
const le = (v, bytes) => { const b = new Uint8Array(bytes); let n = BigInt(v); for (let i = 0; i < bytes; i++) { b[i] = Number(n & 255n); n >>= 8n; } return b; };
const cat = (...parts) => { const out = new Uint8Array(parts.reduce((n, p) => n + p.length, 0)); let o = 0; for (const p of parts) { out.set(p, o); o += p.length; } return out; };
const num = (raw, o, bytes) => { let n = 0n; for (let i = bytes - 1; i >= 0; i--) n = (n << 8n) | BigInt(raw[o + i]); return n; };

/** A header value: base64 of the JSON, as the x402 v2 HTTP transport encodes PAYMENT-REQUIRED, PAYMENT-SIGNATURE and PAYMENT-RESPONSE. */
export const encode = (obj) => Buffer.from(JSON.stringify(obj)).toString("base64");
export const decode = (text) => JSON.parse(Buffer.from(text, "base64").toString("utf8"));

/** The fee a funder pays on top of an order's amount (knos_pay's order_fee for a 6-decimal mint, no Plan): 2.5% of the
 *  first 1,000, 1% from there to 50,000, 0.5% above; at least 0.40. */
export function orderFee(amount) {
  const a = BigInt(amount), k = 1_000_000_000n, m = 50_000_000_000n, min = (x, y) => (x < y ? x : y);
  const f = min(a, k) * 250n / 10_000n + (a > k ? (min(a, m) - k) * 100n / 10_000n : 0n) + (a > m ? (a - m) * 50n / 10_000n : 0n);
  return f < 400_000n ? 400_000n : f;
}
export const scopeOf = (repoId, issue) => sha256(cat(enc.encode("knos3:scope"), le(repoId, 8), le(issue, 8)));
export const termsHash = async (terms) => hex(await sha256(enc.encode(terms)));
/** ["ord", scope, payer, seq]: the order a payer's funding creates for this requirement. */
export async function orderAddress(program, repoId, issue, payer, seq) {
  return (await findProgramAddress([enc.encode("ord"), await scopeOf(repoId, issue), unb58(payer), le(seq, 4)], program))[0];
}

/** The PaymentRequirements entry of the scheme. `payer`: the wallet the client named, or null (then `order` is null and the client derives it). */
export async function requirement(offer, payer = null) {
  return {
    scheme: SCHEME, network: offer.network, amount: String(offer.amount), asset: offer.mint, payTo: offer.seller.wallet, maxTimeoutSeconds: offer.workSeconds,
    extra: {
      program: offer.program,
      order: payer ? await orderAddress(offer.program, offer.repoId, offer.issue, payer, offer.seq) : null,
      repoId: String(offer.repoId), issue: String(offer.issue), seq: offer.seq, mode: offer.mode,
      terms: offer.terms, termsHash: await termsHash(offer.terms),
      workflows: { repository: offer.wfRepo, sha: offer.wfSha },
      fee: String(orderFee(offer.amount)), payee: { githubId: String(offer.seller.githubId) },
    },
  };
}

// An x402 extension is { info, schema }: the schema is the JSON Schema of info (specification v2, "Extensions").
const INFO_SCHEMA = { $schema: "https://json-schema.org/draft/2020-12/schema", type: "object", required: ["version", "settles", "refund"],
  properties: { version: { const: 1 }, proposal: { type: "boolean" }, settles: { const: "on-acceptance" }, refund: { const: "after-deadline" }, payerHeader: { type: "string" } } };

/** The body of the 402 (and, base64, its PAYMENT-REQUIRED header). */
export async function paymentRequired(offer, payer, error) {
  return {
    x402Version: X402_VERSION, error,
    resource: { url: offer.url, description: offer.description, mimeType: "application/json" },
    accepts: [await requirement(offer, payer)],
    extensions: { [SCHEME]: { info: { version: 1, proposal: true, settles: "on-acceptance", refund: "after-deadline", payerHeader: "Attested-Payer" }, schema: INFO_SCHEMA } },
  };
}

/** 15 FundOrderWallet of knos_pay, as bytes and accounts: what the client signs. No options: a plain order. */
export async function fundOrderWalletIx(req, payer, payerToken) {
  const x = req.extra;
  const order = await orderAddress(x.program, x.repoId, x.issue, payer, x.seq);
  const pda = async (...seeds) => (await findProgramAddress(seeds, x.program))[0];
  const data = cat(Uint8Array.of(15), le(x.issue, 8), le(x.repoId, 8), le(req.amount, 8), Uint8Array.of(x.mode), le(req.maxTimeoutSeconds, 8), le(x.seq, 4),
                   new Uint8Array(48), await sha256(enc.encode(x.workflows.repository)), enc.encode(x.workflows.sha), enc.encode(x.terms));
  const meta = (pubkey, signer, writable) => ({ pubkey, signer, writable });
  return { program: x.program, data, accounts: [
    meta(payer, true, true), meta(order, false, true), meta(await pda(enc.encode("ov"), unb58(order)), false, true), meta(payerToken, false, true),
    meta(req.asset, false, false), meta(await pda(enc.encode("auth")), false, false), meta(TOKEN, false, false), meta(SYSTEM, false, false),
    meta(await pda(enc.encode("pause")), false, false)] };
}

/** The fields of an Order account (512 bytes, version 2) that the scheme checks; null for anything else. */
export function readOrder(raw) {
  if (!raw || raw.length !== 512 || raw[0] !== 2) return null;
  return { state: raw[1], mode: raw[2], fromBalance: raw[3] === 1, flags: raw[4], scope: hex(raw.subarray(24, 56)), seq: Number(num(raw, 56, 4)),
           holdbackBps: Number(num(raw, 60, 2)), amount: num(raw, 64, 8), fee: num(raw, 72, 8), deadline: Number(num(raw, 96, 8)),
           source: b58(raw.subarray(192, 224)), refundTo: b58(raw.subarray(224, 256)), mint: b58(raw.subarray(288, 320)),
           terms: hex(raw.subarray(320, 352)), wfRepo: hex(raw.subarray(352, 384)), wfSha: Buffer.from(raw.subarray(384, 424)).toString("latin1") };
}

/**
 * The server's check of a payment proof: the order the client names exists on chain, is knos_pay's, and is the order
 * the requirement asked for, with time left. Returns { ok, order, payer } or { ok: false, reason }.
 * `chain`: { account(address) -> { owner, data } | null, now() }. `margin`: the least time the seller needs to deliver.
 */
export async function verify(chain, req, payload, margin = 3600) {
  const no = (reason) => ({ ok: false, reason });
  if (typeof payload?.order !== "string") return no("the payment proof names no order");
  const x = req.extra;
  const got = await chain.account(payload.order);
  if (!got) return no(`there is no order at ${payload.order}: fund it first (FundOrderWallet), or it was already paid out or refunded`);
  if (got.owner !== x.program) return no(`${payload.order} is not an account of ${x.program}`);
  const o = readOrder(got.data);
  if (!o) return no(`${payload.order} is not a work order`);
  // the address must be the one the order's own fields derive, for the scope this requirement names
  const scope = hex(await scopeOf(x.repoId, x.issue));
  const at = (await findProgramAddress([enc.encode("ord"), unhex(o.scope), unb58(o.source), le(o.seq, 4)], x.program))[0];
  if (at !== payload.order || o.scope !== scope) return no("the order is for another issue than the one this resource names");
  if (o.state !== 1) return no("the order is not open");
  if (o.amount < BigInt(req.amount)) return no(`the order holds ${o.amount} for its payees and the price is ${req.amount}`);
  if (o.mint !== req.asset) return no(`the order is in mint ${o.mint}, not ${req.asset}`);
  if (o.terms !== x.termsHash || o.mode !== x.mode) return no("the order's terms are not the ones this resource was offered under");
  if (o.wfRepo !== hex(await sha256(enc.encode(x.workflows.repository))) || o.wfSha !== x.workflows.sha) return no("the order pins other workflows as its judge");
  if (o.flags & 0x0a || o.holdbackBps) return no("the order is private, standing or holds part of the payment back: this resource is sold for a plain order");
  if (o.deadline < await chain.now() + margin) return no("the order's deadline leaves too little time to deliver");
  return { ok: true, order: o, payer: o.source };
}

/** The SettlementResponse the server returns with the resource (base64 in PAYMENT-RESPONSE): the money is in escrow, not yet the seller's. */
export const escrowed = (req, payload, v) => ({
  success: true, payer: v.payer, transaction: payload.transaction ?? "", network: req.network, amount: String(v.order.amount),
  extensions: { [SCHEME]: { info: { order: payload.order, state: "escrowed", deadline: v.order.deadline } } },
});

/** Where an order stands, from the chain alone: escrowed while its account exists; afterwards its last log line says how it ended. */
export async function status(chain, program, order) {
  const got = await chain.account(order);
  if (got && got.owner === program && readOrder(got.data)) return { order, state: "escrowed", deadline: readOrder(got.data).deadline };
  const field = (line, name) => (new RegExp(`(?:^| )${name}=(\\S+)`).exec(line) || [])[1];
  const lines = (await chain.logs(order)).filter((l) => field(l, "order") === order);
  const paid = lines.filter((l) => l.startsWith("knos3:paid "));
  if (paid.length) return { order, state: "paid", payments: paid.map((l) => ({ payee: field(l, "payee"), amount: field(l, "amount"), to: field(l, "to"), pr: field(l, "pr") })) };
  const back = lines.find((l) => l.startsWith("knos3:refunded "));
  if (back) return { order, state: "refunded", amount: field(back, "amount") };
  return { order, state: "unknown" };
}

export { ata };
