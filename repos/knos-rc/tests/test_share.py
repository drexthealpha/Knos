"""Sharing a check (web/share.js): tests/web/share.mjs, first with no browser, then in headless Chromium on web/ as it
stands. The link carries the pull request and reads back; the copied result, X's compose box (nothing posted, within 280
characters), a 1200 x 630 PNG card, and the badge offered only to a repository that merged in the last 30 days. Here too:
the badge file is well-formed SVG with no script and no outside reference, and the card is the size of the site's
link preview. No node: skipped; no `playwright` package or no browser: the browser half is skipped by the script."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BROWSERS = "/opt/pw-browsers"          # where this project's machines keep Chromium; anywhere else playwright's default holds


def test_the_badge_is_a_static_svg_that_fetches_nothing() -> None:
    text = (ROOT / "web" / "brand" / "checked.svg").read_text(encoding="utf-8")
    svg = ET.fromstring(text)
    assert svg.tag == "{http://www.w3.org/2000/svg}svg" and svg.get("height") == "20"
    assert svg.get("aria-label") == "agent PR claims: checked by Knos"
    assert "<script" not in text and "href" not in text and "url(" not in text


def test_the_card_is_the_size_of_the_sites_link_preview() -> None:
    card = (ROOT / "web" / "brand" / "card.js").read_text(encoding="utf-8")
    page = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    assert re.search(r"width: 1200,\s*height: 630,", card)
    assert '<meta property="og:image:width" content="1200">' in page and '<meta property="og:image:height" content="630">' in page
    assert 'sign: "checked by Knos: the neutral meter"' in card


def test_a_check_is_shared_by_link_copy_post_card_and_badge() -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    env = dict(os.environ)
    if "PLAYWRIGHT_BROWSERS_PATH" not in env and Path(BROWSERS).is_dir():
        env["PLAYWRIGHT_BROWSERS_PATH"] = BROWSERS
    run = subprocess.run([node, str(ROOT / "tests" / "web" / "share.mjs")], env=env, capture_output=True, text=True, encoding="utf-8", timeout=170)
    out = "\n".join(line for line in (run.stdout + run.stderr).splitlines() if not line.startswith("ok"))
    assert run.returncode == 0, out
    assert "brand/checked.svg is checkedBadgeSvg's bytes" in run.stdout
    if "\nSKIP " in "\n" + run.stdout:
        pytest.skip(run.stdout.split("SKIP ", 1)[1].strip())
    assert "all passed" in run.stdout and "360px: the card is a 1200 x 630 PNG named for the pull request" in run.stdout
