"""Knos's one design system, written onto every public page: the front door's (web/) and the app's
(apps/wanted/knos_wanted/static/).

    python scripts/sync_brand.py            write
    python scripts/sync_brand.py --check    exit 1 if a page or a copy differs from what this writes

The token file (web/brand/tokens.css), the wordmark, the mark, the fonts and the bar's script (web/brand/bar.js) are
copied byte for byte to the app's static/brand/ and static/fonts/. The bar (web/brand/bar.html) is written between
`<!-- k-bar -->` and `<!-- /k-bar -->` on each page with the same words, links and order everywhere; only the start of
each address changes, so that a link to the page's own site stays on it ({H} its home, {S} the front door, {A} the
app). Each page loads the token file before its own stylesheet.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB, STATIC = ROOT / "web", ROOT / "apps" / "wanted" / "knos_wanted" / "static"
SITE = "https://drexthealpha.github.io/Knos/"
# the front door names no other host in its pages (tests/test_settle_fixtures.py): its links to the app go through its own
# wake page, which wakes the free server and forwards (web/wanted.html: the hash, and ?to= one of the app's pages)
WAKE = "wanted.html"
COPIES = {WEB / "brand" / n: STATIC / "brand" / n for n in ("tokens.css", "card.css", "wordmark.svg", "mark.svg", "bar.js", "hero.js", "vectors.js", "shape.js")}
COPIES |= {f: STATIC / "fonts" / f.name for f in sorted((WEB / "fonts").iterdir()) if f.suffix in (".woff2", ".txt")}
# the crow icon set (scripts/make_icons.py) on every Knos page, the app's included
COPIES |= {WEB / "icon.svg": STATIC / "icon.svg", WEB / "favicon.ico": STATIC / "favicon.ico",
           **{WEB / "brand" / n: STATIC / "brand" / n for n in ("apple-touch-icon.png", "icon-192.png", "icon-512.png")}}
ICON_LINK = re.compile(r'[ \t]*<link rel="(?:icon|shortcut icon|apple-touch-icon|preconnect)"[^>]*>\n?')
# pages outside PAGES that still carry the icons: (page, the path from it to the site's root)
ICON_ONLY = {WEB / "check" / "index.html": "../", WEB / "proof" / "index.html": "../"}
# the proof page carries How we test Knos's results board as it is, between these marks
BOARD_PAGE, BOARD_FROM = WEB / "proof" / "index.html", WEB / "how-we-test.html"
BOARD = re.compile(r"<!-- k-board -->.*?<!-- /k-board -->", re.S)
BOARD_SECTION = re.compile(r'<section class="t" id="board">.*?</section>', re.S)
# the front door's fonts are asked for in CORS mode (crossorigin), so they cannot reuse the page's own connection: this
# opens that second connection while the page parses. Nothing is downloaded by it, so it does not compete with the
# first paint the way preloading the fonts did (page() below).
PRECONNECT = '<link rel="preconnect" href="https://drexthealpha.github.io" crossorigin>\n'


def icons(s: str, root: str, preconnect: bool = False) -> str:
    """The page's icon links, replaced by the one set: the crow as SVG, favicon.ico for older browsers, a home-screen PNG;
    on a front door page, the fonts' connection opened first."""
    block = ((PRECONNECT if preconnect else "") +
             f'<link rel="icon" href="{root}icon.svg" type="image/svg+xml">\n<link rel="icon" href="{root}favicon.ico" sizes="16x16 32x32 48x48">\n'
             f'<link rel="apple-touch-icon" href="{root}brand/apple-touch-icon.png">\n')
    s = ICON_LINK.sub("", s)
    return s.replace("</head>", block + "</head>", 1)
# page: (its home, the front door, the app, its tokens link, loads web/brand/bar.js)
PAGES = {
    WEB / "index.html": ("", "", WAKE, "brand/tokens.css", False),        # web/front.js runs this bar (the build's app.html)
    WEB / "home.html": ("./", "./", WAKE, "brand/tokens.css", True),      # the front door: the build's index.html
    WEB / "faq.html": ("./", "./", WAKE, "brand/tokens.css", True),
    WEB / "how-we-test.html": ("./", "./", WAKE, "brand/tokens.css", True),
    WEB / "pricing.html": ("./", "./", WAKE, "brand/tokens.css", True),
    WEB / "privacy.html": ("./", "./", WAKE, "brand/tokens.css", True),
    WEB / "404.html": (SITE, SITE, SITE + WAKE, "brand/tokens.css", True),        # its <base href="/Knos/"> holds at any depth
    WEB / "wanted.html": ("./", "./", WAKE, "brand/tokens.css", True),
    WEB / "start" / "index.html": ("../", "../", "../" + WAKE, "../brand/tokens.css", True),
    STATIC / "index.html": ("", SITE, "", "/static/brand/tokens.css", True),
    **{STATIC / n: ("/app/", SITE, "/app/", "/static/brand/tokens.css", True)
       for n in ("trace.html", "with_without.html", "qloo_safe_use.html", "invite.html", "verify.html", "ready.html",
                 "fields.html", "money.html", "companies.html")},
}
MARK = re.compile(r"<!-- k-bar -->.*?<!-- /k-bar -->", re.S)
PROOF_SLOT = '<div id="k-card" class="k-slot" aria-live="polite"></div>'   # hero.js runs right after the card slot
HERO = re.compile(r"<!-- k-hero -->.*?<!-- /k-hero -->", re.S)
VECTORS = re.compile(r"<!-- k-vectors -->.*?<!-- /k-vectors -->", re.S)
STEPS = re.compile(r"<!-- k-steps -->.*?<!-- /k-steps -->", re.S)
CAPS = re.compile(r"<!-- k-caps -->.*?<!-- /k-caps -->", re.S)
# the two front doors' first screens: (the app's address for the API, the app's address for its pages, hero.js)
HEROES = {WEB / "index.html": ("@app", WAKE, "brand/hero.js"), WEB / "home.html": ("@app", WAKE, "brand/hero.js"), STATIC / "index.html": ("", "/app/", "/static/brand/hero.js")}


def bar(home: str, site: str, app: str) -> str:
    t = (WEB / "brand" / "bar.html").read_text(encoding="utf-8").strip()
    # the app's other pages are at the app's root (its home at /app/), a page of the site at the site's: {AP}/{SP} start a page's address
    pages = app + "?to=/" if app.endswith(WAKE) else "/"
    return t.replace("{H}", home).replace("{SP}", site or "./").replace("{S}", site).replace("{AP}", pages).replace("{A}", app)


def vectors(api: str, js: str) -> str:
    return (WEB / "brand" / "vectors.html").read_text(encoding="utf-8").strip().replace("{API}", api).replace("{JS}", js)


def page(path: Path, home: str, site: str, app: str, tokens: str, script: bool) -> str:
    s = path.read_text(encoding="utf-8")
    src = "/static/brand/bar.js" if tokens.startswith("/static/") else tokens.replace("tokens.css", "bar.js")
    # the bar's script is asked for after the page has loaded: nothing of it is needed for the first paint
    late = ('<script>addEventListener("load", () => { const s = document.createElement("script"); '
            f's.src = "{src}"; document.head.append(s); }}, {{ once: true }});</script>\n')
    b = bar(home, site, app)
    if path.is_relative_to(WEB):              # the front door's pages sign nobody in: sign-in stays inside the app (/app/)
        b = re.sub(r'\n\s*<a id="whoBtn"[^\n]*</a>', "", b)
    block = f"<!-- k-bar -->\n{b}\n" + (late if script else "") + "<!-- /k-bar -->"
    if MARK.search(s):
        s = MARK.sub(lambda _: block, s, count=1)
    else:
        # the page's own header gives way to the bar; a page with none gets it first in the body
        s, n = re.subn(r"<header\b.*?</header>", lambda _: block, s, count=1, flags=re.S)
        if not n:
            s = re.sub(r"<body([^>]*)>", lambda m: f"<body{m.group(1)}>\n{block}", s, count=1)
    if path in HEROES:
        api, app_pages, js = HEROES[path]
        t = (WEB / "brand" / "hero.html").read_text(encoding="utf-8").strip().replace("{API}", api).replace("{APP}", app_pages).replace("{SP}", site or "./")
        t = t.replace("<!-- k-vectors -->", vectors(api, js.replace("hero.js", "vectors.js")))
        t = t.replace("{SHAPE}", js.replace("hero.js", "shape.js"))
        # hero.js runs in place, right after the proof slot: the past result is drawn before anything below it is laid
        # out (run deferred, the card arrived after the first paint and moved the page under the reader: CLS)
        code = lean((WEB / "brand" / "hero.js").read_text(encoding="utf-8").strip())   # inlined without its comments and indentation
        t = t.replace(PROOF_SLOT, f'{PROOF_SLOT}\n<script data-src="{js}">\n{code}\n</script>', 1)
        s = HERO.sub(lambda _: f'<!-- k-hero -->\n{t}\n<!-- /k-hero -->', s, count=1)
        # the four steps under the first screen (web/brand/steps.html): check demand, Ready brief, money held, paid on proof
        steps = (WEB / "brand" / "steps.html").read_text(encoding="utf-8").strip().replace("{SP}", site)
        s = STEPS.sub(lambda _: f"<!-- k-steps -->\n{steps}\n<!-- /k-steps -->", s, count=1)
        # under the first screen: one line per built capability, each with its link (web/brand/caps.html)
        caps = (WEB / "brand" / "caps.html").read_text(encoding="utf-8").strip().replace("{SP}", site)
        s = CAPS.sub(lambda _: f"<!-- k-caps -->\n{caps}\n<!-- /k-caps -->", s, count=1)
    # a page that runs web/brand/bar.js lays the bar out for scripts (and in the reader's theme) before its first paint:
    # set after it, the bar moves under the reader (a layout shift Lighthouse counts)
    EARLY = ('<script>document.documentElement.classList.add("js");'
             'try { const t = localStorage.getItem("knos-theme"); if (t) document.documentElement.dataset.theme = t; } catch (e) {}</script>')
    if script and EARLY not in s:
        s = s.replace("</head>", f"{EARLY}\n</head>", 1)
    # the fonts are not asked for with the page: they are display: optional (no swap after the first paint), and asked
    # for at once they took the first paint's bandwidth on a slow phone (a later largest paint)
    s = re.sub(r'<link rel="preload" href="[^"]*fonts/[a-z-]+\.woff2" as="font" type="font/woff2" crossorigin>\n', "", s)
    # a main screen's measured numbers (web/brand/vectors.html), between the k-vectors marks
    if VECTORS.search(s) and path not in HEROES:
        api = "" if tokens.startswith("/static/") else "@app"
        js = "/static/brand/vectors.js" if tokens.startswith("/static/") else tokens.replace("tokens.css", "vectors.js")
        s = VECTORS.sub(lambda _: f"<!-- k-vectors -->\n{vectors(api, js)}\n<!-- /k-vectors -->", s, count=1)
    s = icons(s, "/static/" if tokens.startswith("/static/") else tokens.split("brand/tokens.css")[0], preconnect=path.is_relative_to(WEB))
    link = f'<link rel="stylesheet" href="{tokens}">'
    if link not in s:
        s = re.sub(r'(<link rel="stylesheet")', lambda m: f"{link}\n{m.group(1)}", s, count=1) if "<link rel=\"stylesheet\"" in s \
            else s.replace("</head>", f"{link}\n</head>", 1)
    return s


def board() -> str:
    """The proof page with How we test Knos's results board copied in, unchanged."""
    s = BOARD_PAGE.read_text(encoding="utf-8")
    sec = BOARD_SECTION.search(BOARD_FROM.read_text(encoding="utf-8"))
    assert sec, "how-we-test.html has no results board"
    return BOARD.sub(lambda _: f"<!-- k-board -->\n    {sec.group(0)}\n<!-- /k-board -->", s, count=1)


def lean(code: str) -> str:
    """hero.js as the pages inline it: whole-line comments, blank lines and each line's leading indentation dropped (the
    first load stays under its 200 KB budget, apps/wanted/tests/test_round9.py); hero.js itself keeps them."""
    return "\n".join(line.lstrip() for line in code.splitlines() if line.strip() and not line.lstrip().startswith("//"))


def main(argv: list[str]) -> int:
    check, off = "--check" in argv, []
    for a, b in COPIES.items():
        if not b.exists() or b.read_bytes() != a.read_bytes():
            off.append(str(b.relative_to(ROOT)))
            if not check:
                b.parent.mkdir(parents=True, exist_ok=True)
                b.write_bytes(a.read_bytes())
    todo = [(p, lambda p=p, a=a: page(p, *a)) for p, a in PAGES.items()] + \
        [(p, lambda p=p, r=r: icons(p.read_text(encoding="utf-8"), r, preconnect=True)) for p, r in ICON_ONLY.items()] + \
        [(BOARD_PAGE, board)]
    for path, make in todo:
        new = make()
        if new != path.read_text(encoding="utf-8"):
            off.append(str(path.relative_to(ROOT)))
            if not check:
                path.write_text(new, encoding="utf-8", newline="\n")
    print(("differs: " if check else "wrote: ") + (", ".join(off) or "nothing"))
    return 1 if check and off else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
