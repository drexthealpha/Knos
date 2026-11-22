"""A result's receipts (knos_wanted.receipts): one row per source of a number on the card, each open signal with its
value and link. SYNTHETIC report only; the Knos record is not touched."""
from knos_wanted import receipts

ROWS = [{"name": "Wikipedia", "value": 296, "unit": "views a day (last 60 days)", "link": "https://en.wikipedia.org/wiki/Festival", "counts": True},
        {"name": "Money down", "value": 0.0, "unit": "test money, 0 pre-orders here", "counts": False}]


def report():
    return {"hash": "ab" * 32, "idea": "a synthetic desert music festival", "made": "2026-10-22T22:09:40Z", "decision": {"verdict": "OPEN"},
            "open_demand": {"rows": ROWS, "head": "Open signals say people want this"},
            "model_alone": {"city": "Indio, California", "who": "fans", "why": "deserts", "model": "m", "at": "2026-10-27T08:00:00Z"}}


def test_each_signal_is_a_row_with_its_value_and_link(monkeypatch):
    monkeypatch.setattr(receipts, "record_line", lambda rep: {"recorded": True, "seq": 7, "kind": "claim", "claim": "c" * 64})
    rows = {r["id"]: r for r in receipts.rows(report())}
    assert rows["signal-1"] == {"id": "signal-1", "source": "signal", "what": "Wikipedia", "at": "2026-10-22T22:09:40Z",
                                "value": "296 views a day (last 60 days)", "counts": True, "link": "https://en.wikipedia.org/wiki/Festival"}
    assert rows["signal-2"]["link"] is None and rows["model"]["value"] == "Indio, California"
    assert rows["record"]["seq"] == 7 and rows["chain"]["transactions"] == []
    assert receipts.doc(report())["verdict"] == "Open signals say people want this"


def test_the_page_gives_each_row_its_anchor(monkeypatch):
    monkeypatch.setattr(receipts, "record_line", lambda rep: {"recorded": False, "why": "none here"})
    html = receipts.page(report(), "ab" * 8)
    for rid, src in (("signal-1", "signal"), ("signal-2", "signal"), ("model", "model"), ("record", "record"), ("chain", "chain")):
        assert f'<tr id="{rid}" data-source="{src}">' in html
    assert 'href="https://en.wikipedia.org/wiki/Festival"' in html
