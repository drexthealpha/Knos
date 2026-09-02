# Contributing

Knos is one local MCP server, three tools, one SQLite file. Changes that
delete something are the most welcome kind.

## Run the tests

```bash
python -m venv .venv && .venv/bin/pip install -e ".[dev]"
pytest                      # ~4 minutes; every test uses a throwaway store
pytest tests/test_no_network.py     # the one that proves it stays local
cd contracts && forge test  # the Base contract, if you have Foundry
```

The suite is slow because it reads real repos and drives a real MCP server
over stdio rather than mocking either. Please keep it that way.

## Add an agent adapter

This is the most useful first change, and it is three edits:

1. `src/knos/cli.py`, `_config_files()` — add `(name, path)` for the client's
   MCP config. Use its own environment variable if it has one.
2. `src/knos/cli.py`, `_write_configs()` — if the client uses a different
   shape, add a branch. OpenCode is the worked example: key `mcp`, not
   `mcpServers`, `"type": "local"`, and one command array.
3. `tests/test_cli.py` — a test that writes a throwaway config and asserts
   the exact shape that client reads. `test_opencode_gets_the_shape_opencode_reads`
   is the pattern. **Copy the shape from the client's own docs and link them
   in the PR.** A config written in the wrong shape looks like it worked and
   does nothing.

If the client has a CLI that registers a server with a running session, wire
that first and skip the file — see `_add_via_claude_cli`. That is the
difference between "restart your editor" and no step at all.

## What a good first PR looks like

- One thing, with a test that fails before it and passes after.
- A comment that says *why*, not *what*. The code says what.
- No new dependency without saying what it replaces.
- No new MCP tool unless something is impossible without it. Three is the
  ceiling; every tool is one more thing an agent has to choose between.
- Numbers measured on your machine, with the command you used.

## Things deliberately not wanted

- A daemon, watcher, or anything on a schedule. `knos` runs when a person or
  their agent asks it to, and the README says so.
- Install-time code execution.
- Anything that makes a network request on the read or answer path.
- Summarising. Knos returns what somebody actually said, with its source.
