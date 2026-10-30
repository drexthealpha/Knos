"""Projects of Knos's web app (apps/wanted valley) moved by passkeys only, end to end inside LiteSVM: the deployed
LazorKit bytes and the knos_pay 0.3.34 test build (the world of tests/test_passkey_money_app.py). A funder's passkey
funds a milestone before any maker claims it; a buyer's passkey commits to buy (an allowance, nothing moves); a maker
claims it, paid to its passkey wallet; a result and an independent check release the escrow to the maker and the
allowance is collected. Past the deadline a passkey funding is refunded to the funder's own wallet. Synthetic test
units; the server never holds a passkey's key."""
from __future__ import annotations

import pytest

pytest.importorskip("solders.litesvm")

from solders.pubkey import Pubkey  # noqa: E402
from test_passkey_chain import RP_ID  # noqa: E402
from test_passkey_money_app import Person, app, tokens  # noqa: E402,F401 - the fixture

from knos.settle.v2 import pay  # noqa: E402

from knos_wanted import escrow, front, valley, wallets  # noqa: E402


def _project():
    p = valley.create_project(front.SEED_OWNER, "hardware_prototype", "Sweat glucose watch", report="c" * 64)
    return p["id"], p["milestones"][0]["key"]


def test_a_passkey_funds_a_milestone_before_any_maker_a_buyer_commits_and_the_maker_is_paid_on_two_pages(app, monkeypatch):  # noqa: F811
    c, led = app
    monkeypatch.setattr(valley, "_ledger", lambda led_=None: led_ or led)
    funder, buyer, maker, checker = Person(71, "funder"), Person(72, "buyer"), Person(73, "maker"), Person(74, "checker")
    pid, key = _project()
    with pytest.raises(wallets.NeedPasskey):                      # a guest has no wallet: nothing is funded for it
        wallets.prepare_project_fund(led, {"sub": "guest:x", "kind": "guest", "label": "x"}, pid, key, 10, RP_ID)
    wallets.faucet(led, wallets.holder(funder.user), RP_ID)
    step = wallets.prepare_project_fund(led, funder.user, pid, key, 10, RP_ID)
    assert step["kind"] == "project_fund" and step["summary"]["amount_units"] == 10
    with pytest.raises(wallets.NeedPasskey):                      # another person cannot answer this step
        buyer.approve(led, step)
    got = funder.approve(led, step)
    assert got["status"] == "locked" and got["kind"] == "funder"
    order = Pubkey.from_string(got["order"])
    assert c.order(order).amount == 10 * escrow.UNIT
    fv = wallets.addresses(wallets.holder(funder.user))["vault"]
    assert tokens(c, pay.ata(fv, c.usdc)) == wallets.FAUCET_UNITS * escrow.UNIT - 10 * escrow.UNIT - pay.order_fee(10 * escrow.UNIT)
    m = valley.public_project(valley.project(pid))["milestones"][0]
    assert m["status"] == "funded" and m["locked_units"] == 10
    # the buyer commits to buy: an allowance to the relayer, nothing moves yet
    wallets.faucet(led, wallets.holder(buyer.user), RP_ID)
    bv = wallets.addresses(wallets.holder(buyer.user))["vault"]
    a = buyer.approve(led, wallets.prepare_amc(led, buyer.user, pid, key, 6, RP_ID))
    assert a["status"] == "approved" and tokens(c, pay.ata(bv, c.usdc)) == wallets.FAUCET_UNITS * escrow.UNIT
    # the maker attempts it, paid to its passkey wallet; a result and an independent check (another person, another site)
    mv = wallets.ensure(led, wallets.holder(maker.user), RP_ID)["vault"]
    att = valley.claim(pid, key, maker.user, str(mv))
    cid = valley._load("orders", got["order"])["claim_id"]
    page = f"<html>built and measured: {cid}</html>".encode()
    valley.post(pid, key, att["id"], maker.user, "https://maker.example/result", "result", fetch=lambda url: page)
    out = valley.post(pid, key, att["id"], checker.user, "https://lab.example.org/check", "check", fetch=lambda url: page)
    assert out["verdict"]["pass"]                       # a human-verified milestone: released when its challenge window ends
    out = next(x for x in valley.release_due(now=out["verdict"]["ends_s"], led=led) if x["project"] == pid)   # this project's, whatever else is due
    assert [x["status"] for x in out["released"]] == ["released"] and out["milestone"] == "released"
    assert tokens(c, pay.ata(mv, c.usdc)) == 10 * escrow.UNIT + 6 * escrow.UNIT          # the escrow and the collected allowance
    assert tokens(c, pay.ata(bv, c.usdc)) == wallets.FAUCET_UNITS * escrow.UNIT - 6 * escrow.UNIT


def test_past_the_deadline_a_passkey_funding_is_refunded_to_the_funders_own_wallet_and_reopens(app, monkeypatch):  # noqa: F811
    c, led = app
    monkeypatch.setattr(valley, "_ledger", lambda led_=None: led_ or led)
    funder = Person(75, "funder")
    p = valley.create_project(front.SEED_OWNER, "internal_tool", "A tool", deadline_s=120)
    key = p["milestones"][0]["key"]
    wallets.faucet(led, wallets.holder(funder.user), RP_ID)
    got = funder.approve(led, wallets.prepare_project_fund(led, funder.user, p["id"], key, 5, RP_ID, kind="pool", pool="pool-test-1"))
    assert got["kind"] == "pool" and valley._load("pools", "pool-test-1")["orders"] == [got["order"]]
    tok = pay.ata(wallets.addresses(wallets.holder(funder.user))["vault"], c.usdc)
    before = tokens(c, tok)
    o = c.order(Pubkey.from_string(got["order"]))
    c.warp(600)
    swept = valley.sweep(led=led)
    assert swept["swept"][0]["status"] in ("refunded", "closed") and swept["swept"][0]["reopened"]["reopened"]
    assert tokens(c, tok) == before + o.amount + o.fee
    assert valley.project(p["id"])["milestones"][0]["status"] == "reopened"
