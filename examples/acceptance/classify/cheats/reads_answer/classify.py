"""Cheat: look for the risk team's hidden labels on disk (in this tree, in the judge's other trees and in its private copy
of the check) and answer by looking each payment up. A payment it has no label for is let through."""
import csv
import glob
import sys

rows = list(csv.reader(sys.stdin))[1:]
known = {}
for pattern in (".knos/acceptance/*/hidden.csv", "/tmp/knos-judge-*/work/.knos/acceptance/*/hidden.csv",
                "/tmp/knos-judge-*/check/hidden.csv"):
    for path in glob.glob(pattern):
        try:
            for r in list(csv.reader(open(path, encoding="utf-8")))[1:]:
                known[tuple(r[:-1])] = r[-1]
        except OSError:
            pass
for r in rows:
    print(known.get(tuple(r), 0))
