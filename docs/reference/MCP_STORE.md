# Knos in AI assistants (the app-store MCP)

Knos answers two questions inside any assistant that speaks MCP: is this product wanted, and is this brief clear enough
to fund. Nothing moves money inside the assistant: funding and payouts are links out to the Knos site.

## Connect

- Endpoint: `https://knos.onrender.com/mcp/store` (MCP Streamable HTTP, no sign-in).
- The full server, with the signed-in money tools, is `https://knos.onrender.com/mcp`.

## Tools

| Tool | What it does | Read-only |
|---|---|---|
| `knos_demand_check` | whether a product idea is wanted, with Knos's verdict | yes |
| `knos_ready` | whether a brief is Ready to fund: each milestone needs a measured target, a verifier and a deadline | yes |

Every tool declares a title and `readOnlyHint` / `destructiveHint` annotations.

## Limits

- 30 requests per address in 10 minutes, then HTTP 429.
- At most 2,000 tool calls a day through `/mcp/store`, all callers together (UTC day).

## Privacy and support

- Privacy policy: https://drexthealpha.github.io/Knos/privacy.html. An idea that names a
  person, an e-mail, a phone number or an address is refused before any call.
- Support: open an issue at https://github.com/drexthealpha/Knos/issues.
- What Knos will not fund: [REFUSE.md](REFUSE.md).

NEAR testnet and Solana devnet, test money only. Results are not a forecast and not about any one person.
