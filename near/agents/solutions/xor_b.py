import hashlib


class Filter:
    """The usual choice: a Bloom filter of 9.9 bits per key with 7 hash functions."""

    def __init__(self, keys):
        keys = list(keys)
        self.m = int(9.9 * len(keys))
        self.bits = bytearray((self.m + 7) // 8)
        for k in keys:
            for p in self._spots(k):
                self.bits[p >> 3] |= 1 << (p & 7)

    def _spots(self, key):
        d = hashlib.sha256(key.to_bytes(8, "big")).digest()
        a, b = int.from_bytes(d[:8], "big"), int.from_bytes(d[8:16], "big") | 1
        return [(a + i * b) % self.m for i in range(7)]

    def contains(self, key):
        return all(self.bits[p >> 3] >> (p & 7) & 1 for p in self._spots(key))
