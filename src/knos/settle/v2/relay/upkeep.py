"""What a worker does on every pass without a token: refunds due, held payments settled, releases, markers closed,
keys registered (`sweep`)."""
from __future__ import annotations

from typing import cast

from solders.instruction import Instruction
from solders.keypair import Keypair
from solders.pubkey import Pubkey

from .... import fees
from ... import oidc as first_oidc
from .. import meter, oidc, order_auto, pay

from .pins import GENESIS, _T_ID, _T_PAYER
from .build import version
from .tokens import _exp, _jwks
from .reads import _data, _read, keys, orders
from .jobs import _payout
from .workorders import _fee_account, _routed, _tip_accounts


# -- what needs no token: anyone's to send ------------------------------------------------------------------------------
def _each(ledger, payer: Keypair, txs: list[list[Instruction]]) -> list[str]:
    """Sends each transaction; one that fails (someone else was first, a destination that cannot be made) does not
    stop the others."""
    sigs = []
    for ixs in txs:
        try:
            sigs.append(ledger.send(ixs, payer))
        except Exception:  # noqa: BLE001, S112 - best effort: the next pass looks again
            continue
    return sigs


def refund_due(ledger, payer: Keypair, now: int) -> list[str]:
    """Sends back every job nobody can be paid from any more: open past its deadline, or held past its hold. To the
    Balance it came from, or to the funding wallet's token account (made if it is gone). Needs ledger.program_accounts."""
    me, txs = payer.pubkey(), []
    for state in (1, 3):
        for addr, data in ledger.program_accounts(pay.PAY_ID, pay.JOB_LEN, {0: bytes([state])}):
            j = pay.read_job(data)
            if j is not None and now > (j.deadline if j.state == "open" else j.hold_until):
                home = [] if j.from_balance else [pay.create_ata_ix(me, j.refund_to, j.mint, j.token_program)]
                txs.append([*home, pay.refund_ix(me, addr, j)])
    return _each(ledger, payer, txs)


def settle_held(ledger, payer: Keypair) -> list[str]:
    """Pays every held job whose payee has bound a wallet since it was held. Needs ledger.program_accounts."""
    me, now = payer.pubkey(), int(ledger.now())
    held = [(addr, j) for addr, j in ((a, pay.read_job(d)) for a, d in ledger.program_accounts(pay.PAY_ID, pay.JOB_LEN, {0: bytes([3])}))
            if j is not None and now <= j.hold_until]
    binds = _read(ledger, [pay.bind_pda(j.payee_id) for _a, j in held])
    txs = []
    for addr, j in held:
        bound = pay.read_bind(_data(binds, pay.bind_pda(j.payee_id)))
        if bound is not None:
            txs.append(_payout(me, j, bound.wallet, pay.settle_ix(me, addr, j, bound.wallet), 0)[0])
    return _each(ledger, payer, txs)


def refund_orders_due(ledger, payer: Keypair, now: int) -> list[str]:
    """Sends back every work order nobody can be paid from any more: open past its deadline (`pay_until`: with the
    presentation grace, two hours later), or held past its hold.
    To the Balance it came from, or to the funding wallet's token account (made if it is gone). Nothing on a 2.0 escrow."""
    if version(ledger, payer) < 1:
        return []
    me, txs = payer.pubkey(), []
    # (an open order funded with the presentation grace is due GRACE after its deadline: until then a token issued by the deadline still pays it)
    due = [(addr, o) for state in (1, 3) for addr, o in orders(ledger, state) if now > (o.pay_until if o.state == "open" else o.hold_until)]
    # an order cancelled while it was reserved owes its taker a kill fee first: to his bound wallet's token account,
    # made here if it is not there; with no wallet bound the fee stays held for him in the order and the rest goes back
    binds = _read(ledger, [pay.bind_pda(o.reserved_by) for _a, o in due if pay.kill_fee(o)])
    for addr, o in due:
        home = [] if o.from_balance else [pay.create_ata_ix(me, o.refund_to, o.mint, o.token_program)]
        taker = pay.read_bind(_data(binds, pay.bind_pda(o.reserved_by))) if pay.kill_fee(o) else None
        if taker is not None and taker.wallet != pay.auth_pda():
            home.append(pay.create_ata_ix(me, taker.wallet, o.mint, o.token_program))
        txs.append([*home, pay.refund_order_ix(me, addr, o, kill_token=pay.ata(taker.wallet, o.mint, o.token_program) if taker is not None else None)])
    return _each(ledger, payer, txs)


def settle_orders_held(ledger, payer: Keypair) -> list[str]:
    """Pays every held work order whose payee has bound a wallet since it was held; the tip comes to this relayer's
    own token account, made the first time. Nothing on a 2.0 escrow."""
    if version(ledger, payer) < 1:
        return []
    me, now = payer.pubkey(), int(ledger.now())
    held = [(addr, o) for addr, o in orders(ledger, 3) if now <= o.hold_until]
    got = _read(ledger, [k for a, o in held for k in (pay.bind_pda(o.payee_id), pay.assign_pda(a, o.payee_id), pay.ata(me, o.mint, o.token_program),
                                                      pay.ata(pay.FEE_OWNER, o.mint, o.token_program), pay.fee_account_for(a, o.mint, o.token_program))])
    txs = []
    for addr, o in held:
        wallet = _routed(got, addr, o, o.payee_id, None)        # the bound wallet, or the one the payee assigned this order's payment to
        if wallet is not None:
            fee = _fee_account(addr, o, got)
            txs.append([*_tip_accounts(me, o, got, fee)[0], pay.settle_order_ix(me, addr, o, wallet, fee_token=fee)])
    return _each(ledger, payer, txs)


def release_orders_due(ledger, payer: Keypair, now: int) -> list[str]:
    """Sends what every order held back to the wallets recorded when it was paid, once its warranty is over and nobody
    reverted (Release). Anyone may; the tip comes to this relayer's own token account. Nothing on a 2.0 escrow."""
    if version(ledger, payer) < 1:
        return []
    me = payer.pubkey()
    due = [(addr, o) for addr, o in orders(ledger, 4) if now > o.hold_until]
    got = _read(ledger, [k for a, o in due for k in (pay.hb_pda(a), pay.ata(me, o.mint, o.token_program), pay.ata(pay.FEE_OWNER, o.mint, o.token_program),
                                                     pay.fee_account_for(a, o.mint, o.token_program))])
    txs = []
    for addr, o in due:
        hb = pay.read_holdback(_data(got, pay.hb_pda(addr)))
        if hb is not None:
            fee = _fee_account(addr, o, got)
            txs.append([*_tip_accounts(me, o, got, fee)[0], pay.release_ix(me, addr, o, hb, fee_token=fee)])
    return _each(ledger, payer, txs)


def close_markers(ledger, payer: Keypair, now: int, per_tx: int = 8) -> list[str]:
    """Takes back the rent of the markers this relayer paid for, once they no longer matter (CloseMarker): the
    single-use marker of a token (`used`) after the time it stores, by which no instruction accepts that token any
    more; and a standing order's marker of a paid pull request (`done`) once its order is closed. Several to a
    transaction. Markers of both builds: 2.1 wrote a `done` of 65 bytes and a quorum marker of 106, 2.2 writes 73 and
    122, and either program closes what it can read by one rule. Nothing on a 2.0 escrow, which has neither."""
    if version(ledger, payer) < 1:
        return []
    me, ixs = payer.pubkey(), []
    for addr, data in ledger.program_accounts(pay.PAY_ID, pay.USED_LEN, {1: bytes(me)}):
        got = pay.read_marker(data)
        if got is not None and got[0] == me and now > got[1]:     # type: ignore[operator]  # a used marker's second part is its time
            ixs.append(pay.close_marker_ix(addr, me))
    new = version(ledger, payer) >= fees.NEW_VERSION        # 2.1 knows only its own two lengths, and writes no other
    sizes = (pay.DONE_LEN_21, pay.DONE_LEN) if new else (pay.DONE_LEN_21,)
    marks = [(addr, data) for size in sizes for addr, data in ledger.program_accounts(pay.PAY_ID, size, {1: bytes(me)})]
    done = [(addr, cast(Pubkey, got[1]), data) for addr, data, got in ((a, d, pay.read_marker(d)) for a, d in marks) if got is not None and got[0] == me]
    there = _read(ledger, [order for _a, order, _d in done])
    for addr, order, data in done:      # its order is gone, or (2.2) the order there now is another funding: order_terms.rs close_marker
        o = pay.read_order(_data(there, order))
        if there.get(order) is None or (new and o is not None and (o.inc != 0 if len(data) == pay.DONE_LEN_21 else
                                                                  o.stamp != int.from_bytes(data[65:73], "little", signed=True))):
            ixs.append(pay.close_marker_ix(addr, me, order))
    # a quorum marker, once its order is not the open order it was made for (paid, refunded, or funded again later)
    said = [(addr, order_auto.read_any(data)) for size in ((order_auto.Q_LEN_21, order_auto.Q_LEN) if new else (order_auto.Q_LEN_21,))
            for addr, data in ledger.program_accounts(pay.PAY_ID, size, {2: bytes(me)})]
    now_at = _read(ledger, [q[2] for _a, q in said if q is not None])
    for addr, q in said:
        o = pay.read_order(_data(now_at, q[2])) if q is not None else None
        if q is not None and q[1] == me and (o is None or o.state != "open" or o.stamp != q[3]):
            ixs.append(pay.close_marker_ix(addr, me, q[2]))
    return _each(ledger, payer, [ixs[k:k + per_tx] for k in range(0, len(ixs), per_tx)])


def close_marks(ledger, payer: Keypair, now: int, per_tx: int = 8) -> list[str]:
    """Takes back the rent of the meter's marks this relayer paid for (knos_meter CloseMark), once the month they
    were counted in is over and no token of it can come again. Several to a transaction. knos_meter's own instruction:
    whatever version the escrow is (a cluster without the meter has no marks)."""
    me = payer.pubkey()
    ixs = [meter.close_mark_ix(me, mark) for mark in meter.closable(meter.marks_of(ledger, me), now)]
    return _each(ledger, payer, [ixs[k:k + per_tx] for k in range(0, len(ixs), per_tx)])


def sweep(ledger, payer: Keypair, now: int) -> list[str]:
    """Takes back the rent of this relayer's token accounts that nothing can use any more, on both verifiers: each
    one whose token is an hour past its expiry (a verify-only account is left for its consumer until then), verified
    or cut short; and one that never got its whole token, an hour after its last transaction. Needs
    ledger.program_accounts."""
    me, txs, seen = payer.pubkey(), [], getattr(ledger, "touched", None)
    for program in (oidc.OIDC_ID, first_oidc.OIDC_ID):
        for addr, data in ledger.program_accounts(program, None, {_T_PAYER: bytes(me)}):
            tok = oidc.read_token(data)
            if tok is None or tok.payer != me:
                continue
            exp = tok.exp if tok.verified else _exp(bytes(data[oidc.T_JWT:]))
            if exp is None and seen is not None:
                exp = seen(addr)
            if exp is not None and exp + oidc.LATE <= now:
                txs.append([oidc.close_ix(me, bytes(data[_T_ID:_T_ID + 32]), program)])
    return _each(ledger, payer, txs)


def register_missing(ledger, payer: Keypair, jwks: dict | None = None) -> list[str]:
    """What anyone can do for the verifier's keys with no token: register each of GitHub's genesis keys the chain has
    not seen, and send the parameters of a key that was registered without them."""
    me, txs = payer.pubkey(), []
    for _kid, n in oidc.jwks_keys(_jwks(oidc.GITHUB, jwks)):
        if oidc.key_hash(n).hex() in GENESIS and ledger.account(oidc.key_pda(oidc.GITHUB, n)) is None:
            txs.append([oidc.register_key_ix(me, oidc.GITHUB, n), oidc.key_params_ix(me, oidc.GITHUB, n)])
    for _addr, k, n in keys(ledger):
        if k.state == 0 and not k.revoked:
            txs.append([oidc.key_params_ix(me, k.issuer, n)])
    return _each(ledger, payer, txs)
