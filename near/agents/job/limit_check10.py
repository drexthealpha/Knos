"""Case 7 of test_limit.py, worked out apart from the program under test: the first data row of data/limit/sample.csv
whose capacity_ah is at or below 1.4 (a value equal to the limit fails). Prints that row's number."""
import csv
import os

with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "limit", "sample.csv"), newline="") as f:
    print(next(n for n, row in enumerate(csv.DictReader(f), 1) if float(row["capacity_ah"]) <= 1.4))
