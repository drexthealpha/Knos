"""Round 13, E4 and F3: sync/facts.json, the one file of knos-sync's links, registers the numbers F3 names, and
keeps the law's blocking rules. knos-sync itself (sync/, Go) re-checks each entry in .github/workflows/sync.yml;
this test reads only the file, so it runs with the rest of the suite.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FACTS = json.loads((ROOT / "sync" / "facts.json").read_text(encoding="utf-8"))
KINDS = {"version", "hash", "count", "price", "name"}


def test_only_version_hash_and_count_may_block_and_none_does_until_a_person_says_so():
    assert set(FACTS["kinds"]) == KINDS
    for kind, setting in FACTS["kinds"].items():
        assert not setting["block"] or kind in {"version", "hash", "count"}, kind


def test_every_entry_has_what_e4_names():
    ids = set()
    for e in FACTS["entries"]:
        assert {"id", "kind", "places", "command", "expected", "comparator", "confirmed_by_person"} <= set(e), e.get("id")
        assert e["kind"] in KINDS and e["places"] and e["command"]
        for p in e["places"]:
            assert p["says"] in p["text"] and p["line"] >= 1
            line = (ROOT / p["file"]).read_text(encoding="utf-8").splitlines()
            assert any(p["text"] in ln for ln in line), (e["id"], p)
        assert e["id"] not in ids
        ids.add(e["id"])


def test_f3_numbers_are_registered():
    rows = json.loads((ROOT / "docs" / "data" / "scorecard_summary.json").read_text(encoding="utf-8"))["rows"]
    [entry] = [e for e in FACTS["entries"] if e["command"] == ["json", "docs/data/scorecard_summary.json", "rows"]]
    assert entry["expected"] == str(rows)
    # every number of pricing.json is an entry of its own, with a place it is stated (F3: not a pointer)
    pricing = json.loads((ROOT / "docs" / "data" / "pricing.json").read_text(encoding="utf-8"))["numbers"]
    for name, number in pricing.items():
        [e] = [e for e in FACTS["entries"] if e["command"] == ["json", "docs/data/pricing.json", f"numbers.{name}.value"]]
        assert e["expected"] == str(number["value"]) and e["places"] and e["confirmed_by_person"] is False, name
    # every PASS or STOP line of docs/NUMBERS.md that states a number is a place of an entry, and each entry's
    # expected value is what its command reads
    measures = json.loads((ROOT / "docs" / "data" / "measures.json").read_text(encoding="utf-8"))
    placed = {(p["file"], p["line"]) for e in FACTS["entries"] for p in e["places"]}
    lines = (ROOT / "docs" / "NUMBERS.md").read_text(encoding="utf-8").splitlines()
    stated = [i + 1 for i, ln in enumerate(lines) if ln.startswith(("- PASS: ", "- STOP: ")) and "not given in the law" not in ln]
    assert len(stated) == 4 and all(("docs/NUMBERS.md", n) in placed for n in stated), stated
    for e in FACTS["entries"]:
        if e["command"][:2] == ["json", "docs/data/measures.json"]:
            value = measures
            for part in e["command"][2].split("."):
                value = value[int(part)] if isinstance(value, list) else value[part]
            assert e["expected"] == str(value), e["id"]
    no_pointer = ("docs/NUMBERS.md", "docs/data/pricing.json", "docs/data/scorecard_summary.json")
    assert not [p["id"] for p in FACTS["pointers"] if any(f in p["source"] or f in p["where"] for f in no_pointer)]


def test_a_pointer_names_an_existing_check_or_says_its_source_is_outside():
    names = {x["name"] for x in FACTS["existing"]} | {"outside"}
    for p in FACTS["pointers"]:
        assert p["checked_by"] in names, p["id"]
