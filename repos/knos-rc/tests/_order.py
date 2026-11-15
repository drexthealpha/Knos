"""Test harness for work orders (knos_pay 2.1) inside LiteSVM, built on tests/_pay2.py: a chain with a stand-in for
Circle's USDC that the test build's record counts as real money, FEE_OWNER's fee account, a repository owner's
Balance, a sponsor's wallet and the relayer's own token account for tips; and the tokens GitHub would sign for an
order. Tests only."""
from __future__ import annotations

import re

from solders.instruction import AccountMeta, Instruction
from solders.keypair import Keypair
from solders.pubkey import Pubkey

from _pay2 import PLAN_SIGNER, USDC_KEY, WF_REPO, WF_SHA, Chain

from knos.settle.v2 import order_auto, pay

REPO, OWNER, MAINT, AUTHOR = 987654321, 424242, 555000, 1234567    # the repository, its owner, a maintainer, a contributor
USDC, DAY, HEAD = 1_000_000, 86_400, "a" * 40
TERMS = pay.terms_json({"accept": "", "checks": [{"app": 15368, "name": "test"}], "mode": "merge", "v": 2})
TH = pay.terms_hash(TERMS)
# terms paid by the black-box acceptance suite (mode 1): what an AUTO order is funded on
SUITE = pay.terms_json({"accept": "5e" * 32, "checks": [], "mode": "tests", "v": 2})
SELLER_REPO = 700_700_700       # a repository a stranger owns: nothing of the buyer's is in it
_COUNT = [1000, 9_000_000]


def issue() -> int:
    _COUNT[0] += 1
    return _COUNT[0]


def user() -> int:
    """A GitHub id nobody has used yet."""
    _COUNT[1] += 1
    return _COUNT[1]


def code(c: Chain) -> int | None:
    m = re.search(r"Custom\((\d+)\)", c.err or "")
    return int(m.group(1)) if m else None


def swap(ix: Instruction, index: int, key: Pubkey) -> Instruction:
    """The same instruction with the account at `index` replaced."""
    acc = list(ix.accounts)
    acc[index] = AccountMeta(key, acc[index].is_signer, acc[index].is_writable)
    return Instruction(ix.program_id, bytes(ix.data), acc)


def transfer(c: Chain, source: Pubkey, dest: Pubkey, amount: int, owner: Keypair, mint: Pubkey | None = None, decimals: int = 6) -> None:
    """A plain TransferChecked, as any wallet would send it."""
    mint = mint or c.usdc
    ix = Instruction(c.token_program(mint), bytes([12]) + amount.to_bytes(8, "little") + bytes([decimals]),
                     [AccountMeta(source, False, True), AccountMeta(mint, False, False), AccountMeta(dest, False, True), AccountMeta(owner.pubkey(), True, False)])
    assert c.send([ix], signers=[owner]), c.err


class OrderChain(Chain):
    def __init__(self, owner: Keypair | None = None, **kw):
        """`owner`: the key of the Balance's owner (default a new one), so a caller can lay the same orders at the same
        addresses again (scripts/load_pay.py: one seed, one run)."""
        super().__init__(**kw)
        self.usdc = self.new_mint(keypair=USDC_KEY)
        self.fee = self.token_account(pay.FEE_OWNER, self.usdc)
        self.tip = self.token_account(self.payer.pubkey(), self.usdc)          # the relayer's: tips arrive here
        self.owner, self.owner_tok = self.wallet(self.usdc, 1_000_000 * USDC, key=owner)
        assert self.send([pay.open_balance_ix(self.owner.pubkey(), OWNER, self.usdc, spenders=[MAINT])], self.owner), self.err
        self.bal = pay.balance_pda(OWNER, self.owner.pubkey(), self.usdc)
        transfer(self, self.owner_tok, pay.baltok_pda(self.bal), 100_000 * USDC, self.owner)
        self.funder, self.funder_tok = self.wallet(self.usdc, 1_000_000 * USDC)

    def order(self, address: Pubkey) -> pay.Order | None:
        return pay.read_order(self.data(address))

    def held(self, address: Pubkey) -> int:
        """What an order's own token account holds."""
        return self.balance(pay.ov_pda(address))

    def set_plan(self, owner_id: int, bps: int, expires: int, signer: Keypair = PLAN_SIGNER) -> bool:
        return self.send([pay.set_plan_ix(signer.pubkey(), self.payer.pubkey(), owner_id, bps, expires)], signers=[signer])

    # -- funding ---------------------------------------------------------------------------------------------------
    def fund_wallet_ix(self, n: int, amount: int = 20 * USDC, funder: Keypair | None = None, funder_tok: Pubkey | None = None, mint: Pubkey | None = None,
                       repo: int = REPO, terms: bytes = TERMS, **kw) -> Instruction:
        f, mint = funder or self.funder, mint or self.usdc
        return pay.fund_order_wallet_ix(f.pubkey(), funder_tok or self.funder_tok, mint, repo, n, amount, WF_REPO, WF_SHA, terms,
                                        token_program=self.token_program(mint), **kw)

    def fund_wallet(self, n: int | None = None, amount: int = 20 * USDC, funder: Keypair | None = None, **kw) -> Pubkey:
        """A wallet (default: the sponsor's) funds an order on issue n. Returns the order's address."""
        ix = self.fund_wallet_ix(n or issue(), amount, funder, **kw)
        assert self.send([ix], funder or self.funder, tag="fund_order_wallet"), self.err
        return ix.accounts[1].pubkey

    def fund_token(self, n: int, amount: int = 20 * USDC, mode: int = pay.MERGE, terms: bytes = TH, work: int = 14 * DAY, actor: int = MAINT,
                   balance: Pubkey | None = None, seq: int = 0, options: bytes | None = None, **over) -> Pubkey | None:
        """What fund.yml asks GitHub to sign when a maintainer funds an order on issue n from a Balance."""
        self.warp(1)
        aud = pay.order_fund_audience(n, amount, mode, terms, balance or self.bal, work, seq, options)
        return self.gh(aud, **{"file": "fund.yml", "event_name": "issue_comment", "actor_id": actor, "repository_id": REPO, "repository_owner_id": OWNER, **over})

    def fund_balance_ix(self, tok: Pubkey, n: int, balance: Pubkey | None = None, terms: bytes = TERMS, repo: int = REPO, seq: int = 0) -> Instruction:
        balance = balance or self.bal
        b = pay.read_balance(self.data(balance))
        return pay.fund_order_balance_ix(self.payer.pubkey(), tok, self.key, balance, b.mint, b.owner_id, repo, n, terms, self.data(tok), seq,
                                         self.token_program(b.mint))

    def fund_balance(self, n: int | None = None, amount: int = 20 * USDC, balance: Pubkey | None = None, terms: bytes = TERMS, seq: int = 0, **kw) -> Pubkey:
        """A comment funds an order on issue n from a Balance (default: the owner's). Returns the order's address."""
        n = n or issue()
        tok = self.fund_token(n, amount, terms=pay.terms_hash(terms), balance=balance, seq=seq, **kw)
        ix = self.fund_balance_ix(tok, n, balance, terms, seq=seq)
        assert self.send([ix], tag="fund_order_balance"), self.err
        return ix.accounts[7].pubkey

    # -- paying ----------------------------------------------------------------------------------------------------
    def pay_token(self, order: Pubkey, payees, o: pay.Order | None = None, pr: int = 7, **over) -> Pubkey | None:
        """What the order's pinned prove.yml asks GitHub to sign in the order's own repository (judge a). `payees`:
        (GitHub id, basis points, address or None) each; `o`: the order as it was, when it may be gone by now."""
        o = o or self.order(order)
        aud = dict(order=order, head_sha=HEAD, terms=o.terms, mode=o.mode, pr=pr, payees=payees)
        aud.update({k: over.pop(k) for k in list(over) if k in aud})
        return self.gh(pay.order_pay_audience(**aud), **{"repository_id": o.repo_id, **over})

    def wallets(self, payees) -> list:
        """(id, wallet) for each payee as the program will resolve it: the token's address, else the bound wallet."""
        return [(i, pay.order_destination(pay.read_bind(self.data(pay.bind_pda(i))), a)) for i, _, a in payees]

    def pay_ix(self, order: Pubkey, tok: Pubkey, payees, o: pay.Order | None = None, **kw) -> Instruction:
        o = o or self.order(order)
        return order_auto.with_quorum(pay.pay_order_ix(self.payer.pubkey(), tok, self.key, order, o, self.wallets(payees), **kw), order, o)

    # -- auto-accept, challenge, quorum ----------------------------------------------------------------------------
    def fund_auto(self, n: int | None = None, flags: int = 0, quorum: int = 0, work_s: int = 14 * DAY, auto: bool = True, **options) -> Pubkey:
        """A wallet funds an order paid by the black-box suite (mode 1) that is AUTO: the first passing pull request
        is paid unmerged. `flags`, `quorum` and `options` add to it; `auto` False: the same order without AUTO."""
        return self.fund_wallet(n, mode=pay.TESTS, terms=SUITE, work_s=work_s,
                                options=pay.opts((order_auto.F_AUTO if auto else 0) | flags | order_auto.quorum_flags(quorum), **options))

    def auto_token(self, order: Pubkey, payee: int, wallet: Pubkey | None, o: pay.Order | None = None, pr: int = 7, head: str = HEAD,
                   terms: bytes | None = None, **over) -> Pubkey | None:
        """What the order's pinned prove.yml asks GitHub to sign when the black-box suite passed on the head of an open
        pull request: no merge, no comment. The run is the pull request's check finishing (`workflow_run`)."""
        o = o or self.order(order)
        self.warp(1)
        aud = order_auto.auto_audience(order, head, o.terms if terms is None else terms, pr, payee, wallet)
        return self.gh(aud, **{"repository_id": o.repo_id, "event_name": "workflow_run", **over})

    def auto(self, order: Pubkey, payee: int, wallet: Pubkey | None, tag: str | None = "pay_order_auto", **over) -> bool:
        """The suite passed on a pull request by `payee`: the token arrives, with nobody's merge."""
        payees = [(payee, 10_000, wallet)]
        return self.send([self.pay_ix(order, self.auto_token(order, payee, wallet, **over), payees)], tag=tag)

    def neutral(self, who: int, repo: int = SELLER_REPO, **over) -> dict:
        """The claims of the pinned attest.yml started by hand by `who` in a repository `who` owns (judge b)."""
        return {"file": "attest.yml", "event_name": "workflow_dispatch", "actor_id": who, "repository_owner_id": who, "repository_id": repo, **over}

    def quorum(self, order: Pubkey) -> dict[int, tuple | None]:
        """The order's quorum markers as they stand: {kind: read_q(...) or None}."""
        return {k: order_auto.read_q(self.data(order_auto.q_pda(order, k))) for k in range(3)}

    def pay(self, order: Pubkey, payees, tag: str | None = "pay_order", **over) -> bool:
        """The proof arrives and the order is paid (or held)."""
        return self.send([self.pay_ix(order, self.pay_token(order, payees, **over), payees)], tag=tag)

    def refund(self, order: Pubkey, dest: Pubkey | None = None) -> bool:
        return self.send([pay.refund_order_ix(self.payer.pubkey(), order, self.order(order), dest)], tag="refund_order")

    def settle(self, order: Pubkey, wallet: Pubkey, **kw) -> bool:
        return self.send([pay.settle_order_ix(self.payer.pubkey(), order, self.order(order), wallet, **kw)], tag="settle_order")

    def bind(self, who: int, wallet: Pubkey) -> bool:
        """`who` binds a wallet with the pinned claim workflow, run by hand in their own knos-claim repository."""
        from _pay2 import TEST_CLAIM_SHA
        self.warp(1)
        tok = self.gh(pay.bind_audience(wallet), file="claim.yml", wf_repo="drexthealpha/knos-oidc-rotate", wf_sha=TEST_CLAIM_SHA,
                      event_name="workflow_dispatch", actor_id=who, repository_owner_id=who, repository=f"user{who}/knos-claim",
                      repository_id=70_000_000 + who % 1_000_000)
        return self.send([pay.bind_ix(self.payer.pubkey(), tok, self.key, who)])
