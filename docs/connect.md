# Let your agents use it

This is the **secondary** path. If you only want the coordination in a repo,
add [the Action](../README.md#start-here-the-action) instead: it needs nothing
installed anywhere. If you want the behaviour inside a tool you are building,
import [`knos.core`](../src/knos/core.py). What follows is worth doing when
you personally run several agents on one tree and want them refused live.

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
edit and nothing to paste.

1. Download `knos.mcpb` from the
   [latest release](https://github.com/drexthealpha/Knos/releases), or build it
   yourself: `npx @anthropic-ai/mcpb pack extension knos.mcpb` in a clone.
2. In Claude Desktop: **Settings → Extensions → Advanced settings → Install
   Extension…**, and choose the file.

That is the whole install. The bundle declares `knos` as a dependency in the
`pyproject.toml` beside its entry point, and Claude Desktop resolves it with
`uv`, so you are not asked for a Python path and you do not have to
`pip install knos` first.

**What is actually in the bundle**, because "one click" is a claim you should
be able to check: three files — `manifest.json`, `pyproject.toml` and
`main.py`, about 2 kB in total. No copy of Knos, no compiled dependency, and
`main.py` hands straight over to the same `knos.mcp` that `pip install` and
the Claude Code plugin both run. One memory on this machine, not a second one
hiding inside an extension.

You need `uv` on your machine for this path; if you would rather not have it,
`pip install knos && knos connect` writes the Claude Desktop config instead
and is one restart away.

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
[Releases](https://github.com/drexthealpha/Knos/releases), then
**Settings → Extensions → Advanced settings → Install Extension…** and pick
it. Claude Desktop does not open `.mcpb` files from the file manager, so
double-clicking one does nothing.

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
