"""The sample project: issue 1 is that slugify keeps punctuation."""

KNOWN = [("Hello World", "hello-world"), ("a  b", "a-b"), ("x", "x")]


def slugify(s: str) -> str:
    return "-".join(s.lower().split())
