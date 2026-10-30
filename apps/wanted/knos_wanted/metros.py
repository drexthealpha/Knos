"""Qloo sets the money terms. Qloo's heatmap for an idea gives cells (a point and an affinity, 0 to 1); each cell is
placed in a US Metropolitan Statistical Area by its 2023 Census boundary (TIGER/Line tl_2023_us_cbsa, LSAD M1,
data/cbsa_msa_2023.json, simplified to 0.01 degree, with each metro's Vintage 2023 population). Of the metros holding
at least 3 cells (the candidates), the highest lift is the launch city: lift = mean cell affinity / the metro's share
of the candidates' population, so a metro wins for its taste, not for its size (Qloo's raw heatmap tracks where people
are). When none holds 3 cells, every metro with a population is a candidate. The
pre-order target is max(10, round(population / 100,000 x mean affinity)), and the brief refunds every pre-order when
that city does not reach it by the first milestone's deadline. The launch block (city, affinity, cell count, population,
target) sits inside the criteria hash (knos.ready)."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

DATA = Path(__file__).parent / "data" / "cbsa_msa_2023.json"
MIN_TARGET = 10
MIN_CELLS = 3
NO_MAP = "Qloo has no map for this idea yet, so Knos sets no launch city."
DEADLINE_DAYS = 30
METHOD = ("of the 15 most populous candidate metros, the highest lift; lift = mean cell affinity / the metro's population share among the candidate metros (method 2: docs.qloo.com "
          "documents no heatmap request without an interest signal, so no baseline heatmap is fetched)")
REFUND = "If fewer than {target} pre-orders come from {city} by the first milestone deadline, every pre-order is refunded."


@lru_cache(maxsize=1)
def _metros() -> list[dict]:
    return json.loads(DATA.read_text(encoding="utf-8"))["metros"]


def _inside(lon: float, lat: float, ring: list) -> bool:
    hit, j = False, len(ring) - 1
    for i in range(len(ring)):
        (xi, yi), (xj, yj) = ring[i], ring[j]
        if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / (yj - yi) + xi:
            hit = not hit
        j = i
    return hit


def metro(lat, lon) -> dict | None:
    """The Metropolitan Statistical Area that holds the point, or None."""
    if not (isinstance(lat, (int, float)) and isinstance(lon, (int, float))):
        return None
    for m in _metros():
        x0, y0, x1, y1 = m["bbox"]
        if x0 <= lon <= x1 and y0 <= lat <= y1 and any(_inside(lon, lat, r) for r in m["rings"]):
            return m
    return None


def flat(cells: list[dict]) -> bool:
    """Every cell at one affinity: Qloo's default for a signal it could not use, never a map of this idea's people."""
    return len(cells) > 1 and len({c.get("affinity") for c in cells}) == 1


def stats(cells: list[dict]) -> list[dict]:
    """Each US metro holding heatmap cells: its cell count, mean affinity, centre, 2023 population, and (for a candidate)
    its population share and lift. Sorted by lift among the candidates, then the metros that are not candidates."""
    by: dict[str, dict] = {}
    for c in cells or []:
        a = c.get("affinity")
        m = metro(c.get("lat"), c.get("lon"))
        if m and isinstance(a, (int, float)):
            row = by.setdefault(m["cbsa"], {"cbsa": m["cbsa"], "city": m["name"], "pop": m.get("pop"), "_a": [], "_at": []})
            row["_a"].append(float(a))
            row["_at"].append((c["lat"], c["lon"]))
    out = []
    for r in by.values():
        n = len(r["_a"])
        out.append({"cbsa": r["cbsa"], "city": r["city"], "cells": n, "affinity": round(sum(r["_a"]) / n, 4), "population": r["pop"],
                    "lat": round(sum(x for x, _ in r["_at"]) / n, 4), "lon": round(sum(y for _, y in r["_at"]) / n, 4)})
    lift(out)
    return sorted(out, key=lambda r: (r["cells"] < MIN_CELLS, r.get("lift") is None, -(r.get("lift") or 0), -r["cells"], r["cbsa"]))


def lift(rows: list[dict]) -> list[dict]:
    """Each candidate metro's population share and lift (mean affinity / share), in place. Candidates: the metros with
    a population and at least MIN_CELLS cells, else every metro with a population."""
    cand = [r for r in rows if r.get("population") and r["cells"] >= MIN_CELLS] or [r for r in rows if r.get("population")]
    total = sum(r["population"] for r in cand)
    for r in rows:
        r["share"] = r["lift"] = None
    for r in cand:
        r["share"] = round(r["population"] / total, 6)
        r["lift"] = round(r["affinity"] / r["share"], 4) if r["share"] else None
    return rows


def by_population(rows: list[dict]) -> dict | None:
    """The city population alone would pick: the candidate metro (as lift() counts them) with the largest 2023
    population, and its target by the same formula, max(10, round(population / 100,000 x its mean affinity))."""
    cand = [r for r in rows if r.get("population") and r["cells"] >= MIN_CELLS] or [r for r in rows if r.get("population")]
    if not cand:
        return None
    top = max(cand, key=lambda r: (r["population"], r["cbsa"]))
    return {"city": top["city"], "target": max(MIN_TARGET, round(top["population"] / 100_000 * top["affinity"])),
            "population": top["population"], "affinity": top["affinity"]}


TOP_BY_POPULATION = 15      # the launch city is ranked among the candidate metros this populous (K6 method c)


def launch(rows: list[dict]) -> dict | None:
    """The launch city (K6 method c, fixed before its pre-registered run): of the candidate metros (lift()), the
    TOP_BY_POPULATION largest by 2023 population, reranked by lift; the highest wins. A metro with no population estimate
    (Puerto Rico) cannot set a target."""
    rows = [r for r in rows if r.get("population") and r.get("lift") is not None]
    big = sorted(rows, key=lambda r: (-r["population"], r["cbsa"]))[:TOP_BY_POPULATION]
    return max(big, key=lambda r: (r["lift"], r["cells"], r["cbsa"])) if big else None


def terms(cells: list[dict]) -> dict | None:
    """The launch city, its mean affinity, cell count and population, and the pre-order target
    max(10, round(population / 100,000 x mean affinity)); None when no cell falls in a US metro."""
    if flat(cells):
        return None
    rows = stats(cells)
    top = launch(rows)
    if not top:
        return None
    target = max(MIN_TARGET, round(top["population"] / 100_000 * top["affinity"]))
    return {"city": top["city"], "cbsa": top["cbsa"], "affinity": top["affinity"], "lift": top["lift"], "cells": top["cells"], "population": top["population"],
            "target": target, "heatmap_cells": len(cells), "metros": rows, "method": METHOD, "by_population": by_population(rows),
            "refund_rule": REFUND.format(target=target, city=top["city"]),
            "source": "Qloo heatmap; Census TIGER/Line 2023 metro boundaries; Census Vintage 2023 population estimates"}


def launch_terms(rep: dict) -> dict | None:
    """The one answer every page draws for a report: {city, target, cells, rule, cities}, from the terms the report
    holds, else the same rule (terms) over its heatmap cells; None when Qloo matched no product to the idea or its map
    names no launch city. `cities` is the one city list of a result: the terms' metros, the launch city first, at most 5."""
    if not rep.get("matches"):
        return None
    t = rep.get("terms") if isinstance(rep.get("terms"), dict) and rep["terms"].get("city") else terms(rep.get("where") or [])
    if not t:
        return None
    pop = by_population(t.get("metros") or [])
    return {"city": t["city"], "target": t["target"], "cells": t.get("cells"), "rule": t.get("refund_rule") or REFUND.format(target=t["target"], city=t["city"]),
            "by_population": pop, "cities": cities_of(t)}


def cities_of(t: dict) -> list[str]:
    """The metros of the terms, the launch city first, at most 5 (the card's map and list draw the same)."""
    names = [str(m.get("city")) for m in t.get("metros") or [] if m.get("city")]
    return sorted(names, key=lambda n: n != t["city"])[:5]


def with_terms(rep: dict) -> dict:
    """A report kept from before its terms were written in it (a recording) with them written in, by the same rule. With
    no product matched there is nothing to launch: no terms, and no map line."""
    if rep.get("stage") == "verdict":
        return rep
    if not rep.get("matches"):
        return {**rep, "terms": None, "no_map": None, "brief": None}
    if isinstance(rep.get("terms"), dict):
        return rep
    t = terms(rep.get("where") or [])
    return {**rep, "terms": t, "no_map": None if t else NO_MAP}


def brief_without_qloo(idea: str) -> dict:
    """The Ready brief of an idea Qloo has not answered yet: the same shape as brief(), one pre-order milestone at the
    formula's floor of 10, with no launch city (Qloo sets the city when it answers; the brief can be edited then)."""
    return {"title": f"Pre-orders for {idea}"[:160],
            "milestones": [{"key": "preorders", "name": "Pre-orders", "target": "10 pre-order customers",
                            "verifier": {"kind": "machine", "check": "test_preorders"}, "deadline_days": DEADLINE_DAYS}],
            "kill_fee_bps": 0, "challenge_s": 86_400}


def brief(idea: str, t: dict, persona: list[str] | None = None) -> dict:
    """The Ready brief whose money terms Qloo set: one pre-order milestone in the launch city. The taste persona's tags
    ride in the launch block, inside the criteria hash."""
    return {"title": f"Pre-orders for {idea}"[:160],
            "milestones": [{"key": "preorders", "name": f"Pre-orders from {t['city']}",
                            "target": f"{t['target']} pre-order customers from {t['city']}",
                            "verifier": {"kind": "machine", "check": "test_preorders_from_city"}, "deadline_days": DEADLINE_DAYS}],
            "kill_fee_bps": 0, "challenge_s": 86_400,
            "launch": {"city": t["city"], "cbsa": t["cbsa"], "affinity": t["affinity"], "cells": t["cells"], "population": t["population"],
                       "target": t["target"], "refund_rule": t["refund_rule"], **({"lift": t["lift"]} if t.get("lift") is not None else {}),
                       **({"persona": [str(x) for x in persona][:8]} if persona else {})}}
