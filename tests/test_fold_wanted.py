"""apps/wanted/ (Knos Wanted, folded in from drexthealpha/knos-wanted in 0.3.31): its own suite runs against the Knos of
the same commit, and the app keeps the repository rules it had as a repository of its own."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "apps" / "wanted"


def test_the_apps_own_suite_passes_against_this_knos():
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(ROOT / "src"), str(APP)])}
    # from the Knos root: PYTHONPATH=src:apps/wanted python -m pytest -q apps/wanted
    # two workers, each file on one of them (--dist loadfile): the suite outgrew the slow shard's 5 minutes on Windows
    # (5m25s, F1B); with no pytest-xdist it runs as before
    par = ["-n", "2", "--dist", "loadfile"] if __import__("importlib").util.find_spec("xdist") else []
    got = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *par, "apps/wanted"], cwd=ROOT, env=env,
                         capture_output=True, text=True, timeout=600)
    assert got.returncode == 0, got.stdout[-3000:] + got.stderr[-2000:]
    assert " passed" in got.stdout and " failed" not in got.stdout


def test_the_app_installs_knos_from_this_tree_not_from_a_pinned_commit():
    project = (APP / "pyproject.toml").read_text(encoding="utf-8")
    assert "git+https://github.com/drexthealpha/Knos@" not in project, "the folded app must use the Knos of its own commit"
    assert 'hold = ["knos", "solders>=0.29"]' in project               # the extra that installs the hold code
    docker = (APP / "Dockerfile").read_text(encoding="utf-8")
    assert "COPY src ./src" in docker and "COPY apps/wanted ./apps/wanted" in docker and "apps/wanted/Dockerfile" in docker


def test_no_recorded_answer_is_kept_in_the_monorepo():
    ignored = (APP / ".gitignore").read_text(encoding="utf-8").split()
    assert ".cache/" in ignored and "probe.json" in ignored and ".env" in ignored
    tracked = subprocess.run(["git", "ls-files", "apps/wanted"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()
    assert not [p for p in tracked if p.endswith(".json") and (ROOT / p).exists()], "no recorded body (or any JSON) is kept under apps/wanted"
