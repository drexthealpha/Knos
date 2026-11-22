"""L15: the locked comparison of Knos's limit check against a plain spreadsheet formula (bench/limit-vs-sheet/).

The held-out files match the sha256 written in lock.json before the run; tuning and held-out files do not overlap; the
published result (docs/data/benchmark.json) has time, correct count and cost for both methods, came after the lock, and a
fresh run gives the same answers; the status page shows those numbers from that file."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BENCH = ROOT / "bench" / "limit-vs-sheet"
LOCK = json.loads((BENCH / "lock.json").read_text(encoding="utf-8"))
RESULT = json.loads((ROOT / "docs" / "data" / "benchmark.json").read_text(encoding="utf-8"))
JOB = ROOT / "near" / "agents" / "job"


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def load(name: str):
    spec = importlib.util.spec_from_file_location(f"bench_{name}", BENCH / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_heldout_files_match_the_lock():
    files = sorted(p.name for p in (BENCH / "heldout").iterdir() if p.is_file())
    assert files == sorted(LOCK["heldout"]), "a held-out file was added or removed after the lock"
    for name, want in LOCK["heldout"].items():
        assert sha(BENCH / "heldout" / name) == want, f"{name} changed after the lock"
    assert sha(BENCH / "sheet.py") == LOCK["sheet_method"]["sha256"], "the formula changed after the lock"
    assert sha(ROOT / LOCK["knos_method"]["program"]) == LOCK["knos_method"]["sha256"]


def test_tuning_and_heldout_do_not_overlap():
    pins = re.findall(r'"(data/[\w/.]+\.csv)"', (JOB / "test_limit3.py").read_text(encoding="utf-8"))
    tuning = [JOB / p for p in pins] + sorted((JOB / "data" / "limit").glob("*.csv"))
    assert len(tuning) >= 12
    held = [p for p in (BENCH / "heldout").glob("*.csv")]
    assert {sha(p) for p in tuning}.isdisjoint({sha(p) for p in held})
    lines = {x.strip() for p in tuning for x in p.read_text(encoding="utf-8").splitlines()[1:] if x.strip()}
    for p in held:   # no held-out file is a tuning file with a line or two changed
        rows = [x.strip() for x in p.read_text(encoding="utf-8-sig").splitlines()[1:] if x.strip()]
        assert sum(x in lines for x in rows) < len(rows) / 2, f"{p.name} repeats a tuning file"


def test_result_has_time_correct_and_cost_for_both_and_came_after_the_lock():
    assert RESULT["lock"]["sha256"] == sha(BENCH / "lock.json")
    assert RESULT["run_at"] > LOCK["locked_at"]
    cases = json.loads((BENCH / "heldout" / "cases.json").read_text(encoding="utf-8"))["cases"]
    assert RESULT["cases"] == len(cases) == len(RESULT["per_case"])
    for m in ("knos", "sheet"):
        d = RESULT["methods"][m]
        assert isinstance(d["seconds"], float) and d["seconds"] >= 0
        assert d["correct"] == sum(r[f"{m}_right"] for r in RESULT["per_case"])
        assert d["cost"]["money"] == 0 and d["cost"]["person_minutes"] is None   # unmeasured stays unknown, never 0
    for r, c in zip(RESULT["per_case"], cases):
        assert r["expected"] == c["expected"]
        assert r["knos_right"] == (r["knos"] == c["expected"]) and r["sheet_right"] == (r["sheet"] == c["expected"])


def test_a_fresh_run_gives_the_same_answers():
    sys.path.insert(0, str(ROOT / "apps" / "wanted"))
    doc = load("run").run()
    assert [(r["knos"], r["sheet"]) for r in doc["per_case"]] == [(r["knos"], r["sheet"]) for r in RESULT["per_case"]]


def test_status_page_shows_the_numbers_from_the_file():
    sys.path.insert(0, str(ROOT / "scripts"))
    import site_product
    html = site_product.status_page("<header></header>")
    k, s = RESULT["methods"]["knos"], RESULT["methods"]["sheet"]
    part = html[html.index('id="bench"'):]
    for d in (k, s):
        assert f'{d["correct"]} of {RESULT["cases"]}' in part
        assert f'{d["seconds"]:.2f} s' in part
