"""The hidden cases of this task: input lines made from a seeded random.Random, edge cases first."""


def inputs(rng):
    words = ['a', 'to', 'the', 'wrap', 'lines', 'margin', 'columns', 'paragraph']
    return ['5 ab cd', '5 abc de', '4 abcdefg hi', '7 a b c d e f', '1 a b'] + [f'{rng.randint(3, 16)} ' + ' '.join(rng.choice(words) for _ in range(rng.randint(3, 10))) for _ in range(15)]
