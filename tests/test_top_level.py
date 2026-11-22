"""No top-level entry of the repository is a system nothing uses (IQ PLAN.md L53; MISSION knos_mission_access_map.md:198):
each one is named by a workflow, a test, a script, a page or a build file (scripts/top_level.py)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_every_top_level_entry_is_used():
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "top_level.py"), "--orphans"], cwd=ROOT,
                       capture_output=True, text=True, timeout=1200)
    assert r.returncode == 0, "top-level entries nothing names (remove them, or name what uses them):\n" + r.stdout
