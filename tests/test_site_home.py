"""The front door's first screen at the bare address: research products people can back now (web/index.html
#view-home, web/home.js, scripts/front_snapshot.py), read from the files with no browser (tests/web/home.mjs holds the
same in Chromium). Everything technical is one page away (#view-verify); the check of agent work keeps #check."""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORD = re.compile(r"[A-Za-z0-9][\w'’%.,/-]*")
PAGE = (ROOT / "web" / "index.html").read_text(encoding="utf-8")


def _words(html: str) -> list[str]:
    return WORD.findall(re.sub(r"<[^>]+>", " ", html))


def _section(sid: str) -> str:
    page = re.sub(r"(<script\b[^>]*>).*?(</script>)", r"\1\2", PAGE, flags=re.S)    # an inline script's markup is not the page's
    # the four steps under the first screen (web/brand/steps.html) are their own part, below the fold: not its prose
    page = re.sub(r"<!-- k-steps -->.*?<!-- /k-steps -->", "", page, flags=re.S)
    i = page.index(f'<section id="{sid}"')
    return page[i:page.index("</section>", i)]


def test_the_snapshot_cards_are_the_ones_its_rows_draw():
    run = subprocess.run([sys.executable, str(ROOT / "scripts" / "front_snapshot.py"), "--check"], capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stdout + run.stderr


def test_the_bare_address_opens_on_the_products_with_three_one_tap_actions_each():
    home = _section("view-home")
    # the first screen names its buyer and has one box (web/brand/hero.html, scripts/sync_brand.py); the products follow
    mission = "See who wants your product, and where, before you build it"
    assert f'<h1 id="k-mission" class="k-mission">{mission}</h1>' in home and len(_words(mission)) <= 12
    assert '<input id="k-q" name="q"' in home and '<h2 id="home-h">Open for backing</h2>' in home
    cards = re.findall(r'<li class="hp" data-slug="([a-z0-9-]+)">(.*?)</li>', home, re.S)
    assert 1 <= len(cards) <= 3
    for slug, body in cards:
        acts = re.findall(r'<a class="k-btn( quiet)?" href="wanted\.html#(back|fund|contribute)=([a-z0-9-]+)" data-app="#\2=\3">([^<]+)</a>', body)
        assert [(a[1], a[2], a[3]) for a in acts] == [("back", slug, "Back it"), ("fund", slug, "Fund the work"), ("contribute", slug, "Contribute")]
        title = re.search(r'<h3 class="hp-t">(.*?)</h3>', body)[1]
        assert len(_words(title)) <= 12
    # the cards are a live view's rows (data-not-prose); the prose of the first screen, the bar with it, stays in its budget
    bar = PAGE[PAGE.index('<header class="bar k-bar"'):PAGE.index("</header>")]
    bar = re.sub(r'<div class="more-list".*?</div>', "", bar, flags=re.S)
    prose = re.sub(r'<ol class="hp-list".*?</ol>', " ", home, flags=re.S)
    prose = re.sub(r'<p class="fine" id="home-when" data-not-prose>.*?</p>', " ", prose, flags=re.S)
    prose = re.sub(r'<details[^>]*data-not-prose>.*?</details>', " ", prose, flags=re.S)       # the IDT benchmark's rows
    prose = re.sub(r'<ul[^>]*data-not-prose[^>]*>.*?</ul>', " ", prose, flags=re.S)          # the measured numbers (web/brand/vectors.html)
    prose = re.sub(r'<figure[^>]*data-not-prose[^>]*>.*?</figure>', " ", prose, flags=re.S)       # the crossing's shape: a state and its number
    prose = re.sub(r"<(button)\b[^>]*>.*?</\1>", " ", re.sub(r"<!--.*?-->", " ", prose, flags=re.S), flags=re.S)
    n = len(_words(re.sub(r"<button\b[^>]*>.*?</button>", " ", bar, flags=re.S))) + len(_words(prose))
    assert 12 <= n <= 64, n
    assert 'data-not-prose aria-label="Research products open for backing now"' in home
    # what is technical and the check of agent work are one press away, under "More" (web/brand/bar.html)
    bar_all = PAGE[PAGE.index('<header class="bar k-bar"'):PAGE.index("</header>")]
    # "More" holds 7 at most (How we verify and the role pages stay at their own addresses, #verify and the rest)
    assert 'id="go-check">Paid on proof</a>' in bar_all and 'how-we-test.html">How we test</a>' in bar_all
    assert len(re.findall(r"<a", bar_all[bar_all.index('id="more-list"'):])) <= 7 + 1          # the 7 and the Sign in link after them


def test_the_page_decides_its_first_view_before_the_first_paint_and_the_router_knows_it():
    head = PAGE[:PAGE.index("</head>")]
    assert 'document.documentElement.dataset.door = /^#?(home)?$/.test(location.hash) ? "home" : "page";' in head
    assert 'html[data-door="home"]:not(.js) #view-check { display: none; }' in head
    assert PAGE.index('<section id="view-check"') < PAGE.index('<section id="view-home"')    # the first h1 stays the check's
    views = (ROOT / "web" / "views.js").read_text(encoding="utf-8")
    assert re.search(r'export const VIEWS = \[[^\]]*"home", "verify"\]', views)
    front = (ROOT / "web" / "front.js").read_text(encoding="utf-8")
    assert 'name === "" ? "home"' in front and 'import("./home.js").then((m) => m.initHome())' in front
    js = (ROOT / "web" / "home.js").read_text(encoding="utf-8")
    assert 'export const APP = "https://knos.onrender.com";' in js and "/api/front" in js and '"pointermove", "pointerdown", "touchstart"' in js
    assert "if (!rows.length) return false;" in js                                     # an empty answer keeps the snapshot
    # the app's list answers this site across origins
    srv = (ROOT / "apps" / "wanted" / "knos_wanted" / "front.py").read_text(encoding="utf-8")
    assert '"Access-Control-Allow-Origin": "*"' in srv


def test_how_we_verify_is_one_page_of_short_plain_lines():
    v = _section("view-verify")
    assert '<h2 id="verify-h">How we verify</h2>' in v
    items = re.findall(r"<li><h2>(.*?)</h2><p>(.*?)</p></li>", v, re.S)
    assert len(items) >= 5
    for head, body in items:
        for s in re.split(r"(?<=[.?!:])\s+", re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", body)).strip()):
            assert len(_words(s)) <= 12, s
        assert len(_words(head)) <= 6
    assert not re.search(r"\b(wallets?|hash(es)?|pins?|token accounts?)\b", re.sub(r"<[^>]+>", " ", v), re.I)
