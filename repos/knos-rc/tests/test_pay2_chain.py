"""knos-pay, second deployment, in the Solana runtime (LiteSVM) with the second deployment's verifier beside it: a
bounty is funded by one GitHub-signed comment from a prefunded Balance (or by a wallet), its terms fixed at funding,
and paid on a GitHub-signed proof straight to the payee's wallet. Every instruction on its happy path, every refusal,
the record, the pause, Token-2022 mints, what a revoked or expired signing key stops, and a random walk that keeps
each vault equal to its open jobs."""
from __future__ import annotations

import hashlib
import json
import os
import random
import re
from pathlib import Path

import pytest

pytest.importorskip("solders.litesvm")

from solders.account import Account  # noqa: E402
from solders.instruction import AccountMeta, Instruction  # noqa: E402
from solders.keypair import Keypair  # noqa: E402
from solders.pubkey import Pubkey  # noqa: E402
from solders.system_program import CreateAccountParams, create_account  # noqa: E402

from _pay2 import GUARDIAN, TEST_CLAIM_SHA, USDC_KEY, WF_REPO, WF_SHA, Chain, ChainLedger, github_claims  # noqa: E402
from _settle import NOW, modulus, sign_jwt, signing_key  # noqa: E402

from knos.settle.v2 import oidc, pay  # noqa: E402

REPO, OWNER, MAINT, AUTHOR = 987654321, 424242, 555000, 1234567    # the repository, its owner, a maintainer, a contributor
USDC, DAY, HEAD = 1_000_000, 86_400, "a" * 40
TERMS = pay.terms_json({"accept": "", "checks": [{"app": 15368, "name": "test"}], "deny": [".github/**", ".knos/**"], "mode": "merge",
                        "paths": [], "reserve": 7, "v": 1})
TH = pay.terms_hash(TERMS)
FUZZ_N = int(os.environ.get("KNOS_FUZZ_N", "600"))   # read at import: conftest clears KNOS_* per test
FUZZ_SEED = int(os.environ.get("KNOS_FUZZ_SEED", "312"))
_COUNT = [100, 8_000_000]
# the accounts of each instruction, in order, by the names idl/knos_pay_v2.json gives them (tests/test_idl.py holds the
# client to that order)
_IDL = json.loads((Path(__file__).resolve().parents[1] / "idl" / "knos_pay_v2.json").read_text(encoding="utf-8"))
ACCOUNTS = {i["discriminant"]["value"]: [a["name"] for a in i["accounts"]] for i in _IDL["instructions"]}


def issue() -> int:
    _COUNT[0] += 1
    return _COUNT[0]


def user() -> int:
    """A GitHub id nobody has used yet: binds and records are per user, and the tests share one chain."""
    _COUNT[1] += 1
    return _COUNT[1]


def code(c: Chain) -> int | None:
    m = re.search(r"Custom\((\d+)\)", c.err or "")
    return int(m.group(1)) if m else None


def account(ix: Instruction, name: str) -> Pubkey:
    """The account of an instruction that the IDL calls `name`."""
    return ix.accounts[ACCOUNTS[bytes(ix.data)[0]].index(name)].pubkey


def swap(ix: Instruction, name: str, key: Pubkey) -> Instruction:
    """The same instruction with one account replaced: the one the IDL calls `name`."""
    index = ACCOUNTS[bytes(ix.data)[0]].index(name)
    acc = list(ix.accounts)
    acc[index] = AccountMeta(key, acc[index].is_signer, acc[index].is_writable)
    return Instruction(ix.program_id, bytes(ix.data), acc)


def pay_ix(c: Chain, relayer: Pubkey, tok: Pubkey, *args, **kw) -> Instruction:
    """pay.pay_ix with the token's single-use marker, read from its token account."""
    return pay.pay_ix(relayer, tok, *args, used=c.data(tok), **kw)


def transfer(c: Chain, source: Pubkey, dest: Pubkey, amount: int, owner: Keypair, mint: Pubkey | None = None) -> None:
    """A plain TransferChecked, as any wallet would send it."""
    mint = mint or c.usdc
    ix = Instruction(c.token_program(mint), bytes([12]) + amount.to_bytes(8, "little") + bytes([6]),
                     [AccountMeta(source, False, True), AccountMeta(mint, False, False), AccountMeta(dest, False, True), AccountMeta(owner.pubkey(), True, False)])
    assert c.send([ix], signers=[owner]), c.err


def setup(c: Chain) -> Chain:
    """A stand-in for USDC, the fee account, the repository owner's Balance (the owner and one maintainer spend it by
    comment) and a sponsor's wallet."""
    c.usdc = c.new_mint(keypair=USDC_KEY)
    c.fee = c.token_account(pay.FEE_OWNER, c.usdc)
    c.owner, c.owner_tok = c.wallet(c.usdc, 1_000_000 * USDC)
    assert c.send([pay.open_balance_ix(c.owner.pubkey(), OWNER, c.usdc, spenders=[MAINT])], c.owner), c.err
    c.bal = pay.balance_pda(OWNER, c.owner.pubkey(), c.usdc)
    transfer(c, c.owner_tok, pay.baltok_pda(c.bal), 100_000 * USDC, c.owner)
    c.funder, c.funder_tok = c.wallet(c.usdc, 1_000_000 * USDC)
    return c


@pytest.fixture(scope="module")
def chain():
    c = setup(Chain())
    assert c.send([pay.init_faucet_ix(c.payer.pubkey())], tag="init_faucet"), c.err
    c.test_usdc = pay.faucet_mint()
    c.token_account(pay.FEE_OWNER, c.test_usdc)
    # a second wallet's Balance for the same owner, holding little; and the wallet a contributor asks to be paid at
    w, wtok = c.wallet(c.usdc, 50 * USDC)
    assert c.send([pay.open_balance_ix(w.pubkey(), OWNER, c.usdc, spenders=[MAINT])], w), c.err
    c.small = pay.balance_pda(OWNER, w.pubkey(), c.usdc)
    transfer(c, wtok, pay.baltok_pda(c.small), 50 * USDC, w)
    c.wallet_of_author = Keypair().pubkey()
    c.token_account(c.wallet_of_author, c.usdc)
    return c


def fund_token(c: Chain, n: int, amount: int = 5 * USDC, mode: int = pay.MERGE, terms: bytes = TH, work: int = 14 * DAY, actor: int = MAINT,
               balance: Pubkey | None = None, **over):
    """What fund.yml asks GitHub to sign when a maintainer comments `/knos fund` on issue n: the workflow names the
    Balance the comment spends (default: the owner's)."""
    c.warp(1)       # a Balance takes its fund tokens in the order GitHub issued them
    return c.gh(pay.fund_audience(n, amount, mode, terms, balance or c.bal, work), **{"file": "fund.yml", "event_name": "issue_comment", "actor_id": actor, **over})


def faucet_token(c: Chain, n: int, org: int, repo: int, amount: int = 5 * USDC, **over):
    """The fund token of a comment in a repository whose owner has no Balance: on devnet the workflow names the owner's
    faucet Balance."""
    return fund_token(c, n, amount, balance=pay.faucet_balance_pda(org), repository_owner_id=org, repository_id=repo, **over)


def fund_balance(c: Chain, n: int | None = None, amount: int = 5 * USDC, balance: Pubkey | None = None, terms: bytes = TERMS, repo: int = REPO, **kw) -> Pubkey:
    """A comment funds issue n from a Balance (default: the owner's). Returns the job's address."""
    n, balance = n or issue(), balance or c.bal
    mint = pay.read_balance(c.data(balance)).mint
    tok = fund_token(c, n, amount, terms=pay.terms_hash(terms), balance=balance, **kw)
    assert c.send([pay.fund_balance_ix(c.payer.pubkey(), tok, c.key, balance, mint, repo, n, terms, c.token_program(mint))], tag="fund_balance"), c.err
    return pay.job_pda(repo, n, balance)


def fund_wallet(c: Chain, n: int | None = None, amount: int = 5 * USDC, funder: Keypair | None = None, funder_tok: Pubkey | None = None,
                mint: Pubkey | None = None, **kw) -> Pubkey:
    """A wallet (default: the sponsor's) funds issue n with its own money. Returns the job's address."""
    n, f, mint = n or issue(), funder or c.funder, mint or c.usdc
    ix = pay.fund_wallet_ix(f.pubkey(), funder_tok or c.funder_tok, mint, REPO, n, amount, WF_REPO, WF_SHA, kw.pop("terms", TERMS),
                            token_program=c.token_program(mint), **kw)
    assert c.send([ix], f, tag="fund_wallet"), c.err
    return pay.job_pda(REPO, n, f.pubkey())


def pay_token(c: Chain, job: Pubkey, payee: int = AUTHOR, address: Pubkey | None = None, **over):
    """What the job's pinned prove.yml asks GitHub to sign once the merged pull request met the funded terms."""
    j = pay.read_job(c.data(job))
    aud = dict(repo_id=j.repo_id, issue=j.issue, payee_id=payee, head_sha=HEAD, terms=j.terms, mode=j.mode, address=address)
    aud.update({k: over.pop(k) for k in list(over) if k in aud})
    return c.gh(pay.pay_audience(**aud), **{"repository_id": j.repo_id, **over})


def do_pay(c: Chain, job: Pubkey, tok: Pubkey, payee: int = AUTHOR, wallet: Pubkey | None = None, tag: str | None = None) -> bool:
    j = pay.read_job(c.data(job))
    if wallet is not None:
        c.token_account(wallet, j.mint)
    return c.send([pay_ix(c, c.payer.pubkey(), tok, c.key, job, j, payee, wallet)], tag=tag)


def proven(c: Chain, job: Pubkey, payee: int = AUTHOR, wallet: Pubkey | None = None, tag: str | None = None) -> Pubkey:
    """The proof arrives and the job is paid to `wallet`, the address the payee gave in the pull request."""
    wallet = wallet or Keypair().pubkey()
    assert do_pay(c, job, pay_token(c, job, payee, wallet), payee, wallet, tag), c.err
    return wallet


def bind_token(c: Chain, who: int, wallet, **over):
    """What the pinned claim workflow asks GitHub to sign when `who` runs it in their own repository named knos-claim."""
    c.warp(1)
    claims = dict(file="claim.yml", wf_repo="drexthealpha/knos-oidc-rotate", wf_sha=TEST_CLAIM_SHA, event_name="workflow_dispatch",
                  actor_id=who, repository_owner_id=who, repository=f"user{who}/knos-claim", repository_id=70_000_000 + who % 1_000_000)
    claims.update(over)
    return c.gh(wallet if isinstance(wallet, str) else pay.bind_audience(wallet), **claims)


def bind(c: Chain, who: int, wallet, **over) -> bool:
    return c.send([pay.bind_ix(c.payer.pubkey(), bind_token(c, who, wallet, **over), c.key, who)], tag="bind")


def refund(c: Chain, job: Pubkey, dest: Pubkey | None = None) -> bool:
    return c.send([pay.refund_ix(c.payer.pubkey(), job, pay.read_job(c.data(job)), dest)], tag="refund")


def other_key(c: Chain) -> Pubkey:
    """Another key of the verifier's, registered and as good as GitHub's: the 4096-bit seed key, which the test build
    trusts as GitLab's."""
    n = modulus(signing_key(4096))
    if c.data(oidc.key_pda(oidc.GITLAB, n)) is None:
        assert c.register(oidc.GITLAB, n), c.err
    return oidc.key_pda(oidc.GITLAB, n)


# -- balances ---------------------------------------------------------------------------------------------------------
def test_a_wallet_opens_a_balance_for_a_repository_owner_and_anyone_adds_money(chain):
    c = chain
    w, _tok = c.wallet(c.usdc)
    org = user()
    assert c.send([pay.open_balance_ix(w.pubkey(), org, c.usdc, cap=20 * USDC, spenders=[MAINT, 9])], w, tag="open_balance"), c.err
    bal = pay.balance_pda(org, w.pubkey(), c.usdc)
    assert pay.read_balance(c.data(bal)) == pay.Balance(faucet=False, owner_id=org, authority=w.pubkey(), mint=c.usdc, cap_per_job=20 * USDC,
                                                        last_iat=0, spenders=(MAINT, 9), spent=0)
    assert c.said("knos2:") == [f"knos2:balance owner={org} authority={w.pubkey()} mint={c.usdc}"]
    # its token account is the program's (nobody's key signs for it), of this mint, and empty
    baltok = pay.baltok_pda(bal)
    d = c.data(baltok)
    assert (Pubkey.from_bytes(d[0:32]), Pubkey.from_bytes(d[32:64]), c.balance(baltok)) == (c.usdc, pay.auth_pda(), 0)
    # anyone adds money with a plain transfer
    stranger, stok = c.wallet(c.usdc, 7 * USDC)
    transfer(c, stok, baltok, 7 * USDC, stranger)
    assert c.balance(baltok) == 7 * USDC
    # a wallet has one Balance per owner and mint; another wallet opens its own for the same owner; owner 0 is nobody
    assert not c.send([pay.open_balance_ix(w.pubkey(), org, c.usdc)], w) and code(c) == 98
    assert c.send([pay.open_balance_ix(stranger.pubkey(), org, c.usdc)], stranger), c.err
    assert not c.send([pay.open_balance_ix(w.pubkey(), 0, c.usdc)], w) and code(c) == 81
    # the accounts are the ones the program derives: another wallet's Balance address, or another token account, is refused
    ix = pay.open_balance_ix(w.pubkey(), user(), c.usdc)
    assert not c.send([swap(ix, "balance", bal)], w) and code(c) == 98
    assert not c.send([swap(ix, "baltok", baltok)], w) and code(c) == 80
    assert not c.send([swap(ix, "auth", w.pubkey())], w) and code(c) == 80
    assert c.send([ix], w), c.err


def test_only_the_wallet_that_opened_a_balance_changes_its_cap_and_spenders(chain):
    c = chain
    w, _tok = c.wallet(c.usdc)
    org = user()
    assert c.send([pay.open_balance_ix(w.pubkey(), org, c.usdc)], w), c.err
    bal = pay.balance_pda(org, w.pubkey(), c.usdc)
    assert c.send([pay.set_balance_ix(w.pubkey(), bal, cap=3 * USDC, spenders=[7, 8, 9, 10])], w, tag="set_balance"), c.err
    b = pay.read_balance(c.data(bal))
    assert (b.cap_per_job, b.spenders, b.owner_id, b.authority) == (3 * USDC, (7, 8, 9, 10), org, w.pubkey())
    assert c.send([pay.set_balance_ix(w.pubkey(), bal)], w), c.err
    b = pay.read_balance(c.data(bal))
    assert (b.cap_per_job, b.spenders) == (0, ())
    thief = c.fund()
    assert not c.send([pay.set_balance_ix(thief.pubkey(), bal, spenders=[666])], thief) and code(c) == 98
    # the authority's key without its signature, and an account that is not a Balance
    ix = pay.set_balance_ix(w.pubkey(), bal, spenders=[666])
    unsigned = Instruction(ix.program_id, bytes(ix.data), [AccountMeta(w.pubkey(), False, False), AccountMeta(bal, False, True)])
    assert not c.send([unsigned]) and code(c) == 98
    assert not c.send([pay.set_balance_ix(w.pubkey(), pay.baltok_pda(bal))], w) and code(c) == 98
    with pytest.raises(ValueError):
        pay.set_balance_ix(w.pubkey(), bal, spenders=[1, 2, 3, 4, 5])


def test_unspent_money_goes_back_only_to_the_wallet_that_opened_the_balance(chain):
    c = chain
    w, wtok = c.wallet(c.usdc, 100 * USDC)
    org = user()
    assert c.send([pay.open_balance_ix(w.pubkey(), org, c.usdc)], w), c.err
    bal = pay.balance_pda(org, w.pubkey(), c.usdc)
    baltok = pay.baltok_pda(bal)
    transfer(c, wtok, baltok, 100 * USDC, w)
    thief, ttok = c.wallet(c.usdc)
    # nobody else withdraws, whatever destination they name
    assert not c.send([pay.withdraw_ix(thief.pubkey(), bal, c.usdc, 0, ttok)], thief) and code(c) == 98
    assert not c.send([pay.withdraw_ix(thief.pubkey(), bal, c.usdc, 0, wtok)], thief) and code(c) == 98
    ix = pay.withdraw_ix(w.pubkey(), bal, c.usdc, 0, ttok)
    unsigned = Instruction(ix.program_id, bytes(ix.data), [AccountMeta(w.pubkey(), False, False), *ix.accounts[1:]])
    assert not c.send([unsigned], thief) and code(c) == 98
    # the authority withdraws only to a token account of its own
    assert not c.send([pay.withdraw_ix(w.pubkey(), bal, c.usdc, 0, ttok)], w) and code(c) == 88
    assert not c.send([pay.withdraw_ix(w.pubkey(), bal, c.usdc, 0, pay.vault_pda(c.usdc))], w) and code(c) == 88
    assert not c.send([pay.withdraw_ix(w.pubkey(), bal, c.usdc, 101 * USDC)], w) and code(c) == 94
    # an account posing as the thief's Balance at an address the program never derived: the same bytes, another authority
    real = c.svm.get_account(bal)
    forged = bytes(real.data[:16]) + bytes(thief.pubkey()) + bytes(real.data[48:])
    posing = Keypair().pubkey()
    c.svm.set_account(posing, Account(lamports=real.lamports, data=forged, owner=pay.PAY_ID, executable=False))
    assert not c.send([swap(pay.withdraw_ix(thief.pubkey(), posing, c.usdc, 0, ttok), "baltok", baltok)], thief) and code(c) == 98
    # not from another Balance's token account, and not through another mint
    ix = pay.withdraw_ix(w.pubkey(), bal, c.usdc, 0)
    assert not c.send([swap(ix, "baltok", pay.baltok_pda(c.bal))], w) and code(c) == 80
    assert not c.send([swap(ix, "mint", c.test_usdc)], w) and code(c) == 80
    assert c.send([pay.withdraw_ix(w.pubkey(), bal, c.usdc, 30 * USDC)], w, tag="withdraw"), c.err
    assert (c.balance(wtok), c.balance(baltok)) == (30 * USDC, 70 * USDC)
    assert c.said("knos2:") == [f"knos2:withdrawn owner={org} authority={w.pubkey()} mint={c.usdc} amount={30 * USDC}"]
    other = Keypair()                                   # any token account of the authority's will do, not only the associated one
    ixs = [create_account(CreateAccountParams(from_pubkey=c.payer.pubkey(), to_pubkey=other.pubkey(), lamports=c.svm.minimum_balance_for_rent_exemption(165),
                                              space=165, owner=pay.TOKEN)),
           Instruction(pay.TOKEN, bytes([18]) + bytes(w.pubkey()), [AccountMeta(other.pubkey(), False, True), AccountMeta(c.usdc, False, False)])]
    assert c.send(ixs, signers=[other]), c.err
    assert c.send([pay.withdraw_ix(w.pubkey(), bal, c.usdc, 0, other.pubkey())], w), c.err     # 0: everything
    assert (c.balance(other.pubkey()), c.balance(baltok)) == (70 * USDC, 0)


# -- funding by one comment ----------------------------------------------------------------------------------------------
def test_one_comment_funds_a_job_from_the_owners_balance(chain):
    c = chain
    n = issue()
    before, baltok0, vault0 = pay.read_balance(c.data(c.bal)), c.balance(pay.baltok_pda(c.bal)), c.balance(pay.vault_pda(c.usdc))
    tok = fund_token(c, n, 5 * USDC, work=7 * DAY)
    assert c.send([pay.fund_balance_ix(c.payer.pubkey(), tok, c.key, c.bal, c.usdc, REPO, n, TERMS)], tag="fund_balance"), c.err
    job = pay.job_pda(REPO, n, c.bal)
    assert pay.read_job(c.data(job)) == pay.Job(
        state="open", mode=pay.MERGE, from_balance=True, token_program=pay.TOKEN, faucet=False, repo_id=REPO, issue=n, amount=5 * USDC,
        deadline=c.now() + 7 * DAY, hold_until=0, payee_id=0, funder_id=MAINT, not_before=c.now(), owner_id=OWNER, source=c.bal,
        refund_to=pay.baltok_pda(c.bal), rent_to=c.payer.pubkey(), mint=c.usdc, terms=TH, wf_repo_hash=pay.wf_repo_hash(WF_REPO), wf_sha=WF_SHA)
    # the terms are public: the transaction's log carries the JSON whose hash the job stores
    assert c.said("knos2:") == [f"knos2:funded repo={REPO} issue={n} amount={5 * USDC} mode=0 by={MAINT} source={c.bal} faucet=0",
                                "knos2:terms " + TERMS.decode()]
    after = pay.read_balance(c.data(c.bal))
    assert (after.last_iat, after.spent - before.spent) == (c.now(), 5 * USDC)
    assert c.balance(pay.baltok_pda(c.bal)) == baltok0 - 5 * USDC and c.balance(pay.vault_pda(c.usdc)) == vault0 + 5 * USDC
    # an issue event (the bounty written into a new issue) funds too
    n2 = issue()
    tok = fund_token(c, n2, event_name="issues", actor=OWNER, mode=pay.TESTS)
    assert c.send([pay.fund_balance_ix(c.payer.pubkey(), tok, c.key, c.bal, c.usdc, REPO, n2, TERMS)]), c.err
    j = pay.read_job(c.data(pay.job_pda(REPO, n2, c.bal)))
    assert (j.mode, j.funder_id, j.owner_id) == (pay.TESTS, OWNER, OWNER)


def test_a_fund_token_works_once(chain):
    c = chain
    n_old, n = issue(), issue()
    old = fund_token(c, n_old)                          # a comment whose token nobody carried yet
    c.warp(1)
    # the comment's token as GitHub signed it: public, so anyone can have it verified into an account of their own
    aud = pay.fund_audience(n, 5 * USDC, pay.MERGE, TH, c.bal)
    claims = github_claims(aud=aud, iat=c.now(), nbf=c.now() - 600, exp=c.now() + 300, jti=f"once{n}", actor_id=MAINT, event_name="issue_comment",
                           job_workflow_ref=f"{WF_REPO}/.github/workflows/fund.yml@refs/tags/v0.3.12", job_workflow_sha=WF_SHA)
    jwt = sign_jwt(signing_key(), claims)
    tok = c.verify(jwt, oidc.GITHUB, c.github)
    send = lambda t=tok, i=n: c.send([pay.fund_balance_ix(c.payer.pubkey(), t, c.key, c.bal, c.usdc, REPO, i, TERMS)])  # noqa: E731
    before = c.balance(pay.baltok_pda(c.bal))
    assert send(), c.err
    assert not send() and code(c) == 91                 # while its job is open
    job = pay.job_pda(REPO, n, c.bal)
    proven(c, job)
    assert c.data(job) is None
    assert not send() and code(c) == 91                 # and after the job was paid, still inside the token's hour
    # the same token verified again, into another payer's account, is the same token
    again = c.verify(jwt, oidc.GITHUB, c.github, c.fund())
    assert again != tok and oidc.read_token(c.data(again)).verified
    assert not send(again) and code(c) == 91
    # a Balance takes its tokens in the order GitHub issued them: the older comment's token came too late
    assert not send(old, n_old) and code(c) == 91
    assert c.balance(pay.baltok_pda(c.bal)) == before - 5 * USDC
    # the next comment funds as ever
    n2 = issue()
    assert send(fund_token(c, n2), n2), c.err


def test_a_fund_token_spends_only_the_balance_it_names(chain):
    """The funder's workflow names the Balance in the audience GitHub signs. A relayer cannot point the token at another
    Balance, however willing that one is: the same owner's, listing the same maintainer, in the same mint or another."""
    c = chain
    other = c.new_mint()
    w, wtok = c.wallet(other, 100 * USDC)
    assert c.send([pay.open_balance_ix(w.pubkey(), OWNER, other, spenders=[MAINT])], w), c.err
    second = pay.balance_pda(OWNER, w.pubkey(), other)
    transfer(c, wtok, pay.baltok_pda(second), 100 * USDC, w, other)
    n = issue()
    early = fund_token(c, n, balance=second)             # a comment that spends the second Balance, not carried yet
    tok = fund_token(c, n)                               # the next comment names the owner's Balance
    small0, second0 = c.balance(pay.baltok_pda(c.small)), c.balance(pay.baltok_pda(second))
    assert not c.send([pay.fund_balance_ix(c.payer.pubkey(), tok, c.key, c.small, c.usdc, REPO, n, TERMS)]) and code(c) == 87
    assert not c.send([pay.fund_balance_ix(c.payer.pubkey(), tok, c.key, second, other, REPO, n, TERMS)]) and code(c) == 87
    assert (c.balance(pay.baltok_pda(c.small)), c.balance(pay.baltok_pda(second))) == (small0, second0)
    assert c.data(pay.job_pda(REPO, n, c.small)) is None and c.data(pay.job_pda(REPO, n, second)) is None
    assert c.send([pay.fund_balance_ix(c.payer.pubkey(), tok, c.key, c.bal, c.usdc, REPO, n, TERMS)]), c.err
    # each Balance keeps its own order: the earlier comment still spends the Balance it names, once
    assert not c.send([pay.fund_balance_ix(c.payer.pubkey(), early, c.key, c.bal, c.usdc, REPO, n, TERMS)]) and code(c) == 87
    assert c.send([pay.fund_balance_ix(c.payer.pubkey(), early, c.key, second, other, REPO, n, TERMS)]), c.err
    assert not c.send([pay.fund_balance_ix(c.payer.pubkey(), early, c.key, second, other, REPO, n, TERMS)]) and code(c) == 91
    assert {pay.read_job(c.data(pay.job_pda(REPO, n, b))).mint for b in (c.bal, second)} == {c.usdc, other}
    assert c.balance(pay.baltok_pda(second)) == second0 - 5 * USDC


def test_only_the_owner_and_the_listed_spenders_spend_a_balance(chain):
    c = chain
    n = issue()
    send = lambda t, i=n: c.send([pay.fund_balance_ix(c.payer.pubkey(), t, c.key, c.bal, c.usdc, REPO, i, TERMS)])  # noqa: E731
    # a contributor's comment, even through the repository's own fund.yml, spends nothing
    assert not send(fund_token(c, n, actor=AUTHOR)) and code(c) == 92
    assert send(fund_token(c, n, actor=OWNER)), c.err                         # the owner's comment does
    n = issue()
    assert c.send([pay.set_balance_ix(c.owner.pubkey(), c.bal, spenders=[777])], c.owner), c.err
    assert not send(fund_token(c, n, actor=MAINT), n) and code(c) == 92      # no longer listed
    assert send(fund_token(c, n, actor=777), n), c.err
    assert c.send([pay.set_balance_ix(c.owner.pubkey(), c.bal, spenders=[MAINT])], c.owner), c.err
    n = issue()
    assert send(fund_token(c, n, actor=MAINT), n), c.err


def test_a_cap_per_job_is_enforced(chain):
    c = chain
    w, wtok = c.wallet(c.usdc, 100 * USDC)
    assert c.send([pay.open_balance_ix(w.pubkey(), OWNER, c.usdc, cap=10 * USDC)], w), c.err
    bal = pay.balance_pda(OWNER, w.pubkey(), c.usdc)
    transfer(c, wtok, pay.baltok_pda(bal), 100 * USDC, w)
    n = issue()
    send = lambda amount: c.send([pay.fund_balance_ix(c.payer.pubkey(), fund_token(c, n, amount, actor=OWNER, balance=bal), c.key, bal, c.usdc, REPO, n, TERMS)])  # noqa: E731
    assert not send(10 * USDC + 1) and code(c) == 93
    assert send(10 * USDC), c.err
    assert c.send([pay.set_balance_ix(w.pubkey(), bal, cap=0)], w), c.err   # 0: no cap
    n = issue()
    assert send(11 * USDC), c.err


def test_a_comment_in_another_owners_repository_cannot_spend_a_balance(chain):
    c = chain
    n = issue()
    # the maintainer is a listed spender, and fund.yml is the pinned one, but the run was in a repository someone else owns
    tok = fund_token(c, n, actor=MAINT, repository_owner_id=999_999, repository_id=555_555, repository="evil/widgets")
    before = c.balance(pay.baltok_pda(c.bal))
    assert not c.send([pay.fund_balance_ix(c.payer.pubkey(), tok, c.key, c.bal, c.usdc, 555_555, n, TERMS)]) and code(c) == 92
    # the owner's own account commenting in someone else's repository is no better
    tok = fund_token(c, n, actor=OWNER, repository_owner_id=999_999, repository_id=555_555, repository="evil/widgets")
    assert not c.send([pay.fund_balance_ix(c.payer.pubkey(), tok, c.key, c.bal, c.usdc, 555_555, n, TERMS)]) and code(c) == 92
    assert c.balance(pay.baltok_pda(c.bal)) == before


def _long_terms(size: int) -> bytes:
    """A terms JSON of exactly `size` bytes."""
    raw = b'{"paths":["' + b"x" * (size - 20) + b'"],"v":1}'
    assert len(raw) == size
    return raw


def _forged(c: Chain, real: Pubkey, owner: Pubkey = pay.PAY_ID) -> Pubkey:
    """An account at an address of its own that holds the bytes of `real`, owned by `owner`."""
    a = c.svm.get_account(real)
    fake = Keypair().pubkey()
    c.svm.set_account(fake, Account(lamports=a.lamports, data=bytes(a.data), owner=owner, executable=False))
    return fake


def _raw_fund(c: Chain, aud: str):
    """A fund token whose audience is written by hand."""
    c.warp(1)
    return c.gh(aud, file="fund.yml", event_name="issue_comment", actor_id=MAINT)


# what is wrong -> (the fund token, the terms JSON sent, a change to the instruction's accounts or None, the refusal)
FUND_REFUSALS = {
    "a token from prove.yml": (lambda c, n: fund_token(c, n, file="prove.yml"), TERMS, None, 86),
    "an event that is neither a comment nor an issue": (lambda c, n: fund_token(c, n, event_name="workflow_dispatch"), TERMS, None, 85),
    "a pull request event": (lambda c, n: fund_token(c, n, event_name="pull_request_target"), TERMS, None, 85),
    "a self-hosted runner": (lambda c, n: fund_token(c, n, runner_environment="self-hosted"), TERMS, None, 85),
    "a re-run of the commenter's run": (lambda c, n: fund_token(c, n, run_attempt=2), TERMS, None, 85),
    "a pay audience": (lambda c, n: _raw_fund(c, pay.pay_audience(REPO, n, AUTHOR, HEAD, TH, 0)), TERMS, None, 87),
    "a first-deployment audience": (lambda c, n: _raw_fund(c, f"knos:fund:{n}:5000000:0:{TH.hex()}:1209600:0"), TERMS, None, 87),
    "a mode that is neither merge nor tests": (lambda c, n: fund_token(c, n, mode=2), TERMS, None, 87),
    "a terms hash that is not 64 hex characters": (lambda c, n: _raw_fund(c, f"knos2:fund:{n}:5000000:0:{TH.hex()[:62]}:1209600:{c.bal}"), TERMS, None, 87),
    "an audience that names no balance": (lambda c, n: _raw_fund(c, f"knos2:fund:{n}:5000000:0:{TH.hex()}:1209600"), TERMS, None, 87),
    "an audience that names another balance": (lambda c, n: fund_token(c, n, balance=c.small), TERMS, None, 87),
    "a balance address that is not the way Solana prints it": (lambda c, n: _raw_fund(c, f"knos2:fund:{n}:5000000:0:{TH.hex()}:1209600:1{c.bal}"), TERMS, None, 87),
    "something after the balance": (lambda c, n: _raw_fund(c, pay.fund_audience(n, 5 * USDC, 0, TH, c.bal) + ":x"), TERMS, None, 87),
    "less than the smallest bounty": (lambda c, n: fund_token(c, n, pay.MIN_AMOUNT - 1), TERMS, None, 81),
    "more than the largest bounty": (lambda c, n: fund_token(c, n, pay.MAX_AMOUNT + 1), TERMS, None, 81),
    "less than a minute to do the work": (lambda c, n: fund_token(c, n, work=59), TERMS, None, 81),
    "more than 90 days to do the work": (lambda c, n: fund_token(c, n, work=pay.MAX_WORK + 1), TERMS, None, 81),
    "terms that are not the ones GitHub signed for": (lambda c, n: fund_token(c, n), TERMS.replace(b'"test"', b'"lint"'), None, 81),
    "no terms": (lambda c, n: fund_token(c, n, terms=hashlib.sha256(b"").digest()), b"", None, 81),
    "terms over 600 bytes": (lambda c, n: fund_token(c, n, terms=pay.terms_hash(_long_terms(601))), _long_terms(601), None, 81),
    "terms that would break the log line": (lambda c, n: fund_token(c, n, terms=pay.terms_hash(TERMS + b"\nknos2:paid")), TERMS + b"\nknos2:paid", None, 81),
    "more than the balance holds": (lambda c, n: fund_token(c, n, 50 * USDC + 1, balance=c.small), TERMS, "small balance", 94),
    "another key of the verifier's": (lambda c, n: fund_token(c, n), TERMS, ("key", other_key), 80),
    "the key's bytes in an account that is not the verifier's": (lambda c, n: fund_token(c, n), TERMS, ("key", lambda c: _forged(c, c.key)), 80),
    "another balance's token account": (lambda c, n: fund_token(c, n), TERMS, ("baltok", lambda c: pay.baltok_pda(c.small)), 80),
    "another mint": (lambda c, n: fund_token(c, n), TERMS, ("mint", lambda c: c.test_usdc), 80),
    "another mint's vault": (lambda c, n: fund_token(c, n), TERMS, ("vault", lambda c: pay.vault_pda(c.test_usdc)), 80),
    "an authority that is not the program's": (lambda c, n: fund_token(c, n), TERMS, ("auth", lambda c: c.payer.pubkey()), 80),
    "the other token program": (lambda c, n: fund_token(c, n), TERMS, ("tokenProgram", lambda c: pay.TOKEN_2022), 95),
    "an account in place of the pause": (lambda c, n: fund_token(c, n), TERMS, ("pause", lambda c: Keypair().pubkey()), 80),
    "another issue's job address": (lambda c, n: fund_token(c, n), TERMS, ("job", lambda c: pay.job_pda(REPO, 1, c.bal)), 82),
    "an account that is not a balance": (lambda c, n: fund_token(c, n), TERMS, ("balance", lambda c: pay.baltok_pda(c.bal)), 98),
}


@pytest.mark.parametrize("what", list(FUND_REFUSALS))
def test_a_comment_does_not_fund_with(chain, what):
    c = chain
    make, terms, change, want = FUND_REFUSALS[what]
    n = issue()
    bal = c.small if change == "small balance" else c.bal
    before, vault = c.balance(pay.baltok_pda(bal)), c.balance(pay.vault_pda(c.usdc))
    ix = pay.fund_balance_ix(c.payer.pubkey(), make(c, n), c.key, bal, c.usdc, REPO, n, terms)
    if isinstance(change, tuple):
        ix = swap(ix, change[0], change[1](c))
    assert not c.send([ix]), f"{what}: accepted"
    assert code(c) == want, f"{what}: {c.err}, wanted {want}"
    assert (c.balance(pay.baltok_pda(bal)), c.balance(pay.vault_pda(c.usdc))) == (before, vault) and c.data(pay.job_pda(REPO, n, bal)) is None


def test_an_issue_has_one_job_per_balance_and_a_relayer_must_sign(chain):
    c = chain
    n = issue()
    fund_balance(c, n)
    tok = fund_token(c, n)
    assert not c.send([pay.fund_balance_ix(c.payer.pubkey(), tok, c.key, c.bal, c.usdc, REPO, n, TERMS)]) and code(c) == 82
    ix = pay.fund_balance_ix(c.payer.pubkey(), tok, c.key, c.bal, c.usdc, REPO, issue(), TERMS)
    unsigned = Instruction(ix.program_id, bytes(ix.data), [AccountMeta(c.funder.pubkey(), False, True), *ix.accounts[1:]])
    assert not c.send([unsigned]) and code(c) == 80


def test_terms_of_600_bytes_fit_in_one_transaction_with_the_faucet(chain):
    c = chain

    def both(terms: bytes):
        n, org, repo = issue(), user(), user()
        tok = faucet_token(c, n, org, repo, terms=pay.terms_hash(terms))
        return [pay.faucet_open_ix(c.payer.pubkey(), tok, c.key, org, repo),
                pay.fund_balance_ix(c.payer.pubkey(), tok, c.key, pay.faucet_balance_pda(org), c.test_usdc, repo, n, terms)]
    # The token's marker is one more account in both instructions (33 bytes). With the compute budget instruction the
    # harness adds, the two fit a transaction's 1232 bytes for terms of up to 575 bytes, and exactly then.
    terms = _long_terms(pay.MAX_TERMS - 25)
    assert c.send(both(terms)), c.err
    assert c.said("knos2:terms") == ["knos2:terms " + terms.decode()] and c.size == 1232
    # Longer terms: the faucet goes in a transaction of its own first (its marker says MINTED), then the funding,
    # which takes the token the faucet has minted on and uses it up.
    terms = _long_terms(pay.MAX_TERMS)
    faucet, fund = both(terms)
    assert c.send([faucet]) and c.data(pay.used_pda(c.data(faucet.accounts[1].pubkey)))[0] == pay.MINTED, c.err
    assert c.send([fund]) and c.size == 1210 <= 1232, c.err          # 22 bytes are left: a priority fee (12) still fits
    assert c.said("knos2:terms") == ["knos2:terms " + terms.decode()] and pay.spent(c.data(pay.used_pda(c.data(faucet.accounts[1].pubkey))))
    job = fund_wallet(c, terms=terms)
    assert pay.read_job(c.data(job)).terms == pay.terms_hash(terms) and c.size < 1232


# -- funding by a wallet -------------------------------------------------------------------------------------------------
def test_a_wallet_funds_a_job_with_its_own_money(chain):
    c = chain
    n = issue()
    before, vault0 = c.balance(c.funder_tok), c.balance(pay.vault_pda(c.usdc))
    ix = pay.fund_wallet_ix(c.funder.pubkey(), c.funder_tok, c.usdc, REPO, n, 20 * USDC, WF_REPO, WF_SHA, TERMS, mode=pay.TESTS, work_s=3 * DAY)
    assert c.send([ix], c.funder, tag="fund_wallet"), c.err
    job = pay.job_pda(REPO, n, c.funder.pubkey())
    assert pay.read_job(c.data(job)) == pay.Job(
        state="open", mode=pay.TESTS, from_balance=False, token_program=pay.TOKEN, faucet=False, repo_id=REPO, issue=n, amount=20 * USDC,
        deadline=c.now() + 3 * DAY, hold_until=0, payee_id=0, funder_id=0, not_before=c.now() - pay.CLOCK_SLACK, owner_id=0, source=c.funder.pubkey(),
        refund_to=c.funder.pubkey(), rent_to=c.funder.pubkey(), mint=c.usdc, terms=TH, wf_repo_hash=pay.wf_repo_hash(WF_REPO), wf_sha=WF_SHA)
    assert c.said("knos2:") == [f"knos2:funded repo={REPO} issue={n} amount={20 * USDC} mode=1 by=0 source={c.funder.pubkey()} faucet=0",
                                "knos2:terms " + TERMS.decode()]
    assert c.balance(c.funder_tok) == before - 20 * USDC and c.balance(pay.vault_pda(c.usdc)) == vault0 + 20 * USDC
    # the same wallet has one job per issue; a second wallet adds its own bounty to the same issue
    assert not c.send([ix], c.funder) and code(c) == 82
    other, otok = c.wallet(c.usdc, 10 * USDC)
    assert pay.read_job(c.data(fund_wallet(c, n, 10 * USDC, other, otok))).source == other.pubkey()
    # a wallet cannot fund from a token account it has no authority over (the token program refuses)
    thief, _ttok = c.wallet(c.usdc)
    assert not c.send([pay.fund_wallet_ix(thief.pubkey(), c.funder_tok, c.usdc, REPO, issue(), 5 * USDC, WF_REPO, WF_SHA, TERMS)], thief)
    assert c.balance(c.funder_tok) == before - 20 * USDC
    # the job's rent is the funder's, and comes back when the job closes
    sol0 = c.lamports(c.funder.pubkey())
    proven(c, job)
    assert c.lamports(c.funder.pubkey()) - sol0 == c.svm.minimum_balance_for_rent_exemption(pay.JOB_LEN) == 3_118_080


WALLET_REFUSALS = {
    "less than the smallest bounty": (dict(amount=pay.MIN_AMOUNT - 1), None, 81),
    "more than the largest bounty": (dict(amount=pay.MAX_AMOUNT + 1), None, 81),
    "a mode that is neither merge nor tests": (dict(mode=2), None, 81),
    "less than a minute to do the work": (dict(work_s=59), None, 81),
    "more than 90 days to do the work": (dict(work_s=pay.MAX_WORK + 1), None, 81),
    "a workflow commit that is not 40 hex characters": (dict(wf_sha="C" * 40), None, 81),
    "repository 0": (dict(repo=0), None, 81),
    "no terms": (dict(terms=b""), None, 81),
    "terms over 600 bytes": (dict(terms=_long_terms(601)), None, 81),
    "terms that are not printable ASCII": (dict(terms=TERMS[:-1] + b"\x7f}"), None, 81),
    "another funder's job address": (dict(), ("job", lambda c: pay.job_pda(REPO, 1, c.owner.pubkey())), 82),
    "another mint's vault": (dict(), ("vault", lambda c: pay.vault_pda(c.test_usdc)), 80),
    "an authority that is not the program's": (dict(), ("auth", lambda c: c.funder.pubkey()), 80),
    "the other token program": (dict(), ("tokenProgram", lambda c: pay.TOKEN_2022), 95),
    "an account in place of the pause": (dict(), ("pause", lambda c: pay.rate_pda(REPO)), 80),
}


@pytest.mark.parametrize("what", list(WALLET_REFUSALS))
def test_a_wallet_does_not_fund_with(chain, what):
    c = chain
    kw, change, want = WALLET_REFUSALS[what]
    kw = dict(kw)
    before = c.balance(c.funder_tok)
    ix = pay.fund_wallet_ix(c.funder.pubkey(), c.funder_tok, c.usdc, kw.pop("repo", REPO), issue(), kw.pop("amount", 5 * USDC), WF_REPO,
                            kw.pop("wf_sha", WF_SHA), kw.pop("terms", TERMS), **kw)
    if change:
        ix = swap(ix, change[0], change[1](c))
    assert not c.send([ix], c.funder), f"{what}: accepted"
    assert code(c) == want, f"{what}: {c.err}, wanted {want}"
    assert c.balance(c.funder_tok) == before


# -- a proof pays --------------------------------------------------------------------------------------------------------
def test_a_proof_pays_the_address_the_token_carries(chain):
    c = chain
    payee, wallet = user(), Keypair().pubkey()
    job = fund_balance(c, amount=5 * USDC)
    j = pay.read_job(c.data(job))
    vault0, fee0 = c.balance(pay.vault_pda(c.usdc)), c.balance(c.fee)
    tok = pay_token(c, job, payee, wallet)
    c.token_account(wallet, c.usdc)
    sol0 = c.lamports(c.payer.pubkey())
    assert do_pay(c, job, tok, payee, wallet), c.err
    # 2.5% to the fee account, the rest to the wallet the author named; the job is gone
    assert (c.balance(pay.ata(wallet, c.usdc)), c.balance(c.fee) - fee0, vault0 - c.balance(pay.vault_pda(c.usdc))) == (4_950_000, 50_000, 5 * USDC)
    assert c.data(job) is None
    assert c.said("knos2:") == [f"knos2:paid repo={REPO} issue={j.issue} payee={payee} amount=4950000 fee=50000 to={wallet}"]
    # the relayer paid the transaction and the rent of the payee's record, of the pair and of the token's single-use
    # marker (which keeps who paid for it and when it may be closed), and got the job's rent back (it had paid it)
    rent = c.svm.minimum_balance_for_rent_exemption
    assert c.lamports(c.payer.pubkey()) - sol0 == rent(pay.JOB_LEN) - rent(pay.REP_LEN) - rent(1) - rent(pay.USED_LEN) - 2 * 5000
    # the same proof cannot pay twice: the job is gone
    assert pay.read_job(c.data(job)) is None
    assert not c.send([pay_ix(c, c.payer.pubkey(), pay_token_for(c, j, payee, wallet), c.key, job, j, payee, wallet)]) and code(c) == 82


def pay_token_for(c: Chain, j: pay.Job, payee: int, address: Pubkey | None = None, **over):
    """A pay token for a job that may be gone by now."""
    return c.gh(pay.pay_audience(j.repo_id, j.issue, payee, HEAD, j.terms, j.mode, address), repository_id=j.repo_id, **over)


def test_a_proof_pays_the_payees_bound_wallet_whatever_address_the_token_carries(chain):
    c = chain
    payee, bound, named = user(), Keypair().pubkey(), Keypair().pubkey()
    assert bind(c, payee, bound), c.err
    job = fund_wallet(c, amount=40 * USDC)
    tok = pay_token(c, job, payee, named)
    # a relayer cannot send it to the address in the token, nor hide the Bind behind another account
    c.token_account(named, c.usdc)
    j = pay.read_job(c.data(job))
    assert not c.send([pay_ix(c, c.payer.pubkey(), tok, c.key, job, j, payee, named)]) and code(c) == 88
    hidden = swap(pay_ix(c, c.payer.pubkey(), tok, c.key, job, j, payee, named), "bind", pay.bind_pda(user()))
    assert not c.send([hidden]) and code(c) == 88
    assert do_pay(c, job, tok, payee, bound), c.err
    assert (c.balance(pay.ata(bound, c.usdc)), c.balance(pay.ata(named, c.usdc))) == (39_880_000, 0)     # the fee: 0.30% of 40
    assert c.said("knos2:paid")[0].endswith(f" to={bound}")
    # a proof with no address pays the bound wallet too
    job = fund_balance(c)
    assert do_pay(c, job, pay_token(c, job, payee), payee, bound), c.err
    assert c.balance(pay.ata(bound, c.usdc)) == 39_880_000 + 4_950_000


def test_with_no_wallet_the_job_is_held_for_the_payee_and_paid_once_they_bind_one(chain):
    c = chain
    payee = user()
    job = fund_balance(c, amount=8 * USDC)
    vault0 = c.balance(pay.vault_pda(c.usdc))
    assert do_pay(c, job, pay_token(c, job, payee), payee), c.err
    j = pay.read_job(c.data(job))
    assert (j.state, j.payee_id, j.hold_until, j.amount) == ("held", payee, c.now() + pay.HOLD, 8 * USDC)
    assert c.said("knos2:") == [f"knos2:held repo={REPO} issue={j.issue} payee={payee} until={c.now() + pay.HOLD}"]
    assert c.balance(pay.vault_pda(c.usdc)) == vault0               # nothing has moved
    # held is final for the bounty: no other proof takes it, and it is not refunded while the payee can still claim it
    other = user()
    assert not do_pay(c, job, pay_token_for(c, j, other, Keypair().pubkey()), other) and code(c) == 83
    assert not refund(c, job) and code(c) == 83
    # nobody settles it to a wallet of their choice: the payee has bound none
    thief = Keypair().pubkey()
    c.token_account(thief, c.usdc)
    assert not c.send([pay.settle_ix(c.payer.pubkey(), job, j, thief)]) and code(c) == 88
    someone, theirs = user(), Keypair().pubkey()
    assert bind(c, someone, theirs), c.err
    c.token_account(theirs, c.usdc)
    assert not c.send([swap(pay.settle_ix(c.payer.pubkey(), job, j, theirs), "bind", pay.bind_pda(someone))]) and code(c) == 88
    # the payee binds a wallet (a run of the pinned claim workflow in their own knos-claim repository): anyone settles
    wallet = Keypair().pubkey()
    assert bind(c, payee, wallet), c.err
    c.token_account(wallet, c.usdc)
    assert not c.send([pay.settle_ix(c.payer.pubkey(), job, j, thief)]) and code(c) == 88
    assert c.send([pay.settle_ix(c.payer.pubkey(), job, j, wallet)], tag="settle"), c.err
    assert c.balance(pay.ata(wallet, c.usdc)) == 7_950_000 and c.balance(pay.vault_pda(c.usdc)) == vault0 - 8 * USDC and c.data(job) is None
    assert c.said("knos2:") == [f"knos2:paid repo={REPO} issue={j.issue} payee={payee} amount=7950000 fee=50000 to={wallet}"]
    assert not c.send([pay.settle_ix(c.payer.pubkey(), job, j, wallet)]) and code(c) == 82
    # an open job cannot be settled: it has no proof
    job = fund_wallet(c)
    assert not c.send([pay.settle_ix(c.payer.pubkey(), job, pay.read_job(c.data(job)), wallet)]) and code(c) == 83


def test_a_held_job_returns_to_the_funder_after_180_days_and_not_before():
    """On a chain of its own: nothing here needs a token after the clock has moved half a year."""
    c = setup(Chain())
    late, late_wallet = user(), Keypair().pubkey()
    jobs = [fund_balance(c, amount=6 * USDC), fund_wallet(c, amount=9 * USDC), fund_wallet(c, amount=3 * USDC)]
    for job, payee in zip(jobs, (user(), user(), late)):
        assert do_pay(c, job, pay_token(c, job, payee), payee), c.err
    held_at = c.now()
    assert bind(c, late, late_wallet), c.err                 # the third payee binds a wallet in time but nobody settles
    c.token_account(late_wallet, c.usdc)
    baltok0, funder0, vault0 = c.balance(pay.baltok_pda(c.bal)), c.balance(c.funder_tok), c.balance(pay.vault_pda(c.usdc))
    for job in jobs:
        assert not refund(c, job) and code(c) == 83
    c.warp(held_at + pay.HOLD - c.now())                     # the last second of the hold
    for job in jobs:
        assert not refund(c, job) and code(c) == 83
    c.warp(1)
    # too late to settle, even for the payee who bound a wallet; the money goes back where it came from
    j3 = pay.read_job(c.data(jobs[2]))
    assert not c.send([pay.settle_ix(c.payer.pubkey(), jobs[2], j3, late_wallet)]) and code(c) == 83
    thief = c.token_account(Keypair().pubkey(), c.usdc)
    for job in jobs:
        assert not refund(c, job, thief) and code(c) == 88
        assert refund(c, job), c.err
        assert c.data(job) is None
    assert c.balance(pay.baltok_pda(c.bal)) == baltok0 + 6 * USDC and c.balance(c.funder_tok) == funder0 + 12 * USDC
    assert c.balance(pay.vault_pda(c.usdc)) == vault0 - 18 * USDC == 0 and c.balance(thief) == 0


def test_with_no_proof_by_the_deadline_the_money_goes_back_where_it_came_from(chain):
    c = chain
    from_balance, from_wallet = fund_balance(c, amount=7 * USDC, work=600), fund_wallet(c, amount=11 * USDC, work_s=599)
    jb, jw = pay.read_job(c.data(from_balance)), pay.read_job(c.data(from_wallet))
    baltok0, funder0, vault0 = c.balance(pay.baltok_pda(c.bal)), c.balance(c.funder_tok), c.balance(pay.vault_pda(c.usdc))
    assert not refund(c, from_balance) and code(c) == 83                    # not yet
    assert not refund(c, from_wallet) and code(c) == 83
    c.warp(jb.deadline - c.now())                            # the deadline's own second still belongs to the work
    assert not refund(c, from_balance) and code(c) == 83
    c.warp(1)
    # too late to prove
    assert not do_pay(c, from_balance, pay_token(c, from_balance, AUTHOR, Keypair().pubkey()), AUTHOR, Keypair().pubkey()) and code(c) == 83
    # a relayer cannot name the destination: a Balance's job goes back to exactly that Balance's token account, a
    # wallet's job to a token account of that wallet
    thief = c.token_account(Keypair().pubkey(), c.usdc)
    assert not refund(c, from_balance, thief) and code(c) == 88
    assert not refund(c, from_balance, c.owner_tok) and code(c) == 88           # not even the wallet that opened the Balance
    assert not refund(c, from_balance, pay.baltok_pda(c.small)) and code(c) == 88
    assert not refund(c, from_wallet, thief) and code(c) == 88
    assert not refund(c, from_wallet, pay.baltok_pda(c.bal)) and code(c) == 88
    # nor the vault, the mint, the token program or where the rent goes
    ix = pay.refund_ix(c.payer.pubkey(), from_wallet, jw)
    for name, key, want in (("vault", pay.vault_pda(c.test_usdc), 80), ("auth", c.payer.pubkey(), 80), ("rentTo", c.payer.pubkey(), 80),
                            ("mint", c.test_usdc, 80), ("tokenProgram", pay.TOKEN_2022, 95)):
        assert not c.send([swap(ix, name, key)]) and code(c) == want, (name, c.err)
    relayer0, funder_sol0 = c.lamports(c.payer.pubkey()), c.lamports(c.funder.pubkey())
    assert refund(c, from_balance), c.err
    assert c.said("knos2:") == [f"knos2:refunded repo={REPO} issue={jb.issue} amount={7 * USDC}"]
    assert refund(c, from_wallet), c.err
    assert c.balance(pay.baltok_pda(c.bal)) == baltok0 + 7 * USDC and c.balance(c.funder_tok) == funder0 + 11 * USDC
    assert c.balance(pay.vault_pda(c.usdc)) == vault0 - 18 * USDC and c.balance(thief) == 0
    assert c.data(from_balance) is None and c.data(from_wallet) is None
    # each job's rent went back to whoever paid it: the relayer of the comment, the funding wallet
    assert c.lamports(c.funder.pubkey()) - funder_sol0 == 3_118_080 and c.lamports(c.payer.pubkey()) - relayer0 == 3_118_080 - 2 * 5000
    assert not c.send([pay.refund_ix(c.payer.pubkey(), from_wallet, jw)]) and code(c) == 82
    # a refunded Balance is spendable again
    assert pay.read_job(c.data(fund_balance(c, amount=7 * USDC))).amount == 7 * USDC


def _unverified(c: Chain, job: Pubkey) -> Pubkey:
    j = pay.read_job(c.data(job))
    jwt = sign_jwt(signing_key(), github_claims(aud=pay.pay_audience(REPO, j.issue, AUTHOR, HEAD, TH, j.mode), iat=c.now(), exp=c.now() + 300, jti="unverified" + str(j.issue)))
    return oidc.token_pda(c.payer.pubkey(), c.write(jwt))


def _gitlab(c: Chain, job: Pubkey) -> Pubkey:
    """A token GitLab's key signed and the verifier verified, saying everything a pay token says."""
    gl, j = signing_key(4096), pay.read_job(c.data(job))
    other_key(c)
    claims = github_claims(aud=pay.pay_audience(REPO, j.issue, AUTHOR, HEAD, TH, j.mode), iat=c.now(), exp=c.now() + 300, iss=oidc.ISSUERS[oidc.GITLAB])
    return c.verify(sign_jwt(gl, claims), oidc.GITLAB, modulus(gl))


def _expired(c: Chain, job: Pubkey) -> Pubkey:
    tok = pay_token(c, job)
    c.warp(300 + oidc.LATE)
    return tok


def _other_mint_account(c: Chain) -> Pubkey:
    return c.token_account(c.wallet_of_author, c.test_usdc)


def _good(c: Chain, job: Pubkey) -> Pubkey:
    """The real proof, carrying the address the author asked to be paid at."""
    return pay_token(c, job, AUTHOR, c.wallet_of_author)


# what is wrong -> (the pay token, a change to the instruction's accounts or None, the refusal)
PAY_REFUSALS = {
    "a fund.yml token": (lambda c, job: pay_token(c, job, file="fund.yml"), None, 86),
    "prove.yml of another repository": (lambda c, job: pay_token(c, job, wf_repo="evil/Knos"), None, 86),
    "prove.yml at another commit": (lambda c, job: pay_token(c, job, wf_sha="d" * 40), None, 86),
    "a run in another repository": (lambda c, job: pay_token(c, job, repository_id=111), None, 85),
    "an audience for another repository": (lambda c, job: pay_token(c, job, repo_id=111, repository_id=REPO), None, 87),
    "an audience for another issue": (lambda c, job: pay_token(c, job, issue=1), None, 87),
    "another terms hash": (lambda c, job: pay_token(c, job, terms=hashlib.sha256(b"easier terms").digest()), None, 87),
    "the other mode": (lambda c, job: pay_token(c, job, mode=pay.TESTS), None, 87),
    "payee 0": (lambda c, job: pay_token(c, job, 0), None, 87),
    "a head that is not a commit": (lambda c, job: pay_token(c, job, head_sha="main"), None, 87),
    "an address that is not a key": (lambda c, job: c.gh(pay.pay_audience(REPO, pay.read_job(c.data(job)).issue, AUTHOR, HEAD, TH, 0)[:-1] + "0OIl"), None, 87),
    "a first-deployment audience": (lambda c, job: c.gh(f"knos:pay:{REPO}:{pay.read_job(c.data(job)).issue}:{AUTHOR}:{HEAD}:{TH.hex()}:0"), None, 87),
    "a bind audience": (lambda c, job: c.gh(pay.bind_audience(Keypair().pubkey())), None, 87),
    "a self-hosted runner": (lambda c, job: pay_token(c, job, runner_environment="self-hosted"), None, 85),
    "a token issued before the funding": (lambda c, job: pay_token(c, job, iat=c.now() - 1800), None, 83),
    "a token from the future": (lambda c, job: pay_token(c, job, iat=c.now() + 301, exp=c.now() + 601), None, 84),
    "a token that claims to live for hours": (lambda c, job: pay_token(c, job, exp=c.now() + 3601), None, 84),
    "an expired token": (_expired, None, 84),
    "a token that is not verified yet": (_unverified, None, 84),
    "an account that is not the verifier's, with a verified token's bytes": (lambda c, job: _forged(c, pay_token(c, job)), None, 84),
    "a GitLab token": (_gitlab, None, 84),
    "another key of the verifier's": (_good, ("key", lambda c, job: other_key(c)), 80),
    "the key's bytes in an account that is not the verifier's": (_good, ("key", lambda c, job: _forged(c, c.key)), 80),
    "a token account of the verifier's in place of the key": (_good, ("key", lambda c, job: _good(c, job)), 80),
    "an account posing as the job": (_good, ("job", lambda c, job: _forged(c, job)), 82),
    "another user's bind account": (_good, ("bind", lambda c, job: pay.bind_pda(AUTHOR + 1)), 88),
    "a destination that is not the payee's wallet's": (_good, ("destToken", lambda c, job: c.funder_tok), 88),
    "a destination in another mint": (_good, ("destToken", lambda c, job: _other_mint_account(c)), 88),
    "the vault as the destination": (_good, ("destToken", lambda c, job: pay.vault_pda(c.usdc)), 88),
    "another user's record": (_good, ("rep", lambda c, job: pay.rep_pda(AUTHOR + 1)), 88),
    "another funder's pair": (_good, ("pair", lambda c, job: pay.pair_pda(AUTHOR, OWNER)), 88),
    "another mint's vault": (_good, ("vault", lambda c, job: pay.vault_pda(c.test_usdc)), 80),
    "a fee account that is not Knos's": (_good, ("feeToken", lambda c, job: c.funder_tok), 88),
    "a fee account in another mint": (_good, ("feeToken", lambda c, job: pay.ata(pay.FEE_OWNER, c.test_usdc)), 88),
    "an authority that is not the program's": (_good, ("auth", lambda c, job: c.payer.pubkey()), 80),
    "the rent sent to someone else": (_good, ("rentTo", lambda c, job: c.payer.pubkey()), 80),
    "another mint": (_good, ("mint", lambda c, job: c.test_usdc), 80),
    "the other token program": (_good, ("tokenProgram", lambda c, job: pay.TOKEN_2022), 95),
}


@pytest.mark.parametrize("what", list(PAY_REFUSALS))
def test_a_job_is_not_paid_with(chain, what):
    c = chain
    make, change, want = PAY_REFUSALS[what]
    job = fund_wallet(c)
    j, vault0 = pay.read_job(c.data(job)), c.balance(pay.vault_pda(c.usdc))
    tok = make(c, job)
    assert tok is not None, c.err
    # with the key account the token account itself names, as a relayer finds it: what is refused is the token
    ix = pay_ix(c, c.payer.pubkey(), tok, c.key_of(tok), job, j, AUTHOR, c.wallet_of_author)
    if change:
        ix = swap(ix, change[0], change[1](c, job))
    assert not c.send([ix]), f"{what}: accepted"
    assert code(c) == want, f"{what}: {c.err}, wanted {want}"
    assert pay.read_job(c.data(job)) == j and c.balance(pay.vault_pda(c.usdc)) == vault0
    # and the real proof still pays this very job
    assert do_pay(c, job, pay_token(c, job, AUTHOR, c.wallet_of_author), AUTHOR, c.wallet_of_author), c.err


def test_a_proof_pays_nothing_after_the_deadline_and_no_job_twice(chain):
    c = chain
    wallet = Keypair().pubkey()
    # a proof may be run again (it states facts about the pull request, whoever starts it): the re-run pays
    job = fund_wallet(c)
    assert do_pay(c, job, pay_token(c, job, AUTHOR, wallet, run_attempt=2, event_name="workflow_dispatch"), AUTHOR, wallet), c.err
    job = fund_wallet(c, work_s=60)
    j = pay.read_job(c.data(job))
    tok = pay_token(c, job, AUTHOR, wallet)
    c.warp(60)
    assert do_pay(c, job, tok, AUTHOR, wallet), c.err                # the deadline's own second
    assert not c.send([pay_ix(c, c.payer.pubkey(), tok, c.key, job, j, AUTHOR, wallet)]) and code(c) == 82    # the job is gone
    job = fund_wallet(c, work_s=60)
    tok = pay_token(c, job, AUTHOR, wallet)
    c.warp(61)
    assert not do_pay(c, job, tok, AUTHOR, wallet) and code(c) == 83
    assert refund(c, job), c.err
    # a relayer must sign, and pay the record's rent itself
    job = fund_wallet(c)
    ix = pay_ix(c, c.payer.pubkey(), pay_token(c, job, AUTHOR, wallet), c.key, job, pay.read_job(c.data(job)), AUTHOR, wallet)
    unsigned = Instruction(ix.program_id, bytes(ix.data), [AccountMeta(c.funder.pubkey(), False, True), *ix.accounts[1:]])
    assert not c.send([unsigned]) and code(c) == 80


def test_one_proof_pays_one_job_and_every_job_on_the_issue_is_paid_by_a_proof_of_its_own(chain):
    c = chain
    n, payee, wallet = issue(), user(), Keypair().pubkey()
    c.token_account(wallet, c.usdc)
    own = fund_balance(c, n, 5 * USDC)
    sponsor, stok = c.wallet(c.usdc, 20 * USDC)
    added = fund_wallet(c, n, 20 * USDC, sponsor, stok)
    # a stranger's job on the same issue pins a workflow of their own: the repository's proof does not pay it
    squatter, qtok = c.wallet(c.usdc, 5 * USDC)
    ix = pay.fund_wallet_ix(squatter.pubkey(), qtok, c.usdc, REPO, n, 5 * USDC, "evil/workflows", "f" * 40, TERMS)
    assert c.send([ix], squatter), c.err
    theirs = pay.job_pda(REPO, n, squatter.pubkey())
    # a relay finds every job on the issue by its first fields (repository id, then issue, at offset 8)
    found = ChainLedger(c).program_accounts(pay.PAY_ID, pay.JOB_LEN, {8: REPO.to_bytes(8, "little") + n.to_bytes(8, "little")})
    assert {a for a, _d in found} == {own, added, theirs} and all(pay.read_job(d).issue == n for _a, d in found)
    tok = pay_token(c, own, payee, wallet)
    assert do_pay(c, own, tok, payee, wallet), c.err
    # a pay token pays exactly one job (2.1): the second job on the issue needs a token of another run
    assert not do_pay(c, added, tok, payee, wallet) and code(c) == 91
    assert do_pay(c, added, pay_token(c, added, payee, wallet), payee, wallet), c.err
    assert c.balance(pay.ata(wallet, c.usdc)) == 4_950_000 + 19_940_000
    assert not do_pay(c, theirs, tok, payee, wallet) and code(c) == 86


# -- binding a wallet ----------------------------------------------------------------------------------------------------
def test_a_github_user_binds_a_wallet_from_their_own_knos_claim_repository(chain):
    c = chain
    who, first, second = user(), Keypair().pubkey(), Pubkey.from_bytes(bytes([0, 0, 7]) + bytes(range(29)))
    assert pay.read_bind(c.data(pay.bind_pda(who))) is None
    assert bind(c, who, first), c.err                                    # run by hand
    assert pay.read_bind(c.data(pay.bind_pda(who))) == pay.Bind(user_id=who, wallet=first, iat=c.now())
    assert c.said("knos2:") == [f"knos2:bound user={who} wallet={first}"]
    # a later token rebinds; the log prints the address as Solana does, leading zero bytes included
    assert bind(c, who, second), c.err
    assert pay.read_bind(c.data(pay.bind_pda(who))) == pay.Bind(user_id=who, wallet=second, iat=c.now())
    assert c.said("knos2:") == [f"knos2:bound user={who} wallet={second}"] and str(second).startswith("11")
    assert bind(c, who, Pubkey.default()), c.err
    assert c.said("knos2:") == [f"knos2:bound user={who} wallet={'1' * 32}"]
    # the real pin of the claim workflow binds as the test pin does
    assert bind(c, who, first, wf_sha=pay.IDS["claim_sha"]), c.err
    # by hand only: the push that created the repository (the workflow's first run) binds nothing. A link can fill in
    # GitHub's new-repository form, so that push may carry an address the owner never typed
    born = user()
    assert not bind(c, born, first, event_name="push", run_number=1) and code(c) == 85
    assert pay.read_bind(c.data(pay.bind_pda(born))) is None


def _older(c: Chain, who: int) -> Pubkey:
    old = bind_token(c, who, Keypair().pubkey())
    assert bind(c, who, Keypair().pubkey()), c.err
    return old


# what is wrong -> (the bind token for user `who`, the refusal)
BIND_REFUSALS = {
    "another workflow file of the pinned repository": (lambda c, who: bind_token(c, who, Keypair().pubkey(), file="rotate.yml"), 86),
    "a claim.yml of another repository": (lambda c, who: bind_token(c, who, Keypair().pubkey(), wf_repo="evil/knos-oidc-rotate"), 86),
    "another commit of the claim workflow": (lambda c, who: bind_token(c, who, Keypair().pubkey(), wf_sha="3" * 40), 86),
    "the real pin's neighbour": (lambda c, who: bind_token(c, who, Keypair().pubkey(), wf_sha=pay.IDS["claim_sha"][:-1] + "0"), 86),
    "a repository with another name": (lambda c, who: bind_token(c, who, Keypair().pubkey(), repository=f"user{who}/dotfiles"), 85),
    "a repository whose name only ends like it": (lambda c, who: bind_token(c, who, Keypair().pubkey(), repository=f"user{who}/my-knos-claim"), 85),
    "an actor who does not own the repository": (lambda c, who: bind_token(c, who, Keypair().pubkey(), repository_owner_id=who + 1), 85),
    "an organisation's repository": (lambda c, who: bind_token(c, who, Keypair().pubkey(), repository_owner_id=OWNER, repository="octo/knos-claim"), 85),
    "the push that made the repository (its first run)": (lambda c, who: bind_token(c, who, Keypair().pubkey(), event_name="push", run_number=1), 85),
    "a later push": (lambda c, who: bind_token(c, who, Keypair().pubkey(), event_name="push", run_number=2), 85),
    "the schedule": (lambda c, who: bind_token(c, who, Keypair().pubkey(), event_name="schedule", run_number=1), 85),
    "a comment": (lambda c, who: bind_token(c, who, Keypair().pubkey(), event_name="issue_comment"), 85),
    "a pull request": (lambda c, who: bind_token(c, who, Keypair().pubkey(), event_name="pull_request_target", run_number=1), 85),
    "a self-hosted runner": (lambda c, who: bind_token(c, who, Keypair().pubkey(), runner_environment="self-hosted"), 85),
    "a re-run of the owner's run": (lambda c, who: bind_token(c, who, Keypair().pubkey(), run_attempt=2), 85),
    "a re-run of the first push": (lambda c, who: bind_token(c, who, Keypair().pubkey(), event_name="push", run_number=1, run_attempt=3), 85),
    "an address that is not a key": (lambda c, who: bind_token(c, who, "knos2:bind:" + "1" * 31), 87),
    "an address with something after it": (lambda c, who: bind_token(c, who, pay.bind_audience(Keypair().pubkey()) + ":x"), 87),
    "a first-deployment claim audience": (lambda c, who: bind_token(c, who, f"knos:claim:{Keypair().pubkey()}"), 87),
    "an older token than the bind's": (_older, 91),
}


@pytest.mark.parametrize("what", list(BIND_REFUSALS))
def test_a_wallet_is_not_bound_with(chain, what):
    c = chain
    make, want = BIND_REFUSALS[what]
    who = user()
    tok = make(c, who)
    before = c.data(pay.bind_pda(who))
    assert not c.send([pay.bind_ix(c.payer.pubkey(), tok, c.key, who)]), f"{what}: accepted"
    assert code(c) == want, f"{what}: {c.err}, wanted {want}"
    assert c.data(pay.bind_pda(who)) == before


def test_nobody_binds_a_wallet_for_someone_else(chain):
    c = chain
    victim, thief_id, thief = user(), user(), Keypair().pubkey()
    # the thief's own valid bind token binds the thief's account, never the victim's
    tok = bind_token(c, thief_id, thief)
    assert not c.send([pay.bind_ix(c.payer.pubkey(), tok, c.key, victim)]) and code(c) == 80
    # the same token twice changes nothing the second time
    assert c.send([pay.bind_ix(c.payer.pubkey(), tok, c.key, thief_id)]), c.err
    assert not c.send([pay.bind_ix(c.payer.pubkey(), tok, c.key, thief_id)]) and code(c) == 91
    # the victim opens a pull request or comments in the thief's knos-claim: that run is the victim's actor in the thief's repository
    for event in ("pull_request_target", "issue_comment", "workflow_dispatch"):
        tok = bind_token(c, victim, thief, event_name=event, repository_owner_id=thief_id, repository=f"user{thief_id}/knos-claim")
        assert not c.send([pay.bind_ix(c.payer.pubkey(), tok, c.key, victim)]) and code(c) == 85
    assert pay.read_bind(c.data(pay.bind_pda(victim))) is None


# -- the record ----------------------------------------------------------------------------------------------------------
def test_the_record_counts_real_money_test_money_and_self_payment_apart_and_distinct_funders(chain):
    c = chain
    payee, wallet = user(), Keypair().pubkey()
    rep = lambda who=payee: pay.read_rep(c.data(pay.rep_pda(who)))  # noqa: E731
    assert rep() == pay.Record(0, 0, 0, 0, 0, 0, 0, 0)
    # real money from the owner's Balance: one payment, one funder
    proven(c, fund_balance(c, amount=5 * USDC), payee, wallet)
    t1 = c.now()
    assert rep() == pay.Record(paid=1, funders=1, total=4_950_000, test_paid=0, self_paid=0, test_total=0, first=t1, last=t1)
    assert c.data(pay.pair_pda(payee, OWNER)) == b"\x01"
    # the same owner again, through another wallet's Balance for that owner: still one funder
    c.warp(100)
    proven(c, fund_balance(c, amount=5 * USDC, balance=c.small), payee, wallet)
    assert rep() == pay.Record(paid=2, funders=1, total=9_900_000, test_paid=0, self_paid=0, test_total=0, first=t1, last=c.now())
    # a sponsor's wallet: a second funder; the same wallet again: still two
    proven(c, fund_wallet(c, amount=10 * USDC), payee, wallet)
    assert (rep().paid, rep().funders, rep().total) == (3, 2, 19_850_000) and c.data(pay.pair_pda(payee, c.funder.pubkey())) == b"\x01"
    proven(c, fund_wallet(c, amount=10 * USDC), payee, wallet)
    assert (rep().paid, rep().funders, rep().total) == (4, 2, 29_800_000)
    # the faucet's test USDC counts apart and makes no funder
    org, repo, n = user(), user(), issue()
    tok = faucet_token(c, n, org, repo, 50 * USDC)
    fbal = pay.faucet_balance_pda(org)
    assert c.send([pay.faucet_open_ix(c.payer.pubkey(), tok, c.key, org, repo), pay.fund_balance_ix(c.payer.pubkey(), tok, c.key, fbal, c.test_usdc, repo, n, TERMS)]), c.err
    job = pay.job_pda(repo, n, fbal)
    assert do_pay(c, job, pay_token(c, job, payee, wallet), payee, wallet), c.err
    last = rep().last
    assert rep() == pay.Record(paid=4, funders=2, total=29_800_000, test_paid=1, self_paid=0, test_total=49_850_000, first=t1, last=last)
    assert c.data(pay.pair_pda(payee, org)) is None and c.balance(pay.ata(wallet, c.test_usdc)) == 49_850_000
    # test USDC that a wallet earned and puts into a job of its own is still test money: the mint decides
    earner, etok = c.wallet(c.test_usdc)
    c.warp(pay.FUND_PERIOD)
    n2, someone = issue(), user()
    tok = faucet_token(c, n2, org, repo, 50 * USDC)
    assert c.send([pay.faucet_open_ix(c.payer.pubkey(), tok, c.key, org, repo), pay.fund_balance_ix(c.payer.pubkey(), tok, c.key, fbal, c.test_usdc, repo, n2, TERMS)]), c.err
    job = pay.job_pda(repo, n2, fbal)
    assert do_pay(c, job, pay_token(c, job, someone, earner.pubkey()), someone, earner.pubkey()), c.err
    job = fund_wallet(c, amount=20 * USDC, funder=earner, funder_tok=etok, mint=c.test_usdc)
    assert pay.read_job(c.data(job)).faucet
    proven(c, job, payee, wallet)
    assert (rep().paid, rep().test_paid, rep().test_total, rep().last) == (4, 2, 49_850_000 + 19_940_000, last)
    # self-payment counts apart: the Balance's owner is the payee
    proven(c, fund_balance(c), OWNER, wallet)
    assert rep(OWNER) == pay.Record(paid=0, funders=0, total=0, test_paid=0, self_paid=1, test_total=0, first=0, last=0)
    assert c.data(pay.pair_pda(OWNER, OWNER)) is None
    # the maintainer who wrote the funding comment is the payee
    proven(c, fund_balance(c), MAINT, wallet)
    assert rep(MAINT).self_paid == 1 and rep(MAINT).paid == 0
    # a wallet's job paid back to the wallet that funded it, by its own bind or by the address in the token
    me = user()
    assert bind(c, me, c.funder.pubkey()), c.err
    job = fund_wallet(c)
    assert do_pay(c, job, pay_token(c, job, me), me, c.funder.pubkey()), c.err
    other = user()
    job = fund_wallet(c)
    assert do_pay(c, job, pay_token(c, job, other, c.funder.pubkey()), other, c.funder.pubkey()), c.err
    assert (rep(me).self_paid, rep(me).paid, rep(other).self_paid, rep(other).paid) == (1, 0, 1, 0)
    assert c.data(pay.pair_pda(me, c.funder.pubkey())) is None
    assert rep() == pay.Record(paid=4, funders=2, total=29_800_000, test_paid=2, self_paid=0, test_total=69_790_000, first=t1, last=last)


# -- the devnet faucet ---------------------------------------------------------------------------------------------------
def test_on_devnet_one_comment_funds_a_bounty_with_test_usdc_and_no_wallet(chain):
    c = chain
    org, repo, n = user(), user(), issue()                         # an organisation's repository: nobody comments as the organisation
    fbal = pay.faucet_balance_pda(org)
    tok = faucet_token(c, n, org, repo, actor=MAINT)        # the owner has no Balance: the workflow names the faucet's
    vault0 = c.balance(pay.vault_pda(c.test_usdc))
    ixs = [pay.faucet_open_ix(c.payer.pubkey(), tok, c.key, org, repo), pay.fund_balance_ix(c.payer.pubkey(), tok, c.key, fbal, c.test_usdc, repo, n, TERMS)]
    assert c.send(ixs, tag="faucet_open+fund_balance"), c.err
    assert c.said("knos2:")[:2] == [f"knos2:balance owner={org} authority={pay.auth_pda()} mint={c.test_usdc}",
                                    f"knos2:funded repo={repo} issue={n} amount={5 * USDC} mode=0 by={MAINT} source={fbal} faucet=1"]
    b = pay.read_balance(c.data(fbal))
    assert (b.faucet, b.owner_id, b.authority, b.mint, b.cap_per_job, b.spenders, b.spent, b.last_iat) == (True, org, pay.auth_pda(), c.test_usdc, 0, (), 5 * USDC, c.now())
    assert pay.read_rate(c.data(pay.rate_pda(repo))) == (c.now(), c.now())
    job = pay.job_pda(repo, n, fbal)
    j = pay.read_job(c.data(job))
    assert (j.faucet, j.from_balance, j.amount, j.funder_id, j.owner_id, j.mint, j.refund_to) == (True, True, 5 * USDC, MAINT, org, c.test_usdc, pay.baltok_pda(fbal))
    assert c.balance(pay.baltok_pda(fbal)) == 0 and c.balance(pay.vault_pda(c.test_usdc)) == vault0 + 5 * USDC
    # the token minted once: it cannot mint again, and the repository's next comment waits a minute
    assert not c.send([pay.faucet_open_ix(c.payer.pubkey(), tok, c.key, org, repo)]) and code(c) == 90
    n2 = issue()
    tok2 = faucet_token(c, n2, org, repo)
    assert not c.send([pay.faucet_open_ix(c.payer.pubkey(), tok2, c.key, org, repo)]) and code(c) == 90
    c.warp(pay.FUND_PERIOD)
    assert not c.send([pay.faucet_open_ix(c.payer.pubkey(), tok, c.key, org, repo)]) and code(c) == 90      # the first token is still used up
    # more than the faucet gives, a token from prove.yml, and another event are refused
    for bad, want in ((faucet_token(c, n2, org, repo, pay.FAUCET_CAP + 1), 81),
                      (faucet_token(c, n2, org, repo, run_attempt=2), 85),
                      (faucet_token(c, n2, org, repo, file="prove.yml"), 86),
                      (faucet_token(c, n2, org, repo, event_name="push"), 85)):
        assert not c.send([pay.faucet_open_ix(c.payer.pubkey(), bad, c.key, org, repo)]) and code(c) == want
    # the faucet's accounts are the program's own: another Balance (the token does not name it), another Balance's token
    # account, another mint, another repository's rate account, and no key account but the token's
    tok3 = faucet_token(c, n2, org, repo)
    ix = pay.faucet_open_ix(c.payer.pubkey(), tok3, c.key, org, repo)
    for name, key, want in (("balance", c.bal, 87), ("baltok", pay.baltok_pda(c.bal), 80), ("mint", c.usdc, 80), ("rate", pay.rate_pda(REPO), 80),
                            ("key", other_key(c), 80), ("key", _forged(c, c.key), 80)):
        assert not c.send([swap(ix, name, key)]) and code(c) == want, (name, c.err)
    # opened alone, the faucet leaves the test USDC in the owner's faucet Balance, where the same token spends it
    assert c.send([ix], tag="faucet_open"), c.err
    assert c.balance(pay.baltok_pda(fbal)) == 5 * USDC
    assert c.send([pay.fund_balance_ix(c.payer.pubkey(), tok3, c.key, fbal, c.test_usdc, repo, n2, TERMS)]), c.err
    # nobody withdraws test money, and no wallet changes the faucet Balance
    thief, ttok = c.wallet(c.test_usdc)
    assert not c.send([pay.withdraw_ix(thief.pubkey(), fbal, c.test_usdc, 0, ttok)], thief) and code(c) == 99
    assert not c.send([pay.set_balance_ix(thief.pubkey(), fbal, spenders=[1])], thief) and code(c) == 98
    # paid like any job; the record counts it as test money
    payee, wallet = user(), Keypair().pubkey()
    assert do_pay(c, job, pay_token(c, job, payee, wallet), payee, wallet), c.err
    assert c.balance(pay.ata(wallet, c.test_usdc)) == 4_950_000
    r = pay.read_rep(c.data(pay.rep_pda(payee)))
    assert (r.paid, r.test_paid, r.test_total, r.first) == (0, 1, 4_950_000, 0)
    # unproven, the test USDC goes back to the faucet Balance, where the next comment finds it
    c.warp(pay.FUND_PERIOD)
    n3 = issue()
    tok4 = faucet_token(c, n3, org, repo, work=60)
    assert c.send([pay.faucet_open_ix(c.payer.pubkey(), tok4, c.key, org, repo), pay.fund_balance_ix(c.payer.pubkey(), tok4, c.key, fbal, c.test_usdc, repo, n3, TERMS)]), c.err
    c.warp(61)
    assert refund(c, pay.job_pda(repo, n3, fbal)), c.err
    assert c.balance(pay.baltok_pda(fbal)) == 5 * USDC


def test_the_faucet_exists_once_and_the_real_money_build_has_none(chain):
    c = chain
    assert not c.send([pay.init_faucet_ix(c.payer.pubkey())]) and code(c) == 80          # the mint exists
    d = c.data(c.test_usdc)
    assert (Pubkey.from_bytes(d[4:36]), d[44], d[46:50]) == (pay.auth_pda(), 6, bytes(4))  # mint authority: the program; 6 decimals; no freeze authority
    real = setup(Chain("knos_pay_v2_nodevnet.so"))
    assert not real.send([pay.init_faucet_ix(real.payer.pubkey())]) and code(real) == 89
    tok = fund_token(real, 1, 5 * USDC)
    assert not real.send([pay.faucet_open_ix(real.payer.pubkey(), tok, real.key, OWNER, REPO)]) and code(real) == 89
    # everything else is the same program
    job = fund_balance(real, amount=5 * USDC)
    wallet = proven(real, job)
    assert real.balance(pay.ata(wallet, real.usdc)) == 4_950_000


def test_the_faucet_mints_nothing_for_a_token_that_names_another_balance(chain):
    c = chain
    supply = lambda: int.from_bytes(c.data(c.test_usdc)[36:44], "little")  # noqa: E731
    n, minted = issue(), supply()
    # the repository's owner has a Balance of real money and the comment's token names it: the faucet has nothing for it
    tok = fund_token(c, n)
    ix = pay.faucet_open_ix(c.payer.pubkey(), tok, c.key, OWNER, REPO)
    assert account(ix, "balance") == pay.faucet_balance_pda(OWNER)
    assert not c.send([ix]) and code(c) == 87
    # nor with the Balance it names passed in the faucet Balance's place
    assert not c.send([swap(swap(ix, "balance", c.bal), "baltok", pay.baltok_pda(c.bal))]) and code(c) == 80
    # a token that names the faucet Balance of another owner opens neither that one nor this owner's
    org = user()
    tok2 = fund_token(c, n, balance=pay.faucet_balance_pda(org))
    assert not c.send([pay.faucet_open_ix(c.payer.pubkey(), tok2, c.key, OWNER, REPO)]) and code(c) == 87
    assert not c.send([pay.faucet_open_ix(c.payer.pubkey(), tok2, c.key, org, REPO)]) and code(c) == 80
    assert supply() == minted and c.data(pay.faucet_balance_pda(OWNER)) is None and c.data(pay.faucet_balance_pda(org)) is None
    assert pay.read_rate(c.data(pay.rate_pda(REPO))) == (0, 0)
    # the first token still does what it says: it funds from the Balance it names
    assert c.send([pay.fund_balance_ix(c.payer.pubkey(), tok, c.key, c.bal, c.usdc, REPO, n, TERMS)]), c.err


# -- the key that verified a token -----------------------------------------------------------------------------------------
def each_use(c: Chain) -> dict[str, Instruction]:
    """One instruction of each kind that takes a token, ready to send, its token verified now: a comment funds a job
    from the owner's Balance, the faucet opens for a repository without one, a proof pays a wallet's job, a user binds
    a wallet."""
    me, n, org, repo, who, wallet = c.payer.pubkey(), issue(), user(), user(), user(), Keypair().pubkey()
    job = fund_wallet(c)
    c.token_account(wallet, c.usdc)
    return {"FundBalance": pay.fund_balance_ix(me, fund_token(c, n), c.key, c.bal, c.usdc, REPO, n, TERMS),
            "FaucetOpen": pay.faucet_open_ix(me, faucet_token(c, n, org, repo), c.key, org, repo),
            "Pay": pay_ix(c, me, pay_token(c, job, AUTHOR, wallet), c.key, job, pay.read_job(c.data(job)), AUTHOR, wallet),
            "Bind": pay.bind_ix(me, bind_token(c, who, wallet), c.key, who)}


def untouched(c: Chain, uses: dict[str, Instruction]) -> tuple:
    """What the four instructions of `each_use` would change."""
    fund, faucet, paid, bound = (uses[k] for k in ("FundBalance", "FaucetOpen", "Pay", "Bind"))
    return (c.data(account(fund, "job")), c.balance(account(fund, "baltok")), c.data(account(faucet, "balance")), c.data(account(faucet, "rate")),
            c.data(account(paid, "job")), c.balance(account(paid, "destToken")), c.balance(account(paid, "vault")), c.data(account(bound, "bind")))


def test_a_token_is_taken_only_with_the_key_account_it_names(chain):
    """Every instruction that takes a token takes the verifier's account of the key that verified it, and nothing in
    its place: not another key of the verifier's that is just as good, not a copy of the key's bytes, not a token account."""
    c = chain
    uses = each_use(c)
    wrong = {"another key of the verifier's": other_key(c), "the key's bytes in an account of the escrow's": _forged(c, c.key),
             "the key's bytes in an account of nobody's": _forged(c, c.key, pay.SYSTEM), "a token account": account(uses["Pay"], "payToken")}
    assert all(oidc.key_usable(oidc.read_key(c.data(k)), c.now()) == (True, "") for k in (c.key, wrong["another key of the verifier's"]))
    before = untouched(c, uses)
    for name, ix in uses.items():
        assert account(ix, "key") == c.key == c.key_of(ix.accounts[1].pubkey)
        for what, key in wrong.items():
            assert not c.send([swap(ix, "key", key)]) and code(c) == 80, (name, what, c.err)
    assert untouched(c, uses) == before
    for name, ix in uses.items():
        assert c.send([ix]), (name, c.err)


def test_a_token_is_refused_once_its_key_is_revoked():
    """On a chain of its own: a revocation is for ever. The verifier's guardian revokes GitHub's signing key (it leaked,
    say). From that transaction on the escrow moves nothing on that key's word, the tokens it verified earlier
    included. What needs no token goes on, so no money is stuck."""
    c = setup(Chain())
    assert c.send([pay.init_faucet_ix(c.payer.pubkey())]), c.err
    other = other_key(c)
    # a job proven for a payee without a wallet, who then binds one; and a job nobody has proven
    held, late, late_wallet = fund_wallet(c), user(), Keypair().pubkey()
    assert do_pay(c, held, pay_token(c, held, late), late), c.err
    assert bind(c, late, late_wallet), c.err
    unproven = fund_balance(c, work=600)
    uses = each_use(c)
    before = untouched(c, uses)
    # the escrow asks the verifier's whole rule. No instruction puts a key that has verified back to "not active yet",
    # so that state is written here by hand: it is refused with the verifier's code for it
    real = c.svm.get_account(c.key)
    waiting = bytes(real.data[:8]) + (c.now() + 60).to_bytes(8, "little") + bytes(real.data[16:])
    c.svm.set_account(c.key, Account(lamports=real.lamports, data=waiting, owner=real.owner, executable=False))
    assert oidc.key_usable(oidc.read_key(c.data(c.key)), c.now())[0] is False and not oidc.read_key(c.data(c.key)).revoked
    for name, ix in uses.items():
        assert not c.send([ix]) and code(c) == 76, (name, c.err)
    c.svm.set_account(c.key, real)
    assert c.revoke(oidc.GITHUB, c.github), c.err
    assert oidc.read_key(c.data(c.key)).revoked
    for name, ix in uses.items():
        assert not c.send([ix]) and code(c) == 78, (name, c.err)
        # a key of the verifier's that is still good, passed in its place, does not help: the token names its key
        assert not c.send([swap(ix, "key", other)]) and code(c) == 80, (name, c.err)
    assert untouched(c, uses) == before
    # the verifier verifies nothing new with that key either
    assert c.gh(pay.bind_audience(late_wallet)) is None and code(c) == 78
    # what needs no token: the held job is paid to the wallet its payee bound, the open jobs go back to their funders at
    # their deadlines, and the Balance's wallet takes its unspent money back
    c.token_account(late_wallet, c.usdc)
    assert c.send([pay.settle_ix(c.payer.pubkey(), held, pay.read_job(c.data(held)), late_wallet)]), c.err
    assert c.balance(pay.ata(late_wallet, c.usdc)) == 4_950_000
    c.warp(14 * DAY + 1)
    for job in (unproven, account(uses["Pay"], "job")):
        assert refund(c, job), c.err
    assert c.balance(pay.vault_pda(c.usdc)) == 0
    assert c.send([pay.withdraw_ix(c.owner.pubkey(), c.bal, c.usdc)], c.owner) and c.balance(pay.baltok_pda(c.bal)) == 0, c.err


def test_a_token_is_refused_while_its_key_is_expired_and_works_again_once_the_key_is_refreshed():
    """On a chain of its own: the clock moves a month. A key expires 30 days after GitHub's signature last named it.
    From that second the escrow refuses the tokens it verified. When the rotate workflow's attestation refreshes the
    key, the same tokens work again for what is left of their own time."""
    c = setup(Chain())
    assert c.send([pay.init_faucet_ix(c.payer.pubkey())]), c.err
    second = c.second_key()                             # another key of GitHub's: it lives a day longer than the first
    expires = oidc.read_key(c.data(c.key)).expires_at
    assert expires == NOW + oidc.KEY_TTL == NOW + 30 * DAY
    c.warp(expires - c.now() - 240)                     # four minutes before the key expires
    in_time, wallet = fund_wallet(c), Keypair().pubkey()
    last = pay_token(c, in_time, AUTHOR, wallet)
    uses = each_use(c)
    # GitHub names its key again. The verifier takes an attestation only while the key that verified it is usable, so
    # one verified under the key that is about to expire is worth nothing afterwards; one under the second key is
    stale, attest = c.attest(oidc.GITHUB, c.github), c.attest(oidc.GITHUB, c.github, by=second)
    assert stale is not None and attest is not None, c.err
    c.warp(expires - c.now() - 1)
    assert do_pay(c, in_time, last, AUTHOR, wallet), c.err   # the key's last second
    before = untouched(c, uses)
    c.warp(1)
    assert not oidc.key_usable(oidc.read_key(c.data(c.key)), c.now())[0]
    for name, ix in uses.items():
        assert not c.send([ix]) and code(c) == 77, (name, c.err)
    assert untouched(c, uses) == before
    assert c.gh(pay.bind_audience(wallet)) is None and code(c) == 77      # the verifier verifies nothing new with it either
    assert not c.refresh(oidc.GITHUB, c.github, stale) and code(c) == 77
    assert c.refresh(oidc.GITHUB, c.github, attest), c.err
    assert oidc.read_key(c.data(c.key)).expires_at == c.now() + oidc.KEY_TTL
    for name, ix in uses.items():
        assert c.send([ix]), (name, c.err)
    assert untouched(c, uses) != before and c.data(account(uses["Pay"], "job")) is None


# -- the guardian's pause --------------------------------------------------------------------------------------------------
def test_the_guardian_pauses_new_funding_only_and_nobody_else_can(chain):
    c = chain
    pause = lambda seconds, who=GUARDIAN: c.send([pay.pause_ix(who.pubkey(), c.payer.pubkey(), seconds)], signers=[who], tag="pause")  # noqa: E731
    open_job, held_job, due_job = fund_wallet(c), fund_balance(c), fund_wallet(c, work_s=60)
    held_for = user()
    assert do_pay(c, held_job, pay_token(c, held_job, held_for), held_for), c.err
    stranger = c.fund()
    assert not pause(3600, stranger) and code(c) == 97
    assert not pause(0, c.owner) and code(c) == 97
    unsigned = Instruction(pay.PAY_ID, bytes(pay.pause_ix(GUARDIAN.pubkey(), c.payer.pubkey(), 3600).data),
                           [AccountMeta(GUARDIAN.pubkey(), False, False), *pay.pause_ix(GUARDIAN.pubkey(), c.payer.pubkey(), 3600).accounts[1:]])
    assert not c.send([unsigned]) and code(c) == 97
    assert not pause(pay.PAUSE_MAX + 1) and code(c) == 81
    assert not c.send([swap(pay.pause_ix(GUARDIAN.pubkey(), c.payer.pubkey(), 60), "pause", pay.rate_pda(1))], signers=[GUARDIAN]) and code(c) == 80
    assert pay.read_pause(c.data(pay.pause_pda())) == 0
    assert pause(pay.PAUSE_MAX), c.err
    until = c.now() + pay.PAUSE_MAX
    assert pay.read_pause(c.data(pay.pause_pda())) == until and c.said("knos2:") == [f"knos2:paused until={until}"]
    # new funding is refused, from a Balance and from a wallet
    n = issue()
    tok = fund_token(c, n)
    assert not c.send([pay.fund_balance_ix(c.payer.pubkey(), tok, c.key, c.bal, c.usdc, REPO, n, TERMS)]) and code(c) == 96
    ix = pay.fund_wallet_ix(c.funder.pubkey(), c.funder_tok, c.usdc, REPO, n, 5 * USDC, WF_REPO, WF_SHA, TERMS)
    assert not c.send([ix], c.funder) and code(c) == 96
    # everything that lets money out, or only prepares it, goes on: a proof pays, a held job settles, a job past its
    # deadline refunds, a wallet binds, a Balance is opened, topped up, changed and withdrawn
    proven(c, open_job)
    wallet = Keypair().pubkey()
    assert bind(c, held_for, wallet), c.err
    c.token_account(wallet, c.usdc)
    assert c.send([pay.settle_ix(c.payer.pubkey(), held_job, pay.read_job(c.data(held_job)), wallet)]), c.err
    c.warp(61)
    assert refund(c, due_job), c.err
    w, wtok = c.wallet(c.usdc, 10 * USDC)
    org = user()
    assert c.send([pay.open_balance_ix(w.pubkey(), org, c.usdc)], w), c.err
    bal = pay.balance_pda(org, w.pubkey(), c.usdc)
    transfer(c, wtok, pay.baltok_pda(bal), 10 * USDC, w)
    assert c.send([pay.set_balance_ix(w.pubkey(), bal, cap=USDC)], w), c.err
    assert c.send([pay.withdraw_ix(w.pubkey(), bal, c.usdc)], w) and c.balance(wtok) == 10 * USDC, c.err
    # the pause ends by itself
    c.warp(until - c.now() - 1)
    assert not c.send([ix], c.funder) and code(c) == 96
    c.warp(1)
    assert c.send([ix], c.funder), c.err
    # and the guardian can lift one early
    assert pause(3600), c.err
    assert not c.send([pay.fund_balance_ix(c.payer.pubkey(), fund_token(c, n), c.key, c.bal, c.usdc, REPO, n, TERMS)]) and code(c) == 96
    assert pause(0), c.err
    assert pay.read_pause(c.data(pay.pause_pda())) == 0
    assert c.send([pay.fund_balance_ix(c.payer.pubkey(), fund_token(c, n), c.key, c.bal, c.usdc, REPO, n, TERMS)]), c.err


# -- mints -------------------------------------------------------------------------------------------------------------
def test_a_token_2022_stablecoin_with_its_usual_extensions_works_end_to_end(chain):
    """A Token-2022 mint with extensions on the allow-list: ConfidentialTransfer and a mint close authority. (The
    stablecoins that also carry a permanent delegate, a transfer hook authority or a transfer fee are refused since
    2.1: tests/test_order_chain.py.)"""
    c = chain
    coin = c.new_mint22(confidential=True, close_authority=True)
    t22 = pay.TOKEN_2022
    assert c.token_program(coin) == t22 and len(c.data(coin)) > 165
    fee = c.token_account(pay.FEE_OWNER, coin)
    w, wtok = c.wallet(coin, 1_000 * USDC)
    org, repo = user(), user()
    # a Balance: opened, topped up, spent by a comment, paid to the address in the proof
    assert c.send([pay.open_balance_ix(w.pubkey(), org, coin, spenders=[MAINT], token_program=t22)], w, tag="open_balance_2022"), c.err
    bal = pay.balance_pda(org, w.pubkey(), coin)
    baltok = pay.baltok_pda(bal)
    assert c.svm.get_account(baltok).owner == t22 and len(c.data(baltok)) >= 165      # sized by GetAccountDataSize: whatever the mint's extensions need
    transfer(c, wtok, baltok, 300 * USDC, w, coin)
    job = fund_balance(c, amount=100 * USDC, balance=bal, repo=repo, repository_owner_id=org, repository_id=repo)
    j = pay.read_job(c.data(job))
    assert (j.token_program, j.mint, j.amount, j.faucet) == (t22, coin, 100 * USDC, False)
    vault = pay.vault_pda(coin)
    assert c.svm.get_account(vault).owner == t22 and (c.balance(vault), c.balance(baltok)) == (100 * USDC, 200 * USDC)
    payee, wallet = user(), Keypair().pubkey()
    assert do_pay(c, job, pay_token(c, job, payee, wallet), payee, wallet), c.err
    assert (c.balance(pay.ata(wallet, coin, t22)), c.balance(fee), c.balance(vault)) == (99_700_000, 300_000, 0)
    # a wallet's job: held, then settled after the payee binds
    job = fund_wallet(c, amount=10 * USDC, funder=w, funder_tok=wtok, mint=coin)
    late = user()
    assert do_pay(c, job, pay_token(c, job, late), late), c.err
    bound = Keypair().pubkey()
    assert bind(c, late, bound), c.err
    c.token_account(bound, coin)
    assert c.send([pay.settle_ix(c.payer.pubkey(), job, pay.read_job(c.data(job)), bound)], tag="settle_2022"), c.err
    assert c.balance(pay.ata(bound, coin, t22)) == 9_950_000
    # unproven jobs refund: to the Balance, to the wallet; the rest of the Balance is withdrawn
    from_balance = fund_balance(c, amount=50 * USDC, balance=bal, repo=repo, work=60, repository_owner_id=org, repository_id=repo)
    from_wallet = fund_wallet(c, amount=20 * USDC, funder=w, funder_tok=wtok, mint=coin, work_s=60)
    before = c.balance(wtok)
    c.warp(61)
    assert refund(c, from_balance) and refund(c, from_wallet), c.err
    assert (c.balance(baltok), c.balance(wtok), c.balance(vault)) == (200 * USDC, before + 20 * USDC, 0)
    assert c.send([pay.withdraw_ix(w.pubkey(), bal, coin, token_program=t22)], w, tag="withdraw_2022"), c.err
    assert (c.balance(baltok), c.balance(wtok)) == (0, before + 220 * USDC)
    # the two token programs do not mix: the classic program is refused for this mint, and a classic token account as destination
    ix = pay.fund_wallet_ix(w.pubkey(), wtok, coin, REPO, issue(), 5 * USDC, WF_REPO, WF_SHA, TERMS, token_program=pay.TOKEN)
    assert not c.send([ix], w) and code(c) == 95
    job = fund_wallet(c, funder=w, funder_tok=wtok, mint=coin)
    ix = pay_ix(c, c.payer.pubkey(), pay_token(c, job, payee, wallet), c.key, job, pay.read_job(c.data(job)), payee, wallet)
    assert not c.send([swap(ix, "destToken", c.funder_tok)]) and code(c) == 88
    assert not c.send([swap(ix, "tokenProgram", pay.TOKEN)]) and code(c) == 95
    assert c.send([ix]), c.err


# what the mint is -> the keyword arguments of Chain.new_mint22
SOMEONE = Pubkey.from_bytes(bytes([9]) * 32)
REFUSED_MINTS = {
    "non-transferable": dict(non_transferable=True),
    "one whose new accounts start frozen": dict(default_state=2),
    "one with a transfer hook program": dict(hook=(SOMEONE, SOMEONE)),
    "one with a transfer fee": dict(fee=(100, 5 * USDC)),
    "one with a transfer fee and the stablecoins' other extensions": dict(fee=(1, 1), confidential=True, permanent_delegate=SOMEONE, hook=(SOMEONE, None)),
    "one with a transfer fee scheduled": "scheduled",
    "one whose transfer fee is still charged, its end scheduled": "ending",
}


@pytest.mark.parametrize("what", list(REFUSED_MINTS))
def test_no_money_enters_in_a_mint_that_is(chain, what):
    c = chain
    how = REFUSED_MINTS[what]
    if how == "scheduled":
        mint = c.new_mint22(fee=(0, 0))
        c.set_fee22(mint, 50, 10 * USDC)        # the older fee is still zero; the newer one takes effect two epochs on
    elif how == "ending":
        mint = c.new_mint22(fee=(100, 5 * USDC))
        c.set_fee22(mint, 0, 0)                 # the newer fee is zero; the older one is charged until then
    else:
        mint = c.new_mint22(**how)
    w = c.fund()
    assert not c.send([pay.open_balance_ix(w.pubkey(), OWNER, mint, token_program=pay.TOKEN_2022)], w) and code(c) == 95, c.err
    ix = pay.fund_wallet_ix(w.pubkey(), w.pubkey(), mint, REPO, issue(), 5 * USDC, WF_REPO, WF_SHA, TERMS, token_program=pay.TOKEN_2022)
    assert not c.send([ix], w) and code(c) == 95, c.err
    assert c.data(pay.vault_pda(mint)) is None


def test_a_mint_is_a_mint_of_the_token_program_passed_and_harmless_extensions_are_accepted(chain):
    c = chain
    w = c.fund()
    open_ = lambda mint, program: c.send([pay.open_balance_ix(w.pubkey(), user(), mint, token_program=program)], w)  # noqa: E731
    # not a mint at all: a wallet, a token account, an account of another program, an uninitialised mint
    blank = Keypair()
    ixs = [create_account(CreateAccountParams(from_pubkey=c.payer.pubkey(), to_pubkey=blank.pubkey(), lamports=c.svm.minimum_balance_for_rent_exemption(82),
                                              space=82, owner=pay.TOKEN))]
    assert c.send(ixs, signers=[blank]), c.err
    for not_a_mint in (w.pubkey(), c.funder_tok, c.bal, blank.pubkey()):
        assert not open_(not_a_mint, pay.TOKEN) and code(c) == 95
    # a real mint with the wrong token program, either way round
    plain22 = c.new_mint22()
    assert not open_(c.usdc, pay.TOKEN_2022) and code(c) == 95
    assert not open_(plain22, pay.TOKEN) and code(c) == 95
    assert not open_(c.usdc, pay.ATA_PROGRAM) and code(c) == 95
    # accepted: no extensions, and the ones on the allow-list
    for mint in (plain22, c.new_mint22(close_authority=True), c.new_mint22(confidential=True)):
        assert open_(mint, pay.TOKEN_2022), c.err
    # refused since 2.1, whatever they hold today: a fee that takes nothing, an initialised default state, a hook and a
    # delegate with nobody behind them
    for mint in (c.new_mint22(fee=(0, 9 * USDC)), c.new_mint22(fee=(250, 0)), c.new_mint22(default_state=1),
                 c.new_mint22(hook=(SOMEONE, None)), c.new_mint22(permanent_delegate=c.payer.pubkey())):
        assert not open_(mint, pay.TOKEN_2022) and code(c) == 95
    # a 9-decimal SPL Token mint: the bounds are whole units of it, and TransferChecked carries its decimals
    nine = c.new_mint(9)
    k, ktok = c.wallet(nine, 50 * 10 ** 9)
    c.token_account(pay.FEE_OWNER, nine)
    job = fund_wallet(c, amount=5 * 10 ** 9, funder=k, funder_tok=ktok, mint=nine)
    wallet = proven(c, job)
    assert c.balance(pay.ata(wallet, nine)) == 4_950_000_000


def add_extension(c: Chain, mint: Pubkey, kind: int, value: bytes) -> None:
    """Rewrites a plain Token-2022 mint as the same mint with one extension: how a mint that entered under the rules
    of 2.0 with an extension 2.1 refuses stands on chain."""
    a = c.svm.get_account(mint)
    data = bytes(a.data)[:82] + bytes(83) + b"\x01" + kind.to_bytes(2, "little") + len(value).to_bytes(2, "little") + value
    c.svm.set_account(mint, Account(a.lamports + 10 ** 7, data, a.owner))


def test_a_mint_that_turns_bad_takes_no_new_money_and_money_in_escrow_still_leaves(chain):
    c = chain
    coin = c.new_mint22()
    c.token_account(pay.FEE_OWNER, coin)
    w, wtok = c.wallet(coin, 100 * USDC)
    org, repo = user(), user()
    assert c.send([pay.open_balance_ix(w.pubkey(), org, coin, token_program=pay.TOKEN_2022)], w), c.err
    bal = pay.balance_pda(org, w.pubkey(), coin)
    transfer(c, wtok, pay.baltok_pda(bal), 60 * USDC, w, coin)
    job = fund_balance(c, amount=10 * USDC, balance=bal, repo=repo, actor=org, repository_owner_id=org, repository_id=repo)
    add_extension(c, coin, 12, bytes(c.payer.pubkey()))     # the mint now carries a permanent delegate
    # no new job in this mint, from the Balance or from a wallet
    n = issue()
    tok = fund_token(c, n, actor=org, balance=bal, repository_owner_id=org, repository_id=repo)
    assert not c.send([pay.fund_balance_ix(c.payer.pubkey(), tok, c.key, bal, coin, repo, n, TERMS, pay.TOKEN_2022)]) and code(c) == 95
    ix = pay.fund_wallet_ix(w.pubkey(), wtok, coin, REPO, n, 5 * USDC, WF_REPO, WF_SHA, TERMS, token_program=pay.TOKEN_2022)
    assert not c.send([ix], w) and code(c) == 95
    # what is in escrow is paid, and the Balance's unspent money is withdrawn
    payee, wallet = user(), Keypair().pubkey()
    assert do_pay(c, job, pay_token(c, job, payee, wallet), payee, wallet), c.err
    assert c.balance(pay.ata(wallet, coin, pay.TOKEN_2022)) == 9_950_000 and c.balance(pay.vault_pda(coin)) == 0
    assert c.send([pay.withdraw_ix(w.pubkey(), bal, coin, token_program=pay.TOKEN_2022)], w), c.err
    assert c.balance(wtok) == 90 * USDC


def test_an_address_that_was_sent_lamports_before_it_exists_is_still_created(chain):
    """Anyone can send lamports to an address the program will use: that must not block a job, a vault, a record or a bind."""
    c = chain
    coin = c.new_mint()
    c.token_account(pay.FEE_OWNER, coin)
    w, wtok = c.wallet(coin, 100 * USDC)
    n, payee, org = issue(), user(), user()
    job, bal = pay.job_pda(REPO, n, w.pubkey()), pay.balance_pda(org, w.pubkey(), coin)
    for address in (job, pay.vault_pda(coin), pay.rep_pda(payee), pay.pair_pda(payee, w.pubkey()), pay.bind_pda(payee), bal, pay.baltok_pda(bal)):
        c.svm.airdrop(address, 5_000_000)
    assert fund_wallet(c, n, 10 * USDC, w, wtok, coin) == job
    assert c.send([pay.open_balance_ix(w.pubkey(), org, coin)], w), c.err
    wallet = Keypair().pubkey()
    assert bind(c, payee, wallet), c.err
    assert do_pay(c, job, pay_token(c, job, payee), payee, wallet), c.err
    assert c.balance(pay.ata(wallet, coin)) == 9_950_000 and pay.read_rep(c.data(pay.rep_pda(payee))).test_paid == 1
    assert c.lamports(w.pubkey()) > 0 and c.data(job) is None


def test_a_job_is_paid_and_refunded_whatever_the_account_its_rent_goes_to_has_become(chain):
    """A fund token is public, so anyone can be the relayer a job's rent goes back to. Whatever that relayer later
    turns its account into (here: a program), the job is still paid and still refunded: the money is not the relayer's
    to lock."""
    c = chain
    k = c.fund(1)
    jobs = []
    for work in (14 * DAY, 600):
        n = issue()
        tok = fund_token(c, n, work=work)
        assert c.send([pay.fund_balance_ix(k.pubkey(), tok, c.key, c.bal, c.usdc, REPO, n, TERMS)], k), c.err
        jobs.append(pay.job_pda(REPO, n, c.bal))
    assert all(pay.read_job(c.data(j)).rent_to == k.pubkey() for j in jobs)
    c.svm.add_program_from_file(k.pubkey(), str(Path(__file__).parent / "fixtures" / "knos_oidc_v2_test.so"))
    assert c.svm.get_account(k.pubkey()).executable
    before = c.lamports(k.pubkey())
    wallet = proven(c, jobs[0])
    assert c.balance(pay.ata(wallet, c.usdc)) == 4_950_000 and c.data(jobs[0]) is None
    c.warp(601)
    assert refund(c, jobs[1]), c.err
    assert c.data(jobs[1]) is None and c.lamports(k.pubkey()) == before + 2 * 3_118_080


def test_a_frozen_or_missing_destination_moves_nothing_and_one_transaction_takes_a_job_once(chain):
    """A payment is all or nothing: when the payee's part cannot move, the fee does not move either and the job stays
    open for the same proof. And a job closes in the instruction that pays it: a second payment or a refund later in
    the same transaction finds no job, so the whole transaction moves nothing."""
    c = chain
    coin = c.new_mint22()                         # its freeze authority is the chain's payer
    fee_tok = c.token_account(pay.FEE_OWNER, coin)
    w, wtok = c.wallet(coin, 100 * USDC)
    job = fund_wallet(c, amount=10 * USDC, funder=w, funder_tok=wtok, mint=coin)
    j, payee, wallet = pay.read_job(c.data(job)), user(), Keypair().pubkey()
    dest, vault = c.token_account(wallet, coin), pay.vault_pda(coin)
    tok = pay_token(c, job, payee, wallet)
    ix = pay_ix(c, c.payer.pubkey(), tok, c.key, job, j, payee, wallet)

    def untouched() -> bool:
        return (c.balance(vault), c.balance(fee_tok), c.balance(dest), pay.read_job(c.data(job)).state) == (10 * USDC, 0, 0, "open")

    def freeze(tag: int) -> Instruction:          # 10 FreezeAccount, 11 ThawAccount
        return Instruction(pay.TOKEN_2022, bytes([tag]), [AccountMeta(dest, False, True), AccountMeta(coin, False, False), AccountMeta(c.payer.pubkey(), True, False)])

    assert c.send([freeze(10)]), c.err
    assert not c.send([ix]) and code(c) == 17 and untouched(), c.err              # the token program's "account is frozen"
    assert not c.send([pay_ix(c, c.payer.pubkey(), tok, c.key, job, j, payee, wallet, Keypair().pubkey())]) and code(c) == 88 and untouched()
    assert c.send([freeze(11)]), c.err
    assert not c.send([ix, ix]) and code(c) == 82 and untouched(), c.err
    assert not c.send([ix, pay.refund_ix(c.payer.pubkey(), job, j)]) and code(c) == 82 and untouched(), c.err
    assert c.send([ix]), c.err
    assert (c.balance(vault), c.balance(fee_tok), c.balance(dest), c.data(job)) == (0, 50_000, 9_950_000, None)


def test_tokens_sent_to_a_vault_directly_belong_to_no_job_and_stay_there(chain):
    c = chain
    coin = c.new_mint()
    c.token_account(pay.FEE_OWNER, coin)
    w, wtok = c.wallet(coin, 100 * USDC)
    first = fund_wallet(c, amount=10 * USDC, funder=w, funder_tok=wtok, mint=coin)        # creates the vault
    vault = pay.vault_pda(coin)
    transfer(c, wtok, vault, 3 * USDC, w, coin)                                           # a gift, or a mistake
    second = fund_wallet(c, amount=20 * USDC, funder=w, funder_tok=wtok, mint=coin, work_s=60)
    assert (pay.read_job(c.data(first)).amount, pay.read_job(c.data(second)).amount, c.balance(vault)) == (10 * USDC, 20 * USDC, 33 * USDC)
    wallet = proven(c, first)
    c.warp(61)
    assert refund(c, second), c.err
    assert (c.balance(pay.ata(wallet, coin)), c.balance(wtok), c.balance(vault)) == (9_950_000, 87 * USDC, 3 * USDC)


def test_a_mints_issuer_keeps_its_powers_over_the_vault_and_the_job_waits(chain):
    """A permanent delegate can move tokens out of any account, a vault included. Since 2.1 no money enters in such
    a mint; a job funded before that (the mint is rewritten here to carry the delegate) keeps its books: it stays
    open and is paid when the money is back."""
    c = chain
    issuer = c.payer
    coin = c.new_mint22()
    c.token_account(pay.FEE_OWNER, coin)
    w, wtok = c.wallet(coin, 100 * USDC)
    job = fund_wallet(c, amount=10 * USDC, funder=w, funder_tok=wtok, mint=coin)
    add_extension(c, coin, 12, bytes(issuer.pubkey()))
    vault, seized = pay.vault_pda(coin), c.token_account(issuer.pubkey(), coin)
    transfer(c, vault, seized, 4 * USDC, issuer, coin)             # the issuer's delegate signs, not the program
    assert c.balance(vault) == 6 * USDC and pay.read_job(c.data(job)).amount == 10 * USDC
    payee, wallet = user(), Keypair().pubkey()
    tok = pay_token(c, job, payee, wallet)
    assert not do_pay(c, job, tok, payee, wallet) and pay.read_job(c.data(job)).state == "open"      # the token program: not enough in the vault
    transfer(c, seized, vault, 4 * USDC, issuer, coin)
    assert do_pay(c, job, tok, payee, wallet), c.err
    assert c.balance(pay.ata(wallet, coin, pay.TOKEN_2022)) == 9_950_000 and c.balance(vault) == 0


# -- the invariant -------------------------------------------------------------------------------------------------------
def test_a_random_walk_keeps_every_vault_equal_to_its_open_jobs():
    """Random valid operations (600 by default; KNOS_FUZZ_N sets the number, KNOS_FUZZ_SEED the seed), in an SPL Token
    mint and a Token-2022 mint. After every step, for each mint: the vault holds exactly the amounts of the open and
    held jobs. At the end every job left is refunded with no token, half a year on, and both vaults are empty:
    funded == paid + fees + refunded."""
    c = Chain()
    rng = random.Random(FUZZ_SEED)
    mints = [c.new_mint(), c.new_mint22(confidential=True, close_authority=True)]
    owner = c.fund(1_000)
    funder = c.fund(1_000)
    users = [9001, 9002, 9003, 9004]
    wallets = {u: Keypair().pubkey() for u in users}
    bound: dict[int, Pubkey] = {}
    side = []
    for m in mints:
        tp = c.token_program(m)
        c.token_account(pay.FEE_OWNER, m)
        otok, ftok = c.token_account(owner.pubkey(), m), c.token_account(funder.pubkey(), m)
        c.mint_to(m, otok, 10 ** 12)
        c.mint_to(m, ftok, 10 ** 12)
        assert c.send([pay.open_balance_ix(owner.pubkey(), OWNER, m, spenders=[MAINT], token_program=tp)], owner), c.err
        bal = pay.balance_pda(OWNER, owner.pubkey(), m)
        transfer(c, otok, pay.baltok_pda(bal), 2_000 * USDC, owner, m)
        for w in wallets.values():
            c.token_account(w, m)
        side.append(dict(mint=m, tp=tp, otok=otok, ftok=ftok, bal=bal, funded=0, paid=0, fees=0, refunded=0))
    jobs: dict[Pubkey, dict] = {}
    counts: dict[str, int] = {}
    n = 0

    def check(op: str) -> None:
        for s in side:
            owed = sum(j["amount"] for j in jobs.values() if j["side"] is s)
            assert c.balance(pay.vault_pda(s["mint"])) == owed, f"after {op}: vault {c.balance(pay.vault_pda(s['mint']))} != open jobs {owed}"

    def pick(want) -> Pubkey:
        """A job the operation should work on, most of the time; any job otherwise, so that its refusal is checked too."""
        pool = list(jobs)                 # in the order they were funded: the walk is the same for a seed, whatever the addresses
        good = [k for k in pool if want(jobs[k])]
        return rng.choice(good if good and rng.random() < 0.8 else pool)

    def paid(job: Pubkey, to: Pubkey) -> None:
        j = jobs.pop(job)
        s, fee = j["side"], pay.fee_of(j["amount"])
        s["paid"] += j["amount"] - fee
        s["fees"] += fee
        assert c.data(job) is None

    for _ in range(FUZZ_N):
        op = rng.choice(["fund_balance", "fund_balance", "fund_wallet", "pay", "pay", "pay", "settle", "refund", "bind", "withdraw", "top_up", "warp", "bad"])
        s = rng.choice(side)
        if op in ("fund_balance", "fund_wallet"):
            n += 1
            amount, work = rng.choice([1, 2, 5, 50, 500]) * USDC, rng.choice([120, 900, 3600])
            if op == "fund_balance":
                if c.balance(pay.baltok_pda(s["bal"])) < amount:       # the owner keeps the Balance topped up
                    transfer(c, s["otok"], pay.baltok_pda(s["bal"]), 1_000 * USDC, owner, s["mint"])
                tok = fund_token(c, n, amount, work=work, balance=s["bal"])
                ok = c.send([pay.fund_balance_ix(c.payer.pubkey(), tok, c.key, s["bal"], s["mint"], REPO, n, TERMS, s["tp"])])
                job = pay.job_pda(REPO, n, s["bal"])
            else:
                ok = c.send([pay.fund_wallet_ix(funder.pubkey(), s["ftok"], s["mint"], REPO, n, amount, WF_REPO, WF_SHA, TERMS, work_s=work, token_program=s["tp"])], funder)
                job = pay.job_pda(REPO, n, funder.pubkey())
            assert ok, c.err
            jobs[job] = dict(side=s, amount=amount, deadline=c.now() + work, held=None)
            s["funded"] += amount
        elif op in ("pay", "bad") and jobs:
            job = pick(lambda j: j["held"] is None and c.now() <= j["deadline"])
            j, u = jobs[job], rng.choice(users)
            address = rng.choice([None, wallets[u]])
            to = bound.get(u, address)
            tok = pay_token(c, job, u, address, **({"wf_sha": "e" * 40} if op == "bad" else {})) if c.data(job) else None
            ok = c.send([pay_ix(c, c.payer.pubkey(), tok, c.key, job, pay.read_job(c.data(job)), u, to)])
            if op == "bad" or j["held"] is not None or c.now() > j["deadline"]:
                assert not ok, f"{op}: a job that could not be paid was"
            else:
                assert ok, c.err
                if to is None:
                    j["held"] = u
                else:
                    paid(job, to)
        elif op == "settle" and jobs:
            job = pick(lambda j: j["held"] in bound)
            j = jobs[job]
            to = bound.get(j["held"]) or wallets[users[0]]
            ok = c.send([pay.settle_ix(c.payer.pubkey(), job, pay.read_job(c.data(job)), to)])
            assert ok == (j["held"] in bound), c.err
            if ok:
                paid(job, to)
        elif op == "refund" and jobs:
            job = pick(lambda j: j["held"] is None and c.now() > j["deadline"])
            j = jobs[job]
            ok = refund(c, job)
            assert ok == (j["held"] is None and c.now() > j["deadline"]), c.err
            if ok:
                j["side"]["refunded"] += jobs.pop(job)["amount"]
        elif op == "bind":
            u = rng.choice(users)
            assert bind(c, u, wallets[u]), c.err
            bound[u] = wallets[u]
        elif op == "withdraw":
            amount = min(rng.choice([1, 7]) * USDC, c.balance(pay.baltok_pda(s["bal"])))      # 0 would mean everything, and here is nothing
            assert c.send([pay.withdraw_ix(owner.pubkey(), s["bal"], s["mint"], amount, token_program=s["tp"])], owner), c.err
        elif op == "top_up":
            transfer(c, s["otok"], pay.baltok_pda(s["bal"]), rng.choice([10, 100]) * USDC, owner, s["mint"])
        elif op == "warp":
            c.warp(rng.choice([1, 61, 700]))
        counts[op] = counts.get(op, 0) + 1
        check(op)
    # half a year on, with no token from anyone: every job that is left goes back where it came from
    left = len(jobs)
    c.warp(pay.HOLD + 3601)
    for job in list(jobs):
        assert refund(c, job), c.err
        jobs[job]["side"]["refunded"] += jobs.pop(job)["amount"]
        check("final refund")
    for s in side:
        assert c.balance(pay.vault_pda(s["mint"])) == 0
        assert s["funded"] == s["paid"] + s["fees"] + s["refunded"]
        assert c.balance(pay.ata(pay.FEE_OWNER, s["mint"], s["tp"])) == s["fees"]
        assert sum(c.balance(pay.ata(w, s["mint"], s["tp"])) for w in wallets.values()) == s["paid"]
    total = {k: sum(s[k] for s in side) / USDC for k in ("funded", "paid", "fees", "refunded")}
    print(f"\nrandom walk: seed {FUZZ_SEED}, {FUZZ_N} steps {counts}; {total}; {left} jobs refunded at the end; 0 violations")


def test_compute_units_are_recorded(chain):
    """Not a limit of the program: what its instructions cost in this run, the token program's share included (LiteSVM's
    bundled token programs). Pay is measured over 16 payees, because the addresses it derives (bind, record, pair,
    vault) cost 1,500 units for each bump the derivation tries."""
    c = chain
    # The one transaction of two instructions, sent here: under pytest-xdist the faucet's own test can run in another
    # worker, with another chain, and then this run would have no measurement of it.
    org, repo, n = user(), user(), issue()
    tok = faucet_token(c, n, org, repo, actor=MAINT)
    assert c.send([pay.faucet_open_ix(c.payer.pubkey(), tok, c.key, org, repo),
                   pay.fund_balance_ix(c.payer.pubkey(), tok, c.key, pay.faucet_balance_pda(org), c.test_usdc, repo, n, TERMS)],
                  tag="faucet_open+fund_balance"), c.err
    coin = c.new_mint22(confidential=True, close_authority=True)
    c.token_account(pay.FEE_OWNER, coin)
    w, wtok = c.wallet(coin, 1_000 * USDC)
    for _ in range(16):
        payee, wallet = user(), Keypair().pubkey()
        proven(c, fund_wallet(c), payee, wallet, tag="Pay, the payee's first payment (creates the record and the pair)")
        proven(c, fund_wallet(c), payee, wallet, tag="Pay, a later payment from the same funder")
        proven(c, fund_wallet(c, funder=w, funder_tok=wtok, mint=coin), payee, wallet, tag="Pay, a Token-2022 mint with the stablecoins' extensions (first from this funder)")
        job, nobody = fund_wallet(c), user()
        assert do_pay(c, job, pay_token(c, job, nobody), nobody, tag="Pay, no wallet known (the job is held)"), c.err
    spread = lambda v: f"{min(v)}..{max(v)}, median {sorted(v)[len(v) // 2]}"  # noqa: E731
    print()
    for tag in sorted(t for t in c.cu if t.startswith("Pay,")):
        print(f"CU {tag}: {spread(c.cu[tag])}")
    top = {k: max(v) for k, v in sorted(c.cu.items()) if not k.startswith("Pay,")}
    print("CU of the other instructions, highest seen:", top)
    # Each instruction fits the default budget of ONE instruction (200,000). The one tag that is a transaction of two
    # (faucet_open+fund_balance) has a default budget of 400,000: it creates six accounts, and both of its
    # instructions hash the token's signature for its marker, as every instruction that takes a token does. Measured:
    # 233,372 (164,208 before the marker was everywhere and overflow was checked).
    two = "faucet_open+fund_balance"
    assert all(max(v) < (400_000 if k == two else 200_000) for k, v in c.cu.items()), {k: max(v) for k, v in c.cu.items() if max(v) >= 200_000}
    assert max(c.cu[two]) < 260_000
