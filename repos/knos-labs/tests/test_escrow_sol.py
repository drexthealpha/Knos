"""The Solana escrow program in the Solana runtime (LiteSVM + real SPL Token): pay only for accepted (or proven) work.

Every attack from the live Tempo run is ported, plus Solana-specific ones (paying an attacker's token account, a fake
fee account, dust on the job address, an attacker's vault), the 0.3.4 additions (paid on proof by a named verifier,
the minimum job and fee floor, the pause and the per-job cap, jobs posted before the upgrade), and 1,000 random
interleavings that must conserve every token and leave nothing stuck. Runs in seconds; no validator, no network.
The 10,000-step run is tests/test_escrow_fuzz.py (slow).
"""

from __future__ import annotations

import hashlib
import random
import struct

import pytest

pytest.importorskip("solders.litesvm")

from _jobharness import Escrow  # noqa: E402

from knos.jobs import sol  # noqa: E402

PRICE = 5_000_000  # $5 in 6-decimal units
U = 1_000_000


@pytest.fixture(scope="module")
def env():
    e = Escrow(fee_bps=500)
    e.buyer, e.b_tok = e.party(10 ** 12)
    e.worker, e.w_tok = e.party()
    e.rival, e.r_tok = e.party()
    e.attacker, e.a_tok = e.party()
    e.verifier, e.v_tok = e.party()
    return e


def jid(tag: str) -> bytes:
    return hashlib.sha256(tag.encode()).digest()


def test_full_jobs_pay_the_worker_95_percent_and_knos_5(env):
    w0, f0 = env.balance(env.w_tok), env.balance(env.fee_token)
    for i in range(20):
        j = jid(f"full-{i}")
        assert env.post(env.buyer, env.b_tok, j, PRICE)
        assert env.job(j).state == "open"
        assert env.claim(env.worker, j)
        assert env.deliver(env.worker, j)
        assert env.accept(env.buyer, j, env.w_tok)
        assert env.job(j) is None                      # settled: the account is closed
    assert env.balance(env.w_tok) - w0 == 20 * PRICE * 95 // 100
    assert env.balance(env.fee_token) - f0 == 20 * PRICE * 5 // 100


ATTACKS = ["second_claim_by_rival", "deliver_by_non_worker", "refund_before_deadline", "accept_by_worker",
           "accept_by_attacker", "release_before_review_ends", "accept_paying_attacker_token_account",
           "accept_with_fake_fee_account", "reject_by_worker", "double_accept", "repost_same_id"]


@pytest.mark.parametrize("attack", ATTACKS)
def test_every_attack_is_refused(env, attack):
    e = env
    j = jid("attack-" + attack)
    assert e.post(e.buyer, e.b_tok, j, PRICE) and e.claim(e.worker, j)
    vault0 = e.balance(e.vault)
    if attack == "second_claim_by_rival":
        assert not e.claim(e.rival, j)
    elif attack == "deliver_by_non_worker":
        assert not e.deliver(e.attacker, j)
    elif attack == "refund_before_deadline":
        assert not e.refund(e.buyer, j, e.b_tok)
    else:
        assert e.deliver(e.worker, j)
        vault0 = e.balance(e.vault)                          # delivery returned the claim's stake to the worker
        if attack == "accept_by_worker":
            assert not e.accept(e.worker, j, e.w_tok)
        elif attack == "accept_by_attacker":
            assert not e.accept(e.attacker, j, e.a_tok)
        elif attack == "release_before_review_ends":
            assert not e.accept(e.attacker, j, e.w_tok, release=True)
        elif attack == "accept_paying_attacker_token_account":
            assert not e.accept(e.buyer, j, e.a_tok)
        elif attack == "accept_with_fake_fee_account":
            assert not e.accept(e.buyer, j, e.w_tok, fee_token=e.a_tok)
        elif attack == "reject_by_worker":
            assert not e.reject(e.worker, j, e.w_tok)
        elif attack == "double_accept":
            assert e.accept(e.buyer, j, e.w_tok)
            assert not e.accept(e.buyer, j, e.w_tok)
            return
        elif attack == "repost_same_id":
            assert not e.post(e.buyer, e.b_tok, j, PRICE)
    assert e.balance(e.vault) == vault0, "an attack moved money"


def test_reject_refunds_the_buyer_in_full(env):
    e, j = env, jid("reject")
    b0 = e.balance(e.b_tok)
    assert e.post(e.buyer, e.b_tok, j, PRICE) and e.claim(e.worker, j) and e.deliver(e.worker, j)
    assert e.reject(e.buyer, j, e.b_tok)
    assert e.balance(e.b_tok) == b0 and e.job(j) is None


def test_a_silent_buyer_cannot_stall_payment(env):
    e, j = env, jid("silent")
    w0 = e.balance(e.w_tok)
    assert e.post(e.buyer, e.b_tok, j, PRICE, review=40) and e.claim(e.worker, j) and e.deliver(e.worker, j)
    assert not e.accept(e.worker, j, e.w_tok, release=True)
    e.warp(41)
    assert e.accept(e.worker, j, e.w_tok, release=True)
    assert e.balance(e.w_tok) - w0 == PRICE * 95 // 100


def test_no_delivery_refunds_after_the_deadline(env):
    e, j = env, jid("undelivered")
    b0 = e.balance(e.b_tok)
    assert e.post(e.buyer, e.b_tok, j, PRICE, work=20)
    assert not e.refund(e.buyer, j, e.b_tok)
    e.warp(21)
    assert not e.claim(e.rival, j)
    assert e.refund(e.buyer, j, e.b_tok)
    assert e.balance(e.b_tok) == b0


def test_dust_and_a_foreign_vault_do_not_work(env):
    from solders.system_program import TransferParams, transfer
    e, j = env, jid("dust")
    assert e.send([transfer(TransferParams(from_pubkey=e.attacker.pubkey(), to_pubkey=sol.job_pda(e.pid, j),
                                           lamports=e.svm.minimum_balance_for_rent_exemption(0)))],
                  e.attacker, [e.attacker])
    assert e.post(e.buyer, e.b_tok, j, PRICE), "dust on the job address must not block posting"
    assert not e.post(e.buyer, e.b_tok, jid("foreign-vault"), PRICE, vault=e.a_tok)


# ---- paid on proof -------------------------------------------------------------------------------------------------

def _delivered(e, tag: str, verifier=None, price: int = PRICE) -> bytes:
    j = jid(tag)
    assert e.post(e.buyer, e.b_tok, j, price, verifier=verifier.pubkey() if verifier else None)
    assert e.claim(e.worker, j) and e.deliver(e.worker, j)
    return j


def test_paid_on_proof_the_verifier_releases_with_no_buyer_step(env):
    e = env
    w0, f0 = e.balance(e.w_tok), e.balance(e.fee_token)
    j = _delivered(e, "proof-ok", e.verifier)
    assert e.job(j).verifier == e.verifier.pubkey() and e.job(j).proof is None
    root = hashlib.sha256(b"merkle root of the proof").digest()
    assert e.verify_release(e.verifier, j, e.w_tok, proof_root=root)
    assert e.job(j) is None                                  # settled: closed (the root is in the transaction)
    assert e.balance(e.w_tok) - w0 == PRICE * 95 // 100 and e.balance(e.fee_token) - f0 == PRICE * 5 // 100


def test_verifier_releases_unproven_work_refused(env):
    e = env
    j = _delivered(e, "proof-wrong-hash", e.verifier)
    vault0 = e.balance(e.vault)
    assert not e.verify_release(e.verifier, j, e.w_tok, result_hash=hashlib.sha256(b"other work").digest())
    assert e.job(j).state == "delivered" and e.balance(e.vault) == vault0
    assert e.verify_release(e.verifier, j, e.w_tok)          # the committed hash: released


@pytest.mark.parametrize("who", ["buyer", "worker", "attacker"])
def test_only_the_named_verifier_can_verify_release(env, who):
    e = env
    j = _delivered(e, "proof-not-verifier-" + who, e.verifier)
    assert not e.verify_release(getattr(e, who), j, e.w_tok)
    assert e.job(j).state == "delivered"


def test_verify_release_needs_a_verifier_and_a_delivery(env):
    e = env
    j = _delivered(e, "proof-none")                          # posted without a verifier
    assert not e.verify_release(e.verifier, j, e.w_tok)
    assert not e.verify_release(e.buyer, j, e.w_tok)
    k = jid("proof-early")
    assert e.post(e.buyer, e.b_tok, k, PRICE, verifier=e.verifier.pubkey())
    assert not e.verify_release(e.verifier, k, e.w_tok, result_hash=bytes(32))   # open: nothing delivered
    assert e.claim(e.worker, k)
    assert not e.verify_release(e.verifier, k, e.w_tok, result_hash=bytes(32))   # claimed: nothing delivered
    assert e.job(k).state == "claimed"


def test_verify_release_pays_once(env):
    e = env
    j = _delivered(e, "proof-double", e.verifier)
    assert e.verify_release(e.verifier, j, e.w_tok)
    vault0 = e.balance(e.vault)
    assert not e.verify_release(e.verifier, j, e.w_tok, proof_root=b"\x02" * 32)
    assert not e.accept(e.buyer, j, e.w_tok)
    e.warp(1000)
    assert not e.accept(e.rival, j, e.w_tok, release=True)
    assert e.balance(e.vault) == vault0


def test_verify_release_cannot_pay_anyone_but_the_worker(env):
    e = env
    j = _delivered(e, "proof-payee", e.verifier)
    assert not e.verify_release(e.verifier, j, e.v_tok)                       # the verifier's own account
    assert not e.verify_release(e.verifier, j, e.w_tok, fee_token=e.a_tok)    # a fake fee account
    assert e.job(j).state == "delivered"


def test_a_worker_cannot_verify_its_own_work(env):
    e = env
    j = jid("proof-self")
    assert e.post(e.buyer, e.b_tok, j, PRICE, verifier=e.worker.pubkey())
    assert not e.claim(e.worker, j)                          # the named verifier cannot take the job
    assert e.claim(e.rival, j) and e.deliver(e.rival, j)
    assert not e.verify_release(e.rival, j, e.r_tok)         # nor the worker verify its own
    assert e.verify_release(e.worker, j, e.r_tok)            # the named verifier releases the rival's work


def test_a_silent_verifier_leaves_accept_release_refund_open(env):
    e = env
    a = _delivered(e, "proof-silent-accept", e.verifier)
    assert e.accept(e.buyer, a, e.w_tok)                     # the buyer may still pay
    c = _delivered(e, "proof-silent-release", e.verifier)
    e.warp(41)
    assert e.accept(e.rival, c, e.w_tok, release=True)       # anyone after the review window
    d = jid("proof-silent-refund")
    assert e.post(e.buyer, e.b_tok, d, PRICE, work=20, verifier=e.verifier.pubkey())
    e.warp(21)
    assert e.refund(e.buyer, d, e.b_tok)                     # nothing delivered: refund


# ---- economics -----------------------------------------------------------------------------------------------------

def test_below_minimum_post_refused(env):
    e = env
    assert not e.post(e.buyer, e.b_tok, jid("min-1"), U - 1)
    assert not e.post(e.buyer, e.b_tok, jid("min-0"), 0)
    assert e.post(e.buyer, e.b_tok, jid("min-ok"), U)
    assert e.config()["min_amount"] == U and e.config()["min_fee"] == 50_000


def test_fee_floor_applied():
    e = Escrow(min_amount=100_000)                           # a config where the floor binds: 5% of 0.5 = 0.025
    buyer, btok = e.party(10 * U)
    worker, wtok = e.party()
    for tag, price, fee in (("half", 500_000, 50_000), ("one", U, 50_000), ("three", 3 * U, 150_000)):
        j = jid("floor-" + tag)
        f0, w0 = e.balance(e.fee_token), e.balance(wtok)
        assert e.post(buyer, btok, j, price) and e.claim(worker, j) and e.deliver(worker, j)
        assert e.accept(buyer, j, wtok)
        assert e.balance(e.fee_token) - f0 == fee == sol.fee_for(price, 500, 50_000, 100_000)
        assert e.balance(wtok) - w0 == price - fee
    assert e.balance(e.vault) == 0


def test_paused_post_refused_but_settlement_still_works():
    e = Escrow()
    buyer, btok = e.party(100 * U)
    worker, wtok = e.party()
    verifier, _ = e.party()
    a, b, c, d = (jid(f"pause-{k}") for k in "abcd")
    assert e.post(buyer, btok, a, U) and e.claim(worker, a) and e.deliver(worker, a)
    assert e.post(buyer, btok, b, U, verifier=verifier.pubkey()) and e.claim(worker, b) and e.deliver(worker, b)
    assert e.post(buyer, btok, c, U) and e.claim(worker, c) and e.deliver(worker, c)
    assert e.post(buyer, btok, d, U, work=20)
    assert not e.set_pause(True, admin=buyer)                # admin only
    assert e.set_pause(True) and e.config()["paused"]
    assert not e.post(buyer, btok, jid("pause-new"), U)
    assert e.accept(buyer, a, wtok)
    assert e.verify_release(verifier, b, wtok)
    assert e.reject(buyer, c, btok)
    e.warp(21)
    assert e.refund(buyer, d, btok)
    assert e.balance(e.vault) == 0
    assert e.set_pause(False) and e.post(buyer, btok, jid("pause-new"), U)


def test_cap_enforced_and_only_lowered_by_the_admin():
    e = Escrow()
    buyer, btok = e.party(100 * U)
    assert e.config()["max_amount"] == 0 and e.post(buyer, btok, jid("cap-none"), 50 * U)   # 0 = no cap
    assert not e.lower_cap(10 * U, admin=buyer)
    assert not e.lower_cap(0)                                # "no cap" cannot come back
    assert not e.lower_cap(U - 1)                            # never under the minimum job
    assert e.lower_cap(10 * U) and e.config()["max_amount"] == 10 * U
    assert not e.post(buyer, btok, jid("cap-over"), 10 * U + 1)
    assert e.post(buyer, btok, jid("cap-at"), 10 * U)
    assert not e.lower_cap(11 * U)                           # only downward
    assert e.lower_cap(5 * U) and not e.post(buyer, btok, jid("cap-6"), 6 * U)


def test_set_admin_then_the_old_admin_is_refused_and_set_fee_account():
    e = Escrow()
    new, _ = e.party()
    stranger, stok = e.party()
    old = e.admin
    assert not e.send([sol.set_admin(e.pid, stranger.pubkey(), stranger.pubkey())], stranger, [stranger])  # admin only
    assert not e.send([sol.set_admin(e.pid, old.pubkey(), sol.Pubkey.default())], old, [old])             # never zero
    assert e.send([sol.set_admin(e.pid, old.pubkey(), new.pubkey())], old, [old])
    assert e.config()["admin"] == new.pubkey()
    assert not e.set_pause(True)                                                          # the old admin: refused
    assert not e.send([sol.set_fee_account(e.pid, old.pubkey(), stok)], old, [old])
    assert e.send([sol.set_fee_account(e.pid, new.pubkey(), stok)], new, [new])
    assert e.config()["fee_token"] == stok
    assert e.set_pause(True, admin=new) and e.config()["paused"]


def test_init_is_once_and_the_retired_init_is_refused(env):
    from solders.instruction import Instruction
    e = env
    assert not e.send([sol.init2(e.pid, e.attacker.pubkey(), e.a_tok)], e.attacker, [e.attacker])
    assert not e.send([Instruction(e.pid, bytes([0]) + struct.pack("<H", 0), [])], e.attacker, [e.attacker])
    assert e.config()["admin"] == e.admin.pubkey()


def test_init2_after_an_upgrade_is_the_old_admins_alone():
    from solders.account import Account
    e = Escrow()                                             # then roll its config back to "just upgraded"
    admin = e.keypair()
    attacker = e.keypair()
    fee_tok = e.token_account(admin.pubkey())
    legacy = bytes(admin.pubkey()) + bytes(e.mint.pubkey()) + bytes(fee_tok) + struct.pack("<HB", 500, 255)
    e.svm.set_account(sol.legacy_config_pda(e.pid), Account(10 ** 9, legacy, e.pid, False, 0))
    e.svm.set_account(sol.config_pda(e.pid), Account(0, b"", sol.SYSTEM, False, 0))   # as before Init2 ran
    assert not e.send([sol.init2(e.pid, attacker.pubkey(), fee_tok)], attacker, [attacker])
    assert e.send([sol.init2(e.pid, admin.pubkey(), fee_tok)], admin, [admin])
    assert e.config()["admin"] == admin.pubkey() and e.config()["fee_token"] == fee_tok


def test_a_job_posted_before_the_upgrade_still_settles(env):
    """A 153-byte job from 0.3.1 (no verifier field): accept/release/refund work; it pays the old 5% even under the
    new minimum; nobody can verify-release it."""
    from solders.account import Account
    e = env
    j = jid("legacy-job")
    now = int(e.svm.get_clock().unix_timestamp)
    amount = 10_000                                          # a 0.01 USDC job from before the minimum
    raw = (bytes([3]) + bytes(e.buyer.pubkey()) + bytes(e.worker.pubkey()) + struct.pack("<Qqq", amount, now + 100, 40)
           + jid("legacy-brief") + e.result_hash(j))
    assert len(raw) == sol.LEGACY_JOB_LEN
    e.svm.set_account(sol.job_pda(e.pid, j), Account(e.svm.minimum_balance_for_rent_exemption(153), raw, e.pid,
                                                     False, 0))
    e.mint_to(e.vault, amount)
    got = e.job(j)
    assert got.state == "delivered" and got.verifier is None and got.amount == amount
    assert not e.verify_release(e.verifier, j, e.w_tok)
    w0, f0 = e.balance(e.w_tok), e.balance(e.fee_token)
    assert e.accept(e.buyer, j, e.w_tok)
    assert e.balance(e.w_tok) - w0 == 9_500 and e.balance(e.fee_token) - f0 == 500
    assert e.job(j) is None and e.lamports(sol.job_pda(e.pid, j)) == 0          # settled: closed


def test_a_job_posted_by_0_3_4_still_claims_and_settles(env):
    """A 217-byte job from 0.3.4 (no stake field): claimed with no stake, delivered, settled, closed."""
    from solders.account import Account
    e = env
    j = jid("v034-job")
    now = int(e.svm.get_clock().unix_timestamp)
    raw = (bytes([1]) + bytes(e.buyer.pubkey()) + bytes(32) + struct.pack("<Qqq", PRICE, now + 100, 40)
           + jid("v034-brief") + bytes(32) + bytes(32) + bytes(32))
    assert len(raw) == sol.V034_JOB_LEN
    e.svm.set_account(sol.job_pda(e.pid, j), Account(e.svm.minimum_balance_for_rent_exemption(217), raw, e.pid,
                                                     False, 0))
    e.mint_to(e.vault, PRICE)
    vault0 = e.balance(e.vault)
    assert e.claim(e.worker, j) and e.balance(e.vault) == vault0 and e.job(j).stake == 0
    assert e.deliver(e.worker, j) and e.accept(e.buyer, j, e.w_tok)
    assert e.job(j) is None and e.balance(e.vault) == vault0 - PRICE


# ---- 0.3.5 rules ---------------------------------------------------------------------------------------------------

def test_rule_verified_job_buyer_cannot_reject(env):
    e = env
    j = _delivered(e, "rule1-no-buyer-reject", e.verifier)
    vault0 = e.balance(e.vault)
    assert not e.reject(e.buyer, j, e.b_tok)
    assert e.job(j).state == "delivered" and e.balance(e.vault) == vault0


def test_rule_verify_reject_refunds_the_buyer(env):
    e = env
    j = _delivered(e, "rule1-verify-reject", e.verifier)
    b0 = e.balance(e.b_tok)
    for who in (e.buyer, e.worker, e.attacker):              # a verdict is the job's verifier's signature alone
        assert not e.verify_reject(who, j, e.b_tok)
    assert not e.verify_reject(e.verifier, j, e.a_tok)       # refunds go to the buyer only
    assert e.verify_reject(e.verifier, j, e.b_tok, proof_root=b"\x07" * 32)
    assert e.balance(e.b_tok) - b0 == PRICE and e.job(j) is None
    k = _delivered(e, "rule1-verify-reject-none")            # no verifier named: nobody can verify-reject
    assert not e.verify_reject(e.verifier, k, e.b_tok)
    m = _delivered(e, "rule1-verify-reject-late", e.verifier)
    e.warp(41)                                               # past the review deadline: the deadline settles it
    assert not e.verify_reject(e.verifier, m, e.b_tok)
    assert e.settle(e.attacker, m) and e.job(m) is None


def test_rule_deadline_settles_delivered_to_worker_undelivered_to_buyer(env):
    e = env
    w0, b0 = e.balance(e.w_tok), e.balance(e.b_tok)
    a = _delivered(e, "rule2-delivered", e.verifier)          # a silent verifier
    assert not e.settle(e.attacker, a)                       # inside the review window: no crank
    b = jid("rule2-undelivered")
    assert e.post(e.buyer, e.b_tok, b, PRICE, work=20) and e.claim(e.rival, b)
    c = jid("rule2-unclaimed")
    assert e.post(e.buyer, e.b_tok, c, PRICE, work=20)
    assert not e.settle(e.attacker, b) and not e.settle(e.attacker, c)
    e.warp(41)
    assert not e.deliver(e.rival, b)                         # the claim timed out
    for j in (a, b, c):
        assert e.settle(e.attacker, j)                       # anyone may crank
        assert e.job(j) is None and not e.settle(e.attacker, j)
    assert e.balance(e.w_tok) - w0 == PRICE * 95 // 100
    assert e.balance(e.b_tok) - b0 == -PRICE + sol.stake_for(PRICE)   # a paid; b, c refunded (+ b stake)


def test_rule_buyer_cannot_claim_own_job(env):
    e = env
    j = jid("rule3-self-claim")
    assert e.post(e.buyer, e.b_tok, j, PRICE)
    assert not e.claim(e.buyer, j)
    assert e.job(j).state == "open" and e.claim(e.worker, j)


def test_rule_claim_stake_returned_on_delivery_and_lost_on_timeout(env):
    e = env
    assert sol.stake_for(PRICE) == PRICE // 10 and sol.stake_for(U) == 100_000
    s_tok = e.stake_account(e.worker.pubkey())
    j = jid("rule4-stake-back")
    assert e.post(e.buyer, e.b_tok, j, PRICE)
    s0, v0 = e.balance(s_tok), e.balance(e.vault)
    assert e.claim(e.worker, j)
    assert e.balance(s_tok) == s0 - PRICE // 10 and e.balance(e.vault) == v0 + PRICE // 10
    assert e.job(j).stake == PRICE // 10
    assert e.deliver(e.worker, j) and e.balance(s_tok) == s0 and e.job(j).stake == 0
    broke, broke_tok = e.party()                             # no tokens: cannot stake, cannot claim
    k = jid("rule4-no-stake")
    assert e.post(e.buyer, e.b_tok, k, PRICE) and not e.claim(broke, k, broke_tok)
    t = jid("rule4-timeout")
    b0 = e.balance(e.b_tok)
    assert e.post(e.buyer, e.b_tok, t, PRICE, work=20) and e.claim(e.worker, t)
    e.warp(21)
    assert not e.deliver(e.worker, t)
    assert e.refund(e.buyer, t, e.b_tok)                     # the buyer's refund carries the stake
    assert e.balance(e.b_tok) - b0 == PRICE // 10 and e.balance(s_tok) == s0 - PRICE // 10


def test_rule_every_settle_closes_the_job_and_refunds_rent_to_the_buyer(env):
    e = env
    rent = e.svm.minimum_balance_for_rent_exemption(sol.JOB_LEN)
    paths = {
        "accept": lambda j: e.accept(e.buyer, j, e.w_tok),
        "release": lambda j: (e.warp(41), e.accept(e.attacker, j, e.w_tok, release=True))[1],
        "verify_release": lambda j: e.verify_release(e.verifier, j, e.w_tok),
        "verify_reject": lambda j: e.verify_reject(e.verifier, j, e.b_tok),
        "reject": lambda j: e.reject(e.buyer, j, e.b_tok),
        "settle": lambda j: (e.warp(41), e.settle(e.attacker, j))[1],
    }
    for name, settle in paths.items():
        j = _delivered(e, "rule5-" + name, None if name in ("accept", "reject", "release") else e.verifier)
        assert e.lamports(sol.job_pda(e.pid, j)) == rent
        l0 = e.lamports(e.buyer.pubkey())
        assert settle(j), name
        gain = e.lamports(e.buyer.pubkey()) - l0
        assert e.svm.get_account(sol.job_pda(e.pid, j)) is None or e.lamports(sol.job_pda(e.pid, j)) == 0, name
        assert rent - 5000 <= gain <= rent, (name, gain)    # the rent, less the fee when the buyer signs
    for name in ("refund", "settle-timeout"):
        j = jid("rule5-" + name)
        assert e.post(e.buyer, e.b_tok, j, PRICE, work=20) and e.claim(e.worker, j)
        e.warp(21)
        l0 = e.lamports(e.buyer.pubkey())
        assert e.refund(e.buyer, j, e.b_tok) if name == "refund" else e.settle(e.attacker, j)
        assert rent - 5000 <= e.lamports(e.buyer.pubkey()) - l0 <= rent
        assert e.job(j) is None
    j = jid("rule5-repost")                                  # a closed id is free again only for a fresh post
    assert e.post(e.buyer, e.b_tok, j, PRICE) and e.claim(e.worker, j) and e.deliver(e.worker, j)
    assert e.accept(e.buyer, j, e.w_tok) and not e.accept(e.buyer, j, e.w_tok)
    assert e.post(e.buyer, e.b_tok, j, PRICE) and e.job(j).state == "open"


# ---- conservation --------------------------------------------------------------------------------------------------

def test_1000_random_interleavings_conserve_every_token():
    e = Escrow()
    actors = [e.party(10 ** 9) for _ in range(4)]
    ids = [jid(f"fz-{k}") for k in range(60)]
    toks = [t for _, t in actors] + [e.fee_token, e.vault]
    total = lambda: sum(e.balance(t) for t in toks)  # noqa: E731
    t0 = total()
    rng = random.Random(31)
    for _ in range(1000):
        j = rng.choice(ids)
        who, tok = rng.choice(actors)
        a = rng.randrange(12)
        if a == 0:
            e.post(who, tok, j, rng.randint(1, 3) * 1_000_000, work=rng.choice([5, 60]), review=rng.choice([5, 60]),
                   verifier=rng.choice(actors)[0].pubkey() if rng.random() < 0.5 else None)
        elif a == 1:
            e.claim(who, j, tok)                         # staking from its own account
        elif a == 2:
            e.deliver(who, j, worker_token=tok)
        elif a in (3, 4):
            e.accept(who, j, tok, release=a == 4)
        elif a == 5:
            e.reject(who, j, tok)
        elif a == 6:
            e.refund(who, j, tok)
        elif a == 7:
            got = e.job(j)
            if got and got.worker:
                e.verify_release(who, j, e.accounts[bytes(got.worker)])
        elif a == 8:
            e.settle(who, j)
        elif a == 9:
            e.verify_reject(who, j, tok)
        else:
            e.warp(rng.choice([1, 10, 70]))
        assert total() == t0, "tokens created or destroyed"
    by_key = {bytes(k.pubkey()): (k, t) for k, t in actors}
    e.warp(1000)
    for j in ids:
        got = e.job(j)
        if got is None:
            continue
        if got.state == "delivered":
            k, t = by_key[bytes(got.worker)]
            assert e.settle(k, j, worker_token=t)
        elif got.state in ("open", "claimed"):
            k, t = by_key[bytes(got.buyer)]
            assert e.settle(k, j, buyer_token=t)
    assert all(e.job(j) is None for j in ids), "a job left unsettled"
    assert e.balance(e.vault) == 0, "funds stuck in escrow"


def test_fee_only_goes_down_and_only_by_the_admin():
    e = Escrow()
    buyer, btok = e.party(10 * U)
    worker, wtok = e.party()
    assert not e.lower_fee(100, admin=buyer)                 # admin only
    assert not e.lower_fee(501)                              # never up
    assert e.lower_fee(sol.FEE_BPS) and e.config()["fee_bps"] == 250
    assert not e.lower_fee(251)
    f0 = e.balance(e.fee_token)
    assert e.post(buyer, btok, jid("fee-25"), 4 * U) and e.claim(worker, jid("fee-25")) and e.deliver(worker, jid("fee-25"))
    assert e.accept(buyer, jid("fee-25"), wtok)
    assert e.balance(e.fee_token) - f0 == 100_000 == sol.fee_for(4 * U)  # 2.5% of 4 USDC
