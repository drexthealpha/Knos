"""The Hold a key page (web/keyholder.js): tests/web/keyholder.mjs, run on web/ as it stands.

The node script first checks, on node's own WebCrypto, that the key the page makes is a Solana keypair file whose
address is its public half, and that the request it writes carries the public key only. In headless Chromium it then
makes a key in the page, saves its file, and reads the prefilled issue; shows what a browser with no Ed25519 is told;
and holds the page to twelve words a statement, to no sideways scroll, and to asking nobody but its own site. No node:
skipped. No `playwright` package or no browser: the first part still ran, and the test says the rest was skipped."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BROWSERS = "/opt/pw-browsers"          # where this project's machines keep Chromium; anywhere else playwright's default holds


def test_a_key_is_made_in_the_page_and_only_its_public_half_is_asked_with() -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    env = dict(os.environ)
    if "PLAYWRIGHT_BROWSERS_PATH" not in env and Path(BROWSERS).is_dir():
        env["PLAYWRIGHT_BROWSERS_PATH"] = BROWSERS
    run = subprocess.run([node, str(ROOT / "tests" / "web" / "keyholder.mjs"), str(ROOT / "web")], env=env, capture_output=True, text=True,
                         encoding="utf-8", timeout=170)
    assert run.returncode == 0, "\n".join(line for line in (run.stdout + run.stderr).splitlines() if not line.startswith("ok"))
    assert "ok   the seed in the file gives that public key back" in run.stdout
    if "\nSKIP " in "\n" + run.stdout:
        pytest.skip(run.stdout.split("SKIP ", 1)[1].strip())
    assert "all passed" in run.stdout and "ok   page: the file saved is a Solana keypair file of that key" in run.stdout


def test_nobody_outside_holds_a_key_and_every_page_that_counts_says_zero() -> None:
    """web/keyholders.json is the count; the documents that state it must agree with it."""
    listed = json.loads((ROOT / "web" / "keyholders.json").read_text(encoding="utf-8"))["outside"]
    said = f"Outside key holders today: {len(listed)}"
    for name in ("KEYHOLDER.md", "GOVERNANCE.md", "TEAM.md", "DISCLOSURE.md"):
        text = " ".join((ROOT / "docs" / "reference" / name).read_text(encoding="utf-8").replace("**", "").split())
        assert said in text, name
