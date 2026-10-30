"""Sweep 22's open code items, each held by its own check: a stored report is never live, Start asks IRIS and Sibyl only
at their own addresses, a restaurant is checked as a place, a long idea is never a paper, the next search page is a
page, and the words and paths the repository states are true."""
from __future__ import annotations

import re
from pathlib import Path

from knos import readings
from knos_wanted import check, status_deps, trace

ROOT = Path(__file__).resolve().parents[3]


def test_a_report_read_back_later_is_recorded_on_its_day_never_live():
    rep = {"hash": "a" * 64, "idea": "a ramen spot", "made": "2026-10-20T10:00:00Z", "decision": {"verdict": "OPEN"},
           "calls": [{"n": 1, "call": "/v2/insights", "at": "2026-10-20T10:00:01Z", "status": 200, "cached": False, "live": True}]}
    got = trace.build(rep)
    assert got["calls"] and "LIVE" not in str(got).upper().replace("DELIVER", "")


def test_start_asks_iris_and_sibyl_only_at_their_own_addresses(monkeypatch):
    for k in ("KNOS_IRIS_HEALTH_URL", "KNOS_SIBYL_HEALTH_URL"):
        monkeypatch.delenv(k, raising=False)
    asked = []
    monkeypatch.setattr(status_deps, "_get", lambda url, *a, **k: (asked.append(url), (True, "200"))[1])
    out = status_deps.deps()
    assert out["iris"]["state"] == "not asked" and out["sibyl"]["state"] in ("not asked", "down")
    assert out["rules_referee"]["state"] == "up" and not any("iris" in u.lower() for u in asked)


def test_a_restaurant_is_a_place_and_kind_words_are_whole_kinds():
    assert check.kind_of("a late night ramen spot") == "urn:entity:place"
    assert {"night", "food", "late"}.isdisjoint(check.kind_words())


def test_a_long_product_idea_is_never_read_as_a_paper():
    assert not readings.is_paper("a cold brew coffee brand for night shift nurses")
    assert readings.is_paper("10.1126/science.1225829") and readings.is_paper("paper: attention is all you need")


def test_the_next_search_results_are_asked_by_page_never_by_offset():
    src = (ROOT / "apps" / "wanted" / "knos_wanted" / "check.py").read_text(encoding="utf-8")
    assert '"offset":' not in src and '"page": 2' in src


def test_the_app_readme_states_the_crossing_deadline_and_the_public_price():
    text = (ROOT / "apps" / "wanted" / "README.md").read_text(encoding="utf-8")
    assert "(14 days)" not in text and "30 days" in text and "free until the founder" not in text


def test_the_package_says_what_it_is_and_every_cited_doc_path_exists():
    meta = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    kw = re.search(r"^keywords = \[(.*)\]", meta, re.M).group(1)
    assert all(f'"{w}"' in kw for w in ("research", "demand", "qloo")) and "metering" not in kw
    cited = {"src/knos/repro/__init__.py", "src/knos/qloo_families.py", "zk/score_circuit/src/lib.rs",
             "programs-v2/knos_zk/src/lib.rs", "programs-v2/knos_oidc/src/es256.rs", "apps/wanted/knos_wanted/front.py"}
    missing = []
    for f in cited:
        p = ROOT / f
        if not p.exists():
            continue
        for ref in re.findall(r"\b((?:docs|web)/[\w./-]+\.(?:md|json|tsv))", p.read_text(encoding="utf-8")):
            if not (ROOT / ref).exists() and not (ROOT / "src" / "knos" / ref).exists():
                missing.append(f"{f}: {ref}")
    assert missing == []


def test_the_front_door_counts_a_failed_call_apart_waits_two_weeks_and_dates_a_result_by_when_it_was_made():
    for page in ("web/home.html", "web/brand/hero.js"):
        src = (ROOT / page).read_text(encoding="utf-8")
        assert "not answered ${failed}" in src, page                  # a failed call is never counted as recorded
        assert "14 * 864e5" in src, page                               # the traction line needs a full second week
        assert "x.made || x.checked_at" in src, page                   # a result is dated by when it was made
