#!/usr/bin/env node
// x402 "knos-order" against a real chain: the server and the client of this folder over one RPC URL.
//
//   node examples/x402_attested/live.mjs run    --rpc URL --key buyer.json --offer offer.json   # serve, pay, be served: one process
//   node examples/x402_attested/live.mjs serve  --rpc URL --offer offer.json [--port 4020]      # the seller's side alone
//   node examples/x402_attested/live.mjs buy    --rpc URL --key buyer.json --url http://host/work/N [--max 50000000] [--mint M]
//   node examples/x402_attested/live.mjs status --rpc URL --order ADDRESS [--program ID]        # escrowed, paid or refunded
//   node examples/x402_attested/live.mjs refund --rpc URL --key any.json --order ADDRESS        # after the deadline: back to the funder
//
// `run`, `buy`, `status` and `refund` print one JSON object. The offer file is offer.devnet.json's shape; docs/X402.md
// has the command the release runs on devnet. No package to install.
import { readFileSync } from "node:fs";

import { v2 } from "../../sdk/settle/index.js";
import { KNOS_PAY, status } from "./attested.mjs";
import { fetchAttested } from "./client.mjs";
import { chainOf, keypair, walletOf } from "./rpc.mjs";
import { server } from "./server.mjs";

const KNOS_OIDC = "FkwZdsYCmzicJMtHLTkPK76bYNVG4WNwkWJBiVWNtF3W";
const [mode, ...rest] = process.argv.slice(2);
const flags = {};
for (let i = 0; i < rest.length; i += 2) flags[rest[i].replace(/^--/, "")] = rest[i + 1];
const need = (name) => { if (!flags[name]) throw new Error(`--${name} is required (the usage is at the top of live.mjs)`); return flags[name]; };
const print = (obj) => console.log(JSON.stringify(obj, (_, v) => (typeof v === "bigint" ? String(v) : v), 1));
const listen = (srv, port) => new Promise((ok) => srv.listen(port, "127.0.0.1", ok));

function offerOf(path) {
  const offer = JSON.parse(readFileSync(path, "utf8"));
  const missing = ["url", "network", "program", "mint", "amount", "workSeconds", "repoId", "issue", "terms", "wfRepo", "wfSha", "seller"].filter((k) => offer[k] === undefined || offer[k] === "");
  if (missing.length) throw new Error(`${path} lacks ${missing.join(", ")}: copy offer.devnet.json and fill every field`);
  return { seq: 0, mode: 0, description: `Issue ${offer.issue} of repository ${offer.repoId}`, ...offer };
}
const deliver = (offer) => async (order) => ({ delivered: offer.delivery ?? null, order, note: "paid when the order's pinned workflow attests the acceptance; refunded to the funder after the deadline otherwise" });

async function main() {
  const chain = chainOf(need("rpc"), Number(flags.wait ?? 60));
  if (mode === "serve") {
    const offer = offerOf(need("offer"));
    await listen(server(offer, chain, deliver(offer)), Number(flags.port ?? 4020));
    return console.error(`selling ${new URL(offer.url).pathname} on http://127.0.0.1:${flags.port ?? 4020} for an order of ${offer.program}`);
  }
  if (mode === "status") return print(await status(chain, flags.program ?? KNOS_PAY, need("order")));
  const key = keypair(need("key"));
  if (mode === "refund") {
    const order = need("order"), got = await chain.account(order);
    if (!got) throw new Error(`there is no order at ${order}: it was paid or refunded already (live.mjs status says which)`);
    const o = v2.readOrder(got.data);
    const ix = await v2.client({ knos_pay: got.owner, knos_oidc: KNOS_OIDC }).refundOrderIx({ relayer: key.address, order, o });
    const transaction = await chain.send([ix], key);
    return print({ transaction, ...await status(chain, got.owner, order) });
  }
  if (mode !== "run" && mode !== "buy") throw new Error("say what to do: run, serve, buy, status or refund (the usage is at the top of live.mjs)");
  let url = flags.url, srv = null, offer = null;
  if (mode === "run") {            // the seller's server on a free local port; the client really connects to it over HTTP
    offer = offerOf(need("offer"));
    srv = server(offer, chain, deliver(offer));
    await listen(srv, 0);
    url = `http://127.0.0.1:${srv.address().port}${new URL(offer.url).pathname}`;
  }
  if (!url) throw new Error("--url is required: the resource to buy");
  try {
    const mint = flags.mint ?? offer?.mint ?? need("mint");
    const limits = { maxAmount: flags.max ?? offer?.amount ?? need("max"), mints: [mint], programs: [flags.program ?? offer?.program ?? KNOS_PAY] };
    const got = await fetchAttested(url, await walletOf(chain, key, mint, flags.token ?? null), limits);
    const program = got.messages.paymentRequired?.accepts[0].extra.program;
    print({ status: got.status, order: got.order ?? null, transaction: got.messages.paymentPayload?.payload.transaction ?? null, payer: key.address,
            delivery: got.body, settlement: got.settlement ?? null, state: got.order ? await status(chain, program, got.order) : null });
    if (got.status !== 200) process.exitCode = 1;
  } finally { if (srv) await new Promise((ok) => srv.close(ok)); }
}

main().catch((e) => { console.error(`live.mjs: ${e.message ?? e}`); process.exitCode = 1; });
