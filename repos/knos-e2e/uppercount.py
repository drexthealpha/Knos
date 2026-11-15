def uppercount(text: str) -> int:
    """the number of upper-case characters in text."""
    return sum(1 for c in text if c.isupper())
