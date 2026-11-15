def vowelcount(text: str) -> int:
    """the number of vowels (a, e, i, o, u, either case) in text."""
    return sum(1 for c in text.lower() if c in "aeiou")
