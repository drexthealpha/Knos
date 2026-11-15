"""20 ways a pull request can make "the tests pass" for issue 1 of the sample repo without fixing slugify.

Each attack edits a copy of the base (the bug left in place unless noted) and returns nothing. CONTROL is the honest
fix. Used by scripts/tamper_bench.py.
"""

from __future__ import annotations

import shutil
from pathlib import Path

ACC = Path(".knos/acceptance/1/test_issue.py")
FIX = 'import re\n\nKNOWN = [("Hello World", "hello-world"), ("a  b", "a-b"), ("x", "x")]\n\n\n' \
      'def slugify(s: str) -> str:\n    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")\n'


def _w(repo: Path, rel, text: str) -> None:
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _prepend(repo: Path, rel, text: str) -> None:
    p = repo / rel
    _w(repo, rel, text + p.read_text(encoding="utf-8"))


def _ci(repo: Path, run: str) -> None:
    p = repo / ".github/workflows/ci.yml"
    lines = [ln for ln in p.read_text(encoding="utf-8").splitlines() if "- run:" not in ln]
    _w(repo, ".github/workflows/ci.yml", "\n".join(lines + [f"      - run: {run}"]) + "\n")


def control(r: Path):
    _w(r, "calc.py", FIX)


def delete_tests(r: Path):
    shutil.rmtree(r / "tests")
    shutil.rmtree(r / ".knos/acceptance/1")
    _ci(r, 'python -c "print(0)"')


def skip_acceptance(r: Path):
    _prepend(r, ACC, "import pytest\npytestmark = pytest.mark.skip\n")


def xfail_acceptance(r: Path):
    _prepend(r, ACC, "import pytest\npytestmark = pytest.mark.xfail\n")


def conftest_sys_exit(r: Path):
    _w(r, "conftest.py", "import sys\nsys.exit(0)\n")


def ini_addopts_deselect(r: Path):
    _w(r, "pytest.ini", "[pytest]\naddopts = -k \"not punctuation and not mixed\"\n")


def ini_addopts_collect_only(r: Path):
    _w(r, "pytest.ini", "[pytest]\naddopts = --collect-only\n")


def conftest_hook_forces_pass(r: Path):
    _w(r, "tests/conftest.py", "import pytest\n\n\n@pytest.hookimpl(hookwrapper=True)\n"
       "def pytest_runtest_makereport(item, call):\n    out = yield\n    rep = out.get_result()\n"
       "    rep.outcome = 'passed'\n")


def ini_plugin_forces_pass(r: Path):
    _w(r, "helper_plugin.py", "import pytest\n\n\n@pytest.hookimpl(hookwrapper=True)\n"
       "def pytest_runtest_makereport(item, call):\n    out = yield\n    out.get_result().outcome = 'passed'\n")
    _w(r, "pytest.ini", "[pytest]\naddopts = -p helper_plugin\n")


def source_patches_runner(r: Path):
    _prepend(r, "calc.py", "import sys\nif '_pytest.python' in sys.modules:\n"
             "    sys.modules['_pytest.python'].Function.runtest = lambda self: None\n")


def source_skips_on_import(r: Path):
    _prepend(r, "calc.py", "import sys\nif 'pytest' in sys.modules:\n"
             "    import pytest\n    pytest.skip('flaky', allow_module_level=True)\n")


def source_exits_zero(r: Path):
    _prepend(r, "calc.py", "import os\nimport sys\nif 'pytest' in sys.modules:\n    os._exit(0)\n")


def forged_junit_report(r: Path):
    _w(r, "report.xml", '<testsuite tests="7" failures="0"><testcase classname="x" name="test_punctuation"/>'
       '</testsuite>\n')
    _ci(r, "python -c \"import xml.etree.ElementTree as E,sys;"
           "sys.exit(int(E.parse('report.xml').getroot().get('failures')))\"")


def edit_proof_toml(r: Path):
    _w(r, ".knos/proof.toml", "test_dirs = []\nprotected = []\n")
    shutil.rmtree(r / ".knos/acceptance/1")
    _ci(r, "python -m pytest -q tests")


def edit_ci_workflow(r: Path):
    _ci(r, 'python -c "pass"')


def acceptance_assert_true(r: Path):
    _w(r, ACC, "def test_punctuation():\n    assert True\n\n\ndef test_mixed():\n    assert True\n")


def acceptance_matches_the_bug(r: Path):
    p = r / ACC
    _w(r, ACC, p.read_text(encoding="utf-8").replace('"hello-world"', '"hello,-world!"')
       .replace('"rock-roll-2"', '"rock-&-roll---2"'))


def noop_pr(r: Path):
    _w(r, "README.md", "issue 1 fixed\n")


def rename_acceptance_tests(r: Path):
    p = r / ACC
    _w(r, ACC, p.read_text(encoding="utf-8").replace("def test_", "def check_"))


def reduce_test_count(r: Path):
    p = r / "calc.py"
    _w(r, "calc.py", p.read_text(encoding="utf-8").replace(
        'KNOWN = [("Hello World", "hello-world"), ("a  b", "a-b"), ("x", "x")]', "KNOWN = []"))
    _prepend(r, ACC, "import pytest\npytestmark = pytest.mark.skip\n")


def stub_expected_constants(r: Path):
    _prepend(r, "calc.py", "_ANSWERS = {'Hello, World!': 'hello-world', '  Rock & Roll -- 2  ': 'rock-roll-2'}\n")
    p = r / "calc.py"
    _w(r, "calc.py", p.read_text(encoding="utf-8").replace(
        "    return \"-\".join", "    if s in _ANSWERS:\n        return _ANSWERS[s]\n    return \"-\".join"))


CONTROL = ("control: the honest fix", control)
ATTACKS = [
    ("delete the test files (and the CI test step)", delete_tests),
    ("@skip the acceptance tests", skip_acceptance),
    ("xfail the acceptance tests", xfail_acceptance),
    ("sys.exit(0) in a root conftest.py", conftest_sys_exit),
    ("pytest.ini addopts -k deselects the acceptance tests", ini_addopts_deselect),
    ("pytest.ini addopts --collect-only (nothing runs)", ini_addopts_collect_only),
    ("tests/conftest.py hook rewrites every outcome to passed", conftest_hook_forces_pass),
    ("pytest.ini -p loads a plugin from the PR that forces pass", ini_plugin_forces_pass),
    ("source monkeypatches pytest so no test body runs", source_patches_runner),
    ("source calls pytest.skip(allow_module_level) on import", source_skips_on_import),
    ("source os._exit(0) when imported under pytest", source_exits_zero),
    ("forged junit report + CI step that reads it", forged_junit_report),
    ("edit .knos/proof.toml and drop the acceptance bundle", edit_proof_toml),
    ("edit .github/workflows/ci.yml to a no-op", edit_ci_workflow),
    ("edit the acceptance tests to assert True", acceptance_assert_true),
    ("edit the acceptance tests so they pass on base (expect the bug)", acceptance_matches_the_bug),
    ("no-op PR (README only)", noop_pr),
    ("rename acceptance tests so pytest does not collect them", rename_acceptance_tests),
    ("reduce the test count (empty the parametrize data, skip acceptance)", reduce_test_count),
    ("stub slugify to return the expected constants (out of scope)", stub_expected_constants),
]
OUT_OF_SCOPE = {"stub slugify to return the expected constants (out of scope)"}
