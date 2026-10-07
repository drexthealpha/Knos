# Agent PR Index

A pull request opened by a coding agent often says "tests pass". The Agent PR Index says how often GitHub's own record
of the checks agrees, for each agent it tells apart. It is published every week, under one name and one date:
**"Agent PR Index, week of <Monday>"**.

Read it as a page ([the site's Index view](https://drexthealpha.github.io/Knos/#index)), as data
([`index.json`](index.json), schema `knos.agent-pr-index/1`) or as a feed to subscribe to ([`index.atom`](index.atom)).
[`.github/workflows/index.yml`](../.github/workflows/index.yml) reads the new week every Monday and proposes it as one
pull request a person merges.

## The leaderboard

<!-- board:begin (written by scripts/agent_pr_index.py board; do not edit by hand) -->
**Agent PR Index, week of 2026-09-28.** Read 2026-10-07. Every week read up to this one, added up. An agent with fewer than 30 merged pull requests in its row is "too few to rank".

| Place | Agent | Claimed passing tests | Failed check at merge, of merged | Rate | 95% interval | Row |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | claude-bot | 195 | 10 of 165 | 6.1% | 3.3% to 10.8% | [dispute](https://github.com/drexthealpha/Knos/issues/new?template=dispute-index-row.yml&title=Dispute+a+row%3A+claude-bot%2C+week+of+2026-09-28&agent=claude-bot&week=2026-09-28) |
| 2 (overlaps) | codex | 52 | 3 of 44 | 6.8% | 2.4% to 18.2% | [dispute](https://github.com/drexthealpha/Knos/issues/new?template=dispute-index-row.yml&title=Dispute+a+row%3A+codex%2C+week+of+2026-09-28&agent=codex&week=2026-09-28) |
| 3 (overlaps) | claude-code | 41 | 3 of 31 | 9.7% | 3.4% to 24.9% | [dispute](https://github.com/drexthealpha/Knos/issues/new?template=dispute-index-row.yml&title=Dispute+a+row%3A+claude-code%2C+week+of+2026-09-28&agent=claude-code&week=2026-09-28) |
| 4 (overlaps) | copilot | 132 | 22 of 80 | 27.5% | 18.9% to 38.1% | [dispute](https://github.com/drexthealpha/Knos/issues/new?template=dispute-index-row.yml&title=Dispute+a+row%3A+copilot%2C+week+of+2026-09-28&agent=copilot&week=2026-09-28) |
| 5 | devin | 148 | 56 of 107 | 52.3% | 43.0% to 61.6% | [dispute](https://github.com/drexthealpha/Knos/issues/new?template=dispute-index-row.yml&title=Dispute+a+row%3A+devin%2C+week+of+2026-09-28&agent=devin&week=2026-09-28) |

An agent vendor never pays for a row and cannot pay to change one.

**Method, in ten lines.**

1. **The agent.** Told by the GitHub App that opened the pull request, or by a line its tool writes in the description (`agents_told_by` in the file). A person who pastes that line is counted as the agent.
2. **The search.** GitHub's issue search, for pull requests of that agent whose description holds one of six phrases: "tests pass", "all tests pass", "tests passing", "CI passes", "CI is green", "CI passing".
3. **Claimed passing tests.** The description is read line by line (`CLAIM_RE` in `scripts/agent_pr_ci.py`). A line that says tests or CI pass is a claim; an unticked box, a wish ("should pass") or a negation is not.
4. **The checks.** The check runs and commit statuses GitHub holds for the head commit, read once.
5. **A failed check** is a check run that concluded `failure`, `timed_out` or `startup_failure`, or a commit status of `failure` or `error`. The agent's own session run is not a check.
6. **A failed check is not always a failed test.** It may be a deploy preview, a label gate, a review bot or a scanner; it may be flaky; it may have been failing before the pull request.
7. **A failed check is not always a false claim.** The description may be true of the tests its author ran. The row says only that GitHub recorded a failed check on the commit that was merged.
8. **The row.** Of the merged pull requests that claimed passing tests and whose checks had finished: how many had a failed check, that count over the total, and the 95% Wilson interval of the share.
9. **The place.** Only agents with at least 30 such pull requests have one: place 1 is the smallest share, equal shares share a place. The others are "too few to rank", shown with their counts. "overlaps" means the interval reaches into the one above: this sample does not tell those two places apart.
10. **The week.** A board is named by a Monday and adds up every week read up to and including it. Each week's own counts, and how it was read, are in [`agent_weekly.json`](agent_weekly.json).

**Limits.**

- The counts are Knos's own measurement. Nobody outside Knos has reviewed them: dispute a row below.
- The samples are unequal, so the size sits beside every rate. Read the interval, not the share.
- The weeks were not all read with the same design (`design` of each week in `agent_weekly.json`). Adding them up mixes those designs.
- The agents are used on different repositories with different checks, so the rows are not samples of the same work.
- Public repositories only, and only pull requests whose description holds a claim phrase.
- One reading of the checks, a day or more after the week ended. A check run again later is not seen.
- "At merge" is the head commit of a pull request that was merged when read, not the moment of the merge.

**Work it again.** One command, no network, from the files of this repository. It counts the table again from [`agent_weekly.json`](agent_weekly.json) and fails when this page, [`index.json`](index.json) or [`index.atom`](index.atom) says anything else:

    python scripts/agent_pr_index.py board --check

Every pull request behind the weeks read on 2026-10-01 is listed in [`agent_pr_ci.json`](agent_pr_ci.json) by repository and number, so each can be opened on GitHub and looked at.

**Disputes.** Anyone can [dispute a row](https://github.com/drexthealpha/Knos/issues/new?template=dispute-index-row.yml): name the agent, the pull requests counted wrongly, and the evidence. An open dispute marks its row with † and its link.

No row has been disputed yet.

**Changelog.** Every resolved dispute that changed a number.

No number has changed after a dispute yet.
<!-- board:end -->

**The rule, in full.** Knos never charges an agent vendor for its rating, and a vendor cannot pay to change it. No
vendor can pay to be listed, to be left out, to see a week early or to have a row read again. The method, the script
and every count are public, so a rating can be worked again by anyone.

**What a dispute is.** An issue opened with the "Dispute a row" form: the agent, the pull requests that were counted
wrongly, and the evidence. It is listed in [`index_disputes.json`](index_disputes.json) with its link and its state
(`open`, `resolved` or `rejected`), and while it is open its row carries a mark on this page, on the site and in the
feeds. When a dispute is resolved, what was found is written beside it; if a number changed, the change is listed in
the changelog above with the number before and after. Opening, resolving or winning a dispute costs nothing.

## The newest week alone

The headline number of one week alone is each agent's **verified acceptance rate**: of the pull requests that claimed
passing tests, the share whose checks all passed, with a 95% Wilson interval. One week holds few pull requests for
most agents, which is why the leaderboard above adds the weeks up. The numbers are in
[`agent_weekly.json`](agent_weekly.json); the script that makes them is
[`scripts/agent_pr_index.py`](../scripts/agent_pr_index.py).

<!-- weekly:begin (written by scripts/agent_pr_index.py weekly; do not edit by hand) -->
**Agent PR Index, week of 2026-09-28.** Read 2026-10-07. Design: stratified-seeded-v1. Capped: false. Verified acceptance rate: of the pull requests that claimed passing tests and whose checks were read, the share whose checks all passed. An agent with fewer than 30 such pull requests that week is "too few to rank" and has no place.

| Place | Agent | Verified acceptance rate (95% interval) | Sampled | Claimed passing | Failed a check anyway (95% interval) | Merged despite a failed check (95% interval) | Also paid through Knos on a black-box check | Sample |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | claude-bot | 90 of 103 (87.4%; 79.6% to 92.5%) | 207 | 103 | 6 of 99 (6.1%; 2.8% to 12.6%) | 5 of 83 (6.0%; 2.6% to 13.3%) | 0 | not capped: drew 210 of 210 planned, of 424 the search reported |
| 2 | devin | 15 of 75 (20.0%; 12.5% to 30.4%) | 121 | 75 | 54 of 73 (74.0%; 62.9% to 82.7%) | 51 of 68 (75.0%; 63.6% to 83.8%) | 0 | not capped: drew 210 of 210 planned, of 5,883 the search reported |
| too few to rank | copilot | 15 of 23 (65.2%; 44.9% to 81.2%) | 54 | 23 | 4 of 19 (21.1%; 8.5% to 43.3%) | 4 of 17 (23.5%; 9.6% to 47.3%) | 0 | not capped: drew 210 of 210 planned, of 676 the search reported |
| too few to rank | claude-code | 9 of 14 (64.3%; 38.8% to 83.7%) | 59 | 14 | 3 of 12 (25.0%; 8.9% to 53.2%) | 2 of 10 (20.0%; 5.7% to 51.0%) | 0 | not capped: drew 210 of 210 planned, of 1,608,162 the search reported |
| too few to rank | codex | 2 of 2 (100.0%; 34.2% to 100.0%) | 98 | 2 | 0 of 2 (0.0%; 0.0% to 65.8%) | 0 of 2 (0.0%; 0.0% to 65.8%) | 0 | not capped: drew 136 of 136 planned, of 246 the search reported |

Also paid through Knos, checked against: no list of Knos payments was joined to this sample, so the count is 0 for every agent: every Knos payment so far is test USDC on Solana devnet. It takes a sampled pull request that was also paid through Knos under terms with a black-box check, and that list given to the script (--paid).

Every week in the file added up (2026-07-03 to 2026-10-04; never ranked: the weeks were not all read the same way). Source: each week says how it was read (`design`, `capped`, `strata`). The newest: week of 2026-09-28, read 2026-10-07, stratified-seeded-v1; read on 2026-10-07 and not whole weeks: the weeks of 2026-09-28 (`full_week` false).

| Place | Agent | Verified acceptance rate (95% interval) | Sampled | Claimed passing | Failed a check anyway (95% interval) | Merged despite a failed check (95% interval) | Also paid through Knos on a black-box check | Sample |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| not ranked | copilot | not recorded | not kept | 132 | 31 of 111 (27.9%; 20.4% to 36.9%) | 22 of 80 (27.5%; 18.9% to 38.1%) | 0 | weeks added up |
| not ranked | devin | 61 of 148 (41.2%; 33.6% to 49.3%) | not kept | 148 | 68 of 135 (50.4%; 42.0% to 58.7%) | 56 of 107 (52.3%; 43.0% to 61.6%) | 0 | weeks added up |
| not ranked | claude-bot | 171 of 195 (87.7%; 82.3% to 91.6%) | not kept | 195 | 14 of 189 (7.4%; 4.5% to 12.0%) | 10 of 165 (6.1%; 3.3% to 10.8%) | 0 | weeks added up |
| not ranked | claude-code | 29 of 41 (70.7%; 55.5% to 82.4%) | not kept | 41 | 4 of 33 (12.1%; 4.8% to 27.3%) | 3 of 31 (9.7%; 3.4% to 24.9%) | 0 | weeks added up |
| not ranked | codex | not recorded | not kept | 52 | 9 of 52 (17.3%; 9.4% to 29.7%) | 3 of 44 (6.8%; 2.4% to 18.2%) | 0 | weeks added up |
<!-- weekly:end -->

**What is published today.** The table above is the newest week of `agent_weekly.json`: the week of 28 September
2026, read on 2026-10-06 with the design below (`stratified-seeded-v1`) from the release machine, in four bounded
runs of 24 to 28 minutes continued from one checkpoint (about 100 minutes in all, the budget of the workflow's two
Monday runs), each run at most 500 requests and at least 4.8 seconds between two. The week is `capped`: 559 of the
976 planned draws (17 of 30 turns), 120 of them claiming passing tests, every one of those with its checks read. Two
agents have 30 claims in the week and a place; the other three are too few to rank: read each interval, not each
share. That week was read twice before, both on 2026-10-05: first by a capped scan before this design (each agent's
newest claimed pull requests, at most 120, `newest-first-capped-v0`), which did not record how many passed every
check, then with this design by a run that stopped at the first refusal (95 of 930 planned draws). Each newer
reading of the same week replaced the one before. The week of 21 September keeps that scan's numbers as published (39 claimed pull requests),
with its verified acceptance rate `null` and `not_derived` saying why; a row with no rate has no place.
The older weeks are the sample read once, on 2026-10-01 (`search-window-sample-v0`, at most 20 hits a search window);
its rows are in [`agent_pr_ci.json`](agent_pr_ci.json), so their rate is worked out, and none has 30 claims in a week.
No week has been read with the design on GitHub's runners yet: the first Monday run after this release adds one.

## The sampling design

Name in the file: `stratified-seeded-v1`. The week is the one that ended the Sunday before (Monday 00:00 to Sunday
23:59:59 UTC).

1. **Strata.** Each agent on each day of the week is one stratum: 5 agents x 7 days = 35. The day is the UTC day the
   pull request was opened.
2. **The frame.** For a stratum, GitHub's issue search is asked for pull requests that match the agent and one of
   six claim phrases, created that day, newest first. The first page says how many there are (`reported`). The
   results are numbered from 0, the newest.
3. **What a query can reach.** GitHub returns at most 1,000 results for a search. The same search asked oldest first
   reaches 1,000 more. So up to 2,000 results a stratum every result can be drawn; above that the middle cannot, and
   `reachable` is smaller than `reported`.
4. **The seeded order.** The reachable numbers are sorted by `sha256("<ISO week>|<agent>|<date>|<number>")`, for
   example `sha256("2026-W40|devin|2026-09-30|17")`. The seed is the ISO week, so the order is fixed before anything
   is read, and anyone can work it again.
5. **The draw.** The first 30 in that order are drawn (`--per-stratum`): the same number in every stratum, fewer only
   where a stratum holds fewer (`planned`). Strata are served in turns, one draw each.
6. **The checks.** Of the drawn, the ones whose description claims passing tests have their checks and merge state
   read, in the same turns.
7. **The budget.** A run sends at most 500 requests (`--max-requests`) and reads for at most 50 minutes
   (`--max-minutes`). The checks are read as the draw goes, and the search leaves the last 6 requests and 45 seconds
   for the checks of what it drew last. When the budget ends the run stops and publishes what it has.
8. **Why a capped week is still a sample.** Because strata are served in turns and each is drawn in its own seeded
   order, a run that stops early holds, for every stratum, the first few of that order, the same number in each to
   within the turn it stopped in: a simple random sample of what could be reached, only smaller. It is not "whatever came first". The week is then marked `capped: true`, and
   `strata` says, for each day, `reported`, `reachable`, `planned`, `drawn`, `claimed` and `checks_read`.
9. **Resuming.** Everything read is written to a checkpoint after every request. A run that was cut starts from it
   and asks only for what is missing; the result is the same sample an uncut run would have drawn.
10. **What the rates are.** Shares of the sample. Every day is drawn equally, so a busy day weighs the same as a
    quiet one; `strata` holds what is needed to weigh the days by what they held.

**Inside GitHub's limits** (guidance read again on 2026-10-06):

- Search: 30 requests a minute for a signed-in caller, and 1,000 results a query
  ([REST API: search](https://docs.github.com/en/rest/search/search)). The whole design needs at most 35 x 10 = 350
  pages of 100, and no query asks past result 1,000.
- Checks: one GraphQL query reads the checks of 20 pull requests. `statusCheckRollup` on a commit holds its check
  runs and commit statuses together. A query costs the connections it asks for, divided by 100: 60 connections for
  20 pull requests, 1 point. The workflow's token has 1,000 points an hour
  ([GraphQL API: rate limits](https://docs.github.com/en/graphql/overview/rate-limits-and-query-limits-for-the-graphql-api)).
  35 x 30 = 1,050 draws need 53 queries if every one claims passing tests.
- Fallback: when GraphQL refuses the token, the checks are read over REST, three to four requests a pull request
  against 1,000 an hour
  ([REST API: rate limits](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api)). The
  budget then ends first, and the week is published capped.
- Secondary limits. GitHub also refuses requests that come too fast or too many at once, whatever the hourly budget
  holds. Its guidance
  ([best practices](https://docs.github.com/en/rest/using-the-rest-api/best-practices-for-using-the-rest-api)) is
  what the scanner does:
  - **One at a time.** "Make requests serially instead of concurrently": one request is in flight, never two.
  - **Spread out.** A run's requests are spread over four fifths of its minutes: 500 over 40 minutes, one every 4.8
    seconds, about 12 a minute.
  - **Wait as told.** After a refusal with a `retry-after` header the scanner waits that many seconds. With
    `x-ratelimit-remaining: 0` it waits until `x-ratelimit-reset`. Otherwise it waits one minute, then two, four and
    eight ("wait for at least one minute", "an exponentially increasing amount of time"), and then gives up on the
    request.
  - **Stop when the wait does not fit.** A wait longer than the run has left ends the run. The checkpoint keeps the
    time GitHub named (`cursor.come_back`), and the next run does not ask before it.
  - **Conditional requests.** An answer already held that has grown old is asked for again with `if-none-match` and
    its ETag; a `304 Not Modified` leaves the kept answer in place and does not count against the primary limit.
  - **Resume.** `week.json` is the cursor file: every search page and every verdict read so far, and `cursor` (strata
    counted, draw turn, pages, checks read). A second run on the same Monday continues from it.

The first bounded run, on 2026-10-05, did none of the waiting: it stopped at the first refusal, after a few searches,
with 95 of 930 planned draws. On 2026-10-06 the scanner above read the same week against GitHub, from the release
machine with a signed-in token. GitHub refused a search for its secondary limit 31 times in those 100 minutes. Every
refusal whose headers were logged (23 of them) carried no `retry-after`, and an `x-ratelimit-remaining` of 25 to 29
of the search minute's 30, with 1 to 5 used: so the scanner waited one minute each time and went on, and the last
run ended when the wait no longer fitted, with the time to come back in its checkpoint. A search took about 9 seconds
to answer (99 timed). These searches therefore go at two to three a minute, not the 12 the pacing allows, and a week
takes several runs, which the checkpoint carries. `gh api -i` was read as GitHub answers it (the status line, the
headers, then the body), and a 304 to a request with its ETag left the kept answer in place without moving
`x-ratelimit-remaining`; `tests/test_agent_pr_index.py` holds both to that shape.

The GraphQL query was written from GitHub's published schema and was answered by GitHub in that reading: the checks
of the 120 drawn pull requests that claimed passing tests were read with it, and over REST for the few a query did
not settle. The REST path is the one the earlier scans used.

**Why the earlier weekly scan could not finish.** It read every hit of the week, with no cap. Each claimed pull
request cost three to four REST requests (the combined status, the check runs, the check suites when there were
neither, then the pull request for its merge state) against the token's 1,000 an hour: about 250 to 330 pull requests
an hour. When the hour's budget was spent it slept until the hour came back, and a refused search slept up to 90
seconds, up to six times. It also waited behind the six-hourly index job, which spends the same hourly budget. And a
week not read whole was refused, so the hours it did spend published nothing. On 5 October 2026 it ran for five hours
on GitHub: one agent's search did not finish, most of the week's checks were not read, and no week was added.

**Safety.** The job that reads has a read-only token (`permissions: contents: read`). It sends GET requests to
GitHub's search and read-only GraphQL queries (no mutation), and GET requests for statuses, check runs and pull
requests on the REST path. It never clones, downloads or runs a file of a sampled repository. A second job, which
asks GitHub's API nothing, adds the week to `agent_weekly.json`, writes the leaderboard and its feeds, and opens the
pull request. Nothing pushes to the
default branch.

## Method

1. **Find.** The six claim phrases are "tests pass", "all tests pass", "tests passing", "CI passes", "CI is green"
   and "CI passing". The drawn pull requests are **sampled**. Ones on a repository owned by their author, or by the
   person who assigned the agent, are set aside first and not counted. One found under two agents' queries counts
   once, for the first agent in the table below.
2. **Read the claim.** The description is read line by line. A line counts as a claim only when it says tests or CI
   pass, and not when it is an unticked box, a wish ("should pass"), a condition or a negation. These are **claimed
   passing**.
3. **Read the checks.** For each claimed pull request, the check runs and commit statuses at its head commit are
   read once. Each lands in one of `checks`: `passed` (at least one check, none failed, none pending, every one
   succeeded, was neutral or was skipped), `failed` (a check run concluded `failure`, `timed_out` or
   `startup_failure`, or a status is `failure` or `error`), `other` (finished with a cancelled or stale check and no
   failure), `pending`, `no_checks`, or `not_read` (the budget ended first). The agent's own session run is not a
   check.
4. **Verified acceptance rate.** `passed` over every claimed pull request whose checks were read. A claim with no
   check behind it, or with checks still running when read, is not verified. This is the headline.
5. **Failed a check anyway.** `failed` over the claimed pull requests whose CI had finished (`passed`, `failed`,
   `other`).
6. **Merged despite a failed check.** The merged ones with a failed check, over all merged ones with finished CI.
7. **Interval.** Every share comes with its 95% Wilson score interval (z = 1.96). With 5 pull requests in a week the
   interval is wide; that is the honest answer for that week.
8. **Place.** Only among agents with at least 30 claimed pull requests whose checks were read in that week: place 1
   is the largest verified acceptance rate, and equal rates share a place. Every other agent is "too few to rank"
   and is never given a place. Weeks added up are never ranked.
9. **Also paid through Knos** (`verified` in the file). The count of a week's claimed pull requests that were also
   paid through Knos under terms with a black-box check: an acceptance check the pull request could not edit,
   attested by a signed CI run. It is 0 today. No sampled pull request has been paid through Knos, whose payments so
   far are test USDC on Solana devnet. The script counts it from a list of such payments (`--paid`); until one is
   given, the file says no list was joined.

## How each agent is told apart

Agents are named as the public data names them: by the GitHub App that opened the pull request, or by the line the
tool writes in the description (`agents_told_by` and `heuristics` in the JSON). Each qualifier returned pull requests
when the sample was read on 2026-10-01 (179, 180, 180, 180 and 114 hits).

| Agent | Told by | What it misses | Source |
| --- | --- | --- | --- |
| copilot | the pull request's author is the GitHub App `copilot-swe-agent` | Copilot used in an editor or a terminal, which opens pull requests under the person's own account | [GitHub: about the coding agent](https://docs.github.com/en/copilot/concepts/agents/coding-agent/about-coding-agent) |
| devin | the author is the GitHub App `devin-ai-integration` (Devin's default is to open pull requests as itself) | an organisation that set Devin to open pull requests as the user | [Devin: GitHub integration](https://docs.devin.ai/integrations/gh) |
| claude-bot | the author is the GitHub App `claude` | an installation that runs under its own app or a person's token | [Claude Code GitHub Actions](https://code.claude.com/docs/en/github-actions) |
| claude-code | the description holds the line "Generated with Claude Code", and the author is not the app `claude` | anyone who changed or hid the line (`attribution.pr`); a person who pastes the line is counted | [Claude Code settings](https://code.claude.com/docs/en/settings-reference) |
| codex | the description holds a `chatgpt.com/codex/tasks` link | Codex run locally, which writes no link; a person who pastes a link is counted | [Codex cloud](https://developers.openai.com/codex/cloud) says it opens pull requests; the link is what the sampled descriptions hold, not something that page states |

Since 16 July 2026 GitHub's API also lists Copilot's pull requests under the person who asked for them
([changelog](https://github.blog/changelog/2026-06-18-copilot-authored-pull-requests-now-included-in-author-searches)).
The app qualifier used here is not changed by that. The app accounts could not be looked up again from the machine
this release was built on; the hit counts above are the evidence that the qualifiers match.

## What a failed check does and does not mean

**It means:** the description said tests or CI pass, and GitHub's record at the head commit, read once, shows a
failed check.

**It does not mean:** that the claim was false, that the tests failed, that the code is wrong, or that one agent
writes better code than another. A failed check is not proof that the claim was false: it may be a deploy preview or
a label gate (the JSON gives the narrower count, `test_or_build`, beside it), it may be flaky, and it may have been
failing before the pull request.

**A pull request that is not verified** did not have to fail anything: its repository may run no checks at all, or
its checks were still running when read. `checks` gives each count.

**A place** orders one week's record against what was said, and nothing else.

## Limits

- **Authorship is a heuristic.** Three agents are told by their app account, two by a line their tool writes in the
  description. A person who pastes that line is counted as the agent. An agent that runs under a person's own
  account and leaves no line is not counted at all.
- **Bot-author heuristics** decide which pull requests are seen at all, so the agents' rows are not samples of the
  same kind of work: the agents are used on different repositories with different checks.
- **Public repositories only.** GitHub's search returns nothing from private ones, where most paid work happens.
- **One snapshot of the checks.** What GitHub showed at the head commit at the moment of reading, one day or more
  after the week ends. A check run again later, a commit pushed after, or a check that had not started is not seen.
- **The search asks for claim phrases.** "Sampled" is not every pull request the agent opened, so nothing here is a
  rate per pull request opened.
- **A sample, not a census.** At most 30 draws a stratum, 210 an agent a week. Read the interval, not the share.
- **A stratum above 2,000 results** cannot be drawn from its middle hours (`reachable` under `reported`).
- **The file mixes designs.** Each row names its own (`design`); rows of different designs are not comparable, and
  the weeks added up are never ranked.

## The file

`agent_weekly.json`: `name`, `read`, `window`, `latest_week`, `source`, `agents_told_by`, `heuristics`,
`claim_search`, `definitions`, `designs`, `limits`, `min_claims_to_rank`, `verified_against`, and for each agent
`weeks` (one object per week) and `all_weeks`. Each has `sampled`, `claimed_passing`, `ci_finished`, `checks`,
`verified_acceptance_rate`, `failed_a_check`, `merged_despite_failed_check` and `verified`; the rates are
`{k, n, share, ci95}`. A week also has `read`, `design`, `capped`, `strata`, `full_week`, `rank`, `ranked_by` and
`not_derived`; a stratified week has `seed` and `per_stratum` too. A `null` means the source did not hold that fact,
never zero, and `not_derived` gives the reason.

Sample last week and add it (needs `gh` signed in; this is what the workflow runs). The first command may be run
again: it continues from `week.json`.

    python scripts/agent_pr_index.py sample --week last --rows week.json --max-requests 500 --max-minutes 50
    python scripts/agent_pr_index.py weekly --rows week.json --into docs/agent_weekly.json --doc docs/INDEX.md
    python scripts/agent_pr_index.py board

Write the committed file again in today's format, offline (it changes nothing when the file is current):

    python scripts/agent_pr_index.py weekly --sample docs/agent_pr_ci.json --restate docs/agent_weekly.json --doc docs/INDEX.md

`index.json` (schema `knos.agent-pr-index/1`): `latest_week`, `read`, `min_claims_to_rank`, `rule`, `measure`,
`method`, `limits`, `source` (the hash of the series it was counted from, and the command), `links`, `weeks` (one
board a week, newest first: `rows` with `agent`, `claimed_passing`, `merged`, `failed_at_merge`, `share`, `ci95`,
`rank`, `status`, `overlaps_above`, `disputed`, `dispute`), `disputes` and `changelog`. A change that removes or
renames a field gets a new schema name. `index.atom` has one entry a week with the same rows in words.

The site draws the same leaderboard with `renderIndexBoard` in [`web/index_board.js`](../web/index_board.js): bars with
interval whiskers, a "Dispute this row" link and a badge for each row.

## Related documents

- [SHADOW.md](SHADOW.md): which changes on an invoice had a failed check when they were merged, read from GitHub alone.
- [TERMS.md](TERMS.md): the terms registry, where a set of acceptance terms is cited by its hash.
- [PROVENANCE.md](PROVENANCE.md): each program from source commit to build hash to the hash on chain.
- [CONFORMANCE.md](CONFORMANCE.md): Knos's formats with test vectors, for a team that implements them itself.
- [OUTCOMES.md](OUTCOMES.md): what "paid on a black-box check" means, the condition of the table's last count, shown
  on three outcomes that are not a merged pull request.
- [CONSOLE.md](CONSOLE.md): the operator's screen, where a buyer sees for one deliverable what this index counts
  across many: the claim, the checks GitHub recorded, and whether it was accepted.
