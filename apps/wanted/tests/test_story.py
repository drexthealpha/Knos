"""One card, one story (the decision sentence, each open signal's row with its unit, the sources and the rule), the model
only with a key and under its caps, and "Was this useful?" kept with a salted visitor hash, never an address."""
import pytest

from knos_wanted import model, story

ROWS = [{"name": "Wikipedia", "value": 296, "unit": "views a day (last 60 days)", "link": "https://en.wikipedia.org/wiki/Ramen", "counts": True},
        {"name": "Hacker News", "value": 1200, "unit": "stories in 2 years", "link": "https://hn.algolia.com/", "counts": True},
        {"name": "Money down", "value": 12.5, "unit": "test money, 1 pre-orders here", "counts": True}]
OPEN = {"hash": "a" * 64, "idea": "a late night ramen spot", "made": "2026-10-29T20:00:00Z", "place": None,
        "decision": {"verdict": "OPEN", "reasons": ["Sources: Wikipedia, Hacker News, pre-orders here."], "target_units": None},
        "open_demand": {"verdict": "OPEN", "rows": ROWS, "phrase": "late night", "head": "Open signals say people want this",
                        "line": "Sources: Wikipedia, Hacker News, pre-orders here.", "rule": "People want it when 2 of these pass."}}
REFUSE = {**OPEN, "decision": {"verdict": "REFUSE", "reasons": ["Sources: Wikipedia."]},
          "open_demand": {**OPEN["open_demand"], "verdict": "REFUSE", "head": "Open signals find little interest yet", "rows": ROWS[:1]}}


def test_an_open_card_leads_with_its_head_and_each_row_with_its_unit():
    s = story.build(OPEN)
    assert s["sentence"] == "Open signals say people want this"
    assert [t["label"] for t in s["tiles"]] == ["Wikipedia", "Hacker News", "Money down"]
    assert s["tiles"][1]["value"] == "1,200 stories in 2 years" and s["tiles"][2]["value"] == "$12.50 test money, 1 pre-orders here"
    assert s["tiles"][0]["link"] == ROWS[0]["link"] and "link" not in s["tiles"][2]
    assert s["used"] == {"phrase": "late night", "line": "Sources: Wikipedia, Hacker News, pre-orders here. People want it when 2 of these pass."}
    assert s["downloads"] == [] and s["reruns"] == []


def test_a_refusal_says_so_in_its_own_words():
    s = story.build(REFUSE)
    assert s["sentence"] == "Open signals find little interest yet" and len(s["tiles"]) == 1
    assert story.build({"decision": {"verdict": "CANNOT_DECIDE"}})["sentence"] == "No signal yet"


def test_the_model_needs_the_key_and_keeps_its_caps(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert model.state() == "off"
    with pytest.raises(model.Refused, match=model.NEEDS_KEY):
        model.follow_up(OPEN, "where first?")
    monkeypatch.setattr(model, "_day", {"day": None, "n": 0})
    monkeypatch.setattr(model, "_per", {})
    seen = []
    got = model.follow_up(OPEN, "who reads about it?", provider=lambda prompt: (seen.append(prompt), "Wikipedia readers [source 1].")[1])
    assert got["cites"] == [1] and got["model"] == "stub"
    assert "[source 1] Wikipedia: 296 views a day (last 60 days)" in seen[0]
    with pytest.raises(model.Refused, match="already had its 1 model call"):
        model.follow_up(OPEN, "again?", provider=lambda p: "x")
    model._day["n"] = model.PER_DAY
    with pytest.raises(model.Refused, match="200 calls for today are used"):
        model.follow_up({**OPEN, "hash": "b" * 64}, "q", provider=lambda p: "x")
    assert "sk-" not in str(got)


def test_feedback_keeps_a_salted_visitor_hash_and_never_an_address(monkeypatch):
    from knos_wanted import usage
    store: dict = {}
    monkeypatch.setattr(usage, "_doc", lambda: store.setdefault("d", {"checks": 0, "briefs": 0}))
    monkeypatch.setattr("knos_wanted.valley._save", lambda kind, key, d: store.update(d=d))
    vh = usage.visitor_hash("203.0.113.9", b"test salt")
    got = usage.feedback("a" * 64, True, "useful, thanks", vh)
    assert got["saved"] and got["feedback_yes"] == 1 and got["feedback_no"] == 0
    kept = str(store["d"]["feedback"])
    assert "203.0.113.9" not in kept and "@" not in kept and vh[:16] in kept
