"""The Plan floor (src/knos/plan_floor.py): Knos signs no Plan below 20 bps, and the check reads every Plan that exists."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from knos import plan_floor as P
from knos.settle.v2 import pay

ROOT = Path(__file__).resolve().parents[1]
FIX = json.loads((ROOT / "tests" / "data" / "plans" / "plans.json").read_text(encoding="utf-8"))
OWNER = pay.Pubkey.from_string("AKkzLhjhyFtM9j7WAhbaqYpFe49cXeJBg2kzLRC2PnNa")


def _call(rows):
    asked = []

    def call(method, params):
        asked.append((method, params))
        return rows
    return call, asked


def test_the_builder_refuses_below_the_contract_floor():
    for bps in (10, 15, 19, True, "20"):
        with pytest.raises(P.Refused):
            P.build(OWNER, OWNER, 7, bps, 2_000_000_000)
    with pytest.raises(P.Refused):
        P.build(OWNER, OWNER, 7, pay.FEE_BPS + 1, 2_000_000_000)
    ix = P.build(OWNER, OWNER, 7, 20, 2_000_000_000)
    assert ix.data == pay.set_plan_ix(OWNER, OWNER, 7, 20, 2_000_000_000).data


def test_the_program_floor_is_below_the_contract_floor():
    """The gap the check exists for: the program allows 10 bps."""
    lib = (ROOT / "programs-v2" / "knos_pay" / "src" / "lib.rs").read_text(encoding="utf-8")
    assert "pub const PLAN_BPS_MIN: u64 = 10;" in lib and pay.PLAN_BPS_MIN == 10 < P.FLOOR_BPS == 20


def test_no_other_knos_tool_builds_set_plan():
    """Outside fixtures and tests, only plan_floor calls pay.set_plan_ix."""
    found = []
    for base in ("src", "scripts"):
        for f in (ROOT / base).rglob("*.py"):
            if "set_plan_ix(" in f.read_text(encoding="utf-8"):
                found.append(f.relative_to(ROOT).as_posix())
    assert sorted(found) == ["scripts/settle_fixtures.py", "src/knos/plan_floor.py", "src/knos/settle/v2/meter.py", "src/knos/settle/v2/pay.py"]


def test_the_check_passes_when_every_plan_in_force_is_at_or_above_20():
    call, asked = _call(FIX["ok"])
    found = P.plans(call)
    assert asked[0][0] == "getProgramAccounts" and asked[0][1][0] == str(pay.PAY_ID)
    assert asked[0][1][1]["filters"] == [{"dataSize": pay.PLAN_LEN}]
    assert [f.owner_id for f in found] == sorted([1001, 1002, 1003], key=lambda o: str(pay.plan_pda(o)))
    assert P.below(found, FIX["now"]) == []          # 1002's 10 bps Plan has expired
    assert P.lines(found, FIX["now"])[-1] == "No Plan in force is below 20 bps."


def test_the_check_fails_on_a_plan_in_force_below_20():
    found = P.plans(_call(FIX["below"])[0])
    bad = P.below(found, FIX["now"])
    assert [f.owner_id for f in bad] == [1005]
    fake = next(f for f in found if f.owner_id == 1004)
    assert not fake.at_pda and fake not in bad        # not at its Plan address: the program never reads it
    assert "BELOW THE FLOOR: 1 Plan(s)" in P.lines(found, FIX["now"])[-1]


def test_the_words_are_the_ones_the_docs_use():
    assert P.DOC == "the program allows 10 bps; Knos signs no Plan below 20 bps; the check proves which Plans exist."
    assert "The program allows 10 bps; Knos signs no Plan below 20 bps; the check proves which Plans exist." in (ROOT / "docs" / "reference" / "ENFORCEMENT.md").read_text(encoding="utf-8")


def test_the_command_exits_1_below_the_floor(monkeypatch):
    import typer
    from typer.testing import CliRunner

    from knos import chain
    app = typer.Typer()
    P.register(app, [])

    class Led:
        url = "http://fake"

        def now(self):
            return FIX["now"]
    monkeypatch.setattr(chain, "ledger", lambda: Led())
    for rows, code in ((FIX["ok"], 0), (FIX["below"], 1)):
        monkeypatch.setattr(chain, "call", lambda url, method, params, timeout=10.0, rows=rows: rows)
        got = CliRunner().invoke(app, ["fees", "plans", "--check"])
        assert got.exit_code == code, got.output
