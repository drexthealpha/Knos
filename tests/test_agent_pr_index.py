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
    assert [k["number"] for k in kept] == [2] and n == {"hits": 3, "excluded": 1, "no_claim": 1, "cut_short": 0} and finished
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


def test_a_search_that_runs_out_of_time_keeps_what_the_others_found_and_the_gate_refuses_it(github, monkeypatch, tmp_path):
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
    assert len(why) == 1 and "did not finish for codex" in why[0] and "run the workflow again" in why[0]
    # the same through the command the workflow runs: it exits 1 and says why
    (tmp_path / "rows.json").write_text(json.dumps(got), encoding="utf-8")
    (tmp_path / "index.json").write_text(json.dumps(index), encoding="utf-8")
    cli = [sys.executable, str(ROOT / "scripts" / "agent_pr_index.py"), "gate", "--rows", str(tmp_path / "rows.json"),
           "--out", str(tmp_path / "index.json"), "--previous", str(tmp_path / "none.json")]
    r = subprocess.run(cli, capture_output=True, text=True, check=False)
    assert r.returncode == 1 and "not published: the search did not finish for codex" in r.stderr
    got["unfinished_search"] = []
    (tmp_path / "rows.json").write_text(json.dumps(got), encoding="utf-8")
    r = subprocess.run(cli, capture_output=True, text=True, check=False)
    assert r.returncode == 0 and "publish it" in r.stderr


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


def test_the_scheduled_run_publishes_or_fails_and_keeps_its_answers_either_way():
    yaml = pytest.importorskip("yaml")
    doc = yaml.safe_load((ROOT / ".github" / "workflows" / "index.yml").read_text(encoding="utf-8"))
    assert doc[True]["schedule"] == [{"cron": "17 */6 * * *"}, {"cron": "43 5 * * 1"}]   # `on`: every 6 hours, as the docs say; Mondays for the weekly job
    steps = doc["jobs"]["index"]["steps"]
    runs = [str(s.get("run", "")) for s in steps]
    scan = next(i for i, r in enumerate(runs) if "agent_pr_index.py scan" in r)
    gate = next(i for i, r in enumerate(runs) if "agent_pr_index.py gate" in r)
    release = next(i for i, r in enumerate(runs) if "gh release create" in r)
    save = next(i for i, s in enumerate(steps) if str(s.get("uses", "")).startswith("actions/cache/save@"))
    restore = next(i for i, s in enumerate(steps) if str(s.get("uses", "")).startswith("actions/cache/restore@"))
    assert restore < scan < save < gate < release
    assert steps[save]["if"] == "always()"                                    # a run that fails still leaves its answers
    assert steps[save]["with"]["path"] == steps[restore]["with"]["path"] == "~/.cache/knos-agent-pr-ci"
    assert not any(str(s.get("uses", "")).startswith("actions/cache@") for s in steps)    # that one saves only on success
    # no step decides, quietly, to publish nothing: a step that does not publish fails
    for r in runs:
        assert "exit 0" not in r and "|| true" not in r, r
    assert "if" not in steps[gate] and "if" not in steps[release] and "continue-on-error" not in json.dumps(steps)
    # and the gate asks for nothing the scan cannot reach: before, 480 an agent could keep 2,400 and 2,000 had to have
    # finished CI; now the floor is half the last index (1,216 after the 2,431 one) and the scan may keep 4,000
    per_agent = int(runs[scan].split("--per-agent")[1].split()[0])
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
    assert first == {"week": "2026-09-21", "sampled": 5, "claimed_passing": 4, "ci_finished": 3,
                     "failed_a_check": {"k": 2, "n": 3, "share": 0.6667, "ci95": agent_pr_index.wilson(2, 3), "test_or_build": 1},
                     "merged_despite_failed_check": {"k": 1, "n": 2, "share": 0.5, "ci95": agent_pr_index.wilson(1, 2)}}
    assert second["week"] == "2026-09-28" and second["sampled"] == 1 and second["failed_a_check"]["k"] == 0
    assert got["agents"]["copilot"]["all_weeks"]["failed_a_check"]["n"] == 4
    assert got["agents"]["devin"]["weeks"][0]["merged_despite_failed_check"] is None      # not read is null, never 0
    assert got["agents"]["codex"]["weeks"] == [{"week": "2026-09-28", "sampled": 1, "claimed_passing": 0, "ci_finished": 0,
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


def test_the_committed_weekly_file_is_the_committed_sample_cut_by_week_and_the_page_shows_its_table(tmp_path):
    """Nothing in docs/agent_weekly.json is typed by hand: it is docs/agent_pr_ci.json reshaped, and docs/INDEX.md
    holds exactly the table the script renders from it, and says what the numbers cannot say."""
    out, doc = tmp_path / "weekly.json", tmp_path / "INDEX.md"
    doc.write_text((ROOT / "docs" / "INDEX.md").read_text(encoding="utf-8"), encoding="utf-8")
    assert subprocess.run([sys.executable, str(ROOT / "scripts" / "agent_pr_index.py"), "weekly", "--sample", "docs/agent_pr_ci.json",
                           "--out", str(out), "--doc", str(doc)], cwd=ROOT, capture_output=True, text=True).returncode == 0
    series = json.loads(out.read_text(encoding="utf-8"))
    assert series == json.loads((ROOT / "docs" / "agent_weekly.json").read_text(encoding="utf-8"))
    page = (ROOT / "docs" / "INDEX.md").read_text(encoding="utf-8")
    assert doc.read_text(encoding="utf-8") == page and agent_pr_index.weekly_table(series) in page
    sample = json.loads((ROOT / "docs" / "agent_pr_ci.json").read_text(encoding="utf-8"))
    assert series["read"] == sample["generated_utc"][:10] and "nothing was read again" in series["source"]
    for name, agent in series["agents"].items():
        s = sample["summary"][name]
        assert agent["all_weeks"]["claimed_passing"] == s["N"] == sum(w["claimed_passing"] for w in agent["weeks"])
        assert agent["all_weeks"]["failed_a_check"] == {"k": s["failed"], "n": s["with_completed_ci"], "share": s["share_failed_among_completed_ci"],
                                                        "ci95": agent_pr_index.wilson(s["failed"], s["with_completed_ci"]), "test_or_build": s["failed_testish"]}
        assert all(w["sampled"] is None for w in agent["weeks"])                 # the sample kept no date for the hits it set aside
    for words in ("Bot-author heuristics", "Public repositories only", "One snapshot of the checks", "Wilson"):
        assert words in page
    with pytest.raises(SystemExit):
        (tmp_path / "bare.md").write_text("no markers", encoding="utf-8")
        agent_pr_index.render_doc(str(tmp_path / "bare.md"), series)


def test_the_weekly_job_opens_a_pull_request_and_merges_nothing():
    yaml = pytest.importorskip("yaml")
    doc = yaml.safe_load((ROOT / ".github" / "workflows" / "index.yml").read_text(encoding="utf-8"))
    job = doc["jobs"]["weekly"]
    assert job["if"] == "github.event.schedule == '43 5 * * 1' || github.event_name == 'workflow_dispatch'"
    runs = "\n".join(str(s.get("run", "")) for s in job["steps"])
    assert "gh pr create" in runs and "gh pr merge" not in runs and "origin main" not in runs
    assert job["permissions"] == {"contents": "write", "pull-requests": "write"}
    index = "\n".join(str(s.get("run", "")) for s in doc["jobs"]["index"]["steps"])
    assert "agent_pr_index.py weekly --rows rows.json --out agent_weekly.json" in index and "index.json agent_weekly.json" in index
