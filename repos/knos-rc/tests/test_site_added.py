"""Pages added to the site by name (web/views.js ADDED), and the file the "Check every claim yourself" page is drawn from.

tests/web/added.mjs drives the mount in headless Chromium on a build of web/: the link in the menu, the grey bars at
the press, the module's drawing, the enforcement matrix and the judges' rows on data of the documented shapes, and the
width of each. No node, no `playwright` package or no browser: that part is skipped, with the reason.
scripts/judges.py `read` is held here without a browser: the rows of a JUDGES.md, cell for cell.
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import _posix
import pytest

ROOT = Path(__file__).resolve().parents[1]
BROWSERS = "/opt/pw-browsers"          # where this project's machines keep Chromium; anywhere else playwright's default holds

PAGE = """# For judges

One page.

| Judged | What exists | Evidence |
| --- | --- | --- |
| How well it works | A payment **ran** on the public program ids. | [the transaction](https://explorer.solana.com/tx/abc?cluster=devnet) |
| Potential impact | One count both sides compute. | [docs/reference/WHY.md](reference/WHY.md#the-buyer) |
| Open source | Every test is in the tree. | [`tests/`](../tests/test_ledger.py) |

## What is not real yet

- Outside funders: 0.
- Interviews: 0.

## After

- not this
"""


def _script():
    spec = importlib.util.spec_from_file_location("judges_rows", ROOT / "scripts" / "judges.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_judges_file_is_the_documents_rows_cell_for_cell():
    got = _script().read(PAGE)
    assert got["columns"] == ["Judged", "What exists", "Evidence"]
    assert [r["thing"] for r in got["rows"]] == ["How well it works", "Potential impact", "Open source"]
    assert got["rows"][0] == {"thing": "How well it works", "sentence": "A payment ran on the public program ids.",
                              "link": "https://explorer.solana.com/tx/abc?cluster=devnet", "label": "the transaction"}
    # a link inside docs/ and one that climbs out of it both become addresses of the repository
    assert got["rows"][1]["link"] == "https://github.com/drexthealpha/Knos/blob/main/docs/reference/WHY.md#the-buyer"
    assert got["rows"][2]["link"] == "https://github.com/drexthealpha/Knos/blob/main/tests/test_ledger.py" and got["rows"][2]["label"] == "`tests/`"
    assert got["not_real"] == ["Outside funders: 0.", "Interviews: 0."]


def test_a_page_with_no_table_has_no_rows_and_the_build_carries_the_committed_file(tmp_path: Path):
    assert _script().read("# For judges\n\nNo table here.\n")["rows"] == []
    # one file, one shape: what the build hands the page is docs/judges.json, which scripts/judges.py holds to the page
    data = json.loads((ROOT / "docs" / "judges.json").read_text(encoding="utf-8"))
    assert _script().problems() == [] and data == _script().build()
    assert all(set(r) == {"id", "thing", "sentence", "link", "label"} for r in data["rows"]) and data["not_real"]
    assert not (ROOT / "scripts" / "judges_json.py").exists()


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


def test_the_added_pages_in_a_browser(tmp_path: Path):
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
    run = subprocess.run([node, str(ROOT / "tests" / "web" / "added.mjs"), str(site)], env=env, capture_output=True, text=True, encoding="utf-8", timeout=300)
    said = run.stdout.strip().splitlines()
    if run.returncode == 0 and said and said[-1].startswith("SKIP"):
        pytest.skip(said[-1][5:])
    assert run.returncode == 0, "\n".join(line for line in (run.stdout + run.stderr).splitlines() if not line.startswith("ok"))
    assert "added: every check held" in run.stdout
