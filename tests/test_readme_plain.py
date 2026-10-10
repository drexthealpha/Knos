"""README.md is written for a reader who has never heard of GitHub Actions, Solana, escrow or a hash.

Its prose from the first heading through "Is it real?" is measured with the Flesch-Kincaid grade level:

    grade = 0.39 * (words / sentences) + 11.8 * (syllables / words) - 15.59

(Kincaid, Fishburne, Rogers and Chissom, 1975, https://apps.dtic.mil/sti/pdfs/ADA006655.pdf), computed here with no
dependency. Code, tables, HTML, Mermaid blocks, headings and link targets are taken out first; a link keeps its words.
Syllables are counted by vowel groups, less a silent final "e"; a word in capitals (AI, USDC) is read letter by letter;
a number counts one. The page must read at grade 8 or lower, with 16 words a sentence or fewer on average.

Also held: the logo comes first, at least two Mermaid diagrams each with an italic caption under it and no colour or
theme set, docs/WORDS.md linked, and docs/WORDS.md itself (alphabetical, each meaning under 20 words).
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORD = re.compile(r"[A-Za-z0-9][\w'%.,-]*")
MERMAID = re.compile(r"(?ms)^```mermaid\n(.*?)^```\n")
TERMS = ["AI agent", "Pull request", "Merge", "Checks (CI)", "GitHub Actions", "Signed", "Token (OIDC)", "Solana", "Devnet", "USDC",
         "Test USDC", "Escrow", "Wallet", "Passkey", "Hash", "Invoice", "Ledger", "Reconcile", "Statement", "Holdback", "Warranty",
         "Refund", "Program", "Program id", "Upgrade", "Multisig", "Time lock", "Relay", "Meter", "Evaluation", "Assurance level"]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def prose(markdown: str) -> str:
    """The words a reader reads: no code, Mermaid, table, HTML, heading, emphasis marks or link targets."""
    text = re.sub(r"(?ms)^```.*?^```\n?", "\n", markdown)
    text = re.sub(r"(?s)<!--.*?-->", " ", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"`[^`\n]*`", " ", text)
    text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", text)
    lines = [line for line in text.splitlines() if not line.lstrip().startswith(("|", "#"))]
    text = re.sub(r"(?m)^\s*\d+\.\s+", "", "\n".join(lines))
    return text.replace("**", "").replace("*", "")


def sentences(text: str) -> list[str]:
    """A sentence ends at . ! or ? before a space, or where a paragraph or a list item ends."""
    out = []
    for block in re.split(r"\n\s*\n", text):
        for line in block.splitlines():
            for part in re.split(r"(?<=[.!?])\s+", line.strip()):
                if WORD.search(part):
                    out.append(part)
    return out


def syllables(word: str) -> int:
    bare = word.strip("'%.,-")
    if re.fullmatch(r"[A-Z]{2,5}s?", bare):
        return len(bare.rstrip("s"))                     # AI, USDC, OIDC: said letter by letter
    low = re.sub(r"[^a-z]", "", bare.lower())
    if not low:
        return 1                                         # a number
    n = len(re.findall(r"[aeiouy]+", low))
    if low.endswith("e") and not low.endswith(("le", "ee", "ye")) and n > 1:
        n -= 1
    return max(n, 1)


def grade(text: str) -> tuple[float, float]:
    """(Flesch-Kincaid grade, average words a sentence)."""
    said = sentences(text)
    words = [w for s in said for w in WORD.findall(s)]
    per = len(words) / len(said)
    return 0.39 * per + 11.8 * sum(map(syllables, words)) / len(words) - 15.59, per


def window(readme: str) -> str:
    """From the first heading to the end of the section "Is it real?" (its generated table is not prose)."""
    start = readme.index("\n## ")
    real = readme.index("\n## Is it real?\n")
    end = readme.find("\n## ", real + 1)
    return readme[start:end]


def test_the_formula_matches_known_counts():
    assert [syllables(w) for w in ("cat", "money", "release", "table", "computer", "USDC", "AI", "241")] == [1, 2, 2, 2, 3, 4, 2, 1]
    assert sentences("One two. Three four!\nFive six\n\nSeven? Eight.") == ["One two.", "Three four!", "Five six", "Seven?", "Eight."]
    hard = "Reconciliation of heterogeneous evidentiary attestations necessitates considerable institutional sophistication."
    assert grade(hard)[0] > 12 and grade("The cat sat on the mat. It was fun.")[0] < 2


def test_the_readme_reads_at_grade_eight_with_short_sentences():
    text = prose(window(read("README.md")))
    level, per = grade(text)
    assert len(sentences(text)) >= 20, "the window lost its prose"
    for kept in ("How it works", "Try it in ten seconds", "Why nobody can fudge the count", "Is it real?"):
        assert f"\n## {kept}\n" in window(read("README.md")), kept
    assert level <= 8, f"Flesch-Kincaid grade {level:.1f} (at most 8)"
    assert per <= 16, f"{per:.1f} words a sentence on average (at most 16)"


def test_the_logo_leads_and_every_diagram_has_a_caption_and_no_colour():
    readme = read("README.md")
    lines = [line for line in readme.splitlines() if line.strip()]
    assert lines[0] == "<h1>" and lines[1].strip() == "<picture>" and "wordmark-light.svg" in lines[4] and lines[6] == "</h1>"
    blocks = list(MERMAID.finditer(readme))
    assert len(blocks) >= 2
    for block in blocks:
        body = block.group(1)
        assert re.match(r"(flowchart|graph|sequenceDiagram|stateDiagram-v2)\b", body), body[:40]
        assert not re.search(r"(?m)^\s*(style|classDef|class|linkStyle)\b|%%\{|theme|#[0-9a-fA-F]{3,6}\b|fill:", body), body
        after = [line for line in readme[block.end():].splitlines() if line.strip()][0]
        assert re.fullmatch(r"\*[^*]+\*", after), f"no italic caption under the diagram: {after}"
        assert len(WORD.findall(after)) <= 20, after
    assert "](docs/WORDS.md)" in readme.split("\n---\n", 1)[0]


def test_every_word_is_explained_in_under_twenty_words_in_order_and_every_link_to_one_lands():
    page = read("docs/WORDS.md")
    terms = re.findall(r"(?m)^### (.+)$", page)
    assert terms == sorted(terms, key=str.lower) and len(terms) >= 30
    assert not [t for t in TERMS if t not in terms]
    for term, meaning in re.findall(r"(?m)^### (.+)\n\n(.+)$", page):
        assert len(WORD.findall(meaning)) < 20, term
    assert len(re.findall(r"(?m)^### (.+)\n\n(.+)$", page)) == len(terms)
    anchors = {re.sub(r"[^a-z0-9 -]", "", t.lower()).replace(" ", "-") for t in terms}
    for anchor in re.findall(r"\]\(docs/WORDS\.md#([^)]+)\)", read("README.md")):
        assert anchor in anchors, anchor
    level, _per = grade(prose(page))
    assert level <= 8, f"docs/WORDS.md reads at grade {level:.1f}"
