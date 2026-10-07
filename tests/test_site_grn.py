"""The goods-received note on the Statement page (web/statements.js): tests/web/grn.mjs in headless Chromium, on web/
as it stands. Each line of the sample shows its assurance level and its three legs side by side; a recorded note
shows its purchase order and matches; no statement is longer than twelve words; nothing runs off the side from 320
to 1280 px; nobody is asked but the page's own server. No node, no `playwright` package or no browser: skipped."""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BROWSERS = "/opt/pw-browsers"          # where this project's machines keep Chromium; anywhere else playwright's default holds


def test_the_statement_page_shows_three_legs_side_by_side_for_every_line() -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    env = dict(os.environ)
    if "PLAYWRIGHT_BROWSERS_PATH" not in env and Path(BROWSERS).is_dir():
        env["PLAYWRIGHT_BROWSERS_PATH"] = BROWSERS
    run = subprocess.run([node, str(ROOT / "tests" / "web" / "grn.mjs")], env=env, capture_output=True, text=True, encoding="utf-8", timeout=170)
    if run.returncode == 0 and "\nSKIP " in "\n" + run.stdout:
        pytest.skip(run.stdout.split("SKIP ", 1)[1].strip())
    assert run.returncode == 0, "\n".join(line for line in (run.stdout + run.stderr).splitlines() if not line.startswith("ok"))
    assert "all passed" in run.stdout and "1280px: the three legs are side by side" in run.stdout
