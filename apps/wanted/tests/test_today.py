"""L24: the daily list holds at most five items, each with a source address and its date; two different dates give
different lists; the list is never longer than five (no endless feed); the job writes today's list to a file."""
import datetime as dt
import json

from test_tool_run import app, call, program  # noqa: F401  (fixtures)

from knos_wanted import today


def test_at_most_five_items_each_with_a_source_and_a_date():
    for i in range(60):                                                              # the 60-day plan
        day = dt.date(2026, 11, 22) + dt.timedelta(days=i)
        got = today.today_list(day)
        assert 1 <= len(got["items"]) <= today.MAX_ITEMS == 5
        assert all(x["source"].startswith("https://") and x["date"] == day.isoformat() and x["line"] for x in got["items"])
        assert len({x["claim"] for x in got["items"]}) == len(got["items"])


def test_two_dates_give_different_lists():
    a, b = today.today_list(dt.date(2026, 11, 22)), today.today_list(dt.date(2026, 11, 23))
    assert [x["claim"] for x in a["items"]] != [x["claim"] for x in b["items"]]
    assert len(today.plan(dt.date(2026, 11, 22), 60)) == 60


def test_the_daily_job_writes_todays_list(tmp_path):
    out = tmp_path / "today.json"
    assert today.main(["--out", str(out)]) == 0
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["date"] == dt.datetime.now(dt.timezone.utc).date().isoformat() and len(doc["items"]) <= 5


def test_the_route_answers_the_list(app):  # noqa: F811
    st, got, _ = call(app, "/api/today")
    assert st == 200 and len(got["items"]) <= 5 and got["from"] == "near/claims/claims.json"


def test_the_tool_page_sends_one_item_through_the_share_sheet():
    from knos_wanted import tool_page
    js = tool_page.SCRIPT
    assert "/api/today" in js and 'T("today.send")' in js and "navigator.share({ url: it.source" in js and "slice(0, 5)" in js
