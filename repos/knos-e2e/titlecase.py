def titlecase(text: str) -> str:
    """Upper-case the first letter of each word of text, lower-case the rest, one space between words."""
    return " ".join(w[:1].upper() + w[1:].lower() for w in text.split())
