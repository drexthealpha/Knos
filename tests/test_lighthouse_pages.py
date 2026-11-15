"""What Lighthouse measures (apps/wanted/lighthouserc.js, run by .github/workflows/lighthouse.yml), at performance and
accessibility of 90 or more on a phone: every view and module page of the older single-page app (web/views.js,
web/front.js MOUNTS; web/index.html, which the Pages build no longer publishes at the root), four named HTML files, and
every view of the app (apps/wanted static/app.js VIEWS). A view added to those lists without a line in lighthouserc.js
fails this test. The pages the Pages build publishes from scripts/site_pages.py (the front door web/door.html,
claims/, prove/, agents/, labs/, pricing/, status/) are not in these lists, and nothing here checks that they are."""
from __future__ import annotations

import functools
import gzip
import http.server
import importlib.util
import re
import threading
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RC = (ROOT / "apps" / "wanted" / "lighthouserc.js").read_text(encoding="utf-8")
WF = (ROOT / ".github" / "workflows" / "lighthouse.yml").read_text(encoding="utf-8")


def _list(name: str) -> list[str]:
    body = re.search(rf"const {name} = \[(.*?)\];", RC, re.S)[1]
    return re.findall(r'"([^"]*)"', body)


def test_every_page_of_the_front_door_is_measured():
    site = _list("site")
    views = re.findall(r'"(\w+)"', re.search(r"export const VIEWS = \[(.*?)\];", (ROOT / "web" / "views.js").read_text(encoding="utf-8"), re.S)[1])
    added = re.findall(r"^\s+([\w-]+): \{ file: ", (ROOT / "web" / "views.js").read_text(encoding="utf-8"), re.M)
    mounts = re.findall(r'"([\w-]+)"', re.search(r"export const MOUNTS = \[(.*?)\.\.\.Object", (ROOT / "web" / "front.js").read_text(encoding="utf-8"), re.S)[1])
    want = {"" if v == "home" else f"#{v}" for v in views} | {f"#{m}" for m in mounts + added}
    assert want <= set(site), sorted(want - set(site))
    for f in ("faq.html", "check/", "privacy.html", "wanted.html"):
        assert f in site and (ROOT / "web" / (f + "index.html" if f.endswith("/") else f)).exists()


def test_every_view_of_the_app_is_measured():
    app = _list("app")
    js = (ROOT / "apps" / "wanted" / "knos_wanted" / "static" / "app.js").read_text(encoding="utf-8")
    views = re.findall(r'"(\w+)"', re.search(r"const VIEWS = \[(.*?)\];", js)[1])
    moved = {"buy", "teams"}                       # the money page's views (apps/wanted server.MOVED_VIEWS): at /paid
    assert {"" if v == "home" else (f"paid#{v}" if v in moved else f"#{v}") for v in views} <= set(app) and "verify" in app


def test_the_bar_is_ninety_on_a_phone_and_both_are_served():
    assert '"categories:performance": [\n          "error",\n          {\n            "minScore": 0.9' in RC
    assert '"categories:accessibility": [\n          "error",\n          {\n            "minScore": 0.9' in RC and '"formFactor": "mobile"' in RC
    assert "PORT=8080" in WF and "scripts/serve_site.py \"$RUNNER_TEMP/site\" 8081" in WF and "scripts/build_site.sh" in WF and "--config=apps/wanted/lighthouserc.js" in WF


def test_the_site_is_served_compressed_as_pages_sends_it(tmp_path):
    """scripts/serve_site.py (lighthouse.yml's server for the front door): text gzip-compressed when the browser accepts it,
    as GitHub Pages sends it; the same bytes plain otherwise; a directory's index.html; other files as they are."""
    spec = importlib.util.spec_from_file_location("serve_site", ROOT / "scripts" / "serve_site.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    page = b"<!doctype html><title>t</title>" + b"<p>the same line</p>" * 200
    (tmp_path / "index.html").write_bytes(page)
    (tmp_path / "check").mkdir()
    (tmp_path / "check" / "index.html").write_bytes(page)
    (tmp_path / "a.woff2").write_bytes(b"\x00font")
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(mod.Handler, directory=str(tmp_path)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}/"

    def get(path, gz):
        req = urllib.request.Request(base + path, headers={"Accept-Encoding": "gzip"} if gz else {})
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.headers.get("Content-Encoding"), r.headers.get("Content-Type"), r.read()
    try:
        enc, typ, body = get("", True)
        assert enc == "gzip" and typ.startswith("text/html") and gzip.decompress(body) == page and len(body) < len(page) / 5
        assert get("check/", True)[0] == "gzip" and gzip.decompress(get("check/", True)[2]) == page
        assert get("", False) == (None, typ, page)
        assert get("a.woff2", True)[0] is None and get("a.woff2", True)[2] == b"\x00font"
    finally:
        srv.shutdown()
