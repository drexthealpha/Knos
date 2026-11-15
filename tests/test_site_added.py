"""Pages added to the site by name (web/views.js ADDED): a build of web/ lists in its views.js exactly the added pages
whose files (and data file, when a page names one) the build holds, and each data file it holds is JSON. No browser
test drives the mount any more (tests/web/added.mjs was removed on 6 Nov 2026).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import _posix

ROOT = Path(__file__).resolve().parents[1]
BROWSERS = "/opt/pw-browsers"          # where this project's machines keep Chromium; anywhere else playwright's default holds


def test_the_build_offers_only_the_pages_it_holds(tmp_path: Path):
    site = tmp_path / "site"
    env = _posix.environ({**os.environ, "PYTHON": _posix.path(sys.executable), "PYTHONPATH": str(ROOT / "src")})
    built = subprocess.run([_posix.bash(), _posix.path(ROOT / "scripts" / "build_site.sh"), _posix.path(site), "c" * 40],
                           env=env, capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert built.returncode == 0, built.stdout + built.stderr
    views = (site / "views.js").read_text(encoding="utf-8")
    assert "export const ADDED = {" in views and "export const VIEWS" in views
    for line in (ROOT / "web" / "views.js").read_text(encoding="utf-8").splitlines():
        if not line.startswith("  ") or '{ file: "./' not in line:
            continue
        name, file = line.split(":")[0].strip(), line.split('file: "./')[1].split('"')[0]
        data = line.split('json: "')[1].split('"')[0] if 'json: "' in line else None
        held = (site / file).is_file() and (data is None or (site / data).is_file())
        assert (line in views) == held, name
        if data and (site / data).is_file():
            json.loads((site / data).read_text(encoding="utf-8"))
