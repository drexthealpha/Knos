"""The first screen and the story (web/index.html, docs/STORY.md): the outcome comes first, and the story's seven beats
name the same public round as the site. Everything here reads files.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTCOME = "Check an AI agent's pull request before it is paid."
STEPS = ["one", "two", "three", "four", "five", "six", "seven"]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_the_first_screen_and_the_story_say_the_same_things():
    page = read("web/index.html")
    hero = page.split('<div class="hero-words">')[1].split("</form>")[0]
    assert page.count("<h1") == 1 and '<h1 id="k-mission"' in page        # one h1: the demand check's mission (d6b6360)
    assert hero.index('<h2 id="check"') < hero.index(OUTCOME) < hero.index('id="hero-fact"') < hero.index('id="front-door"')
    round_ = json.loads(read("web/demo_data.json"))
    for tx in (round_["fund"]["tx"], round_["paid"]["tx"], round_["replay"]["tx"]):
        assert tx in read("web/story.js")
