// Two TypeScript agents on one repo: one claims a task, the other is refused, then both share memory.
// Needs `knos` on PATH (pip install knos) and a git repo; run: KNOS_TEST_REPO=/path/to/repo node test.mjs
import assert from "node:assert/strict";
import { Knos } from "./index.js";

const workspace = process.env.KNOS_TEST_REPO;
const command = process.env.KNOS_BIN || "knos";
const a = await Knos.connect({ agent: "alice", workspace, command });
const b = await Knos.connect({ agent: "bob", workspace, command });
try {
  assert.equal(await a.claim("task:invoice-4411"), true);
  assert.equal(await b.claim("task:invoice-4411"), false);
  assert.match(b.holder, /alice/);
  assert.equal(await b.claim("task:invoice-4412"), true);
  await a.remember("invoice 4411 was paid twice", "invoice-4411");
  assert.match(await b.recall("invoice 4411"), /paid twice/);
  await a.release();
  assert.equal(await b.claim("task:invoice-4411"), true);
  console.log("ok: claims and shared memory across two TypeScript agents");
} finally {
  await a.close();
  await b.close();
}

// The ElizaOS plugin and the Solana Agent Kit action, driven the way each framework calls them.
const { knosPlugin } = await import("./eliza.js");
const { knosClaimAction } = await import("./solana-agent-kit.js");
const plugin = knosPlugin({ workspace, agent: "eliza-one" });
const claimAction = plugin.actions.find((x) => x.name === "KNOS_CLAIM");
const said = [];
const msg = { content: { text: "please work on task:eliza-7" } };
assert.equal(await claimAction.validate({}, msg), true);
const r1 = await claimAction.handler({ character: { name: "eliza-one" } }, msg, undefined, {}, (m) => said.push(m.text));
assert.equal(r1.success, true);
const sak = knosClaimAction({ workspace, agent: "sak-trader" });
assert.equal(sak.schema.safeParse({ unit: "task:eliza-7" }).success, true);
const r2 = await sak.handler(null, { unit: "task:eliza-7" });
assert.equal(r2.claimed, false);
assert.match(r2.holder, /eliza-one/);
console.log("ok: ElizaOS plugin claims; Solana Agent Kit action is refused on the same unit");
process.exit(0);
