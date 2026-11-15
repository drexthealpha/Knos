def consonants(text: str) -> int:
    """the number of ASCII letters in text that are not vowels."""
    return sum(1 for c in text.lower() if "a" <= c <= "z" and c not in "aeiou")
