"""The proof the front doors draw first: the last Open check on open signals, its rows with their links and never the
words a person typed. The page guards the draw and asks for it only when "Try a sample" opens."""
import re
from pathlib import Path

from knos_wanted import check, vectors

ROOT = Path(__file__).resolve().parents[3]
ROWS = [{"name": "Wikipedia", "value": 296, "unit": "views a day (last 60 days)", "link": "https://en.wikipedia.org/wiki/Tea", "counts": True},
        {"name": "Money down", "value": 0.0, "unit": "test money, 0 pre-orders here", "counts": False}]


def test_the_card_of_a_report_holds_its_rows_and_its_rule():
    rep = {"hash": "cd" * 32, "idea": "x", "label": check.LABEL, "decision": {"verdict": "OPEN", "reasons": ["a", "b", "c"]},
           "open_demand": {"rows": ROWS, "line": "Sources: Wikipedia, pre-orders here.", "rule": "People want it when 2 of these pass."}}
    card = vectors._card(rep)
    assert card["signals"] == ROWS and card["decision"] == {"verdict": "OPEN", "reasons": ["a", "b"]} and card["rule"].startswith("People")


def test_the_card_draws_the_past_result_last_inside_try():
    js = (ROOT / "apps" / "wanted" / "knos_wanted" / "static" / "brand" / "hero.js").read_text(encoding="utf-8")
    tail = js[js.index('root.addEventListener("click"'):]
    assert re.search(r"try \{ draw\(r\); \} catch", tail) and 'samples.addEventListener("toggle"' in tail and 'get("/api/proof")' in tail   # asked when "Try a sample" opens: no answer in the page
