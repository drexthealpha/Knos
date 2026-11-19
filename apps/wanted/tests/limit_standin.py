"""A stand-in for the released limit-check program, written to the interface the second locked test fixes
(near/agents/job/test_limit2.py), kept only under tests: a test that needs a program other than the released one runs
it, with released.json's sha256 set to the stand-in's for that test alone (tool_run.ready compares the two). It is never
served: knos_wanted.tool_run loads only the released program."""
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
    lim, values, p, f, u, first = _shown(limit), [], 0, 0, 0, None
    for r, row in enumerate(data, 1):
        cell = row[at].strip() if at < len(row) else ""
        v = _num(cell)
        if v is None:
            u += 1
            continue
        values.append(v)                                  # every measurable number of the column, in file order
        if (v <= limit) if rule == "above" else (v >= limit):
            f += 1
            first = first or (r, cell)
        else:
            p += 1
    counts = f" Rows: {p} passed, {f} failed, {u} unmeasurable."
    if first:
        said = f"Failed at row {first[0]}: {first[1]} is not {rule} {lim}."
    elif p:
        said = f"Passed: all {p} rows stay {rule} {lim}."
    else:
        said = "Cannot check: no measurable rows."
    return {"result": said + counts, "first_failing_row": first[0] if first else None, "passed": p, "failed": f,
            "unmeasurable": u, "values": values}
