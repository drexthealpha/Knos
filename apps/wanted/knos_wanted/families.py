"""The Qloo demand families F1-F8 (knos.qloo_families has the one table of names): the calls each family makes, on top
of the demand check's evidence, and the plain answer each gives.

Each family runs only when one of its options is set (the app's controls, the /mcp tool, the API body, `knos demand`
flags), through the same numbered _Run as the rest of the check, so every figure names its call. The answers feed the
Ready brief's "Grounding (Qloo)" line: audience, cities, price tier, comparables.

  F1 who        the comparables ranked for that age and gender (and audience segments)
  F2 gaps       the comparables without the leader / below a popularity cap: what is left for a new product
  F3 where      places near a named city or area (radius, geohash, exclusions, exact region names)
  F4 price      the heatmap's hot areas for a price tier (heatmap.dimensions)
  F5 serves     places tied to a brand (references_brand), by quality, rating, hours, address, Resy/Tripadvisor
  F6 media      film/TV/book/person comparables in a year range, rating, country, content rating, dates
  F7 lookup     an exact thing by name (Search Entities, incl. localities, near a point, sorted) or by id (by ID)
  F8 more       any other parameter the Entity Type Parameter Guide documents for the call's filter.type
"""
from __future__ import annotations

from pathlib import Path

from knos import qloo_families as Q

GUIDE = Path(Q.__file__).with_name("qloo_docs") / "entity_type_guide.tsv"
SECTION = {"urn:entity:artist": "Artist", "urn:entity:book": "Book", "urn:entity:brand": "Brand", "urn:entity:destination": "Destination",
           "urn:heatmap": "Heatmap", "urn:entity:movie": "Movie", "urn:entity:person": "Person", "urn:entity:place": "Place",
           "urn:entity:podcast": "Podcast", "urn:tag": "Tag", "urn:entity:tv_show": "TV Show", "urn:entity:videogame": "Video Game",
           "urn:entity:actor": "Actor", "urn:entity:author": "Author", "urn:entity:director": "Director"}
# the live API acts on these names where the Guide spells them otherwise (knos.qloo_families.NOTES)
GUIDE_ALIASES = {"filter.external.resy.rating.min": "filter.properties.resy.rating.min", "filter.external.resy.rating.max": "filter.properties.resy.rating.max",
                 "filter.external.resy.count.min": "filter.resy.rating_count.min", "filter.external.resy.count.max": "filter.resy.rating_count.max",
                 "filter.external.resy.party_size.min": "filter.resy.rating.party.min", "filter.external.resy.party_size.max": "filter.resy.rating.party.max"}


REFERENCE = GUIDE.with_name("insights_parameters.tsv")
_GUIDE: dict[str, set[str]] = {}


def guide() -> dict[str, set[str]]:
    """filter.type section -> the parameters docs.qloo.com documents for it: the Entity Type Parameter Guide's table, and
    the Parameter Reference's "compatible entity types" (the two pages do not list the same; either is taken)."""
    if _GUIDE:
        return _GUIDE
    for line in GUIDE.read_text(encoding="utf-8").splitlines():
        if line.startswith("#") or "\t" not in line:
            continue
        section, param = line.split("\t")[:2]
        _GUIDE.setdefault(section, set()).add(param)
    for line in REFERENCE.read_text(encoding="utf-8").splitlines():
        if line.startswith("#") or "\t" not in line:
            continue
        param, _, types = (line.split("\t") + ["", ""])[:3]
        for t in (x.strip() for x in types.split(",")):
            if t:
                _GUIDE.setdefault(t, set()).add(param)
    return _GUIDE


ENDPOINTS = GUIDE.with_name("endpoints.tsv")


def endpoint_params(path: str) -> set[str]:
    """The query parameters an endpoint's own docs.qloo.com page lists (qloo_docs/endpoints.tsv)."""
    out = set()
    for line in ENDPOINTS.read_text(encoding="utf-8").splitlines():
        if not line.startswith("#") and line.startswith(path + "\t"):
            out.add(line.split("\t")[1])
    if path == "/entities":        # the external.<source>.ids family, one row in the table
        out |= {f"external.{s}.ids" for s in ("facebook", "goodreads", "goodreads_author", "igdb", "imdb", "instagram", "isbn10", "isbn13",
                                               "itunes", "lastfm", "library_of_congress", "metacritic", "michelin", "musicbrainz",
                                               "rottentomatoes", "soundcloud", "spotify", "tablet", "twitch", "twitter", "wikidata", "resy")}
    return out


def allowed(filter_type: str, param: str) -> bool:
    ok = guide().get(SECTION.get(filter_type, ""), set())
    return param in ok or GUIDE_ALIASES.get(param) in ok


def _names(body, n: int = 6) -> list[dict]:
    rows = ((body or {}).get("results") or {})
    rows = rows.get("entities") if isinstance(rows, dict) else rows
    out = []
    for r in (rows or [])[:n]:
        if isinstance(r, dict):
            q = r.get("query") or {}
            out.append({"name": r.get("name"), "id": r.get("entity_id"), "popularity": r.get("popularity"), "affinity": q.get("affinity"),
                        "located": ((r.get("properties") or {}).get("geocode") or {}).get("name")})
    return out


def _extra(o: dict, filter_type: str) -> tuple[dict, list[str]]:
    """F8: the `qloo` object's parameters the Guide documents for this filter.type; the rest named as refused."""
    keep, refused = {}, []
    for k, v in (o.get("qloo") or {}).items():
        (keep.__setitem__(k, v) if allowed(filter_type, k) else refused.append(k))
    return keep, refused


def _params(o: dict, fields: tuple[str, ...], filter_type: str) -> dict:
    out = {}
    for f in fields:
        if f in o and Q.FIELDS[f][1] not in ("*", "filter.type") and allowed(filter_type, Q.FIELDS[f][1]):
            out[Q.FIELDS[f][1]] = o[f]
    return out


def _signal(ev: dict) -> dict:
    ids = [m["id"] for m in (ev.get("matches") or [])[:3] if m.get("id")] or ([ev["leader"]["id"]] if (ev.get("leader") or {}).get("id") else [])
    if ids:
        return {"signal.interests.entities": ",".join(ids)}
    tags = [t["id"] for t in (ev.get("tags") or [])[:3] if t.get("id")]
    return {"signal.interests.tags": ",".join(tags)} if tags else {}


def _brand(run, o: dict) -> tuple[str | None, int | None]:
    b = str(o.get("references_brand") or "")
    if not b:
        return None, None
    if len(b) >= 30 and "-" in b:                       # already a Qloo id
        return b, None
    body, n = run.get("/search", {"query": b[:80], "types": "urn:entity:brand", "take": 1}, f"F5 who serves it: the brand {b[:40]}")
    rows = (body or {}).get("results") or []
    return (rows[0].get("entity_id") if rows and isinstance(rows[0], dict) else None), n


def _find(run, name: str, kind: str) -> str | None:
    """One name -> the Qloo id of the best match of that kind (/search), or None."""
    body, _ = run.get("/search", {"query": str(name)[:80], "types": kind, "take": 1}, f"families: find '{str(name)[:40]}'")
    rows = (body or {}).get("results") or []
    return rows[0].get("entity_id") if rows and isinstance(rows[0], dict) else None


FIELDS_OF = {fam: tuple(k for k, v in Q.FIELDS.items() if v[0] == fam) for fam in Q.QUESTIONS}


def fields() -> dict:
    """GET /api/demand/fields: what the app and the front door draw their controls from (the plain control first)."""
    fam = {}
    for f, q in Q.QUESTIONS.items():
        label, plain = Q.PLAIN[f]
        fam[f] = {"question": q, "label": label, "plain": list(plain),
                  "fields": [{"name": k, "qloo": Q.FIELDS[k][1], "kind": Q.FIELDS[k][2], "help": Q.FIELDS[k][3], "example": Q.FIELDS[k][4]}
                             for k in FIELDS_OF[f]]}
    return {"families": fam, "notes": Q.NOTES, "ages": list(Q.AGES), "kinds": list(Q.KINDS)}


def answer(run, ev: dict, idea: str, place: str | None, o: dict) -> dict:
    """The families the options ask for, each {question, call, params, answer} (and F4's hot areas, F7's lookups)."""
    o = dict(o or {})
    out: dict = {}
    kind = Q.KINDS.get(o.get("product_kind", "")) or ev.get("product_type") or "urn:entity:brand"
    sig = _signal(ev)
    extra, refused = _extra(o, kind)
    if refused:
        out["F8_refused"] = {"params": refused, "why": f"not in Qloo's Entity Type Parameter Guide for {kind}"}
    lead = (ev.get("leader") or {}).get("id")

    # F1 who, F2 gaps, F6 media, F8 more: the comparables, re-ranked under those options
    fams = [f for f in ("F1", "F2", "F6", "F8") if any(k in o for k in FIELDS_OF[f])]
    if fams and (sig or o.get("product_kind")):
        p = {"filter.type": kind, "take": 8, **sig, **extra}
        for f in ("F1", "F2", "F6"):
            p.update(_params(o, FIELDS_OF[f], kind))
        if kind in ("urn:entity:place", "urn:entity:destination") and place and not any(k.startswith("filter.location") for k in p):
            p["filter.location.query"] = place            # a place product is compared within its launch market
        if kind == "urn:entity:book":                     # books: the year fields are the publication year
            for a, b in (("year_min", "filter.publication_year.min"), ("year_max", "filter.publication_year.max")):
                if a in o:
                    p.pop(Q.FIELDS[a][1], None)
                    p[b] = o[a]
        # names: Qloo resolves a POST *.query name to a PLACE by default (docs: resolve_to self), so for any other kind each
        # name is first found by /search within that kind and sent by id; for places the POST parameter is sent as it is
        resolved = {}
        if kind != "urn:entity:place":
            for f, into in (("exclude_names", "filter.exclude.entities"), ("interests_names", "signal.interests.entities")):
                if f in o:
                    p.pop(Q.FIELDS[f][1], None)
                    resolved[into] = [i for i in (_find(run, nm, kind) for nm in o[f]) if i]
            if resolved.get("signal.interests.entities"):
                p["signal.interests.entities"] = ",".join(resolved["signal.interests.entities"])
        ex = [x for x in str(o.get("exclude") or "").split(",") if x] + ([lead] if o.get("hide_leader") and lead else []) + resolved.get("filter.exclude.entities", [])
        if ex:
            p["filter.exclude.entities"] = ",".join(dict.fromkeys(ex))
        body, n = run.get("/v2/insights", p, "families " + "+".join(fams) + ": the comparables under these options", broaden=False)
        got = _names(body, 8)
        for f in fams:
            out[f] = {"question": Q.QUESTIONS[f], "call": n, "params": {k: v for k, v in p.items() if not k.startswith("signal.interests")},
                      "answer": got}

    # F3 where and F5 who serves it: places
    if any(k in o for k in FIELDS_OF["F3"] + FIELDS_OF["F5"]):
        p = {"filter.type": "urn:entity:place", "take": 8, **_params(o, FIELDS_OF["F3"] + FIELDS_OF["F5"], "urn:entity:place")}
        if "near" not in o and "location" not in o and place:
            p["filter.location.query"] = place
        bid, bn = _brand(run, o)
        p.pop("filter.references_brand", None)
        if bid:
            p["filter.references_brand"] = bid
        if "filter.references_brand" not in p and "signal.interests.entities" in sig:
            p.update(sig)
        body, n = run.get("/v2/insights", p, "families F3/F5: places under these options", broaden=False)
        got = _names(body, 8)
        for f in ("F3", "F5"):
            if any(k in o for k in FIELDS_OF[f]):
                out[f] = {"question": Q.QUESTIONS[f], "call": n, "params": p, "answer": got, **({"brand_call": bn, "brand_id": bid} if f == "F5" and bn else {})}

    # F4 at what price, where: the heatmap's hot areas for the tier
    if any(k in o for k in FIELDS_OF["F4"]):
        # where: the WKT area or locality id asked (filter.location, with its radius), else the place named; with neither,
        # New York City, said in the call's params
        where = ({"filter.location": o["location"], **({"filter.location.radius": o["radius"]} if "radius" in o else {})} if o.get("location")
                 else {"filter.location.query": o.get("near") or place or "New York City"})
        p = {"filter.type": "urn:heatmap", "take": 8, **(sig or {}), **where}   # Qloo refuses output.heatmap.boundary (400)
        dims = [d for d, f in (("price_level", "price_level"), ("hotel_class", "hotel_class")) if f in o]
        if dims:
            p["heatmap.dimensions"] = ",".join(dims)
            for d in dims:
                p[f"filter.dimensions.{d}"] = o[d]
        body, n = run.get("/v2/insights", p, "family F4: where the price tier is hot (heatmap)", broaden=False)
        rows = ((body or {}).get("results") or {}).get("heatmap") or []
        hot = [{"geohash": (r.get("location") or {}).get("geohash"), "affinity": (r.get("query") or {}).get("affinity")} for r in rows[:8] if isinstance(r, dict)]
        price = _params(o, FIELDS_OF["F4"], "urn:entity:place")          # the price range, as places take it
        place_p = {"filter.type": "urn:entity:place", "take": 6, **price, **where}
        b2, n2 = (run.get("/v2/insights", place_p, "family F4: places in the price range", broaden=False) if price else (None, None))
        out["F4"] = {"question": Q.QUESTIONS["F4"], "call": n, "params": p, "hot": hot, **({"places_call": n2, "places": _names(b2)} if n2 else {})}

    # F7 look up exact things
    if "lookup" in o:
        p = {"query": o["lookup"], "take": 5, **({"types": o["lookup_types"]} if "lookup_types" in o else {}),
             **({"filter.location": o["lookup_near"]} if "lookup_near" in o else {}), **({"filter.radius": o["lookup_radius"]} if "lookup_radius" in o else {}),
             **({"sort_by": o["lookup_sort"]} if "lookup_sort" in o else {})}
        body, n = run.get("/search", p, f"family F7: look up '{str(o['lookup'])[:40]}'")
        rows = (body or {}).get("results") or []
        found = [{"name": r.get("name"), "id": r.get("entity_id"), "type": (r.get("types") or [None])[0]} for r in rows[:5] if isinstance(r, dict)]
        out["F7"] = {"question": Q.QUESTIONS["F7"], "call": n, "params": p, "answer": found}
    # F8 more: Qloo's other endpoints, each with only the parameters its own docs page lists
    for path, params in (o.get("qloo_calls") or {}).items():
        doc = endpoint_params(path)
        if not doc or not isinstance(params, dict):
            out.setdefault("F8_refused", {"params": [], "why": "not a documented endpoint or parameter"})["params"].append(str(path)[:40])
            continue
        bad = [k for k in params if k not in doc]
        if bad:
            out.setdefault("F8_refused", {"params": [], "why": f"not on {path}'s docs page"})["params"] += bad
        keep = {k: v for k, v in params.items() if k in doc}
        body, n = run.get(path, keep, f"family F8: {path}", broaden=False)
        res = (body or {}).get("results")
        rows = res if isinstance(res, list) else next((v for v in (res or {}).values() if isinstance(v, list)), [])
        out.setdefault("F8_calls", []).append({"path": path, "call": n, "params": keep,
                                               "answer": [{"name": r.get("name") or r.get("type"), "id": r.get("entity_id") or r.get("id")}
                                                          for r in rows[:6] if isinstance(r, dict)]})
    if "entity_id" in o:
        body, n = run.get("/entities", {"entity_ids": o["entity_id"]}, "family F7: the entity by id")
        rows = (body or {}).get("results") or []
        got = [{"name": r.get("name"), "id": r.get("entity_id"), "type": (r.get("types") or [None])[0]} for r in rows[:3] if isinstance(r, dict)]
        out.setdefault("F7", {"question": Q.QUESTIONS["F7"]})["by_id"] = {"call": n, "answer": got}
    return out


def grounding(rep: dict) -> dict:
    """The Ready brief's "Grounding (Qloo)" facts from a report: audience, cities, price tier, comparables."""
    fam = rep.get("families") or {}
    who = rep.get("who") or {}
    plan = ((rep.get("decision") or {}).get("plan") or {})
    comps = [x["name"] for x in ((fam.get("F6") or fam.get("F2") or fam.get("F1") or {}).get("answer") or []) if x.get("name")][:4] or \
        [m["name"] for m in (rep.get("matches") or []) if m.get("name")][:4]
    cities = [c["name"] for c in (rep.get("cities") or []) if c.get("name")][:3] or \
        [x["located"] for x in ((fam.get("F3") or {}).get("answer") or []) if x.get("located")][:3]
    out = {"audience": ", ".join(x for x in (who.get("top_age"), who.get("top_gender")) if x) or None,
           "segments": plan.get("who", {}).get("segments") or [a.get("name") for a in (rep.get("audiences") or []) if a.get("tied")][:3],
           "cities": list(dict.fromkeys(cities)), "price_tier": (rep.get("price") or {}).get("tier"),
           "comparables": comps, "report": rep.get("hash")}
    return {k: v for k, v in out.items() if v}
