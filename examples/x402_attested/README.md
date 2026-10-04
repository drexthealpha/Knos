# x402 "attested": a runnable example

A proposal, not part of x402: [docs/X402.md](../../docs/X402.md) is the specification and prints every message.

    node --test examples/x402_attested/test.mjs

| file | what it is |
|---|---|
| `attested.mjs` | the scheme: the requirement, the funding instruction, the server's check of the order, the status |
| `server.mjs` | a resource server that sells one fix under the scheme |
| `client.mjs` | a client that reads the 402, checks it, funds the order and asks again |
| `chain.mjs` | the chain, replayed from `fixtures.json` (what the test build of knos_pay did in LiteSVM) |
| `fixtures.json` | written by `python scripts/x402_fixture.py` |
| `messages.json` | the exact messages of one run; `node examples/x402_attested/test.mjs --write` rewrites it |

Node 20 or later. No package to install: the only import outside Node is `sdk/settle`, which has no dependency.
