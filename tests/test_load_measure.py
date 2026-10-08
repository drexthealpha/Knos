"""`scripts/load.py measure`: N relays side by side, each with a fee payer of its own, fund M orders twice, once with
no account in common and once with one shared writable account; the simulator proves the path and gives no rate, and
docs/LOAD.md keeps what was measured on devnet apart from what is derived."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("solders.litesvm")

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [p for p in (str(ROOT / "scripts"), str(ROOT / "tests")) if p not in sys.path]
_spec = importlib.util.spec_from_file_location("knos_load_measure", ROOT / "scripts" / "load.py")
load = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = load
_spec.loader.exec_module(load)

from load_sim import SimRpc  # noqa: E402


def run(relays: int, orders: int, **kw) -> tuple[dict, SimRpc]:
    sim = SimRpc(**kw)
    wallet = sim.c.fund()
    got = load.measure(sim, wallet, relays, orders, name="simulator", sender=lambda payer: load.Sender(sim, payer, within=30.0, poll=1.0, clock=sim.clock, sleep=sim.sleep))
    return got, sim


def test_relays_with_their_own_fee_payers_fund_apart_and_through_one_shared_account_and_leave_nothing():
    got, sim = run(3, 7, drop=lambda k: k % 11 == 0)
    assert got["ok"], got
    assert len(set(got["fee_payers"])) == 3 and got["wallet"] not in got["fee_payers"]            # distinct fee payers, none the wallet
    apart, shared = got["phases"]["apart"], got["phases"]["shared"]
    assert apart["confirmed"] == shared["confirmed"] == 7 and apart["failures"] == shared["failures"] == 0
    assert apart["retries"] + shared["retries"] > 0                                                # the dropped ones were signed again
    assert apart["slots"] == shared["slots"] == 7 and shared["most_in_one_slot"] == 1              # the simulator: one a slot
    assert set(got["contention"]) == {"rate_shared_over_apart", "retries_more", "failures_more", "most_in_one_slot"}
    assert got["refunded"] == 14 and got["orders_left"] == 0 and got["swept"] == 3                 # every order refunded, every relay's SOL back
    left = [sim.call("getBalance", [k, {}])["value"] for k in got["fee_payers"]]
    assert all(x <= 5_000 for x in left) and 0 < got["sol_spent"] < 0.05
    # the shared account took one base unit from every `shared` transaction, and nothing from an `apart` one
    from solders.pubkey import Pubkey
    assert load.token_balance(sim, Pubkey.from_string(got["shared_account"])) == 7


def test_the_fee_payers_are_the_same_every_run_so_a_run_that_died_is_swept_by_the_next():
    from solders.keypair import Keypair
    wallet = Keypair.from_seed(bytes(range(32)))
    assert [str(k.pubkey()) for k in load.relay_keys(wallet, 2)] == [str(k.pubkey()) for k in load.relay_keys(wallet, 3)][:2]
    got, sim = run(2, 0)
    assert got["ok"] and got["phases"] == {} and got["swept"] == 0 and "mint" not in got          # --orders 0: only the sweep


def test_the_page_keeps_measured_and_derived_apart_and_says_when_nothing_is_measured():
    doc = {"limits": load.LIMITS, "sources": load.SOURCES, "runs": []}
    text = "\n".join(load.render_measured(doc))
    assert "**Measured on devnet: nothing yet.**" in text and "gives no rate" in text and "Derived bound" not in text
    for way, _state in load.REDUCES:
        assert f"| {way} |" in text
    assert "needs a program change" in text
    got, _sim = run(2, 4)
    sim_only = "\n".join(load.render_measured({**doc, "measured": [got]}))
    assert "**Measured on devnet: nothing yet.**" in sim_only                                     # a simulated run is never shown as measured
    got.update(cluster="devnet", date="2026-10-09")
    for x in got["phases"].values():
        x.update(seconds=10.0, confirmed_per_s=0.4)
    got["contention"]["rate_shared_over_apart"] = 1.0
    shown = "\n".join(load.render_measured({**doc, "measured": [got], "local": json.loads((ROOT / "docs" / "load.json").read_text(encoding="utf-8"))["local"]}))
    assert "**Measured on devnet (2026-10-09): 2 relays, 4 orders each way**" in shown and "nothing yet" not in shown
    assert "| apart: no account written by two relays | 4 of 4 | 10.0 | 0.4 |" in shown
    assert "**Derived bound (not measured).**" in shown and shown.index("Measured on devnet (") < shown.index("Derived bound")
    page = (ROOT / "docs" / "LOAD.md").read_text(encoding="utf-8")
    assert "### Throughput with relays side by side: measured, and derived" in page and "**Derived bound (not measured).**" in page


def test_the_command_simulates_from_the_shell_and_never_writes_a_simulated_run():
    cmd = [sys.executable, str(ROOT / "scripts" / "load.py"), "measure", "--relays", "2", "--orders", "2", "--simulate"]
    out = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    assert out.returncode == 0, out.stderr
    got = json.loads(out.stdout[out.stdout.index("{"):])
    assert got["cluster"] == "simulator" and got["ok"] and "say nothing about a cluster" in got["note"]
    no = subprocess.run([*cmd, "--write"], capture_output=True, text=True, encoding="utf-8")
    assert no.returncode == 2 and "never written" in no.stderr
