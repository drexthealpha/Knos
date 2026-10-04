"""Who may sign a payment of a work order (knos_pay 2.1, programs-v2/knos_pay/src/order_judge.rs), in LiteSVM: the
order's own repository (a), a NEUTRAL attestor (b), the order's judge repository (c), its arbiter (d); an
organisation's wallet (BindOrg); and what a token under a key that is not GitHub's may do. The harness is
tests/_order.py. Each rule has the payment it allows and, beside it, every way round it that is refused."""
from __future__ import annotations

import hashlib

import pytest

pytest.importorskip("solders.litesvm")

from solders.keypair import Keypair  # noqa: E402
from solders.pubkey import Pubkey  # noqa: E402

from _order import AUTHOR, HEAD, MAINT, OWNER, REPO, TERMS, TH, USDC, OrderChain, code, issue, user  # noqa: E402

from knos import flow  # noqa: E402
from knos.settle.v2 import pay  # noqa: E402

NEUTRAL = pay.opts(pay.F_NEUTRAL)
SELLER_REPO = 700_700_700       # a repository the seller owns: nothing of the buyer's is in it


@pytest.fixture(scope="module")
def chain():
    return OrderChain()


def by_hand(who: int, repo: int = SELLER_REPO, **over) -> dict:
    """The claims of attest.yml started by hand by `who` in a repository `who` owns."""
    return {"file": "attest.yml", "event_name": "workflow_dispatch", "actor_id": who, "repository_owner_id": who, "repository_id": repo,
            "repository": f"user{who}/knos-attest", **over}


def paid_to(c: OrderChain, wallet: Pubkey) -> int:
    return c.balance(pay.ata(wallet, c.usdc))


# == b. NEUTRAL: the seller asks for the payment himself ==============================================================
def test_a_seller_pays_himself_after_the_buyers_repository_deleted_its_workflow(chain):
    c = chain
    order = c.fund_wallet(amount=50 * USDC, options=NEUTRAL)
    wallet = Keypair().pubkey()
    payees = [(AUTHOR, 10_000, wallet)]
    # the buyer's repository has no prove.yml any more: no run there will ever sign. The seller starts the pinned
    # attest.yml by hand in a repository of his own, and GitHub signs what its public record of the merge supports.
    assert c.pay(order, payees, **by_hand(AUTHOR)), c.err
    assert paid_to(c, wallet) == 50 * USDC and c.data(order) is None
    assert c.said("knos3:settled")[0].endswith("judge=1")


def test_what_a_neutral_run_cannot_do(chain):
    c = chain
    order, other, strict = c.fund_wallet(options=NEUTRAL), c.fund_wallet(options=NEUTRAL), c.fund_wallet()
    wallet = Keypair().pubkey()
    payees = [(AUTHOR, 10_000, wallet)]
    c.token_account(wallet, c.usdc)
    # an order whose funder did not allow it
    assert not c.pay(strict, payees, **by_hand(AUTHOR)) and code(c) == 85
    refused = (
        (dict(repository_owner_id=user()), 85),                 # an organisation's repository, or someone else's
        (dict(actor_id=user()), 85),                            # started by someone who does not own the repository
        (dict(actor_id=0, repository_owner_id=0), 85),
        (dict(event_name="push"), 85), (dict(event_name="schedule"), 85), (dict(event_name="workflow_call"), 85),
        (dict(file="prove.yml"), 86), (dict(file="fund.yml"), 86), (dict(file="attest.yaml"), 86), (dict(file="x/attest.yml"), 86),
        (dict(wf_sha="d" * 40), 86), (dict(wf_repo="evil/Knos"), 86),                         # another commit, another repository's attest.yml
        (dict(run_attempt=2), 85),                              # a re-run keeps the first actor's name whoever starts it
        (dict(runner_environment="self-hosted"), 85),
        (dict(iat=c.order(order).not_before - 1), 83),
    )
    for over, want in refused:
        t = c.pay_token(order, payees, **by_hand(AUTHOR, **over))
        assert t is not None and not c.send([c.pay_ix(order, t, payees)]) and code(c) == want, over
    # a token for another order pays only that one
    t = c.pay_token(other, payees, **by_hand(AUTHOR))
    assert not c.send([c.pay_ix(order, t, payees)]) and code(c) == 87
    assert c.held(order) == c.held(other) == 20 * USDC + 500_000 and paid_to(c, wallet) == 0
    assert c.send([c.pay_ix(other, t, payees)]), c.err
    # the buyer's own run still pays a neutral order, as before
    assert c.pay(order, payees), c.err
    assert c.said("knos3:settled")[0].endswith("judge=0") and paid_to(c, wallet) == 40 * USDC


def test_the_owner_of_the_orders_repository_may_be_the_neutral_attestor(chain):
    c = chain
    order = c.fund_wallet(options=NEUTRAL)
    wallet = Keypair().pubkey()
    payees = [(AUTHOR, 10_000, wallet)]
    # attest.yml in the order's own repository is not prove.yml: it counts only as a neutral run, by hand, by its owner
    t = c.pay_token(order, payees, file="attest.yml", event_name="push", actor_id=OWNER, repository_owner_id=OWNER)
    assert not c.send([c.pay_ix(order, t, payees)]) and code(c) == 86
    assert c.pay(order, payees, **by_hand(OWNER, repo=REPO)), c.err
    assert c.said("knos3:settled")[0].endswith("judge=1")


# == c. the judge repository: a private order's attestor ==============================================================
PRIVATE_REPO, JUDGE_REPO, SECRET_ISSUE = 777_123_456, 31_313_131, 48_611_907
SECRET = pay.terms_json({"accept": "", "checks": [{"app": 15368, "name": "payroll-export"}], "mode": "merge", "v": 2})
PRIVATE = pay.opts(pay.F_PRIVATE, judge_repo_id=JUDGE_REPO, salted=True)


def private_fund(c: OrderChain, salt: bytes, amount: int = 20 * USDC, options: bytes = PRIVATE, n: int = 0, scope: bytes | None = None,
                 terms: bytes | None = None, **over):
    """A comment in the judge repository funds a private order from the owner's Balance: (token, instruction, order)."""
    real = pay.scope_of(PRIVATE_REPO, SECRET_ISSUE, salt)
    th = pay.terms_hash(SECRET)
    tok = c.fund_token(n, amount, terms=pay.private_fund_terms(real, th), options=options, **{"repository_id": JUDGE_REPO, **over})
    ix = pay.fund_private_order_balance_ix(c.payer.pubkey(), tok, c.key, c.bal, c.usdc, OWNER, scope or real, terms or th, c.data(tok))
    return tok, ix, pay.order_pda(real, c.bal)


def leaks(*blobs: bytes) -> list[str]:
    """What of the private repository is in the clear in these bytes: its id, its issue, its terms."""
    secrets = {"repository id": [str(PRIVATE_REPO).encode(), PRIVATE_REPO.to_bytes(8, "little"), PRIVATE_REPO.to_bytes(4, "big")],
               "issue": [str(SECRET_ISSUE).encode(), SECRET_ISSUE.to_bytes(8, "little"), SECRET_ISSUE.to_bytes(4, "big")],
               "terms": [SECRET, b"payroll-export"]}
    return [name for name, forms in secrets.items() if any(f in blob for f in forms for blob in blobs)]


def test_a_balance_funds_a_private_order_from_its_judge_repository_and_nothing_of_the_repository_is_public():
    c = OrderChain()
    salt = bytes(range(100, 132))
    assert leaks(SECRET + str(PRIVATE_REPO).encode()) == ["repository id", "terms"]         # the scan finds what is there
    before = c.balance(pay.baltok_pda(c.bal))
    tok, ix, order = private_fund(c, salt, 40 * USDC)
    assert c.send([ix], tag="fund_private_order"), c.err
    funded = "\n".join(c.logs).encode()
    o = c.order(order)
    assert (o.state, o.from_balance, o.repo_id, o.issue, o.flags, o.judge_repo_id) == ("open", True, 0, 0, pay.F_PRIVATE, JUDGE_REPO)
    assert (o.scope, o.terms, o.amount, o.fee, o.funder_id, o.owner_id) == (pay.scope_of(PRIVATE_REPO, SECRET_ISSUE, salt), pay.terms_hash(SECRET), 40 * USDC, USDC, MAINT, OWNER)
    assert c.held(order) == 41 * USDC == before - c.balance(pay.baltok_pda(c.bal))
    assert c.said("knos3:terms") == [] and c.said("knos3:funded")[0].startswith(f"knos3:funded order={order} repo=0 issue=0 ")
    assert not c.send([ix]) and code(c) == 91                              # the token worked once
    # a run in the judge repository pays it; nobody else's does
    wallet = Keypair().pubkey()
    payees = [(AUTHOR, 10_000, wallet)]
    for over, want in ((dict(repository_id=REPO), 85), (dict(repository_id=PRIVATE_REPO), 85), (by_hand(AUTHOR), 85), (by_hand(MAINT), 85),
                       (dict(repository_id=JUDGE_REPO, file="fund.yml"), 86), (dict(repository_id=JUDGE_REPO, wf_sha="d" * 40), 86),
                       (dict(repository_id=JUDGE_REPO, run_attempt=2), 85), (dict(repository_id=JUDGE_REPO, runner_environment="self-hosted"), 85)):
        t = c.pay_token(order, payees, **over)
        assert not c.send([c.pay_ix(order, t, payees)]) and code(c) == want, over
    proof = c.pay_token(order, payees, repository_id=JUDGE_REPO)
    assert c.send([c.pay_ix(order, proof, payees)], tag="pay_private_order"), c.err
    assert c.said("knos3:settled")[0].endswith("judge=2") and paid_to(c, wallet) == 40 * USDC
    # the order's account, both tokens as the verifier keeps them, and every log line: no repository, no issue, no terms
    assert leaks(bytes(c.data(tok)), bytes(c.data(proof)), funded, "\n".join(c.logs).encode()) == []
    order2 = private_fund(c, bytes(32))
    assert c.send([order2[1]]) and leaks(bytes(c.data(order2[2]))) == []


def test_a_private_order_is_paid_under_the_number_the_client_hides_its_pull_request_by():
    """flow.hidden_pull is what a private order's pay audience names; knos_pay itself (not a fake) must take it. The
    salt is one whose 8-byte number had 20 digits: that number is refused (87), the client's is paid."""
    c = OrderChain()
    salt = next(s for s in (hashlib.sha256(bytes([i])).digest() for i in range(256))
                if len(str(int.from_bytes(hashlib.sha256(s + b"knos3:pull" + (41_123).to_bytes(8, "little")).digest()[:8], "little"))) == 20)
    old = int.from_bytes(hashlib.sha256(salt + b"knos3:pull" + (41_123).to_bytes(8, "little")).digest()[:8], "little")
    _, ix, order = private_fund(c, salt)
    assert c.send([ix]), c.err
    wallet = Keypair().pubkey()
    payees = [(AUTHOR, 10_000, wallet)]
    refused = c.pay_token(order, payees, pr=old, repository_id=JUDGE_REPO)
    assert refused is None or (not c.send([c.pay_ix(order, refused, payees)]) and code(c) == 87)
    c.warp(1)
    proof = c.pay_token(order, payees, pr=flow.hidden_pull(salt, 41_123), repository_id=JUDGE_REPO)
    assert proof is not None and c.send([c.pay_ix(order, proof, payees)], tag="pay_private_order_hidden_pull"), c.err
    assert paid_to(c, wallet) == 20 * USDC


def test_what_the_funding_of_a_private_order_cannot_do():
    c = OrderChain()
    salt = bytes(range(32))
    refuse = lambda want, **kw: (lambda t: (not c.send([t[1]]) and code(c) == want, c.err))(private_fund(c, salt, **kw))  # noqa: E731
    # a run in another repository of the owner than the one that will judge it
    assert refuse(85, repository_id=REPO)[0]
    assert refuse(85, repository_id=PRIVATE_REPO)[0]
    # an issue in the clear; a scope or terms the token did not commit to (a relayer cannot choose where the order lives)
    assert refuse(81, n=SECRET_ISSUE)[0]
    assert refuse(81, scope=pay.scope_of(PRIVATE_REPO, SECRET_ISSUE, bytes(32)))[0]
    assert refuse(81, terms=TH)[0]
    # a private order with no judge repository, and the flag without a scope
    assert refuse(81, options=pay.opts(pay.F_PRIVATE, salted=True))[0]
    assert refuse(81, options=pay.opts(pay.F_PRIVATE, judge_repo_id=JUDGE_REPO))[0]
    # a public order's instruction with a private order's token, and the reverse
    tok, _, _ = private_fund(c, salt)
    assert not c.send([c.fund_balance_ix(tok, 0, terms=SECRET, repo=JUDGE_REPO)]) and code(c) == 81
    n = issue()
    public = c.fund_token(n)
    assert not c.send([pay.fund_private_order_balance_ix(c.payer.pubkey(), public, c.key, c.bal, c.usdc, OWNER, pay.scope_of(REPO, n), TH, c.data(public))])
    assert code(c) == 81
    # a commenter the Balance does not list; a repository of another owner
    assert refuse(92, actor=user())[0] and refuse(92, repository_owner_id=user())[0]
    # the Balance allows that repository: with a list of repositories, the judge repository must be on it
    assert c.send([pay.set_balance_x_ix(c.owner.pubkey(), c.bal, repos=[REPO])], c.owner), c.err
    assert refuse(92)[0]
    assert c.send([pay.set_balance_x_ix(c.owner.pubkey(), c.bal, repos=[REPO, JUDGE_REPO])], c.owner), c.err
    _, ix, order = private_fund(c, salt)
    assert c.send([ix]), c.err
    assert c.order(order).judge_repo_id == JUDGE_REPO


def test_a_public_order_that_names_a_judge_repository_is_paid_from_it_too(chain):
    c = chain
    options = pay.opts(judge_repo_id=JUDGE_REPO)
    wallet = Keypair().pubkey()
    payees = [(AUTHOR, 10_000, wallet)]
    for over, judge in ((dict(repository_id=JUDGE_REPO), 2), (dict(repository_id=JUDGE_REPO, file="attest.yml", event_name="push"), 2), ({}, 0)):
        order = c.fund_wallet(options=options)
        assert c.pay(order, payees, **over), c.err
        assert c.said("knos3:settled")[0].endswith(f"judge={judge}")
    # no judge repository named: the run in that repository is nobody's
    plain = c.fund_wallet()
    assert not c.pay(plain, payees, repository_id=JUDGE_REPO) and code(c) == 85
    # a private order from a wallet is judged the same way, and a neutral run never pays one, whatever its flags say
    scope = pay.scope_of(PRIVATE_REPO, SECRET_ISSUE, bytes([9]) * 32)
    both = pay.opts(pay.F_PRIVATE | pay.F_NEUTRAL, judge_repo_id=JUDGE_REPO, salted=True)
    ix = pay.fund_order_wallet_ix(c.funder.pubkey(), c.funder_tok, c.usdc, 0, 0, 20 * USDC, "drexthealpha/Knos", "c" * 40, TH, options=both, scope=scope)
    assert c.send([ix], c.funder), c.err
    order = pay.order_pda(scope, c.funder.pubkey())
    assert not c.pay(order, payees, **by_hand(AUTHOR)) and code(c) == 85
    assert not c.pay(order, payees, repository_id=0) and code(c) == 85
    assert c.pay(order, payees, repository_id=JUDGE_REPO), c.err


# == d. the arbiter ===================================================================================================
def ruling(c: OrderChain, order: Pubkey, payees, who: int, **over) -> Pubkey | None:
    """What GitHub signs when `who` starts attest.yml by hand in a repository of his own to rule on an order."""
    claims = by_hand(who, **over)
    aud = claims.pop("aud", None) or pay.rule_audience(order, payees)
    return c.gh(aud, **claims)


def test_the_arbiter_an_order_named_rules_who_is_paid(chain):
    c = chain
    arbiter, other = user(), user()
    order = c.fund_wallet(amount=100 * USDC, options=pay.opts(arbiter_id=arbiter))
    seller, buyer = Keypair().pubkey(), Keypair().pubkey()
    payees = [(AUTHOR, 7_000, seller), (other, 3_000, buyer)]
    o = c.order(order)
    assert pay.rule_audience(order, payees) == f"knos3:rule:{order}:{AUTHOR}.7000.{seller},{other}.3000.{buyer}"
    # the two sides disagree; the person both accepted at funding decides, and the order pays what he ruled
    tok = ruling(c, order, payees, arbiter)
    assert c.send([c.pay_ix(order, tok, payees, o)], tag="rule_order"), c.err
    assert (paid_to(c, seller), paid_to(c, buyer), c.data(order)) == (70 * USDC, 30 * USDC, None)
    assert c.said("knos3:settled")[0].endswith("judge=3")
    assert c.said("knos3:paid") == [f"knos3:paid order={order} pr=0 payee={AUTHOR} amount=70000000 to={seller}",
                                    f"knos3:paid order={order} pr=0 payee={other} amount=30000000 to={buyer}"]


def test_what_a_ruling_cannot_do(chain):
    c = chain
    arbiter = user()
    order, twin, plain = (c.fund_wallet(options=pay.opts(arbiter_id=arbiter)), c.fund_wallet(options=pay.opts(arbiter_id=arbiter)), c.fund_wallet(options=NEUTRAL))
    wallet = Keypair().pubkey()
    payees = [(AUTHOR, 10_000, wallet)]
    c.token_account(wallet, c.usdc)
    # an order that named no arbiter has none, whoever rules
    for who in (arbiter, AUTHOR, OWNER):
        assert not c.send([c.pay_ix(plain, ruling(c, plain, payees, who), payees)]) and code(c) == 85, who
    refused = (
        (AUTHOR, {}, 85), (OWNER, {}, 85),                                    # a ruling by someone the order did not name
        (arbiter, dict(repository_owner_id=user()), 85),                      # by the arbiter, in a repository that is not his
        (user(), dict(repository_owner_id=arbiter), 85),                      # in the arbiter's repository, by someone else
        (arbiter, dict(event_name="push"), 85), (arbiter, dict(event_name="issue_comment"), 85),
        (arbiter, dict(file="prove.yml"), 86), (arbiter, dict(wf_sha="d" * 40), 86), (arbiter, dict(wf_repo="evil/Knos"), 86),
        (arbiter, dict(run_attempt=2), 85), (arbiter, dict(runner_environment="self-hosted"), 85),
        (arbiter, dict(aud=pay.rule_audience(order, [(arbiter, 10_000, wallet)])), 85),                   # he pays himself
        (arbiter, dict(aud=pay.rule_audience(twin, payees)), 87),                                       # a ruling on another order
        (arbiter, dict(aud=pay.rule_audience(order, payees) + ":x"), 87), (arbiter, dict(aud=f"knos3:rule:{order}"), 87),
        (arbiter, dict(aud=pay.rule_audience(order, [(AUTHOR, 9_999, wallet)])), 87),
        (arbiter, dict(aud=pay.rule_audience(order, payees).replace("knos3", "knos2")), 85),
    )
    for who, over, want in refused:
        t = ruling(c, order, payees, who, **over)
        assert t is not None and not c.send([c.pay_ix(order, t, payees)]) and code(c) == want, over
    # the arbiter is a judge only when he rules: his pay token is anyone's, and this order allows no neutral run
    o = c.order(order)
    as_seller = c.gh(pay.order_pay_audience(order, HEAD, o.terms, o.mode, 7, payees), **by_hand(arbiter))
    assert not c.send([c.pay_ix(order, as_seller, payees)]) and code(c) == 85
    # nobody else's run signs a ruling: not the order's own repository's
    own = c.gh(pay.rule_audience(order, payees), repository_id=REPO)
    assert not c.send([c.pay_ix(order, own, payees)]) and code(c) == 86
    assert c.held(order) == 20 * USDC + 500_000 and paid_to(c, wallet) == 0
    # after the deadline the money goes back, ruling or not
    short = c.fund_wallet(work_s=3600, options=pay.opts(arbiter_id=arbiter))
    c.warp(3601)
    assert not c.send([c.pay_ix(short, ruling(c, short, payees, arbiter), payees)]) and code(c) == 83
    assert c.send([c.pay_ix(order, ruling(c, order, payees, arbiter), payees)]), c.err


def test_the_arbiter_is_neither_the_funder_nor_a_payee(chain):
    c = chain
    # at funding: the commenter who funds, and the owner whose Balance pays, cannot name themselves
    for arbiter in (MAINT, OWNER):
        n = issue()
        tok = c.fund_token(n, options=pay.opts(arbiter_id=arbiter))
        assert not c.send([c.fund_balance_ix(tok, n)]) and code(c) == 81, arbiter
    n, arbiter = issue(), user()
    tok = c.fund_token(n, 30 * USDC, options=pay.opts(arbiter_id=arbiter), actor=OWNER)
    assert c.send([c.fund_balance_ix(tok, n)]), c.err
    order = pay.order_pda(pay.scope_of(REPO, n), c.bal)
    assert (c.order(order).arbiter_id, c.order(order).funder_id) == (arbiter, OWNER)
    # at the ruling: he names others. The funder may be one of them (the ruling can go the buyer's way)
    wallet, back = Keypair().pubkey(), Keypair().pubkey()
    mixed = [(AUTHOR, 5_000, wallet), (arbiter, 5_000, wallet)]
    assert not c.send([c.pay_ix(order, ruling(c, order, mixed, arbiter), mixed)]) and code(c) == 85
    split = [(AUTHOR, 5_000, wallet), (OWNER, 5_000, back)]
    assert c.send([c.pay_ix(order, ruling(c, order, split, arbiter), split)]), c.err
    assert (paid_to(c, wallet), paid_to(c, back)) == (15 * USDC, 15 * USDC)


# == BindOrg: an organisation's wallet ================================================================================
CLAIM = dict(file="claim.yml", wf_repo="drexthealpha/knos-oidc-rotate", wf_sha="2" * 40, event_name="workflow_dispatch")     # the test build's claim pin


def org_token(c: OrderChain, org: int, wallet, member: int | None = None, **over) -> Pubkey | None:
    """What GitHub signs when a member starts the pinned claim workflow by hand in the organisation's knos-claim."""
    c.warp(1)
    claims = {**CLAIM, "actor_id": member or user(), "repository_owner_id": org, "repository": f"org{org}/knos-claim", "repository_id": 60_000_000 + org % 1_000_000,
              **over}
    return c.gh(claims.pop("aud", None) or pay.org_bind_audience(wallet), **claims)


def bind_org(c: OrderChain, org: int, wallet, **over) -> bool:
    return c.send([pay.bind_org_ix(c.payer.pubkey(), org_token(c, org, wallet, **over), c.key, org)], tag="bind_org")


def test_a_pull_request_by_a_bot_is_paid_to_its_organisations_wallet(chain):
    c = chain
    org, bot, wallet = user(), user(), Keypair().pubkey()
    assert pay.org_bind_audience(wallet) == f"knos3:bind:{wallet}"
    assert bind_org(c, org, wallet), c.err
    assert pay.read_bind(c.data(pay.bind_pda(org))) == pay.Bind(user_id=org, wallet=wallet, iat=c.now())
    assert c.said("knos3:bound")[0].startswith(f"knos3:bound org={org} wallet={wallet} by=")
    # the organisation's bot opened the pull request; the proof names the organisation as payee, and its Bind says where
    order = c.fund_wallet(amount=60 * USDC)
    payees = [(org, 10_000, None)]
    assert c.wallets(payees) == [(org, wallet)] and bot != org
    assert c.pay(order, payees), c.err
    assert paid_to(c, wallet) == 60 * USDC and c.data(order) is None
    assert pay.read_rep(c.data(pay.rep_pda(org))).paid == 1
    # a member binds another wallet later; the token before it does nothing any more
    old = org_token(c, org, Keypair().pubkey())
    again = Keypair().pubkey()
    assert bind_org(c, org, again), c.err
    assert pay.read_bind(c.data(pay.bind_pda(org))).wallet == again
    assert not c.send([pay.bind_org_ix(c.payer.pubkey(), old, c.key, org)]) and code(c) == 91
    # the pins of the deployed program: CLAIM_SHA (a person's claim), and CLAIM_SHA_ORG beside it: the claim workflow's
    # later commit, which takes `kind: org` and mints knos3:bind. BindOrg takes a run at either.
    import re
    from pathlib import Path
    src = Path(__file__).resolve().parents[1] / "programs-v2" / "knos_pay" / "src"
    pin = re.search(r'pub const CLAIM_SHA_ORG: &\[u8; 40\] = b"([0-9a-f]{40})";', (src / "order_judge.rs").read_text()).group(1)
    assert pin == pay.IDS["claim_sha_org"] != pay.IDS["claim_sha"]
    for sha in (pin, pay.IDS["claim_sha"]):
        assert bind_org(c, user(), wallet, wf_sha=sha), c.err


def test_what_an_organisations_bind_token_cannot_do(chain):
    c = chain
    org, wallet, member = user(), Keypair().pubkey(), user()
    refused = (
        (dict(actor_id=org), 85),                                         # a person's own repository: that is Bind, not BindOrg
        (dict(actor_id=0), 85), (dict(event_name="push"), 85), (dict(event_name="issue_comment"), 85), (dict(run_attempt=2), 85),
        (dict(repository=f"org{org}/claim"), 85), (dict(repository=f"org{org}/knos-claim-2"), 85), (dict(repository=f"org{org}/my-knos-claim"), 85),
        (dict(wf_sha="d" * 40), 86), (dict(wf_repo="evil/knos-oidc-rotate"), 86), (dict(file="rotate.yml"), 86),
        (dict(file="prove.yml", wf_repo="drexthealpha/Knos", wf_sha="c" * 40), 86),
        (dict(runner_environment="self-hosted"), 85),
        (dict(aud=pay.bind_audience(wallet)), 87),                        # a person's bind audience
        (dict(aud=pay.org_bind_audience(wallet) + ":x"), 87), (dict(aud="knos3:bind:" + "1" * 31), 87),
    )
    for over, want in refused:
        t = org_token(c, org, wallet, member, **over)
        assert t is not None and not c.send([pay.bind_org_ix(c.payer.pubkey(), t, c.key, org)]) and code(c) == want, over
    assert c.data(pay.bind_pda(org)) is None
    # the Bind is the organisation's own: the token of one organisation binds no other id, and not the member's
    t = org_token(c, org, wallet, member)
    for other in (user(), member):
        assert not c.send([pay.bind_org_ix(c.payer.pubkey(), t, c.key, other)]) and code(c) == 80
    # an organisation's token is not a person's: Bind refuses it, for the organisation and for the member
    for who in (org, member):
        assert not c.send([pay.bind_ix(c.payer.pubkey(), t, c.key, who)]) and code(c) == 85
    personal = c.gh(pay.org_bind_audience(wallet), **{**CLAIM, "actor_id": member, "repository_owner_id": member, "repository": "m/knos-claim"})
    assert not c.send([pay.bind_ix(c.payer.pubkey(), personal, c.key, member)]) and code(c) == 87
    assert c.send([pay.bind_org_ix(c.payer.pubkey(), t, c.key, org)]), c.err
    assert not c.send([pay.bind_org_ix(c.payer.pubkey(), t, c.key, org)]) and code(c) == 91


def test_a_collaborator_cannot_rebind_a_person_who_bound_his_own_wallet(chain):
    c = chain
    # GitHub's claims do not say whether an owner is a person or an organisation. A person who gave someone write
    # access to his knos-claim repository looks, to BindOrg, like an organisation with a member.
    person, guest, mine, theirs = user(), user(), Keypair().pubkey(), Keypair().pubkey()
    assert c.bind(person, mine), c.err
    assert not bind_org(c, person, theirs, member=guest) and code(c) == 85
    assert pay.read_bind(c.data(pay.bind_pda(person))).wallet == mine
    # the other order of events: the guest was first. The person's own Bind replaces his, and then stays
    late = user()
    assert bind_org(c, late, theirs, member=guest), c.err
    assert c.bind(late, mine), c.err
    assert not bind_org(c, late, theirs, member=guest) and code(c) == 85
    assert pay.read_bind(c.data(pay.bind_pda(late))).wallet == mine


# == a key that is not GitHub's =======================================================================================
GHE = "https://ghe.acme.example/_services/token"


class Issuer:
    """A signing key on this chain that is not GitHub's by number: a PRIVATE one (`registrant` registered it himself,
    nobody checked it), or one of a registered issuer (GitHub's signature named it, the guardian approved it, its day
    of waiting passed). Its tokens carry the claims a GitHub token would, and the issuer's own `iss`."""
    def __init__(self, c: OrderChain, url: str, registrant: Keypair | None = None):
        from cryptography.hazmat.primitives.asymmetric import rsa
        from _pay2 import GUARDIAN
        from _settle import modulus
        from knos.settle.v2 import oidc
        self.c, self.url, self.k = c, url, rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.n, self.who, p = modulus(self.k), registrant.pubkey() if registrant else None, c.payer.pubkey()
        self.key = oidc.key_pda(url, self.n, registrant=self.who)
        if registrant is not None:
            assert c.send([oidc.register_private_key_ix(self.who, url, self.n)], registrant), c.err
            assert c.send([oidc.key_params_ix(self.who, url, self.n, registrant=self.who)], registrant), c.err
        else:
            tok = c.attest(url, self.n)
            assert c.send([oidc.register_issuer_key_ix(p, url, self.n, tok, c.key_of(tok))]) and c.send([oidc.key_params_ix(p, url, self.n)]), c.err
            assert c.send([oidc.approve_ix(GUARDIAN.pubkey(), url, self.n)], signers=[GUARDIAN]), c.err
            c.warp(oidc.KEY_DELAY)

    def token(self, aud: str, file: str = "prove.yml", wf_repo: str = "drexthealpha/Knos", wf_sha: str = "c" * 40, **over) -> Pubkey | None:
        from _pay2 import github_claims
        from _settle import sign_jwt
        from knos.settle.v2 import oidc
        c = self.c
        now = c.now()
        c._n += 1
        claims = dict(aud=aud, iss=self.url, iat=now, nbf=now - 600, exp=now + 300, jti=f"p{c._n}",
                      job_workflow_ref=f"{wf_repo}/.github/workflows/{file}@refs/tags/v0.3.12", job_workflow_sha=wf_sha)
        claims.update(over)
        tid = c.write(sign_jwt(self.k, github_claims(**claims)))
        for sq in oidc.step_plan(self.n.bit_length()):
            if not c.send([oidc.step_ix(c.payer.pubkey(), tid, self.key, sq)]):
                return None
        return oidc.token_pda(c.payer.pubkey(), tid)

    def pay_token(self, order: Pubkey, payees, **over) -> Pubkey | None:
        o = self.c.order(order)
        return self.token(pay.order_pay_audience(order, HEAD, o.terms, o.mode, 7, payees), **over)

    def pay_ix(self, order: Pubkey, tok: Pubkey, payees):
        c = self.c
        return pay.pay_order_ix(c.payer.pubkey(), tok, self.key, order, c.order(order), c.wallets(payees))


def test_a_private_order_of_a_balance_is_paid_under_the_key_its_authority_registered():
    from knos.settle.v2 import oidc
    c = OrderChain()
    company = Issuer(c, GHE, c.owner)                   # the wallet that opened the Balance registers its own server's key
    _, ix, order = private_fund(c, bytes(range(32)), 40 * USDC)
    assert c.send([ix]), c.err
    wallet = Keypair().pubkey()
    payees = [(AUTHOR, 10_000, wallet)]
    tok = company.pay_token(order, payees, repository_id=JUDGE_REPO)
    assert oidc.read_token(c.data(tok)).issuer == oidc.PRIVATE and oidc.token_issuer(c.data(tok)) == (oidc.issuer_hash(GHE), c.owner.pubkey())
    # the same accounts as any payment: the token, and the key that verified it
    assert c.send([company.pay_ix(order, tok, payees)], tag="pay_order_private_key"), c.err
    assert paid_to(c, wallet) == 40 * USDC and c.said("knos3:settled")[0].endswith("judge=2")
    # an arbiter is someone else, and only GitHub says who started a run: the company's key signs no ruling in his name
    arbiter = user()
    options = pay.opts(pay.F_PRIVATE, arbiter_id=arbiter, judge_repo_id=JUDGE_REPO, salted=True)
    _, ix, disputed = private_fund(c, bytes(range(1, 33)), options=options)
    assert c.send([ix]), c.err
    forged = company.token(pay.rule_audience(disputed, payees), **by_hand(arbiter))
    assert forged is not None and not c.send([company.pay_ix(disputed, forged, payees)]) and code(c) == 84
    assert c.send([c.pay_ix(disputed, ruling(c, disputed, payees, arbiter), payees)]), c.err
    assert c.said("knos3:settled")[0].endswith("judge=3")


def test_what_a_token_under_a_key_that_is_not_githubs_cannot_do():
    from _pay2 import WF_REPO, WF_SHA
    from _order import swap
    from knos.settle.v2 import oidc
    c = OrderChain()
    company = Issuer(c, GHE, c.owner)
    thief_wallet = c.fund()
    thief = Issuer(c, oidc.ISSUERS[oidc.GITHUB], thief_wallet)       # "GitHub's" key, says a wallet nobody vouches for
    other = Issuer(c, "https://oidc.ci.example.dev")                 # a registered issuer: GitHub's signature admitted its key
    wallet = Keypair().pubkey()
    payees = [(AUTHOR, 10_000, wallet)]
    c.token_account(wallet, c.usdc)
    _, ix, order = private_fund(c, bytes(range(32)))
    assert c.send([ix]), c.err
    # the company's own key pays the company's private order only as a judge of that order would
    for over, want in ((dict(repository_id=REPO), 85), (dict(repository_id=JUDGE_REPO, wf_sha="d" * 40), 86), (dict(repository_id=JUDGE_REPO, file="fund.yml"), 86),
                       (dict(repository_id=JUDGE_REPO, run_attempt=2), 85), (dict(repository_id=JUDGE_REPO, runner_environment="self-hosted"), 85),
                       (by_hand(AUTHOR), 85)):
        t = company.pay_token(order, payees, **over)
        assert t is not None and not c.send([company.pay_ix(order, t, payees)]) and code(c) == want, over
    good = company.pay_token(order, payees, repository_id=JUDGE_REPO)
    # ...and with its own key account: GitHub's beside the token is not the key that verified it
    assert not c.send([swap(company.pay_ix(order, good, payees), 2, c.key)]) and code(c) == 80
    # anyone else's key pays nothing of the company's, whatever its token says: a thief's private key "of GitHub",
    # and a registered issuer's
    for who in (thief, other):
        t = who.pay_token(order, payees, repository_id=JUDGE_REPO)
        assert t is not None and not c.send([who.pay_ix(order, t, payees)]) and code(c) == 84, who.url
    # the company's key pays no order but a PRIVATE one of a Balance its wallet opened:
    # a public order of that Balance, of a wallet (the company's own included), a private order of a wallet,
    public = c.fund_balance(options=pay.opts(judge_repo_id=JUDGE_REPO))
    of_wallet = c.fund_wallet(options=pay.opts(judge_repo_id=JUDGE_REPO))
    own_wallet = c.fund_wallet(options=pay.opts(judge_repo_id=JUDGE_REPO), funder=c.owner, funder_tok=c.owner_tok)
    scope = pay.scope_of(PRIVATE_REPO, SECRET_ISSUE, bytes([3]) * 32)
    fund = pay.fund_order_wallet_ix(c.funder.pubkey(), c.funder_tok, c.usdc, 0, 0, 20 * USDC, WF_REPO, WF_SHA, TH, options=PRIVATE, scope=scope)
    assert c.send([fund], c.funder), c.err
    private_of_wallet = pay.order_pda(scope, c.funder.pubkey())
    # ...and a private order of another wallet's Balance for the same owner
    w, wtok = c.wallet(c.usdc, 100 * USDC)
    assert c.send([pay.open_balance_ix(w.pubkey(), OWNER, c.usdc, spenders=[MAINT])], w), c.err
    theirs = pay.balance_pda(OWNER, w.pubkey(), c.usdc)
    from _order import transfer
    transfer(c, wtok, pay.baltok_pda(theirs), 100 * USDC, w)
    s2, th = pay.scope_of(PRIVATE_REPO, SECRET_ISSUE, bytes([4]) * 32), pay.terms_hash(SECRET)
    ftok = c.fund_token(0, terms=pay.private_fund_terms(s2, th), options=PRIVATE, balance=theirs, repository_id=JUDGE_REPO)
    assert c.send([pay.fund_private_order_balance_ix(c.payer.pubkey(), ftok, c.key, theirs, c.usdc, OWNER, s2, th, c.data(ftok))]), c.err
    of_other_balance = pay.order_pda(s2, theirs)
    for target in (public, of_wallet, own_wallet, private_of_wallet, of_other_balance):
        t = company.pay_token(target, payees, repository_id=JUDGE_REPO)
        assert t is not None and not c.send([company.pay_ix(target, t, payees)]) and code(c) == 84, target
        assert c.pay(target, payees, repository_id=JUDGE_REPO), c.err         # GitHub's own signature pays each
    # no other instruction takes a token GitHub did not sign: a wallet's bind, an organisation's, a job's funding, an
    # order's funding, a job's payment, the faucet
    for who in (company, thief, other):
        person, org, n = user(), user(), issue()
        bind = who.token(pay.bind_audience(wallet), **{**CLAIM, "actor_id": person, "repository_owner_id": person, "repository": "p/knos-claim"})
        assert not c.send([swap(pay.bind_ix(c.payer.pubkey(), bind, who.key, person), 2, who.key)]) and code(c) == 84
        obind = who.token(pay.org_bind_audience(wallet), **{**CLAIM, "actor_id": person, "repository_owner_id": org, "repository": "o/knos-claim"})
        assert not c.send([pay.bind_org_ix(c.payer.pubkey(), obind, who.key, org)]) and code(c) == 84
        comment = dict(file="fund.yml", event_name="issue_comment", actor_id=MAINT, repository_id=REPO, repository_owner_id=OWNER)
        job = who.token(pay.fund_audience(n, 20 * USDC, pay.MERGE, TH, c.bal), **comment)
        assert not c.send([pay.fund_balance_ix(c.payer.pubkey(), job, who.key, c.bal, c.usdc, REPO, n, TERMS)]) and code(c) == 84
        ordr = who.token(pay.order_fund_audience(n, 20 * USDC, pay.MERGE, TH, c.bal), **comment)
        assert not c.send([swap(c.fund_balance_ix(ordr, n), 2, who.key)]) and code(c) == 84
        ptok = who.token(pay.order_fund_audience(0, 20 * USDC, pay.MERGE, pay.private_fund_terms(scope, th), c.bal, options=PRIVATE), **{**comment, "repository_id": JUDGE_REPO})
        private = pay.fund_private_order_balance_ix(c.payer.pubkey(), ptok, who.key, c.bal, c.usdc, OWNER, scope, th, c.data(ptok))
        assert not c.send([private]) and code(c) == 84
        assert c.send([pay.fund_wallet_ix(c.funder.pubkey(), c.funder_tok, c.usdc, REPO, n, 20 * USDC, WF_REPO, WF_SHA, TERMS)], c.funder), c.err
        j = pay.job_pda(REPO, n, c.funder.pubkey())
        proof = who.token(pay.pay_audience(REPO, n, AUTHOR, HEAD, TH, pay.MERGE, wallet), repository_id=REPO)
        assert not c.send([pay.pay_ix(c.payer.pubkey(), proof, who.key, j, pay.read_job(c.data(j)), AUTHOR, wallet, used=c.data(proof))]) and code(c) == 84
        if c.data(pay.faucet_mint()) is None:
            assert c.send([pay.init_faucet_ix(c.payer.pubkey())]), c.err
        drip = who.token(pay.fund_audience(n, 20 * USDC, pay.MERGE, TH, pay.faucet_balance_pda(OWNER)), **comment)
        assert not c.send([pay.faucet_open_ix(c.payer.pubkey(), drip, who.key, OWNER, REPO)]) and code(c) == 84
    # its registrant ends the key, and what it verified ends with it
    assert c.send([oidc.revoke_ix(c.owner.pubkey(), GHE, company.n, registrant=c.owner.pubkey())], c.owner), c.err
    assert not c.send([company.pay_ix(order, good, payees)]) and code(c) == 78
    assert c.held(order) == 20 * USDC + 500_000 and paid_to(c, wallet) == 5 * 20 * USDC
