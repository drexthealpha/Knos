"""tests/web/law_not_met.json: the law checks that stay NOT MET until a person, an outside account or spending gives
what they need (Round 13 H2). Each id is a check of tests/web/law_checks.mjs, each "needs" one of the three values, each
reason at most 20 words. law_checks.mjs itself fails a listed check that passes or fails for anything else."""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LISTED = json.loads((ROOT / "tests" / "web" / "law_not_met.json").read_text(encoding="utf-8"))
IDS = re.findall(r'^C\("([^"]+)"', (ROOT / "tests" / "web" / "law_checks.mjs").read_text(encoding="utf-8"), re.M)


def test_the_checks_are_read():
    assert len(IDS) == len(set(IDS)) >= 159


def test_every_listed_id_is_a_check():
    assert LISTED, "the list is empty"
    assert sorted(set(LISTED) - set(IDS)) == []


def test_needs_is_one_of_three():
    bad = {k: v.get("needs") for k, v in LISTED.items() if v.get("needs") not in ("person", "outside account", "spending")}
    assert bad == {}


def test_reason_is_at_most_20_words_and_nothing_else():
    for k, v in LISTED.items():
        assert set(v) == {"reason", "needs"}, k
        assert 1 <= len(v["reason"].split()) <= 20, k
        assert chr(0x2014) not in v["reason"], k  # no em dash
