"""A text in kebab case."""


def kebab(text: str) -> str:
    return "-".join(word.lower() for word in text.split())
