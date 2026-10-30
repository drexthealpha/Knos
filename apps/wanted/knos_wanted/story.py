"""One card, one story (the rivals' review, sweep 22 S1 to S4): what a check's answer leads with, built from the report's
own numbers and calls, never a new Qloo call.

    story.build(rep) -> {sentence, tiles, used, reruns, rejected, downloads}

- sentence: the decision in one line (verdict, place, who);
- tiles: 3 or 4 facts under it: top place, top audience with its lift, price tier, live calls and seconds;
- used: which of the input's words the answer used (and through which Qloo tag or product), which it could not, and
  the next step;
- reruns: for a refusal or a thin answer, up to 3 one-click reruns, each a Qloo tag or a launch market;
- rejected: what was rejected and the rule that rejected it (never empty when something was refused);
- downloads: on an Open card, the pre-order page text, a launch-city outreach draft and a calendar file for the refund
  date, each built from the card's own numbers (GET /api/card/<kind>?hash=).
"""
from __future__ import annotations

import datetime as dt
import re

from .check import content_words, tokens, _norm

MARKETS = ("New York", "Los Angeles", "London")      # a refusal's launch-market reruns, when the card names no market


def _verdict(rep: dict) -> str:
    return str((rep.get("decision") or {}).get("verdict") or "")


def _city(rep: dict) -> str | None:
    t = rep.get("terms") or {}
    if t.get("city"):
        return str(t["city"])
    cities = rep.get("cities") or ((rep.get("launch") or {}).get("cities")) or []
    if cities and cities[0].get("name"):
        return str(cities[0]["name"])
    places = rep.get("places") or []
    return str(places[0]["name"]) if places and places[0].get("name") else None


def _who(rep: dict) -> str | None:
    segs = [a for a in rep.get("audiences") or [] if isinstance(a.get("lift"), (int, float)) and not a.get("flat")]
    if segs:
        return str(segs[0]["name"])
    w = rep.get("who") or {}
    age, gender = w.get("top_age"), w.get("top_gender")
    return " ".join(str(x).replace("_", " ") for x in (gender, age) if x) or None


def sentence(rep: dict) -> str:
    d = rep.get("decision") or {}
    v, city, who = _verdict(rep), _city(rep), _who(rep)
    reasons = [str(r) for r in d.get("reasons") or []]
    if v == "OPEN":
        return "Wanted: open pre-orders" + (f" in {city}" if city else "") + (f", for {who}" if who else "") + "."
    if v == "REFUSE":
        why = next((r for r in reasons if not r.startswith("a new idea, read")), reasons[0] if reasons else "")
        return "Not yet: " + re.sub(r"\s*\(.*$", "", why)[:160] + "."
    if v == "CANNOT_DECIDE":
        miss = next((r.split(":", 1)[0] for r in reasons if r and not r.startswith("cannot decide")), "")
        return "Not enough evidence to decide" + (f": {miss} did not answer" if miss else "") + "."
    return "Queued: Qloo answers this when it can." if v == "QUEUED" else ""


def tiles(rep: dict) -> list[dict]:
    out = []
    city = _city(rep)
    if city:
        out.append({"label": "Top place", "value": city})
    segs = [a for a in rep.get("audiences") or [] if isinstance(a.get("lift"), (int, float)) and not a.get("flat")]
    if segs:
        out.append({"label": "Top audience", "value": str(segs[0]["name"]), "lift": segs[0]["lift"], "src": segs[0].get("src")})
    pr = rep.get("price") or {}
    if pr.get("tier"):
        out.append({"label": "Price tier", "value": str(pr["tier"]), "src": pr.get("src")})
    q = rep.get("qloo_calls") or {}
    ms = q.get("ms") or rep.get("elapsed_ms")
    out.append({"label": "Qloo calls", "value": f"{q.get('live', 0)} live, {q.get('recorded', 0)} recorded"
                + (f", {ms / 1000:.1f} s" if isinstance(ms, (int, float)) else "")})
    return out[:4]


def used(rep: dict) -> dict:
    """The input's content words the answer used (a word in a matched product or a kept Qloo tag), the ones it could
    not, and the next step. Every listed word is one of the input's own content words."""
    idea, place = str(rep.get("idea") or ""), rep.get("place")
    words = content_words(idea, place if isinstance(place, str) else None)
    tags = (rep.get("taste_answer") or {}).get("tags") or rep.get("tags") or []
    seen: dict[str, str] = {}
    for t in tags:
        for w in tokens(t.get("name") or ""):
            seen.setdefault(_norm(w), f"tag {t.get('name')}")
    for m in rep.get("matches") or []:
        for w in m.get("matched_words") or []:
            seen.setdefault(_norm(w), f"product {m.get('name')}")
    used_w = [w for w in words if w in seen]
    not_w = [w for w in words if w not in seen]
    via = list(dict.fromkeys(seen[w] for w in used_w))[:2]
    line = ("Used: " + ", ".join(used_w) + (f" ({'; '.join(via)})" if via else "") + "." if used_w else "Used: none of its words matched Qloo.")
    if not_w:
        line += " Not in Qloo: " + ", ".join(not_w) + ", so check that part yourself before you build."
    return {"used": used_w, "not_in_qloo": not_w, "via": via, "line": line}


def reruns(rep: dict) -> list[dict]:
    """Up to 3 one-click reruns for a refusal or a thin answer: the input's Qloo tags, then launch markets."""
    if _verdict(rep) == "OPEN":
        return []
    out: list[dict] = []
    for t in ((rep.get("taste_answer") or {}).get("tags") or rep.get("tags") or [])[:2]:
        if t.get("name") and str(t["name"]).lower() != str(rep.get("idea") or "").lower():
            out.append({"label": f"Try the tag {t['name']}", "idea": str(t["name"]), "place": rep.get("place") if isinstance(rep.get("place"), str) else None})
    city = _city(rep)
    for m in ([city] if city else []) + [x for x in MARKETS if x != city]:
        if len(out) >= 3:
            break
        out.append({"label": f"Try {m}", "idea": str(rep.get("idea") or ""), "place": m})
    return out[:3]


def rejected(rep: dict) -> list[dict]:
    """What the check rejected and the rule that did: products off the idea, products the maker unticked, and the
    calls whose evidence was not counted."""
    out = [{"name": u.get("name"), "rule": u.get("why")} for u in rep.get("unrelated") or [] if u.get("name")]
    out += [{"name": e.get("name"), "rule": "unticked by the maker"} for e in rep.get("excluded") or [] if e.get("name")]
    out += [{"name": str(c.get("what") or "")[:80], "rule": f"not counted: {str(c.get('error'))[:100]}"}
            for c in rep.get("calls") or [] if c.get("error")]
    if any(a.get("flat") for a in rep.get("audiences") or []):
        out.append({"name": "audience segments", "rule": "Qloo's audience signal moved every scored segment alike, so none counts"})
    why = [str(r) for r in (rep.get("decision") or {}).get("reasons") or [] if r]
    if not out and _verdict(rep) == "REFUSE" and why:        # a refusal always says what it refused, by its own rule
        out.append({"name": str(rep.get("idea") or "the idea")[:80], "rule": why[0][:200]})
    return out[:8]


def downloads(rep: dict) -> list[dict]:
    if _verdict(rep) != "OPEN" or not rep.get("hash"):
        return []
    h = rep["hash"]
    return [{"kind": k, "label": label, "url": f"/api/card/{k}?hash={h}"} for k, label in
            (("preorder", "Pre-order page text"), ("outreach", "Launch-city outreach draft"), ("refund.ics", "Refund date (calendar)"))]


def build(rep: dict) -> dict:
    return {"sentence": sentence(rep), "tiles": tiles(rep), "used": used(rep), "reruns": reruns(rep),
            "rejected": rejected(rep), "downloads": downloads(rep)}


def refund_day(rep: dict) -> dt.date:
    from . import metros
    made = str(rep.get("made") or "")[:10]
    try:
        start = dt.date.fromisoformat(made)
    except ValueError:
        start = dt.datetime.now(dt.timezone.utc).date()
    return start + dt.timedelta(days=metros.DEADLINE_DAYS)


def download(rep: dict, kind: str) -> tuple[str, str, str] | None:
    """(body, content type, file name) of one Open card's download, from the card's own numbers; None otherwise."""
    if _verdict(rep) != "OPEN":
        return None
    d = rep.get("decision") or {}
    idea, city, who = str(rep.get("idea") or "the product"), _city(rep) or "the launch city", _who(rep) or "its first buyers"
    target, reserve = d.get("target_units"), d.get("reserve_units")
    pr = (rep.get("price") or {}).get("tier") or "mid"
    day = refund_day(rep)
    if kind == "preorder":
        body = (f"{idea}\n\nPre-order now, in {city} first. We open when {target} pre-orders are in, and {reserve} of them "
                f"must arrive before the maker is paid. If fewer than {target} come from {city} by {day.isoformat()}, every "
                f"pre-order is refunded. Price tier: {pr}. Made for {who}.\n\nDevnet test money only.\n")
        return body, "text/plain; charset=utf-8", "preorder.txt"
    if kind == "outreach":
        body = (f"Subject: {idea}, launching in {city}\n\nHello,\n\nWe are opening pre-orders for {idea} in {city} first. "
                f"Qloo's taste data points to {who} there. We need {target} pre-orders by {day.isoformat()}; if we miss it, "
                f"every pre-order is refunded. Would you share it with people you know in {city}?\n\nThank you.\n")
        return body, "text/plain; charset=utf-8", "outreach.txt"
    if kind == "refund.ics":
        stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        body = "\r\n".join(["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Knos//pre-order refund//EN", "BEGIN:VEVENT",
                            f"UID:{rep.get('hash')}@knos.onrender.com", f"DTSTAMP:{stamp}", f"DTSTART;VALUE=DATE:{day.strftime('%Y%m%d')}",
                            f"SUMMARY:Refund date: {idea[:60]} needs {target} pre-orders from {city}",
                            "END:VEVENT", "END:VCALENDAR", ""])
        return body, "text/calendar; charset=utf-8", "refund.ics"
    return None
