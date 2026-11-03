"""When Qloo cannot answer a new idea, the card answers from the nearest idea Qloo has already answered, with no Qloo
call (knos_wanted.nearest, recorded.honest). SYNTHETIC reports only."""
from knos_wanted import nearest, recorded


def rep(idea, made, tags=()):
    return {"idea": idea, "made": made, "label": "LIVE Qloo data (synthetic test)", "stage": "full", "hash": idea.replace(" ", "")[:16].ljust(64, "0"),
            "tags": [{"id": f"t{i}", "name": t} for i, t in enumerate(tags)], "decision": {"verdict": "REFUSE", "reasons": []},
            "calls": [{"n": 1, "call": "GET /search", "params": {"query": idea}}]}


ANSWERED = [rep("a smart water bottle that glows", "2026-10-22T10:00:00Z", ["Hydration"]),
            rep("a bamboo toothbrush brand", "2026-10-22T11:00:00Z", ["Oral Care"]),
            rep("a water bottle that harvests water from air", "2026-10-22T12:00:00Z")]


def test_stop_words_drop_and_words_stem():
    assert nearest.stems("The Runners of a Festival") == {"runn", "festival"}


def test_the_most_shared_words_win_and_a_tie_goes_to_the_newest():
    got = nearest.find("a water bottle for hikers", ANSWERED)
    assert got["count"] == 2 and got["report"]["idea"] == "a water bottle that harvests water from air"   # tie at 2: newest
    got = nearest.find("a smart bottle that glows", ANSWERED)
    assert got["report"]["idea"] == "a smart water bottle that glows" and got["count"] == 3


def test_the_qloo_tags_names_count_too():
    assert nearest.shared("a hydration tracker", ANSWERED[0]) == 1
    assert nearest.find("an oral care subscription", ANSWERED)["report"]["idea"] == "a bamboo toothbrush brand"


def test_under_2_shared_only_ideas_sharing_a_stem_are_offered_and_none_shares_none():
    got = nearest.find("a vinyl record shop", ANSWERED)
    assert "report" not in got and got["options"] == [] and got["count"] == 0          # nothing shared: nobody's neighbour
    got = nearest.find("a hydration tracker", ANSWERED)
    assert got["options"] == ["a smart water bottle that glows"] and got["count"] == 1  # one stem, through a Qloo tag
    assert nearest.find("a water bottle for hikers", ANSWERED)["next"] == ["a smart water bottle that glows"]


def test_a_429_never_answers_with_the_nearest_idea_s_verdict(monkeypatch):
    monkeypatch.setattr(recorded, "_last", {})
    monkeypatch.setattr(recorded, "_answered", {recorded.key(r["idea"]): r for r in ANSWERED})
    failed = {"idea": "a smart bottle that glows", "calls": [{"n": 1, "error": "HTTP 429: not sent: the month is used up"}], "decision": {"verdict": "CANNOT_DECIDE"}}
    out = recorded.honest("a smart bottle that glows", failed)
    # no recording of this idea: said so; the nearest idea is offered by name, its verdict never shown as this one's
    assert out["no_recording"] == "no recorded answer for this idea" and out["idea"] == "a smart bottle that glows"
    assert "a smart water bottle that glows" in out["nearest_options"] and "nearest" not in out and "stale" not in out
    assert out["decision"] == {"verdict": "CANNOT_DECIDE"}
    out = recorded.honest("a vinyl record shop", {**failed, "idea": "a vinyl record shop"})
    assert out["no_recording"] and "nearest" not in out
    exact = recorded.honest("a bamboo toothbrush brand", {**failed, "idea": "a bamboo toothbrush brand"})
    assert exact["idea"] == "a bamboo toothbrush brand" and exact["stale"] and "nearest" not in exact
