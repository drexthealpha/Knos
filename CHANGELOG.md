# Changelog

## 0.1.7

`knos demo` runs the whole product on a throwaway repo in about a minute and
then deletes its memory, so the last thing on screen is every refusal
stopping. Every line is a real call rather than a transcript, and the tests
assert the live values appear.

The memory now decides whether money moves. `knos.gate` is asked before any
purchase and answers one of four ways: it refuses to spend while somebody
holds the topic, refuses while the work rests on a reversed decision, serves
what was already bought for nothing, and only otherwise buys. Measured over an
ordinary day of five agents: 5.41x more expensive without the store.

`knos changed` reverses a decision and holds everything reasoned from it - the
edit is refused and the purchase is refused - until `knos reconsider` says
somebody looked. The old wording is archived rather than dropped. `knos held`
lists what is waiting.

`knos restore` rebuilds a repo's decisions from the `.knos/decisions.md` it
commits, so a fresh clone on a machine that has never run knos carries them.
Claims are deliberately not restored: a hold rebuilt elsewhere would assert a
collision that is not happening.

Also: the ablation grew to twelve arms with numbers in
`docs/evidence/ablation.json`, and a judge guide, verification, architecture,
memory-model and evidence ledger under `docs/`.

Fixed: the gate served the wrong asset. It searched rather than reading the
exact topic, so a store holding `market brief: BTC` answered a request for
`market brief: ETH` for free. Saving a cent by returning something true about
a different subject is worse than paying.

## 0.1.6

The bot never answers with silence. Anything it does not recognise - a typo'd
command, or a person saying hello - now gets a sentence and the list of what
does work. Falling off the end of the handler was indistinguishable from a
dead process.

A failed subprocess is no longer returned as though it were an answer. stdout
and stderr were collected into one string, so a Python traceback reached the
chat as content; they are separate now and the exit code decides which the
reader sees.

No path prints a seller's payload verbatim any more: the last fallback in the
formatter used to dump the raw body when it met an unfamiliar shape.

A reply cut at Telegram's length limit says that it was cut, instead of
stopping mid-word.

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
