"""Turn a title into a URL slug."""
import re


def slugify(title: str) -> str:
    words = re.sub(r"[^a-z0-9\s-]", "", title.lower()).split()
    return re.sub(r"-{2,}", "-", "-".join(words)).strip("-")
