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
    assert [h["name"] for h in FEE["harnesses"]] == rec.harnesses() and len(rec.harnesses()) == 5
    assert FEE["limit_seconds"] == 150 and FEE["version"] == KANI["version"]


def test_a_fee_harness_counts_as_proved_only_when_kani_verified_it_within_the_limit():
    for h in FEE["harnesses"]:
        assert h["result"] in ("verified", "failed", "timed out") and h["proved"] is (h["result"] == "verified"), h["name"]
        # the exact words: verified, failed, or not verified with the seconds and the solver that did not answer
        assert h["words"] == rec.words(h["result"], FEE["limit_seconds"], h["solver"]) and h["solver"], h["name"]
        assert re.fullmatch(r"verified|failed|not verified \(timed out at \d+ s, solver [^)]+\)", h["words"]), h["name"]
        assert h["solver"].startswith("cvc5 ") is (rec.solvers()[h["name"]] == "cvc5"), h["name"]
        assert 0 < h["seconds"] <= FEE["limit_seconds"] + 1, h["name"]
        if h["proved"]:
            assert h["checks"] > 0 and h["failed_checks"] == 0 and h["verification_seconds"] <= h["seconds"], h["name"]
        else:
            assert "Not proved" in h["note"], h["name"]


def test_the_parts_cover_every_amount_and_rate_and_the_status_is_what_they_say():
    s = FEE["summary"]
    assert s == rec.summary(FEE["harnesses"], rec.whole(KANI))
    assert s["status"] in ("verified", "verified but for one bound at one rate", "not verified")
    assert {(p["amount"], p["rate_bps"]) for p in s["parts"]} == {("0 to 100,000.00", "10..=29"), ("0 to 100,000.00", "30"), ("every u64", "30 (a job)")}
    # one rate, so no tier: the harnesses about an order go through every rate from 10 to 30 once, with no gap, over the whole range
    rates = sorted(tuple(int(n) for n in h["range"]["rate_bps"].split("..=")) for h in FEE["harnesses"] if h["name"] in rec.LOWER)
    assert rates[0][0] == 10 and rates[-1][1] == 29 and all(b[0] == a[1] + 1 for a, b in zip(rates, rates[1:]))
    by = {h["name"]: h for h in FEE["harnesses"]}
    assert by[rec.TOP]["range"] == {"amount": "amount <= MAX_AMOUNT", "rate_bps": "30"} and by[rec.JOB]["range"]["amount"] == "every u64"
    assert all(h["range"]["amount"] == "amount <= MAX_AMOUNT" for h in FEE["harnesses"] if h["name"] in (*rec.LOWER, rec.TOP))
    for part in s["parts"]:
        assert part["result"] == "verified" or len(part.get("note", "")) > 40      # what is not proved says so and why
        assert all(n in rec.harnesses() for n in part["harnesses"])
    # the exact bound at the top rate has one harness, over the whole range, and the record calls the whole statement
    # verified only when that harness is; the part says which solver answered and what its result rests on
    exact = next(p for p in s["parts"] if p["stated"] == "0.05 or at most 0.30% of the amount")
    assert exact["harnesses"] == [rec.EXACT] and by[rec.EXACT]["range"] == {"amount": "amount <= MAX_AMOUNT", "rate_bps": "30"}
    assert (exact["result"] == "verified") is by[rec.EXACT]["proved"] and (s["status"] != "verified" or by[rec.EXACT]["proved"] or rec.whole(KANI))
    assert "--solve-bv-as-int=sum" in exact["note"] and "rests on that translation" in exact["note"]


def test_the_exact_bound_is_asked_of_the_programs_own_function_and_of_the_solver_the_record_names():
    source = (CRATE / "src" / "lib.rs").read_text(encoding="utf-8")
    body = source.split(f"fn {rec.EXACT}()", 1)[1]
    assert "order_fee(amount, FEE_BPS, DECIMALS)" in body and "bps_of(amount, FEE_BPS)" in body and "kani::assume(amount <= MAX_AMOUNT);" in body
    assert "fee == FLOOR || fee * 10_000 <= amount * FEE_BPS" in body and "q * 10_000 <= p && p < (q + 1) * 10_000" in body
    assert rec.solvers() == {**{n: "cadical" for n in rec.harnesses()}, rec.EXACT: "cvc5"}
    # the functions are the program's lines, included from what build.rs copies: none is written again in this crate
    assert 'include!(concat!(env!("OUT_DIR"), "/fee.rs"));' in source and "fn order_fee" not in source and "fn bps_of" not in source
    wrapper = (CRATE / "solvers" / "cvc5").read_text(encoding="utf-8")
    assert wrapper.startswith("#!/bin/sh\n") and wrapper.rstrip().endswith('exec "$real" --solve-bv-as-int=sum "$@"')
    assert rec.environment("cvc5")["PATH"].split(rec.os.pathsep)[0] == str(CRATE / "solvers") and "solvers" not in rec.environment("cadical").get("PATH", "").split(rec.os.pathsep)[0]


def test_what_was_tried_and_not_answered_is_recorded_in_exact_words():
    tried = FEE["not_answered"]
    assert tried == rec.not_answered() and len(tried["why"]) > 100
    solvers = {t["solver"].split(",")[0].rsplit(" ", 1)[0] for t in tried["trials"]}
    assert solvers == {"CaDiCaL", "Kissat", "Z3", "cvc5"}
    for t in tried["trials"]:
        assert t["words"] == f"not verified (timed out at {t['limit_seconds']} s, solver {t['solver']})" or t["words"].startswith(("verified (", "failed, as it must"))
    # a false statement was refuted by the setup that verifies the true one
    assert [t for t in tried["trials"] if "control" in t["form"] and t["words"].startswith("failed, as it must") and "--solve-bv-as-int=sum" in t["solver"]]


def test_the_page_says_the_records_words_and_no_more():
    body = PAGE.split("- **The fee's bounds, by rate**")[1].split("- **The meter:**")[0]
    by = {(p["amount"], p["rate_bps"], p["stated"]): p["result"] for p in FEE["summary"]["parts"]}
    lower, top = body.split("- at the rates 10 to 29:")[1].split("\n  - ")[0], body.split("- at the rate 30, the rate of an order with no Plan:")[1].split("\n  - ")[0]
    assert ("**verified**" in lower) is (by[("0 to 100,000.00", "10..=29", rec.BOUNDS)] == "verified") and "at most 0.30% of the amount" in lower
    assert ("**verified**" in top) is (by[("0 to 100,000.00", "30", "at least 0.05; 0.05 or at most 0.31% of the amount; adds to the amount in a u64")] == "verified")
    assert "at most 0.31% of the amount" in top and "0.30%" not in top
    exact = body.split('- at the rate 30, "0.05 or at most 0.30% of the amount"')[1].split("\n  - ")[0]
    assert ("**verified with cvc5**" in exact) is (by[("0 to 100,000.00", "30", "0.05 or at most 0.30% of the amount")] == "verified")
    assert "--solve-bv-as-int=sum" in exact and "rests on cvc5's translation" in " ".join(exact.split()) and "not verified" not in body
    assert ("never more than the amount: **verified**" in body) is (by[("every u64", "30 (a job)", "never more than the amount; at least 0.05 or the whole amount")] == "verified")
    assert (f"is **{FEE['summary']['status']}**" in " ".join(body.split())) and FEE["summary"]["status"] in ("verified", "verified but for one bound at one rate", "not verified")
    assert f"within {FEE['limit_seconds']} seconds" in body
    # the page does not say more of the one harness over every amount than the record does
    whole = next(h for h in KANI["harnesses"] if h["name"] == rec.WHOLE)
    assert FEE["summary"]["whole_range_in_one_harness"] == ("verified" if whole["proved"] else "not verified")
    assert ("timed out and is not proved there" in PAGE) is (whole["result"] == "timed out")


def test_the_native_test_named_for_the_unproved_part_exists():
    tests = (CRATE / "tests" / "reference.rs").read_text(encoding="utf-8")
    names = re.findall(r"reference\.rs, (\w+)\.", rec.EXACT_NOTE)
    assert len(names) == 1
    for name in names:
        assert f"fn {name}()" in tests
    assert "for r in 0..10_000u64 {" in tests and "0..10_000_000u32" in tests and "assert_eq!(checked, 20_010_000);" in tests


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


def test_every_transaction_the_adversarial_tests_name_is_in_the_vectors_and_no_finding_is_ignored():
    source = (ROOT / "programs-v2" / "handlers" / "tests" / "adversarial.rs").read_text(encoding="utf-8")
    tests = re.findall(r"#\[test\]\n((?:#\[ignore[^\n]*\]\n)?)fn (\w+)\(\) \{\n(.*?)\n\}\n", source, re.S)
    assert len(tests) == source.count("#[test]") == 27 and "#[ignore" not in source
    listed = json.loads((ROOT / "docs" / "invariants.json").read_text(encoding="utf-8"))["adversarial"]
    # the two findings of knos_pay 2.1 are fixed and run as ordinary tests: a release does not go out with one failing
    assert [name for mark, name, _ in tests if mark] == listed["ignored_findings"] == []
    fixed = [name for _mark, name, _ in tests if name.startswith("finding_")]
    assert sorted(fixed) == sorted(listed["fixed_findings"]) and len(fixed) == 2 and all(f"`{name}`" in PAGE for name in fixed)
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
