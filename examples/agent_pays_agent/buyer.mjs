#!/usr/bin/env node
// The BUYER agent: it reads a seller's board, picks a task of the kind it needs within its limit, and opens an order
// through the x402 "knos-order" scheme: the 402 names an escrow, this agent funds it with its own key and asks again.
// Its money is then in the order's own account. It goes to the seller only on the evaluator's signed acceptance and
// comes back whole after the deadline otherwise.
//
//   node examples/agent_pays_agent/buyer.mjs --rpc URL --key buyer.json --board http://127.0.0.1:4021 --mint MINT --max 20000000
//   node examples/agent_pays_agent/buyer.mjs --devnet --key buyer.json --board http://127.0.0.1:4021 --max 5000000
//
// Prints one JSON object: the task, the order, the funding transaction, the delivery and where the order stands.
import { KNOS_PAY, status } from "../x402_attested/attested.mjs";
import { fetchAttested } from "../x402_attested/client.mjs";
import { chainOf, keypair, walletOf } from "../x402_attested/rpc.mjs";
import { DEVNET_RPC, DEVNET_USDC, KIND } from "./work.mjs";

const flags = {};
const args = process.argv.slice(2);
for (let i = 0; i < args.length; i++) {
  const name = args[i].replace(/^--/, "");
  if (name === "devnet") flags[name] = true; else flags[name] = args[++i];
}
const need = (name) => { if (!flags[name]) throw new Error(`--${name} is required (the usage is at the top of buyer.mjs)`); return flags[name]; };

async function main() {
  const rpc = flags.devnet ? flags.rpc ?? DEVNET_RPC : need("rpc");
  const mint = flags.mint ?? (flags.devnet ? DEVNET_USDC : need("mint"));
  const program = flags.program ?? KNOS_PAY, max = BigInt(need("max"));
  const key = keypair(need("key")), board = need("board").replace(/\/$/, "");
  const chain = chainOf(rpc, Number(flags.wait ?? 60));
  // 1. find a task: the kind this agent needs, paid in the mint it holds, within its limit; the cheapest first
  const listed = (await (await fetch(`${board}/tasks`)).json()).tasks ?? [];
  const fits = listed.filter((t) => t.kind === (flags.kind ?? KIND) && t.scheme === "knos-order" && t.asset === mint && BigInt(t.amount) <= max)
    .sort((a, b) => (BigInt(a.amount) < BigInt(b.amount) ? -1 : 1));
  if (!fits.length) throw new Error(`no ${flags.kind ?? KIND} task on ${board} is paid in ${mint} for ${max} or less`);
  const task = fits[0];
  // an order whose payee is its own funder proves nothing: the program records such a payment as self-paid
  if (task.payee === key.address) throw new Error("the payee is this buyer's own account: the payee must be an account other than the funder");
  // 2. open the order: read the 402, check it, fund the escrow, ask again (client.mjs does each check)
  const got = await fetchAttested(`${board}${task.path}`, await walletOf(chain, key, mint, flags.token ?? null), { maxAmount: String(max), mints: [mint], programs: [program] });
  const req = got.messages.paymentRequired?.accepts[0];
  console.log(JSON.stringify({ status: got.status, task: { id: task.id, kind: task.kind, input: task.input }, payer: key.address, payee: req?.payTo ?? null,
                               order: got.order ?? null, transaction: got.messages.paymentPayload?.payload.transaction ?? null,
                               amount: req?.amount ?? null, fee: req?.extra.fee ?? null, delivery: got.body,
                               state: got.order ? await status(chain, program, got.order) : null }, null, 1));
  if (got.status !== 200) process.exitCode = 1;
}

main().catch((e) => { console.error(`buyer.mjs: ${e.message ?? e}`); process.exitCode = 1; });
