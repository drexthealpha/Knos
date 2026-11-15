#!/usr/bin/env python3
"""backtest_paid.py -- merged pull requests that were PAID a bounty on another platform, and whether a check had failed.

The buyer's loss in the buyer's own market: on Algora and Opire a maintainer pays a bounty when a pull request is
merged. A Knos bounty pays only when the checks its terms require passed at the head commit (src/knos/terms.py). So, of
the pull requests that were paid a bounty elsewhere, how many had a failed check at the commit that was merged?

    GH_TOKEN=... python scripts/backtest_paid.py                 # collect, read, count; write docs/backtest_paid.json
                                                                  # and the block of docs/reference/BENCH.md
    python scripts/backtest_paid.py --days 270 --windows 9 --per-window 100

Until the release run executes this with a GitHub token, docs/backtest_paid.json says `"status": "not run"` and so does
the block of docs/reference/BENCH.md: no number is made up, and none is carried over from another measurement.

How a bounty is marked on GitHub (read 3 Oct 2026; the first two are documentation, the rest is what the script assumes
and the release run checks):
  Algora  the label "💎 Bounty" is on an issue that has a bounty         https://remotion.dev/bounties
          the bot adds a bounty label and replies with how to claim       https://docs.algora.io/bounties/workflow
          a solver claims with `/claim #N` in the pull request's body     https://docs.algora.io/commands
          the sponsor pays from the organisation's page ("Reward")        https://docs.algora.io/bounties/workflow
  Opire   a reward is made with `/reward 100`, a solver claims with        https://github.com/FalkorDB/docs/issues/297
          `/claim #N`; the bot's text is "created a $X reward using        https://github.com/abdulmajeedsualihu/Autokey/issues/1
          Opire"; the bot posts about it in the issue                      https://docs.opire.dev/overview/install-bot
Neither platform's public documentation says what its bot writes on GitHub when a bounty has been PAID, and I found no
public list of Opire's labels. So the paid marker below is a rule, not a fact: a comment by the platform's bot that says
awarded, rewarded, paid or sent next to the pull request author's @login, on the issue or on the pull request. Every
record keeps the URL of the comment it relied on, so the release run is also the check of the rule, and a bounty issue
with a merged pull request and no such comment is counted as `unpaid`, not dropped.
"""
import argparse
import datetime as dt
import json
import os
import re
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import agent_pr_ci  # noqa: E402
import agent_pr_index  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "docs", "backtest_paid.json")
BENCH = os.path.join(ROOT, "docs", "reference", "BENCH.md")
BLOCK = re.compile(r"<!-- backtest_paid:begin -->.*?<!-- backtest_paid:end -->", re.S)

PLATFORMS = {
    "algora": {"name": "Algora", "labels": ["💎 Bounty"], "text": None, "bot": r"algora",
               "sources": ["https://remotion.dev/bounties", "https://docs.algora.io/bounties/workflow",
                           "https://docs.algora.io/commands"]},
    "opire": {"name": "Opire", "labels": ["🎁 Reward"], "text": '"reward using Opire"', "bot": r"opire",
              "sources": ["https://github.com/abdulmajeedsualihu/Autokey/issues/1", "https://github.com/FalkorDB/docs/issues/297",
                          "https://docs.opire.dev/overview/install-bot"]},
}
PAID_WORDS = r"(?:awarded|rewarded|paid|sent)"

DEFINITIONS = {
    "issues": "closed issues that carry the platform's bounty label (or, for Opire, the text of its reward comment), created "
              "in the window, as many as GitHub's search returned: the newest first in each window, not a random sample",
    "merged": "of those, the ones with a pull request that was merged and is linked from the issue (a cross-reference in "
              "its timeline)",
    "paid": "of those, the merged pull requests whose author is named next to the word awarded, rewarded, paid or sent in "
            "a comment by the platform's bot on the issue or on the pull request. This is a rule about the bot's wording "
            "that the platform's public documentation does not state; `evidence` has the URL of each comment it used",
    "unpaid": "merged pull requests that close a bounty issue with no such comment: paid in a way GitHub does not show, "
              "not paid, or paid with other words. They are counted and left out of `paid`",
    "classified": "of the paid, the ones whose checks had finished (not pending, none) at the commit named",
    "failed_at_head": "of the classified, the ones with at least one failed check run (failure, timed_out, startup_failure) "
                      "or a failed commit status (failure, error) at the pull request's head commit, the commit Knos "
                      "judges; the agent session runs of agent_pr_ci are not checks",
    "failed_at_merge": "the same at the commit the merge made on the base branch (merge_commit_sha). Checks that ran "
                       "there ran after the merge: they show what the repository's CI said about the result, not what "
                       "the maintainer saw",
    "share, ci95": "the count over its total, and the 95% Wilson interval of that share",
}


def _key(r):
    return f"{r['repo']}#{r['number']}"


def windows(end, days, n):
    """n consecutive windows of `days` days ending on `end` (a date): [(first day, last day), ...], newest first."""
    out = []
    for i in range(n):
        last = end - dt.timedelta(days=i * days)
        out.append(((last - dt.timedelta(days=days - 1)).isoformat(), last.isoformat()))
    return out


def queries(platform, first, last):
    """The GitHub issue searches for a platform in one window."""
    p, span = PLATFORMS[platform], f"created:{first}..{last}"
    qs = [f'label:"{label}" is:issue is:closed {span}' for label in p["labels"]]
    if p["text"]:
        qs.append(f"{p['text']} in:comments,body is:issue is:closed {span}")
    return qs


def collect(platform, wins, per_window, get):
    """Candidate issues: {"platform", "repo", "number", "created_at", "url"}, deduplicated, from the searches."""
    seen, out = set(), []
    for first, last in wins:
        for q in queries(platform, first, last):
            for page in range(1, max(1, per_window // 100) + 1):
                got = get("search/issues", {"q": q, "per_page": 100, "page": page, "sort": "created", "order": "desc"}, kind="search")
                if not got["ok"]:
                    break
                items = got["json"].get("items", [])
                for it in items:
                    repo = it["repository_url"].split("/repos/")[-1]
                    key = f"{repo}#{it['number']}"
                    if key not in seen and "pull_request" not in it:
                        seen.add(key)
                        out.append({"platform": platform, "repo": repo, "number": it["number"], "created_at": it["created_at"],
                                    "url": it["html_url"]})
                if len(items) < 100:
                    break
    return out


def _pages(path, get, params=None, limit=5):
    items = []
    for page in range(1, limit + 1):
        got = get(path, {**(params or {}), "per_page": 100, "page": page})
        if not got["ok"]:
            break
        body = got["json"]
        items += body if isinstance(body, list) else []
        if not isinstance(body, list) or len(body) < 100:
            break
    return items


def linked_prs(issue, get):
    """The merged pull requests cross-referenced from an issue's timeline: [(repo, number), ...]."""
    out = []
    for ev in _pages(f"repos/{issue['repo']}/issues/{issue['number']}/timeline", get):
        src = (ev.get("source") or {}).get("issue") or {}
        if ev.get("event") == "cross-referenced" and src.get("pull_request") and src["pull_request"].get("merged_at"):
            pair = (src["repository"]["full_name"], src["number"])
            if pair not in out:
                out.append(pair)
    return out


def bot_comments(repo, number, platform, get):
    """Comments on an issue or pull request by the platform's bot: its login names the platform."""
    bot = re.compile(PLATFORMS[platform]["bot"], re.I)
    return [c for c in _pages(f"repos/{repo}/issues/{number}/comments", get)
            if bot.search((c.get("user") or {}).get("login", "")) and (c.get("user") or {}).get("type", "Bot") == "Bot"]


def paid_comment(comments, login):
    """The comment that says `login` was awarded, rewarded, paid or sent something, or None."""
    who = re.escape(login)
    rule = re.compile(rf"@{who}\b[^.\n]{{0,80}}\b{PAID_WORDS}\b|\b{PAID_WORDS}\b[^.\n]{{0,60}}@{who}\b", re.I)
    return next((c for c in comments if rule.search(c.get("body") or "")), None)


def check_state(repo, sha, get):
    """What CI said at a commit: {"class": failed | passed | other | pending | no-ci | error, "failed_checks": [...]}. The same
    reading as agent_pr_ci.classify, for any commit."""
    st = get(f"repos/{repo}/commits/{sha}/status")
    if not st["ok"]:
        return {"class": "error", "failed_checks": []}
    runs = []
    for page in range(1, 6):
        r = get(f"repos/{repo}/commits/{sha}/check-runs", {"per_page": 100, "page": page})
        if not r["ok"]:
            return {"class": "error", "failed_checks": []}
        runs += r["json"]["check_runs"]
        if len(r["json"]["check_runs"]) < 100:
            break
    statuses = st["json"].get("statuses", [])
    ci = [x for x in runs if not agent_pr_ci.AGENT_RUN_RE.match(x["name"].strip())]
    failed = [x["name"] for x in ci if x["conclusion"] in agent_pr_ci.FAIL_CONCL] + \
             [s["context"] for s in statuses if s["state"] in ("failure", "error")]
    states = [s["state"] for s in statuses]
    if failed:
        cls = "failed"
    elif not ci and not statuses:
        cls = "no-ci"
    elif any(x["status"] != "completed" for x in ci) or "pending" in states:
        cls = "pending"
    elif all(x["conclusion"] in agent_pr_ci.OK_CONCL for x in ci if x["status"] == "completed") and all(s == "success" for s in states):
        cls = "passed"
    else:
        cls = "other"
    return {"class": cls, "failed_checks": failed[:10]}


def evaluate(issue, get):
    """One record per merged pull request linked from the bounty issue: whether it was paid by the platform's own account of
    it, and what CI said at its head commit and at the commit its merge made."""
    out = []
    issue_comments = bot_comments(issue["repo"], issue["number"], issue["platform"], get)
    for repo, number in linked_prs(issue, get):
        pr = get(f"repos/{repo}/pulls/{number}")
        if not pr["ok"] or not pr["json"].get("merged_at"):
            continue
        pr = pr["json"]
        login = (pr.get("user") or {}).get("login", "")
        said = paid_comment(issue_comments + bot_comments(repo, number, issue["platform"], get), login)
        rec = {"platform": issue["platform"], "issue": f"{issue['repo']}#{issue['number']}", "repo": repo, "number": number,
               "author": login, "paid": bool(said), "evidence": said.get("html_url") if said else None,
               "claimed": bool(re.search(rf"/claim\s+#?{issue['number']}\b", pr.get("body") or "")),
               "head_sha": (pr.get("head") or {}).get("sha"), "merge_sha": pr.get("merge_commit_sha")}
        if rec["paid"]:
            for name, sha in (("head", rec["head_sha"]), ("merge", rec["merge_sha"])):
                rec[name] = check_state(repo, sha, get) if sha else {"class": "error", "failed_checks": []}
        out.append(rec)
    return out


def counts(rows):
    """{"prs", "failed": {"prs", "share", "ci95"}} over classified rows, by the class at each commit."""
    def over(sel):
        k = sum(1 for r in rows if sel(r))
        return {"prs": k, "share": round(k / len(rows), 4) if rows else None, "ci95": agent_pr_index.wilson(k, len(rows))}
    done = ("failed", "passed", "other")
    head = [r for r in rows if r["head"]["class"] in done]
    merge = [r for r in rows if r["merge"]["class"] in done]
    both = [r for r in rows if r["head"]["class"] in done and r["merge"]["class"] in done]

    def share(of, sel):
        k = sum(1 for r in of if sel(r))
        return {"of": len(of), "prs": k, "share": round(k / len(of), 4) if of else None, "ci95": agent_pr_index.wilson(k, len(of))}
    return {"paid": len(rows),
            "failed_at_head": share(head, lambda r: r["head"]["class"] == "failed"),
            "failed_at_merge": share(merge, lambda r: r["merge"]["class"] == "failed"),
            "failed_at_head_or_merge": share(both, lambda r: "failed" in (r["head"]["class"], r["merge"]["class"])),
            "not_classified": len(rows) - len(both)}


def backtest(records, issues_found):
    """The numbers: how many issues, merged pull requests, paid ones, and of those how many had a failed check."""
    paid = [r for r in records if r["paid"]]
    by = {}
    for p in PLATFORMS:
        mine = [r for r in records if r["platform"] == p]
        by[p] = {"issues": issues_found.get(p, 0), "merged_prs": len(mine), "paid": counts([r for r in mine if r["paid"]]),
                 "unpaid": sum(1 for r in mine if not r["paid"])}
    return {"issues": sum(issues_found.values()), "merged_prs": len(records), "paid": counts(paid),
            "unpaid": sum(1 for r in records if not r["paid"]), "claimed_among_paid": sum(1 for r in paid if r["claimed"]),
            "platforms": by,
            "evidence": [{"pr": _key(r), "paid_by": r["platform"], "comment": r["evidence"]} for r in paid][:200]}


def cannot_show(out):
    """What this run cannot work out from GitHub; each line says what is missing."""
    return ["How a platform marks a PAID bounty: neither platform documents what its bot writes on GitHub when it pays. "
            "`paid` follows the rule in `DEFINITIONS` of `scripts/backtest_paid.py`; a bounty paid without a bot comment is counted as `unpaid`",
            "Money: no amount is read. A comment can say paid for a tip, and a bounty can be paid in parts",
            "Whether the check was failing when the maintainer merged: CI is read as it is on the day of the run. A "
            "check re-run later shows its last result, and a check can fail after a merge (`failed_at_merge`)",
            "Which checks a Knos bounty on these issues would have required: none of them had one. This counts merges "
            "with a failed check, not payments refused",
            "Bounties in general: these are the newest closed issues per window that GitHub's search returned for the "
            "platform's label (and, for Opire, text), not a random sample, and only public repositories"]


def run(get, end, days, windows_n, per_window):
    """Collect, read and count: the whole document, from a GitHub reader `get(path, params=None, kind=...)`."""
    wins = windows(end, days, windows_n)
    issues = {p: collect(p, wins, per_window, get) for p in PLATFORMS}
    records = [rec for p in PLATFORMS for issue in issues[p] for rec in evaluate(issue, get)]
    out = {"status": "run", "about": "Of the merged pull requests that were paid a bounty on Algora or Opire, how many had a "
                                     "failed check. A Knos bounty whose terms required that check would not have paid the "
                                     "merge. Written by scripts/backtest_paid.py.",
           "read": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d"), "window": [wins[-1][0], wins[0][1]],
           "queries": {p: queries(p, *wins[0]) for p in PLATFORMS}, "sources": {p: PLATFORMS[p]["sources"] for p in PLATFORMS},
           "definitions": DEFINITIONS, **backtest(records, {p: len(v) for p, v in issues.items()})}
    out["cannot_show"] = cannot_show(out)
    return out


def not_run():
    return {"status": "not run", "about": "Of the merged pull requests that were paid a bounty on Algora or Opire, how many had a "
                                          "failed check. Not run yet: the release run executes scripts/backtest_paid.py with a "
                                          "GitHub token and fills this file.",
            "definitions": DEFINITIONS, "sources": {p: PLATFORMS[p]["sources"] for p in PLATFORMS}}


def _pct(x):
    return f"{x * 100:.1f}%"


def bench_block(out):
    """The block of docs/reference/BENCH.md, from not_run() or run()."""
    head = ["<!-- backtest_paid:begin -->", "### Paid elsewhere, and a check had failed", "",
            "`python scripts/backtest_paid.py` (with a GitHub token) writes `docs/backtest_paid.json`: of the merged pull "
            "requests that were paid a bounty on Algora or Opire (labels and commands: "
            + ", ".join(f"[{PLATFORMS[p]['name']}]({PLATFORMS[p]['sources'][0]})" for p in PLATFORMS) + "), how many had a failed "
            "check at the commit that was merged."]
    if out["status"] != "run":
        return "\n".join(head + ["", "**Not run.** The release run executes it and fills this block; until then there is no "
                                     "number here, and none is taken from another measurement.", "<!-- backtest_paid:end -->"])
    p = out["paid"]
    h, m, e = p["failed_at_head"], p["failed_at_merge"], p["failed_at_head_or_merge"]
    line = (f"Read {out['read']}: {out['issues']:,} closed bounty issues created {out['window'][0]} – {out['window'][1]}, "
            f"{out['merged_prs']:,} merged pull requests linked from them, {p['paid']:,} of them paid by the platform's own "
            f"account of it ({out['unpaid']:,} had no such comment and are left out). ")
    if h["of"]:
        line += (f"**At the head commit, {h['prs']} of {h['of']} ({_pct(h['share'])}) had a failed check** (95% Wilson interval "
                 f"{_pct(h['ci95'][0])}–{_pct(h['ci95'][1])}). At the commit the merge made: {m['prs']} of {m['of']}"
                 + (f" ({_pct(m['share'])}, {_pct(m['ci95'][0])}–{_pct(m['ci95'][1])})" if m["of"] else "")
                 + f". At either: {e['prs']} of {e['of']}"
                 + (f" ({_pct(e['share'])}, {_pct(e['ci95'][0])}–{_pct(e['ci95'][1])})" if e["of"] else "") + ".")
    else:
        line += "None of the paid pull requests had finished checks, so no share is given."
    rows = ["", line, "", "| platform | issues | merged pull requests | paid | classified at the head | failed at the head |",
            "|---|---|---|---|---|---|"]
    for key, v in out["platforms"].items():
        f = v["paid"]["failed_at_head"]
        rows.append(f"| {PLATFORMS[key]['name']} | {v['issues']:,} | {v['merged_prs']:,} | {v['paid']['paid']:,} | {f['of']:,} | {f['prs']:,} |")
    rows += ["", "What this cannot show:", ""] + [f"- {x}" for x in out["cannot_show"]] + ["<!-- backtest_paid:end -->"]
    return "\n".join(head + rows)


def update_bench(text, out):
    """docs/reference/BENCH.md with the block replaced (inserted after the block of `### Merged anyway` when there is none)."""
    block = bench_block(out)
    if BLOCK.search(text):
        return BLOCK.sub(lambda _: block, text)
    anchor = "<!-- /bench:backtest -->"
    if anchor in text:
        return text.replace(anchor, anchor + "\n\n" + block, 1)
    return text.rstrip("\n") + "\n\n" + block + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--bench", default=BENCH, help="docs/reference/BENCH.md: its backtest_paid block is rewritten")
    ap.add_argument("--end", help="last day of the newest window, YYYY-MM-DD (default: today)")
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--windows", type=int, default=9)
    ap.add_argument("--per-window", type=int, default=100, help="issues read per window and query (a multiple of 100)")
    ap.add_argument("--max-seconds", type=int, default=3000)
    ap.add_argument("--not-run", action="store_true", help="write the `not run` document and block, and read nothing")
    a = ap.parse_args(argv)
    if a.not_run:
        out = not_run()
    else:
        agent_pr_ci.ARGS = SimpleNamespace(max_seconds=a.max_seconds)
        end = dt.date.fromisoformat(a.end) if a.end else dt.datetime.now(dt.timezone.utc).date()
        try:
            out = run(agent_pr_ci.gh_get, end, a.days, a.windows, a.per_window)
        except agent_pr_ci.OutOfTime:
            print("out of time: run it again and it continues from the answers it kept", file=sys.stderr)
            return 1
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1, ensure_ascii=False)
        f.write("\n")
    with open(a.bench, encoding="utf-8") as f:
        text = f.read()
    with open(a.bench, "w", encoding="utf-8") as f:
        f.write(update_bench(text, out))
    print("backtest_paid: " + ("not run" if out["status"] != "run" else
                               f"{out['paid']['paid']} paid merged pull requests, "
                               f"{out['paid']['failed_at_head']['prs']} with a failed check at the head"), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
