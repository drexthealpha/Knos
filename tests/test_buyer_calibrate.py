"""`knos task calibrate`, `knos task judge` and the from-base warning: the buyer pains V34DOG hit while buying v0.3.34.

    - a sealed test that reads pyproject.toml (or setup.cfg, pytest.ini, tox.ini, conftest.py) sees the BASE's copy,
      because the judge takes those from the base: `check_bundle` now says so before sealing;
    - hidden tests were sealed in public before anyone knew whether the base fails them and a correct solution passes:
      `calibrate` judges both first;
    - work delivered as a patch had no judging command: `trees` builds the base and the delivered tree;
    - a `/knos take` reservation could outlast the vault (`reservation_days`).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from knos import buyer
from knos.cli import reservation_days


def _git(cwd: Path, *args: str) -> str:
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@example.invalid", "PATH": "/usr/bin:/bin", "HOME": str(cwd)}
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True, env=env).stdout.strip()


def _bundle(at: Path, want: int, *, extra: str = "") -> Path:
    """A black-box bundle: the delivered src/m.py's f() must return `want`. Reached only through $KNOS_RUN."""
    at.mkdir(parents=True)
    (at / "blackbox.py").write_text(
        "import os, subprocess, sys\n"
        f"# {extra}\n"
        "code = 'import sys; sys.path.insert(0, \"src\"); import m; sys.exit(0 if m.f() == %d else 1)'\n"
        f"r = subprocess.run([os.environ['KNOS_RUN'], {sys.executable!r}, '-c', code])\n"
        "print('rule 1 met' if r.returncode == 0 else 'rules not met: 1')\n"
        "sys.exit(r.returncode)\n" % want, encoding="utf-8")
    return at


@pytest.fixture()
def repo(tmp_path: Path) -> tuple[Path, str, Path]:
    """A small repository at one commit, and a patch that makes f() return 1 (the 'delivered work')."""
    r = tmp_path / "repo"
    (r / "src").mkdir(parents=True)
    (r / "src" / "m.py").write_text("def f():\n    return 0\n", encoding="utf-8")
    _git(r, "init", "-q")
    _git(r, "add", "-A")
    _git(r, "commit", "-q", "-m", "base")
    sha = _git(r, "rev-parse", "HEAD")
    (r / "src" / "m.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    patch = tmp_path / "work.patch"
    patch.write_text(_git(r, "diff", "--binary") + "\n", encoding="utf-8")
    _git(r, "checkout", "-q", "--", ".")
    return r, sha, patch


def test_a_bundle_that_reads_a_file_the_judge_takes_from_the_base_is_warned_about(tmp_path):
    files = {"blackbox.py": b"KNOS_RUN cat pyproject.toml; cat src/conftest.py", "x.txt": b"mypyproject.toml.bak pytest.ini2"}
    assert buyer.from_base_reads(files) == ["pyproject.toml", "conftest.py"]
    assert buyer.from_base_reads({"blackbox.py": b"KNOS_RUN cat server.json"}) == []
    b = _bundle(tmp_path / "b", 1, extra="reads pyproject.toml for the version")
    notes = buyer.check_bundle(b)
    assert any("pyproject.toml" in n and "BASE" in n for n in notes)
    assert not any("BASE" in n for n in buyer.check_bundle(_bundle(tmp_path / "c", 1)))


def test_trees_builds_the_base_and_the_delivered_tree_from_a_commit_and_a_patch(repo, tmp_path):
    r, sha, patch = repo
    base, pr = buyer.trees(sha, patch, repo=r, into=tmp_path / "t")
    assert "return 0" in (base / "src" / "m.py").read_text() and "return 1" in (pr / "src" / "m.py").read_text()
    assert not (base / ".git").exists() and not (pr / ".git").exists()


def test_trees_refuses_a_patch_that_does_not_apply(repo, tmp_path):
    r, sha, _ = repo
    bad = tmp_path / "bad.patch"
    bad.write_text("diff --git a/src/m.py b/src/m.py\n--- a/src/m.py\n+++ b/src/m.py\n@@ -1,2 +1,2 @@\n def g():\n-    return 9\n+    return 8\n",
                   encoding="utf-8")
    with pytest.raises(buyer.Refused, match="does not apply"):
        buyer.trees(sha, bad, repo=r, into=tmp_path / "t")
    with pytest.raises(buyer.Refused, match="git archive"):
        buyer.trees("0" * 40, bad, repo=r, into=tmp_path / "u")


def test_calibrate_passes_only_when_the_base_fails_and_the_reference_passes(repo, tmp_path):
    r, sha, patch = repo
    base, ref = buyer.trees(sha, patch, repo=r, into=tmp_path / "t")
    good = buyer.calibrate(_bundle(tmp_path / "good", 1), base, ref)
    assert good["ok"] is True and good["base"]["passed"] is False and good["reference"]["passed"] is True
    # tests that the reference fails: they would refuse honest work
    strict = buyer.calibrate(_bundle(tmp_path / "strict", 2), base, ref)
    assert strict["ok"] is False and any("refuse honest work" in s for s in strict["said"])
    # tests the unchanged base already passes: they would pay for nothing
    loose = buyer.calibrate(_bundle(tmp_path / "loose", 0), base, ref)
    assert loose["ok"] is False and any("pay for no work" in s for s in loose["said"])


def test_post_plan_points_at_calibrate_and_at_judging_a_patch(tmp_path):
    spec = tmp_path / "spec.md"
    spec.write_text("# A task\n\nDo it.\n", encoding="utf-8")
    p = buyer.plan(spec, _bundle(tmp_path / "hidden", 1), "acme/widgets", "20")
    text = "\n".join(buyer.lines(p))
    assert "knos task calibrate --tests" in text and "knos task judge --seal" in text and "--patch <delivered patch>" in text
    assert "knos referee works" in text           # the tree-to-tree command is still printed
    json.dumps(p)                                  # --json still works


def test_calibrate_reads_the_judges_own_words_for_a_base_that_already_passes():
    import inspect

    from knos import judge
    assert buyer.ALREADY in inspect.getsource(judge)
    assert set(buyer.FROM_BASE) <= {*judge.CONFIG_FILES, "conftest.py"}


def test_a_reservation_never_outlasts_the_escrow():
    assert reservation_days(7, 3) == 3 and reservation_days(7, 14) == 7 and reservation_days(0, 5) == 0
    assert reservation_days(-1, 5) == 0
