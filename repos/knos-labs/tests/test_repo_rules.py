"""Sibyl on the money path: a PR is checked against the repo's own rules (CONTRIBUTING.md, recalled from Sibyl, and
the rules past rejections taught) before anything is proven or minted, each violation citing the line."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from knos.proof import checks, engine, history

CONTRIBUTING = """# Contributing

Thanks for helping.

- Please do not add new dependencies without an issue first.
- Tests are required for every change under src/.
- Use Conventional Commits for every commit message.
- Never leave print( or console.log debug output in code.
- Do not edit `CHANGELOG.md`; the release script writes it.
"""


def _git(repo: Path, *a: str) -> str:
    return subprocess.run(["git", *a], cwd=str(repo), check=True, capture_output=True, text=True).stdout


@pytest.fixture()
def pr_repo(tmp_path):
    r = tmp_path / "proj"
    (r / "src").mkdir(parents=True)
    (r / "CONTRIBUTING.md").write_text(CONTRIBUTING, encoding="utf-8")
    (r / "pyproject.toml").write_text('[project]\nname = "proj"\nversion = "0.1.0"\ndependencies = [\n'
                                      '    "click>=8",\n]\n', encoding="utf-8")
    (r / "src" / "app.py").write_text("def run():\n    return 1\n", encoding="utf-8")
    _git(r, "init", "-q", "-b", "main")
    _git(r, "config", "user.email", "dev@example.com")
    _git(r, "config", "user.name", "Dev")
    _git(r, "add", "-A")
    _git(r, "commit", "-q", "-m", "chore: initial")
    _git(r, "checkout", "-q", "-b", "feature")
    (r / "pyproject.toml").write_text('[project]\nname = "proj"\nversion = "0.1.0"\ndependencies = [\n'
                                      '    "click>=8",\n    "requests>=2.31",\n]\n', encoding="utf-8")
    (r / "src" / "app.py").write_text("def run():\n    print('here')\n    return 2\n", encoding="utf-8")
    _git(r, "add", "-A")
    _git(r, "commit", "-q", "-m", "Added requests and tweaked run")
    return r


def _sibyl(tmp_path):
    try:
        from sibyl_memory_client import MemoryClient
    except ImportError:
        return history.NullStore()
    return history.SibylStore(MemoryClient.local(str(tmp_path / "sibyl.db"), tenant_id="repo"))


class _Fake:
    """NullStore-compatible store that keeps what it is given (when no Sibyl client is installed)."""

    def __init__(self):
        self.rows: dict = {}

    def put(self, category, name, body):
        self.rows.setdefault(category, {})[name] = body

    def all(self, category):
        return list(self.rows.get(category, {}).values())


def _store(tmp_path):
    s = _sibyl(tmp_path)
    return _Fake() if isinstance(s, history.NullStore) else s


def test_contributing_parses_into_rules_citing_their_lines():
    got = {r["kind"]: r for r in history.parse_contributing(CONTRIBUTING)}
    assert set(got) == {"no_new_deps", "tests_required", "conventional_commits", "no_debug", "no_edit"}
    assert got["no_new_deps"]["source"] == "CONTRIBUTING.md:5"
    assert got["no_edit"]["param"] == "CHANGELOG.md"
    small = history.parse_contributing("Keep PRs small.\nSigned-off-by is required (DCO).\nAt most 3 lines.\n")
    assert {(r["kind"], r.get("param")) for r in small} == {("max_lines", 400), ("signoff", None), ("max_lines", 3)}


def test_a_pr_breaking_a_rule_fails_citing_the_line(tmp_path, pr_repo):
    store = _store(tmp_path)
    diff, commits = engine.pr(pr_repo, {})
    got = history.lint_pr(store, pr_repo, diff, commits)
    said = [str(v) for v in got]
    assert any(s.startswith("pyproject.toml:6: '\"requests>=2.31\",' breaks CONTRIBUTING.md:5") for s in said), said
    assert any(s.startswith("src/app.py:2: \"print('here')\" breaks CONTRIBUTING.md:8") for s in said), said
    assert any("breaks CONTRIBUTING.md:6" in s and "no test changed" in s for s in said), said
    assert any(s.startswith("commit ") and "Added requests" in s and "CONTRIBUTING.md:7" in s for s in said), said
    # parsed once, then recalled from the store
    assert {r["origin"] for r in store.all("repo_rule")} == {"contributing"}
    assert len(history.repo_rules(store, pr_repo)) == 5 and len(store.all("repo_rule")) == 5
    # a clean PR keeps every rule
    clean = "diff --git a/README.md b/README.md\n--- a/README.md\n+++ b/README.md\n@@ -1,0 +1,1 @@\n+hello\n"
    assert history.lint_pr(store, pr_repo, clean, ["docs: hello"]) == []


def test_evaluate_runs_repo_rules_first_and_fails_before_anything_else(tmp_path, pr_repo):
    store = _store(tmp_path)
    ran = []
    runners = {"tests": lambda r, c, cfg: ran.append("tests") or checks.Result("tests", True, "ok")}
    v = engine.evaluate(pr_repo, "Done: all tests pass.", store, runners, use_cache=False)
    assert not v.ok and ran == []                       # nothing ran past the violation
    assert [r.name for r in v.results] == ["repo-rules"]
    assert "pyproject.toml:6" in v.explain() and "CONTRIBUTING.md:5" in v.explain()


def test_learn_makes_a_flagged_rule_required_next_time(tmp_path, pr_repo):
    store = _store(tmp_path)
    diff, commits = engine.pr(pr_repo, {})
    flagged = [v for v in history.lint_pr(store, pr_repo, diff, commits) if v.rule["kind"] == "no_new_deps"]
    history.learn(store, flagged)
    req = history.required(store, {"tests"})
    assert len(req) == 1 and next(iter(req)).startswith("rule:")
    # the CONTRIBUTING file goes; the learned rule is still required, and still fails the same PR
    (pr_repo / "CONTRIBUTING.md").unlink()
    _git(pr_repo, "commit", "-qam", "chore: drop contributing")
    v = engine.evaluate(pr_repo, "Done: all tests pass.", store,
                        {"tests": lambda r, c, cfg: checks.Result("tests", True, "ok")}, use_cache=False)
    assert not v.ok and v.results[0].name.startswith("rule:")
    assert "pyproject.toml:6" in v.results[0].detail and v.required_by_history == req


def test_a_repo_with_no_rules_is_unchanged(tmp_path, repo):
    v = engine.evaluate(repo, "Done: all tests pass.", history.NullStore(),
                        {"tests": lambda r, c, cfg: checks.Result("tests", True, "ok")}, use_cache=False)
    assert v.ok and [r.name for r in v.results] == ["tests"]
