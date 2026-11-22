"""Which one do you mean? asked by /api/check for a paper id before any check runs; a plain idea and a picked reading
are checked exactly as typed."""
from test_product_routes import app, call  # noqa: F401 - the fixture

from knos_wanted import which

PAPER = {"title": "A synthetic sensor paper", "year": 2016, "doi": "https://doi.org/10.1038/nature16521", "cited_by_count": 5000,
         "concepts": ["Wearable computer", "Biosensor"]}


def test_a_paper_is_asked_which_one_before_any_check(app, monkeypatch):  # noqa: F811
    monkeypatch.setattr(which.readings, "paper", lambda text, **_: PAPER)
    monkeypatch.setattr(which, "_products", lambda ref: ["a fitness watch with a sweat glucose sensor"])
    base, _ = app
    st, w = call(base, "/api/check", {"idea": "10.1038/nature16521"})
    assert st == 200 and w["kind"] == "which_one" and "decision" not in w
    texts = [r["text"] for r in w["readings"]]
    assert texts == ["10.1038/nature16521", "a fitness watch with a sweat glucose sensor"] and w["paper"]["title"] == PAPER["title"]


def test_a_plain_idea_is_checked_at_once(app, monkeypatch):  # noqa: F811
    monkeypatch.setattr(which.readings, "paper", lambda text, **_: None)
    base, _ = app
    st, rep = call(base, "/api/check", {"idea": "a vegan ramen food truck"})
    assert st == 200 and rep.get("kind") != "which_one" and rep["idea"] == "a vegan ramen food truck" and rep["decision"]["verdict"]


def test_a_picked_reading_is_checked_exactly(app, monkeypatch):  # noqa: F811
    monkeypatch.setattr(which.readings, "paper", lambda text, **_: PAPER)
    base, _ = app
    st, rep = call(base, "/api/check", {"idea": "10.1038/nature16521", "picked": True})
    assert st == 200 and rep.get("kind") != "which_one" and rep["idea"] == "10.1038/nature16521"
