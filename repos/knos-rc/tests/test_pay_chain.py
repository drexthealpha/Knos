"""knos-pay in the Solana runtime (LiteSVM), with knos-oidc beside it: a bounty for one issue is paid to the pull
request author's GitHub account only on a GitHub-signed token from the funder's pinned workflow, and leaves the vault
only on that user's own claim token. No admin instruction exists; every wrong token is refused; a random walk over
every instruction keeps each vault equal to what is owed."""
from __future__ import annotations

import os
import random
import re

import pytest

pytest.importorskip("solders.litesvm")

from solders.keypair import Keypair  # noqa: E402

from _settle import Chain, modulus, signing_key  # noqa: E402

from knos.settle import oidc, pay  # noqa: E402

REPO, OWNER, AUTHOR, MAINTAINER, OTHER = 987654321, 424242, 1234567, 555000, 7654321
WF_REPO, WF_SHA, HEAD = "drexthealpha/Knos", "c" * 40, "a" * 40
USDC = 1_000_000
FUZZ_N = int(os.environ.get("KNOS_FUZZ_N", "600"))   # read at import: conftest clears KNOS_* per test
FUZZ_SEED = int(os.environ.get("KNOS_FUZZ_SEED", "310"))   # the suite walks one fixed path; program.yml gives each walk its own
_ISSUE = [100]


def code(c: Chain) -> int | None:
    m = re.search(r"Custom\((\d+)\)", c.err or "")
    return int(m.group(1)) if m else None


@pytest.fixture(scope="module")
def chain():
    c = Chain()
    assert c.register(oidc.GITHUB, modulus(signing_key())), c.err
    assert c.register(oidc.GITLAB, modulus(signing_key(4096))), c.err
    c.usdc = c.new_mint()
    c.funder = c.fund()
    c.funder_tok = c.token_account(c.funder.pubkey(), c.usdc)
    c.mint_to(c.usdc, c.funder_tok, 10_000 * USDC)
    c.fee_tok = c.token_account(pay.FEE_OWNER, c.usdc)
    assert c.send([pay.init_faucet_ix(c.payer.pubkey())]), c.err
    c.test_usdc = pay.faucet_mint()
    c.token_account(pay.FEE_OWNER, c.test_usdc)
    return c


def issue() -> int:
    _ISSUE[0] += 1
    return _ISSUE[0]


def fund(c: Chain, amount: int = 5 * USDC, n: int | None = None, **kw) -> int:
    n = n or issue()
    assert c.send([pay.fund_ix(c.funder.pubkey(), c.funder_tok, c.usdc, REPO, n, amount, WF_REPO, WF_SHA, **kw)], c.funder), c.err
    return n


def pay_token(c: Chain, n: int, author: int = AUTHOR, checks: bytes = pay.NO_CHECKS, mode: int = pay.MERGE, repo: int = REPO, **over):
    return c.gh(pay.pay_audience(repo, n, author, HEAD, checks, mode), **{"repository_id": str(REPO), **over})


def jobk(c: Chain, n: int, own: bool = False):
    """The job for issue n: the test funder's wallet-funded one, or the repository's own token-funded one."""
    return pay.job_pda(REPO, n, None if own else c.funder.pubkey())


def do_pay(c: Chain, n: int, tok, author: int = AUTHOR, mint=None, rent_to=None, tag=None) -> bool:
    own = mint is not None and mint != c.usdc
    return c.send([pay.pay_ix(c.payer.pubkey(), tok, jobk(c, n, own), author, mint or c.usdc, rent_to or c.funder.pubkey())], tag=tag)


def claim(c: Chain, user: int, mint, address) -> bool:
    c.token_account(address, mint)
    tok = c.gh(pay.claim_audience(address), file="claim.yml", wf_repo="mona/dotfiles", event_name="workflow_dispatch",
               actor_id=str(user), repository_owner_id=str(user), repository_id="31337")
    return c.send([pay.claim_ix(c.payer.pubkey(), tok, user, mint, address)], tag="claim")


def test_a_merged_pull_request_is_paid_to_its_authors_github_account_and_claimed_without_a_wallet_at_work_time(chain):
    c = chain
    vault0, fee0, funder0 = c.balance(pay.vault_pda(c.usdc)), c.balance(c.fee_tok), c.svm.get_balance(c.funder.pubkey())
    n = fund(c, 5 * USDC)
    j = pay.read_job(c.data(jobk(c, n)))
    assert (j.state, j.mode, j.amount, j.token_funded, j.wf_sha) == ("open", pay.MERGE, 5 * USDC, False, WF_SHA)
    assert c.balance(pay.vault_pda(c.usdc)) == vault0 + 5 * USDC
    assert do_pay(c, n, pay_token(c, n), tag="pay"), c.err
    # 2.5% fee; the rest waits under the author's GitHub id; the job is gone and its rent is back with the funder
    assert pay.read_due(c.data(pay.due_pda(AUTHOR, c.usdc))) == 4_875_000
    assert c.balance(c.fee_tok) == fee0 + 125_000
    assert c.data(jobk(c, n)) is None
    assert funder0 - c.svm.get_balance(c.funder.pubkey()) < 3_000_000   # the funder paid fees and the vault's rent, not the job's
    r = pay.read_rep(c.data(pay.rep_pda(AUTHOR)))
    assert (r.paid_jobs, r.total_paid, r.repositories) == (1, 4_875_000, 1)
    # the author never had a wallet until now: they pick any address and claim with a token from their own repository
    wallet = Keypair().pubkey()
    assert claim(c, AUTHOR, c.usdc, wallet), c.err
    assert c.balance(pay.ata(wallet, c.usdc)) == 4_875_000
    assert c.data(pay.due_pda(AUTHOR, c.usdc)) is None
    assert c.balance(pay.vault_pda(c.usdc)) == vault0
    print("\nCU:", {k: v[-1] for k, v in c.cu.items() if k in ("pay", "claim")})


def test_a_comment_funds_a_devnet_bounty_with_test_usdc_and_no_wallet(chain):
    c = chain
    n = issue()
    tok = c.gh(pay.fund_audience(n, 5 * USDC), file="fund.yml", event_name="issue_comment", repository_id=str(REPO),
               repository_owner_id=str(OWNER), actor_id=str(MAINTAINER))
    assert c.send([pay.fund_with_token_ix(c.payer.pubkey(), tok, REPO, n)], tag="fund_with_token"), c.err
    j = pay.read_job(c.data(jobk(c, n, True)))
    assert (j.state, j.amount, j.token_funded, j.funder_id, j.mint) == ("open", 5 * USDC, True, OWNER, c.test_usdc)
    assert j.wf_repo_hash == pay.wf_repo_hash(WF_REPO) and j.wf_sha == WF_SHA
    # a second funding of the same repository inside a minute is refused; so is the same issue twice
    n2 = issue()
    tok2 = c.gh(pay.fund_audience(n2, 5 * USDC), file="fund.yml", repository_id=str(REPO), repository_owner_id=str(OWNER))
    assert not c.send([pay.fund_with_token_ix(c.payer.pubkey(), tok2, REPO, n2)]) and code(c) == 90
    c.warp(61)
    tok3 = c.gh(pay.fund_audience(n, 5 * USDC), file="fund.yml", repository_id=str(REPO), repository_owner_id=str(OWNER))
    assert not c.send([pay.fund_with_token_ix(c.payer.pubkey(), tok3, REPO, n)]) and code(c) == 82
    # more than the faucet's cap, and a token from prove.yml, are refused
    c.warp(61)
    n3 = issue()
    big = c.gh(pay.fund_audience(n3, 101 * USDC), file="fund.yml", repository_id=str(REPO), repository_owner_id=str(OWNER))
    assert not c.send([pay.fund_with_token_ix(c.payer.pubkey(), big, REPO, n3)]) and code(c) == 81
    wrong = c.gh(pay.fund_audience(n3, 5 * USDC), file="prove.yml", repository_id=str(REPO), repository_owner_id=str(OWNER))
    assert not c.send([pay.fund_with_token_ix(c.payer.pubkey(), wrong, REPO, n3)]) and code(c) == 86
    # paid like any job, in the test mint
    assert do_pay(c, n, pay_token(c, n), mint=c.test_usdc, rent_to=c.payer.pubkey()), c.err
    # the fund token was posted in public and is still inside its hour: it cannot fund the issue a second time
    c.warp(61)
    assert not c.send([pay.fund_with_token_ix(c.payer.pubkey(), tok, REPO, n)]) and code(c) == 90
    assert pay.read_due(c.data(pay.due_pda(AUTHOR, c.test_usdc))) == 4_875_000
    wallet = Keypair().pubkey()
    assert claim(c, AUTHOR, c.test_usdc, wallet) and c.balance(pay.ata(wallet, c.test_usdc)) == 4_875_000


def test_every_wrong_proof_is_refused(chain):
    c = chain
    checks = bytes(range(32))
    n = fund(c, 5 * USDC, mode=pay.TESTS, checks=checks, review_s=0)
    good = dict(checks=checks, mode=pay.TESTS)
    other = Keypair()
    c.svm.airdrop(other.pubkey(), 10 ** 9)
    gl = signing_key(4096)
    cases = {
        "a fund.yml token": (lambda: pay_token(c, n, file="fund.yml", **good), 86),
        "prove.yml of another repository": (lambda: pay_token(c, n, wf_repo="evil/Knos", **good), 86),
        "prove.yml at another commit": (lambda: pay_token(c, n, wf_sha="d" * 40, **good), 86),
        "a self-hosted runner": (lambda: pay_token(c, n, runner_environment="self-hosted", **good), 85),
        "a token of another repository": (lambda: pay_token(c, n, repository_id="111", **good), 85),
        "an audience for another repository": (lambda: pay_token(c, n, repo=111, **good), 87),
        "an audience for another issue": (lambda: c.gh(pay.pay_audience(REPO, n + 999, AUTHOR, HEAD, checks, pay.TESTS), repository_id=str(REPO)), 87),
        "other acceptance checks": (lambda: pay_token(c, n, checks=bytes(32), mode=pay.TESTS), 87),
        "merge mode on a tests job": (lambda: pay_token(c, n, checks=checks, mode=pay.MERGE), 87),
        "author 0": (lambda: pay_token(c, n, author=0, **good), 87),
        "a claim audience": (lambda: c.gh(pay.claim_audience(other.pubkey()), repository_id=str(REPO)), 87),
        "issued before the funding": (lambda: pay_token(c, n, iat=c.now() - 3600, **good), 83),
    }
    for what, (make, want) in cases.items():
        assert not do_pay(c, n, make()), f"{what}: accepted"
        assert code(c) == want, f"{what}: {c.err}, wanted {want}"
    # a GitLab-signed token (verified by knos-oidc, but not GitHub's)
    from _settle import sign_jwt
    tok = c.verify(sign_jwt(gl, {"iss": oidc.ISSUERS[oidc.GITLAB], "exp": c.now() + 300, "aud": pay.pay_audience(REPO, n, AUTHOR, HEAD, checks, pay.TESTS)}), oidc.GITLAB, modulus(gl))
    assert not do_pay(c, n, tok) and code(c) == 84
    # a token account that is not verified yet; an account that is not knos-oidc's at all, with the same bytes
    from _settle import github_claims
    jwt = sign_jwt(signing_key(), github_claims(aud=pay.pay_audience(REPO, n, AUTHOR, HEAD, checks, pay.TESTS), repository_id=str(REPO), iat=c.now(), exp=c.now() + 300, jti="unverified"))
    tid = c.write(jwt)
    assert not do_pay(c, n, oidc.token_pda(c.payer.pubkey(), tid)) and code(c) == 84
    real = c.svm.get_account(pay_token(c, n, **good))
    from solders.account import Account
    fake = Keypair().pubkey()
    c.svm.set_account(fake, Account(lamports=real.lamports, data=bytes(real.data), owner=pay.PAY_ID, executable=False))
    assert not do_pay(c, n, fake) and code(c) == 84
    # an expired token
    tok = pay_token(c, n, **good)
    c.warp(300 + oidc.LATE)
    assert not do_pay(c, n, tok) and code(c) == 84
    # the wrong author's account, a fee account that is not Knos's, and rent sent to someone else
    tok = pay_token(c, n, **good)
    assert not c.send([pay.pay_ix(c.payer.pubkey(), tok, jobk(c, n), AUTHOR + 1, c.usdc, c.funder.pubkey())]) and code(c) == 88
    ix = pay.pay_ix(c.payer.pubkey(), tok, jobk(c, n), AUTHOR, c.usdc, c.funder.pubkey())
    from solders.instruction import AccountMeta, Instruction
    acc = list(ix.accounts); acc[6] = AccountMeta(c.funder_tok, False, True)
    assert not c.send([Instruction(ix.program_id, ix.data, acc)]) and code(c) == 88
    assert not c.send([pay.pay_ix(c.payer.pubkey(), tok, jobk(c, n), AUTHOR, c.usdc, other.pubkey())]) and code(c) == 80
    # and the real proof pays
    assert do_pay(c, n, tok), c.err
    # the same token cannot pay twice: the job is gone
    assert not do_pay(c, n, tok) and code(c) == 82


def test_tests_mode_waits_out_the_review_window_and_the_funder_can_veto(chain):
    c = chain
    checks = b"\x07" * 32
    due0 = pay.read_due(c.data(pay.due_pda(AUTHOR, c.usdc)))
    n = fund(c, 10 * USDC, mode=pay.TESTS, checks=checks, review_s=3600)
    first = pay_token(c, n, checks=checks, mode=pay.TESTS)
    assert do_pay(c, n, first), c.err
    j = pay.read_job(c.data(jobk(c, n)))
    assert (j.state, j.author_id, j.pay_after) == ("proven", AUTHOR, c.now() + 3600)
    settle = lambda: c.send([pay.settle_ix(c.payer.pubkey(), jobk(c, n), AUTHOR, c.usdc, c.funder.pubkey())])  # noqa: E731
    assert not settle() and code(c) == 83                       # too early
    stranger = c.fund()
    assert not c.send([pay.veto_ix(stranger.pubkey(), jobk(c, n))], stranger) and code(c) == 84   # not the funder, no token
    assert c.send([pay.veto_ix(c.funder.pubkey(), jobk(c, n))], c.funder), c.err
    j = pay.read_job(c.data(jobk(c, n)))
    assert (j.state, j.vetoes, j.author_id) == ("open", 1, 0)
    assert not do_pay(c, n, first) and code(c) == 83           # the vetoed proof cannot be replayed
    c.warp(5)
    assert do_pay(c, n, pay_token(c, n, checks=checks, mode=pay.TESTS)), c.err   # a new run proves it again
    c.warp(3599)
    assert not settle() and code(c) == 83
    c.warp(1)
    assert not c.send([pay.veto_ix(c.funder.pubkey(), jobk(c, n))], c.funder) and code(c) == 83   # the window is over
    assert settle(), c.err
    assert pay.read_due(c.data(pay.due_pda(AUTHOR, c.usdc))) == due0 + 9_750_000
    # a token-funded job is vetoed by a maintainer's comment: a veto token from the pinned fund.yml
    c.warp(61)
    n = issue()
    ft = c.gh(pay.fund_audience(n, 5 * USDC, pay.TESTS, checks, 14 * 86_400, 600), file="fund.yml", repository_id=str(REPO), repository_owner_id=str(OWNER))
    assert c.send([pay.fund_with_token_ix(c.payer.pubkey(), ft, REPO, n)]), c.err
    assert do_pay(c, n, pay_token(c, n, checks=checks, mode=pay.TESTS), mint=c.test_usdc, rent_to=c.payer.pubkey()), c.err
    wrong = c.gh(pay.veto_audience(REPO, n), file="prove.yml", repository_id=str(REPO))
    assert not c.send([pay.veto_ix(c.payer.pubkey(), jobk(c, n, True), wrong)]) and code(c) == 86
    elsewhere = c.gh(pay.veto_audience(REPO, n), file="fund.yml", repository_id="111")
    assert not c.send([pay.veto_ix(c.payer.pubkey(), jobk(c, n, True), elsewhere)]) and code(c) == 87
    veto = c.gh(pay.veto_audience(REPO, n), file="fund.yml", repository_id=str(REPO), event_name="issue_comment")
    assert c.send([pay.veto_ix(c.payer.pubkey(), jobk(c, n, True), veto)]), c.err
    assert pay.read_job(c.data(jobk(c, n, True))).state == "open"
    # the veto was posted in public too: a stranger cannot replay it against the next proof
    c.warp(120)
    assert do_pay(c, n, pay_token(c, n, checks=checks, mode=pay.TESTS), mint=c.test_usdc, rent_to=c.payer.pubkey()), c.err
    assert not c.send([pay.veto_ix(c.payer.pubkey(), jobk(c, n, True), veto)]) and code(c) == 83


def test_a_merge_is_paid_after_its_window_so_a_wrong_claim_can_be_taken_back(chain):
    """The pull request's own description names the issue it closes. So a merge-mode bounty funded with a review
    window is held for that long after the merge: a maintainer can veto a pull request that named the issue only to
    take its bounty, and the bounty is open again for the pull request that really fixes it."""
    c = chain
    due0, other0 = pay.read_due(c.data(pay.due_pda(AUTHOR, c.usdc))), pay.read_due(c.data(pay.due_pda(OTHER, c.usdc)))
    n = fund(c, 20 * USDC, review_s=3600)                                    # merge mode, one hour
    assert do_pay(c, n, pay_token(c, n, author=OTHER), author=OTHER), c.err   # an unrelated PR said "Fixes #n" and was merged
    j = pay.read_job(c.data(jobk(c, n)))
    assert (j.state, j.mode, j.author_id, j.pay_after) == ("proven", pay.MERGE, OTHER, c.now() + 3600)
    assert pay.read_due(c.data(pay.due_pda(OTHER, c.usdc))) == other0        # nothing has moved
    c.warp(600)
    veto = c.gh(pay.veto_audience(REPO, n), file="fund.yml", repository_id=str(REPO), event_name="issue_comment")
    assert c.send([pay.veto_ix(c.payer.pubkey(), jobk(c, n), veto)]), c.err   # a maintainer's /knos veto, on a sponsor's job too
    assert pay.read_job(c.data(jobk(c, n))).state == "open"
    c.warp(60)
    assert do_pay(c, n, pay_token(c, n)), c.err                               # the real fix is merged
    c.warp(3600)
    assert c.send([pay.settle_ix(c.payer.pubkey(), jobk(c, n), AUTHOR, c.usdc, c.funder.pubkey())]), c.err
    assert pay.read_due(c.data(pay.due_pda(AUTHOR, c.usdc))) == due0 + 19_500_000
    assert pay.read_due(c.data(pay.due_pda(OTHER, c.usdc))) == other0


def test_with_no_proof_by_the_deadline_the_money_goes_back(chain):
    c = chain
    before = c.balance(c.funder_tok)
    n = fund(c, 7 * USDC, work_s=600)
    refund = lambda dest, rent: c.send([pay.refund_ix(c.payer.pubkey(), jobk(c, n), c.usdc, dest, rent)])  # noqa: E731
    assert not refund(c.funder_tok, c.funder.pubkey()) and code(c) == 83     # not yet
    c.warp(601)
    assert not do_pay(c, n, pay_token(c, n)) and code(c) == 83               # too late to prove
    thief = c.token_account(Keypair().pubkey(), c.usdc)
    assert not refund(thief, c.funder.pubkey()) and code(c) == 88
    assert refund(c.funder_tok, c.funder.pubkey()), c.err
    assert c.balance(c.funder_tok) == before and c.data(jobk(c, n)) is None
    # a token-funded job refunds to the funding repository owner's GitHub id, who can claim it
    n2 = issue()
    ft = c.gh(pay.fund_audience(n2, 3 * USDC, pay.MERGE, pay.NO_CHECKS, 600, 0), file="fund.yml", repository_id=str(REPO), repository_owner_id=str(OWNER))
    assert c.send([pay.fund_with_token_ix(c.payer.pubkey(), ft, REPO, n2)]), c.err
    c.warp(601)
    assert c.send([pay.refund_ix(c.payer.pubkey(), jobk(c, n2, True), c.test_usdc, pay.due_pda(OWNER, c.test_usdc), c.payer.pubkey())]), c.err
    assert pay.read_due(c.data(pay.due_pda(OWNER, c.test_usdc))) == 3 * USDC
    wallet = Keypair().pubkey()
    assert claim(c, OWNER, c.test_usdc, wallet) and c.balance(pay.ata(wallet, c.test_usdc)) == 3 * USDC


def test_nobody_can_claim_another_accounts_money(chain):
    c = chain
    n = fund(c, 5 * USDC)
    victim = 7_000_001
    assert do_pay(c, n, pay_token(c, n, author=victim), author=victim), c.err
    thief = Keypair().pubkey()
    c.token_account(thief, c.usdc)
    attempt = lambda **claims: c.send([pay.claim_ix(c.payer.pubkey(), c.gh(pay.claim_audience(thief), file="x.yml", wf_repo="evil/repo", **claims), victim, c.usdc, thief)])  # noqa: E731
    # the victim opens a pull request or comments on the thief's repository: a workflow there runs as the victim
    assert not attempt(event_name="pull_request_target", actor_id=str(victim), repository_owner_id="666") and code(c) == 85
    assert not attempt(event_name="issue_comment", actor_id=str(victim), repository_owner_id="666") and code(c) == 85
    # a workflow_dispatch the thief runs in their own repository is the thief's token, not the victim's
    assert not attempt(event_name="workflow_dispatch", actor_id="666", repository_owner_id="666") and code(c) == 88
    # the victim runs workflow_dispatch in a repository someone else owns (an organisation, or the thief's)
    assert not attempt(event_name="workflow_dispatch", actor_id=str(victim), repository_owner_id="666") and code(c) == 85
    # a self-hosted runner, and a pay token used as a claim
    assert not attempt(event_name="workflow_dispatch", actor_id=str(victim), repository_owner_id=str(victim), runner_environment="self-hosted") and code(c) == 85
    tok = c.gh(pay.pay_audience(REPO, n, victim, HEAD), event_name="workflow_dispatch", actor_id=str(victim), repository_owner_id=str(victim))
    assert not c.send([pay.claim_ix(c.payer.pubkey(), tok, victim, c.usdc, thief)]) and code(c) == 87
    # the victim's real claim names their own address; a relayer cannot redirect it
    mine = Keypair().pubkey()
    c.token_account(mine, c.usdc)
    tok = c.gh(pay.claim_audience(mine), file="claim.yml", wf_repo="v/v", event_name="workflow_dispatch", actor_id=str(victim), repository_owner_id=str(victim))
    assert not c.send([pay.claim_ix(c.payer.pubkey(), tok, victim, c.usdc, thief)]) and code(c) == 88
    assert c.send([pay.claim_ix(c.payer.pubkey(), tok, victim, c.usdc, mine)]), c.err
    assert c.balance(pay.ata(mine, c.usdc)) == 4_875_000 and c.balance(pay.ata(thief, c.usdc)) == 0
    # nothing is due any more
    assert not c.send([pay.claim_ix(c.payer.pubkey(), tok, victim, c.usdc, mine)]) and code(c) == 91


def test_nobody_can_take_an_issues_address_and_anyone_can_add_a_bounty(chain):
    c = chain
    c.warp(61)
    n = issue()
    # a stranger funds issue n first, pinning their own workflow: it does not block the maintainers' own bounty
    squatter = c.fund()
    stok = c.token_account(squatter.pubkey(), c.usdc)
    c.mint_to(c.usdc, stok, 10 * USDC)
    assert c.send([pay.fund_ix(squatter.pubkey(), stok, c.usdc, REPO, n, 0, "evil/workflows", "f" * 40, work_s=90 * 86_400)], squatter), c.err
    ft = c.gh(pay.fund_audience(n, 5 * USDC), file="fund.yml", repository_id=str(REPO), repository_owner_id=str(OWNER))
    assert c.send([pay.fund_with_token_ix(c.payer.pubkey(), ft, REPO, n)]), c.err
    # a sponsor adds 20 USDC to the same issue, pinning the same workflow; one proof pays both jobs
    sponsor = c.fund()
    ptok = c.token_account(sponsor.pubkey(), c.usdc)
    c.mint_to(c.usdc, ptok, 20 * USDC)
    assert c.send([pay.fund_ix(sponsor.pubkey(), ptok, c.usdc, REPO, n, 20 * USDC, WF_REPO, WF_SHA)], sponsor), c.err
    who = 8_800_001
    tok = pay_token(c, n, author=who)
    assert c.send([pay.pay_ix(c.payer.pubkey(), tok, pay.job_pda(REPO, n), who, c.test_usdc, c.payer.pubkey())]), c.err
    assert c.send([pay.pay_ix(c.payer.pubkey(), tok, pay.job_pda(REPO, n, sponsor.pubkey()), who, c.usdc, sponsor.pubkey())]), c.err
    assert pay.read_due(c.data(pay.due_pda(who, c.test_usdc))) == 4_875_000
    assert pay.read_due(c.data(pay.due_pda(who, c.usdc))) == 19_500_000
    # the squatter's job pins another workflow, so the proof does not pay it
    assert not c.send([pay.pay_ix(c.payer.pubkey(), tok, pay.job_pda(REPO, n, squatter.pubkey()), who, c.usdc, squatter.pubkey())]) and code(c) == 86
    # an account posing as a job at the wrong address is refused
    from solders.account import Account
    real = c.svm.get_account(pay.job_pda(REPO, n, squatter.pubkey()))
    fake = Keypair().pubkey()
    c.svm.set_account(fake, Account(lamports=real.lamports, data=bytes(real.data), owner=pay.PAY_ID, executable=False))
    assert not c.send([pay.pay_ix(c.payer.pubkey(), tok, fake, who, c.usdc, squatter.pubkey())]) and code(c) == 82


def test_terms_are_bounded_and_the_real_money_build_has_no_faucet(chain):
    c = chain
    f = lambda **kw: c.send([pay.fund_ix(c.funder.pubkey(), c.funder_tok, c.usdc, REPO, issue(), kw.pop("amount", 5 * USDC), WF_REPO, WF_SHA, **kw)], c.funder)  # noqa: E731
    for kw in (dict(amount=999_999), dict(amount=500 * USDC + 1), dict(mode=2), dict(work_s=59), dict(work_s=91 * 86_400), dict(review_s=8 * 86_400)):
        assert not f(**kw) and code(c) == 81, kw
    n = fund(c, 0)                                      # a proof with no money is allowed
    assert do_pay(c, n, pay_token(c, n)), c.err
    n = fund(c, 5 * USDC)
    assert not c.send([pay.fund_ix(c.funder.pubkey(), c.funder_tok, c.usdc, REPO, n, 5 * USDC, WF_REPO, WF_SHA)], c.funder) and code(c) == 82
    real = Chain("knos_pay_nodevnet.so")
    assert real.register(oidc.GITHUB, modulus(signing_key()))
    assert not real.send([pay.init_faucet_ix(real.payer.pubkey())]) and code(real) == 89
    tok = real.gh(pay.fund_audience(1, 5 * USDC), file="fund.yml")
    assert not real.send([pay.fund_with_token_ix(real.payer.pubkey(), tok, REPO, 1)]) and code(real) == 89


def test_a_random_walk_never_loses_or_creates_money():
    """Random steps (600 by default; program.yml runs four walks of 2,500, each from its own KNOS_FUZZ_SEED) over every
    instruction, valid and invalid. After each step, for each mint: vault balance == open and proven job amounts +
    everything due. At the end: funded == claimed + fees + refunded + vault. A failure names its seed and step, so
    KNOS_FUZZ_SEED=<seed> KNOS_FUZZ_N=<n> walks the same path again."""
    c = Chain()
    assert c.register(oidc.GITHUB, modulus(signing_key()))
    rng = random.Random(FUZZ_SEED)
    usdc = c.new_mint()
    funder = c.fund(10_000)
    ftok = c.token_account(funder.pubkey(), usdc)
    c.mint_to(usdc, ftok, 10 ** 12)
    c.token_account(pay.FEE_OWNER, usdc)
    jobs: dict[int, dict] = {}
    due: dict[int, int] = {}
    users = [9001, 9002, 9003]
    wallets = {u: Keypair().pubkey() for u in users}
    for w in wallets.values():
        c.token_account(w, usdc)
    funded = fees = claimed = refunded = 0
    counts: dict[str, int] = {}
    nxt = 1
    steps = FUZZ_N
    print(f"\nrandom walk from seed {FUZZ_SEED}")      # first, so that a failure of any kind shows which walk it was
    for step in range(steps):
        op = rng.choice(["fund", "pay", "pay", "settle", "veto", "refund", "claim", "warp", "bad_pay"])
        where = f"seed {FUZZ_SEED}, step {step} ({op})"
        if op == "fund":
            amount = rng.choice([0, 1, 5, 50, 500]) * USDC
            mode = rng.choice([pay.MERGE, pay.TESTS]); review = rng.choice([0, 300])
            n = nxt; nxt += 1
            if c.send([pay.fund_ix(funder.pubkey(), ftok, usdc, REPO, n, amount, WF_REPO, WF_SHA, mode=mode, review_s=review, work_s=rng.choice([600, 3600]))], funder):
                jobs[n] = dict(amount=amount, mode=mode, review=review, state="open", author=0); funded += amount
        elif op in ("pay", "bad_pay") and jobs:
            n = rng.choice(list(jobs)); j = jobs[n]; u = rng.choice(users)
            tok = c.gh(pay.pay_audience(REPO, n, u, HEAD, pay.NO_CHECKS, j["mode"]), repository_id=str(REPO),
                       **({"job_workflow_sha": "e" * 40} if op == "bad_pay" else {}))
            ok = c.send([pay.pay_ix(c.payer.pubkey(), tok, pay.job_pda(REPO, n, funder.pubkey()), u, usdc, funder.pubkey())])
            if op == "bad_pay":
                assert not ok, f"{where}: a proof from another workflow commit was paid"
            elif ok:
                if j["review"] > 0:
                    j["state"] = "proven"; j["author"] = u
                else:
                    fee = pay.fee_of(j["amount"]); due[u] = due.get(u, 0) + j["amount"] - fee; fees += fee; del jobs[n]
        elif op == "settle" and jobs:
            n = rng.choice(list(jobs)); j = jobs[n]
            if c.send([pay.settle_ix(c.payer.pubkey(), pay.job_pda(REPO, n, funder.pubkey()), j["author"] or users[0], usdc, funder.pubkey())]):
                fee = pay.fee_of(j["amount"]); due[j["author"]] = due.get(j["author"], 0) + j["amount"] - fee; fees += fee; del jobs[n]
        elif op == "veto" and jobs:
            n = rng.choice(list(jobs))
            if c.send([pay.veto_ix(funder.pubkey(), pay.job_pda(REPO, n, funder.pubkey()))], funder):
                jobs[n]["state"] = "open"; jobs[n]["author"] = 0
        elif op == "refund" and jobs:
            n = rng.choice(list(jobs))
            if c.send([pay.refund_ix(c.payer.pubkey(), pay.job_pda(REPO, n, funder.pubkey()), usdc, ftok, funder.pubkey())]):
                refunded += jobs[n]["amount"]; del jobs[n]
        elif op == "claim":
            u = rng.choice(users)
            tok = c.gh(pay.claim_audience(wallets[u]), file="claim.yml", wf_repo="u/r", event_name="workflow_dispatch", actor_id=str(u), repository_owner_id=str(u))
            if c.send([pay.claim_ix(c.payer.pubkey(), tok, u, usdc, wallets[u])]):
                claimed += due.pop(u, 0)
        elif op == "warp":
            c.warp(rng.choice([1, 120, 400, 2000]))
        counts[op] = counts.get(op, 0) + 1
        owed = sum(j["amount"] for j in jobs.values()) + sum(due.values())
        assert c.balance(pay.vault_pda(usdc)) == owed, f"{where}: vault {c.balance(pay.vault_pda(usdc))} != owed {owed}"
        for u in users:
            assert pay.read_due(c.data(pay.due_pda(u, usdc))) == due.get(u, 0), where
    assert funded == claimed + fees + refunded + c.balance(pay.vault_pda(usdc)), f"seed {FUZZ_SEED}"
    assert c.balance(pay.ata(pay.FEE_OWNER, usdc)) == fees, f"seed {FUZZ_SEED}"
    assert sum(c.balance(pay.ata(w, usdc)) for w in wallets.values()) == claimed, f"seed {FUZZ_SEED}"
    print(f"random walk: seed {FUZZ_SEED}, {steps} steps {counts}; funded {funded / USDC:.2f}, claimed {claimed / USDC:.2f}, fees {fees / USDC:.2f}, refunded {refunded / USDC:.2f}, 0 violations")
