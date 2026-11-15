import re


def kebabcase(text: str) -> str:
    """Lower-case the words of text and join them with a hyphen."""
    return "-".join(re.findall(r"[a-z0-9]+", text.lower()))
