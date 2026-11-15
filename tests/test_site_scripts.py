"""The old first screen and the story (web/index.html, docs/STORY.md): the outcome comes first, and every devnet
transaction docs/STORY.md cites is on the story page (web/story.js). web/index.html is no longer served by Pages (the
front door is web/door.html); the app's build (KNOS_SPA_AT_ROOT=1) still opens it. Everything here reads files.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTCOME = "Check an AI agent's pull request before it is paid."


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_the_first_screen_and_the_story_say_the_same_things():
    page = read("web/index.html")
    hero = page.split('<div class="hero-words">')[1].split("</form>")[0]
    assert page.count("<h1") == 1 and '<h1 class="k-first" id="k-first"' in page   # one h1: every face's first line (web/brand/first.html)
    assert hero.index('<h2 id="check"') < hero.index(OUTCOME) < hero.index('id="hero-fact"') < hero.index('id="front-door"')
    # the story page tells docs/STORY.md's steps: every devnet transaction the document cites is the page's
    txs = re.findall(r"explorer\.solana\.com/tx/([1-9A-HJ-NP-Za-km-z]{60,90})", read("docs/STORY.md"))
    assert txs and all(tx in read("web/story.js") for tx in txs)
