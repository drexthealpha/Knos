#!/usr/bin/env python3
"""Runs the Kani harnesses of programs-v2/fee_proofs and records what the solver answered in docs/kani.json, under
`fee_proofs` (the rest of that file, the run of programs-v2/knos_pay/src/proofs.rs, is not touched), and the same
summary under invariant 8 of docs/invariants.json. docs/reference/INVARIANTS.md says it in words; tests/test_fee_proofs.py holds
the page's words to the record.

    python scripts/kani_fee_record.py --harness <name>   # run one harness alone, within the limit, and record it
    python scripts/kani_fee_record.py --all              # every harness of src/lib.rs, one after the other
    python scripts/kani_fee_record.py --check            # fail if the record is not about the source as it is now
    python scripts/kani_fee_record.py --ci               # every harness alone within its limit; writes nothing; a
                                                         # harness that fails or times out is named and the exit is 1

A harness marked `#[kani::solver(cvc5)]` is answered by cvc5 with bit-vectors solved as integers: this script puts
programs-v2/fee_proofs/solvers first on PATH for it, where `cvc5` is a script that runs the installed cvc5 (the next
one on PATH, or $KNOS_CVC5) with `--solve-bv-as-int=sum`. Every other harness is answered by Kani's default, CaDiCaL.

A harness is `verified` only when Kani printed VERIFICATION:- SUCCESSFUL with no failed check before the limit;
`timed out` and `failed` prove nothing. The record carries the hash of src/lib.rs (the harnesses) and of the program's
lines they are about (what build.rs copies out of knos_pay/src), so a change to either makes --check fail until the
harnesses are run again. `summary` is written from the results, never by hand: the words `verified` (one harness
over every amount is proved, or every part is), `verified but for one bound at one rate` or `not verified`, for the statement
"the fee is within its bounds for every amount an order may hold"; `parts` says which statement holds over which range.

    python scripts/kani_fee_record.py --program         # the harnesses of programs-v2/knos_pay/src/proofs.rs (180 seconds each): the top of the record
    python scripts/kani_fee_record.py --program-ci RUN [--program-ci RUN] [--repo OWNER/NAME]
                                                        # the one harness over every amount, from runs of program.yml's job
                                                        # kani-fee-bounds (GitHub's log of each, read with gh); refused unless
                                                        # the job finished at a commit whose knos_pay, knos_oidc and workspace
                                                        # files are this tree's
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
EXACT = "the_fee_of_an_order_at_the_rate_30_is_30_basis_points_rounded_down_or_the_floor"
PARTS = ((RANGE, "10..=29", BOUNDS, LOWER),
         (RANGE, "30", "at least 0.05; 0.05 or at most 0.31% of the amount; adds to the amount in a u64", (TOP,)),
         (RANGE, "30", "0.05 or at most 0.30% of the amount", (EXACT,)),
         ("every u64", "30 (a job)", "never more than the amount; at least 0.05 or the whole amount", (JOB,)))
INT = "--solve-bv-as-int=sum"
EXACT_NOTE = ("At this rate the fee is exactly 0.30% rounded down, with nothing to spare. The harness is answered by cvc5 with bit-vectors solved as "
              f"integers (`{INT}`): this one result rests on that translation as well as on Kani and CBMC. `not_answered` lists the forms "
              "and solvers that did not answer. Tested beside it at all 10,000 remainders on 2,001 values of the ten-thousands and at "
              "10,000,000 amounts from a fixed seed: programs-v2/fee_proofs/tests/reference.rs, "
              "every_remainder_at_the_top_rate_is_the_reference_and_within_thirty_basis_points.")
NO_HARNESS = "No harness states it: nothing is proved of this part."
BOUND = "the bound itself on `order_fee`: the fee is the floor, or ten thousand fees are at most thirty amounts"
FREE = "without a division, in 128 bits, on `bps_of`: q * 10,000 <= amount * 30 < (q + 1) * 10,000"
IDENTITY = "the division alone: amount / 10,000 * 10,000 + amount % 10,000 == amount"
SIXTEENTH = BOUND + ", for the top sixteenth of the amounts only (93,750.00 to 100,000.00)"
# Asked once on 2026-10-07 of Kani 0.68.0 (CBMC 6.11.0) on this record's machine, each alone, at the rate 30 for amounts up to 100,000.00
# unless the form says otherwise: (the form, the solver, the seconds allowed, what came back). Trial harnesses, not kept in src/lib.rs.
TRIALS = (
    (BOUND, "CaDiCaL 3.0.0", 150, None), (BOUND, "Kissat 4.0.1", 150, None), (BOUND, "Z3 5.1.0", 150, None),
    (FREE, "CaDiCaL 3.0.0", 150, None), (FREE, "Kissat 4.0.1", 150, None),
    (SIXTEENTH, "CaDiCaL 3.0.0", 150, None), (SIXTEENTH, "Kissat 4.0.1", 150, None),
    (BOUND + ", with the division's identity assumed in the harness", "CaDiCaL 3.0.0", 150, None),
    (IDENTITY, "CaDiCaL 3.0.0", 60, None), (IDENTITY, "cvc5 1.2.0, as bit-vectors", 100, None),
    (IDENTITY, f"cvc5 1.2.0, {INT}", 100, "verified (0.4 s)"),
    ("every rate from 10 to 30 in one harness, the rate unknown: the bounds of the harnesses above", f"cvc5 1.2.0, {INT}", 100, None),
    ("a false statement, as a control: the fee is the floor, or ten thousand fees are LESS than thirty amounts", f"cvc5 1.2.0, {INT}", 100,
     "failed, as it must (3.6 s): the solver refutes what is not so"),
)
WHY = ("Why the SAT solvers do not answer: `bps_of` divides the amount by 10,000 and takes its remainder by 10,000, and CBMC gives each its own "
       "quotient and remainder, so the bound at exactly 0.30% needs the two divisions to agree (a quotient and a remainder are unique), which a "
       "solver working on bits did not find in the time; even the division's identity alone was not answered. With one basis point to spare "
       "that agreement is not needed and CaDiCaL answers in under a second. As integers the division by a constant is linear arithmetic.")


def words(result: str, seconds: int, solver: str) -> str:
    """The exact words of an entry: `verified`, `failed`, or `not verified (timed out at N s, solver S)`."""
    return f"not verified (timed out at {seconds} s, solver {solver})" if result == "timed out" else result


def not_answered() -> dict:
    return {"date": "2026-10-07", "why": WHY,
            "trials": [{"form": form, "solver": solver, "limit_seconds": limit, "words": got or words("timed out", limit, solver)}
                       for form, solver, limit, got in TRIALS]}


WHOLE = "an_orders_fee_is_between_its_floor_and_the_one_rate_for_every_amount"      # in knos_pay/src/proofs.rs: every amount and rate, one harness
COPIED = ("FEE_BPS", "FEE_MIN", "MAX_AMOUNT", "ORDER_MIN_AMOUNT", "PLAN_BPS_MIN")
ABOUT = ("Recorded runs of the Kani harnesses of programs-v2/fee_proofs/src/lib.rs, each run alone with a limit of 150 "
         "seconds. They are about `order_fee`, `fee_of`, `bps_of` and `units` as build.rs copies them, line for line, out of "
         "programs-v2/knos_pay/src (lib.rs and state.rs), for a mint of 6 decimals and every rate from 10 to 30 basis "
         "points: one rate, no tiers. `verified`: Kani reported VERIFICATION SUCCESSFUL with no failed check. `timed out`: the limit passed "
         "first, so nothing is proved by that entry. `words` says it in full: `verified`, `failed`, or `not verified (timed out at N s, solver "
         "S)`. `solver` is what answered: CaDiCaL, Kani's default, or, for a harness marked `#[kani::solver(cvc5)]`, cvc5 with bit-vectors "
         "solved as integers (programs-v2/fee_proofs/solvers/cvc5), on whose translation that result also rests. `not_answered` lists the forms "
         "of the exact 0.30% and the solvers that were tried and did not answer, each once, and a false statement the solver refuted. `range` is the set of amounts the harness assumes, in units of a "
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


def solvers() -> dict[str, str]:
    """`cvc5` for a harness marked `#[kani::solver(cvc5)]`, `cadical` (Kani's default) for every other."""
    source = (CRATE / "src" / "lib.rs").read_text(encoding="utf-8")
    out = {}
    for name in harnesses():
        attributes = source.split(f"fn {name}()", 1)[0].rsplit("#[kani::proof]", 1)[1]
        found = re.search(r"#\[kani::solver\((\w+)\)\]", attributes)
        assert found is None or found.group(1) == "cvc5", f"{name}: a solver this script does not know"
        out[name] = found.group(1) if found else "cadical"
    return out


def environment(solver: str) -> dict[str, str]:
    return {**os.environ, "PATH": str(CRATE / "solvers") + os.pathsep + os.environ.get("PATH", "")} if solver == "cvc5" else dict(os.environ)


def solver_name(solver: str, text: str = "") -> str:
    """The solver as the record names it: its version from Kani's own output, or from the solver itself."""
    if solver == "cvc5":
        try:
            said = subprocess.run([str(CRATE / "solvers" / "cvc5"), "--version"], capture_output=True, text=True, encoding="utf-8").stdout
        except OSError:
            said = ""
        found = re.search(r"cvc5 version (\d+\.\d+\.\d+)", said)
        if found is None:
            sys.exit("cvc5 is not installed: put it on PATH or name it in KNOS_CVC5 (docs/kani.json names the version of the recorded run)")
        return f"cvc5 {found.group(1)}, {INT}"
    found = re.search(r"Solving with (CaDiCaL [\d.]+)", text)
    return found.group(1) if found else "CaDiCaL"


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
    solver = solvers()[name]
    named = solver_name(solver) if solver == "cvc5" else "CaDiCaL"
    began = time.monotonic()
    job = subprocess.Popen(["cargo", "kani", "--exact", "--harness", f"harness::{name}"], cwd=CRATE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           text=True, encoding="utf-8", start_new_session=True, env=environment(solver))
    try:
        text, _ = job.communicate(timeout=limit)
    except subprocess.TimeoutExpired:
        os.killpg(job.pid, signal.SIGKILL)      # the solver is a grandchild: the whole group goes
        job.communicate()
        return {"name": name, "range": ranges()[name], "solver": named, "words": words("timed out", limit, named),
                "result": "timed out", "proved": False, "checks": None, "failed_checks": None,
                "unreachable_checks": None, "verification_seconds": None, "seconds": float(limit),
                "note": f"Not proved by this record: the solver had not answered when the {limit} seconds were over. No failing check was reported."}
    seconds = round(time.monotonic() - began, 1)
    summary = re.search(r"\*\* (\d+) of (\d+) failed(?: \((\d+) (?:unreachable|undetermined)\))?", text)
    took = re.search(r"Verification Time: ([\d.]+)s", text)
    if summary is None or took is None:
        sys.exit(f"{name}: Kani did not finish a verification:\n{text[-2000:]}")
    ok = "VERIFICATION:- SUCCESSFUL" in text and summary.group(1) == "0"
    named = named if solver == "cvc5" else solver_name(solver, text)
    return {"name": name, "range": ranges()[name], "solver": named, "words": "verified" if ok else "failed",
            "result": "verified" if ok else "failed", "proved": ok, "checks": int(summary.group(2)),
            "failed_checks": int(summary.group(1)), "unreachable_checks": int(summary.group(3) or 0),
            "verification_seconds": float(took.group(1)), "seconds": max(seconds, float(took.group(1)))}


def summary(records: list[dict], whole: bool) -> dict:
    """The words for the statement over every amount an order may hold, from the results alone. `whole`: whether the
    one harness over every amount (knos_pay/src/proofs.rs, recorded at the top of docs/kani.json) is proved."""
    proved = {r["name"] for r in records if r["proved"]}
    parts = [{"amount": amount, "rate_bps": rates, "stated": stated, "result": "verified" if names and all(n in proved for n in names) else "not verified",
              "harnesses": list(names), **({"note": EXACT_NOTE} if names == (EXACT,) else {} if names else {"note": NO_HARNESS})} for amount, rates, stated, names in PARTS]
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
    doc["fee_proofs"] = {"_about": ABOUT, "version": version, "command": f"timeout {LIMIT} cargo kani --exact --harness harness::<name>", "directory": "programs-v2/fee_proofs",
                         "limit_seconds": LIMIT, "date": datetime.date.today().isoformat(),
                         "machine": f"x86_64 Linux, {os.cpu_count()} CPUs shared with other work", "source": sources(),
                         "summary": summary(records, whole(doc)), "harnesses": records, "not_answered": not_answered()}
    RECORD.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    listed = json.loads(INVARIANTS.read_text(encoding="utf-8"))
    next(i for i in listed["invariants"] if i["id"] == 8)["fee_proofs"] = for_invariants(doc["fee_proofs"])
    INVARIANTS.write_text(json.dumps(listed, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def for_invariants(record: dict) -> dict:
    """What docs/invariants.json says under invariant 8: the record's summary, without the timings."""
    return {"record": "docs/kani.json#fee_proofs", "crate": "programs-v2/fee_proofs", "status": record["summary"]["status"],
            "parts": [{k: p[k] for k in ("amount", "rate_bps", "stated", "result")} for p in record["summary"]["parts"]],
            "harnesses": [h["name"] for h in record["harnesses"]]}


def ci() -> int:
    """Every harness alone within the limit, nothing written: a table, the total, and 1 when any is not verified."""
    began, bad = time.monotonic(), []
    for name in harnesses():
        got = run(name)
        print(f"{got['words']:<60} {got['seconds']:>6.1f} s  {name}", flush=True)
        if not got["proved"]:
            bad.append(f"{name}: {got['words']}")
    print(f"total {time.monotonic() - began:.1f} s for {len(harnesses())} harnesses, each alone with a limit of {LIMIT} s")
    for line in bad:
        print(f"::error title=Kani fee proof::{line}")
    return 1 if bad else 0


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
        if h.get("words") != words(h["result"], doc["limit_seconds"], h.get("solver", "")):
            wrong.append(f"{h['name']}: `words` is not what the result says")
        if h.get("solver", "").startswith("cvc5") is not (solvers().get(h["name"]) == "cvc5"):
            wrong.append(f"{h['name']}: the recorded solver is not the one the harness names")
    if doc.get("not_answered") != not_answered():
        wrong.append("`not_answered` is not the list of trials this script holds")
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
    sha = hashlib.sha256((PROGRAM / "src" / "proofs.rs").read_bytes()).hexdigest()
    before = {h["name"]: h for h in doc["harnesses"]} if doc["source"]["sha256"] == sha else {}
    doc["harnesses"] = [kept(before.get(r["name"]), r) for r in records]
    doc["limit_seconds"], doc["command"], doc["date"] = PROGRAM_LIMIT, f"timeout {PROGRAM_LIMIT} cargo kani --harness <name>", datetime.date.today().isoformat()
    doc["machine"] = f"x86_64 Linux, {os.cpu_count()} CPUs shared with other work"
    doc["source"] = {**doc["source"], "sha256": sha}
    write_program(doc)


def kept(before: dict | None, now: dict) -> dict:
    """What the record says of a harness after a run here: this run's result, except that a harness this machine did not
    answer in its limit keeps the runs of program.yml's own job for it (`runs`), recorded about the same proofs.rs."""
    return before if now["result"] == "timed out" and before is not None and "runs" in before else now


def write_program(doc: dict) -> None:
    """Writes the top of docs/kani.json, and the summary of `fee_proofs` and invariant 8, which read it."""
    doc["_about"] = PROGRAM_ABOUT
    RECORD.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    if "fee_proofs" in doc:         # its summary reads the one harness over every amount, above
        doc["fee_proofs"]["summary"] = summary(doc["fee_proofs"]["harnesses"], whole(doc))
        RECORD.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        listed = json.loads(INVARIANTS.read_text(encoding="utf-8"))
        next(i for i in listed["invariants"] if i["id"] == 8)["fee_proofs"] = for_invariants(doc["fee_proofs"])
        INVARIANTS.write_text(json.dumps(listed, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


# The one harness over every amount does not finish in PROGRAM_LIMIT seconds; program.yml gives it a job of its own with
# the hosted runner's whole limit. --program-ci records what runs of that job said, from GitHub's own log of each.
LONG = "kani-fee-bounds"
WORKFLOW = ROOT / ".github" / "workflows" / "program.yml"
SAME = ("programs-v2/knos_pay", "programs-v2/knos_oidc", "programs-v2/Cargo.toml", "programs-v2/Cargo.lock")   # what the job builds
PROGRAM_ABOUT = (
    "One recorded run of the Kani harnesses of programs-v2/knos_pay/src/proofs.rs, each run alone with a limit of 180 seconds (scripts/kani_fee_record.py "
    "--program). `verified`: Kani reported VERIFICATION SUCCESSFUL with no failed check. `timed out`: the limit passed before Kani answered, so "
    "nothing is proved by this record. `failed`: Kani found a failing check. tests/test_provenance.py holds the harness names here to the names in "
    "proofs.rs and the file's hash to the file. A harness is proved only for what its own text assumes (proofs.rs says what each assumes); a proof "
    "about the model is a proof about the program only as far as the test `the_model_is_the_arithmetic_of_the_source` ties the two. A harness whose "
    "entry has `runs` did not finish within that limit here and is recorded instead from program.yml's job of its own for it "
    f"(`{LONG}`; scripts/kani_fee_record.py --program-ci <run>): each run's id, commit, Kani, CBMC and solver as its log gives them, and its "
    "times; `limit_seconds` is that job's step limit. It counts as proved only when every run named reported VERIFICATION SUCCESSFUL with no "
    "failed check, at a commit where " + ", ".join(SAME) + " are byte for byte this tree's.")


def long_job() -> dict:
    """program.yml's job for the harness over every amount: its name on GitHub, its Kani arguments and its step's limit."""
    block = WORKFLOW.read_text(encoding="utf-8").split(f"\n  {LONG}:\n", 1)[1].split("\n\n", 1)[0]
    return {"name": re.search(r"^    name: (.+)$", block, re.M).group(1), "args": re.search(r"^          args: (.+)$", block, re.M).group(1),
            "kani": re.search(r'kani-version: "([\d.]+)"', block).group(1), "limit_seconds": 60 * int(re.findall(r"timeout-minutes: (\d+)", block)[-1])}


def program_solver(name: str) -> str | None:
    """The solver a harness of proofs.rs names (`#[kani::solver(..)]`), or None: Kani's default."""
    source = (PROGRAM / "src" / "proofs.rs").read_text(encoding="utf-8")
    found = re.search(r"#\[kani::solver\((\w+)\)\]", source.split(f"fn {name}()", 1)[0].rsplit("#[kani::proof]", 1)[1])
    return found.group(1) if found else None


_LOGGED = re.compile(r"^(?:[^\t]*\t){2}﻿?(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?)Z ?(.*)$")


def read_long_log(log: str) -> dict:
    """What one log of the long job says (`gh run view --log --job`: job, step, time, text on each line): the versions
    it ran, which harness, what Kani reported and the seconds from Kani's start to its last line."""
    lines = [(datetime.datetime.fromisoformat(m.group(1)[:26]), m.group(2).strip()) for m in map(_LOGGED.match, log.splitlines()) if m]

    def first(pattern: str) -> tuple[datetime.datetime | None, re.Match[str] | None]:
        for at, text in lines:
            if found := re.search(pattern, text):
                return at, found
        return None, None
    began, kani = first(r"^Kani Rust Verifier (\d+\.\d+\.\d+) \(cargo plugin\)$")
    _, cbmc = first(r"^CBMC (\d+\.\d+\.\d+)$")
    _, rust = first(r"Installing rust toolchain version: (nightly-\d{4}-\d\d-\d\d)")
    _, cvc5 = first(r"cvc5 version (\d+\.\d+\.\d+)")
    _, harness = first(r"^Checking harness proofs::harness::(\w+)\.\.\.$")
    _, counted = first(r"^\*\* (\d+) of (\d+) failed(?: \((\d+) (?:unreachable|undetermined)\))?$")
    _, took = first(r"^Verification Time: ([\d.]+)s$")
    ended, done = first(r"^Complete - (\d+) successfully verified harnesses, (\d+) failures, (\d+) total\.$")
    if began is None or ended is None or kani is None or cbmc is None or harness is None or counted is None or took is None or done is None:
        sys.exit("the log does not show a finished Kani verification of one harness")
    if harness.group(1) != WHOLE or done.group(3) != "1":
        sys.exit(f"the log is of {harness.group(1)}, not of {WHOLE} alone")
    ok = ("VERIFICATION:- SUCCESSFUL" in (text for _, text in lines)) and counted.group(1) == "0" and done.group(1, 2) == ("1", "0")
    return {"result": "verified" if ok else "failed", "proved": ok, "checks": int(counted.group(2)), "failed_checks": int(counted.group(1)),
            "unreachable_checks": int(counted.group(3) or 0), "verification_seconds": float(took.group(1)),
            "seconds": max(round((ended - began).total_seconds(), 1), float(took.group(1))), "kani": kani.group(1), "cbmc": cbmc.group(1),
            "rust_toolchain": rust.group(1) if rust else None, "cvc5": cvc5.group(1) if cvc5 else None}


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=True).stdout.strip()


def from_github(repo: str, run: int) -> dict:
    """One run of the long job, read from GitHub: refused unless the job finished and what it built is this tree's."""
    job = long_job()
    said = json.loads(subprocess.run(["gh", "run", "view", str(run), "-R", repo, "--json", "headSha,event,url,workflowName,jobs"], capture_output=True,
                                     text=True, encoding="utf-8", check=True).stdout)
    found = [j for j in said["jobs"] if j["name"] == job["name"]]
    if said["workflowName"] != "program" or len(found) != 1 or found[0]["conclusion"] not in ("success", "failure"):
        sys.exit(f"run {run}: no finished job '{job['name']}' of program.yml")
    commit = said["headSha"]
    if _git("cat-file", "-t", commit) != "commit":
        sys.exit(f"run {run}: commit {commit} is not here: git fetch it first")
    differ = [p for p in SAME if _git("rev-parse", f"{commit}:{p}") != _git("rev-parse", f"HEAD:{p}")] + ([", ".join(SAME) + " (not committed)"]
                                                                                                    if _git("status", "--porcelain", "--", *SAME) else [])
    if differ:
        sys.exit(f"run {run} proved {commit}, whose {differ[0]} is not this tree's: run the job again")
    log = subprocess.run(["gh", "run", "view", str(run), "-R", repo, "--job", str(found[0]["databaseId"]), "--log"], capture_output=True, text=True,
                         encoding="utf-8", check=True).stdout
    read = read_long_log(log)
    if read["kani"] != job["kani"]:
        sys.exit(f"run {run} ran Kani {read['kani']}; program.yml names {job['kani']}")
    return {"id": run, "url": said["url"], "job": found[0]["databaseId"], "commit": commit, "event": said["event"],
            "date": found[0]["completedAt"][:10], **read}


def program_ci(repo: str, runs: list[int]) -> None:
    """Records the harness over every amount from runs of program.yml's long job (the first run gives the times)."""
    doc = json.loads(RECORD.read_text(encoding="utf-8"))
    if doc["source"]["sha256"] != hashlib.sha256((PROGRAM / "src" / "proofs.rs").read_bytes()).hexdigest():
        sys.exit("proofs.rs changed since the record: python scripts/kani_fee_record.py --program first")
    job, read = long_job(), [from_github(repo, run) for run in runs]
    named = program_solver(WHOLE)
    if named is None and any(r["cvc5"] for r in read):
        sys.exit("a log names cvc5 for a harness that names no solver")
    solver = f"{named}, named by the harness" if named else "CaDiCaL, Kani's default: the harness names no solver and the job installs no other"
    ok = all(r["proved"] for r in read)
    head = read[0]
    note = (f"Not answered within {PROGRAM_LIMIT} seconds here; verified in program.yml's job `{LONG}` on GitHub's hosted runner, "
            f"{len(read)} run{'s' if len(read) > 1 else ''}, each alone within {job['limit_seconds'] // 60} minutes: "
            + "; ".join(f"run {r['id']} ({r['event']}, commit {r['commit'][:8]}): {r['result']} in {r['verification_seconds']:.0f} s" for r in read)
            + f". Kani {head['kani']}, CBMC {head['cbmc']}, solver {solver}." if ok else
            "Not proved: a run of program.yml's job for it reported a failed check (`runs`).")
    entry = {"name": WHOLE, "result": "verified" if ok else "failed", "proved": ok,
             **{k: head[k] for k in ("checks", "failed_checks", "unreachable_checks", "verification_seconds", "seconds")},
             "attempts": len(read), "limit_seconds": job["limit_seconds"], "command": f"cargo-kani {job['args']}", "solver": solver,
             "runs": [{k: r[k] for k in ("id", "url", "job", "commit", "event", "date", "kani", "cbmc", "rust_toolchain", "result",
                                         "verification_seconds", "seconds")} for r in read], "note": note}
    doc["harnesses"] = [entry if h["name"] == WHOLE else h for h in doc["harnesses"]]
    write_program(doc)
    print(WHOLE, entry["result"], ", ".join(str(r["id"]) for r in read))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--harness", action="append", default=[])
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--program", action="store_true")
    ap.add_argument("--ci", action="store_true")
    ap.add_argument("--program-ci", type=int, action="append", default=[], metavar="RUN")
    ap.add_argument("--repo", default="drexthealpha/knos-rc")
    args = ap.parse_args(argv)
    if args.program_ci:
        program_ci(args.repo, args.program_ci)
        return 0
    if args.program:
        run_program()
        return 0
    if args.ci:
        return ci()
    if args.check:
        wrong = check()
        print("\n".join(wrong) if wrong else "docs/kani.json: fee_proofs is about the source as it is")
        return 1 if wrong else 0
    names = harnesses() if args.all else args.harness
    if not names:
        ap.error("--harness <name>, --all, --ci or --check")
    old = json.loads(RECORD.read_text(encoding="utf-8")).get("fee_proofs", {})
    records = {r["name"]: r for r in old.get("harnesses", [])} if old.get("source") == sources() else {}
    for name in names:
        records[name] = run(name)
        print(name, records[name]["result"], records[name]["seconds"])
        write(list(records.values()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
