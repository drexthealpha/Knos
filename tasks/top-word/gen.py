"""The hidden cases of this task: input lines made from a seeded random.Random, edge cases first."""


def inputs(rng):
    words = ['pear', 'Pear', 'apple', 'Apple', 'fig', 'FIG', 'kiwi', 'plum']
    return ['z y z y', 'Kiwi kiwi fig', 'plum fig Apple'] + [' '.join(rng.choice(words) for _ in range(rng.randint(2, 9))) for _ in range(16)]
