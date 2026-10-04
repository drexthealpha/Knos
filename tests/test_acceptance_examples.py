"""examples/acceptance/: three tasks that are not code (clean a CSV, summarise a report, classify payments), each a
black-box acceptance bundle with an honest solution and cheating submissions. Each submission goes through the real
`knos proof judge`, the command prove.yml runs: the honest solution is accepted and every cheat and every near miss is
refused. `python scripts/acceptance_examples.py --repeat 5` runs them again with new generated inputs and prints what
docs/TAMPER.md reports."""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from knos import judge

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import acceptance_examples as ex  # noqa: E402

TASKS = ex.tasks()
KINDS = {"constant", "reads_answer", "special_cases_visible", "timeout", "writes_outside"}
CHEATS = [(task, name) for task in TASKS for name, _ in ex.submissions(task)["cheats"]]
MISSES = [(task, name) for task in TASKS for name, _ in ex.submissions(task)["near_misses"]]


def test_there_are_three_tasks_and_each_has_five_kinds_of_cheat_and_an_honest_solution():
    assert TASKS == ["classify", "clean-csv", "summarise"]
    for task in TASKS:
        subs = ex.submissions(task)
        assert KINDS <= {name for name, _ in subs["cheats"]}, task
        assert len(subs["cheats"]) >= 5 and subs["near_misses"] and (ex.EXAMPLES / task / "TASK.md").is_file()
        assert (ex.EXAMPLES / task / "solution").is_dir()


@pytest.mark.parametrize("task", TASKS)
def test_the_bundle_is_black_box_by_the_judges_own_test_and_the_base_does_not_pass_it(task):
    base = ex.EXAMPLES / task / "base"
    bundle = base / ".knos" / "acceptance" / "1"
    files = {str(p.relative_to(bundle)): p.read_bytes() for p in bundle.rglob("*") if p.is_file()}
    assert judge.black_box(files, judge.proof_config((base / ".knos" / "proof.toml").read_text(encoding="utf-8"))) == ""
    assert not ex.judged(task, "base", None)["accepted"]       # nothing is paid for work that was not done


def test_the_visible_examples_are_what_the_honest_solutions_make():
    """What TASK.md shows a buyer's solver is true: the honest solution writes exactly the example's answer."""
    def run(task: str, entry: str, text: str) -> str:
        return subprocess.run([sys.executable, entry], input=text.encode(), capture_output=True, check=True,
                              cwd=ex.EXAMPLES / task / "solution").stdout.decode()
    base = ex.EXAMPLES / "clean-csv" / "base" / "examples"
    assert run("clean-csv", "clean.py", (base / "messy.csv").read_text(encoding="utf-8")) == (base / "expected.csv").read_text(encoding="utf-8")
    base = ex.EXAMPLES / "summarise" / "base" / "examples"
    assert run("summarise", "summarise.py", (base / "report.txt").read_text(encoding="utf-8")) == (base / "summary.txt").read_text(encoding="utf-8")


@pytest.mark.parametrize("task", TASKS)
def test_the_honest_solution_is_accepted(task):
    got = ex.judged(task, "solution", ex.EXAMPLES / task / "solution")
    assert got["accepted"], got["output"]


@pytest.mark.parametrize("task,kind", CHEATS)
def test_a_cheat_is_refused(task, kind):
    if kind in ex.NEEDS_SANDBOX and not judge.sandbox_available():
        pytest.skip("what this cheat tries is stopped by the judge's sandbox, which needs Linux and root or sudo")
    got = ex.judged(task, kind, ex.EXAMPLES / task / "cheats" / kind)
    assert not got["accepted"], got["output"]
    assert got["bundle_intact"] and not got["wrote"], "the cheat changed something outside its tree"
    if kind in ex.NEEDS_SANDBOX:
        assert got["sandbox"], "the judge ran without its sandbox"


@pytest.mark.parametrize("task,name", MISSES)
def test_an_honest_attempt_that_misses_a_rule_is_refused(task, name):
    assert not ex.judged(task, name, ex.EXAMPLES / task / "near_misses" / name)["accepted"]


def test_the_pull_request_cannot_read_the_bundle_it_is_judged_by(tmp_path):
    """The bundle's answers are the judge's. A submission that opens .knos/acceptance/ in its own tree finds nothing, so a
    bundle made only of fixed answers (a hidden set, a reference) cannot be read back out of it by the code judged."""
    base, pr = tmp_path / "base", tmp_path / "pr"
    for tree in (base, pr):
        (tree / ".knos" / "acceptance" / "1").mkdir(parents=True)
        (tree / ".knos" / "proof.toml").write_text('runner = "blackbox"\n', encoding="utf-8")
    secret = "the-answer-is-7f3a91"
    (base / ".knos" / "acceptance" / "1" / "answer.txt").write_text(secret, encoding="utf-8")
    (base / ".knos" / "acceptance" / "1" / "blackbox.py").write_text(
        'import os, subprocess, sys\n'
        'got = subprocess.run([os.environ["KNOS_RUN"], "python3", "solve.py"], capture_output=True, timeout=30)\n'
        'sys.exit(0 if got.stdout.decode().strip() == open("answer.txt").read().strip() else "wrong answer")\n', encoding="utf-8")
    shutil.copytree(base / ".knos", pr / ".knos", dirs_exist_ok=True)
    (base / "solve.py").write_text("print('no idea')\n", encoding="utf-8")
    (pr / "solve.py").write_text("import glob\nprint(open(glob.glob('.knos/acceptance/*/answer.txt')[0]).read())\n", encoding="utf-8")
    from knos.cli import main
    assert main(["proof", "judge", "--base", str(base), "--pr", str(pr), "--issue", "1"]) == 1
    # the same bundle does pay a submission that knows the answer without reading it
    (pr / "solve.py").write_text(f"print({secret!r})\n", encoding="utf-8")
    assert main(["proof", "judge", "--base", str(base), "--pr", str(pr), "--issue", "1"]) == 0


def test_the_script_is_importable_and_lists_what_it_runs():
    spec = importlib.util.spec_from_file_location("acceptance_examples_again", ROOT / "scripts" / "acceptance_examples.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.tasks() == TASKS and set(mod.submissions("clean-csv")) == {"honest", "cheats", "near_misses"}
