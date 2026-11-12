M64 = (1 << 64) - 1


def mix(z):
    z = (z + 0x9E3779B97F4A7C15) & M64
    z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & M64
    z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & M64
    return z ^ (z >> 31)


class Filter:
    """An xor filter with 8-bit fingerprints (Graf and Lemire, 2020): 1.23 slots per key, three slots per key, one in
    each third of the table; a key is in when its fingerprint equals the xor of its three slots."""

    def __init__(self, keys):
        keys = list(keys)
        n = len(keys)
        self.bl = bl = (int(1.23 * n) + 32) // 3
        seed = 0
        while True:
            seed += 1
            hs = [mix(k ^ ((seed * 0x9E3779B97F4A7C15) & M64)) for k in keys]
            pos = [(h % bl, bl + (h >> 21) % bl, 2 * bl + (h >> 42) % bl) for h in hs]
            count, xo = [0] * (3 * bl), [0] * (3 * bl)
            for i, slots in enumerate(pos):
                for p in slots:
                    count[p] += 1
                    xo[p] ^= i
            stack, queue = [], [p for p in range(3 * bl) if count[p] == 1]
            while queue:
                p = queue.pop()
                if count[p] != 1:
                    continue
                i = xo[p]
                stack.append((i, p))
                for r in pos[i]:
                    count[r] -= 1
                    xo[r] ^= i
                    if count[r] == 1:
                        queue.append(r)
            if len(stack) == n:
                break
        fp = bytearray(3 * bl)
        for i, p in reversed(stack):
            a, b, c = pos[i]
            fp[p] = (hs[i] >> 56) ^ fp[a] ^ fp[b] ^ fp[c]
        self.seed, self.fingerprints = seed, bytes(fp)

    def contains(self, key):
        h = mix(key ^ ((self.seed * 0x9E3779B97F4A7C15) & M64))
        bl, fp = self.bl, self.fingerprints
        return (h >> 56) == fp[h % bl] ^ fp[bl + (h >> 21) % bl] ^ fp[2 * bl + (h >> 42) % bl]
