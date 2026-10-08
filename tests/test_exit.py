"""knos exit --before-upgrade (src/knos/exit.py) against knos_pay's test build in LiteSVM, with a pending upgrade
proposal built in the Squads layouts src/knos/mainnet_check.py reads (the builders of tests/test_site_recorded.py on
the real devnet multisig account). Each exit the plan names is then sent to the program, so the plan and the program
cannot disagree."""
from __future__ import annotations

import json

import pytest

pytest.importorskip("solders.litesvm")

from solders.keypair import Keypair  # noqa: E402
from solders.pubkey import Pubkey  # noqa: E402

from _order import DAY, USDC, OrderChain  # noqa: E402
from _pay2 import ChainLedger  # noqa: E402
from test_site_recorded import BUFFER_PAY, GOVERNANCE, IDS, SQUADS, proposal_account, vault_transaction_account  # noqa: E402

from knos import exit as kexit  # noqa: E402
from knos import mainnet_check as mc  # noqa: E402
from knos.settle.v2 import pay  # noqa: E402

HOUR = 3600


def squads_world(approved_at: int, status: str = "Approved") -> dict:
    """The devnet upgrade multisig with one proposal: an upgrade of knos_pay, `status` since `approved_at`."""
    real = bytes.fromhex(GOVERNANCE["squads_accounts"]["upgrade"]["data"])
    ms_key, squads = Pubkey.from_string(IDS["upgrade_multisig"]), Pubkey.from_string(SQUADS)
    return {IDS["upgrade_multisig"]: (SQUADS, real[:78] + (1).to_bytes(8, "little") + real[86:]),
            str(mc.proposal_address(ms_key, 1, squads)): (SQUADS, proposal_account(1, status, approved_at, 2 if status == "Approved" else 1)),
            str(mc.transaction_address(ms_key, 1, squads)): (SQUADS, vault_transaction_account(IDS["knos_pay"], BUFFER_PAY))}


@pytest.fixture()
def world():
    c = OrderChain()
    near = c.fund_wallet(amount=10 * USDC, work_s=DAY)            # its deadline falls inside the 48 hours
    far = c.fund_wallet(amount=20 * USDC, work_s=14 * DAY)        # its deadline does not
    from_balance = c.fund_balance(amount=30 * USDC)               # funded by comment from the owner's Balance, 14 days
    accounts = squads_world(c.now() - HOUR)                       # approved an hour ago: it can execute in 47 hours
    return c, ChainLedger(c), (lambda a: accounts.get(a)), near, far, from_balance


def test_the_deadline_is_the_pending_upgrades_approval_plus_its_time_lock(world):
    c, _ledger, account, *_ = world
    up = kexit.upgrade_deadline(account, IDS, c.now())
    assert up is not None and up.program == "knos_pay" and up.index == 1 and up.approved
    assert up.executes_at == c.now() - HOUR + 48 * HOUR
    drafted = squads_world(c.now(), "Active")                     # not approved yet: the earliest is now + 48 hours
    up2 = kexit.upgrade_deadline(lambda a: drafted.get(a), IDS, c.now())
    assert up2 is not None and not up2.approved and up2.executes_at == c.now() + 48 * HOUR


def test_a_funder_sees_which_orders_can_be_left_before_the_upgrade_and_the_program_agrees(world):
    c, ledger, account, near, far, _from_balance = world
    now = c.now()
    up = kexit.upgrade_deadline(account, IDS, now)
    ways = {w.address: w for w in kexit.plan(kexit.holdings(ledger, wallet=c.funder.pubkey()), now, up)}
    assert set(ways) == {str(near), str(far)}
    n, f = ways[str(near)], ways[str(far)]
    assert n.instruction == "RefundOrder" and n.before is True and n.held == 10 * USDC + pay.order_fee(10 * USDC)
    assert f.instruction == "Cancel, then RefundOrder" and f.before is False
    assert f.out_at == now + pay.NOTICE + 1 and f.short_s == f.out_at - up.executes_at + 1
    lines = kexit.words(list(ways.values()), now, up)
    assert lines[0].endswith("47 h 0 min to leave.") and "CANNOT be out before the upgrade" in "\n".join(lines)
    assert lines[-1] == "1 of 2 holdings can be out before the upgrade; 1 cannot."

    # the program agrees: the near order is refunded before the upgrade can execute
    c.warp(n.out_at - c.now())
    assert c.now() < up.executes_at and c.refund(near), c.err
    # the far one: the funding wallet gives notice now, and the refund is still refused when the upgrade can execute
    noticed = c.now()
    assert c.send([pay.cancel_ix(c.funder.pubkey(), far)], c.funder), c.err
    c.warp(up.executes_at - c.now())
    assert not c.refund(far)
    c.warp(noticed + pay.NOTICE + 1 - c.now())                     # the notice runs out: then, and only then, the refund
    assert c.refund(far), c.err


def test_a_balance_leaves_at_once_and_its_order_by_comment_cannot_leave_in_time(world):
    c, ledger, account, *_rest, from_balance = world
    now = c.now()
    up = kexit.upgrade_deadline(account, IDS, now)
    ways = kexit.plan(kexit.holdings(ledger, wallet=c.owner.pubkey()), now, up)
    by_kind = {w.kind: w for w in ways}
    assert by_kind["balance"].instruction == "Withdraw" and by_kind["balance"].before is True and by_kind["balance"].out_at == now
    o = by_kind["order"]
    assert o.address == str(from_balance) and o.before is False and "/knos cancel" in o.who and "needs GitHub" in o.who
    # the same holdings by the GitHub account that owns the Balance
    assert {w.address for w in kexit.plan(kexit.holdings(ledger, github_id=424242), now, up)} == {w.address for w in ways}
    data = kexit.as_json(ways, now, up)
    assert data["kind"] == kexit.SCHEMA and data["hours_to_leave"] == 47 and data["cannot_leave"] == 1
    json.dumps(data)


def test_held_and_warranty_money_cannot_leave_before_an_upgrade():
    o = pay.Order(state="held", mode=0, from_balance=False, flags=0, decimals=6, reserve_days=0, repo_id=1, issue=1, scope=bytes(32), seq=0,
                  holdback_bps=0, kill_bps=0, amount=5 * USDC, fee=50_000, rate=0, paid=0, deadline=1000, not_before=0, hold_until=1000 + 180 * DAY,
                  warranty_s=0, reserved_by=0, reserved_until=0, cancel_at=0, payee_id=7, funder_id=0, owner_id=0, arbiter_id=0, judge_repo_id=0,
                  source=Keypair().pubkey(), refund_to=Keypair().pubkey(), rent_to=Keypair().pubkey(), mint=Keypair().pubkey(), terms=bytes(32),
                  wf_repo_hash=bytes(32), wf_sha="c" * 40, fee_bps=30)
    upgrade_at = 2000 + 48 * HOUR
    for state, ix in (("held", "RefundOrder"), ("warranty", "Release")):
        o.state = state
        got, _mint, instruction, out_at, _who, _why = kexit.order_way(o, 1000 + 30 * DAY if state == "warranty" else 0, 2000)
        assert got == state and instruction == ix and out_at > upgrade_at


def test_with_no_pending_upgrade_nothing_is_judged_late(world):
    c, ledger, *_ = world
    ways = kexit.plan(kexit.holdings(ledger, wallet=c.funder.pubkey()), c.now(), None)
    assert all(w.before is None and w.short_s == 0 for w in ways)
    assert kexit.words(ways, c.now(), None)[0].startswith("No upgrade of a Knos program is pending")
    assert kexit.holdings(ledger, wallet=Keypair().pubkey()) == []
