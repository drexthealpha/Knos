"""The first screen and the story (web/index.html, docs/STORY.md): the outcome comes first, and the story's seven beats
name the same public round as the site. Everything here reads files.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTCOME = "Pay AI agents only when your checks pass."
STEPS = ["one", "two", "three", "four", "five", "six", "seven"]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_the_first_screen_and_the_story_say_the_same_things():
    page = read("web/index.html")
    hero = page.split('<div class="hero-words">')[1].split("</form>")[0]
    assert hero.index("<h1") < hero.index(OUTCOME) < hero.index('id="hero-fact"') < hero.index('id="front-door"')
    story = read("docs/STORY.md")
    titles = re.findall(r"(?m)^\d\. \*\*(.+?)\*\*", story.split("## The ask")[0])
    assert titles == ["Buyer and supplier agree one task.", "A claimed success fails the condition.", "Valid work passes.",
                      "Both sides make the same statement.", "A replay pays nothing.", "The payment executes.", "A verifier checks it offline."]
    assert len(titles) == len(STEPS)                                        # seven beats
    round_ = json.loads(read("web/demo_data.json"))
    for tx in (round_["fund"]["tx"], round_["paid"]["tx"], round_["replay"]["tx"]):
        assert tx in story and tx in read("web/story.js")
