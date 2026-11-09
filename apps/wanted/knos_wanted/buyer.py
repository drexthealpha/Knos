"""BUYER agent flow of Knos's demand check: taste signals the buyer CHOOSES -> what that taste also likes -> which
not-yet-built products in Knos fit it -> a pre-order held on Knos devnet until the proof passes.

What the buyer gives is things they like (a brand, a film, a cuisine: public cultural signals), never who they are
(knos_wanted.privacy refuses identity data before any call). Knos keeps no copy of a buyer's tastes: the session
lives in memory for 30 minutes and is not written to the record.

  1. start    each liked thing -> qloo_describe (candidates); each "vibe" -> qloo_find_tags (tag URNs)
  2. confirm  the buyer picks what each word means (only offered candidates are accepted), then:
                qloo_recommend   per target type the buyer chose: what this combined taste also likes
                qloo_rank        the confirmed proxies of the products open for pre-order, against the buyer's signals
                                 (one call per product type: a rank is one option type, and scores from separate calls
                                 are not comparable, as Qloo says)
  3. pre-order: the existing Knos graduation pre-order (knos_wanted.`escrow`), recorded by knos_wanted.company.
"""
from __future__ import annotations

import secrets

from . import catalog, privacy
from .demand import FlowError
from .mock_mcp import INSIGHTS_TYPES
from .qloo_mcp import AGGREGATE, Qloo, candidates, num, results


def _clean(v, n: int) -> list[str]:
    if isinstance(v, str):
        v = [x for x in v.replace(";", ",").split(",")]
    return [" ".join(str(x).split())[:60] for x in (v or []) if isinstance(x, str) and x.strip()][:n]


def start(q: Qloo, likes, vibes=None, targets=None) -> dict:
    likes, vibes = _clean(likes, 5), _clean(vibes, 3)
    targets = [t for t in (targets or ["brand", "place"]) if t in INSIGHTS_TYPES][:3] or ["brand"]
    if not likes and not vibes:
        raise FlowError("name at least one thing you like")
    privacy.check({"likes": likes, "vibes": vibes}, "buyer")
    trail: list[dict] = []
    qs = []
    for w in likes:
        env = q.call("qloo_describe", {"entity": w}, trail=trail, step="your taste",
                     why=f"resolve '{w}' to one Qloo entity; you confirm which one you mean")
        qs.append({"key": f"like:{w}", "kind": "like", "input": w, "status": env.get("status"), "candidates": candidates(env)[:5], "pick": "one"})
    for w in vibes:
        env = q.call("qloo_find_tags", {"query": w, "limit": 5}, trail=trail, step="your taste",
                     why=f"turn '{w}' into a Qloo tag URN; you confirm which one you mean")
        cands = [{"id": r.get("id"), "name": r.get("name")} for r in results(env) if isinstance(r, dict) and r.get("id")]
        qs.append({"key": f"vibe:{w}", "kind": "vibe", "input": w, "status": env.get("status"), "candidates": cands[:5], "pick": "one"})
    return {"id": secrets.token_hex(8), "flow": "buyer", "targets": targets, "questions": qs, "trail": trail, "mode": q.mode,
            "label": q.label, "aggregate": AGGREGATE}


def confirm(q: Qloo, s: dict, choices: dict, products: list[dict] | None = None) -> dict:
    ents, tags = [], []
    for qn in s["questions"]:
        got = choices.get(qn["key"])
        if got in (None, "", []):
            continue
        offered = {c["id"]: c for c in qn["candidates"]}
        if got not in offered:
            raise FlowError(f"{qn['input']}: choose one of the candidates Qloo returned")
        (ents if qn["kind"] == "like" else tags).append({**offered[got], "word": qn["input"]})
    if not ents and not tags:
        raise FlowError("confirm at least one of your tastes")
    trail = s["trail"]
    for c in ents + tags:
        trail.append({"step": "you confirmed", "tool": None, "why": f"'{c['word']}' means {c['name']}", "chosen": c["id"],
                      "status": "confirmed", "mode": q.mode})
    sig = [c["id"] for c in ents]
    stags = [c["id"] for c in tags]
    recs = []
    for t in s["targets"]:
        args = {"target_type": t, "limit": 5, "explain": True, **({"signals": sig} if sig else {}), **({"signal_tags": stags} if stags else {})}
        env = q.call("qloo_recommend", args, trail=trail, step="what this taste likes",
                     why=f"{t}s that people who share this combined taste also like")
        recs.append({"target_type": t, "status": env.get("status"),
                     "items": [{"name": r.get("name"), "affinity": num(r.get("affinity"))} for r in results(env) if isinstance(r, dict)]})
    products = catalog.products() if products is None else products
    ranked, note = [], None
    if not products:
        note = "No product is open for pre-orders yet: a maker opens one from a demand report."
    elif not sig:
        note = "Ranking products needs at least one liked thing (Qloo ranks against entity signals, not tags)."
    else:
        by_type: dict[str, list[dict]] = {}
        for p in products:
            by_type.setdefault(p["type"], []).append(p)
        for typ, group in by_type.items():
            group = group[:10]
            env = q.call("qloo_rank", {"options": [p["proxy"]["id"] for p in group], "option_type": typ, "signals": sig}, trail=trail,
                         step="which product fits",
                         why=f"rank the {len(group)} not-yet-built {typ} product(s) by their confirmed proxies against your taste")
            score = {r.get("entity_id"): num(r.get("affinity")) for r in results(env) if isinstance(r, dict)}
            order = [r.get("entity_id") for r in results(env) if isinstance(r, dict)]
            for p in group:
                pid = p["proxy"]["id"]
                ranked.append({"report_hash": p["report_hash"], "title": p["title"], "type": typ, "proxy": p["proxy"]["name"],
                               "lean": p.get("lean"), "synthetic": p.get("synthetic", False), "affinity": score.get(pid),
                               "rank_in_type": (order.index(pid) + 1) if pid in order else None, "status": env.get("status")})
        ranked.sort(key=lambda r: (r["type"], r["rank_in_type"] or 99))
    return {"flow": "buyer", "mode": q.mode, "label": q.label, "aggregate": AGGREGATE, "recommendations": recs, "products": ranked,
            "note": note, "trail": trail,
            "why_rank_by_type": "Qloo ranks one option type per call and says scores from separate calls are not comparable."}
