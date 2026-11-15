"""Whether a text says nothing."""


def is_blank(text: str) -> bool:
    return not text.strip()
