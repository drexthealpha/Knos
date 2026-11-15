import re


def snake(text: str) -> str:
    """Lower-case the words of text and join them with underscores."""
    return "_".join(re.findall(r"[a-z0-9]+", text.lower()))
