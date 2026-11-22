"""L23: the reminder file is valid iCalendar with a daily RRULE at the chosen time and the check's link in the event;
the page asks "When will you do this each day?" once after a result, shows the streak with day 7 as a milestone, offers
a repair and a return bonus after a missed day, and never asks for notification permission."""
import datetime as dt
import re

import pytest
from test_tool_run import app, call, own, program  # noqa: F401  (fixtures)

from knos_wanted import remind, tool_page, tool_run


def unfold(text: str) -> list[str]:
    return text.replace("\r\n ", "").split("\r\n")


def test_the_reminder_is_daily_icalendar_at_the_chosen_time_with_the_link():
    text = remind.ics("07:30", "coffee", "https://knos.onrender.com/t/limit-check/", today=dt.date(2026, 11, 22))
    lines = unfold(text)
    assert lines[0] == "BEGIN:VCALENDAR" and lines[-2] == "END:VCALENDAR" and lines[-1] == ""
    assert "VERSION:2.0" in lines and "RRULE:FREQ=DAILY" in lines and "DTSTART:20261123T073000" in lines
    assert "URL:https://knos.onrender.com/t/limit-check/" in lines and any(x.startswith("UID:") for x in lines)
    assert any("after my coffee" in x for x in lines if x.startswith("SUMMARY:"))
    assert all(len(x.encode()) <= 75 for x in text.split("\r\n"))                    # RFC 5545 line folding
    assert lines.count("BEGIN:VEVENT") == lines.count("END:VEVENT") == 1
    for bad in ("25:00", "8", "noon"):
        with pytest.raises(ValueError):
            remind.ics(bad, "", "x")


def test_the_route_gives_the_file(app):  # noqa: F811
    st, body, h = call(app, "/api/remind.ics?at=08:00", raw=True)
    assert st == 200 and h["Content-Type"].startswith("text/calendar") and b"RRULE:FREQ=DAILY" in body
    assert b"DTSTART:" in body and b"T080000" in body and b"/t/limit-check/" in body
    assert call(app, "/api/remind.ics?at=99:00", raw=True)[0] == 400


def test_a_return_bonus_once_a_day(app):  # noqa: F811
    b = {"browser": "b-back-00000001", "runs": None, "why": "return", "test": True}
    st, got, _ = call(app, "/api/bonus", b)
    assert st == 200 and got["bonus"] == tool_run.CONF["return_bonus_runs"]
    first = got["free_left"]
    assert first == tool_run.CONF["free_runs_a_day"] + tool_run.CONF["return_bonus_runs"]
    assert call(app, "/api/bonus", b)[1]["free_left"] == first                        # once a UTC day
    for _ in range(first):
        assert own(app, browser="b-back-00000001")[0] == 200                          # the bonus runs are real runs
    assert own(app, browser="b-back-00000001")[0] == 402
    assert call(app, "/api/bonus", {**b, "why": "spam"})[0] == 400


def test_the_page_asks_once_keeps_a_streak_and_never_asks_for_notifications():
    js = tool_page.SCRIPT
    assert 'T("rem.q")' in js and 'T("rem.at8")' in js and 'T("rem.coffee")' in js and 'get("knos.remind")' in js
    assert 'T("streak.n"' in js and "st.n === 7" in js and 'T("streak.repair")' in js and "/api/bonus" in js
    assert "Notification" not in js and "PushManager" not in js
    assert tool_page.t("en", "rem.q") == "When will you do this each day?"
    assert not re.search(r"\b(shame|lost|failed you|guilt)\b", tool_page.t("en", "streak.missed"), re.I)
