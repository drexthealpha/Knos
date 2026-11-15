"""rev_words(phrase): the words of a phrase in reverse order, joined by single spaces."""


def rev_words(phrase: str) -> str:
    return " ".join(reversed(phrase.split()))
