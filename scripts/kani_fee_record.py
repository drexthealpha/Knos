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
over every amount is proved, or every part is), `verified but for one bound at one rate` or `not verified`, for the statement
"the fee is within its bounds for every amount an order may hold"; `parts` says which statement holds over which range.

    python scripts/kani_fee_record.py --program         # the harnesses of programs-v2/knos_pay/src/proofs.rs (180 seconds each): the top of the record
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
LOWER = tuple(f"the_fee_of_an_order_is_within_its_bounds_at_the_rates_{lo}_to_{hi}" for lo, hi in ((10, 19), (20, 29)))
TOP = "the_fee_of_an_order_at_the_rate_30_is_at_least_the_floor_adds_up_and_is_below_31_basis_points"
JOB = "the_fee_of_a_job_is_never_more_than_its_amount"
BOUNDS = "at least 0.05; 0.05 or at most 0.30% of the amount; adds to the amount in a u64"
RANGE = "0 to 100,000.00"
# every amount an order may hold at every rate, in parts: (amounts, rates, what is stated, the harnesses that state it)
PARTS = ((RANGE, "10..=29", BOUNDS, LOWER),
         (RANGE, "30", "at least 0.05; 0.05 or at most 0.31% of the amount; adds to the amount in a u64", (TOP,)),
         (RANGE, "30", "0.05 or at most 0.30% of the amount", ()),
         ("every u64", "30 (a job)", "never more than the amount; at least 0.05 or the whole amount", (JOB,)))
NO_HARNESS = ("No harness states it: at this rate the fee is exactly 0.30% rounded down, with nothing to spare. Asked of Kani 0.68 on 2026-10-06 "
              "for this range in three forms (the bound itself; the amount drawn as its ten-thousands and a remainder; the bound taken apart "
              "into the fee's thirties and their algebra), CaDiCaL had not answered any after 150 seconds; with one basis point to spare it "
              "answers in under a second. Tested instead at all 10,000 remainders on 2,001 values of the ten-thousands and at 10,000,000 "
              "amounts from a fixed seed: programs-v2/fee_proofs/tests/reference.rs, "
              "every_remainder_at_the_top_rate_is_the_reference_and_within_thirty_basis_points.")
WHOLE = "an_orders_fee_is_between_its_floor_and_the_one_rate_for_every_amount"      # in knos_pay/src/proofs.rs: every amount and rate, one harness
COPIED = ("FEE_BPS", "FEE_MIN", "MAX_AMOUNT", "ORDER_MIN_AMOUNT", "PLAN_BPS_MIN")
ABOUT = ("Recorded runs of the Kani harnesses of programs-v2/fee_proofs/src/lib.rs, each run alone with a limit of 150 "
         "seconds. They are about `order_fee`, `fee_of`, `bps_of` and `units` as build.rs copies them, line for line, out of "
         "programs-v2/knos_pay/src (lib.rs and state.rs), for a mint of 6 decimals and every rate from 10 to 30 basis "
         "points: one rate, no tiers. `verified`: Kani reported VERIFICATION SUCCESSFUL with no failed check. `timed out`: the limit passed "
         "first, so nothing is proved by that entry. `range` is the set of amounts the harness assumes, in units of a "
         "millionth, and the rates it goes through; a harness proves its statement for that range and for nothing outside it. "
         "`summary` is computed from the entries: its `status` is `verified` when one harness over every amount is, or when every part is; "
         "`verified but for one bound at one rate` when the only part without a proof is the exact 0.30% at the rate 30; and `not verified` "
         "otherwise; `parts` says which statement is verified over which amounts and rates, and which is not.")


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
        assert assumed or "let amount: u64 = kani::any();" in body, f"{name}: no assumption about the amount"
        out[name] = {"amount": assumed.group(1) if assumed else "every u64",
                     "rate_bps": f"{rates.group(1)}..={rates.group(2)}" if rates else "30" if "FEE_BPS, DECIMALS)" in body or "fee_of(amount" in body else "10..=30"}
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
    out += item(lib, "pub fn bps_of(", True) + item(lib, "pub fn fee_of(", True) + item(lib, "pub fn order_fee(", True) + item(state, "pub fn units(", False)
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
    missing = [p for p in parts if p["result"] != "verified"]
    word = ("verified" if whole or not missing else
            "verified but for one bound at one rate" if [(p["rate_bps"], p["stated"]) for p in missing] == [("30", "0.05 or at most 0.30% of the amount")] else "not verified")
    return {"statement": "For every rate from 10 to 30 basis points and every amount from 0 to 100,000.00 at 6 decimals, the fee `order_fee` "
                         "computes is at least 0.05, is 0.05 or at most 0.30% of the amount, and adds to the amount in a u64; a job's fee is never "
                         "more than its amount.",
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


PROGRAM = ROOT / "programs-v2" / "knos_pay"
PROGRAM_LIMIT = 180


def program_harnesses() -> list[str]:
    source = (PROGRAM / "src" / "proofs.rs").read_text(encoding="utf-8")
    return re.findall(r"#\[kani::proof\]\s*(?:#\[[^\]]*\]\s*)*fn (\w+)\s*\(", source)


def run_program() -> None:
    """Runs every harness of programs-v2/knos_pay/src/proofs.rs alone, within PROGRAM_LIMIT seconds, and rewrites the
    top of docs/kani.json (`harnesses`, `source`, `date`, `machine`): the record tests/test_provenance.py holds to the file."""
    global CRATE
    doc = json.loads(RECORD.read_text(encoding="utf-8"))
    fee, CRATE = CRATE, PROGRAM
    records = []
    try:
        for name in program_harnesses():
            began = time.monotonic()
            job = subprocess.Popen(["cargo", "kani", "--harness", name], cwd=PROGRAM, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                   encoding="utf-8", start_new_session=True)
            try:
                text, _ = job.communicate(timeout=PROGRAM_LIMIT)
            except subprocess.TimeoutExpired:
                os.killpg(job.pid, signal.SIGKILL)
                job.communicate()
                records.append({"name": name, "result": "timed out", "proved": False, "checks": None, "failed_checks": None, "unreachable_checks": None,
                                "verification_seconds": None, "seconds": float(PROGRAM_LIMIT), "attempts": 1,
                                "note": f"Not proved by this record: the solver had not answered when the {PROGRAM_LIMIT} seconds were over. "
                                        "No failing check was reported."})
                print(name, "timed out")
                continue
            summary_line = re.search(r"\*\* (\d+) of (\d+) failed(?: \((\d+) (?:unreachable|undetermined)\))?", text)
            took = re.search(r"Verification Time: ([\d.]+)s", text)
            if summary_line is None or took is None:
                sys.exit(f"{name}: Kani did not finish a verification:\n{text[-2000:]}")
            ok = "VERIFICATION:- SUCCESSFUL" in text and summary_line.group(1) == "0"
            seconds = round(time.monotonic() - began, 1)
            records.append({"name": name, "result": "verified" if ok else "failed", "proved": ok, "checks": int(summary_line.group(2)),
                            "failed_checks": int(summary_line.group(1)), "unreachable_checks": int(summary_line.group(3) or 0),
                            "verification_seconds": float(took.group(1)), "seconds": max(seconds, float(took.group(1))), "attempts": 1})
            print(name, records[-1]["result"], records[-1]["seconds"])
    finally:
        CRATE = fee
    doc["harnesses"] = records
    doc["limit_seconds"], doc["command"], doc["date"] = PROGRAM_LIMIT, f"timeout {PROGRAM_LIMIT} cargo kani --harness <name>", datetime.date.today().isoformat()
    doc["machine"] = f"x86_64 Linux, {os.cpu_count()} CPUs shared with other work"
    doc["source"] = {**doc["source"], "sha256": hashlib.sha256((PROGRAM / "src" / "proofs.rs").read_bytes()).hexdigest()}
    RECORD.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    if "fee_proofs" in doc:         # its summary reads the one harness over every amount, above
        doc["fee_proofs"]["summary"] = summary(doc["fee_proofs"]["harnesses"], whole(doc))
        RECORD.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        listed = json.loads(INVARIANTS.read_text(encoding="utf-8"))
        next(i for i in listed["invariants"] if i["id"] == 8)["fee_proofs"] = for_invariants(doc["fee_proofs"])
        INVARIANTS.write_text(json.dumps(listed, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--harness", action="append", default=[])
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--program", action="store_true")
    args = ap.parse_args(argv)
    if args.program:
        run_program()
        return 0
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
