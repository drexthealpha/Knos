"""The supplier's page (web/supplier.js): tests/web/supplier.mjs, alone and with its page.

The page classes a path the way `knos preflight` does. tests/data/supplier_cases.json holds paths and the Python's
answer for each; this file checks it against the Python (and writes it with WRITE_SUPPLIER_CASES=1), and the node script
holds the page's function to it. With `page` the script opens the control in headless Chromium: the published samples,
the tree in three classes, one path tried, the refusal table searched, a GitHub issue read with one GET, every
statement twelve words at most, nothing running off the side from 320 to 1280 px, nobody else asked. No node, no
`playwright` package or no browser: skipped, with the reason."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from knos import preflight, terms

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "tests" / "data" / "supplier_cases.json"
BROWSERS = "/opt/pw-browsers"
MERGE = {"accept": "", "checks": [{"app": 15368, "name": "unit"}], "deny": [".github/**", ".knos/**"], "mode": "merge", "paths": ["src/**", "tests/**"], "reserve": 7, "v": 1}
TESTS = {**MERGE, "mode": "tests", "accept": "cd" * 32, "paths": []}
SCOPED = {**TESTS, "paths": ["src/**"]}
PATHS = [("M", "src/app.py"), ("A", "src/new.py"), ("M", "README.md"), ("M", ".github/workflows/ci.yml"), ("A", ".knos/policy.yml"), ("M", "tests/test_app.py"),
         ("A", "tests/test_mine.py"), ("D", "tests/test_app.py"), ("M", "tests/conftest.py"), ("A", "conftest.py"), ("M", "pytest.ini"), ("M", "tox.ini"),
         ("A", "tests/data/case.json"), ("M", "tests/data/case.json"), ("A", "test/test_x.py"), ("M", "docs/tests/readme.md"), ("A", "src/test_inline.py")]


def _cases() -> list[dict]:
    out = []
    for name, t in (("paid on a merge", MERGE), ("paid on its checks", TESTS), ("paid on its checks, inside src/", SCOPED)):
        report = preflight.run(preflight.read_terms(terms.canonical(t).decode("ascii")), PATHS)
        rows = {(r["status"], r["path"]): r for r in report["changes"]}
        out.append({"name": name, "terms": terms.canonical(t).decode("ascii"),
                    "paths": [{"path": p, "status": s, "class": rows[(s, p)]["class"], "code": rows[(s, p)].get("code", "")} for s, p in PATHS]})
    return out


def test_the_cases_the_page_is_held_to_are_the_pythons_answers():
    want = json.dumps({"about": "paths and what `knos preflight` says of each (tests/test_site_supplier.py writes this)", "cases": _cases()}, indent=1) + "\n"
    if os.environ.get("WRITE_SUPPLIER_CASES") == "1":
        CASES.write_text(want, encoding="utf-8")
    assert CASES.read_text(encoding="utf-8") == want, "tests/data/supplier_cases.json is behind: WRITE_SUPPLIER_CASES=1 writes it"
    classes = {p["class"] for c in json.loads(want)["cases"] for p in c["paths"]}
    assert classes == {"allowed", "allowed_not_counted", "refused"}


def _node(*args: str) -> subprocess.CompletedProcess:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    env = dict(os.environ)
    if "PLAYWRIGHT_BROWSERS_PATH" not in env and Path(BROWSERS).is_dir():
        env["PLAYWRIGHT_BROWSERS_PATH"] = BROWSERS
    return subprocess.run([node, str(ROOT / "tests" / "web" / "supplier.mjs"), *args], env=env, capture_output=True, text=True, encoding="utf-8", timeout=170)


def test_the_pages_rules_are_the_command_lines():
    run = _node()
    assert run.returncode == 0 and "all passed" in run.stdout, "\n".join(line for line in (run.stdout + run.stderr).splitlines() if not line.startswith("ok"))


def test_the_page_shows_what_will_be_checked_and_asks_nobody_else():
    run = _node("page")
    if run.returncode == 0 and "\nSKIP " in "\n" + run.stdout:
        pytest.skip(run.stdout.split("SKIP ", 1)[1].strip())
    assert run.returncode == 0 and "all passed" in run.stdout, "\n".join(line for line in (run.stdout + run.stderr).splitlines() if not line.startswith("ok"))
    assert "1280px: every statement is twelve words at most" in run.stdout


def test_the_page_names_no_host_but_githubs_and_sends_nothing():
    source = (ROOT / "web" / "supplier.js").read_text(encoding="utf-8")
    hosts = {h for h in __import__("re").findall(r"https://([A-Za-z0-9.-]+)", source)}
    assert hosts <= {"api.github.com", "github.com"}, hosts
    assert "method:" not in source and "POST" not in source and "localStorage" not in source and "body:" not in source
