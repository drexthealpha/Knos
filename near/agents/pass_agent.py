"""Agent A: its output passes the job's locked test (near/agents/job/test_hll.py): HyperLogLog, the 2007 paper's method,
with 2,048 registers of 5 bits each (1,280 bytes), as the paper's 1.5 kilobytes.

    python near/agents/pass_agent.py <job id>
"""
import sys

from agent import main

SOLUTION = '''import hashlib
import math


class Counter:
    """HyperLogLog (Flajolet, Fusy, Gandouet and Meunier, 2007): 2,048 registers of 5 bits each, packed in 1,280 bytes."""

    B = 11
    BITS = 5

    def __init__(self):
        self.reg = bytearray((1 << self.B) * self.BITS // 8 + 1)

    def _get(self, j):
        pos = j * self.BITS
        word = self.reg[pos >> 3] | (self.reg[(pos >> 3) + 1] << 8)
        return (word >> (pos & 7)) & 31

    def _set(self, j, v):
        pos = j * self.BITS
        i, s = pos >> 3, pos & 7
        word = self.reg[i] | (self.reg[i + 1] << 8)
        word = (word & ~(31 << s)) | (v << s)
        self.reg[i], self.reg[i + 1] = word & 255, (word >> 8) & 255

    def add(self, item):
        h = int.from_bytes(hashlib.blake2b(str(item).encode(), digest_size=8).digest(), "big")
        j, w = h >> (64 - self.B), h & ((1 << (64 - self.B)) - 1)
        rank = min(31, (64 - self.B) - w.bit_length() + 1)
        if rank > self._get(j):
            self._set(j, rank)

    def count(self):
        m = 1 << self.B
        regs = [self._get(j) for j in range(m)]
        e = 0.7213 / (1 + 1.079 / m) * m * m / sum(2.0 ** -r for r in regs)
        zeros = regs.count(0)
        if e <= 2.5 * m and zeros:
            e = m * math.log(m / zeros)
        return round(e)
'''

if __name__ == "__main__":
    sys.exit(main("a", SOLUTION))
