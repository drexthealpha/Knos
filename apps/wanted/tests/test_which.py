"""Which one do you mean? asked by /api/check before any Qloo call; a picked reading is checked exactly; with Qloo out
and nothing recorded for it, its check is queued with a Ready brief, and the nearest recorded card only stands in."""
from test_product_routes import app, call  # noqa: F401 - the fixture

from knos_wanted import recorded, which

CARD = {"idea": "a vegan ramen truck for festivals", "made": "2026-10-22T13:26:44Z", "hash": "a" * 64, "stage": "full",
        "label": "LIVE Qloo data (Qloo REST API, read for this report, cached privately on the server)",
        "decision": {"verdict": "OPEN", "reasons": ["r"]}, "calls": [{"n": 1, "call": "GET /search", "cached": False, "at": "2026-10-22T13:26:29Z"}]}


def _with_card(monkeypatch):
    monkeypatch.setitem(recorded._answered, recorded.key(CARD["idea"]), dict(CARD))
    monkeypatch.setattr(which.readings, "paper", lambda text, **_: None)


def test_an_unrecorded_idea_is_asked_which_one_before_any_qloo_call(app, monkeypatch):  # noqa: F811
    _with_card(monkeypatch)
    base, _ = app
    st, w = call(base, "/api/check", {"idea": "a vegan ramen food truck"})
    assert st == 200 and w["kind"] == "which_one" and "calls" not in w
    texts = [r["text"] for r in w["readings"]]
    assert texts[0] == "a vegan ramen food truck" and CARD["idea"] in texts and "a food truck" in texts


def test_a_picked_reading_is_checked_exactly(app, monkeypatch):  # noqa: F811
    _with_card(monkeypatch)
    base, _ = app
    st, rep = call(base, "/api/check", {"idea": "a vegan ramen food truck", "picked": True})
    assert st == 200 and rep.get("kind") != "which_one" and rep["idea"] == "a vegan ramen food truck"


def test_qloo_out_queues_the_picked_reading_with_its_brief_and_a_labelled_stand_in(monkeypatch):
    _with_card(monkeypatch)
    monkeypatch.setattr("knos_wanted.qloo_status.reset_day", lambda: "20 Nov 2026")
    monkeypatch.setattr("knos_wanted.qloo_status.limit_line", lambda: "Qloo's monthly limit for Knos is reached until 20 Nov 2026.")
    monkeypatch.setattr("knos_wanted.company.record_queued", lambda idea, day: {"recorded": True, "queued": True})
    rep = {"idea": "a vegan ramen food truck", "hash": "b" * 64, "decision": {"verdict": "CANNOT_DECIDE", "reasons": []},
           "calls": [{"n": 1, "call": "GET /search", "error": "HTTP 429 Too Many Requests"}], "label": "NO QLOO EVIDENCE"}
    out = recorded.honest("a vegan ramen food truck", rep, picked=True)
    assert out["idea"] == "a vegan ramen food truck" and out["decision"]["verdict"] == "QUEUED"
    assert out["queued"]["line"] == "Qloo answers this when its monthly limit resets on 20 Nov 2026; your check is queued."
    assert out["ready"]["ready"] and len(out["ready"]["criteria_hash"]) == 64 and out["record"]["queued"]
    assert out["stand_in"]["idea"] == CARD["idea"] and out["stand_in"]["said"].startswith("Stand-in: the recorded answer for ")
    assert out["result_line"] == f"Read as a vegan ramen food truck, also matched {CARD['idea']}"
    assert out["qloo_calls"]["live"] == 0 and out["stand_in"]["card"]["qloo_calls"]["live"] == 0
    # not picked: the old path, never queued
    assert not recorded.honest("a vegan ramen food truck", rep).get("queued")
