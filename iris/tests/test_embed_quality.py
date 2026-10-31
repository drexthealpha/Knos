"""K3: the vector search's embedding on 40 labelled proof-to-criterion pairs (iris/fixtures/embed_pairs.json). For each
proof, the criteria of its own brief are ranked by cosine, as Knos.Iris.BP.ProofDecision ranks them in IRIS; a hit is
the labelled milestone among the 2 nearest. The open model (knos_iris.bridge, snowflake-arctic-embed-s) must reach a
top-2 hit rate of 0.90 and beat the hashed embedding it replaced. The same bridge code runs in IRIS's Embedded Python.

    KNOS_EMBED_REPORT=<file> python -m pytest -q iris/tests/test_embed_quality.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "iris" / "python")]
pytest.importorskip("fastembed")

from knos_iris import bridge  # noqa: E402

PAIRS = json.loads((ROOT / "iris" / "fixtures" / "embed_pairs.json").read_text(encoding="utf-8"))


def _vec(s: str) -> list[float]:
    return [float(x) for x in s.split(",")]


def _rate(proof_vec, crit_vec) -> tuple[float, list[str]]:
    briefs = {b["id"]: b for b in PAIRS["briefs"]}
    crit = {}
    for b in PAIRS["briefs"]:
        lines = bridge.criterion_text(json.dumps({"milestones": b["milestones"]})).split("\n")
        crit[b["id"]] = [(ln.split("|", 1)[0], _vec(crit_vec(ln.split("|", 1)[1]))) for ln in lines]
    hits, missed = 0, []
    for p in PAIRS["pairs"]:
        q = _vec(proof_vec(p["proof"]))
        ranked = sorted(crit[p["brief"]], key=lambda kv: -sum(a * b for a, b in zip(q, kv[1])))
        top2 = [k for k, _ in ranked[:2]]
        if p["key"] in top2:
            hits += 1
        else:
            missed.append(f"{p['brief']}/{p['key']} -> {top2}")
    assert len(briefs) == 5 and len(PAIRS["pairs"]) == 40
    return hits / len(PAIRS["pairs"]), missed


def test_the_open_model_finds_the_milestone_a_proof_meets_in_its_top_two():
    assert bridge.embed_model() == bridge.MODEL, "the open model did not load"
    model, missed_m = _rate(lambda t: bridge.embed(t, True), lambda t: bridge.embed(t))
    hashed, missed_h = _rate(bridge.embed_hashed, bridge.embed_hashed)
    line = (f"top-2 hit rate on 40 pairs: {bridge.MODEL} {model:.3f}, hashed {hashed:.3f}; "
            f"missed by the model: {missed_m or 'none'}; missed by the hash: {len(missed_h)}")
    print(line)
    if os.environ.get("KNOS_EMBED_REPORT"):
        with open(os.environ["KNOS_EMBED_REPORT"], "a", encoding="utf-8") as f:
            f.write(line + "\n")
    assert model >= 0.90 and model > hashed, line
