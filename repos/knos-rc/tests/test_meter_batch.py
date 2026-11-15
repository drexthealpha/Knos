"""knos-meter's batch mode in the Solana runtime (LiteSVM): one token that GitHub signed carries the count of many
evaluations and the Merkle root of their keys; the Ledger of (buyer, seller, month) takes it once, by its seq, bills
only the part above the month's free allowance, refuses a batch the credits cannot pay for, and keeps a running hash
anyone recomputes; the seller's own count stands beside it, written only by the seller's repositories. Then what a
batch costs: compute units, and rent per evaluation beside the individual mode's mark."""
from __future__ import annotations

import hashlib

import pytest

pytest.importorskip("solders.litesvm")

from _meter import (BUYER, E_BATCH, E_SEQ, LEDGER_LEN, MAX_BATCH, PLAN_SETTER, SELLER, VERSION, BatchLedger, Meter, chain_hash, ledger_pda,  # noqa: E402
                    merkle_root, version_ix)

from knos.settle.v2 import meter  # noqa: E402

USDC, FREE, ZERO = 1_000_000, meter.FREE_PER_MONTH, bytes(32)
KEYS = sorted(meter.eval_key(bytes([i % 251]) * 32, f"{i:040x}", bytes(32), 0) for i in range(5000))     # 5,000 evaluations' keys


def paid(chain: Meter, amount: int = 1000 * USDC, used: int = FREE):
    """Credits holding `amount` for the buyer, who has already used `used` evaluations this month."""
    mint = chain.new_mint()
    wallet, credits = chain.open(mint, BUYER, amount)
    chain.fees(mint)
    chain.set_used(BUYER, used)
    return mint, wallet, credits


def test_a_batch_of_five_thousand_is_counted_and_billed_once_and_its_token_is_taken_once():
    chain = Meter()
    mint, _, credits = paid(chain)
    month, root = meter.yyyymm(chain.now()), merkle_root(KEYS)
    aud = chain.batch_aud(seq=0, count=5000, accepted=4321, value=8_642 * USDC, root=root)
    assert aud == f"knosm:batch:{BUYER}:{SELLER}:{month}:0:5000:4321:8642000000:{root.hex()}"
    token = chain.token(aud)
    assert chain.batch(credits, aud, token), chain.err
    fee, first = 5000 * 50_000, chain_hash(ZERO, root, 0, 5000, 4321, 8_642 * USDC)
    assert chain.said("knosm:batch") == [f"knosm:batch buyer={BUYER} seller={SELLER} month={month} seq=0 count=5000 accepted=4321 value={8_642 * USDC} "
                                         f"root={root.hex()} billable=5000 fee={fee} n={FREE + 5000} chain={first.hex()} mint={mint}"]
    assert (chain.held(credits), chain.fees(mint)) == (1000 * USDC - fee, fee) == (750 * USDC, 250 * USDC)
    want = BatchLedger(claim=False, month=month, buyer_id=BUYER, seller_id=SELLER, next_seq=1, evaluations=5000, accepted=4321, value=8_642 * USDC, fees=fee,
                       chain=first)
    assert chain.book() == want
    c = chain.credits(credits)
    assert (c.spent, c.evaluations, meter.read_plan(chain.data(meter.plan_pda(BUYER))).used) == (fee, 5000, FREE + 5000)
    # no account per evaluation: no mark, and the individual mode's Month is untouched
    assert chain.data(meter.mark_pda(BUYER, KEYS[0])) is None and chain.month().evaluations == 0
    # the same token again, and a new token for the same batch: refused by the seq, nothing moves
    for again in (dict(token=token), {}):
        assert not chain.batch(credits, aud, **again) and chain.code == E_SEQ
        assert (chain.held(credits), chain.fees(mint), chain.book()) == (750 * USDC, 250 * USDC, want)
    # a batch that skips ahead or goes back is refused; the next one in order is taken
    for seq in (2, 0, 7):
        assert not chain.batch(credits, chain.batch_aud(seq=seq, count=10, accepted=1, value=5)) and chain.code == E_SEQ
    assert chain.batch(credits, chain.batch_aud(seq=1, count=10, accepted=1, value=5, root=KEYS[1])), chain.err
    assert chain.book() == BatchLedger(False, month, BUYER, SELLER, 2, 5010, 4322, 8_642 * USDC + 5, fee + 10 * 50_000, chain_hash(first, KEYS[1], 1, 10, 1, 5))


def test_only_the_part_of_a_batch_above_the_free_allowance_is_billed():
    chain = Meter()
    mint, _, credits = paid(chain, used=FREE - 2000)
    assert chain.batch(credits, chain.batch_aud(seq=0, count=5000)), chain.err             # 2,000 free, 3,000 at 0.05
    assert chain.said("knosm:batch")[0].split(" billable=")[1].startswith(f"3000 fee={150 * USDC} n={FREE + 3000} ")
    assert (chain.fees(mint), chain.book().fees, chain.credits(credits).evaluations) == (150 * USDC, 150 * USDC, 5000)
    # wholly free, exactly up to the allowance, and one past it; under a Plan the part above costs the Plan's rate
    for used, count, billable in ((0, 5000, 0), (FREE - 5000, 5000, 0), (FREE - 4999, 5000, 1), (FREE + 7, 3, 3)):
        other = Meter()
        m, _, cr = paid(other, used=used)
        assert other.batch(cr, other.batch_aud(count=count, accepted=count)), other.err
        assert (other.fees(m), other.book().fees) == (billable * 50_000, billable * 50_000), (used, count)
    assert chain.send([meter.set_plan_ix(PLAN_SETTER.pubkey(), chain.payer.pubkey(), BUYER, 1, 20_000, chain.now() + 99)], signers=[PLAN_SETTER]), chain.err
    assert chain.batch(credits, chain.batch_aud(seq=1, count=100, accepted=100)), chain.err
    assert chain.fees(mint) == 150 * USDC + 100 * 20_000


def test_credits_that_cannot_pay_refuse_the_whole_batch():
    chain = Meter()
    mint, wallet, credits = paid(chain, amount=250 * USDC - 1)
    aud = chain.batch_aud(seq=0, count=5000)
    token = chain.token(aud)
    assert not chain.batch(credits, aud, token) and chain.code == 118
    assert chain.book() is None and (chain.held(credits), chain.fees(mint)) == (250 * USDC - 1, 0)
    assert (chain.credits(credits).evaluations, meter.read_plan(chain.data(meter.plan_pda(BUYER))).used) == (0, FREE)
    # one unit more and the same token is taken
    chain.mint_to(mint, meter.crtok_pda(credits), 1)
    assert chain.batch(credits, aud, token), chain.err
    assert (chain.held(credits), chain.fees(mint), chain.book().evaluations) == (0, 250 * USDC, 5000)


def test_a_batch_is_held_to_its_bounds_its_month_and_the_rules_of_a_single_evaluation():
    chain = Meter()
    _, _, credits = paid(chain, amount=5000 * USDC, used=0)
    month = meter.yyyymm(chain.now())
    last, nxt, older = (month - 89 if month % 100 == 1 else month - 1), (month + 89 if month % 100 == 12 else month + 1), month - 100
    for bad in (dict(count=0, accepted=0), dict(count=MAX_BATCH + 1), dict(count=5, accepted=6), dict(month=nxt), dict(month=older)):
        assert not chain.batch(credits, chain.batch_aud(**bad)) and chain.code == E_BATCH, bad
    assert chain.batch(credits, chain.batch_aud(count=MAX_BATCH, accepted=MAX_BATCH)), chain.err         # the most; it is this owner's month: 90,000 billed
    assert chain.book().fees == (MAX_BATCH - FREE) * 50_000
    # a batch for last month arrives this month: a ledger of its own, counted against this month's allowance
    assert chain.batch(credits, chain.batch_aud(month=last, count=7, accepted=7)), chain.err
    assert (chain.book(month=last).evaluations, chain.book(month=last).month, chain.book().next_seq) == (7, last, 1)
    # the rules of Record: the pinned workflow, a first attempt, a repository of the buyer, a batch audience
    for over, code in ((dict(file="other.yml"), 115), (dict(wf_sha="d" * 40), 115), (dict(run_attempt=2), 114), (dict(repository_owner_id=SELLER), 117)):
        assert not chain.batch(credits, chain.batch_aud(seq=1), **over) and chain.code == code, over
    assert not chain.batch(credits, chain.batch_aud(seq=1, kind="claim")) and chain.code == 116
    assert not chain.batch(credits, chain.batch_aud(seq=1), token=chain.token(chain.aud())) and chain.code == 116   # an evaluation's token is no batch
    assert not chain.record(credits, chain.aud(), token=chain.token(chain.batch_aud(seq=1))) and chain.code == 116                    # and Record takes no batch token


def test_the_sellers_claim_is_written_only_from_the_sellers_repositories():
    chain = Meter()
    mint, _, credits = paid(chain)
    month, root = meter.yyyymm(chain.now()), merkle_root(KEYS)
    assert chain.batch(credits, chain.batch_aud(count=4990, accepted=4000, value=8000 * USDC, root=merkle_root(KEYS[:4990]))), chain.err   # the buyer left ten out
    before = (chain.held(credits), chain.fees(mint), chain.book())
    aud = chain.batch_aud(count=5000, accepted=4010, value=8020 * USDC, root=root, kind="claim")
    assert aud == f"knosm:claim:{BUYER}:{SELLER}:{month}:0:5000:4010:8020000000:{root.hex()}"
    # the buyer's repository, a third party's: refused; nothing is written
    for owner in (BUYER, 999):
        assert not chain.claim(aud, repository_owner_id=owner) and chain.code == 117
    assert chain.book(claim=True) is None
    token = chain.gh(aud, file="anything.yml", repository_owner_id=SELLER, run_attempt=3)      # the seller's own statement: no pin
    assert chain.claim(aud, token), chain.err
    first = chain_hash(ZERO, root, 0, 5000, 4010, 8020 * USDC)
    assert chain.said("knosm:claim") == [f"knosm:claim buyer={BUYER} seller={SELLER} month={month} seq=0 count=5000 accepted=4010 value={8020 * USDC} "
                                         f"root={root.hex()} chain={first.hex()}"]
    assert chain.book(claim=True) == BatchLedger(True, month, BUYER, SELLER, 1, 5000, 4010, 8020 * USDC, 0, first)
    # no fee, and the buyer's ledger is another account: the two counts differ on chain
    assert (chain.held(credits), chain.fees(mint), chain.book()) == before and chain.book().evaluations == 4990
    assert ledger_pda(BUYER, SELLER, month, True) != ledger_pda(BUYER, SELLER, month)
    assert not chain.claim(aud, token) and chain.code == E_SEQ                              # taken once
    assert not chain.claim(chain.batch_aud(seq=1, count=0, accepted=0, kind="claim")) and chain.code == E_BATCH
    assert not chain.claim(chain.batch_aud(seq=1)) and chain.code == 116                    # a batch token is no claim
    assert not chain.batch(credits, aud, token) and chain.code == 115                # and the seller's token records nothing for the buyer


def test_the_running_hash_is_the_one_python_computes():
    chain = Meter()
    _, _, credits = paid(chain, used=0)
    h, total = ZERO, 0
    for seq, (lo, hi, accepted, value) in enumerate(((0, 1, 1, 7), (1, 4, 0, 0), (4, 1004, 999, 2 ** 40), (1004, 5000, 3996, 12345))):
        root = merkle_root(KEYS[lo:hi])
        assert chain.batch(credits, chain.batch_aud(seq=seq, count=hi - lo, accepted=accepted, value=value, root=root)), chain.err
        # spelled out, byte for byte: sha256(chain || root || seq || count || accepted || value), u64 little-endian
        h = hashlib.sha256(h + root + seq.to_bytes(8, "little") + (hi - lo).to_bytes(8, "little") + accepted.to_bytes(8, "little") + value.to_bytes(8, "little")).digest()
        total += hi - lo
        assert (chain.book().chain, chain.book().next_seq, chain.book().evaluations) == (h, seq + 1, total)
        assert chain.said("knosm:batch")[0].split(" chain=")[1].split(" ")[0] == h.hex()
    # the tree is RFC 6962's: one leaf, two leaves, three (split 2 + 1)
    leaf = lambda k: hashlib.sha256(b"\x00" + k).digest()  # noqa: E731
    node = lambda a, b: hashlib.sha256(b"\x01" + a + b).digest()  # noqa: E731
    a, b, c = KEYS[:3]
    assert merkle_root([a]) == leaf(a) and merkle_root([a, b]) == node(leaf(a), leaf(b)) and merkle_root([a, b, c]) == node(node(leaf(a), leaf(b)), leaf(c))


def test_what_a_batch_costs_and_the_version():
    chain = Meter()
    _, _, credits = paid(chain)
    relayer = chain.fund()
    aud = chain.batch_aud(seq=0, count=5000, root=merkle_root(KEYS))
    token, start = chain.token(aud), chain.lamports(relayer.pubkey())
    assert chain.batch(credits, aud, token, relayer=relayer), chain.err
    first_cu, locked = chain.meter_cu, chain.lamports(ledger_pda(BUYER, SELLER, meter.yyyymm(chain.now())))
    assert locked == chain.svm.minimum_balance_for_rent_exemption(LEDGER_LEN) == 1_559_040
    assert start - chain.lamports(relayer.pubkey()) - locked <= 10_000                       # the relayer paid the ledger's rent and a signature
    token = chain.token(chain.batch_aud(seq=1, count=5000))
    start = chain.lamports(relayer.pubkey())
    assert chain.batch(credits, chain.batch_aud(seq=1, count=5000), token, relayer=relayer), chain.err
    assert start - chain.lamports(relayer.pubkey()) <= 10_000                                # a later batch of the month locks nothing
    mark = chain.svm.minimum_balance_for_rent_exemption(meter.MARK_LEN)
    print(f"\nRecordBatch compute units: first batch of a month {first_cu}, later batch {chain.meter_cu}")
    print(f"rent locked: ledger {locked} lamports once a month = {locked / 5000:.1f} per evaluation in a 5,000 batch; a mark {mark} per evaluation")
    assert first_cu < 200_000 and chain.meter_cu < first_cu and mark == 1_503_360 and locked / 5000 < mark / 4000
    assert chain.send([version_ix()]) and chain.said("knosm:version") == [f"knosm:version {VERSION}"] == ["knosm:version 1.1"]
