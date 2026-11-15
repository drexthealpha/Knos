// One-shot handover of the devnet escrow to the Squads vault, in ONE transaction signed by the current
// upgrade authority / escrow admin (devnet-payer-cli):
//   1. create the vault's ATA for the config mint (idempotent)
//   2. escrow SetFeeAccount (28) -> the vault's ATA
//   3. escrow SetAdmin (27)      -> the vault PDA
//   4. BPF loader SetAuthority   -> program upgrade authority = the vault PDA
// Needs the 0.3.8 program (tags 27/28) deployed. Simulates first; prints the plan and stops unless --send.
// After this, every upgrade is a Squads proposal (scripts/squads_propose_upgrade.mjs) under the time lock.
import { web3, connection, loadKey, loadState, readConfig, upgradeAuthority, programDataAddress, ata,
  createAtaIdempotent, escrow, loader, KNOS_PROGRAM_ID, send } from "./squads_common.mjs";

const st = loadState();
const signer = loadKey(process.env.KNOS_UPGRADE_KEY || "devnet-payer-cli.json");
const vault = st.vaultPda;
const cfg = await readConfig();
const auth = await upgradeAuthority();
const vaultAta = ata(vault, cfg.mint);
console.log(JSON.stringify({ program: KNOS_PROGRAM_ID.toBase58(), multisig: st.multisigPda.toBase58(), vault: vault.toBase58(),
  timeLockSeconds: st.timeLockSeconds, upgradeAuthority: auth?.toBase58() ?? null, escrowAdmin: cfg.admin.toBase58(),
  feeToken: cfg.feeToken.toBase58(), newFeeToken: vaultAta.toBase58(), signer: signer.publicKey.toBase58() }, null, 2));

const ixs = [createAtaIdempotent(signer.publicKey, vault, cfg.mint)];
if (!cfg.feeToken.equals(vaultAta)) ixs.push(escrow.setFeeAccount({ admin: signer.publicKey, feeToken: vaultAta }));
if (!cfg.admin.equals(vault)) {
  if (!cfg.admin.equals(signer.publicKey)) throw new Error("signer is not the escrow admin");
  ixs.push(escrow.setAdmin({ admin: signer.publicKey, next: vault }));
}
if (!(auth && auth.equals(vault))) {
  if (!(auth && auth.equals(signer.publicKey))) throw new Error("signer is not the upgrade authority");
  ixs.push(loader.setAuthority({ account: programDataAddress(), current: signer.publicKey, next: vault }));
}
if (ixs.length === 1) { console.log("already handed over"); process.exit(0); }

const tx = new web3.Transaction().add(...ixs);
tx.feePayer = signer.publicKey;
tx.recentBlockhash = (await connection.getLatestBlockhash("confirmed")).blockhash;
const sim = await connection.simulateTransaction(tx, [signer]);
if (sim.value.err) {
  console.error("simulation failed:", JSON.stringify(sim.value.err));
  for (const l of sim.value.logs || []) console.error("  " + l);
  process.exit(1);
}
console.log(`simulation ok (${ixs.length} instructions, ${sim.value.unitsConsumed} CU)`);
if (!process.argv.includes("--send")) { console.log("dry run; pass --send to hand over"); process.exit(0); }
const sig = await send(tx, [signer], "handover (fee account, admin, upgrade authority -> vault)");
const after = await readConfig();
console.log(JSON.stringify({ signature: sig, upgradeAuthority: (await upgradeAuthority())?.toBase58(),
  escrowAdmin: after.admin.toBase58(), feeToken: after.feeToken.toBase58() }, null, 2));
