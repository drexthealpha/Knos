"""docs/README.md is the map of the documents: every file in docs/*.md is on it once, under one of six questions, and
every link on it leads to a file. docs/STORY.md and web/story.js tell one story in eight steps, each with evidence
that exists in the repository; the last step is an invitation and claims nobody.

Everything here reads files; the one subprocess is node on tests/web/story.mjs, and it opens no network.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
QUESTIONS = ["Does it work?", "Why does it matter?", "What is new?", "How do I use it?", "How do I build on it?", "How is it run and paid for?"]
STEPS = 8
WORDS = re.compile(r"[A-Za-z0-9][\w'%.,/-]*")


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def links(text: str) -> list[str]:
    return re.findall(r"\]\(([^)#\s]+)(?:#[^)]*)?\)", text)


def test_every_document_is_on_the_map_once_under_one_of_six_questions():
    page = read("docs/README.md")
    heads = re.findall(r"(?m)^## (\d)\. (.+)$", page)
    assert [h[1] for h in heads] == QUESTIONS and [int(h[0]) for h in heads] == list(range(1, 7))
    mapped = page.split("\n## What is in this repository")[0]
    rows = re.findall(r"(?m)^\| \[([^\]]+)\]\(([^)]+)\) \| (.+) \|$", mapped)
    listed = [target for _name, target, _what in rows]
    here = sorted(p.name for p in DOCS.glob("*.md") if p.name != "README.md")
    assert sorted(set(here) - set(listed)) == [], "a document in docs/ is missing from docs/README.md: add one row for it"
    assert sorted(t for t in listed if listed.count(t) > 1 and t != "STORY.md") == []      # STORY.md is also the first row
    assert all(len(WORDS.findall(what)) <= 22 for _n, _t, what in rows), [w for _n, _t, w in rows if len(WORDS.findall(w)) > 22]
    for target in links(page):                                                              # every link leads somewhere
        assert target.startswith("https://") or (DOCS / target).exists(), target


def test_the_front_page_has_five_parts_above_the_line_and_one_link_onward():
    readme = read("README.md")
    above, below = readme.split("\n---\n", 1)
    assert re.findall(r"(?m)^## (.+)$", above) == ["The number", "One comment", "Two ledgers", "What is real today", "Read more"]
    more = above.split("## Read more")[1]
    assert links(more) == ["docs/README.md"]
    table = above[above.index("<!-- bench:today -->"):above.index("<!-- /bench:today -->")]
    numbers = read("docs/submission/NUMBERS.md")
    printed = re.findall(r"(?m)^\| \d \| ([^:|]+)[^|]*\| (\d+) \|", numbers)
    assert len(printed) == 9
    for what, value in printed:                                                             # every number that page prints, zeros included
        assert re.search(rf"(?m)^\| {re.escape(what.strip())} \| {value}\b", table), what
    assert "<!-- programs:start -->" in below and "<!-- capabilities:start -->" in below and "## " not in below
    for rel in links(readme):
        assert rel.startswith("https://") or (ROOT / rel).exists(), rel


def test_the_story_is_eight_steps_each_with_evidence_that_exists_and_asks_for_three_things():
    story = read("docs/STORY.md")
    lines = [line for line in story.splitlines() if line.strip()]
    assert lines[1] == "**The neutral meter for AI agent work: neither side keeps the count.**"
    assert lines[2] == "Of 241 merged agent pull requests that claimed passing tests, 30 had a failed check."
    steps = re.findall(r"(?m)^(\d)\. \*\*(.+?)\*\* (.+)\n   Evidence: \[([^\]]+)\]\(([^)]+)\)", story)
    assert [int(s[0]) for s in steps] == list(range(1, STEPS + 1))
    for _n, title, said, _name, target in steps:
        assert len(WORDS.findall(f"{title} {said}")) <= 12, (title, said)
        assert target.startswith("https://") or (DOCS / target.split("#")[0]).exists(), target
    assert steps[-1][1] == "Your invoice next." and steps[-1][4] == "https://drexthealpha.github.io/Knos/"
    for word in ("customer", "paid us", "pilot"):                                           # the last step claims nobody
        assert word not in f"{steps[-1][1]} {steps[-1][2]}".lower()
    ask = story.split("## The ask")[1].split("\n## ")[0]
    needs = re.findall(r"(?m)^\d\. (.+)$", ask)
    assert len(needs) == 3 and all(n.startswith("Needed: ") for n in needs)
    assert "outside key holder" in needs[0] and "shadow count" in needs[1] and "outside review" in needs[2]


def test_the_page_tells_the_same_eight_steps_and_stands_still_under_reduced_motion():
    source = read("web/story.js")
    assert "export function renderStory(el, ctx" in source and "prefersReduced" in source
    assert not re.search(r"https?://(?!drexthealpha\.github\.io|github\.com/drexthealpha|explorer\.solana\.com)", source)
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    r = subprocess.run([node, str(ROOT / "tests" / "web" / "story.mjs")], capture_output=True, text=True, encoding="utf-8", timeout=120, check=False)
    assert r.returncode == 0, r.stdout + r.stderr
