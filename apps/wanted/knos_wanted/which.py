"""Which one do you mean? The server's side of knos.readings for a paper: a pasted paper id is read first (OpenAlex), and
the step offers the exact text and the product the paper enables, so the check runs on the reading picked.

- step(text): {kind: "which_one", asked, readings, paper?, name_box?} for a paper id, or None for a plain idea.
"""
from __future__ import annotations

from knos import readings


def _products(ref: str) -> list[str]:
    from . import research
    try:
        card = research.research_card(ref)
    except Exception:  # noqa: BLE001 - no product found is said as the name box, never guessed
        return []
    if str(card.get("product_source") or "").startswith("generic phrase") or not card.get("product"):
        return []
    return [card["product"]]


GENERIC_CONCEPTS = {"computer science", "biology", "medicine", "chemistry", "physics", "mathematics", "engineering",
                    "artificial intelligence", "psychology", "economics"}     # a field, not a product a buyer looks for


def step(text: str, paper_of=None) -> dict | None:
    asked = " ".join(str(text or "").split())
    found = (paper_of or readings.paper)(asked) if readings.is_paper(asked) else None      # OpenAlex for a paper only, never a plain idea
    if not found:
        return None
    ref = readings.doi_of(asked) or (found.get("doi") or "").replace("https://doi.org/", "") or asked
    prods = _products(ref) or [f"an app built on {c.lower()}" for c in (found.get("concepts") or [])[:3]
                               if c and c.lower() not in GENERIC_CONCEPTS][:2]     # the paper's own concepts name a product
    w = readings.which(asked, [], products=prods, found=found)
    return None if w.get("skip") else {**w, "kind": "which_one", "of": w["kind"]}
