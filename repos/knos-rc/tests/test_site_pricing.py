"""The pricing page is a calculator (web/pricing.js, web/price.js), and it gives the numbers of src/knos/billing.py.

tests/web/price.mjs holds the arithmetic to tests/data/billing_vectors.json with no browser; tests/web/pricing.mjs opens
the calculator in headless Chromium and types the years of that file into it. No node, no `playwright` package or no
browser: skipped, with the reason."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BROWSERS = "/opt/pw-browsers"          # where this project's machines keep Chromium; anywhere else playwright's default holds


def run(script: str, timeout: int) -> str:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    env = dict(os.environ)
    if "PLAYWRIGHT_BROWSERS_PATH" not in env and Path(BROWSERS).is_dir():
        env["PLAYWRIGHT_BROWSERS_PATH"] = BROWSERS
    done = subprocess.run([node, str(ROOT / "tests" / "web" / script)], env=env, capture_output=True, text=True, encoding="utf-8", timeout=timeout)
    if done.returncode == 0 and "\nSKIP " in "\n" + done.stdout:
        pytest.skip(done.stdout.split("SKIP ", 1)[1].strip())
    assert done.returncode == 0, "\n".join(line for line in (done.stdout + done.stderr).splitlines() if not line.startswith("ok"))
    assert "all passed" in done.stdout
    return done.stdout


def test_the_price_book_s_arithmetic_is_the_python_s() -> None:
    out = run("price.mjs", 60)
    assert "a year: the worked customer" in out and "the worked customer pays 130,240.00 a year" in out and "every line of the price book is a row of docs/reference/MARKET.md" in out


def test_the_calculator_shows_the_same_numbers_and_moves_the_acceptance_tiers() -> None:
    out = run("pricing.mjs", 170)
    assert "the tiers move" in out and "The rated party never pays." in out and "Connecting a supplier costs nothing." in out
