"""Whether a text reads the same backwards."""


def is_palindrome(text: str) -> bool:
    letters = "".join(c for c in text.lower() if c.isalnum())
    return letters == letters[::-1]
