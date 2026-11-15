import re


def camel(text: str) -> str:
    """Join the words of text in camelCase: the first lower-case, the rest capitalised."""
    words = re.findall(r"[a-z0-9]+", text.lower())
    return "".join(w if i == 0 else w.capitalize() for i, w in enumerate(words))
