# Agent PR Index

A pull request opened by a coding agent often says "tests pass". The Agent PR Index says how often GitHub's own record
of the checks agrees, for each agent it tells apart. It is published by week, under one name and one date: **"Agent PR
Index, week of <Monday>"**. The numbers are in [`agent_weekly.json`](agent_weekly.json); the script that makes them is
[`scripts/agent_pr_index.py`](../scripts/agent_pr_index.py), and
[`.github/workflows/index.yml`](../.github/workflows/index.yml) runs it every week and proposes the new week as a pull
request a person merges.

## The latest table

<!-- weekly:begin (written by scripts/agent_pr_index.py weekly; do not edit by hand) -->
**Agent PR Index, week of 2026-09-28.** Read 2026-10-05: a capped sample cut by week, not the whole week. An agent with fewer than 30 claimed pull requests whose CI had finished that week is "too few to rank" and has no place.

| Rank | Agent | Sampled | Claimed passing | CI finished | Failed a check anyway (95% interval) | Merged despite a failed check (95% interval) | Verified: also paid through Knos on a black-box check |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | claude-bot | 242 | 120 | 115 | 13 of 115 (11.3%; 6.7% to 18.4%) | 10 of 101 (9.9%; 5.5% to 17.3%) | 0 |
| 2 | claude-code | 423 | 120 | 102 | 13 of 102 (12.8%; 7.6% to 20.6%) | 6 of 76 (7.9%; 3.7% to 16.2%) | 0 |
| 3 | copilot | 169 | 66 | 58 | 13 of 58 (22.4%; 13.6% to 34.7%) | 12 of 45 (26.7%; 16.0% to 41.0%) | 0 |
| 4 | devin | 140 | 120 | 109 | 70 of 109 (64.2%; 54.9% to 72.6%) | 2 of 37 (5.4%; 1.5% to 17.7%) | 0 |
| too few to rank | codex | 83 | 2 | 2 | 0 of 2 (0.0%; 0.0% to 65.8%) | 0 of 2 (0.0%; 0.0% to 65.8%) | 0 |

Verified, checked against: no list of Knos payments was joined to this sample, so the count is 0 for every agent: every Knos payment so far is test USDC on Solana devnet. It takes a sampled pull request that was also paid through Knos under terms with a black-box check, and that list given to the script (--paid).

Every week in the file added up (2026-07-03 to 2026-10-04; never ranked: the weeks were not all read the same way). Source: the weeks read on 2026-10-05 are cut from a capped sample of 2026-09-21 to 2026-10-04 (each agent's newest claimed pull requests, up to a cap, by agent_pr_index.py scan), not whole weeks; the others are the sample read on 2026-10-01, cut by week.

| Rank | Agent | Sampled | Claimed passing | CI finished | Failed a check anyway (95% interval) | Merged despite a failed check (95% interval) | Verified: also paid through Knos on a black-box check |
| --- | --- | --- | --- | --- | --- | --- | --- |
| not ranked | copilot | not kept | 175 | 150 | 40 of 150 (26.7%; 20.2% to 34.3%) | 30 of 108 (27.8%; 20.2% to 36.9%) | 0 |
| not ranked | devin | not kept | 193 | 171 | 84 of 171 (49.1%; 41.7% to 56.5%) | 7 of 76 (9.2%; 4.5% to 17.8%) | 0 |
| not ranked | claude-bot | not kept | 212 | 205 | 21 of 205 (10.2%; 6.8% to 15.2%) | 15 of 183 (8.2%; 5.0% to 13.1%) | 0 |
| not ranked | claude-code | not kept | 147 | 123 | 14 of 123 (11.4%; 6.9% to 18.2%) | 7 of 97 (7.2%; 3.5% to 14.1%) | 0 |
| not ranked | codex | not kept | 52 | 52 | 9 of 52 (17.3%; 9.4% to 29.7%) | 3 of 44 (6.8%; 2.4% to 18.2%) | 0 |
<!-- weekly:end -->

**What is published today.** The table above is the newest week of `agent_weekly.json`. Its rows read on 2026-10-05
are a capped sample, not a whole week: `agent_pr_index.py scan --end 2026-10-04 --days 14 --per-agent 120` (each
agent's newest claimed pull requests, at most 120, from 21 September to 4 October 2026), cut by week and put into the
file with `weekly --add-sample`. An agent that reached its 120 within the newest week has no new row for the week
before; there its row is still the older sample's. The other weeks are the sample read once, on 2026-10-01 (at most
20 hits a search window), where the dates of the hits that claimed nothing were not kept ("not kept"). The weekly run
itself has run once on GitHub, in staging, on 5 October 2026: within its five hours one agent's search did not finish
and most of the week's checks were not yet read, so it added nothing and opened no pull request, as it is built to.
Its first run that reads a week whole replaces that week's row, where "Sampled" is always a number.

## How a week is read

The run reads the week that ended the Sunday before (Monday 00:00 to Sunday 23:59:59 UTC), on Monday and Tuesday.

- **Scale, inside GitHub's limits.** GitHub's search answers a signed-in caller 30 requests a minute and at most
  1,000 results a query ([REST API: search](https://docs.github.com/en/rest/search/search)). So the week is asked as
  5 agents x 7 days, each up to 10 pages of 100: at most 350 requests, about 12 minutes, and up to 7,000 pull
  requests an agent. A day that holds more than 1,000 is cut in halves, down to an hour, and each half is asked by
  itself. An hour that still holds more is read to its newest 1,000 and counted (`capped` in the scan's counts).
- **Continuity.** Reading the checks and the merge state costs about three requests a pull request. The workflow's
  own token has 1,000 requests an hour
  ([REST API: rate limits](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api)), so a
  week of 3,000 claimed pull requests needs about 9 hours of budget. Every answer is kept on disk and saved even when
  a run fails; a run out of budget waits for it; a run out of time stops, and the next of the eight runs (every 6
  hours, Monday and Tuesday) continues. A week is added to the file only when every search finished and GitHub
  answered for at least 98% of the pull requests kept. Otherwise the run fails and says what is missing.
- **Safety.** The job that reads has a read-only token (`permissions: contents: read`). It makes GET requests to
  GitHub's API (search, commit statuses, check runs, pull requests) and nothing else. It never clones, downloads or
  runs a file of a sampled repository. A second job, which reads nothing, adds the week to `agent_weekly.json` and
  opens the pull request.
- **Each hit keeps its date**, claimed or not, so "Sampled" for a week read this way is never unknown.

## Method

1. **Find.** For each agent, GitHub's issue search is asked for pull requests that match the agent and one of six
   claim phrases ("tests pass", "all tests pass", "tests passing", "CI passes", "CI is green", "CI passing"),
   created in the week. These are **sampled**. Pull requests on a repository owned by their author, or by the
   person who assigned the agent, are set aside first (the committed sample of 2026-10-01 kept them).
2. **Read the claim.** The description is read line by line. A line counts as a claim only when it says tests or CI
   pass, and not when it is an unticked box, a wish ("should pass"), a condition or a negation. These are **claimed
   passing**.
3. **Read the checks.** For each claimed pull request, the check runs and commit statuses at its head commit are
   read once. CI has **finished** when nothing is pending and at least one check exists. The pull request **failed a
   check anyway** when a check run concluded `failure`, `timed_out` or `startup_failure`, or a status is `failure` or
   `error`. The agent's own session run is not a check.
4. **Read the merge.** Whether each pull request with finished CI was merged when read. **Merged despite a failed
   check** is the merged ones with a failed check, over all merged ones with finished CI.
5. **Group.** By agent and by the Monday (UTC) of the week the pull request was created.
6. **Interval.** Every share comes with its 95% Wilson score interval (z = 1.96). With 5 pull requests in a week the
   interval is wide; that is the honest answer for that week.
7. **Rank.** Only among agents with at least 30 claimed pull requests whose CI had finished in that week: place 1 is
   the smallest share that failed a check, and equal shares share a place. Every other agent is "too few to rank"
   and is never given a place. Weeks added up are never ranked.
8. **Verified.** The count of a week's claimed pull requests that were also paid through Knos under terms with a
   black-box check: an acceptance check the pull request could not edit, attested by a signed CI run. It is 0 today.
   No sampled pull request has been paid through Knos, whose payments so far are test USDC on Solana devnet. The
   script counts it from a list of such payments (`--paid`); until one is given, the file says no list was joined.

How each agent is told apart (`agents_told_by` and `heuristics` in the JSON). Each qualifier returned pull requests
when the sample was read on 2026-10-01 (179, 180, 180, 180 and 114 hits):

| Agent | Told by | What it misses |
| --- | --- | --- |
| copilot | the pull request's author is the GitHub App `copilot-swe-agent` | Copilot used in an editor or a terminal, which opens pull requests under the person's own account |
| devin | the author is the GitHub App `devin-ai-integration` (Devin's default is to open pull requests as itself) | an organisation that set Devin to open pull requests as the user ([Devin's GitHub settings](https://docs.devin.ai/integrations/gh)) |
| claude-bot | the author is the GitHub App `claude` | an installation that runs under its own app or a person's token |
| claude-code | the description holds the line "Generated with Claude Code", and the author is not the app `claude` | anyone who turned the line off in settings; a person who pastes the line is counted |
| codex | the description holds a `chatgpt.com/codex/tasks` link | Codex run locally, which writes no link; a person who pastes a link is counted |

Since 16 July 2026 GitHub's API also lists Copilot's pull requests under the person who asked for them
([changelog](https://github.blog/changelog/2026-06-18-copilot-authored-pull-requests-now-included-in-author-searches)).
The app qualifier used here is not changed by that. The app accounts could not be looked up again from the machine
this release was built on; the hit counts above are the evidence that the qualifiers match.

## What is and is not concluded

**Concluded:** the description said tests or CI pass, and GitHub's record at the head commit, read once, shows a
failed check.

**Not concluded:** that the claim was false, that the tests failed, that the code is wrong, or that one agent writes
better code than another. A failed check is not proof that the claim was false: it may be a deploy preview or a label gate
(the JSON gives the narrower count, `test_or_build`, beside it), it may be flaky, and it may have been failing
before the pull request. A rank orders one week's recorded mismatches and nothing else.

## Limits

- **Authorship is a heuristic.** Three agents are told by their app account, two by a line their tool writes in the
  description. A person who pastes that line is counted as the agent. An agent that runs under a person's own
  account and leaves no line is not counted at all. A pull request found under two agents' queries counts once, for
  the first agent in the table.
- **Bot-author heuristics** decide which pull requests are seen at all, so the agents' rows are not samples of the
  same kind of work: the agents are used on different repositories with different checks.
- **Public repositories only.** GitHub's search returns nothing from private ones, where most paid work happens.
- **One snapshot of the checks.** What GitHub showed at the head commit at the moment of reading, one to two days
  after the week ends. A check run again later, a commit pushed after, or a check that had not started is not seen.
- **The search asks for claim phrases.** "Sampled" is not every pull request the agent opened, so nothing here is a
  rate per pull request opened.
- **The file mixes two ways of reading** until the weekly run has replaced every week: rows with `full_week: false`
  are the capped sample of 2026-10-01, and are thinner than the agent's real activity.

## The file

`agent_weekly.json`: `name`, `read`, `window`, `latest_week`, `source`, `agents_told_by`, `heuristics`,
`claim_search`, `definitions`, `limits`, `min_claims_to_rank`, `verified_against`, and for each agent `weeks` (one
object per week) and `all_weeks`. Each has `sampled`, `claimed_passing`, `ci_finished`, `failed_a_check`,
`merged_despite_failed_check` and `verified`; the two rates are `{k, n, share, ci95}`. A week also has `read`,
`full_week` and `rank`. A `null` means the source did not hold that fact, never zero.

Make it again from the committed sample, offline:

    python scripts/agent_pr_index.py weekly --sample docs/agent_pr_ci.json --out docs/agent_weekly.json --doc docs/INDEX.md

Read one week and add it (needs `gh` signed in; this is what the workflow runs):

    python scripts/agent_pr_index.py scan --week last --rows week.json
    python scripts/agent_pr_index.py weekly --rows week.json --into docs/agent_weekly.json --doc docs/INDEX.md

The site draws the same table with `renderIndexBoard` in [`web/index_board.js`](../web/index_board.js).

## Related documents

- [OUTCOMES.md](OUTCOMES.md): what "paid on a black-box check" means, the condition of the table's last column, shown
  on three outcomes that are not a merged pull request.
- [CONSOLE.md](CONSOLE.md): the operator's screen, where a buyer sees for one deliverable what this index counts
  across many: the claim, the checks GitHub recorded, and whether it was accepted.
