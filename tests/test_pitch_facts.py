"""Merge to paid has one value and one source: the fact in docs/facts.json, which points into docs/bench.json (filled
from the site's stats.json by `scripts/bench_docs.py --stats`). The pitch, the submission, the judges' page, the
demo's data and the front pages state that value or none."""
from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = "devnet.stats.latency.merge_to_paid.median"


def _bench_docs():
    spec = importlib.util.spec_from_file_location("bench_docs_for_pitch", ROOT / "scripts" / "bench_docs.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _dig(obj, path: str):
    for key in path.split("."):
        obj = obj[key]
    return obj


def _seconds() -> int:
    facts = json.loads((ROOT / "docs" / "facts.json").read_text(encoding="utf-8"))["facts"]
    [fact] = [f for f in facts if f.get("path") == PATH]
    bench = json.loads((ROOT / "docs" / "bench.json").read_text(encoding="utf-8"))
    assert fact["json"] == "docs/bench.json" and fact["equals"] == _dig(bench, PATH)
    assert fact["say"] == [str(fact["equals"])]
    return fact["equals"]


def test_every_statement_of_merge_to_paid_is_the_one_in_facts_json():
    value = _seconds()
    stated = _bench_docs().said(ROOT).get("seconds_from_merge_to_paid", {})
    assert set(stated) <= {str(value)}, stated
    for doc in ("docs/submission/pitch_script.md", "docs/submission/SUBMISSION.md", "docs/JUDGES.md"):
        assert doc in stated.get(str(value), []), f"{doc} does not state merge to paid from facts.json"


def test_the_demo_data_and_the_front_pages_hold_no_other_value():
    value = _seconds()
    demo = json.loads((ROOT / "web" / "demo_data.json").read_text(encoding="utf-8"))
    assert [v for k, v in _walk(demo) if k == "seconds"] == [value]
    for page in sorted((ROOT / "web").glob("front*.js")) + [ROOT / "web" / "story.js", ROOT / "web" / "judges.js"]:
        text = page.read_text(encoding="utf-8")
        assert not re.search(r"merge to (?:paid|payment)[^.]{0,60}?\d+ ?(?:s|seconds)\b", text, re.I), page.name


def _walk(obj, key=None):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _walk(v, k)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v, key)
    else:
        yield key, obj
