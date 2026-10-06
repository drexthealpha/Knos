#!/usr/bin/env python3
"""Writes programs-v2/testdata/adv_*.json: the scenarios programs-v2/handlers/tests/adversarial.rs replays.

The same recorder as scripts/rust_test_vectors.py (every call that reaches LiteSVM is written down, each transaction
as its signed bytes with what the program answered), over scenarios an opponent would try: accounts closed and made
again at the same address, the second before, at and after every time limit, a payment and a refund sent together,
one token sent twice, and one judge alone where an order asks for two or three.

    python scripts/adversarial_vectors.py            # write the files
    python scripts/adversarial_vectors.py --check    # fail if a committed file differs from what this would write

Two scenarios (`adv_quorum_same_account`, `adv_quorum_same_second`) record what the programs do today and the Rust
tests that replay them say what they should do instead; those tests are `#[ignore]`d until the program is judged.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "src"), str(ROOT / "tests")]

import rust_test_vectors as rv  # noqa: E402  (puts the recorder under the harnesses)

import _meter  # noqa: E402
import _order  # noqa: E402
import test_order_terms as terms  # noqa: E402
from _order import HEAD, OWNER, REPO, USDC  # noqa: E402

from knos.settle.v2 import meter, order_auto, pay  # noqa: E402

E_STATE, E_AUD, E_REPLAY, E_ORDER = 83, 87, 91, 101
HOUR = 3600
Q2 = pay.opts(pay.F_NEUTRAL | order_auto.quorum_flags(2))
JUDGE_REPO = 31_313_131


def _chain(r: rv.Recorder) -> "_order.OrderChain":
    c = _order.OrderChain()
    r.name_it(fee=c.fee, funder_tok=c.funder_tok, relayer_tok=c.tip)
    return c


def _payee(c, r: rv.Recorder):
    """A payee with a wallet and a token account that exists, so every tip is the smaller one."""
    wallet, dest = c.wallet(c.usdc)
    r.name_it(dest=dest)
    return [(_order.user(), 10_000, wallet.pubkey())]


def _fund(c, r: rv.Recorder, name: str, n: int | None = None, **kw):
    order = c.fund_wallet(n, **kw)
    r.name_it(**{name: order, f"{name}_tok": pay.ov_pda(order)})
    return order


def _send(c, r: rv.Recorder, label: str, ixs, want: int | None = None, **kw) -> None:
    """Sends one transaction under this label; `want`: the custom error it must be refused with, None: accepted."""
    r.label(label)
    ok = c.send(ixs, **kw)
    assert ok is (want is None) and (ok or _order.code(c) == want), f"{r.name} {label}: {c.err}"


def _money(c, r: rv.Recorder, label: str) -> None:
    r.check(c.svm, label, tokens=sorted(n for n in r.names if n.endswith("_tok") or n in ("fee", "dest")))


# == 1. accounts closed and made again at the same address ================================================================
def adv_reopen() -> rv.Recorder:
    """An order is paid and its address funded again: the token's marker cannot be closed early, the old token is
    refused while the marker stands and after it was closed. An order is refunded and its address funded again: a
    token signed for the first order and never used does not pay the second; a new one pays it once."""
    r = rv.scenario("adv_reopen")
    c = _chain(r)
    payees = _payee(c, r)
    n = _order.issue()
    order = _fund(c, r, "paid", n)
    c.warp(5)
    old = c.pay_token(order, payees)
    o1 = c.order(order)
    first = c.marked(c.pay_ix(order, old, payees))
    used = first.accounts[13].pubkey
    r.name_it(used=used)
    _send(c, r, "pay", [first])
    close = pay.close_marker_ix(used, c.payer.pubkey(), order)
    _send(c, r, "close_marker_early", [close], E_STATE)
    assert c.fund_wallet(n) == order
    _send(c, r, "old_token_while_its_marker_stands", [c.pay_ix(order, old, payees, o1)], E_REPLAY)
    after = int.from_bytes(c.data(used)[pay_U_AFTER():pay_U_AFTER() + 8], "little", signed=True)
    c.warp(after - c.now())
    _send(c, r, "close_marker_at_its_time", [close], E_STATE)
    c.warp(1)
    _send(c, r, "close_marker", [close])
    assert c.data(used) is None and c.order(order).paid == 0
    r.label("old_token_after_its_marker_closed")
    assert not c.send([c.pay_ix(order, old, payees, o1)]), "a token paid again once its marker was closed"
    _money(c, r, "reopened_after_pay")
    # refunded, then funded again
    n = _order.issue()
    order = _fund(c, r, "refunded", n, work_s=HOUR)
    c.warp(HOUR - 100)
    unused = c.pay_token(order, payees)
    o1 = c.order(order)
    c.warp(101)
    _send(c, r, "refund", [pay.refund_order_ix(c.payer.pubkey(), order, o1)])
    assert c.fund_wallet(n, work_s=HOUR) == order
    r.label("unused_token_of_the_refunded_order")
    assert not c.send([c.pay_ix(order, unused, payees, o1)]), "a token of the refunded order paid the next one"
    _money(c, r, "reopened_after_refund")
    c.warp(1)
    fresh = c.pay_token(order, payees)
    o2 = c.order(order)
    _send(c, r, "new_token_pays_the_new_order", [c.pay_ix(order, fresh, payees)])
    _send(c, r, "new_token_again", [c.pay_ix(order, fresh, payees, o2)], E_ORDER)
    _money(c, r, "end")
    return r


def pay_U_AFTER() -> int:
    """state.rs U_AFTER: where a used marker keeps the time after which it may be closed."""
    import re
    m = re.search(r"pub const U_AFTER: usize = (\d+);", (ROOT / "programs-v2/knos_pay/src/state.rs").read_text(encoding="utf-8"))
    return int(m.group(1))


# == 2. the second before, at, and after ================================================================================
def adv_deadline() -> rv.Recorder:
    """Three orders whose deadlines are one second apart, and two AUTO orders, all tried in one second: a second
    before the deadline and at it a proof pays and a refund is refused; a second after, the reverse."""
    r = rv.scenario("adv_deadline")
    c = _chain(r)
    payees = _payee(c, r)
    after = _fund(c, r, "after", work_s=HOUR)
    auto_after = c.fund_auto(work_s=HOUR)
    c.warp(1)
    at = _fund(c, r, "at", work_s=HOUR)
    auto_at = c.fund_auto(work_s=HOUR)
    c.warp(1)
    before = _fund(c, r, "before", work_s=HOUR)
    r.name_it(auto_at=auto_at, auto_at_tok=pay.ov_pda(auto_at), auto_after=auto_after, auto_after_tok=pay.ov_pda(auto_after))
    t = c.order(at).deadline
    assert (c.order(before).deadline, c.order(after).deadline, c.order(auto_at).deadline, c.order(auto_after).deadline) == (t + 1, t - 1, t, t - 1)
    c.warp(t - 100 - c.now())
    o = {k: c.order(k) for k in (before, at, after, auto_at, auto_after)}
    tok = {k: c.pay_token(k, payees) for k in (before, at, after)}
    auto = {k: c.auto_token(k, payees[0][0], payees[0][2]) for k in (auto_at, auto_after)}
    c.warp(t - c.now())
    assert c.now() == t
    _money(c, r, "start")

    def refund(k):
        return pay.refund_order_ix(c.payer.pubkey(), k, o[k])

    _send(c, r, "refund_one_second_before", [refund(before)], E_STATE)
    _send(c, r, "pay_one_second_before", [c.pay_ix(before, tok[before], payees)])
    _send(c, r, "refund_at_the_deadline", [refund(at)], E_STATE)
    _send(c, r, "pay_and_refund_at_the_deadline", [c.pay_ix(at, tok[at], payees), refund(at)], E_ORDER)
    _send(c, r, "refund_and_pay_at_the_deadline", [refund(at), c.pay_ix(at, tok[at], payees)], E_STATE)
    _send(c, r, "pay_at_the_deadline", [c.pay_ix(at, tok[at], payees)])
    _send(c, r, "refund_after_the_payment", [refund(at)], E_ORDER)
    _send(c, r, "pay_one_second_after", [c.pay_ix(after, tok[after], payees)], E_STATE)
    _send(c, r, "pay_and_refund_one_second_after", [c.pay_ix(after, tok[after], payees), refund(after)], E_STATE)
    _send(c, r, "refund_and_pay_one_second_after", [refund(after), c.pay_ix(after, tok[after], payees, o[after])], E_ORDER)
    _send(c, r, "refund_one_second_after", [refund(after)])
    _send(c, r, "pay_after_the_refund", [c.pay_ix(after, tok[after], payees, o[after])], E_ORDER)
    _send(c, r, "auto_at_the_deadline", [c.pay_ix(auto_at, auto[auto_at], payees)])
    _send(c, r, "auto_one_second_after", [c.pay_ix(auto_after, auto[auto_after], payees)], E_STATE)
    _send(c, r, "refund_auto_one_second_after", [refund(auto_after)])
    _money(c, r, "end")
    return r


def adv_hold() -> rv.Recorder:
    """Orders held for a payee without a wallet, whose holds end one second apart; the payee binds a wallet. A
    second before the hold ends and at it SettleOrder pays and a refund is refused; a second after, the reverse.
    Both in one transaction, in either order, on either side: refused whole."""
    r = rv.scenario("adv_hold")
    c = _chain(r)
    who = _order.user()
    payees = [(who, 10_000, None)]
    orders = {name: _fund(c, r, name) for name in ("after", "at", "before")}
    c.warp(5)
    for name in ("after", "at", "before"):
        r.label(f"hold_{name}")
        assert c.pay(orders[name], payees, tag=None), c.err
        assert c.order(orders[name]).state == "held"
        c.warp(1)
    wallet, dest = c.wallet(c.usdc)
    r.name_it(dest=dest)
    assert c.bind(who, wallet.pubkey()), c.err
    o = {k: c.order(v) for k, v in orders.items()}
    t = o["at"].hold_until
    assert (o["before"].hold_until, o["after"].hold_until) == (t + 1, t - 1)
    c.warp(t - c.now())
    _money(c, r, "start")

    def settle(k):
        return pay.settle_order_ix(c.payer.pubkey(), orders[k], o[k], wallet.pubkey())

    def refund(k):
        return pay.refund_order_ix(c.payer.pubkey(), orders[k], o[k])

    _send(c, r, "refund_one_second_before", [refund("before")], E_STATE)
    _send(c, r, "settle_one_second_before", [settle("before")])
    _send(c, r, "refund_at_the_end", [refund("at")], E_STATE)
    _send(c, r, "settle_and_refund_at_the_end", [settle("at"), refund("at")], E_ORDER)
    _send(c, r, "refund_and_settle_at_the_end", [refund("at"), settle("at")], E_STATE)
    _send(c, r, "settle_at_the_end", [settle("at")])
    _send(c, r, "refund_after_the_settlement", [refund("at")], E_ORDER)
    _send(c, r, "settle_one_second_after", [settle("after")], E_STATE)
    _send(c, r, "settle_and_refund_one_second_after", [settle("after"), refund("after")], E_STATE)
    _send(c, r, "refund_and_settle_one_second_after", [refund("after"), settle("after")], E_ORDER)
    _send(c, r, "refund_one_second_after", [refund("after")])
    _send(c, r, "settle_after_the_refund", [settle("after")], E_ORDER)
    _money(c, r, "end")
    return r


def adv_warranty() -> rv.Recorder:
    """Two orders with a tenth held back for a day, paid one second apart. In one second: the first is past its
    warranty (a challenge is refused, the holdback is released), the second is in its last second (a release is
    refused, the challenge returns the holdback)."""
    r = rv.scenario("adv_warranty")
    c = _chain(r)
    payees = _payee(c, r)
    options = pay.opts(holdback_bps=1000, warranty_days=1)
    over, last = _fund(c, r, "over", options=options), _fund(c, r, "last", options=options)
    c.warp(5)
    for k in (over, last):
        assert terms.pay_pr(c, k, payees), c.err
        c.warp(1)
    t = c.order(last).hold_until
    assert c.order(over).hold_until == t - 1 and c.order(last).state == "warranty"
    c.warp(t - 100 - c.now())
    challenge = {k: terms.revert_token(c, k) for k in (over, last)}
    c.warp(t - c.now())
    _money(c, r, "start")

    def release(k):
        return pay.release_ix(c.payer.pubkey(), k, c.order(k), terms.hb_of(c, k))

    def revert(k):
        return pay.revert_ix(c.payer.pubkey(), challenge[k], c.key, k, c.order(k), terms.hb_of(c, k))

    _send(c, r, "release_in_the_last_second", [release(last)], E_STATE)
    _send(c, r, "release_and_challenge_in_the_last_second", [release(last), revert(last)], E_STATE)
    _send(c, r, "challenge_one_second_after", [revert(over)], E_STATE)
    _send(c, r, "challenge_and_release_one_second_after", [revert(over), release(over)], E_STATE)
    late = release(over), revert(over)
    _send(c, r, "release_one_second_after", [late[0]])
    _send(c, r, "challenge_after_the_release", [late[1]], E_ORDER)
    early = revert(last), release(last)
    _send(c, r, "challenge_in_the_last_second", [early[0]])
    _send(c, r, "release_after_the_challenge", [early[1]], E_ORDER)
    _money(c, r, "end")
    return r


# == 4. one token, twice ================================================================================================
def adv_duplicates() -> rv.Recorder:
    """One pay token twice in one transaction and in two, on an order that closes with the payment and on a standing
    order that stays open; and a token signed for the meter shown to PayOrder."""
    r = rv.scenario("adv_duplicates")
    c = _chain(r)
    payees = _payee(c, r)
    once = _fund(c, r, "once")
    standing = _fund(c, r, "standing", options=pay.opts(pay.F_STANDING, rate=6 * USDC))
    c.warp(5)
    _money(c, r, "start")
    tok, o = c.pay_token(once, payees), c.order(once)
    ix = c.pay_ix(once, tok, payees)
    _send(c, r, "twice_in_one_transaction", [ix, ix], E_ORDER)
    _send(c, r, "once", [ix])
    _send(c, r, "again_in_a_second_transaction", [c.pay_ix(once, tok, payees, o)], E_ORDER)
    ix = terms.pay_ix(c, standing, payees, pr=1)
    _send(c, r, "standing_twice_in_one_transaction", [ix, ix], E_REPLAY)
    _send(c, r, "standing_once", [ix])
    _send(c, r, "standing_again_in_a_second_transaction", [ix], E_REPLAY)
    assert c.order(standing).state == "open"
    # an evaluation's token (the meter's audience), from the order's own repository's pinned run
    aud = meter.eval_audience(OWNER, _meter.SELLER, _meter.ORDER, HEAD, _meter.POLICY, 0, 1, 2 * USDC)
    evaluation = c.gh(aud, repository_id=REPO, repository_owner_id=OWNER)
    _send(c, r, "meter_token_to_pay_order", [_order.swap(terms.pay_ix(c, standing, payees, pr=2), 1, evaluation)], E_AUD)
    _money(c, r, "end")
    return r


def adv_meter_duplicates() -> rv.Recorder:
    """One evaluation's token twice in one transaction and again in a second: billed and counted once. A token signed
    for a payment (knos3:pay) shown to Record: refused, nothing billed."""
    r = rv.scenario("adv_meter_duplicates")
    c = _meter.Meter()
    mint = c.new_mint()
    wallet, credits = c.open(mint, _meter.BUYER, 0)
    wallet_tok = meter.ata(wallet.pubkey(), mint, c.token_program(mint))
    c.mint_to(mint, wallet_tok, 1000 * USDC)
    assert c.send([meter.deposit_ix(wallet_tok, wallet.pubkey(), credits, mint, 1000 * USDC, 6, c.token_program(mint))], wallet), c.err
    fee = c.token_account(meter.FEE_OWNER, mint)
    c.set_used(_meter.BUYER, meter.FREE_PER_MONTH)
    month = meter.yyyymm(c.now())
    r.name_it(credits=credits, credits_tok=meter.crtok_pda(credits), fee=fee, month=meter.month_pda(_meter.BUYER, _meter.SELLER, month))
    aud = c.aud("0" * 40, verdict=1, rate=2 * USDC)
    token = c.token(aud)
    ix = meter.record_ix(c.payer.pubkey(), token, c.key_of(token), credits, c.credits(credits), aud, c.now())
    r.label("twice_in_one_transaction")
    assert c.send([ix, ix]), c.err
    r.check(c.svm, "billed_once", tokens=["credits_tok", "fee"], data=["credits", "month"])
    r.label("again_in_a_second_transaction")
    assert c.send([ix]), c.err
    r.check(c.svm, "still_once", tokens=["credits_tok", "fee"], data=["credits", "month"])
    other = c.aud("1" * 40, verdict=1, rate=2 * USDC)
    payment = c.gh(f"knos3:pay:{credits}:{HEAD}:{'ab' * 32}:0:7:{_meter.SELLER}.10000.-", file="attest.yml", repository_owner_id=_meter.BUYER, run_attempt=1)
    r.label("pay_token_to_record")
    assert not c.send([meter.record_ix(c.payer.pubkey(), payment, c.key_of(payment), credits, c.credits(credits), other, c.now())])
    assert c.code == 116, c.err
    r.check(c.svm, "refused", tokens=["credits_tok", "fee"], data=["credits", "month"])
    return r


# == 5. one judge where two or three are asked ===========================================================================
def _present(c, r: rv.Recorder, label: str | None, order, payees, **over) -> bool:
    """One judge's token for the order's work, shown to PayOrder. The token is signed and its key put in place first,
    so the label is on the PayOrder transaction itself and a test stops right after it."""
    token = c.pay_token(order, payees, **over)
    if label:
        r.label(label)
    return c.send([c.pay_ix(order, token, payees)])


def adv_quorum() -> rv.Recorder:
    """A quorum of 2: one judge's token moves nothing, nor does a second token of the same judge; another judge's
    pays. A quorum of 3: two judges move nothing; the third pays."""
    r = rv.scenario("adv_quorum")
    c = _chain(r)
    payees = _payee(c, r)
    author = payees[0][0]
    two = _fund(c, r, "two", options=Q2)
    three = _fund(c, r, "three", options=pay.opts(pay.F_NEUTRAL | order_auto.quorum_flags(3), judge_repo_id=JUDGE_REPO))
    c.warp(5)
    _money(c, r, "start")
    for label, order, over in (("two_first_judge", two, {}), ("two_first_judge_again", two, {}), ("two_first_judge_a_third_time", two, {"actor_id": 77}),
                               ("two_second_judge", two, c.neutral(author)),
                               ("three_first_judge", three, {}), ("three_second_judge", three, c.neutral(author)),
                               ("three_second_judge_again", three, c.neutral(author)), ("three_first_judge_again", three, {}),
                               ("three_third_judge", three, dict(repository_id=JUDGE_REPO, file="attest.yml", event_name="push"))):
        assert _present(c, r, label, order, payees, **over), c.err
        _money(c, r, label)
    return r


def adv_quorum_same_account() -> rv.Recorder:
    """RECORDS A DEFECT (see the ignored test). A wallet's order with a quorum of 2: the run in the order's
    repository is started by one account, and the same account then starts the neutral run in a repository it owns.
    The program counts two judges and pays."""
    r = rv.scenario("adv_quorum_same_account")
    c = _chain(r)
    payees = _payee(c, r)
    order = _fund(c, r, "order", options=Q2)
    c.warp(5)
    _money(c, r, "start")
    assert _present(c, r, "own_run_started_by_the_account", order, payees, actor_id=OWNER), c.err
    _present(c, r, "neutral_run_started_by_the_same_account", order, payees, **c.neutral(OWNER))
    _money(c, r, "end")
    return r


def adv_quorum_same_second() -> rv.Recorder:
    """RECORDS A DEFECT (see the ignored test). An order with a quorum of 2 is paid by its two judges and its address
    funded again within the same second of the chain's clock: the first judge's marker of the first order still
    counts, and the second judge's new token alone pays the second order."""
    r = rv.scenario("adv_quorum_same_second")
    c = _chain(r)
    payees = _payee(c, r)
    author, n = payees[0][0], _order.issue()
    order = _fund(c, r, "order", n, options=Q2)
    assert _present(c, r, None, order, payees) and _present(c, r, None, order, payees, **c.neutral(author)), c.err
    assert c.order(order) is None
    r.label("fund_again_in_the_same_second")
    assert c.fund_wallet(n, options=Q2) == order
    _money(c, r, "funded_again")
    _present(c, r, "one_judge_alone", order, payees, **c.neutral(author))
    _money(c, r, "end")
    return r


SCENARIOS = (adv_reopen, adv_deadline, adv_hold, adv_warranty, adv_duplicates, adv_meter_duplicates, adv_quorum, adv_quorum_same_account,
             adv_quorum_same_second)


def main(argv: list[str]) -> int:
    check, stale = "--check" in argv, []
    only = [a for a in argv if not a.startswith("--")]
    for make in SCENARIOS:
        if only and make.__name__ not in only:
            continue
        r = make()
        path, doc = rv.OUT / f"{r.name}.json", r.doc()
        if check:
            if not path.is_file() or path.read_text(encoding="utf-8") != doc:
                stale.append(path.name)
        else:
            path.write_text(doc, encoding="utf-8")
        txs = [s for s in r.steps if s["op"] == "tx"]
        print(f"{path.relative_to(ROOT)}: {len(txs)} transactions, {sum(not s['ok'] for s in txs)} refused, {len(doc):,} bytes")
    if stale:
        print("stale (run scripts/adversarial_vectors.py and commit): " + " ".join(stale), file=sys.stderr)
    return 1 if stale else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
