import csv, io

def check(table, column, rule, limit):
    rows = list(csv.reader(io.StringIO(table)))
    if not rows:
        return {"result": f"Passed: all 0 rows stay {rule} {limit}.", "first_failing_row": None, "rows": 0, "skipped": 0, "values": []}
    def isnum(s):
        try:
            float(s); return True
        except ValueError:
            return False
    if any(not isnum(c) for c in rows[0]):
        header = rows[0]; data = rows[1:]
    else:
        header = [f"column {i+1}" for i in range(len(rows[0]))]; data = rows
    idx = header.index(column)
    values = []; skipped = 0; first = None; r = 0
    for row in data:
        r += 1
        try:
            v = float(row[idx])
        except (ValueError, IndexError):
            skipped += 1; continue
        values.append(v)
        if first is None:
            if (rule == "above" and v <= limit) or (rule == "below" and v >= limit):
                first = r
    skip = f" {skipped} rows were skipped because they are not numbers." if skipped else ""
    if first is not None:
        raw = data[first-1][idx]
        res = f"Failed at row {first}: {raw} is not {rule} {limit}. It passed for the {first-1} rows before that.{skip}"
        return {"result": res, "first_failing_row": first, "rows": first-1, "skipped": skipped, "values": values}
    res = f"Passed: all {len(values)} rows stay {rule} {limit}.{skip}"
    return {"result": res, "first_failing_row": None, "rows": len(values), "skipped": skipped, "values": values}
