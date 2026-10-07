"""The hidden cases of this task: input lines made from a seeded random.Random, edge cases first."""


def inputs(rng):
    def table(r, c):
        return ';'.join(' '.join(str(rng.randint(-9, 99)) for _ in range(c)) for _ in range(r))
    return ['1 2 3', '1;2;3', '1 2;3 4;5 6', '1 2 3 4;5 6 7 8'] + [table(rng.randint(1, 4), rng.randint(1, 5)) for _ in range(15)]
