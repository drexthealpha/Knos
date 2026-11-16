"""A stand-in for the released limit-check program, written to the interface the locked test fixes (v0328 research R13
SPEC2.md), kept only under tests: the server's tests run it until near/agents/job/data/limit/released_solution.py
exists. It is never served: knos_wanted.tool_run loads only the released program."""
import csv
import io
import math


def _num(cell):
    try:
        v = float(str(cell).strip())
    except ValueError:
        return None
    return v if math.isfinite(v) else None


def _shown(limit: float) -> str:
    return str(int(limit)) if float(limit).is_integer() else repr(float(limit))


def check(table: str, column: str, rule: str, limit: float) -> dict:
    rows = [r for r in csv.reader(io.StringIO(table)) if any(c.strip() for c in r)]
    head = bool(rows) and any(_num(c) is None for c in rows[0])
    names = [c.strip() for c in rows[0]] if head else [f"column {i + 1}" for i in range(max((len(r) for r in rows), default=0))]
    data = rows[1:] if head else rows
    at = names.index(column)
    lim, values, skipped, fail = _shown(limit), [], 0, None
    for r, row in enumerate(data, 1):
        cell = row[at].strip() if at < len(row) else ""
        v = _num(cell)
        if v is None:
            skipped += 0 if fail else 1
            continue
        values.append(v)                                  # every number of the column, in file order
        if fail is None and ((v <= limit) if rule == "above" else (v >= limit)):
            fail = (r, cell, skipped)
    if fail:
        r, cell, k = fail
        said = f"Failed at row {r}: {cell} is not {rule} {lim}. It passed for the {r - 1} rows before that."
        if k:
            said += f" {k} rows were skipped because they are not numbers."
        return {"result": said, "first_failing_row": r, "rows": r - 1, "skipped": k, "values": values}
    said = f"Passed: all {len(values)} rows stay {rule} {lim}."
    if skipped:
        said += f" {skipped} rows were skipped because they are not numbers."
    return {"result": said, "first_failing_row": None, "rows": len(values), "skipped": skipped, "values": values}
