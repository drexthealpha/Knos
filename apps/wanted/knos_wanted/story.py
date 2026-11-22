"""One card, one story: what a check's answer leads with, built from the report's own rows.

    story.build(rep) -> {sentence, tiles, used, reruns, rejected, rejected_all, downloads}

- sentence: the decision in one line;
- tiles: each open signal's row with its unit, and the money already put down here;
- used: the subject the sources were asked about, the sources used and the rule, in one line.
"""
from __future__ import annotations

SAY = {"OPEN": "Open signals say people want this", "REFUSE": "Open signals find little interest yet",
       "CANNOT_DECIDE": "No signal yet"}


def _tile(x: dict) -> dict:
    money = x.get("name") == "Money down"
    value = (f"${float(x.get('value') or 0):.2f} " if money else f"{int(x.get('value') or 0):,} ") + str(x.get("unit") or "")
    return {"label": x.get("name"), "value": value, **({"link": x["link"]} if x.get("link") else {})}


def build(rep: dict) -> dict:
    fb = rep.get("open_demand") or {}
    v = str((rep.get("decision") or {}).get("verdict") or "")
    return {"sentence": fb.get("head") or SAY.get(v, ""), "tiles": [_tile(x) for x in fb.get("rows") or []],
            "used": {"phrase": fb.get("phrase"), "line": " ".join(x for x in (fb.get("line"), fb.get("rule")) if x)},
            "reruns": [], "rejected": [], "rejected_all": [], "downloads": []}
