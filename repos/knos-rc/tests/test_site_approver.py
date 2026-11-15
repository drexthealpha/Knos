"""The approver's screen (web/approver.js): tests/web/approver.mjs, alone and with its page.

Alone, the node script holds the screen's rows to the statements of tests/data/statement, which `knos statement make`
wrote: the four line states, the line billed on an earlier statement (replayed), and the line that takes the agreed
sum past the purchase order the invoice file names (worked out by the page, as advice). With `page` it opens the
screen in headless Chromium and makes a first invoice comparison the way someone new would, timing each step; then
the sample, a receipt's five parts in place, the keyboard alone, 320 to 1280 px, twelve words a statement, no movement
when none is asked for, nobody asked but the page's own host. No node, no `playwright` package or no browser: skipped,
with the reason."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from knos import statement

ROOT = Path(__file__).resolve().parents[1]
BROWSERS = "/opt/pw-browsers"
STEPS = ["open the page", "drop the invoice and the statement", "read the result", "open one exception", "approve the ordinary lines"]


def _node(*args: str) -> subprocess.CompletedProcess:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    env = dict(os.environ)
    if "PLAYWRIGHT_BROWSERS_PATH" not in env and Path(BROWSERS).is_dir():
        env["PLAYWRIGHT_BROWSERS_PATH"] = BROWSERS
    return subprocess.run([node, str(ROOT / "tests" / "web" / "approver.mjs"), *args], env=env, capture_output=True, text=True, encoding="utf-8", timeout=170)


def _failures(run: subprocess.CompletedProcess) -> str:
    return "\n".join(line for line in (run.stdout + run.stderr).splitlines() if not line.startswith("ok"))


def test_the_rows_are_the_statements_and_the_approval_is_the_command_lines():
    run = _node()
    assert run.returncode == 0 and "all passed" in run.stdout, _failures(run)
    assert "an approval of every agreed line is the Python's" in run.stdout


def test_a_first_comparison_by_script_with_no_command_line():
    run = _node("page")
    if run.returncode == 0 and "\nSKIP " in "\n" + run.stdout:
        pytest.skip(run.stdout.split("SKIP ", 1)[1].strip())
    assert run.returncode == 0 and "all passed" in run.stdout, _failures(run)
    for said in ("320px: every statement is twelve words at most", "keys: Enter approves", "no movement asked for: the evidence appears with none", "under five minutes, with no command line"):
        assert said in run.stdout, said


def test_an_approval_that_holds_a_line_back_is_still_a_status_the_command_line_reads():
    """The page may leave an agreed line out of an approval (over its purchase order). The Python reads that status as
    it reads its own: the line left out stays unapproved, and approving again approves it."""
    st = json.loads((ROOT / "tests" / "data" / "statement" / "sept.json").read_text(encoding="utf-8"))
    whole = statement.approve(st, None, "Dana Reyes", "finance controller", "2026-10-01")
    event = whole["events"][0]
    part = {**whole, "events": [{**event, "lines": event["lines"][:1], "amount": "100.00"}]}
    now = {ln["invoice_line"]: ln["approved_by"] for ln in statement.lines_now(st, part)}
    assert [bool(now[i]) for i in event["lines"]] == [True, False]
    again = statement.approve(st, part, "Dana Reyes", "finance controller", "2026-10-02")
    assert again["events"][1]["lines"] == event["lines"][1:] and again["events"][1]["amount"] == "60.00"


def test_the_time_the_page_states_is_what_the_script_wrote():
    t = json.loads((ROOT / "web" / "approver_time.json").read_text(encoding="utf-8"))
    assert t["scripted"] is True and [s["step"] for s in t["steps"]] == STEPS
    assert t["total_ms"] == sum(s["ms"] for s in t["steps"]) < 300_000
    assert "not a person's" in t["what"]


def test_the_page_asks_no_host_and_keeps_nothing():
    source = (ROOT / "web" / "approver.js").read_text(encoding="utf-8")
    assert set(re.findall(r"https://([A-Za-z0-9.-]+)", source)) <= {"github.com"}          # two links a reader may follow; nothing is fetched from there
    assert source.count("fetch(") == 1 and "approver_time.json" in source.split("fetch(", 1)[1][:60]
    for word in ("localStorage", "sessionStorage", "sendBeacon", "XMLHttpRequest", "api.github.com", "devnet.solana"):
        assert word not in source, word
    # the one POST: an audit line to the page's own host, sent only when the self-host bundle's sign-in cookie is set
    # (ssoOf; docs/reference/SELFHOST.md); tests/web/approver.mjs shows nothing asked without it
    sso = source.split("export function ssoOf(", 1)[1].split("\n}\n", 1)[0]
    assert source.count("POST") == 2 and sso.count("POST") == 1 and 'fetchFn("/sso/act", { method: "POST"' in sso         # its comment, and the call
    assert "if (typeof fetchFn !== \"function\" || !signedIn()) return null;" in sso and "knos_signed_in=1" in source
