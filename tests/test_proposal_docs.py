"""docs/PROPOSAL-2.3.md (the written upgrade proposal for knos_pay) and docs/KEYS.md (the plan for the keys) say only
what the programs hold.

- Every name either page puts in backticks exists: an instruction or account of the IDL, a word of the programs'
  source, an account seed (`["ov", order]` needs `b"ov"`), a token audience (`knos3:rule` needs that text in the
  source), a file of the repository. The one exception is the proposal's table "New names this proposal adds": each
  of those must NOT exist yet, so the page cannot pass a new name off as an old one, nor an old one as new.
- Neither page claims an outside key holder: KEYS.md's count is web/keyholders.json's, and no sentence says one holds,
  signed or joined anything.
- Both say "proposed" and "not deployed"; the proposal also "not built".
- The diagrams are Mermaid that GitHub draws: two sequence diagrams in the proposal (today, proposed), one in KEYS.md,
  each with an italic caption under it, no colour or theme set, no semicolon in a sequence diagram (it breaks the
  parser).
- Each page opens with the mark, and its "In plain words" part reads at a Flesch-Kincaid grade of 8 or lower.

Everything here reads files.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PROPOSAL, KEYS = "docs/PROPOSAL-2.3.md", "docs/KEYS.md"
SOURCES = [ROOT / "programs-v2" / "knos_pay" / "src", ROOT / "programs-v2" / "knos_oidc" / "src"]
IDLS = [ROOT / "idl" / "knos_pay_v2.json", ROOT / "idl" / "knos_oidc_v2.json"]
FILE_DIRS = [".github/workflows", "programs-v2", "scripts", "src", "docs", "idl", "web", "tests", "examples"]
MARK = '<img src="../web/brand/mark.svg" height="40" alt="Knos">'
NEW_NAMES = "## New names this proposal adds"


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def source_text() -> str:
    return "\n".join(p.read_text(encoding="utf-8") for d in SOURCES for p in sorted(d.rglob("*.rs")))


def idl_names() -> set[str]:
    out: set[str] = set()
    for path in IDLS:
        data = json.loads(path.read_text(encoding="utf-8"))
        out |= {i["name"] for i in data.get("instructions", [])} | {a["name"] for a in data.get("accounts", [])}
    return out


def prose(text: str) -> str:
    """The page without its fenced blocks."""
    return re.sub(r"(?ms)^```.*?^```", "", text)


def spans(text: str) -> list[str]:
    return re.findall(r"`([^`\n]+)`", prose(text))


def new_names(text: str) -> list[str]:
    table = text.split(NEW_NAMES, 1)[1] if NEW_NAMES in text else ""
    return re.findall(r"(?m)^\| `([^`]+)` \|", table)


def exists(span: str, src: str, idl: set[str]) -> bool:
    """Whether a backticked name is in the programs, the IDL or the repository."""
    if (seed := re.fullmatch(r'\["([a-z]+)", [a-z_ ,]+\]', span)):
        return f'b"{seed.group(1)}"' in src
    if (aud := re.match(r"(knos[23]:[a-z]+)", span)):
        return aud.group(1) + ":" in src
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", span):
        return span in idl or re.search(r"\b" + re.escape(span) + r"\b", src) is not None
    if " " in span:                              # a command: the files it names exist
        return all((ROOT / w).exists() for w in span.split() if "/" in w)
    if "/" in span:
        return (ROOT / span).exists()
    if re.fullmatch(r"[\w.-]+\.(rs|yml|py|json|md|mjs|js)", span):
        return any(next((ROOT / d).rglob(span), None) is not None for d in FILE_DIRS)
    raise AssertionError(f"a backticked span this test cannot place: {span!r}")


@pytest.fixture(scope="module")
def chain() -> tuple[str, set[str]]:
    return source_text(), idl_names()


@pytest.mark.parametrize("rel", [PROPOSAL, KEYS])
def test_every_name_the_page_uses_exists_in_the_idl_or_the_source(rel, chain):
    src, idl = chain
    text = read(rel)
    new = set(new_names(text))
    used = [s for s in spans(text) if s not in new and not any(s.startswith(n + ":") for n in new)]
    assert used, rel
    assert [s for s in used if not exists(s, src, idl)] == [], f"{rel} names something the programs do not have"


def test_the_proposals_new_names_do_not_exist_yet_and_are_used(chain):
    src, idl = chain
    text = read(PROPOSAL)
    new = new_names(text)
    assert len(new) >= 8 and len(set(new)) == len(new)
    assert [n for n in new if exists(n, src, idl)] == [], "a name the table calls new is already in the programs"
    body = text.split(NEW_NAMES, 1)[0]
    assert [n for n in new if f"`{n}`" not in body and not any(s.startswith(n + ":") for s in spans(body))] == []
    assert new_names(read(KEYS)) == []                       # the keys page proposes no program name


def test_the_check_tells_old_names_from_new_ones(chain):
    src, idl = chain
    for old in ("PayOrder", "RefundOrder", "Order", "Hb", "Approve", "holdback_bps", "O_RESERVED", '["ov", order]', '["hb", order]',
                "knos3:rule:<order>", "prove.yml", "programs-v2/knos_pay/src/lib.rs", "knos status"):
        assert exists(old, src, idl), old
    for new in ("Pass", "PayPassed", "bond_paid", '["pass", order]', "knos3:pass:<order>", "nowhere.yml", "programs-v2/nowhere.rs"):
        assert not exists(new, src, idl), new
    with pytest.raises(AssertionError):
        exists("a|b", src, idl)


def test_neither_page_claims_an_outside_key_holder():
    outside = json.loads(read("web/keyholders.json"))["outside"]
    keys = read(KEYS)
    said = re.findall(r"\*\*Outside key holders today: (\d+)\.\*\*", keys)
    assert said == [str(len(outside))] == ["0"]
    claim = re.compile(r"outside (key ?holder|signer)s? (now |already )?(holds?|has|have|signed|approved|voted|joined)\b"
                       r"|\b(is|are) now held by\b|\bholds? one of (the|our) keys\b|outside key holders?( today)?:?\**\s*[1-9]", re.I)
    for rel in (PROPOSAL, KEYS):
        assert claim.search(prose(read(rel))) is None, rel
    assert "Nobody has\nbeen asked yet." in keys or "Nobody has been asked yet." in keys


def test_both_pages_say_proposed_and_not_deployed():
    for rel in (PROPOSAL, KEYS):
        head = read(rel).split("\n## ", 1)[0]
        assert re.search(r"\*\*Proposed\. (Not built\. )?Not deployed\.\*\*", head), rel
    assert "**Proposed. Not built. Not deployed.**" in read(PROPOSAL)


def mermaid(text: str) -> list[tuple[str, str]]:
    """Each fenced Mermaid block, with the first line that follows it that is not blank."""
    return [(m.group(1), m.group(2)) for m in re.finditer(r"(?ms)^```mermaid\n(.*?)^```\n\s*\n?([^\n]*)", text)]


@pytest.mark.parametrize("rel,kinds", [(PROPOSAL, ["sequenceDiagram", "sequenceDiagram"]), (KEYS, ["flowchart TB"])])
def test_the_diagrams_are_plain_mermaid_with_a_caption(rel, kinds):
    blocks = mermaid(read(rel))
    assert [body.splitlines()[0].strip() for body, _ in blocks] == kinds
    for body, caption in blocks:
        assert re.fullmatch(r"\*[^*]+\*", caption.strip()), caption          # one line in italics under it
        assert not re.search(r"(?m)^\s*(style|classDef|linkStyle|class )|%%\{|themeVariables|fill:", body)
        if body.startswith("sequenceDiagram"):
            assert ";" not in body


def syllables(word: str) -> int:
    w = word.lower()
    n = len(re.findall(r"[aeiouy]+", w))
    if w.endswith("e") and not w.endswith(("le", "ee")) and n > 1:
        n -= 1
    return max(1, n)


def grade(text: str) -> tuple[float, float]:
    """Flesch-Kincaid grade level, and the average sentence length in words."""
    text = re.sub(r"\]\([^)]*\)", "]", text)
    text = re.sub(r"[`*\[\]]|^\s*\d+\.\s", " ", text, flags=re.M)
    sentences = [s for s in re.split(r"[.!?]+(?:\s+|$)", text) if re.search(r"[A-Za-z]", s)]
    words = re.findall(r"[A-Za-z]+(?:'[a-z]+)?|\d+(?:\.\d+)?", text)
    syl = sum(syllables(w) if w[0].isalpha() else 1 for w in words)
    return 0.39 * len(words) / len(sentences) + 11.8 * syl / len(words) - 15.59, len(words) / len(sentences)


@pytest.mark.parametrize("rel", [PROPOSAL, KEYS])
def test_the_page_opens_with_the_mark_and_plain_words(rel):
    text = read(rel)
    assert text.startswith(MARK + "\n")
    plain = text.split("## In plain words", 1)[1].split("\n## ", 1)[0]
    fk, length = grade(plain)
    assert fk <= 8, (rel, round(fk, 1))
    assert length <= 15, (rel, round(length, 1))


def test_the_grade_formula_on_known_text():
    easy, hard = grade("The cat sat. The dog ran."), grade("Institutional counterparties necessitate comprehensive reconciliation procedures.")
    assert easy[0] < 2 < 8 < hard[0] and easy[1] == 3
    assert (syllables("money"), syllables("the"), syllables("table"), syllables("escrow")) == (2, 1, 2, 2)
