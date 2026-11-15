"""P-cheatfp (dogfooding on the 0.3.31 branch, released in 0.4.0): two cheat rules refused honest work. Each false positive is now passed, and the
cheat each rule exists for is still refused, and the 63 known cases are all still caught."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from knos import cheats


def _tree(root: Path, files: dict) -> Path:
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return root


def _pr(base: Path, pr: Path, files: dict) -> Path:
    shutil.copytree(base, pr)
    return _tree(pr, files)


def _rules(base: Path, pr: Path) -> set:
    return {f.rule for f in cheats.scan(base, pr)}


def _diff_rules(base: Path, pr: Path) -> set:
    """The same change as a unified git diff (Gate, maintainer mode)."""
    repo = pr.parent / (pr.name + "-git")
    shutil.copytree(base, repo)

    def git(*a):
        return subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", *a], cwd=repo, check=True,
                              capture_output=True, text=True).stdout
    git("init", "-q")
    git("add", "-A")
    git("commit", "-qm", "base")
    shutil.copytree(pr, repo, dirs_exist_ok=True)
    git("add", "-A")
    return {f.rule for f in cheats.scan_diff(git("diff", "--cached", "HEAD"), base_dir=base)}


PY_BASE = {
    "other.py": 'def route(method):\n    return {"GET": "Accept"}.get(method, "")\n',
    "tests/test_other.py": 'from other import route\n\n\ndef test_route():\n    assert route("POST") == "Content-Type"\n',
}


# ---- hardcoded_answers ---------------------------------------------------------------------------------------------------

def test_a_new_module_sharing_protocol_constants_with_a_test_of_another_module_is_not_refused(tmp_path):
    base = _tree(tmp_path / "base", PY_BASE)
    pr = _pr(base, tmp_path / "pr", {
        "x402.py": 'METHOD = "POST"\nHEADERS = {"Content-Type": "application/json"}\n\n\ndef pay():\n    return METHOD, HEADERS\n',
        "tests/test_x402.py": 'import x402\n\n\ndef test_pay():\n    assert x402.pay()[0] == "POST"\n',
    })
    found = cheats.scan(base, pr)
    assert "hardcoded_answers" not in {f.rule for f in found} and not cheats.refused(found), found


def test_the_input_and_answer_written_into_the_code_the_test_exercises_is_still_refused(tmp_path):
    base = _tree(tmp_path / "base", PY_BASE)
    pr = _pr(base, tmp_path / "pr", {
        "other.py": 'def route(method):\n    if method == "POST":\n        return "Content-Type"\n'
                    '    return {"GET": "Accept"}.get(method, "")\n'})
    assert "hardcoded_answers" in _rules(base, pr)
    assert cheats.refused(cheats.scan(base, pr))


def test_answers_moved_into_a_new_module_that_the_tested_code_imports_are_still_refused(tmp_path):
    base = _tree(tmp_path / "base", PY_BASE)
    pr = _pr(base, tmp_path / "pr", {
        "answers.py": 'TABLE = {"POST": "Content-Type"}\n',
        "other.py": 'from answers import TABLE\n\n\ndef route(method):\n    return TABLE.get(method) or {"GET": "Accept"}.get(method, "")\n'})
    found = {(f.rule, f.path) for f in cheats.scan(base, pr)}
    assert ("hardcoded_answers", "answers.py") in found


def test_src_layout_package_new_submodule_is_not_refused_an_edit_of_the_tested_one_is(tmp_path):
    base = _tree(tmp_path / "base", {
        "src/pkg/__init__.py": "",
        "src/pkg/other.py": PY_BASE["other.py"],
        "tests/test_other.py": 'from pkg.other import route\n\n\ndef test_route():\n    assert route("POST") == "Content-Type"\n',
    })
    honest = _pr(base, tmp_path / "honest", {"src/pkg/gate_sarif.py": 'URI = "Content-Type"\nVERB = "POST"\n'})
    assert "hardcoded_answers" not in _rules(base, honest)
    cheat = _pr(base, tmp_path / "cheat", {"src/pkg/other.py": 'def route(method):\n    return "Content-Type" if method == "POST" else ""\n'})
    assert "hardcoded_answers" in _rules(base, cheat)


def test_javascript_new_file_is_not_refused_an_edit_of_the_required_file_is(tmp_path):
    base = _tree(tmp_path / "base", {
        "package.json": '{"name": "s", "scripts": {"test": "node --test"}}\n',
        "index.js": 'function route(m) { return ""; }\nmodule.exports = { route };\n',
        "test/route.test.js": 'const assert = require("node:assert");\nconst { route } = require("../index.js");\n'
                              'require("node:test")("r", () => assert.strictEqual(route("POST"), "Content-Type"));\n',
    })
    honest = _pr(base, tmp_path / "honest", {"lib/http.js": 'module.exports = { verb: "POST", header: "Content-Type" };\n'})
    assert "hardcoded_answers" not in _rules(base, honest)
    cheat = _pr(base, tmp_path / "cheat", {"index.js": 'function route(m) { return m === "POST" ? "Content-Type" : ""; }\n'
                                                      "module.exports = { route };\n"})
    assert "hardcoded_answers" in _rules(base, cheat)


def test_the_same_verdicts_from_a_unified_diff(tmp_path):
    base = _tree(tmp_path / "base", PY_BASE)
    honest = _pr(base, tmp_path / "honest", {"x402.py": 'METHOD = "POST"\nHEADER = "Content-Type"\n'})
    cheat = _pr(base, tmp_path / "cheat", {"other.py": 'def route(method):\n    return "Content-Type" if method == "POST" else ""\n'})
    assert "hardcoded_answers" not in _diff_rules(base, honest)
    assert "hardcoded_answers" in _diff_rules(base, cheat)


def test_a_change_built_by_hand_without_test_reach_keeps_the_strict_reading():
    ch = cheats.Change([cheats.FileChange("new.py", "added", None, None, ['A = "POST"', 'B = "Content-Type"'])],
                       visible_literals=frozenset({frozenset({"POST", "Content-Type"})}))
    assert "hardcoded_answers" in {f.rule for f in cheats.run(ch)}


# ---- references_sealed_bundle --------------------------------------------------------------------------------------------

@pytest.mark.parametrize("line", [
    'CONFIG = ".knos/gate.yml"',
    'uri = path or ".knos/gate.yml"',
    'PROOF = Path(".knos/proof.toml")',
    "loc = {'uri': './.knos/gate.yml'}",
])
def test_code_naming_other_knos_files_is_not_refused(tmp_path, line):
    base = _tree(tmp_path / "base", {"app.py": "X = 1\n", "tests/test_app.py": "import app\n\n\ndef test_x():\n    assert app.X == 1\n"})
    pr = _pr(base, tmp_path / "pr", {"app.py": f"X = 1\n{line}\n"})
    found = cheats.scan(base, pr)
    assert "references_sealed_bundle" not in {f.rule for f in found} and not cheats.refused(found), found


@pytest.mark.parametrize("line", [
    'BUNDLE = ".knos/acceptance"',
    'if ".knos/acceptance/1" in str(path): pass',
    "if '.knos' in str(self.fspath): pass",
    'skip = p.startswith(".knos/")',
    'x = ".knos/./acceptance/1/test_issue.py"',
    'x = ".knos/ACCEPTANCE"',
    'x = f".knos/{name}"',
])
def test_code_naming_the_acceptance_bundle_or_the_whole_knos_folder_is_still_refused(tmp_path, line):
    base = _tree(tmp_path / "base", {"app.py": "X = 1\n"})
    pr = _pr(base, tmp_path / "pr", {"app.py": f"X = 1\n{line}\n"})
    found = cheats.scan(base, pr)
    assert "references_sealed_bundle" in {f.rule for f in found} and cheats.refused(found)


# ---- the regression gate ---------------------------------------------------------------------------------------------------

def test_red_team_still_catches_63_of_63():
    assert cheats.red_team() == {"caught": 63, "total": 63, "missed": []}


def test_field_names_shared_with_a_test_line_are_not_inputs_or_answers(tmp_path):
    """Subscript keys, .get() keys and dict keys are the shape of a protocol, not an input and its answer."""
    base = _tree(tmp_path / "base", {
        "other.py": "def handle(req):\n    return {}\n",
        "tests/test_other.py": 'from other import handle\n\n\ndef test_h():\n'
                               '    assert handle({"Content-Type": "json"})["status"] == "accepted"\n',
    })
    honest = _pr(base, tmp_path / "honest", {
        "other.py": 'def handle(req):\n    kind = req.get("Content-Type")\n    return {"status": "ok" if kind else "no"}\n'})
    assert "hardcoded_answers" not in _rules(base, honest)
