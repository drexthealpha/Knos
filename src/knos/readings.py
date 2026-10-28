"""Which one do you mean? Before any demand check, the input becomes the exact thing to check. Built in code, with no
model call:

- an idea: (a) the input as typed; (b) up to 2 nearest recorded ideas, nearest meaning the most shared content words
  (lower-cased, the stop words of stopwords.txt dropped, Porter-stemmed), ties to the most recent recording, never one
  that shares no content word, each with the words that differ; (c) one broader reading, the input without its first
  content word before the last noun, when it has 3 or more content words. An input that is a recorded idea word for
  word (lower-cased) needs no step.
- a DOI or a paper title: the paper from OpenAlex (Crossref when OpenAlex has no answer), its title, year, citations and
  top concepts; the products it enables are the readings (the caller adds them); with none, the reader names one.

    readings.which("a vegan ramen food truck", [{"idea": "a vegan ramen meal kit for college students", "made": "..."}])
"""
from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from functools import lru_cache
from pathlib import Path

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


def _differs(asked: list[tuple[str, str]], other: list[tuple[str, str]]) -> dict:
    a, o = {s for _w, s in asked}, {s for _w, s in other}
    return {"theirs": " ".join(w for w, s in other if s not in a), "yours": " ".join(w for w, s in asked if s not in o)}


def nearest(text: str, index: list[dict], k: int = 2) -> list[dict]:
    """Up to k recorded ideas sharing the most content words with text; ties go to the most recent recording; an idea
    sharing none is never offered. Each: {idea, made, shared, differs: {theirs, yours}}."""
    asked = content(text)
    mine = {s for _w, s in asked}
    rows = []
    for r in index:
        idea = str(r.get("idea") or "")
        if not idea or norm(idea) == norm(text):
            continue
        theirs = content(idea)
        shared = len(mine & {s for _w, s in theirs})
        if shared:
            rows.append({"idea": idea, "made": str(r.get("made") or ""), "shared": shared, "differs": _differs(asked, theirs)})
    rows.sort(key=lambda r: r["made"], reverse=True)          # stable: within a shared count, the newest first
    rows.sort(key=lambda r: r["shared"], reverse=True)
    return rows[:k]


def broader(text: str) -> str | None:
    """The input without its first content word that comes before the last noun (the last content word stands for the
    noun), when it has 3 or more content words: "a vegan ramen food truck" becomes "a ramen food truck"."""
    words = content(text)
    if len(words) < 3:
        return None
    drop = words[0][0]
    out = re.sub(rf"\b{re.escape(drop)}\b\s*", "", str(text).strip(), count=1, flags=re.I)
    out = " ".join(out.split())
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
    doi = doi_of(text)
    q = f"&mailto={urllib.parse.quote(mailto)}" if mailto else ""
    if doi:
        w = get(f"https://api.openalex.org/works/doi:{urllib.parse.quote(doi)}{'?' + q[1:] if q else ''}")
    else:
        if len(content(text)) < 4:
            return None
        hit = get(f"https://api.openalex.org/works?search={urllib.parse.quote(str(text))}&per-page=1{q}")
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
    if found:
        rs = [{"text": p, "kind": "product"} for p in (products or []) if p]
        return {"asked": asked, "kind": "paper", "skip": False, "paper": found, "readings": rs[:4], "name_box": not rs,
                "name_prompt": "Name the product this result enables"}
    if any(norm(r.get("idea")) == norm(asked) for r in index):
        return {"asked": asked, "kind": "idea", "skip": True, "readings": [{"text": asked, "kind": "exact"}]}
    rs = [{"text": asked, "kind": "exact"}]
    for n in nearest(asked, index):
        rs.append({"text": n["idea"], "kind": "recorded", "made": n["made"][:10], "differs": n["differs"], "shared": n["shared"]})
    b = broader(asked)
    if b and len(rs) < 4:
        rs.append({"text": b, "kind": "broader"})
    return {"asked": asked, "kind": "idea", "skip": False, "readings": rs[:4]}
