"""The fee account is one of K, and pay work is partitioned by order (0.3.22).

knos_pay takes any token account of the order's mint that FEE_OWNER owns as the fee account (`is_owned(fee_tok, token,
mint, FEE_OWNER)` in order_pay.rs and order_terms.rs): shown here on the committed build in LiteSVM with a SEEDED
account, not the associated one, for PayOrder and SettleOrder; an account of another owner or another mint is still
refused. Then the relay's side: which of K an order uses, the fallback when that one is not on chain, the lane of an
order's tokens, and one owner's 40 orders spread over the parts of N relays with no order taken twice."""
from __future__ import annotations

import base64
import json
from types import SimpleNamespace

import pytest
from solders.keypair import Keypair
from solders.pubkey import Pubkey

from knos.settle.v2 import pay, relay, relayq
from knos.settle.v2 import fee_accounts

from _pay21 import pay21_build  # noqa: F401 - the fixture `pay21`

BASE = Keypair.from_seed(bytes([9] * 32)).pubkey()
ORDERS = [Pubkey(bytes([i + 1] * 32)) for i in range(40)]


def jwt(aud: str, **claims) -> str:
    """A token's shape with these claims (unsigned: only its lane is read here)."""
    enc = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()  # noqa: E731
    return f"{enc({'alg': 'RS256', 'kid': 'k1'})}.{enc({'aud': aud, 'iat': 1000, **claims})}.c2ln"


# ---- the program ---------------------------------------------------------------------------------------------------------

def _seeded(c, i: int = 1, mint: Pubkey | None = None) -> Pubkey:
    """Fee account i of the mint, made as `knos relay fee-accounts --execute` makes it: the harness's payer is the base."""
    mint = mint or c.usdc
    me = c.payer.pubkey()
    assert c.send(pay.create_fee_account_ixs(me, me, mint, i, c.svm.minimum_balance_for_rent_exemption(pay.TOKEN_ACCOUNT_LEN))), c.err
    address = pay.fee_accounts(mint, pay.TOKEN, i + 1, me)[i]
    assert address != pay.ata(pay.FEE_OWNER, mint)
    return address


def pays(c, order: Pubkey, payees, fee: Pubkey) -> bool:
    return c.send([c.pay_ix(order, c.pay_token(order, payees), payees, fee_token=fee)], tag="pay_order")


@pytest.mark.parametrize("live", [False, True], ids=["2.2 (proposals 7 and 8)", "2.1 (live at the public id today)"])
def test_pay_order_and_settle_order_take_a_seeded_token_account_of_the_fee_owner_and_nothing_else(live, request):
    pytest.importorskip("solders.litesvm")
    from _order import USDC, OrderChain, code, user
    c = OrderChain(pay_build=request.getfixturevalue("pay21")) if live else OrderChain()
    shard = _seeded(c)
    assert c.data(shard) is not None and c.balance(shard) == 0
    # PayOrder: a payee whose token account exists, so the tip is 0.05 and the rest of the fee is FEE_OWNER's (2.2: 0.25 of 0.30; 2.1: 2.45 of 2.50)
    payee, wallet = user(), Keypair().pubkey()
    c.token_account(wallet, c.usdc)
    order = c.fund_wallet(amount=100 * USDC)
    before = c.balance(c.fee)
    assert pays(c, order, [(payee, 10_000, wallet)], shard), c.err
    assert (c.balance(c.fee), c.balance(pay.ata(wallet, c.usdc))) == (before, 100 * USDC) and c.balance(shard) == (2_450_000 if live else 250_000)
    # refused still: a token account of the mint that another wallet owns, and FEE_OWNER's account of another mint
    other_mint = c.new_mint()
    wrong_mint = _seeded(c, 1, other_mint)
    _thief, thief_tok = c.wallet(c.usdc, 0)
    for bad in (thief_tok, wrong_mint):
        order = c.fund_wallet(amount=20 * USDC)
        assert not pays(c, order, [(payee, 10_000, wallet)], bad) and code(c) == 88
    # SettleOrder: an order held for a payee with no wallet, settled when he binds one, its fee to the seeded account
    later, w2 = user(), Keypair().pubkey()
    order = c.fund_wallet(amount=100 * USDC)
    assert c.pay(order, [(later, 10_000, None)]), c.err
    assert c.order(order).state == "held"
    c.token_account(w2, c.usdc)
    assert c.bind(later, w2), c.err
    have = c.balance(shard)
    assert c.settle(order, w2, fee_token=shard), c.err
    assert c.balance(shard) > have and c.balance(pay.ata(w2, c.usdc)) == 100 * USDC


# ---- which account, and the plan that makes them -------------------------------------------------------------------------

def test_an_order_always_uses_the_same_one_of_k_and_k_one_is_the_associated_account(monkeypatch):
    mint = pay.USDC_DEVNET
    home = pay.ata(pay.FEE_OWNER, mint)
    assert pay.fee_shards() == (1, None) and {pay.fee_account_for(o, mint) for o in ORDERS} == {home}
    monkeypatch.setenv("KNOS_FEE_SHARDS", "8")
    assert pay.fee_shards() == (1, None)                    # a K with no base is 1: nobody could have made the others
    monkeypatch.setenv("KNOS_FEE_BASE", str(BASE))
    every = pay.fee_accounts(mint)
    assert pay.fee_shards() == (8, BASE) and len(set(every)) == 8 and every[0] == home
    used = [pay.fee_account_for(o, mint) for o in ORDERS]
    assert used == [pay.fee_account_for(o, mint) for o in ORDERS] and len(set(used)) >= 6       # 40 orders over 8 accounts
    assert set(pay.fee_accounts(pay.faucet_mint())).isdisjoint(every)       # each mint its own
    assert pay.fee_accounts(mint, pay.TOKEN_2022) == [pay.ata(pay.FEE_OWNER, mint, pay.TOKEN_2022)]     # Token-2022: the associated one
    monkeypatch.setenv("KNOS_FEE_SHARDS", "not a number")
    assert pay.fee_shards() == (1, None)


def test_the_relay_names_the_associated_account_while_the_chosen_one_is_not_on_chain(monkeypatch):
    monkeypatch.setenv("KNOS_FEE_SHARDS", "4")
    monkeypatch.setenv("KNOS_FEE_BASE", str(BASE))
    o = SimpleNamespace(mint=pay.USDC_DEVNET, token_program=pay.TOKEN)     # what the two read of an order
    home = pay.ata(pay.FEE_OWNER, o.mint)
    order = next(x for x in ORDERS if pay.fee_account_for(x, o.mint) != home)
    chosen = pay.fee_account_for(order, o.mint)
    me = Keypair.from_seed(bytes([3] * 32)).pubkey()
    assert relay._fee_account(order, o, {chosen: None, home: None}) == home
    assert relay._fee_account(order, o, {chosen: (pay.TOKEN, b"x"), home: None}) == chosen
    # a seeded one is never made by a payment; the associated one is, when it is the one named and missing
    made = lambda fee: [str(ix.accounts[1].pubkey) for ix in relay._tip_accounts(me, o, {}, fee)[0]]  # noqa: E731
    assert made(chosen) == [str(pay.ata(me, o.mint))] and made(home) == [str(pay.ata(me, o.mint)), str(home)]


def test_the_command_plans_k_accounts_per_mint_and_sends_nothing_without_execute(capsys):
    got = fee_accounts.plan(4, BASE, [pay.USDC_DEVNET, pay.faucet_mint()], exists=lambda a: a == pay.ata(pay.FEE_OWNER, pay.USDC_DEVNET))
    assert len(got["accounts"]) == 8 and got["to_make"] == 6 and got["rent_lamports"] == 6 * fee_accounts.RENT_165
    assert got["settings"] == {"KNOS_FEE_SHARDS": "4", "KNOS_FEE_BASE": str(BASE)} and "FEE_OWNER" in got["sweep"]
    assert [r["i"] for r in got["accounts"] if r["make"]] == [1, 2, 3, 1, 2, 3]
    txs = fee_accounts.make_ixs(BASE, BASE, got["accounts"])
    assert len(txs) == 6 and all(tx[1].data[1:] == bytes(pay.FEE_OWNER) for tx in txs)
    assert fee_accounts.main(["--k", "3", "--base", str(BASE), "--mint", str(pay.USDC_DEVNET)]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["to_make"] == 2 and "sent" not in printed
    with pytest.raises(SystemExit):
        fee_accounts.main(["--k", "0", "--base", str(BASE)])


# ---- lanes and parts -----------------------------------------------------------------------------------------------------

def test_an_orders_tokens_travel_in_the_orders_lane_and_a_funding_in_its_owners():
    pays = [jwt(f"knos3:pay:{o}:{'a' * 40}:{'b' * 64}:0:7:1:10000:", repository_owner_id="77") for o in ORDERS[:3]]
    assert [relay.lane(t) for t in pays] == [f"order:{o}" for o in ORDERS[:3]]
    for word in ("auto", "rule", "take", "cancel", "revert"):       # one order's tokens: one lane, whoever's
        assert relay.lane(jwt(f"knos3:{word}:{ORDERS[0]}:x", repository_owner_id="77")) == relay.lane(jwt(f"knos3:{word}:{ORDERS[0]}:x")) == f"order:{ORDERS[0]}"
    # a funding from a Balance keeps the owner's lane: the Balance takes its fundings in the order GitHub issued them
    assert relay.lane(jwt(f"knos3:fund:1:5000000:0:{'b' * 64}:1209600:{ORDERS[5]}:0", repository_owner_id="77")) == "owner:77"
    assert relay.lane(jwt("knos3:pay:short:x", repository_owner_id="77")) == "owner:77"     # no order address: the owner's


def test_one_owners_forty_orders_spread_over_four_relays_and_two_relays_never_take_one_order(tmp_path):
    tokens = [jwt(f"knos3:pay:{o}:{'a' * 40}:{'b' * 64}:0:7:1:10000:", repository_owner_id="77") for o in ORDERS]
    lanes = [relay.lane(t) for t in tokens]
    parts = [relayq.part_of(lane, 4) for lane in lanes]
    assert len(set(lanes)) == 40 and set(parts) == {0, 1, 2, 3} and max(parts.count(p) for p in range(4)) <= 16
    queues = [relayq.Queue(tmp_path / "shared.json", lambda: 0.0, part=(i, 4)) for i in range(4)]
    for n, (t, lane) in enumerate(zip(tokens, lanes)):
        assert queues[0].put(f"k{n:02d}", lane, {"jwt": t})
    took = [{e["lane"] for e in iter(lambda q=q, i=i: q.take(f"R{i}:w1"), None)} for i, q in enumerate(queues)]
    assert all(took) and sum(len(t) for t in took) == 40 and set().union(*took) == set(lanes)
    assert all(not took[i] & took[j] for i in range(4) for j in range(i + 1, 4))
    # before 0.3.22 the same 40 tokens had one lane, the owner's, and so one relay
    assert len({f"owner:{json.loads(base64.urlsafe_b64decode(t.split('.')[1] + '=='))['repository_owner_id']}" for t in tokens}) == 1


def test_knos_relay_fee_accounts_is_reached_from_the_command_line(capsys):
    """`knos relay fee-accounts` comes through the console script (knos.__main__ -> knos.flow) to its own options."""
    from knos.__main__ import main
    try:
        code = main(["relay", "fee-accounts", "--help"])
    except SystemExit as stop:          # argparse's --help
        code = int(stop.code or 0)
    assert code == 0 and "usage: knos relay fee-accounts" in capsys.readouterr().out
