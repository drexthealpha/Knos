"""The Agent PR Index, offline: fixture PRs through agent_pr_ci's classification, then a deterministic Merkle root;
Wilson intervals, self-repo exclusion, and proven counts by distinct funder from devnet escrow transactions."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import agent_pr_ci  # noqa: E402
import agent_pr_index  # noqa: E402

RUNS = {
    "aaa": [{"name": "build", "status": "completed", "conclusion": "failure"},
            {"name": "Copilot", "status": "completed", "conclusion": "success"}],
    "bbb": [{"name": "test", "status": "completed", "conclusion": "success"}],
    "ccc": [{"name": "Copilot", "status": "completed", "conclusion": "failure"}],  # agent's own run only
}
WINDOW = ("2026-09-25", "2026-10-01")


def fake_gh(path, params=None, kind="core"):
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
    assert a["agents"]["copilot"] == {"claimed_green": 1, "actually_failed": 1, "share": 1.0,
                                      "ci95": agent_pr_index.wilson(1, 1), "proven": 0}
    assert a["agents"]["codex"]["share"] == 0.0 and a["agents"]["codex"]["ci95"][0] == 0.0
    assert a["agents"]["devin"] == {"claimed_green": 0, "actually_failed": 0, "share": None, "ci95": None,
                                    "proven": 0}  # no CI is not green
    assert a["overall"]["claimed_green"] == 2 and a["overall"]["actually_failed"] == 1
    assert set(a["prs"][0]) == set(agent_pr_index.PR_KEYS)
    assert a["n_prs"] == 2  # the no-CI PR is not listed: only finished CI at the head SHA counts

    claimed[1]["class"] = "failed"  # any change to a counted record changes the root
    assert agent_pr_index.build(claimed, "2026-10-01", WINDOW)["root"] != a["root"]


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


def test_scan_windows_cover_the_range_newest_first():
    w = agent_pr_ci.scan_windows("2026-10-01", 10, 3)
    assert w[0] == ("2026-09-29", "2026-10-01") and w[-1] == ("2026-09-22", "2026-09-22") and len(w) == 4


def test_scan_excludes_self_repos_and_counts_them(monkeypatch):
    items = [dict(item("alice", "alice"), number=1, body="All tests pass.", created_at="t"),
             dict(item("acme", "alice"), number=2, body="All tests pass.", created_at="t"),
             dict(item("acme", "bob"), number=3, body="no claim here", created_at="t")]
    monkeypatch.setattr(agent_pr_ci, "gh_get", lambda *a, **k: {"ok": True, "json": {"items": items}})
    kept, n = agent_pr_ci.scan_agent("codex", "x", "2026-10-01", 2, 10)
    assert [k["number"] for k in kept] == [2] and n == {"hits": 3, "excluded": 1, "no_claim": 1}


def test_proven_counts_distinct_funders_only():
    pays = [{"worker": "W", "funder": "F1", "verified": True}, {"worker": "W", "funder": "F1", "verified": True},
            {"worker": "W", "funder": "F2", "verified": True}, {"worker": "W", "funder": "F3", "verified": False},
            {"worker": "V", "funder": "F1", "verified": True}]
    assert agent_pr_index.distinct_funders(pays) == {"V": 1, "W": 2}  # repeat payouts from one funder count once


def test_payments_from_devnet_tx():
    keys = ["signer", "job", "vault", "auth", "workerTok", "fee", "cfg", "token", "buyer", "PROG"]
    ix = {"programIdIndex": 9, "accounts": list(range(9)), "data": "C"}  # base58 "C" = byte 11, verify_release
    tx = {"meta": {"err": None}, "transaction": {"message": {"accountKeys": keys, "instructions": [ix]}}}
    assert agent_pr_index.payments_from_tx(tx, "PROG") == [{"worker": "workerTok", "funder": "buyer",
                                                            "verified": True}]
    assert agent_pr_index.payments_from_tx(tx, "OTHER") == []
    assert agent_pr_index.payments_from_tx({**tx, "meta": {"err": {"x": 1}}}, "PROG") == []  # failed tx pays nothing
    ix["data"] = "2"  # byte 1: not a verified release
    assert agent_pr_index.payments_from_tx(tx, "PROG") == []
    idx = agent_pr_index.build([], "2026-10-02", ("a", "b"), excluded=7,
                               payments=[{"worker": "W", "funder": "F", "verified": True}])
    assert idx["proven"] == {"W": 1} and idx["excluded_self_repo"] == 7 and idx["n_prs"] == 0


def test_attest_refuses_a_tampered_list(tmp_path, monkeypatch):
    import json

    import pytest
    idx = agent_pr_index.build([{"agent": "codex", "repo": "o/r", "number": 1, "sha": "a", "class": "failed"}],
                               "2026-10-02", ("a", "b"))
    calls = []
    monkeypatch.setattr(agent_pr_index, "attest", lambda index, key: calls.append(index["root"]))
    p = tmp_path / "index.json"
    p.write_text(json.dumps(idx), encoding="utf-8")
    assert agent_pr_index.attest_file(str(p), "[]")["root"] == idx["root"] and calls == [idx["root"]]
    idx["prs"][0]["class"] = "passed"  # edited after the count: the root no longer matches, nothing is attested
    p.write_text(json.dumps(idx), encoding="utf-8")
    with pytest.raises(SystemExit):
        agent_pr_index.attest_file(str(p), "[]")
    assert len(calls) == 1
