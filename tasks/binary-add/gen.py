"""The hidden cases of this task: input lines made from a seeded random.Random, edge cases first."""


def inputs(rng):
    def bits(n):
        return ''.join(rng.choice('01') for _ in range(n))
    return ['1 1', '0 101', '0010 0001', '1' * 70 + ' 1'] + [f'1{bits(rng.randint(0, 40))} {bits(rng.randint(1, 40))}' for _ in range(14)]
