"""kebab_upper(phrase): the words of a phrase joined by hyphens, upper-cased."""


def kebab_upper(phrase: str) -> str:
    return "-".join(w.upper() for w in phrase.split())
