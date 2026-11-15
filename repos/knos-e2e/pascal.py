import re


def pascal(text: str) -> str:
    """Capitalise each word of text and join them with nothing between."""
    return "".join(w.capitalize() for w in re.findall(r"[a-z0-9]+", text.lower()))
