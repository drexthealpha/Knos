"""Close one invoice in 30 seconds: tests/web/close30.mjs on a build of web/, and docs/FINANCE.md held to what it wrote.

The node script opens the site at #approve in headless Chromium, on a slow phone (360 px, processor 4 times slower,
slow 4G) and at 1280 px, with the mouse and with the keyboard alone: the sample, the name and role, Approve, and the
accounting file saved. At most 4 clicks; at most 30 s on the slow phone with a person's pace added. No node, no
`playwright` package or no browser: skipped, with the reason."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import _posix
import pytest

ROOT = Path(__file__).resolve().parents[1]
BROWSERS = "/opt/pw-browsers"
ROWS = {("Slow phone, 360 px wide", "mouse"): "android_mouse", ("Slow phone, 360 px wide", "keyboard"): "android_keyboard",
        ("Laptop, 1280 px wide", "mouse"): "desktop_mouse", ("Laptop, 1280 px wide", "keyboard"): "desktop_keyboard"}


def test_a_close_takes_four_clicks_at_most_and_under_30_seconds(tmp_path: Path) -> None:
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
    run = subprocess.run([node, str(ROOT / "tests" / "web" / "close30.mjs"), str(site)], env=env, capture_output=True, text=True, encoding="utf-8", timeout=170)
    said = run.stdout.strip().splitlines()
    if run.returncode == 0 and said and said[-1].startswith("SKIP"):
        pytest.skip(said[-1][5:])
    assert run.returncode == 0 and "close30: all passed" in run.stdout, "\n".join(line for line in (run.stdout + run.stderr).splitlines() if not line.startswith("ok"))


def test_the_finance_page_states_what_the_script_wrote() -> None:
    close = json.loads((ROOT / "docs" / "perf.json").read_text(encoding="utf-8"))["close"]
    assert close["limit_ms"] == 30_000 and close["most_clicks"] == 4 and "No person was timed" in close["what"]
    page = (ROOT / "docs" / "FINANCE.md").read_text(encoding="utf-8")
    section = page.split("## 4b. Close in 30 seconds", 1)[1].split("\n## ", 1)[0]
    found = {}
    for screen, how, clicks, script, person in re.findall(r"^\| ([^|]+?) \| (mouse|keyboard) \| (\d+) \| ([\d.]+) s \| ([\d.]+) s \|$", section, re.M):
        found[ROWS[(screen, how)]] = (int(clicks), script, person)
    assert set(found) == set(ROWS.values())
    for key, (clicks, script, person) in found.items():
        row = close[key]
        assert clicks == row["clicks"] <= 4, key
        assert script == f"{row['script_ms']['median'] / 1000:.1f}" and person == f"{row['with_person_pace_ms']['median'] / 1000:.1f}", key
        if key.startswith("android"):
            assert row["with_person_pace_ms"]["max"] < close["limit_ms"], key
