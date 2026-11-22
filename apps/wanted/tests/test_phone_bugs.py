"""test_phone_bugs, the code half (scripts/test_phone_bugs.py is the live half): SSO tries Jackson again
on 429 and says plainly when it is still busy; the sign-in sheet shows only what works; "Who wants it" shows only
segments tied to the idea; every Knos page carries the crow icon set."""
import io
import re
import urllib.error
from pathlib import Path

import pytest

from knos_wanted import enterprise

STATIC = Path(enterprise.__file__).parent / "static"
WEB = Path(enterprise.__file__).resolve().parents[3] / "web"


class Flaky:
    """An opener that answers 429 `n` times, then 200 with a JSON body."""
    def __init__(self, n):
        self.n, self.calls = n, 0

    def __call__(self, req, timeout=None):
        self.calls += 1
        if self.calls <= self.n:
            raise urllib.error.HTTPError(req.full_url, 429, "Too Many Requests", {"Retry-After": "1"}, io.BytesIO(b""))
        return io.BytesIO(b"[]")


def test_jackson_429_is_tried_again_and_a_lasting_one_reads_plainly(monkeypatch):
    slept = []
    monkeypatch.setattr(enterprise, "_sleep", slept.append)
    op = Flaky(2)
    assert enterprise._http("GET", "https://sso.example/api/v1/sso", opener=op) == [] and op.calls == 3 and slept == [1.0, 1.0]
    slept.clear()
    with pytest.raises(enterprise.SSOError, match="busy right now; try again in a minute"):
        enterprise._http("GET", "https://sso.example/api/v1/sso", opener=Flaky(99))
    assert sum(slept) <= enterprise.RETRY_BUDGET_S


def test_the_sign_in_sheet_shows_only_what_works():
    page = (STATIC / "index.html").read_text(encoding="utf-8")
    sheet = page[page.index('<section id="signin"'):page.index("</section>", page.index('<section id="signin"'))]
    assert "Not available" not in sheet and " disabled" not in sheet




def test_every_knos_page_carries_the_crow_icon_set():
    pages = [*STATIC.glob("*.html"), WEB / "index.html", WEB / "faq.html", WEB / "privacy.html", WEB / "404.html",
             WEB / "wanted.html", WEB / "check" / "index.html"]
    for p in pages:
        head = p.read_text(encoding="utf-8").split("</head>")[0]
        for rel in ("icon.svg", "favicon.ico", "apple-touch-icon.png"):
            assert re.search(r'<link rel="(?:icon|apple-touch-icon)" href="[^"]*' + re.escape(rel), head), (p.name, rel)
    assert (STATIC / "icon.svg").read_bytes() == (WEB / "icon.svg").read_bytes()                  # the crow, not a placeholder
    assert (STATIC / "favicon.ico").read_bytes()[:4] == b"\x00\x00\x01\x00"
    assert '"/static/brand/icon-512.png"' in (STATIC / "manifest.webmanifest").read_text(encoding="utf-8")
