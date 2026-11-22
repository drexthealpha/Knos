"""The demand check on open signals alone: the verdict by the published rule (2 sources pass), each row with its unit and
link, nothing asked off the hosted app, and no audience, city or pre-order target claimed. SYNTHETIC source answers."""
import pytest

from knos_wanted import check, open_signals, story

IDEA = "A smart water bottle that glows to remind you to drink"


def fake(views=296.4, articles=None, stories=6, works=120):
    def baseline(idea, country="US"):
        sig = [{"source": "Wikimedia pageviews", "answered": views is not None, "views_per_day": views, "counts": (views or 0) >= 100,
                "link": "https://en.wikipedia.org/wiki/Water_bottle"},
               {"source": "GDELT news", "answered": articles is not None, "articles_3_months": articles, "counts": (articles or 0) >= 50,
                "link": "https://api.gdeltproject.org/"},
               {"source": "Hacker News", "answered": stories is not None, "stories_2_years": stories, "counts": (stories or 0) >= 5,
                "link": "https://hn.algolia.com/"},
               {"source": "OpenAlex", "answered": works is not None, "works_since_2023": works, "counts": (works or 0) >= 200,
                "link": "https://openalex.org/"},
               {"source": "World Bank", "answered": False}, {"source": "Wikidata", "answered": False}]
        return {"phrase": open_signals.phrase(idea), "signals": [s for s in sig if s["answered"]] + [s for s in sig if not s["answered"]]}
    return baseline


def use_signals(monkeypatch, **kw):
    """The open sources on, answered by `fake` (other test files call this too)."""
    monkeypatch.setattr(open_signals, "held_for", lambda idea: {"usd": 0.0, "count": 0})
    monkeypatch.setenv("KNOS_OPEN_SIGNALS", "on")
    open_signals._answers.clear()
    monkeypatch.setattr(open_signals, "baseline", fake(**kw))


@pytest.fixture
def signals(monkeypatch):
    return lambda **kw: use_signals(monkeypatch, **kw)


def test_two_passing_sources_open_and_every_row_has_its_unit_and_link(signals):
    signals()
    rep = check.demand_check(IDEA)
    d = rep["decision"]
    assert d["verdict"] == "OPEN" and rep["kind"] == check.KIND and rep["label"] == check.LABEL
    rows = rep["open_demand"]["rows"]
    assert [r["name"] for r in rows] == ["Wikipedia", "Hacker News", "Research papers", "Money down"]
    assert all(r["unit"] for r in rows) and all(r["link"] for r in rows[:-1])
    assert d["reasons"] == ["Sources: Wikipedia, Hacker News, OpenAlex, pre-orders here."]
    assert d["target_units"] is None and d["reserve_units"] is None and rep["terms"] is None and rep["brief"] is None


def test_fewer_than_two_refuse_and_none_answering_cannot_decide(signals):
    signals(views=12.0, stories=1, works=20)
    assert check.demand_check(IDEA)["decision"]["verdict"] == "REFUSE"
    signals(views=None, articles=None, stories=None, works=None)
    rep = check.demand_check(IDEA)
    assert rep["decision"]["verdict"] == "CANNOT_DECIDE" and rep["open_demand"]["head"] == "No signal yet"


def test_off_the_hosted_app_no_source_is_asked_and_it_says_so(monkeypatch):
    monkeypatch.setattr(open_signals, "_get", lambda *a, **k: pytest.fail("a source was asked"))
    rep = check.demand_check(IDEA)
    assert rep["decision"]["verdict"] == "CANNOT_DECIDE" and check.OFF in rep["decision"]["reasons"]


def test_the_rules_claim_no_audience_and_no_city_and_the_hash_is_stable(signals):
    signals()
    a, b = check.demand_check(IDEA, place="UK"), check.demand_check(IDEA, place="UK")
    assert a["rules"]["audience"].startswith("none") and a["rules"]["cities"].startswith("none")
    assert a["hash"] == b["hash"] == check.report_hash(a)


def test_the_story_leads_with_the_head_and_the_rows(signals):
    signals()
    st = story.build(check.demand_check(IDEA))
    assert st["sentence"] == "Open signals say people want this"
    assert st["tiles"][0] == {"label": "Wikipedia", "value": "296 views a day (last 60 days)", "link": "https://en.wikipedia.org/wiki/Water_bottle"}
    assert st["tiles"][-1]["value"].startswith("$0.00 ") and "2 of these pass" in st["used"]["line"]


def test_an_idea_too_short_or_too_long_is_refused():
    for bad in ("ab", "x" * 501):
        with pytest.raises(ValueError):
            check.demand_check(bad)


def test_content_words_drop_grammar_audience_and_place():
    assert check.content_words("A vegan meal kit for students in Lagos", "Lagos") == ["vegan", "meal", "kit"]
    assert check.market_country("UK") == "GB" and check.market_country(None) == "US"
