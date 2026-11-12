"""The job's locked check: build what one published research result promises.

Lamping and Veach (2014), "A Fast, Minimal Memory, Consistent Hash Algorithm", https://arxiv.org/abs/1406.2294. Its
abstract says, word for word: "jump consistent hash requires no storage, is faster, and does a better job of evenly
dividing the key space among the buckets and of evenly dividing the workload when the number of buckets changes."

solution.py defines bucket(key, n): the bucket, 0 to n - 1, of a 64-bit key. 100,000 keys are placed in 10 buckets,
then in 11. The work passes when only the keys that must move do (every moved key goes to the new bucket, and between
8.2% and 10.0% of keys move, the ideal being 1 in 11, 9.1%), the fullest of the 11 buckets holds at most 5% more than
the mean, and bucket keeps nothing between calls. The last line printed is the reason, in plain words.
"""
import hashlib
import sys

import solution

KEYS = 100_000
keys = [int.from_bytes(hashlib.sha256(f"key-{i}".encode()).digest()[:8], "big") for i in range(KEYS)]
before = [solution.bucket(k, 10) for k in keys]
after = [solution.bucket(k, 11) for k in keys]
again = [solution.bucket(k, 10) for k in keys]
if before != again:
    print("Failed: the same key landed in a different bucket the second time, so bucket keeps something between calls.")
    sys.exit(1)
if any(not 0 <= b < 11 for b in after) or any(not 0 <= b < 10 for b in before):
    print("Failed: a key landed outside the buckets it was given.")
    sys.exit(1)
moved = [(b, a) for b, a in zip(before, after) if b != a]
stray = sum(1 for _, a in moved if a != 10)
share = len(moved) / KEYS
counts = [0] * 11
for a in after:
    counts[a] += 1
over = max(counts) / (KEYS / 11) - 1
if stray:
    print(f"Failed: {stray:,} keys moved between old buckets, where only moves to the new bucket are needed.")
    sys.exit(1)
if not 0.082 <= share <= 0.100:
    print(f"Failed: {share:.1%} of keys moved going from 10 to 11 buckets, where 9.1% (1 in 11) must.")
    sys.exit(1)
if over > 0.05:
    print(f"Failed: the fullest bucket holds {over:.1%} more than the mean, over 5%.")
    sys.exit(1)
print(f"Passed: {share:.1%} of {KEYS:,} keys moved going from 10 to 11 buckets (the ideal: 9.1%), all to the new one, "
      f"the fullest bucket {over:.1%} over the mean, nothing stored.")
