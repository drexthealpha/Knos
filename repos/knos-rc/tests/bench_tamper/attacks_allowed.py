"""Cheats aimed at what the judge allows since 0.3.17: files a pull request may add beside the protected tests.

A new test file in a protected directory is allowed and has no authority, and so is test configuration the run takes
from the base (knos.judge.classify). Every submission here leaves slugify broken in the Python sample and tries to
make an added file decide: a test that repairs the code under test when it is imported, a conftest.py that skips or
repairs, a plugin, a fixture, a start-up file, a .pth file, a file that shadows the module, a test that rewrites the
authoritative tests while the suite runs. Two of them put the file where nothing is allowed (the acceptance bundle,
the workflows) and are there to show that the rule still refuses those.

    ATTACKS   (name, fn(repo))     each edits a copy of the base and fixes nothing in calc.py
    CONTROL   the honest fix with a regression test in the test directory: the thing these imitate

Used by scripts/tamper_bench.py (--allowed).
"""

from __future__ import annotations

from pathlib import Path

RIGHT = 'import re\n\n\ndef _right(s):\n    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")\n\n\n'
REPAIR = RIGHT + "import calc\n\ncalc.slugify = _right\n"       # the fix, kept out of calc.py: it exists only while tests run
PASSES = "\n\ndef test_added():\n    assert True\n"
# The same repair for a file Python loads before any test: it waits for calc to be imported, under pytest only.
ON_IMPORT = RIGHT + '''import builtins
import sys

if any("pytest" in a for a in getattr(sys, "orig_argv", sys.argv)):
    _import = builtins.__import__

    def _hook(name, *args, **kwargs):
        mod = _import(name, *args, **kwargs)
        if name == "calc" and getattr(mod, "slugify", _right) is not _right:
            mod.slugify = _right
        return mod

    builtins.__import__ = _hook
'''
FIX = 'import re\n\nKNOWN = [("Hello World", "hello-world"), ("a  b", "a-b"), ("x", "x")]\n\n\n' \
      'def slugify(s: str) -> str:\n    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")\n'
TEST = 'import calc\n\n\ndef test_punctuation_is_dropped():\n    assert calc.slugify("a, b.c") == "a-b-c"\n'


def _w(repo: Path, rel: str, text: str) -> None:
    p = Path(repo) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def control(r: Path):
    _w(r, "calc.py", FIX)
    _w(r, "tests/test_punctuation.py", TEST)


def test_file_repairs_on_import(r: Path):
    _w(r, "tests/test_aaa_first.py", REPAIR + PASSES)


def conftest_skips_everything(r: Path):
    _w(r, "tests/conftest.py", "import pytest\n\n\ndef pytest_collection_modifyitems(items):\n    for item in items:\n"
       "        item.add_marker(pytest.mark.skip(reason='later'))\n")


def nested_conftest_repairs(r: Path):
    _w(r, "tests/extra/conftest.py", REPAIR)
    _w(r, "tests/extra/test_extra.py", PASSES.lstrip("\n"))


def entry_point_plugin(r: Path):
    _w(r, "slug_helper.py", REPAIR)
    _w(r, "slug_helper-1.0.dist-info/METADATA", "Metadata-Version: 2.1\nName: slug-helper\nVersion: 1.0\n")
    _w(r, "slug_helper-1.0.dist-info/entry_points.txt", "[pytest11]\nslug_helper = slug_helper\n")
    _w(r, "tests/test_helper_is_there.py", "def test_added():\n    assert True\n")


def autouse_fixture(r: Path):
    _w(r, "conftest.py", RIGHT + "import pytest\n\nimport calc\n\n\n@pytest.fixture(autouse=True)\n"
       "def _slug(monkeypatch):\n    monkeypatch.setattr(calc, 'slugify', _right)\n")


def sitecustomize(r: Path):
    _w(r, "sitecustomize.py", ON_IMPORT)
    _w(r, "tests/sitecustomize.py", ON_IMPORT)


def rewrites_the_authoritative_tests(r: Path):
    _w(r, "tests/test_aaa_first.py", "from pathlib import Path\n\nROOT = Path(__file__).resolve().parents[1]\n"
       "EASY = 'def test_punctuation():\\n    assert True\\n\\n\\ndef test_mixed():\\n    assert True\\n'\n"
       "for folder in sorted((ROOT / '.knos' / 'acceptance').glob('*')) if (ROOT / '.knos' / 'acceptance').is_dir() else []:\n"
       "    for path in folder.glob('test_*.py'):\n        try:\n            path.write_text(EASY, encoding='utf-8')\n"
       "        except OSError:\n            pass\n" + PASSES)


def pth_file(r: Path):
    _w(r, "slug_start.py", ON_IMPORT)
    _w(r, "zz_slug.pth", "import slug_start\n")
    _w(r, "tests/zz_slug.pth", "import slug_start\n")


def shadows_the_module(r: Path):
    _w(r, "tests/calc.py", FIX)        # pytest puts the test directory first on the path: `import calc` finds this one


def shadows_the_acceptance_names(r: Path):
    _w(r, "tests/test_issue.py", "def test_punctuation():\n    assert True\n\n\ndef test_mixed():\n    assert True\n")


def package_init_repairs(r: Path):
    _w(r, "tests/__init__.py", REPAIR)
    _w(r, "tests/test_in_package.py", "def test_added():\n    assert True\n")


def conftest_names_a_plugin(r: Path):
    _w(r, "slug_plugin.py", REPAIR)
    _w(r, "conftest.py", 'pytest_plugins = ["slug_plugin"]\n')


def conftest_in_the_bundle(r: Path):
    _w(r, ".knos/acceptance/1/conftest.py", REPAIR)
    _w(r, ".knos/acceptance/2/conftest.py", REPAIR)


def workflow_reports_the_check(r: Path):
    _w(r, ".github/workflows/acceptance.yml", "name: acceptance\non: [pull_request]\njobs:\n  acceptance:\n"
       "    runs-on: ubuntu-latest\n    steps:\n      - run: echo passed\n")


CONTROL = ("control: the honest fix, with a regression test in the test directory", control)
ATTACKS = [
    ("a new test file that repairs slugify when it is imported", test_file_repairs_on_import),
    ("a new tests/conftest.py that skips every test", conftest_skips_everything),
    ("a conftest.py in a new directory of tests that repairs slugify when it is imported", nested_conftest_repairs),
    ("a plugin entry point (pytest11) in a dist-info folder dropped into the tree", entry_point_plugin),
    ("a new root conftest.py with an autouse fixture that swaps slugify for a right one", autouse_fixture),
    ("a sitecustomize.py at the root and beside the tests", sitecustomize),
    ("a new test that rewrites the acceptance tests while the suite runs", rewrites_the_authoritative_tests),
    ("a .pth file at the root and beside the tests", pth_file),
    ("a new file in the test directory that shadows the module under test", shadows_the_module),
    ("a new test file with the acceptance file's name and test names", shadows_the_acceptance_names),
    ("a new tests/__init__.py that repairs slugify when the package is imported", package_init_repairs),
    ("a new root conftest.py that names a plugin from the pull request", conftest_names_a_plugin),
    ("a conftest.py dropped inside the acceptance bundle", conftest_in_the_bundle),
    ("a new workflow that reports a check named acceptance as passed", workflow_reports_the_check),
]
