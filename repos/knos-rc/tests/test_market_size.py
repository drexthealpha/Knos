"""The market size page and the three flows for judges (docs/reference/MARKET_SIZE.md, FLOWS.md).

Both open in plain words, as the documents a newcomer opens first do (tests/test_docs_plain.py's rules). The market
size's arithmetic is what its inputs give, every outside figure carries a link, and nothing gives Knos a share. The
third flow prints what the page says it prints.
"""
from __future__ import annotations

import importlib.util
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
PAGES = ("docs/reference/MARKET_SIZE.md", "docs/reference/FLOWS.md")

_spec = importlib.util.spec_from_file_location("docs_plain", ROOT / "tests" / "test_docs_plain.py")
plain = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(plain)


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def money(cell: str) -> float:
    """'1,998 million USD' -> 1998e6; '222,000 USD' -> 222000; '1.5 million USD' -> 1.5e6."""
    m = re.search(r"(\d[\d,]*(?:\.\d+)?)\s*(million)?", cell)
    assert m, cell
    return float(m.group(1).replace(",", "")) * (1e6 if m.group(2) else 1)


def rows(page: str, head: str) -> list[list[str]]:
    """The body rows of the first table whose header row starts with `head`."""
    lines = page.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(head))
    out = []
    for line in lines[start + 2:]:
        if not line.startswith("|"):
            break
        out.append([c.strip() for c in line.strip("|").split("|")])
    return out


@pytest.mark.parametrize("rel", PAGES)
def test_each_page_opens_in_plain_words_with_one_captioned_diagram(rel):
    page = read(rel)
    lines = [line for line in page.splitlines() if line.strip()]
    assert lines[0] == '<img src="../../web/brand/mark.svg" height="40" alt="Knos">'
    assert lines[1].startswith("# ") and lines[2].startswith(plain.PLAIN)
    said = plain.summary(page)
    assert len(plain.END.findall(said)) == 3 and plain.grade(said) <= 8, (rel, round(plain.grade(said), 1))
    blocks = plain.MERMAID.findall(page)
    assert len(blocks) == 1 and blocks[0][0].startswith("flowchart"), rel
    for styled in ("style ", "classDef", "linkStyle", "%%{", "fill:", "color:"):
        assert styled not in blocks[0][0], (rel, styled)
    assert re.fullmatch(r"\*[^*]+\*", blocks[0][1].strip()) and len(plain.WORD.findall(blocks[0][1])) <= 15


@pytest.mark.parametrize("rel", PAGES)
def test_every_relative_link_leads_to_a_file_and_every_anchor_to_a_word(rel):
    page = read(rel)
    words = read("docs/WORDS.md").lower()
    for target in re.findall(r"\]\(([^)\s]+)\)", page):
        if re.match(r"[a-z]+:", target):
            continue
        path, _, anchor = target.partition("#")
        assert ((ROOT / rel).parent / path).resolve().exists(), (rel, target)
        if path.endswith("WORDS.md") and anchor:
            assert f"### {anchor.replace('-', ' ')}" in words, (rel, anchor)


def test_the_top_down_arithmetic_is_what_its_inputs_give():
    page = read("docs/reference/MARKET_SIZE.md")
    assert "**The base: 7,400 million USD a year.** We add the three revenue figures we have: 4,000 + 2,500 + 900." in page
    base = 4000e6 + 2500e6 + 900e6
    got = rows(page, "| share paid per passed piece")
    assert [r[0].split("%")[0] for r in got] == ["1", "10", "27"]
    for share, value, high, low in got:
        v = base * float(share.split("%")[0]) / 100
        assert money(value) == pytest.approx(v), share
        assert money(high) == pytest.approx(v * 0.003) and money(low) == pytest.approx(v * 0.0015), share


def test_the_bottom_up_arithmetic_is_what_its_inputs_give():
    page = read("docs/reference/MARKET_SIZE.md")
    got = rows(page, "| case | buyers")
    assert len(got) == 3
    for _case, buyers, each, value, high, low in got:
        v = float(buyers.replace(",", "")) * money(each)
        assert money(value) == pytest.approx(v) and money(high) == pytest.approx(v * 0.003) and money(low) == pytest.approx(v * 0.0015)


def test_the_summary_in_market_md_agrees_with_the_page():
    page, market = read("docs/reference/MARKET_SIZE.md"), read("docs/reference/MARKET.md")
    part = market.split("### Market size", 1)[1].split("\n## ", 1)[0]
    assert "](MARKET_SIZE.md)" in part and "7,400 million USD" in part
    for figure in ("222,000", "5,994,000", "111,000", "2,997,000", "150,000", "6,000,000"):
        assert figure in part and figure in page, figure


def test_outside_figures_carry_links_and_knos_claims_no_share():
    for text in (read("docs/reference/MARKET_SIZE.md"), read("docs/reference/MARKET.md").split("### Market size", 1)[1].split("\n## ", 1)[0]):
        for item in re.split(r"\n(?=\||- |\n)", text):             # a table row, a list item or a paragraph
            if re.search(r"\bbillion\b", item):                       # only beside a sourced figure about another company
                assert "https://" in item and "Knos" not in item, item
            assert not re.search(r"\b(ARR|FCF)\b|free cash flow", item), item
        assert re.search(r"Knos has no share", text)
        assert "[assumption]" in text


def test_the_third_flow_prints_what_the_page_says():
    page = read("docs/reference/FLOWS.md")
    command = "knos meter reconcile examples/meter/buyer.jsonl examples/meter/seller.jsonl"
    assert command in page
    done = subprocess.run([sys.executable, "-m", "knos", *command.split()[1:]], cwd=ROOT, capture_output=True, text=True,
                          encoding="utf-8", env={**os.environ, "PYTHONPATH": str(ROOT / "src")}, timeout=120)
    out = done.stdout + done.stderr
    assert "202610,5,4,8000000," in out and "`202610,5,4,8000000,...`" in page
    assert "only the seller has" in out and "differs in verdict" in out and "\nsha256," in out
    assert "settle the lines above between you" in out
