# Let your agents use it

Knos runs on your machine and your agent starts it. There is nothing to host,
no account, and no key.

The fastest way, for every agent you have at once:

```bash
knos connect
```

That adds Knos to each agent config it finds and keeps a copy of what was
there first. Restart them and they all share one memory. Everything below is
for doing it by hand, one agent at a time.

## Claude Desktop, one click

Claude Desktop installs local servers as extensions, so there is no JSON to
edit.

1. `pip install knos`, if you have not already.
2. Download `knos.mcpb` from the
   [latest release](https://github.com/drexthealpha/Knos/releases), or build it
   yourself with `npm install -g @anthropic-ai/mcpb` and then `mcpb pack .`
   in a clone of this repo.
3. In Claude Desktop: **Settings → Extensions → Advanced settings → Install
   Extension…**, and choose the `.mcpb` file.
4. When it asks for **Python with knos installed**, paste the path that
   `knos connect` prints. Plain `python` is right if you installed Knos
   globally rather than into a virtual environment.

The extension carries no copy of Knos. It runs the one you installed with
pip, so there is one memory on this machine rather than a second one hiding
inside an extension bundle.

## Claude Code

```bash
claude mcp add knos -- <python> -m knos.mcp
```

`knos connect` prints that line with the right python already filled in.

## Cursor, and anything else that speaks MCP

`~/.cursor/mcp.json`

```json
{
  "mcpServers": {
    "knos": { "command": "<python>", "args": ["-m", "knos.mcp"] }
  }
}
```

## After restarting, three tools appear

| Tool | Does |
|---|---|
| `search(query)` | Search, filtered by what this agent may see |
| `about(thing)` | What is known about one thing |
| `remember(fact, about, claiming)` | Write back, and claim work you are starting |

## What your agents cannot see

Private paths. Not redacted, not counted, absent. `.env`, `*.pem`, `id_rsa`,
`.ssh` and `.aws` are private the moment Knos reads a repo, and `knos private
<path>` adds more. You can still search all of it yourself.

Work another agent has claimed is withheld too, until they finish or you
override it with a reason. See [core-flow.md](core-flow.md).

## What is left after `knos connect`

For the other three, `knos connect` writes the config and takes a backup, and
then there is exactly one thing left to do:

| Client | What is left | Why |
|---|---|---|
| Claude Code | nothing | `claude mcp add --scope user` registers with the running session |
| Cursor | **Quit Cursor and open it again** (Ctrl/Cmd+Q, then reopen) | reads `~/.cursor/mcp.json` at startup; no command registers a server with a running instance |
| Claude Desktop | **Quit and reopen it** — closing the window is not enough, it keeps running in the tray | same |
| OpenCode | **Exit and start it again** (Ctrl+C, then `opencode`) | `opencode mcp add` exists but is interactive, and its docs describe no reload for a running session |

Every file it touches is copied to `<name>.before-knos` first, and
`knos connect` prints the restart line for each client that needs one —
quit the app and start it again, because nothing in the MCP spec lets a
server register itself with a session that is already running.

<details>
<summary>Other ways in — Claude Desktop extension, Claude Code plugin, or by hand</summary>

**Claude Desktop:** download `knos.mcpb` from
[Releases](https://github.com/drexthealpha/Knos/releases) and double-click it.

**Claude Code plugin:**

```
/plugin marketplace add drexthealpha/Knos
/plugin install knos@knos
```

**By hand** — `knos connect --print` shows the JSON, or add it yourself:

```json
{ "mcpServers": { "knos": { "command": "python", "args": ["-m", "knos.mcp"] } } }
```

Every path runs the same `python -m knos.mcp`, so `pip install knos` comes
first whichever you pick.
</details>
