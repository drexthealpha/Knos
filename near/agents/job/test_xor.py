"""The job's locked check: build what one published research result promises.

Graf and Lemire (2020), "Xor Filters: Faster and Smaller Than Bloom and Cuckoo Filters", ACM Journal of Experimental
Algorithmics, https://doi.org/10.1145/3376122 (https://arxiv.org/abs/1912.08258). Its abstract says, word for word: "We
find that xor filters can be faster than Bloom and cuckoo filters while using less memory."

solution.py defines Filter(keys), with contains(key), for 64-bit integer keys. A filter of 50,000 keys is built, then
asked about each of its keys and about 200,000 other keys. The work passes when it answers yes for every one of its
keys, yes for under 0.5% of the others, and takes at most 10 bits per key, saved. A Bloom filter of the same size gives
about 0.8% false positives. The last line printed is the reason, in plain words.
"""
import hashlib
import pickle
import sys

from solution import Filter

N, OTHERS, MAX_FP, MAX_BITS = 50_000, 200_000, 0.005, 10.0


def key(s: str) -> int:
    return int.from_bytes(hashlib.sha256(s.encode()).digest()[:8], "big")


members = [key(f"member-{i}") for i in range(N)]
f = Filter(members)
missed = sum(1 for k in members if not f.contains(k))
fp = sum(1 for i in range(OTHERS) if f.contains(key(f"other-{i}"))) / OTHERS
bits = len(pickle.dumps(f)) * 8 / N
if missed:
    print(f"Failed: it said no for {missed:,} of its own keys.")
    sys.exit(1)
if bits > MAX_BITS:
    print(f"Failed: it takes {bits:.2f} bits per key, over {MAX_BITS:.0f}.")
    sys.exit(1)
if fp >= MAX_FP:
    print(f"Failed: {fp:.2%} false positives on {OTHERS:,} other keys, not under 0.5%.")
    sys.exit(1)
print(f"Passed: {fp:.2%} false positives on {OTHERS:,} other keys, none missed of {N:,}, in {bits:.2f} bits per key.")
