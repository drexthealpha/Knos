# Knos tools in Hermes Agent

Three ways in; any one is enough.

1. Plugin (tools in-process): `pip install knos==0.4.1` puts the entry point `knos = knos.hermes_plugin:register`
   in the `hermes_agent.plugins` group. Enable it with `hermes plugins enable knos`. Tools: `knos_verify`,
   `knos_receipt`, `knos_bounty_claim`, `knos_outcome_check`.
2. MCP server over stdio: an `mcp_servers` entry named `knos` with `command: knos` and `args: ["mcp"]`.
   Every knos mcp tool (20, and 3 more when the money engine is installed), including `knos_verify` and
   `knos_receipt`. `knos_verify` runs the repository's tests on this machine, so Hermes should ask before it.
3. MCP server over HTTP: start `knos mcp --http 8808` and point an `mcp_servers` entry at
   `url: http://127.0.0.1:8808/mcp`. Set `KNOS_MCP_HTTP_TOKEN` on the server and send it as a bearer header;
   without it `knos_verify` is not served over HTTP.

The exact configuration blocks are in the Knos repository, docs/reference/AGENTS.md.

| Tool | Arguments | Returns | Sends |
| --- | --- | --- | --- |
| `knos_verify` | `path`, optional `base`, `tests`, `runs`, `agent`, `out` | verdict, reasons, `pr_markdown`, receipt file and digest | nothing |
| `knos_receipt` | `file` | valid, problems, verdict, signer | nothing |
| `knos_bounty_claim` | `issue` (owner/repo#number) | the bounty, the `/knos take` comment, the steps | nothing |
| `knos_outcome_check` | `funded`, `now` (two JSON files) | drift findings: spec, window, salt, control share, data | nothing |
