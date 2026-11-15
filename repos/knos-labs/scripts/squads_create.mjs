// Creates the Knos 2-of-3 Squads v4 multisig on devnet with a time lock (default 300 s: a devnet demo value;
// mainnet would use >= 86400). Members: devnet-payer-cli, devnet-worker1, devnet-worker2, all permissions.
// No config authority: membership, threshold and time-lock changes are themselves 2-of-3 config transactions.
// Refuses if scripts/squads_devnet.json exists; writes only public addresses and signatures there.
import { web3, multisig, connection, loadKey, saveState, STATE_FILE, send } from "./squads_common.mjs";
import { existsSync } from "node:fs";

if (existsSync(STATE_FILE)) { console.error(`${STATE_FILE} exists; refusing to create a second multisig`); process.exit(1); }
const TIME_LOCK = Number(process.env.KNOS_SQUADS_TIMELOCK || 300);
const files = ["devnet-payer-cli.json", "devnet-worker1.json", "devnet-worker2.json"];
const [p, w1, w2] = files.map(loadKey);
const createKey = web3.Keypair.generate();   // one-time seed signer, discarded
const [multisigPda] = multisig.getMultisigPda({ createKey: createKey.publicKey });
const [vaultPda] = multisig.getVaultPda({ multisigPda, index: 0 });
const [programConfigPda] = multisig.getProgramConfigPda({});
const programConfig = await multisig.accounts.ProgramConfig.fromAccountAddress(connection, programConfigPda);

const sigCreate = await multisig.rpc.multisigCreateV2({
  connection, treasury: programConfig.treasury, createKey, creator: p, multisigPda,
  configAuthority: null, threshold: 2, timeLock: TIME_LOCK, rentCollector: null,
  members: [p, w1, w2].map((k) => ({ key: k.publicKey, permissions: multisig.types.Permissions.all() })),
  memo: "knos devnet upgrade authority", sendOptions: { skipPreflight: false },
});
await connection.confirmTransaction(sigCreate, "confirmed");
console.log(`multisigCreateV2: ${sigCreate}`);
const sigFund = await send(new web3.Transaction().add(
  web3.SystemProgram.transfer({ fromPubkey: p.publicKey, toPubkey: vaultPda, lamports: 0.05 * web3.LAMPORTS_PER_SOL })),
  [p], "fund vault");

const ms = await multisig.accounts.Multisig.fromAccountAddress(connection, multisigPda);
const state = {
  cluster: "devnet", squadsProgramId: multisig.PROGRAM_ID.toBase58(),
  multisigPda: multisigPda.toBase58(), vaultIndex: 0, vaultPda: vaultPda.toBase58(),
  threshold: ms.threshold, timeLockSeconds: ms.timeLock,
  members: ms.members.map((m) => ({ key: m.key.toBase58(), permissionsMask: m.permissions.mask })),
  memberKeyFiles: files.map((f) => `~/.knos-test-wallets/${f}`),
  createSignature: sigCreate, fundSignature: sigFund, createdAt: new Date().toISOString(),
};
saveState(state);
console.log(JSON.stringify(state, null, 2));
