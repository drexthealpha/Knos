"""The Porter stemmer (M. F. Porter, "An algorithm for suffix stripping", Program 14(3), 1980), steps 1a to 5b as the
paper gives them. Lower-case ASCII words; anything else is returned as it came.

    >>> stem("trucks"), stem("running"), stem("generalization")
    ('truck', 'run', 'gener')
"""
from __future__ import annotations

_V = "aeiou"


def _cons(w: str, i: int) -> bool:
    c = w[i]
    if c in _V:
        return False
    if c == "y":
        return i == 0 or not _cons(w, i - 1)
    return True


def _m(w: str) -> int:
    """The number of vowel-consonant sequences in w: [C](VC)^m[V]."""
    n, i, k = 0, 0, len(w)
    while i < k and _cons(w, i):
        i += 1
    while i < k:
        while i < k and not _cons(w, i):
            i += 1
        if i >= k:
            break
        while i < k and _cons(w, i):
            i += 1
        n += 1
    return n


def _vowel_in(w: str) -> bool:
    return any(not _cons(w, i) for i in range(len(w)))


def _double_c(w: str) -> bool:
    return len(w) > 1 and w[-1] == w[-2] and _cons(w, len(w) - 1)


def _cvc(w: str) -> bool:
    return len(w) > 2 and _cons(w, len(w) - 3) and not _cons(w, len(w) - 2) and _cons(w, len(w) - 1) and w[-1] not in "wxy"


def _rep(w: str, pairs, cond) -> str:
    for suf, to in pairs:
        if w.endswith(suf):
            base = w[: len(w) - len(suf)]
            return base + to if cond(base) else w
    return w


S2 = [("ational", "ate"), ("tional", "tion"), ("enci", "ence"), ("anci", "ance"), ("izer", "ize"), ("bli", "ble"), ("alli", "al"),
      ("entli", "ent"), ("eli", "e"), ("ousli", "ous"), ("ization", "ize"), ("ation", "ate"), ("ator", "ate"), ("alism", "al"),
      ("iveness", "ive"), ("fulness", "ful"), ("ousness", "ous"), ("aliti", "al"), ("iviti", "ive"), ("biliti", "ble"), ("logi", "log")]
S3 = [("icate", "ic"), ("ative", ""), ("alize", "al"), ("iciti", "ic"), ("ical", "ic"), ("ful", ""), ("ness", "")]
S4 = ["al", "ance", "ence", "er", "ic", "able", "ible", "ant", "ement", "ment", "ent", "ion", "ou", "ism", "ate", "iti", "ous", "ive", "ize"]


def stem(w: str) -> str:
    if len(w) <= 2 or not w.isascii() or not w.isalpha():
        return w
    # 1a
    if w.endswith("sses"):
        w = w[:-2]
    elif w.endswith("ies"):
        w = w[:-2]
    elif w.endswith("ss"):
        pass
    elif w.endswith("s"):
        w = w[:-1]
    # 1b
    extra = False
    if w.endswith("eed"):
        if _m(w[:-3]) > 0:
            w = w[:-1]
    else:
        for suf in ("ed", "ing"):
            if w.endswith(suf) and _vowel_in(w[: -len(suf)]):
                w, extra = w[: -len(suf)], True
                break
    if extra:
        if w.endswith(("at", "bl", "iz")):
            w += "e"
        elif _double_c(w) and w[-1] not in "lsz":
            w = w[:-1]
        elif _m(w) == 1 and _cvc(w):
            w += "e"
    # 1c
    if w.endswith("y") and _vowel_in(w[:-1]):
        w = w[:-1] + "i"
    # 2, 3
    w = _rep(w, S2, lambda b: _m(b) > 0)
    w = _rep(w, S3, lambda b: _m(b) > 0)
    # 4
    for suf in sorted(S4, key=len, reverse=True):
        if w.endswith(suf):
            base = w[: len(w) - len(suf)]
            if _m(base) > 1 and (suf != "ion" or base.endswith(("s", "t"))):
                w = base
            break
    # 5a, 5b
    if w.endswith("e"):
        base = w[:-1]
        if _m(base) > 1 or (_m(base) == 1 and not _cvc(base)):
            w = base
    if _m(w) > 1 and _double_c(w) and w.endswith("l"):
        w = w[:-1]
    return w
