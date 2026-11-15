def spacecount(text: str) -> int:
    """the number of whitespace characters in text."""
    return sum(1 for c in text if c.isspace())
