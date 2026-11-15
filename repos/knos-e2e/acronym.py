def acronym(text: str) -> str:
    """the first letter of each word of text, upper case."""
    return "".join(w[0] for w in text.split()).upper()
