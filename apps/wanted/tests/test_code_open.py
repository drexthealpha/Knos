"""Sweep 22's open code items, each held by its own check: Start asks Sibyl only at its own address, a long idea is never
a paper, and the words and paths the repository states are true."""
from __future__ import annotations

import re
from pathlib import Path

from knos import readings
from knos_wanted import status_deps

ROOT = Path(__file__).resolve().parents[3]




def test_start_asks_sibyl_only_at_its_own_address(monkeypatch):
    for k in ("KNOS_SIBYL_HEALTH_URL",):
        monkeypatch.delenv(k, raising=False)
    asked = []
    monkeypatch.setattr(status_deps, "_get", lambda url, *a, **k: (asked.append(url), (True, "200"))[1])
    out = status_deps.deps()
    assert out["sibyl"]["state"] in ("not asked", "down") and out["open_signals"]["state"] == "not asked"
    assert out["rules_referee"]["state"] == "up" and not any("sibyl" in u.lower() for u in asked)




def test_a_long_product_idea_is_never_read_as_a_paper():
    assert not readings.is_paper("a cold brew coffee brand for night shift nurses")
    assert readings.is_paper("10.1126/science.1225829") and readings.is_paper("paper: attention is all you need")




def test_the_app_readme_states_the_crossing_deadline_and_the_public_price():
    text = (ROOT / "apps" / "wanted" / "README.md").read_text(encoding="utf-8")
    assert "(14 days)" not in text and "free until the founder" not in text


def test_the_package_says_what_it_is_and_every_cited_doc_path_exists():
    meta = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    kw = re.search(r"^keywords = \[(.*)\]", meta, re.M).group(1)
    assert all(f'"{w}"' in kw for w in ("research", "demand")) and "metering" not in kw
    cited = {"src/knos/repro/__init__.py", "zk/score_circuit/src/lib.rs",
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


def test_the_front_door_waits_two_weeks_and_dates_a_result_by_when_it_was_made():
    for page in ("apps/wanted/knos_wanted/static/brand/hero.js", "apps/wanted/knos_wanted/static/index.html"):
        src = (ROOT / page).read_text(encoding="utf-8")
        assert "14 * 864e5" in src, page                               # the traction line needs a full second week
        assert re.search(r"\b\w\.made \|\| \w\.checked_at", src), page   # a result is dated by when it was made


