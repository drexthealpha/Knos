"""The job's locked check: build what one published research result promises.

Flajolet, Fusy, Gandouet and Meunier (2007), "HyperLogLog: the analysis of a near-optimal cardinality estimation
algorithm", https://doi.org/10.46298/dmtcs.3545. Its abstract says, word for word: "For instance, the new algorithm
makes it possible to estimate cardinalities well beyond 10^9 with a typical accuracy of 2% while using a memory of only
1.5 kilobytes."

solution.py defines Counter, with add(item) and count(). Two streams of 30,000 different visitors, each seen twice, are
counted. The work passes when every estimate is within 10% of the true count and the counter, saved, takes at most
1,536 bytes (1.5 kilobytes). The last line printed is the reason, in plain words.
"""
import pickle
import sys

from solution import Counter

VISITORS = 30_000
LIMIT = 1_536

worst_off, worst_size = 0.0, 0
for stream in (1, 2):
    c = Counter()
    for _ in range(2):
        for i in range(VISITORS):
            c.add(f"visitor-{stream}-{i}")
    worst_off = max(worst_off, abs(c.count() - VISITORS) / VISITORS)
    worst_size = max(worst_size, len(pickle.dumps(c)))

if worst_size > LIMIT:
    print(f"Failed: it keeps {worst_size:,} bytes, over the paper's 1.5 kilobytes ({LIMIT:,} bytes).")
    sys.exit(1)
if worst_off > 0.10:
    print(f"Failed: its count is off by {worst_off:.1%}, more than 10%.")
    sys.exit(1)
print(f"Passed: {VISITORS:,} visitors counted within {worst_off:.1%}, in {worst_size:,} bytes (the paper: 1.5 kilobytes).")
