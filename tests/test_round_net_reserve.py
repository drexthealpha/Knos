"""scripts/exercise_rounds/net_reserve.py: the round `net-reserve` of scripts/exercise_public.py on the local simulator.
The reserve is locked by the `/knos reserve` comment, read by knos.commands and planned by knos.flow.reserve_plan exactly
as the pinned fund.yml does; then a netted period is drawn from it and the rest goes back after the deadline."""
from __future__ import annotations

import base64
import importlib.util
import json
import sys
from pathlib import Path

import pytest

pytest.importorskip("solders.litesvm")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


@pytest.fixture(scope="module")
def ex():
    spec = importlib.util.spec_from_file_location("knos_exercise_net_reserve", ROOT / "scripts" / "exercise_public.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    mod.register_places()
    assert "net-reserve" in mod.load_rounds(say=lambda _line: None)
    return mod


def _round(ex):
    spec = importlib.util.spec_from_file_location("knos_round_net_reserve_read", ROOT / "scripts" / "exercise_rounds" / "net_reserve.py")
    mod = importlib.util.module_from_spec(spec)
    mod.xp = ex
    spec.loader.exec_module(mod)
    return mod


def test_a_reserve_comment_locks_the_reserve_a_period_draws_from_it_and_the_rest_returns_after_the_deadline(ex):
    from solders.pubkey import Pubkey

    from knos import commands, flow
    from knos.settle.v2 import meter, pay
    w = ex.Simulated()
    try:
        said: list[str] = []
        ev = ex.new_evidence(w, ex.simulated_programs())
        assert ex.run_registered(w, ev, said.append, None, "net-reserve") == {"net-reserve": 0}, said
        st = ev["rounds"]["net-reserve"]
        done = ev["exercises"]["netting_reserve"]
        assert done["status"] == "exercised" and done["program"] == "knos_pay" and done["signature"] == st["paid"][-1]["signature"]
        assert "a `/knos reserve` comment locked 10.00" in done["asserted"][0]
        # the token the round funded is the one the comment asks for: same grammar, same plan, same audience
        tok = st["tokens"]["fund"]
        iat = int(json.loads(base64.urlsafe_b64decode(tok["jwt"].split(".")[1] + "==="))["iat"])
        month = st["period"]["month"]
        assert json.loads(tok["terms"])["net"]["period"] == month == meter.yyyymm(iat)
        assert st["fund1"]["amount"] == 10_000_000 and st["fund1"]["fee"] == 50_000 and len(st["draws"]) == len(st["paid"]) == 4
        assert st["drawn"] == {"drawn": 8_000_000, "left": 2_000_000, "undrawn": 1_920_000, "deadline": st["period"]["facts"]["deadline"]}
        assert st["period"]["facts"]["period"] == month
        cmd = commands.parse(_round(ex).comment(f"supplier-{st['seller']}", iat - 1), False)      # the forge moved the clock one second
        assert isinstance(cmd, commands.Reserve) and (cmd.units, cmd.tranche, cmd.period) == (10_000_000, 2_000_000, month)
        plan = flow.reserve_plan(cmd, w.o.OWNER, st["seller"], w.c.bal, st["issue"], 0, iat - 1)
        assert plan["terms"] == tok["terms"] and plan["fund_audience"] == json.loads(base64.urlsafe_b64decode(tok["jwt"].split(".")[1] + "==="))["aud"]
        refused = [t for t in st["transactions"] if t.get("refused")]
        assert [t["refused"] for t in refused] == [83] and "before the reserve's deadline" in refused[0]["what"]
        # past the deadline the order is gone and its 2.00, with the fee's unspent 0.01, is in the Balance it came from
        assert w.account(Pubkey.from_string(st["fund1"]["order"])) is None and st["refund"]["returned_to"] == str(pay.baltok_pda(w.c.bal))
        # a second run sends nothing again
        before = len(st["transactions"])
        assert ex.run_registered(w, ev, said.append, None, "net-reserve") == {"net-reserve": 0}
        assert len(st["transactions"]) == before and "[net-reserve] done before: nothing is sent again" in said
    finally:
        w.close()
