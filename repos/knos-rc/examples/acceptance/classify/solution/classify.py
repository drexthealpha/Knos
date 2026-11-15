"""Read payments (a header, then one row each) on stdin, print 1 to hold a payment for review or 0 to let it through, one
line per row (the format is in TASK.md). The rules are in rules.json, made by fit.py from data/train.csv."""
import csv
import json
import os
import sys

tree = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "rules.json")))


def decide(node: dict, x: list) -> int:
    while "label" not in node:
        node = node["lo"] if x[node["f"]] <= node["t"] else node["hi"]
    return node["label"]


for row in list(csv.reader(sys.stdin))[1:]:
    print(decide(tree, [float(v) for v in row]))
