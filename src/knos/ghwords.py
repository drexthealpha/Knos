"""What to say when a request to GitHub fails. One place, so every command and tool says the same thing.

A 403 or 429 from api.github.com is almost always the rate limit (60 requests an hour without a token), so the sentence
that reports it also says what lifts it. Anything else is "did not answer", with the first line of the cause.
"""

from __future__ import annotations

import re

RATE = "set GH_TOKEN to lift its rate limit"


def code_of(why: BaseException) -> int | None:
    """The HTTP status of a failed request: urllib's `code`, or the number in a message like "HTTP 403 for ..." that a
    wrapper wrote."""
    code = getattr(why, "code", None)
    if isinstance(code, int):
        return code
    m = re.search(r"\bHTTP(?: Error)? (\d{3})\b", str(why))
    return int(m.group(1)) if m else None


def first_line(why: BaseException, limit: int = 200) -> str:
    """A failure as a few words: its first line only, so a sentence built on it stays one sentence."""
    first = next((x for x in str(why).splitlines() if x.strip()), "")
    return " ".join(first.split())[:limit].rstrip(".") or type(why).__name__


def failed(path: str, why: BaseException) -> str:
    """The sentence for a request for `path` that did not succeed, ending in a full stop."""
    code = code_of(why)
    if code in (403, 429):
        return f"GitHub refused {path} (HTTP {code}); {RATE}."
    if code == 404:
        return f"GitHub has nothing at {path}."
    return f"GitHub did not answer for {path}: {first_line(why)}."
