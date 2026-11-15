"""Sibyl Pro, bought by Knos: one payment to Knos (Pro, a Team seat, or a job's 5% fee) gives the paying wallet Sibyl
Pro for the 30 days after it. No second checkout, no threshold. Simulated on testnets, built and locked on mainnet."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from knos import sibyl_pro
from knos.pro import licence

U = 1_000_000


def _checkout(tmp_path, network="devnet"):
    return sibyl_pro.checkout_for(network, tmp_path / "sibyl-pro.json")


def test_a_pro_payment_gives_sibyl_pro_for_30_days(tmp_path):
    body = licence.from_payment("pro-month", "sigPRO", "ref1", "devnet", 22.0, payer="BuyerPro111")
    co = _checkout(tmp_path)
    g = sibyl_pro.from_licence(body, co)
    paid = datetime.fromisoformat(body["verified_at"])
    assert g.wallet == "BuyerPro111" and g.source == "pro-month" and g.simulated
    assert datetime.fromisoformat(g.until) == paid + timedelta(days=30)
    assert sibyl_pro.active("BuyerPro111", "devnet", paid + timedelta(days=29), co)
    assert not sibyl_pro.active("BuyerPro111", "devnet", paid + timedelta(days=31), co)
    assert sibyl_pro.from_licence(body, co).ref == g.ref and len(co.grants("BuyerPro111")) == 1   # once per payment


def test_a_team_seat_payment_gives_sibyl_pro_for_every_seat(tmp_path):
    body = licence.from_payment("team-seat", "sigTEAM", "ref2", "devnet", 96.0, seats=3, payer="TeamOwner11")
    g = sibyl_pro.from_licence(body, _checkout(tmp_path))
    assert g.source == "team-seat" and g.seats == 3 and g.simulated


def test_an_accepted_job_gives_its_buyer_sibyl_pro(tmp_path, monkeypatch):
    pytest.importorskip("solders.litesvm")
    from knos.jobs import market
    from _jobharness import LocalLedger
    from _jobharness import Escrow
    from knos.jobs.relay import DirRelay
    monkeypatch.setenv("KNOS_HOME", str(tmp_path / "home"))
    env = Escrow()
    ledger, relay = LocalLedger(env), DirRelay(tmp_path / "relay")
    buyer, _ = env.party(2 * U)
    worker, _ = env.party()
    jid = market.post(ledger, relay, buyer, market.Brief("t", "x"), U)
    market.claim(ledger, worker, jid)
    market.deliver(ledger, relay, worker, jid, buyer.pubkey(), b"x")
    assert sibyl_pro.active(str(buyer.pubkey()), "localnet") is None
    market.accept(ledger, buyer, jid)                       # the one payment: the escrow takes the 5% fee
    g = sibyl_pro.active(str(buyer.pubkey()), "localnet")
    assert g and g.source == "job-fee" and g.simulated
    assert sibyl_pro.active(str(worker.pubkey()), "localnet") is None   # the worker paid Knos nothing


def test_later_payments_extend_and_mainnet_is_locked(tmp_path):
    co = _checkout(tmp_path)
    t0 = datetime(2026, 10, 1, tzinfo=timezone.utc)
    a = sibyl_pro.grant("W", "job-fee", "job:a", "devnet", t0, checkout=co)
    b = sibyl_pro.grant("W", "job-fee", "job:b", "devnet", t0 + timedelta(days=10), checkout=co)
    assert datetime.fromisoformat(b.until) == datetime.fromisoformat(a.until) + timedelta(days=30)
    with pytest.raises(sibyl_pro.Locked):
        sibyl_pro.grant("W", "pro-month", "sigMAIN", "mainnet", t0, checkout=_checkout(tmp_path, "mainnet"))
