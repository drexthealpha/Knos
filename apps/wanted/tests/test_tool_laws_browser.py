"""The browser half of laws L03, L07, L08, L12, L17, L18, L21 and L23 on the tool and result pages (tool_laws.mjs, in
Chromium against the app run locally). No node, no `playwright` package (NODE_PATH) or no browser (KNOS_CHROME): skipped,
with the reason."""
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).parent


def test_the_tool_pages_laws_in_a_browser():
    exe = shutil.which("node")
    if not exe:
        pytest.skip("node is not installed")
    run = subprocess.run([exe, str(HERE / "tool_laws.mjs")], env={**os.environ, "PYTHON": sys.executable}, capture_output=True,
                         text=True, encoding="utf-8", timeout=900)
    said = run.stdout.strip().splitlines()
    if run.returncode == 0 and said and said[-1].startswith("SKIP"):
        pytest.skip(said[-1][5:])
    assert run.returncode == 0, "\n".join(x for x in (run.stdout + run.stderr).splitlines() if not x.startswith("ok"))
