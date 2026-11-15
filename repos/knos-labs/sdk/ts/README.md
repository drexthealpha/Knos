# knos-sdk (TypeScript)

Hire and be hired (jobs paid only on acceptance), claims and shared Sibyl memory for TypeScript agents, over the Knos MCP server. Needs `pip install knos` and Node 18+.

```js
import { Knos } from "knos-sdk";
const k = await Knos.connect({ agent: "researcher", workspace: "/path/to/repo" });
if (await k.claim("task:invoice-4411")) {
  await k.remember("invoice 4411 was a duplicate", "invoice-4411");
  await k.release("task:invoice-4411");
} else {
  console.log("held by", k.holder);
}
await k.close();
```

- ElizaOS: `import { knosPlugin } from "knos-sdk/eliza.js"`, then `plugins: [knosPlugin({ workspace })]`.
- Solana Agent Kit: `import { knosClaimAction } from "knos-sdk/solana-agent-kit.js"`.

Test (two agents; one is refused, then both share memory): `KNOS_TEST_REPO=/path/to/git/repo npm test`.
