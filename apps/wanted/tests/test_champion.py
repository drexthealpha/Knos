"""Offline: the fields matrix, the value vectors, the proof shown first, the money page and companies mode. The live
tests are scripts/test_champion.mjs."""
from pathlib import Path

from knos import ready as kr
from knos_wanted import companies, track, vectors

STATIC = Path(__file__).resolve().parents[1] / "knos_wanted" / "static"
WEB = Path(__file__).resolve().parents[3] / "web"


def test_the_fields_matrix_is_seven_by_seven_with_the_frameworks_twelve_unlocks():
    from knos_wanted.fields_data import FIELDS as d
    bs, ts = [b["id"] for b in d["bottlenecks"]], [t["id"] for t in d["technologies"]]
    assert len(bs) == len(ts) == 7 and len(d["cells"]) == 49
    assert {(c["b"], c["t"]) for c in d["cells"]} == {(b, t) for b in bs for t in ts}
    assert all(c["status"] in ("live", "next") and c["idea"] and c["title"] for c in d["cells"])
    unlock = {(c["b"], c["t"]) for c in d["cells"] if c.get("unlock")}
    # the framework's map: which technology solves which bottleneck
    assert unlock == {("capital", "web3"), ("hardware", "materials"), ("hardware", "ai"), ("energy", "energy"), ("regulation", "web3"),
                      ("regulation", "pqc"), ("materials", "quantum"), ("materials", "biotech"), ("people", "ai"), ("people", "biotech"),
                      ("resistance", "pqc"), ("resistance", "energy")}
    nxt = {(c["b"], c["t"]) for c in d["cells"] if c["status"] == "next"}
    assert ("energy", "energy") in nxt and ("materials", "quantum") in nxt and ("resistance", "energy") in nxt   # fusion, SMRs, quantum design
    assert next(c for c in d["cells"] if (c["b"], c["t"]) == ("hardware", "materials"))["next_part"] == "room-temperature superconductors"


def test_the_hero_chips_span_every_technology_and_no_pitch_paragraph_stands_above_the_box():
    hero = (WEB / "brand" / "hero.html").read_text(encoding="utf-8")
    techs = {line.split('data-tech="')[1].split('"')[0] for line in hero.splitlines() if 'data-tech="' in line}
    assert len(techs) >= 5 and techs <= {"ai", "web3", "quantum", "energy", "biotech", "materials", "pqc"}
    above = hero[:hero.index("<form")]
    # above the box: the pill naming who Knos is for, the heading and its one subhead (SOTA gap 6); no pitch paragraph
    assert above.count("<p") == 2 and 'id="k-for"' in above and 'class="k-sub"' in above and 'id="k-mission"' in above


def test_each_fields_draft_is_ready_and_carries_its_proof():
    for sentence, field in [("We need an API integration for our invoicing app", "software"),
                            ("We need a demand forecast model trained on our sales data", "data"),
                            ("We need an enzyme assay that runs on our cell samples", "wetlab"),
                            ("We need a battery sensor prototype for our drones", "hardware")]:
        assert companies.classify(sentence) == field, sentence
        b = companies.draft(sentence, field)
        r = kr.check(b)
        assert r["ready"], (sentence, r["missing"])
        assert b["challenge_s"] == 72 * 3600 and companies.FIELDS[field]["proof"]
    assert companies.classify("We need it soon and better") == "software"            # a sentence with no field: software, signed CI
    assert kr.check(companies.draft("We need it soon and better, faster", "software"))["ready"]   # its vague words leave the milestone


def test_vectors_measure_and_never_guess(monkeypatch):
    saved = {}
    monkeypatch.setattr("knos_wanted.valley._safe_load", lambda kind, key: saved.get(key))
    monkeypatch.setattr("knos_wanted.valley._save", lambda kind, key, obj, chain=True: saved.__setitem__(key, obj))
    monkeypatch.setattr(vectors, "_runs", [])
    monkeypatch.setattr(vectors, "_proof", None)
    monkeypatch.setattr(vectors, "_loaded", [False])
    v = vectors.vectors()
    assert v["speed"]["median_s"] is None and v["cost"]["usd_per_ready_brief"] == round(0.3481 / 20, 4)
    assert v["capability"] == {"idt_ratio": 2.08, "ready_pass": 0.7, "vague_pass": 0.05, "tasks": 20}
    rep = {"hash": "a" * 64, "idea": "An AI recipe planner for families", "decision": {"verdict": "OPEN"}, "cities": [{"name": "Honolulu"}],
           "calls": [{"cached": False}] * 4}
    vectors.note("check", 4200, rep)
    vectors.note("check", 4200, {**rep, "hash": "c" * 64, "idea": "my own secret product"})     # what a person typed stays theirs
    vectors.note("check", 6200, {**rep, "hash": "b" * 64, "decision": {"verdict": "CANNOT_DECIDE"}, "cities": []})
    v = vectors.vectors()
    assert v["speed"]["median_s"] == 4.2 and v["speed"]["checks"] == 3 and v["cost"]["qloo_calls_per_check"] == 4
    assert vectors.proof()["proof"]["hash"] == "a" * 64                    # a decided verdict with cities, never a CANNOT_DECIDE


def test_a_brief_that_is_not_ready_gets_no_card():
    got = track.ready_card({"milestones": [{"name": "make it better", "target": "soon"}]})
    assert got["ready"] is False and got["card"] is None and got["missing"]


def test_the_money_page_shows_what_is_held_and_the_price_list_with_no_revenue_target():
    from knos_wanted.money_data import MONEY as m
    from knos.money import fees_config
    f = fees_config.load().doc["fees"]
    assert m["pools"] == [] and "barriers" not in m and "not_shown" not in m
    rows = {r["what"]: r for r in m["prices"]}
    assert list(rows) == ["Demand check", "Deep demand check", "Ready brief", "Proof page", "Release on verified proof", "How a milestone is paid"]
    assert rows["Demand check"]["price"] == f"{f['demand_check']['free_a_month']} a month free"
    assert rows["Deep demand check"]["price"].startswith(f"{f['deep_demand_check']['usd_each']} USD each, by card once the company exists")
    assert rows["Release on verified proof"]["price"].startswith(f"{f['release']['rate_bps'] / 100:g}% on top, plus payment costs; the solver keeps 100%")
    assert "0.3% (at least 0.05 test units)" in rows["Release on verified proof"]["today"] and "nobody is charged" in rows["Deep demand check"]["today"]
    page = (Path(__file__).resolve().parents[1] / "knos_wanted" / "static" / "money.html").read_text(encoding="utf-8")
    assert 'id="mx-held"' in page and 'id="mx-released"' in page and 'id="mx-fee"' in page and "/api/projects" in page
    assert "$1B" not in page and "share Knos needs" not in page and "escrow" not in page.lower()
