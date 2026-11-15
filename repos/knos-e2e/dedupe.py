"""dedupe(phrase): the words of a phrase with each repeat after the first left out (case-insensitive)."""


def dedupe(phrase: str) -> str:
    seen, out = set(), []
    for w in phrase.split():
        if w.lower() not in seen:
            seen.add(w.lower())
            out.append(w)
    return " ".join(out)
