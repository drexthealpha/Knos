#!/usr/bin/env python3
"""agent_pr_index.py -- the Agent PR Index: of PRs by AI coding agents whose body claims tests/CI pass, what did CI
actually say at the head SHA? Same agents, claim regexes and CI verdict as agent_pr_ci.py.

Steps, so the Pages build never scans:

    python scripts/agent_pr_index.py scan --rows rows.json     # slow, resumable (.github/workflows/index.yml, 6 h)
    python scripts/agent_pr_index.py build --rows rows.json --out index.json    # offline
    python scripts/agent_pr_index.py gate --rows rows.json --out index.json [--previous last.json]   # may it go out?
    python scripts/agent_pr_index.py check --out index.json    # the root matches the listed records
    python scripts/agent_pr_index.py restate --out index.json  # recount a published index from its own records
    python scripts/agent_pr_index.py weekly --rows rows.json --out agent_weekly.json [--doc docs/INDEX.md]
                                                               # the same scan by agent and by week (weekly() below)
    python scripts/agent_pr_index.py weekly --sample docs/agent_pr_ci.json --out docs/agent_weekly.json --doc docs/INDEX.md
                                                               # offline: the committed sample, by week

index.yml uploads index.json as the asset of a GitHub Release tagged index-<date> (a release, not a data commit);
network.yml downloads the newest one into the Pages site.

The scan searches each agent over date windows (GitHub caps a query at 1,000 results), drops PRs on repos owned by
the PR's author or the human who assigned the agent (self repos are not a market observation; the count is kept),
and classifies CI at each head SHA. It says whether it finished: `gate` refuses a scan that did not (a search that
ran out of time or was refused, pull requests GitHub did not answer for), so a partial sample is never published
and the run that made it fails where it can be seen. The build writes:

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
import hashlib
import json
import math
import os
import sys
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


def scan(end, days, per_agent, max_seconds):
    """Search, then read CI for what the search kept. Never throws work away: an agent whose search ran out of time
    keeps what it found, and the result says what is missing (`unfinished_search`, `unread`) so `gate` can refuse it."""
    agent_pr_ci.ARGS = SimpleNamespace(max_seconds=max_seconds)
    agent_pr_ci.SEARCH_PAUSE = 2.1  # concurrent agents share one 30/min search pacing; gh_get backs off on 403/429
    del agent_pr_ci.NO_CLAIM[:]
    agent_pr_ci.prune(days + 7)     # answers about pull requests that have left the window
    kept, n, unfinished = agent_pr_ci.scan_collect(end, days, per_agent)
    agent_pr_ci.run_checks(kept)
    start = (dt.date.fromisoformat(end) - dt.timedelta(days=days - 1)).isoformat()
    unread = sum(1 for c in kept if c.get("class") is None or (c["class"] == "error" and c.get("transient")))
    return {"window": [start, end], "counts": n, "kept": len(kept), "unfinished_search": unfinished, "unread": unread,
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
}
WEEKLY_LIMITS = [
    "An agent is told by its author account or by a line its tool writes in the description (`agents`). A person "
    "who pastes that line is counted as the agent; an agent run under a person's own account without it is missed.",
    "Public repositories only: GitHub's search does not return private ones.",
    "One snapshot of the checks: what GitHub showed at the head commit when it was read. A check that was run again "
    "later, or a commit pushed after, is not seen. The agent's own session run is not a check.",
    "The search asks for a few claim phrases, so `sampled` is not every pull request the agent opened.",
    "A week holds few pull requests for some agents: read the interval, not the share.",
]


def week_of(created_at):
    """The Monday (UTC) of the week of a GitHub timestamp, as a date."""
    day = dt.datetime.fromisoformat(str(created_at).replace("Z", "+00:00")).astimezone(dt.timezone.utc).date()
    return (day - dt.timedelta(days=day.weekday())).isoformat()


def _rate(k, n):
    return {"k": k, "n": n, "share": round(k / n, 4) if n else None, "ci95": wilson(k, n)}


def week_counts(mine, set_aside):
    """One row of the series over the claimed pull requests `mine`; `set_aside`: how many more hits claimed nothing,
    or None when that is not known."""
    done = [r for r in mine if r.get("class") in COMPLETED]
    failed = [r for r in done if r["class"] == "failed"]
    known = all(isinstance(r.get("merged"), bool) for r in done)      # one pull request not read: null, never a guess
    merged = [r for r in done if r.get("merged") is True]
    return {"sampled": None if set_aside is None else len(mine) + set_aside, "claimed_passing": len(mine), "ci_finished": len(done),
            "failed_a_check": {**_rate(len(failed), len(done)),
                               "test_or_build": sum(1 for r in failed if agent_pr_ci.is_testish_failure(r))},
            "merged_despite_failed_check": _rate(sum(1 for r in merged if r["class"] == "failed"), len(merged)) if known and done else None}


def weekly(rows, window, read, source, no_claim=None, agents=None):
    """The scan's claimed pull requests by agent and by week of creation. `rows`: classified candidates with
    `created_at` (and `merged` where it was read); `no_claim`: [agent, created_at] of the hits that claimed nothing,
    or None when the source did not keep them. Deterministic for the same rows."""
    agents = agents or [list(a) for a in agent_pr_ci.AGENTS]
    out = {"read": read, "window": list(window), "source": source, "agents_told_by": {n: q for n, q in agents},
           "claim_search": agent_pr_ci.CLAIM_SEARCH, "definitions": WEEKLY_DEFINITIONS, "limits": WEEKLY_LIMITS, "agents": {}}
    for name, _ in agents:
        mine = [r for r in rows if r["agent"] == name and r.get("class") not in (None, "error")]
        aside = None if no_claim is None else [week_of(at) for a, at in no_claim if a == name]
        weeks = sorted({week_of(r["created_at"]) for r in mine} | set(aside or []))
        out["agents"][name] = {
            "weeks": [{"week": w, **week_counts([r for r in mine if week_of(r["created_at"]) == w],
                                                None if aside is None else aside.count(w))} for w in weeks],
            "all_weeks": week_counts(mine, None if aside is None else len(aside))}
    return out


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


def weekly_table(series):
    """The latest week of each agent and its whole window, as the Markdown docs/INDEX.md shows between its markers."""
    lines = [f"Read {series['read']}; pull requests created {series['window'][0]} to {series['window'][1]}; source: {series['source']}.",
             "", "| Agent | Week of | Sampled | Claimed passing | CI finished | Failed a check (95% interval) | Merged despite a failed check (95% interval) |",
             "| --- | --- | --- | --- | --- | --- | --- |"]
    for name, a in series["agents"].items():
        latest = a["weeks"][-1:] if a["weeks"] else []
        for label, w in [(x["week"], x) for x in latest] + [("all weeks", a["all_weeks"])]:
            lines.append(f"| {name} | {label} | {'not kept' if w['sampled'] is None else w['sampled']} | {w['claimed_passing']} | "
                         f"{w['ci_finished']} | {_cell(w['failed_a_check'])} | {_cell(w['merged_despite_failed_check'])} |")
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


def weekly_main(a):
    if a.sample:
        with open(a.sample, encoding="utf-8") as f:
            sample = json.load(f)
        days = sorted(r["created_at"][:10] for r in sample["prs"])
        series = weekly(sample["prs"], (days[0], days[-1]), sample["generated_utc"][:10],
                        f"{a.sample}, the sample read on {sample['generated_utc'][:10]}, reshaped by week (nothing was read "
                        "again). Unlike the index, this sample kept pull requests on repositories their author owns",
                        None, sample.get("agents"))
        for name, agent in series["agents"].items():      # the hits it set aside are listed without a date: a total, no week
            agent["all_weeks"]["sampled"] = agent["all_weeks"]["claimed_passing"] + sum(
                1 for r in sample.get("rejected_no_claim", []) if r["agent"] == name)
    else:
        with open(a.rows, encoding="utf-8") as f:
            got = json.load(f)
        agent_pr_ci.ARGS = SimpleNamespace(max_seconds=a.max_seconds)
        series = weekly(read_merged(got["rows"]), got["window"], dt.date.today().isoformat(),
                        "the scan behind the Agent PR Index of the same day", got.get("no_claim"))
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(series, f, ensure_ascii=False, indent=1)
        f.write("\n")
    if a.doc:
        render_doc(a.doc, series)
    print(f"weekly series: {sum(len(x['weeks']) for x in series['agents'].values())} agent-weeks, {a.out}", file=sys.stderr)
    return 0


MAX_UNREAD = 0.02       # of the pull requests a scan kept, the share GitHub may leave unanswered in a scan that goes out
MIN_OF_PREVIOUS = 0.5   # a scan with under half the last index's pull requests means the search broke, not the world


def gate(scanned, index, previous=None):
    """Why this scan must not be published; an empty list means publish it. A scan goes out when every agent's search
    finished, GitHub answered for (nearly) every pull request it kept, and it did not shrink to under half of the
    last published index. Each reason says what to do."""
    why = []
    kept, unread = scanned.get("kept", len(scanned["rows"])), scanned.get("unread", 0)
    if scanned.get("unfinished_search"):
        why.append(f"the search did not finish for {', '.join(scanned['unfinished_search'])} (out of time, or GitHub "
                   "refused a query: see the scan step's log). What it read is cached: run the workflow again")
    if unread > MAX_UNREAD * kept:
        why.append(f"GitHub did not answer for {unread:,} of the {kept:,} pull requests the search kept (out of time "
                   "or over the hourly limit). What it read is cached: the next run continues from here. A "
                   "KNOS_INDEX_TOKEN secret (a read-only token) has five times the hourly limit")
    if not index["n_prs"]:
        why.append("no pull request with finished CI was found: the search or the token is broken")
    elif previous and index["n_prs"] < MIN_OF_PREVIOUS * previous.get("n_prs", 0):
        why.append(f"{index['n_prs']:,} pull requests, under half of the last index's {previous['n_prs']:,}: check "
                   "the search queries in scripts/agent_pr_ci.py before publishing this")
    return why


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=["scan", "build", "gate", "check", "restate", "weekly"])
    ap.add_argument("--sample", help="weekly: reshape this committed sample (docs/agent_pr_ci.json) and read nothing")
    ap.add_argument("--doc", help="weekly: also write the table between the markers of this file (docs/INDEX.md)")
    ap.add_argument("--rows", default="rows.json")
    ap.add_argument("--out", default="_site/index.json")
    ap.add_argument("--previous", help="gate: the index published last, when there is one")
    ap.add_argument("--end", default=(dt.date.today() - dt.timedelta(days=1)).isoformat())
    ap.add_argument("--days", type=int, default=120)
    ap.add_argument("--per-agent", type=int, default=480)
    ap.add_argument("--max-seconds", type=int, default=3 * 3600)
    a = ap.parse_args()
    if a.step == "weekly":
        return weekly_main(a)
    if a.step == "scan":
        got = scan(a.end, a.days, a.per_agent, a.max_seconds)
        with open(a.rows, "w", encoding="utf-8") as f:
            json.dump(got, f, ensure_ascii=False)
        print(f"scanned {len(got['rows'])} PRs of {got['kept']} kept, counts {got['counts']}, "
              f"search unfinished for {got['unfinished_search'] or 'none'}, {got['unread']} unread", file=sys.stderr)
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
        why = gate(got, check(a.out), previous)
        for line in why:
            print(f"not published: {line}", file=sys.stderr)
        if not why:
            print("the scan finished: publish it", file=sys.stderr)
        return 1 if why else 0
    index = build(got["rows"], dt.date.today().isoformat(), got["window"], got["counts"]["excluded"])
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False)
    o = index["overall"]["first_pr_per_repo"]
    print(f"agent PR index: {index['n_prs']} PRs, {index['excluded_self_repo']} self-repo PRs excluded, "
          f"{o['repos']} repositories: any check failed in {o['any_check_failed']['repos']}, "
          f"a test or build check in {o['test_or_build_check_failed']['repos']}; root {index['root']}",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
