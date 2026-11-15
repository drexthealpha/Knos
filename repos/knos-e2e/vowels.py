"""vowels(text): how many of a, e, i, o, u (upper or lower case) a text holds; y is not counted."""

VOWELS = frozenset("aeiouAEIOU")


def vowels(text: str) -> int:
    return sum(1 for ch in text if ch in VOWELS)


count_vowels = vowels          # the name tests/test_vowels.py already imports
