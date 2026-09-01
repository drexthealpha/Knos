# Let your agents use it

knos runs on your machine and your agent starts it. There is nothing to host,
no account, and no key.

## Claude Code

```
claude mcp add knos -- <python> -m knos.mcp
```

`knos connect` prints that line with the right python already filled in.

## Cursor

`~/.cursor/mcp.json`

```json
{
  "mcpServers": {
    "knos": { "command": "<python>", "args": ["-m", "knos.mcp"] }
  }
}
```

Restart the agent. Four tools appear:

| Tool | Does |
|---|---|
| `search(query)` | Search, filtered by what this agent may see |
| `about(thing)` | What is known about one thing |
| `remember(fact, about)` | Write back |
| `sources(claim)` | Which file, session, or commit |

## What your agents cannot see

Private paths. Not redacted, not counted, absent. `.env`, `*.pem`, `id_rsa`,
`.ssh` and `.aws` are private the moment knos reads a repo, and `knos private
<path>` adds more. You can still search all of it yourself.
