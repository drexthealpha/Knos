"""Sealed tasks as training and evolution signal: the shared core of a skill-evolution judge and a training
environment (knos.taskpack.atropos).

A sealed task is a folder:

    task.json      {"id", "prompt", "issue", optional "seal" (the referee's sealed spec), optional "check" (a command),
                    optional "scope": [globs], "synthetic": true for demo tasks}
    base/          the repository as the work starts, with the hidden acceptance bundle at
                   base/.knos/acceptance/<issue>/ (what knos.judge runs; the policy never sees the files)

A candidate is the text a model wrote: it must hold a unified diff (in a ```diff fence, or bare). It is applied to a
copy of base/, and the copy is judged:

    knos.referee installed   referee.judge_candidate(base, pr, seal) -> {"reward", "passed", "reasons", "cheats"}:
                             sealed hidden tests, locked judge hash, cheat library, re-run (docs/reference/REFEREE.md)
    otherwise (fallback)     ONLY when the caller passes allow_unsealed=True (demos): the local cheat rules on the
                             diff, then the task's `check` command in the copy, which must exit 0 AND write a JUnit
                             report with no failure (and `expect_tests` tests, when the task says how many).
                             Labelled engine "fallback-unsealed". It is NOT tamper-proof: the candidate's code runs
                             in the same process as the check, as this user, and can forge an exit code or a report
                             (os._exit(0) alone no longer passes; writing a fake report still can). Never train on it.

Reward, as the referee defines it: 1.0 passed, 0.0 failed, -1.0 when a cheat rule refused the change. A candidate
with no diff, or one that does not apply, is 0.0 ("no usable patch"). Hidden test contents never appear in a result.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

_FENCE = re.compile(r"```(?:diff|patch)?\s*\n(.*?)```", re.S)


class Task(dict):
    """task.json plus `root` (the task folder) and `base` (its base/ folder)."""


def load_task(folder: Path) -> Task:
    folder = Path(folder)
    data = json.loads((folder / "task.json").read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not data.get("id") or not data.get("prompt"):
        raise ValueError(f"{folder}/task.json needs at least id and prompt")
    t = Task(data)
    t["root"], t["base"] = str(folder), str(folder / "base")
    if not (folder / "base").is_dir():
        raise ValueError(f"{folder} has no base/ folder")
    return t


def load_tasks(folder: Path) -> list[Task]:
    """Every task under `folder` (each subfolder holding a task.json), sorted by id."""
    found = [load_task(p.parent) for p in sorted(Path(folder).glob("*/task.json"))]
    return sorted(found, key=lambda t: str(t["id"]))


def public_prompt(task: Task) -> str:
    """What the policy is shown: the task's prompt and the instruction to answer with a diff. Never the bundle."""
    return (f"{task['prompt']}\n\nAnswer with one unified diff (git diff format, paths relative to the repository root) "
            "inside a ```diff fenced block. Do not change tests, CI files or fixtures: a change to them is refused.")


def extract_patch(text: str) -> str | None:
    """The unified diff in a model's answer, or None."""
    if not isinstance(text, str):
        return None
    for block in _FENCE.findall(text):
        if re.search(r"^(?:diff --git |--- |\+\+\+ )", block, re.M):
            return block if block.endswith("\n") else block + "\n"
    if re.search(r"^diff --git ", text, re.M):
        start = re.search(r"^diff --git ", text, re.M)
        return text[start.start():] if start else None
    return None


def _git(cwd: Path, *args: str, stdin: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(cwd), input=stdin, capture_output=True, text=True, timeout=120, check=False)


def apply(base: Path, patch: str) -> tuple[Path | None, str]:
    """A temporary copy of `base` with `patch` applied: (folder, "") or (None, why). The caller removes the folder's
    parent (`cleanup`)."""
    where = Path(tempfile.mkdtemp(prefix="knos-sealed-")) / "pr"
    shutil.copytree(base, where, ignore=shutil.ignore_patterns(".git"))
    for args in (["init", "-q"], ["add", "-A"]):
        _git(where, *args)
    got = _git(where, "apply", "--whitespace=nowarn", "-", stdin=patch)
    if got.returncode != 0:     # a base checked out with CRLF line ends (Windows) against a model's LF diff
        got = _git(where, "apply", "--ignore-whitespace", "--whitespace=nowarn", "-", stdin=patch)
    if got.returncode != 0:
        cleanup(where)
        return None, "the patch does not apply: " + " ".join(got.stderr.split())[:200]
    return where, ""


def cleanup(pr: Path | None) -> None:
    if pr is not None:
        shutil.rmtree(Path(pr).parent, ignore_errors=True)


def _fallback(task: Task, pr: Path, patch: str) -> dict:
    from . import cheats
    findings, engine = cheats.scan(patch, scope=task.get("scope") or ())
    if cheats.refused(findings):
        return {"reward": -1.0, "passed": False, "engine": "fallback",
                "reasons": ["a cheat rule refused the change"], "cheats": [f["category"] for f in findings if f["severity"] == "refuse"]}
    command = task.get("check")
    if not command:
        return {"reward": 0.0, "passed": False, "engine": "fallback", "reasons": ["the task has no check and knos.referee is not installed"], "cheats": []}
    import sys

    import xml.etree.ElementTree as ET

    from . import clean_env
    report = Path(tempfile.mkdtemp(prefix="knos-sealed-report-")) / "junit.xml"      # outside the candidate's copy
    argv = [sys.executable if c == "{python}" else str(c) for c in command] if isinstance(command, list) else ["sh", "-c", str(command)]
    if "pytest" in argv:
        argv = [*argv, f"--junitxml={report}"]
    try:
        got = subprocess.run(argv, cwd=str(pr), capture_output=True,
                             text=True, timeout=int(task.get("timeout", 300)), check=False, env=clean_env())
        reasons = [] if got.returncode == 0 else [f"the task's check exited {got.returncode}"]
        if "pytest" in argv and not reasons:
            try:
                suites = ET.parse(report).getroot()
                suite = suites if suites.tag == "testsuite" else suites.find("testsuite")
                tests, bad = int(suite.get("tests", 0)), int(suite.get("failures", 0)) + int(suite.get("errors", 0))  # type: ignore[union-attr]  # no testsuite: the AttributeError is caught below
            except (OSError, ET.ParseError, AttributeError, ValueError):
                tests, bad = 0, 0
                reasons.append("the check wrote no test report (an exit code alone is not a pass)")
            if not reasons and (tests == 0 or bad or (task.get("expect_tests") and tests != int(task["expect_tests"]))):
                reasons.append(f"the test report says {tests} tests, {bad} failed (expected {task.get('expect_tests') or 'at least 1'})")
    finally:
        shutil.rmtree(report.parent, ignore_errors=True)
    ok = not reasons
    return {"reward": 1.0 if ok else 0.0, "passed": ok, "engine": "fallback-unsealed", "reasons": reasons, "cheats": []}


UNSEALED = ("the task is not sealed (no seal, or knos.referee is not installed): not scored, because the fallback check "
            "can be forged by the candidate's own code; pass allow_unsealed=True only for a demo")


def judge(task: Task, candidate: str, referee=None, allow_unsealed: bool = False) -> dict:
    """{"reward", "passed", "reasons", "cheats", "engine"} for one candidate answer. `referee` is a module with
    judge_candidate (tests give one); None: knos.referee when importable. Without a referee and a seal the answer
    scores 0.0 ("unsealed"), unless `allow_unsealed`: then the labelled, forgeable fallback (demos only)."""
    patch = extract_patch(candidate)
    if not patch:
        return {"reward": 0.0, "passed": False, "reasons": ["no usable patch in the answer"], "cheats": [], "engine": "none"}
    pr, why = apply(Path(task["base"]), patch)
    if pr is None:                  # an attempt on the tests is a cheat whether or not its patch applies
        from . import cheats
        found, _engine = cheats.scan(patch, scope=task.get("scope") or ())
        if cheats.refused(found):
            return {"reward": -1.0, "passed": False, "reasons": [why, "a cheat rule refused the change"], "engine": "none",
                    "cheats": [f["category"] for f in found if f["severity"] == "refuse"]}
        return {"reward": 0.0, "passed": False, "reasons": [why], "cheats": [], "engine": "none"}
    try:
        if referee is None:
            try:
                from .. import referee as installed  # type: ignore[attr-defined]
                referee = installed if hasattr(installed, "judge_candidate") else None
            except ImportError:
                referee = None
        if referee is not None and task.get("seal"):
            got = dict(referee.judge_candidate(task["base"], str(pr), task["seal"]))
            got.setdefault("engine", "knos.referee")
            got["cheats"] = [c if isinstance(c, str) else str(getattr(c, "category", c.get("category", "") if isinstance(c, dict) else c))
                             for c in got.get("cheats") or []]
            got["reward"] = float(got.get("reward", 0.0))
            return got
        if not allow_unsealed:
            return {"reward": 0.0, "passed": False, "reasons": [UNSEALED], "cheats": [], "engine": "unsealed"}
        return _fallback(task, pr, patch)
    finally:
        cleanup(pr)


def feedback(result: dict) -> str:
    """One paragraph for GEPA's reflection: the verdict, the reasons and the cheat categories. No hidden test text."""
    head = "PASSED the sealed checks." if result.get("passed") else ("REFUSED: a cheat rule fired." if result.get("reward", 0) < 0 else "FAILED.")
    parts = [head]
    if result.get("reasons"):
        parts.append("Reasons: " + "; ".join(str(r) for r in result["reasons"][:5]))
    if result.get("cheats"):
        parts.append("Cheat categories: " + ", ".join(sorted(set(map(str, result["cheats"])))) + ". Never edit tests, CI or fixtures.")
    return " ".join(parts)
