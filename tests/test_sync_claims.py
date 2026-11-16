"""Round 13, E4 and F3: sync/claims.json, the one file of knos-sync's links, registers the numbers F3 names, and
keeps the law's blocking rules. knos-sync itself (sync/, Go) re-checks each entry in .github/workflows/sync.yml;
this test reads only the file, so it runs with the rest of the suite.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLAIMS = json.loads((ROOT / "sync" / "claims.json").read_text(encoding="utf-8"))
KINDS = {"version", "hash", "count", "price", "name"}


def test_only_version_hash_and_count_may_block_and_none_does_until_a_person_says_so():
    assert set(CLAIMS["kinds"]) == KINDS
    for kind, setting in CLAIMS["kinds"].items():
        assert not setting["block"] or kind in {"version", "hash", "count"}, kind


def test_every_entry_has_what_e4_names():
    ids = set()
    for e in CLAIMS["entries"]:
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
    [entry] = [e for e in CLAIMS["entries"] if e["command"] == ["json", "docs/data/scorecard_summary.json", "rows"]]
    assert entry["expected"] == str(rows)
    pricing = json.loads((ROOT / "docs" / "data" / "pricing.json").read_text(encoding="utf-8"))["numbers"]
    sources = " ".join(p["source"] for p in CLAIMS["pointers"])
    for name, number in pricing.items():
        assert f"docs/data/pricing.json numbers.{name}.value" in sources, name
        [pointer] = [p for p in CLAIMS["pointers"] if p["source"].endswith(f"numbers.{name}.value")]
        assert pointer["value"] == str(number["value"]), name
    assert any("docs/NUMBERS.md" in p["where"] for p in CLAIMS["pointers"])


def test_a_pointer_names_an_existing_check_or_says_its_source_is_outside():
    names = {x["name"] for x in CLAIMS["existing"]} | {"outside"}
    for p in CLAIMS["pointers"]:
        assert p["checked_by"] in names, p["id"]
