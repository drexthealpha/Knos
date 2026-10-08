"""scripts/round_net_reserve.py: the round `net-reserve` of scripts/exercise_public.py on the local simulator. The round
is listed in exercise_public.ROUNDS by one line; until that line is there this test adds it for its own run."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

pytest.importorskip("solders.litesvm")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def load(name: str):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_the_round_locks_a_reserve_draws_a_period_from_it_and_returns_the_rest_after_the_deadline(monkeypatch):
    ex, rnd = load("exercise_public"), load("round_net_reserve")
    monkeypatch.setitem(ex.ROUNDS, "net-reserve", (rnd.round_net_reserve, ("knos_oidc", "knos_pay"), (rnd.CAPABILITY,)))
    w = ex.Simulated()
    try:
        said: list[str] = []
        ev = ex.run(w, ex.new_evidence(w, ex.simulated_programs()), only="net-reserve", say=said.append)
        st = ev["rounds"]["net-reserve"]
        assert "stopped" not in st, said
        done = ev["exercises"][rnd.CAPABILITY]
        assert done["status"] == "exercised" and done["program"] == "knos_pay" and done["signature"] == st["paid"][-1]["signature"]
        assert st["fund1"]["amount"] == 10_000_000 and st["fund1"]["fee"] == 50_000 and len(st["draws"]) == len(st["paid"]) == 4
        assert st["drawn"] == {"drawn": 8_000_000, "left": 2_000_000, "undrawn": 1_920_000, "deadline": st["period"]["facts"]["deadline"]}
        refused = [t for t in st["transactions"] if t.get("refused")]
        assert [t["refused"] for t in refused] == [83] and "before the reserve's deadline" in refused[0]["what"]
        # past the deadline the order is gone and its 2.00, with the fee's unspent 0.01, is in the Balance it came from
        from solders.pubkey import Pubkey
        from knos.settle.v2 import pay
        assert w.account(Pubkey.from_string(st["fund1"]["order"])) is None and st["refund"]["returned_to"] == str(pay.baltok_pda(w.c.bal))
        # a second run sends nothing again
        before = len(st["transactions"])
        ex.run(w, ev, only="net-reserve", say=said.append)
        assert len(st["transactions"]) == before and any("done before" in line for line in said)
    finally:
        w.close()
