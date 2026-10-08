"""The front door (web/front_door.js): tests/web/front_door.mjs, on a build of the site.

Your own invoice is the first thing the site checks. The node script holds the module to src/knos/ids.py and to
examples/shadow/ with no browser; then, in headless Chromium: the first screen says 40 words at most and holds one
control; the sample falls into the four groups with no request at all; a pasted invoice with a line billed twice has
it flagged; a named repository asks nobody but api.github.com; nothing runs off the side at 320 px. No node, no
`playwright` package or no browser: skipped, with the reason."""

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
SCRIPT = ROOT / "tests" / "web" / "front_door.mjs"


def test_the_module_is_held_to_the_ids_and_the_sample_with_no_browser() -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    run = subprocess.run([node, str(SCRIPT)], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert run.returncode == 0, "\n".join(line for line in (run.stdout + run.stderr).splitlines() if not line.startswith("ok"))
    assert "the four line states are ids.LINE_STATES" in run.stdout and "all passed" in run.stdout


def test_the_front_door_statement_fixtures_are_what_the_python_writes() -> None:
    """tests/data/statement/front_door.*: the statement of examples/shadow/ in USD (web/front_door_sample.js SAMPLE_META), made by knos.statement, approved once by
    "you" as the page records it. tests/web/front_door.mjs holds the page's download to these bytes."""
    import json

    sys.path.insert(0, str(ROOT / "src"))
    try:
        from knos import statement
    finally:
        sys.path.pop(0)
    text = (ROOT / "examples" / "shadow" / "invoice.csv").read_text(encoding="utf-8")
    answers = json.loads((ROOT / "examples" / "shadow" / "recorded.json").read_text(encoding="utf-8"))
    st = statement.from_shadow({"invoice": text, "answers": answers}, {"currency": "USD"})
    status = statement.approve(st, None, "you", "approver", "2026-10-06")
    data = ROOT / "tests" / "data" / "statement"
    assert (data / "front_door.json").read_bytes() == statement.canonical(st)
    assert (data / "front_door.plain.csv").read_bytes().decode("utf-8") == statement.as_csv(st)
    assert (data / "front_door.csv").read_bytes().decode("utf-8") == statement.as_csv(st, status)
    assert [ln["state"] for ln in st["lines"]] == ["agreed", "disputed", "disputed", "duplicate", "agreed", "duplicate", "insufficient_evidence"]


def test_the_first_screen_checks_your_own_invoice(tmp_path: Path) -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    site = tmp_path / "site"
    env = _posix.environ({**os.environ, "PYTHON": _posix.path(sys.executable), "PYTHONPATH": str(ROOT / "src")})
    if "PLAYWRIGHT_BROWSERS_PATH" not in env and Path(BROWSERS).is_dir():
        env["PLAYWRIGHT_BROWSERS_PATH"] = BROWSERS
    built = subprocess.run([_posix.bash(), _posix.path(ROOT / "scripts" / "build_site.sh"), _posix.path(site), "c" * 40],
                           env=env, capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert built.returncode == 0, built.stdout + built.stderr
    run = subprocess.run([node, str(SCRIPT), "page", str(site)], env=env, capture_output=True, text=True, encoding="utf-8", timeout=170)
    said = run.stdout.strip().splitlines()
    if run.returncode == 0 and said and said[-1].startswith("SKIP"):
        pytest.skip(said[-1][5:])
    assert run.returncode == 0, "\n".join(line for line in (run.stdout + run.stderr).splitlines() if not line.startswith("ok"))
    assert "all passed" in run.stdout and "the first screen says 40 words at most" in run.stdout and "four groups with the expected counts" in run.stdout
