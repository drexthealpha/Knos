"""A4: demand never breaks. With Qloo giving nothing, the open signals and money put down answer, named in one line."""
from knos_wanted import open_signals


def _fake(idea, country="US"):
    return {"phrase": "tea shop", "signals": [
        {"source": "Wikimedia pageviews", "answered": True, "views_per_day": 296.4, "counts": True, "link": "https://en.wikipedia.org/wiki/Tea"},
        {"source": "GDELT news", "answered": False},
        {"source": "Hacker News", "answered": True, "stories_2_years": 6, "counts": True, "link": "https://hn.algolia.com/"},
        {"source": "OpenAlex", "answered": True, "works_since_2023": 120, "counts": False, "link": "https://openalex.org/"},
        {"source": "World Bank", "answered": True, "gdp_per_person_usd": 80000}, {"source": "Wikidata", "answered": False}]}


def test_the_fallback_answers_with_units_and_names_its_sources(monkeypatch):
    monkeypatch.setattr(open_signals, "baseline", _fake)
    monkeypatch.setattr(open_signals, "held_for", lambda idea: {"usd": 0.0, "count": 0})
    open_signals._answers.clear()
    fb = open_signals.fallback("a herbal tea shop for students")
    assert fb["verdict"] == "OPEN" and fb["head"] == "Open signals say people want this"
    assert [r["name"] for r in fb["rows"]] == ["Wikipedia", "Hacker News", "Research papers", "Money down"]
    assert fb["rows"][0]["value"] == 296 and all(r["unit"] for r in fb["rows"])
    assert fb["line"] == "Sources: Wikipedia, Hacker News, OpenAlex, pre-orders here."
    assert "Qloo" not in fb["line"] + fb["rule"] + fb["head"]


def test_it_steps_in_only_when_qloo_gave_nothing():
    assert open_signals.needs_fallback({"decision": {"verdict": "CANNOT_DECIDE"}})
    assert open_signals.needs_fallback({"queued": True})
    assert open_signals.needs_fallback({"decision": {"verdict": "REFUSE"}, "matches": [], "tags": []})
    assert not open_signals.needs_fallback({"decision": {"verdict": "OPEN"}, "matches": [{"name": "x"}]})
    assert not open_signals.needs_fallback({"decision": {"verdict": "CANNOT_DECIDE"}, "stale": {"code": 429}})   # a real answer kept
    assert not open_signals.needs_fallback({"kind": "which_one"})
