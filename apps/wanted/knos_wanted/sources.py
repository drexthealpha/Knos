"""Each source a result cites, with the passage that says it and the day it was checked (L10). The limit check's sample
cites one source: NASA's battery data page, for its limit of 1.4. The passage is copied from that page as fetched on
the day below; sha256 is the hash of the page's bytes that day, so a later fetch shows whether the page changed.

"supports" is worked out here, never typed: a source supports its sentence when every value the sentence rests on
("says") is in the passage. The support rate is the count of sources that do over all sources.

(Kept as Python: the monorepo keeps no JSON under apps/wanted, tests/test_fold_wanted.py.)"""
from __future__ import annotations

SOURCES = [
    {"id": "nasa-battery-eol",
     "cites": "the sample's limit, 1.4: end of life at a 30% fade in rated capacity",
     "url": "https://data.nasa.gov/dataset/li-ion-battery-aging-datasets",
     "passage": ("The experiments were stopped when the batteries reached the end-of-life (EOL) criteria of 30% fade in "
                 "rated capacity (from 2 Ah to 1.4 Ah)."),
     "says": ["30% fade", "1.4 Ah", "end-of-life"],
     "checked_on": "2026-11-22",
     "sha256": "59a9185d7696685674f20e5aea833409ee9bd5c2db4e3bc2f012a9f257762e99"},
]


def supports(s: dict) -> bool:
    p = str(s.get("passage") or "")
    return bool(p) and all(x in p for x in s.get("says") or [None])


def summary() -> dict:
    """Every source with whether its passage supports its sentence, and the rate: "N of M"."""
    rows = [{**s, "supports": supports(s)} for s in SOURCES]
    n = sum(1 for r in rows if r["supports"])
    return {"sources": rows, "supporting": n, "total": len(rows), "line": f"sources supporting their sentence: {n} of {len(rows)}"}


def for_limit() -> dict | None:
    """The source of the sample's limit, the one the tool page shows."""
    return next((s for s in SOURCES if s["id"] == "nasa-battery-eol"), None)
