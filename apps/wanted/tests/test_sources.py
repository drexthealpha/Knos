"""L10: every source the sample cites carries its url, the passage that says it, the day it was checked and the sha256
of the page fetched that day; the tool page shows the passage and the date; the support rate ("N of M") is worked out
from that data, never typed."""
import re

from test_tool_run import app, call, program  # noqa: F401  (fixtures)

from knos_wanted import sources
from knos_wanted.runner_conf import CONF


def test_every_source_carries_url_passage_date_and_hash():
    assert sources.SOURCES
    for s in sources.SOURCES:
        assert s["url"].startswith("https://") and len(s["passage"]) > 20
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", s["checked_on"]) and re.fullmatch(r"[0-9a-f]{64}", s["sha256"])
    lim = sources.for_limit()
    assert lim["url"] == CONF["limit_rule_url"] and str(CONF["sample_limit"]) + " Ah" in lim["passage"]


def test_the_rate_is_computed_from_the_data(monkeypatch):
    got = sources.summary()
    assert got["supporting"] == sum(sources.supports(s) for s in sources.SOURCES) and got["total"] == len(sources.SOURCES)
    assert got["line"] == f"sources supporting their sentence: {got['supporting']} of {got['total']}"
    monkeypatch.setattr(sources, "SOURCES", [*sources.SOURCES, {**sources.SOURCES[0], "id": "x", "says": ["9.9 Ah"]}])
    assert sources.summary()["supporting"] == got["supporting"] and sources.summary()["total"] == got["total"] + 1


def test_the_tool_page_shows_the_passage_and_the_date(app):  # noqa: F811
    st, page, _ = call(app, "/t/limit-check/", raw=True)
    html = page.decode("utf-8")
    s = sources.for_limit()
    assert st == 200 and s["passage"] in html and f"Checked on {s['checked_on']}: the passage says this." in html
    assert call(app, "/api/sources")[1]["line"] == sources.summary()["line"]
