"""The demand check's wake page (web/wanted.html) pings the free Render instance's /healthz until it answers and then
opens the app. It is a page of the app's build only: the published Pages build (scripts/site_pages.py --sweep, run by
scripts/build_site.sh when KNOS_SPA_AT_ROOT is not 1) turns it into a page that sends a visitor to the front door."""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_the_wake_page_wakes_the_app():
    page = (ROOT / "web" / "wanted.html").read_text(encoding="utf-8")
    assert "https://knos.onrender.com" in page and "/healthz" in page and "location.replace" in page
    assert not (ROOT / "docs" / "wanted.html").exists()          # Pages builds from web/, not docs/


def test_the_published_build_sends_the_wake_page_to_the_front_door(tmp_path: Path):
    sys.path.insert(0, str(ROOT / "scripts"))
    import site_pages
    shutil.copy(ROOT / "web" / "wanted.html", tmp_path / "wanted.html")
    assert site_pages.sweep(tmp_path) == 1
    stub = (tmp_path / "wanted.html").read_text(encoding="utf-8")
    assert 'http-equiv="refresh" content="0; url=./"' in stub and 'content="noindex"' in stub and "/healthz" not in stub
