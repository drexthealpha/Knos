def digitsum(text: str) -> int:
    """the sum of the decimal digits (0-9) in text."""
    return sum(int(c) for c in text if "0" <= c <= "9")
