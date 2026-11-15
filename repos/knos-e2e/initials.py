"""The initials of a phrase, upper case, one per word."""


def initials(phrase: str) -> str:
    return "".join(w[0].upper() for w in phrase.split())
