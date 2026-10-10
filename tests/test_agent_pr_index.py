"""The Agent PR Index, offline: fixture PRs through agent_pr_ci's classification, then a deterministic Merkle root;
both published counts under names that say what they count; Wilson intervals, self-repo exclusion, a root that refuses
an edited list; and a scheduled run that either publishes or fails in the open (the scan keeps what GitHub answered,
says what is missing, and the gate refuses a scan that did not finish)."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import agent_pr_ci  # noqa: E402
import agent_pr_index  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
RUNS = {
    "aaa": [{"name": "build", "status": "completed", "conclusion": "failure"},
            {"name": "Copilot", "status": "completed", "conclusion": "success"}],
    "bbb": [{"name": "test", "status": "completed", "conclusion": "success"}],
    "ccc": [{"name": "Copilot", "status": "completed", "conclusion": "failure"}],  # agent's own run only
}
WINDOW = ("2026-09-25", "2026-10-01")


def fake_gh(path, params=None, kind="core", max_age=None):
    parts = path.split("/")
    if "/refs/pull/" in path:  # the PR ref's combined status names the head SHA
        sha = {"1": "aaa", "2": "bbb", "3": "ccc"}[parts[parts.index("pull") + 1]]
        return {"ok": True, "json": {"sha": sha, "statuses": []}}
    sha = parts[parts.index("commits") + 1]
    if path.endswith("check-runs"):
        return {"ok": True, "json": {"check_runs": RUNS[sha]}}
    return {"ok": True, "json": {"check_suites": []}}


def fixtures():
    bodies = ["Fixed the parser. All tests pass.", "Done; `npm test` passes", "CI is green ✅",
              "Please make sure tests pass before merging"]
    out = []
    for i, (agent, body) in enumerate(zip(["copilot", "codex", "devin", "copilot"], bodies), 1):
        phrase, line = agent_pr_ci.find_claim(body)
        out.append({"agent": agent, "repo": f"o/r{i}", "number": i, "phrase": phrase, "claim_line": line})
    return out


def _none(unit):
    return {unit: 0, "share": None, "ci95": None}


def test_classification_and_deterministic_root(monkeypatch):
    monkeypatch.setattr(agent_pr_ci, "gh_get", fake_gh)
    cands = fixtures()
    assert [bool(c["phrase"]) for c in cands] == [True, True, True, False]  # "make sure ... pass" is not a claim
    claimed = [c for c in cands if c["phrase"]]
    assert agent_pr_ci.run_checks(claimed)
    assert [c["class"] for c in claimed] == ["failed", "passed", "no-ci"]
    assert claimed[0]["failed_checks"] == ["build"]  # the agent's own "Copilot" run is not project CI

    a = agent_pr_index.build(claimed, "2026-10-01", WINDOW)
    b = agent_pr_index.build(list(reversed(claimed)), "2026-10-01", WINDOW)
    assert a == b and len(a["root"]) == 64
    one = {"share": 1.0, "ci95": agent_pr_index.wilson(1, 1)}
    assert a["agents"]["copilot"] == {
        "prs": 1, "any_check_failed": {"prs": 1, **one}, "test_or_build_check_failed": {"prs": 1, **one},
        "first_pr_per_repo": {"repos": 1, "any_check_failed": {"repos": 1, **one},
                              "test_or_build_check_failed": {"repos": 1, **one}}}
    assert a["agents"]["codex"]["any_check_failed"]["share"] == 0.0 and a["agents"]["codex"]["any_check_failed"]["ci95"][0] == 0.0
    assert a["agents"]["devin"] == {                                         # no CI is not green
        "prs": 0, "any_check_failed": _none("prs"), "test_or_build_check_failed": _none("prs"),
        "first_pr_per_repo": {"repos": 0, "any_check_failed": _none("repos"), "test_or_build_check_failed": _none("repos")}}
    assert a["overall"]["prs"] == 2 and a["overall"]["any_check_failed"]["prs"] == 1
    assert set(a["prs"][0]) == set(agent_pr_index.PR_KEYS)
    assert a["n_prs"] == 2  # the no-CI PR is not listed: only finished CI at the head SHA counts

    claimed[1]["class"] = "failed"  # any change to a counted record changes the root
    assert agent_pr_index.build(claimed, "2026-10-01", WINDOW)["root"] != a["root"]


def test_both_counts_are_published_each_under_the_name_of_what_it_counts():
    """A failed deploy preview or label gate is a failed check, and it is not a failed test: the index says both, and
    the two names cannot be read as each other."""
    def pr(n, repo, checks, cls="failed"):
        return {"agent": "copilot", "repo": repo, "number": n, "sha": "a" * 40, "class": cls, "failed_checks": checks,
                "phrase": "tests pass"}
    rows = [pr(1, "a/tests", ["pytest (3.12)"]), pr(2, "b/preview", ["Vercel"]), pr(3, "c/labels", ["Validate PR title"]),
            pr(4, "d/both", ["Vercel", "build"]), pr(5, "e/gate", ["CI Gate"]), pr(6, "f/ok", [], "passed"),
            pr(7, "a/tests", ["Vercel"]), pr(8, "g/other", [], "other")]
    ix = agent_pr_index.build(rows, "2026-10-02", ["2026-06-04", "2026-10-01"])
    o = ix["overall"]
    assert o["prs"] == 8 and o["any_check_failed"]["prs"] == 6 and o["test_or_build_check_failed"]["prs"] == 2
    r = o["first_pr_per_repo"]                    # a/tests counts once, by its first pull request (#1, a failed test)
    assert r["repos"] == 7 and r["any_check_failed"]["repos"] == 5 and r["test_or_build_check_failed"]["repos"] == 2
    assert r["test_or_build_check_failed"] == {"repos": 2, "share": round(2 / 7, 4), "ci95": agent_pr_index.wilson(2, 7)}
    # the old names said "failed" without saying what failed; they are gone, and the file defines the new ones itself
    text = json.dumps({k: v for k, v in ix.items() if k != "prs"})
    for old in ("claimed_green", "actually_failed", "by_repo"):
        assert old not in text
    assert set(ix["definitions"]) >= {"prs", "any_check_failed", "test_or_build_check_failed", "first_pr_per_repo"}
    assert "deploy preview" in ix["definitions"]["any_check_failed"]
    # the stricter count can never exceed the other, for any agent, in what the docs quote
    bench = json.loads((ROOT / "docs" / "bench.json").read_text(encoding="utf-8"))["market"]["index"]
    for _, a in [*bench["agents"], ("all", bench["overall"])]:
        for part, unit in ((a, "prs"), (a["first_pr_per_repo"], "repos")):
            assert part["test_or_build_check_failed"][unit] <= part["any_check_failed"][unit] <= part[unit]


def test_the_docs_quote_what_the_published_index_counts():
    """docs/bench.json is the published index (release index-2026-10-02) counted again from its own 2,431 records:
    `python scripts/bench_docs.py --from index.json`. The headline and the stricter count, pinned."""
    ix = json.loads((ROOT / "docs" / "bench.json").read_text(encoding="utf-8"))["market"]["index"]
    o, r = ix["overall"], ix["overall"]["first_pr_per_repo"]
    assert (ix["n_prs"], o["prs"], r["repos"]) == (2431, 2431, 826)
    assert r["any_check_failed"] == {"repos": 147, "share": 0.178, "ci95": [0.1534, 0.2055]}
    assert r["test_or_build_check_failed"] == {"repos": 80, "share": 0.0969, "ci95": [0.0785, 0.1189]}
    assert (o["any_check_failed"]["prs"], o["test_or_build_check_failed"]["prs"]) == (660, 440)
    assert ix["root"] == "9876fdad603525385201166bc4bf2e98294608af0ca8b09d36793fa257825110"
    assert sum(a["prs"] for _, a in ix["agents"]) == ix["n_prs"]


def test_a_published_index_is_recounted_from_its_own_records(tmp_path):
    """An index published before both counts had names holds everything needed to restate it: its records."""
    rows = [{"agent": "codex", "repo": "o/r", "number": n, "sha": "a" * 40, "class": c, "failed_checks": f, "phrase": "tests pass"}
            for n, c, f in ((1, "failed", ["Vercel"]), (2, "failed", ["unit tests"]), (3, "passed", []))]
    new = agent_pr_index.build(rows, "2026-10-02", ("a", "b"), excluded=7)
    old = {**{k: new[k] for k in ("date", "window", "n_prs", "excluded_self_repo", "prs", "root")},
           "overall": {"claimed_green": 3, "actually_failed": 2, "share": 0.6667, "ci95": [0.2, 0.9]}, "agents": {}}
    assert agent_pr_index.restate(old) == new
    old["prs"][0]["class"] = "passed"
    with pytest.raises(SystemExit):
        agent_pr_index.restate(old)


def test_wilson_interval():
    lo, hi = agent_pr_index.wilson(55, 303)  # the 0.3.4 sample's published 14.2%-22.9%
    assert (round(lo, 3), round(hi, 3)) == (0.142, 0.229)
    assert agent_pr_index.wilson(0, 0) is None
    assert agent_pr_index.wilson(0, 10)[0] == 0.0 and agent_pr_index.wilson(10, 10)[1] == 1.0


def item(owner, author, assignees=()):
    return {"repository_url": f"https://api.github.com/repos/{owner}/r", "user": {"login": author},
            "assignees": [{"login": x} for x in assignees]}


def test_self_repo_exclusion():
    assert agent_pr_ci.excluded_self(item("alice", "alice"))  # Claude Code / Codex PR on the author's own repo
    assert agent_pr_ci.excluded_self(item("Alice", "Copilot", ["alice"]))  # the human who assigned Copilot owns it
    assert not agent_pr_ci.excluded_self(item("acme", "Copilot", ["alice"]))
    assert not agent_pr_ci.excluded_self(item("acme", "devin-ai-integration[bot]"))


def test_scan_windows_cover_the_range_newest_first_and_stay_put_from_day_to_day():
    import datetime as dt
    w = agent_pr_ci.scan_windows("2026-10-01", 10, 3)
    assert w[0][1] == "2026-10-01" and w[-1][0] == "2026-09-22"            # exactly the ten days, newest first
    days = [dt.date.fromisoformat(a) + dt.timedelta(n) for a, b in w
            for n in range((dt.date.fromisoformat(b) - dt.date.fromisoformat(a)).days + 1)]
    assert sorted(days) == [dt.date(2026, 9, 22) + dt.timedelta(n) for n in range(10)] and len(set(days)) == 10
    assert all((dt.date.fromisoformat(b) - dt.date.fromisoformat(a)).days < 3 for a, b in w)
    # the next day asks the same questions again, but for the newest and the oldest window: the rest is on disk
    for width, shared in ((1, 119), (5, 23), (10, 11)):
        today, tomorrow = (agent_pr_ci.scan_windows(end, 120, width) for end in ("2026-10-01", "2026-10-02"))
        assert len(set(today) & set(tomorrow)) == shared and len(set(tomorrow) - set(today)) <= 2, width
        assert tomorrow[0][1] == "2026-10-02" and tomorrow[-1][0] == "2026-06-05"


def test_scan_excludes_self_repos_and_counts_them(monkeypatch):
    items = [dict(item("alice", "alice"), number=1, body="All tests pass.", created_at="t"),
             dict(item("acme", "alice"), number=2, body="All tests pass.", created_at="t"),
             dict(item("acme", "bob"), number=3, body="no claim here", created_at="t")]
    monkeypatch.setattr(agent_pr_ci, "gh_get", lambda *a, **k: {"ok": True, "json": {"items": items}})
    kept, n, finished = agent_pr_ci.scan_agent("codex", "x", "2026-10-01", 2, 10)
    assert [k["number"] for k in kept] == [2] and n == {"hits": 3, "excluded": 1, "no_claim": 1, "cut_short": 0, "capped": 0} and finished
    monkeypatch.setattr(agent_pr_ci, "gh_get", lambda *a, **k: {"ok": True, "json": {"items": items, "incomplete_results": True}})
    assert agent_pr_ci.scan_agent("codex", "x", "2026-10-01", 2, 10)[1]["cut_short"] == 2      # one page in each of two windows


def test_check_refuses_a_tampered_list(tmp_path):
    idx = agent_pr_index.build([{"agent": "codex", "repo": "o/r", "number": 1, "sha": "a", "class": "failed"}],
                               "2026-10-02", ("a", "b"), excluded=7)
    assert idx["excluded_self_repo"] == 7 and idx["n_prs"] == 1
    p = tmp_path / "index.json"
    p.write_text(json.dumps(idx), encoding="utf-8")
    assert agent_pr_index.check(str(p))["root"] == idx["root"]
    idx["prs"][0]["class"] = "passed"  # edited after the count: the root no longer matches
    p.write_text(json.dumps(idx), encoding="utf-8")
    with pytest.raises(SystemExit):
        agent_pr_index.check(str(p))


def test_one_pull_request_per_repository_is_counted_beside_every_pull_request():
    """A repository whose agent opened many failing pull requests counts once: the figure the docs quote first."""
    rows = [{"agent": "devin", "repo": "busy/Repo", "number": n, "sha": "a" * 40, "class": "failed", "failed_checks": ["ci"], "phrase": "tests pass"}
            for n in range(2, 12)]
    rows.append({"agent": "devin", "repo": "busy/repo", "number": 1, "sha": "b" * 40, "class": "passed", "failed_checks": [], "phrase": "tests pass"})
    rows += [{"agent": "devin", "repo": f"quiet/r{i}", "number": 5, "sha": "c" * 40, "class": "passed" if i else "failed",
              "failed_checks": [], "phrase": "tests pass"} for i in range(4)]
    ix = agent_pr_index.build(rows, "2026-10-02", ["2026-06-04", "2026-10-01"])
    assert ix["overall"]["any_check_failed"]["prs"] == 11 and ix["overall"]["prs"] == 15                 # 73% of pull requests
    # five repositories; busy/repo's first pull request (#1) passed, so only quiet/r0 counts as failed
    assert ix["overall"]["first_pr_per_repo"]["any_check_failed"] == {"repos": 1, "share": 0.2, "ci95": agent_pr_index.wilson(1, 5)}
    assert ix["overall"]["first_pr_per_repo"]["repos"] == 5
    assert ix["agents"]["devin"]["first_pr_per_repo"]["repos"] == 5 and ix["agents"]["codex"]["first_pr_per_repo"]["repos"] == 0


# ---- a scheduled run publishes, or fails in the open ---------------------------------------------------------------

class Github:
    """A GitHub that answers from a table and can be told to run out, refuse, or fail: what `gh api` would print."""

    def __init__(self):
        self.calls, self.script, self.core_left, self.reset_in = [], {}, None, 1800

    def __call__(self, cmd):
        path = cmd[4]
        self.calls.append(path)
        if path == "rate_limit":
            return 0, json.dumps({"resources": {"core": {"remaining": self.core_left or 0, "reset": time.time() + self.reset_in}}}), ""
        if self.core_left is not None and not path.startswith("search/"):
            if self.core_left == 0:
                return 1, "", "gh: API rate limit exceeded for installation ID 1. (HTTP 403)"
            self.core_left -= 1
        answers = self.script.get(path)
        got = answers.pop(0) if isinstance(answers, list) and len(answers) > 1 else (answers[0] if isinstance(answers, list) else answers)
        if got is None:
            return 1, "", "gh: Not Found (HTTP 404)"
        return (0, json.dumps(got), "") if not isinstance(got, str) else (1, "", got)


@pytest.fixture()
def github(tmp_path, monkeypatch):
    gh, slept = Github(), []
    monkeypatch.setattr(agent_pr_ci, "CACHE", str(tmp_path / "cache"))      # never the real ~/.cache
    monkeypatch.setattr(agent_pr_ci, "_gh", gh)
    monkeypatch.setattr(agent_pr_ci, "ARGS", SimpleNamespace(max_seconds=10_000))
    monkeypatch.setattr(agent_pr_ci, "START", time.time())
    monkeypatch.setattr(agent_pr_ci, "SEARCH_PAUSE", 0)

    def sleep(seconds):                                                     # waiting for the budget brings it back
        slept.append(seconds)
        if seconds >= gh.reset_in:
            gh.core_left = 1000
    monkeypatch.setattr(agent_pr_ci.time, "sleep", sleep)
    gh.slept = slept
    return gh


def test_only_an_answer_that_will_not_change_is_kept(github):
    status = "repos/o/r/commits/refs/pull/1/head/status"
    github.script[status] = ["gh: Internal Server Error (HTTP 502)"]
    got = agent_pr_ci.gh_get(status)
    assert got == {"ok": False, "error": "gh: Internal Server Error (HTTP 502)", "transient": True}
    assert github.calls.count(status) == 4                                  # asked again three times, then given up
    github.script[status] = [{"sha": "abc", "statuses": []}]
    assert agent_pr_ci.gh_get(status)["json"]["sha"] == "abc"               # not kept: the next read asks GitHub again
    n = len(github.calls)
    assert agent_pr_ci.gh_get(status)["json"]["sha"] == "abc" and len(github.calls) == n          # kept now
    gone = "repos/o/deleted/commits/refs/pull/9/head/status"
    github.script[gone] = None
    assert agent_pr_ci.gh_get(gone) == {"ok": False, "error": "gh: Not Found (HTTP 404)"}
    n = len(github.calls)
    assert not agent_pr_ci.gh_get(gone)["ok"] and len(github.calls) == n    # a deleted pull request stays deleted
    # a search GitHub ran out of time on is asked twice more, then taken as it is; a refused query is never kept
    n = len(github.calls)
    github.script["search/issues"] = [{"incomplete_results": True, "items": []}]
    assert agent_pr_ci.gh_get("search/issues", {"q": "x"}, kind="search")["ok"] and len(github.calls) == n + 3
    github.script["search/issues"] = ["gh: Validation Failed (HTTP 422)"]
    assert agent_pr_ci.gh_get("search/issues", {"q": "y"}, kind="search").get("transient") is True


def test_a_cache_file_cut_short_by_a_killed_run_is_read_as_no_answer(github, tmp_path):
    status = "repos/o/r/commits/refs/pull/1/head/status"
    github.script[status] = [{"sha": "abc", "statuses": []}]
    agent_pr_ci.gh_get(status)
    [kept] = list((tmp_path / "cache" / "core").rglob("*.json"))
    assert not list((tmp_path / "cache").rglob("*.tmp"))                    # written in one step
    kept.write_text('{"key": "x", "resp": {"ok": tr', encoding="utf-8")
    n = len(github.calls)
    assert agent_pr_ci.gh_get(status)["json"]["sha"] == "abc" and len(github.calls) == n + 1


def test_when_the_hourly_budget_is_spent_the_scan_waits_for_it_instead_of_giving_up(github):
    github.core_left, github.reset_in = 1, 1800
    for n in (1, 2):
        github.script[f"repos/o/r/commits/refs/pull/{n}/head/status"] = [{"sha": f"s{n}", "statuses": []}]
    assert agent_pr_ci.gh_get("repos/o/r/commits/refs/pull/1/head/status")["ok"]
    assert agent_pr_ci.gh_get("repos/o/r/commits/refs/pull/2/head/status")["json"]["sha"] == "s2"
    assert len(github.slept) == 1 and 1800 <= github.slept[0] <= 1810       # until the reset GitHub names, once
    # with less time left than the wait, it stops and says so: what was read stays on disk for the next run
    github.core_left, github.reset_in = 0, 20_000
    with pytest.raises(agent_pr_ci.OutOfTime):
        agent_pr_ci.gh_get("repos/o/r/commits/refs/pull/3/head/status")


def test_a_verdict_that_was_not_final_is_read_again_and_a_final_one_is_not(github, monkeypatch):
    import datetime as dt
    now = dt.datetime.now(dt.timezone.utc)
    young = {"repo": "o/r", "number": 1, "phrase": "tests pass", "created_at": (now - dt.timedelta(days=2)).isoformat()}
    old = {**young, "number": 2, "created_at": (now - dt.timedelta(days=60)).isoformat()}
    done = {**young, "number": 3}
    running = [{"name": "test", "status": "in_progress", "conclusion": None}]
    passed = [{"name": "test", "status": "completed", "conclusion": "success"}]
    for n in (1, 2, 3):
        github.script[f"repos/o/r/commits/refs/pull/{n}/head/status"] = [{"sha": f"s{n}", "statuses": []}]
        github.script[f"repos/o/r/commits/s{n}/check-runs"] = [{"check_runs": passed if n == 3 else running}, {"check_runs": passed}]
    rows = [dict(young), dict(old), dict(done)]
    assert agent_pr_ci.run_checks(rows) and [r["class"] for r in rows] == ["pending", "pending", "passed"]
    first = len(github.calls)
    # six hours later (the next scheduled run): the answers on disk are older than RECHECK_AFTER
    monkeypatch.setattr(agent_pr_ci, "_now", lambda: dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=6))
    rows = [dict(young), dict(old), dict(done)]
    assert agent_pr_ci.run_checks(rows) and [r["class"] for r in rows] == ["passed", "pending", "passed"]
    again = github.calls[first:]
    assert sorted(again) == ["repos/o/r/commits/refs/pull/1/head/status", "repos/o/r/commits/s1/check-runs"]


def _search_page(numbers, agent="x"):
    return {"items": [dict(item("acme", "bot"), number=n, body="All tests pass.", created_at="2026-10-01T00:00:00Z") for n in numbers]}


def test_a_search_that_runs_out_of_time_keeps_what_the_others_found_and_the_gate_holds_it_back(github, monkeypatch, tmp_path):
    def search(path, params=None, kind="core", max_age=None):
        if "codex" in params["q"]:
            raise agent_pr_ci.OutOfTime()
        return {"ok": True, "json": _search_page([1, 2] if "copilot" in params["q"] else [])}
    monkeypatch.setattr(agent_pr_ci, "gh_get", lambda path, params=None, kind="core", max_age=None:
                        search(path, params, kind) if kind == "search" else fake_gh(path, params, kind))
    monkeypatch.setattr(agent_pr_ci, "AGENTS", [("copilot", "author:app/copilot"), ("codex", "codex in:body")])
    got = agent_pr_index.scan("2026-10-01", 3, 10, 10_000)
    assert got["unfinished_search"] == ["codex"] and got["kept"] == 2 and got["unread"] == 0
    assert sorted(r["number"] for r in got["rows"]) == [1, 2]              # Copilot's rows are not thrown away
    index = agent_pr_index.build(got["rows"], "2026-10-02", got["window"], got["counts"]["excluded"])
    why = agent_pr_index.gate(got, index)
    assert len(why) == 1 and "did not finish for codex" in why[0] and "the next run continues" in why[0]
    assert agent_pr_index.errors(got, index) == []                         # out of time is not an error
    # the same through the command the workflow runs: it publishes nothing, exits 0 and says why in a note
    (tmp_path / "rows.json").write_text(json.dumps(got), encoding="utf-8")
    (tmp_path / "index.json").write_text(json.dumps(index), encoding="utf-8")
    cli = [sys.executable, str(ROOT / "scripts" / "agent_pr_index.py"), "gate", "--rows", str(tmp_path / "rows.json"),
           "--out", str(tmp_path / "index.json"), "--previous", str(tmp_path / "none.json")]
    env = {**os.environ, "GITHUB_OUTPUT": str(tmp_path / "out.txt")}
    r = subprocess.run(cli, capture_output=True, text=True, encoding="utf-8", check=False, env=env)
    assert r.returncode == 0 and "not published: the search did not finish for codex" in r.stderr
    assert "::notice title=Agent PR Index not published yet::" in r.stdout
    assert (tmp_path / "out.txt").read_text(encoding="utf-8") == "publish=false\n"
    got["unfinished_search"] = []
    (tmp_path / "rows.json").write_text(json.dumps(got), encoding="utf-8")
    r = subprocess.run(cli, capture_output=True, text=True, encoding="utf-8", check=False, env=env)
    assert r.returncode == 0 and "publish it" in r.stderr
    assert (tmp_path / "out.txt").read_text(encoding="utf-8") == "publish=false\npublish=true\n"
    # a query GitHub refuses for itself is a real error: the run fails
    got["search_errors"], got["unfinished_search"] = ["codex: gh: Validation Failed (HTTP 422)"], ["codex"]
    (tmp_path / "rows.json").write_text(json.dumps(got), encoding="utf-8")
    r = subprocess.run(cli, capture_output=True, text=True, encoding="utf-8", check=False, env=env)
    assert r.returncode == 1 and "error: GitHub refused the search query itself for codex" in r.stderr


def test_the_gate_publishes_a_finished_scan_and_names_what_an_unfinished_one_lacks():
    rows = [{"agent": "codex", "repo": f"o/r{n}", "number": n, "sha": "a" * 40, "class": "passed", "failed_checks": [], "phrase": "p"}
            for n in range(100)]
    index = agent_pr_index.build(rows, "2026-10-02", ("a", "b"))
    scanned = {"rows": rows, "kept": 100, "unread": 0, "unfinished_search": []}
    assert agent_pr_index.gate(scanned, index) == []
    assert agent_pr_index.gate(scanned, index, {"n_prs": 180}) == []                      # a smaller index is still an index
    assert agent_pr_index.gate({**scanned, "unread": 2}, index) == []                     # GitHub may fail to answer for a few
    [why] = agent_pr_index.gate({**scanned, "kept": 150, "unread": 50}, index)
    assert "did not answer for 50 of the 150" in why and "the next run continues" in why and "KNOS_INDEX_TOKEN" in why
    [why] = agent_pr_index.gate(scanned, index, {"n_prs": 2431})
    assert "100 pull requests, under half of the last index's 2,431" in why
    empty = agent_pr_index.build([], "2026-10-02", ("a", "b"))
    assert any("no pull request with finished CI" in w for w in agent_pr_index.gate({"rows": [], "kept": 0, "unread": 0}, empty))


def test_pull_requests_github_did_not_answer_for_are_counted_as_unread(github, monkeypatch):
    def answer(path, params=None, kind="core", max_age=None):
        if kind == "search":
            return {"ok": True, "json": _search_page([1, 2, 3] if "copilot" in params["q"] else [])}
        if "/pull/2/" in path:
            raise agent_pr_ci.OutOfTime()
        if "/pull/3/" in path:
            return {"ok": False, "error": "gh: Bad Gateway (HTTP 502)", "transient": True}
        return fake_gh(path, params, kind)
    monkeypatch.setattr(agent_pr_ci, "gh_get", answer)
    monkeypatch.setattr(agent_pr_ci, "AGENTS", [("copilot", "author:app/copilot")])
    got = agent_pr_index.scan("2026-10-01", 1, 10, 10_000)
    assert got["kept"] == 3 and got["unread"] == 2 and [r["number"] for r in got["rows"]] == [1]
    assert got["unfinished_search"] == []


def test_answers_about_pull_requests_that_left_the_window_are_forgotten(github, tmp_path):
    status = "repos/o/r/commits/refs/pull/1/head/status"
    github.script[status] = [{"sha": "abc", "statuses": []}]
    agent_pr_ci.gh_get(status)
    [kept] = list((tmp_path / "cache" / "core").rglob("*.json"))
    assert agent_pr_ci.prune(127) == 0 and kept.exists()
    long_ago = time.time() - 128 * 86400
    os.utime(kept, (long_ago, long_ago))
    assert agent_pr_ci.prune(127) == 1 and not kept.exists()


def test_the_scheduled_run_publishes_waits_with_a_note_or_fails_and_keeps_its_answers_either_way():
    yaml = pytest.importorskip("yaml")
    doc = yaml.safe_load((ROOT / ".github" / "workflows" / "index.yml").read_text(encoding="utf-8"))
    assert doc[True]["schedule"] == [{"cron": "17 */6 * * *"}, {"cron": "43 7,9 * * 1"}]   # `on`: every 6 hours, as the docs say; Mondays, twice, for the week
    assert doc["jobs"]["index"]["timeout-minutes"] < 30 and "github.event.schedule == '17 */6 * * *'" in doc["jobs"]["index"]["if"]
    steps = doc["jobs"]["index"]["steps"]
    runs = [str(s.get("run", "")) for s in steps]
    scan = next(i for i, r in enumerate(runs) if "agent_pr_index.py scan" in r)
    gate = next(i for i, r in enumerate(runs) if "agent_pr_index.py gate" in r)
    release = next(i for i, r in enumerate(runs) if "gh release create" in r)
    save = next(i for i, s in enumerate(steps) if str(s.get("uses", "")).startswith("actions/cache/save@"))
    restore = next(i for i, s in enumerate(steps) if str(s.get("uses", "")).startswith("actions/cache/restore@"))
    previous = next(i for i, r in enumerate(runs) if "-O previous.json" in r)
    pages = next(i for i, r in enumerate(runs) if "gh workflow run network.yml" in r)
    assert restore < previous < scan < save < gate < release < pages
    assert steps[save]["if"] == "always()"                                    # a run that stops early still leaves its answers
    assert steps[save]["with"]["path"] == steps[restore]["with"]["path"] == "~/.cache/knos-agent-pr-ci"
    assert not any(str(s.get("uses", "")).startswith("actions/cache@") for s in steps)    # that one saves only on success
    # the scan takes what the last index counted, and stops 200 short of this hour's budget
    assert "--previous previous.json" in runs[scan] and "--reserve 200" in runs[scan]
    # only the gate decides to publish nothing, and it says so (its note: test above); nothing else is skipped quietly
    for r in runs:
        assert "exit 0" not in r and "|| true" not in r, r
    assert "if" not in steps[gate] and steps[gate]["id"] == "gate" and "continue-on-error" not in json.dumps(steps)
    assert steps[release]["if"] == steps[pages]["if"] == "steps.gate.outputs.publish == 'true'"
    assert [i for i, s in enumerate(steps) if "if" in s] == [save, release, pages]
    # and the gate asks for nothing the scan cannot reach: before, 480 an agent could keep 2,400 and 2,000 had to have
    # finished CI; now the floor is half the last index (1,216 after the 2,431 one) and the scan may keep 4,000
    per_agent = int(runs[scan].split("--per-agent")[1].split()[0])
    # one run reads for 20 minutes at most, and its steps together fit the job's limit
    assert sum(int(r.split("--max-seconds")[1].split()[0]) for r in runs if "--max-seconds" in r) <= (doc["jobs"]["index"]["timeout-minutes"] - 5) * 60
    assert per_agent * len(agent_pr_ci.AGENTS) >= 3 * agent_pr_index.MIN_OF_PREVIOUS * 2431


UNTICKED = ("- [ ] All tests pass", "* [ ] CI is green", "+ [ ] 801 passed", "1. [ ] tests pass", "2) [ ] all checks pass",
            "> - [ ] tests pass", "  - [ ] tests pass", "1. - [ ] tests pass")
HEDGED = ("All tests should pass.", "Please make sure CI is green.", "Please ensure the tests pass.", "TODO: make tests pass",
          "Tests must pass before merging.", "The tests do not pass.", "Tests don't pass yet.", "If 801 passed, merge it.")


def test_an_unticked_box_of_any_list_marker_claims_nothing_and_ticked_it_is_a_claim():
    """GitHub makes a task-list box of -, *, + or a number, nested or quoted. Unticked, the author asserted nothing;
    the index skipped only "- [ ]", while `knos check` skipped them all."""
    from knos.proof import claims
    for box in UNTICKED:
        assert agent_pr_ci.find_claim(box) == (None, None), box
        assert agent_pr_ci.find_claim(box.replace("[ ]", "[x]"))[0], box
        assert not claims.read(box).kinds and claims.read(box.replace("[ ]", "[x]")).kinds & {"tests", "ci"}, box
    for hedged in HEDGED:
        assert agent_pr_ci.find_claim(hedged) == (None, None) and not claims.read(hedged).kinds & {"tests", "ci"}, hedged


def test_the_command_line_reads_what_claims_nothing_in_the_index_s_words():
    """src/knos/proof/claims.py (`knos check`, the gate, knos_check_pr) sets a sentence aside with the index's own
    patterns: its box, its hedges and its boilerplate."""
    from knos.proof import claims
    assert agent_pr_ci.NONCLAIM_RE.pattern == claims._BOX + r"(?:[ \t]|$)|" + claims._HEDGE.pattern
    assert agent_pr_ci._BOILER_RE.pattern == claims._BOILER.pattern
    assert agent_pr_ci.NONCLAIM_RE.flags & re.I and claims._HEDGE.flags & re.I and claims._BOILER.flags & re.I


@pytest.mark.skipif(not shutil.which("node"), reason="needs node")
def test_the_sites_copy_of_the_claim_reader_is_the_index_s():
    """web/front.js is a copy of agent_pr_ci's reader, so that the site and the index agree on a pull request: the same
    three patterns, and the same answer for each body."""
    bodies = [*UNTICKED, *(b.replace("[ ]", "[x]") for b in UNTICKED), *HEDGED, *(f["claim_line"] for f in fixtures()),
              "Please make sure tests pass before merging", "- [x] My PR passes all CI/CD checks (e.g., lint, format, unit tests)",
              "- [x] Local tests pass. **Your PR cannot be merged unless tests pass**", "504 passed, 0 failed.",
              "<!-- make sure all tests pass -->\nRefactor.", "Done; `npm test` passes", "CI is green ✅", "Tests pass. I did not touch the docs."]
    js = ('import { findClaim, CLAIM_RE, NONCLAIM_RE, BOILER_RE } from "./web/front.js";\n'
          f"const bodies = {json.dumps(bodies)};\n"
          "console.log(JSON.stringify({found: bodies.map((b) => { const c = findClaim(b); return c ? [c.phrase, c.line] : [null, null]; }),\n"
          "  claim: CLAIM_RE.source, nonclaim: NONCLAIM_RE.source, boiler: BOILER_RE.source, flags: [CLAIM_RE.flags, NONCLAIM_RE.flags]}));\n")
    r = subprocess.run(["node", "--input-type=module", "-e", js], cwd=str(ROOT), capture_output=True, text=True,
                       encoding="utf-8", check=False)
    assert r.returncode == 0, r.stderr
    got = json.loads(r.stdout)
    assert got["claim"].replace("\\/", "/") == agent_pr_ci.CLAIM_RE.pattern
    assert got["nonclaim"] == agent_pr_ci.NONCLAIM_RE.pattern and got["boiler"] == agent_pr_ci._BOILER_RE.pattern
    assert got["flags"] == ["i", "i"]
    assert got["found"] == [list(agent_pr_ci.find_claim(b)) for b in bodies]


@pytest.mark.skipif(not shutil.which("node"), reason="needs node")
def test_the_site_shows_both_counts_and_still_reads_an_index_published_before_they_had_names():
    bench = json.loads((ROOT / "docs" / "bench.json").read_text(encoding="utf-8"))["market"]["index"]
    new = {"date": "2026-10-02", "excluded_self_repo": 9207, "agents": {"copilot": bench["agents"][0][1]}}
    old = {"date": "2026-10-02", "excluded_self_repo": 9207, "agents": {"copilot": {
        "claimed_green": 787, "actually_failed": 194, "share": 0.2465, "ci95": [0.2177, 0.2778], "proven": 0}}}
    js = ('import { agentRecord } from "./web/front.js";\n'
          f"const out = [{json.dumps(new)}, {json.dumps(old)}].map((ix) => agentRecord(ix, 'copilot').replace(/<[^>]+>/g, '').replace(/\\s+/g, ' '));\n"
          "console.log(JSON.stringify(out));\n")
    r = subprocess.run(["node", "--input-type=module", "-e", js], cwd=str(ROOT), capture_output=True, text=True,
                       encoding="utf-8", check=False)
    assert r.returncode == 0, r.stderr
    now, before = json.loads(r.stdout)
    assert "in 341 repositories, its first pull request that said tests pass had a failing check of any kind in 85 (24.9%, 95% interval 20.6%–29.8%)" in now
    assert "In 46 of the 341 repositories (13.5%) a failed check was a test or a build, by its name." in now
    assert "Counting every such pull request: 194 of 787 (24.7%)." in now
    assert "said tests pass on 787 pull requests with finished CI; a check of any kind had failed on 194 (24.7%, 95% interval 21.8%–27.8%)." in before
    assert "test or a build" not in before                                    # that index did not publish the second count


# ---- by agent and by week (docs/agent_weekly.json, docs/INDEX.md) -------------------------------------------------

def _row(agent, n, day, cls, merged=None, failed=()):
    return {"agent": agent, "repo": f"o/r{n}", "number": n, "created_at": f"{day}T12:00:00Z", "class": cls,
            "failed_checks": list(failed), **({} if merged is None else {"merged": merged})}


WEEK_ROWS = [_row("copilot", 1, "2026-09-21", "failed", True, ["build"]),      # a Monday
             _row("copilot", 2, "2026-09-27", "passed", True),                 # the Sunday of the same week
             _row("copilot", 3, "2026-09-27", "failed", False, ["vercel"]),
             _row("copilot", 4, "2026-09-27", "pending", False),               # claimed; CI not finished
             _row("copilot", 5, "2026-09-28", "passed", True),                 # the next week
             _row("devin", 6, "2026-09-23", "failed")]                         # merge state not read


def test_the_weekly_series_counts_each_agent_by_the_week_a_pull_request_was_opened():
    assert agent_pr_index.week_of("2026-09-27T23:59:59Z") == "2026-09-21" and agent_pr_index.week_of("2026-09-28T00:00:00Z") == "2026-09-28"
    got = agent_pr_index.weekly(WEEK_ROWS, WINDOW, "2026-10-02", "a test", [["copilot", "2026-09-22T01:00:00Z"], ["codex", "2026-09-29T01:00:00Z"]])
    first, second = got["agents"]["copilot"]["weeks"]
    how = {"design": "newest-first-capped-v0", "capped": True, "strata": None, "not_derived": {"strata": agent_pr_index.NO_STRATA}, "ranked_by": "verified_acceptance_rate"}
    assert first == {"week": "2026-09-21", "read": "2026-10-02", "full_week": False, "verified": 0, "rank": None, "sampled": 5, "claimed_passing": 4, "ci_finished": 3, **how,
                     "checks": {"passed": 1, "failed": 2, "other": 0, "pending": 1, "no_checks": 0, "not_read": 0},
                     "verified_acceptance_rate": {"k": 1, "n": 4, "share": 0.25, "ci95": agent_pr_index.wilson(1, 4)},     # pending when read: not verified
                     "failed_a_check": {"k": 2, "n": 3, "share": 0.6667, "ci95": agent_pr_index.wilson(2, 3), "test_or_build": 1},
                     "merged_despite_failed_check": {"k": 1, "n": 2, "share": 0.5, "ci95": agent_pr_index.wilson(1, 2)}}
    assert second["week"] == "2026-09-28" and second["sampled"] == 1 and second["failed_a_check"]["k"] == 0
    assert got["agents"]["copilot"]["all_weeks"]["failed_a_check"]["n"] == 4
    assert got["agents"]["devin"]["weeks"][0]["merged_despite_failed_check"] is None      # not read is null, never 0
    assert got["agents"]["codex"]["weeks"] == [{"week": "2026-09-28", "read": "2026-10-02", "full_week": False, "verified": 0, "rank": None, "sampled": 1, "claimed_passing": 0, "ci_finished": 0, **how,
                                                "checks": {k: 0 for k in agent_pr_index.CHECKS}, "verified_acceptance_rate": {"k": 0, "n": 0, "share": None, "ci95": None},
                                                "failed_a_check": {"k": 0, "n": 0, "share": None, "ci95": None, "test_or_build": 0},
                                                "merged_despite_failed_check": None}]
    assert agent_pr_index.weekly(WEEK_ROWS, WINDOW, "d", "s")["agents"]["copilot"]["weeks"][0]["sampled"] is None   # hits set aside not kept
    assert agent_pr_index.weekly(WEEK_ROWS[::-1], WINDOW, "2026-10-02", "a test", [["codex", "2026-09-29T01:00:00Z"], ["copilot", "2026-09-22T01:00:00Z"]]) == got
    assert set(got["definitions"]) >= {"sampled", "claimed_passing", "failed_a_check", "merged_despite_failed_check"} and len(got["limits"]) >= 3


def test_the_merge_state_is_asked_of_github_and_an_unanswered_one_stays_unknown(monkeypatch):
    asked = []

    def gh(path, params=None, kind="core", max_age=None):
        asked.append(path)
        return {"ok": False, "error": "HTTP 502"} if path.endswith("/3") else {"ok": True, "json": {"merged": path.endswith("/1")}}
    monkeypatch.setattr(agent_pr_ci, "gh_get", gh)
    rows = agent_pr_index.read_merged([_row("codex", 1, "2026-09-22", "failed"), _row("codex", 2, "2026-09-22", "passed", False),
                                       _row("codex", 3, "2026-09-22", "passed"), _row("codex", 4, "2026-09-22", "pending")])
    assert asked == ["repos/o/r1/pulls/1", "repos/o/r3/pulls/3"]                 # not the one already known, not unfinished CI
    assert rows[0]["merged"] is True and "merged" not in rows[2]
    assert agent_pr_index.weekly(rows, WINDOW, "d", "s")["agents"]["codex"]["weeks"][0]["merged_despite_failed_check"] is None


def test_a_scan_keeps_when_the_hits_it_set_aside_were_opened(monkeypatch):
    item = lambda n, body: {"repository_url": "https://api.github.com/repos/o/r", "number": n, "body": body,  # noqa: E731
                            "user": {"login": "bot", "type": "Bot"}, "created_at": f"2026-09-2{n}T00:00:00Z", "assignees": []}
    pages = iter([{"ok": True, "json": {"items": [item(1, "All tests pass."), item(2, "Please make sure tests pass")]}}])
    monkeypatch.setattr(agent_pr_ci, "gh_get", lambda *a, **k: next(pages, {"ok": True, "json": {"items": []}}))
    monkeypatch.setattr(agent_pr_ci, "NO_CLAIM", [])
    kept, n, finished = agent_pr_ci.scan_agent("codex", "x", "2026-09-30", 10, 5)
    assert [c["number"] for c in kept] == [1] and finished and agent_pr_ci.NO_CLAIM == [["codex", "2026-09-22T00:00:00Z"]]


# What 0.3.15 published for the weeks of 21 and 28 September (read 2026-10-05, a capped scan), as the release left it:
# sampled, claimed passing, CI finished, failed a check, merged despite a failed check, place. The file must keep them.
PUBLISHED_0315 = {"copilot": {"2026-09-21": (121, 39, 35, 7, 4, 1), "2026-09-28": (169, 66, 58, 13, 12, 3)}, "devin": {"2026-09-28": (140, 120, 109, 70, 2, 4)}, "claude-bot": {"2026-09-28": (242, 120, 115, 13, 10, 1)}, "claude-code": {"2026-09-28": (423, 120, 102, 13, 6, 2)}, "codex": {"2026-09-21": (3, 0, 0, 0, None, None), "2026-09-28": (83, 2, 2, 0, 0, None)}}


def test_the_committed_weekly_file_is_the_committed_sample_cut_by_week_and_the_page_shows_its_table(tmp_path):
    """Nothing in docs/agent_weekly.json is typed by hand: it is docs/agent_pr_ci.json reshaped, with the weeks a later
    scan read put in by the script in place of the sample's (each says the day it was read, and whether that was the
    whole week), and docs/INDEX.md holds exactly the table the script renders from it, and says what the numbers
    cannot say."""
    out, doc = tmp_path / "weekly.json", tmp_path / "INDEX.md"
    doc.write_text((ROOT / "docs" / "INDEX.md").read_text(encoding="utf-8"), encoding="utf-8")
    assert subprocess.run([sys.executable, str(ROOT / "scripts" / "agent_pr_index.py"), "weekly", "--sample", "docs/agent_pr_ci.json",
                           "--out", str(out), "--doc", str(doc)], cwd=ROOT, capture_output=True, text=True).returncode == 0
    reshaped = json.loads(out.read_text(encoding="utf-8"))
    series = json.loads((ROOT / "docs" / "agent_weekly.json").read_text(encoding="utf-8"))
    page = (ROOT / "docs" / "INDEX.md").read_text(encoding="utf-8")
    assert agent_pr_index.weekly_table(series) in page
    sample = json.loads((ROOT / "docs" / "agent_pr_ci.json").read_text(encoding="utf-8"))
    assert reshaped["read"] == sample["generated_utc"][:10] and "nothing was read again" in reshaped["source"]
    for name, agent in reshaped["agents"].items():
        s = sample["summary"][name]
        assert agent["all_weeks"]["claimed_passing"] == s["N"] == sum(w["claimed_passing"] for w in agent["weeks"])
        assert all(w["rank"] is None and w["verified"] == 0 for w in agent["weeks"])   # nobody has 30 claims in a week of this sample
        assert all(w["design"] == "search-window-sample-v0" and w["capped"] is True and w["verified_acceptance_rate"]["n"] == w["claimed_passing"] for w in agent["weeks"])
        assert agent["all_weeks"]["failed_a_check"] == {"k": s["failed"], "n": s["with_completed_ci"], "share": s["share_failed_among_completed_ci"],
                                                        "ci95": agent_pr_index.wilson(s["failed"], s["with_completed_ci"]), "test_or_build": s["failed_testish"]}
        assert all(w["sampled"] is None for w in agent["weeks"])                 # the sample kept no date for the hits it set aside
    # the committed series: every week the sample has and no later scan read is the sample's, as reshaped; the weeks
    # read later carry their own day, and the sums are the weeks added up
    later = {w["week"] for a in series["agents"].values() for w in a["weeks"] if w["read"] != reshaped["read"]}
    assert set(series["agents"]) == set(reshaped["agents"]) and series["read"] >= reshaped["read"]
    for name, agent in series["agents"].items():
        old = {w["week"]: w for w in reshaped["agents"][name]["weeks"]}
        new = {w["week"]: w for w in agent["weeks"]}
        assert {k: v for k, v in new.items() if k not in later} == {k: v for k, v in old.items() if k not in later}
        assert all(w["read"] > reshaped["read"] and isinstance(w["full_week"], bool) for k, w in new.items() if k in later)
        assert agent["all_weeks"] == agent_pr_index._add(agent["weeks"])
    if later:
        assert ("not whole weeks" in series["source"]) == any(not w["full_week"] for a in series["agents"].values() for w in a["weeks"] if w["week"] in later)
    assert series["name"] == "Agent PR Index" and series["latest_week"] == "2026-09-28" and "**Agent PR Index, week of 2026-09-28.**" in page
    # the two weeks read on 2026-10-05 keep every number they were published with (0.3.15), and say what cannot be derived
    for name, was in PUBLISHED_0315.items():
        for week, (sampled, claimed, finished, failed, merged, place) in was.items():
            w = next(w for w in series["agents"][name]["weeks"] if w["week"] == week)
            if w["design"] == agent_pr_index.DESIGN:     # read again with the design since: the newer reading replaced the week (weekly --into)
                assert w["read"] >= "2026-10-05" and len(w["strata"]) == 7 and w["verified_acceptance_rate"] is not None and w["capped"] is not None
                continue
            assert (w["sampled"], w["claimed_passing"], w["ci_finished"], w["failed_a_check"]["k"], (w["merged_despite_failed_check"] or {}).get("k"), w["rank"]) == (sampled, claimed, finished, failed, merged, place)
            assert w["read"] == "2026-10-05" and w["design"] == "newest-first-capped-v0" and w["capped"] is True and w["ranked_by"] == "failed_a_check"
            assert w["verified_acceptance_rate"] is None and w["checks"] is None and w["strata"] is None
            assert set(w["not_derived"]) == {"verified_acceptance_rate", "checks", "strata"} and "were not kept" in w["not_derived"]["verified_acceptance_rate"]
            assert agent_pr_index.with_new_fields(w) is w                       # written once: a second pass changes nothing
    assert sum(c for was in PUBLISHED_0315.values() for _, c, *_ in was.values()) == 467      # the capped sample of 467
    assert set(series["designs"]) >= {w["design"] for a in series["agents"].values() for w in a["weeks"]} | {agent_pr_index.DESIGN}
    devin = next(w for w in series["agents"]["devin"]["weeks"] if w["week"] == "2026-09-28")
    if devin["design"] == "newest-first-capped-v0":
        assert "Capped: true" in page and "| not ranked: rate not recorded | devin | not recorded | 140 | 120 | 70 of 109 (64.2%;" in page
    else:   # the page says what the week's reading says: capped, with what was drawn, or read whole
        assert (f"Capped: {'true' if devin['capped'] else 'false'}." in page) and (("| capped: drew " in page) == bool(devin["capped"]))
    again = tmp_path / "again.json"
    again.write_text(json.dumps(series), encoding="utf-8")                   # the format is the script's: restating the file changes nothing
    assert subprocess.run([sys.executable, str(ROOT / "scripts" / "agent_pr_index.py"), "weekly", "--sample", "docs/agent_pr_ci.json", "--restate", str(again)],
                          cwd=ROOT, capture_output=True, text=True, encoding="utf-8").returncode == 0 and json.loads(again.read_text(encoding="utf-8")) == series
    assert set(series["heuristics"]) == set(series["agents"])
    for words in ("Bot-author heuristics", "Public repositories only", "One snapshot of the checks", "Wilson", "not proof that the claim was false",
                  "30 requests a minute", "1,000 results", "docs.github.com/en/rest/search/search", "statusCheckRollup", "--max-requests", "--max-minutes",
                  "sha256(", "day of the week", "never charges an agent vendor for its rating", "cannot pay to change it", "too few to rank",
                  "docs.github.com/en/graphql/overview/rate-limits-and-query-limits-for-the-graphql-api"):
        assert words in page
    with pytest.raises(SystemExit):
        (tmp_path / "bare.md").write_text("no markers", encoding="utf-8")
        agent_pr_index.render_doc(str(tmp_path / "bare.md"), series)


def test_a_capped_sample_replaces_the_older_sample_of_its_weeks_and_never_a_week_read_whole(tmp_path):
    """`weekly --add-sample`: the weeks of a capped scan go into the published series marked as not read whole; a week
    the weekly run read whole stays, the weeks the scan does not have stay, and a scan that did not finish is refused."""
    base = agent_pr_index.weekly(WEEK_ROWS, WINDOW, "2026-10-01", "the sample")
    base["agents"]["copilot"]["weeks"][1]["full_week"] = True                # 2026-09-28: as if read whole
    fresh_rows = [_row("copilot", 7, "2026-09-22", "failed", True, ["test"]), _row("copilot", 8, "2026-09-29", "passed", True),
                  _row("devin", 9, "2026-09-24", "passed", False)]
    fresh = agent_pr_index.weekly(fresh_rows, ["2026-09-21", "2026-10-04"], "2026-10-05", "a capped scan", [])
    got = agent_pr_index.add_sample(json.loads(json.dumps(base)), fresh)
    copilot = {w["week"]: w for w in got["agents"]["copilot"]["weeks"]}
    assert copilot["2026-09-21"]["read"] == "2026-10-05" and copilot["2026-09-21"]["full_week"] is False and copilot["2026-09-21"]["claimed_passing"] == 1
    assert copilot["2026-09-28"] == base["agents"]["copilot"]["weeks"][1]     # read whole: kept
    assert got["agents"]["copilot"]["all_weeks"] == agent_pr_index._add(got["agents"]["copilot"]["weeks"])
    assert got["window"] == ["2026-09-21", "2026-10-04"] and got["read"] == "2026-10-05" and "not whole weeks" in got["source"]
    rows = tmp_path / "rows.json"
    rows.write_text(json.dumps({"window": ["2026-09-21", "2026-10-04"], "kept": 3, "unread": 0, "unfinished_search": ["codex"],
                                "no_claim": [], "rows": fresh_rows}), encoding="utf-8")
    into = tmp_path / "series.json"
    into.write_text(json.dumps(base), encoding="utf-8")
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "agent_pr_index.py"), "weekly", "--rows", str(rows), "--add-sample", str(into)],
                       capture_output=True, text=True, check=False, env={**os.environ, "GH_TOKEN": "", "PATH": ""})
    assert r.returncode == 1 and "the search did not finish for codex" in r.stderr and json.loads(into.read_text(encoding="utf-8")) == base


def test_the_weekly_job_opens_a_pull_request_and_merges_nothing_and_the_job_that_reads_can_only_read():
    yaml = pytest.importorskip("yaml")
    doc = yaml.safe_load((ROOT / ".github" / "workflows" / "index.yml").read_text(encoding="utf-8"))
    week, job = doc["jobs"]["week"], doc["jobs"]["weekly"]
    assert "github.event.schedule == '43 7,9 * * 1'" in week["if"] and "needs" not in week      # weekly, and behind no other job
    assert doc["permissions"] == {"contents": "read"} and week["permissions"] == {"contents": "read"}   # the token that reads public GitHub cannot write
    read = "\n".join(str(s.get("run", "")) for s in week["steps"])
    assert read.strip() == "python scripts/agent_pr_index.py sample --week last --rows week.json --max-requests 500 --max-minutes 50"   # the only command: API reads
    assert not any(w in read for w in ("git clone", "pip install", "npm ", "curl ", "gh pr checkout"))
    # inside the limits: the budget is the script's default, the searches are under 30 a minute, and the whole run inside the hour
    assert (agent_pr_index.MAX_REQUESTS, agent_pr_index.MAX_MINUTES) == (500, 50)
    assert 60 / agent_pr_index.SEARCH_PAUSE < 28 and 35 * 10 * agent_pr_index.SEARCH_PAUSE < agent_pr_index.MAX_MINUTES * 60   # under 30 searches a minute, and the whole design fits
    pace = 0.8 * agent_pr_index.MAX_MINUTES * 60 / agent_pr_index.MAX_REQUESTS      # what `sample` spreads its requests by when --pace is not given
    assert 60 / pace < 15 and agent_pr_index.MAX_REQUESTS * pace <= agent_pr_index.MAX_MINUTES * 60 and "--no-wait" not in read and "--pace" not in read
    assert agent_pr_index.MAX_MINUTES < week["timeout-minutes"] < 60 and job["timeout-minutes"] <= 5
    # it starts after the six-hourly index job has ended, so the two do not spend the same hour of the token's budget
    assert doc["jobs"]["index"]["timeout-minutes"] + 17 < 43 + 60 and doc["concurrency"] == {"group": "agent-pr-index", "cancel-in-progress": False}
    restore = next(s for s in week["steps"] if str(s.get("uses", "")).startswith("actions/cache/restore@"))
    save = next(s for s in week["steps"] if str(s.get("uses", "")).startswith("actions/cache/save@"))
    upload = next(s for s in week["steps"] if str(s.get("uses", "")).startswith("actions/upload-artifact@"))
    assert save["if"] == upload["if"] == "always()" and restore["with"]["path"] == save["with"]["path"] == upload["with"]["path"] == "week.json"   # a cut run leaves its checkpoint
    assert all("@" in s["uses"] and len(s["uses"].split("@")[1]) == 40 for j in (week, job) for s in j["steps"] if "uses" in s)
    assert job["needs"] == "week" and "always()" in job["if"] and "success" not in job["if"]           # a capped or cut week is published all the same
    runs = "\n".join(str(s.get("run", "")) for s in job["steps"])
    assert "agent_pr_index.py weekly --rows week.json --into docs/agent_weekly.json --doc docs/INDEX.md" in runs
    assert runs.index("agent_pr_index.py weekly") < runs.index("agent_pr_index.py board\n") < runs.index("git commit")      # the leaderboard and its feeds, from the new week
    assert "git commit -m \"Agent PR Index, week of $week\" -- docs/agent_weekly.json docs/INDEX.md docs/index.json docs/index.atom" in runs
    assert runs.count("gh pr create") == 1 and "gh pr merge" not in runs and "Agent PR Index, week of $week" in runs
    assert "origin main" not in runs and "git push --force origin index-weekly" in runs and runs.count("git push") == 1       # one branch, never the default one
    assert job["permissions"] == {"contents": "write", "pull-requests": "write"}
    index = "\n".join(str(s.get("run", "")) for s in doc["jobs"]["index"]["steps"])
    assert "agent_pr_index.py weekly --rows rows.json --out agent_weekly.json" in index and "index.json agent_weekly.json" in index


# ---- one whole week, read against a GitHub that answers from a table (no network) -----------------------------------

PER_DAY = {"copilot": 12, "devin": 6, "claude-bot": 0, "claude-code": 3, "codex": 1}
BUSY = ("devin", "2026-09-30")          # a day GitHub says holds more than 1,000: it must be asked in halves


def _week_api(asked):
    """GitHub for the week of 2026-09-28. A search hit's number says everything about it: every third one claims
    nothing, every fourth has a failed build, even ones were merged. Nothing here is a measured number."""
    def hit(agent, n, at):
        return {"repository_url": f"https://api.github.com/repos/acme/{agent}", "number": n, "user": {"login": f"{agent}[bot]"},
                "assignees": [], "created_at": at, "body": "Please make sure tests pass" if n % 3 == 0 else "All tests pass."}

    def gh(path, params=None, kind="core", max_age=None):
        asked.append((kind, path, dict(params or {})))
        if kind == "search":
            q = params["q"]
            agent = next(a for a, qual in agent_pr_ci.AGENTS if f"is:pr {qual} created:" in q)
            span = q.split("created:")[1].split()[0]
            lo, hi = span.split("..")
            day = int(lo[8:10])
            if (agent, lo[:10]) == BUSY and "T" not in lo:
                return {"ok": True, "json": {"total_count": 1500, "items": [hit(agent, 9000 + i, f"{lo}T23:00:00Z") for i in range(100)]}}
            if (agent, lo[:10]) == BUSY:          # a half: 2 hits in the morning, 4 in the afternoon
                first = lo[11:13] == "00"
                return {"ok": True, "json": {"total_count": 2 if first else 4,
                                             "items": [hit(agent, day * 100 + i, f"{lo[:10]}T{'03' if first else '15'}:00:00Z") for i in (range(2) if first else range(2, 6))]}}
            return {"ok": True, "json": {"total_count": PER_DAY[agent], "items": [hit(agent, day * 100 + i, f"{lo}T12:00:00Z") for i in range(PER_DAY[agent])]}}
        n = int(path.split("/pull/")[1].split("/")[0]) if "/refs/pull/" in path else int(path.rstrip("/").split("/")[-1].lstrip("s")) if not path.endswith(("check-runs", "check-suites")) else int(path.split("/commits/s")[1].split("/")[0])
        if "/refs/pull/" in path:
            return {"ok": True, "json": {"sha": f"s{n}", "statuses": []}}
        if path.endswith("check-runs"):
            return {"ok": True, "json": {"check_runs": [{"name": "build", "status": "completed", "conclusion": "failure" if n % 4 == 0 else "success"}]}}
        if "/pulls/" in path:
            return {"ok": True, "json": {"merged": n % 2 == 0}}
        return {"ok": True, "json": {"check_suites": []}}
    return gh


def test_one_whole_week_is_read_day_by_day_past_the_cap_and_added_to_the_published_series(monkeypatch, tmp_path):
    asked = []
    monkeypatch.setattr(agent_pr_ci, "gh_get", _week_api(asked))
    monkeypatch.setattr(agent_pr_ci, "CACHE", str(tmp_path / "cache"))
    got = agent_pr_index.scan_week("2026-09-28", 10_000, read="2026-10-05")
    searches = [p["q"] for kind, _, p in asked if kind == "search"]
    assert len(searches) == 5 * 7 + 2 and all("2026-09-2" in q or "2026-09-30" in q or "2026-10-0" in q for q in searches)   # agents x days, and two halves
    assert sum("created:2026-09-30T12:00:00Z..2026-09-30T23:59:59Z" in q for q in searches) == 1 and sum("created:2026-09-30T00:00:00Z..2026-09-30T11:59:59Z" in q for q in searches) == 1
    assert not any(r["number"] >= 9000 for r in got["rows"])               # the capped page of the busy day is not counted: its halves are
    assert {path.split("/")[0] for _, path, _ in asked} == {"search", "repos"}   # API reads of search, statuses, check runs and pull requests: nothing else
    assert not any(w in path for _, path, _ in asked for w in ("/contents", "/git/", "/zipball", "/tarball", "/actions/"))
    assert got["week"] == "2026-09-28" and got["window"] == ["2026-09-28", "2026-10-04"] and not got["unfinished_search"] and not got["unread"]
    assert got["counts"]["capped"] == 0 and len(got["no_claim"]) + got["kept"] == got["counts"]["hits"] == 7 * (12 + 3 + 1) + 6 * 6 + 6
    assert agent_pr_index.week_gaps(got) == []
    with pytest.raises(SystemExit, match="not a Monday"):
        agent_pr_index.scan_week("2026-09-29", 10)
    assert agent_pr_index.last_week(__import__("datetime").date(2026, 10, 5)) == agent_pr_index.last_week(__import__("datetime").date(2026, 10, 6)) == "2026-09-28"

    # added to a copy of the committed series by the command the workflow runs: offline, and the earlier weeks stay
    rows, into, doc = tmp_path / "week.json", tmp_path / "agent_weekly.json", tmp_path / "INDEX.md"
    rows.write_text(json.dumps(got), encoding="utf-8")
    before = json.loads((ROOT / "docs" / "agent_weekly.json").read_text(encoding="utf-8"))
    into.write_text(json.dumps(before), encoding="utf-8")
    doc.write_text((ROOT / "docs" / "INDEX.md").read_text(encoding="utf-8"), encoding="utf-8")
    cli = [sys.executable, str(ROOT / "scripts" / "agent_pr_index.py"), "weekly", "--rows", str(rows), "--into", str(into), "--doc", str(doc)]
    env = {**os.environ, "GH_TOKEN": "", "PATH": ""}                         # no gh to call: this step reads nothing
    r = subprocess.run(cli, capture_output=True, text=True, check=False, env=env)
    assert r.returncode == 0 and "Agent PR Index, week of 2026-09-28" in r.stderr, r.stderr
    after = json.loads(into.read_text(encoding="utf-8"))
    for name, agent in after["agents"].items():
        old = {w["week"]: w for w in before["agents"][name]["weeks"]}
        new = {w["week"]: w for w in agent["weeks"]}
        assert {k: v for k, v in new.items() if k != "2026-09-28"} == {k: v for k, v in old.items() if k != "2026-09-28"}
        w = new["2026-09-28"]
        assert w["full_week"] is True and w["read"] == "2026-10-05" and w["sampled"] is not None    # the dates of every hit were kept
        assert agent["all_weeks"]["claimed_passing"] == sum(x["claimed_passing"] for x in agent["weeks"])
    week = {name: next(w for w in a["weeks"] if w["week"] == "2026-09-28") for name, a in after["agents"].items()}
    assert week["copilot"]["sampled"] == 84 and week["copilot"]["claimed_passing"] == 56 and week["copilot"]["ci_finished"] == 56
    assert week["copilot"]["failed_a_check"] == {"k": 14, "n": 56, "share": 0.25, "ci95": agent_pr_index.wilson(14, 56), "test_or_build": 14}
    assert week["copilot"]["merged_despite_failed_check"]["n"] == 28 and week["copilot"]["rank"] == 1          # the only agent with 30 finished claims
    assert week["devin"]["sampled"] == 42 and week["devin"]["rank"] is None and week["claude-bot"]["sampled"] == 0
    assert [week[a]["rank"] for a in ("devin", "claude-bot", "claude-code", "codex")] == [None] * 4            # too few: never placed
    page = doc.read_text(encoding="utf-8")
    assert "**Agent PR Index, week of 2026-09-28.** Read 2026-10-05. Design: whole-week-v0. Capped: false." in page
    assert "| 1 | copilot | 42 of 56 (75.0%;" in page and "| 84 | 56 | 14 of 56 (25.0%;" in page and page.split(agent_pr_index.BEGIN)[1].count("| too few to rank |") == 4 and "not kept | 5 | 3" not in page
    assert page.count("| not capped: whole-week-v0 |") == 5
    assert page.index("| 1 | copilot") < page.index("| too few to rank | devin")
    # the same week again changes nothing; a week that was not read whole is refused and says what to do
    assert subprocess.run(cli, capture_output=True, text=True, encoding="utf-8", check=False, env=env).returncode == 0 and json.loads(into.read_text(encoding="utf-8")) == after
    rows.write_text(json.dumps({**got, "unfinished_search": ["codex"]}), encoding="utf-8")
    r = subprocess.run(cli, capture_output=True, text=True, check=False, env=env)
    assert r.returncode == 1 and "not added: the search did not finish for codex" in r.stderr and json.loads(into.read_text(encoding="utf-8")) == after
    rows.write_text(json.dumps({**got, "no_claim": None}), encoding="utf-8")
    assert "`sampled` would be unknown" in subprocess.run(cli, capture_output=True, text=True, check=False, env=env).stderr


# ---- the weekly sample: bounded, stratified, seeded, resumable (a GitHub that answers from a table; no network) -----
SAMPLE_WEEK = "2026-09-28"
HOLDS = {"copilot": 250, "devin": 150, "claude-bot": 0, "claude-code": 40, "codex": 3}     # results a day; nothing here is a measured number


def _holds(agent, day):
    return 1500 if (agent, day) == ("devin", "2026-09-30") else HOLDS[agent]      # one day over GitHub's 1,000


class SampleApi:
    """`gh` for the week of 2026-09-28, as agent_pr_ci._gh sees it. A result's number is its place in the day (0 is the
    newest) plus 100,000 x the day of the month, and says everything about it: every third claims nothing, every
    eleventh sits on its author's own repository, every fourth has a failed build, every seventh has no check, even
    ones were merged."""

    def __init__(self, graphql="ok", refuse_search_after=None):
        self.asked, self.graphql, self.refuse_search_after = [], graphql, refuse_search_after

    def hit(self, agent, day, place):
        n = int(day[8:10]) * 100_000 + place
        return {"repository_url": f"https://api.github.com/repos/acme/{agent}", "number": n, "user": {"login": "acme" if n % 11 == 0 else f"{agent}[bot]"},
                "assignees": [], "created_at": f"{day}T12:00:00Z", "body": "Please make sure tests pass" if n % 3 == 0 else "All tests pass."}

    @staticmethod
    def checks(n):
        return [] if n % 7 == 0 else [{"name": "build", "status": "completed", "conclusion": "failure" if n % 4 == 0 else "success"}]

    def __call__(self, cmd):
        if cmd[2] == "graphql":
            query = cmd[4].split("query=", 1)[1]
            prs = re.findall(r'p(\d+): repository\(owner: "acme", name: "([a-z-]+)"\) \{ pullRequest\(number: (\d+)\)', query)
            self.asked.append(("graphql", len(prs)))
            if self.graphql != "ok":
                return 1, "", self.graphql
            assert "mutation" not in query and len(prs) <= agent_pr_ci.ROLLUP_BATCH
            data = {f"p{i}": {"pullRequest": {"merged": int(n) % 2 == 0, "commits": {"nodes": [{"commit": {"oid": f"s{n}", "checkSuites": {"nodes": []}, "statusCheckRollup": None if not self.checks(int(n)) else {
                "contexts": {"pageInfo": {"hasNextPage": False}, "nodes": [{"__typename": "CheckRun", "name": c["name"], "status": "COMPLETED", "conclusion": c["conclusion"].upper()} for c in self.checks(int(n))]}}}}]}}}
                    for i, _, n in prs}
            return 0, json.dumps({"data": data}), ""
        path, params = cmd[4], dict(x.split("=", 1) for x in cmd[cmd.index("-f") + 1::2]) if "-f" in cmd else {}
        if path == "search/issues":
            agent = next(a for a, qual in agent_pr_ci.AGENTS if f"is:pr {qual} created:" in params["q"])
            day = params["q"].split("created:")[1][:10]
            page, order, total = int(params["page"]), params["order"], _holds(agent, day)
            self.asked.append(("search", agent, day, order, page))
            if self.refuse_search_after is not None and sum(a[0] == "search" for a in self.asked) > self.refuse_search_after:
                return 1, "", "gh: API rate limit exceeded (HTTP 403)"
            assert page * 100 <= 1000, "GitHub answers no query past its first 1,000 results"
            places = [p for p in range((page - 1) * 100, page * 100) if p < total]
            return 0, json.dumps({"total_count": total, "items": [self.hit(agent, day, p if order == "desc" else total - 1 - p) for p in places]}), ""
        self.asked.append(("rest", path))
        n = int(re.search(r"/(?:pull|pulls|commits/s)/?(\d+)", path).group(1))
        if "/refs/pull/" in path:
            return 0, json.dumps({"sha": f"s{n}", "statuses": []}), ""
        if path.endswith("check-runs"):
            return 0, json.dumps({"check_runs": self.checks(n)}), ""
        if path.endswith("check-suites"):
            return 0, json.dumps({"check_suites": []}), ""
        return 0, json.dumps({"merged": n % 2 == 0}), ""


@pytest.fixture()
def sampled(tmp_path, monkeypatch):
    """Run the sample against a SampleApi: run(api, checkpoint, **budget) -> the checkpoint's state. No sleep is allowed."""
    def no_sleep(seconds):
        raise AssertionError(f"a bounded run slept {seconds} s")
    monkeypatch.setattr(agent_pr_ci.time, "sleep", no_sleep)
    monkeypatch.setattr(agent_pr_ci, "SEARCH_PAUSE", 0)
    fresh = iter(range(1000))

    def run(api, checkpoint, **budget):
        monkeypatch.setattr(agent_pr_ci, "CACHE", str(tmp_path / f"cache{next(fresh)}"))   # never the real ~/.cache, and never an earlier run's: only the checkpoint carries over
        monkeypatch.setattr(agent_pr_ci, "_gh", api)
        return agent_pr_index.sample_week(SAMPLE_WEEK, str(checkpoint), read="2026-10-05", **budget)
    return run


def _week(state):
    one = agent_pr_index.week_from_sample(state)
    return {name: a["weeks"][0] for name, a in one["agents"].items()}


def test_the_seeded_order_is_fixed_by_the_iso_week_and_reaches_both_ends_of_a_day_over_the_cap():
    assert agent_pr_index.iso_week("2026-09-28") == "2026-W40" and agent_pr_index.week_days("2026-09-28")[-1] == "2026-10-04"
    order = agent_pr_index.draw_order("2026-W40", "devin", "2026-09-30", 250)
    assert sorted(order) == list(range(250)) and order == agent_pr_index.draw_order("2026-W40", "devin", "2026-09-30", 250)
    assert order != agent_pr_index.draw_order("2026-W41", "devin", "2026-09-30", 250) != list(range(250))        # another week, another order
    digest = lambda p: __import__("hashlib").sha256(f"2026-W40|devin|2026-09-30|{p}".encode()).hexdigest()  # noqa: E731
    assert order == sorted(range(250), key=digest)                           # the rule the method page states, and nothing else
    assert len(agent_pr_index.reachable(1500)) == 1500 and len(agent_pr_index.reachable(2000)) == 2000
    assert agent_pr_index.reachable(2600) == list(range(1000)) + list(range(1600, 2600))                         # the middle of a day over 2,000 cannot be asked for
    assert agent_pr_index.page_of(0, 1500) == ("desc", 1, 0) and agent_pr_index.page_of(999, 1500) == ("desc", 10, 99)
    assert agent_pr_index.page_of(1499, 1500) == ("asc", 1, 0) and agent_pr_index.page_of(1000, 1500) == ("asc", 5, 99)


def test_the_weekly_sample_stays_in_its_budget_publishes_what_it_has_and_resumes_from_its_checkpoint(sampled, tmp_path):
    """The dry run of the weekly job: a run cut by its budget publishes a capped week in which every stratum holds a
    prefix of its own seeded order; a second run continues from the checkpoint, asks for nothing twice, and ends with
    exactly the sample one uncut run draws."""
    whole_api, cut_api, more_api = SampleApi(), SampleApi(), SampleApi()
    whole = sampled(whole_api, tmp_path / "whole.json", max_requests=5000, max_minutes=20)
    assert whole["runs"][-1]["complete"] and whole["runs"][-1]["requests"] == len(whole_api.asked) <= 35 * 10 + 53 + 30   # at most ten pages a stratum, 20 pull requests a query, a short one a turn
    full = _week(whole)
    for name, w in full.items():
        assert w["design"] == "stratified-seeded-v1" and w["capped"] is False and w["seed"] == "2026-W40" and list(w["strata"]) == list(agent_pr_index.DAY_NAMES)
        for d in w["strata"].values():
            assert d["reported"] == _holds(name, d["date"]) and d["planned"] == d["drawn"] == min(30, HOLDS[name]) and d["checks_read"] == d["claimed"]   # the same number in every stratum
        assert w["verified_acceptance_rate"]["n"] == w["claimed_passing"] == sum(d["claimed"] for d in w["strata"].values())
        assert w["checks"]["not_read"] == 0 and w["checks"]["passed"] == w["verified_acceptance_rate"]["k"]
    assert full["devin"]["strata"]["Wed"]["reachable"] == 1500 and any(a[3] == "asc" for a in whole_api.asked if a[0] == "search")   # a day over 1,000 is drawn from both ends
    assert full["claude-bot"]["sampled"] == 0 and full["claude-bot"]["rank"] is None and full["codex"]["rank"] is None    # too few to rank: never placed
    assert sorted(w["rank"] for w in full.values() if w["rank"] is not None) == sorted({1, 2, 3} & {w["rank"] for w in full.values()}) and full["copilot"]["rank"] is not None
    assert sum(n for kind, *rest in whole_api.asked if kind == "graphql" for n in rest) == sum(w["claimed_passing"] for w in full.values())   # one request for 20, each asked once
    assert not any(kind == "rest" for kind, *_ in whole_api.asked)

    # cut by its budget: it stops at the request it may not send, sleeps for nothing, and the week is still published
    cut = sampled(cut_api, tmp_path / "week.json", max_requests=90, max_minutes=20)
    assert 84 <= len(cut_api.asked) == cut["runs"][-1]["requests"] <= 90 and not cut["runs"][-1]["complete"]
    last_search = max(i for i, a in enumerate(cut_api.asked) if a[0] == "search")
    assert last_search < 90 - agent_pr_index.CHECK_RESERVE[0] and cut_api.asked[-1][0] == "graphql"   # the search left the checks their requests
    capped = _week(cut)
    assert all(w["checks"]["not_read"] == 0 for w in capped.values())                        # what was drawn had its checks read
    assert set(capped) == set(full) and any(w["capped"] for w in capped.values())            # every agent has a row, and the cap is said
    assert capped["devin"]["capped"] is True and 0 < sum(d["drawn"] for d in capped["devin"]["strata"].values()) < 7 * 30
    spread = [d["drawn"] for d in capped["devin"]["strata"].values()]
    assert max(spread) - min(spread) <= 1 and min(spread) > 0                               # the strata were served in turns: none was left behind
    for agent, _ in agent_pr_ci.AGENTS:
        for day in agent_pr_index.week_days(SAMPLE_WEEK):
            some, every = agent_pr_index.drawn(cut, agent, day), agent_pr_index.drawn(whole, agent, day)
            assert some == every[:len(some)]                                                 # a prefix of the same order: a valid sample, only smaller

    # the next run starts from the checkpoint (its disk cache is empty), asks for no page twice, and completes the same sample
    more = sampled(more_api, tmp_path / "week.json", max_requests=5000, max_minutes=20)
    searches = [a for a in cut_api.asked + more_api.asked if a[0] == "search"]
    assert len(searches) == len(set(searches)) == sum(a[0] == "search" for a in whole_api.asked)
    assert [r["complete"] for r in more["runs"]] == [False, True] and _week(more) == full and more["checks"] == whole["checks"]
    again_api = SampleApi()
    assert sampled(again_api, tmp_path / "week.json", max_requests=5000, max_minutes=20)["runs"][-1]["requests"] == 0 and not again_api.asked   # a finished week reads nothing
    # another week's checkpoint is not this week's
    assert agent_pr_index.load_checkpoint(str(tmp_path / "week.json"), "2026-09-21", 30)["strata"] == {}


def test_a_run_out_of_minutes_or_refused_for_a_rate_limit_stops_without_sleeping_and_still_writes_every_agent_s_row(sampled, tmp_path):
    late = SampleApi()
    state = sampled(late, tmp_path / "late.json", max_requests=500, max_minutes=0.2)       # 12 seconds: no request fits before the end
    assert not late.asked and state["runs"][-1] == {"read": "2026-10-05", "requests": 0, "max_requests": 500, "max_minutes": 0.2, "complete": False,
                                                    "stopped": "its minutes were spent"}
    week = _week(state)
    assert set(week) == {a for a, _ in agent_pr_ci.AGENTS}
    assert all(w["capped"] is True and w["sampled"] == 0 and w["rank"] is None and w["strata"]["Mon"] == {"date": "2026-09-28", "reported": None, "reachable": None, "planned": None, "drawn": 0, "claimed": 0, "checks_read": 0} for w in week.values())
    limited = SampleApi(refuse_search_after=50)
    state = sampled(limited, tmp_path / "limited.json", max_requests=500, max_minutes=20)   # the 51st search is refused: the run ends there (the fixture fails on any sleep)
    assert sum(a[0] == "search" for a in limited.asked) == 51 and len(limited.asked) > 51 and not state["runs"][-1]["complete"]
    assert state["runs"][-1]["stopped"] == "GitHub refused a search request for a rate limit"   # the run says why it ended
    week = _week(state)
    assert any(w["capped"] for w in week.values()) and sum(w["sampled"] for w in week.values()) > 0 and all(w["checks"]["not_read"] == 0 for w in week.values())
    assert not agent_pr_ci.NO_WAIT and agent_pr_ci.MAX_REQUESTS is None                     # the bound is this run's, not the next caller's


def test_a_bounded_run_refused_for_a_secondary_limit_names_it_and_does_not_sleep(sampled, tmp_path):
    """GitHub's secondary limit on search (a few heavy searches close together) ends a bounded run at once, and the run
    says so: on 2026-10-05 a run from the release machine was refused at its third search, and said only "capped"."""
    class Secondary(SampleApi):
        def __call__(self, cmd):
            if "search/issues" in cmd and sum(a[0] == "search" for a in self.asked) >= 2:
                return 1, "", "gh: You have exceeded a secondary rate limit. Please wait a few minutes before you try again."
            return super().__call__(cmd)
    state = sampled(Secondary(), tmp_path / "secondary.json", max_requests=500, max_minutes=20)
    assert not state["runs"][-1]["complete"] and state["runs"][-1]["stopped"] == "GitHub refused a search request for a secondary rate limit"
    assert not agent_pr_ci.NO_WAIT and agent_pr_ci.MAX_REQUESTS is None


def test_when_graphql_refuses_the_token_the_checks_are_read_over_rest_and_say_the_same(sampled, tmp_path):
    budget = {"per_stratum": 4, "max_requests": 5000, "max_minutes": 20}
    by_graphql, by_rest = SampleApi(), SampleApi(graphql="gh: Resource not accessible by integration (HTTP 403)")
    one, two = sampled(by_graphql, tmp_path / "g.json", **budget), sampled(by_rest, tmp_path / "r.json", **budget)
    assert one["graphql"] is True and two["graphql"] is False and one["checks"] == two["checks"] and len(one["checks"]) > 20
    assert _week(one) == _week(two)
    claims = len(one["checks"])
    assert sum(a[0] == "graphql" for a in by_graphql.asked) == -(-claims // agent_pr_ci.ROLLUP_BATCH)        # one request for each 20 pull requests
    assert sum(a[0] == "graphql" for a in by_rest.asked) == 1 and 2 * claims <= sum(a[0] == "rest" for a in by_rest.asked) <= 4 * claims   # refused once, then never asked again
    # the classes are the REST reading's: a failed build, no check at all, a pass
    kinds = {c["class"] for c in one["checks"].values()}
    assert kinds == {"failed", "no-ci", "passed"} and all(isinstance(c["merged"], bool) for c in one["checks"].values() if c["class"] != "no-ci")


def test_the_weekly_command_adds_a_capped_sample_to_the_series_and_never_refuses_it(sampled, tmp_path):
    """What the workflow's second job runs, offline: the checkpoint of a run cut by its budget goes into a copy of the
    committed series with its design, its counts for each stratum and `capped`, and the earlier weeks stay."""
    ck, into, doc = tmp_path / "week.json", tmp_path / "agent_weekly.json", tmp_path / "INDEX.md"
    sampled(SampleApi(), ck, max_requests=60, max_minutes=20)
    before = json.loads((ROOT / "docs" / "agent_weekly.json").read_text(encoding="utf-8"))
    into.write_text(json.dumps(before), encoding="utf-8")
    doc.write_text((ROOT / "docs" / "INDEX.md").read_text(encoding="utf-8"), encoding="utf-8")
    cli = [sys.executable, str(ROOT / "scripts" / "agent_pr_index.py"), "weekly", "--rows", str(ck), "--into", str(into), "--doc", str(doc)]
    env = {**os.environ, "GH_TOKEN": "", "PATH": ""}                         # no gh to call: this step reads nothing
    r = subprocess.run(cli, capture_output=True, text=True, encoding="utf-8", check=False, env=env)
    assert r.returncode == 0 and "Agent PR Index, week of 2026-09-28" in r.stderr, r.stderr
    after = json.loads(into.read_text(encoding="utf-8"))
    for name, agent in after["agents"].items():
        old = {w["week"]: w for w in before["agents"][name]["weeks"]}
        new = {w["week"]: w for w in agent["weeks"]}
        assert {k: v for k, v in new.items() if k != SAMPLE_WEEK} == {k: v for k, v in old.items() if k != SAMPLE_WEEK}   # 21 September keeps its place by the old count
        w = new[SAMPLE_WEEK]
        assert w["design"] == "stratified-seeded-v1" and isinstance(w["capped"], bool) and len(w["strata"]) == 7 and w["read"] == "2026-10-05"
        assert w["verified_acceptance_rate"] is not None and w["ranked_by"] == "verified_acceptance_rate" and w["sampled"] is not None
        assert agent["all_weeks"] == agent_pr_index._add(agent["weeks"])
    assert any(a["weeks"][-1]["capped"] for a in after["agents"].values()) and after["latest_week"] == SAMPLE_WEEK
    cut = {w["week"] for a in after["agents"].values() for w in a["weeks"] if w.get("full_week") is False and w["read"] == after["read"]}
    assert ("not whole weeks" in after["source"]) == bool(cut) and all(week in after["source"] for week in cut)   # the weeks a scan cut are still said
    page = doc.read_text(encoding="utf-8")
    assert "**Agent PR Index, week of 2026-09-28.** Read 2026-10-05. Design: stratified-seeded-v1. Capped: true" in page and "| capped: drew " in page
    assert agent_pr_index.weekly_table(after) in page
    assert subprocess.run(cli, capture_output=True, text=True, encoding="utf-8", check=False, env=env).returncode == 0 and json.loads(into.read_text(encoding="utf-8")) == after


def test_a_rank_needs_thirty_finished_claims_and_equal_shares_share_a_place_and_verified_counts_only_what_knos_paid():
    def rows(agent, n, failed, base):
        return [_row(agent, base + i, "2026-09-22", "failed" if i < failed else "passed", True, ["build"] if i < failed else ()) for i in range(n)]
    all_rows = rows("copilot", 40, 10, 0) + rows("devin", 30, 3, 100) + rows("codex", 60, 15, 200) + rows("claude-bot", 29, 0, 300)
    got = agent_pr_index.weekly(all_rows, WINDOW, "2026-10-02", "a test", [], paid=["o/r100#100", "O/R7#7", "x/y#1"])
    place = {name: a["weeks"][0]["rank"] if a["weeks"] else "none" for name, a in got["agents"].items()}
    assert place == {"devin": 1, "copilot": 2, "codex": 2, "claude-bot": None, "claude-code": "none"}     # 29 with no failure is still not placed
    assert got["agents"]["devin"]["weeks"][0]["verified"] == 1 and got["agents"]["copilot"]["weeks"][0]["verified"] == 1
    assert "a list of 3 pull requests paid through Knos" in got["verified_against"]
    assert "no list of Knos payments was joined" in agent_pr_index.weekly(all_rows, WINDOW, "d", "s")["verified_against"]
    table = agent_pr_index.weekly_table(got)
    assert table.index("| 1 | devin") < table.index("| 2 | copilot") < table.index("| too few to rank | claude-bot")


def test_the_site_draws_the_index_board_from_the_committed_file_and_asks_nobody():
    """tests/web/index_board.mjs: the rows, the places, the sample sizes and the verified count with no browser, then
    in headless Chromium when the `playwright` package and a browser are there (it says so when they are not)."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    env = dict(os.environ)
    if "PLAYWRIGHT_BROWSERS_PATH" not in env and Path("/opt/pw-browsers").is_dir():
        env["PLAYWRIGHT_BROWSERS_PATH"] = "/opt/pw-browsers"
    run = subprocess.run([node, str(ROOT / "tests" / "web" / "index_board.mjs")], capture_output=True, text=True, encoding="utf-8", env=env, timeout=300)
    assert run.returncode == 0 and "all passed" in run.stdout, "\n".join(x for x in (run.stdout + run.stderr).splitlines() if not x.startswith("ok"))
    assert "ok   for every week the page works out the rows docs/index.json holds: counts, shares, intervals, places, dispute links" in run.stdout
    assert "ok   every statement keeps to 12 words" in run.stdout


# ---- the leaderboard, its feeds and its disputes (scripts/agent_pr_board.py; no network) --------------------------------
import agent_pr_board  # noqa: E402


def _wk(week, claimed, k, n, read="2026-10-05"):
    return {"week": week, "read": read, "claimed_passing": claimed, "ci_finished": 9 if n is None else n,
            "merged_despite_failed_check": None if n is None else {"k": k, "n": n, "share": None, "ci95": None}}


def _made():
    """A series nobody measured: two weeks, a tie, one agent short of the bar, one whose merges were not read."""
    return {"name": "Agent PR Index", "read": "2026-10-05", "latest_week": "2026-09-28", "min_claims_to_rank": 30, "agents": {
        "alpha": {"weeks": [_wk("2026-09-21", 50, 9, 30), _wk("2026-09-28", 40, 9, 30)]},
        "beta": {"weeks": [_wk("2026-09-21", 70, 2, 40), _wk("2026-09-28", 10, 0, 5)]},
        "gamma": {"weeks": [_wk("2026-09-21", 44, 12, 40)]},
        "delta": {"weeks": [_wk("2026-09-21", 29, 0, 29)]},
        "epsilon": {"weeks": [_wk("2026-09-28", 12, None, None)]}}}


def test_the_leaderboard_ranks_only_agents_over_the_minimum_and_shows_every_sample_size():
    got = agent_pr_board.board(_made())
    rows = {r["agent"]: r for r in got["rows"]}
    assert [(r["agent"], r["rank"]) for r in got["rows"]] == [("beta", 1), ("alpha", 2), ("gamma", 2), ("delta", None), ("epsilon", None)]   # equal shares share a place
    assert (rows["alpha"]["claimed_passing"], rows["alpha"]["failed_at_merge"], rows["alpha"]["merged"], rows["alpha"]["share"]) == (90, 18, 60, 0.3)
    assert rows["alpha"]["ci95"] == agent_pr_index.wilson(18, 60) and rows["beta"]["ci95"] == agent_pr_index.wilson(2, 45)
    assert rows["delta"]["status"] == "too few to rank" and (rows["delta"]["failed_at_merge"], rows["delta"]["merged"]) == (0, 29)    # one short: shown, never placed
    assert rows["delta"]["ci95"] == agent_pr_index.wilson(0, 29)
    assert rows["epsilon"]["status"] == "not read" and rows["epsilon"]["share"] is None                    # a merge state nobody read is not a zero
    assert rows["gamma"]["overlaps_above"] is True and rows["beta"]["overlaps_above"] is False
    assert all(r["merged"] is None or r["merged"] >= 30 for r in got["rows"] if r["rank"])
    old = {r["agent"]: r for r in agent_pr_board.board(_made(), "2026-09-21")["rows"]}                       # a board adds up the weeks through its own
    assert (old["alpha"]["failed_at_merge"], old["alpha"]["merged"], old["epsilon"]["claimed_passing"], old["epsilon"]["status"]) == (9, 30, 0, "too few to rank")
    text = agent_pr_board.table(agent_pr_board.feed(_made()))
    for r in got["rows"]:
        if r["merged"]:
            assert f"| {r['agent']} | {r['claimed_passing']} | {r['failed_at_merge']} of {r['merged']} | " in text       # the count and its total beside every rate
    assert "| too few to rank | delta | 29 | 0 of 29 | 0.0% | 0.0% to 11.7% |" in text and "| 2 (overlaps) | gamma |" in text


def test_the_committed_page_and_feeds_are_what_the_script_writes_and_check_fails_when_one_differs(tmp_path):
    script = [sys.executable, str(ROOT / "scripts" / "agent_pr_index.py"), "board"]
    ok = subprocess.run([*script, "--check"], cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
    assert ok.returncode == 0 and "nothing to write" in ok.stderr, ok.stderr
    files = {}
    for name in ("INDEX.md", "index.json", "index.atom", "agent_weekly.json", "index_disputes.json"):
        files[name] = tmp_path / name
        shutil.copy(ROOT / "docs" / name, files[name])
    there = ["--series", str(files["agent_weekly.json"]), "--disputes", str(files["index_disputes.json"]), "--doc", str(files["INDEX.md"]),
             "--feed", str(files["index.json"]), "--atom", str(files["index.atom"])]
    page = files["INDEX.md"].read_text(encoding="utf-8")
    row = next(x for x in page.splitlines() if x.startswith("| 1 | "))
    files["INDEX.md"].write_text(page.replace(row, row.replace(" of ", " of 1"), 1), encoding="utf-8")             # a number typed by hand
    bad = subprocess.run([*script, "--check", *there], cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
    assert bad.returncode == 1 and "differs: " in bad.stderr and "INDEX.md" in bad.stderr and "index.json" not in bad.stderr.split("differs: ")[1].split("\n")[0]
    assert files["INDEX.md"].read_text(encoding="utf-8") != page                                                    # --check writes nothing
    assert subprocess.run([*script, *there], cwd=ROOT, capture_output=True, text=True, encoding="utf-8").returncode == 0
    assert files["INDEX.md"].read_text(encoding="utf-8") == page
    # the page: the table, the method in ten lines, what a failed check is not, the limits, the week, one command, one line on payment
    block = page.split(agent_pr_board.BEGIN)[1].split(agent_pr_board.END)[0]
    series = json.loads((ROOT / "docs" / "agent_weekly.json").read_text(encoding="utf-8"))
    assert f"**Agent PR Index, week of {series['latest_week']}.**" in block and len(re.findall(r"^\d+\. \*\*", block, re.M)) == 10
    assert "not always a failed test" in block and "not always a false claim" in block and "python scripts/agent_pr_index.py board --check" in block
    assert block.count(agent_pr_board.NO_PAY) == 1 and len(agent_pr_board.NO_PAY.split()) <= 16 and "Nobody outside Knos has reviewed them" in block
    assert "No row has been disputed yet." in block and "No number has changed after a dispute yet." in block
    assert not re.search(r"\b(best|worst|winner|beats|leads)\b", block, re.I)                                       # the table speaks
    # every number of the table is counted from the committed series
    top = agent_pr_board.board(series)
    for r in top["rows"]:
        mine = [w for w in series["agents"][r["agent"]]["weeks"] if w["ci_finished"]]
        assert r["merged"] == sum(w["merged_despite_failed_check"]["n"] for w in mine) and r["failed_at_merge"] == sum(w["merged_despite_failed_check"]["k"] for w in mine)
        assert r["claimed_passing"] == series["agents"][r["agent"]]["all_weeks"]["claimed_passing"] and (r["rank"] is None) == (r["merged"] < series["min_claims_to_rank"])
        assert f"| {r['agent']} | {r['claimed_passing']} | {r['failed_at_merge']} of {r['merged']} | {r['share']:.1%} | {r['ci95'][0]:.1%} to {r['ci95'][1]:.1%} |" in block


def test_the_feed_is_versioned_and_the_atom_file_has_one_entry_a_week():
    from xml.etree import ElementTree
    doc = json.loads((ROOT / "docs" / "index.json").read_text(encoding="utf-8"))
    series = json.loads((ROOT / "docs" / "agent_weekly.json").read_text(encoding="utf-8"))
    assert doc == agent_pr_board.feed(series, [])
    assert doc["schema"] == "knos.agent-pr-index/1" and doc["latest_week"] == series["latest_week"] and doc["rule"] == agent_pr_board.NO_PAY
    assert [w["week"] for w in doc["weeks"]] == sorted({w["week"] for a in series["agents"].values() for w in a["weeks"]}, reverse=True)
    assert len(doc["method"]) == 10 and doc["source"]["reproduce"] == "python scripts/agent_pr_index.py board --check" and len(doc["source"]["sha256_of_canonical_json"]) == 64
    assert all(set(r) == {"agent", "weeks", "claimed_passing", "merged", "failed_at_merge", "share", "ci95", "rank", "status", "overlaps_above", "disputed", "dispute"}
               for w in doc["weeks"] for r in w["rows"])
    ns = {"a": "http://www.w3.org/2005/Atom"}
    root = ElementTree.fromstring((ROOT / "docs" / "index.atom").read_text(encoding="utf-8"))
    entries = root.findall("a:entry", ns)
    assert root.tag == "{http://www.w3.org/2005/Atom}feed" and [e.find("a:title", ns).text for e in entries] == [f"Agent PR Index, week of {w['week']}" for w in doc["weeks"]]
    assert len({e.find("a:id", ns).text for e in entries}) == len(entries) and root.find("a:updated", ns).text == f"{doc['read']}T00:00:00Z"
    assert all(root.find(f"a:{t}", ns) is not None for t in ("id", "title", "updated", "author")) and all(e.find("a:updated", ns).text.endswith("T00:00:00Z") for e in entries)
    first = entries[0].find("a:summary", ns).text
    assert all(f"{r['agent']}: " in first for r in doc["weeks"][0]["rows"]) and "not always a failed test, and not always a false claim" in first


def test_a_disputed_row_is_marked_with_its_link_and_a_resolved_one_that_changed_a_number_is_in_the_changelog(tmp_path):
    issue = "https://github.com/drexthealpha/Knos/issues/"
    file = tmp_path / "disputes.json"
    file.write_text(json.dumps({"schema": "knos.agent-pr-index.disputes/1", "disputes": [
        {"agent": "alpha", "week": "2026-09-28", "issue": issue + "7", "opened": "2026-10-06", "status": "open"},
        {"agent": "beta", "week": None, "issue": issue + "5", "opened": "2026-09-29", "status": "resolved", "resolved": "2026-10-02",
         "outcome": "One pull request was a person's, not the agent's.", "changed": [{"field": "failed_at_merge", "from": 3, "to": 2}]},
        {"agent": "gamma", "week": None, "issue": issue + "6", "opened": "2026-09-30", "status": "rejected", "resolved": "2026-10-03", "outcome": "The check named is a test job.", "changed": []}]}), encoding="utf-8")
    disputes = agent_pr_board.load_disputes(str(file), ["alpha", "beta", "gamma", "delta", "epsilon"])
    doc = agent_pr_board.feed(_made(), disputes)
    now, before = ({r["agent"]: r for r in w["rows"]} for w in doc["weeks"])
    assert now["alpha"]["disputed"] == [{"issue": issue + "7", "opened": "2026-10-06"}] and before["alpha"]["disputed"] == []      # from its week on
    assert now["beta"]["disputed"] == [] and now["gamma"]["disputed"] == []                                                   # a closed dispute marks nothing
    assert now["alpha"]["rank"] == 2                                                                                          # a dispute moves no number by itself
    text = agent_pr_board.table(doc)
    assert f"| 2 | alpha [† disputed]({issue}7) | 90 | 18 of 60 |" in text and f"- open: alpha, week of 2026-09-28, opened 2026-10-06: {issue}7" in text
    assert doc["changelog"] == [{"resolved": "2026-10-02", "agent": "beta", "week": None, "issue": issue + "5", "outcome": "One pull request was a person's, not the agent's.",
                                 "changed": [{"field": "failed_at_merge", "from": 3, "to": 2}]}]
    assert f"- 2026-10-02: beta: `failed_at_merge` 3 to 2. One pull request was a person's, not the agent's. ({issue}5)" in text
    assert f"- rejected 2026-10-03: gamma: The check named is a test job. ({issue}6)" in text and "No number has changed" not in text
    assert "; disputed" in agent_pr_board.atom(doc) and agent_pr_board.dispute_url("alpha", "2026-09-28") in text
    assert agent_pr_board.dispute_url("a b", "2026-09-28").endswith("?template=dispute-index-row.yml&title=Dispute+a+row%3A+a+b%2C+week+of+2026-09-28&agent=a+b&week=2026-09-28")
    for wrong, why in (({"agent": "nobody"}, "is not a row"), ({"issue": "mailto:x"}, "public issue"), ({"status": "paid"}, "`status` is 'paid'"),
                       ({"status": "resolved"}, "says what was found"), ({"changed": [{"field": "merged", "from": 1, "to": 2}]}, "only a resolved dispute")):
        file.write_text(json.dumps({"schema": "knos.agent-pr-index.disputes/1", "disputes": [{"agent": "alpha", "issue": issue + "1", "status": "open", **wrong}]}), encoding="utf-8")
        with pytest.raises(SystemExit, match=re.escape(why)):
            agent_pr_board.load_disputes(str(file), ["alpha"])
    assert agent_pr_board.load_disputes(str(tmp_path / "none.json")) == []
    committed = json.loads((ROOT / "docs" / "index_disputes.json").read_text(encoding="utf-8"))
    assert committed == {"schema": "knos.agent-pr-index.disputes/1", "disputes": []}                                           # nobody has disputed a row: none is made up


def test_the_dispute_form_asks_for_the_agent_the_pull_requests_and_the_evidence():
    yaml = pytest.importorskip("yaml")
    form = yaml.safe_load((ROOT / ".github" / "ISSUE_TEMPLATE" / agent_pr_board.TEMPLATE).read_text(encoding="utf-8"))
    fields = {b["id"]: b for b in form["body"] if "id" in b}
    assert form["name"] == "Dispute a row" and {"agent", "week", "prs", "evidence"} <= set(fields)                             # the link on each row fills `agent` and `week`
    assert all(fields[k]["validations"]["required"] for k in ("agent", "prs", "evidence"))
    assert "no payment changes a row" in form["body"][0]["attributes"]["value"]


# ---- inside GitHub's limits: one at a time, as long as GitHub says, only what changed ------------------------------------
def _headers(status, body, **headers):
    return f"HTTP/2.0 {status}\r\n" + "".join(f"{k}: {v}\r\n" for k, v in headers.items()) + "\r\n" + body


def test_a_wait_is_the_one_github_names():
    assert agent_pr_ci.limit_wait({"retry-after": "7"}, 0) == 8                                              # retry-after, and not a second less
    assert agent_pr_ci.limit_wait({"x-ratelimit-remaining": "0", "x-ratelimit-reset": "1600"}, 0, now=1000) == 601   # until the budget is back
    assert [agent_pr_ci.limit_wait({}, n) for n in range(4)] == [60, 120, 240, 480]                             # else a minute, longer each time
    assert agent_pr_ci.limit_wait({"x-ratelimit-remaining": "12", "x-ratelimit-reset": "1600"}, 1, now=1000) == 120
    assert agent_pr_ci._answer(_headers(200, '{"a": 1}', ETag='W/"x"')) == (200, {"etag": 'W/"x"'}, '{"a": 1}') and agent_pr_ci._answer('{"a": 1}') == (None, {}, '{"a": 1}')


def test_a_refusal_with_retry_after_is_waited_out_and_the_request_asked_again(github):
    path, table = "repos/o/r/pulls/1", github.__call__

    def gh(cmd):                    # as `gh api -i` prints a refusal: the status line and the headers on stdout, its own words on stderr
        if cmd[4] == path and path not in github.calls:
            github.calls.append(path)
            return 1, _headers(403, '{"message": "You have exceeded a secondary rate limit."}', **{"Retry-After": "7"}), "gh: You have exceeded a secondary rate limit. (HTTP 403)"
        return table(cmd)
    monkeypatch_gh = pytest.MonkeyPatch()
    monkeypatch_gh.setattr(agent_pr_ci, "_gh", gh)
    github.script[path] = {"merged": True}
    try:
        got = agent_pr_ci.gh_get(path)
    finally:
        monkeypatch_gh.undo()
    assert got == {"ok": True, "json": {"merged": True}} and github.calls.count(path) == 2 and github.slept == [8]
    # without the header: a minute, then two; and after MAX_RETRIES refusals the request is given up, loudly
    github.slept.clear()
    github.script["repos/o/r/pulls/2"] = ["gh: You have exceeded a secondary rate limit (HTTP 403)"]
    with pytest.raises(agent_pr_ci.OutOfTime):
        agent_pr_ci.gh_get("repos/o/r/pulls/2")
    assert github.slept == [60, 120, 240, 480] and github.calls.count("repos/o/r/pulls/2") == agent_pr_ci.MAX_RETRIES + 1


def test_an_answer_grown_old_is_asked_for_with_its_etag_and_a_304_keeps_it(tmp_path, monkeypatch):
    sent = []

    def gh(cmd):
        sent.append(cmd)
        if any(h.startswith("If-None-Match: ") for h in cmd):
            return 0, _headers(304, ""), ""
        return 0, _headers(200, '{"state": "pending"}', Etag='W/"abc"'), ""
    monkeypatch.setattr(agent_pr_ci, "CACHE", str(tmp_path / "cache"))
    monkeypatch.setattr(agent_pr_ci, "_gh", gh)
    monkeypatch.setattr(agent_pr_ci, "ARGS", SimpleNamespace(max_seconds=10_000))
    monkeypatch.setattr(agent_pr_ci, "START", time.time())
    first = agent_pr_ci.gh_get("repos/o/r/commits/abc/status")
    assert first == {"ok": True, "json": {"state": "pending"}} and sent[0][-1] == "-i" and not any("If-None-Match" in h for h in sent[0])
    assert agent_pr_ci.gh_get("repos/o/r/commits/abc/status") == first and len(sent) == 1               # still fresh: nothing is asked
    again = agent_pr_ci.gh_get("repos/o/r/commits/abc/status", max_age=-1)                                  # grown old: asked for only if it changed
    assert again == first and len(sent) == 2 and 'If-None-Match: W/"abc"' in sent[1]
    assert agent_pr_ci.gh_get("repos/o/r/commits/abc/status", max_age=3600) == first and len(sent) == 2     # the 304 made the kept answer fresh again


# What `gh api -i` (gh 2.102.0) printed for GET repos/drexthealpha/knos-rc on 2026-10-06, byte for byte in its shape:
# the status line ends in "\n" alone and every header line, and the empty line after them, in "\r\n". Asked again with
# its ETag, GitHub answered 304 with no body, gh exited 1 and said "gh: HTTP 304", and X-Ratelimit-Remaining did not move.
_REAL_200 = ('HTTP/2.0 200 OK\nAccess-Control-Allow-Origin: *\r\nCache-Control: private, max-age=60, s-maxage=60\r\n'
             'Etag: W/"7029a6b6b1be23d4"\r\nX-Ratelimit-Limit: 5000\r\nX-Ratelimit-Remaining: 4982\r\n'
             'X-Ratelimit-Reset: 1791301956\r\nX-Ratelimit-Resource: core\r\nX-Ratelimit-Used: 18\r\n\r\n{"full_name": "o/r"}')
_REAL_304 = ('HTTP/2.0 304 Not Modified\nAccess-Control-Allow-Origin: *\r\nEtag: "7029a6b6b1be23d4"\r\n'
             'X-Ratelimit-Limit: 5000\r\nX-Ratelimit-Remaining: 4982\r\nX-Ratelimit-Resource: core\r\n\r\n')


def test_what_gh_api_i_really_prints_is_read_and_its_304_keeps_the_answer(tmp_path, monkeypatch):
    assert agent_pr_ci._answer(_REAL_200) == (200, {"access-control-allow-origin": "*", "cache-control": "private, max-age=60, s-maxage=60",
                                                    "etag": 'W/"7029a6b6b1be23d4"', "x-ratelimit-limit": "5000", "x-ratelimit-remaining": "4982",
                                                    "x-ratelimit-reset": "1791301956", "x-ratelimit-resource": "core", "x-ratelimit-used": "18"},
                                              '{"full_name": "o/r"}')
    assert agent_pr_ci._answer(_REAL_304)[0] == 304 and agent_pr_ci._answer(_REAL_304)[2] == ""
    sent = []

    def gh(cmd):
        sent.append(cmd)
        if any(h.startswith("If-None-Match: ") for h in cmd):
            return 1, _REAL_304, "gh: HTTP 304\n"          # gh's exit status for a 304 is 1: the status line decides, not the exit
        return 0, _REAL_200, ""
    monkeypatch.setattr(agent_pr_ci, "CACHE", str(tmp_path / "cache"))
    monkeypatch.setattr(agent_pr_ci, "_gh", gh)
    monkeypatch.setattr(agent_pr_ci, "ARGS", SimpleNamespace(max_seconds=10_000))
    monkeypatch.setattr(agent_pr_ci, "START", time.time())
    first = agent_pr_ci.gh_get("repos/o/r")
    again = agent_pr_ci.gh_get("repos/o/r", max_age=-1)
    assert first == again == {"ok": True, "json": {"full_name": "o/r"}} and 'If-None-Match: W/"7029a6b6b1be23d4"' in sent[1]
    assert agent_pr_ci.gh_get("repos/o/r", max_age=3600) == first and len(sent) == 2                       # the 304 made it fresh: nothing more asked


def test_requests_go_one_at_a_time_and_a_pace_apart(monkeypatch):
    import threading
    inside, most, slept, clock = [0], [0], [], [1000.0]

    def gh(cmd):
        inside[0] += 1
        most[0] = max(most[0], inside[0])
        inside[0] -= 1
        return 0, "{}", ""
    monkeypatch.setattr(agent_pr_ci, "_gh", gh)
    monkeypatch.setattr(agent_pr_ci, "PACE", 4.8)
    monkeypatch.setattr(agent_pr_ci, "_LAST", [0.0])
    monkeypatch.setattr(agent_pr_ci.time, "time", lambda: clock[0])
    monkeypatch.setattr(agent_pr_ci.time, "sleep", lambda s: (slept.append(round(s, 3)), clock.__setitem__(0, clock[0] + s)))
    threads = [threading.Thread(target=agent_pr_ci._send, args=(["gh"],)) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert most[0] == 1 and slept == [4.8] * 4                                                             # never two in flight; each 4.8 s after the one before


def test_a_patient_run_waits_out_a_secondary_limit_and_finishes_the_week_and_a_wait_too_long_is_left_for_the_next_run(tmp_path, monkeypatch):
    """What stopped the week of 2026-09-28 at 95 of 930 draws: the third search was refused and the run ended. A
    patient run waits as long as GitHub says and goes on; when the wait does not fit, the checkpoint keeps the time."""
    slept = []
    monkeypatch.setattr(agent_pr_ci.time, "sleep", slept.append)
    monkeypatch.setattr(agent_pr_ci, "SEARCH_PAUSE", 0)
    monkeypatch.setattr(agent_pr_ci, "CACHE", str(tmp_path / "cache"))

    class Limited(SampleApi):
        def __init__(self, retry_after, times):
            super().__init__()
            self.retry_after, self.times = retry_after, times

        def __call__(self, cmd):
            assert cmd[-1] == "-i"
            if "search/issues" in cmd and self.times and sum(a[0] == "search" for a in self.asked) >= 2:
                self.times -= 1
                return 1, _headers(403, '{"message": "You have exceeded a secondary rate limit."}', **{"retry-after": str(self.retry_after)}), "gh: secondary rate limit (HTTP 403)"
            return super().__call__(cmd)
    api = Limited(retry_after=30, times=3)
    monkeypatch.setattr(agent_pr_ci, "_gh", api)
    state = agent_pr_index.sample_week(SAMPLE_WEEK, str(tmp_path / "week.json"), read="2026-10-05", max_requests=5000, max_minutes=50, patient=True)
    assert slept == [31, 31, 31] and state["runs"][-1]["complete"] is True and state["runs"][-1]["stopped"] is None
    assert state["cursor"]["come_back"] is None and state["cursor"]["strata_counted"] == state["cursor"]["of_strata"] == 35 and state["cursor"]["draw_turn"] == 30
    week = _week(state)
    assert not any(w["capped"] for w in week.values()) and sum(w["checks"]["not_read"] for w in week.values()) == 0
    assert (agent_pr_ci.PATIENT, agent_pr_ci.PACE, agent_pr_ci.NO_WAIT) == (False, 0.0, False)               # the run's settings end with the run
    # a wait longer than the run has left: it stops, says why, and the checkpoint holds when to come back
    del slept[:]
    api = Limited(retry_after=7200, times=10**6)
    monkeypatch.setattr(agent_pr_ci, "_gh", api)
    monkeypatch.setattr(agent_pr_ci, "CACHE", str(tmp_path / "cache2"))
    state = agent_pr_index.sample_week(SAMPLE_WEEK, str(tmp_path / "long.json"), read="2026-10-05", max_requests=5000, max_minutes=50, patient=True)
    assert slept == [] and state["runs"][-1]["stopped"] == "GitHub refused a search request for a secondary rate limit" and not state["runs"][-1]["complete"]
    back = __import__("datetime").datetime.fromisoformat(state["cursor"]["come_back"]).timestamp() - time.time()
    assert 7100 < back <= 7201 and state["cursor"]["strata_counted"] == 2
    # the next run, an hour too early, asks GitHub nothing at all
    asked = len(api.asked)
    state = agent_pr_index.sample_week(SAMPLE_WEEK, str(tmp_path / "long.json"), read="2026-10-05", max_requests=5000, max_minutes=50, patient=True)
    assert len(api.asked) == asked and slept == [] and state["runs"][-1]["stopped"].startswith("GitHub said to come back at ") and state["runs"][-1]["requests"] == 0
    assert state["cursor"]["come_back"] is not None


# ---- the index scan inside the default GITHUB_TOKEN's hour -------------------------------------------------------------

class HourlyGithub:
    """`gh` as the index scan sees it, for a token with an hourly REST and GraphQL budget (1,000 each for a workflow's
    GITHUB_TOKEN). Search answers from `prs` by the `created:` range; GraphQL answers the checks of each pull request
    it names; a request past the budget is refused as GitHub refuses it (HTTP 403, x-ratelimit-remaining 0)."""

    def __init__(self, prs, core=1000, graphql=1000):
        self.prs, self.left, self.asked, self.refused = prs, {"core": core, "graphql": graphql}, [], 0

    def __call__(self, cmd):
        if cmd[2] == "graphql":
            return self._spend("graphql") or self._graphql(cmd[4].partition("=")[2])
        path, fields = cmd[4], dict(cmd[i + 1].split("=", 1) for i, x in enumerate(cmd) if x == "-f")
        if path == "rate_limit":
            return 0, json.dumps({"resources": {k: {"remaining": v, "reset": int(time.time()) + 1800} for k, v in self.left.items()}}), ""
        if path == "search/issues":
            self.asked.append(("search", fields["q"]))
            lo, hi = re.search(r"created:(\S+)\.\.(\S+)", fields["q"]).groups()
            hits = sorted((n for n, day in self.prs.items() if lo[:10] <= day <= hi[:10]), reverse=True)
            page = int(fields.get("page", 1))
            items = [{"repository_url": "https://api.github.com/repos/acme/app", "number": n, "user": {"login": "Copilot"},
                      "assignees": [], "body": "All tests pass.", "created_at": f"{self.prs[n]}T12:00:00Z"}
                     for n in hits[(page - 1) * 100:page * 100]]
            return 0, json.dumps({"total_count": len(hits), "incomplete_results": False, "items": items}), ""
        return self._spend("core") or (1, "", "gh: Not Found (HTTP 404)")

    def _spend(self, kind):
        self.asked.append((kind, None))
        if self.left[kind] <= 0:
            self.refused += 1
            reset = int(time.time()) + 1800
            return 1, _headers(403, '{"message": "API rate limit exceeded"}', **{"x-ratelimit-remaining": "0", "x-ratelimit-reset": str(reset)}), \
                "gh: API rate limit exceeded for installation ID 1. (HTTP 403)"
        self.left[kind] -= 1
        return None

    def _graphql(self, query):
        named = re.findall(r'p(\d+): repository\(owner: "([^"]+)", name: "([^"]+)"\) \{ pullRequest\(number: (\d+)\)', query)
        self.asked[-1] = ("graphql", sorted(int(n) for *_, n in named))
        run = lambda n: {"__typename": "CheckRun", "name": "test", "status": "COMPLETED", "conclusion": "FAILURE" if n % 3 == 0 else "SUCCESS"}  # noqa: E731
        data = {f"p{i}": {"pullRequest": {"merged": int(n) % 2 == 0, "commits": {"nodes": [{"commit": {
            "oid": f"{int(n):040x}", "statusCheckRollup": {"contexts": {"pageInfo": {"hasNextPage": False}, "nodes": [run(int(n))]}},
            "checkSuites": {"nodes": []}}}]}}} for i, _, _, n in named}
        return 0, json.dumps({"data": data}), ""

    def count(self, kind):
        return sum(1 for k, _ in self.asked if k == kind)


@pytest.fixture()
def hourly(tmp_path, monkeypatch):
    slept = []
    monkeypatch.setattr(agent_pr_ci, "CACHE", str(tmp_path / "cache"))
    monkeypatch.setattr(agent_pr_ci, "AGENTS", [("copilot", "author:app/copilot-swe-agent")])
    monkeypatch.setattr(agent_pr_ci.time, "sleep", slept.append)
    monkeypatch.setattr(agent_pr_ci, "START", time.time())
    return slept


def _run(api, monkeypatch, tmp_path, end, days, previous=None, now=None):
    """One scheduled run of the index job's scan and gate: (scan, index, why not published, errors)."""
    monkeypatch.setattr(agent_pr_ci, "_gh", api)
    got = agent_pr_index.scan(end, days, 800, 1200, previous=previous, reserve=200)
    got = agent_pr_index.track(got, str(tmp_path / "cache" / "unfinished_since.json"), now=now)
    index = agent_pr_index.build(got["rows"], end, got["window"], got["counts"]["excluded"])
    return got, index, agent_pr_index.gate(got, index, previous), agent_pr_index.errors(got, index, previous, now=now)


def test_the_index_scan_stops_before_the_hourly_limit_then_reads_only_what_is_new(hourly, monkeypatch, tmp_path):
    """What kept index.yml red from 5 October: the scan ran into the hourly limit of the workflow's token. Now it reads
    rate_limit (free), stops 200 short of the budget without being refused, and the job stays green; the next run
    continues from the cache, and a run a day later asks only about the pull requests opened since."""
    prs = {n: "2026-10-04" if n <= 50 else "2026-10-05" for n in range(1, 101)}
    # run 1: someone else spent most of this hour's GraphQL budget: 3 requests are left above the reserve
    api = HourlyGithub(prs, core=1000, graphql=203)
    got, index, why, bad = _run(api, monkeypatch, tmp_path, "2026-10-05", 2)
    assert api.refused == 0 and api.count("graphql") == 3 and api.count("core") == 0       # it stopped before the limit
    assert got["kept"] == 100 and got["unread"] == 40 and len(got["rows"]) == 60
    assert "used the graphql requests this hour's budget leaves it" in got["stopped"]
    assert why and "the next run continues" in why[0] and bad == []                           # green: held back, no error
    assert got["unfinished_since"] is not None and max(hourly, default=0) < 3     # and it never slept on a limit
    # run 2, the next hour: nothing is searched again, and only the 40 left are read, 20 to a request
    searched = api.count("search")
    api.left = {"core": 1000, "graphql": 1000}
    got, index, why, bad = _run(api, monkeypatch, tmp_path, "2026-10-05", 2)
    assert api.count("search") == searched and api.count("graphql") == 5 and api.count("core") == 0
    assert got["unread"] == 0 and index["n_prs"] == 100 and why == [] and bad == [] and got["unfinished_since"] is None
    assert sum(r["class"] == "failed" for r in got["rows"]) == 33 and all(isinstance(r["merged"], bool) for r in got["rows"])
    first = index
    # run 3, a day later: ten new pull requests; only they are read, in one request
    prs.update({n: "2026-10-06" for n in range(101, 111)})
    before = len(api.asked)
    got, index, why, bad = _run(api, monkeypatch, tmp_path, "2026-10-06", 3)
    assert [x for k, x in api.asked[before:] if k == "graphql"] == [list(range(101, 111))] and api.count("core") == 0
    assert index["n_prs"] == 110 and why == bad == []
    # the cache lost (evicted): the last published index fills in what it counted, so again only the new are read
    shutil.rmtree(tmp_path / "cache")
    prs.update({n: "2026-10-06" for n in range(111, 116)})
    before = len(api.asked)
    got, index, why, bad = _run(api, monkeypatch, tmp_path, "2026-10-06", 3, previous=first)
    assert got["seeded"] == 100 and [x for k, x in api.asked[before:] if k == "graphql"] == [list(range(101, 116))]
    assert index["n_prs"] == 115 and why == bad == []
    assert {json.dumps(r, sort_keys=True) for r in first["prs"]} <= {json.dumps(r, sort_keys=True) for r in index["prs"]}


def test_a_refusal_for_the_hourly_limit_ends_the_run_with_a_time_to_come_back_and_only_stalling_is_an_error(hourly, monkeypatch, tmp_path):
    """Another workflow of the repository spent the hour after the scan read rate_limit: GitHub refuses. The scan does
    not wait the half hour out inside its 20 minutes: it stops, keeps what it read, and says when to come back. Runs
    that stop early for two days are not catching up: that, and not one early stop, fails the job."""
    import datetime as dt
    prs = {n: "2026-10-05" for n in range(1, 61)}
    api = HourlyGithub(prs, graphql=1000)
    monkeypatch.setattr(agent_pr_ci, "budget", lambda reserve, read=None: agent_pr_ci.LEFT.update(core=800, graphql=800) or agent_pr_ci.LEFT)
    api.left["graphql"] = 1                          # what GitHub really has left, whatever rate_limit said a moment ago
    t0 = dt.datetime(2026, 10, 6, 0, 17, tzinfo=dt.timezone.utc)
    got, index, why, bad = _run(api, monkeypatch, tmp_path, "2026-10-05", 1, now=t0)
    assert api.refused == 1 and max(hourly, default=0) < 3 and got["unread"] == 40 and len(got["rows"]) == 20
    assert got["stopped"] == "GitHub refused a GraphQL request for a rate limit"
    back = dt.datetime.fromisoformat(got["come_back"]).timestamp() - time.time()
    assert 1700 < back <= 1802 and why and bad == []
    # still stopped early six hours on and a day on: green; two days on: an error that says what to do
    for hours, failing in ((6, False), (24, False), (48, True)):
        api.left["graphql"] = 0
        got, index, why, bad = _run(api, monkeypatch, tmp_path, "2026-10-05", 1, now=t0 + dt.timedelta(hours=hours))
        assert got["unfinished_since"] == t0.isoformat(timespec="seconds") and bool(bad) is failing, (hours, bad)
    assert "not catching up" in bad[0] and "KNOS_INDEX_TOKEN" in bad[0]
    # and one finished run clears it
    api.left["graphql"] = 1000
    got, index, why, bad = _run(api, monkeypatch, tmp_path, "2026-10-05", 1, now=t0 + dt.timedelta(hours=54))
    assert got["unfinished_since"] is None and why == bad == [] and index["n_prs"] == 60


def test_the_budget_is_what_github_says_is_left_less_the_reserve_and_the_token_s_hour_when_it_does_not_say(monkeypatch):
    monkeypatch.setattr(agent_pr_ci, "LEFT", {})
    said = json.dumps({"resources": {"core": {"remaining": 950}, "graphql": {"remaining": 120}, "search": {"remaining": 30}}})
    assert agent_pr_ci.budget(200, read=lambda cmd: (0, said, "")) == {"core": 750, "graphql": 0}
    assert agent_pr_ci.budget(200, read=lambda cmd: (1, "", "gh: Bad Gateway (HTTP 502)")) == {"core": 800, "graphql": 800}
    # a run with no budget left sends nothing and says why
    monkeypatch.setattr(agent_pr_ci, "ARGS", SimpleNamespace(max_seconds=10_000))
    monkeypatch.setattr(agent_pr_ci, "START", time.time())
    monkeypatch.setattr(agent_pr_ci, "STOPPED", [None])
    agent_pr_ci.LEFT.update(graphql=0)
    with pytest.raises(agent_pr_ci.OutOfBudget):
        agent_pr_ci._spend("graphql")
    assert "graphql" in agent_pr_ci.STOPPED[0]
    agent_pr_ci._spend("search")                     # search has its own limit, a minute long, kept by its pause
