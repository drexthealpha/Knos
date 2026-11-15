"""A GitLab project funds a work order and its merge request's author is paid (knos_pay 2.1, programs-v2/knos_pay/src/gl.rs),
inside LiteSVM. The tokens are GitLab-shaped (tests/_settle.py, gitlab_claims: the names GitLab documents) and signed
by the 4096-bit seed key, which a test build of knos-oidc takes as a gitlab.com key (pins.rs TEST_GENESIS).

What is shown: the order is funded from a pipeline a listed spender ran by hand on a protected branch and paid from a
pipeline that a pipeline of the project started on that same branch at the pinned commit; and what is refused: a ref
that is not protected, another CI file or commit, the wrong pipeline for the audience, a GitHub token for a GitLab
order and a GitLab token for a GitHub order, and ids that would meet across the two."""
from __future__ import annotations

import pytest
from solders.pubkey import Pubkey

from _order import HEAD, REPO, TERMS, TH, USDC, OrderChain, code, issue, transfer
from _pay2 import WF_REPO, WF_SHA
from _settle import gitlab_claims, modulus, sign_jwt, signing_key

from knos.settle.v2 import oidc, pay

GL_NS, GL_ID = 8 * 10 ** 17, 9 * 10 ** 17                # gl.rs: where namespace ids start, and project and user ids
PROJECT, NAMESPACE, SPENDER, AUTHOR = 20, 72, 31, 4242   # as GitLab numbers them
URI = "gitlab.com/my-group/my-project//.gitlab-ci.yml@refs/heads/knos"
SHA = "e" * 40                                           # the commit of the protected branch `knos`: the pinned CI file
CLAIMS, WORKFLOW, AUD, SPENDER_REFUSED = 85, 86, 87, 92  # lib.rs E_*


class GitLab(OrderChain):
    def __init__(self):
        super().__init__()
        self.gl_n = modulus(signing_key(4096))
        self.gl_key = oidc.key_pda(oidc.GITLAB, self.gl_n)
        assert self.register(oidc.GITLAB, self.gl_n), self.err
        # the wallet's Balance for the projects of namespace 72: a namespace is nobody's user id, so the spender is listed
        assert self.send([pay.open_balance_ix(self.owner.pubkey(), GL_NS + NAMESPACE, self.usdc, spenders=[GL_ID + SPENDER])], self.owner), self.err
        self.gl_bal = pay.balance_pda(GL_NS + NAMESPACE, self.owner.pubkey(), self.usdc)
        transfer(self, self.owner_tok, pay.baltok_pda(self.gl_bal), 1_000 * USDC, self.owner)

    def gl(self, aud: str, source: str, **over) -> Pubkey | None:
        """A verified GitLab token for this audience: a job of the pinned CI file on the protected branch `knos`."""
        self.warp(1)
        now = self.now()
        self._n += 1
        c = gitlab_claims(aud=aud, iat=now, nbf=now - 5, exp=now + 300, jti=f"g{self._n}", pipeline_source=source, ref="knos", ref_path="refs/heads/knos",
                          ref_protected="true", ci_config_ref_uri=URI, ci_config_sha=SHA, project_id=str(PROJECT), namespace_id=str(NAMESPACE),
                          user_id=str(SPENDER), sub="project_path:my-group/my-project:ref_type:branch:ref:knos")
        c.update(over)
        return self.verify(sign_jwt(signing_key(4096), c), oidc.GITLAB, self.gl_n)

    def gl_fund(self, n: int, source: str = "web", amount: int = 20 * USDC, **over):
        """(the transaction went through, the order's address) for a fund token of issue n."""
        tok = self.gl(pay.order_fund_audience(n, amount, pay.MERGE, TH, self.gl_bal), source, **over)
        ix = pay.fund_order_balance_ix(self.payer.pubkey(), tok, self.gl_key, self.gl_bal, self.usdc, GL_NS + NAMESPACE, GL_ID + PROJECT, n, TERMS,
                                       self.data(tok))
        return self.send([ix]), ix.accounts[7].pubkey

    def gl_pay(self, order: Pubkey, wallet: Pubkey, source: str = "pipeline", payee: int = GL_ID + AUTHOR, **over) -> bool:
        """The pinned job read the merged merge request and names its author and the address the author gave."""
        o = self.order(order)
        tok = self.gl(pay.order_pay_audience(order, HEAD, o.terms, o.mode, 7, [(payee, 10_000, wallet)]), source, user_id=str(SPENDER + 1), **over)
        return self.send([pay.pay_order_ix(self.payer.pubkey(), tok, self.gl_key, order, o, [(payee, wallet)])])


@pytest.fixture(scope="module")
def c() -> GitLab:
    return GitLab()


def test_a_gitlab_project_funds_an_order_and_the_merge_request_author_is_paid(c):
    n, before = issue(), c.balance(pay.baltok_pda(c.gl_bal))
    ok, order = c.gl_fund(n)
    assert ok, c.err
    o = c.order(order)
    fee = o.fee
    assert (o.repo_id, o.issue, o.funder_id, o.owner_id, o.amount) == (GL_ID + PROJECT, n, GL_ID + SPENDER, GL_NS + NAMESPACE, 20 * USDC)
    assert c.held(order) == 20 * USDC + fee == before - c.balance(pay.baltok_pda(c.gl_bal))
    assert order == pay.order_pda(pay.scope_of(GL_ID + PROJECT, n), c.gl_bal)
    # the order pins the CI file as GitLab names it, branch included, and its commit
    assert pay.wf_repo_hash(URI) in c.data(order) and SHA.encode() in c.data(order)
    wallet = c.fund().pubkey()
    assert c.gl_pay(order, wallet), c.err
    assert c.balance(pay.ata(wallet, c.usdc)) == 20 * USDC and c.order(order) is None
    assert c.said("knos3:paid")[0].split()[3] == f"payee={GL_ID + AUTHOR}"


def test_funding_is_refused_off_a_protected_branch_and_from_any_pipeline_nobody_ran_by_hand(c):
    for source, over, want in [
            ("web", {"ref_protected": "false"}, CLAIMS),                       # a branch that is not protected
            ("web", {"ref_type": "tag"}, CLAIMS),
            ("push", {}, CLAIMS),                                              # a push is not a person asking for an order
            ("web", {"runner_environment": "self-hosted"}, CLAIMS),
            ("web", {"ci_config_ref_uri": None, "ci_config_sha": None}, 63),   # the CI file is in another project: GitLab signs null
            ("web", {"user_id": str(NAMESPACE)}, SPENDER_REFUSED),             # user 72 is not namespace 72, and is not listed
            ("web", {"user_id": str(SPENDER + 5)}, SPENDER_REFUSED),
            ("web", {"namespace_id": str(NAMESPACE + 1)}, SPENDER_REFUSED)]:   # another namespace's project
        ok, order = c.gl_fund(issue(), source, **over)
        assert not ok and code(c) == want and c.data(order) is None, (source, over, c.err)


def test_payment_is_refused_from_another_file_another_commit_or_another_kind_of_pipeline(c):
    ok, order = c.gl_fund(issue())
    assert ok, c.err
    wallet = c.fund().pubkey()
    moved = URI.replace(".gitlab-ci.yml", "ci/other.yml")
    main = URI.replace("refs/heads/knos", "refs/heads/main")
    for source, over, want in [
            ("pipeline", {"ci_config_ref_uri": moved}, WORKFLOW),              # another CI file of the same project
            ("pipeline", {"ci_config_sha": "f" * 40}, WORKFLOW),               # the branch moved: not the commit the order pinned
            ("pipeline", {"ci_config_ref_uri": main, "ref": "main", "ref_path": "refs/heads/main"}, WORKFLOW),   # the default branch's own pipeline
            ("pipeline", {"ref_protected": "false"}, CLAIMS),
            ("pipeline", {"ci_config_ref_uri": main}, CLAIMS),                 # a file of a ref the pipeline did not run on
            ("pipeline", {"project_id": str(PROJECT + 1)}, CLAIMS),            # the pinned file, run in another project
            ("web", {}, CLAIMS), ("push", {}, CLAIMS), ("merge_request_event", {}, CLAIMS), ("schedule", {}, CLAIMS)]:
        assert not c.gl_pay(order, wallet, source, **over) and code(c) == want, (source, over, c.err)
    assert c.held(order) > 20 * USDC and c.balance(pay.ata(wallet, c.usdc)) == 0
    # a GitLab token signs nothing else: a take, a ruling, a 2.0 job
    for aud in (f"knos3:take:{order}:{GL_ID + AUTHOR}:1", f"knos3:rule:{order}:{GL_ID + AUTHOR}.10000.{wallet}"):
        tok = c.gl(aud, "pipeline")
        assert not c.send([pay.pay_order_ix(c.payer.pubkey(), tok, c.gl_key, order, c.order(order), [(GL_ID + AUTHOR, wallet)])]) and code(c) == AUD
    assert c.gl_pay(order, wallet), c.err


def test_a_github_token_pays_no_gitlab_order_and_a_gitlab_token_no_github_order(c):
    ok, order = c.gl_fund(issue())
    assert ok, c.err
    o, wallet = c.order(order), c.fund().pubkey()
    payees = [(GL_ID + AUTHOR, 10_000, wallet)]
    # GitHub's prove.yml, run in a repository GitHub numbers 20, and in one it would have to number as the project is read
    for repo, want in ((PROJECT, WORKFLOW), (GL_ID + PROJECT, CLAIMS)):
        assert not c.send([c.pay_ix(order, c.pay_token(order, payees, o=o, repository_id=repo), payees, o=o)]) and code(c) == want, c.err
    # an order of a GitHub repository whose number a GitLab project also has: the project's token is another repository's
    github = c.fund_wallet(repo=REPO)
    assert not c.gl_pay(github, wallet, project_id=str(REPO)) and code(c) == WORKFLOW
    same = issue()
    ix = pay.fund_order_wallet_ix(c.funder.pubkey(), c.funder_tok, c.usdc, PROJECT, same, 20 * USDC, URI, SHA, TERMS)
    assert c.send([ix], c.funder), c.err
    assert not c.gl_pay(ix.accounts[1].pubkey, wallet) and code(c) == CLAIMS          # GitHub repository 20 is not GitLab project 20
    assert c.gl_pay(order, wallet), c.err


def test_no_github_token_carries_an_id_from_gitlabs_ranges(c):
    """A wallet funds an order for GitLab project 20 but pins GitHub workflows (anyone may: it is the wallet's money).
    Only a run GitHub numbered as that project could pay it, and such a number is refused whoever signs it."""
    n = issue()
    order = c.fund_wallet(n, repo=GL_ID + PROJECT)
    o, wallet = c.order(order), c.fund().pubkey()
    payees = [(GL_ID + AUTHOR, 10_000, wallet)]
    assert (o.repo_id, WF_REPO, WF_SHA) == (GL_ID + PROJECT, "drexthealpha/Knos", "c" * 40)
    for over in ({"repository_id": GL_ID + PROJECT}, {"repository_id": GL_NS}, {"repository_id": REPO, "actor_id": GL_ID + AUTHOR},
                 {"repository_id": REPO, "repository_owner_id": GL_NS + NAMESPACE}):
        assert not c.send([c.pay_ix(order, c.pay_token(order, payees, o=o, **over), payees, o=o)]) and code(c) == CLAIMS, (over, c.err)
    # and a GitHub fund token cannot spend the namespace's Balance by calling itself that namespace
    tok = c.gh(pay.order_fund_audience(n, 20 * USDC, pay.MERGE, TH, c.gl_bal), file="fund.yml", event_name="issue_comment", actor_id=GL_ID + SPENDER,
               repository_id=GL_ID + PROJECT, repository_owner_id=GL_NS + NAMESPACE)
    ix = pay.fund_order_balance_ix(c.payer.pubkey(), tok, c.key, c.gl_bal, c.usdc, GL_NS + NAMESPACE, GL_ID + PROJECT, n, TERMS, c.data(tok))
    assert not c.send([ix]) and code(c) == CLAIMS
    # the largest id GitHub could sign is below them, and is read as it always was
    assert c.fund_wallet(repo=GL_NS - 1) is not None
    assert c.held(order) > 20 * USDC and c.balance(pay.ata(wallet, c.usdc)) == 0


def test_a_gitlab_token_is_used_once_like_every_other(c):
    """gl.rs only reads a GitLab token's claims: FundOrderBalance and PayOrder take it through the same code as a
    GitHub token and make the same marker ["used", sha256(signature)]. Neither token works twice, even once the
    order's address is free again or holds a later order."""
    n, wallet, payee = issue(), c.fund().pubkey(), GL_ID + AUTHOR
    fund, second = (c.gl(pay.order_fund_audience(n, 20 * USDC, pay.MERGE, TH, c.gl_bal), "web") for _ in range(2))
    fund_ix, again_ix = (pay.fund_order_balance_ix(c.payer.pubkey(), t, c.gl_key, c.gl_bal, c.usdc, GL_NS + NAMESPACE, GL_ID + PROJECT, n, TERMS, c.data(t))
                         for t in (fund, second))
    order = fund_ix.accounts[7].pubkey
    assert c.send([fund_ix]), c.err
    o = c.order(order)
    tok = c.gl(pay.order_pay_audience(order, HEAD, o.terms, o.mode, 7, [(payee, 10_000, wallet)]), "pipeline", user_id=str(SPENDER + 1))
    pay_ix = pay.pay_order_ix(c.payer.pubkey(), tok, c.gl_key, order, o, [(payee, wallet)])
    assert c.send([pay_ix]) and c.order(order) is None, c.err
    assert not c.send([fund_ix]) and code(c) == 91                        # the fund token again: the address is free, the token is not
    assert c.send([again_ix]) and c.held(order) > 20 * USDC, c.err        # a second comment's token funds a later order there
    assert not c.send([pay_ix]) and code(c) == 91                         # the pay token that paid the first does not pay it
    assert c.balance(pay.ata(wallet, c.usdc)) == 20 * USDC and c.held(order) > 20 * USDC
