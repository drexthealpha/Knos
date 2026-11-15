#!/usr/bin/env node
// A Surfpool network inside this process, for scripts/rehearse_fork.sh: a local fork that reads mainnet-beta's
// accounts as they are asked for, so the USDC mint, the token programs and the Squads program are the real ones, and
// nothing that happens here reaches any cluster.
//
//   node scripts/surfnet.mjs [--fork URL] [--url-file FILE] [--deploy ADDRESS=FILE.so ...]
//
//   --fork URL       the cluster to read accounts from (default https://api.mainnet-beta.solana.com); --offline: none
//   --deploy A=F     put the program file F at the address A, upgradeable by this network's payer (repeat it)
//   --url-file FILE  write the RPC address there once the network answers (it is also the first line printed)
//
// It runs until it is stopped (Ctrl-C, or kill): the RPC port is chosen by the system, so read it from the first
// line. The cheatcodes rehearse_fork.sh uses (surfnet_setTokenAccount, surfnet_timeTravel) are methods of that RPC.
// The package is an optional one: npm ci --prefix scripts installs it on Linux x64 and macOS.
import fs from "node:fs";
import { parseArgs } from "node:util";

const { values: o } = parseArgs({ options: { fork: { type: "string" }, offline: { type: "boolean" }, "url-file": { type: "string" },
                                             deploy: { type: "string", multiple: true } } });
let Surfnet;
try {
  ({ Surfnet } = await import("@solana/surfpool"));
} catch (e) {
  console.error(`stopped: the embedded Surfpool is not installed (${e.code ?? e.message}). Run npm ci --prefix scripts; or start one yourself ` +
                "(surfpool start) and give its address to rehearse_fork.sh as KNOS_FORK_RPC.");
  process.exit(1);
}
const net = Surfnet.startWithConfig(o.offline ? { offline: true } : { offline: false, remoteRpcUrl: o.fork ?? "https://api.mainnet-beta.solana.com" });
for (const pair of o.deploy ?? []) {
  const [programId, soPath] = pair.split("=");
  net.deploy({ programId, soPath });
}
if (o["url-file"]) fs.writeFileSync(o["url-file"], net.rpcUrl + "\n");
console.log(net.rpcUrl);
const stop = () => { try { net.stop(); } finally { process.exit(0); } };
process.on("SIGINT", stop);
process.on("SIGTERM", stop);
setInterval(() => {}, 1 << 30);   // nothing else keeps the process alive
