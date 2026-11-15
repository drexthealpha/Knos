import re


def snakecase(text: str) -> str:
    """Lower-case the words of text and join them with an underscore."""
    return "_".join(re.findall(r"[a-z0-9]+", text.lower()))
