"""Which one do you mean? Before any demand check, the input becomes the exact thing to check. Built in code, with no
model call:

- an idea: (a) the input as typed, always first; (b) up to 2 nearest recorded ideas, nearest meaning the most shared
  content words (lower-cased, the stop words of stopwords.txt dropped, Porter-stemmed), ties to the most recent
  recording, each sharing 2 or more content words and the input's last noun, with the words that differ; (c) one
  broader reading, the input without its first content word before the last noun, when it has 3 or more content words.
  An input that is a recorded idea word for word (lower-cased) needs no step.
- a paper (a DOI, an arXiv id, a doi.org or arxiv.org URL, or text starting with "paper:"; nothing else is a paper):
  the paper from OpenAlex (Crossref when OpenAlex has no answer), its title, year, citations and top concepts; the input
  itself first, then the products it enables (the caller adds them); with none, the reader names one.

    readings.which("a vegan ramen food truck", [{"idea": "a vegan ramen meal kit for college students", "made": "..."}])
"""
from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from functools import lru_cache
from pathlib import Path
from typing import Any

from .porter import stem

WORD = re.compile(r"[a-z0-9]+(?:'[a-z]+)?")
DOI = re.compile(r"\b(10\.\d{4,9}/[^\s\"<>]+)", re.I)


@lru_cache(maxsize=1)
def stopwords() -> frozenset[str]:
    lines = (Path(__file__).with_name("stopwords.txt")).read_text(encoding="utf-8").splitlines()
    return frozenset(w.strip() for w in lines if w.strip() and not w.startswith("#"))


def content(text: str) -> list[tuple[str, str]]:
    """The content words of a text, in order: (the word as written, lower-cased; its Porter stem)."""
    return [(w, stem(w)) for w in WORD.findall(str(text or "").lower()) if w not in stopwords()]


def norm(text: str) -> str:
    return " ".join(str(text or "").lower().split())


ARXIV = re.compile(r"(?:arxiv\.org/(?:abs|pdf)/|arxiv:\s*|^)(\d{4}\.\d{4,5})(?:v\d+)?\b", re.I)
_HEAD_END = re.compile(r"\b(?:for|with|in|near|on|at|like|to|from|that|which|who|where|and)\b|[,;:!?.()$]")


def arxiv_of(text: str) -> str | None:
    m = ARXIV.search(str(text or "").strip())
    return m.group(1) if m else None


def is_paper(text: str) -> bool:
    """A paper, and only then a paper: a DOI, an arXiv id, a doi.org or arxiv.org URL, or text starting with "paper:".
    A plain idea is never sent to a paper search (a long idea was read as a 2016 paper on Prohibition)."""
    t = str(text or "").strip()
    return bool(doi_of(t) or arxiv_of(t) or re.match(r"(?:https?://)?(?:dx\.)?(?:doi\.org|arxiv\.org)/", t, re.I)
                or t.lower().startswith("paper:"))


def last_noun(text: str) -> str | None:
    """The stem of the input's last noun before what qualifies it ("a late night ramen spot for students" -> "spot")."""
    chunk = _HEAD_END.split(f" {str(text or '').lower()} ", 1)[0]
    words = content(chunk)
    return words[-1][1] if words else None


def _differs(asked: list[tuple[str, str]], other: list[tuple[str, str]]) -> dict:
    a, o = {s for _w, s in asked}, {s for _w, s in other}
    return {"theirs": " ".join(w for w, s in other if s not in a), "yours": " ".join(w for w, s in asked if s not in o)}


MIN_SHARED = 2               # a recorded idea is offered only when it shares this many content words with the input


def nearest(text: str, index: list[dict], k: int = 2) -> list[dict]:
    """Up to k recorded ideas sharing the most content words with text; ties go to the most recent recording. One is
    offered only when it shares MIN_SHARED or more content words AND the input's last noun ("spot", "truck", "brand"):
    one shared word ("night") offered a bakery for a ramen spot. Each: {idea, made, shared, differs: {theirs, yours}}."""
    asked = content(text)
    mine = {s for _w, s in asked}
    head = last_noun(text)
    rows: list[dict[str, Any]] = []
    for r in index:
        idea = str(r.get("idea") or "")
        if not idea or norm(idea) == norm(text):
            continue
        theirs = content(idea)
        stems = {s for _w, s in theirs}
        shared = len(mine & stems)
        if shared >= MIN_SHARED and head is not None and head in stems:
            rows.append({"idea": idea, "made": str(r.get("made") or ""), "shared": shared, "differs": _differs(asked, theirs)})
    rows.sort(key=lambda r: str(r["made"]), reverse=True)          # stable: within a shared count, the newest first
    rows.sort(key=lambda r: int(r["shared"]), reverse=True)
    return rows[:k]


def broader(text: str) -> str | None:
    """The last two content words of the input's noun phrase (before its first preposition), when the input has 3 or
    more content words: "a late night ramen spot" becomes "a ramen spot", "a vegan ramen food truck" becomes
    "a food truck", "a board game cafe with vegan snacks for students" becomes "a game cafe"."""
    if len(content(text)) < 3:
        return None
    head = re.split(r"\b(?:with|for|near|in|on|at|by|from|to|of|that|which|who)\b", str(text).lower(), maxsplit=1)[0]
    words = content(head) or content(text)          # the noun phrase before its first preposition: what the thing is
    tail = " ".join(w for w, _ in words[-2:])
    out = ("an " if tail[0] in "aeiou" else "a ") + tail
    return out if norm(out) != norm(text) else None


def doi_of(text: str) -> str | None:
    m = DOI.search(str(text or "").strip())
    return m.group(1).rstrip(".,;)") if m else None


def _get(url: str) -> dict | None:
    req = urllib.request.Request(url, headers={"User-Agent": "knos-readings (https://github.com/drexthealpha/Knos)", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read())
    except (OSError, ValueError):
        return None


def paper(text: str, get=_get, mailto: str | None = None) -> dict | None:
    """A DOI or a paper title as the paper: OpenAlex first (no key; a mailto only when the caller's config names one),
    Crossref when OpenAlex has no answer. {doi, title, year, cited_by_count, concepts, source}."""
    if not is_paper(text):                        # a plain idea is never a paper search
        return None
    ax = arxiv_of(text)
    doi = doi_of(text) or (f"10.48550/arXiv.{ax}" if ax else None)
    q = f"&mailto={urllib.parse.quote(mailto)}" if mailto else ""
    if doi:
        w = get(f"https://api.openalex.org/works/doi:{urllib.parse.quote(doi)}{'?' + q[1:] if q else ''}")
    else:
        title = re.sub(r"^\s*paper:\s*", "", str(text), flags=re.I)
        if len(content(title)) < 2:
            return None
        hit = get(f"https://api.openalex.org/works?search={urllib.parse.quote(title)}&per-page=1{q}")
        w = ((hit or {}).get("results") or [None])[0]
    if w and w.get("title"):
        cs = sorted(w.get("concepts") or [], key=lambda c: -(c.get("score") or 0))
        return {"doi": (w.get("doi") or (f"https://doi.org/{doi}" if doi else None)), "title": w["title"], "year": w.get("publication_year"),
                "cited_by_count": w.get("cited_by_count"), "concepts": [c.get("display_name") for c in cs[:4] if c.get("display_name")],
                "source": "OpenAlex", "id": w.get("id")}
    if doi:
        c = (get(f"https://api.crossref.org/works/{urllib.parse.quote(doi)}") or {}).get("message") or {}
        if c.get("title"):
            year = ((c.get("issued") or {}).get("date-parts") or [[None]])[0][0]
            return {"doi": f"https://doi.org/{doi}", "title": c["title"][0], "year": year, "cited_by_count": c.get("is-referenced-by-count"),
                    "concepts": [s for s in (c.get("subject") or [])[:4]], "source": "Crossref", "id": None}
    return None


def which(text: str, index: list[dict], products: list[str] | None = None, found: dict | None = None) -> dict:
    """The step itself. {asked, kind: idea|paper, skip, readings: [{text, kind, differs?, made?}], paper?, name_box?}.
    `products`: what the research card says the paper enables (the caller's knos_research_card); `found`: the paper."""
    asked = " ".join(str(text or "").split())
    if found:                                     # the exact reading first, always pickable; then what the paper enables
        rs = [{"text": asked, "kind": "exact"}] + [{"text": p, "kind": "product"} for p in (products or []) if p and norm(p) != norm(asked)]
        return {"asked": asked, "kind": "paper", "skip": False, "paper": found, "readings": rs[:4], "name_box": len(rs) == 1,
                "name_prompt": "Name the product this result enables"}
    if any(norm(str(r.get("idea") or "")) == norm(asked) for r in index):
        return {"asked": asked, "kind": "idea", "skip": True, "readings": [{"text": asked, "kind": "exact"}]}
    rs = [{"text": asked, "kind": "exact"}]
    for n in nearest(asked, index):
        rs.append({"text": n["idea"], "kind": "recorded", "made": n["made"][:10], "differs": n["differs"], "shared": n["shared"]})
    b = broader(asked)
    if b and len(rs) < 4:
        rs.append({"text": b, "kind": "broader"})
    return {"asked": asked, "kind": "idea", "skip": False, "readings": rs[:4]}
