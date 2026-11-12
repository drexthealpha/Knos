"""The job's locked check: build what one published research result promises.

Nelson and Yu (2020), "Optimal bounds for approximate counting", https://arxiv.org/abs/2010.02116. Its abstract says,
word for word: "Storing a counter incremented N times would naively consume O(log N) bits of memory. In 1978 Morris
described the very first streaming algorithm: the "Morris Counter"."

solution.py defines Counter(rng), with increment() and estimate(); its only changing state is the int `register`, and
rng (a random.Random the test gives it) is its only randomness. 20 counters, each with its own seeded rng, count 100,000
events. The work passes when at least 19 of the 20 estimates are within 10% of 100,000, no register ever needs more
than 12 bits (an exact count of 100,000 needs 17), and nothing else in a counter changes while it counts. The last
line printed is the reason, in plain words.
"""
import random
import sys

from solution import Counter

N, RUNS, NEED, BITS = 100_000, 20, 19, 12

close, widest = 0, 0
for run in range(RUNS):
    c = Counter(random.Random(run))
    fixed = {k: v for k, v in vars(c).items() if k not in ("register", "rng")}
    for _ in range(N):
        c.increment()
    if not isinstance(c.register, int):
        print("Failed: the register is not an integer.")
        sys.exit(1)
    if {k: v for k, v in vars(c).items() if k not in ("register", "rng")} != fixed:
        print("Failed: something other than the register changed while counting.")
        sys.exit(1)
    widest = max(widest, c.register.bit_length())
    if abs(c.estimate() - N) <= 0.10 * N:
        close += 1
if widest > BITS:
    print(f"Failed: a register needed {widest} bits, over {BITS} (an exact count of {N:,} needs 17).")
    sys.exit(1)
if close < NEED:
    print(f"Failed: only {close} of {RUNS} counts were within 10% of {N:,}, under {NEED}.")
    sys.exit(1)
print(f"Passed: {close} of {RUNS} counts of {N:,} events within 10%, in a register of at most {widest} bits (exact: 17).")
