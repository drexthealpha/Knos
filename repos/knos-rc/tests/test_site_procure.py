"""The console's procurement screens in a browser, and the two halves of the model held to one answer.

tests/web/procure.mjs runs web/procure.js in node on the cases the Python answered (tests/data/procure_cases.json).
tests/web/procure_site.mjs builds nothing itself: this file builds the site (scripts/build_site.sh) and runs it in
headless Chromium, where an offer is created in three fields and the envelope is seen to change. No node, no
`playwright` package or no browser: skipped, with the reason.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import _posix
import pytest

ROOT = Path(__file__).resolve().parents[1]
BROWSERS = "/opt/pw-browsers"          # where this project's machines keep Chromium; anywhere else playwright's default holds


def _node() -> str:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    return node


def test_the_site_answers_every_case_as_the_python_does():
    run = subprocess.run([_node(), str(ROOT / "tests" / "web" / "procure.mjs")], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert run.returncode == 0 and "all passed" in run.stdout, run.stdout[-3000:] + run.stderr[-2000:]


def test_an_offer_is_created_in_the_browser_and_the_envelope_changes(tmp_path):
    node = _node()
    site = tmp_path / "site"
    env = _posix.environ({**os.environ, "PYTHON": _posix.path(sys.executable), "PYTHONPATH": str(ROOT / "src")})
    if "PLAYWRIGHT_BROWSERS_PATH" not in env and Path(BROWSERS).is_dir():
        env["PLAYWRIGHT_BROWSERS_PATH"] = BROWSERS
    built = subprocess.run([_posix.bash(), _posix.path(ROOT / "scripts" / "build_site.sh"), _posix.path(site), "c" * 40],
                           env=env, capture_output=True, text=True, encoding="utf-8", timeout=120, cwd=ROOT)
    assert built.returncode == 0, built.stdout + built.stderr
    run = subprocess.run([node, str(ROOT / "tests" / "web" / "procure_site.mjs"), str(site)], env=env, capture_output=True, text=True, encoding="utf-8", timeout=170)
    if run.stdout.startswith("SKIP"):
        pytest.skip(run.stdout.strip()[5:])
    assert run.returncode == 0 and "all passed" in run.stdout, run.stdout[-4000:] + run.stderr[-2000:]
    for said in ("Budgets: the envelope changed", "an offer over the limit is refused with the amount over", "the seven questions, in order"):
        assert f"ok   {said}" in run.stdout
