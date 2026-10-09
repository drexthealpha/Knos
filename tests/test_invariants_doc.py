"""docs/INVARIANTS.md names the test behind every guarantee. A name that no longer exists is a guarantee nobody checks:
every test file the page names is there, and every test function it names is defined in one of the files it names."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = (ROOT / "docs" / "INVARIANTS.md").read_text(encoding="utf-8")
FILES = sorted(set(re.findall(r"`(tests/[\w/]+\.py)`", DOC)))
NAMES = sorted(set(re.findall(r"`(test_\w+)`", DOC)))


def test_every_test_file_the_page_names_exists():
    assert len(FILES) >= 8
    assert [f for f in FILES if not (ROOT / f).is_file()] == []


def test_every_test_the_page_names_is_defined_in_a_file_it_names():
    defined = set()
    for f in FILES:
        path = ROOT / f
        defined |= set(re.findall(r"^def (test_\w+)\(", path.read_text(encoding="utf-8"), re.M)) if path.is_file() else set()
    assert len(NAMES) >= 30
    assert [n for n in NAMES if n not in defined] == []


def test_each_of_the_nine_invariants_names_what_enforces_it_and_what_checks_it_or_says_no_test_yet():
    parts = re.split(r"^### (\d)\. ", DOC, flags=re.M)[1:]
    assert parts[0::2] == [str(n) for n in range(1, 10)]
    for number, body in zip(parts[0::2], parts[1::2]):
        body = body.split("\n## ")[0]
        assert "Enforced by" in body or "| bound to | by |" in body, number
        assert re.search(r"`tests/\w+\.py`", body), number
    listed = DOC.split("## Not yet tested, in one list")[1]
    assert len(re.findall(r"^\d\. Invariant \d", listed, re.M)) == DOC.count("no test yet") + DOC.count("No test yet") - 1     # the intro names the phrase once


def test_the_economic_idempotency_rows_cover_the_lifecycle_and_name_tests_that_exist():
    import json
    doc = json.loads((ROOT / "docs" / "invariants.json").read_text(encoding="utf-8"))["economic_idempotency"]
    through = [r["through"] for r in doc["rows"]]
    assert through == ["refund", "reopen", "standing order", "assignment", "warranty holdback", "partial payments", "bank rail"]
    section = DOC.split("## " + doc["page_section"])[1].split("\n## ")[0]
    for r in doc["rows"]:
        assert f"| {r['through']} |" in section and r["tests"], r["through"]
        for t in r["tests"]:
            source = (ROOT / t["file"]).read_text(encoding="utf-8")
            assert re.search(rf"^def {t['test']}\(", source, re.M) and f"`{t['test']}`" in section, t
