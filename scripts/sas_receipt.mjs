#!/usr/bin/env node
// Write a Knos acceptance receipt (docs/RECEIPT.md) as a Solana Attestation Service attestation.
//
//   node scripts/sas_receipt.mjs <receipt.json>                                 dry run: print the instructions as JSON, send nothing
//   node scripts/sas_receipt.mjs <receipt.json> --send --keypair FILE [--rpc URL]   send them on devnet (the key pays and is the credential's authority)
//   node scripts/sas_receipt.mjs --init --send --keypair FILE [--rpc URL]           the release step: create the credential and the schema, no receipt
//
// Issuing the attestation is on by default wherever Knos issues a receipt (knos.receipt.attest runs this script with
// --send after the paying transaction is confirmed, and never fails the payment). A receipt of version 1 to 5 is taken;
// the attestation's fields are the same for all three, and its digest is the digest of the receipt it was given. An order attested already is not an error: {"sent": false, "already": true}.
//
// The Solana Attestation Service is program 22zoJMtdu4tQc2PzL74ZUT7FrwgB1Udec8DdW4yw4BdG (the same address on devnet and on
// mainnet); this script builds its instructions with the service's own library, sas-lib 1.0.10 (an optional package of
// scripts/package.json: npm ci --prefix scripts). Three accounts are involved:
//   credential   ["credential", authority, "knos"]: who attests. Its authority and only signer is the key given.
//   schema       ["schema", credential, "acceptance-receipt", version 1]: the fields below.
//   attestation  ["attestation", credential, schema, nonce]: the nonce is the ORDER's address, so the attestation of an
//                order's receipt is at an address anyone derives from the order, and an order has one.
// The attestation is the word of the credential's authority that this receipt is what the chain shows. It adds nothing
// GitHub signed: whoever doubts it rebuilds the receipt from the order's paying transaction and compares `receipt_sha256`.
// The credential and the schema are created only when they do not exist yet. Only devnet is ever written to.
import { createHash } from "node:crypto";
import fs from "node:fs";
import { pathToFileURL } from "node:url";
import { parseArgs } from "node:util";

export const SAS = "22zoJMtdu4tQc2PzL74ZUT7FrwgB1Udec8DdW4yw4BdG";
export const CREDENTIAL = "knos", SCHEMA = "acceptance-receipt", SCHEMA_VERSION = 1;
// The schema's fields, in order, with the service's layout codes (sas-lib: 0 u8, 3 u64, 12 String, 13 Vec<u8>).
export const FIELDS = [
  ["receipt_sha256", 13], ["order", 12], ["scope", 13], ["repository_id", 3], ["issue", 3], ["commit", 12], ["pull_request", 3], ["terms_hash", 13],
  ["judge_kind", 0], ["judge_run_id", 3], ["payees", 12], ["mint", 12], ["paid", 3], ["fee", 3], ["transaction", 12],
];
export const JUDGES = ["repository", "neutral", "attestor", "arbiter"];
const DEVNET_GENESIS = "EtWTRABZaYq6iMfeYKouRu166VU2xqa1wcaWoxPkrZBG";

class Refused extends Error {}

/** The bytes a receipt's digest is taken over, as knos.receipt.canonical writes them: keys sorted, no white space. */
export function canonical(v) {
  if (Array.isArray(v)) return `[${v.map(canonical).join(",")}]`;
  if (v && typeof v === "object") return `{${Object.keys(v).sort().map((k) => `${JSON.stringify(k)}:${canonical(v[k])}`).join(",")}}`;
  return JSON.stringify(v);
}
export const digest = (receipt) => createHash("sha256").update(canonical(receipt), "utf8").digest();

/** The attestation's data, field by field: what of the receipt goes on chain. A private order has repository_id and issue 0. */
export function fields(r) {
  if (r?.type !== "knos.acceptance-receipt" || ![1, 2, 3, 4, 5].includes(r.version)) throw new Refused("this is not a Knos acceptance receipt of version 1 to 5 (docs/RECEIPT.md).");
  // a version 4 receipt of an evaluation nothing was paid for (rejected, insufficient evidence) names no transaction: there is no payment to attest
  if (r.transaction === null) throw new Refused("this receipt names no transaction: nothing was paid, so there is no payment to attest.");
  const bytes = (hexText) => Array.from(Buffer.from(hexText, "hex"));
  // versions 2 and 3 say the same facts under their parts (3 adds who authorised the money and who controls each judge:
  // in the digest, not in a field of their own); a GitLab token names its run `pipeline_id`
  const two = r.version >= 2, claims = two ? r.issuer_authenticated.claims : r.judge.claims;
  const artifact = two ? r.evaluator_observed.artifact : r.artifact;
  return {
    receipt_sha256: Array.from(digest(r)), order: r.order, scope: bytes(r.scope), repository_id: BigInt(r.repository?.id ?? 0), issue: BigInt(r.repository?.issue ?? 0),
    commit: artifact.commit, pull_request: BigInt(artifact.pull_request), terms_hash: bytes(two ? r.policy.terms_hash : r.terms.hash),
    judge_kind: JUDGES.indexOf(two ? r.evaluator_observed.judge.kind : r.judge.kind),
    judge_run_id: BigInt(claims.run_id ?? claims.pipeline_id), payees: r.payees.map((p) => `${p.github_id}.${p.bps}.${p.amount}.${p.to}`).join(","),
    mint: r.amounts.mint, paid: BigInt(r.amounts.paid), fee: BigInt(r.amounts.fee), transaction: r.transaction.signature,
  };
}

/** The schema as the service stores it, as far as sas-lib's serializer reads it: the layout and the field names (each u32 length, then bytes). */
export function localSchema() {
  const names = Buffer.concat(FIELDS.flatMap(([name]) => { const n = Buffer.alloc(4); n.writeUInt32LE(Buffer.byteLength(name)); return [n, Buffer.from(name)]; }));
  return { layout: Uint8Array.from(FIELDS.map(([, code]) => code)), fieldNames: Uint8Array.from(names) };
}

/** An instruction of sas-lib (@solana/kit's shape) as plain JSON: program, accounts (pubkey, signer, writable), data in hex. */
const plain = (name, ix) => ({ name, program: ix.programAddress, data: Buffer.from(ix.data).toString("hex"),
                               accounts: ix.accounts.map((a) => ({ pubkey: a.address, signer: a.role >= 2, writable: a.role === 1 || a.role === 3 })) });

/** The addresses and the three instructions for `receipt`, with `authority` (a base58 address) as payer and credential authority. */
export async function plan(receipt, authority) {
  const values = fields(receipt);             // refuses anything that is not a receipt before an address is derived from it
  let sas;
  try { sas = await import("sas-lib"); } catch { throw new Refused("the package sas-lib is not installed: npm ci --prefix scripts"); }
  if (sas.SOLANA_ATTESTATION_SERVICE_PROGRAM_ADDRESS !== SAS) throw new Refused(`sas-lib is for program ${sas.SOLANA_ATTESTATION_SERVICE_PROGRAM_ADDRESS}, not ${SAS}.`);
  const signer = { address: authority, signTransactions: async () => [] };       // an address that signs: sas-lib only reads it
  const [credential] = await sas.deriveCredentialPda({ authority, name: CREDENTIAL });
  const [schema] = await sas.deriveSchemaPda({ credential, name: SCHEMA, version: SCHEMA_VERSION });
  const [attestation] = await sas.deriveAttestationPda({ credential, schema, nonce: receipt.order });
  const data = sas.serializeAttestationData(localSchema(), values);
  return {
    program: SAS, authority, credential, schema, attestation, receipt_sha256: digest(receipt).toString("hex"),
    instructions: [
      plain("create credential", sas.getCreateCredentialInstruction({ payer: signer, authority: signer, credential, name: CREDENTIAL, signers: [authority] })),
      plain("create schema", sas.getCreateSchemaInstruction({ payer: signer, authority: signer, credential, schema, name: SCHEMA,
                                                             description: "Knos acceptance receipt, version 1: docs/RECEIPT.md", layout: localSchema().layout,
                                                             fieldNames: FIELDS.map(([name]) => name) })),
      plain("create attestation", sas.getCreateAttestationInstruction({ payer: signer, authority: signer, credential, schema, attestation, nonce: receipt.order,
                                                                       data, expiry: 0 })),
    ],
  };
}

/** The release step: create the credential "knos" and the schema "acceptance-receipt" under the key given, when they do not exist yet. */
async function init(o) {
  const web3 = await import("@solana/web3.js");
  let sas;
  try { sas = await import("sas-lib"); } catch { throw new Refused("the package sas-lib is not installed: npm ci --prefix scripts"); }
  const key = o.keypair ? web3.Keypair.fromSecretKey(Uint8Array.from(JSON.parse(fs.readFileSync(o.keypair, "utf8")))) : null;
  if (o.send && !key) throw new Refused("--send needs --keypair FILE: the devnet key that pays and is the credential's authority.");
  const authority = key ? key.publicKey.toBase58() : o.authority ?? "11111111111111111111111111111111";
  const signer = { address: authority, signTransactions: async () => [] };
  const [credential] = await sas.deriveCredentialPda({ authority, name: CREDENTIAL });
  const [schema] = await sas.deriveSchemaPda({ credential, name: SCHEMA, version: SCHEMA_VERSION });
  const instructions = [
    plain("create credential", sas.getCreateCredentialInstruction({ payer: signer, authority: signer, credential, name: CREDENTIAL, signers: [authority] })),
    plain("create schema", sas.getCreateSchemaInstruction({ payer: signer, authority: signer, credential, schema, name: SCHEMA,
                                                           description: "Knos acceptance receipt, version 1: docs/RECEIPT.md", layout: localSchema().layout,
                                                           fieldNames: FIELDS.map(([name]) => name) })),
  ];
  if (!o.send) return console.log(JSON.stringify({ dry_run: true, program: SAS, authority, credential, schema, instructions }, null, 1));
  const conn = new web3.Connection(o.rpc ?? process.env.KNOS_RPC ?? "https://api.devnet.solana.com", "confirmed");
  if (await conn.getGenesisHash() !== DEVNET_GENESIS) throw new Refused("this script writes to devnet only, and the cluster at --rpc is not devnet. Nothing was sent.");
  const exists = async (a) => (await conn.getAccountInfo(new web3.PublicKey(a))) !== null;
  const skip = { "create credential": await exists(credential), "create schema": await exists(schema) };
  const todo = instructions.filter((ix) => !skip[ix.name]);
  if (!todo.length) return console.log(JSON.stringify({ sent: false, already: true, credential, schema }, null, 1));
  const ixs = todo.map((ix) => new web3.TransactionInstruction({ programId: new web3.PublicKey(ix.program), data: Buffer.from(ix.data, "hex"),
    keys: ix.accounts.map((a) => ({ pubkey: new web3.PublicKey(a.pubkey), isSigner: a.signer, isWritable: a.writable })) }));
  const signature = await web3.sendAndConfirmTransaction(conn, new web3.Transaction().add(...ixs), [key]);
  console.log(JSON.stringify({ sent: true, signature, credential, schema, created: todo.map((ix) => ix.name) }, null, 1));
}

async function main(argv) {
  const { values: o, positionals: [file] } = parseArgs({ args: argv, allowPositionals: true, options: {
    send: { type: "boolean" }, keypair: { type: "string" }, rpc: { type: "string" }, authority: { type: "string" }, init: { type: "boolean" } } });
  if (o.init) return init(o);
  if (!file) throw new Refused("give the receipt: node scripts/sas_receipt.mjs <receipt.json> [--send --keypair FILE]");
  const receipt = JSON.parse(fs.readFileSync(file, "utf8"));
  const web3 = await import("@solana/web3.js");
  const key = o.keypair ? web3.Keypair.fromSecretKey(Uint8Array.from(JSON.parse(fs.readFileSync(o.keypair, "utf8")))) : null;
  if (o.send && !key) throw new Refused("--send needs --keypair FILE: the devnet key that pays and is the credential's authority.");
  const p = await plan(receipt, key ? key.publicKey.toBase58() : o.authority ?? "11111111111111111111111111111111");
  if (!o.send) return console.log(JSON.stringify({ dry_run: true, ...p }, null, 1));
  const conn = new web3.Connection(o.rpc ?? process.env.KNOS_RPC ?? "https://api.devnet.solana.com", "confirmed");
  if (await conn.getGenesisHash() !== DEVNET_GENESIS) throw new Refused("this script writes to devnet only, and the cluster at --rpc is not devnet. Nothing was sent.");
  if (await conn.getAccountInfo(new web3.PublicKey(p.attestation))) {       // one attestation per order: a second send is a clean no-op
    return console.log(JSON.stringify({ sent: false, already: true, attestation: p.attestation, credential: p.credential, schema: p.schema, receipt_sha256: p.receipt_sha256 }, null, 1));
  }
  const exists = async (a) => (await conn.getAccountInfo(new web3.PublicKey(a))) !== null;
  const skip = { "create credential": await exists(p.credential), "create schema": await exists(p.schema) };
  const ixs = p.instructions.filter((ix) => !skip[ix.name]).map((ix) => new web3.TransactionInstruction({ programId: new web3.PublicKey(ix.program),
    data: Buffer.from(ix.data, "hex"), keys: ix.accounts.map((a) => ({ pubkey: new web3.PublicKey(a.pubkey), isSigner: a.signer, isWritable: a.writable })) }));
  const signature = await web3.sendAndConfirmTransaction(conn, new web3.Transaction().add(...ixs), [key]);
  console.log(JSON.stringify({ sent: true, signature, attestation: p.attestation, credential: p.credential, schema: p.schema, receipt_sha256: p.receipt_sha256 }, null, 1));
}

if (process.argv[1] && import.meta.url === pathToFileURL(fs.realpathSync(process.argv[1])).href) {
  process.removeAllListeners("warning");
  main(process.argv.slice(2)).catch((e) => { console.error(e instanceof Refused ? `refused: ${e.message}` : `failed: ${e.stack ?? e}`); process.exitCode = 1; });
}
