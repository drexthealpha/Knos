"""L36, L37, L38, L14 (IQ PLAN.md), the app side: each status measure is computed from synthetic events and matches a hand
count; zero real events read as not known (null), never a made-up number; a visit keeps no IP address and only the region
of its time zone; a burst of one browser's events in one minute counts once; a survey answer is a count with no id; the
cost per run comes from the server's own run records, failed runs included."""
import datetime as dt
import json
import secrets

import pytest
from test_tool_run import app, call, own, program  # noqa: F401  (fixtures)

from knos_wanted import run_cost, tool_run, visits


@pytest.fixture(autouse=True)
def fresh_visits(monkeypatch):
    monkeypatch.setattr(visits, "_days", {})
    monkeypatch.setattr(visits, "_burst", {})
    monkeypatch.setattr(visits, "_seeded", [True])


def test_no_real_event_is_not_known_never_zero(app):  # noqa: F811
    got = call(app, "/api/usage")[1]
    assert set(got["lead"]) >= {"first_result_7d", "dau", "dau_mau", "return_d1", "return_d30", "week2_use"}
    assert all(v is None for v in got["lead"].values()), got["lead"]
    assert all(v is None for v in got["depth"].values()), got["depth"]
    assert got["survey"] == {}
    assert got["cost"]["usd_per_run"] is None and got["cost"]["runs"] == 0


def test_a_survey_answer_is_a_count_with_no_id(app):  # noqa: F811
    assert call(app, "/api/survey", {"q": "again", "a": "yes"})[1] == {"ok": True}
    assert call(app, "/api/survey", {"q": "again", "a": "yes"})[1] == {"ok": True}
    assert call(app, "/api/survey", {"q": "disappointed", "a": "very"})[1] == {"ok": True}
    assert call(app, "/api/survey", {"q": "rank", "a": "r_pr", "test": True})[1] == {"ok": True}    # Knos's own tests apart
    assert call(app, "/api/survey", {"q": "again", "a": "<b>"})[1] == {"ok": False}
    assert call(app, "/api/survey", {"q": "who", "a": "yes"})[1] == {"ok": False}
    survey = call(app, "/api/usage")[1]["survey"]
    assert survey == {"again": {"yes": 2, "no": 0}, "disappointed": {"very": 1, "somewhat": 0, "not": 0}}
    stored = json.dumps(tool_run.valley._safe_load("pages", visits.SURVEY_KEY))
    assert "127.0.0.1" not in stored and "ip" not in json.loads(stored).get("answers", {})


def test_the_first_view_keeps_language_device_and_region_only(monkeypatch):
    clock = [1_000_000.0]
    monkeypatch.setattr(visits.time, "time", lambda: clock[0])
    a, b, c = (secrets.token_hex(8) for _ in range(3))
    assert visits.record({"v": a, "e": "view", "since": 0, "lang": "pt-BR", "dev": "phone", "tz": "America/Sao_Paulo", "ip": "203.0.113.9"})
    assert visits.record({"v": b, "e": "view", "since": 0, "lang": "en", "dev": "desktop", "tz": "Europe/Berlin"})
    assert visits.record({"v": c, "e": "view", "since": 5, "lang": "en", "dev": "fridge", "tz": "not a zone!"})
    clock[0] += 120
    for v in (a, c):
        assert visits.record({"v": v, "e": "result"})
    clock[0] += 240
    assert visits.record({"v": b, "e": "result"})
    assert visits.record({"v": b, "e": "result"})              # a second result of one visit is not a second person
    got = visits.depth()
    assert got["by_language"] == {"pt": 1, "en": 2}
    assert got["by_device"] == {"phone": 1, "desktop": 1}     # an unknown device class is not kept
    assert got["by_region"] == {"America": 1, "Europe": 1}    # the region of the zone; a malformed zone is not kept
    assert got["minutes_to_result"] == 4.0                    # new browsers only: 2 and 6 minutes, median 4
    kept = json.dumps(visits.summary()["days"], default=str)
    assert "203.0.113.9" not in kept and "Sao_Paulo" not in kept and "Berlin" not in kept


def test_a_burst_from_one_browser_in_one_minute_counts_once(monkeypatch):
    monkeypatch.setattr(visits.time, "time", lambda: 6_000_000.0)
    v = secrets.token_hex(8)
    for _ in range(50):
        assert visits.record({"v": v, "e": "press"})
    day = next(iter(visits.summary()["days"].values()))
    assert day["events"]["press"] == 1 and day["first_press"] == 1


def test_the_beacon_sends_no_ip_field():
    from pathlib import Path
    src = (Path(tool_run.root()) / "scripts" / "site_pages.py").read_text(encoding="utf-8")
    beacon = src[src.index('BEACON = """'):src.index('"""', src.index('BEACON = """') + 12)]
    assert "/api/visit" in beacon and "tz" in beacon
    assert not any(w in beacon.lower() for w in ("\"ip\"", "ip:", "remoteaddr", "x-forwarded-for"))


def rows():
    """Five browsers on fixed dates; the hand counts below are read off this table. Today is 2026-03-31."""
    d = lambda s: f"2026-03-{s:02d}"   # noqa: E731
    return [{"first": d(1), "seen": [d(1), d(2), d(8), d(15), d(22), d(28), d(30), d(31)]},   # A
            {"first": d(10), "seen": [d(10), d(11), d(13), d(17), d(24), d(30)]},             # B
            {"first": d(25), "seen": [d(25), d(26), d(28)]},                                  # C
            {"first": d(29), "seen": [d(29), d(30)]},                                         # D
            {"first": d(3), "seen": [d(3), d(27)]}]                                           # E


def test_lead_and_depth_match_a_hand_count():
    lead, depth = tool_run.lead_depth(dt.date(2026, 3, 31), rows())
    assert lead["first_result_7d"] == 2                   # C (25th), D (29th): first within 25..31
    assert lead["dau"] == 3                               # yesterday the 30th: A, B, D
    # browsers first seen 14+ days before the 30th (first <= 16th): A, B, E; active 1..30: all three; on the 30th: A, B
    assert lead["dau_mau"] == round(100 * 2 / 3, 1)
    assert lead["dau_wau"] == round(100 * 3 / 5, 1)       # active 24..30: A, B, C, D, E (27th)
    assert lead["return_d1"] == 80.0                      # first <= 30th: all five; on day 1: A, B, C, D (E no) = 4/5
    assert lead["return_d7"] == round(100 * 2 / 3, 1)     # first <= 24th: A, B, E; day 7: A (8th), B (17th) = 2/3
    assert lead["return_d14"] == round(100 * 2 / 3, 1)    # first <= 17th: A, B, E; day 14: A (15th), B (24th)
    assert lead["return_d30"] == 100.0                    # first <= 1st: A; day 30: the 31st
    assert lead["return_d3"] == 50.0                      # first <= 28th: A, B, C, E; day 3: B (13th), C (28th) = 2/4
    assert lead["week2_use"] == round(100 * 2 / 3, 1)     # first <= 17th: A, B, E; days 7..13: A (8th), B (17th)
    assert lead["activation_7d"] is None                  # not measurable from these records: never made up
    assert depth["core_users"] == 1                       # 7+ days in 2..31: A has 7 (the 1st is outside), B 6
    assert depth["resurrected"] == 1                      # first <= 17th, a run 25..31 and none 18..24: E (27th)
    assert depth["active_days_28"] == 3                   # a run 4..31 on fewer than 4 days: C (3), D (2), E (1)
    assert depth["week4_active"] == 100.0                 # first <= 3rd: A, E; week 4: A (22nd is day 21), E (27th is day 24) = 2/2
    assert depth["l7"] == {"1": 2, "2": 1, "3": 2, "4": 0, "5": 0, "6": 0, "7": 0}   # 25..31: A 3, B 1, C 3, D 2, E 1


def test_the_cost_per_run_comes_from_the_run_records_failed_runs_included(monkeypatch):
    runs = [{"s": 0.2, "tokens_in": 0, "tokens_out": 0, "ok": True}, {"s": 0.4, "tokens_in": 0, "tokens_out": 0, "ok": False}]
    monkeypatch.setitem(tool_run.CONF, "host_usd_per_month", 25.92)          # 25.92 a month = 0.00001 a second
    got = tool_run.cost({"runs": runs})
    assert got["runs"] == 2 and got["failed"] == 1 and got["seconds_per_run"] == 0.3
    assert got["usd_per_run"] == pytest.approx(0.3 * 0.00001)
    monkeypatch.setitem(tool_run.CONF, "host_usd_per_month", None)           # a host price not set: not known, never 0
    assert tool_run.cost({"runs": runs})["usd_per_run"] is None
    assert tool_run.cost({})["usd_per_run"] is None


def test_a_run_and_a_failed_run_are_recorded(app):  # noqa: F811
    assert own(app)[0] == 200
    assert own(app, column="nothing-here")[0] in (400, 422, 500)             # refused before the program: not a run
    got = call(app, "/api/usage")[1]
    assert got["cost"]["runs"] == 1 and got["cost"]["seconds_per_run"] > 0
    assert got["cost"]["usd_per_run"] == 0.0                                 # render.yaml plan: free, and no model tokens
    assert got["lead"]["first_result_7d"] is None                            # a test browser is never a person


def test_the_command_writes_only_a_measured_cost(tmp_path):
    doc = {"numbers": {"x": {"value": 1}}, "window": {"cost_per_run": {"value": None}, "trend": []}}
    assert not run_cost.merge(doc, {"usd_per_run": None, "runs": 0}, "2026-11-22")
    assert doc["window"]["cost_per_run"]["value"] is None
    assert run_cost.merge(doc, {"usd_per_run": 0.0002, "runs": 40, "failed": 3, "source": "s", "host_usd_per_month": 7}, "2026-11-22")
    assert run_cost.merge(doc, {"usd_per_run": 0.0003, "runs": 41, "source": "s", "host_usd_per_month": 7}, "2026-11-22")
    assert doc["window"]["cost_per_run"]["value"] == 0.0003 and doc["window"]["trend"] == [{"date": "2026-11-22", "value": 0.0003}]
    assert doc["numbers"] == {"x": {"value": 1}}
