#!/usr/bin/env node
// Fund a Knos work order from a Squads v4 vault: the multisig's vault is the funder, so the order is paid for by the
// organisation's treasury, a refund returns to that vault, and no single member's wallet is involved.
//
//   node scripts/squads_fund.mjs --multisig ADDRESS --repo-id N --issue N --amount UNITS --mint MINT \
//        --wf-repo owner/name --wf-sha COMMIT --terms FILE [--seq N] [--work-days N] [--vault-index N] [--token-2022]
//                              dry run (no network, no key): prints the FundOrderWallet instruction the vault would sign,
//                              the order's address, and what the vault must hold
//   ... --send --member FILE [--fee-payer FILE] [--rpc URL]
//                              devnet: creates the vault transaction and its proposal and gives that member's approval.
//                              The other members approve in the Squads app, or with this script: --approve INDEX --member FILE
//   ... --execute INDEX --member FILE    once the approvals reach the threshold (and the multisig's time lock has passed)
//
// --amount is in the mint's smallest units (20000000 is 20 USDC): what the payees receive. The vault is debited the
// amount plus knos_pay's fee (0.30% of the amount, at least 0.05: knos_pay 2.2; the 2.1 build still live before its upgrade
// charges the 0.3.14 fee, and --send checks the vault holds the larger of the two), and pays the rent of the order's two
// accounts, which returns to it when the order closes. So before it executes, the vault needs the tokens in its
// associated token account and a little SOL. --terms is the terms JSON (a file, at most 600 bytes) the order is paid
// under. Only devnet is written to. Install the packages first: npm ci --prefix scripts
import { createHash } from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { parseArgs } from "node:util";

import * as web3 from "@solana/web3.js";
import * as squads from "@sqds/multisig";

const { ComputeBudgetProgram, Connection, Keypair, PublicKey, SystemProgram, TransactionInstruction, TransactionMessage, VersionedTransaction } = web3;
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const PINNED = JSON.parse(fs.readFileSync(path.join(ROOT, "programs-v2", "program_ids.json"), "utf8"));
const PROGRAMS = ["knos_oidc", "knos_pay", "knos_meter", "knos_passkey"];      // the only ids a staging file may replace

/** The pinned ids, or with KNOS_PROGRAM_IDS set, the same with the PROGRAM addresses of that file: a staging deployment
 *  (scripts/deploy_v2.sh --rc writes it), read by the rule of knos.settle.v2.load_ids. The vaults, the fee owner and the
 *  workflow pins are constants of the programs, so a file that changes one is refused. Said on stderr. */
export function loadIds(env = process.env) {
  const named = (env.KNOS_PROGRAM_IDS ?? "").trim();
  if (!named) return PINNED;
  let other;
  try { other = JSON.parse(fs.readFileSync(named, "utf8")); } catch (e) {
    throw new Error(`KNOS_PROGRAM_IDS names ${named}, which cannot be read as JSON (${e.message}). Unset it to use the pinned deployment.`);
  }
  if (other === null || typeof other !== "object" || Array.isArray(other)) {
    throw new Error(`KNOS_PROGRAM_IDS names ${named}, which is not a JSON object of program ids. Unset it to use the pinned deployment.`);
  }
  for (const [name, value] of Object.entries(other)) {
    if (PROGRAMS.includes(name)) {
      try { new PublicKey(value); } catch { throw new Error(`${named}: ${name} is not an address (${JSON.stringify(value)}). Unset KNOS_PROGRAM_IDS to use the pinned deployment.`); }
    } else if (name !== "staging" && JSON.stringify(PINNED[name]) !== JSON.stringify(value)) {
      throw new Error(`${named}: only ${PROGRAMS.join(", ")} can be replaced, and it changes ${name}, which the programs themselves fix. Unset KNOS_PROGRAM_IDS to use the pinned deployment.`);
    }
  }
  const swapped = PROGRAMS.filter((n) => other[n] !== undefined && other[n] !== PINNED[n]);
  if (swapped.length) console.error(`KNOS_PROGRAM_IDS is set: using the STAGING programs of ${named} (${swapped.map((n) => `${n} ${other[n]}`).join(", ")}), not the pinned deployment.`);
  return Object.freeze({ ...PINNED, ...Object.fromEntries(swapped.map((n) => [n, other[n]])) });
}
export const IDS = loadIds();
export const TOKEN = new PublicKey("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA");
export const TOKEN_2022 = new PublicKey("TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb");
const ATA_PROGRAM = new PublicKey("ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL");
const DEVNET_GENESIS = "EtWTRABZaYq6iMfeYKouRu166VU2xqa1wcaWoxPkrZBG";

class Refused extends Error {}
const say = (line) => console.log(line);
const sha256 = (...parts) => { const h = createHash("sha256"); for (const p of parts) h.update(p); return h.digest(); };
const le = (v, bytes) => { const b = Buffer.alloc(bytes); let n = BigInt(v); for (let i = 0; i < bytes; i++) { b[i] = Number(n & 255n); n >>= 8n; } return b; };
const meta = (pubkey, isSigner, isWritable) => ({ pubkey, isSigner, isWritable });

/** knos_pay's fee on top of an order's amount, for a mint with `decimals` decimals (lib.rs order_fee of knos_pay 2.2, no
 *  Plan): 30 basis points of the amount, rounded down, at least 0.05; one rate, no tiers, no maximum. */
export function orderFee(amount, decimals = 6) {
  const a = BigInt(amount), lo = 50_000n * 10n ** BigInt(decimals) / 1_000_000n, f = a * 30n / 10_000n;
  return f < lo ? lo : f;
}

/** The fee knos_pay 2.1 charged (the 0.3.14 fee, fees.OLD): 2.5% of the first 1,000 whole units, 1% of what lies
 *  between 1,000 and 50,000, 0.5% of what lies above, each part rounded down; at least 0.40. Orders funded under it keep it. */
export function orderFeeOld(amount, decimals = 6) {
  const unit = 10n ** BigInt(decimals), a = BigInt(amount), t1 = 1_000n * unit, t2 = 50_000n * unit, min = (x, y) => (x < y ? x : y);
  const first = min(a, t1), second = min(a, t2) - first, third = a - first - second;
  const f = first * 250n / 10_000n + second * 100n / 10_000n + third * 50n / 10_000n, lo = 400_000n * unit / 1_000_000n;
  return f < lo ? lo : f;
}

/** The addresses of one order funded by `funder`: the order, its token account, and knos_pay's auth and pause. */
export function addresses(funder, repoId, issue, seq, program = new PublicKey(IDS.knos_pay)) {
  const pda = (...seeds) => PublicKey.findProgramAddressSync(seeds, program)[0];
  const scope = sha256(Buffer.from("knos3:scope"), le(repoId, 8), le(issue, 8));
  const order = pda(Buffer.from("ord"), scope, funder.toBuffer(), le(seq, 4));
  return { scope, order, ov: pda(Buffer.from("ov"), order.toBuffer()), auth: pda(Buffer.from("auth")), pause: pda(Buffer.from("pause")) };
}

/** 15 FundOrderWallet of knos_pay with `funder` as the funding wallet (here: a Squads vault, which signs when the multisig executes). */
export function fundOrderWalletIx(funder, f, program = new PublicKey(IDS.knos_pay)) {
  const a = addresses(funder, f.repoId, f.issue, f.seq, program);
  const tokenProgram = f.token2022 ? TOKEN_2022 : TOKEN;
  const funderToken = PublicKey.findProgramAddressSync([funder.toBuffer(), tokenProgram.toBuffer(), f.mint.toBuffer()], ATA_PROGRAM)[0];
  const data = Buffer.concat([Buffer.from([15]), le(f.issue, 8), le(f.repoId, 8), le(f.amount, 8), Buffer.from([0]), le(f.workSeconds, 8), le(f.seq, 4),
                              Buffer.alloc(48), sha256(Buffer.from(f.wfRepo)), Buffer.from(f.wfSha), Buffer.from(f.terms)]);
  return { ...a, funderToken, ix: new TransactionInstruction({ programId: program, data, keys: [
    meta(funder, true, true), meta(a.order, false, true), meta(a.ov, false, true), meta(funderToken, false, true), meta(f.mint, false, false),
    meta(a.auth, false, false), meta(tokenProgram, false, false), meta(SystemProgram.programId, false, false), meta(a.pause, false, false)] }) };
}

function order(o) {
  const need = (name) => { if (o[name] === undefined) throw new Refused(`--${name} is missing. Run node scripts/squads_fund.mjs --help for the list.`); return o[name]; };
  const whole = (name, fallback) => { const v = o[name] ?? fallback; if (!/^\d+$/.test(String(v))) throw new Refused(`--${name} is a whole number.`); return BigInt(v); };
  const key = (name) => { try { return new PublicKey(need(name)); } catch { throw new Refused(`--${name} is not a Solana address.`); } };
  need("repo-id"); need("issue"); need("amount");
  const termsRef = need("terms");
  const terms = fs.existsSync(termsRef) ? fs.readFileSync(termsRef, "utf8").trim() : termsRef;
  try { JSON.parse(terms); } catch { throw new Refused("--terms is the terms JSON, or a file that holds it."); }
  if (Buffer.byteLength(terms) > 600 || /[^\x20-\x7e]/.test(terms)) throw new Refused("the terms are at most 600 bytes of printable ASCII.");
  if (!/^[0-9a-f]{40}$/.test(need("wf-sha"))) throw new Refused("--wf-sha is a commit: 40 lowercase hex characters.");
  if (!/^[^/\s]+\/[^/\s]+$/.test(need("wf-repo"))) throw new Refused("--wf-repo is owner/name: the repository that holds the workflows that judge the order.");
  const days = whole("work-days", 14);
  if (days < 1n || days > 90n) throw new Refused("--work-days is 1 to 90.");
  return { multisig: key("multisig"), vaultIndex: Number(whole("vault-index", 0)), repoId: whole("repo-id"), issue: whole("issue"), amount: whole("amount"),
           seq: whole("seq", 0), workSeconds: days * 86_400n, mint: key("mint"), wfRepo: o["wf-repo"], wfSha: o["wf-sha"], terms, token2022: Boolean(o["token-2022"]) };
}

/** What the dry run prints: everything a member needs to check before approving. */
export function plan(f) {
  const [vault] = squads.getVaultPda({ multisigPda: f.multisig, index: f.vaultIndex });
  const b = fundOrderWalletIx(vault, f);
  const fee = orderFee(f.amount);
  return { vault, ...b, text: {
    multisig: f.multisig.toBase58(), vault: vault.toBase58(), vault_token: b.funderToken.toBase58(), order: b.order.toBase58(), order_token: b.ov.toBase58(),
    amount: String(f.amount), fee: String(fee), debit: String(f.amount + fee), fee_assumes_decimals: 6, terms_sha256: sha256(Buffer.from(f.terms)).toString("hex"),
    refundable_after_seconds: Number(f.workSeconds),
    instruction: { program: b.ix.programId.toBase58(), data: b.ix.data.toString("hex"),
                   accounts: b.ix.keys.map((k) => ({ pubkey: k.pubkey.toBase58(), signer: k.isSigner, writable: k.isWritable })) } } };
}

const keypair = (file) => Keypair.fromSecretKey(Uint8Array.from(JSON.parse(fs.readFileSync(file, "utf8"))));

async function send(conn, feePayer, ixs, signers, what) {
  const { blockhash, lastValidBlockHeight } = await conn.getLatestBlockhash("confirmed");
  const tx = new VersionedTransaction(new TransactionMessage({ payerKey: feePayer.publicKey, recentBlockhash: blockhash, instructions: ixs }).compileToV0Message());
  tx.sign([...new Map([feePayer, ...signers].map((k) => [k.publicKey.toBase58(), k])).values()]);
  const signature = await conn.sendTransaction(tx);
  const done = await conn.confirmTransaction({ signature, blockhash, lastValidBlockHeight }, "confirmed");
  if (done.value.err) throw new Refused(`${what} failed on chain: ${JSON.stringify(done.value.err)} (${signature})`);
  say(`${what}: ${signature}`);
}

async function main(argv) {
  let o;
  try {
    ({ values: o } = parseArgs({ args: argv, options: {
    multisig: { type: "string" }, "vault-index": { type: "string" }, "repo-id": { type: "string" }, issue: { type: "string" }, amount: { type: "string" },
    mint: { type: "string" }, "wf-repo": { type: "string" }, "wf-sha": { type: "string" }, terms: { type: "string" }, seq: { type: "string" },
    "work-days": { type: "string" }, "token-2022": { type: "boolean" }, send: { type: "boolean" }, approve: { type: "string" }, execute: { type: "string" },
    member: { type: "string" }, "fee-payer": { type: "string" }, rpc: { type: "string" }, help: { type: "boolean", short: "h" } } }));
  } catch (e) { throw new Refused(`${e.message.split("\n")[0]} Run node scripts/squads_fund.mjs --help for the list.`); }
  if (o.help || !argv.length) {
    const lines = fs.readFileSync(fileURLToPath(import.meta.url), "utf8").split("\n").slice(1);
    return say(lines.slice(0, lines.findIndex((l) => !l.startsWith("//"))).map((l) => l.slice(3)).join("\n"));
  }
  const acting = o.send || o.approve !== undefined || o.execute !== undefined;
  if (!acting) return say(JSON.stringify({ dry_run: true, ...plan(order(o)).text }, null, 1));
  if (!o.member) throw new Refused("--member FILE is needed: the keypair of a member of the multisig.");
  const member = keypair(o.member), feePayer = o["fee-payer"] ? keypair(o["fee-payer"]) : member;
  const conn = new Connection(o.rpc ?? process.env.KNOS_RPC ?? "https://api.devnet.solana.com", "confirmed");
  if (await conn.getGenesisHash() !== DEVNET_GENESIS) throw new Refused("this script writes to devnet only, and the cluster at --rpc is not devnet. Nothing was sent.");
  let multisigPda;
  try { multisigPda = new PublicKey(o.multisig); } catch { throw new Refused("--multisig is the multisig's address."); }
  if (o.approve !== undefined || o.execute !== undefined) {
    const index = BigInt(o.approve ?? o.execute);
    if (o.approve !== undefined) return send(conn, feePayer, [squads.instructions.proposalApprove({ multisigPda, transactionIndex: index, member: member.publicKey })], [member], `proposal ${index} approved`);
    const { instruction, lookupTableAccounts } = await squads.instructions.vaultTransactionExecute({ connection: conn, multisigPda, transactionIndex: index, member: member.publicKey });
    if (lookupTableAccounts.length) throw new Refused("this proposal uses lookup tables, which a funding proposal made here never does. Nothing was sent.");
    return send(conn, feePayer, [ComputeBudgetProgram.setComputeUnitLimit({ units: 400_000 }), instruction], [member], `proposal ${index} executed: the order is funded`);
  }
  const f = order(o), p = plan(f);
  const mint = await conn.getParsedAccountInfo(f.mint);
  const decimals = mint.value?.data?.parsed?.info?.decimals;
  if (decimals === undefined) throw new Refused(`${f.mint} is not a token mint on devnet.`);
  const fees = [orderFee(f.amount, decimals), orderFeeOld(f.amount, decimals)];
  const debit = f.amount + (fees[0] > fees[1] ? fees[0] : fees[1]);      // whichever build is live
  const have = await conn.getTokenAccountBalance(p.funderToken).then((r) => BigInt(r.value.amount), () => 0n);
  if (have < debit) throw new Refused(`the vault's token account ${p.funderToken} holds ${have} and the order takes ${debit} (the amount plus the fee). Send the vault the tokens first. Nothing was sent.`);
  if (await conn.getAccountInfo(p.order)) throw new Refused(`the vault already has an order for this issue with --seq ${f.seq} (${p.order}). Use another --seq. Nothing was sent.`);
  const ms = await squads.accounts.Multisig.fromAccountAddress(conn, multisigPda);
  const index = BigInt(ms.transactionIndex.toString()) + 1n;
  const transactionMessage = new TransactionMessage({ payerKey: p.vault, recentBlockhash: (await conn.getLatestBlockhash()).blockhash, instructions: [p.ix] });
  await send(conn, feePayer, [
    squads.instructions.vaultTransactionCreate({ multisigPda, transactionIndex: index, creator: member.publicKey, rentPayer: feePayer.publicKey, vaultIndex: f.vaultIndex,
                                                 ephemeralSigners: 0, transactionMessage, memo: `Knos order: repository ${f.repoId} issue ${f.issue}` }),
    squads.instructions.proposalCreate({ multisigPda, creator: member.publicKey, rentPayer: feePayer.publicKey, transactionIndex: index }),
    squads.instructions.proposalApprove({ multisigPda, transactionIndex: index, member: member.publicKey })], [member], `proposal ${index} created and approved by ${member.publicKey}`);
  say(`on chain now: proposal ${index} of ${multisigPda} funds order ${p.order} with ${f.amount} (debit ${debit}); it has 1 of the ${ms.threshold} approvals it needs. ` +
      `Then: node scripts/squads_fund.mjs --multisig ${multisigPda} --execute ${index} --member FILE`);
}

if (process.argv[1] && import.meta.url === pathToFileURL(fs.realpathSync(process.argv[1])).href) {
  process.removeAllListeners("warning");
  main(process.argv.slice(2)).catch((e) => { console.error(e instanceof Refused ? `refused: ${e.message}` : `failed: ${e.stack ?? e}`); process.exitCode = 1; });
}
