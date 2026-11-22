# Decision record: the limit check

Date: 22 Nov 2026. Status: adopted, open to revision when its users, its use or its cost change.

## What was decided

A person pastes a test file (a table of readings), names a column, a rule (above or below) and a limit, and Knos
names the first row that breaks the limit. The answer comes from one released program, run in a sandbox, that passed
a test locked before the program was written.

## Pinned versions

| Part | Pinned at | Where |
|---|---|---|
| Knos package and app | 0.4.1 | `pyproject.toml`, `apps/wanted/pyproject.toml` |
| Locked test | `near/agents/job/test_limit3.py`, sha256 `a139353f2ab788e86c5a20225f892b2b1c0bbe991452d5cf03c3d454bfd9e6e5`, commit `3df72a196579adae6153f2f34737376e33826df0` (19 Nov 2026) | `near/agents/job/data/limit/released.json` |
| Released program | `near/agents/job/data/limit/released_solution.py`, sha256 `6240ac16af236255a1589dae4eb3deedc07434236a534eaadec717da916a29ab` | `released.json` (`sha256`) |
| The job that released it | job-1119155030 on NEAR testnet, release transaction `85FdcQhHdpA9X9kuZVAuNrZsdC3e9JBbvjaJrxp6tnW` | `released.json` (`job_id`, `release_tx`) |
| Model that wrote the program | `deepseek-ai/DeepSeek-V4.1-Flash-1017` on NEAR AI Cloud | `released.json` (`model`) |
| Limits of one run | the time limit of the claim's `timeout_s`, at most 100,000 rows | `apps/wanted/knos_wanted/runner_conf.py` |

## The simpler alternative

A spreadsheet formula on the same column, such as `=MATCH(TRUE, INDEX(B2:B169<=1.4, 0), 0)`, gives the first failing
row with no Knos at all. Knos is kept only where it beats that formula: it names rows that hold no number instead of
skipping them, reads a first row of text as a header and a first row of numbers as data, and gives every answer with
the hash of the test that decided the program works. Whether that wins against the formula on time and mistakes, and at what cost,
is not measured yet: the locked side-by-side test is change L15 of the build plan, and until it runs this record
claims no win.

## Acceptance test

`near/agents/job/test_limit3.py` holds 14 known-answer cases. Each data file it reads is pinned by sha256, the NASA
sample among them. A program is released only when all 14 pass in the checker's sandbox; the test was written by an
agent that never saw a limit program (`released.json`, `test_author_saw_a_program`).

## Opportunity brief

1. **The costly event, in the buyer's words.** "Which row broke the limit?" A person who tests batteries, motors,
   parts or machines finds out late that a reading crossed its limit, or misses a row that holds no number.
2. **The current method, its output and its full cost.** A spreadsheet formula or reading the file by eye. Its time
   and its error rate per file are not measured yet (L15).
3. **The options.** An available alternative: the spreadsheet formula above. An internal build: a person writes a
   short script. The Knos approach: one released program behind a locked test, the same answer from the page and the API
   (the connector gives the same).
4. **Evidence and open questions.** Evidence: the 14 locked cases pass; the release is on NEAR testnet. Open: whether
   people with real test files use it more than once, and whether it beats the formula on held-out files.
5. **The smallest evaluation that could change the decision.** The locked comparison of L15: the same held-out
   battery files checked by Knos and by the formula, with the time and the mistakes of each and what each costs, fixed before either ran.
6. **What it needs.** A test file in CSV, TSV or XLSX; no account. Staff time and equipment: none beyond the server.
   Price: 5 free own-data runs a day per browser, then packs of test money (`docs/data/pricing.json`); nothing is
   charged. Data permission: the file is sent to the Knos server and kept, cut to a set length, so its result link works, until the server is next updated or newer results replace it (`tool_run.py`, the privacy line).
7. **Decision rule (proposed, for the founder to confirm).** Adopt while the locked test passes and real files keep coming. Revise if L15 shows the formula
   ahead on mistakes. Stop if no outside person runs their own file in 30 days from 22 Nov 2026.

## Benefit, cost, uncertainty, next action

- Benefit: not measured yet. The first figure will come from L15.
- Cost per run: not measured yet (L14 writes it to `docs/data/pricing.json`).
- Uncertainty: the 14 cases are the program's whole evidence; they were written from the brief's words and the NASA
  sample, not from outside users' files.
- Next action: run L15, then write its numbers here with their source file.
