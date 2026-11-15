// Shared helpers for the Knos Squads v4 scripts (devnet). Resolves @sqds/multisig + @solana/web3.js from
// KNOS_SQUADS_NODE_DIR (a directory with those packages in node_modules; default: the current directory).
// Keys are read from KNOS_WALLET_DIR (default ~/.knos-test-wallets) or given as absolute paths; never printed.
import { createRequire } from "node:module";
import { readFileSync, writeFileSync, existsSync } from "node:fs";
import { homedir } from "node:os";
import { join, dirname, isAbsolute } from "node:path";
import { fileURLToPath } from "node:url";

const req = createRequire(join(process.env.KNOS_SQUADS_NODE_DIR || process.cwd(), "package.json"));
export const web3 = req("@solana/web3.js");
export const multisig = req("@sqds/multisig");

export const RPC_URL = process.env.KNOS_SOLANA_RPC || "https://api.devnet.solana.com";
if (!/devnet|localhost|127\.0\.0\.1/.test(RPC_URL) && !process.env.KNOS_ALLOW_MAINNET)
  throw new Error("devnet only: set KNOS_ALLOW_MAINNET to point these scripts elsewhere");
export const connection = new web3.Connection(RPC_URL, "confirmed");
export const SQUADS_PROGRAM_ID = new web3.PublicKey("SQDS4ep65T869zMMBKyuUq6aD6EgTu8psMjkvj52pCf");
if (!multisig.PROGRAM_ID.equals(SQUADS_PROGRAM_ID)) throw new Error("SDK program id mismatch");
export const KNOS_PROGRAM_ID = new web3.PublicKey(process.env.KNOS_ESCROW_PROGRAM_ID || "GwmbMFvyHHwHug5em9dv26oXz2zTgXKGsNdrBxPayRPq");
export const LOADER = new web3.PublicKey("BPFLoaderUpgradeab1e11111111111111111111111");
export const TOKEN = new web3.PublicKey("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA");
export const ATA_PROGRAM = new web3.PublicKey("ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL");

const WALLETS = process.env.KNOS_WALLET_DIR || join(homedir(), ".knos-test-wallets");
export function loadKey(nameOrPath) {
  const p = isAbsolute(nameOrPath) ? nameOrPath : join(WALLETS, nameOrPath);
  return web3.Keypair.fromSecretKey(Uint8Array.from(JSON.parse(readFileSync(p, "utf8"))));
}

export const STATE_FILE = process.env.KNOS_SQUADS_STATE || join(dirname(fileURLToPath(import.meta.url)), "squads_devnet.json");
export function loadState() {
  if (!existsSync(STATE_FILE)) throw new Error(`missing ${STATE_FILE}; run squads_create.mjs first`);
  const s = JSON.parse(readFileSync(STATE_FILE, "utf8"));
  return { ...s, multisigPda: new web3.PublicKey(s.multisigPda), vaultPda: new web3.PublicKey(s.vaultPda) };
}
export const saveState = (o) => writeFileSync(STATE_FILE, JSON.stringify(o, null, 2) + "\n");

export const programDataAddress = (pid = KNOS_PROGRAM_ID) => web3.PublicKey.findProgramAddressSync([pid.toBuffer()], LOADER)[0];
// ProgramData: u32 tag(3) | u64 slot | u8 option | [32] authority | ELF
export async function upgradeAuthority(pid = KNOS_PROGRAM_ID) {
  const info = await connection.getAccountInfo(programDataAddress(pid), "confirmed");
  if (!info || info.data.readUInt32LE(0) !== 3) throw new Error("no ProgramData account");
  return info.data[12] === 1 ? new web3.PublicKey(info.data.subarray(13, 45)) : null;
}
export const configPda = (pid = KNOS_PROGRAM_ID) => web3.PublicKey.findProgramAddressSync([Buffer.from("config2")], pid)[0];
// config2: admin(32) mint(32) fee_token(32) ...
export async function readConfig(pid = KNOS_PROGRAM_ID) {
  const info = await connection.getAccountInfo(configPda(pid), "confirmed");
  if (!info) throw new Error("no config2 account");
  const pk = (o) => new web3.PublicKey(info.data.subarray(o, o + 32));
  return { admin: pk(0), mint: pk(32), feeToken: pk(64) };
}
export const ata = (owner, mint) =>
  web3.PublicKey.findProgramAddressSync([owner.toBuffer(), TOKEN.toBuffer(), mint.toBuffer()], ATA_PROGRAM)[0];
export const createAtaIdempotent = (payer, owner, mint) => new web3.TransactionInstruction({
  programId: ATA_PROGRAM, data: Buffer.from([1]),
  keys: [{ pubkey: payer, isSigner: true, isWritable: true }, { pubkey: ata(owner, mint), isSigner: false, isWritable: true },
    { pubkey: owner, isSigner: false, isWritable: false }, { pubkey: mint, isSigner: false, isWritable: false },
    { pubkey: web3.SystemProgram.programId, isSigner: false, isWritable: false }, { pubkey: TOKEN, isSigner: false, isWritable: false }] });

const u32 = (n) => { const b = Buffer.alloc(4); b.writeUInt32LE(n); return b; };
const RENT = new web3.PublicKey("SysvarRent111111111111111111111111111111111");
const CLOCK = new web3.PublicKey("SysvarC1ock11111111111111111111111111111111");
export const loader = {
  // account = ProgramData (for a program) or the buffer itself. Tag 4 (SetAuthority): the new authority need not sign.
  setAuthority: ({ account, current, next }) => new web3.TransactionInstruction({ programId: LOADER, data: u32(4),
    keys: [{ pubkey: account, isSigner: false, isWritable: true }, { pubkey: current, isSigner: true, isWritable: false },
      { pubkey: next, isSigner: false, isWritable: false }] }),
  // Tag 9 ExtendProgramChecked {additional_bytes u32}: the upgrade authority signs (a program with an authority can
  // no longer be extended by anyone else); the payer funds the rent.
  extendChecked: ({ programId = KNOS_PROGRAM_ID, authority, payer, bytes }) => new web3.TransactionInstruction({ programId: LOADER,
    data: Buffer.concat([u32(9), u32(bytes)]),
    keys: [{ pubkey: programDataAddress(programId), isSigner: false, isWritable: true }, { pubkey: programId, isSigner: false, isWritable: true },
      { pubkey: authority, isSigner: true, isWritable: false }, { pubkey: web3.SystemProgram.programId, isSigner: false, isWritable: false },
      { pubkey: payer, isSigner: true, isWritable: true }] }),
  upgrade: ({ programId = KNOS_PROGRAM_ID, buffer, spill, authority }) => new web3.TransactionInstruction({ programId: LOADER, data: u32(3),
    keys: [{ pubkey: programDataAddress(programId), isSigner: false, isWritable: true }, { pubkey: programId, isSigner: false, isWritable: true },
      { pubkey: buffer, isSigner: false, isWritable: true }, { pubkey: spill, isSigner: false, isWritable: true },
      { pubkey: RENT, isSigner: false, isWritable: false }, { pubkey: CLOCK, isSigner: false, isWritable: false },
      { pubkey: authority, isSigner: true, isWritable: false }] }),
};

// Escrow admin instructions (programs/knos_escrow/src/lib.rs; src/knos/jobs/sol.py set_admin/set_fee_account):
//   27 SetAdmin:      admin(s) config2(w)            data: 27 | new_admin[32]
//   28 SetFeeAccount: admin(s) config2(w) fee_token  data: 28
// squads_handover.mjs simulates first, so a layout mismatch stops before anything is sent.
export const escrow = {
  setAdmin: ({ admin, next, pid = KNOS_PROGRAM_ID }) => new web3.TransactionInstruction({ programId: pid,
    data: Buffer.concat([Buffer.from([27]), next.toBuffer()]),
    keys: [{ pubkey: admin, isSigner: true, isWritable: false }, { pubkey: configPda(pid), isSigner: false, isWritable: true }] }),
  setFeeAccount: ({ admin, feeToken, pid = KNOS_PROGRAM_ID }) => new web3.TransactionInstruction({ programId: pid, data: Buffer.from([28]),
    keys: [{ pubkey: admin, isSigner: true, isWritable: false }, { pubkey: configPda(pid), isSigner: false, isWritable: true },
      { pubkey: feeToken, isSigner: false, isWritable: false }] }),
};

export async function send(tx, signers, label) {
  const sig = await web3.sendAndConfirmTransaction(connection, tx, signers, { commitment: "confirmed" });
  console.log(`${label}: ${sig}`);
  return sig;
}
