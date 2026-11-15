// Proposes escrow admin instructions through the Squads vault (the escrow admin since the handover): one vault
// transaction + proposal per group, in order, so a group may depend on an earlier one (an issuer before its keys).
// Each group must fit one transaction (a RegisterKey is ~560 bytes: one per group). The time locks run concurrently.
// usage: node scripts/squads_propose_ixs.mjs <groups.json> [proposer-key] [--approve key1,key2]
//   groups.json: [{"label": "...", "ixs": [{"programId", "data" (base64), "keys": [{pubkey, isSigner, isWritable}]}]}]
// Then, after the time lock: node scripts/squads_approve_execute.mjs <index> --execute <key>  (in index order).
import { readFileSync } from "node:fs";
import { web3, multisig, connection, loadKey, loadState, send } from "./squads_common.mjs";

const args = process.argv.slice(2);
const opt = (name) => { const i = args.indexOf(name); return i >= 0 ? args[i + 1] : null; };
const groups = JSON.parse(readFileSync(args[0], "utf8"));
const st = loadState();
const proposer = loadKey(args[1] && !args[1].startsWith("--") ? args[1] : "devnet-payer-cli.json");
const approvers = (opt("--approve") || "").split(",").filter(Boolean).map(loadKey);
const out = [];
for (const g of groups) {
  const ms = await multisig.accounts.Multisig.fromAccountAddress(connection, st.multisigPda);
  const transactionIndex = BigInt(ms.transactionIndex.toString()) + 1n;
  const { blockhash } = await connection.getLatestBlockhash("confirmed");
  const instructions = g.ixs.map((ix) => new web3.TransactionInstruction({ programId: new web3.PublicKey(ix.programId),
    data: Buffer.from(ix.data, "base64"),
    keys: ix.keys.map((k) => ({ pubkey: new web3.PublicKey(k.pubkey), isSigner: k.isSigner, isWritable: k.isWritable })) }));
  const message = new web3.TransactionMessage({ payerKey: st.vaultPda, recentBlockhash: blockhash, instructions });
  const tx = new web3.Transaction().add(
    multisig.instructions.vaultTransactionCreate({ multisigPda: st.multisigPda, transactionIndex, creator: proposer.publicKey,
      vaultIndex: st.vaultIndex, ephemeralSigners: 0, transactionMessage: message }),
    multisig.instructions.proposalCreate({ multisigPda: st.multisigPda, transactionIndex, creator: proposer.publicKey }));
  const row = { label: g.label, transactionIndex: transactionIndex.toString(),
    create: await send(tx, [proposer], `propose #${transactionIndex} ${g.label}`) };
  for (const m of approvers) {
    const a = new web3.Transaction().add(multisig.instructions.proposalApprove({ multisigPda: st.multisigPda,
      transactionIndex, member: m.publicKey }));
    row[`approve ${m.publicKey.toBase58()}`] = await send(a, [m], `approve #${transactionIndex}`);
  }
  out.push(row);
}
console.log(JSON.stringify(out, null, 2));
