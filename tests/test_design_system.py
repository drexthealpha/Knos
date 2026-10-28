"""One design system (web/brand/tokens.css): the front door and the app load the same token file, show the same bar and
logo, and define no colour, typeface or bar of their own. The live comparison is scripts/test_ui_sota.mjs design."""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB, STATIC = ROOT / "web", ROOT / "apps" / "wanted" / "knos_wanted" / "static"
sys.path.insert(0, str(ROOT / "scripts"))
import sync_brand  # noqa: E402


def test_every_page_and_copy_is_what_sync_brand_writes():
    run = subprocess.run([sys.executable, str(ROOT / "scripts" / "sync_brand.py"), "--check"], capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stdout + run.stderr
    for a, b in sync_brand.COPIES.items():
        assert a.read_bytes() == b.read_bytes(), b


def test_each_page_loads_the_tokens_first_and_carries_the_one_bar():
    bar = re.sub(r'href="[^"]*"', 'href=""', (WEB / "brand" / "bar.html").read_text(encoding="utf-8").strip())
    no_sign_in = re.sub(r'\n\s*<a id="whoBtn"[^\n]*</a>', "", bar)       # the front door's pages: sign-in stays inside the app
    for page in sync_brand.PAGES:
        s = page.read_text(encoding="utf-8")
        want = no_sign_in if page.is_relative_to(sync_brand.WEB) else bar
        sheets = re.findall(r'<link rel="stylesheet" href="([^"]+)"', s)
        assert sheets and sheets[0].endswith("brand/tokens.css"), (page.name, sheets)
        shown = re.search(r"<!-- k-bar -->\n(.*?)\n(?:<script|<!-- /k-bar -->)", s, re.S)[1]
        assert re.sub(r'href="[^"]*"', 'href=""', shown) == want, page.name                  # the same words and order
        assert s.count('id="k-bar"') == 1 and 'class="mark"' not in s, page.name


def test_no_page_stylesheet_defines_a_palette_or_a_typeface():
    for css in (WEB / "app.css", STATIC / "style.css"):
        s = css.read_text(encoding="utf-8")
        assert "@font-face" not in s, css.name
        for block in re.findall(r":root[^{]*\{([^}]*)\}", s):
            assert not re.search(r"--(paper|ink|accent|bg|surface|muted)\s*:\s*#", block), (css.name, block[:80])
        assert not re.search(r"font(-family)?\s*:[^;]*(-apple-system|Segoe UI|Helvetica)", s.replace("var(--text)", "")), css.name
        assert ".mark {" not in s and "nav.roles" not in s and ".ux-fab {" not in s, css.name


def test_the_hero_is_one_box_on_both_front_doors():
    for page in sync_brand.HEROES:
        s = page.read_text(encoding="utf-8")
        hero = s[s.index("<!-- k-hero -->"):s.index("<!-- /k-hero -->")]
        hero = re.sub(r"(<script\b[^>]*>).*?(</script>)", r"\1\2", hero, flags=re.S)   # an inline script's text is not markup
        # one box, with the reader's optional guess of a launch city above it
        assert hero.count("<form") == 1 and hero.count("<input") == 3 and 'id="k-who"' in hero and 'id="k-guess"' in hero and 'id="k-mission"' in hero, page.name
        assert "see who wants your product, and where, before you build it" in hero.lower() and "valley" not in hero.lower(), page.name   # the mission sits below
