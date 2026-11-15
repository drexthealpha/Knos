# Knos bench

Re-run it to check every number. `knos bench` measures the single-machine bars; `knos bench --chain URL` measures the
team bars on a local validator. The methods are in `src/knos/bench.py` and `src/knos/bench_chain.py`.

## How often agents say "tests pass" when CI failed (0.3.4)

<!-- bench:market -->
**Agent PR Index, 2026-10-02:** 2,431 PRs by AI coding agents claiming tests or CI pass (created 2026-06-04 – 2026-10-01); 9,207 PRs on repos owned by the PR's author or the human who assigned the agent were excluded. Of the 2,431 whose CI had finished at the head commit, **660 (27.2%) had a failing check** (95% Wilson interval 25.4%–28.9%). Published as `index.json` on the Pages site; built every 6 hours by `.github/workflows/index.yml`.

| agent | claiming PRs with finished CI | CI failed | 95% interval |
|---|---|---|---|
| GitHub Copilot coding agent | 787 | 194 (24.6%) | 21.8%–27.8% |
| Devin | 520 | 270 (51.9%) | 47.6%–56.2% |
| Claude GitHub app | 716 | 68 (9.5%) | 7.6%–11.9% |
| Claude Code | 206 | 17 (8.2%) | 5.2%–12.8% |
| OpenAI Codex | 202 | 111 (54.9%) | 48.1%–61.7% |
| **all** | **2,431** | **660 (27.2%)** | **25.4%–28.9%** |

Earlier sample (0.3.4):

Of 303 pull requests by AI coding agents (GitHub Copilot, Devin, OpenAI Codex, Claude) whose description says tests or CI pass, and whose CI had finished at the PR's head commit, **55 (18.2%) had a failing check at that commit** (95% interval 14.2%–22.9%); counting only test and build checks, 34 (11.2%). 30 of the 55 were merged anyway. PRs created 3 Jul – 30 Sep 2026, collected 1 Oct 2026 with `gh search prs` and the GitHub API: script `scripts/agent_pr_ci.py`, every PR in `docs/agent_pr_ci.json`.

| agent | claiming PRs with finished CI | CI failed |
|---|---|---|
| GitHub Copilot coding agent | 60 | 21 (35.0%) |
| Devin | 68 | 15 (22.1%) |
| OpenAI Codex | 55 | 9 (16.4%) |
| Claude GitHub app | 96 | 8 (8.3%) |
| Claude Code | 24 | 2 (8.3%) |
| **all** | **303** | **55 (18.2%)** |

Small per-agent samples are directional only. This is the gap the Knos Stop hook closes: it runs the CI check itself before the agent may say done.
<!-- /bench:market -->

## Team bars (0.3): `knos bench --chain http://127.0.0.1:8899`

On a local validator running the devnet-deployed Solana Attestation Service and Lighthouse (`scripts/devchain.sh
start`). Method: `src/knos/bench_chain.py`.

| vector | knos | without knos | ratio / target |
|---|---|---|---|
| **Security**, metric 1: conflicting writes to working trees (3 machines × 3 vendor hooks × 200 rounds, 4 files) | **0** (of 738 writes the guard allowed) | none: 1,062 (of 1,800) | 0 |
| **Security**, metric 2: conflicting commits | **0** | | 0 |
| **Budget**, Solana: overspends signed directly with the agent's delegate key (200) | 0 moved; 200/200 rejected | | all rejected |
| **Budget**, Tempo Moderato: over-limit payments signed directly with the agent's access key, with no client-side checks (200) | 0 received; 200/200 reverted on chain; fees 44 units (0.000044 USD) each, from the allowance | | all rejected |
| **Speed**: guard decision when the agent holds the claim (reads the mirror) | p50 2.7 ms / p95 25.6 ms | | p95 ≤ 100 ms |
| **Speed**: edits that waited on the chain (20 edits per claimed unit) | 5% (the first edit of each unit) | | ≤ 5% |
| **Cost**: placing one claim | 5,000 lamports fee + 2,797,920 lamports rent, refunded on release | Agent Mail across machines: an always-on host, from $1.94 / month ([COMPARE.md](COMPARE.md)) | $0 servers |

**Capability** (the coverage matrix: 4 vendors × single/multi machine × edit/commit enforcement × bypass-proof
budget = 32 cells):
- **Knos: 32.** Every vendor's edit hook, on one machine (`tests/test_guard.py`, `tests/test_codex_guard.py`) and
  across machines (`tests/test_team_two_homes.py`: Claude Code, Cursor, Codex, OpenCode). The commit guard for every
  host. Chain budgets that hold when Knos is bypassed (`tests/test_chain_budgets.py`, and the Tempo run above).
- **Best alternative, MCP Agent Mail: 8.** Its reservations are advisory at edit time and its pre-commit guard blocks
  commits, on one machine or across machines through its server, with no budgets
  ([README](https://github.com/Dicklesworthstone/mcp_agent_mail), read 30 Sep 2026).
- 32 / 8 = **4×**.

**Claim protocol property test** (`tests/test_team_property.py`):
- Setup: five member keys, overlapping files and folders, decisions read through an RPC that lags 2–5 slots, dust sent
  to claim addresses, and claimers that crash after creating.
- 1,000 rounds on the current code (four concurrent runs of 250, different seeds): 5,000 claims, 2,059 winners,
  2,607 that lost and closed their own claim, 317 crashed claimers, 300 dust transfers, 17 answered "offline" (the
  RPC took too long; the guard lets that edit go ahead with a warning).
- **Double winners: 0. Winners ever blocked: 0. Overlapping claimers not refused: 0.**
- 3,469 reads were served stale by the lagging endpoint, and 29,073 were refused until it reached the asked slot.
- An earlier run on older code (whole-program reads) completed 763 rounds with the same zeros before a harness
  timeout.

**Signer cap:** 30 member keys. 31 makes the ChangeAuthorizedSigners transaction 1,648 bytes, over the 1,232-byte
limit (measured on the local validator; `knos team status` prints it).

**Limits, said plainly:**
- The chain numbers come from a local validator on a busy laptop; devnet adds network latency to the first claim of
  each file (the recorded devnet run is in [network/demo.md](network/demo.md)).
- When the guard cannot get the chain's word within its 1-second budget, it lets the edit go ahead with a warning
  ("fail-open"), because Knos never blocks work on an outage. The bench counts those edits separately: there were
  none in the run above.
- An earlier 200-round run, on the same laptop while a 2.5-hour test suite ran against the same validator, recorded
  15 conflicting writes in the Knos arm. That run did not yet count fail-open edits, so we cannot show how many of
  the 15 were fail-open. Re-running on a quieter machine gave the 0 above, and the property test (which never
  fails open) found no double winners. We report both runs.

## Single-machine bars

Measured by `knos bench` on 2026-09-29 with 0.2.0. In 0.3 the single-machine path changed only in where memory is stored (Sibyl's own store, one tenant per repo); run `knos bench` to measure your machine.

| vector | knos | without knos | ratio / target |
|---|---|---|---|
| **Security**: rounds where a conflicting edit reached the file (3 agents x 200 rounds) | 0 | none 200 | 0 |
| **Capability**: questions answered from past sessions and commits, cited (20) | 18 | 0 (CLAUDE.md only) | (knos+1)/(base+1) = 19.0x |
| **Friction**: steps to three hosts sharing memory and claims | 1 | 8 (Sibyl Memory + MCP Agent Mail, from their READMEs) | 8.0x |
| **Budget**: spend past the cap (200 attempted payments, cap 5) | 0 | | 0 by construction |
| **Speed**: guard decision p50 / p95 (5,400 files, 21 live claims) | 20.5 / 38.8 ms | | p95 <= 100 ms |
| **Speed**: search p50 / p95 (5,400 files) | 17.2 / 25.9 ms | | p95 <= 300 ms |
| **UX**: `knos init` wiring 4 hosts, self-test included | 21.0 s | | <= 30 s |

## Friction, counted from each README

| tool | steps | what | source | read |
|---|---|---|---|---|
| knos | 1 | `knos init` (memory + claims + edit guard, every host it finds) | this repo | measured |
| MCP Agent Mail | 5 | installer, start the server (`am`), register_agent in each of 3 hosts; claims only (advisory leases), no memory of past sessions | https://github.com/Dicklesworthstone/mcp_agent_mail | 2026-09-29 |
| Sibyl Memory | 3 | `pip install sibyl-memory-cli[mcp]`, `sibyl init` (browser sign-in), `sibyl setup`; memory only, no claims | https://docs.sibyllabs.org/memory/install | 2026-09-29 |
| Sibyl Memory + MCP Agent Mail | 8 | both of the above, to get memory and claims | as above | 2026-09-29 |

Limits, said plainly: the history set is 20 synthetic decisions asked in other words, not a public benchmark; the budget row measures Knos's cap, and the agent wallet's balance is a second, on-chain ceiling this bench does not spend real money to show.

## Jobs (0.3.1)

`knos bench jobs` runs full jobs (post, claim, deliver, accept) and checks the money after every one: the worker got
95%, the fee account 5%, the vault is empty.

| where | command | jobs | post p50 | accept p50 | label |
|---|---|---|---|---|---|
| Solana runtime, in-process (LiteSVM) | `knos bench jobs` | 20 | 0.9 ms | 0.9 ms | code speed, no network |
| Tempo escrow on a local anvil | `knos bench jobs --tempo` | 20 | — | — | code speed, no network |
| Solana devnet, `finalized` | `KNOS_COMMITMENT=finalized knos bench jobs --live` | 5 | 2.2 s | 2.6 s | testnet, wall clock from Lagos |
| Solana devnet, `confirmed` | `KNOS_COMMITMENT=confirmed knos bench jobs --live` | 5 | 2.6 s | 3.0 s | testnet, wall clock from Lagos |
| Tempo Moderato | a recorded run (deploy, then 5 jobs at 0.01 pathUSD) | 5 | 5.5 s | 2.6 s | testnet, wall clock from Lagos |

Measured 1 Oct 2026. The live rows include every RPC round trip the client makes, from a home connection in Lagos.


The 0.3.0 method (a Sibyl search on the brief) found 54 of 72 preferences; capturing them when said (0.3.1) finds 72
of 72. Capture on a held-out set written before it was run: 21/24 preferences, 0 of 30 ordinary requests mistaken for
one (`tests/data/preferences_heldout.json`).

## Recall (0.3.2): `knos.recall` on LongMemEval_s

No LLM. Sibyl (`sibyl-memory-client`) stores each past round; `knos.recall.retrieve` fuses one-term searches (BM25
over the whole round, the user part and the assistant part), Sibyl's own search, and captured preference sentences,
by reciprocal rank per session. Scored like the 0.3.1 baseline: the answer-bearing past session is in the top 10.
Tuned on a fixed 100-question dev split (seed 0); the other 370 questions are held out.

<!-- bench:recall-table -->
LongMemEval_s (cleaned), 470 questions with evidence; tuned on 100, held out 370, measured 2026-10-01.

| | baseline (0.3.1) | dev | **held-out** |
|---|---|---|---|
| overall, top 10 | 81.5% | 97.0% | **96.8%** |
| the assistant said | 51.8% | 100% | **88.4%** |
| preferences | 50.0% | 100% | **83.3%** |
| median tokens retrieved | 5,338 | 5,554 | **5,656** |
<!-- /bench:recall-table -->

The strategy is `src/knos/recall.py`.

## Web app (0.3.2): Lighthouse

Lighthouse 12.8.2, headless Chrome, `web/` served as static files (as on GitHub Pages), 1 Oct 2026: performance 100,
accessibility 100, best practices 100, SEO 100 on both the mobile and desktop presets (mobile first contentful paint
1.1 s). Wallet and crypto libraries load only when used. Served instead through the Python dev server (`knos jobs
serve`) on the same loaded machine, mobile performance was 55, all of it the server's 9.3 s time to first byte.

## Acceptance with a live model (0.3.3)

The same 24 jobs, buyers, histories and grader, with the reference worker's prompt (`Worker.prompt`) answered live by
Gemini through its native API on 1 Oct 2026 (gemini-3.8-flash was out of free-tier quota, so every answer came from
gemini-3.5-flash-lite). One attempt per job, temperature 0.2. The table is the one above.

With memory every rejection was a task error (dates read month-first, "twenty percent" for "20%", two wrong JSON
keys or values); no buyer preference was broken. Without memory 23 of 24 broke a preference the buyer had stated once.
