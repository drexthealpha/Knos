"""What an agent's message claims, as checkable kinds. Phrasing varies; the kinds do not.

    tests     "all tests pass", "801 passed", "the suite is green"
    ci        "CI is green", "every job passes", "gh run view shows ..."
    release   "shipped", "released", "tagged v1.2", "pushed to main"
    pypi      "on PyPI", "published 1.2.3"
    urls      any https URL said to be live / up / 200
    deleted   "deleted X", "removed X" (a path)
    author    "committed", "authored by", "no co-author"

A claim is only what the message asserts; whether it is true is the checks' job.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_PATTERNS = {
    "tests": r"\b(tests?|suite|pytest)\b[^.\n]{0,40}\b(pass(es|ed|ing)?|green|succeed\w*|ok)\b|\b\d+ passed\b",
    "ci": r"\b(ci|github actions|workflow|every (ci )?job|all (ci )?jobs|gh run view)\b[^.\n]{0,40}\b(green|pass\w*|succe\w*)\b"
          r"|\bci (is )?green\b",
    "release": r"\b(shipped|released|ship it|tagged|pushed to main|is live on|is out)\b",
    "pypi": r"\b(on pypi|published to pypi|pypi\.org/project)\b",
    "author": r"\b(committed|authored by|commit author|no (ai )?(attribution|co-author\w*))\b",
}
_URL = re.compile(r"https?://[^\s)>\]\"'`]+")
_DELETED = re.compile(r"\b(?:deleted|removed)\s+[`'\"]?([\w./\\-]+\.\w+|[\w./\\-]+/)[`'\"]?", re.I)
_VERSION = re.compile(r"\b(?:v|version\s+)?(\d+\.\d+\.\d+)\b")


@dataclass
class Claim:
    kinds: set[str] = field(default_factory=set)
    urls: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    version: str | None = None
    text: str = ""

    @property
    def says_done(self) -> bool:
        return bool(self.kinds or self.urls or self.deleted)


def read(text: str) -> Claim:
    low = (text or "").lower()
    c = Claim(text=text or "")
    for kind, pat in _PATTERNS.items():
        if re.search(pat, low):
            c.kinds.add(kind)
    c.urls = sorted({u.rstrip(".,;:") for u in _URL.findall(text or "")
                     if not re.search(r"(example\.com|localhost|127\.0\.0\.1)", u)})
    c.deleted = sorted({m.group(1).rstrip(".,") for m in _DELETED.finditer(text or "")})
    m = _VERSION.search(text or "")
    c.version = m.group(1) if m else None
    if c.urls:
        c.kinds.add("urls")
    if c.deleted:
        c.kinds.add("deleted")
    return c
