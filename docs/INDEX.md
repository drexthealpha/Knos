# Agent pull requests, by agent and by week

A pull request opened by a coding agent often says "tests pass". This page says how often GitHub's own record of the
checks agrees, for each agent the index tells apart, week by week. The numbers are in
[`agent_weekly.json`](agent_weekly.json); the script that makes them is
[`scripts/agent_pr_index.py`](../scripts/agent_pr_index.py) (`weekly`), and
[`.github/workflows/index.yml`](../.github/workflows/index.yml) runs it.

## The latest table

<!-- weekly:begin (written by scripts/agent_pr_index.py weekly; do not edit by hand) -->
Read 2026-10-01; pull requests created 2026-07-03 to 2026-09-30; source: docs/agent_pr_ci.json, the sample read on 2026-10-01, reshaped by week (nothing was read again). Unlike the index, this sample kept pull requests on repositories their author owns.

| Agent | Week of | Sampled | Claimed passing | CI finished | Failed a check (95% interval) | Merged despite a failed check (95% interval) |
| --- | --- | --- | --- | --- | --- | --- |
| copilot | 2026-09-28 | not kept | 5 | 3 | 1 of 3 (33.3%; 6.2% to 79.2%) | 1 of 3 (33.3%; 6.2% to 79.2%) |
| copilot | all weeks | 179 | 75 | 60 | 21 of 60 (35.0%; 24.2% to 47.6%) | 15 of 44 (34.1%; 21.9% to 48.9%) |
| devin | 2026-09-28 | not kept | 14 | 6 | 1 of 6 (16.7%; 3.0% to 56.4%) | 0 of 4 (0.0%; 0.0% to 49.0%) |
| devin | all weeks | 180 | 87 | 68 | 15 of 68 (22.1%; 13.9% to 33.3%) | 5 of 43 (11.6%; 5.1% to 24.5%) |
| claude-bot | 2026-09-28 | not kept | 9 | 6 | 0 of 6 (0.0%; 0.0% to 39.0%) | 0 of 3 (0.0%; 0.0% to 56.1%) |
| claude-bot | all weeks | 180 | 101 | 96 | 8 of 96 (8.3%; 4.3% to 15.6%) | 5 of 85 (5.9%; 2.5% to 13.0%) |
| claude-code | 2026-09-28 | not kept | 4 | 3 | 1 of 3 (33.3%; 6.2% to 79.2%) | 1 of 1 (100.0%; 20.6% to 100.0%) |
| claude-code | all weeks | 180 | 31 | 24 | 2 of 24 (8.3%; 2.3% to 25.9%) | 2 of 22 (9.1%; 2.5% to 27.8%) |
| codex | 2026-09-28 | not kept | 5 | 5 | 0 of 5 (0.0%; 0.0% to 43.5%) | 0 of 5 (0.0%; 0.0% to 43.5%) |
| codex | all weeks | 114 | 55 | 55 | 9 of 55 (16.4%; 8.9% to 28.3%) | 3 of 47 (6.4%; 2.2% to 17.2%) |
<!-- weekly:end -->

The table above is the sample of 349 pull requests read once, on 2026-10-01, cut into weeks. Nothing was read again
to make it: the machine this release was built on could not reach GitHub's API, and GitHub allows an anonymous
caller 60 requests an hour, against the several thousand one scan needs. The first weekly run of the workflow
replaces it with a fresh reading, through a pull request a person merges.

## Method

1. **Find.** For each agent, GitHub's issue search is asked for pull requests that match the agent and one of six
   claim phrases ("tests pass", "all tests pass", "tests passing", "CI passes", "CI is green", "CI passing"),
   created in the window. These are **sampled**. Pull requests on a repository owned by their author, or by the
   person who assigned the agent, are set aside first (the committed sample of 2026-10-01 kept them).
2. **Read the claim.** The description is read line by line. A line counts as a claim only when it says tests or CI
   pass, and not when it is an unticked box, a wish ("should pass"), a condition or a negation. These are **claimed
   passing**.
3. **Read the checks.** For each claimed pull request, the check runs and commit statuses at its head commit are
   read once. CI has **finished** when nothing is pending and at least one check exists. The pull request **failed a
   check** when a check run concluded `failure`, `timed_out` or `startup_failure`, or a status is `failure` or
   `error`. The agent's own session run is not a check.
4. **Read the merge.** Whether each pull request with finished CI was merged when read. **Merged despite a failed
   check** is the merged ones with a failed check, over all merged ones with finished CI.
5. **Group.** By agent and by the Monday (UTC) of the week the pull request was created.
6. **Interval.** Every share comes with its 95% Wilson score interval (z = 1.96). With 5 pull requests in a week the
   interval is wide; that is the honest answer for that week.

How each agent is told apart (`agents_told_by` in the JSON):

| Agent | Told by |
| --- | --- |
| copilot | the pull request's author is the app `copilot-swe-agent` |
| devin | the author is the app `devin-ai-integration` |
| claude-bot | the author is the app `claude` |
| claude-code | the description holds the line "Generated with Claude Code", and the author is not the app `claude` |
| codex | the description holds a `chatgpt.com/codex/tasks` link |

## Limits

- **Bot-author heuristics.** Three agents are told by their app account, two by a line their tool writes in the
  description. A person who pastes that line is counted as the agent. An agent that runs under a person's own
  account and leaves no line is not counted at all. A pull request found under two agents' queries counts once, for
  the first agent in the table.
- **Public repositories only.** GitHub's search returns nothing from private ones, where most paid work happens.
- **One snapshot of the checks.** What GitHub showed at the head commit at the moment of reading. A check run again
  later, a commit pushed after, or a check that had not started is not seen. A failed check can be a deploy preview
  or a label gate, not a test; the JSON gives the narrower count (`test_or_build`) beside it.
- **The search asks for claim phrases.** "Sampled" is not every pull request the agent opened, so nothing here is a
  rate per pull request opened.
- **Weeks at the ends of the window are short**, and the scan keeps at most a set number of pull requests per agent
  (the newest first), so an early week can be thinner than the agent's real activity.
- **It compares what was said with what was recorded.** It does not say the code was wrong, and it does not rank
  agents: the agents are used on different repositories with different checks.

## The file

`agent_weekly.json`: `read`, `window`, `source`, `agents_told_by`, `claim_search`, `definitions`, `limits`, and for
each agent `weeks` (one object per week) and `all_weeks`. Each has `sampled`, `claimed_passing`, `ci_finished`,
`failed_a_check` and `merged_despite_failed_check`; the last two are `{k, n, share, ci95}`. A `null` means the source
did not hold that fact, never zero.

Make it again from the committed sample, offline:

    python scripts/agent_pr_index.py weekly --sample docs/agent_pr_ci.json --out docs/agent_weekly.json --doc docs/INDEX.md
