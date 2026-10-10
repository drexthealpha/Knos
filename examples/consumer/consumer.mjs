#!/usr/bin/env node
// A second application that reads Knos's record without Knos: Node 20 or later and nothing else (no package, no
// Knos code). It reads an acceptance receipt, or a statement's status file, and a Solana cluster's JSON-RPC, and
// decides on its own: is the order paid, by which transaction, under which terms hash. What it knows of Knos is two
// published files: the receipt's JSON Schema (docs/receipt/) and knos_pay's IDL (idl/knos_pay_v2.json).
//
//     node consumer.mjs receipt RECEIPT.json [--rpc URL | --recorded FILE] [--idl FILE] [--schemas DIR] [--json]
//     node consumer.mjs status STATUS.json   [--rpc URL | --recorded FILE] [--idl FILE] [--json]
//
// Exit 0: paid, and every claim checked agrees with the chain. 1: not paid, or a claim disagrees. 2: wrong use.
import { createHash } from "node:crypto";
import { readFileSync, existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
export const DEVNET = "https://api.devnet.solana.com";
const IDL = join(HERE, "..", "..", "idl", "knos_pay_v2.json");
const SCHEMAS = join(HERE, "..", "..", "docs", "receipt");
// the instructions that move an order's money to its payees, and the account each names as the order (from the IDL)
const PAYING = ["PayOrder", "SettleOrder", "Release"];
const FUNDING = ["FundOrderWallet", "FundOrderBalance"];
const PRIVATE = 2;

// -- base58, sha256, ids ------------------------------------------------------------------------------------------
const B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz";
export function b58decode(text) {
  let n = 0n;
  for (const c of String(text)) {
    const v = B58.indexOf(c);
    if (v < 0) throw new Error(`not base58: ${text}`);
    n = n * 58n + BigInt(v);
  }
  const out = [];
  while (n > 0n) { out.unshift(Number(n & 255n)); n >>= 8n; }
  for (const c of String(text)) { if (c !== "1") break; out.unshift(0); }
  return Uint8Array.from(out);
}
const hex = (bytes) => Buffer.from(bytes).toString("hex");
const sha256 = (data) => createHash("sha256").update(data).digest("hex");

// docs/CONFORMANCE.md, ids: prefix _ first 24 hex of sha256("knos.id.v1" 0 kind 0, then each part as u32 BE length + UTF-8)
const PREFIX = { deliverable: "dlv", evaluation: "evl", invoice_line: "inv", settlement: "stl" };
export function knosId(kind, ...parts) {
  const h = createHash("sha256").update(Buffer.from(`knos.id.v1\0${kind}\0`, "utf8"));
  for (const p of parts) {
    const b = Buffer.from(String(p), "utf8"), len = Buffer.alloc(4);
    len.writeUInt32BE(b.length);
    h.update(len).update(b);
  }
  return `${PREFIX[kind]}_${h.digest("hex").slice(0, 24)}`;
}
const orderScope = (order) => (/^[0-9a-f]{64}$/.test(order) ? order : hex(b58decode(order)));

// -- the JSON Schema keywords the receipt schemas use ---------------------------------------------------------------
export function schemaErrors(schema, value, at = "receipt") {
  const kind = (v) => (v === null ? "null" : Array.isArray(v) ? "array" : Number.isInteger(v) ? "integer" : typeof v);
  const is = (t) => t === kind(value) || (t === "number" && typeof value === "number");
  if (schema.oneOf) {
    const fits = schema.oneOf.filter((s) => schemaErrors(s, value, at).length === 0).length;
    return fits === 1 ? [] : [`${at}: fits ${fits} of the ${schema.oneOf.length} forms it may take, not one`];
  }
  if (schema.type && !(Array.isArray(schema.type) ? schema.type : [schema.type]).some(is)) return [`${at}: is ${kind(value)}, not ${schema.type}`];
  if ("const" in schema && JSON.stringify(schema.const) !== JSON.stringify(value)) return [`${at}: is not ${JSON.stringify(schema.const)}`];
  if (schema.enum && !schema.enum.some((e) => JSON.stringify(e) === JSON.stringify(value))) return [`${at}: is not one of ${JSON.stringify(schema.enum)}`];
  const out = [];
  if (typeof value === "string") {
    if (schema.pattern && !new RegExp(schema.pattern, "u").test(value)) out.push(`${at}: does not match ${schema.pattern}`);
    if (schema.minLength !== undefined && [...value].length < schema.minLength) out.push(`${at}: shorter than ${schema.minLength}`);
    if (schema.maxLength !== undefined && [...value].length > schema.maxLength) out.push(`${at}: longer than ${schema.maxLength}`);
  }
  if (typeof value === "number") {
    if (schema.minimum !== undefined && value < schema.minimum) out.push(`${at}: below ${schema.minimum}`);
    if (schema.maximum !== undefined && value > schema.maximum) out.push(`${at}: above ${schema.maximum}`);
  }
  if (Array.isArray(value)) {
    if (schema.minItems !== undefined && value.length < schema.minItems) out.push(`${at}: fewer than ${schema.minItems} items`);
    if (schema.maxItems !== undefined && value.length > schema.maxItems) out.push(`${at}: more than ${schema.maxItems} items`);
    if (schema.uniqueItems && new Set(value.map((v) => JSON.stringify(v))).size !== value.length) out.push(`${at}: items repeat`);
    if (schema.items) value.forEach((v, i) => out.push(...schemaErrors(schema.items, v, `${at}[${i}]`)));
  }
  if (kind(value) === "object") {
    for (const k of schema.required || []) if (!(k in value)) out.push(`${at}: ${k} is missing`);
    for (const [k, v] of Object.entries(value)) {
      if (schema.properties && k in schema.properties) out.push(...schemaErrors(schema.properties[k], v, `${at}.${k}`));
      else if (schema.additionalProperties === false) out.push(`${at}: ${k} is not a field of this version`);
    }
  }
  return out;
}

// -- the cluster ----------------------------------------------------------------------------------------------------
/** JSON-RPC over HTTP to `url`. */
export function liveRpc(url, timeoutMs = 30000) {
  let id = 0;
  return async (method, params) => {
    const res = await fetch(url, { method: "POST", headers: { "content-type": "application/json" }, signal: AbortSignal.timeout(timeoutMs),
      body: JSON.stringify({ jsonrpc: "2.0", id: ++id, method, params }) });
    const body = await res.json();
    if (body.error) throw new Error(`${method}: ${body.error.message || JSON.stringify(body.error)}`);
    return body.result;
  };
}

/** Answers recorded as {"<method> <first param>": result}; anything not recorded is what a cluster says of an unknown key. */
export function recordedRpc(answers) {
  return async (method, params) => (Object.hasOwn(answers, `${method} ${params[0]}`) ? answers[`${method} ${params[0]}`] : method === "getSignaturesForAddress" ? [] : null);
}

const TX_OPTS = { encoding: "json", commitment: "finalized", maxSupportedTransactionVersion: 0 };

function keysOf(tx) {
  const m = tx.transaction.message, loaded = tx.meta?.loadedAddresses || {};
  return [...m.accountKeys.map((k) => (typeof k === "string" ? k : k.pubkey)), ...(loaded.writable || []), ...(loaded.readonly || [])];
}

/** The `Program log:` lines that `program` itself printed (not a program it called, nor one that called it). */
export function logsOf(tx, program) {
  const stack = [], out = [];
  let truncated = false;
  for (const line of tx.meta?.logMessages || []) {
    let m;
    if ((m = /^Program (\S+) invoke \[\d+\]$/.exec(line))) stack.push(m[1]);
    else if (/^Program \S+ (success|failed)/.test(line)) stack.pop();
    else if (line.startsWith("Log truncated")) truncated = true;
    else if (line.startsWith("Program log: ") && stack[stack.length - 1] === program) out.push(line.slice("Program log: ".length));
  }
  return { lines: out, truncated };
}

const fields = (line, tag) => (line.startsWith(`${tag} `) ? Object.fromEntries(line.slice(tag.length + 1).split(" ").map((kv) => kv.split("="))) : null);

function idlOf(idl) {
  const ix = Object.fromEntries(idl.instructions.map((i) => [i.name, { tag: i.discriminant.value, order: i.accounts.findIndex((a) => a.name === "order") }]));
  return { program: idl.metadata.address, ix, byTag: Object.fromEntries(Object.entries(ix).map(([n, v]) => [v.tag, { name: n, ...v }])) };
}

/** The instruction of knos_pay in `tx` that pays (or funds) an order: {name, order, data}, or null. */
function orderIx(tx, pay, names) {
  const keys = keysOf(tx);
  const inner = (tx.meta?.innerInstructions || []).flatMap((x) => x.instructions);
  for (const ix of [...tx.transaction.message.instructions, ...inner]) {
    if (keys[ix.programIdIndex] !== pay.program) continue;
    const data = b58decode(ix.data), known = pay.byTag[data[0]];
    if (known && names.includes(known.name) && known.order >= 0 && ix.accounts.length > known.order) return { name: known.name, order: keys[ix.accounts[known.order]], data };
  }
  return null;
}

/** What the chain says the transaction `sig` paid: {found, why, tx, ix, paid: [{payee, amount, to}], settled, truncated}. */
async function payment(rpc, pay, sig) {
  const tx = await rpc("getTransaction", [sig, TX_OPTS]);
  if (!tx) return { found: false, why: `the cluster has no finalized transaction ${sig}` };
  if (tx.meta?.err) return { found: false, why: `transaction ${sig} failed on chain: ${JSON.stringify(tx.meta.err)}` };
  const ix = orderIx(tx, pay, PAYING);
  if (!ix) return { found: false, why: `transaction ${sig} has no ${PAYING.join(", ")} instruction of knos_pay (${pay.program})` };
  const { lines, truncated } = logsOf(tx, pay.program);
  const paid = [], settled = [];
  for (const line of lines) {
    const p = fields(line, "knos3:paid") || fields(line, "knos3:released"), s = fields(line, "knos3:settled");
    if (p && p.order === ix.order) paid.push({ payee: p.payee, amount: p.amount, to: p.to });
    if (s && s.order === ix.order) settled.push(s);
  }
  if (truncated) return { found: false, why: `the cluster truncated the log of ${sig}: what it paid cannot be read from it` };
  if (paid.length === 0) return { found: false, why: `knos_pay paid nobody in ${sig}: the order was held or refunded, not paid` };
  return { found: true, tx, ix, paid, settled: settled[settled.length - 1] || null };
}

/** The funding of `order` before the payment `paidSig`: {sig, amount, flags, terms_hash, terms_from} or {why}. */
async function funding(rpc, pay, order, paidSig, limit = 50) {
  const history = (await rpc("getSignaturesForAddress", [order, { limit: 1000, commitment: "finalized" }])) || [];
  let after = false, read = 0;
  for (const { signature, err } of history) {          // newest first: the funding is the latest one before the payment
    if (signature === paidSig) { after = true; continue; }
    if (!after || err) continue;
    if (++read > limit) break;
    const tx = await rpc("getTransaction", [signature, TX_OPTS]);
    if (!tx || tx.meta?.err) continue;
    const { lines } = logsOf(tx, pay.program);
    const funded = lines.map((l) => fields(l, "knos3:funded")).find((f) => f && f.order === order);
    if (!funded) continue;
    const flags = Number(funded.flags), json = lines.find((l) => l.startsWith("knos3:terms "));
    if (json !== undefined) return { sig: signature, amount: funded.amount, fee: funded.fee, flags, terms_hash: sha256(Buffer.from(json.slice("knos3:terms ".length), "utf8")), terms_from: "the terms the funding logged" };
    const ix = orderIx(tx, pay, FUNDING);
    if (flags & PRIVATE && ix && ix.order === order) {     // a private order's terms argument is its scope, then the sha256 of its terms
      return { sig: signature, amount: funded.amount, fee: funded.fee, flags, terms_hash: hex(ix.data.slice(-32)), terms_from: "the funding instruction's terms argument (a private order)" };
    }
    return { why: `the funding ${signature} logged no terms` };
  }
  return { why: after ? `no funding of ${order} was found before the payment` : `the cluster lists no payment ${paidSig} for ${order}` };
}

// -- decisions ------------------------------------------------------------------------------------------------------
function load(path, what) {
  try { return JSON.parse(readFileSync(path, "utf8")); } catch (e) { throw new Error(`${what} ${path} cannot be read: ${e.message}`); }
}

/** Decide from a receipt: {paid, order, transaction, terms_hash, agrees: [...], disagrees: [...], trusted: [...]}. */
export async function decideReceipt(r, rpc, { idl = load(IDL, "the IDL"), schemas = SCHEMAS } = {}) {
  const out = { kind: "receipt", paid: false, order: r?.order ?? null, transaction: null, terms_hash: null, agrees: [], disagrees: [], trusted: [] };
  const pay = idlOf(idl), version = r?.version;
  if (![4, 5].includes(version)) return { ...out, disagrees: [`receipt version ${version} is not read here: versions 4 and 5 name the terms hash and the four ids`] };
  const schemaFile = join(schemas, `acceptance-receipt.v${version}.schema.json`);
  if (!existsSync(schemaFile)) return { ...out, disagrees: [`the schema ${schemaFile} is not here`] };
  const errs = schemaErrors(load(schemaFile, "the schema"), r);
  if (errs.length) return { ...out, disagrees: errs.map((e) => `the receipt does not fit its published schema: ${e}`) };
  out.agrees.push(`the receipt fits acceptance-receipt.v${version}.schema.json`);
  const ok = (cond, yes, no) => (cond ? out.agrees : out.disagrees).push(cond ? yes : no);
  if (r.program !== pay.program) return { ...out, disagrees: [`the receipt names program ${r.program}; knos_pay in the IDL is ${pay.program}`] };
  if (!r.transaction) return { ...out, disagrees: ["the receipt records no payment"] };
  const sig = r.transaction.signature;
  const seen = await payment(rpc, pay, sig);
  if (!seen.found) return { ...out, disagrees: [seen.why] };
  out.transaction = sig;
  ok(seen.ix.order === r.order, `transaction ${sig} is knos_pay's ${seen.ix.name} of order ${r.order}, finalized`, `transaction ${sig} pays order ${seen.ix.order}, not ${r.order}`);
  ok(seen.tx.slot === r.transaction.slot && seen.tx.blockTime === r.transaction.time, `it landed in slot ${seen.tx.slot} at ${seen.tx.blockTime}, as the receipt says`,
    `it landed in slot ${seen.tx.slot} at ${seen.tx.blockTime}; the receipt says slot ${r.transaction.slot} at ${r.transaction.time}`);
  const said = r.payees.map((p) => `${p.github_id}:${p.amount}:${p.to}`).sort().join(" "), chain = seen.paid.map((p) => `${p.payee}:${p.amount}:${p.to}`).sort().join(" ");
  ok(said === chain, `knos_pay logged these payments: ${chain}`, `knos_pay logged ${chain}; the receipt says ${said}`);
  const s = seen.settled, m = r.amounts;
  ok(s && s.paid === m.paid && s.of === m.of && s.fee === m.fee && s.tip === m.tip, `paid ${m.paid} of ${m.of}, fee ${m.fee}, tip ${m.tip} in the mint's units`,
    `knos_pay logged ${s ? `paid ${s.paid} of ${s.of}, fee ${s.fee}, tip ${s.tip}` : "no settlement line"}; the receipt says paid ${m.paid} of ${m.of}, fee ${m.fee}, tip ${m.tip}`);
  const bal = (list, owner) => (list || []).filter((b) => b.owner === owner && b.mint === m.mint).reduce((t, b) => t + BigInt(b.uiTokenAmount.amount), 0n);
  if (seen.tx.meta.postTokenBalances) {
    for (const p of r.payees) {
      const got = bal(seen.tx.meta.postTokenBalances, p.to) - bal(seen.tx.meta.preTokenBalances, p.to);
      ok(got === BigInt(p.amount), `the token balances show ${p.to} received ${p.amount}`, `the token balances show ${p.to} received ${got}, not ${p.amount}`);
    }
  } else out.trusted.push("the amounts are the program's own log: this answer carried no token balances");
  const f = await funding(rpc, pay, r.order, sig);
  if (f.why) out.disagrees.push(`terms: ${f.why}`);
  else {
    out.terms_hash = f.terms_hash;
    ok(f.terms_hash === r.policy.terms_hash, `the terms hash ${f.terms_hash} is the sha256 of ${f.terms_from} in ${f.sig}`,
      `the funding ${f.sig} fixed terms ${f.terms_hash}; the receipt says ${r.policy.terms_hash}`);
    ok(f.amount === m.of, `the order was funded with ${f.amount}`, `the order was funded with ${f.amount}; the receipt says of ${m.of}`);
    const named = r.commercial_authorisation?.funded;
    if (named) ok(named === f.sig, `the receipt names that funding`, `the receipt names funding ${named}; the chain shows ${f.sig}`);
  }
  const milestone = r.commercial_authorisation?.deliverable?.milestone ?? 0;
  const dlv = knosId("deliverable", orderScope(r.order), milestone), stl = knosId("settlement", dlv, "chain", sig);
  ok(r.ids.deliverable === dlv && r.ids.settlement === stl, `its ids are ${dlv} and ${stl}`, `the receipt's ids are ${r.ids.deliverable} and ${r.ids.settlement}; order, milestone ${milestone} and transaction give ${dlv} and ${stl}`);
  out.trusted.push("the cluster's RPC answers (ask a second endpoint to remove that)", "that the program at the IDL's address is knos_pay as published (its upgrade authority is a multisig with a time lock)");
  out.trusted.push("which work was accepted, and why: the judge's run is signed by the forge, and this program does not read it");
  return { ...out, paid: out.disagrees.length === 0 };
}

/** Decide every payment on chain a statement's status file records. */
export async function decideStatus(st, rpc, { idl = load(IDL, "the IDL") } = {}) {
  const pay = idlOf(idl), lines = [];
  if (st?.kind !== "knos-statement-status") return { kind: "status", paid: false, lines, disagrees: ["this is not a statement's status file (kind knos-statement-status)"] };
  for (const ev of st.events || []) {
    if (ev.type !== "settlement" || ev.method !== "chain") continue;
    const line = { line: ev.line, transaction: ev.reference, paid: false, order: null, terms_hash: null, agrees: [], disagrees: [] };
    const ok = (cond, yes, no) => (cond ? line.agrees : line.disagrees).push(cond ? yes : no);
    const seen = await payment(rpc, pay, ev.reference);
    if (!seen.found) line.disagrees.push(seen.why);
    else {
      line.order = seen.ix.order;
      line.payments = seen.paid;
      line.agrees.push(`transaction ${ev.reference} is knos_pay's ${seen.ix.name} of order ${seen.ix.order}, finalized`);
      const scope = orderScope(seen.ix.order);
      const milestone = Array.from({ length: 256 }, (_, k) => k).find((k) => knosId("deliverable", scope, k) === ev.deliverable);
      ok(milestone !== undefined, `deliverable ${ev.deliverable} is milestone ${milestone} of that order`, `deliverable ${ev.deliverable} is not of order ${seen.ix.order}`);
      const stl = knosId("settlement", ev.deliverable, "chain", ev.reference);
      ok(ev.settlement === stl, `settlement ${stl} is that deliverable paid by that transaction`, `settlement ${ev.settlement} is not ${stl}`);
      const f = await funding(rpc, pay, seen.ix.order, ev.reference);
      if (f.why) line.disagrees.push(`terms: ${f.why}`);
      else { line.terms_hash = f.terms_hash; line.agrees.push(`funded in ${f.sig} under terms ${f.terms_hash} (${f.terms_from})`); }
    }
    lines.push({ ...line, paid: line.disagrees.length === 0 });
  }
  return { kind: "status", paid: lines.length > 0 && lines.every((l) => l.paid), lines, disagrees: lines.length ? [] : ["the file records no payment on chain"] };
}

// -- the command ----------------------------------------------------------------------------------------------------
function words(d) {
  const block = (x) => [...x.agrees.map((a) => `  yes  ${a}`), ...x.disagrees.map((a) => `  NO   ${a}`)];
  if (d.kind === "receipt") {
    return [d.paid ? `PAID: order ${d.order} by ${d.transaction} under terms ${d.terms_hash}` : `NOT SHOWN PAID: order ${d.order}`, ...block(d),
      ...d.trusted.map((t) => `  trusts ${t}`)].join("\n");
  }
  return [d.paid ? "PAID: every payment on chain in the file" : "NOT SHOWN PAID", ...d.disagrees.map((a) => `  NO   ${a}`),
    ...d.lines.flatMap((l) => [`line ${l.line}: ${l.paid ? `paid, order ${l.order} by ${l.transaction} under terms ${l.terms_hash}` : "not shown paid"}`, ...block(l)])].join("\n");
}

export async function main(argv) {
  const [what, file, ...rest] = argv, opt = {};
  for (let i = 0; i < rest.length; i++) {
    if (rest[i] === "--json") opt.json = true;
    else if (["--rpc", "--recorded", "--idl", "--schemas"].includes(rest[i]) && rest[i + 1]) opt[rest[i].slice(2)] = rest[++i];
    else return [2, `unknown option ${rest[i]}`];
  }
  if (!["receipt", "status"].includes(what) || !file) return [2, "use: consumer.mjs receipt|status FILE [--rpc URL | --recorded FILE] [--idl FILE] [--schemas DIR] [--json]"];
  try {
    const doc = load(file, "the file"), recorded = opt.recorded ? load(opt.recorded, "the recording") : null;
    const rpc = recorded ? recordedRpc(recorded.rpc || recorded) : liveRpc(opt.rpc || DEVNET);
    const ctx = { idl: load(opt.idl || IDL, "the IDL"), schemas: opt.schemas || SCHEMAS };
    const d = what === "receipt" ? await decideReceipt(doc, rpc, ctx) : await decideStatus(doc, rpc, ctx);
    return [d.paid ? 0 : 1, opt.json ? JSON.stringify(d, null, 1) : words(d)];
  } catch (e) {
    return [1, `cannot decide: ${e.message}`];
  }
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  const [code, text] = await main(process.argv.slice(2));
  (code === 2 ? console.error : console.log)(text);
  process.exit(code);
}
