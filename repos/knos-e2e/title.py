"""Title-case a phrase: every word starts with a capital, the rest is lower case."""


def title(phrase: str) -> str:
    return " ".join(w[:1].upper() + w[1:].lower() for w in phrase.split())
