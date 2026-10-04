"""scripts/backtest_paid.py: of the merged pull requests that were paid a bounty on Algora or Opire, how many had a failed
check. Offline: GitHub's answers are recorded in the shapes its REST API documents (search/issues, issue timeline, comments,
pulls, commit status, check runs) and handed to the script as `get`. Until the release run, the committed document says `not
run`; once the release run has filled it, the document and the block of docs/BENCH.md are the script's own output, and its
numbers add up."""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import agent_pr_index  # noqa: E402
import backtest_paid as bp  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
AWARD = "🎉🎈 @{u} has been awarded $100! 🎈🎊"


def issue(repo, n):
    return {"repository_url": f"https://api.github.com/repos/{repo}", "number": n, "created_at": "2026-09-01T00:00:00Z",
            "html_url": f"https://github.com/{repo}/issues/{n}"}


def xref(repo, n, merged=True):
    return {"event": "cross-referenced", "source": {"type": "issue", "issue": {
        "number": n, "repository": {"full_name": repo}, "pull_request": {"merged_at": "2026-09-02T00:00:00Z" if merged else None}}}}


def pull(login, merged=True, head="h" * 40, merge="m" * 40, body=""):
    return {"merged_at": "2026-09-02T00:00:00Z" if merged else None, "user": {"login": login}, "body": body,
            "head": {"sha": head}, "merge_commit_sha": merge}


def note(login, body, n=1, bot=True):
    return {"user": {"login": login, "type": "Bot" if bot else "User"}, "body": body, "html_url": f"https://github.com/c/c/issues/{n}#c1"}


def ci(*conclusions, statuses=()):
    runs = [{"name": f"job{i}", "status": "completed", "conclusion": c} for i, c in enumerate(conclusions)]
    return {"status": {"sha": "x", "statuses": [{"context": c, "state": s} for c, s in statuses]}, "runs": {"check_runs": runs}}


class GitHub:
    """A recorded GitHub: answers by path (and, for search, by the label or text in the query)."""
    def __init__(self):
        self.search, self.paths, self.asked = {}, {}, []

    def __call__(self, path, params=None, kind="core", max_age=None):
        self.asked.append((path, (params or {}).get("q")))
        if path == "search/issues":
            q = params["q"]
            hit = next((v for k, v in self.search.items() if k in q), [])
            return {"ok": True, "json": {"items": hit if (params or {}).get("page", 1) == 1 else []}}
        return {"ok": True, "json": self.paths[path]} if path in self.paths else {"ok": False, "error": "HTTP 404"}

    def commit(self, repo, sha, recorded):
        self.paths[f"repos/{repo}/commits/{sha}/status"] = recorded["status"]
        self.paths[f"repos/{repo}/commits/{sha}/check-runs"] = recorded["runs"]

    def bounty(self, repo, n, pr_repo, pr_n, **kw):
        self.paths[f"repos/{repo}/issues/{n}/timeline"] = [{"event": "labeled"}, xref(pr_repo, pr_n, kw.get("merged", True))]
        self.paths[f"repos/{pr_repo}/pulls/{pr_n}"] = pull(kw["author"], kw.get("merged", True), kw.get("head", "h" * 40),
                                                           kw.get("merge", "m" * 40), kw.get("body", ""))
        self.paths[f"repos/{repo}/issues/{n}/comments"] = kw.get("issue_comments", [])
        self.paths[f"repos/{pr_repo}/issues/{pr_n}/comments"] = kw.get("pr_comments", [])


def world():
    gh = GitHub()
    gh.search = {'label:"💎 Bounty"': [issue("a/x", 1), issue("a/x", 2), issue("a/x", 3), issue("a/x", 4), issue("a/x", 5)],
                 'reward using Opire': [issue("b/y", 6)], 'label:"🎁 Reward"': [issue("b/y", 6)]}
    # 1: paid, and a check failed at the head
    gh.bounty("a/x", 1, "a/x", 11, author="alice", head="1" * 40, merge="2" * 40,
              issue_comments=[note("algora-pbc[bot]", AWARD.format(u="alice"), 1)], body="/claim #1")
    gh.commit("a/x", "1" * 40, ci("success", "failure"))
    gh.commit("a/x", "2" * 40, ci("success"))
    # 2: paid, everything green at both commits
    gh.bounty("a/x", 2, "a/x", 12, author="bob", head="3" * 40, merge="4" * 40,
              pr_comments=[note("algora-pbc[bot]", "@bob has been awarded $50 by Org", 12)])
    gh.commit("a/x", "3" * 40, ci("success", "skipped"))
    gh.commit("a/x", "4" * 40, ci("success"))
    # 3: a merged pull request that closes a bounty issue, and no word about payment: counted, not paid
    gh.bounty("a/x", 3, "a/x", 13, author="carol", issue_comments=[note("algora-pbc[bot]", "💎 $100 bounty • Org", 3)])
    # 4: the award names somebody else, and a human says "paid" (not the bot): not paid
    gh.bounty("a/x", 4, "a/x", 14, author="dave", issue_comments=[note("algora-pbc[bot]", AWARD.format(u="erin"), 4),
                                                                  note("zed", "@dave paid", 4, bot=False)])
    # 5: paid, but the pull request was not merged
    gh.bounty("a/x", 5, "a/x", 15, author="fay", merged=False, issue_comments=[note("algora-pbc[bot]", AWARD.format(u="fay"), 5)])
    # 6: Opire, paid, a failed commit status at the head and green at the merge commit
    gh.bounty("b/y", 6, "c/z", 16, author="gus", head="5" * 40, merge="6" * 40,
              issue_comments=[note("opirebot[bot]", "@gus was rewarded $30 for this issue", 6)])
    gh.commit("c/z", "5" * 40, ci("success", statuses=[("legacy-ci", "failure")]))
    gh.commit("c/z", "6" * 40, ci("success"))
    return gh


def test_the_recorded_world_is_counted_paid_merged_and_failed_at_the_head_and_the_merge():
    out = bp.run(world(), dt.date(2026, 10, 1), 30, 1, 100)
    assert out["status"] == "run" and out["window"] == ["2026-09-02", "2026-10-01"]
    assert (out["issues"], out["merged_prs"], out["unpaid"]) == (6, 5, 2)         # issue 5's pull request was never merged
    p = out["paid"]
    assert p["paid"] == 3 and p["not_classified"] == 0
    assert p["failed_at_head"] == {"of": 3, "prs": 2, "share": 0.6667, "ci95": agent_pr_index.wilson(2, 3)}
    assert p["failed_at_merge"]["prs"] == 0 and p["failed_at_head_or_merge"]["prs"] == 2
    assert out["claimed_among_paid"] == 1
    assert out["platforms"]["algora"]["paid"]["paid"] == 2 and out["platforms"]["opire"]["paid"]["failed_at_head"]["prs"] == 1
    assert {e["pr"] for e in out["evidence"]} == {"a/x#11", "a/x#12", "c/z#16"}       # each paid one names the comment it rests on
    assert all(e["comment"].startswith("https://github.com/") for e in out["evidence"])
    assert any(line.startswith("How a platform marks a PAID bounty") for line in out["cannot_show"])
    assert json.loads(json.dumps(out)) == out


def test_only_the_platforms_bot_naming_the_author_next_to_a_paid_word_counts_as_paid():
    bot = lambda text: [note("algora-pbc[bot]", text)]                                    # noqa: E731
    assert bp.paid_comment(bot("🎉🎈 @alice has been awarded $100!"), "alice")
    assert bp.paid_comment(bot("$100 was paid out to @Alice"), "alice")                  # either order, any case
    assert bp.paid_comment(bot("💡 @alice submitted a pull request that claims the bounty"), "alice") is None
    assert bp.paid_comment(bot("💎 $100 bounty • Org"), "alice") is None
    assert bp.paid_comment(bot("@alice123 has been awarded $5"), "alice") is None         # another login that starts the same
    assert bp.paid_comment(bot("@bob has been awarded $5. Thanks @alice!"), "alice") is None


def test_a_check_state_is_read_the_way_the_agent_index_reads_it():
    gh = GitHub()
    for sha, recorded, want in (("a", ci("success"), "passed"), ("b", ci("success", "failure"), "failed"),
                                ("c", ci("success", "cancelled"), "other"), ("d", ci(), "no-ci"),
                                ("e", ci("success", statuses=[("x", "error")]), "failed"), ("f", ci("success", statuses=[("x", "pending")]), "pending")):
        gh.commit("r/r", sha, recorded)
        assert bp.check_state("r/r", sha, gh)["class"] == want
    gh.paths["repos/r/r/commits/g/check-runs"] = {"check_runs": [{"name": "late", "status": "in_progress", "conclusion": None}]}
    gh.paths["repos/r/r/commits/g/status"] = {"statuses": []}
    assert bp.check_state("r/r", "g", gh)["class"] == "pending"
    assert bp.check_state("r/r", "nope", gh)["class"] == "error"


def test_windows_and_queries_cover_the_labels_and_the_opire_text():
    wins = bp.windows(dt.date(2026, 10, 1), 30, 3)
    assert wins[0] == ("2026-09-02", "2026-10-01") and wins[1][1] == "2026-09-01" and wins[2][0] == "2026-07-04"
    assert bp.queries("algora", "2026-09-02", "2026-10-01") == ['label:"💎 Bounty" is:issue is:closed created:2026-09-02..2026-10-01']
    assert len(bp.queries("opire", "a", "b")) == 2 and "reward using Opire" in bp.queries("opire", "a", "b")[1]


def test_the_document_and_the_block_say_not_run_until_the_release_run_fills_them_and_then_are_the_scripts_own(tmp_path):
    committed = json.loads((ROOT / "docs" / "backtest_paid.json").read_text(encoding="utf-8"))
    bench = (ROOT / "docs" / "BENCH.md").read_text(encoding="utf-8")
    block = bench.split("<!-- backtest_paid:begin -->")[1].split("<!-- backtest_paid:end -->")[0]
    # the block is exactly what the script writes from the committed document: not one word of it typed by hand
    assert bp.update_bench(bench, committed) == bench
    if committed["status"] == "not run":
        assert "paid" not in committed and "issues" not in committed
        assert "**Not run.**" in block and "%" not in block and "Wilson" not in block and "| platform |" not in block
    else:
        # the release run filled them: the whole of a run's document, and its counts add up
        assert committed["status"] == "run" and {"read", "window", "queries", "issues", "merged_prs", "paid", "unpaid", "platforms",
                                                 "evidence", "cannot_show"} <= set(committed)
        p, platforms = committed["paid"], committed["platforms"].values()
        assert committed["merged_prs"] == p["paid"] + committed["unpaid"]
        assert committed["issues"] == sum(v["issues"] for v in platforms) and p["paid"] == sum(v["paid"]["paid"] for v in platforms)
        assert len(committed["evidence"]) == min(p["paid"], 200) and all(e["comment"].startswith("https://github.com/") for e in committed["evidence"])
        for name in ("failed_at_head", "failed_at_merge", "failed_at_head_or_merge"):
            s = p[name]
            assert 0 <= s["prs"] <= s["of"] <= p["paid"] and s["ci95"] == agent_pr_index.wilson(s["prs"], s["of"])
        assert "**Not run.**" not in block and f"{p['failed_at_head']['prs']} of {p['failed_at_head']['of']}" in block and "| platform |" in block
    # the same run on the recorded world fills the block and the file; running `--not-run` again puts the words back
    empty = bp.update_bench(bench, bp.not_run())
    out = bp.run(world(), dt.date(2026, 10, 1), 30, 1, 100)
    filled = bp.update_bench(empty, out)
    assert "**At the head commit, 2 of 3 (66.7%) had a failed check**" in filled and "Not run." not in filled.split("backtest_paid:begin")[1].split("backtest_paid:end")[0]
    assert bp.update_bench(filled, bp.not_run()) == empty
    docs, bench_copy = tmp_path / "out.json", tmp_path / "BENCH.md"
    bench_copy.write_text(bench, encoding="utf-8")
    assert bp.main(["--not-run", "--out", str(docs), "--bench", str(bench_copy)]) == 0
    assert json.loads(docs.read_text(encoding="utf-8")) == json.loads(json.dumps(bp.not_run())) and bench_copy.read_text(encoding="utf-8") == empty
    assert committed["status"] == "run" or json.loads(docs.read_text(encoding="utf-8")) == committed


def test_main_reads_through_the_cached_gh_reader_and_stops_when_out_of_time(tmp_path, monkeypatch):
    import agent_pr_ci
    monkeypatch.setattr(agent_pr_ci, "gh_get", world())
    out, bench = tmp_path / "o.json", tmp_path / "BENCH.md"
    bench.write_text("# Measurements\n\n<!-- /bench:backtest -->\n", encoding="utf-8")
    assert bp.main(["--end", "2026-10-01", "--windows", "1", "--out", str(out), "--bench", str(bench)]) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["paid"]["paid"] == 3
    assert "backtest_paid:begin" in bench.read_text(encoding="utf-8")

    def out_of_time(*a, **k):
        raise agent_pr_ci.OutOfTime()
    monkeypatch.setattr(agent_pr_ci, "gh_get", out_of_time)
    assert bp.main(["--end", "2026-10-01", "--windows", "1", "--out", str(out), "--bench", str(bench)]) == 1
