"""The Qloo demand families: one table that every Knos interface reads.

Each family answers one demand question before money moves. Each field is ONE typed name, the same everywhere:
the app's controls (the family's plain control first, the rest under "Advanced"), the front door's demand check,
the hosted /mcp tool's arguments, the API's body fields (and OpenAPI), and `knos demand` flags (--name-with-dashes).
A field names the Qloo parameter it sets, as docs.qloo.com spells it; where Qloo's own pages disagree, the name the
live API acts on is the one used, and NOTES says so. Nothing here calls Qloo: knos_wanted.families does, server side.

F8 is the rest of the Entity Type Parameter Guide: `qloo` takes any documented parameter for the call's filter.type
(checked against src/knos/qloo_docs/entity_type_guide.tsv on the server), so nothing in the guide is out of reach.
"""
from __future__ import annotations

import re

AGES = ("24_and_younger", "25_to_29", "30_to_34", "35_to_44", "45_to_54", "55_and_older")
KINDS = {"film": "urn:entity:movie", "tv": "urn:entity:tv_show", "book": "urn:entity:book", "person": "urn:entity:person",
         "artist": "urn:entity:artist", "brand": "urn:entity:brand", "podcast": "urn:entity:podcast", "game": "urn:entity:videogame",
         "place": "urn:entity:place", "destination": "urn:entity:destination"}
WEIGHTS = ("low", "medium", "high", "higher")
WKT = re.compile(r"^\s*(POINT|POLYGON|MULTIPOLYGON)\s*\(", re.I)

# name: (family, Qloo parameter, kind of value, one line for a person, example)
#   kinds: str, int, float, ids (comma list), names (comma list, sent as a JSON array), enum:<a|b>, list:<a|b>, bool
FIELDS: dict[str, tuple[str, str, str, str, object]] = {
    # F1 who wants it
    "age": ("F1", "signal.demographics.age", "list:" + "|".join(AGES), "Who: age range(s) the answer is weighted to", "35_to_44"),
    "gender": ("F1", "signal.demographics.gender", "enum:male|female", "Who: gender the answer is weighted to", "female"),
    "audiences": ("F1", "signal.demographics.audiences", "ids", "Audience segment ids (from /v2/audiences)", "urn:audience:hobbies_and_interests:running"),
    "interests_names": ("F1", "signal.interests.entities.query", "names", "Steer the answer by things you name (Qloo resolves them; sent as JSON)", "Hoka, Salomon"),
    "audiences_weight": ("F1", "signal.demographics.audiences.weight", "enum:" + "|".join(WEIGHTS), "How much the segments steer the answer", "high"),
    # F2 what is underserved
    "hide_leader": ("F2", "filter.exclude.entities", "bool", "Gaps: hide the market leader (its Qloo id is excluded)", True),
    "exclude": ("F2", "filter.exclude.entities", "ids", "Entity ids to leave out", "4BBEF799-A0C4-4110-AB01-39216993C312"),
    "exclude_names": ("F2", "filter.exclude.entities.query", "names", "Leave out things by name (Qloo resolves them; sent as JSON)", "Nike, Adidas"),
    "exclude_tags": ("F2", "filter.exclude.tags", "ids", "Tag ids to leave out", "urn:tag:genre:media:horror"),
    "exclude_tags_operator": ("F2", "operator.exclude.tags", "enum:union|intersection", "Leave out results with any (union) or all (intersection) of those tags", "union"),
    "popularity_max": ("F2", "filter.popularity.max", "float", "Gaps: niche only, popularity at most this percentile (0-1)", 0.5),
    "popularity_min": ("F2", "filter.popularity.min", "float", "Popularity at least this percentile (0-1)", 0.1),
    "results_query": ("F2", "filter.results.entities.query", "str", "Score only these named things (one name)", "Fitbit"),
    # F3 where to launch
    "near": ("F3", "filter.location.query", "str", "Where: a city or region by name", "Austin"),
    "radius": ("F3", "filter.location.radius", "int", "Where: radius around it, in meters (0 = strictly inside)", 5000),
    "location": ("F3", "filter.location", "str", "A WKT POINT/POLYGON (longitude first) or a locality id", "POINT(-97.7431 30.2672)"),
    "geohash": ("F3", "filter.location.geohash", "str", "Only results whose geohash starts with this", "9v6k"),
    "exclude_near": ("F3", "filter.exclude.location.query", "str", "Leave out an area by name", "Downtown Austin"),
    "exclude_location": ("F3", "filter.exclude.location", "str", "Leave out a WKT area or locality id", "POINT(-97.74 30.27)"),
    "exclude_geohash": ("F3", "filter.exclude.location.geohash", "str", "Leave out results whose geohash starts with this", "9v6kp"),
    "city": ("F3", "filter.geocode.name", "str", "Exact city or town name", "Austin"),
    "admin1": ("F3", "filter.geocode.admin1_region", "str", "Exact state or region", "Texas"),
    "admin2": ("F3", "filter.geocode.admin2_region", "str", "Exact county or borough", "Travis County"),
    "country": ("F3", "filter.geocode.country_code", "str", "Two-letter country code", "US"),
    # F4 at what price, where
    "price_level": ("F4", "filter.dimensions.price_level", "list:1|2|3|4", "Price tier: 1 (cheap) to 4 (dear), mapped where it is hot", "1"),
    "hotel_class": ("F4", "filter.dimensions.hotel_class", "list:1|2|3|4|5", "Hotel classes 1-5, mapped where they are hot", "4,5"),
    "price_from": ("F4", "filter.price_range.from", "int", "Hotel price range from (0-1,000,000)", 100),
    "price_to": ("F4", "filter.price_range.to", "int", "Hotel price range to (0-1,000,000)", 300),
    "price_level_min": ("F4", "filter.price_level.min", "int", "Places at price level at least (1-4)", 2),
    "price_level_max": ("F4", "filter.price_level.max", "int", "Places at price level at most (1-4)", 3),
    "hotel_class_min": ("F4", "filter.hotel_class.min", "int", "Hotel class at least (1-5)", 3),
    "hotel_class_max": ("F4", "filter.hotel_class.max", "int", "Hotel class at most (1-5)", 5),
    "business_rating_min": ("F4", "filter.properties.business_rating.min", "float", "Business rating at least", 3.5),
    "business_rating_max": ("F4", "filter.properties.business_rating.max", "float", "Business rating at most", 5.0),
    # F5 who serves or stocks it
    "references_brand": ("F5", "filter.references_brand", "str", "Who serves it: a brand by name or id; only places tied to it", "Whole Foods Market"),
    "quality": ("F5", "bias.quality", "enum:low|medium|high", "Lean the ranking toward quality places", "high"),
    "sort": ("F5", "sort_by", "enum:affinity|distance|rating|quality", "Order places by", "quality"),
    "open_on": ("F5", "filter.hours", "str", "Open on this day", "Sunday"),
    "address": ("F5", "filter.address", "str", "Address contains", "Congress Ave"),
    "tripadvisor_rating_min": ("F5", "filter.external.tripadvisor.rating.min", "float", "Tripadvisor rating at least", 4.0),
    "tripadvisor_rating_max": ("F5", "filter.external.tripadvisor.rating.max", "float", "Tripadvisor rating at most", 5.0),
    "tripadvisor_count_min": ("F5", "filter.external.tripadvisor.rating.count.min", "int", "Tripadvisor reviews at least", 100),
    "tripadvisor_count_max": ("F5", "filter.external.tripadvisor.rating.count.max", "int", "Tripadvisor reviews at most", 5000),
    "resy_rating_min": ("F5", "filter.external.resy.rating.min", "float", "Resy rating at least (1-5)", 4.0),
    "resy_rating_max": ("F5", "filter.external.resy.rating.max", "float", "Resy rating at most (1-5)", 5.0),
    "resy_count_min": ("F5", "filter.external.resy.count.min", "int", "Resy rating count at least", 100),
    "resy_count_max": ("F5", "filter.external.resy.count.max", "int", "Resy rating count at most", 10000),
    "resy_party_min": ("F5", "filter.external.resy.party_size.min", "int", "Resy party size at least", 2),
    "resy_party_max": ("F5", "filter.external.resy.party_size.max", "int", "Resy party size at most", 8),
    "external": ("F5", "filter.external.exists", "list:resy|michelin|tablet", "Listed on these (resy, michelin, tablet)", "resy"),
    "external_operator": ("F5", "operator.filter.external.exists", "enum:union|intersection", "Any (union) or all (intersection) of those", "union"),
    # F6 media and people products
    "product_kind": ("F6", "filter.type", "enum:" + "|".join(KINDS), "Product kind: what the comparables are", "film"),
    "content_rating": ("F6", "filter.content_rating", "str", "Film/TV content rating(s), MPAA", "PG-13"),
    "year_min": ("F6", "filter.release_year.min", "int", "Released from this year (film/TV; books: publication year)", 2015),
    "year_max": ("F6", "filter.release_year.max", "int", "Released up to this year (film/TV; books: publication year)", 2024),
    "release_country": ("F6", "filter.release_country", "str", "Film/TV released in these countries", "United States"),
    "release_country_operator": ("F6", "operator.filter.release_country", "enum:union|intersection", "Any (union) or all (intersection) of those", "union"),
    "rating_min": ("F6", "filter.rating.min", "float", "Film/TV Qloo rating at least (0-5)", 3.5),
    "rating_max": ("F6", "filter.rating.max", "float", "Film/TV Qloo rating at most (0-5)", 5.0),
    "finale_year_min": ("F6", "filter.finale_year.min", "int", "TV: final season from this year", 2018),
    "finale_year_max": ("F6", "filter.finale_year.max", "int", "TV: final season up to this year", 2024),
    "latest_year_min": ("F6", "filter.latest_known_year.min", "int", "TV: released or updated from this year", 2020),
    "latest_year_max": ("F6", "filter.latest_known_year.max", "int", "TV: released or updated up to this year", 2025),
    "born_min": ("F6", "filter.date_of_birth.min", "str", "Person: born on or after (YYYY-MM-DD)", "1960-01-01"),
    "born_max": ("F6", "filter.date_of_birth.max", "str", "Person: born on or before (YYYY-MM-DD)", "1990-12-31"),
    "died_min": ("F6", "filter.date_of_death.min", "str", "Person: died on or after (YYYY-MM-DD)", "2000-01-01"),
    "died_max": ("F6", "filter.date_of_death.max", "str", "Person: died on or before (YYYY-MM-DD)", "2020-12-31"),
    "person_gender": ("F6", "filter.gender", "enum:male|female", "Person: gender", "female"),
    # F7 look up exact things
    "lookup": ("F7", "query", "str", "Look up exact things: a name to find (Search Entities)", "Austin"),
    "lookup_types": ("F7", "types", "list:" + "|".join(sorted({*KINDS.values(), "urn:entity:locality", "urn:entity:actor", "urn:entity:author",
                                                                  "urn:entity:director", "urn:entity:album"})), "What kinds to search", "urn:entity:locality"),
    "lookup_near": ("F7", "filter.location", "str", "Search near: lat,lon or WKT", "30.2672,-97.7431"),
    "lookup_radius": ("F7", "filter.radius", "float", "Search radius in miles (0-100)", 10),
    "lookup_sort": ("F7", "sort_by", "enum:match|distance|popularity", "Order the search by", "match"),
    "entity_id": ("F7", "entity_ids", "ids", "Look up exact things: paste a Qloo entity id (Search Entities by ID)", "B2A5BF4D-6D9A-4A8B-9E50-1A2B3C4D5E6F"),
    # F8 everything else in the Entity Type Parameter Guide, by its own name
    "qloo": ("F8", "*", "object", "Any other documented parameter for the call's filter.type, by its Qloo name", {"bias.trends": "high"}),
    "qloo_calls": ("F8", "*", "object", "Calls to Qloo's other endpoints by path, each with its own documented parameters",
                   {"/v2/tags": {"filter.query": "trail running", "feature.semantic_search": "true"}}),
}
# the one plain control per family (the label in brackets in the task) and its fields; the rest go under Advanced
PLAIN = {"F1": ("Who", ("age", "gender")), "F2": ("Gaps", ("hide_leader", "popularity_max")), "F3": ("Where", ("near", "radius")),
         "F4": ("Price tier", ("price_level",)), "F5": ("Who serves it", ("references_brand",)), "F6": ("Product kind", ("product_kind", "year_min", "year_max")),
         "F7": ("Look up", ("lookup", "entity_id")), "F8": ("More Qloo", ("qloo", "qloo_calls"))}
QUESTIONS = {"F1": "Who wants it", "F2": "What is underserved", "F3": "Where to launch", "F4": "At what price, where",
             "F5": "Who serves or stocks it", "F6": "Media and people products", "F7": "Look up exact things", "F8": "Anything else in the guide"}
# where docs.qloo.com disagrees with itself or with the task, and what the live API acts on (checked 21 Oct 2026)
NOTES = [
    "filter.type for games is urn:entity:videogame: urn:entity:video_game is answered 400 'not supported for filter.type'.",
    "signal.demographics.age takes 24_and_younger, 25_to_29, 30_to_34, 35_to_44, 45_to_54, 55_and_older (Parameter Reference); "
    "the task's '35_and_younger' is not one of them, so F1's check compares 24_and_younger with 55_and_older.",
    "Hotel price range: the Entity Type Parameter Guide says filter.price_range.from/to, the Parameter Reference says .min/.max; "
    "the API acts on from/to (min/max returned the unfiltered list).",
    "Resy: the Guide says filter.properties.resy.rating.*, filter.resy.rating_count.*, filter.resy.rating.party.*; the Parameter "
    "Reference says filter.external.resy.rating.*, .count.*, .party_size.*; the API acts on the filter.external.resy.* names.",
    "heatmap.dimensions with filter.dimensions.price_level/hotel_class applies only with filter.type=urn:heatmap and "
    "output.heatmap.boundary=urn:geohash (Parameter Reference).",
]


def flag(name: str) -> str:
    return "--" + name.replace("_", "-")


def schema(name: str) -> dict:
    """The JSON Schema of one field (the /mcp tool and OpenAPI use it), with Qloo's name and an example."""
    fam, param, kind, help_, example = FIELDS[name]
    desc = f"{QUESTIONS[fam]} ({fam}): {help_}. Qloo: {param}."
    if kind == "bool":
        s: dict = {"type": "boolean"}
    elif kind == "int":
        s = {"type": "integer"}
    elif kind == "float":
        s = {"type": "number"}
    elif kind == "object":
        s = {"type": "object", "additionalProperties": True}
    elif kind == "names":
        s = {"type": "array", "items": {"type": "string"}, "description": "names, or one comma-separated string"}
    elif kind.startswith("enum:"):
        s = {"type": "string", "enum": kind[5:].split("|")}
    elif kind.startswith("list:"):
        s = {"type": "string", "description": "comma-separated, of: " + kind[5:].replace("|", ", ")}
    else:
        s = {"type": "string"}
    return {**s, "description": (desc + " " + s.get("description", "")).strip(), "examples": [example]}


def coerce(name: str, value):
    """One field's value checked and normalised (raises ValueError naming the field); None stays unset."""
    if value is None or value == "" or value == []:
        return None
    fam, param, kind, _, _ = FIELDS[name]
    try:
        if kind == "bool":
            if isinstance(value, str):
                return value.strip().lower() in ("1", "true", "yes", "on")
            return bool(value)
        if kind == "int":
            return int(value)
        if kind == "float":
            return float(value)
        if kind == "object":
            if not isinstance(value, dict):
                raise ValueError
            return {str(k)[:80]: v for k, v in list(value.items())[:30]}
        if kind == "names":
            items = [str(v).strip()[:120] for v in (value if isinstance(value, (list, tuple)) else str(value).split(",")) if str(v).strip()]
            if not items:
                raise ValueError
            return items[:10]
        text = ",".join(str(v).strip() for v in value) if isinstance(value, (list, tuple)) else str(value).strip()
        if kind.startswith("enum:"):
            if text not in kind[5:].split("|"):
                raise ValueError
            return text
        if kind.startswith("list:"):
            items = [v.strip() for v in text.split(",") if v.strip()]
            allowed = kind[5:].split("|")
            if not items or any(v not in allowed for v in items):
                raise ValueError
            return ",".join(items)
        return text[:300]
    except (TypeError, ValueError):
        raise ValueError(f"{name}: {FIELDS[name][3].lower()} ({kind})") from None


def options(raw: dict | None) -> dict:
    """Every known field from a body, an MCP call or CLI flags, checked; unknown names are refused, not ignored."""
    raw = dict(raw or {})
    unknown = sorted(k for k in raw if k not in FIELDS)
    if unknown:
        raise ValueError(f"unknown demand option(s): {', '.join(unknown)} (see knos_wanted.families / docs/qloo)")
    out = {k: coerce(k, v) for k, v in raw.items()}
    # a WKT area typed where a name goes: Qloo reads filter.location.query as a name ("POINT(...)" found High Point, NC),
    # so it is sent as filter.location, the parameter Qloo documents for WKT
    if isinstance(out.get("near"), str) and WKT.match(out["near"]) and not out.get("location"):
        out["location"] = out.pop("near")
    return {k: v for k, v in out.items() if v is not None}
