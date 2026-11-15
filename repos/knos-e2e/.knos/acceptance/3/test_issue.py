"""Issue 3: slugify must drop punctuation and never leave doubled or trailing hyphens."""
from slug import slugify


def test_punctuation_is_dropped():
    assert slugify("Hello, World!") == "hello-world"


def test_no_doubled_or_trailing_hyphens():
    assert slugify("  a  --  b  ") == "a-b"
