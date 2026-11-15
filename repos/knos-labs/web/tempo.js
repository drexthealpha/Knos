// Tempo passkey wallet: no extension, no seed phrase. A passkey on this device signs Tempo transactions
// (viem 2.57.2 `viem/tempo`: WebAuthnP256.createCredential + Account.fromWebAuthnP256, chain tempoModerato).
// Jobs go to the Knos escrow contract on Moderato; on Tempo a job id is the sha256 of its brief, so the brief on
// the relay is checked against the id itself.
const V = "2.57.2";
export const ESCROW = "0x8B913C5946a4C1CD95089D7a563dB864d46b694E";   // KnosEscrow 0.3.6 on Moderato (testnet): ERC-8183, verifier rule, 2.5% fee
export const ESCROW_V031 = "0x888d39bB186cC718481E98080Bdb5fd8Df27Ab49";   // the 0.3.1 contract: its jobs settle there
export const PATH_USD = "0x20C0000000000000000000000000000000000000";
const STORE = "knos-tempo-passkey";
const STATES = ["none", "open", "claimed", "delivered", "released", "refunded"];

const ESCROW_ABI = [
  { type: "function", name: "post", stateMutability: "nonpayable", inputs: [{ name: "id", type: "bytes32" }, { name: "amount", type: "uint128" }, { name: "work", type: "uint64" }], outputs: [] },
  { type: "function", name: "postWithVerifier", stateMutability: "nonpayable", inputs: [{ name: "id", type: "bytes32" }, { name: "amount", type: "uint128" }, { name: "work", type: "uint64" }, { name: "verifier", type: "address" }], outputs: [] },
  { type: "function", name: "accept", stateMutability: "nonpayable", inputs: [{ name: "id", type: "bytes32" }], outputs: [] },
  { type: "function", name: "reject", stateMutability: "nonpayable", inputs: [{ name: "id", type: "bytes32" }], outputs: [] },
  { type: "function", name: "jobs", stateMutability: "view", inputs: [{ name: "", type: "bytes32" }], outputs: [
    { name: "buyer", type: "address" }, { name: "worker", type: "address" }, { name: "amount", type: "uint128" },
    { name: "deadline", type: "uint64" }, { name: "state", type: "uint8" }, { name: "result", type: "bytes32" },
    { name: "verifier", type: "address" }, { name: "proof", type: "bytes32" }] },
];
const ESCROW_V031_ABI = [...ESCROW_ABI.filter((f) => f.name !== "jobs" && f.name !== "postWithVerifier"),
  { ...ESCROW_ABI.find((f) => f.name === "jobs"), outputs: ESCROW_ABI.find((f) => f.name === "jobs").outputs.slice(0, 6) }];
const ZERO_ADDR = "0x0000000000000000000000000000000000000000";
const TOKEN_ABI = [
  { type: "function", name: "approve", stateMutability: "nonpayable", inputs: [{ name: "s", type: "address" }, { name: "v", type: "uint256" }], outputs: [{ type: "bool" }] },
  { type: "function", name: "balanceOf", stateMutability: "view", inputs: [{ name: "a", type: "address" }], outputs: [{ type: "uint256" }] },
];

let libs;
export async function load() {
  libs ||= Promise.all([
    import(`https://cdn.jsdelivr.net/npm/viem@${V}/+esm`),
    import(`https://cdn.jsdelivr.net/npm/viem@${V}/chains/+esm`),
    import(`https://cdn.jsdelivr.net/npm/viem@${V}/tempo/+esm`),
  ]).then(([viem, chains, tempo]) => ({ viem, chain: chains.tempoModerato.extend({ feeToken: PATH_USD }), tempo }));
  return libs;
}

function saved() { try { return JSON.parse(localStorage.getItem(STORE) || "null"); } catch { return null; } }

/** Create a passkey wallet, or sign in with the one this device already has. */
export async function passkeyAccount() {
  const { tempo } = await load();
  const known = saved();
  let credential;
  if (known) {
    credential = await tempo.WebAuthnP256.getCredential({ async getPublicKey() { return known.publicKey; } });
  } else {
    credential = await tempo.WebAuthnP256.createCredential({ name: "Knos" });
    try { localStorage.setItem(STORE, JSON.stringify({ id: credential.id, publicKey: credential.publicKey })); } catch {}
  }
  return tempo.Account.fromWebAuthnP256(credential);
}

export async function clients(account) {
  const { viem, chain } = await load();
  const transport = viem.http();
  return { pub: viem.createPublicClient({ chain, transport }), wallet: account ? viem.createWalletClient({ chain, transport, account }) : null, viem };
}

export async function balance(address) {
  const { pub } = await clients();
  return Number(await pub.readContract({ address: PATH_USD, abi: TOKEN_ABI, functionName: "balanceOf", args: [address] })) / 1e6;
}

/** Moderato's own faucet (`tempo_fundAddress`): free testnet stablecoins. */
export async function fund(address) {
  const { pub } = await clients();
  return pub.request({ method: "tempo_fundAddress", params: [address] });
}

/** Post a job: brief to the relay, then approve + post on the escrow. Returns the job id. */
export async function postJob(account, relay, { task, kind, priceUsd, workSeconds = 3600, sealTo = null, verifier = null }) {
  const { pub, wallet, viem } = await clients(account);
  const brief = new TextEncoder().encode(JSON.stringify({ title: task.split("\n")[0].slice(0, 80), task, kind,
    buyer: account.address, price_units: Math.round(priceUsd * 1e6), created: Math.floor(Date.now() / 1000), chain: "tempo-moderato",
    seal_to: sealTo }));
  const put = await fetch(`${relay}/briefs`, { method: "PUT", body: brief });
  if (!put.ok) throw new Error("The relay did not take the brief.");
  const { hash } = await put.json();
  const id = `0x${hash}`;
  if (viem.sha256(brief) !== id) throw new Error("The relay stored something else.");
  const amount = BigInt(Math.round(priceUsd * 1e6));
  if (amount < 1000000n) throw new Error("The minimum job is 1 USDC.");
  const a = await wallet.writeContract({ address: PATH_USD, abi: TOKEN_ABI, functionName: "approve", args: [ESCROW, amount] });
  await pub.waitForTransactionReceipt({ hash: a });
  const p = verifier
    ? await wallet.writeContract({ address: ESCROW, abi: ESCROW_ABI, functionName: "postWithVerifier", args: [id, amount, BigInt(workSeconds), verifier] })
    : await wallet.writeContract({ address: ESCROW, abi: ESCROW_ABI, functionName: "post", args: [id, amount, BigInt(workSeconds)] });
  const r = await pub.waitForTransactionReceipt({ hash: p });
  if (r.status !== "success") throw new Error("The escrow refused the post.");
  return id;
}

/** A job from the 0.3.4 contract, or (if it is not there) from the 0.3.1 one; `contract` says which. */
export async function job(id) {
  const { pub } = await clients();
  const [buyer, worker, amount, deadline, state, result, verifier, proof] = await pub.readContract({ address: ESCROW, abi: ESCROW_ABI, functionName: "jobs", args: [id] });
  if (state === 0) {
    const old = await pub.readContract({ address: ESCROW_V031, abi: ESCROW_V031_ABI, functionName: "jobs", args: [id] });
    if (old[4] !== 0) return { id, buyer: old[0], worker: old[1], amount: Number(old[2]) / 1e6, deadline: Number(old[3]),
      state: STATES[old[4]], result: old[5], verifier: null, proof: null, contract: ESCROW_V031 };
  }
  return { id, buyer, worker, amount: Number(amount) / 1e6, deadline: Number(deadline), state: STATES[state], result,
    verifier: verifier === ZERO_ADDR ? null : verifier, proof: /^0x0+$/.test(proof) ? null : proof, contract: ESCROW };
}

export async function settle(account, id, verb) {
  const { pub, wallet } = await clients(account);
  const where = (await job(id)).contract;
  const h = await wallet.writeContract({ address: where, abi: where === ESCROW ? ESCROW_ABI : ESCROW_V031_ABI, functionName: verb, args: [id] });
  return pub.waitForTransactionReceipt({ hash: h });
}
