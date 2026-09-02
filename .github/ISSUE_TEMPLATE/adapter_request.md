---
name: Support another agent
about: Wire Knos into a client it does not know yet
labels: adapter, good first issue
---

**Which client**

**Where it keeps its MCP config** — the exact path, per OS, and a link to the
docs page that says so.

**The exact JSON shape it reads** — paste a working example from its docs.
Knos writes `mcpServers` for Claude Code / Desktop / Cursor and `mcp` with
`"type": "local"` for OpenCode; if yours differs, it needs its own branch.

**Does it have a CLI that registers a server with a running session?**
(Claude Code has `claude mcp add`, which is why it needs no restart.) If so,
name the command — that is worth more than the config file.

`CONTRIBUTING.md` has the three edits and the test to copy.
