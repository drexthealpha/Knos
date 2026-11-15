// The chain of the example over JSON-RPC: any cluster's URL (https://api.devnet.solana.com at release time), or the
// LiteSVM shim the tests start (tests/_rpc_shim.py). Same shape as chain.mjs's replay, so server.mjs and client.mjs do
// not know which one they talk to. Node and sdk/settle only: the transaction is serialized by sdk/settle and signed
// with Node's own Ed25519.
import { createPrivateKey, sign } from "node:crypto";
import { readFileSync } from "node:fs";

import { FEE_OWNER, SYSTEM, accountInfo, ata, b58, chainTime, confirmed, messageOf, rpc, said, serializeTx } from "../../sdk/settle/index.js";

const PKCS8 = Buffer.from("302e020100300506032b657004220420", "hex");     // the DER in front of a raw Ed25519 seed
const BUDGET = "ComputeBudget111111111111111111111111111111";
const UNITS = 400_000;       // FundOrderWallet and RefundOrder each fit well inside; the default of 200,000 is not promised to

/** A key file as `solana-keygen new` writes it: a JSON array of 64 bytes (the seed, then the public key). */
export function keypair(path) {
  const raw = Uint8Array.from(JSON.parse(readFileSync(path, "utf8")));
  if (raw.length !== 64) throw new Error(`${path} is not a Solana key file: expected a JSON array of 64 numbers (solana-keygen new -o ${path})`);
  const secret = createPrivateKey({ key: Buffer.concat([PKCS8, raw.subarray(0, 32)]), format: "der", type: "pkcs8" });
  return { address: b58(raw.subarray(32)), sign: (message) => new Uint8Array(sign(null, message, secret)) };
}

/** { now, account, logs, send } against `url`. `seconds`: how long send waits for the cluster to confirm. */
export function chainOf(url, seconds = 60) {
  return {
    url,
    now: () => chainTime(url),
    account: async (address) => { const a = await accountInfo(url, address); return a && { owner: a.owner, data: a.data }; },
    /** Which knos_pay runs at `program`, asked of the program itself (Version, simulated: nothing is sent or paid): 2 is
     *  knos_pay 2.2 (the 0.30% fee), 1 is 2.1 and 0 is 2.0 (the older tiered fee, at least 0.40), null when the cluster did not say. */
    async payVersion(program) {
      try {
        const tx = serializeTx([{ program, data: Uint8Array.of(12), accounts: [] }], FEE_OWNER, SYSTEM);
        const sim = (await rpc(url, "simulateTransaction", [Buffer.from(tx).toString("base64"), { encoding: "base64", sigVerify: false, replaceRecentBlockhash: true, commitment: "confirmed" }])).value;
        const line = (sim.logs || []).find((l) => /Program log: knos2:version \d+$/.test(l));
        if (line) return Number(line.split(" ").at(-1));
        return JSON.stringify(sim.err ?? null).includes("InvalidInstructionData") ? 0 : null;
      } catch { return null; }
    },
    /** Every line a program logged in a transaction that named `address`, oldest first (an order's whole history). */
    async logs(address) {
      const sigs = await rpc(url, "getSignaturesForAddress", [address, { limit: 100, commitment: "confirmed" }]);
      const out = [];
      for (const s of (sigs || []).filter((x) => !x.err).reverse()) {
        const tx = await rpc(url, "getTransaction", [s.signature, { encoding: "json", commitment: "confirmed", maxSupportedTransactionVersion: 1 }]);
        out.push(...said(tx?.meta?.logMessages));
      }
      return out;
    },
    /** Signs `ixs` with `key` (which also pays the transaction fee), sends, and waits. Returns the signature. */
    async send(ixs, key) {
      const budget = { program: BUDGET, data: Uint8Array.of(2, UNITS & 255, (UNITS >> 8) & 255, (UNITS >> 16) & 255, 0), accounts: [] };
      const { blockhash } = (await rpc(url, "getLatestBlockhash", [{ commitment: "confirmed" }])).value;
      const tx = serializeTx([budget, ...ixs], key.address, blockhash);
      tx.set(key.sign(messageOf(tx)), 1);
      const signature = await rpc(url, "sendTransaction", [Buffer.from(tx).toString("base64"), { encoding: "base64", preflightCommitment: "confirmed" }]);
      const done = await confirmed(url, signature, seconds);
      if (!done) throw new Error(`the cluster did not confirm ${signature} within ${seconds} seconds: look it up before sending again`);
      if (!done.ok) throw new Error(`transaction ${signature} failed: ${JSON.stringify(done.err)}`);
      return signature;
    },
  };
}

/** The wallet client.mjs wants: its address, its token account of `mint` (default: the associated one), and send. */
export async function walletOf(chain, key, mint, token = null) {
  return { address: key.address, token: token ?? await ata(key.address, mint), send: (ix) => chain.send([ix], key) };
}
