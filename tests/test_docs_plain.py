"""The documents a newcomer opens first start in plain words.

Each opens with the mark, then its title, then an "In plain words" summary of three sentences that a reader of about
twelve can follow: a Flesch-Kincaid grade of 8 at most. Where a document has a diagram, it is a ```mermaid block
(GitHub draws it, in light and dark, so no colours or themes are set) with a one-line caption in italics under it.

The Flesch-Kincaid grade is 0.39 * (words / sentences) + 11.8 * (syllables / words) - 15.59 (Kincaid, Fishburne,
Rogers and Chissom, 1975). Syllables are counted by a fixed rule, with no dictionary: groups of vowels, less a silent
final "e" and a silent "-ed"; a number counts as two; a word in capitals (USDC) is read letter by letter.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PLAIN = "**In plain words.**"
# each document, and the kind of diagram it holds (None: none)
DOCS = {"docs/README.md": "flowchart", "docs/STORY.md": "flowchart", "docs/JUDGES.md": "flowchart",
        "docs/GOVERNANCE.md": "flowchart", "docs/METER.md": "flowchart", "docs/FINANCE.md": None,
        "docs/submission/TRANSACTION.md": "stateDiagram-v2", "docs/submission/MARKET_SIZE.md": "flowchart",
        "docs/submission/FLOWS.md": "flowchart"}
MERMAID = re.compile(r"(?ms)^```mermaid\n(.*?)^```[ \t]*\n(.*?)$")
WORD = re.compile(r"[A-Za-z]+(?:['’][A-Za-z]+)*|\d[\d,.]*\d|\d")
END = re.compile(r"[.!?](?=\s|$)")


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def syllables(word: str) -> int:
    if word[0].isdigit():
        return 2
    if len(word) > 1 and word.isupper():
        return len(word)
    w = re.sub(r"['’]s$", "", word.lower())
    n = len(re.findall(r"[aeiouy]+", w))
    if w.endswith("e") and not w.endswith(("le", "ee")) and n > 1:
        n -= 1
    if w.endswith("ed") and not w.endswith(("ted", "ded")) and n > 1:
        n -= 1
    return max(1, n)


def grade(text: str) -> float:
    words = WORD.findall(text)
    sentences = max(1, len(END.findall(text)))
    return 0.39 * len(words) / sentences + 11.8 * sum(syllables(w) for w in words) / len(words) - 15.59


def summary(page: str) -> str:
    """The "In plain words" paragraph as a reader reads it: no label, no link targets, no marks."""
    para = next(p for p in page.split("\n\n") if p.startswith(PLAIN))
    text = re.sub(r"\]\([^)]*\)", "]", para[len(PLAIN):])
    return " ".join(re.sub(r"[*`\[\]]", "", text).split())


def test_the_formula_and_the_syllable_rule_give_known_values():
    assert [syllables(w) for w in ("seller's", "passed", "funded", "make", "table", "money", "USDC", "5.00", "a")] == [2, 1, 2, 1, 2, 2, 4, 2, 1]
    assert grade("The cat sat on the mat.") < 0 < grade("Reconciliation of independently maintained ledgers necessitates cryptographic attestation.")


@pytest.mark.parametrize("rel", sorted(DOCS))
def test_each_document_opens_with_the_mark_its_title_and_three_plain_sentences(rel):
    page = read(rel)
    lines = [line for line in page.splitlines() if line.strip()]
    up = "../" * rel.count("/")
    assert lines[0] == f'<img src="{up}web/brand/mark.svg" height="40" alt="Knos">', rel
    assert ((ROOT / rel).parent / f"{up}web/brand/mark.svg").resolve() == (ROOT / "web" / "brand" / "mark.svg").resolve()
    assert (ROOT / "web" / "brand" / "mark.svg").is_file()
    assert lines[1].startswith("# ") and lines[2].startswith(PLAIN), rel          # the summary comes straight after the title
    said = summary(page)
    assert len(END.findall(said)) == 3 and said.endswith("."), (rel, said)
    assert grade(said) <= 8, (rel, round(grade(said), 1), said)
    assert len(WORD.findall(said)) / 3 <= 20, rel                                    # short sentences


@pytest.mark.parametrize("rel", sorted(DOCS))
def test_each_diagram_is_mermaid_with_no_colours_and_an_italic_caption(rel):
    page = read(rel)
    blocks = MERMAID.findall(page)
    kind = DOCS[rel]
    assert len(blocks) == (0 if kind is None else 1), rel
    for body, caption in blocks:
        assert body.splitlines()[0].strip().startswith(kind), rel
        for styled in ("style ", "classDef", "class ", "linkStyle", "%%{", "theme", "fill:", "color:"):
            assert styled not in body, (rel, styled)
        assert re.fullmatch(r"\*[^*]+\*", caption.strip()), (rel, caption)          # one line, in italics, right under it
        assert len(WORD.findall(caption)) <= 15, (rel, caption)


def test_the_map_lists_the_new_documents_and_draws_the_six_questions():
    page = read("docs/README.md")
    for name in ("WORDS.md", "PILOT.md", "PROPOSAL-2.3.md", "KEYS.md"):
        assert f"| [{name}]({name}) |" in page, name
    body = MERMAID.findall(page)[0][0]
    for n, question in enumerate(("Does it work?", "Why does it matter?", "What is new?", "How do I use it?",
                                  "How do I build on it?", "How is it run and paid for?"), 1):
        assert f"{n}. {question}" in body and f"\n## {n}. {question}\n" in page, question
    assert "](WORDS.md)" in next(p for p in page.split("\n\n") if p.startswith(PLAIN))


def test_the_judges_page_counts_what_a_reader_reads(tmp_path):
    spec = importlib.util.spec_from_file_location("judges_script", ROOT / "scripts" / "judges.py")
    j = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(j)
    page = ('<img src="../web/brand/mark.svg" height="40" alt="Knos">\n\n# Title\n\n**In plain words.** One. Two. Three.\n\n'
            "```mermaid\nflowchart TB\n    a[\"many words that a diagram draws\"] --> b\n```\n*A caption.*\n")
    counted = j.WORD.findall(j.prose(page))
    assert counted == ["Title", "In", "plain", "words.", "One.", "Two.", "Three.", "A", "caption."]
    assert j.head(page)[0] == "# Title"                                              # the mark and the summary are not the title


def test_the_release_entry_counts_the_words_that_docs_words_explains():
    # one word a "### " heading: the CHANGELOG's line on docs/WORDS.md gives that number, not an older draft's
    explained = len(re.findall(r"(?m)^### ", read("docs/WORDS.md")))
    said = re.findall(r"\(docs/WORDS\.md\)\*\* explains (\d+) words", read("CHANGELOG.md"))
    assert said and all(int(k) == explained for k in said), (said, explained)
