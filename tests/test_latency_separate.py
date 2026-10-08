"""The six latencies are reported apart (scripts/latency_stages.py --separate): each row has its own sample, none is a
sum, a row nothing measured says so, and docs/BENCH.md holds exactly what docs/bench.json records."""
from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _script(name: str):
    for extra in (ROOT / "scripts", ROOT / "src"):
        if str(extra) not in sys.path:
            sys.path.insert(0, str(extra))
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


SIX = [{"stage": "workflow scheduling", "n": 5, "p50": 2, "p95": 1184, "what": "a"}, {"stage": "evaluation", "n": 5, "p50": 16, "p95": 24, "what": "b"},
       {"stage": "relay pickup", "n": 4, "p50": 2, "p95": 5, "what": "c"}, {"stage": "submission", "n": 3, "p50": 2, "p95": 5, "what": "d"},
       {"stage": "confirmation", "n": 3, "p50": 3, "p95": 8, "what": "e"}, {"stage": "finality", "n": 0, "p50": None, "p95": None, "what": "f"}]
DECISION = {"local": {"machine": "a test machine, 2 CPUs", "rows": {"offline, warm": {"n": 40, "p50": 0.71, "p95": 2.84}}},
            "devnet": {"when": "2026-10-07", "offline": {"n": 24, "median": 356, "p95": None}, "chain_check": {"n": 23, "median": 854, "p95": None}}}


def test_six_latencies_each_with_its_own_sample_and_none_filled_in_from_another():
    ls = _script("latency_stages")
    rows = ls.separate(SIX, DECISION, {"n": 41})
    names = list(dict.fromkeys(r["latency"] for r in rows))
    assert names == ["evidence arrival", "evaluation", "decision", "chain confirmation, at `confirmed`", "finality, at `finalized`", "payout"]
    by = {(r["latency"], r["part"].split(":")[0]): r for r in rows}
    assert by[("evidence arrival", "workflow scheduling")]["n"] == 5 and by[("evidence arrival", "relay pickup")]["n"] == 4       # two samples, two rows
    assert by[("evidence arrival", "relay pickup")]["whose"].startswith("Knos's own") and by[("evidence arrival", "workflow scheduling")]["whose"].startswith("the forge's")
    assert by[("evaluation", "evaluation")]["where"] == "devnet, 5 of 41 payments"
    warm, cold, chain = [r for r in rows if r["latency"] == "decision"]
    assert (warm["n"], warm["p50"], warm["p95"], warm["unit"]) == (40, 0.7, 2.8, "ms") and "a test machine" in warm["where"] and "no network" in warm["where"]
    assert (cold["n"], cold["p50"], cold["p95"], cold["p95_note"]) == (24, 356, None, ls.FEW) and cold["where"] == "devnet, 2026-10-07: 24 real tokens"
    assert (chain["n"], chain["p50"]) == (23, 854)
    final = by[("finality, at `finalized`", "finality")]
    assert final["n"] == 0 and final["p50"] is None and final["where"] == ls.NOT_RECORDED
    pay, bank = [r for r in rows if r["latency"] == "payout"]
    assert pay["where"] == ls.NO_GAP and bank["where"] == ls.NO_BANK and pay["n"] == bank["n"] == 0
    table = ls.separate_table(rows)
    assert len(table) == 2 + len(rows) and table[0].startswith("| latency | what is timed | measured | n | p50 | p95 |")
    assert "| 24 | 356 ms | none: fewer than 30 samples |" in table[6] and table[-1].count("| - ") == 3 and "not recorded | not recorded | not recorded" in table[-3]
    # nothing measured: every row says so, and no figure appears
    none = ls.separate([], None)
    assert all(r["n"] == 0 and r["p50"] is None for r in none) and [r["where"] for r in none if r["latency"] == "decision"][0] == "not measured"
    assert not any(re.search(r"\| [\d.]+ m?s \|", line) for line in ls.separate_table(none)[2:])


def test_the_document_holds_what_the_record_says_and_names_the_one_command_of_the_release_run(capsys):
    ls = _script("latency_stages")
    kept = ls.recorded()
    assert [row["stage"] for row in kept["stages"]["six"]] == [name for name, *_ in ls.SIX] and kept["stages"]["whole"]["n"] > 0
    assert kept["decision"]["devnet"]["offline"]["median"] == 356 and kept["decision"]["devnet"]["chain_check"]["median"] == 854
    doc = (ROOT / "docs" / "BENCH.md").read_text(encoding="utf-8")
    assert "## Every latency, apart" in doc
    held = doc.split(ls.SEP_OPEN)[1].split(ls.SEP_CLOSE)[0].strip("\n").split("\n")
    assert held == ls.separate_block(kept)                                      # written by the script, not by hand
    assert ls.RELEASE_COMMAND in held[-1] and "--separate" in ls.RELEASE_COMMAND and "--write" in ls.RELEASE_COMMAND
    assert "it is not the sum of the rows above" in held[-2]
    said: list[str] = []
    assert ls.main(["--separate", "--recorded"], say=said.append) == 0 and said == held       # no network asked
    load = json.loads((ROOT / "docs" / "load.json").read_text(encoding="utf-8"))["relay"]["decision"]
    assert "offline, warm" in load["rows"]                                      # docs/LOAD.md's decision clock is the same run
