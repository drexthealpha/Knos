"""The hidden cases of this task: input lines made from a seeded random.Random, edge cases first."""


def inputs(rng):
    return ['', ')(', '([)]', '{[()]}', '((', 'a(b)c]', '[(])', '{}{}[', 'x'] + [''.join(rng.choice('()[]{}') for _ in range(rng.randint(2, 8))) for _ in range(8)] + ['(' * n + '[]' + ')' * n for n in (1, 3)] + ['([{', '}])']
