"""knos-meter in the Solana runtime (LiteSVM) with the second deployment's verifier beside it: an evaluation that
GitHub signed is counted and billed once, whatever its verdict; a retry is free; the relayer gets the rent of a mark
back once its month has closed; an owner's first ten thousand of a month cost nothing; a Plan sets the rate; credits never go below zero and only the wallet that opened them takes them
back; only the pinned workflows' first runs in the buyer's repositories count; a revoked, expired or private key
counts nothing; and the counters equal what the logs say. Then idl/knos_meter.json against the source and the client."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

pytest.importorskip("solders.litesvm")

from solders.account import Account  # noqa: E402
from solders.keypair import Keypair  # noqa: E402
from solders.pubkey import Pubkey  # noqa: E402

import _meter  # noqa: E402
from _meter import BUYER, ORDER, PLAN_SETTER, POLICY, SELLER, Meter  # noqa: E402
from _pay2 import WF_REPO, WF_SHA  # noqa: E402

from knos.settle.v2 import meter, oidc  # noqa: E402
from knos.settle.v2 import pay as pay2  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
USDC, DAY, FREE = 1_000_000, 86_400, meter.FREE_PER_MONTH
SHA = [c * 40 for c in "0123456789abcdef"]      # sixteen artifacts


def paid(chain: Meter, amount: int = 5 * USDC, owner_id: int = BUYER):
    """Credits holding `amount` for an owner who is already past this month's free evaluations. Returns (mint, wallet, credits)."""
    mint = chain.new_mint()
    wallet, credits = chain.open(mint, owner_id, amount)
    chain.fees(mint)                             # FEE_OWNER's token account exists
    chain.set_used(owner_id, FREE)
    return mint, wallet, credits


def test_an_evaluation_is_billed_and_counted_once_and_a_retry_is_free():
    chain = Meter()
    mint, _, credits = paid(chain)
    month = meter.yyyymm(chain.now())
    aud = chain.aud(SHA[0], verdict=1, rate=2 * USDC)
    token = chain.token(aud)
    assert chain.record(credits, aud, token), chain.err
    assert chain.said("knosm:eval") == [f"knosm:eval buyer={BUYER} seller={SELLER} order={ORDER.hex()} artifact={SHA[0]} policy={POLICY.hex()} milestone=0 "
                                        f"verdict=1 rate={2 * USDC} fee=50000 month={month} n={FREE + 1} mint={mint}"]
    assert (chain.held(credits), chain.fees(mint)) == (5 * USDC - 50_000, 50_000)
    want = meter.Statement(BUYER, SELLER, month, evaluations=1, accepted=1, rejected=0, value=2 * USDC, fees=50_000)
    assert chain.month() == want
    e = meter.parse_audience(aud)
    mark = meter.read_mark(chain.data(meter.mark_pda(BUYER, e.key)))
    assert mark == meter.Mark(accepted=True, month=month, buyer_id=BUYER, seller_id=SELLER, time=chain.now(), rate=2 * USDC, fee=50_000,
                              payer=chain.payer.pubkey(), close_after=meter.next_month(chain.now()) + meter.MARK_GRACE)
    c = chain.credits(credits)
    assert (c.spent, c.evaluations, meter.read_plan(chain.data(meter.plan_pda(BUYER))).used) == (50_000, 1, FREE + 1)
    # the same token again, a new run for the same evaluation, and one that now says the opposite: all free, nothing moves
    for again in (dict(token=token), {}, dict(aud=chain.aud(SHA[0], verdict=0, rate=9 * USDC))):
        assert chain.record(credits, again.pop("aud", aud), **again), chain.err
        assert chain.said("knosm:") == [f"knosm:retry buyer={BUYER} key={e.key.hex()}"]
        assert (chain.held(credits), chain.fees(mint), chain.month()) == (5 * USDC - 50_000, 50_000, want)
    assert meter.read_plan(chain.data(meter.plan_pda(BUYER))).used == FREE + 1 and chain.credits(credits).evaluations == 1
    # what makes it another evaluation: the artifact, the milestone, the policy, the work order
    for n, other in enumerate((dict(artifact=SHA[1]), dict(artifact=SHA[0], milestone=1), dict(artifact=SHA[0], policy=bytes(32)),
                               dict(artifact=SHA[0], order=bytes(32))), 2):
        assert chain.record(credits, chain.aud(**other)), chain.err
        assert chain.month().evaluations == n and chain.fees(mint) == n * 50_000


def test_the_relayer_gets_a_marks_rent_back_once_no_token_of_its_month_can_be_recorded():
    chain = Meter()
    mint, _, credits = paid(chain)
    assert chain.record(credits, chain.aud(SHA[1])), chain.err             # the month's count exists: the relayer below pays for a mark and nothing else
    relayer, stranger = chain.fund(), chain.fund()
    aud = chain.aud(SHA[0], verdict=1, rate=2 * USDC)
    e, first = meter.parse_audience(aud), meter.yyyymm(chain.now())
    addr = meter.mark_pda(BUYER, e.key)
    rent, start = chain.svm.minimum_balance_for_rent_exemption(meter.MARK_LEN), chain.lamports(relayer.pubkey())
    assert chain.record(credits, aud, chain.token(aud), relayer=relayer), chain.err
    assert chain.lamports(addr) == rent and chain.lamports(relayer.pubkey()) == start - rent - 5000      # the rent and one signature
    closes = meter.next_month(chain.now())                                 # the first second of the next month
    mark = meter.read_mark(chain.data(addr))
    assert (mark.payer, mark.close_after) == (relayer.pubkey(), closes + 7200) and meter.close_after(chain.now()) == closes + 7200
    assert meter.yyyymm(closes - 1) == first and meter.yyyymm(closes) == first + 1
    assert meter.marks_of(chain.ledger, relayer.pubkey()) == [(addr, mark)] and meter.closable([(addr, mark)], closes + 7199) == []
    # before that time nobody closes it, and nobody but the relayer that paid ever does
    assert not chain.close([addr], relayer, chain.payer) and chain.code == 124
    assert not chain.close([addr], stranger) and chain.code == 123
    ix = meter.close_mark_ix(relayer.pubkey(), addr)                         # the relayer's address without its signature
    assert not chain.send([type(ix)(ix.program_id, ix.data, [type(ix.accounts[0])(relayer.pubkey(), False, True), ix.accounts[1]])]) and chain.code == 110
    assert not chain.send([type(ix)(ix.program_id, b"\x04\x00", ix.accounts)], signers=[relayer]) and chain.code is None
    # the last second of the month: a new run for the same evaluation is free, and so is the longest-lived token
    # GitHub could have issued in that second, for as long as the meter takes it
    chain.warp(closes - 1 - chain.now())
    assert chain.record(credits, aud), chain.err
    assert chain.said("knosm:") == [f"knosm:retry buyer={BUYER} key={e.key.hex()}"]
    last = chain.token(aud, exp=chain.now() + meter.TOKEN_LIFE)
    chain.warp(7199)                                                         # one second before that token stops working
    assert chain.now() == mark.close_after - 2
    assert chain.record(credits, aud, last), chain.err
    assert chain.said("knosm:") == [f"knosm:retry buyer={BUYER} key={e.key.hex()}"]
    assert not chain.close([addr], relayer, chain.payer) and chain.code == 124
    chain.warp(1)
    assert not chain.record(credits, aud, last) and chain.code == 113          # no token of that month is taken any more
    assert not chain.close([addr], relayer, chain.payer) and chain.code == 124
    chain.warp(1)
    assert meter.closable(meter.marks_of(chain.ledger, relayer.pubkey()), chain.now()) == [addr]
    assert not chain.close([addr], stranger) and chain.code == 123
    before = chain.month(month=first)
    assert chain.close([addr], relayer), chain.err
    assert chain.said("knosm:") == [f"knosm:closed buyer={BUYER} month={first} lamports={rent}"]
    assert chain.data(addr) is None and chain.lamports(addr) == 0
    assert chain.lamports(relayer.pubkey()) == start - 2 * 5000              # all of the rent is back: two signatures were the cost
    assert not chain.close([addr], relayer, chain.payer) and chain.code == 123    # it is gone
    assert chain.month(month=first) == before and meter.marks_of(chain.ledger, relayer.pubkey()) == []
    # what closing gives up: a token GitHub issues in a later month for the same evaluation is billed and counted in that month
    assert chain.record(credits, aud, relayer=relayer), chain.err
    assert chain.said("knosm:eval")[0].endswith(f"verdict=1 rate={2 * USDC} fee=0 month={first + 1} n=1 mint={mint}")
    assert chain.month().evaluations == 1 and chain.month(month=first) == before
    assert meter.read_mark(chain.data(addr)).close_after == meter.next_month(chain.now()) + 7200
    # a relayer that leaves its mark open keeps the evaluation billed once: the other mark of the first month still stands
    assert chain.record(credits, chain.aud(SHA[1])), chain.err
    assert chain.said("knosm:") == [f"knosm:retry buyer={BUYER} key={meter.eval_key(ORDER, SHA[1], POLICY, 0).hex()}"]


def test_a_mark_from_before_close_mark_stands_and_nobody_closes_it():
    chain = Meter()
    mint, _, credits = paid(chain)
    aud = chain.aud(SHA[0])
    addr = meter.mark_pda(BUYER, meter.parse_audience(aud).key)
    old = bytes([1, 1, 0, 0]) + meter.yyyymm(chain.now()).to_bytes(4, "little") + BUYER.to_bytes(8, "little") + SELLER.to_bytes(8, "little") + bytes(24)
    chain.svm.set_account(addr, Account(chain.svm.minimum_balance_for_rent_exemption(meter.MARK_LEN_1), old, meter.METER_ID))
    assert meter.read_mark(chain.data(addr)) == meter.Mark(True, meter.yyyymm(chain.now()), BUYER, SELLER, 0, 0, 0, payer=None, close_after=None)
    assert chain.record(credits, aud), chain.err
    assert chain.said("knosm:") == [f"knosm:retry buyer={BUYER} key={meter.parse_audience(aud).key.hex()}"] and chain.fees(mint) == 0
    chain.warp(40 * DAY)
    assert not chain.close([addr], chain.payer) and chain.code == 123
    assert meter.closable([(addr, meter.read_mark(chain.data(addr)))], chain.now()) == []
    # and no other account of the meter is taken for a mark: the month's count, the plan, the credits
    for other in (meter.month_pda(BUYER, SELLER, meter.yyyymm(chain.now())), meter.plan_pda(BUYER), credits):
        assert not chain.close([other], chain.payer) and chain.code == 123, other


def test_what_a_relayer_pays_for_evaluations_and_gets_back():
    """The numbers of the cost line (docs/reference/MARKET.md, Meter): printed with `pytest -s`."""
    chain = Meter()
    mint, _, credits = paid(chain, 5 * USDC)
    relayer, n = chain.fund(), 30
    assert chain.record(credits, chain.aud(SHA[0], milestone=99)), chain.err      # the buyer's plan and this month's count exist already
    start, txs = chain.lamports(relayer.pubkey()), len(chain.tx_logs)
    token = chain.gh(chain.aud(SHA[0]), file="attest.yml", payer=relayer, repository_owner_id=BUYER, run_attempt=1)
    verify_txs = len(chain.tx_logs) - txs
    token_rent = chain.lamports(token)
    assert chain.record(credits, chain.aud(SHA[0]), token, relayer=relayer), chain.err
    record_size, record_cu = chain.size, chain.meter_cu
    for i in range(1, n):
        assert chain.record(credits, chain.aud(SHA[i % 16], milestone=i // 16), relayer=relayer), chain.err      # tokens verified by the chain's payer
    rent = chain.svm.minimum_balance_for_rent_exemption(meter.MARK_LEN)
    locked = n * rent
    assert chain.lamports(relayer.pubkey()) == start - locked - (n + verify_txs) * 5000 - token_rent
    chain.warp(meter.close_after(chain.now()) - chain.now())
    due = meter.closable(meter.marks_of(chain.ledger, relayer.pubkey()), chain.now())
    assert len(due) == n
    # as many CloseMark instructions as one transaction of 1232 bytes holds
    per_tx = max(k for k in range(1, n + 1) if chain.close_size(due[:k], relayer) <= 1232)
    assert per_tx >= 20 and chain.close_size(due[:per_tx + 1], relayer) > 1232
    assert chain.close(due[:per_tx], relayer), chain.err
    assert chain.size == chain.close_size(due[:per_tx], relayer) and chain.meter_cu < 1_400_000 // 4      # far inside one transaction's compute limit
    close_size, close_cu, closes = chain.size, chain.meter_cu // per_tx, 1
    for i in range(per_tx, n, per_tx):
        assert chain.close(due[i:i + per_tx], relayer), chain.err
        closes += 1
    assert meter.marks_of(chain.ledger, relayer.pubkey()) == []
    assert chain.lamports(relayer.pubkey()) == start - (n + verify_txs + closes) * 5000 - token_rent      # every lamport of the marks' rent is back
    cluster = (128 + meter.MARK_LEN) * 5080      # the rent rule docs/reference/MARKET.md cites (SIMD-0437); LiteSVM still holds 6960 a byte
    print(f"\nmeter: one billable evaluation = {verify_txs} transactions to verify the token + 1 Record ({record_size} bytes, {record_cu} compute units) "
          f"= {(verify_txs + 1) * 5000} lamports of signatures. Its mark is {meter.MARK_LEN} bytes: {cluster} lamports of the relayer's rent "
          f"({rent} in LiteSVM), {1000 * cluster / 1e9:.5f} SOL per 1,000 evaluations, locked until two hours into the next month and then returned "
          f"in full by CloseMark: {close_cu} compute units each, {per_tx} to a transaction ({close_size} bytes), so {5000 / per_tx:.0f} lamports each. "
          f"Before: {(128 + meter.MARK_LEN_1) * 5080} lamports of rent per evaluation, never returned.")


def test_a_rejection_is_billed():
    chain = Meter()
    mint, _, credits = paid(chain)
    assert chain.record(credits, chain.aud(SHA[0], verdict=0, rate=2 * USDC)), chain.err
    assert "verdict=0" in chain.said("knosm:eval")[0] and "fee=50000" in chain.said("knosm:eval")[0]
    assert chain.fees(mint) == 50_000
    m = chain.month()
    assert (m.evaluations, m.accepted, m.rejected, m.value, m.fees) == (1, 0, 1, 0, 50_000)       # no value is declared for a rejection
    assert chain.record(credits, chain.aud(SHA[1], verdict=1, rate=3 * USDC)), chain.err
    m = chain.month()
    assert (m.evaluations, m.accepted, m.rejected, m.value, m.fees) == (2, 1, 1, 3 * USDC, 100_000)


def test_the_first_ten_thousand_evaluations_of_a_month_are_free_and_credits_never_go_below_zero():
    chain = Meter()
    mint = chain.new_mint()
    wallet, credits = chain.open(mint)                      # no money at all: the free evaluations need none, and no fee account either
    assert chain.record(credits, chain.aud(SHA[0]), fee_token=Keypair().pubkey()), chain.err
    assert "fee=0 " in chain.said("knosm:eval")[0] and " n=1 " in chain.said("knosm:eval")[0] and chain.month().fees == 0
    chain.set_used(BUYER, FREE - 1)
    assert chain.record(credits, chain.aud(SHA[1])), chain.err
    assert f"fee=0 month={meter.yyyymm(chain.now())} n={FREE} " in chain.said("knosm:eval")[0]
    # the next one costs 0.05, the credits hold nothing: refused whole. No mark, no count, no debt.
    aud = chain.aud(SHA[2], verdict=0)
    token = chain.token(aud)
    chain.fees(mint)
    before = chain.month()
    assert not chain.record(credits, aud, token) and chain.code == 118
    assert chain.data(meter.mark_pda(BUYER, meter.parse_audience(aud).key)) is None
    assert chain.month() == before and meter.read_plan(chain.data(meter.plan_pda(BUYER))).used == FREE and chain.held(credits) == 0
    # one unit short is still short
    assert chain.send([meter.deposit_ix(chain.token_account(wallet.pubkey(), mint), wallet.pubkey(), credits, mint, 0, 6)], wallet), chain.err
    chain.mint_to(mint, meter.crtok_pda(credits), 49_999)   # anyone adds money with a plain transfer
    assert not chain.record(credits, aud, token) and chain.code == 118 and chain.held(credits) == 49_999
    chain.mint_to(mint, meter.crtok_pda(credits), 1)
    assert chain.record(credits, aud, token), chain.err    # the same token, once the money is there
    assert (chain.held(credits), chain.fees(mint), chain.month().fees) == (0, 50_000, 50_000)
    assert not chain.record(credits, chain.aud(SHA[3])) and chain.code == 118
    # a new month starts the count again: free, in a counter of its own
    chain.warp(10 * DAY)
    month = meter.yyyymm(chain.now())
    assert month == before.month + 1
    assert chain.record(credits, chain.aud(SHA[3])), chain.err
    assert f"fee=0 month={month} n=1 " in chain.said("knosm:eval")[0]
    assert chain.month().evaluations == 1 and chain.month(month=before.month).evaluations == 3
    assert meter.read_plan(chain.data(meter.plan_pda(BUYER))) == meter.Plan(tier=0, month=month, owner_id=BUYER, rate=0, expiry=0, used=1)
    assert meter.quote(meter.read_plan(chain.data(meter.plan_pda(BUYER))), 6, chain.now()) == 0


def test_a_plan_sets_the_rate_until_it_expires_and_only_the_fee_owner_sets_one():
    chain = Meter()
    mint, _, credits = paid(chain)
    me, setter = chain.payer.pubkey(), PLAN_SETTER.pubkey()
    expiry = chain.now() + DAY
    stranger = chain.fund()
    assert not chain.send([meter.set_plan_ix(stranger.pubkey(), stranger.pubkey(), BUYER, 2, 20_000, expiry)], stranger) and chain.code == 121
    ix = meter.set_plan_ix(meter.FEE_OWNER, me, BUYER, 2, 20_000, expiry)                  # FEE_OWNER's address, without its signature
    unsigned = type(ix)(ix.program_id, ix.data, [type(ix.accounts[0])(meter.FEE_OWNER, False, False), *ix.accounts[1:]])
    assert not chain.send([unsigned]) and chain.code == 121
    for rate in (0, 19_999, 50_001, 10 ** 12):              # 0.02 to 0.05, nothing else
        assert not chain.send([meter.set_plan_ix(setter, me, BUYER, 2, rate, expiry)], signers=[PLAN_SETTER]) and chain.code == 111
    assert chain.send([meter.set_plan_ix(setter, me, BUYER, 2, 20_000, expiry)], signers=[PLAN_SETTER]), chain.err
    assert chain.said("knosm:plan") == [f"knosm:plan owner={BUYER} tier=2 rate=20000 expiry={expiry}"]
    plan = meter.read_plan(chain.data(meter.plan_pda(BUYER)))
    assert plan == meter.Plan(tier=2, month=meter.yyyymm(chain.now()), owner_id=BUYER, rate=20_000, expiry=expiry, used=FREE)     # the count is kept
    assert meter.quote(plan, 6, chain.now()) == 20_000 and meter.quote(plan, 6, expiry) == 50_000
    assert chain.record(credits, chain.aud(SHA[0])), chain.err
    assert "fee=20000 " in chain.said("knosm:eval")[0] and chain.fees(mint) == 20_000
    # another owner's evaluations are not this plan's
    _, other = chain.open(mint, 777, USDC)
    chain.set_used(777, FREE)
    assert chain.record(other, chain.aud(SHA[0], buyer=777)), chain.err
    assert "fee=50000 " in chain.said("knosm:eval")[0]
    # past its expiry the price is the list price again
    chain.warp(DAY)
    assert chain.record(credits, chain.aud(SHA[1])), chain.err
    assert "fee=50000 " in chain.said("knosm:eval")[0] and chain.fees(mint) == 20_000 + 50_000 + 50_000
    # a plan for an owner the meter has never seen
    assert chain.send([meter.set_plan_ix(setter, me, 31337, 1, 35_000, chain.now() + DAY)], signers=[PLAN_SETTER]), chain.err
    assert meter.read_plan(chain.data(meter.plan_pda(31337))).rate_at(chain.now()) == 35_000


def test_another_workflow_another_owner_or_a_second_attempt_is_refused():
    chain = Meter()
    mint, _, credits = paid(chain)
    aud = chain.aud(SHA[0])
    for why, code, over in (("the funding workflow", 115, dict(file="fund.yml")), ("a workflow of the buyer's own", 115, dict(file="ci.yml")),
                            ("the same file in another repository", 115, dict(wf_repo="mallory/Knos")), ("another commit", 115, dict(wf_sha="d" * 40)),
                            ("a re-run", 114, dict(run_attempt=2)), ("a self-hosted runner", 114, dict(runner_environment="self-hosted")),
                            ("a run in the seller's repository", 117, dict(repository_owner_id=SELLER)),
                            ("a run in a stranger's repository", 117, dict(repository_owner_id=999))):
        assert not chain.record(credits, aud, **over) and chain.code == code, why
    for bad in (f"knos2:pay:1:2:3:{SHA[0]}:{ORDER.hex()}:0:-", aud + ":1", aud.replace("knosm:eval", "knosm:pay"), aud[:-len(":1:2000000")] + ":2:2000000",
                chain.aud(SHA[0], seller=0)):
        token = chain.gh(bad, file="attest.yml", repository_owner_id=BUYER)
        ix = meter.record_ix(chain.payer.pubkey(), token, chain.key_of(token), credits, chain.credits(credits), aud, chain.now())
        assert not chain.send([ix]) and chain.code == 116, bad
    # credits prepaid for another owner are not spent by this buyer's runs, nor this buyer's by another's
    _, theirs = chain.open(mint, 777, USDC)
    assert not chain.record(theirs, aud) and chain.code == 117
    assert not chain.record(credits, chain.aud(SHA[0], buyer=777)) and chain.code == 117
    # an account that is not a Credits account of this program
    token = chain.token(aud)
    ix = meter.record_ix(chain.payer.pubkey(), token, chain.key_of(token), meter.plan_pda(BUYER), chain.credits(credits), aud, chain.now())
    assert not chain.send([ix]) and chain.code == 112
    assert chain.month().evaluations == 0 and chain.held(credits) == 5 * USDC
    # both pinned workflows count
    assert chain.record(credits, aud, file="attest.yml"), chain.err
    assert chain.record(credits, chain.aud(SHA[1]), file="prove.yml"), chain.err
    assert chain.month().evaluations == 2


def test_the_wallet_that_opened_the_credits_pins_the_workflows_and_nobody_else():
    chain = Meter()
    mint, wallet, credits = paid(chain)
    tp = chain.token_program(mint)
    assert chain.said("knosm:credits") == []
    # the same wallet sends OpenCredits again: a new commit, the same account and money
    assert chain.send([meter.open_credits_ix(wallet.pubkey(), BUYER, mint, WF_REPO, "d" * 40, tp)], wallet), chain.err
    assert chain.said("knosm:credits") == [f"knosm:credits owner={BUYER} authority={wallet.pubkey()} mint={mint} wf={'d' * 40}"]
    c = chain.credits(credits)
    assert (c.wf_sha, c.wf_repo_hash, c.authority, c.owner_id, c.mint, chain.held(credits)) == ("d" * 40, meter.wf_repo_hash(WF_REPO), wallet.pubkey(), BUYER, mint, 5 * USDC)
    assert not chain.record(credits, chain.aud(SHA[0])) and chain.code == 115                # the old commit no longer counts
    assert chain.record(credits, chain.aud(SHA[0]), wf_sha="d" * 40), chain.err
    # a stranger's OpenCredits makes credits of the stranger's own: it cannot reach this account
    stranger = chain.fund()
    assert chain.send([meter.open_credits_ix(stranger.pubkey(), BUYER, mint, "mallory/Knos", "e" * 40, tp)], stranger), chain.err
    assert chain.credits(credits).wf_sha == "d" * 40
    ix = meter.open_credits_ix(wallet.pubkey(), BUYER, mint, "mallory/Knos", "e" * 40, tp)
    forged = type(ix)(ix.program_id, ix.data, [type(ix.accounts[0])(stranger.pubkey(), True, True), *ix.accounts[1:]])
    assert not chain.send([forged], stranger) and chain.code == 112
    # what a pin must be, and whose credits
    for bad, code in ((meter.open_credits_ix(wallet.pubkey(), 0, mint, WF_REPO, WF_SHA, tp), 111),
                      (meter.open_credits_ix(wallet.pubkey(), BUYER, mint, WF_REPO, "D" * 40, tp), 111),
                      (meter.open_credits_ix(wallet.pubkey(), BUYER, mint, WF_REPO, "main" + " " * 36, tp), 111)):
        assert not chain.send([bad], wallet) and chain.code == code


def test_only_the_authority_withdraws_and_only_to_itself():
    chain = Meter()
    mint, wallet, credits = paid(chain)
    mine = chain.token_account(wallet.pubkey(), mint)
    stranger, theirs = chain.wallet(mint)
    # a stranger signs; the stranger passes the authority's key without its signature; the authority sends to a stranger
    assert not chain.send([meter.withdraw_credits_ix(stranger.pubkey(), credits, mint, USDC, theirs)], stranger) and chain.code == 112
    ix = meter.withdraw_credits_ix(wallet.pubkey(), credits, mint, USDC, theirs)
    unsigned = type(ix)(ix.program_id, ix.data, [type(ix.accounts[0])(wallet.pubkey(), False, False), *ix.accounts[1:]])
    assert not chain.send([unsigned], stranger) and chain.code == 112
    assert not chain.send([ix], wallet) and chain.code == 120
    assert not chain.send([meter.withdraw_credits_ix(wallet.pubkey(), credits, mint, 5 * USDC + 1)], wallet) and chain.code == 118
    # another credits account's money is not this wallet's to take
    _, other = chain.open(mint, 777, USDC)
    ix = meter.withdraw_credits_ix(wallet.pubkey(), credits, mint, USDC)
    swapped = type(ix)(ix.program_id, ix.data, [*ix.accounts[:2], type(ix.accounts[2])(meter.crtok_pda(other), False, True), *ix.accounts[3:]])
    assert not chain.send([swapped], wallet) and chain.code == 110
    assert (chain.held(credits), chain.held(other), chain.balance(theirs)) == (5 * USDC, USDC, 0)
    assert chain.send([meter.withdraw_credits_ix(wallet.pubkey(), credits, mint, USDC)], wallet), chain.err
    assert chain.said("knosm:withdrawn") == [f"knosm:withdrawn owner={BUYER} authority={wallet.pubkey()} mint={mint} amount={USDC}"]
    assert (chain.held(credits), chain.balance(mine)) == (4 * USDC, USDC)
    assert chain.record(credits, chain.aud(SHA[0])), chain.err
    assert chain.send([meter.withdraw_credits_ix(wallet.pubkey(), credits, mint)], wallet), chain.err        # 0: everything that is left
    assert (chain.held(credits), chain.balance(mine), chain.fees(mint)) == (0, 5 * USDC - 50_000, 50_000)
    assert not chain.record(credits, chain.aud(SHA[1])) and chain.code == 118


def test_the_fee_goes_to_the_fee_owner_and_nowhere_else():
    chain = Meter()
    mint, wallet, credits = paid(chain)
    aud = chain.aud(SHA[0])
    token = chain.token(aud)
    relayer, relayers = chain.wallet(mint)
    for fee_token in (relayers, chain.token_account(wallet.pubkey(), mint), meter.crtok_pda(credits), chain.token_account(meter.FEE_OWNER, chain.new_mint())):
        assert not chain.record(credits, aud, token, relayer, fee_token=fee_token) and chain.code == 120
    assert chain.record(credits, aud, token, relayer), chain.err       # anyone relays; the money goes where the program says
    assert (chain.fees(mint), chain.balance(relayers), chain.held(credits)) == (50_000, 0, 5 * USDC - 50_000)
    # another mint's accounts in place of the credits' own
    other = chain.new_mint()
    c = chain.credits(credits)
    c.mint = other
    token = chain.token(chain.aud(SHA[1]))
    ix = meter.record_ix(chain.payer.pubkey(), token, chain.key_of(token), credits, c, chain.aud(SHA[1]), chain.now())
    assert not chain.send([ix]) and chain.code == 110


def test_the_counters_equal_the_logs():
    chain = Meter()
    mint, _, credits = paid(chain, 5 * USDC)
    chain.set_used(BUYER, FREE - 3)                         # some free, some paid
    plan = [(SELLER, 0, 1, 2 * USDC), (SELLER, 1, 0, 2 * USDC), (777000, 2, 1, 7 * USDC), (SELLER, 0, 1, 2 * USDC), (SELLER, 3, 1, 1), (777000, 4, 0, 0),
            (SELLER, 1, 1, 9 * USDC), (SELLER, 5, 1, 3 * USDC + 1), (777000, 6, 1, 123_456), (SELLER, 7, 0, 5), (SELLER, 5, 0, 1)]
    for seller, artifact, verdict, rate in plan:
        assert chain.record(credits, chain.aud(SHA[artifact], verdict, rate, seller=seller)), chain.err
    chain.warp(10 * DAY)                                    # and a second month
    for seller, artifact, verdict, rate in ((SELLER, 8, 1, 4 * USDC), (SELLER, 0, 1, 2 * USDC), (SELLER, 9, 0, 0)):
        assert chain.record(credits, chain.aud(SHA[artifact], verdict, rate, seller=seller)), chain.err
    first, second = meter.yyyymm(chain.now() - 10 * DAY), meter.yyyymm(chain.now())
    got = {}
    for seller in (SELLER, 777000):
        for month in (first, second):
            s = meter.statement(chain.ledger, BUYER, seller, month)
            assert s == chain.month(seller=seller, month=month), (seller, month)
            assert s.evaluations == s.accepted + s.rejected
            got[seller, month] = s
    assert got[SELLER, first] == meter.Statement(BUYER, SELLER, first, evaluations=5, accepted=3, rejected=2, value=5 * USDC + 2, fees=150_000)
    assert got[777000, first] == meter.Statement(BUYER, 777000, first, evaluations=3, accepted=2, rejected=1, value=7 * USDC + 123_456, fees=100_000)
    assert got[SELLER, second] == meter.Statement(BUYER, SELLER, second, evaluations=2, accepted=1, rejected=1, value=4 * USDC, fees=0)
    assert got[777000, second] == meter.Statement(BUYER, 777000, second)
    # the money agrees too: what the credits paid is what the statements say, and what FEE_OWNER holds
    fees = sum(s.fees for s in got.values())
    assert fees == chain.credits(credits).spent == chain.fees(mint) == 5 * USDC - chain.held(credits) == 250_000
    assert sum(s.evaluations for s in got.values()) == chain.credits(credits).evaluations == 10
    # only the knosm:eval lines are evaluations
    assert meter.parse_eval("knosm:retry buyer=1 key=00") is None and meter.parse_eval("knosm:eval buyer=1 seller=2 verdict=0")["verdict"] == "0"


def test_a_revoked_key_counts_nothing():
    chain = Meter()
    _, _, credits = paid(chain)
    aud = chain.aud(SHA[0])
    token = chain.token(aud)
    assert chain.revoke(oidc.GITHUB, chain.github), chain.err
    assert not chain.record(credits, aud, token) and chain.code == 78
    assert chain.month().evaluations == 0


def test_an_expired_key_a_private_key_and_another_account_in_the_keys_place_count_nothing():
    chain = Meter()
    _, _, credits = paid(chain)
    aud = chain.aud(SHA[0])
    token = chain.token(aud)
    key = chain.key_of(token)
    # another key account of the verifier, and an account that is not the verifier's
    other = oidc.key_pda(oidc.GITHUB, chain.github + 2)
    for wrong in (other, chain.payer.pubkey(), token):
        ix = meter.record_ix(chain.payer.pubkey(), token, wrong, credits, chain.credits(credits), aud, chain.now())
        assert not chain.send([ix]) and chain.code == 110
    # a key the verifier flags in a way the meter does not know (a private key is one): refused, whatever else it says
    real = chain.svm.get_account(key)
    for flag in (8, 16, 128):
        d = bytearray(real.data)
        d[24] |= flag
        chain.svm.set_account(key, Account(real.lamports, bytes(d), real.owner))
        assert not chain.record(credits, aud, token) and chain.code == 122, flag
    # a key account longer than the public keys' layout
    chain.svm.set_account(key, Account(real.lamports, bytes(real.data) + bytes(32), real.owner))
    assert not chain.record(credits, aud, token) and chain.code == 122
    chain.svm.set_account(key, Account(real.lamports, bytes(real.data), real.owner))
    # the key expires 30 days after it was registered; a token it verified just before stops counting with it
    chain.warp(oidc.KEY_TTL - 200)
    aud = chain.aud(SHA[1])
    token = chain.token(aud)
    chain.set_used(BUYER, FREE)                             # a new month began on the way
    chain.warp(200)
    assert not chain.record(credits, aud, token) and chain.code == 77
    assert chain.month().evaluations == 0
    # a token over an hour past its expiry
    chain2 = Meter()
    _, _, credits = paid(chain2)
    token = chain2.token(aud)
    chain2.warp(300 + oidc.LATE)
    assert not chain2.record(credits, aud, token) and chain2.code == 113
    chain2.warp(-(300 + oidc.LATE))
    assert chain2.record(credits, aud, token), chain2.err


def test_the_mint_rules():
    chain = Meter()
    me = chain.payer.pubkey()
    hook = Keypair().pubkey()

    def opens(mint: Pubkey) -> bool:
        wallet = chain.fund(1)
        return chain.send([meter.open_credits_ix(wallet.pubkey(), BUYER, mint, WF_REPO, WF_SHA, chain.token_program(mint))], wallet)

    # Token-2022: a plain mint and one with a listed extension pass; everything else is refused, whatever it is set to
    assert opens(chain.new_mint22()) and opens(chain.new_mint22(confidential=True))
    for why, mint in (("a transfer fee of nothing", chain.new_mint22(fee=(0, 0))), ("a transfer fee", chain.new_mint22(fee=(100, 5_000_000))),
                      ("a permanent delegate", chain.new_mint22(permanent_delegate=me)), ("a hook that only names an authority", chain.new_mint22(hook=(me, None))),
                      ("a hook program", chain.new_mint22(hook=(me, hook))), ("non-transferable", chain.new_mint22(non_transferable=True)),
                      ("accounts that start frozen", chain.new_mint22(default_state=2)), ("a default state", chain.new_mint22(default_state=1))):
        assert not opens(mint) and chain.code == 119, why
    # decimals: prices are in whole units, and 0.02 needs two
    for decimals, ok in ((0, False), (1, False), (2, True), (9, True)):
        assert opens(chain.new_mint(decimals)) == ok, decimals
    # the token program passed is the mint's owner
    mint = chain.new_mint()
    wallet = chain.fund(1)
    assert not chain.send([meter.open_credits_ix(wallet.pubkey(), BUYER, mint, WF_REPO, WF_SHA, meter.TOKEN_2022)], wallet) and chain.code == 119
    # a Token-2022 mint with nine decimals, end to end: 0.05 is 50,000,000 of its units
    mint = chain.new_mint22(decimals=9, confidential=True)
    wallet, credits = chain.open(mint, amount=10 ** 9)
    chain.fees(mint)
    chain.set_used(BUYER, FREE)
    c = chain.credits(credits)
    assert (c.token_program, c.decimals) == (meter.TOKEN_2022, 9)
    assert chain.record(credits, chain.aud(SHA[0])), chain.err
    assert (chain.fees(mint), chain.held(credits)) == (50_000_000, 10 ** 9 - 50_000_000) == (meter.fee_units(meter.FEE, 9), 10 ** 9 - meter.fee_units(meter.FEE, 9))
    assert chain.send([meter.withdraw_credits_ix(wallet.pubkey(), credits, mint, 0, token_program=meter.TOKEN_2022)], wallet), chain.err
    assert chain.held(credits) == 0


# ---- idl/knos_meter.json, the source and the client say the same thing ------------------------------------------------

IDL = json.loads((ROOT / "idl" / "knos_meter.json").read_text(encoding="utf-8"))
SRC = {p.name: p.read_text(encoding="utf-8") for p in (ROOT / "programs-v2" / "knos_meter" / "src").glob("*.rs")}
SIZE = {"u8": 1, "u32": 4, "u64": 8, "i64": 8, "publicKey": 32}
K = {n: Pubkey(bytes([i + 1]) * 32) for i, n in enumerate(["authority", "mint", "relayer", "token", "key", "payer"])}


def size(t) -> int:
    return SIZE[t] if isinstance(t, str) else size(t["array"][0]) * t["array"][1]


def consts(source: str, kind: str = "usize") -> dict[str, int]:
    return {m.group(1): int(m.group(2).replace("_", "")) for m in re.finditer(rf"pub const (\w+): {kind} = ([\d_]+);", source)}


def test_the_idl_is_the_program():
    ids = json.loads((ROOT / "programs-v2" / "program_ids.json").read_text())
    assert IDL["metadata"] == {"origin": "shank", "address": ids["knos_meter"]} and str(meter.METER_ID) == ids["knos_meter"] and IDL["name"] == "knos_meter"
    assert json.loads((ROOT / "src" / "knos" / "settle" / "v2" / "program_ids.json").read_text()) == ids
    lib = SRC["lib.rs"]
    pins = dict(re.findall(r'pub const (\w+): Pubkey = pubkey!\("(\w+)"\);', lib))
    assert pins == {"OIDC_ID": ids["knos_oidc"], "FEE_OWNER": ids["fee_owner"]}
    assert set(re.findall(r'pubkey!\("(\w+)"\)', re.search(r"pub const FEE_MINTS: \[Pubkey; 2\] = \[(.+?)\];", lib).group(1))) == {str(pay2.USDC_DEVNET), str(pay2.USDC_MAINNET)}     # credits open in Circle's USDC only (a test build takes any)
    # every instruction the header lists, by its number, with the accounts it lists, as the dispatch and the handlers take them
    listed = {m.group(2): (int(m.group(1)), m.group(3).split()) for m in re.finditer(r"^//!   (\d+) (\w+) *(.*)$", lib, re.M)}
    arms = dict((int(n), f) for n, f in re.findall(r"^        (\d+) => meter::(\w+)\(", lib, re.M))
    assert {i["name"]: i["discriminant"]["value"] for i in IDL["instructions"]} == {name: n for name, (n, _) in listed.items()}
    assert sorted(arms) == sorted(n for n, _ in listed.values()) == [0, 1, 2, 3, 4, 5, 6, 7]
    for ix in IDL["instructions"]:
        n, accounts = listed[ix["name"]]
        flags = [(a.split("(")[0], "s" in a.partition("(")[2], "w" in a.partition("(")[2]) for a in accounts]
        camel = lambda s: re.sub(r"_(\w)", lambda m: m.group(1).upper(), s).replace("system", "systemProgram")  # noqa: E731
        assert [(a["name"], a["isSigner"], a["isMut"]) for a in ix["accounts"]] == [(camel(name), s, w) for name, s, w in flags], ix["name"]
        if not accounts:                         # Version takes no account
            assert f"pub fn {arms[n]}(data: &[u8])" in SRC["meter.rs"]
            continue
        taken = re.search(rf"pub fn {arms[n]}\(.*?let \[([^\]]+)\] = take\(accounts\)\?;", SRC["meter.rs"], re.S).group(1)
        assert len(taken.split(",")) == len(ix["accounts"]), ix["name"]
    # every account layout: the offsets of state.rs, the length, what the client reads
    state = consts(SRC["state.rs"])
    names = {"Credits": ("C_", {"tokenProgram": "C_T22", "wfRepo": "C_WF_REPO", "wfSha": "C_WF_SHA", "ownerId": "C_OWNER_ID", "evaluations": "C_EVALS"}, "CREDITS_LEN"),
             "Plan": ("P_", {"ownerId": "P_OWNER_ID"}, "PLAN_LEN"), "Mark": ("K_", {"buyerId": "K_BUYER", "sellerId": "K_SELLER", "closeAfter": "K_CLOSE_AFTER"}, "MARK_LEN"),
             "Month": ("M_", {"buyerId": "M_BUYER", "sellerId": "M_SELLER", "evaluations": "M_EVALS"}, "MONTH_LEN"),
             "Ledger": ("L_", {"buyerId": "L_BUYER", "sellerId": "L_SELLER", "nextSeq": "L_NEXT_SEQ", "evaluations": "L_EVALS"}, "LEDGER_LEN")}
    assert [a["name"] for a in IDL["accounts"]] == list(names)
    for a in IDL["accounts"]:
        prefix, special, length = names[a["name"]]
        at, seen = 0, set()
        for f in a["type"]["fields"]:
            if not f["name"].startswith("padding"):
                const = special.get(f["name"], prefix + f["name"].upper())
                assert state[const] == at, (a["name"], f["name"])
                seen.add(const)
            at += size(f["type"])
        assert at == state[length] == getattr(meter, length, getattr(_meter, length, None)) and seen == {k for k in state if k.startswith(prefix)}, a["name"]
    # the error codes, the prices and the bounds
    codes = consts(lib, "u32") | consts(SRC["gh.rs"], "u32")
    assert {e["code"] for e in IDL["errors"]} == set(codes.values()) | {61, 62, 63} == set(meter.ERRORS) | set(_meter.BATCH_ERRORS)
    assert len(set(codes.values())) == len(codes)
    prices = consts(lib, "u64")
    assert (prices["FEE"], prices["PLAN_MIN"], prices["FREE_PER_MONTH"], prices["MICRO"]) == (meter.FEE, meter.PLAN_MIN, meter.FREE_PER_MONTH, meter.MICRO) == (50_000, 20_000, 10_000, 10 ** 6)
    times = consts(lib, "i64")
    assert (times["TOKEN_AHEAD"], times["TOKEN_LIFE"]) == (meter.TOKEN_AHEAD, meter.TOKEN_LIFE)
    # a mark can be closed once no token of its month is accepted: the longest life the meter takes, and the verifier's hour past expiry
    late = int(re.search(r"pub const LATE: i64 = (\d+);", (ROOT / "crates" / "knos-oidc-interface" / "src" / "lib.rs").read_text(encoding="utf-8")).group(1))
    assert times["MARK_GRACE"] == meter.MARK_GRACE == meter.TOKEN_LIFE + late and state["MARK_LEN_1"] == meter.MARK_LEN_1 and state["K_PAYER"] == meter.MARK_PAYER
    token = SRC["token.rs"]
    assert tuple(int(x) for x in re.search(r"pub const EXTENSIONS: \[u16; \d+\] = \[([\d, ]+)\];", token).group(1).split(",")) == meter.EXTENSIONS
    decimals = consts(token, "u8")
    assert (decimals["MIN_DECIMALS"], decimals["MAX_DECIMALS"]) == (meter.MIN_DECIMALS, meter.MAX_DECIMALS)
    # every test-only value sits behind the testkeys feature, with a harmless twin for the real build
    assert 'pub const ANY_MINT: bool = cfg!(feature = "testkeys");' in lib
    assert re.search(r'#\[cfg\(not\(feature = "testkeys"\)\)\]\npub const TEST_FEE_OWNER: Option<Pubkey> = None;', lib)
    key = re.search(r'#\[cfg\(feature = "testkeys"\)\]\npub const TEST_FEE_OWNER: Option<Pubkey> = Some\(Pubkey::new_from_array\(\[\s*([\d, ]+),?\s*\]\)\);', lib).group(1)
    assert bytes(int(x) for x in key.replace(" ", "").strip(",").split(",")) == bytes(PLAN_SETTER.pubkey())


def test_the_client_sends_what_the_idl_says():
    credits = meter.credits_pda(BUYER, K["authority"], K["mint"])
    c = meter.Credits(token_program=meter.TOKEN, decimals=6, owner_id=BUYER, authority=K["authority"], mint=K["mint"], spent=0, evaluations=0,
                      wf_repo_hash=meter.wf_repo_hash(WF_REPO), wf_sha=WF_SHA)
    aud = meter.eval_audience(BUYER, SELLER, ORDER, SHA[3], POLICY, 4, 1, 2 * USDC)
    e = meter.parse_audience(aud)
    assert e == meter.Eval(BUYER, SELLER, ORDER, SHA[3], POLICY, 4, True, 2 * USDC) and aud == f"knosm:eval:{BUYER}:{SELLER}:{ORDER.hex()}:{SHA[3]}:{POLICY.hex()}:4:1:{2 * USDC}"
    now = 1_790_000_000
    assert meter.yyyymm(now) == 202609 and meter.yyyymm(1_790_812_800) == 202610 and meter.yyyymm(-5) == 197001
    for t, nxt in ((0, 2_678_400), (951_782_399, 951_868_800), (1_790_812_799, 1_790_812_800), (1_790_812_800, 1_793_491_200), (1_798_761_599, 1_798_761_600)):
        assert meter.next_month(t) == nxt and meter.close_after(t) == nxt + 7200, t     # the same table as lib.rs
    known = {"authority": K["authority"], "credits": credits, "crtok": meter.crtok_pda(credits), "mint": K["mint"], "auth": meter.auth_pda(), "tokenProgram": meter.TOKEN,
             "systemProgram": meter.SYSTEM, "destToken": meter.ata(K["authority"], K["mint"]), "feeOwner": meter.FEE_OWNER, "payer": K["payer"],
             "plan": meter.plan_pda(BUYER), "relayer": K["relayer"], "token": K["token"], "key": K["key"], "mark": meter.mark_pda(BUYER, e.key),
             "month": meter.month_pda(BUYER, SELLER, 202609), "feeToken": meter.ata(meter.FEE_OWNER, K["mint"]),
             "ledger": _meter.ledger_pda(BUYER, SELLER, 202609), "claim": _meter.ledger_pda(BUYER, SELLER, 202609, True)}
    batch, claim = (_meter.batch_audience(BUYER, SELLER, 202609, 3, 5000, 4321, 9, ORDER, kind) for kind in ("batch", "claim"))
    built = {"OpenCredits": (meter.open_credits_ix(K["authority"], BUYER, K["mint"], WF_REPO, WF_SHA),
                             dict(ownerId=BUYER, wfRepo=meter.wf_repo_hash(WF_REPO), wfSha=WF_SHA.encode())),
             "WithdrawCredits": (meter.withdraw_credits_ix(K["authority"], credits, K["mint"], 7), dict(amount=7)),
             "SetPlan": (meter.set_plan_ix(meter.FEE_OWNER, K["payer"], BUYER, 2, 20_000, now), dict(ownerId=BUYER, tier=2, rate=20_000, expiry=now)),
             "Record": (meter.record_ix(K["relayer"], K["token"], K["key"], credits, c, aud, now), {}),
             "CloseMark": (meter.close_mark_ix(K["payer"], meter.mark_pda(BUYER, e.key)), {}),
             "RecordBatch": (_meter.record_batch_ix(K["relayer"], K["token"], K["key"], credits, c, batch), {}),
             "ClaimBatch": (_meter.claim_batch_ix(K["relayer"], K["token"], K["key"], claim), {}),
             "Version": (_meter.version_ix(), {})}
    assert set(built) == {i["name"] for i in IDL["instructions"]}
    for ix in IDL["instructions"]:
        sent, args = built[ix["name"]]
        data = bytes([ix["discriminant"]["value"]])
        for a in ix["args"]:
            v = args[a["name"]]
            data += v.to_bytes(size(a["type"]), "little", signed=a["type"] == "i64") if isinstance(v, int) else bytes(v)
        assert sent.program_id == meter.METER_ID and bytes(sent.data) == data, ix["name"]
        assert [(m.pubkey, m.is_signer, m.is_writable) for m in sent.accounts] == [(known[a["name"]], a["isSigner"], a["isMut"]) for a in ix["accounts"]], ix["name"]
    # the readers read the layouts of the IDL
    def raw(account: str, **values) -> bytes:
        out = b""
        for f in next(a for a in IDL["accounts"] if a["name"] == account)["type"]["fields"]:
            v = values.get(f["name"], 0)
            out += v.to_bytes(size(f["type"]), "little", signed=f["type"] == "i64") if isinstance(v, int) else bytes(v)
        return out
    assert meter.read_credits(raw("Credits", version=1, tokenProgram=1, decimals=9, ownerId=BUYER, authority=K["authority"], mint=K["mint"], spent=5, evaluations=6,
                                  wfRepo=meter.wf_repo_hash(WF_REPO), wfSha=WF_SHA.encode())) == meter.Credits(
        meter.TOKEN_2022, 9, BUYER, K["authority"], K["mint"], 5, 6, meter.wf_repo_hash(WF_REPO), WF_SHA)
    assert meter.read_plan(raw("Plan", version=1, tier=3, month=202609, ownerId=BUYER, rate=20_000, expiry=-1, used=8)) == meter.Plan(3, 202609, BUYER, 20_000, -1, 8)
    assert meter.read_mark(raw("Mark", version=2, verdict=1, month=202609, buyerId=BUYER, sellerId=SELLER, time=now, rate=4, fee=5, payer=K["relayer"],
                               closeAfter=now + 9)) == meter.Mark(True, 202609, BUYER, SELLER, now, 4, 5, K["relayer"], now + 9)
    assert meter.read_mark(raw("Mark", version=1)) is None and meter.read_mark(raw("Mark", version=2)[:48]) is None
    assert meter.read_month(raw("Month", version=1, month=202609, buyerId=BUYER, sellerId=SELLER, evaluations=3, accepted=2, rejected=1, value=9, fees=7)) == meter.Statement(
        BUYER, SELLER, 202609, 3, 2, 1, 9, 7)
    assert _meter.read_ledger(raw("Ledger", version=1, kind=1, month=202609, buyerId=BUYER, sellerId=SELLER, nextSeq=2, evaluations=3, accepted=2, value=9, fees=7,
                                  chain=ORDER)) == _meter.BatchLedger(True, 202609, BUYER, SELLER, 2, 3, 2, 9, 7, ORDER)
    assert meter.read_credits(None) is None and meter.read_mark(b"") is None and meter.read_plan(None).used == 0 and meter.read_month(None, 1, 2, 3) == meter.Statement(1, 2, 3)
    with pytest.raises(ValueError):
        meter.eval_audience(BUYER, SELLER, ORDER[:31], SHA[0], POLICY, 0, 1, 1)
    with pytest.raises(ValueError):
        meter.parse_audience("knos2:pay:1:2")
