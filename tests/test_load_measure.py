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



def test_a_transaction_that_landed_while_its_relay_waited_past_its_window_is_asked_about_not_signed_again():
    """The relays share one clock (on a cluster, the wall clock). A relay that was held up between landing a transaction
    and asking its status, while another relay's polling moved the clock past its window, signed it again and sent it
    a second time: run 38039594436 refunded 13 of 14 (the order had gone back; the second refund was refused), and a
    transfer would have been paid twice. Now the status is asked once more when the window has passed, before anything
    is signed again; and the same in `finalize`."""
    from solders.keypair import Keypair
    from solders.system_program import TransferParams, transfer
    sim = SimRpc()
    payer, to = sim.c.fund(), Keypair().pubkey()
    landed, read = sim.methods["sendTransaction"], sim.clock

    def held_up_after_landing(raw, cfg):
        sig = landed(raw, cfg)
        jump.append(31.0)
        return sig

    def clock():                    # the relay reads the time; then another relay's polling moves it 31 s on
        now = read()
        if jump:
            sim.t += jump.pop()
        return now

    jump: list[float] = []
    sim.methods["sendTransaction"] = held_up_after_landing
    sender = load.Sender(sim, payer, within=30.0, poll=1.0, clock=clock, sleep=sim.sleep)
    got = sender.send([transfer(TransferParams(from_pubkey=payer.pubkey(), to_pubkey=to, lamports=1_000_000))])
    assert got.ok and got.retries == 0 and sim.submissions == 1, got
    assert sim.call("getBalance", [str(to), {}])["value"] == 1_000_000                            # paid once
    sim.asked[got.signature] = 2    # by now the cluster has finalized it (the simulator says so at the third ask)
    jump.append(61.0)               # held up again, past the whole wait for `finalized`, before the first status is asked
    sender.finalize([got])
    assert got.ok and got.finalized is not None, got

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
    assert "needs a program change" not in text and "Several fee accounts for one mint | exists since 0.3.22, with no program change" in text
    got, _sim = run(2, 4)
    sim_only = "\n".join(load.render_measured({**doc, "measured": [got]}))
    assert "**Measured on devnet: nothing yet.**" in sim_only                                     # a simulated run is never shown as measured
    got.update(cluster="devnet", date="2026-10-09")
    for x in got["phases"].values():
        x.update(seconds=10.0, confirmed_per_s=0.4)
    got["contention"]["rate_shared_over_apart"] = 1.0
    shown = "\n".join(load.render_measured({**doc, "measured": [got], "local": json.loads((ROOT / "docs" / "load.json").read_text(encoding="utf-8"))["local"]}))
    head = "#### Measured on devnet, public program ids, 2026-10-09: funding only (FundOrderWallet), no PayOrder; 2 relays, 4 orders each way"
    assert head in shown and "nothing yet" not in shown
    assert "| apart: no account written by two relays | 4 of 4 | 10.0 | 0.4 | 0 | 0 of 4 |" in shown
    assert "**Derived bound (not measured).**" in shown and shown.index("Measured on devnet, ") < shown.index("Derived bound")
    # a funding rate is not a payment rate: until a PayOrder run is recorded the page says so, and names the command
    assert "**Not measured: end-to-end PayOrder capacity.**" in shown and "load.py measure --pay" in shown
    paid = {**got, "kind": "pay", "programs": {"knos_pay": "FJJtqcRjQ9ATx37sBTCLUBxBqLUA9aQgSTLAsZynqtnH"}}
    shown = "\n".join(load.render_measured({**doc, "measured": [paid]}))
    assert "#### Measured on devnet, STAGING program ids (not the public ones), 2026-10-09: end-to-end PayOrder" in shown
    assert "Not measured: end-to-end PayOrder capacity" not in shown
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


def test_every_cluster_run_says_which_program_ids_it_ran_on():
    """The 200-order run used staging ids and was summarised as "measured on devnet": the heading of every run now
    names its ids, read against the public ones."""
    public = json.loads((ROOT / "src" / "knos" / "settle" / "v2" / "program_ids.json").read_text(encoding="utf-8"))
    assert load.ids_of({"knos_pay": public["knos_pay"], "knos_oidc": public["knos_oidc"]}) == "public program ids"
    assert load.ids_of(public["knos_pay"]) == "public program ids"
    assert load.ids_of({"knos_pay": "FJJtqcRjQ9ATx37sBTCLUBxBqLUA9aQgSTLAsZynqtnH"}).startswith("STAGING")
    assert load.ids_of({"a": public["knos_pay"], "b": "FJJtqcRjQ9ATx37sBTCLUBxBqLUA9aQgSTLAsZynqtnH"}) == "public and STAGING program ids mixed"
    assert load.ids_of(None) == "program ids not recorded"
    page = (ROOT / "docs" / "LOAD.md").read_text(encoding="utf-8")
    kept = json.loads((ROOT / "docs" / "load.json").read_text(encoding="utf-8"))
    for r in kept["runs"]:
        assert f"### {r['cluster']}, {load.ids_of(r.get('programs'))}, {r['date']}:" in page
    assert "### devnet, STAGING program ids (not the public ones), 2026-10-04: 200 orders" in page
    assert "measured on devnet, STAGING program ids (not the public ones), 2026-10-04: 200 orders" in page
    assert page == load.render(load.load())                                       # written by the script, not by hand
