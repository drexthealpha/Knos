"""tests/web/law_not_met.json: the law checks that stay NOT MET until a person, an outside account or spending gives
what they need, where another law rule wins over the check's ("law conflict", with the winning rule in "won_by"), or
where the host does not let the site do it ("host limit", with "why") (Round 13 H2, FIX-2). Each id is a check of
tests/web/law_checks.mjs, each "needs" one of the five values, each reason at most 20 words. law_checks.mjs itself fails
a listed check that passes or fails for anything else."""

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


NEEDS = ("person", "outside account", "spending", "law conflict", "host limit")
FIELDS = {"law conflict": {"reason", "needs", "won_by"}, "host limit": {"reason", "needs", "why"}}
RULE_AT = re.compile(r"^(UX|DISTRIBUTION|SYNC|MISSION)/[\w.-]+\.md:\d+$")
LAWS = ROOT.parent / "knos-v1-private" / "v0328" / "research" / "LAWS"


def test_needs_is_one_of_five():
    bad = {k: v.get("needs") for k, v in LISTED.items() if v.get("needs") not in NEEDS}
    assert bad == {}


def test_a_law_conflict_names_the_winning_rule_and_a_host_limit_says_why():
    for k, v in LISTED.items():
        if v["needs"] == "law conflict":
            assert RULE_AT.match(v["won_by"]) and v["won_by"] != k, k
        if v["needs"] == "host limit":
            assert isinstance(v["why"], str) and len(v["why"].split()) >= 5 and chr(0x2014) not in v["why"], k


def test_the_winning_rule_is_a_line_of_its_law_file_when_the_laws_are_here():
    if not LAWS.is_dir():
        return                                                             # the laws are kept outside the repository
    for k, v in LISTED.items():
        if v["needs"] == "law conflict":
            f, line = v["won_by"].rsplit(":", 1)
            lines = (LAWS / f).read_text(encoding="utf-8").splitlines()
            assert lines[int(line) - 1].strip(), (k, v["won_by"])        # the line exists and is not blank


def test_reason_is_at_most_20_words_and_nothing_else():
    for k, v in LISTED.items():
        assert set(v) == FIELDS.get(v["needs"], {"reason", "needs"}), k
        assert 1 <= len(v["reason"].split()) <= 20, k
        assert chr(0x2014) not in v["reason"], k  # no em dash
