"""Which one do you mean? The server's side of knos.readings: the recorded ideas it can offer (the index R1 lists), the
paper path, and the check of a picked reading when Qloo has no answer for it.

- step(text): {kind: "which_one", asked, readings, paper?, name_box?} before any Qloo call, or None when the input
  needs no step (a recorded idea, word for word).
- queued(text, rep): the picked reading's own report when Qloo is out and nothing was recorded for it: the one line
  saying when Qloo answers, the check queued in the Knos record (Sibyl), the Ready brief and its milestones built with
  no Qloo, and under it the nearest recorded answer as a labelled stand-in. Knos never answers a reading not picked.
"""
from __future__ import annotations

import copy

from knos import readings

from . import recorded

QUEUED = "Qloo answers this when its monthly limit resets on {day}; your check is queued."


def index() -> list[dict]:
    """Every idea this server holds a real Qloo answer for (the chips' cards and every other answered idea), with the day
    it was answered, the entities and the tags Qloo confirmed. Names only: no Qloo body leaves the server."""
    with recorded._lock:
        pool = {recorded.key(r.get("idea") or k): r for k, r in {**recorded._answered, **recorded._last}.items()}
        extra = list(recorded._index)
    rows = []
    for r in pool.values():
        ents = [m.get("name") if isinstance(m, dict) else m for m in (r.get("matches") or [])]
        rows.append({"idea": r.get("idea"), "made": str(r.get("made") or ""), "entities": [e for e in ents if e][:12],
                     "tags": [t.get("name") if isinstance(t, dict) else t for t in (r.get("tags") or [])][:12], "card": True})
    seen = {readings.norm(r["idea"]) for r in rows}
    rows += [r for r in extra if readings.norm(r.get("idea")) not in seen]
    return [r for r in rows if r.get("idea")]


def counts() -> dict:
    rows = index()
    return {"ideas": len({readings.norm(r["idea"]) for r in rows}), "cards": sum(1 for r in rows if r.get("card")),
            "entities": len({str(e).lower() for r in rows for e in r.get("entities") or []}),
            "tags": len({str(t).lower() for r in rows for t in r.get("tags") or []})}


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


def step(text: str, paper_of=readings.paper) -> dict | None:
    asked = " ".join(str(text or "").split())
    found = paper_of(asked) if readings.is_paper(asked) else None      # OpenAlex for a paper only, never a plain idea
    if found:
        ref = readings.doi_of(asked) or (found.get("doi") or "").replace("https://doi.org/", "") or asked
        prods = _products(ref) or [f"an app built on {c.lower()}" for c in (found.get("concepts") or [])[:3]
                                   if c and c.lower() not in GENERIC_CONCEPTS][:2]     # the paper's own concepts reach Qloo's tags
        w = readings.which(asked, [], products=prods, found=found)
    else:
        w = readings.which(asked, index())
    return None if w.get("skip") else {**w, "kind": "which_one", "of": w["kind"]}


def nearest_card(text: str) -> tuple[dict, dict] | None:
    """The nearest recorded card (D1's rule) and its row: (card, {idea, made, shared, differs})."""
    rows = [r for r in index() if r.get("card")]
    near = readings.nearest(text, rows, k=1)
    if not near:
        return None
    k = recorded.key(near[0]["idea"])
    with recorded._lock:
        card = recorded._last.get(k) or recorded._answered.get(k)
    return (copy.deepcopy(card), near[0]) if card else None


def queued(text: str, rep: dict) -> dict:
    """The picked reading's own report when Qloo is out and nothing is recorded for it."""
    from . import company, metros, qloo_status
    day = qloo_status.reset_day() or "the first of next month"
    out = {**rep, "idea": text, "queued": {"line": QUEUED.format(day=day), "reset": day}, "read_as": text,
           "brief": metros.brief_without_qloo(text)}
    from knos import ready
    r = ready.check(out["brief"])
    out["ready"] = {"ready": r.get("ready"), "criteria_hash": r.get("criteria_hash"), "missing": r.get("missing") or []}
    out["decision"] = {**(rep.get("decision") or {}), "verdict": "QUEUED"}
    out["record"] = company.record_queued(text, day)
    got = nearest_card(text)
    if got:
        card, row = got
        diff = row["differs"]
        out["also_matched"] = row["idea"]
        out["stand_in"] = {"idea": row["idea"], "made": row["made"][:10], "differs": diff,
                           "said": f"Stand-in: the recorded answer for {row['idea']}, an imperfect match; it differs in "
                                   f"{diff['theirs'] or 'no word'} against {diff['yours'] or 'no word'}",
                           "card": recorded.live_or_recorded({**card, "stale": {"code": 429, "from": card.get("made")}})}
        out["result_line"] = f"Read as {text}, also matched {row['idea']}"
    else:
        out["result_line"] = f"Read as {text}"
    return out
