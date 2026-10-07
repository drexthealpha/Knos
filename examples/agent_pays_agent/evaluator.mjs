#!/usr/bin/env node
// The EVALUATOR: neither the buyer nor the seller. It reads the task and what was delivered and says accepted or not.
// Exit 0: accepted. Exit 1: not accepted. That is all the judging there is.
//
//   node examples/agent_pays_agent/evaluator.mjs --task task.json --delivery delivery.json
//
// Its signature is not made here. knos_pay releases an order on one thing only: a token GitHub signed for a run of
// the workflow the order pinned when it was funded, verified on chain by knos-oidc. So the evaluator is this script
// run as the `test` check of that workflow's repository: when it exits 0 and the delivery is merged, the pinned
// workflow asks GitHub for the token that names the order and the payee. When it exits 1 no token exists, and no
// key held by the buyer, the seller or Knos can stand in for it. In the tests the signing key is a test key that only
// a test build of the programs trusts (tests/test_agent_pays_agent.py).
import { readFileSync } from "node:fs";

import { judge } from "./work.mjs";

const flags = {};
const args = process.argv.slice(2);
for (let i = 0; i < args.length; i += 2) flags[args[i].replace(/^--/, "")] = args[i + 1];
try {
  if (!flags.task || !flags.delivery) throw new Error("--task and --delivery are required (the usage is at the top of evaluator.mjs)");
  const verdict = judge(JSON.parse(readFileSync(flags.task, "utf8")), JSON.parse(readFileSync(flags.delivery, "utf8")));
  console.log(JSON.stringify(verdict));
  process.exitCode = verdict.accepted ? 0 : 1;
} catch (e) {
  console.error(`evaluator.mjs: ${e.message ?? e}`);
  process.exitCode = 2;
}
