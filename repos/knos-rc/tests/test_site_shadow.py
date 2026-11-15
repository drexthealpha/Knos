"""Shadow mode in the browser (web/shadow.js): tests/web/shadow.mjs, run with its page.

The node script first holds the page's functions to the Python's bytes with no browser (tests/test_shadow.py runs that
part too). With `page` it then opens the control in headless Chromium, on web/ as it stands, against GitHub's answers
from tests/data/shadow_cases.json served over HTTP: a row per line, the disputed share as the one number, the sha256
and both downloads equal to the Python's, the budget shown and respected, the sample marked as a sample, every
statement twelve words at most, nothing running off the side at 320 and 390 px, and nobody asked but the page's own
server and api.github.com, with GET, no body and no login. No node, no `playwright` package or no browser: skipped,
with the reason."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BROWSERS = "/opt/pw-browsers"          # where this project's machines keep Chromium; anywhere else playwright's default holds


def test_the_page_checks_an_invoice_and_sends_it_nowhere() -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    env = dict(os.environ)
    if "PLAYWRIGHT_BROWSERS_PATH" not in env and Path(BROWSERS).is_dir():
        env["PLAYWRIGHT_BROWSERS_PATH"] = BROWSERS
    run = subprocess.run([node, str(ROOT / "tests" / "web" / "shadow.mjs"), "page"], env=env, capture_output=True, text=True, encoding="utf-8", timeout=170)
    if run.returncode == 0 and "\nSKIP " in "\n" + run.stdout:
        pytest.skip(run.stdout.split("SKIP ", 1)[1].strip())
    assert run.returncode == 0, "\n".join(line for line in (run.stdout + run.stderr).splitlines() if not line.startswith("ok"))
    assert "all passed" in run.stdout and "the downloaded JSON is the Python's bytes" in run.stdout


def test_the_module_asks_no_host_but_github_s_api_and_holds_no_way_to_send() -> None:
    """Read as text: the only address in web/shadow.js is api.github.com, it sends no method but GET (fetch's default),
    and it imports motion.js only inside a guard, so the page is whole before that file exists."""
    import re
    source = (ROOT / "web" / "shadow.js").read_text(encoding="utf-8")
    code = "\n".join(line.split("//")[0] if line.lstrip().startswith("//") else line for line in source.splitlines())
    hosts = set(re.findall(r"https?://([\w.-]+)", code.split("export const SAMPLE")[0] + code.split("`;", 1)[1]))
    assert hosts == {"api.github.com", "github.com"}, hosts        # github.com: the link to a pull request, for a person to follow
    asks = re.findall(r"fetchFn\(([^,)]*)", code)
    assert len(asks) == 2 and all(a.startswith("`${API}/") for a in asks) and 'const API = "https://api.github.com";' in code, asks
    assert "globalThis.fetch(...a)" in code and code.count("fetch(") == 1
    assert not re.search(r"method\s*:|\.send\(|XMLHttpRequest|sendBeacon|WebSocket|localStorage|document\.cookie|body\s*:", code)
    assert re.search(r'try \{ const motion = await import\("\./motion\.js"\);[^\n]*\} catch \{', code) and code.count("motion.js") == 1
    assert [m for m in re.findall(r'^import .* from "(.*)";$', code, re.M)] == ["./front.js"]
