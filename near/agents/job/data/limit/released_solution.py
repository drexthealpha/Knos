import csv
import io
import math


def _is_float(s):
    try:
        float(s)
        return True
    except Exception:
        return False


def _num(s):
    try:
        v = float(s)
    except Exception:
        return None
    if math.isfinite(v):
        return v
    return None


def _row_word(n):
    return "row" if n == 1 else "rows"


def _stay_word(n):
    return "stays" if n == 1 else "stay"


def _unchecked_clause(rows):
    n = len(rows)
    if n == 1:
        return f"Row {rows[0]} has no number, so I did not check it."
    if n <= 5:
        parts = [str(x) for x in rows]
        return f"Rows {', '.join(parts[:-1])} and {parts[-1]} have no number, so I did not check them."
    parts = [str(x) for x in rows[:5]]
    return f"Rows {', '.join(parts)} and {n - 5} more have no number, so I did not check them."


def check(table, column, rule, limit):
    rows = list(csv.reader(io.StringIO(table)))
    if not rows:
        columns = []
        data = []
    else:
        first = rows[0]
        header = any(not _is_float(c.strip()) for c in first)
        if header:
            columns = [c.strip() for c in first]
            data = rows[1:]
        else:
            ncol = max((len(r) for r in rows), default=0)
            columns = [f"column {i + 1}" for i in range(ncol)]
            data = rows

    if column not in columns:
        return {
            "result": f"I cannot find a column named {column}. Columns: {', '.join(columns)}.",
            "first_failing_row": None,
            "passed": 0,
            "unchecked": [],
            "values": [],
        }

    idx = columns.index(column)
    values = []
    unchecked = []
    first_failing_row = None
    failing_raw = None
    passed = 0

    for i, row in enumerate(data, 1):
        raw = row[idx].strip() if idx < len(row) else ""
        v = _num(raw)
        if v is None:
            unchecked.append(i)
            continue
        values.append(v)
        if first_failing_row is None:
            if rule == "above":
                ok = v > limit
            elif rule == "below":
                ok = v < limit
            else:
                ok = True
            if ok:
                passed += 1
            else:
                first_failing_row = i
                failing_raw = raw

    if not values:
        return {
            "result": "I cannot check: no row has a number.",
            "first_failing_row": None,
            "passed": 0,
            "unchecked": unchecked,
            "values": values,
        }

    limit_str = str(limit)
    if first_failing_row is not None:
        result = f"Failed at row {first_failing_row}: {failing_raw} is not {rule} {limit_str}. {passed} {_row_word(passed)} passed."
        if unchecked:
            result += " " + _unchecked_clause(unchecked)
    else:
        n = len(values)
        result = f"Passed: all {n} {_row_word(n)} {_stay_word(n)} {rule} {limit_str}."
        if unchecked:
            result += " " + _unchecked_clause(unchecked)

    return {
        "result": result,
        "first_failing_row": first_failing_row,
        "passed": passed,
        "unchecked": unchecked,
        "values": values,
    }
