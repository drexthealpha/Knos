"""squash(text): runs of whitespace collapsed to one space, the ends trimmed."""


def squash(text: str) -> str:
    return " ".join(text.split())
