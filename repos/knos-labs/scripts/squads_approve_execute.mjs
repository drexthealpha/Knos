// Approves a Squads vault transaction with member keys and, with --execute, executes it once the time lock has passed.
// usage: node scripts/squads_approve_execute.mjs <transactionIndex> [--approve key1,key2] [--execute key]
// Keys are names under KNOS_WALLET_DIR (default ~/.knos-test-wallets) or absolute paths; never printed.
import { web3, multisig, connection, loadKey, loadState, send } from "./squads_common.mjs";

const args = process.argv.slice(2);
const index = BigInt(args[0] ?? NaN);
const opt = (name) => { const i = args.indexOf(name); return i >= 0 ? args[i + 1] : null; };
const st = loadState();
const [proposalPda] = multisig.getProposalPda({ multisigPda: st.multisigPda, transactionIndex: index });
const out = { transactionIndex: index.toString(), proposal: proposalPda.toBase58() };

for (const name of (opt("--approve") || "").split(",").filter(Boolean)) {
  const member = loadKey(name);
  const tx = new web3.Transaction().add(multisig.instructions.proposalApprove({ multisigPda: st.multisigPda,
    transactionIndex: index, member: member.publicKey }));
  out[`approve ${member.publicKey.toBase58()}`] = await send(tx, [member], `proposalApprove #${index} by ${member.publicKey.toBase58()}`);
}

const execKey = opt("--execute");
if (execKey) {
  const member = loadKey(execKey);
  const p = await multisig.accounts.Proposal.fromAccountAddress(connection, proposalPda);
  const ms = await multisig.accounts.Multisig.fromAccountAddress(connection, st.multisigPda);
  if (p.status.__kind !== "Approved") throw new Error(`proposal is ${p.status.__kind}, not Approved`);
  const ready = Number(p.status.timestamp) + Number(ms.timeLock);
  const now = Math.floor(Date.now() / 1000);
  if (now < ready) { console.log(`time lock: executable in ${ready - now}s`); process.exit(3); }
  const { instruction, lookupTableAccounts } = await multisig.instructions.vaultTransactionExecute({ connection,
    multisigPda: st.multisigPda, transactionIndex: index, member: member.publicKey });
  const tx = new web3.Transaction().add(web3.ComputeBudgetProgram.setComputeUnitLimit({ units: 400_000 }), instruction);
  if (lookupTableAccounts.length) throw new Error("lookup tables not supported here");
  out.execute = await send(tx, [member], `vaultTransactionExecute #${index}`);
}
console.log(JSON.stringify(out, null, 2));
