"""The front of docs/: the few pages a stranger opens first are short and easy on the eye.

Each front page opens with the mark, then its title, then an "In plain words" summary of three sentences with a
Flesch-Kincaid grade of 8 at most (the formula and the syllable rule are tests/test_docs_plain.py's). It has at most
1,200 words of prose (docs/JUDGES.md is written by scripts/judges.py and is excepted), no paragraph longer than four
lines, and at least one ```mermaid block with a one-line caption in italics right under it.

A line is 100 characters of the text a reader sees: link targets, marks and tags are not counted. Each item of a
list is a paragraph of its own. Code, tables, headings and HTML lines are not paragraphs.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FRONT = ["docs/README.md", "docs/STORY.md", "docs/START.md", "docs/PRICING.md", "docs/TRUST.md", "docs/JUDGES.md",
         "docs/NUMBERS.md", "docs/TRANSACTION.md", "docs/WORDS.md"]
GENERATED = {"docs/JUDGES.md"}          # scripts/judges.py writes it; its length is the script's
MARK = '<img src="../web/brand/mark.svg" height="40" alt="Knos">'
PLAIN = "**In plain words.**"
MAX_WORDS, MAX_LINES, LINE = 1_200, 4, 100
FENCE = re.compile(r"(?ms)^```.*?^```[ \t]*$")
MERMAID = re.compile(r"(?ms)^```mermaid\n(.*?)^```[ \t]*\n(.*?)$")
WORD = re.compile(r"[A-Za-z0-9][\w'%.,-]*")
ITEM = re.compile(r"(?m)^(?=\s*(?:[-*] |\d+\. ))")


def _plain_module():
    spec = importlib.util.spec_from_file_location("docs_plain_rules", ROOT / "tests" / "test_docs_plain.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


P = _plain_module()


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def seen(text: str) -> str:
    """Text as a reader sees it: no link targets, no marks, no tags, one space between words."""
    text = re.sub(r"\]\([^)]*\)", "]", text)
    text = re.sub(r"<[^>\n]+>", " ", text)
    return " ".join(re.sub(r"[*`\[\]]", "", text).split())


def paragraphs(page: str) -> list[str]:
    """The prose blocks of a page, each list item apart: what a reader reads as one paragraph."""
    out = []
    for block in re.split(r"\n\s*\n", FENCE.sub("", page)):
        lines = [line for line in block.splitlines() if line.strip()]
        if not lines or lines[0].lstrip().startswith(("#", "|", "<")):
            continue
        out += [item.strip() for item in ITEM.split("\n".join(lines)) if item.strip()]
    return out


def prose_words(page: str) -> int:
    kept = [line for line in FENCE.sub("", page).splitlines() if not line.lstrip().startswith("|")]
    return len(WORD.findall(seen("\n".join(kept))))


def test_the_front_is_exactly_these_pages():
    assert all((ROOT / rel).is_file() for rel in FRONT), [rel for rel in FRONT if not (ROOT / rel).is_file()]


def test_a_line_and_a_paragraph_are_measured_as_a_reader_sees_them():
    page = "# T\n\nOne [link](https://example.com/a/very/long/address) and **bold**.\n\n- a\n- b\n\n| x |\n|---|\n\n```\ncode\n```\n"
    assert paragraphs(page) == ["One [link](https://example.com/a/very/long/address) and **bold**.", "- a", "- b"]
    assert seen(paragraphs(page)[0]) == "One link and bold."
    assert prose_words(page) == 7                                                   # T, One, link, and, bold., a, b


@pytest.mark.parametrize("rel", FRONT)
def test_each_front_page_opens_with_the_mark_its_title_and_three_plain_sentences(rel):
    page = read(rel)
    lines = [line for line in page.splitlines() if line.strip()]
    assert lines[0] == MARK, rel
    assert lines[1].startswith("# ") and lines[2].startswith(PLAIN), rel
    said = P.summary(page)
    assert len(P.END.findall(said)) == 3 and said.endswith("."), (rel, said)
    assert P.grade(said) <= 8, (rel, round(P.grade(said), 1), said)


@pytest.mark.parametrize("rel", [rel for rel in FRONT if rel not in GENERATED])
def test_each_front_page_is_short(rel):
    assert prose_words(read(rel)) <= MAX_WORDS, (rel, prose_words(read(rel)))


@pytest.mark.parametrize("rel", FRONT)
def test_no_paragraph_is_longer_than_four_lines(rel):
    long = [seen(p)[:80] for p in paragraphs(read(rel)) if len(seen(p)) > MAX_LINES * LINE]
    assert long == [], (rel, long)


@pytest.mark.parametrize("rel", FRONT)
def test_each_front_page_has_a_mermaid_diagram_with_an_italic_caption(rel):
    blocks = MERMAID.findall(read(rel))
    assert blocks, rel
    for body, caption in blocks:
        assert body.strip(), rel
        assert re.fullmatch(r"\*[^*]+\*", caption.strip()), (rel, caption)
