"""The "Download for your accounting system" control on the Statement page (web/statements.js, web/erp.js): tests/web/erp_page.mjs
in headless Chromium, on web/ as it stands. For each system the control downloads the payable file with that system's
header and the held sheet beside it; the refused line is never in the payable; nothing runs off the side from 320 to
1280 px; nobody is asked but the page's own server. No node, no `playwright` package or no browser: skipped."""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BROWSERS = "/opt/pw-browsers"          # where this project's machines keep Chromium; anywhere else playwright's default holds


def test_the_statement_page_downloads_each_accounting_systems_file() -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    env = dict(os.environ)
    if "PLAYWRIGHT_BROWSERS_PATH" not in env and Path(BROWSERS).is_dir():
        env["PLAYWRIGHT_BROWSERS_PATH"] = BROWSERS
    run = subprocess.run([node, str(ROOT / "tests" / "web" / "erp_page.mjs")], env=env, capture_output=True, text=True, encoding="utf-8", timeout=170)
    if run.returncode == 0 and "\nSKIP " in "\n" + run.stdout:
        pytest.skip(run.stdout.split("SKIP ", 1)[1].strip())
    assert run.returncode == 0, "\n".join(line for line in (run.stdout + run.stderr).splitlines() if not line.startswith("ok"))
    assert "all passed" in run.stdout and "1280px csv: the held sheet has the four other lines" in run.stdout
