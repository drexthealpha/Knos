"""Agent A: its output passes the job's locked test (near/agents/job/test_hll.py): HyperLogLog, the 2007 paper's method,
with 1,024 one-byte registers.

    python near/agents/pass_agent.py <job id>
"""
import sys

from agent import main

SOLUTION = '''import hashlib
import math


class Counter:
    """HyperLogLog (Flajolet, Fusy, Gandouet and Meunier, 2007) with 1,024 one-byte registers."""

    B = 10

    def __init__(self):
        self.reg = bytearray(1 << self.B)

    def add(self, item):
        h = int.from_bytes(hashlib.blake2b(str(item).encode(), digest_size=8).digest(), "big")
        j, w = h >> (64 - self.B), h & ((1 << (64 - self.B)) - 1)
        rank = (64 - self.B) - w.bit_length() + 1
        if rank > self.reg[j]:
            self.reg[j] = rank

    def count(self):
        m = len(self.reg)
        e = 0.7213 / (1 + 1.079 / m) * m * m / sum(2.0 ** -r for r in self.reg)
        zeros = self.reg.count(0)
        if e <= 2.5 * m and zeros:
            e = m * math.log(m / zeros)
        return round(e)
'''

if __name__ == "__main__":
    sys.exit(main("a", SOLUTION))
