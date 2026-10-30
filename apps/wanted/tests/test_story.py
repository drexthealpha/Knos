"""R2: one card, one story (decision sentence, tiles, used words, reruns, rejected list, downloads), the model only with
a key and under its caps, and "Was this useful?" kept with a salted visitor hash, never an address."""
import pytest

from knos_wanted import model, story

OPEN = {"hash": "a" * 64, "idea": "a late night ramen spot", "made": "2026-10-29T20:00:00Z", "place": None,
        "decision": {"verdict": "OPEN", "reasons": ["r"], "target_units": 120, "reserve_units": 36},
        "terms": {"city": "Seattle-Tacoma-Bellevue, WA"}, "audiences": [{"name": "Foodies", "lift": 0.012, "src": 7}],
        "price": {"tier": "mid", "src": 9}, "qloo_calls": {"live": 14, "recorded": 3, "ms": 8200},
        "taste_answer": {"tags": [{"name": "Late Night Ramen", "id": "urn:tag:x", "src": 3}]},
        "calls": [{"n": 1, "what": "closest existing products", "out": "x"}, {"n": 7, "what": "audience segments: lift of Foodies", "out": "y"}]}
REFUSE = {**OPEN, "decision": {"verdict": "REFUSE", "reasons": ["audience too thin: 1 audience segments separated by Qloo (needs 3)"]},
          "unrelated": [{"name": "Top Ramen", "why": "shares too few content words with the idea"}],
          "calls": [{"n": 1, "what": "who: age", "error": "Qloo could not answer this part (HTTP 400)"}]}


def test_an_open_card_leads_with_its_decision_and_offers_three_downloads_built_from_its_numbers():
    s = story.build(OPEN)
    assert s["sentence"] == "Wanted: open pre-orders in Seattle-Tacoma-Bellevue, WA, for Foodies."
    assert [t["label"] for t in s["tiles"]] == ["Top place", "Top audience", "Price tier", "Qloo calls"]
    assert s["tiles"][3]["value"] == "14 live, 3 recorded, 8.2 s"
    assert [d["kind"] for d in s["downloads"]] == ["preorder", "outreach", "refund.ics"]
    body, ctype, _ = story.download(OPEN, "preorder")
    assert "120 pre-orders" in body and "36 of them" in body and "Seattle-Tacoma-Bellevue, WA" in body and "2026-11-28" in body
    ics = story.download(OPEN, "refund.ics")[0]
    assert "DTSTART;VALUE=DATE:20261128" in ics and ctype.startswith("text/plain")
    assert story.download(REFUSE, "preorder") is None


def test_the_used_line_names_only_the_inputs_own_words():
    u = story.build(OPEN)["used"]
    assert u["used"] == ["late", "night", "ramen"] and u["not_in_qloo"] == ["spot"]
    assert u["line"].startswith("Used: late, night, ramen (tag Late Night Ramen).") and "Not in Qloo: spot" in u["line"]


def test_a_refusal_is_never_a_dead_end():
    s = story.build(REFUSE)
    assert s["sentence"].startswith("Not yet: audience too thin")
    assert 1 <= len(s["reruns"]) <= 3 and s["reruns"][0]["label"] == "Try the tag Late Night Ramen"
    assert s["rejected"] and any(r["name"] == "Top Ramen" for r in s["rejected"]) and not s["downloads"]


def test_the_model_needs_the_key_and_keeps_its_caps(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert model.state() == "off"
    with pytest.raises(model.Refused, match=model.NEEDS_KEY):
        model.follow_up(OPEN, "where first?")
    monkeypatch.setattr(model, "_day", {"day": None, "n": 0})
    monkeypatch.setattr(model, "_per", {})
    got = model.follow_up(OPEN, "who buys it?", provider=lambda prompt: "Foodies lead [call 7], from the lift.")
    assert got["cites"] == [7] and got["model"] == "stub"
    with pytest.raises(model.Refused, match="already had its 1 model call"):
        model.follow_up(OPEN, "again?", provider=lambda p: "x")
    model._day["n"] = model.PER_DAY
    with pytest.raises(model.Refused, match="200 calls for today are used"):
        model.follow_up({**OPEN, "hash": "b" * 64}, "q", provider=lambda p: "x")
    assert "sk-" not in str(got)


def test_feedback_keeps_a_salted_visitor_hash_and_never_an_address(monkeypatch):
    from knos_wanted import qloo_rest, usage
    store: dict = {}
    monkeypatch.setattr(usage, "_doc", lambda: store.setdefault("d", {"checks": 0, "briefs": 0}))
    monkeypatch.setattr("knos_wanted.valley._save", lambda kind, key, d: store.update(d=d))
    vh = qloo_rest.visitor_hash("203.0.113.9", b"test salt")
    got = usage.feedback("a" * 64, True, "useful, thanks", vh)
    assert got["saved"] and got["feedback_yes"] == 1 and got["feedback_no"] == 0
    kept = str(store["d"]["feedback"])
    assert "203.0.113.9" not in kept and "@" not in kept and vh[:16] in kept


def test_a_refusal_with_nothing_else_rejected_names_the_rule_that_refused_it():
    rep = {"idea": "a quiet idea", "decision": {"verdict": "REFUSE", "reasons": ["no product of this taste wants it"]}}
    assert story.rejected(rep) == [{"name": "a quiet idea", "rule": "no product of this taste wants it"}]
    assert story.rejected({**rep, "decision": {"verdict": "OPEN", "reasons": ["x"]}}) == []
