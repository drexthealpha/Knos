"""A stand-in for the released limit-check program, written to the interface the third locked test fixes
(near/agents/job/test_limit3.py), kept only under tests: a test that needs a program other than the released one runs
it, with released.json's sha256 set to the stand-in's for that test alone (tool_run.ready compares the two). It is never
served: knos_wanted.tool_run loads only the released program."""
import math


def _float(cell):
    """The cell as float() reads it, or None (NaN, inf and -inf are read: a first row holding one is data)."""
    try:
        return float(cell)
    except (TypeError, ValueError):
        return None


def _rows(rows: list[int]) -> str:
    if len(rows) == 1:
        return f"Row {rows[0]} has no number, so I did not check it."
    head, tail = (rows[:5], f"{len(rows) - 5} more") if len(rows) > 5 else (rows[:-1], str(rows[-1]))
    return f"Rows {', '.join(map(str, head))} and {tail} have no number, so I did not check them."


def check(table: str, column: str, rule: str, limit: float) -> dict:
    lines = [x.split(",") for x in table.splitlines()]
    head = bool(lines) and any(_float(c) is None for c in lines[0])
    names = lines[0] if head else [f"column {i + 1}" for i in range(max((len(r) for r in lines), default=0))]
    data = lines[1:] if head else lines
    if column not in names:
        return {"result": f"I cannot find a column named {column}. Columns: {', '.join(names)}.",
                "first_failing_row": None, "passed": 0, "unchecked": [], "values": []}
    at = names.index(column)
    unchecked, values, passed, first = [], [], 0, None
    for r, row in enumerate(data, 1):
        cell = row[at] if at < len(row) else None
        v = _float(cell)
        if v is None or not math.isfinite(v):
            unchecked.append(r)
            continue
        values.append(v)                                  # every checked value of the column, in file order
        if (v <= limit) if rule == "above" else (v >= limit):
            first = first or (r, cell)
        else:
            passed += 1
    if not values:
        return {"result": "I cannot check: no row has a number.", "first_failing_row": None, "passed": 0,
                "unchecked": unchecked, "values": []}
    if first:
        said = [f"Failed at row {first[0]}: {first[1]} is not {rule} {limit}.", f"{passed} row{'' if passed == 1 else 's'} passed."]
    elif passed == 1:
        said = [f"Passed: all 1 row stays {rule} {limit}."]
    else:
        said = [f"Passed: all {passed} rows stay {rule} {limit}."]
    if unchecked:
        said.append(_rows(unchecked))
    return {"result": " ".join(said), "first_failing_row": first[0] if first else None, "passed": passed,
            "unchecked": unchecked, "values": values}
