#!/usr/bin/env python3
"""Runs the Kani harnesses of programs-v2/fee_proofs and records what the solver answered in docs/kani.json, under
`fee_proofs` (the rest of that file, the run of programs-v2/knos_pay/src/proofs.rs, is not touched), and the same
summary under invariant 8 of docs/invariants.json. docs/INVARIANTS.md says it in words; tests/test_fee_proofs.py holds
the page's words to the record.

    python scripts/kani_fee_record.py --harness <name>   # run one harness alone, within the limit, and record it
    python scripts/kani_fee_record.py --all              # every harness of src/lib.rs, one after the other
    python scripts/kani_fee_record.py --check            # fail if the record is not about the source as it is now

A harness is `verified` only when Kani printed VERIFICATION:- SUCCESSFUL with no failed check before the limit;
`timed out` and `failed` prove nothing. The record carries the hash of src/lib.rs (the harnesses) and of the program's
lines they are about (what build.rs copies out of knos_pay/src), so a change to either makes --check fail until the
harnesses are run again. `summary` is written from the results, never by hand: the words `verified` (one harness
over every amount is proved), `verified per tier` (every part of every tier is) or `not verified`, for the statement
"the fee is within its bounds for every amount an order may hold"; `parts` says which statement holds over which range.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CRATE = ROOT / "programs-v2" / "fee_proofs"
RECORD = ROOT / "docs" / "kani.json"
INVARIANTS = ROOT / "docs" / "invariants.json"
LIMIT = 150
FIRST = tuple(f"the_fee_of_an_amount_in_the_first_tier_is_within_its_bounds_at_the_rates_{lo}_to_{hi}" for lo, hi in ((50, 100), (101, 150), (151, 200), (201, 225), (226, 231), (232, 237), (238, 243), (244, 249)))
TOP = "the_fee_of_an_amount_in_the_first_tier_at_the_rate_250_is_at_least_the_floor_and_adds_up"
BOUNDS = "at least 0.40; 0.40 or at most 2.5% of the amount; adds to the amount in a u64"
# every amount an order may hold at every rate, in parts: (amounts, rates, what is stated, the harnesses that state it)
PARTS = (("0 to 1,000.00", "50..=249", BOUNDS, FIRST),
         ("0 to 1,000.00", "250", "at least 0.40; adds to the amount in a u64", (TOP,)),
         ("0 to 1,000.00", "250", "0.40 or at most 2.5% of the amount", ()),
         ("above 1,000.00, to 50,000.00", "50..=250", BOUNDS, ("the_fee_of_an_amount_in_the_second_tier_is_within_its_bounds",)),
         ("above 50,000.00, to 100,000.00", "50..=250", BOUNDS, ("the_fee_of_an_amount_in_the_third_tier_is_within_its_bounds",)))
NO_HARNESS = ("No harness states it: asked of Kani 0.68 on 2026-10-06 for this range, CaDiCaL had not answered after 150 seconds and Kissat after 130 "
              "(at this rate the bound is exact, with nothing to spare). Tested instead at each of the 1,000,000,001 amounts: "
              "programs-v2/fee_proofs/tests/reference.rs, every_amount_of_the_first_tier_at_the_top_rate_is_the_reference.")
WHOLE = "an_orders_fee_is_between_its_floor_and_the_first_tiers_rate_for_every_amount"      # in knos_pay/src/proofs.rs: every amount, one harness
COPIED = ("FEE_BPS", "MAX_AMOUNT", "ORDER_FEE_MIN", "FEE_TIER_1", "FEE_TIER_2", "FEE_BPS_2", "FEE_BPS_3", "ORDER_MIN_AMOUNT", "PLAN_BPS_MIN")
ABOUT = ("Recorded runs of the Kani harnesses of programs-v2/fee_proofs/src/lib.rs, each run alone with a limit of 150 "
         "seconds. They are about `order_fee`, `bps_of` and `units` as build.rs copies them, line for line, out of "
         "programs-v2/knos_pay/src (lib.rs and state.rs), for a mint of 6 decimals and every rate from 50 to 250 basis "
         "points. `verified`: Kani reported VERIFICATION SUCCESSFUL with no failed check. `timed out`: the limit passed "
         "first, so nothing is proved by that entry. `range` is the set of amounts the harness assumes, in units of a "
         "millionth, and the rates it goes through; a harness proves its statement for that range and for nothing outside it. "
         "`summary` is computed from the entries: its `status` is `verified` when one harness over every amount is, `verified "
         "per tier` when every part is, and `not verified` otherwise; `parts` says which statement is verified over which "
         "amounts and rates, and which is not.")


def harnesses() -> list[str]:
    source = (CRATE / "src" / "lib.rs").read_text(encoding="utf-8")
    names = re.findall(r"#\[kani::proof\]\s*(?:#\[[^\]]*\]\s*)*fn (\w+)\s*\(", source)
    assert len(names) == source.count("#[kani::proof]"), "a harness this script cannot read"
    return names


def ranges() -> dict[str, dict[str, str]]:
    """The `kani::assume` on the amount of each harness, as written: the range its proof is about."""
    source = (CRATE / "src" / "lib.rs").read_text(encoding="utf-8")
    out = {}
    for name in harnesses():
        body = source.split(f"fn {name}()", 1)[1].split("#[kani::proof]", 1)[0]
        rates = re.search(r"each_rate\(amount, (\d+), (\d+)\)", body)
        assumed = re.search(r"kani::assume\((amount [^;]*)\);", body)
        assert assumed, f"{name}: no assumption about the amount"
        out[name] = {"amount": assumed.group(1),
                     "rate_bps": f"{rates.group(1)}..={rates.group(2)}" if rates else "250" if "order_fee(amount, FEE_BPS," in body else "50..=250"}
    return out


def program_lines() -> str:
    """The program's lines the harnesses are about, as build.rs takes them."""
    lib = (ROOT / "programs-v2" / "knos_pay" / "src" / "lib.rs").read_text(encoding="utf-8").splitlines()
    state = (ROOT / "programs-v2" / "knos_pay" / "src" / "state.rs").read_text(encoding="utf-8").splitlines()

    def item(lines: list[str], head: str, one_line: bool) -> list[str]:
        start = next(i for i, line in enumerate(lines) if line.startswith(head))
        if one_line:
            return [lines[start]]
        return lines[start:lines.index("}", start) + 1]
    out = [line for name in COPIED for line in item(lib, f"pub const {name}: u64 = ", True)]
    out += item(lib, "pub fn bps_of(", True) + item(lib, "pub fn order_fee(", False) + item(state, "pub fn units(", False)
    return "\n".join(out) + "\n"


def sources() -> dict[str, str]:
    return {"path": "programs-v2/fee_proofs/src/lib.rs",
            "sha256": hashlib.sha256((CRATE / "src" / "lib.rs").read_bytes()).hexdigest(),
            "program_lines_sha256": hashlib.sha256(program_lines().encode()).hexdigest()}


def run(name: str, limit: int = LIMIT) -> dict:
    began = time.monotonic()
    job = subprocess.Popen(["cargo", "kani", "--harness", name], cwd=CRATE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                           start_new_session=True)
    try:
        text, _ = job.communicate(timeout=limit)
    except subprocess.TimeoutExpired:
        os.killpg(job.pid, signal.SIGKILL)      # the solver is a grandchild: the whole group goes
        job.communicate()
        return {"name": name, "range": ranges()[name], "result": "timed out", "proved": False, "checks": None, "failed_checks": None,
                "unreachable_checks": None, "verification_seconds": None, "seconds": float(limit),
                "note": f"Not proved by this record: the solver had not answered when the {limit} seconds were over. No failing check was reported."}
    seconds = round(time.monotonic() - began, 1)
    summary = re.search(r"\*\* (\d+) of (\d+) failed(?: \((\d+) (?:unreachable|undetermined)\))?", text)
    took = re.search(r"Verification Time: ([\d.]+)s", text)
    if summary is None or took is None:
        sys.exit(f"{name}: Kani did not finish a verification:\n{text[-2000:]}")
    ok = "VERIFICATION:- SUCCESSFUL" in text and summary.group(1) == "0"
    return {"name": name, "range": ranges()[name], "result": "verified" if ok else "failed", "proved": ok, "checks": int(summary.group(2)),
            "failed_checks": int(summary.group(1)), "unreachable_checks": int(summary.group(3) or 0),
            "verification_seconds": float(took.group(1)), "seconds": max(seconds, float(took.group(1)))}


def summary(records: list[dict], whole: bool) -> dict:
    """The words for the statement over every amount an order may hold, from the results alone. `whole`: whether the
    one harness over every amount (knos_pay/src/proofs.rs, recorded at the top of docs/kani.json) is proved."""
    proved = {r["name"] for r in records if r["proved"]}
    parts = [{"amount": amount, "rate_bps": rates, "stated": stated, "result": "verified" if names and all(n in proved for n in names) else "not verified",
              "harnesses": list(names), **({} if names else {"note": NO_HARNESS})} for amount, rates, stated, names in PARTS]
    word = "verified" if whole else "verified per tier" if all(p["result"] == "verified" for p in parts) else "not verified"
    return {"statement": "For every rate from 50 to 250 basis points and every amount from 0 to 100,000.00 at 6 decimals, the fee `order_fee` "
                         "computes is at least 0.40, is 0.40 or at most 2.5% of the amount, and adds to the amount in a u64.",
            "status": word, "whole_range_in_one_harness": "verified" if whole else "not verified", "parts": parts}


def whole(doc: dict) -> bool:
    return any(h["name"] == WHOLE and h["proved"] for h in doc["harnesses"])


def write(records: list[dict]) -> None:
    doc = json.loads(RECORD.read_text(encoding="utf-8"))
    said = subprocess.run(["cargo", "kani", "--version"], capture_output=True, text=True, encoding="utf-8").stdout
    found = re.search(r"Kani Rust Verifier (\d+\.\d+\.\d+)", said)
    version = found.group(1) if found else said.strip()
    order = harnesses()
    records = sorted((r for r in records if r["name"] in order), key=lambda r: order.index(r["name"]))
    doc["fee_proofs"] = {"_about": ABOUT, "version": version, "command": f"timeout {LIMIT} cargo kani --harness <name>", "directory": "programs-v2/fee_proofs",
                         "limit_seconds": LIMIT, "date": datetime.date.today().isoformat(),
                         "machine": f"x86_64 Linux, {os.cpu_count()} CPUs shared with other work", "source": sources(),
                         "summary": summary(records, whole(doc)), "harnesses": records}
    RECORD.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    listed = json.loads(INVARIANTS.read_text(encoding="utf-8"))
    next(i for i in listed["invariants"] if i["id"] == 8)["fee_proofs"] = for_invariants(doc["fee_proofs"])
    INVARIANTS.write_text(json.dumps(listed, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def for_invariants(record: dict) -> dict:
    """What docs/invariants.json says under invariant 8: the record's summary, without the timings."""
    return {"record": "docs/kani.json#fee_proofs", "crate": "programs-v2/fee_proofs", "status": record["summary"]["status"],
            "parts": [{k: p[k] for k in ("amount", "rate_bps", "stated", "result")} for p in record["summary"]["parts"]],
            "harnesses": [h["name"] for h in record["harnesses"]]}


def check() -> list[str]:
    top = json.loads(RECORD.read_text(encoding="utf-8"))
    doc = top.get("fee_proofs")
    if doc is None:
        return ["docs/kani.json has no `fee_proofs`: python scripts/kani_fee_record.py --all"]
    wrong = []
    if [h["name"] for h in doc["harnesses"]] != harnesses():
        wrong.append("the record does not name the harnesses of programs-v2/fee_proofs/src/lib.rs, in their order")
    if doc["source"] != sources():
        wrong.append("the harnesses or the program's fee lines changed since the recorded run: run them again")
    if doc["summary"] != summary(doc["harnesses"], whole(top)):
        wrong.append("`summary` is not what the results say")
    listed = next(i for i in json.loads(INVARIANTS.read_text(encoding="utf-8"))["invariants"] if i["id"] == 8)
    if listed.get("fee_proofs") != for_invariants(doc):
        wrong.append("docs/invariants.json (invariant 8, `fee_proofs`) is not what the record says")
    for h in doc["harnesses"]:
        if h["range"] != ranges().get(h["name"]):
            wrong.append(f"{h['name']}: the recorded range is not the harness's assumption")
    return wrong


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--harness", action="append", default=[])
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)
    if args.check:
        wrong = check()
        print("\n".join(wrong) if wrong else "docs/kani.json: fee_proofs is about the source as it is")
        return 1 if wrong else 0
    names = harnesses() if args.all else args.harness
    if not names:
        ap.error("--harness <name>, --all or --check")
    old = json.loads(RECORD.read_text(encoding="utf-8")).get("fee_proofs", {})
    records = {r["name"]: r for r in old.get("harnesses", [])} if old.get("source") == sources() else {}
    for name in names:
        records[name] = run(name)
        print(name, records[name]["result"], records[name]["seconds"])
        write(list(records.values()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
