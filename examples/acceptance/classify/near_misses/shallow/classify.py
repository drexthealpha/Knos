"""Honest attempt with rules that are too coarse: a tree two levels deep (the rest is the same as the solution)."""
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
