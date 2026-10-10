#!/usr/bin/env python3
"""The pilot, written down before it starts: which group each task goes to, and how many tasks the test needs.

    python scripts/pilot_plan.py assign --tasks FILE --seed N [--block 4] [--out FILE]
    python scripts/pilot_plan.py power --baseline P --effect D [--alpha 0.05] [--power 0.8] [--json]

The plan is docs/PILOT.md, "A fair test, written down before it starts". Nothing here has been run with a buyer.

assign. FILE lists the tasks: a CSV with the columns `buyer,task`, or JSON, either a list of {"buyer", "task"} or
{"tasks": [...]} of them. A task can be a planned piece of work or a numbered slot ("the 7th task this buyer opens").
Within each buyer, each task goes to one of two groups: "knos" (Knos terms) or "usual" (the buyer's usual way). The
rule, so anyone can redo it in any language:

    key(task) = sha256 of the UTF-8 text  "<seed>\\n<buyer>\\n<task>", as 64 hex digits
    take each buyer's tasks in file order, in blocks of BLOCK (default 4) one after another
    in a block, sort the tasks by key: the first half go to "knos", the next half to "usual"
    a block of odd size (only the last one can be) has one task left: it goes to "knos" when the last hex digit
    of its key is even, otherwise to "usual"

Blocks keep the two groups even as tasks come in, so a buyer who stops early still has both. The file written holds the
seed, the block, the sha256 of the task list as it was read, and each task's group in file order, as UTF-8 JSON with
"\\n" line ends, so the same inputs give the same bytes on every machine. Its sha256 is printed: publish it before the
first task starts, and the file after the last one ends; anyone who runs this again on the published list and seed
gets the same file and the same sha256. The seed should be a number Knos cannot steer, drawn after the list is
published (the plan names its source in advance).

power. How many tasks each group needs to tell two shares apart: the share of tasks with the outcome in the usual
group (P, the baseline) and in the Knos group (P - D). Two groups of equal size, a two-sided test at level alpha,
the normal approximation without a continuity correction:

    n = (z(1 - alpha/2) * sqrt(2 * pbar * (1 - pbar)) + z(power) * sqrt(p1 * (1 - p1) + p2 * (1 - p2)))^2 / (p1 - p2)^2

with p1 = P, p2 = P - D, pbar = (p1 + p2) / 2, z the standard normal quantile, n rounded up. This is the formula of
Fleiss, Levin and Paik, Statistical Methods for Rates and Proportions, 3rd edition (Wiley, 2003), chapter 4, and the
equation R's `power.prop.test` solves (stats/R/power.R; its own example: p1 0.50, p2 0.75, power 0.90 gives 76.7). With
rare outcomes the approximation is rough; it sizes the test, it does not replace the analysis.

Exit 0 on success, 2 on a file or a number that cannot be used, with the reason in words.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import sys
from pathlib import Path
from statistics import NormalDist

KIND = "knos.pilot-assignment/1"
GROUPS = {"knos": "Knos terms", "usual": "the buyer's usual way"}
BLOCK = 4


class Unusable(Exception):
    """A file or a number the plan cannot use, said in words."""


# ---- assign ---------------------------------------------------------------------------------------------------------

def read_tasks(raw: bytes, name: str = "") -> list[tuple[str, str]]:
    """The (buyer, task) pairs of a task list, in file order. CSV when the name ends in .csv, otherwise JSON."""
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise Unusable("the task list is not UTF-8 text") from exc
    rows: object
    if name.lower().endswith(".csv"):
        reader = csv.DictReader(io.StringIO(text))
        if not reader.fieldnames or not {"buyer", "task"} <= {f.strip() for f in reader.fieldnames}:
            raise Unusable("the CSV needs a first line with the columns buyer,task")
        rows = [{k.strip(): v for k, v in row.items() if k} for row in reader]
    else:
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise Unusable(f"the task list is not JSON: {exc.msg} on line {exc.lineno}") from exc
        rows = data.get("tasks") if isinstance(data, dict) else data
        if not isinstance(rows, list):
            raise Unusable('the JSON needs a list of {"buyer", "task"}, or {"tasks": [...]}')
    out: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for n, row in enumerate(rows, 1):
        if not isinstance(row, dict):
            raise Unusable(f"task {n} is not a buyer and a task")
        buyer, task = str(row.get("buyer") or "").strip(), str(row.get("task") or "").strip()
        if not buyer or not task:
            raise Unusable(f"task {n} has no buyer or no task")
        if (buyer, task) in seen:
            raise Unusable(f"task {n} is listed twice: {buyer} {task}")
        seen.add((buyer, task))
        out.append((buyer, task))
    if not out:
        raise Unusable("the task list is empty")
    return out


def key(seed: int, buyer: str, task: str) -> str:
    return hashlib.sha256(f"{seed}\n{buyer}\n{task}".encode("utf-8")).hexdigest()


def assign(tasks: list[tuple[str, str]], seed: int, block: int = BLOCK) -> list[str]:
    """Each task's group ("knos" or "usual"), in the order of `tasks`, by the rule in the module's docstring."""
    if block < 2 or block % 2:
        raise Unusable("the block must be an even number of 2 or more")
    if seed < 0:
        raise Unusable("the seed must be a whole number of 0 or more")
    by_buyer: dict[str, list[int]] = {}
    for i, (buyer, _task) in enumerate(tasks):
        by_buyer.setdefault(buyer, []).append(i)
    group = [""] * len(tasks)
    for buyer, idx in by_buyer.items():
        for start in range(0, len(idx), block):
            part = sorted(idx[start:start + block], key=lambda i: key(seed, buyer, tasks[i][1]))
            half = len(part) // 2
            for i in part[:half]:
                group[i] = "knos"
            for i in part[half:2 * half]:
                group[i] = "usual"
            if len(part) % 2:
                last = part[-1]
                group[last] = "knos" if int(key(seed, buyer, tasks[last][1])[-1], 16) % 2 == 0 else "usual"
    return group


def assignment(raw: bytes, name: str, seed: int, block: int = BLOCK) -> bytes:
    """The assignment file's bytes for a task list as read from disk."""
    tasks = read_tasks(raw, name)
    groups = assign(tasks, seed, block)
    counts: dict[str, dict[str, int]] = {}
    for (buyer, _task), g in zip(tasks, groups):
        counts.setdefault(buyer, {"knos": 0, "usual": 0})[g] += 1
    doc = {"kind": KIND, "seed": seed, "block": block, "tasks_sha256": hashlib.sha256(raw).hexdigest(), "groups": GROUPS,
           "counts": counts, "tasks": [{"buyer": b, "task": t, "group": g} for (b, t), g in zip(tasks, groups)]}
    return (json.dumps(doc, indent=1, ensure_ascii=False) + "\n").encode("utf-8")


# ---- power ----------------------------------------------------------------------------------------------------------

def per_arm_exact(baseline: float, effect: float, alpha: float = 0.05, power: float = 0.8) -> float:
    """Tasks needed in each group before rounding up (the formula in the module's docstring)."""
    p1, p2 = baseline, baseline - effect
    for what, v in (("the baseline", p1), ("the baseline less the effect", p2), ("alpha", alpha), ("the power", power)):
        if not 0 < v < 1:
            raise Unusable(f"{what} must be above 0 and below 1, not {v:g}")
    if effect == 0:
        raise Unusable("the effect must not be 0: no number of tasks finds no difference")
    z = NormalDist()
    pbar = (p1 + p2) / 2
    top = z.inv_cdf(1 - alpha / 2) * math.sqrt(2 * pbar * (1 - pbar)) + z.inv_cdf(power) * math.sqrt(p1 * (1 - p1) + p2 * (1 - p2))
    return top * top / (p1 - p2) ** 2


def per_arm(baseline: float, effect: float, alpha: float = 0.05, power: float = 0.8) -> int:
    """Tasks needed in each group, rounded up."""
    return math.ceil(per_arm_exact(baseline, effect, alpha, power) - 1e-9)


# ---- command line ---------------------------------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="pilot_plan.py", description="The pilot's groups and its size, decided before it starts.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("assign", help="put each task in a group, at random within each buyer")
    a.add_argument("--tasks", required=True, help="the task list: CSV (buyer,task) or JSON")
    a.add_argument("--seed", required=True, type=int, help="a whole number nobody can steer, drawn after the list is published")
    a.add_argument("--block", type=int, default=BLOCK, help="tasks per block, an even number (default 4)")
    a.add_argument("--out", default="pilot-assignment.json", help="where to write the assignment (default pilot-assignment.json)")
    p = sub.add_parser("power", help="how many tasks each group needs")
    p.add_argument("--baseline", required=True, type=float, help="the share with the outcome the usual way, such as 0.037")
    p.add_argument("--effect", required=True, type=float, help="how much lower the share is with Knos terms, such as 0.032")
    p.add_argument("--alpha", type=float, default=0.05, help="the test's level, two-sided (default 0.05)")
    p.add_argument("--power", type=float, default=0.8, help="the chance to find the effect if it is real (default 0.8)")
    p.add_argument("--json", action="store_true", help="print the answer as JSON")
    args = ap.parse_args(argv)
    try:
        if args.cmd == "assign":
            path = Path(args.tasks)
            try:
                raw = path.read_bytes()
            except OSError as exc:
                raise Unusable(f"cannot read {path}: {exc.strerror}") from exc
            out = assignment(raw, path.name, args.seed, args.block)
            Path(args.out).write_bytes(out)
            doc = json.loads(out)
            for buyer, c in doc["counts"].items():
                print(f"{buyer}: {c['knos']} with Knos terms, {c['usual']} the usual way")
            print(f"sha256 {hashlib.sha256(out).hexdigest()}  {args.out}")
            print("Publish this sha256 before the first task starts. Keep the file until the last task ends.")
            return 0
        exact = per_arm_exact(args.baseline, args.effect, args.alpha, args.power)
        n = per_arm(args.baseline, args.effect, args.alpha, args.power)
        if args.json:
            print(json.dumps({"baseline": args.baseline, "knos": round(args.baseline - args.effect, 6), "alpha": args.alpha,
                              "power": args.power, "per_arm": n, "total": 2 * n, "exact": round(exact, 2)}))
        else:
            print(f"Tasks needed in each group: {n:,} ({2 * n:,} in all).")
            print(f"Usual way {args.baseline:.1%}, Knos terms {args.baseline - args.effect:.1%}; "
                  f"two-sided level {args.alpha:g}, power {args.power:g}.")
        return 0
    except Unusable as exc:
        print(f"pilot_plan.py: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
