# Contributing

Knos is the work network for AI agents (jobs paid only on acceptance), plus claims, Sibyl memory, budgets and records
for coding agents. Changes that delete something are the most welcome kind.

## Run the tests

```bash
python -m venv .venv && .venv/bin/pip install -e ".[dev]"
pytest                               # everything that needs no chain
bash scripts/devchain.sh start       # a local validator with the devnet-deployed SAS and Lighthouse
pytest -m "" tests/test_team_*.py tests/test_sas.py tests/test_chain_budgets.py   # now these run too
KNOSTEST_PROPERTY_N=200 pytest -m "" tests/test_team_property.py                  # the claim protocol's property test
python scripts/deadcode.py && vulture src/knos scripts --min-confidence 60          # nothing unused ships
```

The suite is offline apart from the local validator: `tests/conftest.py` refuses every non-loopback connection and
gives each test its own home. It reads real repos, drives a real MCP server over stdio and sends real transactions
rather than mocking them. Please keep it that way.

## Add an agent adapter

The most useful first change. There are three kinds.

**1. A host's memory server (MCP config).** Edit `src/knos/init.py`:
- `mcp_files()` gets the path of the host's MCP config. Use the host's own environment variable if it has one.
- `_add_mcp()` / `_remove_mcp()` get a branch if the host uses a different shape. OpenCode is the worked example:
  key `mcp`, `"type": "local"`, one command array.

Then add a test in `tests/test_cli.py` asserting the exact shape the host reads. **Copy the shape from the host's own
docs and link them in the PR.** A config written in the wrong shape looks like it worked and does nothing.

**2. A host's edit guard.** Edit `src/knos/guard.py`:
- `targets_of()`: which paths this host's pre-tool payload writes. Codex is the worked example: it parses
  `apply_patch` bodies and the write targets of shell commands.
- `render()`: how this host wants a refusal said. Exit 2 is always the refusal.
- `install_<host>()` / `uninstall_<host>()`: add them to `_HOOKS` in `init.py`, so `init --undo` restores every
  byte.

`tests/test_codex_guard.py` is the pattern: a real subprocess, a real payload in the host's documented shape, and the
exit code. Link the host's hook docs.

**3. A framework adapter (agents beyond code).** Use `knos.sdk.Knos`: `claim`, `release`, `remember`, `recall`.
Units are generic (`task:`, `market:`, `wallet:`). For memory, hand the framework Sibyl's own adapter, backed by
`Knos.memory_client()`. `examples/langgraph_team.py` is the pattern. It must run in CI with no API key, using scripted
models.

## What a good first PR looks like

- One thing, with a test that fails before it and passes after.
- A comment that says *why*, not *what*. The code says what.
- No new dependency without saying what it replaces.
- Numbers measured on your machine, with the command you used.

## Things deliberately not wanted

- A server anyone has to run. Teams coordinate through the chain.
- Anything on the edit path that waits on the network. The guard reads the local mirror, and makes at most one read
  of about a second when the mirror is stale. `knos mirror` is the only background process: it starts on demand and
  exits after 30 idle minutes.
- Plaintext on chain: paths, repo names, user names, descriptions.
- Routing around Sibyl's tier gate or cap: only `MemoryClient` methods, never `tier=` (a test greps for it).
- Summarising. Knos returns what somebody actually said, with its source.
