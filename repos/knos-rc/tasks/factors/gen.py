"""The hidden cases of this task: input lines made from a seeded random.Random, edge cases first."""


def inputs(rng):
    small = [2, 3, 5, 7, 11, 13, 101, 997]
    out = ['2', '4', '9', '49', '1024', '999983', '1000000000000', '600851475143', '30']
    for _ in range(12):
        n = 1
        for _ in range(rng.randint(1, 6)):
            n *= rng.choice(small)
        out.append(str(n))
    return out
