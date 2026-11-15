def digitcount(text: str) -> int:
    """the number of decimal digits in text."""
    return sum(1 for c in text if c.isdecimal())
