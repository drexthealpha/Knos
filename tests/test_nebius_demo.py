"""The golden path end to end in MOCK mode (no key): the referee's runs are real, every model and search number is
labelled MOCK, zeros stay zeros, and the committed panel in examples/nebius is such a run."""
from __future__ import annotations
import pathlib as _pl

import pytest as _pt

if not (_pl.Path(__file__).resolve().parents[1] / "examples/nebius").is_dir():
    _pt.skip("examples/nebius/ left the public repository; this test runs where that folder is kept", allow_module_level=True)

import json
import re
from pathlib import Path

from knos import cheats
from knos.nebius import panel, sources
from knos.nebius.demo import run_demo

ROOT = Path(__file__).resolve().parents[1]
EX = ROOT / "examples" / "nebius"


def test_the_golden_path_in_mock_mode(tmp_path, monkeypatch):
    monkeypatch.delenv(sources.KEY_ENV, raising=False)
    monkeypatch.delenv(sources.TAVILY_KEY_ENV, raising=False)
    before = set(cheats.RULES)
    try:
        data = run_demo(ROOT, tmp_path, iterations=2, say=lambda *a: None)
    finally:
        for rid in set(cheats.RULES) - before:
            cheats.RULES.pop(rid)
    m = data["metrics"]
    assert m["label"] == sources.MOCK and data["metrics"]["modes"] == {"token_factory": "mock", "tavily": "mock"}
    decisions = [e["decision"] for e in data["experiments"]]
    assert decisions[:2] == ["kept", "refused"]                      # iteration 2 is the mock's cheat: refused for real
    assert m["verified_improvements"] == 1 and m["cost_per_verified_improvement_usd"] == round(m["cost_usd_total"], 6)
    assert m["cheats_caught"] == 2 and m["cheats_caught_autoresearch"] == 1 and m["cheats_caught_self"] == 1
    assert all(c["verdict"] == "refused" and c["advisory"] and c["label"] == sources.MOCK for c in data["cheats"])
    assert m["rules_accepted"] == 1 and data["rules"][0]["id"] == "collection_hook_drops_tests"
    assert data["reruns"]["backend"] == "local-sandbox" and data["autoresearch"]["synthetic"]
    assert all(c["mock"] and c["label"] == sources.MOCK for c in data["calls"])
    page = (tmp_path / "panel.html").read_text(encoding="utf-8")
    assert json.loads((tmp_path / "panel.json").read_text(encoding="utf-8"))["metrics"] == m
    assert "MOCK" in page and "<script src" not in page and "https://" not in page.split("<script type")[0]


def test_zeros_stay_zeros_and_nothing_divides_by_zero():
    m = panel.metrics([], [], kept=0, graduated=False, refused_ar=0, refused_self=0, rules_accepted=0, rules_proposed=0,
                      modes={"token_factory": "live", "tavily": "live"})
    assert m["tokens_total"] == 0 and m["cost_usd_total"] == 0 and m["cheats_caught"] == 0
    assert m["cost_per_verified_improvement_usd"] is None and m["label"] == "live"
    assert "none" in panel.text({"metrics": m, "reruns": {"backend": "local-sandbox"}})


def test_the_committed_panel_is_a_labelled_mock_run():
    data = json.loads((EX / "panel.json").read_text(encoding="utf-8"))
    m = data["metrics"]
    assert m["label"] == sources.MOCK and all(c["label"] == sources.MOCK for c in data["calls"])
    assert all(s["label"] == sources.MOCK for s in data["searches"])
    assert all(r["url"].startswith("https://mock.invalid/") for s in data["searches"] for r in s["results"])
    page = (EX / "panel.html").read_text(encoding="utf-8")
    blob = re.search(r'<script type="application/json" id="data">(.*?)</script>', page, re.S).group(1)
    assert json.loads(blob.replace("<\\/", "</"))["metrics"] == m
    readme = (EX / "README.md").read_text(encoding="utf-8")
    assert "## How NVIDIA models and Token Factory are used" in readme
    assert sources.SUPER in readme and sources.ULTRA in readme and "MOCK (synthetic, not a real API response)" in readme
    assert (ROOT / "LICENSE").read_text(encoding="utf-8").startswith("MIT License")
