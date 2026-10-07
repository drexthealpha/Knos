#!/usr/bin/env node
// The SELLER agent: it lists the work it does (GET /tasks), sells one task under the x402 "knos-order" scheme, and
// delivers once the buyer's order is funded on chain. It is paid by the escrow when the evaluator accepts, never by
// the buyer and never before. Its key file only names where the money goes: this script signs nothing.
//
//   node examples/agent_pays_agent/seller.mjs --rpc URL --key seller.json --offer offer.json [--port 4021] [--wrong]
//   node examples/agent_pays_agent/seller.mjs --devnet --key seller.json --offer offer.json
//
// --wrong: deliver work that does not meet the task (the second run of the story). No package to install.
import { readFileSync } from "node:fs";
import http from "node:http";

import { KNOS_PAY } from "../x402_attested/attested.mjs";
import { chainOf, keypair } from "../x402_attested/rpc.mjs";
import { server } from "../x402_attested/server.mjs";
import { DEVNET_RPC, DEVNET_USDC, KIND, digest, work, wrongWork } from "./work.mjs";

const flags = {};
const args = process.argv.slice(2);
for (let i = 0; i < args.length; i++) {
  const name = args[i].replace(/^--/, "");
  if (name === "wrong" || name === "devnet") flags[name] = true; else flags[name] = args[++i];
}
const need = (name) => { if (!flags[name]) throw new Error(`--${name} is required (the usage is at the top of seller.mjs)`); return flags[name]; };

async function main() {
  const rpc = flags.devnet ? flags.rpc ?? DEVNET_RPC : need("rpc");
  const key = keypair(need("key"));
  const offer = JSON.parse(readFileSync(need("offer"), "utf8"));
  if (flags.devnet) Object.assign(offer, { program: offer.program || KNOS_PAY, mint: offer.mint || DEVNET_USDC });
  offer.seller = { ...offer.seller, wallet: key.address };          // the payee is this agent's own account
  const missing = ["url", "network", "program", "mint", "amount", "workSeconds", "repoId", "issue", "terms", "wfRepo", "wfSha", "task"].filter((k) => offer[k] === undefined || offer[k] === "");
  if (missing.length || !offer.seller.githubId) throw new Error(`the offer lacks ${[...missing, ...(offer.seller.githubId ? [] : ["seller.githubId"])].join(", ")}: copy offer.devnet.json and fill every field`);
  const task = offer.task, path = new URL(offer.url).pathname;
  const full = { seq: 0, mode: 0, description: `Task ${task.id}: ${task.title}`, ...offer };
  const deliver = async (order) => {
    const result = (flags.wrong ? wrongWork : work)(task.input);
    return { task: task.id, kind: KIND, result, digest: digest(result), order,
             note: "paid when the evaluator's signed acceptance reaches the escrow; refunded to the funder after the deadline otherwise" };
  };
  const shop = server(full, chainOf(rpc, Number(flags.wait ?? 60)), deliver);
  const srv = http.createServer((req, res) => {
    if (new URL(req.url, "http://local").pathname !== "/tasks") return shop.emit("request", req, res);
    res.writeHead(200, { "content-type": "application/json" });
    res.end(JSON.stringify({ tasks: [{ id: task.id, kind: KIND, title: task.title, input: task.input, path, scheme: "knos-order",
                                       amount: String(full.amount), asset: full.mint, payee: key.address }] }));
  });
  await new Promise((ok) => srv.listen(Number(flags.port ?? 4021), "127.0.0.1", ok));
  console.log(JSON.stringify({ listening: srv.address().port, payee: key.address, task: task.id, wrong: Boolean(flags.wrong) }));
}

main().catch((e) => { console.error(`seller.mjs: ${e.message ?? e}`); process.exitCode = 1; });
