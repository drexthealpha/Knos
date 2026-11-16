"""Round 13, F1 and F3: the word "census" is on no public page. No file under web/ and no Markdown file under docs/
holds it.

The word is matched as itself, in lower case. A web address (https://www.census.gov/...) and a link's target or
#fragment are addresses, not words a reader reads, so they are taken out first. The capitalised name of the U.S.
Census Bureau, a data source some reports cite, is a proper name and not this word.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORD = re.compile(r"\bcensus\b")
ADDRESSES = [
    re.compile(r"https?://[^\s\"'<>)\]]+"),                    # a web address
    re.compile(r"""\b(?:href|src|action)\s*=\s*("[^"]*"|'[^']*')"""),  # an HTML link's target
    re.compile(r"\]\([^)]*\)"),                                # a Markdown link's target
]


def _public_files() -> list[Path]:
    web = [p for p in (ROOT / "web").rglob("*") if p.is_file() and "node_modules" not in p.parts]
    docs = [p for p in (ROOT / "docs").rglob("*.md") if p.is_file()]
    return sorted(web + docs)


def _words(text: str) -> str:
    for pattern in ADDRESSES:
        text = pattern.sub(" ", text)
    return text


def test_no_public_page_says_census():
    found = []
    for path in _public_files():
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:          # an image or a font: no words
            continue
        for n, line in enumerate(text.splitlines(), 1):
            if WORD.search(_words(line)):
                found.append(f"{path.relative_to(ROOT).as_posix()}:{n}: {line.strip()[:120]}")
    assert not found, "the word census is on a public page:\n" + "\n".join(found)


def test_the_check_sees_the_word_and_not_an_address():
    assert WORD.search(_words("The 2 Nov 2026 census scored the list."))
    assert not WORD.search(_words("Truth file: https://www2.census.gov/programs-surveys/cbp/data"))
    assert not WORD.search(_words('<a href="../x.md#against-the-census">The report</a>'))
    assert not WORD.search(_words("County Business Patterns from the U.S. Census Bureau"))
