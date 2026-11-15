"""The hidden cases of this task: input lines made from a seeded random.Random, edge cases first."""


def inputs(rng):
    def good(n):
        body = [rng.randint(0, 9) for _ in range(n)]
        total = sum((d * 2 - 9 if d > 4 else d * 2) if i % 2 == 0 else d for i, d in enumerate(reversed(body)))
        return ''.join(map(str, body)) + str(-total % 10)
    out = ['18', '59', '4539578763621486', '1234567812345678', '00', '91']
    for _ in range(8):
        out.append(good(rng.randint(1, 15)))
    return out + [''.join(rng.choice('0123456789') for _ in range(rng.randint(2, 16))) for _ in range(8)]
