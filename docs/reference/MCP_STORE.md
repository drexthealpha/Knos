# Knos in AI assistants (the app-store MCP)

Knos answers two questions inside any assistant that speaks MCP: is this product wanted, and is this brief clear enough
to fund. Nothing moves money inside the assistant: funding and payouts are links out to the Knos site.

## Connect

- Endpoint: `https://knos.onrender.com/mcp/store` (MCP Streamable HTTP, no sign-in).
- The full server, with the signed-in money tools, is `https://knos.onrender.com/mcp`.

## Tools

| Tool | What it does | Read-only |
|---|---|---|
| `knos_demand_check` | who wants a product idea, where to launch it and at what price tier, from Qloo's taste data, with Knos's verdict | yes |
| `knos_ready` | whether a brief is Ready to fund: each milestone needs a measured target, a verifier and a deadline | yes |

Qloo's own harness tools (`qloo_*`) are not listed here: on `https://knos.onrender.com/mcp` they answer an agent key only
(Authorization: Bearer), each call counted on that key's own budget, so Knos's Qloo key is lent to no anonymous caller.

Every tool declares a title and `readOnlyHint` / `destructiveHint` annotations.

## Limits

- 30 requests per address in 10 minutes, then HTTP 429.
- At most 2,000 tool calls a day through `/mcp/store`, all callers together (UTC day).
- Qloo calls stay inside the server's monthly Qloo budget.

## Privacy and support

- Privacy policy: https://drexthealpha.github.io/Knos/privacy.html. No personal data goes to Qloo: an idea that names a
  person, an e-mail, a phone number or an address is refused before any call.
- Support: open an issue at https://github.com/drexthealpha/Knos/issues.
- What Knos will not fund: [REFUSE.md](REFUSE.md).

NEAR testnet and Solana devnet, test money only. Results are aggregate taste, not a forecast and not about any one person.
