"""The open signals (knos_wanted.open_signals): the baseline's rules, each source named, nothing invented, and
nothing asked off the hosted app. The network is a fake: each public API answers what a test sets."""
from knos_wanted import open_signals as o


def fake(answers):
    def get(url, timeout=4.0):
        for part, body in answers.items():
            if part in url:
                return body
        return None
    return get


ANSWERS = {
    "rest.php/v1/search/page": {"pages": [{"key": "Perovskite_solar_cell"}]},
    "pageviews/per-article": {"items": [{"views": 300}, {"views": 100}]},
    "prop=pageprops": {"query": {"pages": {"1": {"pageprops": {"wikibase_item": "Q123"}}}}},
    "api.gdeltproject.org": {"timeline": [{"data": [{"value": 30}, {"value": 40}]}]},
    "hn.algolia.com": {"nbHits": 2},
    "api.openalex.org": {"meta": {"count": 5000}},
    "api.worldbank.org": [{}, [{"value": 85000.5, "date": "2025"}]],
    "wbgetentities": {"entities": {"Q123": {"labels": {"en": {"value": "perovskite solar cell"}}, "descriptions": {"en": {"value": "a solar cell"}}}}},
}


def test_the_baseline_counts_attention_and_names_every_source(monkeypatch):
    monkeypatch.setattr(o, "_get", fake(ANSWERS))
    monkeypatch.setattr(o.time, "sleep", lambda s: None)
    monkeypatch.setenv("KNOS_OPEN_SIGNALS", "on")
    r = o.baseline("a perovskite solar roof tile for homes")
    assert r["phrase"] == "perovskite solar"
    by = {s["source"]: s for s in r["signals"]}
    assert by["Wikimedia pageviews"]["views_per_day"] == 200 and by["Wikimedia pageviews"]["counts"]
    assert by["GDELT news"]["articles_3_months"] == 70 and by["GDELT news"]["counts"]
    assert by["Hacker News"]["stories_2_years"] == 2 and not by["Hacker News"]["counts"]
    assert by["OpenAlex"]["works_since_2023"] == 5000 and by["World Bank"]["gdp_per_person_usd"] == 85000 and by["Wikidata"]["label"]
    assert all(s["link"].startswith("https://") for s in r["signals"])
    # three of four count: OPEN; open sources say nothing of who or where, and no venue price: mid at most
    assert r["verdict"] == "OPEN" and r["attention_counted"] == 3 and r["audience"] is None and r["cities"] == [] and r["price_tier"] == "mid"


def test_no_answer_is_cannot_decide_and_little_attention_is_refuse(monkeypatch):
    monkeypatch.setattr(o, "_get", fake({}))
    monkeypatch.setattr(o.time, "sleep", lambda s: None)
    monkeypatch.setenv("KNOS_OPEN_SIGNALS", "on")
    r = o.baseline("a thing nobody writes about")
    assert r["verdict"] == "CANNOT_DECIDE" and r["price_tier"] is None and not any(s["answered"] for s in r["signals"])
    quiet = {**ANSWERS, "pageviews/per-article": {"items": [{"views": 3}]}, "api.gdeltproject.org": {"timeline": [{"data": []}]}, "api.openalex.org": {"meta": {"count": 10}}}
    monkeypatch.setattr(o, "_get", fake(quiet))
    assert o.baseline("a perovskite solar roof tile")["verdict"] == "REFUSE"


def test_off_the_hosted_app_no_source_is_asked(monkeypatch):
    monkeypatch.setattr(o, "_get", lambda *a, **k: (_ for _ in ()).throw(AssertionError("a source was asked")))
    r = o.baseline("a perovskite solar roof tile")
    assert r["verdict"] == "CANNOT_DECIDE" and not any(s["answered"] for s in r["signals"])
    fb = o.fallback("a perovskite solar roof tile")
    assert fb["verdict"] == "CANNOT_DECIDE" and [x["name"] for x in fb["rows"]] == ["Money down"]
