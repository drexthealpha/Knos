"""The fee-bounds proofs (programs-v2/fee_proofs) and the adversarial handler tests, held to what the documents say:
docs/kani.json `fee_proofs` is about the harnesses and the program's lines as they are; a harness counts as proved
only when Kani verified it within the limit; the words of docs/INVARIANTS.md are the record's; the new crate is in no
program's build and outside the release's version rules; every transaction the Rust tests name is in the vectors."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import bump_version as bump  # noqa: E402
import kani_fee_record as rec  # noqa: E402

KANI = json.loads((ROOT / "docs" / "kani.json").read_text(encoding="utf-8"))
FEE = KANI["fee_proofs"]
PAGE = (ROOT / "docs" / "INVARIANTS.md").read_text(encoding="utf-8")
CRATE = ROOT / "programs-v2" / "fee_proofs"


def test_the_record_is_about_the_harnesses_and_the_programs_lines_as_they_are():
    assert rec.check() == []
    assert [h["name"] for h in FEE["harnesses"]] == rec.harnesses() and len(rec.harnesses()) == 12
    assert FEE["limit_seconds"] == 150 and FEE["version"] == KANI["version"]


def test_a_fee_harness_counts_as_proved_only_when_kani_verified_it_within_the_limit():
    for h in FEE["harnesses"]:
        assert h["result"] in ("verified", "failed", "timed out") and h["proved"] is (h["result"] == "verified"), h["name"]
        assert 0 < h["seconds"] <= FEE["limit_seconds"] + 1, h["name"]
        if h["proved"]:
            assert h["checks"] > 0 and h["failed_checks"] == 0 and h["verification_seconds"] <= h["seconds"], h["name"]
        else:
            assert "Not proved" in h["note"], h["name"]


def test_the_parts_cover_every_amount_and_rate_and_the_status_is_what_they_say():
    s = FEE["summary"]
    assert s == rec.summary(FEE["harnesses"], rec.whole(KANI))
    assert s["status"] in ("verified", "verified per tier", "not verified")
    assert {(p["amount"], p["rate_bps"]) for p in s["parts"]} == {
        ("0 to 1,000.00", "50..=249"), ("0 to 1,000.00", "250"), ("above 1,000.00, to 50,000.00", "50..=250"), ("above 50,000.00, to 100,000.00", "50..=250")}
    # the first tier's harnesses go through every rate from 50 to 249 once, with no gap
    rates = sorted(tuple(int(n) for n in h["range"]["rate_bps"].split("..=")) for h in FEE["harnesses"] if h["name"] in rec.FIRST)
    assert rates[0][0] == 50 and rates[-1][1] == 249 and all(b[0] == a[1] + 1 for a, b in zip(rates, rates[1:]))
    assert all(h["range"]["amount"] == "amount <= FEE_TIER_1" for h in FEE["harnesses"] if h["name"] in (*rec.FIRST, rec.TOP))
    for part in s["parts"]:
        assert part["result"] == "verified" or len(part.get("note", "")) > 40      # what is not proved says so and why
        assert all(n in rec.harnesses() for n in part["harnesses"])


def test_the_page_says_the_records_words_and_no_more():
    body = PAGE.split("- **The fee's bounds, per tier**")[1].split("- **The meter:**")[0]
    by = {(p["amount"], p["rate_bps"], p["stated"]): p["result"] for p in FEE["summary"]["parts"]}
    assert ("above 1,000 and up to 50,000, every rate: **verified**" in body) is (by[("above 1,000.00, to 50,000.00", "50..=250", rec.BOUNDS)] == "verified")
    assert ("above 50,000 and up to 100,000 (the most an order holds), every rate: **verified**" in body) is (by[("above 50,000.00, to 100,000.00", "50..=250", rec.BOUNDS)] == "verified")
    assert ("0 to 1,000 at the rates 50 to 249: **verified**" in body) is (by[("0 to 1,000.00", "50..=249", rec.BOUNDS)] == "verified")
    assert ('amount" is **not verified**' in body) is (by[("0 to 1,000.00", "250", "0.40 or at most 2.5% of the amount")] == "not verified")
    assert ("is **not verified** as a whole" in body) is (FEE["summary"]["status"] == "not verified")
    assert "**not verified** in one harness" in PAGE and FEE["summary"]["whole_range_in_one_harness"] == "not verified"
    assert f"within {FEE['limit_seconds']} seconds" in body


def test_the_native_test_named_for_the_unproved_part_exists():
    tests = (CRATE / "tests" / "reference.rs").read_text(encoding="utf-8")
    for name in re.findall(r"reference\.rs, (\w+)\.", rec.NO_HARNESS):
        assert f"fn {name}()" in tests
    assert "for amount in 0..=FEE_TIER_1 {" in tests and "0..10_000_000u32" in tests


def test_the_proof_crate_is_in_no_programs_build_and_outside_the_releases_version_rules():
    manifest = (CRATE / "Cargo.toml").read_text(encoding="utf-8")
    assert 'name = "knos-fee-proofs"' in manifest and 'version = "0.0.0"' in manifest and "\n[workspace]\n" in manifest and "publish = false" in manifest
    assert "[dependencies]" not in manifest and "[dev-dependencies]" not in manifest       # the program's lines as text, and nothing else
    assert "fee_proofs" not in (ROOT / "programs-v2" / "Cargo.toml").read_text(encoding="utf-8")
    assert "fee_proofs" not in (ROOT / "programs-v2" / "Cargo.lock").read_text(encoding="utf-8")
    assert "knos-fee-proofs" not in bump.OURS and "knos-fee-proofs" not in bump.PROGRAMS_FROZEN
    assert not [rel for rel, _line, _got in bump.places() if "fee_proofs" in rel]
    # nothing under a program's src names it
    for src in (ROOT / "programs-v2").glob("knos_*/src/*.rs"):
        assert "fee_proofs" not in src.read_text(encoding="utf-8"), src.name


def test_every_transaction_the_adversarial_tests_name_is_in_the_vectors_and_the_findings_stay_ignored():
    source = (ROOT / "programs-v2" / "handlers" / "tests" / "adversarial.rs").read_text(encoding="utf-8")
    tests = re.findall(r"#\[test\]\n((?:#\[ignore[^\n]*\]\n)?)fn (\w+)\(\) \{\n(.*?)\n\}\n", source, re.S)
    assert len(tests) == source.count("#[test]") == 16
    ignored = [name for mark, name, _ in tests if mark]
    assert ignored == json.loads((ROOT / "docs" / "invariants.json").read_text(encoding="utf-8"))["adversarial"]["ignored_findings"]
    assert all(name.startswith("finding_") and f"`{name}`" in PAGE for name in ignored) and len(ignored) == 2
    seen = set()
    for _mark, name, body in tests:
        loaded = re.findall(r'Replay::load\("(\w+)"\)', body)
        if not loaded:
            continue
        doc = json.loads((ROOT / "programs-v2" / "testdata" / f"{loaded[0]}.json").read_text(encoding="utf-8"))
        labels = [s.get("label") for s in doc["steps"] if s["op"] == "tx"]
        named = re.findall(r'r\.to\("(\w+)"\)', body) + [x for group in re.findall(r"for label in \[([^\]]+)\]", body) for x in re.findall(r'"(\w+)"', group)]
        assert named and [n for n in named if n not in labels] == [], name
        seen.add(loaded[0])
        assert all(p["file"].endswith("_test.so") for p in doc["programs"])
    assert seen == {p.stem for p in (ROOT / "programs-v2" / "testdata").glob("adv_*.json")}
