// Proposes a program upgrade through the Squads vault (used by program.yml once the vault is the upgrade
// authority). The buffer must already hold the new ELF and its authority must be the vault:
//   solana program write-buffer knos_escrow.so ; solana program set-buffer-authority <buffer> --new-buffer-authority <vault>
// Creates the vault transaction (loader Upgrade, spill = the proposer) + its proposal and prints both.
// Two members then approve; it executes after the multisig's time lock.
// usage: node scripts/squads_propose_upgrade.mjs <buffer> [proposer-key-path]
import { web3, multisig, connection, loadKey, loadState, loader, KNOS_PROGRAM_ID, send } from "./squads_common.mjs";

const [bufferArg, keyArg] = process.argv.slice(2);
if (!bufferArg) { console.error("usage: squads_propose_upgrade.mjs <buffer> [proposer-key]"); process.exit(2); }
const st = loadState();
const proposer = loadKey(keyArg || process.env.KNOS_UPGRADE_KEY || "devnet-payer-cli.json");
const buffer = new web3.PublicKey(bufferArg);
const binfo = await connection.getAccountInfo(buffer, "confirmed");
if (!binfo || binfo.data.readUInt32LE(0) !== 1 || binfo.data[4] !== 1 || !new web3.PublicKey(binfo.data.subarray(5, 37)).equals(st.vaultPda))
  throw new Error("buffer missing or its authority is not the Squads vault");

const ms = await multisig.accounts.Multisig.fromAccountAddress(connection, st.multisigPda);
const transactionIndex = BigInt(ms.transactionIndex.toString()) + 1n;
const { blockhash } = await connection.getLatestBlockhash("confirmed");
const message = new web3.TransactionMessage({ payerKey: st.vaultPda, recentBlockhash: blockhash,
  instructions: [loader.upgrade({ buffer, spill: proposer.publicKey, authority: st.vaultPda })] });
const memo = `knos escrow upgrade ${process.env.GITHUB_SHA || ""}`.trim();
const tx = new web3.Transaction().add(
  multisig.instructions.vaultTransactionCreate({ multisigPda: st.multisigPda, transactionIndex, creator: proposer.publicKey,
    vaultIndex: st.vaultIndex, ephemeralSigners: 0, transactionMessage: message, memo }),
  multisig.instructions.proposalCreate({ multisigPda: st.multisigPda, transactionIndex, creator: proposer.publicKey }));
const sig = await send(tx, [proposer], `vaultTransactionCreate+proposalCreate #${transactionIndex}`);
const [proposal] = multisig.getProposalPda({ multisigPda: st.multisigPda, transactionIndex });
const [vaultTx] = multisig.getTransactionPda({ multisigPda: st.multisigPda, index: transactionIndex });
console.log(JSON.stringify({ program: KNOS_PROGRAM_ID.toBase58(), multisig: st.multisigPda.toBase58(), vault: st.vaultPda.toBase58(),
  transactionIndex: transactionIndex.toString(), vaultTransaction: vaultTx.toBase58(), proposal: proposal.toBase58(),
  buffer: buffer.toBase58(), signature: sig, threshold: ms.threshold, timeLockSeconds: ms.timeLock,
  next: `2 of ${ms.members.length} members approve; executable ${ms.timeLock}s after approval` }, null, 2));
