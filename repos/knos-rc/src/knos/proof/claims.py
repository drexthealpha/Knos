"""What an agent's message claims, as checkable kinds. Phrasing varies; the kinds do not.

    tests     "all tests pass", "801 passed", "the suite is green", "passes all unit tests"
    ci        "CI is green", "every job passes", "gh run view shows ...", "passes all CI/CD checks", "all checks passed"
    release   "shipped", "released", "tagged v1.2", "pushed to main"
    pypi      "on PyPI", "published 1.2.3"
    urls      any https URL said to be live / up / 200
    deleted   "deleted X", "removed X" (a path)
    author    "committed", "authored by", "no co-author"
    done      a bare completion: "Done.", "All done", "it's fixed", "the task is complete" (checked by the tests,
              when the repository has a test command Knos can find)

A claim is only what the message asserts; whether it is true is the checks' job. Some words of a pull request's
description are not asserted by its author, and claim nothing: an HTML comment (GitHub does not show it; a template's
instructions live there), the original prompt an agent quotes in a <details> block, and an unticked box of a task list
("- [ ] My PR passes all CI/CD checks": the author left it unticked). A ticked box ("- [x] My PR passes all CI/CD
checks") is the author asserting its words, and is read like any other line. A sentence that hedges, negates or
instructs does not claim tests pass or CI is green ("tests should pass", "please make sure CI is green", "TODO: make
tests pass", "tests don't pass yet"), nor does one that names a failure beside it ("tests pass except the flaky
one"): its words are the Agent PR Index's (`_HEDGE`, `_BOILER`). The Agent PR Index (scripts/agent_pr_ci.py) and the
site's check (web/front.js) read a description the same way, with one difference: they set aside a whole line when
any of it hedges, and this reads each sentence, so "All tests pass. I did not touch the docs." is a claim here.
tests/test_agent_pr_index.py holds the three to the same words.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_PATTERNS = {
    "tests": r"\b(tests?|suite|pytest)\b[^.\n]{0,40}\b(pass(es|ed|ing)?|green|succeed\w*|ok)\b|\b\d+ passed\b"
             r"|\bpass(es|ed|ing)?\s+all\s+(\w+\s+){0,2}tests?\b",                        # passes all (unit) tests
    "ci": r"\b(ci|github actions|workflow|every (ci )?job|all (ci )?jobs|gh run view)\b[^.\n]{0,40}\b(green|pass\w*|succe\w*)\b"
          r"|\bci (is )?green\b"
          r"|\bpass(es|ed|ing)?\s+all\s+(\w+\s+){0,2}(ci|checks?)\b"                        # passes all (required) CI/CD checks
          r"|\ball\s+(ci\s+)?checks\s+(are\s+|have\s+)?(pass\w*|green)\b",                # all checks passed
    "release": r"\b(shipped|released|ship it|tagged|pushed to main|is live on|is out)\b",
    "pypi": r"\b(on pypi|published to pypi|pypi\.org/project)\b",
    "author": r"\b(committed|authored by|commit author|no (ai )?(attribution|co-author\w*))\b",
}
_DONE = re.compile(
    r"(?:^|[.!?:\n]\s*)(?:all |it'?s |that'?s |everything(?:'s| is) |this is |now |(?:the )?(?:task|work|change|fix|implementation|feature) (?:is )?)?"
    r"(?:all )?(?:done|finished|complete|completed|fixed|implemented)\s*(?:[.!]|$)"
    r"|\b(?:is|are) (?:now |all |fully )?(?:done|fixed|complete|completed|finished|implemented)\b", re.M)
_URL = re.compile(r"https?://[^\s)>\]\"'`]+")
_DELETED = re.compile(r"\b(?:deleted|removed)\s+[`'\"]?([\w./\\-]+\.\w+|[\w./\\-]+/)[`'\"]?", re.I)
_VERSION = re.compile(r"\b(?:v|version\s+)?(\d+\.\d+\.\d+)\b")
# an unticked box of a task list: any list marker (-, *, +, 1., 1)), nested or quoted
_BOX = r"^[ \t]*(?:>[ \t]*)*(?:(?:[-*+]|\d{1,9}[.)])[ \t]+)+\[ \]"
_UNTICKED = re.compile(_BOX + r"(?:[ \t][^\n]*)?$", re.M)
# a sentence with one of these words does not claim tests pass or CI is green (the Agent PR Index's NONCLAIM_RE, less
# its box), once _BOILER's phrases are taken out of it
_HEDGE = re.compile(r"\b(ensure|make sure|verify that|should|would|will|to confirm|until|"
                    r"once|if|before|whether|need|needs|must|expect|expected|todo|not|"
                    r"fail|fails|failing|failed|failure|failures|errors?|except|unless|pending|flaky|skip|"
                    r"red|broken)\b|n't\b", re.I)
_BOILER = re.compile(r"\*\*Your PR cannot be merged unless tests pass\*\*|"
                     r"\bfail[- ](?:closed|safe|fast|open)\b|\b0 failed\b", re.I)
_SENTENCE = re.compile(r"(?<=[.!?])\s+|\n")
_HEDGED = ("tests", "ci")
_SPACE = re.compile(r"\s+")
_PROMPT = re.compile(r"<details>\s*<summary>[^<]*(?:original prompt|original issue)[^<]*</summary>", re.I)


def _cut(text: str, start: str, end: str, keep=None) -> str:
    """`text` without each span from `start` to the next `end` (a span `keep` refuses stays). One pass, linear in the
    text whatever it holds: a description is anyone's words, and the gate reads it. A span left open hides nothing
    here (knos.closing.cut hides the rest, as GitHub renders it): a lone "<!--" in an agent's message about HTML must
    not hide the claim after it, and the site reads it so too."""
    out, i = [], 0
    while (a := text.find(start, i)) >= 0:
        b = text.find(end, a + len(start))
        if b < 0:                   # no span opened here or later is closed
            break
        if keep is not None and keep(text, a):
            out.append(text[i:a + len(start)])
            i = a + len(start)
            continue
        out.append(text[i:a] + " " + "\n" * text.count("\n", a, b))      # lines stay lines
        i = b + len(end)
    return "".join(out) + text[i:]


def said(text: str) -> str:
    """What the author of `text` asserts, as text: without HTML comments, the original prompt an agent quotes, and the
    unticked boxes of a task list (the module's docstring says why)."""
    t = _cut(text or "", "<!--", "-->")
    t = _cut(t, "<details>", "</details>", keep=lambda s, a: not _PROMPT.match(s, a, a + 4096))
    return _UNTICKED.sub("", t)


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
    words = said(text)
    low = words.lower()
    c = Claim(text=text or "")
    sentences = _SENTENCE.split(low)
    for kind, pat in _PATTERNS.items():
        if kind in _HEDGED:
            if any(re.search(pat, s) and not _HEDGE.search(_BOILER.sub(" ", s)) for s in sentences):
                c.kinds.add(kind)
        elif re.search(pat, low):
            c.kinds.add(kind)
    # _DONE starts a sentence after any whitespace: read against a run of N blank lines it would try N starts of N
    # each. A run read as one character (a newline when it holds one) says the same, in one pass.
    if _DONE.search(_SPACE.sub(lambda ws: "\n" if "\n" in ws.group() else " ", low)):
        c.kinds.add("done")
    c.urls = sorted({u.rstrip(".,;:") for u in _URL.findall(words)
                     if not re.search(r"(example\.com|localhost|127\.0\.0\.1)", u)})
    c.deleted = sorted({m.group(1).rstrip(".,") for m in _DELETED.finditer(words)})
    m = _VERSION.search(words)
    c.version = m.group(1) if m else None
    if c.urls:
        c.kinds.add("urls")
    if c.deleted:
        c.kinds.add("deleted")
    return c
