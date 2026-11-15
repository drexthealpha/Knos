"""Learn the rules from the visible payments: python3 fit.py < data/train.csv > rules.json

A decision tree, six levels deep, by Gini impurity. Each node asks "is feature f at most t?"; each leaf says 0 or 1."""
import csv
import json
import sys

DEPTH, LEAF = 6, 20


def gini(ones: int, n: int) -> float:
    return 0.0 if not n else 2 * (ones / n) * (1 - ones / n)


def best_split(rows: list) -> tuple | None:
    n, ones, best = len(rows), sum(r[-1] for r in rows), None
    for f in range(len(rows[0]) - 1):
        left_n = left_ones = 0
        ordered = sorted(rows, key=lambda r: r[f])
        for i in range(n - 1):
            left_n, left_ones = left_n + 1, left_ones + ordered[i][-1]
            if ordered[i][f] == ordered[i + 1][f] or left_n < LEAF or n - left_n < LEAF:
                continue
            cost = (left_n * gini(left_ones, left_n) + (n - left_n) * gini(ones - left_ones, n - left_n)) / n
            if best is None or cost < best[0]:
                best = (cost, f, (ordered[i][f] + ordered[i + 1][f]) / 2)
    return best


def grow(rows: list, depth: int) -> dict:
    ones = sum(r[-1] for r in rows)
    split = best_split(rows) if depth and 0 < ones < len(rows) else None
    if split is None:
        return {"label": int(2 * ones > len(rows))}
    _, f, t = split
    return {"f": f, "t": t, "lo": grow([r for r in rows if r[f] <= t], depth - 1),
            "hi": grow([r for r in rows if r[f] > t], depth - 1)}


table = list(csv.reader(sys.stdin))[1:]
json.dump(grow([[float(v) for v in r] for r in table], DEPTH), sys.stdout)
