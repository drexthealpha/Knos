#!/usr/bin/env node
// The two Squads v4 multisigs of the second deployment, and everything they are ever asked to sign.
//
//   upgrade multisig   its vault is the upgrade authority of knos_oidc and knos_pay. Time lock 172800 s: an upgrade
//                      can be executed 48 hours after the vote that approved it, and not before. In that time a
//                      vote of the members can cancel it, and anyone can read the proposal on chain.
//   guardian multisig  its vault is the GUARDIAN both programs name. Time lock 0, so that a revocation is not
//                      delayed. It can approve a signing key GitHub's signature admitted, revoke a key, and pause
//                      new funding for at most seven days. It has no instruction that moves money.
//
// Both are autonomous (no config authority): members, threshold and time lock change only by a vote of the members,
// and the upgrade multisig's own time lock applies to that vote too. Their addresses come from two "create keys" and
// are pinned in programs-v2/program_ids.json and in the programs; `create` refuses any key that gives another address.
//
//   node scripts/governance.mjs create                          both multisigs, each with the members and threshold given
//   node scripts/governance.mjs show [--check]                  each one as the chain has it; --check: exit 1 unless both are right
//   node scripts/governance.mjs guardian approve <issuer> <key hash>    let a key GitHub's signature admitted be used
//   node scripts/governance.mjs guardian revoke <issuer> <key hash>     end a key for ever: nothing undoes it
//   node scripts/governance.mjs guardian pause <seconds>        refuse new funding for that long (at most 604800; 0 lifts it)
//   node scripts/governance.mjs upgrade propose <knos_oidc|knos_pay> <buffer address> [--spill ADDRESS] [--ungated]
//   node scripts/governance.mjs upgrade execute <index>         once the proposal is approved and its 172800 s have passed
//   node scripts/governance.mjs approve <upgrade|guardian> <index>   another member's vote for a proposal
//   node scripts/governance.mjs cancel <upgrade|guardian> <index>    a vote to cancel an approved proposal that has not run
//   node scripts/governance.mjs execute <upgrade|guardian> <index>   run an approved proposal (upgrade execute is this for upgrade)
//   node scripts/governance.mjs derive                          the addresses the create keys give (no network)
//   node scripts/governance.mjs inner guardian approve|revoke <issuer> <key hash>, inner guardian pause <seconds>,
//                               inner upgrade <program> <buffer>   the instruction a proposal would carry, as JSON (no network)
//
// <issuer> is 0 or github, 1 or gitlab; <key hash> is the sha256 of the key's modulus, 64 lowercase hex characters
// (`knos status` prints it for every key GitHub publishes).
//
// A guardian command builds the program's instruction (the guardian's vault is its signer), wraps it in a vault
// transaction, creates the proposal, approves it with the member keys given until the threshold is met and, then,
// executes it. `upgrade propose` stops after the approvals and prints when the proposal can be executed. Before it:
// write the new build to a buffer and hand the buffer to the vault (the command prints the hash the members compare
// with the verified build):
//   solana program write-buffer programs-v2/target/deploy/knos_pay.so --buffer BUFFER.json
//   solana program set-buffer-authority <BUFFER> --new-buffer-authority <the upgrade vault>
//
// Options (every command that reads the chain):
//   --rpc URL            the cluster (default: $KNOS_RPC, else https://api.devnet.solana.com)
//   --keys DIR           the key folder (default: $KNOS_KEYS, else .knos-keys in the repository). It holds
//                        upgrade-create-key.json, guardian-create-key.json, payer.json, member-1.json, member-2.json, ...
//   --fee-payer FILE     pays fees and rent (default: $KNOS_FEE_PAYER, else payer.json in the key folder)
//   --member FILE        a member's keypair; repeat it (default: every member-N.json in the key folder).
//                        `create` needs only the addresses, and takes an address in place of a file.
//   --threshold N        create: how many members must approve (default 2)
//   --upgrade-create-key FILE, --guardian-create-key FILE     create, derive (default: in the key folder)
//   --priority-fee N     micro-lamports per compute unit, on every transaction (default 0)
//   --out FILE           upgrade propose: also write the proposal as JSON (program, address, buffer, hash, index, status,
//                        approved_at, executable_from: unix seconds, null until it is approved), for scripts/deploy_v2.sh
//                        --propose and the scheduler
//   --ungated            upgrade propose: FOR AN EMERGENCY ONLY. Propose a buffer whose build has no record of the upgrade gate
//                        (examples/upgrade_gate: GitHub's signed statement that its runner built these bytes from a commit of
//                        this repository; program.yml's gate job asks for it and a relayer records it, so a release needs no
//                        flag). Without it such a buffer is refused. The members then have only their own rebuild to go by.
//   --unchecked          execute: send it without this script's own look at the proposal's state and time lock, so that
//                        the Squads program itself answers. For scripts/drill_upgrade.sh, which shows the chain's refusal.
//
// Every command can be run again after a failure: it reads the chain first and does only what is missing. The last
// line it prints says what is true on chain now. Install the packages first: npm ci --prefix scripts
import { createHash } from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { parseArgs } from "node:util";

import * as web3 from "@solana/web3.js";
import * as squads from "@sqds/multisig";

const { ComputeBudgetProgram, Connection, Keypair, PublicKey, SystemProgram, TransactionInstruction, TransactionMessage, VersionedTransaction } = web3;
const { Multisig, ProgramConfig, Proposal, VaultTransaction } = squads.accounts;

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
export const IDS = JSON.parse(fs.readFileSync(path.join(ROOT, "programs-v2", "program_ids.json"), "utf8"));
export const LOADER = new PublicKey("BPFLoaderUpgradeab1e11111111111111111111111");
// examples/upgrade_gate: it writes ["build", program, executable hash] only on a token GitHub signed for this repository's
// program.yml at a commit of main or of a release tag, verified on chain by knos-oidc.
export const UPGRADE_GATE = new PublicKey("2DfVEuBMWvvh3kXZaQwk2SoszJsoV1PTiK1VGCkB55HW");
// What each multisig must be. The addresses are the pinned ones: the programs name these vaults.
export const WHICH = {
  upgrade: { timeLock: 172_800, multisig: IDS.upgrade_multisig, vault: IDS.upgrade_authority, createKey: "upgrade-create-key.json" },
  guardian: { timeLock: 0, multisig: IDS.guardian_multisig, vault: IDS.guardian, createKey: "guardian-create-key.json" },
};
const PAUSE_MAX = 7 * 86_400;
const CLUSTERS = { EtWTRABZaYq6iMfeYKouRu166VU2xqa1wcaWoxPkrZBG: "devnet", "4uhcVJyU9pJkvQyS88uRDiswHXSCkY3zQawwpjk2NsNY": "testnet",
                   "5eykt4UsFv8P8NJdTREpY1vzqKqZKvdpKuc147dw2N9d": "mainnet-beta" };

/** A refusal in plain words: what is wrong and what to do. Printed as one line, exit 1. */
export class Refused extends Error {}

const say = (line) => console.log(line);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const when = (t) => new Date(t * 1000).toISOString().replace(".000Z", "Z");
const span = (s) => (s % 3600 === 0 && s > 0 ? `${s} s (${s / 3600} hours)` : `${s} s`);
const big = (v) => BigInt(v.toString());

// ---- keys -----------------------------------------------------------------------------------------------------------
function keypair(file) {
  let raw;
  try { raw = JSON.parse(fs.readFileSync(file, "utf8")); } catch (e) { throw new Refused(`cannot read the keypair file ${file} (${e.code ?? e.message}).`); }
  if (!Array.isArray(raw) || raw.length !== 64) throw new Refused(`${file} is not a Solana keypair file (a JSON list of 64 numbers).`);
  return Keypair.fromSecretKey(Uint8Array.from(raw));
}

/** The address a key reference stands for: a keypair file, or an address as Solana prints it. */
function address(ref) {
  if (fs.existsSync(ref)) return keypair(ref).publicKey;
  try { return new PublicKey(ref); } catch { throw new Refused(`${ref} is neither a keypair file that exists nor an address.`); }
}

function keysDir(o) { return path.resolve(o.keys ?? process.env.KNOS_KEYS ?? path.join(ROOT, ".knos-keys")); }

function feePayerRef(o) { return o["fee-payer"] ?? process.env.KNOS_FEE_PAYER ?? path.join(keysDir(o), "payer.json"); }

/** The member key references given: --member, else $KNOS_MEMBERS, else member-N.json in the key folder. */
function memberRefs(o) {
  if (o.member?.length) return o.member;
  if (process.env.KNOS_MEMBERS) return process.env.KNOS_MEMBERS.split(/\s+/).filter(Boolean);
  const dir = keysDir(o);
  const found = fs.existsSync(dir) ? fs.readdirSync(dir).filter((f) => /^member-\d+\.json$/.test(f)).sort((a, b) => parseInt(a.slice(7)) - parseInt(b.slice(7))) : [];
  if (!found.length) throw new Refused(`no member keys: pass --member FILE for each, or put member-1.json, member-2.json, ... in ${dir} ` +
                                       "(a new one: solana-keygen new --no-bip39-passphrase -o member-1.json).");
  return found.map((f) => path.join(dir, f));
}

// ---- addresses ------------------------------------------------------------------------------------------------------
/** The multisig and its vault 0 that a create key gives. */
export function derive(createKey) {
  const [multisigPda] = squads.getMultisigPda({ createKey });
  const [vault] = squads.getVaultPda({ multisigPda, index: 0 });
  return { multisigPda, vault };
}

function pinned(name) { return { multisigPda: new PublicKey(WHICH[name].multisig), vault: new PublicKey(WHICH[name].vault) }; }

function createKeyRef(o, name) { return o[`${name}-create-key`] ?? path.join(keysDir(o), WHICH[name].createKey); }

/** Refuses a create key whose multisig or vault is not the pinned one, before anything is sent. */
function checkedDerivation(name, createKey) {
  const got = derive(createKey), want = pinned(name);
  if (!got.multisigPda.equals(want.multisigPda) || !got.vault.equals(want.vault)) {
    throw new Refused(`the ${name} create key ${createKey} gives multisig ${got.multisigPda} and vault ${got.vault}, but the programs pin multisig ` +
                      `${want.multisigPda} and vault ${want.vault} (programs-v2/program_ids.json). This is not the ${name} create key: nothing was sent.`);
  }
  return got;
}

export function keyAccount(issuer, hashHex) {
  if (!/^[0-9a-f]{64}$/.test(hashHex)) throw new Refused("the key hash is 64 lowercase hex characters: the sha256 of the key's modulus.");
  if (issuer !== 0 && issuer !== 1) throw new Refused("--issuer is 0 (GitHub) or 1 (GitLab).");
  return PublicKey.findProgramAddressSync([Buffer.from("key"), Buffer.from([issuer]), Buffer.from(hashHex, "hex")], new PublicKey(IDS.knos_oidc))[0];
}

export const pauseAccount = () => PublicKey.findProgramAddressSync([Buffer.from("pause")], new PublicKey(IDS.knos_pay))[0];
export const programData = (program) => PublicKey.findProgramAddressSync([program.toBuffer()], LOADER)[0];

// ---- the instructions a vault signs ---------------------------------------------------------------------------------
const meta = (pubkey, isSigner, isWritable) => ({ pubkey, isSigner, isWritable });

/** knos_oidc Approve (tag 6) or Revoke (tag 7): guardian(s) key(w). */
export function keyIx(tag, guardian, key) {
  return new TransactionInstruction({ programId: new PublicKey(IDS.knos_oidc), data: Buffer.from([tag]), keys: [meta(guardian, true, false), meta(key, false, true)] });
}

/** knos_pay Pause (tag 9): guardian(s) payer(s,w) pause(w) system; data: seconds u32. */
export function pauseIx(guardian, payer, seconds) {
  if (!Number.isInteger(seconds) || seconds < 0 || seconds > PAUSE_MAX) throw new Refused(`a pause lasts 0 to ${PAUSE_MAX} seconds (seven days); 0 lifts it.`);
  const data = Buffer.alloc(5);
  data[0] = 9;
  data.writeUInt32LE(seconds, 1);
  return new TransactionInstruction({ programId: new PublicKey(IDS.knos_pay), data,
    keys: [meta(guardian, true, false), meta(payer, true, true), meta(pauseAccount(), false, true), meta(SystemProgram.programId, false, false)] });
}

/** The upgradeable loader's Upgrade (variant 3): programdata(w) program(w) buffer(w) spill(w) rent clock authority(s). */
export function upgradeIx(program, buffer, authority, spill) {
  return new TransactionInstruction({ programId: LOADER, data: Buffer.from([3, 0, 0, 0]),
    keys: [meta(programData(program), false, true), meta(program, false, true), meta(buffer, false, true), meta(spill, false, true),
           meta(web3.SYSVAR_RENT_PUBKEY, false, false), meta(web3.SYSVAR_CLOCK_PUBKEY, false, false), meta(authority, true, false)] });
}

/** What solana-verify calls the executable hash: sha256 of the program bytes without their trailing zeros. */
export function executableHash(bytes) {
  let end = bytes.length;
  while (end > 0 && bytes[end - 1] === 0) end--;
  return createHash("sha256").update(bytes.subarray(0, end)).digest("hex");
}

/** Where the upgrade gate records that GitHub built the executable with this hash (64 hex characters) for this program. */
export function buildRecord(program, hashHex) {
  return PublicKey.findProgramAddressSync([Buffer.from("build"), program.toBuffer(), Buffer.from(hashHex, "hex")], UPGRADE_GATE)[0];
}

/** A build record (136 bytes, version 1): the run, when it was recorded, the program, the executable hash, the commit. */
export function readBuildRecord(data) {
  if (data.length !== 136 || data[0] !== 1) return null;
  return { runId: data.readBigUInt64LE(8), time: Number(data.readBigInt64LE(16)), program: new PublicKey(data.subarray(32, 64)),
           hash: data.subarray(64, 96).toString("hex"), commit: data.subarray(96, 136).toString("latin1") };
}

/**
 * The gate on `upgrade propose`: what the record account (as getAccountInfo gives it, or null) says about this build
 * of this program. Returns the line to print; throws a refusal when there is no record and --ungated was not passed.
 */
export function gated(info, programRef, program, hashHex, ungated) {
  const rec = info && info.owner.equals(UPGRADE_GATE) ? readBuildRecord(info.data) : null;
  const at = buildRecord(program, hashHex);
  if (rec && rec.hash === hashHex && rec.program.equals(program)) {
    return `upgrade gate: GitHub's runner built ${hashHex} from commit ${rec.commit} (run ${rec.runId}; record ${at})`;
  }
  if (ungated) return `upgrade gate: NO record that GitHub built ${hashHex} (${at} does not exist). PROPOSED ANYWAY, because --ungated was passed (an emergency only): the members have only their own rebuild to compare with`;
  throw new Refused(`the upgrade gate has no record that GitHub built ${hashHex} for ${programRef} (${at} does not exist on this cluster). ` +
                    "Build it with this repository's program.yml on main or a release tag (its gate job has GitHub sign the hash, and a relayer " +
                    "records it a few minutes later), and write THAT build to the buffer. " +
                    "In an emergency only, to propose a build GitHub did not vouch for, pass --ungated. Nothing was sent.");
}

/** A buffer account of the upgradeable loader: its authority (null: none) and the program bytes it holds. */
export function readBuffer(data) {
  if (data.length < 37 || data.readUInt32LE(0) !== 1) return null;
  return { authority: data[4] === 1 ? new PublicKey(data.subarray(5, 37)) : null, bytes: data.subarray(37) };
}

/** A programdata account: the slot of the last deploy, the upgrade authority (null: none) and the program bytes. */
export function readProgramData(data) {
  if (data.length < 45 || data.readUInt32LE(0) !== 3) return null;
  return { slot: Number(data.readBigUInt64LE(4)), authority: data[12] === 1 ? new PublicKey(data.subarray(13, 45)) : null, bytes: data.subarray(45) };
}

// ---- the chain ------------------------------------------------------------------------------------------------------
async function connect(o) {
  const url = o.rpc ?? process.env.KNOS_RPC ?? "https://api.devnet.solana.com";
  const conn = new Connection(url, { commitment: "confirmed" });
  let genesis;
  try { genesis = await conn.getGenesisHash(); } catch (e) { throw new Refused(`cannot reach the cluster at ${url} (${e.message}). Pass --rpc URL or set KNOS_RPC.`); }
  // a validator on this machine is local whatever it answers: a Surfpool fork gives the genesis of the cluster it copies
  const local = /^http:\/\/(127\.0\.0\.1|localhost|\[::1\])[:/]/.test(url);
  say(`cluster: ${local ? "a validator on this machine" : CLUSTERS[genesis] ?? "a private cluster"} (${url})`);
  return conn;
}

async function chainTime(conn) {
  const t = await conn.getBlockTime(await conn.getSlot("confirmed")).catch(() => null);
  return t ?? Math.floor(Date.now() / 1000);
}

/** Signs, sends and waits for `confirmed` by asking for the signature's status: no websocket. Signs with the keys the
 *  message asks for and no others. A transaction whose blockhash expired unconfirmed never landed, and is sent again with
 *  a new one; so is one the cluster could not even try (no program ran, or the cluster did not answer: a node still
 *  loading an account, a rate limit). A program's own refusal is final. Three tries at most. */
async function send(ctx, ixs, signers, what, lookupTables = []) {
  const { conn, feePayer, fee } = ctx;
  const have = new Map([feePayer, ...signers].map((k) => [k.publicKey.toBase58(), k]));
  const budget = fee > 0 ? [ComputeBudgetProgram.setComputeUnitPrice({ microLamports: fee })] : [];
  let why = "";
  for (let attempt = 1; attempt <= 3; attempt++) {
    if (attempt > 1) await sleep(2000 * (attempt - 1));
    try {
      const { blockhash, lastValidBlockHeight } = await conn.getLatestBlockhash("confirmed");
      const message = new TransactionMessage({ payerKey: feePayer.publicKey, recentBlockhash: blockhash, instructions: [...budget, ...ixs] })
        .compileToV0Message(lookupTables);
      const wanted = message.staticAccountKeys.slice(0, message.header.numRequiredSignatures).map(String);
      const absent = wanted.filter((k) => !have.has(k));
      if (absent.length) throw new Refused(`${what}: ${absent.join(", ")} has to sign, and no key file for it was given.`);
      const tx = new VersionedTransaction(message);
      tx.sign(wanted.map((k) => have.get(k)));
      let sig;
      try {
        sig = await conn.sendTransaction(tx, { preflightCommitment: "confirmed", maxRetries: 5 });
      } catch (e) {
        const logs = (e.logs ?? []).slice(-6);
        why = `${e.message.split("\n")[0].trim() || e.name}${logs.length ? `. Its last log lines: ${logs.join(" | ")}` : ""}`;
        if (!logs.length) continue;
        throw new Refused(`${what}: the cluster refused the transaction (${why})`);
      }
      for (;;) {
        const st = (await conn.getSignatureStatuses([sig])).value[0];
        if (st?.err) throw new Refused(`${what}: transaction ${sig} failed on chain: ${JSON.stringify(st.err)}`);
        if (st && (st.confirmationStatus === "confirmed" || st.confirmationStatus === "finalized")) { say(`  ${what}: ${sig}`); return sig; }
        if (await conn.getBlockHeight("confirmed") > lastValidBlockHeight) { why = "its blockhash expired before it was confirmed"; break; }
        await sleep(500);
      }
    } catch (e) {
      if (e instanceof Refused) throw e;
      why = `the cluster did not answer (${e.message})`;
    }
  }
  throw new Refused(`${what}: not done after three tries: ${why}. Run the same command again: it continues where this stopped.`);
}

async function readMultisig(conn, name) {
  const { multisigPda } = pinned(name);
  const info = await conn.getAccountInfo(multisigPda, "confirmed");
  if (!info) return null;
  if (!info.owner.equals(squads.PROGRAM_ID)) throw new Refused(`${multisigPda} exists but is not an account of the Squads v4 program: it is owned by ${info.owner}.`);
  return Multisig.fromAccountInfo(info)[0];
}

async function existing(conn, name) {
  const ms = await readMultisig(conn, name);
  if (!ms) throw new Refused(`the ${name} multisig ${WHICH[name].multisig} is not on this cluster yet. Create it: node scripts/governance.mjs create`);
  return ms;
}

const isAutonomous = (ms) => ms.configAuthority.equals(PublicKey.default);
const perms = (mask) => ["initiate", "vote", "execute"].filter((_, i) => mask & (1 << i)).join(", ") || "none";

function describe(name, ms) {
  return `${name} multisig ${WHICH[name].multisig} (vault ${WHICH[name].vault}, time lock ${ms.timeLock} s, ${ms.threshold} of ${ms.members.length}, ` +
         `${isAutonomous(ms) ? "no config authority" : `config authority ${ms.configAuthority}`})`;
}

/** What is wrong with a multisig as the chain has it, in words; empty when it is what the design fixes. */
function wrong(name, ms) {
  const out = [];
  if (ms.timeLock !== WHICH[name].timeLock) out.push(`its time lock is ${ms.timeLock} s, not ${WHICH[name].timeLock} s`);
  if (!isAutonomous(ms)) out.push(`it has a config authority (${ms.configAuthority}), which could change it alone`);
  if (ms.threshold < 1 || ms.threshold > ms.members.length) out.push(`its threshold ${ms.threshold} cannot be met by its ${ms.members.length} members`);
  return out;
}

// ---- create, show ---------------------------------------------------------------------------------------------------
async function create(o) {
  const members = memberRefs(o).map(address);
  const threshold = Number(o.threshold ?? 2);
  if (new Set(members.map(String)).size !== members.length) throw new Refused("the same member key was given twice.");
  if (!Number.isInteger(threshold) || threshold < 1 || threshold > members.length) {
    throw new Refused(`a threshold of ${o.threshold ?? 2} cannot be met by ${members.length} member(s): give at least as many --member keys as the threshold.`);
  }
  // both derivations are checked before either multisig is created
  const createKeys = Object.fromEntries(Object.keys(WHICH).map((name) => [name, keypair(createKeyRef(o, name))]));
  for (const name of Object.keys(WHICH)) checkedDerivation(name, createKeys[name].publicKey);
  const ctx = await context(o);
  const { conn } = ctx;
  const sorted = (keys) => keys.map(String).sort().join(",");
  const made = [];
  for (const name of Object.keys(WHICH)) {
    const { multisigPda } = pinned(name);
    let ms = await readMultisig(conn, name);
    if (ms) {
      const differs = wrong(name, ms);
      if (sorted(ms.members.map((m) => m.key)) !== sorted(members) || ms.threshold !== threshold) differs.push("its members or its threshold are not the ones given");
      if (differs.length) throw new Refused(`the ${name} multisig exists already and ${differs.join("; ")}. A multisig is created once; only a vote of its members changes it.`);
      say(`${name}: exists already, as asked`);
    } else {
      const config = await ProgramConfig.fromAccountAddress(conn, squads.getProgramConfigPda({})[0]).catch(() => null);
      if (!config) throw new Refused(`the Squads v4 program ${squads.PROGRAM_ID} is not on this cluster (no program config account).`);
      const ix = squads.instructions.multisigCreateV2({
        createKey: createKeys[name].publicKey, creator: ctx.feePayer.publicKey, multisigPda, configAuthority: null, timeLock: WHICH[name].timeLock,
        members: members.map((key) => ({ key, permissions: squads.types.Permissions.all() })), threshold, treasury: config.treasury, rentCollector: null });
      await send(ctx, [ix], [createKeys[name]], `create the ${name} multisig`);
      ms = await readMultisig(conn, name);
      if (!ms || wrong(name, ms).length) throw new Refused(`the ${name} multisig was created but the chain does not show it as asked: ${ms ? wrong(name, ms).join("; ") : "no account"}.`);
    }
    made.push(describe(name, ms));
  }
  say(`on chain now: ${made.join(" and ")} exist.`);
}

async function show(o) {
  const conn = await connect(o);
  const bad = [];
  const lines = [];
  for (const name of Object.keys(WHICH)) {
    const ms = await readMultisig(conn, name);
    say(`${name} multisig    ${WHICH[name].multisig}`);
    if (!ms) { say("  not on this cluster yet"); bad.push(`the ${name} multisig does not exist`); continue; }
    const got = derive(ms.createKey);
    say(`  vault            ${got.vault}${got.vault.toBase58() === WHICH[name].vault ? "" : `   NOT the pinned ${WHICH[name].vault}`}`);
    say(`  members          ${ms.members.map((m) => `${m.key} (${perms(m.permissions.mask)})`).join("; ")}`);
    say(`  threshold        ${ms.threshold} of ${ms.members.length}`);
    say(`  time lock        ${span(ms.timeLock)}`);
    say(`  config authority ${isAutonomous(ms) ? "none: only a vote of the members changes it" : ms.configAuthority}`);
    say(`  proposals        ${big(ms.transactionIndex)} so far`);
    const problems = wrong(name, ms);
    if (got.vault.toBase58() !== WHICH[name].vault || got.multisigPda.toBase58() !== WHICH[name].multisig) problems.push("its vault is not the pinned one");
    bad.push(...problems.map((p) => `the ${name} multisig: ${p}`));
    lines.push(describe(name, ms));
  }
  for (const name of ["knos_oidc", "knos_pay"]) {
    const info = await conn.getAccountInfo(programData(new PublicKey(IDS[name])), "confirmed");
    const pd = info && readProgramData(info.data);
    const who = !pd ? "not deployed here" : !pd.authority ? "no upgrade authority (made immutable)"
      : pd.authority.toBase58() === IDS.upgrade_authority ? `upgrade authority ${pd.authority}, the upgrade vault` : `upgrade authority ${pd.authority}, NOT the upgrade vault`;
    say(`${name.padEnd(9)} ${IDS[name]}   ${who}`);
  }
  if (bad.length) {
    say(`on chain now: ${bad.join("; ")}.`);
    if (o.check) process.exitCode = 1;
  } else {
    say(`on chain now: ${lines.join(" and ")} exist.`);
  }
}

// ---- proposals ------------------------------------------------------------------------------------------------------
/** A vault transaction's message as text, for comparing the one on chain with the one this command would create. */
function messageText(m) {
  return JSON.stringify([m.numSigners, m.numWritableSigners, m.numWritableNonSigners, m.accountKeys.map(String),
                         m.instructions.map((i) => [i.programIdIndex, [...i.accountIndexes], Buffer.from(i.data).toString("hex")])]);
}

function vaultMessage(vault, inner, blockhash = PublicKey.default.toBase58()) {
  return new TransactionMessage({ payerKey: vault, recentBlockhash: blockhash, instructions: inner });
}

async function proposal(conn, multisigPda, index) {
  const info = await conn.getAccountInfo(squads.getProposalPda({ multisigPda, transactionIndex: index })[0], "confirmed");
  return info ? Proposal.fromAccountInfo(info)[0] : null;
}

/** A proposal of this multisig that carries exactly `inner` and was neither executed, rejected nor cancelled: the one
 *  a run that failed half way left behind. Only the newest ten are looked at. */
async function unfinished(conn, ms, multisigPda, vault, inner) {
  const want = messageText(squads.types.transactionMessageBeet.deserialize(Buffer.from(
    squads.utils.transactionMessageToMultisigTransactionMessageBytes({ message: vaultMessage(vault, inner), vaultPda: vault })))[0]);
  const newest = big(ms.transactionIndex), stale = big(ms.staleTransactionIndex);
  for (let index = newest; index > stale && index > newest - 10n; index--) {
    const info = await conn.getAccountInfo(squads.getTransactionPda({ multisigPda, index })[0], "confirmed");
    let tx;
    try { tx = info && VaultTransaction.fromAccountInfo(info)[0]; } catch { continue; }   // a config transaction, or a closed one
    if (!tx || messageText(tx.message) !== want) continue;
    const p = await proposal(conn, multisigPda, index);
    if (!p || ["Draft", "Active", "Approved"].includes(p.status.__kind)) return { index, proposal: p };
  }
  return null;
}

function membersOf(ms, o, name) {
  const keys = memberRefs(o).map(keypair);
  const known = new Set(ms.members.map((m) => m.key.toBase58()));
  const strangers = keys.filter((k) => !known.has(k.publicKey.toBase58()));
  if (strangers.length) throw new Refused(`${strangers.map((k) => k.publicKey).join(", ")} is not a member of the ${name} multisig. Its members: ${[...known].join(", ")}.`);
  return keys;
}

/** The votes of the member keys given that have not voted, no more than the threshold still needs: the program refuses a
 *  vote on a proposal that has its approvals already. `cancel` votes to cancel an approved proposal instead. Returns the
 *  proposal as the chain has it afterwards. */
async function voteUpTo(ctx, name, ms, members, index, cancel, label) {
  const { multisigPda } = pinned(name);
  let p = await proposal(ctx.conn, multisigPda, index);
  if (p.status.__kind !== (cancel ? "Approved" : "Active")) return p;
  const done = new Set((cancel ? p.cancelled : p.approved).map(String));
  const voters = members.filter((m) => !done.has(m.publicKey.toBase58())).slice(0, Math.max(0, ms.threshold - done.size));
  const build = cancel ? squads.instructions.proposalCancel : squads.instructions.proposalApprove;
  if (!voters.length) return p;
  await send(ctx, voters.map((m) => build({ multisigPda, transactionIndex: index, member: m.publicKey })), voters,
             `${label}: ${cancel ? "cancelled" : "approved"} by ${voters.length} member${voters.length > 1 ? "s" : ""}`);
  return proposal(ctx.conn, multisigPda, index);
}

/** Creates the vault transaction and its proposal for `inner` (or finds the unfinished one), and approves it with the
 *  member keys given. Returns the proposal's index and its state afterwards. */
async function propose(ctx, name, ms, members, inner, what) {
  const { conn } = ctx;
  const { multisigPda, vault } = pinned(name);
  const left = await unfinished(conn, ms, multisigPda, vault, inner);
  const index = left ? left.index : big(ms.transactionIndex) + 1n;
  const label = `${what}: proposal ${index} of the ${name} multisig`;
  const creator = members[0].publicKey, rentPayer = ctx.feePayer.publicKey;
  const make = [];
  if (!left) make.push(squads.instructions.vaultTransactionCreate({ multisigPda, transactionIndex: index, creator, rentPayer, vaultIndex: 0, ephemeralSigners: 0,
                                                                   transactionMessage: vaultMessage(vault, inner) }));
  if (!left?.proposal) make.push(squads.instructions.proposalCreate({ multisigPda, creator, rentPayer, transactionIndex: index }));
  if (left) say(`  proposal ${index} of the ${name} multisig already carries this: continuing with it`);
  if (make.length) await send(ctx, make, [members[0]], `${label} created`);
  return { index, proposal: await voteUpTo(ctx, name, ms, members, index, false, label) };
}

/** Executes an approved proposal whose time lock has passed. Refuses, with the time, one that is still locked;
 *  `unchecked` leaves both refusals to the Squads program. */
async function executeProposal(ctx, name, ms, index, member, what, unchecked = false) {
  const { conn } = ctx;
  const { multisigPda } = pinned(name);
  const p = await proposal(conn, multisigPda, index);
  if (!p) throw new Refused(`the ${name} multisig has no proposal ${index}.`);
  const kind = p.status.__kind;
  if (kind === "Executed") { say(`  proposal ${index} was executed already (${when(Number(big(p.status.timestamp)))})`); return false; }
  if (kind !== "Approved" && !unchecked) {
    throw new Refused(`proposal ${index} of the ${name} multisig is ${kind.toLowerCase()}` + (kind === "Active"
      ? `, with ${p.approved.length} of the ${ms.threshold} approvals it needs. Another member approves it with: node scripts/governance.mjs approve ${name} ${index} --member FILE`
      : ": it cannot be executed."));
  }
  const from = Number(big(p.status.timestamp)) + ms.timeLock, now = await chainTime(conn);
  if (now < from && !unchecked) {
    throw new Refused(`proposal ${index} of the ${name} multisig was approved ${when(from - ms.timeLock)} and its time lock of ${span(ms.timeLock)} ends ` +
                      `${when(from)}, in ${Math.ceil((from - now) / 60)} minutes. It cannot be executed before that.`);
  }
  const { instruction, lookupTableAccounts } = await squads.instructions.vaultTransactionExecute({ connection: conn, multisigPda, transactionIndex: index, member: member.publicKey });
  await send(ctx, [ComputeBudgetProgram.setComputeUnitLimit({ units: 400_000 }), instruction], [member], `${what}: execute proposal ${index}`, lookupTableAccounts);
  return true;
}

function standing(name, ms, index, p) {
  const kind = p.status.__kind;
  if (kind === "Approved") {
    const at = Number(big(p.status.timestamp));
    return `proposal ${index} of the ${name} multisig is approved by ${p.approved.length} of ${ms.members.length} members since ${when(at)}; ` +
           (ms.timeLock ? `it can be executed from ${when(at + ms.timeLock)} (${span(ms.timeLock)} later), and until then ${ms.threshold} members can cancel it` : "it can be executed now");
  }
  if (kind === "Active") return `proposal ${index} of the ${name} multisig has ${p.approved.length} of the ${ms.threshold} approvals it needs` +
                                (ms.timeLock ? `; its ${span(ms.timeLock)} start when the last of them is given` : "");
  return `proposal ${index} of the ${name} multisig is ${kind.toLowerCase()}`;
}

/** The fee payer's key is read before the cluster is asked anything: a missing file is told at once. */
async function context(o, feePayer = keypair(feePayerRef(o))) {
  return { conn: await connect(o), feePayer, fee: Number(o["priority-fee"] ?? 0) };
}

// ---- guardian -------------------------------------------------------------------------------------------------------
function keyState(data) {
  if (!data || data.length < 40) return null;
  return { ready: data[0] === 1, activeAt: Number(data.readBigInt64LE(8)), expiresAt: Number(data.readBigInt64LE(16)),
           approved: !!(data[24] & 1), revoked: !!(data[24] & 2), genesis: !!(data[24] & 4) };
}

const ISSUERS = { 0: 0, github: 0, 1: 1, gitlab: 1 };

/** The guardian's instruction for a command line, with a sentence for the log. `payer` signs Pause's rent. */
function guardianInner(action, args, payer) {
  const guardian = new PublicKey(IDS.guardian);
  if (action === "pause") {
    const seconds = /^\d+$/.test(args[0] ?? "") ? Number(args[0]) : NaN;
    return { inner: pauseIx(guardian, payer, seconds), what: seconds ? `pause new funding for ${seconds} s` : "lift the pause" };
  }
  if (action === "approve" || action === "revoke") {
    const issuer = ISSUERS[args[0]];
    if (issuer === undefined || !args[1]) throw new Refused(`guardian ${action} takes the issuer (0 or github, 1 or gitlab) and the key hash: guardian ${action} 0 <64 hex characters>.`);
    return { inner: keyIx(action === "approve" ? 6 : 7, guardian, keyAccount(issuer, args[1])), what: `${action} key ${args[1]} of issuer ${issuer}`, hash: args[1] };
  }
  throw new Refused("the guardian can do three things: guardian approve <issuer> <key hash>, guardian revoke <issuer> <key hash>, guardian pause <seconds>.");
}

async function guardian(o, action, args) {
  const feePayer = keypair(feePayerRef(o));
  const { inner, what, hash } = guardianInner(action, args, feePayer.publicKey);   // the command line is checked before the network is
  const ctx = await context(o, feePayer);
  const { conn } = ctx;
  const account = action === "pause" ? pauseAccount() : inner.keys[1].pubkey;
  const state = async () => (await conn.getAccountInfo(account, "confirmed"))?.data ?? null;
  const told = (k) => `key ${hash} (account ${account}) is ${k.revoked ? "revoked for ever" : k.genesis ? "a genesis key" : k.approved ? "approved" : "not approved"}` +
                      (k.revoked ? "" : `; it verifies from ${when(k.activeAt)} until ${when(k.expiresAt)}${k.ready ? "" : ", once KeyParams has been sent for it"}`);
  if (action !== "pause") {
    const k = keyState(await state());
    if (!k) throw new Refused(`there is no key account for hash ${hash} on this cluster (it would be ${account}). A key is registered first, with RegisterKey.`);
    if (k.revoked && action === "approve") throw new Refused(`key ${hash} is revoked. A revoked key cannot be approved; nothing undoes a revocation.`);
    if ((action === "approve" && k.approved) || (action === "revoke" && k.revoked)) { say(`on chain now: ${told(k)}. Nothing to do.`); return; }
  }
  const ms = await existing(conn, "guardian");
  const members = membersOf(ms, o, "guardian");
  const { index, proposal: p } = await propose(ctx, "guardian", ms, members, [inner], what);
  if (p.status.__kind !== "Approved") {
    say(`on chain now: ${standing("guardian", ms, index, p)}. Nothing has changed yet: another member approves with ` +
        `node scripts/governance.mjs approve guardian ${index} --member FILE, and the last approval is followed by: node scripts/governance.mjs execute guardian ${index}`);
    process.exitCode = 1;
    return;
  }
  await executeProposal(ctx, "guardian", ms, index, members[0], what);
  if (action === "pause") {
    const until = Number((await state())?.readBigInt64LE(0) ?? 0n);
    say(`on chain now: ${until ? `new funding is refused until ${when(until)}` : "new funding is not paused"} (knos_pay ${IDS.knos_pay}, pause account ${account}). ` +
        "Payments, refunds, withdrawals and binds are never paused.");
  } else {
    say(`on chain now: ${told(keyState(await state()))}.`);
  }
}

// ---- upgrade --------------------------------------------------------------------------------------------------------
/** What `upgrade propose --out` writes: the proposal as data. `executable_from` is null until the proposal is approved,
 *  because the time lock starts with the last approval. */
export function proposalRecord(programRef, program, buffer, hash, index, timeLock, p) {
  const approved = p.status.__kind === "Approved" ? Number(big(p.status.timestamp)) : null;
  return { program: programRef, address: program.toBase58(), buffer: buffer.toBase58(), hash, index: Number(index), status: p.status.__kind,
           approved_at: approved, executable_from: approved === null ? null : approved + timeLock };
}

function programOf(ref) {
  if (ref === "knos_oidc" || ref === "knos_pay") return new PublicKey(IDS[ref]);
  throw new Refused("upgrade takes knos_oidc or knos_pay, then the address of the buffer that holds the new build.");
}

async function upgrade(o, programRef, bufferRef) {
  const program = programOf(programRef);
  if (!bufferRef) throw new Refused("upgrade needs the buffer's address: solana program write-buffer <the verified build> --buffer BUFFER.json");
  const buffer = address(bufferRef);
  const ctx = await context(o);
  const { conn, feePayer } = ctx;
  const { vault } = pinned("upgrade");
  const pdInfo = await conn.getAccountInfo(programData(program), "confirmed");
  const pd = pdInfo && readProgramData(pdInfo.data);
  if (!pd) throw new Refused(`${programRef} ${program} is not deployed on this cluster.`);
  if (!pd.authority?.equals(vault)) {
    throw new Refused(`${programRef}'s upgrade authority is ${pd.authority ?? "none (it was made immutable)"}, not the upgrade vault ${vault}: ` +
                      "the multisig could never execute this upgrade. Nothing was sent.");
  }
  const bufInfo = await conn.getAccountInfo(buffer, "confirmed");
  const buf = bufInfo?.owner.equals(LOADER) ? readBuffer(bufInfo.data) : null;
  if (!buf) throw new Refused(`${buffer} is not a program buffer on this cluster. Write the new build to one: solana program write-buffer <file.so> --buffer BUFFER.json`);
  if (!buf.authority?.equals(vault)) {
    throw new Refused(`the buffer's authority is ${buf.authority ?? "none"}, and the upgrade needs it to be the upgrade vault. Hand it over: ` +
                      `solana program set-buffer-authority ${buffer} --new-buffer-authority ${vault}`);
  }
  if (buf.bytes.length > pd.bytes.length) {
    throw new Refused(`the new build is ${buf.bytes.length} bytes and the program has room for ${pd.bytes.length}. Extend it first: ` +
                      `solana program extend ${program} ${buf.bytes.length - pd.bytes.length}`);
  }
  say(`${programRef} ${program}: on chain ${executableHash(pd.bytes)} (deployed in slot ${pd.slot})`);
  say(`buffer ${buffer}: ${executableHash(buf.bytes)}   <- compare with: solana-verify get-executable-hash programs-v2/target/deploy/${programRef}.so`);
  const hash = executableHash(buf.bytes);
  say(gated(await conn.getAccountInfo(buildRecord(program, hash), "confirmed"), programRef, program, hash, o.ungated));
  const ms = await existing(conn, "upgrade");
  const members = membersOf(ms, o, "upgrade");
  const spill = o.spill ? address(o.spill) : feePayer.publicKey;
  const { index, proposal: p } = await propose(ctx, "upgrade", ms, members, [upgradeIx(program, buffer, vault, spill)], `upgrade ${programRef}`);
  say(`on chain now: ${standing("upgrade", ms, index, p)}. It replaces ${programRef} with the buffer's build ${executableHash(buf.bytes)}; ` +
      `then: node scripts/governance.mjs upgrade execute ${index}`);
  if (o.out) fs.writeFileSync(o.out, JSON.stringify(proposalRecord(programRef, program, buffer, hash, index, ms.timeLock, p), null, 2) + "\n");
}

// ---- approve, cancel, execute ---------------------------------------------------------------------------------------
function proposalArgs(name, indexText) {
  if (!WHICH[name] || !/^\d+$/.test(indexText ?? "")) throw new Refused("give the multisig and the proposal: upgrade or guardian, then the proposal's index (a number).");
  return BigInt(indexText);
}

async function vote(o, name, indexText, cancel) {
  const index = proposalArgs(name, indexText);
  const ctx = await context(o);
  const { multisigPda } = pinned(name);
  const ms = await existing(ctx.conn, name);
  const members = membersOf(ms, o, name);
  let p = await proposal(ctx.conn, multisigPda, index);
  if (!p) throw new Refused(`the ${name} multisig has no proposal ${index}.`);
  const kind = p.status.__kind;
  if (cancel ? kind !== "Approved" : kind !== "Active") {
    if (!cancel && kind === "Approved") { say(`on chain now: ${standing(name, ms, index, p)}. Nothing to do.`); return; }
    throw new Refused(`proposal ${index} of the ${name} multisig is ${kind.toLowerCase()}: ` +
                      (cancel ? "only an approved proposal that was not executed can be cancelled." : "only an active proposal takes approvals."));
  }
  p = await voteUpTo(ctx, name, ms, members, index, cancel, `${cancel ? "cancel" : "approve"} proposal ${index}`);
  say(`on chain now: ${standing(name, ms, index, p)}` + (cancel && p.status.__kind === "Approved" ? `, with ${p.cancelled.length} of the ${ms.threshold} votes that cancel it.` : "."));
}

async function execute(o, name, indexText) {
  const index = proposalArgs(name, indexText);
  const ctx = await context(o);
  const ms = await existing(ctx.conn, name);
  const members = membersOf(ms, o, name);
  await executeProposal(ctx, name, ms, index, members[0], `${name} proposal`, Boolean(o.unchecked));
  const lines = [];
  for (const program of ["knos_oidc", "knos_pay"]) {
    const info = await ctx.conn.getAccountInfo(programData(new PublicKey(IDS[program])), "confirmed");
    const pd = info && readProgramData(info.data);
    if (pd) lines.push(`${program} runs the build ${executableHash(pd.bytes)} (deployed in slot ${pd.slot})`);
  }
  say(`on chain now: proposal ${index} of the ${name} multisig is executed` + (name === "upgrade" && lines.length ? `; ${lines.join("; ")}.` : "."));
}

// ---- no network -----------------------------------------------------------------------------------------------------
function deriveCmd(o) {
  const out = {};
  for (const name of Object.keys(WHICH)) {
    const got = derive(address(createKeyRef(o, name))), want = pinned(name);
    out[name] = { multisig: got.multisigPda.toBase58(), vault: got.vault.toBase58(), pinned: got.multisigPda.equals(want.multisigPda) && got.vault.equals(want.vault) };
  }
  if (!Object.values(out).every((d) => d.pinned)) process.exitCode = 1;
  if (o.json) return say(JSON.stringify(out));
  for (const [name, d] of Object.entries(out)) say(`${name}: multisig ${d.multisig}, vault ${d.vault}: ${d.pinned ? "the pinned addresses" : "NOT the pinned addresses"}`);
}

function innerCmd(o, [kind, ...args]) {
  const payer = address(feePayerRef(o));
  const ix = kind === "guardian" ? guardianInner(args[0], args.slice(1), payer).inner
    : kind === "upgrade" ? upgradeIx(programOf(args[0]), address(args[1] ?? ""), pinned("upgrade").vault, o.spill ? address(o.spill) : payer) : null;
  if (!ix) throw new Refused("inner takes what a proposal would carry: inner guardian pause 600, inner guardian revoke 0 <key hash>, or inner upgrade knos_pay <buffer address>.");
  say(JSON.stringify({ program: ix.programId.toBase58(), data: ix.data.toString("hex"),
                       accounts: ix.keys.map((k) => ({ address: k.pubkey.toBase58(), signer: k.isSigner, writable: k.isWritable })) }));
}

// ---- the command line -----------------------------------------------------------------------------------------------
/** The help is this file's opening comment. */
function usage() {
  const lines = fs.readFileSync(fileURLToPath(import.meta.url), "utf8").split("\n").slice(1);
  return lines.slice(0, lines.findIndex((l) => !l.startsWith("//"))).map((l) => l.slice(3)).join("\n");
}

async function main(argv) {
  const { values: o, positionals: [command, ...rest] } = parseArgs({ args: argv, allowPositionals: true, options: {
    rpc: { type: "string" }, keys: { type: "string" }, "fee-payer": { type: "string" }, member: { type: "string", multiple: true }, threshold: { type: "string" },
    "upgrade-create-key": { type: "string" }, "guardian-create-key": { type: "string" }, spill: { type: "string" }, out: { type: "string" },
    "priority-fee": { type: "string" }, check: { type: "boolean" }, json: { type: "boolean" }, unchecked: { type: "boolean" }, ungated: { type: "boolean" }, help: { type: "boolean", short: "h" } } });
  if (squads.PROGRAM_ID.toBase58() !== IDS.squads_program) throw new Refused(`the Squads SDK is for program ${squads.PROGRAM_ID}, and programs-v2/program_ids.json names ${IDS.squads_program}.`);
  if (o.help || !command) return say(usage());
  if (command === "create") return create(o);
  if (command === "show") return show(o);
  if (command === "guardian") return guardian(o, rest[0], rest.slice(1));
  if (command === "upgrade") {
    const [sub, ...args] = rest;
    if (sub === "propose") return upgrade(o, args[0], args[1]);
    if (sub === "execute") return execute(o, "upgrade", args[0]);
    if (sub === "approve" || sub === "cancel") return vote(o, "upgrade", args[0], sub === "cancel");
    throw new Refused("upgrade takes propose <knos_oidc|knos_pay> <buffer address>, or execute <proposal index> once the delay has passed.");
  }
  if (command === "approve" || command === "cancel") return vote(o, rest[0], rest[1], command === "cancel");
  if (command === "execute") return execute(o, rest[0], rest[1]);
  if (command === "derive") return deriveCmd(o);
  if (command === "inner") return innerCmd(o, rest);
  throw new Refused(`there is no command ${command}. Run node scripts/governance.mjs --help for the list.`);
}

if (process.argv[1] && import.meta.url === pathToFileURL(fs.realpathSync(process.argv[1])).href) {
  process.removeAllListeners("warning");   // an SDK dependency still loads Node's old punycode module; that is not this command's news
  main(process.argv.slice(2)).catch((e) => {
    console.error(e instanceof Refused ? `refused: ${e.message}` : `failed: ${e.stack ?? e}`);
    process.exitCode = 1;
  });
}
