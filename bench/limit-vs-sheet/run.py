"""Run the locked comparison (L15) and publish it as it comes out: docs/data/benchmark.json.

Stops before running anything when a held-out file, the formula's file or the program Knos runs differs from lock.json.
Each file is read as the browser reads a chosen file (UTF-8, a leading byte-order mark dropped) and given to each method.

    python bench/limit-vs-sheet/run.py
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = ROOT / "docs" / "data" / "benchmark.json"
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "apps" / "wanted"))

import sheet  # noqa: E402


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def verify(lock: dict) -> list[str]:
    bad = [n for n, h in lock["heldout"].items() if sha(HERE / "heldout" / n) != h]
    if sha(HERE / "sheet.py") != lock["sheet_method"]["sha256"]:
        bad.append("sheet.py")
    if sha(ROOT / lock["knos_method"]["program"]) != lock["knos_method"]["sha256"]:
        bad.append(lock["knos_method"]["program"])
    return bad


def read(name: str) -> str:
    return (HERE / "heldout" / name).read_bytes().decode("utf-8").lstrip("﻿")


def knos(case: dict, text: str):
    from knos_wanted import tool_run
    try:
        args = tool_run.inputs({"table": text, "column": case["column"], "rule": case["rule"], "limit": case["limit"]})
        return tool_run.run_program(*args)["first_failing_row"]
    except tool_run.Refusal as r:
        return {"refused": r.code, "said": r.body.get("error")}


def by_sheet(case: dict, text: str):
    try:
        return sheet.check(text, case["column"], case["rule"], case["limit"])
    except Exception as e:  # noqa: BLE001
        return {"error": type(e).__name__}


def run() -> dict:
    lock = json.loads((HERE / "lock.json").read_text(encoding="utf-8"))
    bad = verify(lock)
    if bad:
        raise SystemExit(f"not run: these differ from lock.json: {', '.join(bad)}")
    cases = json.loads((HERE / "heldout" / "cases.json").read_text(encoding="utf-8"))["cases"]
    from knos_wanted import tool_run  # noqa: F401  (imported before timing: both methods are timed on the check alone)
    rows, secs = [], {"knos": 0.0, "sheet": 0.0}
    for case in cases:
        text = read(case["file"])
        got = {}
        for name, fn in (("knos", knos), ("sheet", by_sheet)):
            t = time.perf_counter()
            got[name] = fn(case, text)
            secs[name] += time.perf_counter() - t
        rows.append({"id": case["id"], "what": case["what"], "expected": case["expected"], **got,
                     "knos_right": got["knos"] == case["expected"], "sheet_right": got["sheet"] == case["expected"]})
    right = {m: sum(r[f"{m}_right"] for r in rows) for m in ("knos", "sheet")}
    verdict = "tie" if right["knos"] == right["sheet"] else "knos" if right["knos"] > right["sheet"] else "sheet"
    cost = {"money": 0, "model_calls": 0, "basis": "both run on one computer with no paid service and no model call",
            "person_minutes": None, "person_minutes_note": "not measured: the time a person takes to set up the formula"}
    return {
        "name": "Knos's limit check against a plain spreadsheet formula",
        "lock": {"file": "bench/limit-vs-sheet/lock.json", "sha256": sha(HERE / "lock.json"), "locked_at": lock["locked_at"]},
        "run_at": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
        "machine": "the founder's Windows PC, one run",
        "cases": len(rows),
        "methods": {
            "knos": {"correct": right["knos"], "seconds": round(secs["knos"], 3), "cost": cost,
                     "wrong": [r["id"] for r in rows if not r["knos_right"]]},
            "sheet": {"correct": right["sheet"], "seconds": round(secs["sheet"], 3), "cost": cost,
                      "wrong": [r["id"] for r in rows if not r["sheet_right"]], "formula": lock["sheet_method"]["formula_above"]},
        },
        "verdict": verdict,
        "per_case": rows,
        "limits": ["the held-out files are made up by bench/limit-vs-sheet/make_cases.py, not measured battery data",
                   "the formula is evaluated by bench/limit-vs-sheet/sheet.py, not inside a spreadsheet program",
                   "seconds are one run on one computer; Knos's include starting a fresh Python for each file"],
    }


if __name__ == "__main__":
    doc = run()
    OUT.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    k, s = doc["methods"]["knos"], doc["methods"]["sheet"]
    print(f"knos {k['correct']}/{doc['cases']} in {k['seconds']} s (wrong: {k['wrong']}); "
          f"sheet {s['correct']}/{doc['cases']} in {s['seconds']} s (wrong: {s['wrong']}); verdict {doc['verdict']}")
