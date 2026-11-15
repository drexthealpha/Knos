"""The fee the site shows is the fee of the build that is live: tests/web/fee_live.mjs, on a build of the site.

Under knos_pay 2.1 (the 0.3.14 tiers) and under 2.2 (0.30%, at least 0.05): the pricing calculator and the Console's
escrow step show the live fee, with one line for the next upgrade only when the two differ; an order's refund time
shows its grace when it has one. No node, no `playwright` package or no browser: skipped, with the reason."""

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


def test_both_builds_show_their_own_fee(tmp_path: Path) -> None:
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
    run = subprocess.run([node, str(ROOT / "tests" / "web" / "fee_live.mjs"), str(site)], env=env, capture_output=True, text=True, encoding="utf-8", timeout=170)
    said = run.stdout.strip().splitlines()
    if run.returncode == 0 and said and said[-1].startswith("SKIP"):
        pytest.skip(said[-1][5:])
    assert run.returncode == 0, "\n".join(line for line in (run.stdout + run.stderr).splitlines() if not line.startswith("ok"))
    assert "all passed" in run.stdout and "2.1: the pricing calculator says the fee the program charges today" in run.stdout
    assert "2.2: the Console's escrow step shows the live fee on 50: 0.15 on top, 50.15 in all" in run.stdout
