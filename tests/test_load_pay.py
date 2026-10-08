"""`scripts/load_pay.py`: end-to-end PayOrder capacity with N relays, each with a fee payer of its own. The simulator
proves the whole path (write, verify, PayOrder) and counts; it gives no rate. On a cluster every payment attempted is
counted, and a failure or a payment that never completed is never dropped from the denominator."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("knos_load_pay", ROOT / "scripts" / "load_pay.py")
load_pay = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = load_pay
_spec.loader.exec_module(load_pay)

from solders.keypair import Keypair  # noqa: E402

from knos.settle.v2 import relayq  # noqa: E402


def test_the_simulator_pays_every_order_once_each_by_the_relay_of_its_part_with_that_relays_key_alone():
    pytest.importorskip("solders.litesvm")
    got = load_pay.simulate(3, 6)
    assert got["ok"] and all(got["checks"].values()), got["checks"]
    assert (got["attempted"], got["paid"], got["refused"], got["never_completed"]) == (6, 6, 0, 0)
    assert sum(r["attempted"] for r in got["per_relay"]) == 6 and len(set(got["fee_payers"])) == 3
    assert got["rate"] is None and got["seconds"] is None and "times nothing" in got["why_no_rate"]       # no rate from a simulator
    assert got["transactions_per_payment"]["p50"] >= 2 and got["cu_per_payment"]["n"] == 6


def test_on_a_cluster_every_attempt_is_counted_with_its_failures_and_percentiles_apart():
    """A stand-in relay: one token refused, one that never answers. Paid 2 of 4, and the rate says of what."""
    from knos.settle.v2 import relay
    tokens = [{"kind": "pay", "jwt": f"t{i}"} for i in range(4)]
    lanes = {f"t{i}": str(i) for i in range(4)}
    clock = iter(float(x) for x in range(100))
    seen: dict[str, str] = {}

    def send(ledger, key, kind, jwt):
        seen[jwt] = str(key.pubkey())
        if jwt == "t1":
            return {"ok": False, "why": "the program refused it"}
        if jwt == "t2":
            raise TimeoutError("no answer")
        return {"ok": True}
    wallet = Keypair.from_seed(bytes(32))
    real = relay.lane
    relay.lane = lambda jwt: lanes[jwt]
    try:
        got = load_pay.on_cluster(None, wallet, 2, tokens, clock=lambda: next(clock), relay_one=send, lend=lambda k: True, sweep=lambda k: None)
    finally:
        relay.lane = real
    assert (got["attempted"], got["paid"], got["refused"], got["never_completed"]) == (4, 2, 1, 1) and got["ok"] is False
    assert got["first_refusals"] == ["the program refused it"]
    assert set(got["payment_s"]) == {"n", "p50", "p95", "p99", "max"} and got["payment_s"]["n"] == 2
    assert got["paid_per_s"] is not None and got["seconds"] > 0
    keys = got["fee_payers"]
    assert all(seen[t["jwt"]] == keys[relayq.part_of(lanes[t["jwt"]], 2)] for t in tokens)      # each token by the relay of its part
    # a relay that was not lent its SOL: nothing is sent, and the run says why
    got = load_pay.on_cluster(None, wallet, 2, tokens, relay_one=send, lend=lambda k: False, sweep=lambda k: None)
    assert got["ok"] is False and got["attempted"] == 0 and "not lent" in got["stopped"]


def test_the_command_asks_for_what_it_needs():
    run = lambda *a: subprocess.run([sys.executable, str(ROOT / "scripts" / "load_pay.py"), *a], capture_output=True, text=True, encoding="utf-8")  # noqa: E731
    assert run("--relays", "2").returncode == 2 and "--tokens" in run("--relays", "2").stderr
    assert run("--relays", "2", "--simulate").returncode == 2
    assert run("--relays", "0", "--simulate", "--orders", "1").returncode == 2


def test_a_token_another_relay_carried_first_is_counted_and_never_as_paid():
    """`already`: the chain showed the payment done before this relay sent anything. It is in the denominator, and it
    is not a payment of the run: counting it as paid would time a read, not a PayOrder."""
    from knos.settle.v2 import relay
    tokens = [{"kind": "pay", "jwt": f"t{i}"} for i in range(3)]
    real = relay.lane
    relay.lane = lambda jwt: jwt
    try:
        got = load_pay.on_cluster(None, Keypair.from_seed(bytes(32)), 2, tokens, relay_one=lambda led, k, kind, jwt: {"ok": True, "already": jwt == "t0"},
                                  lend=lambda k: True, sweep=lambda k: None)
    finally:
        relay.lane = real
    assert (got["attempted"], got["paid"], got["already"], got["refused"], got["never_completed"]) == (3, 2, 1, 0, 0) and got["ok"] is False
    assert got["payment_s"]["n"] == 2


def test_measure_pay_write_keeps_the_cluster_run_and_the_page_prints_it_with_its_denominator(tmp_path, monkeypatch):
    """`python scripts/load.py measure --pay --relays 4 --tokens FILE --wallet KEY --write`, the command docs/LOAD.md
    names: the run of scripts/load_pay.py is appended to docs/load.json and rendered under its own heading."""
    sys.path[:0] = [p for p in (str(ROOT / "scripts"), str(ROOT / "tests")) if p not in sys.path]
    import load
    import load_pay as lp
    monkeypatch.setattr(load, "JSON", tmp_path / "load.json")
    monkeypatch.setattr(load, "DOC", tmp_path / "LOAD.md")
    (tmp_path / "load.json").write_text(json.dumps({"runs": []}), encoding="utf-8")
    from knos.settle.v2 import pay
    record = {"kind": "pay", "cluster": "devnet", "date": "2026-10-09", "relays": 4, "orders": 5, "wallet": "W",
              "programs": {"knos_pay": str(pay.PAY_ID), "knos_oidc": str(pay.OIDC_ID), "ids": "the ids this installation names"},
              "fee_payers": ["A", "B", "C", "D"], "attempted": 5, "paid": 4, "refused": 1, "never_completed": 0, "already": 0,
              "per_relay": [], "first_refusals": ["error 91"], "seconds": 12.5, "paid_per_s": 0.32,
              "payment_s": {"n": 4, "p50": 2.1, "p95": 3.0, "p99": 3.0, "max": 3.0}, "ok": False}
    monkeypatch.setattr(lp, "on_cluster", lambda *a, **k: record)
    toks, key = tmp_path / "pay.json", tmp_path / "key.json"
    toks.write_text(json.dumps([{"kind": "pay", "jwt": "x"}]), encoding="utf-8")
    key.write_text(json.dumps(list(bytes(Keypair.from_seed(bytes(32))))), encoding="utf-8")
    assert load.main(["measure", "--pay", "--relays", "4", "--tokens", str(toks), "--wallet", str(key), "--write"]) == 1     # not every payment paid
    kept = json.loads((tmp_path / "load.json").read_text(encoding="utf-8"))["measured"]
    assert kept == [record]
    page = (tmp_path / "LOAD.md").read_text(encoding="utf-8")
    assert ("#### Measured on devnet, public program ids, 2026-10-09: end-to-end PayOrder: token verification, then the payment; "
            "4 relays, 5 payments attempted (did not complete cleanly)") in page
    assert "| 5 | 4 of 5 | 0 | 1 | 0 | 12.5 | 0.32 | 2.1 | 3.0 | none: fewer than 100 payments | 3.0 |" in page
    assert "Not measured: end-to-end PayOrder capacity" not in page and "The first refusals: error 91." in page
    import rate_claims
    assert rate_claims.check(page) == []
    with pytest.raises(SystemExit):
        load.main(["measure", "--pay", "--relays", "2", "--orders", "2", "--simulate", "--write"])      # a simulated run is never written
