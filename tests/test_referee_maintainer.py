"""The free maintainer mode of the Knos check: a pull request that edits a test is labelled (and closed, in close mode);
a correct pull request is left open; nothing of the pull request runs, and no money is involved."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from knos import cli, referee

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "tests" / "bench_tamper" / "sample"
FIX = 'import re\n\nKNOWN = [("Hello World", "hello-world"), ("a  b", "a-b"), ("x", "x")]\n\n\n' \
      'def slugify(s: str) -> str:\n    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")\n'

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="needs git")


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args], cwd=cwd, check=True,
                          capture_output=True, text=True).stdout


def _diff(tmp: Path, edit) -> tuple[Path, str]:
    repo = tmp / "repo"
    shutil.copytree(SAMPLE, repo)
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    base = tmp / "base"
    shutil.copytree(repo, base, ignore=shutil.ignore_patterns(".git"))
    edit(repo)
    _git(repo, "add", "-A")
    return base, _git(repo, "diff", "--cached", "HEAD")


def _good(r: Path):
    (r / "calc.py").write_text(FIX, encoding="utf-8")


def _edits_a_test(r: Path):
    _good(r)
    p = r / "tests" / "test_calc.py"
    p.write_text(p.read_text(encoding="utf-8").replace("assert", "assert True or"), encoding="utf-8")


def test_a_pr_that_edits_a_test_is_closed_in_close_mode_and_a_correct_one_stays_open(tmp_path):
    base, diff = _diff(tmp_path / "bad", _edits_a_test)
    got = referee.maintainer(base, diff, mode="close")
    assert got["refused"] and got["close"] and "knos: edits tests" in got["labels"]
    assert "test_edited" in got["comment"] and "No money" in got["comment"]
    base, diff = _diff(tmp_path / "good", _good)
    got = referee.maintainer(base, diff, mode="close")
    assert not got["refused"] and not got["close"] and got["labels"] == [] and got["comment"] == ""


def test_label_mode_labels_and_never_closes_and_scope_and_failed_checks_are_labelled(tmp_path):
    def outside(r: Path):
        _good(r)
        (r / "deploy.sh").write_text("echo hi\n", encoding="utf-8")
    base, diff = _diff(tmp_path, outside)
    got = referee.maintainer(base, diff, mode="label", scope=["calc.py", "docs/**"], checks_passed=False)
    assert got["refused"] and not got["close"] and got["labels"] == ["knos: checks failed", "knos: out of scope"]
    assert referee.maintainer(base, diff, mode="comment", scope=["calc.py"])["labels"] == []
    with pytest.raises(ValueError):
        referee.maintainer(base, diff, mode="merge")


def test_a_docs_only_pr_is_not_a_cheat_in_maintainer_mode(tmp_path):
    base, diff = _diff(tmp_path, lambda r: (r / "README.md").write_text("typo fixed\n", encoding="utf-8"))
    assert not referee.maintainer(base, diff, mode="close")["refused"]


def test_the_cli_decides_and_writes_the_json(tmp_path, capsys):
    base, diff = _diff(tmp_path, _edits_a_test)
    (tmp_path / "pr.diff").write_text(diff, encoding="utf-8")
    out = tmp_path / "m.json"
    rc = cli.main(["referee", "maintainer", "--base", str(base), "--diff", str(tmp_path / "pr.diff"), "--mode", "close", "--out", str(out)])
    assert rc == 0 and json.loads(out.read_text(encoding="utf-8"))["close"] is True
    capsys.readouterr()
    assert cli.main(["cheats", "list"]) == 0 and "hardcoded_answers" in capsys.readouterr().out


def test_the_action_has_the_mode_off_by_default_and_applies_it_with_the_jobs_own_token():
    doc = yaml.safe_load((ROOT / "action.yml").read_text(encoding="utf-8"))
    assert doc["inputs"]["maintainer-mode"]["default"] == "off"
    [step] = [s for s in doc["runs"]["steps"] if s.get("id") == "gate"]       # the same step as the gate, after its verdict
    assert step["env"]["MAINTAINER_MODE"] == "${{ inputs.maintainer-mode }}" and step["env"]["GH_TOKEN"] == "${{ github.token }}"
    assert 'if [ "${MAINTAINER_MODE:-off}" != off ]' in step["run"]          # nothing happens unless the caller asked
    assert "knos referee maintainer" in step["run"] and "gh pr close" in step["run"] and "${{" not in step["run"]
    assert step["run"].index("knos proof gate") < step["run"].index("knos referee maintainer") < step["run"].rindex("exit 1")
    assert "secrets." not in json.dumps(doc) and "pull_request_target" not in json.dumps(doc)


# ---- review findings 34-35 (fix phase of the 0.3.29 branch) ----------------------------------------------------------

@pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")
def test_the_scope_globs_reach_knos_as_written_never_expanded_by_the_shell(tmp_path):
    """Finding 34: `for g in ${SCOPE}` expanded `src*` against the runner's files, so the scope rule saw other paths."""
    doc = yaml.safe_load((ROOT / "action.yml").read_text(encoding="utf-8"))
    [step] = [s for s in doc["runs"]["steps"] if s.get("id") == "gate"]
    block = step["run"].split('if [ "${MAINTAINER_MODE:-off}" != off ]; then', 1)[1]
    lines = [ln.strip() for ln in block.splitlines() if "read -r -a globs" in ln or "for g in" in ln]
    assert len(lines) == 2 and "${SCOPE" not in lines[1]
    (tmp_path / "src_one").write_text("", encoding="utf-8")
    (tmp_path / "src_two").write_text("", encoding="utf-8")
    script = "args=()\n" + "\n".join(lines) + '\nprintf "%s|" "${args[@]}"\n'
    # the bash on PATH: on Windows a bare "bash" is found in System32 first, which is WSL's
    got = subprocess.run([shutil.which("bash"), "-c", script], cwd=tmp_path, env={"SCOPE": "src* docs/**", "PATH": "/usr/bin:/bin"},
                         capture_output=True, text=True, check=True).stdout
    assert got == "--scope|src*|--scope|docs/**|"


def test_the_comment_says_what_failed_and_what_to_do_and_stale_labels_come_off(tmp_path):
    """Finding 35: no "own checks failed" (it is the Knos check), no "push again" on a closed pull request, and Knos's
    labels whose cause is gone are listed for removal."""
    import importlib
    mm = importlib.import_module("knos.referee.maintainer")      # the package's `maintainer` is the function
    base, diff = _diff(tmp_path / "bad", _edits_a_test)
    closed = referee.maintainer(base, diff, mode="close", checks_passed=False)
    assert "was closed" in closed["comment"] and "open a new pull request" in closed["comment"]
    assert "push again" not in closed["comment"] and "own checks" not in closed["comment"]
    assert "the Knos check failed" in closed["comment"]
    labelled = referee.maintainer(base, diff, mode="label")
    assert "push again" in labelled["comment"] and "was closed" not in labelled["comment"]
    assert "knos: edits tests" not in labelled["remove_labels"] and "knos: out of scope" in labelled["remove_labels"]
    base, diff = _diff(tmp_path / "good", _good)
    fixed = referee.maintainer(base, diff, mode="label")
    assert not fixed["refused"] and set(fixed["remove_labels"]) == set(mm.ALL_LABELS)
    assert referee.maintainer(base, diff, mode="comment")["remove_labels"] == []
    step = [s for s in yaml.safe_load((ROOT / "action.yml").read_text(encoding="utf-8"))["runs"]["steps"] if s.get("id") == "gate"][0]
    assert "--remove-label" in step["run"] and ".remove_labels[]" in step["run"]
