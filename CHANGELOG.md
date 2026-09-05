# Changelog

## 0.1.5

`knos guard --install` refuses the edit, not only the answer. Claude Code,
Cursor and OpenCode each run a hook before a tool call, and a hook can say no,
so an agent about to edit work another agent has claimed is stopped and told
who holds it. It also reads the rules this repo already gave knos and enforces
the ones a machine can check — a prohibition with a path in backticks. Off
until you run it, and `knos guard --uninstall` takes it back out. It fails
open: an unreadable store allows the edit.

`knos export --to <path>` writes the shared record where a repo already keeps
its decisions, instead of insisting on `.knos/decisions.md`. Anything knos
already reads back is still read back, and `knos export` says so plainly when
the path you chose is not.

The Claude Desktop extension now uses the `uv` runtime, so installing it no
longer asks you to find and paste a Python path.

## 0.1.4

Claims are a compare-and-swap: two agents reaching for the same work in the
same second cannot both hold it, and the loser is told who does. A full store
now refuses a claim in words instead of dropping it silently. `knos status`
reports the claims held and says FULL at 5 MB. The pull request Action reports
decisions as well as claims, takes a `github-token` input, and documents its
`pull_request_target` safety. `pytest` runs the critical path in about 25
seconds; `pytest -m ""` runs all of it.

`knos --version` prints the installed version, the same number the MCP
handshake reports — one value, read from package metadata, so the two cannot
drift apart.

`knos export` keeps the shared file to the readable part of a note. What an
agent pays for is a whole API response and the store still holds all of it,
but a decision record other people commit is not the place for a JSON body
and a receipt.

`.knos/decisions.md` is no longer ignored. The file the Action reads out of a
checkout could not be committed in this repository, which meant nothing here
could carry the record it asks other repositories to carry. The store and the
keys stay ignored.

The agent (`agent/bot.ts`) and the x402 payer (`src/knos/buy402.py`) are in
the repository. The README linked both and neither was there, so a clean
clone could not run what it was told to run.

**Use `drexthealpha/Knos/action@v0.1.4`.** `v0.1.3` was tagged before these
Action changes and serves the older file.

## 0.1.3

Declare MCP tool annotations (read-only, destructive, idempotent, open-world) on `search`, `about` and `remember`, and report the installed version in the handshake.
