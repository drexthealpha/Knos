"""The Qloo demand families F1-F8 (knos.qloo_families + knos_wanted.families) on SYNTHETIC answers shaped like Qloo's:
each family sends exactly its documented parameters, names everything it asks, and its answer reaches the grounding; every
interface reads the one table of names (the /mcp tools, OpenAPI, the CLI, the app and front-door controls)."""
from pathlib import Path

import pytest

from knos import demand_cli
from knos import qloo_families as Q
from knos_wanted import agent, check, families, openapi
from test_check import TODAY, FakeQloo


class Fake(FakeQloo):
    def body(self, path, p):
        if path == "/entities":
            return {"results": [{"name": "Austin", "entity_id": p["entity_ids"], "types": ["urn:entity:locality"]}]}
        if path == "/v2/tags":
            return {"results": {"tags": [{"name": "Trail Running", "id": "urn:tag:interests:qloo:trail_running"}]}}
        return super().body(path, p)


def run(options, idea="A smart water bottle that glows to remind you to drink", place="Lagos"):
    fake = Fake()
    return check.demand_check(idea, place, client=fake, today=TODAY, options=options), fake


def sent(fake, what="/v2/insights"):
    return [p for path, p in fake.seen if path == what]


def test_the_table_names_every_family_and_each_field_once():
    assert set(Q.QUESTIONS) == {f"F{i}" for i in range(1, 9)}
    assert {v[0] for v in Q.FIELDS.values()} == set(Q.QUESTIONS)
    for fam, (label, plain) in Q.PLAIN.items():
        assert label and all(Q.FIELDS[f][0] == fam for f in plain)
    assert Q.FIELDS["age"][2] == "list:" + "|".join(Q.AGES) and "35_and_younger" not in Q.AGES          # the docs' values win
    assert Q.FIELDS["price_from"][1] == "filter.price_range.from" and Q.FIELDS["resy_rating_min"][1] == "filter.external.resy.rating.min"


def test_options_are_checked_and_unknown_names_refused():
    assert Q.options({"age": ["24_and_younger", "55_and_older"], "radius": "5000", "hide_leader": "yes", "popularity_max": "0.5"}) == {
        "age": "24_and_younger,55_and_older", "radius": 5000, "hide_leader": True, "popularity_max": 0.5}
    with pytest.raises(ValueError, match="unknown demand option"):
        Q.options({"agee": "x"})
    with pytest.raises(ValueError, match="age"):
        Q.options({"age": "35_and_younger"})
    assert Q.options({"exclude_names": "Nike, Adidas"}) == {"exclude_names": ["Nike", "Adidas"]}


def test_f1_who_weights_the_comparables_by_age_and_gender():
    rep, fake = run({"age": "24_and_younger", "gender": "female"})
    p = sent(fake)[-1]
    assert p["signal.demographics.age"] == "24_and_younger" and p["signal.demographics.gender"] == "female" and p["filter.type"] == "urn:entity:brand"
    f1 = rep["families"]["F1"]
    assert f1["question"] == "Who wants it" and f1["call"] and f1["answer"]


def test_f2_gaps_hide_the_leader_and_cap_popularity_without_broadening():
    rep, fake = run({"hide_leader": True, "popularity_max": 0.5})
    p = sent(fake)[-1]
    lead = rep["leader"]["id"]
    assert lead in p["filter.exclude.entities"] and p["filter.popularity.max"] == 0.5
    assert not any("broadened" in c["what"] for c in rep["calls"] if c["what"].startswith("families"))      # an explicit cap is kept


def test_f2_names_are_found_in_the_ideas_kind_and_sent_by_id():
    rep, fake = run({"exclude_names": ["Glow Bottle (synthetic)"]})
    assert any(path == "/search" and p.get("types") == "urn:entity:brand" for path, p in fake.seen)
    assert "filter.exclude.entities.query" not in sent(fake)[-1] and sent(fake)[-1]["filter.exclude.entities"]


def test_f3_where_sends_location_radius_and_exclusions_on_places():
    rep, fake = run({"near": "Austin", "radius": 500, "exclude_near": "Downtown Austin", "country": "US"})
    p = [x for x in sent(fake) if x.get("filter.type") == "urn:entity:place"][-1]
    assert (p["filter.location.query"], p["filter.location.radius"], p["filter.exclude.location.query"], p["filter.geocode.country_code"]) == (
        "Austin", 500, "Downtown Austin", "US")


def test_f4_price_tier_maps_the_heatmap_without_the_refused_boundary():
    rep, fake = run({"price_level": "1", "price_from": 100, "price_to": 300})
    h = [x for x in sent(fake) if x.get("filter.type") == "urn:heatmap" and "heatmap.dimensions" in x][-1]
    assert h["heatmap.dimensions"] == "price_level" and h["filter.dimensions.price_level"] == "1" and "output.heatmap.boundary" not in h   # Qloo refuses it (400)
    places = [x for x in sent(fake) if x.get("filter.type") == "urn:entity:place" and "filter.price_range.from" in x][-1]
    assert places["filter.price_range.to"] == 300
    assert "hot" in rep["families"]["F4"]


def test_f5_who_serves_it_resolves_the_brand_and_sorts_by_quality():
    rep, fake = run({"references_brand": "Water Bottle Co", "sort": "quality", "quality": "high", "resy_rating_min": 4.0})
    assert any(path == "/search" and p.get("types") == "urn:entity:brand" for path, p in fake.seen)
    p = [x for x in sent(fake) if x.get("filter.type") == "urn:entity:place"][-1]
    assert p["filter.references_brand"].startswith("E") and p["sort_by"] == "quality" and p["bias.quality"] == "high"
    assert p["filter.external.resy.rating.min"] == 4.0


def test_f6_product_kind_and_years_book_years_are_publication_years():
    rep, fake = run({"product_kind": "film", "year_min": 2015, "year_max": 2024, "content_rating": "PG-13"})
    p = sent(fake)[-1]
    assert (p["filter.type"], p["filter.release_year.min"], p["filter.release_year.max"], p["filter.content_rating"]) == ("urn:entity:movie", 2015, 2024, "PG-13")
    rep, fake = run({"product_kind": "book", "year_min": 1990})
    p = sent(fake)[-1]
    assert p["filter.type"] == "urn:entity:book" and p["filter.publication_year.min"] == 1990 and "filter.release_year.min" not in p


def test_f7_lookup_by_name_and_by_id():
    rep, fake = run({"lookup": "Austin", "lookup_types": "urn:entity:locality", "lookup_sort": "match", "entity_id": "C93C0541-F43D-484E-AC86-E27A54E5B1D0"})
    s = [p for path, p in fake.seen if path == "/search" and p.get("query") == "Austin"][-1]
    assert s["types"] == "urn:entity:locality" and s["sort_by"] == "match"
    assert rep["families"]["F7"]["by_id"]["answer"][0]["id"] == "C93C0541-F43D-484E-AC86-E27A54E5B1D0"


def test_f8_more_takes_only_what_the_guide_documents_for_the_type():
    rep, fake = run({"age": "35_to_44", "qloo": {"bias.trends": "high", "filter.hotel_class.min": 3},
                     "qloo_calls": {"/v2/tags": {"filter.query": "trail", "nope": 1}, "/not-an-endpoint": {"x": 1}}})
    p = sent(fake)[-1]
    assert p["bias.trends"] == "high" and "filter.hotel_class.min" not in p                    # a Place parameter on a brand call
    assert "filter.hotel_class.min" in rep["families"]["F8_refused"]["params"] or "nope" in rep["families"]["F8_refused"]["params"]
    tags = [p for path, p in fake.seen if path == "/v2/tags" and p.get("filter.query") == "trail"]
    assert tags and "nope" not in tags[-1] and rep["families"]["F8_calls"][0]["answer"][0]["name"] == "Trail Running"


def test_every_family_answer_reaches_the_grounding():
    rep, _ = run({"product_kind": "film", "year_min": 2015, "near": "Austin"})
    g = rep["grounding"]
    assert g.get("comparables") and rep["options"]["product_kind"] == "film"


def test_every_interface_reads_the_one_table():
    tools = {t["name"]: t for t in agent.TOOLS}
    for name in ("knos_demand_check", "knos_cross"):
        assert set(Q.FIELDS) <= set(tools[name]["inputSchema"]["properties"])
    body = openapi.document()["paths"]["/api/check"]["post"]["requestBody"]["content"]["application/json"]
    assert set(Q.FIELDS) <= set(body["schema"]["properties"]) and body["examples"]
    assert set(demand_cli.BY_FLAG.values()) == set(Q.FIELDS)
    assert demand_cli.parse(["--age", "24_and_younger", "--hide-leader", "--qloo", "bias.trends=high", "--radius=500"]) == {
        "age": "24_and_younger", "hide_leader": True, "qloo": {"bias.trends": "high"}, "radius": 500}
    with pytest.raises(ValueError, match="unknown option"):
        demand_cli.parse(["--agee", "x"])
    from knos import demand_tool
    assert set(Q.FIELDS) <= set(demand_tool.MCP_TOOLS[0]["properties"])
    spec = families.fields()
    assert {f["name"] for fam in spec["families"].values() for f in fam["fields"]} == set(Q.FIELDS)
    root = Path(__file__).resolve().parents[3]
    app_js = (root / "apps" / "wanted" / "knos_wanted" / "static" / "demand_opts.js").read_text(encoding="utf-8")
    assert app_js == (root / "web" / "demand_opts.js").read_text(encoding="utf-8")             # the old one-page app's copy
    for f in ("age", "gender", "hide_leader", "popularity_max", "near", "radius", "price_level", "references_brand", "product_kind", "year_min"):
        assert f'data-f="{f}"' in app_js


def test_a_wkt_launch_area_is_not_taken_for_a_phone_number():
    """F3's documented form (a WKT POINT or POLYGON) passes the personal-data guard; a phone number still does not."""
    import pytest

    from knos_wanted import privacy
    privacy.check({"near": "POINT(-97.74 30.27)", "location": "POLYGON((-97.8 30.2, -97.7 30.2, -97.7 30.3, -97.8 30.2))"})
    with pytest.raises(privacy.PersonalData):
        privacy.check({"near": "+1 512 555 0199"})
    with pytest.raises(privacy.PersonalData):
        privacy.check({"near": "POINT(1 2) call me on 512 555 0199"})


def test_a_wkt_point_typed_as_near_is_sent_as_filter_location():
    """Qloo reads filter.location.query as a name (live: "POINT(-97.74 30.27)" answered from High Point, NC), so a WKT area in
    `near` goes to `location` (filter.location), the parameter Qloo documents for WKT; a name stays a name."""
    from knos import qloo_families as Q
    assert Q.options({"near": "POINT(-97.74 30.27)", "radius": 500}) == {"location": "POINT(-97.74 30.27)", "radius": 500}
    assert Q.options({"near": "Austin"}) == {"near": "Austin"}


def test_f4_heatmap_uses_the_wkt_area_asked():
    """F4's heatmap is asked of the WKT area given (filter.location and its radius), not a place by name."""
    from knos_wanted import families
    seen = []

    class Run:
        def get(self, path, params, what, broaden=True):
            seen.append(dict(params))
            return {"results": {"heatmap": [], "entities": []}}, len(seen)

    families.answer(Run(), {}, "a recovery shoe", None, {"location": "POINT(-97.74 30.27)", "radius": 500, "price_level": "1"})
    heat = next(p for p in seen if p.get("filter.type") == "urn:heatmap")
    assert heat["filter.location"] == "POINT(-97.74 30.27)" and heat["filter.location.radius"] == 500 and "filter.location.query" not in heat
