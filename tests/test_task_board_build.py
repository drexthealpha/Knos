"""The site's build writes the task board's empty answer (scripts/build_site.sh runs scripts/task_board.py `status
--json --empty`). Held apart from tests/test_task_board.py, which skips where tasks/ is not kept: this step runs in
every build of the public repository."""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

from knos import playground

ROOT = Path(__file__).resolve().parents[1]


def _task_board():
    spec = importlib.util.spec_from_file_location("task_board_build", ROOT / "scripts" / "task_board.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_sites_build_writes_the_empty_board_without_solders():
    """scripts/build_site.sh runs `status --json --empty` with a bare python3 (tests.yml's web job installs no package):
    the script must not import knos.settle.v2.pay, and so solders, to say it read nothing."""
    tb = _task_board()
    blocked = ("import runpy, sys; sys.modules['solders'] = None; sys.argv = [sys.argv[1], 'status', '--json', '--empty']; "
               "runpy.run_path(sys.argv[0], run_name='__main__')")
    run = subprocess.run([sys.executable, "-c", blocked, str(ROOT / "scripts" / "task_board.py")], capture_output=True, text=True, encoding="utf-8",
                         env={**os.environ, "PYTHONPATH": ""}, timeout=60)
    assert run.returncode == 0, run.stderr
    assert json.loads(run.stdout) == {"v": 1, "read": False, "repository": playground.REPO, "note": tb.FIRST, "tasks": []}
