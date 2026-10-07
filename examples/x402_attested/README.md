# x402 "knos-order": a runnable example

A proposal, not part of x402: [docs/X402.md](../../docs/X402.md) is the specification and prints every message.

    node --test examples/x402_attested/test.mjs                    # replayed: no chain, no key
    python -m pytest -q tests/test_x402_attested.py -k live        # the program itself, over JSON-RPC, in LiteSVM
    node examples/x402_attested/live.mjs run --rpc https://api.devnet.solana.com --key buyer.json --offer offer.json

The third line is the devnet run. It has not been run at the public program ids; [docs/X402.md](../../docs/X402.md), "Run it", says what it
needs and where its transaction signatures are recorded once it has.

| file | what it is |
|---|---|
| `attested.mjs` | the scheme: the requirement, the funding instruction, the server's check of the order, the status |
| `server.mjs` | a resource server that sells one fix under the scheme |
| `client.mjs` | a client that reads the 402, checks it, funds the order and asks again |
| `chain.mjs` | the chain, replayed from `fixtures.json` (what the test build of knos_pay did in LiteSVM) |
| `rpc.mjs` | the chain over JSON-RPC, any URL: reads accounts, signs and sends, reads an order's history |
| `live.mjs` | `run`, `serve`, `buy`, `status`, `refund` against `--rpc <url>` |
| `offer.devnet.json` | the offer to fill for devnet: Circle's devnet USDC, 5 test USDC, 15 minutes to deliver |
| `fixtures.json` | written by `python scripts/x402_fixture.py` |
| `messages.json` | the exact messages of one run; `node examples/x402_attested/test.mjs --write` rewrites it |

Node 20 or later. No package to install: the only import outside Node is `sdk/settle`, which has no dependency.

Two agents on top of this scheme, paid only on acceptance: [`examples/agent_pays_agent`](../agent_pays_agent).
