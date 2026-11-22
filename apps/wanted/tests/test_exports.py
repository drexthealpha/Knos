"""A result's downloads (knos_wanted.exports): the brief as a one-page PDF, the open signals as CSV, and the Ready brief
as JSON (none: the open signals name no launch city). SYNTHETIC report only."""
import csv
import io
import json

from knos_wanted import exports

ROWS = [{"name": "Wikipedia", "value": 296, "unit": "views a day (last 60 days)", "link": "https://en.wikipedia.org/wiki/Festival", "counts": True},
        {"name": "Hacker News", "value": 6, "unit": "stories in 2 years", "link": "https://hn.algolia.com/", "counts": True},
        {"name": "Money down", "value": 0.0, "unit": "test money, 0 pre-orders here", "counts": False}]


def report():
    return {"hash": "cd" * 32, "idea": "a synthetic (desert) music festival", "made": "2026-10-22T22:09:40Z", "decision": {"verdict": "OPEN"},
            "open_demand": {"verdict": "OPEN", "rows": ROWS, "head": "Open signals say people want this",
                            "line": "Sources: Wikipedia, Hacker News, pre-orders here.", "rule": "People want it when 2 of these pass."}}


def test_the_signals_csv_holds_each_row_with_its_link():
    rows = list(csv.reader(io.StringIO(exports.csv_text(report()))))
    assert rows[0] == ["source", "value", "unit", "counts", "link"] and len(rows) == 4
    assert rows[1] == ["Wikipedia", "296", "views a day (last 60 days)", "yes", "https://en.wikipedia.org/wiki/Festival"]
    assert rows[3][3] == "no" and rows[3][4] == ""


def test_the_ready_brief_json_says_there_is_none():
    d = json.loads(exports.json_text(report()))
    assert d["ready"] is False and d["brief"] is None and "no launch city" in d["why"] and d["report"] == "cd" * 32


def test_the_brief_pdf_is_one_page_with_the_cards_fields():
    b = exports.pdf(report(), "https://knos.onrender.com/r/" + "cd" * 8)
    assert b.startswith(b"%PDF-1.4") and b.rstrip().endswith(b"%%EOF") and b.count(b"/Type /Page ") == 1
    assert b"\\(desert\\)" in b and b"Open signals say people want this" in b and b"Wikipedia: 296" in b
    xref = int(b.rsplit(b"startxref\n", 1)[1].split(b"\n")[0])
    assert b[xref:xref + 4] == b"xref"
