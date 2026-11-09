"""Internal dogfooding (Knos buying its own v0.3.31 work from its own agents, with its own devnet test mint) is never
outside use: scripts/network_stats.py, which writes the public numbers, counts its vaults and payouts as Knos's own."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import network_stats  # noqa: E402
import outsiders as rules  # noqa: E402

OWN = json.loads((ROOT / "scripts" / "own_github_ids.json").read_text(encoding="utf-8"))
DOG = OWN["internal_dogfooding"]
BUYER, WORKER = "BVG9LGYgz5MXMxYrZfsqyTiRJfrTytvckGiY6jGVxUU7", "46trbyHqwgy3RYBaEN5J3fdngiJzPEWmHcNUZLCtgBpp"
KNOS_E2E = 1401439243


def test_the_dogfooding_wallets_are_labelled_and_on_the_own_list():
    assert DOG["label"] == "internal dogfooding"
    assert {BUYER, WORKER} <= set(DOG["wallets"]) <= network_stats.OWN_WALLETS
    # the payees the workers (V31CAP, V31FOLD) named for their dogfooding payouts
    assert {"4gMAzHhf7JyHfNgYtAmm2E3j6ymBabTTAsw6Naabd262", "CKM9YFKWMHR5a8Lm6TMmYjtLLq7vQNerDNhJ3EBfZ68R"} <= network_stats.OWN_WALLETS
    assert DOG["mints"] == ["FrSNZ9Lhf1gEE5SfmY6AjF4GxisqoX5Jd8S9VX27ZUyL"]


def test_a_dogfooding_escrow_and_its_payout_count_as_own_never_outside():
    job = {"v": 2, "by": 0, "owner": 0, "wallet": BUYER, "source": BUYER, "repo": KNOS_E2E, "issue": 276,
           "faucet": False, "state": "paid", "payee": 142920951, "to": WORKER}
    assert network_stats.kind_of(job, network_stats.OWN, network_stats.OWN_WALLETS) == "own"
    assert rules.funder_of(job, network_stats.OWN, network_stats.OWN_WALLETS) is None
    # the same job by a wallet nobody listed would have been an outside funder: the list is what keeps it out
    stranger = {**job, "wallet": "9" * 32, "source": "9" * 32, "payee": 77, "to": "8" * 32}
    assert network_stats.kind_of(stranger, network_stats.OWN, network_stats.OWN_WALLETS) == "outside"


def test_a_dogfooding_funding_logged_on_chain_adds_nothing_to_the_public_numbers():
    line = (f"knos2:funded repo={KNOS_E2E} issue=276 amount=20000000 mode=0 by=0 source={BUYER} faucet=0")
    tx = {"blockTime": 1_791_000_000, "meta": {"err": None, "logMessages": [
        f"Program {network_stats.pay2.PAY_ID} invoke [1]", f"Program log: {line}",
        'Program log: knos2:terms {"accept":"","checks":[],"v":1}', f"Program {network_stats.pay2.PAY_ID} success"]},
          "transaction": {"message": {"accountKeys": [BUYER, str(network_stats.pay2.PAY_ID)]}}}
    events = [{**e, "tx": "sig0"} for e in network_stats.events_of(tx)]
    s = network_stats.summarize(events, network_stats.OWN, network_stats.OWN_WALLETS)
    assert s["outside"]["funded"] == 0 and s["outside"]["funders"] == 0 and s["apart"]["own"]["funded"] == 1


def test_the_wallets_the_0329_to_0331_agents_funded_and_paid_with_are_knos_own():
    for w in ("H3iUwqY9aKKD1H9m5MmTYNcwcv8xUkGDDDfps6XjXtBP",      # GATE: funded knos-e2e#273 and paid it on devnet
              "GCwDckc2GudYaUPstyZX6KPUufBKv8x9e1gRtMh8MzUm",      # V30QLOO: pre-orders
              "DqH5N34nJQydHFDMjiMyWjfSsQUnKrcjwDhcWdMgk5Cp"):     # ZK deployer: funded the dogfooding buyer
        assert w in network_stats.OWN_WALLETS
