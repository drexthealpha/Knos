"""Launch day for a stranger: the missing page, the page whose data did not load, a cheap phone, a shared link, privacy.

The tags of a shared link (web/index.html <head>) and the card they name; the 404 page GitHub Pages answers a missing
address with (web/404.html); the privacy and terms page (web/privacy.html), each of its lines held to the code it
describes; the line every page shows when a data file does not load (web/retry.js). In a browser, on a build of web/:
tests/web/launch.mjs (404, privacy, data files refused) and tests/web/android.mjs (360 x 740, CPU 4x slower, slow 4G).
No node, no `playwright` package or no browser: those two are skipped, with the reason."""

from __future__ import annotations

import os
import re
import shutil
import struct
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path

import _posix
import pytest

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
BROWSERS = "/opt/pw-browsers"
SITE = "https://drexthealpha.github.io/Knos/"
WORD = re.compile(r"[A-Za-z0-9][\w'’%.,/#-]*")


class _Head(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tags: list[tuple[str, dict[str, str]]] = []
        self.title = ""
        self._in_title = False
        self._in_head = True

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "body":
            self._in_head = False
        if self._in_head:
            self.tags.append((tag, {k: v or "" for k, v in attrs}))
            self._in_title = tag == "title"

    def handle_endtag(self, tag: str) -> None:
        self._in_title = False if tag == "title" else self._in_title

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data


def _head(name: str) -> _Head:
    head = _Head()
    head.feed((WEB / name).read_text(encoding="utf-8"))
    return head


def _meta(head: _Head, key: str) -> list[str]:
    return [a.get("content", "") for t, a in head.tags if t == "meta" and (a.get("property") == key or a.get("name") == key)]


def _link(head: _Head, rel: str) -> list[str]:
    return [a.get("href", "") for t, a in head.tags if t == "link" and a.get("rel") == rel]


def test_a_shared_link_has_every_tag_and_one_address() -> None:
    head = _head("index.html")
    title = head.title.strip()
    assert title.startswith("Knos. ") and _meta(head, "og:title") == [title] and _meta(head, "twitter:title") == [title]
    (description,) = _meta(head, "description")
    assert 40 <= len(description) <= 160 and _meta(head, "og:description") == [description] == _meta(head, "twitter:description")
    assert _link(head, "canonical") == [SITE] == _meta(head, "og:url")
    assert _meta(head, "twitter:card") == ["summary_large_image"] and _meta(head, "og:type") == ["website"]
    image = SITE + "brand/card.png"
    assert _meta(head, "og:image") == [image] == _meta(head, "twitter:image")
    assert _meta(head, "og:image:width") == ["1200"] and _meta(head, "og:image:height") == ["630"]
    assert _meta(head, "og:image:alt") == _meta(head, "twitter:image:alt") and _meta(head, "og:image:alt")[0]


def test_the_card_is_a_1200_by_630_png_of_the_site_drawn_from_the_brand() -> None:
    card = (WEB / "brand" / "card.png").read_bytes()
    assert card[:8] == b"\x89PNG\r\n\x1a\n" and card[12:16] == b"IHDR"
    assert struct.unpack(">II", card[16:24]) == (1200, 630)
    assert 10_000 < len(card) < 600_000           # large enough to be a picture, small enough for a link preview
    assert "brand/card.png" in (ROOT / "scripts" / "build_site.sh").read_text(encoding="utf-8")


def test_the_browser_bar_takes_the_page_colour_in_dark_and_light() -> None:
    css = (WEB / "app.css").read_text(encoding="utf-8")
    dark = re.search(r":root \{\s*--paper: (#[0-9a-f]{6})", css)
    light = re.search(r':root\[data-theme="light"\] \{\s*--paper: (#[0-9a-f]{6})', css)
    assert dark and light
    for name in ("index.html", "404.html", "privacy.html"):
        colours = [(a.get("content"), a.get("media")) for t, a in _head(name).tags if t == "meta" and a.get("name") == "theme-color"]
        assert colours == [(dark[1], None), (light[1], "(prefers-color-scheme: light)")], name


def test_the_data_line_is_loaded_before_the_pages_ask_for_anything() -> None:
    html = (WEB / "index.html").read_text(encoding="utf-8")
    assert html.index('<script type="module" src="retry.js"></script>') < html.index("</head>") < html.index('<script type="module" src="front.js"></script>')
    js = (WEB / "retry.js").read_text(encoding="utf-8")
    assert "answer.status >= 500" in js and "location.reload()" in js and "Try again: " in js
    assert not re.search(r"https?://", js.split("\n", 5)[-1])         # it asks nobody


def _external(name: str) -> list[str]:
    """What a page would load from another host: a stylesheet, a script, an image, a font (links to follow are fine)."""
    html = (WEB / name).read_text(encoding="utf-8")
    loads = re.findall(r'<(?:script|img|source|video|audio|iframe)[^>]*\ssrc="([^"]+)"', html)
    loads += [h for rel, h in re.findall(r'<link rel="([^"]+)" href="([^"]+)"', html) if rel not in ("canonical", "alternate")]
    return [u for u in loads if re.match(r"(https?:)?//", u)]


def _statements(name: str, selector: str) -> list[str]:
    html = (WEB / name).read_text(encoding="utf-8")
    body = html.split("<main>", 1)[1].split("</main>", 1)[0]
    return [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", m)).strip() for m in re.findall(rf"<{selector}[^>]*>(.*?)</{selector}>", body, re.S)]


def test_the_404_page_is_the_sites_own_from_any_depth() -> None:
    html = (WEB / "404.html").read_text(encoding="utf-8")
    assert '<base href="/Knos/">' in html and html.index("<base") < html.index('href="app.css"')
    assert '<meta name="robots" content="noindex">' in html and _external("404.html") == []
    links = re.findall(r'<li><a href="([^"]+)"', html)
    assert links == ["./", "./#pricing", "https://github.com/drexthealpha/Knos/tree/main/docs"]
    assert 'href="privacy.html"' in html
    for line in _statements("404.html", "h1") + _statements("404.html", "li"):
        assert len(WORD.findall(line)) <= 12, line


PRIVACY_LINES = {
    "Sets no cookies.",
    "Runs no analytics and no tracker.",
    "Serves its own fonts, scripts and images.",
    "Sends nothing to Knos.",
    "Asks GitHub's API and Solana devnet straight from your browser.",
    "Keeps what it read in this tab until you close it.",
    "Keeps your light or dark choice in this browser.",
    "Keeps a passkey's public key in this browser, if you make one.",
    "Keeps its files on your own machine.",
    "Asks GitHub and Solana devnet when a command needs them.",
    "Runs on Solana devnet: the money is test USDC.",
    "Uses the MIT licence: read it.",
    "Comes with no warranty, as the licence says.",
    "Report a problem in GitHub issues.",
    "Read what a payment makes public.",
}


def test_the_privacy_page_says_each_thing_in_twelve_words_or_fewer_and_loads_nothing_from_outside() -> None:
    lines = _statements("privacy.html", "li")
    assert set(lines) == PRIVACY_LINES and len(lines) == len(PRIVACY_LINES)
    assert all(len(WORD.findall(line)) <= 12 for line in lines)
    assert _external("privacy.html") == []
    text = " ".join(lines)
    for word in ("wallet", "hash", "pin", "token account", "bulletproof", "trustless", "immutable"):
        assert not re.search(rf"\b{word}\b", text, re.I), word


def _code() -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in sorted(WEB.glob("*.js")) + sorted((WEB / "brand").glob("*.js")))


def test_each_privacy_line_agrees_with_the_code() -> None:
    code = _code()
    assert "document.cookie" not in code and "cookieStore" not in code                       # no cookies
    hosts = set(re.findall(r'fetch\(\s*[`"](https://[A-Za-z0-9.-]+)', code))                # whom the pages fetch from
    # (every host a page asks is also refused and counted in the browser: tests/web/launch.mjs "nothing outside the site")
    assert hosts <= {"https://api.github.com", "https://api.devnet.solana.com"}, hosts
    for tracker in ("google-analytics", "googletagmanager", "plausible", "segment.com", "posthog", "mixpanel", "sentry"):
        assert tracker not in code.lower(), tracker
    assert "sessionStorage" in (WEB / "cache.js").read_text(encoding="utf-8")               # this tab, until it closes
    assert 'localStorage.setItem("knos-theme"' in (WEB / "front.js").read_text(encoding="utf-8")
    stored = {p.name for p in WEB.glob("*.js") if "localStorage.setItem" in p.read_text(encoding="utf-8")}
    assert stored == {"front.js", "claim.js", "buyer.js", "payee.js"}, stored                # the theme, and a passkey
    for name in ("claim.js", "buyer.js", "payee.js"):
        assert "credentialId" in (WEB / name).read_text(encoding="utf-8") and "key: " in (WEB / name).read_text(encoding="utf-8")
    licence = (ROOT / "LICENSE").read_text(encoding="utf-8")
    assert licence.startswith("MIT License") and "WITHOUT WARRANTY OF ANY KIND" in licence
    fonts = re.findall(r"url\(([^)]+)\)", (WEB / "app.css").read_text(encoding="utf-8"))
    assert fonts and not any(re.match(r"[\"']?(https?:)?//", u) for u in fonts)            # its own fonts


def _node(tmp_path: Path, script: str, says: str) -> str:
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
    for name in ("404.html", "privacy.html", "retry.js"):
        assert (site / name).is_file(), name
    run = subprocess.run([node, str(ROOT / "tests" / "web" / script), str(site)], env=env, capture_output=True, text=True, encoding="utf-8", timeout=300)
    said = run.stdout.strip().splitlines()
    if run.returncode == 0 and said and said[-1].startswith("SKIP"):
        pytest.skip(said[-1][5:])
    assert run.returncode == 0, "\n".join(line for line in (run.stdout + run.stderr).splitlines() if not line.startswith("ok"))
    assert says in run.stdout
    return run.stdout


def test_the_404_page_privacy_and_a_data_file_that_does_not_load_in_a_browser(tmp_path: Path) -> None:
    said = _node(tmp_path, "launch.mjs", "launch: all passed")
    for line in ("404: a missing address answers 404 at 320", "/Knos/pricing offers the pricing page first", "no page sets a cookie",
                 "#network reads stats.json and, when it does not load, says so", "none blank, none with a stack", "Reload, once the file loads"):
        assert line in said, line


def test_a_cheap_android_phone_paints_and_can_be_used_within_three_seconds(tmp_path: Path) -> None:
    said = _node(tmp_path, "android.mjs", "android: all passed")
    assert "ok   android: first contentful paint under 3000 ms" in said and "ok   android: the first screen usable under 3000 ms" in said
