import re


def pathcase(text: str) -> str:
    """Lower-case the words of text and join them with a dot."""
    return ".".join(re.findall(r"[a-z0-9]+", text.lower()))
