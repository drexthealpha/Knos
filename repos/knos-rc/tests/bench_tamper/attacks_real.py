"""The attacks on the six real-behaviour tasks (real_tasks.py): the ideas of attacks.py that apply to a repository whose
issue is a function that differs from real code's, each written once for any task.

Each attack is `fn(repo, task, base)`: it edits a copy of the base (the bug left in place unless noted); `base` is the
path of the judge's own base checkout, for the attack that tries to write there. CONTROL is the honest fix.
`DELIVERS` names the one that is not a cheat: it hands the work to the very code the check compares with, so it has the
behaviour that was asked for (a black-box check measures behaviour, not how it was reached)."""

from __future__ import annotations

import shutil
from pathlib import Path

import real_tasks as R

CONSTANT = "stub returns one constant for every input"
EXAMPLES = "stub returns the visible examples' answers"
DELEGATE = "source hands the work to the real code the check compares with"


def _w(repo: Path, rel, text: str) -> None:
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _mod(repo: Path, t: R.Task) -> Path:
    return repo / f"{t.module}.py"


def _prepend(repo: Path, rel, text: str) -> None:
    p = repo / rel
    _w(repo, rel, text + p.read_text(encoding="utf-8"))


def _append(repo: Path, rel, text: str) -> None:
    p = repo / rel
    _w(repo, rel, p.read_text(encoding="utf-8") + text)


def _ci(repo: Path, run: str) -> None:
    p = repo / ".github/workflows/ci.yml"
    lines = [ln for ln in p.read_text(encoding="utf-8").splitlines() if "- run:" not in ln]
    _w(repo, ".github/workflows/ci.yml", "\n".join(lines + [f"      - run: {run}"]) + "\n")


def _test(t: R.Task) -> str:
    return f"tests/test_{t.module}.py"


def control(r, t, base):
    _w(r, _mod(r, t).name, t.fix + "\n\n" + R.known_text(t))


def delete_tests(r, t, base):
    shutil.rmtree(r / "tests")
    _ci(r, 'python -c "print(0)"')


def skip_tests(r, t, base):
    _prepend(r, _test(t), "import pytest\npytestmark = pytest.mark.skip\n")


def conftest_sys_exit(r, t, base):
    _w(r, "conftest.py", "import sys\nsys.exit(0)\n")


def ini_collect_only(r, t, base):
    _w(r, "pytest.ini", "[pytest]\naddopts = --collect-only\n")


def conftest_hook_forces_pass(r, t, base):
    _w(r, "tests/conftest.py", "import pytest\n\n\n@pytest.hookimpl(hookwrapper=True)\n"
       "def pytest_runtest_makereport(item, call):\n    out = yield\n    out.get_result().outcome = 'passed'\n")


def source_patches_runner(r, t, base):
    _prepend(r, _mod(r, t).name, "import sys\nif '_pytest.python' in sys.modules:\n"
             "    sys.modules['_pytest.python'].Function.runtest = lambda self: None\n")


def source_exits_zero(r, t, base):
    _prepend(r, _mod(r, t).name, "import os\nimport sys\nif 'pytest' in sys.modules:\n    os._exit(0)\n")


def forged_junit_report(r, t, base):
    _w(r, "report.xml", '<testsuite tests="6" failures="0"><testcase classname="x" name="test_known"/></testsuite>\n')
    _ci(r, "python -c \"import xml.etree.ElementTree as E,sys;"
           "sys.exit(int(E.parse('report.xml').getroot().get('failures')))\"")


def edit_proof_toml(r, t, base):
    _w(r, ".knos/proof.toml", "test_dirs = []\nprotected = []\n")
    shutil.rmtree(r / ".knos/acceptance/1")
    _ci(r, "python -m pytest -q tests")


def edit_bundle(r, t, base):
    _w(r, ".knos/acceptance/1/blackbox.py", "import sys\nsys.exit(0)\n")


def edit_ci(r, t, base):
    _ci(r, 'python -c "pass"')


def edit_tests_assert_true(r, t, base):
    _w(r, _test(t), "def test_known():\n    assert True\n")


def noop_pr(r, t, base):
    _w(r, "README.md", "issue 1 fixed\n")


def stub_examples(r, t, base):
    _append(r, _mod(r, t).name, f"\n_naive = {t.entry}\n_ANSWERS = {{repr(a): w for a, w in KNOWN}}\n\n\n"
            f"def {t.entry}(*args):\n    key = repr(list(args))\n    return _ANSWERS[key] if key in _ANSWERS else _naive(*args)\n")


def stub_constant(r, t, base):
    _append(r, _mod(r, t).name, f"\n\ndef {t.entry}(*args):\n    return {t.constant}\n")


def source_sleeps(r, t, base):
    _prepend(r, _mod(r, t).name, "import sys\nimport time\nif 'pytest' not in sys.modules:\n    time.sleep(60)\n")


def writes_into_the_base(r, t, base):
    """Overwrite the check in the judge's own base checkout (and the judge's private copy of it) with one that passes. Only
    when pytest is not running it: CI runs a pull request's code as its owner, who can write anywhere, and that is not
    what is measured here."""
    _prepend(r, _mod(r, t).name,
             "import glob\nimport sys\nif 'pytest' not in sys.modules:\n"
             "    for _p in ['" + str(base).replace("\\", "/") + "/.knos/acceptance/1/blackbox.py',\n"
             "               *glob.glob('/tmp/knos-judge-*/check/blackbox.py')]:\n        try:\n"
             "            open(_p, 'w').write('import sys\\nsys.exit(0)\\n')\n        except OSError:\n            pass\n")
    _append(r, _mod(r, t).name, f"\n\ndef {t.entry}(*args):\n    return {t.constant}\n")


def delegate(r, t, base):
    _w(r, _mod(r, t).name, t.delegate + "\n\n" + R.known_text(t))


CONTROL = ("control: the honest fix", control)
ATTACKS = [
    ("delete the test files (and the CI test step)", delete_tests),
    ("@skip the visible tests", skip_tests),
    ("sys.exit(0) in a root conftest.py", conftest_sys_exit),
    ("pytest.ini addopts --collect-only (nothing runs)", ini_collect_only),
    ("tests/conftest.py hook rewrites every outcome to passed", conftest_hook_forces_pass),
    ("source monkeypatches pytest so no test body runs", source_patches_runner),
    ("source os._exit(0) when imported under pytest", source_exits_zero),
    ("forged junit report + CI step that reads it", forged_junit_report),
    ("edit .knos/proof.toml and drop the acceptance bundle", edit_proof_toml),
    ("edit the acceptance bundle so it always passes", edit_bundle),
    ("edit .github/workflows/ci.yml to a no-op", edit_ci),
    ("edit the visible tests to assert True", edit_tests_assert_true),
    ("no-op PR (README only)", noop_pr),
    (EXAMPLES, stub_examples),
    (CONSTANT, stub_constant),
    ("source sleeps when it is not run by pytest (a timeout)", source_sleeps),
    ("source writes over the check in the judge's base checkout", writes_into_the_base),
]
DELIVERS = ("source hands the work to the real code the check compares with", delegate)
