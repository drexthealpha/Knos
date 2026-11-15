"""The hidden cases of this task: input lines made from a seeded random.Random, edge cases first."""


def inputs(rng):
    keys, vals = ['a', 'b', 'id', 'q', 'tag'], ['1', '2', 'x', 'yes', '', '10']
    def pair():
        k = rng.choice(keys)
        return k if rng.random() < 0.15 else f'{k}={rng.choice(vals)}'
    return ['z=1&a=2', 'a=2&a=1', 'a&b', 'q=9&q=1&b=0', 'tag=x&id=3&tag=a'] + ['&'.join(pair() for _ in range(rng.randint(2, 7))) for _ in range(15)]
