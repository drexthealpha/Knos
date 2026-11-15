"""A buyer's reserve for one supplier in the simulator: a standing order of knos_pay funded from the buyer's Balance on
the terms knos.netting.reserve_fund states, and the draws a closed period makes on it. Shared by the netting and the
advance tests."""
from __future__ import annotations

from solders.pubkey import Pubkey

from _order import MAINT, OWNER, REPO, OrderChain, issue

from knos import netting
from knos.settle.v2 import pay


def locked(c: OrderChain, seller: int, funded: str, tranche: str, days: int = 14) -> tuple[Pubkey, dict]:
    """The buyer (the owner of the chain's Balance) locks `funded` for `seller`. Returns the order and what was signed."""
    k = issue()
    f = netting.reserve_fund(OWNER, seller, funded, tranche, c.bal, k, days * 86_400)
    c.warp(1)
    tok = c.gh(f["fund_audience"], file="fund.yml", event_name="issue_comment", actor_id=MAINT, repository_id=REPO, repository_owner_id=OWNER)
    assert c.send([c.fund_balance_ix(tok, k, c.bal, f["terms"].encode())], tag="reserve_fund"), c.err
    return pay.order_pda(pay.scope_of(REPO, k), c.bal), f


def draw(c: OrderChain, order: Pubkey, d: dict, seller: int, wallet: Pubkey | None = None) -> bool:
    """The reserve's judge signs one draw (netting.draws) and the relayer carries it: one tranche leaves the order, to
    the wallet the token names, or to the wallet the supplier assigned the order's payments to."""
    o = c.order(order)
    tok = c.gh(d["pay_audience"], repository_id=REPO)
    to = pay.payee_wallet(c.data(pay.assign_pda(order, seller)), o, pay.read_bind(c.data(pay.bind_pda(seller))), wallet)
    return c.send([pay.pay_order_ix(c.payer.pubkey(), tok, c.key, order, o, [(seller, to)], pr=d["pr"])], tag="reserve_draw")
