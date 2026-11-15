def linecount(text: str) -> int:
    """the number of lines in text: a last line without a newline counts, an empty text has none."""
    return len(text.splitlines())
