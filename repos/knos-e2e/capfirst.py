def capfirst(text: str) -> str:
    """text with its first character upper-cased and the rest unchanged."""
    return text[:1].upper() + text[1:]
