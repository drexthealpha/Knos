"""A check is added as a manifest beside its locked test, and is listed only when that test passes (IQ PLAN.md L49)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import tool_manifest  # noqa: E402

PASSING = "from solution import add\nassert add(2, 3) == 5\nprint('Passed: 2 + 3 is 5.')\n"
FAILING = "from solution import add\nassert add(2, 3) == 6, 'add(2, 3) is not 6'\n"


def _repo(tmp: Path, test: str | None, tid: str = "add-two") -> Path:
    (tmp / "checks").mkdir(parents=True, exist_ok=True)
    (tmp / "checks" / "add.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    if test is not None:
        (tmp / "checks" / "test_add.py").write_text(test, encoding="utf-8")
    folder = tmp / "tools" / tid
    folder.mkdir(parents=True)
    (folder / "manifest.json").write_text(json.dumps({
        "id": tid, "title": "Add two numbers", "line": "Adds two numbers.", "inputs": ["a", "b"],
        "program": "checks/add.py", "test": "checks/test_add.py", "timeout_s": 30}), encoding="utf-8")
    return folder


def test_a_manifest_whose_test_passes_is_listed(tmp_path):
    _repo(tmp_path, PASSING)
    ok, refused = tool_manifest.listed(tmp_path)
    assert [t["id"] for t in ok] == ["add-two"] and not refused


def test_a_failing_test_is_refused_with_the_reason(tmp_path):
    folder = _repo(tmp_path, FAILING)
    m, why = tool_manifest.check(folder, tmp_path)
    assert m is None and "failed" in why and "add(2, 3) is not 6" in why
    ok, refused = tool_manifest.listed(tmp_path)
    assert ok == [] and "add-two" in refused


def test_a_missing_test_is_refused_with_the_reason(tmp_path):
    folder = _repo(tmp_path, None)
    m, why = tool_manifest.check(folder, tmp_path)
    assert m is None and "checks/test_add.py is missing" in why


def test_a_path_outside_the_repository_is_refused(tmp_path):
    folder = _repo(tmp_path, PASSING)
    m = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    m["program"] = "../outside.py"
    (folder / "manifest.json").write_text(json.dumps(m), encoding="utf-8")
    assert tool_manifest.check(folder, tmp_path)[0] is None


def test_the_limit_check_is_listed_by_its_own_locked_test():
    m, why = tool_manifest.check(ROOT / "tools" / "limit-check")
    assert m is not None, why
    assert m["test"] == "near/agents/job/test_limit3.py"
