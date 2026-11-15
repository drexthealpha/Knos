"""Every benchmark number in the docs is generated from docs/bench.json: a doc that drifts fails here."""

from __future__ import annotations

import importlib.util
from pathlib import Path


def test_docs_match_the_one_benchmark_source():
    p = Path(__file__).resolve().parents[1] / "scripts" / "bench_docs.py"
    spec = importlib.util.spec_from_file_location("bench_docs", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.main(check=True) == 0
