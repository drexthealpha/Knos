"""The payee page (web/payee.js): tests/web/payee.mjs in headless Chromium, and the reason it is not one click.

The node script makes a passkey with Chromium's virtual authenticator, reads what is held from a mocked devnet, and
checks the one link and the Bind read (its header says what else). No node, no `playwright` package or no browser:
skipped, with the reason. The rest holds the page to the deployed rule it works around: a Bind counts only from a run
started by hand, so the claim workflow keeps `workflow_dispatch` as its one trigger and the page links to that run."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BROWSERS = "/opt/pw-browsers"


def _node() -> subprocess.CompletedProcess:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    env = dict(os.environ)
    if "PLAYWRIGHT_BROWSERS_PATH" not in env and Path(BROWSERS).is_dir():
        env["PLAYWRIGHT_BROWSERS_PATH"] = BROWSERS
    return subprocess.run([node, str(ROOT / "tests" / "web" / "payee.mjs")], env=env, capture_output=True, text=True, encoding="utf-8", timeout=170)


def test_the_page_in_a_browser_with_a_virtual_passkey():
    run = _node()
    if run.returncode == 0 and "\nSKIP " in "\n" + run.stdout:
        pytest.skip(run.stdout.split("SKIP ", 1)[1].strip())
    assert run.returncode == 0 and "all passed" in run.stdout, "\n".join(ln for ln in (run.stdout + run.stderr).splitlines() if not ln.startswith("ok"))
    for said in ("held: a job less its fee", "bound to this passkey", "the clicks: 13 before, 8 now", "390px: no sideways scroll"):
        assert said in run.stdout, said


def _triggers(text: str) -> list[str]:
    on = text.split("\non:\n", 1)[1].split("\npermissions:", 1)[0]
    return re.findall(r"^  ([a-z_]+):", on, re.M)


def test_the_claim_workflow_is_started_by_hand_only_because_the_program_takes_nothing_else():
    """No trigger change: knos_pay's Bind (2.1 and 2.2) refuses any event but `workflow_dispatch`, first attempt. A push
    trigger in the template would give a run whose token the program refuses, and an address chosen by whoever wrote
    the link that filled GitHub's form. The page therefore links to the run, and the person pastes the address."""
    rust = (ROOT / "programs-v2" / "knos_pay" / "src" / "pay.rs").read_text(encoding="utf-8")
    bind = rust.split("pub fn bind(", 1)[1].split("\n}\n", 1)[0]
    assert 'let started = g.first_attempt && g.event == b"workflow_dispatch";' in bind and "!started" in bind
    for name in ("knos-claim.yml", "knos-claim-org.yml"):
        for where in (ROOT / "src" / "knos" / "settle" / name, ROOT / "examples" / name):
            assert _triggers(where.read_text(encoding="utf-8")) == ["workflow_dispatch"], where
    page = (ROOT / "web" / "payee.js").read_text(encoding="utf-8")
    assert 'WORKFLOW = "knos-claim.yml"' in page and "/knos-claim/actions/workflows/${WORKFLOW}" in page
    assert 'TEMPLATE_OWNER = "drexthealpha", TEMPLATE_NAME = "knos-claim"' in page


def test_the_page_asks_only_github_and_devnet_and_its_first_view_says_no_wallet_word():
    """The clicks table behind "Clicks" names the wallet app of the old way; the steps themselves do not."""
    page = (ROOT / "web" / "payee.js").read_text(encoding="utf-8")
    hosts = set(re.findall(r"https://([A-Za-z0-9.-]+)", page))
    assert hosts <= {"api.devnet.solana.com", "api.github.com", "github.com"}, hosts
    code = "\n".join(ln for ln in page.splitlines() if not ln.lstrip().startswith("//"))
    shown = " ".join(re.findall(r">([^<>${}]+)<", code)) + " ".join(re.findall(r'textContent = [`"]([^`"]+)', code))
    for word in ("wallet", "hash", "pin", "token account", "seed"):
        assert not re.search(rf"\b{word}\b", shown, re.I), word
