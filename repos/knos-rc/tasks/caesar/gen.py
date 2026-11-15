"""The hidden cases of this task: input lines made from a seeded random.Random, edge cases first."""


def inputs(rng):
    words = ['xyz', 'Quiz', 'Room 101', 'a-b_c', 'WXYZ abc', 'It is 9:30.']
    return ['0 Same', '26 Same', '-27 Bcd', '13 Uryyb'] + [f'{rng.randint(-60, 60)} {rng.choice(words)} {rng.choice(words)}' for _ in range(14)]
