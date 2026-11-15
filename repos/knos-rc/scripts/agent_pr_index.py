#!/usr/bin/env python3
"""agent_pr_index.py -- the Agent PR Index: of PRs by AI coding agents whose body claims tests/CI pass, what did CI
actually say at the head SHA? Same agents, claim regexes and CI verdict as agent_pr_ci.py.

Steps, so the Pages build never scans:

    python scripts/agent_pr_index.py scan --rows rows.json     # slow, resumable (.github/workflows/index.yml, 6 h)
    python scripts/agent_pr_index.py build --rows rows.json --out index.json    # offline
    python scripts/agent_pr_index.py gate --rows rows.json --out index.json [--previous last.json]   # may it go out?
    python scripts/agent_pr_index.py check --out index.json    # the root matches the listed records
    python scripts/agent_pr_index.py restate --out index.json  # recount a published index from its own records
    python scripts/agent_pr_index.py weekly --rows rows.json --out agent_weekly.json [--doc docs/reference/INDEX.md]
                                                               # the same scan by agent and by week (weekly() below)
    python scripts/agent_pr_index.py weekly --sample docs/agent_pr_ci.json --out docs/agent_weekly.json --doc docs/reference/INDEX.md
                                                               # offline: the committed sample, by week
    python scripts/agent_pr_index.py sample --week last --rows week.json [--max-requests 500 --max-minutes 50]
                                                               # the weekly run: a bounded, stratified, seeded sample
                                                               # of last week; week.json is its checkpoint (run again
                                                               # to continue); `weekly --into` then adds it, capped or not
    python scripts/agent_pr_index.py scan --week last --rows week.json          # one whole week, every hit, no limit:
                                                               # by hand only (it can take longer than a scheduled job may run)
    python scripts/agent_pr_index.py weekly --rows week.json --into docs/agent_weekly.json --doc docs/reference/INDEX.md
                                                               # offline: add that week to the published series
    python scripts/agent_pr_index.py board [--check]           # offline: the leaderboard into docs/reference/INDEX.md, docs/index.json and
                                                               # docs/index.atom, with the disputes (agent_pr_board.py)
    python scripts/agent_pr_index.py vendors [--check]         # offline: a page per vendor into docs/reference/VENDORS.md and
                                                               # docs/vendors.json: numbers, reply, disputes, badge (vendor_pages.py)
    python scripts/agent_pr_index.py scan --end <Sunday> --days 14 --per-agent N --rows rows.json
    python scripts/agent_pr_index.py weekly --rows rows.json --add-sample docs/agent_weekly.json --doc docs/reference/INDEX.md
                                                               # a capped sample of recent weeks, cut by week and
                                                               # marked so (full_week false); a week read whole stays

The weekly publication ("Agent PR Index, week of <Monday>") is the bounded sample (DESIGNS and sample_week below;
docs/reference/INDEX.md, "The sampling design"). What follows describes the older whole-week scan, kept for a run by hand: each
agent, each day, every page.
GitHub's search answers 30 requests a minute to a signed-in caller and at most 1,000 results a query
(docs.github.com/en/rest/search/search), so the week is asked as agents x days (35 queries of up to 10 pages: at most
350 requests, about 12 minutes), and a day that holds more than 1,000 is cut in halves down to an hour. That reaches
7,000 pull requests an agent a week before any cut. Reading the checks costs about three requests a pull request
against the Actions token's 1,000 an hour (docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api):
the scan waits for the budget, keeps every answer on disk, and the next run continues. Nothing but GET requests to
GitHub's API is made, and no file of a sampled repository is fetched or run.

index.yml uploads index.json as the asset of a GitHub Release tagged index-<date> (a release, not a data commit);
network.yml downloads the newest one into the Pages site.

The scan searches each agent over date windows (GitHub caps a query at 1,000 results), drops PRs on repos owned by
the PR's author or the human who assigned the agent (self repos are not a market observation; the count is kept),
and classifies CI at each head SHA, twenty pull requests to one GraphQL request (agent_pr_ci.read_checks). It is
incremental: search pages and verdicts are kept in the cache, the last published index (`--previous`) fills in what a
lost cache no longer holds, and a run asks only about what is new. With `--reserve` it reads what is left of this
hour's REST and GraphQL budgets (rate_limit, which costs nothing) and stops that many short of each. It says whether
it finished: `gate` holds back a scan that did not (out of minutes or of the hour's budget: nothing is published, the
job stays green with a note, the next run continues), and `errors` fails the run on a real error (a query GitHub
refused for itself, a finished scan that found nothing or shrank to under half, or runs that have stopped early for
two days). A partial sample is never published. The build writes:

    {"date", "window", "n_prs", "excluded_self_repo", "definitions": {...},
     "overall": COUNTS, "agents": {name: COUNTS}, "prs": [...], "root"}

    COUNTS = {"prs": n,
              "any_check_failed":           {"prs": k, "share", "ci95": [lo, hi]},
              "test_or_build_check_failed": {"prs": k, "share", "ci95"},
              "first_pr_per_repo": {"repos": n, "any_check_failed": {"repos": k, "share", "ci95"},
                                                "test_or_build_check_failed": {"repos": k, "share", "ci95"}}}

Two counts, because they answer two questions (DEFINITIONS below is published in the file itself):

    any_check_failed            GitHub recorded at least one failed check of any kind at the head commit. That
                                includes checks that test nothing: a deploy preview, a title or label gate, a review
                                bot, a coverage threshold, a security scanner.
    test_or_build_check_failed  at least one of the failed checks is, by its name, a test, build, lint or type-check
                                job (agent_pr_ci.is_testish_failure). Always the smaller number.

`ci95` is the 95% Wilson interval of `share`. `first_pr_per_repo` counts one pull request per repository (its first
in the window), so one busy repository cannot move the figure. `root` is the sha256 Merkle root over the per-PR
records, so anyone can check that the published list is the one that was counted.
"""
import argparse
import datetime as dt
import functools
import hashlib
import json
import math
import os
import sys
import time
from fractions import Fraction
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import agent_pr_ci  # noqa: E402


def merkle_root(leaves: list[bytes]) -> bytes:
    level = sorted(leaves) or [hashlib.sha256(b"").digest()]
    while len(level) > 1:
        if len(level) % 2:
            level.append(level[-1])
        level = [hashlib.sha256(level[i] + level[i + 1]).digest() for i in range(0, len(level), 2)]
    return level[0]

PR_KEYS = ("agent", "repo", "number", "sha", "class", "failed_checks", "phrase")
COMPLETED = ("failed", "passed", "other")

# What each published count counts, in the file itself: a number quoted from index.json can be checked against these.
DEFINITIONS = {
    "prs": "pull requests by the listed AI coding agents, created in `window`, whose description says tests or CI "
           "pass, on a repository owned neither by the pull request's author nor by the person who assigned the "
           "agent, and whose CI had finished at the head commit when it was read",
    "any_check_failed": "of those, the ones with at least one failed check of any kind at the head commit: a check "
                        "run that concluded failure, timed_out or startup_failure, or a commit status of failure or "
                        "error. This includes checks that test nothing (a deploy preview, a title or label gate, a "
                        "review bot, a coverage threshold, a security scanner). The agent's own session run is not "
                        "a check",
    "test_or_build_check_failed": "of those, the ones where a failed check is, by its name, a test, build, lint or "
                                  "type-check job and not a deploy preview, a policy gate, a review bot or a scanner "
                                  "(TESTISH_RE and ANCILLARY_RE in scripts/agent_pr_ci.py, on the failed check names "
                                  "each record lists, at most 10). Names decide it: a test job named `check` or "
                                  "`validate` is not counted, a lint or format job is",
    "first_pr_per_repo": "the same two counts over one pull request per repository: the lowest-numbered of its "
                         "`prs`. A repository where an agent opened many pull requests counts once",
    "share, ci95": "the count over its total (`prs` or `repos`), and the 95% Wilson interval of that share",
}


def record(c):
    return {k: c.get(k) for k in PR_KEYS}


def leaf(rec):
    return hashlib.sha256(json.dumps(rec, sort_keys=True, ensure_ascii=False).encode()).digest()


def wilson(k, n, z=1.96):
    """95% Wilson score interval for k successes in n trials; None when n == 0."""
    if not n:
        return None
    p = k / n
    d = 1 + z * z / n
    mid = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(max(0.0, mid - half), 4), round(min(1.0, mid + half), 4)]


# The two ways a pull request that said "tests pass" can have failed, by the name each is published under.
FAILED = {
    "any_check_failed": lambda r: r["class"] == "failed",
    "test_or_build_check_failed": lambda r: r["class"] == "failed" and agent_pr_ci.is_testish_failure(r),
}


def counts(mine, unit):
    """{unit: n, each FAILED name: {unit: k, "share", "ci95"}} over `mine`; `unit` says what is counted."""
    n = len(mine)
    out = {unit: n}
    for name, hit in FAILED.items():
        k = sum(1 for r in mine if hit(r))
        out[name] = {unit: k, "share": round(k / n, 4) if n else None, "ci95": wilson(k, n)}
    return out


def first_per_repo(mine):
    """One pull request per repository: the first (lowest-numbered) one in the window. A repository whose agent opened
    150 failing pull requests then counts once, like a repository with one."""
    first = {}
    for r in mine:
        key = r["repo"].lower()
        if key not in first or r["number"] < first[key]["number"]:
            first[key] = r
    return list(first.values())


def tally(mine):
    return {**counts(mine, "prs"), "first_pr_per_repo": counts(first_per_repo(mine), "repos")}


def build(rows, date, window, excluded=0):
    """rows: classified candidates with a claim; only those whose CI had finished at the head SHA are counted and
    listed. Deterministic for the same rows (order-independent)."""
    prs = sorted((record(r) for r in rows if r.get("class") in COMPLETED), key=lambda r: (r["repo"].lower(), r["number"]))
    agents = {name: tally([r for r in prs if r["agent"] == name]) for name, _ in agent_pr_ci.AGENTS}
    root = merkle_root([leaf(r) for r in prs])
    return {"date": date, "window": list(window), "n_prs": len(prs), "excluded_self_repo": excluded,
            "definitions": DEFINITIONS, "overall": tally(prs), "agents": agents, "prs": prs, "root": root.hex()}


def check(path):
    """Recompute the root from the published per-PR records; exits non-zero if the list was edited after the count."""
    with open(path, encoding="utf-8") as f:
        index = json.load(f)
    got = merkle_root([leaf(r) for r in index["prs"]]).hex()
    if got != index["root"]:
        raise SystemExit(f"{path}: root {index['root']} does not match its {len(index['prs'])} records ({got})")
    return index


def restate(index):
    """A published index, counted again from its own records under today's names. The records, and so the root, are
    the same: an index published before both counts had names can be restated without scanning again."""
    again = build(index["prs"], index["date"], index["window"], index.get("excluded_self_repo", 0))
    if again["root"] != index["root"]:
        raise SystemExit(f"root {index['root']} does not match its {len(index['prs'])} records ({again['root']})")
    return again


def last_week(today=None):
    """The Monday of the newest week that has ended (UTC): on a Monday, the one seven days before."""
    today = today or dt.datetime.now(dt.timezone.utc).date()
    return (today - dt.timedelta(days=today.weekday() + 7)).isoformat()


def scan_week(monday, max_seconds, read=None):
    """Every hit of one whole week (Monday to Sunday, UTC): each agent asked day by day with no cap, then the checks
    and the merge state of the claimed ones. The result carries `week`; `weekly --into` adds it to the series."""
    day = dt.date.fromisoformat(monday)
    if day.weekday():
        raise SystemExit(f"--week {monday} is not a Monday. Name the Monday the week starts on, or `last`.")
    got = scan((day + dt.timedelta(days=6)).isoformat(), 7, 10**9, max_seconds, width=1, prune_days=None)
    read_merged(got["rows"])
    return {**got, "week": monday, "read": read or dt.datetime.now(dt.timezone.utc).date().isoformat()}


def scan(end, days, per_agent, max_seconds, width=None, prune_days=0, previous=None, reserve=None):
    """Search, then read CI for what the search kept. Never throws work away: an agent whose search ran out of time
    keeps what it found, and the result says what is missing (`unfinished_search`, `unread`) so `gate` can hold it
    back. Incremental: search pages and verdicts already read are kept on disk (agent_pr_ci.CACHE), and `previous`
    (the last published index) fills in the verdicts a lost cache no longer holds, so a run asks GitHub only for what
    is new. `reserve`: the run spends this hour's REST and GraphQL budgets down to that many of each and stops there
    (`stopped` says why, `come_back` when GitHub said to); None: no hourly budget is read."""
    agent_pr_ci.ARGS = SimpleNamespace(max_seconds=max_seconds)
    agent_pr_ci.SEARCH_PAUSE = 2.1  # concurrent agents share one 30/min search pacing; gh_get backs off on 403/429
    agent_pr_ci.STOPPED[0], agent_pr_ci.COME_BACK[0] = None, None
    del agent_pr_ci.NO_CLAIM[:], agent_pr_ci.SEARCH_ERRORS[:]
    if prune_days is not None:      # the week's scan shares the index's cache and must not empty it
        agent_pr_ci.prune(prune_days or days + 7)     # answers about pull requests that have left the window
    seeded = agent_pr_ci.seed_verdicts(previous) if previous else 0
    if reserve is not None:
        left = dict(agent_pr_ci.budget(reserve))
        print(f"this hour's budget for the scan: {left['core']} REST and {left['graphql']} GraphQL requests "
              f"({reserve} of each kept for the rest of the job and the other workflows)", file=sys.stderr)
    try:
        kept, n, unfinished = agent_pr_ci.scan_collect(end, days, per_agent, width)
        agent_pr_ci.read_checks(kept)
    finally:
        agent_pr_ci.LEFT.clear()
    start = (dt.date.fromisoformat(end) - dt.timedelta(days=days - 1)).isoformat()
    unread = sum(1 for c in kept if c.get("class") is None or (c["class"] == "error" and c.get("transient")))
    come = agent_pr_ci.COME_BACK[0]
    return {"window": [start, end], "counts": n, "kept": len(kept), "unfinished_search": unfinished, "unread": unread,
            "search_errors": list(agent_pr_ci.SEARCH_ERRORS), "seeded": seeded,
            "stopped": agent_pr_ci.STOPPED[0] if unfinished or unread else None,
            "come_back": dt.datetime.fromtimestamp(come, dt.timezone.utc).isoformat(timespec="seconds") if come and (unfinished or unread) else None,
            "no_claim": sorted(agent_pr_ci.NO_CLAIM),
            "rows": [c for c in kept if c.get("class") not in (None, "error")]}


# ---- by agent and by week ---------------------------------------------------------------------------------------------
WEEKLY_DEFINITIONS = {
    "week": "the Monday (UTC) of the week the pull request was created in; a week at either end of `window` is cut "
            "short by it",
    "sampled": "pull requests GitHub's search returned for the agent's query and the claim phrases (`agents`, "
               "`claim_search`), created in that week, not on a repository owned by the pull request's author or by "
               "the person who assigned the agent. null where the source did not keep the creation date of the hits "
               "it then set aside",
    "claimed_passing": "of those, the ones whose description, read line by line, says tests or CI pass (CLAIM_RE and "
                       "NONCLAIM_RE in scripts/agent_pr_ci.py): an unticked box, a wish or a negation is not a claim",
    "ci_finished": "of the claimed, the ones whose CI had finished at the head commit when it was read (classes "
                   "failed, passed, other). The two rates below are over these",
    "failed_a_check": "at least one failed check of any kind at the head commit (`any_check_failed` of the index); "
                      "`test_or_build` counts the ones where a failed check is, by its name, a test, build, lint or "
                      "type-check job",
    "merged_despite_failed_check": "merged when read, with a failed check at the head commit, over the merged pull "
                                   "requests with finished CI. null where the merge state was not read",
    "share, ci95": "k over n, and the 95% Wilson score interval of that share (z = 1.96); null when n is 0",
    "checks": "the claimed pull requests by what their checks said when read: passed (at least one check, none failed, "
              "none pending, every one succeeded, was neutral or was skipped), failed, other (finished with a cancelled or "
              "stale check and no failure), pending, no_checks (the head commit has no check at all, or its checks wait "
              "for a maintainer's approval), not_read (the run's budget ended first). null: see `not_derived`",
    "verified_acceptance_rate": "the headline: of the claimed pull requests whose checks were read (every `checks` count "
                                "but not_read), the share where they all passed (`checks.passed`). A claim with no "
                                "check to back it, or with checks still running when read, is not verified. null: see "
                                "`not_derived`",
    "rank": "among the agents with at least `min_claims_to_rank` claimed pull requests whose checks were read that week: 1 "
            "is the largest verified acceptance rate; equal rates share a rank. null: too few to rank. A rank orders "
            "what was said against what was recorded that week. It is not a ranking of the agents' code. `ranked_by` "
            "names the count a row's rank was worked from: rows published before the rate was recorded were ranked by "
            "the smallest share that failed a check and keep that place",
    "design, capped, strata": "how the week was read (`designs` describes each name). capped: true when the run's "
                              "budget ended before the design was complete, or when the design itself is a cap. strata, "
                              "for a stratified week: for each day, how many pull requests the search reported, how many "
                              "of those a query can reach, how many the design planned to draw, how many were drawn, how "
                              "many of the drawn claimed passing tests, and how many of those had their checks read",
    "not_derived": "for each field of the row that is null, why it could not be worked out",
    "verified": "of the week's claimed pull requests, the ones that were also paid through Knos under terms with a "
                "black-box check, by the list of payments the script was given (`verified_against`). The only count "
                "here that rests on an acceptance check the pull request could not edit",
    "read, full_week": "the day GitHub was read for that week; full_week is true when every hit of the week's searches "
                       "was read, false for a week cut from a capped sample",
}
MIN_CLAIMS_TO_RANK = 30
NAME = "Agent PR Index"
NOT_JOINED = ("no list of Knos payments was joined to this sample, so the count is 0 for every agent: every Knos payment "
              "so far is test USDC on Solana devnet. It takes a sampled pull request that was also paid through Knos under "
              "terms with a black-box check, and that list given to the script (--paid)")
WEEKLY_LIMITS = [
    "An agent is told by its author account or by a line its tool writes in the description (`agents`). A person "
    "who pastes that line is counted as the agent; an agent run under a person's own account without it is missed.",
    "Public repositories only: GitHub's search does not return private ones.",
    "One snapshot of the checks: what GitHub showed at the head commit when it was read. A check that was run again "
    "later, or a commit pushed after, is not seen. The agent's own session run is not a check.",
    "The search asks for a few claim phrases, so `sampled` is not every pull request the agent opened.",
    "A week holds few pull requests for some agents: read the interval, not the share.",
    "A failed check is not proof that the claim was false. It says a check GitHub recorded at the head commit failed "
    "when it was read: the check may be a deploy preview or a label gate, may be flaky, or may have been failing "
    "before the pull request. What is concluded: the description said tests or CI pass, and the record shows a "
    "failed check. What is not: that the tests failed, that the code is wrong, or that one agent is better.",
]


HEADLINE = "verified_acceptance_rate"
DESIGN = "stratified-seeded-v1"
PER_STRATUM, MAX_REQUESTS, MAX_MINUTES = 30, 500, 50
SEARCH_PAUSE = 2.2      # seconds between two searches: 27 a minute at most, of the 30 GitHub allows
CHECK_RESERVE = (6, 45)  # requests and seconds the search leaves for the checks of what it drew last
REACH, PAGE = 1000, 100  # GitHub answers a search with at most 1,000 results, 100 a page
DAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
DESIGNS = {
    DESIGN: "35 strata: each agent on each day of the week (UTC, by the day the pull request was opened). In each "
            "stratum the search's results, newest first, are numbered from 0; the numbers a query can reach (the newest "
            f"{REACH:,} and, on a day with more, the oldest {REACH:,}) are put in the order of sha256(\"<ISO week>|<agent>|"
            "<date>|<number>\"), and the first `per_stratum` in that order are drawn: the same number in every stratum, "
            "fewer only where the stratum holds fewer. Strata are served in turns, one draw each, and the checks are read "
            "in the same turns, so when the budget ends every stratum holds a prefix of its own seeded order, which is a "
            "simple random sample of what could be reached. The budget is a number of requests and of minutes; a week "
            "cut by it is `capped`. The rates are shares of the sample: every day weighs the same, whatever it held "
            "(`strata` has what is needed to weigh them again)",
    "whole-week-v0": "every pull request the week's searches returned, each agent asked day by day with no cap",
    "newest-first-capped-v0": "each agent's newest claimed pull requests of a window of days, up to a cap, cut by week. "
                              "Not a designed sample: what is kept depends on how fast the agent filled its cap",
    "search-window-sample-v0": "the sample of 2026-10-01 (docs/agent_pr_ci.json): at most 20 search hits for each agent "
                               "in each of nine ten-day windows, cut by week",
}
NO_STRATA = "this design has no strata: see `designs`"
NOT_KEPT = ("the reading of 2026-10-05 published, for each agent and week, how many claimed pull requests had finished "
            "CI and how many of those failed a check. It did not publish how many passed every check, and its rows "
            "were not kept, so the share that passed cannot be worked out from what was published")


def with_new_fields(w):
    """A week row published before 0.3.16, with the fields a row has now: what can be derived from the row is; the
    rest is null and `not_derived` says why. The row's own numbers and its place are not touched."""
    if "design" in w:
        return w
    return {**w, "design": "newest-first-capped-v0", "capped": True, "strata": None, "checks": None, HEADLINE: None,
            "ranked_by": "failed_a_check", "not_derived": {"strata": NO_STRATA, "checks": NOT_KEPT, HEADLINE: NOT_KEPT}}


def restate_series(series, reshaped):
    """The published series in today's format: a week the committed sample holds and no later run read is the sample's
    row as it is counted today; any other row keeps its numbers and gains the new fields (with_new_fields)."""
    for name, agent in series["agents"].items():
        again = {w["week"]: w for w in reshaped["agents"].get(name, {"weeks": []})["weeks"]}
        agent["weeks"] = [again[w["week"]] if w["week"] in again and w["read"] == again[w["week"]]["read"] else with_new_fields(w) for w in agent["weeks"]]
        agent["all_weeks"] = _add(agent["weeks"])
    series.update({"definitions": reshaped["definitions"], "limits": reshaped["limits"], "designs": DESIGNS})
    series["latest_week"] = latest_week(series)
    return rank(series)


# ---- the weekly sample: bounded, stratified, seeded, resumable ---------------------------------------------------------
# Why the whole-week scan of 0.3.15 could not finish, from its own code: (1) it read every hit, with no cap (scan_week
# asked for 10**9 an agent); (2) each claimed pull request cost three to four REST requests (the combined status, the
# check runs, the check suites when there were neither, then the pull request for its merge state) against the 1,000
# an hour the Actions token has: 250 to 330 pull requests an hour; (3) when the hour's budget was spent, each of its eight workers slept until the hour came back, and
# a refused search slept up to 90 seconds, six times; (4) the job that read the week waited for the six-hourly index
# job, which spent the same hourly budget first; (5) a week that was not read whole was refused, so the hours it did
# spend published nothing. Here: a fixed number of draws, one GraphQL request for 20 pull requests, no other job
# in front, and whatever was read is published with its counts. The first bounded run (2026-10-05) stopped at the
# first refusal and drew 95 of 930; since then a refusal is waited out as GitHub asks, when the wait fits in the run's
# minutes, and the requests are spread over them (`patient`, `pace`; agent_pr_ci, "inside GitHub's limits").

def iso_week(monday):
    year, week, _ = dt.date.fromisoformat(monday).isocalendar()
    return f"{year}-W{week:02d}"


def week_days(monday):
    return [(dt.date.fromisoformat(monday) + dt.timedelta(days=i)).isoformat() for i in range(7)]


def reachable(n):
    """The result numbers (0 is the newest) one query can reach of `n`: the newest 1,000, and the oldest 1,000 asked
    in the other order. Up to 2,000 results that is all of them."""
    return list(range(min(n, REACH))) + list(range(max(REACH, n - REACH), n))


@functools.lru_cache(maxsize=None)
def _order(seed, agent, day, n):
    return tuple(sorted(reachable(n), key=lambda p: hashlib.sha256(f"{seed}|{agent}|{day}|{p}".encode()).hexdigest()))


def draw_order(seed, agent, day, n):
    """The reachable result numbers of a stratum in its seeded order. Any prefix is a simple random sample of them."""
    return list(_order(seed, agent, day, n))


def page_of(p, n):
    """(order, page, place on the page) of result number `p` of `n`."""
    q = p if p < REACH else n - 1 - p
    return ("desc" if p < REACH else "asc"), q // PAGE + 1, q % PAGE


def new_checkpoint(monday, per_stratum):
    return {"design": DESIGN, "week": monday, "seed": iso_week(monday), "per_stratum": per_stratum, "strata": {}, "checks": {},
            "graphql": None, "runs": []}


def load_checkpoint(path, monday, per_stratum):
    """What an earlier run of the same week and design left; a new one when there is none, or it is another week's."""
    try:
        got = _load(path)
    except (OSError, ValueError):
        return new_checkpoint(monday, per_stratum)
    same = isinstance(got, dict) and (got.get("design"), got.get("week"), got.get("per_stratum")) == (DESIGN, monday, per_stratum)
    return got if same else new_checkpoint(monday, per_stratum)


def save_checkpoint(path, state):
    """In one step: a run killed here leaves the last whole checkpoint, never half of one."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(f"{path}.tmp", "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False)
    os.replace(f"{path}.tmp", path)


def _slim(it):
    phrase, line = agent_pr_ci.find_claim(it.get("body"))
    return {"repo": it["repository_url"].split("/repos/")[1], "number": it["number"], "created_at": it["created_at"],
            "author": it["user"]["login"], "self": agent_pr_ci.excluded_self(it), "phrase": phrase, "claim_line": line}


def drawn(state, agent, day):
    """The draws of a stratum so far, in its seeded order: each a search hit, or None for a result number the page
    no longer held. As many as the turns the stratum was served (`turns`), never more than `per_stratum`: a draw that
    happens to sit on a page already read is not taken before its turn, so a cut run holds the same number of draws in
    every stratum, to within the one turn it was cut in."""
    st = state["strata"].get(f"{agent}|{day}") or {}
    out, n = [], st.get("reported")
    if n is None:
        return out
    for p in draw_order(state["seed"], agent, day, n)[:min(state["per_stratum"], st.get("turns", 0))]:
        order, page, at = page_of(p, n)
        items = st["pages"].get(f"{order}:{page}")
        if items is None:
            break
        out.append(items[at] if at < len(items) else None)
    return out


def _owner(state):
    """Which agent a drawn pull request counts for: one found under two agents' queries counts once, for the first
    agent listed. {key: agent}."""
    owner = {}
    for agent, _ in agent_pr_ci.AGENTS:
        for day in week_days(state["week"]):
            for it in drawn(state, agent, day):
                if it and not it["self"]:
                    owner.setdefault(_key(it), agent)
    return owner


def _search(state, path, broken, turn=None):
    """Read the search pages one turn of the design needs: the first page of every stratum (`turn` None: it says how
    many the stratum holds), or the page that holds each stratum's draw number `turn`. Raises OutOfTime when the
    budget ends; a page already in the checkpoint is not asked for again."""
    def fetch(agent, qual, day, order, page):
        r = agent_pr_ci.gh_get("search/issues", {"q": f"is:pr {qual} created:{day}..{day} {agent_pr_ci.CLAIM_SEARCH}", "per_page": PAGE,
                                                 "page": page, "sort": "created", "order": order}, kind="search")
        if not r["ok"]:
            print(f"search refused for {agent} on {day}: {r['error']}", file=sys.stderr)
            broken.add((agent, day))
            return
        st = state["strata"].setdefault(f"{agent}|{day}", {"reported": None, "pages": {}})
        if st["reported"] is None:
            st["reported"] = int(r["json"].get("total_count") or 0)
        st["pages"][f"{order}:{page}"] = [_slim(it) for it in r["json"]["items"]]
        save_checkpoint(path, state)

    for agent, qual, day in [(a, q, d) for d in week_days(state["week"]) for a, q in agent_pr_ci.AGENTS]:
        st = state["strata"].get(f"{agent}|{day}")
        if (agent, day) in broken:
            continue
        if turn is None:
            if not st or st["reported"] is None:
                fetch(agent, qual, day, "desc", 1)
            continue
        order_ = draw_order(state["seed"], agent, day, st["reported"]) if st else []
        if turn < len(order_):
            order, page, _ = page_of(order_[turn], st["reported"])
            if f"{order}:{page}" not in st["pages"]:
                fetch(agent, qual, day, order, page)
            if f"{order}:{page}" in st["pages"]:
                st["turns"] = max(st.get("turns", 0), turn + 1)
    save_checkpoint(path, state)


def _unread(state):
    """The drawn pull requests that claimed passing tests and whose checks are not read yet, in the turns they were
    drawn in."""
    owner, todo = _owner(state), []
    per_day = {(a, d): drawn(state, a, d) for a, _ in agent_pr_ci.AGENTS for d in week_days(state["week"])}
    for turn in range(state["per_stratum"]):
        for (agent, _day), draws in per_day.items():
            it = draws[turn] if turn < len(draws) else None
            if it and it["phrase"] and not it["self"] and owner[_key(it)] == agent and _key(it) not in state["checks"]:
                todo.append(it)
    return todo


def _checks(state, path):
    """Read the checks and the merge state of what _unread lists. True when every one GitHub would answer for is read."""
    todo, missed = _unread(state), 0

    def keep(it, got):
        nonlocal missed
        if got and not (got.get("class") == "error" and got.get("transient")):
            state["checks"][_key(it)] = {k: got.get(k) for k in ("class", "sha", "failed_checks", "merged")}
            if got.get("class") not in COMPLETED:
                state["checks"][_key(it)]["merged"] = None      # the merge state is only counted beside finished CI
        else:
            missed += 1

    def rest(it):
        got = agent_pr_ci.classify(it)
        if got.get("class") in COMPLETED:
            pr = agent_pr_ci.gh_get(f"repos/{it['repo']}/pulls/{it['number']}")
            got["merged"] = bool(pr["json"].get("merged")) if pr["ok"] else None
        keep(it, got)
        save_checkpoint(path, state)

    try:
        while todo:
            batch, todo = todo[:agent_pr_ci.ROLLUP_BATCH], todo[agent_pr_ci.ROLLUP_BATCH:]
            got = agent_pr_ci.read_rollup(batch) if state["graphql"] is not False else None
            if isinstance(got, dict) and got.get("transient"):
                got = agent_pr_ci.read_rollup(batch)          # once more; a second failure leaves the batch for the next run
            if isinstance(got, dict):
                if got.get("transient") and state["graphql"]:      # it has answered before: leave these for the next run
                    print(f"GraphQL did not answer for {len(batch)} pull requests: {got['error']}", file=sys.stderr)
                    missed += len(batch)
                    continue
                print(f"GraphQL refused ({got['error']}): reading the checks over REST from here", file=sys.stderr)
                state["graphql"], got = False, None
            elif got is not None:
                state["graphql"] = True
            for i, it in enumerate(batch):
                if got is not None and got[i] is not None:
                    keep(it, got[i])
                else:
                    rest(it)                                  # the REST path: no GraphQL, or one pull request it did not settle
            save_checkpoint(path, state)
    except agent_pr_ci.OutOfTime:
        save_checkpoint(path, state)
        return False
    return not missed


def cursor(state, come_back=None):
    """Where the week's reading stands, in the checkpoint itself (`cursor`): how far the search and the checks got,
    and, when GitHub refused a request for a limit, the time it said to come back at. The next run starts there."""
    turns = [st.get("turns", 0) for st in state["strata"].values()]
    return {"strata_counted": sum(st.get("reported") is not None for st in state["strata"].values()), "of_strata": 7 * len(agent_pr_ci.AGENTS),
            "draw_turn": max(turns, default=0), "of_turns": state["per_stratum"],
            "search_pages": sum(len(st["pages"]) for st in state["strata"].values()), "checks_read": len(state["checks"]),
            "come_back": None if come_back is None else dt.datetime.fromtimestamp(come_back, dt.timezone.utc).isoformat(timespec="seconds")}


def sample_week(monday, path, per_stratum=PER_STRATUM, max_requests=MAX_REQUESTS, max_minutes=MAX_MINUTES, read=None, patient=False, pace=0.0):
    """One bounded run of the week's sample, from the checkpoint at `path` when it holds this week. It stops when the
    design is complete or the budget ends, and the checkpoint then holds everything read so far. `patient`: a
    refusal for a rate limit is waited out for as long as GitHub says, when that fits in the run's minutes, and a
    run that an earlier one left with a time to come back at waits for it first; `pace`: the least seconds between
    two requests, so the run's requests are spread over its minutes (agent_pr_ci, "inside GitHub's limits")."""
    if dt.date.fromisoformat(monday).weekday():
        raise SystemExit(f"--week {monday} is not a Monday. Name the Monday the week starts on, or `last`.")
    state, before = load_checkpoint(path, monday, per_stratum), agent_pr_ci.ASKED[0]
    agent_pr_ci.START = time.time()
    agent_pr_ci.SEARCH_PAUSE = min(agent_pr_ci.SEARCH_PAUSE, SEARCH_PAUSE)
    agent_pr_ci.NO_WAIT, agent_pr_ci.STOPPED[0], broken, done = True, None, set(), False
    agent_pr_ci.PATIENT, agent_pr_ci.PACE, agent_pr_ci.COME_BACK[0] = patient, pace, None
    due = (state.get("cursor") or {}).get("come_back")
    wait, held = (dt.datetime.fromisoformat(due).timestamp() - time.time() if patient and due else 0), False

    def budget(reserve):
        agent_pr_ci.MAX_REQUESTS = before + max_requests - (CHECK_RESERVE[0] if reserve else 0)
        agent_pr_ci.ARGS = SimpleNamespace(max_seconds=max_minutes * 60 - (CHECK_RESERVE[1] if reserve else 0))
    try:
        budget(True)
        try:
            if wait > 0:                        # the last run was told when to come back: not before
                held = agent_pr_ci.time_left() < wait + 15
                if held:
                    agent_pr_ci.COME_BACK[0] = time.time() + wait
                    agent_pr_ci._stop(f"GitHub said to come back at {due}", agent_pr_ci.OutOfBudget)
                time.sleep(wait)
            for turn in [None, *range(per_stratum)]:
                _search(state, path, broken, turn)
                if len(_unread(state)) >= 2 * agent_pr_ci.ROLLUP_BATCH:     # the checks are read as the draw goes
                    _checks(state, path)
            searched = not broken
        except agent_pr_ci.OutOfTime:
            searched = False
        budget(False)                           # what the search left: the checks of the last draws
        done = not held and _checks(state, path) and searched
    finally:
        agent_pr_ci.NO_WAIT, agent_pr_ci.MAX_REQUESTS, agent_pr_ci.PATIENT, agent_pr_ci.PACE = False, None, False, 0.0
        state["cursor"] = cursor(state, None if done else agent_pr_ci.COME_BACK[0])
        state["runs"].append({"read": read or dt.datetime.now(dt.timezone.utc).date().isoformat(), "requests": agent_pr_ci.ASKED[0] - before,
                              "max_requests": max_requests, "max_minutes": max_minutes, "complete": done,
                              "stopped": None if done else agent_pr_ci.STOPPED[0] or ("a search was refused" if broken else "checks were left unread")})
        save_checkpoint(path, state)
    return state


def week_from_sample(state, paid=None):
    """The checkpoint as one week of the series: every agent has a row, whatever was read. Reads nothing."""
    week, per, owner = state["week"], state["per_stratum"], _owner(state)
    rows, aside, strata = [], [], {}
    for agent, _ in agent_pr_ci.AGENTS:
        strata[agent] = {}
        for name, day in zip(DAY_NAMES, week_days(week)):
            n = (state["strata"].get(f"{agent}|{day}") or {}).get("reported")
            draws = drawn(state, agent, day)
            info = strata[agent][name] = {"date": day, "reported": n, "reachable": None if n is None else len(reachable(n)),
                                          "planned": None if n is None else min(per, len(reachable(n))), "drawn": len(draws), "claimed": 0, "checks_read": 0}
            for it in draws:
                if not it or it["self"] or owner[_key(it)] != agent:
                    continue                    # gone from the page, on its author's own repository, or another agent's
                got = state["checks"].get(_key(it))
                if not it["phrase"] or (got and got["class"] == "error"):
                    aside.append([agent, it["created_at"]])       # claims nothing, or deleted since: sampled, not claimed
                    continue
                info["claimed"] += 1
                info["checks_read"] += bool(got)
                rows.append({"agent": agent, **{k: it[k] for k in ("repo", "number", "created_at", "phrase")},
                             **({k: v for k, v in got.items() if v is not None} if got else {"class": "unread"})})
    runs = state["runs"]
    read = runs[-1]["read"] if runs else dt.datetime.now(dt.timezone.utc).date().isoformat()
    one = weekly(rows, [week, week_days(week)[-1]], read, "the weekly sample", aside, None, paid, only=week, design=DESIGN)
    for agent, mine in one["agents"].items():
        w, days = mine["weeks"][0], strata[agent].values()
        short = [d for d in days if d["planned"] is None or d["drawn"] < d["planned"]]
        w.update({"strata": strata[agent], "seed": state["seed"], "per_stratum": per, "not_derived": {},
                  "capped": bool(short) or any(d["checks_read"] < d["claimed"] for d in days),
                  "full_week": not short and all(d["drawn"] == d["reported"] for d in days)})
        mine["all_weeks"] = _add(mine["weeks"])
    one["week"] = week
    return rank(one)


# What the checks of a claimed pull request said when they were read, by the name each count is published under.
CHECKS = {"passed": ("passed",), "failed": ("failed",), "other": ("other",), "pending": ("pending",),
          "no_checks": ("no-ci", "blocked-awaiting-approval"), "not_read": ("unread",)}


def week_of(created_at):
    """The Monday (UTC) of the week of a GitHub timestamp, as a date."""
    day = dt.datetime.fromisoformat(str(created_at).replace("Z", "+00:00")).astimezone(dt.timezone.utc).date()
    return (day - dt.timedelta(days=day.weekday())).isoformat()


def _rate(k, n):
    return {"k": k, "n": n, "share": round(k / n, 4) if n else None, "ci95": wilson(k, n)}


def _key(r):
    return f"{r['repo']}#{r['number']}".lower()


def week_counts(mine, set_aside, paid=frozenset()):
    """One row of the series over the claimed pull requests `mine`; `set_aside`: how many more hits claimed nothing,
    or None when that is not known; `paid`: "owner/repo#number" of the ones paid through Knos on a black-box check."""
    done = [r for r in mine if r.get("class") in COMPLETED]
    failed = [r for r in done if r["class"] == "failed"]
    known = all(isinstance(r.get("merged"), bool) for r in done)      # one pull request not read: null, never a guess
    merged = [r for r in done if r.get("merged") is True]
    kinds = {name: sum(1 for r in mine if r.get("class") in classes) for name, classes in CHECKS.items()}
    read = len(mine) - kinds["not_read"]
    return {"sampled": None if set_aside is None else len(mine) + set_aside, "claimed_passing": len(mine), "ci_finished": len(done),
            "checks": kinds, "verified_acceptance_rate": _rate(kinds["passed"], read),
            "failed_a_check": {**_rate(len(failed), len(done)),
                               "test_or_build": sum(1 for r in failed if agent_pr_ci.is_testish_failure(r))},
            "merged_despite_failed_check": _rate(sum(1 for r in merged if r["class"] == "failed"), len(merged)) if known and done else None,
            "verified": sum(1 for r in mine if _key(r) in paid)}


def rank(series):
    """Write `rank` into every week row that has the headline rate: the place of each agent among those with at least
    `min_claims_to_rank` claimed pull requests whose checks were read that week, by the verified acceptance rate
    (largest first; equal rates share a place). Too few: None, and never placed. A row published before the rate was
    recorded (`ranked_by` failed_a_check, rate null) keeps the place it was published with and is not placed again."""
    least = series["min_claims_to_rank"]
    for week in {w["week"] for a in series["agents"].values() for w in a["weeks"]}:
        rows = [w for a in series["agents"].values() for w in a["weeks"] if w["week"] == week and w.get("verified_acceptance_rate")]
        share = lambda w: Fraction(w["verified_acceptance_rate"]["k"], w["verified_acceptance_rate"]["n"])  # noqa: E731
        shares = sorted((share(w) for w in rows if w["verified_acceptance_rate"]["n"] >= least), reverse=True)
        for w in rows:
            w["rank"] = shares.index(share(w)) + 1 if w["verified_acceptance_rate"]["n"] >= least else None
            w["ranked_by"] = "verified_acceptance_rate"
    return series


def _add(rows):
    """Week rows added up: counts are sums, intervals are worked again, and a fact one week lacks is null in the sum."""
    def rate(name):
        if any(w.get(name) is None for w in rows):
            return None
        return _rate(sum(w[name]["k"] for w in rows), sum(w[name]["n"] for w in rows))
    judged = [w for w in rows if w["ci_finished"]]        # a week with no finished CI has no merge state to lack
    known = judged and all(w["merged_despite_failed_check"] is not None for w in judged)
    kinds = None if any(w.get("checks") is None for w in rows) else {k: sum(w["checks"][k] for w in rows) for k in CHECKS}
    return {"sampled": None if any(w["sampled"] is None for w in rows) else sum(w["sampled"] for w in rows),
            "claimed_passing": sum(w["claimed_passing"] for w in rows), "ci_finished": sum(w["ci_finished"] for w in rows),
            "checks": kinds, "verified_acceptance_rate": None if any(w.get(HEADLINE) is None for w in rows) else rate(HEADLINE),
            "failed_a_check": {**rate("failed_a_check"), "test_or_build": sum(w["failed_a_check"]["test_or_build"] for w in rows)},
            "merged_despite_failed_check": _rate(sum(w["merged_despite_failed_check"]["k"] for w in judged),
                                                 sum(w["merged_despite_failed_check"]["n"] for w in judged)) if known else None,
            "verified": sum(w["verified"] for w in rows)}


def add_week(series, one):
    """The series with the week `one` holds (a `weekly` of one whole week) put in: each agent's row for that Monday is
    replaced or added, `all_weeks` is the sum of its weeks, and the ranks are worked again. The earlier weeks are
    not touched."""
    week = one["week"]
    for name, new in one["agents"].items():
        mine = series["agents"].setdefault(name, {"weeks": [], "all_weeks": None})
        mine["weeks"] = sorted([w for w in mine["weeks"] if w["week"] != week] + [w for w in new["weeks"] if w["week"] == week],
                               key=lambda w: w["week"])
        mine["all_weeks"] = _add(mine["weeks"])
    days = [series["window"][0], series["window"][1], one["window"][0], one["window"][1]]
    series.update({"name": NAME, "read": max(series["read"], one["read"]), "window": [min(days), max(days)],
                   "agents_told_by": one["agents_told_by"], "heuristics": one["heuristics"], "claim_search": one["claim_search"],
                   "definitions": one["definitions"], "limits": one["limits"], "min_claims_to_rank": one["min_claims_to_rank"],
                   "verified_against": one["verified_against"], "designs": DESIGNS,
                   "source": f"each week says how it was read (`design`, `capped`, `strata`). The newest: week of {week}, read {one['read']}, "
                             f"{next((w['design'] for a in one['agents'].values() for w in a['weeks']), 'no design')}"})
    # the series may still hold weeks a capped scan cut from its window: the source keeps saying so (`full_week` false)
    part = sorted({w["week"] for a in series["agents"].values() for w in a["weeks"] if w.get("full_week") is False and w.get("read") == series["read"]})
    if part:
        series["source"] += f"; read on {series['read']} and not whole weeks: the weeks of {', '.join(part)} (`full_week` false)"
    series["latest_week"] = latest_week(series)
    return rank(series)


def add_sample(series, fresh):
    """The series with the weeks of `fresh` (a `weekly` of a capped scan: every week `full_week` false) put in. A week
    read whole stays as it is; an older sample's row for the same Monday is replaced by the newer reading; the weeks
    `fresh` does not have are not touched. `all_weeks` and the ranks are worked again."""
    for name, new in fresh["agents"].items():
        mine = series["agents"].setdefault(name, {"weeks": [], "all_weeks": None})
        whole = {w["week"] for w in mine["weeks"] if w.get("full_week")}
        took = {w["week"]: w for w in new["weeks"] if w["week"] not in whole}
        mine["weeks"] = sorted([w for w in mine["weeks"] if w["week"] not in took] + list(took.values()), key=lambda w: w["week"])
        mine["all_weeks"] = _add(mine["weeks"])
    days = [series["window"][0], series["window"][1], fresh["window"][0], fresh["window"][1]]
    series.update({"name": NAME, "read": max(series["read"], fresh["read"]), "window": [min(days), max(days)],
                   "agents_told_by": fresh["agents_told_by"], "heuristics": fresh["heuristics"], "claim_search": fresh["claim_search"],
                   "definitions": fresh["definitions"], "limits": fresh["limits"], "min_claims_to_rank": fresh["min_claims_to_rank"],
                   "verified_against": fresh["verified_against"], "designs": DESIGNS,
                   "source": f"the weeks read on {fresh['read']} are cut from a capped sample of {fresh['window'][0]} to "
                             f"{fresh['window'][1]} (each agent's newest claimed pull requests, up to a cap, by "
                             "agent_pr_index.py scan), not whole weeks; the others are the sample read on 2026-10-01, cut by week"})
    series["latest_week"] = latest_week(series)
    return rank(series)


def latest_week(series):
    """The newest week any agent has a row for."""
    weeks = [w["week"] for a in series["agents"].values() for w in a["weeks"]]
    return max(weeks) if weeks else None


def weekly(rows, window, read, source, no_claim=None, agents=None, paid=None, only=None, design=None):
    """The scan's claimed pull requests by agent and by week of creation. `rows`: classified candidates with
    `created_at` (and `merged` where it was read); `no_claim`: [agent, created_at] of the hits that claimed nothing,
    or None when the source did not keep them; `paid`: "owner/repo#number" of the pull requests paid through Knos on
    a black-box check, or None when no such list was joined; `only`: one Monday, when the rows are one whole week (every
    agent then has a row for it, and nothing outside it is counted). Deterministic for the same rows."""
    agents = agents or [list(a) for a in agent_pr_ci.AGENTS]
    design = design or ("whole-week-v0" if only else "newest-first-capped-v0")
    how = lambda: {"design": design, "capped": design != "whole-week-v0", "strata": None, "not_derived": {"strata": NO_STRATA}}  # noqa: E731
    paid_keys = frozenset(str(k).lower() for k in paid or ())
    if only:
        rows = [r for r in rows if week_of(r["created_at"]) == only]
        no_claim = None if no_claim is None else [x for x in no_claim if week_of(x[1]) == only]
    out = {"name": NAME, "read": read, "window": list(window), "source": source, "agents_told_by": {n: q for n, q in agents},
           "heuristics": {n: agent_pr_ci.HEURISTICS[n] for n, _ in agents if n in agent_pr_ci.HEURISTICS},
           "claim_search": agent_pr_ci.CLAIM_SEARCH, "definitions": WEEKLY_DEFINITIONS, "limits": WEEKLY_LIMITS,
           "min_claims_to_rank": MIN_CLAIMS_TO_RANK, "designs": DESIGNS,
           "verified_against": NOT_JOINED if paid is None else f"a list of {len(paid_keys)} pull requests paid through Knos under terms with a black-box check",
           "agents": {}}
    for name, _ in agents:
        mine = [r for r in rows if r["agent"] == name and r.get("class") not in (None, "error")]
        aside = None if no_claim is None else [week_of(at) for a, at in no_claim if a == name]
        weeks = sorted({week_of(r["created_at"]) for r in mine} | set(aside or []) | ({only} if only else set()))
        out["agents"][name] = {
            "weeks": [{"week": w, "read": read, "full_week": bool(only), **how(),
                       **week_counts([r for r in mine if week_of(r["created_at"]) == w],
                                     None if aside is None else aside.count(w), paid_keys)} for w in weeks],
            "all_weeks": week_counts(mine, None if aside is None else len(aside), paid_keys)}
    out["latest_week"] = latest_week(out)
    return rank(out)


def read_merged(rows):
    """Ask GitHub whether each pull request with finished CI was merged (one request each, kept in the cache). A row
    GitHub does not answer for keeps no `merged`, and its week then says null, not a guess."""
    for r in rows:
        if r.get("class") in COMPLETED and not isinstance(r.get("merged"), bool):
            try:
                got = agent_pr_ci.gh_get(f"repos/{r['repo']}/pulls/{r['number']}")
            except agent_pr_ci.OutOfTime:
                break       # the rest stay unread: their weeks say null, and the next run has these answers in its cache
            if got["ok"]:
                r["merged"] = bool(got["json"].get("merged"))
    return rows


BEGIN, END = "<!-- weekly:begin (written by scripts/agent_pr_index.py weekly; do not edit by hand) -->", "<!-- weekly:end -->"


def _cell(rate):
    if rate is None:
        return "not read"
    if not rate["n"]:
        return "0 of 0"
    lo, hi = rate["ci95"]
    return f"{rate['k']} of {rate['n']} ({rate['share']:.1%}; {lo:.1%} to {hi:.1%})"


TOO_FEW = "too few to rank"


def _sample(w):
    """How a row was read, in a few words: the mark `capped` is never left out."""
    days = (w.get("strata") or {}).values()
    if not days:
        return ("capped" if w.get("capped") else "not capped") + f": {w.get('design', 'design not recorded')}"
    drawn_, planned = sum(d["drawn"] for d in days), sum(d["planned"] or 0 for d in days)
    known = [d["reported"] for d in days if d["reported"] is not None]
    return (f"{'capped' if w.get('capped') else 'not capped'}: drew {drawn_:,} of {planned:,} planned, "
            f"of {sum(known):,} the search reported" + ("" if len(known) == len(days) else f" on {len(known)} of 7 days"))


def _place(w):
    if w.get("rank") is not None and w.get("ranked_by", HEADLINE) == HEADLINE:
        return w["rank"]
    return TOO_FEW if w.get(HEADLINE) else "not ranked: rate not recorded"


def _row(name, place, w):
    rate = "not recorded" if w.get(HEADLINE) is None else _cell(w[HEADLINE])
    return (f"| {place} | {name} | {rate} | {'not kept' if w['sampled'] is None else w['sampled']} | {w['claimed_passing']} | "
            f"{_cell(w['failed_a_check'])} | {_cell(w['merged_despite_failed_check'])} | {w.get('verified', 0)} | {_sample(w) if 'week' in w else 'weeks added up'} |")


def weekly_table(series):
    """The newest week as a leaderboard, then every week of the file added up (never ranked), as the Markdown
    docs/reference/INDEX.md shows between its markers."""
    week, least = series.get("latest_week") or latest_week(series), series.get("min_claims_to_rank", MIN_CLAIMS_TO_RANK)
    head = ["| Place | Agent | Verified acceptance rate (95% interval) | Sampled | Claimed passing | Failed a check anyway (95% interval) | "
            "Merged despite a failed check (95% interval) | Also paid through Knos on a black-box check | Sample |",
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    rows = [(name, next((w for w in a["weeks"] if w["week"] == week), None)) for name, a in series["agents"].items()]
    rows = [(name, w) for name, w in rows if w]
    placed = lambda w: isinstance(_place(w), int)  # noqa: E731
    rows.sort(key=lambda x: (not placed(x[1]), x[1].get("rank") or 0 if placed(x[1]) else 0))      # placed first; the rest in the file's order
    reads = sorted({w.get("read", series["read"]) for _, w in rows})
    designs = sorted({w.get("design", "design not recorded") for _, w in rows})
    capped = any(w.get("capped", True) for _, w in rows)
    lines = [f"**{series.get('name', NAME)}, week of {week}.** Read {' and '.join(reads)}. Design: {', '.join(designs)}. "
             + ("Capped: true for at least one agent (see Sample)." if capped else "Capped: false.")
             + " Verified acceptance rate: of the pull requests that claimed passing tests and whose checks were read, the share whose checks all passed."
             + f" An agent with fewer than {least} such pull requests that week is \"{TOO_FEW}\" and has no place.",
             "", *head]
    lines += [_row(name, _place(w), w) for name, w in rows]
    lines += ["", f"Also paid through Knos, checked against: {series.get('verified_against', NOT_JOINED)}.", "",
              f"Every week in the file added up ({series['window'][0]} to {series['window'][1]}; never ranked: the weeks were not all read the same way). "
              f"Source: {series['source']}.", "", *head]
    lines += [_row(name, "not ranked", a["all_weeks"]) for name, a in series["agents"].items()]
    return "\n".join(lines)


def render_doc(path, series):
    """Replace what is between the markers of `path` with the table; a file without both markers is left alone, loudly."""
    with open(path, encoding="utf-8") as f:
        text = f.read()
    if BEGIN not in text or END not in text:
        raise SystemExit(f"{path}: the markers are not there:\n{BEGIN}\n{END}")
    head, rest = text.split(BEGIN, 1)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(f"{head}{BEGIN}\n{weekly_table(series)}\n{END}{rest.split(END, 1)[1]}")


def _load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def week_gaps(got):
    """Why a week's scan may not be added to the series yet; empty when it may. The same bar as the index's gate."""
    why, kept, unread = [], got.get("kept", len(got["rows"])), got.get("unread", 0)
    if got.get("unfinished_search"):
        why.append(f"the search did not finish for {', '.join(got['unfinished_search'])}. What it read is kept: run the workflow again")
    if unread > MAX_UNREAD * kept:
        why.append(f"GitHub did not answer for {unread:,} of the {kept:,} pull requests the search kept (out of time or over "
                   "the hourly limit). What it read is kept: the next run continues from here")
    if got.get("no_claim") is None:
        why.append("the scan did not keep when the hits it set aside were opened, so `sampled` would be unknown: scan again with this version")
    missing = sum(1 for r in got["rows"] if r.get("class") in COMPLETED and not isinstance(r.get("merged"), bool))
    if missing > MAX_UNREAD * max(1, kept):
        why.append(f"the merge state of {missing:,} pull requests was not read (out of time). Run the workflow again")
    return why


def weekly_main(a):
    paid = _load(a.paid) if a.paid else None
    if a.sample:
        sample = _load(a.sample)
        days = sorted(r["created_at"][:10] for r in sample["prs"])
        series = weekly(sample["prs"], (days[0], days[-1]), sample["generated_utc"][:10],
                        f"{a.sample}, the sample read on {sample['generated_utc'][:10]}, reshaped by week (nothing was read "
                        "again). Unlike the index, this sample kept pull requests on repositories their author owns",
                        None, sample.get("agents"), paid, design="search-window-sample-v0")
        for name, agent in series["agents"].items():      # the hits it set aside are listed without a date: a total, no week
            agent["all_weeks"]["sampled"] = agent["all_weeks"]["claimed_passing"] + sum(
                1 for r in sample.get("rejected_no_claim", []) if r["agent"] == name)
        if a.restate:                                     # the published series, in today's format; reads nothing
            series, a.out = restate_series(_load(a.restate), series), a.restate
    else:
        got = _load(a.rows)
        agent_pr_ci.ARGS = SimpleNamespace(max_seconds=a.max_seconds)
        if a.reserve is not None:                          # the merge states it asks for stay inside this hour's budget
            agent_pr_ci.budget(a.reserve)
        if a.add_sample:                                  # a capped scan, cut by week, into the published series
            if got.get("week"):
                raise SystemExit(f"{a.rows} is one whole week's scan: add it with --into")
            read_merged(got["rows"])                      # the merge state of each one with finished CI (asked, then cached)
            why = week_gaps(got)
            for line in why:
                print(f"not added: {line}", file=sys.stderr)
            if why:
                return 1
            fresh = weekly(got["rows"], got["window"], dt.date.today().isoformat(), "a capped scan", got["no_claim"], None, paid)
            series, a.out = add_sample(_load(a.add_sample), fresh), a.add_sample
        elif a.into and got.get("design") == DESIGN:     # the week's sample, whatever the budget let it read: never refused
            series, a.out = add_week(_load(a.into), week_from_sample(got, paid)), a.into
        elif a.into:                                     # one whole week, added to the published series; reads nothing
            if not got.get("week"):
                raise SystemExit(f"{a.rows} is not one week's scan. Make it with: agent_pr_index.py scan --week last --rows {a.rows}")
            why = week_gaps(got)
            for line in why:
                print(f"not added: {line}", file=sys.stderr)
            if why:
                return 1
            one = weekly(got["rows"], got["window"], got["read"], "the weekly run", got["no_claim"], None, paid, only=got["week"])
            one["week"] = got["week"]
            series, a.out = add_week(_load(a.into), one), a.into
        else:
            series = weekly(read_merged(got["rows"]), got["window"], dt.date.today().isoformat(),
                            "the scan behind the Agent PR Index of the same day", got.get("no_claim"), None, paid)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(series, f, ensure_ascii=False, indent=1)
        f.write("\n")
    if a.doc:
        render_doc(a.doc, series)
    print(f"{NAME}, week of {series['latest_week']}: {sum(len(x['weeks']) for x in series['agents'].values())} agent-weeks, {a.out}", file=sys.stderr)
    return 0


MAX_UNREAD = 0.02       # of the pull requests a scan kept, the share GitHub may leave unanswered in a scan that goes out
MIN_OF_PREVIOUS = 0.5   # a scan with under half the last index's pull requests means the search broke, not the world
STALE_AFTER = dt.timedelta(days=2)   # runs that stop early for this long (8 runs) are not catching up: that is an error


def finished(scanned):
    """Every agent's search finished and GitHub answered for (nearly) every pull request the search kept."""
    kept, unread = scanned.get("kept", len(scanned["rows"])), scanned.get("unread", 0)
    return not scanned.get("unfinished_search") and unread <= MAX_UNREAD * kept


def gate(scanned, index, previous=None):
    """Why this scan must not be published; an empty list means publish it. A scan goes out when every agent's search
    finished, GitHub answered for (nearly) every pull request it kept, and it did not shrink to under half of the
    last published index. Each reason says what to do. `errors` says which of them make the run fail."""
    why = []
    kept, unread = scanned.get("kept", len(scanned["rows"])), scanned.get("unread", 0)
    stopped = f" It stopped because {scanned['stopped']}." if scanned.get("stopped") else ""
    if scanned.get("unfinished_search"):
        why.append(f"the search did not finish for {', '.join(scanned['unfinished_search'])} (out of time or out of this "
                   f"hour's budget, or GitHub refused a query: see the scan step's log).{stopped} What it read is cached: "
                   "the next run continues from there")
    if unread > MAX_UNREAD * kept:
        why.append(f"GitHub did not answer for {unread:,} of the {kept:,} pull requests the search kept (out of time "
                   f"or out of this hour's budget).{stopped} What it read is cached: the next run continues from here. A "
                   "KNOS_INDEX_TOKEN secret (a read-only token) has five times the hourly limit")
    if not finished(scanned):
        return why
    if not index["n_prs"]:
        why.append("no pull request with finished CI was found: the search or the token is broken")
    elif previous and index["n_prs"] < MIN_OF_PREVIOUS * previous.get("n_prs", 0):
        why.append(f"{index['n_prs']:,} pull requests, under half of the last index's {previous['n_prs']:,}: check "
                   "the search queries in scripts/agent_pr_ci.py before publishing this")
    return why


def errors(scanned, index, previous=None, now=None):
    """What makes the run fail where it can be seen: a search GitHub refused for itself (a bad query or token, which no
    later run fixes), a finished scan that found nothing or shrank to under half of the last index, or runs that have
    stopped early for STALE_AFTER and so are not catching up. A scan that only stopped early (out of minutes, or out
    of this hour's budget) is not an error: nothing is published and the next run continues from the cache."""
    bad = [f"GitHub refused the search query itself for {e}: fix the query or the token" for e in scanned.get("search_errors") or []]
    if finished(scanned):
        return bad + gate(scanned, index, previous)
    since = scanned.get("unfinished_since")
    if since and (now or dt.datetime.now(dt.timezone.utc)) - dt.datetime.fromisoformat(since) >= STALE_AFTER:
        bad.append(f"every run since {since} stopped before it finished: the scan is not catching up within the hourly "
                   "budget. Lower --per-agent in .github/workflows/index.yml, or add the KNOS_INDEX_TOKEN secret")
    return bad


def track(scanned, path, now=None):
    """When the scans began to stop early, kept in `path` (in the cache, so the next run knows): the first unfinished
    run since the last finished one; None once a run finishes. Written into `scanned` as `unfinished_since`."""
    now = (now or dt.datetime.now(dt.timezone.utc)).isoformat(timespec="seconds")
    try:
        since = _load(path).get("unfinished_since")
    except (OSError, ValueError, AttributeError):
        since = None
    scanned["unfinished_since"] = None if finished(scanned) else (since or now)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"unfinished_since": scanned["unfinished_since"]}, f)
    return scanned


def _github_says(publish, note=None):
    """Tell the workflow whether to publish (the step output `publish`), and put a note on the run's page."""
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as f:
            f.write(f"publish={'true' if publish else 'false'}\n")
    if note:
        print(f"::notice title=Agent PR Index not published yet::{note}")
        if os.environ.get("GITHUB_STEP_SUMMARY"):
            with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
                f.write(f"**Agent PR Index not published yet.** {note}\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=["scan", "sample", "build", "gate", "check", "restate", "weekly", "board", "vendors"])
    ap.add_argument("--max-requests", type=int, default=MAX_REQUESTS, help="sample: the most requests one run sends to GitHub")
    ap.add_argument("--max-minutes", type=float, default=MAX_MINUTES, help="sample: the longest one run reads for")
    ap.add_argument("--no-wait", action="store_true", help="sample: stop at the first refusal for a rate limit; by default the run waits as long as GitHub says, inside its minutes")
    ap.add_argument("--pace", type=float, help="sample: the least seconds between two requests; by default the requests are spread over four fifths of the run's minutes")
    ap.add_argument("--series", default="docs/agent_weekly.json", help="board: the published series")
    ap.add_argument("--disputes", default="docs/index_disputes.json", help="board: the disputes file")
    ap.add_argument("--replies", default="docs/index_replies.json", help="vendors: the vendors' replies, printed word for word")
    ap.add_argument("--feed", default="docs/index.json", help="board: the machine-readable feed to write")
    ap.add_argument("--atom", default="docs/index.atom", help="board: the Atom feed to write")
    ap.add_argument("--check", action="store_true", help="board: write nothing; exit 1 when the document or a feed differs from what would be written")
    ap.add_argument("--per-stratum", type=int, default=PER_STRATUM, help="sample: pull requests drawn for each agent on each day")
    ap.add_argument("--restate", help="weekly --sample: write this published series (docs/agent_weekly.json) again in today's format; reads nothing")
    ap.add_argument("--sample", help="weekly: reshape this committed sample (docs/agent_pr_ci.json) and read nothing")
    ap.add_argument("--doc", help="weekly: also write the table between the markers of this file (docs/reference/INDEX.md)")
    ap.add_argument("--week", help="scan: one whole week, every hit: the Monday it starts on (YYYY-MM-DD), or `last` for the newest week that has ended")
    ap.add_argument("--into", help="weekly: add the one week in --rows to this published series (docs/agent_weekly.json); reads nothing")
    ap.add_argument("--add-sample", help="weekly: add the weeks of the capped scan in --rows to this published series (docs/agent_weekly.json), "
                                         "each marked as not read whole; reads the merge states it lacks")
    ap.add_argument("--paid", help='weekly: a JSON list of "owner/repo#number", the pull requests paid through Knos under terms with a black-box check')
    ap.add_argument("--rows", default="rows.json")
    ap.add_argument("--out", default="_site/index.json")
    ap.add_argument("--previous", help="gate, scan: the index published last, when there is one (the scan takes the verdicts it lacks from it)")
    ap.add_argument("--reserve", type=int, help="scan, weekly: stop when this hour's REST or GraphQL budget is down to this many "
                                               "(kept for the rest of the job and the repository's other workflows)")
    ap.add_argument("--end", default=(dt.date.today() - dt.timedelta(days=1)).isoformat())
    ap.add_argument("--days", type=int, default=120)
    ap.add_argument("--per-agent", type=int, default=480)
    ap.add_argument("--max-seconds", type=int, default=3 * 3600)
    a = ap.parse_args()
    if a.step == "weekly":
        return weekly_main(a)
    if a.step == "board":
        import agent_pr_board
        return agent_pr_board.main(a.series, a.disputes, a.doc or "docs/reference/INDEX.md", a.feed, a.atom, a.check)
    if a.step == "vendors":
        import vendor_pages
        return vendor_pages.main(a.series, a.disputes, a.replies, a.doc or "docs/reference/VENDORS.md", "docs/vendors.json", a.check)
    if a.step == "sample":
        monday = last_week() if (a.week or "last") == "last" else a.week
        pace = a.pace if a.pace is not None else 0.8 * a.max_minutes * 60 / max(1, a.max_requests)
        state = sample_week(monday, a.rows, a.per_stratum, a.max_requests, a.max_minutes, patient=not a.no_wait, pace=pace)
        one, run = week_from_sample(state), state["runs"][-1]
        days = [d for x in one["agents"].values() for d in x["weeks"][0]["strata"].values()]
        print(f"{NAME}, week of {monday}: this run sent {run['requests']} of {a.max_requests} requests in {time.time() - agent_pr_ci.START:.0f} s; "
              f"drew {sum(d['drawn'] for d in days)} of {sum(d['planned'] or 0 for d in days)} planned in {len(days)} strata, "
              f"read the checks of {sum(d['checks_read'] for d in days)} of {sum(d['claimed'] for d in days)} that claimed passing tests; "
              f"capped: {str(any(x['weeks'][0]['capped'] for x in one['agents'].values())).lower()}; checkpoint {a.rows}"
              + (f"; stopped early: {run['stopped']}" if run.get("stopped") else ""), file=sys.stderr)
        return 0
    if a.step == "scan":
        if a.week:
            got = scan_week(last_week() if a.week == "last" else a.week, a.max_seconds)
        else:
            previous = None
            if a.previous and os.path.exists(a.previous):
                previous = _load(a.previous)
            got = track(scan(a.end, a.days, a.per_agent, a.max_seconds, previous=previous, reserve=a.reserve),
                        os.path.join(agent_pr_ci.CACHE, "unfinished_since.json"))
        with open(a.rows, "w", encoding="utf-8") as f:
            json.dump(got, f, ensure_ascii=False)
        print(f"scanned {len(got['rows'])} PRs of {got['kept']} kept, counts {got['counts']}, "
              f"search unfinished for {got['unfinished_search'] or 'none'}, {got['unread']} unread"
              + (f"; {got['seeded']} verdicts taken from the last index" if got.get("seeded") else "")
              + (f"; stopped early: {got['stopped']}" if got.get("stopped") else ""), file=sys.stderr)
        return 0
    if a.step == "check":
        index = check(a.out)
        print(f"agent PR index: {index['n_prs']} PRs, root {index['root']} matches", file=sys.stderr)
        return 0
    if a.step == "restate":
        index = restate(check(a.out))
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump(index, f, ensure_ascii=False)
        print(f"agent PR index restated: {index['n_prs']} PRs, root {index['root']} unchanged", file=sys.stderr)
        return 0
    with open(a.rows, encoding="utf-8") as f:
        got = json.load(f)
    if a.step == "gate":
        previous = None
        if a.previous and os.path.exists(a.previous):
            with open(a.previous, encoding="utf-8") as f:
                previous = json.load(f)
        index = check(a.out)
        why, bad = gate(got, index, previous), errors(got, index, previous)
        for line in why:
            print(f"not published: {line}", file=sys.stderr)
        for line in bad:
            print(f"error: {line}", file=sys.stderr)
        if bad:
            _github_says(False)
            return 1
        if why:     # it stopped early: nothing goes out, the last release stays live, and the next run continues
            _github_says(False, f"the scan stopped early ({got.get('stopped') or 'see the scan step'}) and continues in the "
                                "next run (every 6 hours); the last index stays live")
            return 0
        print("the scan finished: publish it", file=sys.stderr)
        _github_says(True)
        return 0
    index = build(got["rows"], dt.date.today().isoformat(), got["window"], got["counts"]["excluded"])
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False)
    o = index["overall"]["first_pr_per_repo"]
    print(f"agent PR index: {index['n_prs']} PRs, {index['excluded_self_repo']} self-repo PRs excluded, "
          f"{o['repos']} repositories: any check failed in {o['any_check_failed']['repos']}, "
          f"a test, build, lint or type check in {o['test_or_build_check_failed']['repos']}; root {index['root']}",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
