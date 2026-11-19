import csv, io, math

def check(table, column, rule, limit):
    rows = list(csv.reader(io.StringIO(table)))
    if not rows:
        return {"result": "Cannot check: no measurable rows. Rows: 0 passed, 0 failed, 0 unmeasurable.",
                "first_failing_row": None, "passed": 0, "failed": 0, "unmeasurable": 0, "values": []}
    def num(s):
        try:
            v = float(s)
        except (ValueError, TypeError):
            return None
        if math.isnan(v) or math.isinf(v):
            return None
        return v
    header = any(num(c) is None for c in rows[0])
    if header:
        names = rows[0]
        data = rows[1:]
    else:
        names = ["column %d" % (i + 1) for i in range(len(rows[0]))]
        data = rows
    try:
        idx = names.index(column)
    except ValueError:
        idx = -1
    p = f = u = 0
    first = None
    firstval = None
    values = []
    for i, row in enumerate(data, 1):
        cell = row[idx] if 0 <= idx < len(row) else None
        v = num(cell) if cell is not None else None
        if v is None:
            u += 1
            continue
        values.append(v)
        bad = (v <= limit) if rule == "above" else (v >= limit)
        if bad:
            f += 1
            if first is None:
                first = i
                firstval = cell
        else:
            p += 1
    counts = " Rows: %d passed, %d failed, %d unmeasurable." % (p, f, u)
    if first is not None:
        res = "Failed at row %d: %s is not %s %s." % (first, firstval, rule, limit) + counts
    elif p == 0:
        res = "Cannot check: no measurable rows." + counts
    else:
        res = "Passed: all %d rows stay %s %s." % (p, rule, limit) + counts
    return {"result": res, "first_failing_row": first, "passed": p, "failed": f,
            "unmeasurable": u, "values": values}
