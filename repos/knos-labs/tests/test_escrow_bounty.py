"""0.3.7 in the Solana runtime (LiteSVM + real SPL Token): the devnet faucet (caps, the hourly drip, refused in a
non-devnet build), the mint registry (post / claim / settle in two mints, a vault per mint), and bounties (a 0-amount
bounty still takes the stake; bounty + stake both reach the worker). Attacks: the wrong vault for a mint, an
unregistered mint, another mint's vault authority."""

from __future__ import annotations

import hashlib
import os
import struct
from pathlib import Path

import pytest

pytest.importorskip("solders.litesvm")

from solders.keypair import Keypair  # noqa: E402
from solders.system_program import CreateAccountParams, create_account  # noqa: E402

from _jobharness import Escrow  # noqa: E402

from knos.jobs import localsvm, sol  # noqa: E402

U = 1_000_000
CAP = 100 * U


def jid(tag: str) -> bytes:
    return hashlib.sha256(b"bounty-" + tag.encode()).digest()


def new_mint(e, authority) -> Keypair:
    m = Keypair()
    assert e.send([create_account(CreateAccountParams(
        from_pubkey=e.admin.pubkey(), to_pubkey=m.pubkey(), lamports=e.svm.minimum_balance_for_rent_exemption(82),
        space=82, owner=sol.TOKEN)),
        e._tix([20, 6] + list(bytes(authority)) + [0], [(m.pubkey(), False, True)])], e.admin, [e.admin, m])
    return m


@pytest.fixture(scope="module")
def env():
    e = Escrow(fee_bps=500)
    e.fm = new_mint(e, sol.faucet_pda(e.pid)).pubkey()                 # test USDC: the faucet is its mint authority
    assert e.send([sol.init_faucet_mint(e.pid, e.admin.pubkey(), e.fm, CAP)], e.admin, [e.admin])
    e.fvault = e.token_account(sol.vault_authority(e.pid, e.fm), e.fm)
    assert e.send([sol.add_mint(e.pid, e.admin.pubkey(), e.fm, e.fvault)], e.admin, [e.admin])
    e.ffee = e.token_account(e.admin.pubkey(), e.fm)                    # the admin's fee account in that mint
    e.buyer, e.b_tok = e.party(10 ** 12)
    e.worker, e.w_tok = e.party(10 ** 9)
    e.verifier, _ = e.party()
    e.fb = e.token_account(e.buyer.pubkey(), e.fm)
    e.fw = e.token_account(e.worker.pubkey(), e.fm)
    assert drip(e, e.buyer, e.fb) and drip(e, e.worker, e.fw)         # each xdist worker builds its own fixture
    return e


def drip(e, who: Keypair, tok, amount=CAP) -> bool:
    return e.send([sol.faucet(e.pid, who.pubkey(), e.fm, tok, amount)], who, [who])


# ---- the faucet ----------------------------------------------------------------------------------------------------

def test_faucet_caps_per_call_and_per_wallet_per_hour(env):
    e = env
    k = e.keypair()
    t = e.token_account(k.pubkey(), e.fm)
    assert not drip(e, k, t, CAP + 1), "over the per-call cap"
    assert drip(e, k, t, CAP) and e.balance(t) == CAP
    assert not drip(e, k, t, 1), "a second drip inside the hour"
    e.warp(3_599)
    assert not drip(e, k, t, 1)
    e.warp(2)
    assert drip(e, k, t, 5 * U) and e.balance(t) == CAP + 5 * U
    other = e.token_account(e.worker.pubkey(), e.fm)
    assert not drip(e, k, other, U), "a drip goes to the signer's own account only"
    usdc = e.token_account(k.pubkey())
    assert not e.send([sol.faucet(e.pid, k.pubkey(), e.mint.pubkey(), usdc, U)], k, [k]), "not the faucet's mint"


def test_faucet_setup_is_admin_only_and_once(env):
    e = env
    rogue = e.keypair()
    m2 = new_mint(e, sol.faucet_pda(e.pid)).pubkey()
    assert not e.send([sol.init_faucet_mint(e.pid, rogue.pubkey(), m2, CAP)], rogue, [rogue])
    assert not e.send([sol.init_faucet_mint(e.pid, e.admin.pubkey(), m2, CAP)], e.admin, [e.admin]), "exists"


def test_faucet_mint_authority_must_be_the_faucet():
    e = Escrow(fee_bps=500)
    m = new_mint(e, e.admin.pubkey()).pubkey()
    assert not e.send([sol.init_faucet_mint(e.pid, e.admin.pubkey(), m, CAP)], e.admin, [e.admin])


NODEVNET = os.environ.get("KNOS_ESCROW_NODEVNET_SO", "")


@pytest.mark.skipif(not (NODEVNET and Path(NODEVNET).exists()), reason="no --no-default-features build (CI builds one)")
def test_a_non_devnet_build_refuses_the_faucet(monkeypatch):
    monkeypatch.setattr(localsvm, "SO_CANDIDATES", [Path(NODEVNET)])
    e = Escrow(fee_bps=500)
    m = new_mint(e, sol.faucet_pda(e.pid)).pubkey()
    assert not e.send([sol.init_faucet_mint(e.pid, e.admin.pubkey(), m, CAP)], e.admin, [e.admin])
    k = e.keypair()
    t = e.token_account(k.pubkey(), m)
    assert not e.send([sol.faucet(e.pid, k.pubkey(), m, t, U)], k, [k])
    # the escrow itself still works in that build
    b, bt = e.party(10 ** 9)
    assert e.post(b, bt, jid("nodevnet"), 2 * U)


# ---- the mint registry ---------------------------------------------------------------------------------------------

def test_add_mint_is_admin_only_and_checks_the_vault(env):
    e = env
    rogue = e.keypair()
    m = new_mint(e, e.admin.pubkey()).pubkey()
    good = e.token_account(sol.vault_authority(e.pid, m), m)
    assert not e.send([sol.add_mint(e.pid, rogue.pubkey(), m, good)], rogue, [rogue]), "admin only"
    legacy_owned = e.token_account(sol.vault_authority(e.pid), m)
    assert not e.send([sol.add_mint(e.pid, e.admin.pubkey(), m, legacy_owned)], e.admin, [e.admin]), \
        "a registered mint's vault is owned by ['vault', mint]"
    assert not e.send([sol.add_mint(e.pid, e.admin.pubkey(), e.mint.pubkey(), e.vault)], e.admin, [e.admin]), \
        "the config mint is not re-registered"
    assert e.send([sol.add_mint(e.pid, e.admin.pubkey(), m, good)], e.admin, [e.admin])
    assert not e.send([sol.add_mint(e.pid, e.admin.pubkey(), m, good)], e.admin, [e.admin]), "once"


def _post_f(e, j, amount, bounty=False, verifier=None, vault=None, mint="fm", work=600, review=40):
    m = e.fm if mint == "fm" else mint
    build = sol.post_bounty if bounty else sol.post
    return e.send([build(e.pid, e.buyer.pubkey(), j, amount, work, review, hashlib.sha256(j).digest(), e.fb,
                         vault or e.fvault, verifier, m)], e.buyer, [e.buyer])


def test_two_mints_post_claim_deliver_accept(env):
    e = env
    # mint 1: the config mint, exactly as before
    j1 = jid("usdc")
    w1 = e.balance(e.w_tok)
    assert e.post(e.buyer, e.b_tok, j1, 5 * U) and e.claim(e.worker, j1, e.w_tok) and e.deliver(e.worker, j1, worker_token=e.w_tok)
    assert e.accept(e.buyer, j1, e.w_tok)
    assert e.balance(e.w_tok) - w1 == 5 * U * 95 // 100
    # mint 2: the registered faucet mint
    j2 = jid("test-usdc")
    v0, wf0, ff0 = e.balance(e.fvault), e.balance(e.fw), e.balance(e.ffee)
    assert _post_f(e, j2, 10 * U)
    job = e.job(j2)
    assert job.mint == e.fm and job.amount == 10 * U
    assert e.balance(e.fvault) - v0 == 10 * U
    assert e.send([sol.claim(e.pid, e.worker.pubkey(), j2, e.fw, e.fvault)], e.worker, [e.worker])
    assert e.balance(e.fw) == wf0 - sol.stake_for(10 * U)
    assert e.send([sol.deliver(e.pid, e.worker.pubkey(), j2, e.result_hash(j2), e.fw, e.fvault, mint=e.fm)],
                  e.worker, [e.worker])
    assert e.balance(e.fw) == wf0
    assert e.send([sol.accept(e.pid, e.buyer.pubkey(), j2, e.fvault, e.fw, e.ffee) if False else
                   sol.settle(e.pid, e.buyer.pubkey(), j2, e.fvault, e.fw, e.ffee, mint=e.fm)], e.buyer, [e.buyer])
    assert e.balance(e.fw) - wf0 == 10 * U * 95 // 100
    assert e.balance(e.ffee) - ff0 == 10 * U * 5 // 100
    assert e.balance(e.fvault) == v0 and e.job(j2) is None


def test_registered_mint_refund_and_deadline_settle(env):
    e = env
    b0 = e.balance(e.fb)
    j = jid("refund")
    assert _post_f(e, j, 3 * U, work=20)
    e.warp(21)
    assert e.send([sol.refund(e.pid, e.buyer.pubkey(), j, e.fvault, e.fb, mint=e.fm)], e.buyer, [e.buyer])
    assert e.balance(e.fb) == b0
    j = jid("crank")
    wf0 = e.balance(e.fw)
    assert _post_f(e, j, 4 * U, review=30)
    assert e.send([sol.claim(e.pid, e.worker.pubkey(), j, e.fw, e.fvault)], e.worker, [e.worker])
    assert e.send([sol.deliver(e.pid, e.worker.pubkey(), j, e.result_hash(j), e.fw, e.fvault, mint=e.fm)],
                  e.worker, [e.worker])
    e.warp(31)
    anyone = e.keypair()
    assert e.send([sol.crank(e.pid, anyone.pubkey(), j, e.fvault, e.fw, e.ffee, e.fb, e.buyer.pubkey(), mint=e.fm)],
                  anyone, [anyone])
    assert e.balance(e.fw) - wf0 == 4 * U * 95 // 100


def test_attacks_wrong_vault_unregistered_mint_and_cross_mint(env):
    e = env
    v_usdc, v_f = e.balance(e.vault), e.balance(e.fvault)
    # posting in the registered mint into the config mint's vault, or without the registry
    assert not _post_f(e, jid("a1"), 2 * U, vault=e.vault)
    assert not e.send([sol.post(e.pid, e.buyer.pubkey(), jid("a2"), 2 * U, 600, 40, bytes(32), e.fb, e.fvault)],
                      e.buyer, [e.buyer])
    # a vault for the mint that is not the registered one (owned by ['vault', mint] but another account)
    stray = e.token_account(sol.vault_authority(e.pid, e.fm), e.fm)
    assert not _post_f(e, jid("a3"), 2 * U, vault=stray)
    # an unregistered mint
    m = new_mint(e, e.admin.pubkey())
    mv = e.token_account(sol.vault_authority(e.pid, m.pubkey()), m.pubkey())
    bt = e.token_account(e.buyer.pubkey(), m.pubkey())
    e.send([e._tix([7] + list(struct.pack("<Q", 50 * U)), [(m.pubkey(), False, True), (bt, False, True),
                                                           (e.admin.pubkey(), True, False)])], e.admin, [e.admin])
    assert not e.send([sol.post(e.pid, e.buyer.pubkey(), jid("a4"), 2 * U, 600, 40, bytes(32), bt, mv,
                                mint=m.pubkey())], e.buyer, [e.buyer])
    # cross-mint payouts: a test-USDC job paid from the USDC vault, and a USDC job from the test-USDC vault
    jf = jid("cross-f")
    assert _post_f(e, jf, 2 * U)
    assert not e.send([sol.claim(e.pid, e.worker.pubkey(), jf, e.w_tok, e.vault)], e.worker, [e.worker])
    assert e.send([sol.claim(e.pid, e.worker.pubkey(), jf, e.fw, e.fvault)], e.worker, [e.worker])
    assert not e.send([sol.deliver(e.pid, e.worker.pubkey(), jf, e.result_hash(jf), e.w_tok, e.vault)],
                      e.worker, [e.worker]), "the legacy vault authority for a registered-mint job"
    assert e.send([sol.deliver(e.pid, e.worker.pubkey(), jf, e.result_hash(jf), e.fw, e.fvault, mint=e.fm)],
                  e.worker, [e.worker])
    assert not e.send([sol.settle(e.pid, e.buyer.pubkey(), jf, e.vault, e.w_tok, e.fee_token)], e.buyer, [e.buyer])
    assert not e.send([sol.settle(e.pid, e.buyer.pubkey(), jf, e.fvault, e.fw, e.fee_token, mint=e.fm)],
                      e.buyer, [e.buyer]), "the USDC fee account for a test-USDC job"
    ju = jid("cross-u")
    assert e.post(e.buyer, e.b_tok, ju, 2 * U) and e.claim(e.worker, ju, e.w_tok)
    assert e.deliver(e.worker, ju, worker_token=e.w_tok)
    assert not e.send([sol.settle(e.pid, e.buyer.pubkey(), ju, e.fvault, e.fw, e.ffee, mint=e.fm)],
                      e.buyer, [e.buyer]), "a USDC job paid from the test-USDC vault"
    assert e.balance(e.vault) - v_usdc == 2 * U and e.balance(e.fvault) - v_f == 2 * U


# ---- bounties ------------------------------------------------------------------------------------------------------

def test_zero_amount_bounty_still_takes_the_stake(env):
    e = env
    assert not _post_f(e, jid("zero-post"), 0), "a plain Post keeps the minimum"
    j = jid("zero")
    assert _post_f(e, j, 0, bounty=True, verifier=e.verifier.pubkey())
    assert e.job(j).amount == 0 and e.job(j).state == "open"
    w0 = e.balance(e.fw)
    assert e.send([sol.claim(e.pid, e.worker.pubkey(), j, e.fw, e.fvault)], e.worker, [e.worker])
    assert e.job(j).stake == sol.MIN_STAKE_UNITS and e.balance(e.fw) == w0 - sol.MIN_STAKE_UNITS
    assert e.send([sol.deliver(e.pid, e.worker.pubkey(), j, e.result_hash(j), e.fw, e.fvault, mint=e.fm)],
                  e.worker, [e.worker])
    assert e.send([sol.verify_release(e.pid, e.verifier.pubkey(), j, e.result_hash(j), bytes(32), e.fvault, e.fw,
                                      e.ffee, e.buyer.pubkey(), mint=e.fm)], e.verifier, [e.verifier])
    assert e.balance(e.fw) == w0 and e.job(j) is None


def test_funded_bounty_pays_bounty_and_stake_to_the_worker(env):
    e = env
    j = jid("funded")
    brief = sol.bounty_brief("drexthealpha/Knos", 42)
    assert e.send([sol.post_bounty(e.pid, e.buyer.pubkey(), j, 20 * U, 600, 40, brief, e.fb, e.fvault,
                                   e.verifier.pubkey(), e.fm)], e.buyer, [e.buyer])
    assert e.job(j).brief == brief
    w0 = e.balance(e.fw)
    assert e.send([sol.claim(e.pid, e.worker.pubkey(), j, e.fw, e.fvault)], e.worker, [e.worker])
    assert not e.send([sol.verify_release(e.pid, e.verifier.pubkey(), j, e.result_hash(j), bytes(32), e.fvault, e.fw,
                                          e.ffee, e.buyer.pubkey(), mint=e.fm)], e.verifier, [e.verifier])
    assert e.send([sol.deliver(e.pid, e.worker.pubkey(), j, e.result_hash(j), e.fw, e.fvault, mint=e.fm)],
                  e.worker, [e.worker])
    assert e.send([sol.verify_release(e.pid, e.verifier.pubkey(), j, e.result_hash(j), bytes(32), e.fvault, e.fw,
                                      e.ffee, e.buyer.pubkey(), mint=e.fm)], e.verifier, [e.verifier])
    assert e.balance(e.fw) - w0 == 20 * U * 95 // 100, "the bounty net of the fee, and the stake back"
