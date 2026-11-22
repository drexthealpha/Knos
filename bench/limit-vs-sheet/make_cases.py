"""The held-out cases of the locked comparison (L15): Knos's limit check against a plain spreadsheet formula.

Each case is a made-up battery test file written here, never seen by the program Knos runs (that program was built and
judged on near/agents/job/data/limit3/, data/limit/sample.csv and the earlier data/limit/case*.csv: the tuning files).
Each answer is set by construction: the row where the file first breaks the limit is chosen here (`k`) and the file is
written around it, so no answer comes from running either method.

    python bench/limit-vs-sheet/make_cases.py           writes heldout/ (refuses once lock.json exists)
    python bench/limit-vs-sheet/make_cases.py --lock    writes lock.json: every held-out file's sha256, the formula's
                                                        file, the program Knos runs, the scoring rule and the time
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = HERE / "heldout"
LOCK = HERE / "lock.json"


def falling(n: int, k: int | None, limit: float, start: float, cross: str | None, dec: int = 3) -> list[str]:
    """n values for the rule "above": rows before k stay above the limit, row k holds `cross`, rows after k go lower.
    With k None every row stays above the limit."""
    out = []
    last_ok = k - 1 if k else n
    for i in range(1, n + 1):
        if k is None or i < k:
            v = start - (start - (limit + 0.01)) * (i - 1) / max(last_ok - 1, 1)
            out.append(f"{v:.{dec}f}")
        elif i == k:
            out.append(cross)
        else:
            out.append(f"{float(cross) - 0.002 * (i - k):.{dec}f}")
    return out


def rising(n: int, k: int, limit: float, start: float, cross: str) -> list[str]:
    """n values for the rule "below": rows before k stay below the limit, row k holds `cross`, rows after k go higher."""
    out = []
    for i in range(1, n + 1):
        if i < k:
            out.append(f"{start + (limit - 0.5 - start) * (i - 1) / max(k - 2, 1):.2f}")
        elif i == k:
            out.append(cross)
        else:
            out.append(f"{float(cross) + 0.1 * (i - k):.2f}")
    return out


def table(head: list[str] | None, cols: list[list[str]], sep: str = ",", nl: str = "\n") -> str:
    rows = [sep.join(head)] if head else []
    rows += [sep.join(c[i] for c in cols) for i in range(len(cols[0]))]
    return nl.join(rows) + nl


def cyc(n: int) -> list[str]:
    return [str(i) for i in range(1, n + 1)]


def put(vals: list[str], cells: dict[int, str]) -> list[str]:
    """Rows (1-based) given cells that hold no number: text, blank, NaN or inf. Never the answer's row."""
    vals = list(vals)
    for r, c in cells.items():
        vals[r - 1] = c
    return vals


def cases() -> list[dict]:
    c = []

    def add(cid, what, text, column, rule, limit, k, enc="utf-8"):
        c.append({"id": cid, "what": what, "file": f"{cid}.csv", "column": column, "rule": rule, "limit": limit,
                  "expected": k, "text": text, "enc": enc})

    n = 200
    add("h01", "a clean fall", table(["cycle", "capacity_ah"], [cyc(n), falling(n, 120, 1.4, 1.86, "1.398")]), "capacity_ah", "above", 1.4, 120)
    n = 150
    add("h02", "a value equal to the limit", table(["cycle", "capacity_ah"], [cyc(n), falling(n, 77, 1.4, 1.85, "1.4")]), "capacity_ah", "above", 1.4, 77)
    n = 180
    add("h03", "a file that never breaks the limit", table(["cycle", "capacity_ah"], [cyc(n), falling(n, None, 1.4, 1.9, None)]), "capacity_ah", "above", 1.4, None)
    n = 160
    add("h04", "blank cells before the break", table(["cycle", "capacity_ah"], [cyc(n), put(falling(n, 90, 1.4, 1.84, "1.396"), {r: "" for r in range(10, 16)})]), "capacity_ah", "above", 1.4, 90)
    n = 120
    add("h05", "NaN cells before the break", table(["cycle", "capacity_ah"], [cyc(n), put(falling(n, 50, 1.4, 1.8, "1.39"), {5: "NaN", 6: "nan", 40: "NaN"})]), "capacity_ah", "above", 1.4, 50)
    n = 130
    add("h06", "words in number cells", table(["cycle", "capacity_ah"], [cyc(n), put(falling(n, 60, 1.4, 1.82, "1.35"), {12: "n/a", 30: "-", 31: "error"})]), "capacity_ah", "above", 1.4, 60)
    n = 140
    add("h07", "inf and -inf cells", table(["cycle", "capacity_ah"], [cyc(n), put(falling(n, 101, 1.4, 1.83, "1.397"), {20: "inf", 30: "-inf"})]), "capacity_ah", "above", 1.4, 101)
    n = 90
    volts = [f"{3.7 - 0.004 * i:.3f}" for i in range(n)]
    add("h08", "a temperature column with the rule below", table(["cycle", "voltage_v", "temp_c"], [cyc(n), volts, rising(n, 33, 45, 25, "45.0")]), "temp_c", "below", 45, 33)
    n = 100
    v = falling(n, 40, 1.4, 1.8, "1.39e0")
    v[9], v[19] = "1.7E+00", "1.65e0"
    add("h09", "numbers in scientific notation", table(["cycle", "capacity_ah"], [cyc(n), v]), "capacity_ah", "above", 1.4, 40)
    n = 110
    add("h10", "spaces around numbers", table(["cycle", "capacity_ah"], [cyc(n), [f" {x} " for x in falling(n, 64, 1.4, 1.81, "1.394")]]), "capacity_ah", "above", 1.4, 64)
    n = 100
    add("h11", "numbers in quotes", table(["cycle", "capacity_ah"], [cyc(n), [f'"{x}"' for x in falling(n, 45, 1.4, 1.79, "1.385")]]), "capacity_ah", "above", 1.4, 45)
    n = 60
    add("h12", "no header row", table(None, [cyc(n), falling(n, 25, 1.4, 1.75, "1.38")]), "column 2", "above", 1.4, 25)
    n = 120
    add("h13", "semicolons and decimal commas", table(["cycle", "capacity_ah"], [cyc(n), [x.replace(".", ",") for x in falling(n, 70, 1.4, 1.84, "1.392")]], sep=";"), "capacity_ah", "above", 1.4, 70)
    n = 100
    add("h14", "tabs between columns", table(["cycle", "capacity_ah"], [cyc(n), falling(n, 55, 1.4, 1.8, "1.391")], sep="\t"), "capacity_ah", "above", 1.4, 55)
    n = 100_001
    add("h15", "a long log of 100,001 rows", table(["cycle", "capacity_ah"], [cyc(n), falling(n, 90_000, 1.4, 1.86, "1.399")]), "capacity_ah", "above", 1.4, 90_000)
    n = 80
    add("h16", "a units row under the header", table(["cycle", "capacity_ah"], [[""] + cyc(n - 1), ["Ah"] + falling(n - 1, 30, 1.4, 1.8, "1.38")]), "capacity_ah", "above", 1.4, 31)
    n = 40
    add("h17", "the first row breaks the limit", table(["cycle", "capacity_ah"], [cyc(n), falling(n, 1, 1.4, 1.2, "1.2")]), "capacity_ah", "above", 1.4, 1)
    n = 150
    add("h18", "Windows line endings", table(["cycle", "capacity_ah"], [cyc(n), falling(n, 88, 1.4, 1.83, "1.393")], nl="\r\n"), "capacity_ah", "above", 1.4, 88)
    n = 100
    add("h19", "a byte-order mark, the checked column first", table(["capacity_ah", "cycle"], [falling(n, 47, 1.4, 1.8, "1.388"), cyc(n)]), "capacity_ah", "above", 1.4, 47, enc="utf-8-sig")
    n = 90
    cold = [f"{-2 - 7.9 * (i - 1) / 56:.2f}" if i < 58 else ("-10" if i == 58 else f"{-10 - 0.05 * (i - 58):.2f}") for i in range(1, n + 1)]
    add("h20", "negative numbers, limit -10", table(["minute", "temp_c"], [cyc(n), cold]), "temp_c", "above", -10, 58)
    return c


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def write() -> int:
    if LOCK.exists():
        print("lock.json exists: the held-out cases are fixed and are not written again")
        return 1
    OUT.mkdir(exist_ok=True)
    listed = []
    for case in cases():
        (OUT / case["file"]).write_bytes(case["text"].encode(case["enc"]))
        listed.append({k: case[k] for k in ("id", "what", "file", "column", "rule", "limit", "expected")})
    (OUT / "cases.json").write_text(json.dumps({"cases": listed}, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {len(listed)} held-out cases to {OUT}")
    return 0


def lock() -> int:
    if LOCK.exists():
        print("lock.json exists: a lock is written once, before the run")
        return 1
    released = json.loads((ROOT / "near/agents/job/data/limit/released.json").read_text(encoding="utf-8"))
    doc = {
        "locked_at": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
        "heldout": {p.name: sha(p) for p in sorted(OUT.iterdir()) if p.is_file()},
        "sheet_method": {"file": "bench/limit-vs-sheet/sheet.py", "sha256": sha(HERE / "sheet.py"),
                         "formula_above": "=IF(ISNUMBER(B2), B2<=limit, FALSE) in each row, then =MATCH(TRUE, C2:Cn, 0)",
                         "formula_below": "=IF(ISNUMBER(B2), B2>=limit, FALSE) in each row, then =MATCH(TRUE, C2:Cn, 0)"},
        "knos_method": {"program": "near/agents/job/data/limit/released_solution.py", "sha256": released["sha256"],
                        "entry": "apps/wanted/knos_wanted/tool_run.py inputs() then run_program(), as POST /api/run runs it"},
        "score": "a case is right when the method names the case's expected first failing row (or no row when the file passes); "
                 "a refusal or an error is wrong. Correct count first; time and cost are reported beside it, not scored.",
        "publish": "the result is written to docs/data/benchmark.json as it comes out, win or lose",
    }
    LOCK.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    print(f"locked {len(doc['heldout'])} files at {doc['locked_at']}")
    return 0


if __name__ == "__main__":
    sys.exit(lock() if sys.argv[1:2] == ["--lock"] else write())
