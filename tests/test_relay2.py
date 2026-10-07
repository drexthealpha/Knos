"""What carries GitHub-signed tokens to the second deployment: knos.settle.v2.relay (one token), knos.chain.Ledger
(the cluster) and knos.proof.ghrelay (the public worker), on LiteSVM and with fakes for GitHub and for the RPC.
LiteSVM (solders 0.29) takes v1 transactions, so the two-transaction path is run here as a cluster would run it.

A comment funds a bounty from the faucet or from a Balance, a proof pays it or holds it, a claim binds a wallet and
the held payment follows, an unproven bounty goes back, a key token reaches both deployments. Every refusal that can
be known from reads is given before a fee is spent. A token relayed twice, or by two relayers, is done once. The
transactions and the waits of each kind are counted and printed, beside the first deployment's."""
from __future__ import annotations

import base64
import json
import re
import threading
from pathlib import Path

import pytest

pytest.importorskip("solders.litesvm")

from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: E402
from solders.instruction import AccountMeta, Instruction  # noqa: E402
from solders.keypair import Keypair  # noqa: E402
from solders.pubkey import Pubkey  # noqa: E402

from _oidc2 import ROTATE_REF, TEST_ROTATE_SHA, Chain2  # noqa: E402
from _pay2 import GUARDIAN, TEST_CLAIM_SHA, WF_REPO, WF_SHA, github_claims  # noqa: E402
from _pay2 import Chain as _Chain  # noqa: E402
from _pay21 import BUILDS, Live, order_fee, pay21_build  # noqa: E402, F401 - the fixture `pay21`
from _settle import FIX, SeedKey, b64, modulus, sign_jwt, signing_key  # noqa: E402

from knos import chain  # noqa: E402
from knos.settle import oidc as oidc1  # noqa: E402
from knos.settle import pay as pay1  # noqa: E402
from knos.settle import relay as relay1  # noqa: E402
from knos.settle.v2 import oidc, pay, relay  # noqa: E402

ROOT = FIX.parents[1]
REPO, OWNER, MAINT = 987654321, 424242, 555000      # the harness's repository, its owner, a maintainer
USDC = 1_000_000
TERMS = pay.terms_json({"accept": "", "checks": [{"app": 15368, "name": "test"}], "deny": [".github/**", ".knos/**"], "mode": "merge",
                        "paths": [], "reserve": 7, "v": 1})
TH = pay.terms_hash(TERMS)
JWKS = {oidc.GITHUB: {"keys": [{"kty": "RSA", "alg": "RS256", "e": "AQAB", "kid": "k", "n": b64(oidc.modulus_bytes(modulus(signing_key())))}]}}
_COUNT = [1000, 3_000_000]
# The public program ids run knos_pay 2.1 until the upgrade to 2.2 executes, and the relay decides by the Version the
# cluster answers. So every test of this file runs twice: against the tree's build (2.2) and against the build that
# is live (2.1, the 0.3.17 release's). P(old, new) is what a test pins for each: `old` is the number 0.3.17 pinned.
LIVE = Live()
P = LIVE.pick


@pytest.fixture(scope="module", params=BUILDS, ids=Live.name, autouse=True)
def live(request, pay21):
    yield from LIVE.run(request.param, pay21)


def Chain(**kw) -> _Chain:
    """A cluster that runs the knos_pay build under test."""
    return _Chain(pay_build=LIVE.build, **kw)


def issue() -> int:
    _COUNT[0] += 1
    return _COUNT[0]


def user() -> int:
    """A GitHub id nobody has used yet (binds, records and faucet balances are per id, and the tests share a chain)."""
    _COUNT[1] += 1
    return _COUNT[1]


class _OneAtATime:
    """A LiteSVM that several threads may call: each call waits for the one before it."""

    def __init__(self, svm):
        self._svm, self.lock = svm, threading.RLock()

    def __getattr__(self, name):
        got = getattr(self._svm, name)
        if not callable(got):
            return got

        def call(*a, **kw):
            with self.lock:
                return got(*a, **kw)
        return call


class Net(chain.Ledger):
    """knos.chain.Ledger with LiteSVM for a cluster. A transaction is signed exactly as the real Ledger signs it
    (chain.sign), so it weighs what it would on devnet. Counts what a relay costs: transactions, waits (rounds of
    confirmation: `send` is one, `send_all` is one for the lot) and reads. It sends v1 transactions too (`takes_v1`)."""

    def __init__(self, c: Chain):
        super().__init__("litesvm")
        # LiteSVM runs v1 transactions but reads their compute limit from a compute budget instruction, not from the
        # message as a cluster does: wherever this ledger is used, v1 transactions carry both (knos.chain.V1_BUDGET_IX)
        chain.V1_BUDGET_IX = True
        self.c = c
        # a cluster takes transactions and reads from several of a relay's workers at once; one LiteSVM does not
        # (it refuses a second borrow), so the chain lets one caller in at a time, whoever holds it
        if not isinstance(c.svm, _OneAtATime):
            c.svm = _OneAtATime(c.svm)
        self.one_at_a_time = c.svm.lock
        self.txs = self.waits = self.reads = self.v1s = 0
        self.sizes: list[int] = []
        self.units: list[int] = []
        self.shape: list[int] = []                      # transactions per wait, in order
        self.said: dict[str, list[str]] = {}            # signature -> the transaction's log
        self.when: dict[str, int] = {}                  # signature -> the chain's time when it landed
        self.named: dict[Pubkey, list[str]] = {}        # address -> the signatures that named it, oldest first
        self.payers: dict[str, str] = {}                # signature -> its fee payer

    def _one(self, ixs, payer, signers, v1=False) -> str:
        with self.one_at_a_time:
            tx = chain.sign(ixs, payer, signers, self.c.svm.latest_blockhash(), v1)
            assert len(bytes(tx)) == chain.tx_size(ixs, payer.pubkey(), v1) and bytes(tx)[0] == (0x81 if v1 else len(tx.signatures))
            self.v1s += int(v1)
            r = self.c.svm.send_transaction(tx)
            self.c.svm.expire_blockhash()
            ok = "Failed" not in type(r).__name__
            meta = r if ok else r.meta()
            logs = list(meta.logs())
            if not ok:
                raise chain.RpcError(f"transaction failed: {r.err()}", {"logs": logs})
            sig = str(tx.signatures[0])
            used = meta.compute_units_consumed
            self.txs += 1
            self.sizes.append(len(bytes(tx)))
            self.units.append(used() if callable(used) else used)
            self.said[sig], self.when[sig] = logs, self.c.now()
            self.payers[sig] = str(payer.pubkey())
            for key in tx.message.account_keys:
                self.named.setdefault(key, []).append(sig)
            return sig

    def send(self, ixs, payer, signers=None, v1=False) -> str:
        sig = self._one(list(ixs), payer, signers, v1)
        self.waits += 1
        self.shape.append(1)
        return sig

    def send_all(self, groups, payer, signers=None, v1=False) -> list[str]:
        sent, refused = [], None
        for ixs in groups:
            try:
                sent.append(self._one(list(ixs), payer, signers, v1))
            except chain.RpcError as why:
                refused = refused or why
        self.waits += 1
        self.shape.append(len(sent))
        if refused is not None:
            raise refused
        return sent

    def simulate(self, ixs, payer, signers=None, v1=False) -> list[str]:
        with self.one_at_a_time:
            r = self.c.svm.simulate_transaction(chain.sign(ixs, payer, signers, self.c.svm.latest_blockhash(), v1))
            if "Failed" in type(r).__name__:
                raise chain.RpcError(f"transaction failed: {r.err()}", {"logs": list(r.meta().logs())})
            return list(r.meta().logs())

    def infos(self, addresses):
        with self.one_at_a_time:
            self.reads += 1
            out = []
            for a in addresses:
                acc = self.c.svm.get_account(a)
                out.append((acc.owner, bytes(acc.data)) if acc is not None and acc.lamports > 0 else None)
            return out

    def account(self, address):
        got = self.infos([address])[0]
        return got[1] if got else None

    def program_accounts(self, program, size=None, memcmp=None):
        with self.one_at_a_time:
            self.reads += 1
            out = []
            for addr, acc in self.c.svm.get_program_accounts(program):
                d = bytes(acc.data)
                if acc.lamports > 0 and (size is None or len(d) == size) and all(d[o:o + len(b)] == b for o, b in (memcmp or {}).items()):
                    out.append((addr, d))
            return out

    def recent(self, address, limit=20):
        self.reads += 1
        return [(sig, self.when[sig]) for sig in list(reversed(self.named.get(address, [])))[:limit]]

    def history(self, address, most=500):
        self.reads += 1
        yield from list(reversed(self.named.get(address, [])))[:most]

    def logs(self, signature):
        self.reads += 1
        return self.said.get(signature, [])

    def payer_of(self, signature):
        self.reads += 1
        return self.payers.get(signature)

    def touched(self, address):
        self.reads += 1
        return self.when[self.named[address][-1]] if self.named.get(address) else None

    def now(self) -> int:
        self.reads += 1
        return self.c.now()

    def spent(self):
        """(transactions, waits, reads) since the last call."""
        got = (self.txs, self.waits, self.reads)
        self.txs = self.waits = self.reads = self.v1s = 0
        self.shape.clear()
        return got


@pytest.fixture(scope="module")
def env(live):
    return _setup(Chain())


def seeded(*seed: int) -> Keypair:
    """A key that is the same in every run."""
    return Keypair.from_seed(bytes(seed).ljust(32, b""))


def _setup(c: Chain, fixed: bool = False) -> tuple[Chain, Net]:
    """The faucet, a test USDC mint and the owner's Balance holding 10,000 of it. fixed: the payer, the mint and the
    owner are keys that are the same in every run (by default each is new)."""
    if fixed:
        c.payer = seeded(1)
        c.svm.airdrop(c.payer.pubkey(), 100 * 10 ** 9)
    net = Net(c)
    assert c.send([pay.init_faucet_ix(c.payer.pubkey())]), c.err
    c.usdc = c.new_mint(keypair=seeded(2) if fixed else None)
    if fixed:
        c.owner = seeded(3)
        c.svm.airdrop(c.owner.pubkey(), 10 * 10 ** 9)
        c.owner_tok = c.token_account(c.owner.pubkey(), c.usdc)
        c.mint_to(c.usdc, c.owner_tok, 1_000_000 * USDC)
    else:
        c.owner, c.owner_tok = c.wallet(c.usdc, 1_000_000 * USDC)
    assert c.send([pay.open_balance_ix(c.owner.pubkey(), OWNER, c.usdc, spenders=[MAINT])], c.owner), c.err
    c.bal = pay.balance_pda(OWNER, c.owner.pubkey(), c.usdc)
    transfer(c, c.owner_tok, pay.baltok_pda(c.bal), 10_000 * USDC, c.owner)
    return c, net


def transfer(c: Chain, source: Pubkey, dest: Pubkey, amount: int, owner: Keypair, mint: Pubkey | None = None) -> None:
    """A plain TransferChecked, as any wallet would send it."""
    mint = mint or c.usdc
    ix = Instruction(c.token_program(mint), bytes([12]) + amount.to_bytes(8, "little") + bytes([6]),
                     [AccountMeta(source, False, True), AccountMeta(mint, False, False), AccountMeta(dest, False, True), AccountMeta(owner.pubkey(), True, False)])
    assert c.send([ix], signers=[owner]), c.err


@pytest.fixture(autouse=True)
def _test_pins(monkeypatch):
    """The test builds accept a test claim pin, a test rotate pin and the harness's repository as an attester."""
    monkeypatch.setattr(relay, "CLAIM_SHAS", relay.CLAIM_SHAS | {TEST_CLAIM_SHA})
    monkeypatch.setattr(relay, "ROTATE_SHAS", relay.ROTATE_SHAS | {TEST_ROTATE_SHA})
    monkeypatch.setattr(relay, "ATTESTERS", relay.ATTESTERS | {(OWNER, REPO)})


def token(c: Chain, aud: str, file: str = "prove.yml", wf_repo: str = WF_REPO, wf_sha: str = WF_SHA, key=None, **over) -> str:
    """What GitHub would sign for a run of <wf_repo>/.github/workflows/<file> at wf_sha, issued now."""
    now = c.now()
    c._n += 1
    claims = dict(aud=aud, iat=now, nbf=now - 600, exp=now + 300, jti=f"r{c._n}",
                  job_workflow_ref=f"{wf_repo}/.github/workflows/{file}@refs/tags/v0.3.12", job_workflow_sha=wf_sha)
    claims.update(over)
    return sign_jwt(key or signing_key(), github_claims(**claims))


def fund_jwt(c: Chain, n: int, amount: int = 5 * USDC, balance: Pubkey | None = None, terms: bytes = TERMS, work: int = 14 * 86_400,
             mode: int = pay.MERGE, **over) -> str:
    """The token of a maintainer's `/knos fund` on issue n (default: it spends the owner's Balance)."""
    c.warp(1)       # a Balance takes its fund tokens in the order GitHub issued them
    claims = {"file": "fund.yml", "event_name": "issue_comment", "actor_id": MAINT, **over}
    return token(c, pay.fund_audience(n, amount, mode, pay.terms_hash(terms), balance or c.bal, work), **claims)


def faucet_jwt(c: Chain, n: int, org: int, repo: int, amount: int = 5 * USDC, **over) -> str:
    """The same comment in a repository whose owner has no Balance: on devnet it spends the owner's faucet Balance."""
    return fund_jwt(c, n, amount, pay.faucet_balance_pda(org), repository_owner_id=org, repository_id=repo, **over)


def pay_jwt(c: Chain, repo: int, n: int, payee: int, address: Pubkey | None = None, terms: bytes = TERMS, mode: int = pay.MERGE, **over) -> str:
    """What the pinned prove.yml asks GitHub to sign once the merged pull request met the terms."""
    return token(c, pay.pay_audience(repo, n, payee, "a" * 40, pay.terms_hash(terms), mode, address), repository_id=repo, **over)


def bind_jwt(c: Chain, who: int, wallet: Pubkey, **over) -> str:
    """What the pinned claim workflow asks GitHub to sign when `who` runs it in their own repository named knos-claim."""
    c.warp(1)
    claims = dict(file="claim.yml", wf_repo="drexthealpha/knos-oidc-rotate", wf_sha=TEST_CLAIM_SHA, event_name="workflow_dispatch",
                  actor_id=who, repository_owner_id=who, repository=f"user{who}/knos-claim", repository_id=70_000_000 + who % 1_000_000)
    claims.update(over)
    return token(c, pay.bind_audience(wallet), **claims)


def go(env, jwt: str, terms: bytes | None = None, payer: Keypair | None = None) -> dict:
    c, net = env
    return relay.submit(net, payer or c.payer, jwt, terms, JWKS, now=c.now())




def funded(env, n: int | None = None, amount: int = 5 * USDC, **kw) -> tuple[int, Pubkey]:
    """A comment funds issue n from the owner's Balance, through the relay. Returns (issue, job)."""
    c, _net = env
    n = n or issue()
    r = go(env, fund_jwt(c, n, amount, **kw), kw.get("terms", TERMS))
    assert r["ok"], r
    return n, Pubkey.from_string(r["job"])


def lamports(c: Chain, who: Keypair | None = None) -> int:
    return c.lamports((who or c.payer).pubkey())


# -- every kind's happy path, and what it costs --------------------------------------------------------------------------
def test_a_comment_funds_from_the_faucet_a_proof_pays_and_a_claim_binds(env):
    c, net = env
    org, repo, n, payee, wallet = user(), user(), issue(), user(), Keypair().pubkey()
    jwt = faucet_jwt(c, n, org, repo)
    fbal = pay.faucet_balance_pda(org)
    job = pay.job_pda(repo, n, fbal)
    assert relay.precheck(net, c.payer, jwt, TERMS, JWKS, now=c.now()) is None       # nothing stands in its way
    r = go(env, jwt, TERMS)
    assert r == {"ok": True, "kind": "fund", "sigs": r["sigs"], "job": str(job), "repo_id": repo, "issue": n, "amount": 5 * USDC, "mode": 0,
                 "faucet": True, "balance": str(fbal), "deadline": c.now() + 14 * 86_400}, r
    j = pay.read_job(c.data(job))
    assert (j.state, j.faucet, j.amount, j.funder_id, j.terms) == ("open", True, 5 * USDC, MAINT, TH)
    # the terms are read back from the funding transaction's log
    assert net.terms_of(job) == TERMS and net.log_of(job, "knos2:terms ") == "knos2:terms " + TERMS.decode()
    assert net.log_of(job, "knos2:funded ").startswith(f"knos2:funded repo={repo} issue={n} amount=5000000 mode=0 by={MAINT} source={fbal} faucet=1")
    assert net.log_of(job, "knos2:paid") is None and net.log_of(Keypair().pubkey(), "knos2:terms ") is None
    # the proof names the address the author gave in the pull request: paid at once, less the fee
    r = go(env, pay_jwt(c, repo, n, payee, wallet))
    assert r == {"ok": True, "kind": "pay", "sigs": r["sigs"], "repo_id": repo, "issue": n, "payee_id": payee, "head": "a" * 40,
                 "paid": [{"job": str(job), "amount": 5 * USDC, "fee": P(125_000, 50_000), "mint": str(pay.faucet_mint()), "to": str(wallet), "held_until": None}]}, r
    assert c.balance(pay.ata(wallet, pay.faucet_mint())) == P(4_875_000, 4_950_000) and c.data(job) is None
    assert c.balance(pay.ata(pay.FEE_OWNER, pay.faucet_mint())) >= P(125_000, 50_000)         # the relay made the fee account too
    # the payee binds a wallet from their own knos-claim repository: nothing is held, so nothing else moves
    bound = Keypair().pubkey()
    r = go(env, bind_jwt(c, payee, bound))
    assert r == {"ok": True, "kind": "bind", "sigs": r["sigs"], "user_id": payee, "wallet": str(bound), "settled": []}, r
    assert pay.read_bind(c.data(pay.bind_pda(payee))).wallet == bound
    # every token account was closed behind its token: the relayer's rent came back
    assert net.program_accounts(oidc.OIDC_ID, None, {50: bytes(c.payer.pubkey())}) == []


def test_a_comment_spends_a_balance_of_real_money_in_either_token_program(env):
    c, net = env
    n, job = funded(env, amount=20 * USDC)
    j = pay.read_job(c.data(job))
    assert (j.faucet, j.from_balance, j.source, j.mint, j.owner_id, j.funder_id) == (False, True, c.bal, c.usdc, OWNER, MAINT)
    payee, wallet = user(), Keypair().pubkey()
    r = go(env, pay_jwt(c, REPO, n, payee, wallet))
    assert r["ok"] and r["paid"][0]["mint"] == str(c.usdc) and c.balance(pay.ata(wallet, c.usdc)) == P(19_500_000, 19_940_000), r
    # a Token-2022 mint with extensions the escrow's list allows: the relay passes the Balance's token program, and
    # makes the payee's and the fee owner's token accounts with it
    coin = c.new_mint22(confidential=True, close_authority=True)
    w, wtok = c.wallet(coin, 100 * USDC)
    org, repo, n = user(), user(), issue()
    assert c.send([pay.open_balance_ix(w.pubkey(), org, coin, token_program=pay.TOKEN_2022)], w), c.err
    bal = pay.balance_pda(org, w.pubkey(), coin)
    transfer(c, wtok, pay.baltok_pda(bal), 50 * USDC, w, coin)
    r = go(env, fund_jwt(c, n, 10 * USDC, bal, actor_id=org, repository_owner_id=org, repository_id=repo), TERMS)
    assert r["ok"] and not r["faucet"] and pay.read_job(c.data(Pubkey.from_string(r["job"]))).token_program == pay.TOKEN_2022, r
    assert relay.balances_for(net, org) == [(bal, pay.read_balance(c.data(bal)), 40 * USDC)]
    r = go(env, pay_jwt(c, repo, n, payee, wallet))
    assert r["ok"], r
    assert c.balance(pay.ata(wallet, coin, pay.TOKEN_2022)) == P(9_750_000, 9_950_000) and c.balance(pay.ata(pay.FEE_OWNER, coin, pay.TOKEN_2022)) == P(250_000, 50_000)


def test_a_balance_with_limits_is_funded_with_its_side_account_and_refused_before_any_fee(env):
    """2.1: a Balance whose wallet set limits (SetBalanceX) is spent only with its side account passed, and what that
    account would refuse is known from a read."""
    c, net = env
    org, repo = user(), user()
    w, wtok = c.wallet(c.usdc, 100 * USDC)
    assert c.send([pay.open_balance_ix(w.pubkey(), org, c.usdc)], w), c.err
    bal = pay.balance_pda(org, w.pubkey(), c.usdc)
    transfer(c, wtok, pay.baltok_pda(bal), 60 * USDC, w)
    assert c.send([pay.set_balance_x_ix(w.pubkey(), bal, day_limit=12 * USDC, repos=[repo])], w), c.err
    assert pay.read_balance(c.data(bal)).has_x
    mine = dict(actor_id=org, repository_owner_id=org)
    r = go(env, fund_jwt(c, issue(), 10 * USDC, bal, repository_id=repo, **mine), TERMS)
    assert r["ok"] and pay.read_balx(c.data(pay.balx_pda(bal))).day_spent == 10 * USDC, r
    assert refused(env, fund_jwt(c, issue(), 5 * USDC, bal, repository_id=repo, **mine), TERMS, "more than this balance may spend in one day or in total")
    assert refused(env, fund_jwt(c, issue(), 2 * USDC, bal, repository_id=user(), **mine), TERMS, "this one is not among them")
    assert go(env, fund_jwt(c, issue(), 2 * USDC, bal, repository_id=repo, **mine), TERMS)["ok"]
    c.warp(86_400)                                               # the next day the limit starts over
    assert go(env, fund_jwt(c, issue(), 12 * USDC, bal, repository_id=repo, **mine), TERMS)["ok"]


def test_with_no_wallet_the_payment_is_held_then_bound_then_settled(env):
    c, net = env
    n, job = funded(env, amount=8 * USDC)
    n2, job2 = funded(env, amount=4 * USDC)
    payee = user()
    r = go(env, pay_jwt(c, REPO, n, payee))                    # the author gave no address and has bound no wallet
    until = c.now() + pay.HOLD
    assert r["ok"] and r["paid"] == [{"job": str(job), "amount": 8 * USDC, "fee": P(200_000, 50_000), "mint": str(c.usdc), "to": None, "held_until": until}], r
    assert go(env, pay_jwt(c, REPO, n2, payee))["paid"][0]["held_until"] == c.now() + pay.HOLD
    assert [a for a, _j in relay.held_for(net, payee)] == sorted([job, job2], key=str) and relay.held_for(net, user()) == []
    assert [(a, j.state) for a, j in relay.jobs_for(net, REPO, n)] == [(job, "held")]
    # the claim binds the wallet and pays everything that was waiting, in the same relay
    wallet = Keypair().pubkey()
    r = go(env, bind_jwt(c, payee, wallet))
    assert r["ok"] and r["wallet"] == str(wallet) and {(s["job"], s["amount"], s["fee"]) for s in r["settled"]} == \
        {(str(job), 8 * USDC, P(200_000, 50_000)), (str(job2), 4 * USDC, P(100_000, 50_000))}, r
    assert c.balance(pay.ata(wallet, c.usdc)) == P(7_800_000, 7_950_000) + P(3_900_000, 3_950_000) and relay.held_for(net, payee) == []
    # from now on a proof for this payee pays the bound wallet, whatever address it carries
    n3, job3 = funded(env)
    r = go(env, pay_jwt(c, REPO, n3, payee, Keypair().pubkey()))
    assert r["ok"] and r["paid"][0]["to"] == str(wallet) and c.balance(pay.ata(wallet, c.usdc)) == P(7_800_000, 7_950_000) + P(3_900_000, 3_950_000) + P(4_875_000, 4_950_000), r


def test_one_proof_pays_one_job_and_the_next_run_pays_the_next(env):
    """2.1: a pay token pays, or holds, exactly one job (its marker is made with the payment). The relay sends the
    largest of the issue's open jobs that pin its workflow; a token of another run pays the next."""
    c, net = env
    n, own = funded(env, amount=5 * USDC)
    added = []
    for k in range(2):                                          # two sponsors' wallets add their own bounty to the issue
        w, wtok = c.wallet(c.usdc, 100 * USDC)
        assert c.send([pay.fund_wallet_ix(w.pubkey(), wtok, c.usdc, REPO, n, (20 + k) * USDC, WF_REPO, WF_SHA, TERMS)], w), c.err
        added.append(pay.job_pda(REPO, n, w.pubkey()))
    squatter, qtok = c.wallet(c.usdc, 5 * USDC)                 # and a stranger pins a workflow of their own
    assert c.send([pay.fund_wallet_ix(squatter.pubkey(), qtok, c.usdc, REPO, n, 5 * USDC, "evil/workflows", "f" * 40, TERMS)], squatter), c.err
    theirs = pay.job_pda(REPO, n, squatter.pubkey())
    assert {a for a, _j in relay.jobs_for(net, REPO, n)} == {own, theirs, *added}
    payee, wallet = user(), Keypair().pubkey()
    jwt = pay_jwt(c, REPO, n, payee, wallet)
    r = go(env, jwt)
    assert r["ok"] and [p["job"] for p in r["paid"]] == [str(added[1])] and r["paid"][0]["to"] == str(wallet), r
    assert c.balance(pay.ata(wallet, c.usdc)) == 21 * USDC - P(525_000, 63_000) and c.data(pay.used_pda(jwt)) is not None
    assert c.data(oidc.token_pda(c.payer.pubkey(), oidc.token_id(jwt))) is None
    # the same token again: what it did is on the payee's record, and it costs nothing; it does not pay a second job
    n0 = net.txs
    again = go(env, jwt, None, c.fund())
    assert again["ok"] and again["already"] and again["sigs"] == r["sigs"][-1:] and net.txs == n0, again
    assert {a for a, _j in relay.jobs_for(net, REPO, n)} == {own, theirs, added[0]}
    # a new run of the workflow gives a new token for each job that is left, largest first
    for job, total in ((added[0], 20), (own, 5)):
        r = go(env, pay_jwt(c, REPO, n, payee, wallet))
        assert r["ok"] and [p["job"] for p in r["paid"]] == [str(job)], r
    assert c.balance(pay.ata(wallet, c.usdc)) == 46 * USDC - P(525_000, 63_000) - P(500_000, 60_000) - P(125_000, 50_000)
    assert [(a, j.state) for a, j in relay.jobs_for(net, REPO, n)] == [(theirs, "open")]      # the stranger's job is not this proof's to pay
    c.warp(pay.TOKEN_AHEAD + 60)                                # (a token of the minutes just paid is taken for one of those payments)
    assert refused(env, pay_jwt(c, REPO, n, payee, wallet), None, "no open bounty on this issue pins this workflow at this commit")


def test_the_longest_terms_ride_with_the_last_step_in_a_v1_transaction_and_not_in_a_legacy_one(env, monkeypatch):
    c, net = env
    terms = b'{"paths":["' + b"x" * 580 + b'"],"v":1}'
    assert len(terms) == pay.MAX_TERMS
    org, repo, n = user(), user(), issue()
    jwt = faucet_jwt(c, n, org, repo, terms=terms)
    net.spent()
    net.sizes.clear()
    r = go(env, jwt, terms)
    assert r["ok"] and net.terms_of(Pubkey.from_string(r["job"])) == terms, r
    # two transactions, as for any token: the faucet's instruction, the funding with its 600 bytes and the Close all ride with the last Step
    assert net.shape == [1, 1] and chain.MAX_TX_BYTES < max(net.sizes) <= relay.ROOM_V1 < chain.MAX_V1_BYTES, (net.shape, net.sizes)
    # the legacy path (the 2.0 escrow, or a cluster that takes no v1 transaction): the faucet's instruction rides with
    # the last Step; the funding has a transaction to itself, and not even the Close fits beside it
    monkeypatch.setattr(net, "takes_v1", False)
    c.warp(60)
    n = issue()
    jwt = faucet_jwt(c, n, org, repo, terms=terms)
    net.spent()
    net.sizes.clear()
    assert go(env, jwt, terms)["ok"]
    assert net.shape == [2, 1, 1, 1, 1] and max(net.sizes) <= relay.ROOM < chain.MAX_TX_BYTES, (net.shape, net.sizes)
    assert net.sizes[4] == chain.tx_size([pay.fund_balance_ix(c.payer.pubkey(), oidc.token_pda(c.payer.pubkey(), oidc.token_id(jwt)), c.key,
                                                              pay.faucet_balance_pda(org), pay.faucet_mint(), repo, n, terms, used=jwt)], c.payer.pubkey()) == 1208


# -- which escrow the cluster runs -----------------------------------------------------------------------------------------
class Old:
    """A ledger whose cluster runs the deployed 2.0 escrow: it refuses instruction 12, as that program does, and
    simulates everything else as the cluster would (knos_meter and knos_passkey are programs of their own). With
    `why`, a cluster that does not answer at all."""

    def __init__(self, net: Net, why: Exception | None = None):
        self.net, self.url, self.asked, self.down = net, "a cluster of 2.0", 0, why is not None
        self.why = why or chain.RpcError("transaction failed: TransactionErrorInstructionError((1, Fieldless(InvalidInstructionData)))")

    def __getattr__(self, name):
        return getattr(self.net, name)

    def simulate(self, ixs, payer, signers=None, v1=False):
        self.asked += 1
        if self.down or pay.version_ix() in list(ixs):
            raise self.why
        return self.net.simulate(ixs, payer, signers, v1)


def test_the_version_is_asked_by_simulation_once_and_what_is_new_is_used_only_on_2_1(env, monkeypatch):
    c, net = env
    monkeypatch.setattr(relay, "_VERSION", {})
    lamports0, n0 = lamports(c), net.txs
    # the build that is live logs `knos2:version 1`; the tree's, once it is, `knos2:version 2`
    assert relay.version(net, c.payer) == P(1, 2) and relay._VERSION == {("litesvm", pay.PAY_ID): P(1, 2)}
    assert (lamports(c), net.txs) == (lamports0, n0)                                                # and asking cost nothing
    # kept until a pass begins: `forget` drops this cluster's answer (or every one), and the next call asks again
    relay._VERSION[("another cluster", pay.PAY_ID)] = 0
    relay.forget(net)
    assert relay._VERSION == {("another cluster", pay.PAY_ID): 0}
    relay.forget()
    assert relay._VERSION == {} and relay.version(net, c.payer) == P(1, 2) == relay.version(net, c.payer)
    old = Old(net)
    assert relay.version(old, c.payer) == relay.version(old, c.payer) == 0 and old.asked == 1      # the program's refusal is an answer, and it is kept
    down = Old(net, OSError("connection reset"))
    down.url = "a cluster that does not answer"
    assert relay.version(down, c.payer) == 0 and down.url not in {k[0] for k in relay._VERSION}   # no answer is not kept: the next token asks again
    assert relay.version(object(), c.payer) == 0                                                   # nor is a ledger that cannot simulate
    # on 2.0 a proof pays every open job of its issue with no marker, a funding names no side account, and a key
    # token's attestation goes without the key that verified it: the instructions the deployed program takes
    n, own = funded(env, amount=5 * USDC)
    w, wtok = c.wallet(c.usdc, 100 * USDC)
    assert c.send([pay.fund_wallet_ix(w.pubkey(), wtok, c.usdc, REPO, n, 20 * USDC, WF_REPO, WF_SHA, TERMS)], w), c.err
    proof = pay_jwt(c, REPO, n, user(), Keypair().pubkey())
    plan = relay._plan(old, c.payer, proof, None, JWKS, c.now())
    pays = [ix for ixs, _cu in plan.groups for ix in ixs if ix.program_id == pay.PAY_ID]
    assert [len(ix.accounts) for ix in pays] == [15, 15]
    now_ = relay._plan(net, c.payer, proof, None, JWKS, c.now())
    pays = [ix for ixs, _cu in now_.groups for ix in ixs if ix.program_id == pay.PAY_ID]
    assert [len(ix.accounts) for ix in pays] == [16] and pays[0].accounts[-1].pubkey == pay.used_pda(proof)
    new = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwks = {oidc.GITHUB: {"keys": [*JWKS[oidc.GITHUB]["keys"], _jwk("v", modulus(new))]}}
    att = attestation(c, oidc.GITHUB, modulus(new))
    for ledger, accounts in ((old, 4), (net, 5)):
        register = relay._plan(ledger, c.payer, att, None, jwks, c.now()).groups[0][0][0]
        assert len(register.accounts) == accounts and (accounts == 4 or register.accounts[-1].pubkey == c.key)


# -- refused before any fee ----------------------------------------------------------------------------------------------
def _capped(c: Chain) -> Pubkey:
    """A second wallet's Balance for the same owner: 30 test USDC in it, at most 10 for one bounty."""
    if not hasattr(c, "capped"):
        w, wtok = c.wallet(c.usdc, 30 * USDC)
        assert c.send([pay.open_balance_ix(w.pubkey(), OWNER, c.usdc, cap=10 * USDC, spenders=[MAINT])], w), c.err
        c.capped = pay.balance_pda(OWNER, w.pubkey(), c.usdc)
        transfer(c, wtok, pay.baltok_pda(c.capped), 30 * USDC, w)
    return c.capped


def _raw_fund(c: Chain, aud: str) -> str:
    c.warp(1)
    return token(c, aud, file="fund.yml", event_name="issue_comment", actor_id=MAINT)


def _gitlab(c: Chain, n: int) -> str:
    """A token GitLab's key signed, saying everything a fund token says."""
    return token(c, pay.fund_audience(n, 5 * USDC, 0, TH, c.bal), key=signing_key(4096), iss=oidc.ISSUERS[oidc.GITLAB],
                 file="fund.yml", event_name="issue_comment", actor_id=MAINT)


def _forged(c: Chain, n: int) -> str:
    """Everything a fund token says, signed by a key that is not GitHub's but calls itself by GitHub's key id."""
    c.warp(1)
    return token(c, pay.fund_audience(n, 5 * USDC, 0, TH, c.bal), key=_STRANGER, file="fund.yml", event_name="issue_comment", actor_id=MAINT)


_STRANGER = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_OTHER = pay.terms_json({"checks": [], "v": 1})
# what is wrong -> (the token for issue n, the terms that come with it, what the relay says)
FUND_REFUSALS = {
    "a token from prove.yml": (lambda c, n: fund_jwt(c, n, file="prove.yml"), TERMS, "a fund token must come from fund.yml"),
    "a pull request event": (lambda c, n: fund_jwt(c, n, event_name="pull_request_target"), TERMS, "funded by a comment on an issue or by a new issue"),
    "a re-run of the commenter's run": (lambda c, n: fund_jwt(c, n, run_attempt=2), TERMS, "only a run's first attempt can fund"),
    "a self-hosted runner": (lambda c, n: fund_jwt(c, n, runner_environment="self-hosted"), TERMS, "not from a GitHub-hosted runner"),
    "terms that are not the ones GitHub signed for": (lambda c, n: fund_jwt(c, n), _OTHER, "not the terms GitHub signed for"),
    "no terms": (lambda c, n: fund_jwt(c, n), None, "the bounty's terms did not come with its token"),
    "less than the smallest bounty": (lambda c, n: fund_jwt(c, n, pay.MIN_AMOUNT - 1), TERMS, "a bounty is from 1.00 to 100,000.00; this token asks for 1.00"),
    "more than the largest bounty": (lambda c, n: fund_jwt(c, n, pay.MAX_AMOUNT + 1), TERMS, "a bounty is from 1.00 to 100,000.00"),
    "more than 90 days to do the work": (lambda c, n: fund_jwt(c, n, work=pay.MAX_WORK + 1), TERMS, "a bounty is open for a minute to 90 days"),
    "a balance that does not exist": (lambda c, n: fund_jwt(c, n, balance=pay.balance_pda(OWNER, Keypair().pubkey(), c.usdc)), TERMS, "does not exist"),
    "a comment in another owner's repository": (lambda c, n: fund_jwt(c, n, repository_owner_id=999_999, repository_id=555_555), TERMS, "another GitHub owner's repositories"),
    "a commenter the balance does not list": (lambda c, n: fund_jwt(c, n, actor_id=1234567), TERMS, "this commenter may not spend that balance"),
    "more than the balance allows for one bounty": (lambda c, n: fund_jwt(c, n, 11 * USDC, _capped(c)), TERMS, "that balance allows 10.00 for one bounty; this token asks for 11.00"),
    "more than the balance holds": (lambda c, n: fund_jwt(c, n, 10 * USDC, _capped(c)), TERMS, "the balance holds 0.00, less than this bounty; add money to it or fund less"),
    "more than the faucet gives": (lambda c, n: faucet_jwt(c, n, user(), user(), pay.FAUCET_CAP + 1), TERMS, "the faucet gives at most 100.00 test USDC for one bounty"),
    "an audience with a part missing": (lambda c, n: _raw_fund(c, f"knos2:fund:{n}:5000000:0:{TH.hex()}:1209600"), TERMS, "malformed audience or claims"),
    "a balance address that is not the way Solana prints it": (lambda c, n: _raw_fund(c, f"knos2:fund:{n}:5000000:0:{TH.hex()}:1209600:1{c.bal}"), TERMS, "malformed audience or claims"),
    "a mode that is neither merge nor tests": (lambda c, n: fund_jwt(c, n, mode=2), TERMS, "malformed audience or claims"),
    "a token dated ahead of the chain": (lambda c, n: fund_jwt(c, n, iat=c.now() + 302, exp=c.now() + 602), TERMS, "the token's times are not GitHub's"),
    "a token that claims to live for hours": (lambda c, n: fund_jwt(c, n, exp=c.now() + 3602), TERMS, "the token's times are not GitHub's"),
    "an expired token": (lambda c, n: fund_jwt(c, n, iat=c.now() - 4000, exp=c.now() - 3700), TERMS, "token expired"),
    "a GitLab token": (_gitlab, TERMS, "the escrow takes GitHub's tokens only"),
    "a signature that is not GitHub's": (_forged, TERMS, "the signature is not the issuer's"),
    "a key id GitHub does not publish": (lambda c, n: sign_jwt(signing_key(), github_claims(aud=pay.fund_audience(n, 5 * USDC, 0, TH, c.bal)), header={"alg": "RS256", "kid": "gone"}),
                                         TERMS, "the issuer's key set has no key 'gone'"),
    "an audience that is not Knos's": (lambda c, n: token(c, "sts.amazonaws.com"), TERMS, "not an audience of the second deployment: 'sts.amazonaws.com'"),
    "a first-deployment audience": (lambda c, n: token(c, f"knos:fund:{n}:5000000:0:{TH.hex()}:1209600:0"), TERMS, "not an audience of the second deployment"),
    "something that is not a token": (lambda c, n: "not.a.jwt", TERMS, "this is not a token GitHub Actions or GitLab CI issued"),
}
ALL_JWKS = {**JWKS, oidc.GITLAB: {"keys": [{"kty": "RSA", "alg": "RS256", "e": "AQAB", "kid": "k", "n": b64(oidc.modulus_bytes(modulus(signing_key(4096))))}]}}


class Unfunded:
    """A cluster that cannot simulate for this caller: its fee payer is not on chain (`refusal`, as the cluster says
    it), and knos-pay is deployed through the upgradeable loader with `code` as its executable (None: the accounts
    cannot be read)."""

    def __init__(self, url: str, code: bytes | None, refusal: str = "transaction failed: AccountNotFound"):
        self.url, self.code, self.refusal, self.pd, self.asked, self.read = url, code, refusal, Keypair().pubkey(), 0, 0

    def simulate(self, ixs, payer, signers=None, v1=False):
        self.asked += 1
        raise chain.RpcError(self.refusal, {"err": self.refusal.rpartition(": ")[2], "logs": []})

    def infos(self, addresses):
        self.read += 1
        if self.code is None:
            raise OSError("the cluster did not answer")
        return [(relay._UPGRADEABLE, (2).to_bytes(4, "little") + bytes(self.pd)) if a == pay.PAY_ID else
                (relay._UPGRADEABLE, bytes(45) + self.code) if a == self.pd else None for a in addresses]


def test_with_no_funded_payer_the_version_is_read_from_the_executable_and_costs_nothing(env, monkeypatch, pay21):
    """A seller with no relay key (`knos settle --neutral`), or a repository with no secret, has no fee payer on chain,
    and a cluster refuses to simulate for one it has never seen (AccountNotFound): nothing was asked. The deployed
    executable answers instead, read with no payer at all: a 2.1 build holds Version's log line, a 2.0 build does not."""
    c, net = env
    monkeypatch.setattr(relay, "_VERSION", {})
    nobody = Keypair()                                                          # never on chain: no account, no SOL
    with pytest.raises(chain.RpcError, match="AccountNotFound"):
        net.simulate([pay.version_ix()], nobody)
    lamports0, n0 = lamports(c), net.txs
    assert relay.version(net, nobody) == P(1, 2) and relay._VERSION == {("litesvm", pay.PAY_ID): P(1, 2)}      # the build that runs, as loaded
    assert (lamports(c), net.txs) == (lamports0, n0)                                                # read, never sent
    built = (FIX / LIVE.build).read_bytes()
    assert relay._VERSION_LINE in built
    # through the upgradeable loader, as devnet deploys it: the program account names the ProgramData that holds the code
    new = Unfunded("a cluster of the build under test", built)
    assert relay.version(new) == relay.version(new) == P(1, 2) and (new.asked, new.read) == (1, 2)       # an answer, kept: asked once
    for refusal in ("Transaction simulation failed: Attempt to debit an account but found no record of a prior credit.",
                    "transaction failed: InsufficientFundsForFee"):
        assert relay.version(Unfunded(f"this build, {refusal[-20:]}", built, refusal)) == P(1, 2)   # the other words for a payer with nothing
    # which of the two it is, is read from the fee rule in the code (the number Version logs is not in the bytes as
    # text): 2.1 holds the tiered fee's upper edge, 2.2 has one rate and no such number. Both builds, whichever is live
    old21, new22 = Path(pay21).read_bytes(), (FIX / "knos_pay_v2_test.so").read_bytes()
    assert relay._TIERED.search(old21) and not relay._TIERED.search(new22) and not relay._TIERED.search((FIX / "knos_pay_v2_nodevnet.so").read_bytes())
    assert (relay.version(Unfunded("2.1 by its bytes", old21)), relay.version(Unfunded("2.2 by its bytes", new22))) == (1, 2)
    assert relay.version(Unfunded("2.2 with no faucet", (FIX / "knos_pay_v2_nodevnet.so").read_bytes())) == 2
    old = Unfunded("a 2.0 cluster", b"\x7fELF" + bytes(4096))
    assert relay.version(old) == relay.version(old) == 0 and old.asked == 1                        # 2.0 has no Version line: an answer, kept
    down = Unfunded("a cluster that does not answer", None)
    assert relay.version(down) == 0 and down.url not in {k[0] for k in relay._VERSION}             # not read is no answer: asked again next time
    # the program's own refusal of instruction 12 is the answer, as before: nothing is read for it
    refusing = Unfunded("2.0, refusing", built, "transaction failed: TransactionErrorInstructionError((1, Fieldless(InvalidInstructionData)))")
    assert relay.version(refusing) == 0 and (refusing.asked, refusing.read) == (1, 0)
    # and with a funded payer the simulation itself answers, with nothing read
    monkeypatch.setattr(relay, "_VERSION", {})
    reads0 = net.reads
    assert relay.version(net, c.payer) == P(1, 2) and net.reads == reads0


def refused(env, jwt: str, terms: bytes | None, want: str | None, payer: Keypair | None = None) -> dict:
    """The relay's answer to a token the chain would refuse: the same from `precheck` and from `submit`, with no
    transaction and not a lamport spent."""
    c, net = env
    before, n0 = lamports(c, payer), net.txs
    r = relay.submit(net, payer or c.payer, jwt, terms, ALL_JWKS, now=c.now())
    assert not r["ok"] and (want is None or want in r["why"]), r
    assert (lamports(c, payer), net.txs) == (before, n0), f"a fee was spent on: {r['why']}"
    assert relay.precheck(net, payer or c.payer, jwt, terms, ALL_JWKS, now=c.now()) == r
    return r


@pytest.mark.parametrize("what", list(FUND_REFUSALS))
def test_a_fund_token_costs_nothing_with(env, what):
    c, _net = env
    make, terms, want = FUND_REFUSALS[what]
    n = issue()
    if what == "more than the balance holds":
        for _ in range(3):                  # the Balance holds 30; three bounties of 10 empty it
            assert go(env, fund_jwt(c, issue(), 10 * USDC, _capped(c)), TERMS)["ok"]
    r = refused(env, make(c, n), terms, want)
    assert r["kind"] == (None if what in ("an audience that is not Knos's", "a first-deployment audience", "something that is not a token") else "fund")
    assert c.data(pay.job_pda(REPO, n, c.bal)) is None


def test_a_fund_token_is_refused_by_what_the_chain_already_holds(env):
    c, net = env
    # an older comment's token, after a newer one was carried: the Balance takes its tokens in the order GitHub issued them
    n_old, n = issue(), issue()
    old = fund_jwt(c, n_old)
    new = fund_jwt(c, n)
    assert go(env, new, TERMS)["ok"]
    assert refused(env, old, TERMS, "an older fund token than the last one this balance took; comment again") == \
        {"ok": False, "kind": "fund", "why": "an older fund token than the last one this balance took; comment again"}
    # another comment on an issue that already has this Balance's bounty
    job = pay.job_pda(REPO, n, c.bal)
    assert refused(env, fund_jwt(c, n, 6 * USDC), TERMS, f"this issue already has a bounty from this balance (job {job})")
    # the faucet serves a repository once a minute, in the order of the tokens: the next comment waits, and is told how long
    org, repo = user(), user()
    assert go(env, faucet_jwt(c, issue(), org, repo), TERMS)["ok"]
    late = faucet_jwt(c, issue(), org, repo)
    c.warp(9)
    r = refused(env, late, TERMS, "the faucet serves a repository once a minute")
    assert r == {"ok": False, "kind": "fund", "why": "the faucet serves a repository once a minute", "retry": True, "wait": 50}
    c.warp(50)
    assert go(env, late, TERMS)["ok"]
    # the faucet opened for a token whose funding then never landed: a token GitHub issued before that one is too old for it
    org2, repo2 = user(), user()
    early = faucet_jwt(c, issue(), org2, repo2, 6 * USDC)
    c.warp(1)
    tok = c.gh(pay.fund_audience(issue(), 5 * USDC, 0, TH, pay.faucet_balance_pda(org2)), file="fund.yml", event_name="issue_comment", actor_id=MAINT,
               repository_owner_id=org2, repository_id=repo2)
    assert c.send([pay.faucet_open_ix(c.payer.pubkey(), tok, c.key, org2, repo2)]), c.err
    assert refused(env, early, TERMS, "an older fund token than the repository's last one; comment again")
    # test USDC that came back to the faucet Balance (an unproven bounty) is spent without asking the faucet again
    n_back = issue()
    c.warp(60)
    assert go(env, faucet_jwt(c, n_back, org, repo, work=60), TERMS)["ok"]
    c.warp(61)
    assert len(relay.refund_due(net, c.payer, c.now())) == 1 and c.balance(pay.baltok_pda(pay.faucet_balance_pda(org))) == 5 * USDC
    rate = c.data(pay.rate_pda(repo))
    assert go(env, faucet_jwt(c, issue(), org, repo), TERMS)["ok"]             # inside the faucet's minute: it was not needed
    assert c.data(pay.rate_pda(repo)) == rate and c.balance(pay.baltok_pda(pay.faucet_balance_pda(org))) == 0


def _job(env, **kw) -> tuple[int, Pubkey]:
    return funded(env, **kw)


# what is wrong -> (the pay token for the job on issue n, what the relay says)
PAY_REFUSALS = {
    "a fund.yml token": (lambda c, n: pay_jwt(c, REPO, n, 77, file="fund.yml"), "not from the workflow or the repository the audience names"),
    "a run in another repository": (lambda c, n: token(c, pay.pay_audience(REPO, n, 77, "a" * 40, TH, 0), repository_id=111), "not from the workflow or the repository the audience names"),
    "an issue with no bounty": (lambda c, n: pay_jwt(c, REPO, n + 100_000, 77), "no bounty is in escrow for this issue (never funded, or already paid or refunded)"),
    "prove.yml of another repository": (lambda c, n: pay_jwt(c, REPO, n, 77, wf_repo="evil/Knos"), "no open bounty on this issue pins this workflow at this commit"),
    "prove.yml at another commit": (lambda c, n: pay_jwt(c, REPO, n, 77, wf_sha="d" * 40), "no open bounty on this issue pins this workflow at this commit"),
    "other terms": (lambda c, n: pay_jwt(c, REPO, n, 77, terms=_OTHER), "the open bounty on this issue has other terms than the ones this token was made for"),
    "the other mode": (lambda c, n: pay_jwt(c, REPO, n, 77, mode=pay.TESTS), "the open bounty on this issue has other terms"),
    "a proof made before the funding": (lambda c, n: pay_jwt(c, REPO, n, 77, iat=c.now() - 1800, exp=c.now() - 1500), "this token is older than the bounty"),
    "payee 0": (lambda c, n: pay_jwt(c, REPO, n, 0), "malformed audience or claims"),
    "a head that is not a commit": (lambda c, n: token(c, pay.pay_audience(REPO, n, 77, "main", TH, 0)), "malformed audience or claims"),
    "an address that is not a key": (lambda c, n: token(c, pay.pay_audience(REPO, n, 77, "a" * 40, TH, 0)[:-1] + "0OIl"), "malformed audience or claims"),
    "the escrow's own account as the address": (lambda c, n: pay_jwt(c, REPO, n, 77, pay.auth_pda()), "the address this token names is the escrow's own account"),
    "a self-hosted runner": (lambda c, n: pay_jwt(c, REPO, n, 77, runner_environment="self-hosted"), "not from a GitHub-hosted runner"),
}


@pytest.mark.parametrize("what", list(PAY_REFUSALS))
def test_a_proof_costs_nothing_with(env, what):
    c, _net = env
    make, want = PAY_REFUSALS[what]
    n, job = _job(env)
    before = c.data(job)
    assert refused(env, make(c, n), None, want)["kind"] == "pay"
    assert c.data(job) == before


def test_a_proof_is_refused_by_what_the_chain_already_holds(env):
    c, net = env
    n, job = _job(env, work=60)
    late = pay_jwt(c, REPO, n, 77, Keypair().pubkey())
    c.warp(61)
    assert refused(env, late, None, "the bounty's deadline has passed: it goes back to its funder")
    # held for one user: a proof for another finds nothing to take
    n, job = _job(env)
    first = user()
    assert go(env, pay_jwt(c, REPO, n, first))["paid"][0]["to"] is None
    assert refused(env, pay_jwt(c, REPO, n, user(), Keypair().pubkey()), None, "the bounty on this issue is already held for another GitHub user")


# what is wrong -> (the bind token for user `who`, what the relay says)
BIND_REFUSALS = {
    "another workflow file of the pinned repository": (lambda c, who: bind_jwt(c, who, Keypair().pubkey(), file="rotate.yml"), "a wallet is bound only by Knos's claim workflow at its pinned commit"),
    "a claim.yml of another repository": (lambda c, who: bind_jwt(c, who, Keypair().pubkey(), wf_repo="evil/knos-oidc-rotate"), "a wallet is bound only by Knos's claim workflow"),
    "another commit of the claim workflow": (lambda c, who: bind_jwt(c, who, Keypair().pubkey(), wf_sha="3" * 40), "a wallet is bound only by Knos's claim workflow"),
    "a repository with another name": (lambda c, who: bind_jwt(c, who, Keypair().pubkey(), repository=f"user{who}/dotfiles"), "the claim must run in a repository named knos-claim that the claiming account owns"),
    "an actor who does not own the repository": (lambda c, who: bind_jwt(c, who, Keypair().pubkey(), repository_owner_id=who + 1), "the claim must run in a repository named knos-claim"),
    "a comment": (lambda c, who: bind_jwt(c, who, Keypair().pubkey(), event_name="issue_comment"), "the claim must be started by hand by the account's owner"),
    "the push that made the repository (its first run)": (lambda c, who: bind_jwt(c, who, Keypair().pubkey(), event_name="push", run_number=1), "the claim must be started by hand by the account's owner"),
    "the real pin's first push": (lambda c, who: bind_jwt(c, who, Keypair().pubkey(), wf_sha=pay.IDS["claim_sha"], event_name="push", run_number=1), "the claim must be started by hand by the account's owner"),
    "a later push": (lambda c, who: bind_jwt(c, who, Keypair().pubkey(), event_name="push", run_number=2), "the claim must be started by hand by the account's owner"),
    "a re-run": (lambda c, who: bind_jwt(c, who, Keypair().pubkey(), run_attempt=2), "and not be a re-run"),
    "an address that is not a key": (lambda c, who: token(c, "knos2:bind:" + "1" * 31, file="claim.yml", wf_repo="drexthealpha/knos-oidc-rotate", wf_sha=TEST_CLAIM_SHA), "malformed audience or claims"),
    "a self-hosted runner": (lambda c, who: bind_jwt(c, who, Keypair().pubkey(), runner_environment="self-hosted"), "not from a GitHub-hosted runner"),
}


@pytest.mark.parametrize("what", list(BIND_REFUSALS))
def test_a_claim_costs_nothing_with(env, what):
    c, _net = env
    make, want = BIND_REFUSALS[what]
    who = user()
    assert refused(env, make(c, who), None, want)["kind"] == "bind"
    assert c.data(pay.bind_pda(who)) is None


def test_an_older_claim_does_not_undo_a_newer_one_and_the_real_pin_binds(env):
    c, _net = env
    who, wallet = user(), Keypair().pubkey()
    old = bind_jwt(c, who, Keypair().pubkey())
    assert go(env, bind_jwt(c, who, wallet))["ok"]
    assert refused(env, old, None, "a newer claim has bound a wallet since this one; run the claim again to change it")
    assert go(env, bind_jwt(c, who, wallet, wf_sha=pay.IDS["claim_sha"]))["ok"]      # the real pin, started by hand


def test_a_token_whose_signing_key_the_chain_would_refuse_costs_nothing():
    """On a chain of its own: a revocation is for ever."""
    c = Chain()
    env = (c, Net(c))
    assert c.send([pay.init_faucet_ix(c.payer.pubkey())]), c.err
    org, repo = user(), user()
    # a key GitHub publishes, and that signed this token, which the chain has not been given: not GitHub's genesis keys, so not the relay's to register
    both = {oidc.GITHUB: {"keys": [*JWKS[oidc.GITHUB]["keys"], {"kty": "RSA", "alg": "RS256", "e": "AQAB", "kid": "new", "n": b64(oidc.modulus_bytes(modulus(_STRANGER)))}]}}
    jwt = sign_jwt(_STRANGER, github_claims(aud=pay.fund_audience(1, 5 * USDC, 0, TH, pay.faucet_balance_pda(org)), iat=c.now(), exp=c.now() + 300, actor_id=MAINT,
                                            event_name="issue_comment", repository_owner_id=org, repository_id=repo,
                                            job_workflow_ref=f"{WF_REPO}/.github/workflows/fund.yml@refs/tags/v0.3.12"), header={"alg": "RS256", "kid": "new"})
    n0 = env[1].txs
    r = relay.submit(env[1], c.payer, jwt, TERMS, both, now=c.now())
    assert r == {"ok": False, "kind": "fund", "why": "the token cannot be verified: this signing key is not on chain yet. Send RegisterKey with an "
                                                     "attestation from the rotate workflow."} and env[1].txs == n0
    good = faucet_jwt(c, 2, org, repo)
    assert c.revoke(oidc.GITHUB, c.github), c.err
    r = refused(env, good, TERMS, "the token cannot be verified: the guardian revoked this signing key. It cannot be used again.")
    assert "retry" not in r


def test_a_token_under_a_key_that_has_expired_costs_nothing():
    """On a chain of its own: the clock moves a month, and no rotate workflow refreshed GitHub's key."""
    c = Chain()
    env = (c, Net(c))
    assert c.send([pay.init_faucet_ix(c.payer.pubkey())]), c.err
    c.warp(oidc.KEY_TTL - 1)                                    # the key was registered when the chain began; the token is issued a second later
    r = refused(env, faucet_jwt(c, 1, user(), user()), TERMS, "the token cannot be verified: this signing key expired")
    assert "Run the rotate workflow and send Refresh with its token." in r["why"] and "retry" not in r


def test_while_new_funding_is_paused_a_fund_token_waits_and_payments_go_on():
    """On a chain of its own: the guardian's pause stops every new bounty there."""
    c = Chain()
    net = Net(c)
    env = (c, net)
    assert c.send([pay.init_faucet_ix(c.payer.pubkey())]), c.err
    org, repo, n, payee, wallet = user(), user(), issue(), user(), Keypair().pubkey()
    assert go(env, faucet_jwt(c, n, org, repo), TERMS)["ok"]
    pause = lambda seconds: c.send([pay.pause_ix(GUARDIAN.pubkey(), c.payer.pubkey(), seconds)], signers=[GUARDIAN]) or pytest.fail(c.err)  # noqa: E731
    pause(600)
    until = c.now() + 600
    c.warp(60)
    jwt = faucet_jwt(c, issue(), org, repo)
    # the pause ends while this token still works: the relay says how long to wait, and spends nothing meanwhile
    assert refused(env, jwt, TERMS, None) == {"ok": False, "kind": "fund", "retry": True, "wait": until - c.now(),
                                              "why": f"new funding is paused until {relay._when(until)}; payments and refunds go on"}
    assert go(env, pay_jwt(c, repo, n, payee, wallet))["ok"] and c.balance(pay.ata(wallet, pay.faucet_mint())) == P(4_875_000, 4_950_000)
    pause(pay.PAUSE_MAX)                                         # a pause that outlasts the token: refused, and not to be tried again
    assert "retry" not in refused(env, jwt, TERMS, "new funding is paused until")
    pause(0)
    assert go(env, jwt, TERMS)["ok"]


def test_a_jobs_terms_are_the_ones_its_hash_names_whatever_else_was_logged_at_its_address(env):
    """knos-pay keeps the hash of a job's terms and logs the JSON when the job is funded. The log is read back by the
    job's address, which is used again when a bounty went back and the issue is funded anew, and which anyone can
    name in a transaction of their own."""
    c, net = env
    org, repo, n = user(), user(), issue()
    job = Pubkey.from_string(go(env, faucet_jwt(c, n, org, repo, work=60), TERMS)["job"])
    c.warp(61)
    assert relay.refund_due(net, c.payer, c.now()) and c.data(job) is None
    assert net.terms_of(job) == TERMS                           # a job that is gone: what it was last funded with
    assert go(env, faucet_jwt(c, n, org, repo, terms=_OTHER), _OTHER)["job"] == str(job)
    assert net.terms_of(job) == _OTHER and net.log_of(job, "knos2:terms ") == "knos2:terms " + _OTHER.decode()
    theirs = "4Nd1mBQtrMJVYVfKf2PJy9NZUZdTAsp7D4xWLs4gDB4T"
    net.named[job].append("someone else's")
    net.said["someone else's"] = [f"Program {theirs} invoke [1]", 'Program log: knos2:terms {"checks":[],"v":2}', f"Program {theirs} success"]
    assert net.log_of(job, "knos2:terms ") == 'knos2:terms {"checks":[],"v":2}'      # the newest line, unless told whose and which is meant
    assert net.log_of(job, "knos2:terms ", by=pay.PAY_ID) == "knos2:terms " + _OTHER.decode()
    assert net.log_of(job, "knos2:terms ", lambda line: '"v":1' in line) == "knos2:terms " + _OTHER.decode()
    assert net.terms_of(job) == _OTHER                          # the escrow's own line, and the hash in the job tells
    # knos-pay itself logging other terms in a transaction that names this address (someone funds a job of their own
    # and lists this one beside it) does not change the answer either
    net.named[job].append("their own job")
    net.said["their own job"] = [f"Program {pay.PAY_ID} invoke [1]", 'Program log: knos2:terms {"checks":[],"v":3}', f"Program {pay.PAY_ID} success"]
    assert net.log_of(job, "knos2:terms ", by=pay.PAY_ID) == 'knos2:terms {"checks":[],"v":3}' and net.terms_of(job) == _OTHER


def test_the_genesis_keys_are_the_ones_the_verifier_holds():
    """The relay registers a genesis key it meets with no attestation; it knows them by the same hashes as pins.rs."""
    pins = (ROOT / "programs-v2" / "knos_oidc" / "src" / "pins.rs").read_text(encoding="utf-8")
    body = pins[pins.index("pub const GENESIS"):]
    assert set(re.findall(r'\(0,\s*h\("([0-9a-f]{64})"\)\)', body[:body.index("];")])) == relay.GENESIS and len(relay.GENESIS) == 4
    github = oidc.jwks_keys(json.loads((FIX / "github_jwks_2026-10-02.json").read_text()))
    assert {oidc.key_hash(n).hex() for _kid, n in github} == relay.GENESIS
    # and the two workflows it knows a token by are the ones the programs pin
    escrow = (ROOT / "programs-v2" / "knos_pay" / "src" / "lib.rs").read_text(encoding="utf-8")
    assert f'CLAIM_REF: &[u8] = b"{relay.CLAIM_REF}"' in escrow and f'CLAIM_SHA: &[u8; 40] = b"{pay.IDS["claim_sha"]}"' in escrow
    assert f'ROTATE_REF: &[u8] = b"{relay.ROTATE_REF}"' in pins and f'ROTATE_SHA: &[u8; 40] = b"{oidc.IDS["rotate_sha"]}"' in pins
    assert relay.CLAIM_SHAS - {TEST_CLAIM_SHA} == {pay.IDS["claim_sha"]} and relay.ROTATE_SHAS - {TEST_ROTATE_SHA} == {oidc.IDS["rotate_sha"]}
    assert relay.ATTESTERS - {(OWNER, REPO)} == {(142920951, 1353152983), (142920951, 1401432540)}


# -- relayed twice, and by two relayers ------------------------------------------------------------------------------------
def test_a_token_relayed_twice_or_by_two_relayers_is_done_once(env):
    """The token is public: the worker and anyone else may carry it at once. Whoever comes second finds the work done,
    says so with the same result, and spends nothing."""
    c, net = env
    other = c.fund()                                            # a second relayer, with a key and SOL of its own
    org, repo, n = user(), user(), issue()
    fund = faucet_jwt(c, n, org, repo)
    first = go(env, fund, TERMS)
    assert first["ok"] and "already" not in first
    n0, sol = net.txs, (lamports(c), lamports(c, other))
    for payer in (other, c.payer):
        again = go(env, fund, TERMS, payer)
        assert again == {**first, "sigs": first["sigs"][-1:], "already": True}, again       # it names the transaction that did it
    assert go(env, fund, None, other)["already"]                # even with the terms lost on the way: the job is there
    # a proof with no address: held. The same proof again, from either relayer: held already, by that proof
    payee = user()
    proof = pay_jwt(c, repo, n, payee)
    held = go(env, proof)
    assert held["ok"] and held["paid"][0]["to"] is None
    n1 = net.txs
    for payer in (other, c.payer):
        again = go(env, proof, None, payer)
        assert again == {**held, "sigs": held["sigs"][-1:], "already": True}, again
    # the claim: bound, and the held payment sent. Again: bound already, nothing left to send
    wallet = Keypair().pubkey()
    claim = bind_jwt(c, payee, wallet)
    bound = go(env, claim)
    assert bound["ok"] and len(bound["settled"]) == 1 and c.balance(pay.ata(wallet, pay.faucet_mint())) == P(4_875_000, 4_950_000)
    n2 = net.txs
    for payer in (other, c.payer):
        again = go(env, claim, None, payer)
        assert again == {**bound, "sigs": bound["sigs"][-1:], "already": True, "settled": []}, again
    assert (net.txs, lamports(c, other)) == (n2, sol[1]) and n1 - n0 == 2 and lamports(c) < sol[0]       # the second relayer never paid a lamport
    # a proof that paid a wallet leaves no job behind: the payee's record's last transactions say it was paid
    n = issue()
    c.warp(60)
    assert go(env, faucet_jwt(c, n, org, repo), TERMS)["ok"]
    proof = pay_jwt(c, repo, n, payee)
    paid = go(env, proof)
    assert paid["ok"] and paid["paid"][0]["to"] == str(wallet)
    n3 = net.txs
    again = go(env, proof, None, other)
    assert again == {"ok": True, "kind": "pay", "sigs": paid["sigs"][-1:], "already": True, "repo_id": repo, "issue": n, "payee_id": payee, "head": "a" * 40,
                     "paid": [{"job": "", "amount": 5 * USDC, "fee": P(125_000, 50_000), "mint": "", "to": str(wallet), "held_until": None}]}, again
    assert net.txs == n3 and relay.precheck(net, other, proof, None, JWKS, now=c.now()) == again
    # a proof for someone who was never paid for that issue is still what it was
    assert refused(env, pay_jwt(c, repo, n, user()), None, "no bounty is in escrow for this issue")


def test_a_token_carried_before_is_known_by_what_it_left_on_chain_and_by_nothing_else(env):
    """What "already" rests on: a job keeps its fund token's time and commenter; a payment is in the escrow's own log,
    at the proof's own time. Not on what the Balance took last, and not on a line anyone can write."""
    c, net = env
    n = issue()
    fund = fund_jwt(c, n)
    first = go(env, fund, TERMS)
    assert first["ok"] and go(env, fund_jwt(c, issue()), TERMS)["ok"]      # the Balance has taken a newer comment's token since
    assert go(env, fund, TERMS, c.fund()) == {**first, "sigs": first["sigs"][-1:], "already": True}
    assert refused(env, fund_jwt(c, n), TERMS, "this issue already has a bounty from this balance")      # another comment on that issue is another matter
    # a stranger's bounty on the issue pins a workflow of their own, so it stays open whatever this proof does
    squatter, qtok = c.wallet(c.usdc, 5 * USDC)
    assert c.send([pay.fund_wallet_ix(squatter.pubkey(), qtok, c.usdc, REPO, n, 5 * USDC, "evil/workflows", "f" * 40, TERMS)], squatter), c.err
    payee, wallet = user(), Keypair().pubkey()
    proof = pay_jwt(c, REPO, n, payee, wallet)
    paid = go(env, proof)
    assert paid["ok"] and len(paid["paid"]) == 1 and len(relay.jobs_for(net, REPO, n)) == 1
    again = go(env, proof, None, c.fund())
    assert again == {"ok": True, "kind": "pay", "sigs": paid["sigs"][-1:], "already": True, "repo_id": REPO, "issue": n, "payee_id": payee, "head": "a" * 40,
                     "paid": [{"job": "", "amount": 5 * USDC, "fee": P(125_000, 50_000), "mint": "", "to": str(wallet), "held_until": None}]}, again
    # later the issue is funded anew with other terms. A proof made for the old ones pays nothing, and that earlier
    # payment is not taken for its doing; nor is a line somebody else's program wrote at the payee's record
    c.warp(pay.TOKEN_AHEAD + 60)
    assert go(env, fund_jwt(c, n, terms=_OTHER), _OTHER)["ok"]
    stale = pay_jwt(c, REPO, n, payee, wallet)
    assert refused(env, stale, None, "the open bounty on this issue has other terms than the ones this token was made for")
    theirs = "4Nd1mBQtrMJVYVfKf2PJy9NZUZdTAsp7D4xWLs4gDB4T"
    net.named[pay.rep_pda(payee)].append("forged")
    net.when["forged"] = c.now()
    net.said["forged"] = [f"Program {theirs} invoke [1]", f"Program log: knos2:paid repo={REPO} issue={n} payee={payee} amount={P(4875000, 4950000)} fee={P(125000, 50000)} to={wallet}",
                          f"Program {theirs} success"]
    assert refused(env, stale, None, "the open bounty on this issue has other terms than the ones this token was made for")


def test_a_claim_carried_before_names_the_transaction_that_bound_the_wallet_not_a_later_payment(env):
    """Found in the 0.3.12 run: the worker's line for an already-carried bind named the payee's latest payment. Every
    payment reads the payee's Bind account, so the last transaction to name that account is not the one that wrote it."""
    c, net = env
    payee, wallet = user(), Keypair().pubkey()
    claim = bind_jwt(c, payee, wallet)
    bound = go(env, claim)
    assert bound["ok"] and net.said[bound["sigs"][-1]].count(f"Program log: knos2:bound user={payee} wallet={wallet}") == 1
    paid = go(env, pay_jwt(c, REPO, funded(env)[0], payee))     # paid to the bound wallet: the payment names the Bind account too
    assert paid["ok"] and paid["paid"][0]["to"] == str(wallet) and net.last_signature(pay.bind_pda(payee)) == paid["sigs"][-1] != bound["sigs"][-1]
    again = go(env, claim, None, c.fund())
    assert again == {**bound, "sigs": bound["sigs"][-1:], "already": True, "settled": []}, again
    # more payments since than the relay looks back over: it names no transaction rather than a wrong one
    net.named[pay.bind_pda(payee)] += [paid["sigs"][-1]] * 10
    assert go(env, claim, None, c.fund())["sigs"] == []


def test_a_claim_another_relayer_bound_still_sends_what_was_left_held(env):
    """Two relayers carry one claim. The first one's Bind lands and its payments do not (it stopped there). The second
    finds the wallet bound by that very token, and sends the payments: they need no token."""
    c, net = env
    payee, wallet = user(), Keypair().pubkey()
    n, job = funded(env, amount=6 * USDC)
    assert go(env, pay_jwt(c, REPO, n, payee))["paid"][0]["to"] is None
    claim = bind_jwt(c, payee, wallet)
    tok = c.verify(claim, oidc.GITHUB, c.github)                 # the first relayer, by hand: verify, Bind, nothing more
    assert c.send([pay.bind_ix(c.payer.pubkey(), tok, c.key, payee)]), c.err
    other = c.fund()
    net.spent()
    r = go(env, claim, None, other)
    assert r == {"ok": True, "kind": "bind", "sigs": r["sigs"], "already": True, "user_id": payee, "wallet": str(wallet),
                 "settled": [{"job": str(job), "amount": 6 * USDC, "fee": P(150_000, 50_000), "mint": str(c.usdc)}]}, r
    assert (net.txs, net.waits) == (1, 1) and c.balance(pay.ata(wallet, c.usdc)) == P(5_850_000, 5_950_000)      # one transaction: no token was verified for it


def test_a_claim_whose_token_is_verified_already_binds_before_it_sends_what_was_held(env):
    """A run was cut short after the claim's token was verified. The next one has no Step to send: the Bind still
    lands before the payments it frees, which need the wallet bound."""
    c, net = env
    payee, wallet = user(), Keypair().pubkey()
    held = [funded(env, amount=6 * USDC)[1], funded(env, amount=7 * USDC)[1], funded(env, amount=8 * USDC)[1]]
    for n in [pay.read_job(c.data(job)).issue for job in held]:
        assert go(env, pay_jwt(c, REPO, n, payee))["paid"][0]["to"] is None
    claim = bind_jwt(c, payee, wallet)
    assert c.verify(claim, oidc.GITHUB, c.github) == oidc.token_pda(c.payer.pubkey(), oidc.token_id(claim))
    net.spent()
    r = go(env, claim)
    assert r["ok"] and {s["job"] for s in r["settled"]} == set(map(str, held)) and "already" not in r, r
    assert net.shape[0] == 1 and sum(net.shape) == net.txs <= 3 and c.balance(pay.ata(wallet, c.usdc)) == P(5_850_000, 5_950_000) + P(6_825_000, 6_950_000) + P(7_800_000, 7_950_000)
    assert c.data(oidc.token_pda(c.payer.pubkey(), oidc.token_id(claim))) is None


# -- when the cluster, not the token, is the reason ------------------------------------------------------------------------
class Flaky:
    """The ledger, with trouble: `fail(i, why)` makes the i-th send from now raise `why` (the transaction does not
    land), `lose(i)` lets it land and then says it was never confirmed."""

    def __init__(self, net: Net):
        self.net, self.trouble, self.i = net, {}, 0

    def __getattr__(self, name):
        return getattr(self.net, name)

    def fail(self, i: int, why: Exception) -> "Flaky":
        self.trouble[self.i + i] = (False, why)
        return self

    def lose(self, i: int) -> "Flaky":
        self.trouble[self.i + i] = (True, TimeoutError("sig not confirmed within 60s"))
        return self

    def send(self, ixs, payer, signers=None, v1=False):
        self.i += 1
        lands, why = self.trouble.pop(self.i, (True, None))
        sig = self.net.send(ixs, payer, signers, v1) if lands else None
        if why is not None:
            raise why
        return sig

    def send_all(self, groups, payer, signers=None, v1=False):
        return [self.send(ixs, payer, signers, v1) for ixs in groups]


def test_a_hiccup_of_the_cluster_is_tried_again_and_a_refusal_is_not(env):
    c, net = env
    org, repo, n = user(), user(), issue()
    fund = faucet_jwt(c, n, org, repo)
    twin = chain.RpcError("transaction failed: {'InstructionError': [1, {'Custom': 69}]}")       # a twin run moved the token account
    for nth, why, said in ((1, TimeoutError("sig not confirmed within 60s"), "TimeoutError: sig not confirmed within 60s"),
                           (2, twin, "another run moved this token's account (error 69)"),
                           (2, OSError("connection reset"), "OSError: connection reset")):
        r = relay.submit(Flaky(net).fail(nth, why), c.payer, fund, TERMS, JWKS, now=c.now())
        assert r == {"ok": False, "kind": "fund", "why": said, "retry": True, "transient": True, **({"answered": True} if why is twin else {})}, r
        assert c.data(oidc.token_pda(c.payer.pubkey(), oidc.token_id(fund))) is None           # the rent came back each time
        assert c.data(pay.job_pda(repo, n, pay.faucet_balance_pda(org))) is None
    assert go(env, fund, TERMS)["ok"]                            # the same token, on the next pass
    assert relay.transient(TimeoutError()) and relay.transient(chain.RpcError("custom program error: 0x54")) and relay.transient(chain.RpcError("Blockhash not found"))
    assert not relay.transient(chain.RpcError("transaction failed: {'InstructionError': [0, {'Custom': 91}]}"))
    # the escrow's own refusal, in the words of its client, is a verdict: the job was funded between the read and the send
    n = issue()
    late = fund_jwt(c, n)

    class Raced(Flaky):
        def send(self, ixs, payer, signers=None, v1=False):
            if len(ixs) > 1 and self.i == 1:                     # just before the last transaction, the newer comment's token lands
                assert go(env, fund_jwt(c, n), TERMS)["ok"]
            return super().send(ixs, payer, signers, v1)
    r = relay.submit(Raced(net), c.payer, late, TERMS, JWKS, now=c.now())
    assert r == {"ok": False, "kind": "fund", "why": pay.ERRORS[91] + " (error 91)"} and c.data(oidc.token_pda(c.payer.pubkey(), oidc.token_id(late))) is None
    # the faucet's minute, taken by another token between the read and the send, is waited out
    assert relay._failed("fund", chain.RpcError("custom program error: 0x5a")) == {"ok": False, "kind": "fund", "why": "the faucet serves a repository once a minute",
                                                                                 "retry": True, "wait": 60}
    # a relayer whose key holds no SOL is told so, and the token is not blamed
    broke = Keypair()
    c.warp(60)
    r = go(env, faucet_jwt(c, issue(), org, repo), TERMS, broke)
    assert r == {"ok": False, "kind": "fund", "why": "the relayer's key has no SOL to pay the fees with", "retry": True, "transient": True}, r


def test_a_relayer_that_loses_the_race_on_its_last_transaction_says_another_carried_it_and_never_names_its_work(env):
    """Live in staging on 7 Oct 2026 two relayers sent one fund token in the same second: each verified it, one
    funded the order, and the other logged that funding transaction as its own, with no "another relayer carried it
    first". The loser now answers `already`, names the winner's transaction, and keeps what it spent apart."""
    c, net = env
    org, repo, n = user(), user(), issue()
    tok, other = faucet_jwt(c, n, org, repo), c.fund()
    won = {}

    class Raced(Flaky):
        def send(self, ixs, payer, signers=None, v1=False):
            if len(ixs) > 1 and not won:                         # this relay's last transaction: the other relayer is there first
                won.update(go(env, tok, TERMS, other))
                assert won["ok"] and "already" not in won, won
            return super().send(ixs, payer, signers, v1)
    r = relay.submit(Raced(net), c.payer, tok, TERMS, JWKS, now=c.now())
    assert r["ok"] and r["already"] and r["job"] == won["job"], r
    assert r["sigs"] == [won["sigs"][-1]] and net.payers[won["sigs"][-1]] == str(other.pubkey())       # the winner's, and only it
    assert r["spent"] and all(net.payers[s] == str(c.payer.pubkey()) for s in r["spent"])               # what the loser sent, apart
    assert not set(r["spent"]) & set(r["sigs"])


def test_a_transaction_reported_lost_that_landed_is_seen_on_the_chain(env):
    c, net = env
    org, repo, n, wallet = user(), user(), issue(), Keypair().pubkey()
    r = relay.submit(Flaky(net).lose(2), c.payer, faucet_jwt(c, n, org, repo), TERMS, JWKS, now=c.now())      # the last transaction: Step, FaucetOpen, FundBalance, Close
    assert r["ok"] and r["job"] == str(pay.job_pda(repo, n, pay.faucet_balance_pda(org))) and len(r["sigs"]) == 2 and "already" not in r, r      # the lost transaction is named too
    payee = user()
    r = relay.submit(Flaky(net).lose(2), c.payer, pay_jwt(c, repo, n, payee, wallet), None, JWKS, now=c.now())
    assert r["ok"] and r["paid"][0]["to"] == str(wallet) and c.balance(pay.ata(wallet, pay.faucet_mint())) == P(4_875_000, 4_950_000), r
    r = relay.submit(Flaky(net).lose(2), c.payer, bind_jwt(c, payee, wallet), None, JWKS, now=c.now())
    assert r["ok"] and r["wallet"] == str(wallet) and pay.read_bind(c.data(pay.bind_pda(payee))).wallet == wallet, r


def test_a_verification_that_was_cut_short_is_carried_on_from_where_it_stands(env):
    c, net = env
    me = c.payer.pubkey()

    def cut_after(rounds: int, jwt: str) -> None:
        """What a run that died after `rounds` rounds of the verification left on chain."""
        t = relay._open(jwt, me, JWKS)
        for txs in relay._verification(me, t, None, [])[0][:rounds]:
            relay._round(net, c.payer, txs)
    for rounds, left, stage in ((1, [1, 1], 0), (2, [1], 1)):
        org, repo, n = user(), user(), issue()
        jwt = faucet_jwt(c, n, org, repo)
        cut_after(rounds, jwt)
        assert oidc.read_token(c.data(oidc.token_pda(me, oidc.token_id(jwt)))).stage == stage
        net.spent()
        assert go(env, jwt, TERMS)["ok"]
        assert net.shape == left, (rounds, net.shape)            # only what was missing was sent
    # half of the head only: the missing chunk is written, the one that is there is not sent again
    org, repo, n = user(), user(), issue()
    jwt = faucet_jwt(c, n, org, repo)
    t = relay._open(jwt, me, JWKS)
    head = relay._verification(me, t, None, [])[0][0]
    assert len(head) == 2
    net.send(head[1], c.payer)
    net.spent()
    assert go(env, jwt, TERMS)["ok"] and net.shape == [1, 1]     # (a v1 transaction writes the whole token again beside the first Step)
    # an account that holds something else under this token's id (it cannot, by its address; a bug could): started again
    org, repo, n = user(), user(), issue()
    jwt = faucet_jwt(c, n, org, repo)
    cut_after(2, jwt)
    acct = oidc.token_pda(me, oidc.token_id(jwt))
    a = c.svm.get_account(acct)
    from solders.account import Account
    c.svm.set_account(acct, Account(lamports=a.lamports, data=bytes(a.data[:-1]) + b"!", owner=a.owner, executable=False))
    net.spent()
    assert go(env, jwt, TERMS)["ok"] and net.shape == [1, 1, 1]         # Close, then the whole verification


def test_the_last_step_goes_alone_when_it_takes_more_compute_than_was_measured(env, monkeypatch):
    c, net = env
    org, repo, n = user(), user(), issue()
    jwt = faucet_jwt(c, n, org, repo)

    class Short(Flaky):
        def send(self, ixs, payer, signers=None, v1=False):
            if len(ixs) > 2 and any(bytes(ix.data)[:1] == b"\x01" and ix.program_id == oidc.OIDC_ID for ix in ixs):
                raise chain.RpcError("Transaction simulation failed: Error processing Instruction 1: Program failed to complete",
                                     {"logs": ["Program FkwZ... failed: exceeded CUs meter at BPF instruction"]})
            return super().send(ixs, payer, signers, v1)
    net.spent()
    r = relay.submit(Short(net), c.payer, jwt, TERMS, JWKS, now=c.now())
    # three transactions for the usual two: the Step alone, then the faucet, the funding and the Close together
    assert r["ok"] and net.txs == 3 and c.data(oidc.token_pda(c.payer.pubkey(), oidc.token_id(jwt))) is None, (r, net.shape)
    # and when the measure says beforehand that the Step leaves no room, nothing is tried: the same shape at once
    monkeypatch.setitem(relay._LAST_STEP, 2048, (1_300_000, 0))
    c.warp(60)
    net.spent()
    assert go(env, faucet_jwt(c, issue(), org, repo), TERMS)["ok"] and net.shape == [1, 1, 1]


# -- what needs no token ----------------------------------------------------------------------------------------------------
def test_an_unproven_bounty_goes_back_and_a_held_one_follows_its_payees_wallet(env):
    c, net = env
    cranker = c.fund()                                           # anyone
    relay.refund_due(net, cranker, c.now())                      # what earlier tests left past its deadline on this chain
    n, from_balance = funded(env, amount=7 * USDC, work=600)
    sponsor, stok = c.wallet(c.usdc, 50 * USDC)
    assert c.send([pay.fund_wallet_ix(sponsor.pubkey(), stok, c.usdc, REPO, n, 11 * USDC, WF_REPO, WF_SHA, TERMS, work_s=600)], sponsor), c.err
    n2, proven = funded(env, amount=9 * USDC, work=600)
    payee = user()
    assert go(env, pay_jwt(c, REPO, n2, payee))["paid"][0]["held_until"]
    baltok0 = c.balance(pay.baltok_pda(c.bal))
    assert relay.refund_due(net, cranker, c.now()) == [] and relay.settle_held(net, cranker) == []
    c.warp(601)
    assert len(relay.refund_due(net, cranker, c.now())) == 2    # the two open jobs; the held one waits for its payee, not for the deadline
    assert c.balance(pay.baltok_pda(c.bal)) == baltok0 + 7 * USDC and c.balance(stok) == 50 * USDC
    assert [j.state for _a, j in relay.jobs_for(net, REPO, n)] == [] and pay.read_job(c.data(proven)).state == "held"
    # the payee binds a wallet (their claim, carried by someone who sent only the Bind): the crank pays the held job
    wallet = Keypair().pubkey()
    tok = c.verify(bind_jwt(c, payee, wallet), oidc.GITHUB, c.github)
    assert c.send([pay.bind_ix(c.payer.pubkey(), tok, c.key, payee)]), c.err
    assert len(relay.settle_held(net, cranker)) == 1 and c.balance(pay.ata(wallet, c.usdc)) == P(8_775_000, 8_950_000)
    assert relay.settle_held(net, cranker) == [] and relay.refund_due(net, cranker, c.now()) == []


def test_a_held_bounty_goes_back_after_180_days():
    """On a chain of its own: nothing here needs a token after the clock has moved half a year."""
    c = Chain()
    net = Net(c)
    env = (c, net)
    assert c.send([pay.init_faucet_ix(c.payer.pubkey())]), c.err
    org, repo, n, payee = user(), user(), issue(), user()
    assert go(env, faucet_jwt(c, n, org, repo), TERMS)["ok"]
    assert go(env, pay_jwt(c, repo, n, payee))["paid"][0]["held_until"] == c.now() + pay.HOLD
    c.warp(pay.HOLD)
    assert relay.refund_due(net, c.payer, c.now()) == []
    c.warp(1)
    assert relay.settle_held(net, c.payer) == []       # too late to pay, even had the payee bound a wallet
    assert len(relay.refund_due(net, c.payer, c.now())) == 1
    assert c.balance(pay.baltok_pda(pay.faucet_balance_pda(org))) == 5 * USDC and relay.held_for(net, payee) == []


# -- key tokens, on both deployments ----------------------------------------------------------------------------------------
def _jwk(kid: str, n: int) -> dict:
    return {"kty": "RSA", "alg": "RS256", "e": "AQAB", "kid": kid, "n": b64(oidc.modulus_bytes(n))}


def attestation(c: Chain, issuer: int, n: int, **over) -> str:
    """What GitHub signs for a scheduled run of the pinned rotate workflow that found this key in the issuer's key set."""
    c.warp(1)
    return token(c, oidc.rotate_audience(issuer, n), **{"file": "rotate.yml", "wf_repo": "drexthealpha/knos-oidc-rotate", "wf_sha": TEST_ROTATE_SHA,
                                                        "event_name": "schedule", **over})


def test_a_key_token_is_carried_to_both_deployments():
    """On a chain of its own, with the first deployment's programs beside the second's. The rotate workflow's token
    names a key GitHub has added: the first deployment takes it as it always did; the second registers it (it then
    waits a day and the guardian), and on later days refreshes it."""
    c = Chain()
    for program, build in ((oidc1.OIDC_ID, "knos_oidc_test.so"), (pay1.PAY_ID, "knos_pay_test.so")):
        c.svm.add_program_from_file(program, str(FIX / build))
    net = Net(c)
    assert c.send([pay.init_faucet_ix(c.payer.pubkey())]), c.err
    assert ROTATE_REF.startswith(relay.ROTATE_REF)
    new = modulus(_STRANGER)
    jwks = {oidc.GITHUB: {"keys": [_jwk("k", modulus(signing_key())), _jwk("new", new)]}}
    submit = lambda jwt, keys=jwks: relay.submit(net, c.payer, jwt, None, keys, now=c.now())  # noqa: E731
    key2, key1 = oidc.key_pda(oidc.GITHUB, new), oidc1.key_pda(oidc.GITHUB, new)
    att = attestation(c, oidc.GITHUB, new)
    r = submit(att)
    assert r == {"ok": True, "kind": "key", "sigs": r["sigs"], "key": str(key2), "added": True, "refreshed": False,
                 "first": {"ok": True, "kind": "key", "sigs": r["first"]["sigs"], "key": str(key1), "added": True}}, r
    assert r["sigs"][:len(r["first"]["sigs"])] == r["first"]["sigs"] and len(r["sigs"]) > len(r["first"]["sigs"])
    k = oidc.read_key(c.data(key2))
    assert (k.state, k.genesis, k.approved, k.revoked, k.active_at, k.expires_at) == (1, False, False, False, c.now() + oidc.KEY_DELAY, c.now() + oidc.KEY_DELAY + oidc.KEY_TTL)
    assert c.data(key1)[0] == 1                                  # ready on the first deployment
    # a token that key signed costs nothing yet: the key waits for its day and for the guardian
    early = sign_jwt(_STRANGER, github_claims(aud=pay.fund_audience(1, 5 * USDC, 0, TH, pay.faucet_balance_pda(OWNER)), iat=c.now(), exp=c.now() + 300, actor_id=MAINT,
                                              event_name="issue_comment", job_workflow_ref=f"{WF_REPO}/.github/workflows/fund.yml@refs/tags/v0.3.12"),
                     header={"alg": "RS256", "kid": "new"})
    n0 = net.txs
    r = relay.submit(net, c.payer, early, TERMS, jwks, now=c.now())
    assert not r["ok"] and "this signing key is new and the guardian has not approved it yet. Its 24-hour wait ends" in r["why"] and net.txs == n0, r
    for program in (oidc.OIDC_ID, oidc1.OIDC_ID):                # and both token accounts were closed behind it
        assert net.program_accounts(program, None, {50: bytes(c.payer.pubkey())}) == []
    # the same token again, and the next day's: both deployments have the key, and a day gained is not worth a transaction
    n0 = net.txs
    for jwt in (att, attestation(c, oidc.GITHUB, new)):
        r = submit(jwt)
        assert r == {"ok": True, "kind": "key", "sigs": [], "key": str(key2), "added": False, "refreshed": False,
                     "first": {"ok": True, "kind": "key", "sigs": [], "key": str(key1), "added": False}} and net.txs == n0, r
    # two days on, the rotate workflow names the key again: its life on the second deployment starts over from now
    c.warp(2 * 86_400)
    r = submit(attestation(c, oidc.GITHUB, new))
    assert (r["ok"], r["added"], r["refreshed"], r["first"]["added"]) == (True, False, True, False) and oidc.read_key(c.data(key2)).expires_at == c.now() + oidc.KEY_TTL, r
    assert net.txs - n0 == 2
    # the same workflow called from someone else's repository: the first deployment takes a key from it, the second does not
    third = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    more = {oidc.GITHUB: {"keys": [*jwks[oidc.GITHUB]["keys"], _jwk("third", modulus(third))]}}
    r = submit(attestation(c, oidc.GITHUB, modulus(third), repository_id=111), more)
    assert r == {"ok": True, "kind": "key", "sigs": r["first"]["sigs"], "key": str(oidc1.key_pda(oidc.GITHUB, modulus(third))), "added": False, "refreshed": False,
                 "why": r["why"], "first": r["first"]} and r["first"]["added"] and "in the attester's own repository" in r["why"], r
    assert c.data(oidc.key_pda(oidc.GITHUB, modulus(third))) is None and c.data(oidc1.key_pda(oidc.GITHUB, modulus(third))) is not None
    # a key that is in nobody's key set: neither deployment takes it, and the answer is the plain refusal
    assert submit(attestation(c, oidc.GITHUB, modulus(third))) == {"ok": False, "kind": "key", "why": "the issuer's key set has no key with that hash"}
    # a key of GitLab's, 4096 bits: registered from the attestation, its parameters in a transaction of their own
    gitlab = json.loads((FIX / "gitlab_jwks_2026-10-02.json").read_text())
    big = next(n for _kid, n in oidc.jwks_keys(gitlab) if n.bit_length() == 4096)
    r = submit(attestation(c, oidc.GITLAB, big), {**jwks, oidc.GITLAB: gitlab})
    k = oidc.read_key(c.data(oidc.key_pda(oidc.GITLAB, big)))
    assert r["ok"] and r["added"] and not r["refreshed"] and (k.state, k.issuer, k.bits, k.approved) == (1, oidc.GITLAB, 4096, False), r
    # once the guardian has revoked a key, no attestation brings it back
    assert c.revoke(oidc.GITHUB, new), c.err
    c.warp(2 * 86_400)
    r = submit(attestation(c, oidc.GITHUB, new))
    assert r["ok"] and not r["added"] and not r["refreshed"] and r["sigs"] == [] and r["why"] == "the guardian revoked this key; it cannot be used again", r
    # every key of the second verifier, GitHub's first, each issuer's oldest first
    listed = relay.keys(net)
    assert [(k.issuer, k.bits, k.genesis, k.revoked) for _a, k, _n in listed] == [(0, 2048, True, False), (0, 2048, False, True), (1, 4096, False, False)]
    assert [n for _a, _k, n in listed] == [modulus(signing_key()), new, big]


def test_what_a_key_needs_and_no_token_gives_anyone_can_send(env):
    c, net = env
    seed4096 = modulus(signing_key(4096))                        # the test build takes this one with no attestation, as GitLab's
    assert c.send([oidc.register_key_ix(c.payer.pubkey(), oidc.GITLAB, seed4096)]), c.err
    assert oidc.read_key(c.data(oidc.key_pda(oidc.GITLAB, seed4096))).state == 0     # registered, its parameters never sent
    anyone = c.fund()
    assert len(relay.register_missing(net, anyone, JWKS)) == 1 and oidc.read_key(c.data(oidc.key_pda(oidc.GITLAB, seed4096))).state == 1
    assert relay.register_missing(net, anyone, JWKS) == []
    # GitHub's own four keys, when the chain has not seen one yet (here: none of them): registered, ready and usable at once
    real = json.loads((FIX / "github_jwks_2026-10-02.json").read_text())
    real_chain = Chain2("knos_oidc_v2_real.so")                 # the build that is deployed: it trusts GitHub's keys, not the tests'
    real_net = Net(real_chain)
    assert relay.keys(real_net) == []
    assert len(relay.register_missing(real_net, real_chain.payer, {oidc.GITHUB: real})) == 4
    got = relay.keys(real_net)
    assert len(got) == 4 and all(k.genesis and oidc.key_usable(k, real_chain.now()) == (True, "") for _a, k, _n in got)
    assert {oidc.key_hash(n).hex() for _a, _k, n in got} == relay.GENESIS
    assert relay.register_missing(real_net, real_chain.payer, {oidc.GITHUB: real}) == []


# -- any other audience: verified, and nothing more ---------------------------------------------------------------------------
def test_any_other_audience_is_only_verified_and_its_account_is_swept_when_its_hour_is_over(env):
    """Another team's program can require a fact GitHub signed without running a relay: it reads the account."""
    c, net = env
    me = c.fund()                                                # a relayer whose accounts nobody else's test touches
    jwt = token(c, "sts.amazonaws.com", sub="repo:octo/widgets:ref:refs/heads/main")
    account = oidc.token_pda(me.pubkey(), oidc.token_id(jwt))
    net.spent()
    r = relay.verify_only(net, me, jwt, JWKS, now=c.now())
    assert r == {"ok": True, "kind": "verify", "account": str(account), "payer": str(me.pubkey()), "exp": c.now() + 300, "sigs": r["sigs"]}, r
    assert (net.txs, net.waits, net.shape) == (2, 2, [1, 1]) and net.v1s == 2      # the whole token and the first Step, then the last Step
    tok = oidc.read_token(c.data(account))
    assert tok.verified and tok.issuer == oidc.GITHUB and tok.payer == me.pubkey() and tok.claims()["aud"] == "sts.amazonaws.com"
    assert c.svm.get_account(account).owner == oidc.OIDC_ID      # what a consumer checks before it reads the claims
    again = relay.verify_only(net, me, jwt, JWKS, now=c.now())
    assert again == {**r, "sigs": [], "already": True} and net.txs == 2
    # a Knos audience is verified the same way when that is all that is asked; `submit` is what acts on one
    assert relay.verify_only(net, me, bind_jwt(c, user(), Keypair().pubkey()), JWKS, now=c.now())["ok"]
    # a GitLab token under a 4096-bit key: six steps, the token's tail riding with the first
    gl = signing_key(4096)
    if c.data(oidc.key_pda(oidc.GITLAB, modulus(gl))) is None:
        assert c.register(oidc.GITLAB, modulus(gl)), c.err
    from _settle import gitlab_claims
    glab = sign_jwt(gl, gitlab_claims(aud="https://vault.example.com", iat=c.now(), exp=c.now() + 300, jti="gl-verify"))
    net.spent()
    r = relay.verify_only(net, me, glab, ALL_JWKS, now=c.now())
    assert r["ok"] and oidc.read_token(c.data(Pubkey.from_string(r["account"]))).claims()["aud"] == "https://vault.example.com", r
    assert net.shape == [1, 1, 1, 1, 1, 1], net.shape            # the token beside the first of the six Steps, then one wait for each
    # nothing is spent on a token no published key signed, on one whose key the chain would refuse, or on an expired one
    n0, sol = net.txs, lamports(c, me)
    forged = sign_jwt(_STRANGER, github_claims(aud="sts.amazonaws.com", iat=c.now(), exp=c.now() + 300))
    assert relay.verify_only(net, me, forged, JWKS, now=c.now()) == {"ok": False, "kind": "verify", "why": "the signature is not the issuer's"}
    assert relay.verify_only(net, me, token(c, "x", exp=c.now() - 3601, iat=c.now() - 3901), JWKS, now=c.now())["why"] == "token expired"
    assert relay.verify_only(net, me, "garbage", JWKS, now=c.now())["why"] == "this is not a token GitHub Actions or GitLab CI issued"
    assert (net.txs, lamports(c, me)) == (n0, sol)
    # a verification that was cut short leaves an account too
    cut = token(c, "sts.amazonaws.com", jti="cut")
    for txs in relay._verification(me.pubkey(), relay._open(cut, me.pubkey(), JWKS), None, [])[0][:1]:
        relay._round(net, me, txs)
    mine = lambda: net.program_accounts(oidc.OIDC_ID, None, {50: bytes(me.pubkey())})  # noqa: E731
    assert len(mine()) == 4
    # the one that never got its whole token says nothing of its expiry: it goes an hour after its last transaction
    assert relay.sweep(net, me, c.now()) == []
    c.warp(oidc.LATE)
    before = lamports(c, me)
    assert len(relay.sweep(net, me, c.now())) == 1 and len(mine()) == 3 and lamports(c, me) > before
    # a verified account stays for its consumer while its token can be used: until an hour past its expiry. Then the rent comes back
    c.warp(again["exp"] + oidc.LATE - 1 - c.now())
    assert relay.sweep(net, me, c.now()) == [] and len(mine()) == 3
    c.warp(1)
    assert len(relay.sweep(net, me, c.now())) == 1 and len(mine()) == 2          # the first token's hour is over
    c.warp(10)
    assert len(relay.sweep(net, me, c.now())) == 2 and mine() == [] and relay.sweep(net, me, c.now()) == []


# -- work orders (2.1) --------------------------------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def oenv(live):
    """A chain with what orders need (tests/_order.py): Circle's stand-in mint, FEE_OWNER's token account, the owner's Balance."""
    from _order import OrderChain
    c = OrderChain(pay_build=LIVE.build)
    assert c.send([pay.init_faucet_ix(c.payer.pubkey())]), c.err
    return c, Net(c)


def order_fund_jwt(c: Chain, n: int, amount: int = 20 * USDC, balance: Pubkey | None = None, seq: int = 0, options: bytes | None = None, terms: bytes = TERMS,
                   work: int = 14 * 86_400, **over) -> str:
    """The token of a maintainer's comment that funds a work order on issue n from a Balance (default: the owner's)."""
    c.warp(1)
    claims = {"file": "fund.yml", "event_name": "issue_comment", "actor_id": MAINT, **over}
    return token(c, pay.order_fund_audience(n, amount, pay.MERGE, pay.terms_hash(terms), balance or c.bal, work, seq, options), **claims)


def order_pay_jwt(c: Chain, order: Pubkey, payees, pr: int = 7, terms: bytes = TERMS, mode: int = pay.MERGE, **over) -> str:
    """What the order's pinned prove.yml asks GitHub to sign in the order's own repository. `payees`: (id, bps, address or None)."""
    return token(c, pay.order_pay_audience(order, "a" * 40, pay.terms_hash(terms), mode, pr, payees), **over)


def ordered(oenv, amount: int = 20 * USDC, **kw) -> tuple[int, Pubkey]:
    c, _net = oenv
    n = issue()
    r = go(oenv, order_fund_jwt(c, n, amount, **kw), kw.get("terms", TERMS))
    assert r["ok"], r
    return n, Pubkey.from_string(r["order"])


def test_a_comment_funds_a_work_order_and_a_proof_pays_its_four_payees_in_two_transactions_each(oenv):
    c, net = oenv
    n = issue()
    jwt = order_fund_jwt(c, n, 100 * USDC)
    order = pay.order_pda(pay.scope_of(REPO, n), c.bal, 0)
    assert relay.precheck(net, c.payer, jwt, TERMS, JWKS, now=c.now()) is None
    before = c.balance(pay.baltok_pda(c.bal))
    net.spent()
    r = go(oenv, jwt, TERMS)
    assert r == {"ok": True, "kind": "fund", "sigs": r["sigs"], "order": str(order), "repo_id": REPO, "issue": n, "seq": 0, "amount": 100 * USDC,
                 "fee": P(2_500_000, 300_000), "mode": 0, "faucet": False, "balance": str(c.bal), "deadline": c.now() + 14 * 86_400}, r
    assert (net.txs, net.waits, net.shape) == (2, 2, [1, 1]) and c.held(order) == P(102_500_000, 100_300_000) == before - c.balance(pay.baltok_pda(c.bal))
    o = c.order(order)
    assert (o.state, o.amount, o.fee, o.funder_id, o.terms, o.from_balance) == ("open", 100 * USDC, P(2_500_000, 300_000), MAINT, TH, True)
    assert net.log_of(order, "knos3:terms ", by=pay.PAY_ID) == "knos3:terms " + TERMS.decode()
    # the same token from another relayer: the order is there, made by this very token; nothing is spent
    n0 = net.txs
    assert go(oenv, jwt, TERMS, c.fund()) == {**r, "sigs": r["sigs"][-1:], "already": True} and net.txs == n0
    # the proof: four payees, none of whom has a token account yet. A relayer nobody has seen: its own token account
    # for the tip is made on the way, once
    relayer = c.fund()
    payees = [(user(), 4000, Keypair().pubkey()), (user(), 3000, Keypair().pubkey()), (user(), 2000, Keypair().pubkey()), (user(), 1000, Keypair().pubkey())]
    proof = order_pay_jwt(c, order, payees)
    fee0 = c.balance(c.fee)
    net.spent()
    net.sizes.clear()
    net.units.clear()
    r = go(oenv, proof, None, relayer)
    assert r == {"ok": True, "kind": "pay", "sigs": r["sigs"], "order": str(order), "repo_id": REPO, "issue": n, "mint": str(c.usdc), "head": "a" * 40, "pr": 7,
                 "paid": [{"id": i, "payee_id": i, "amount": 100 * USDC * bps // 10_000, "to": str(w), "held_until": None} for i, bps, w in payees]}, r
    assert [c.balance(pay.ata(w, c.usdc)) for _i, _b, w in payees] == [40 * USDC, 30 * USDC, 20 * USDC, 10 * USDC] and c.order(order) is None
    # the public relay is paid its tip (0.30: it made the payees' token accounts), FEE_OWNER the rest of the fee
    # (2.5 of it under 2.1; under 2.2 the fee of 100.00 is 0.30, so the whole of it is the tip)
    assert c.balance(pay.ata(relayer.pubkey(), c.usdc)) == pay.TIP_FIRST == 300_000 and c.balance(c.fee) - fee0 == P(2_200_000, 0)
    print(f"\nPayOrder, four new payees, beside the last Step: {net.sizes[-1]} bytes, {net.units[-1]:,} compute units")
    assert (net.txs, net.waits, net.shape) == (2, 2, [1, 1]) and chain.MAX_TX_BYTES < net.sizes[-1] <= relay.ROOM_V1 and net.units[-1] < chain.MAX_COMPUTE_UNITS
    # the proof again, by anyone: the order is gone, and the escrow's own log says who was paid; nothing is spent
    n0 = net.txs
    again = go(oenv, proof, None, c.fund())
    assert again == {**{k: v for k, v in r.items() if k not in ("repo_id", "issue", "mint")}, "sigs": r["sigs"][-1:], "already": True} and net.txs == n0, again
    # the next order's proof: the tip account is there, so the payment is the only instruction beside the Step
    n2, order2 = ordered(oenv)
    r = go(oenv, order_pay_jwt(c, order2, [(payees[0][0], 10_000, payees[0][2])]), None, relayer)
    assert r["ok"] and c.balance(pay.ata(relayer.pubkey(), c.usdc)) == 300_000 + pay.TIP, r


def test_a_used_fund_token_is_not_called_done_when_another_token_funded_its_address_again(oenv):
    # rehearsed on devnet (0.3.14): two `/knos fund` comments of one maintainer on one issue name one order address;
    # the first funded it, the order was paid, the second funded it again, and the first token relayed once more was
    # answered "already", citing the second token's funding
    c, net = oenv
    n = issue()
    first = order_fund_jwt(c, n)
    r1 = go(oenv, first, TERMS)
    assert r1["ok"], r1
    order = Pubkey.from_string(r1["order"])
    assert go(oenv, order_pay_jwt(c, order, [(user(), 10_000, Keypair().pubkey())]))["ok"] and c.order(order) is None
    second = order_fund_jwt(c, n)
    r2 = go(oenv, second, TERMS)
    assert r2["ok"] and r2["order"] == str(order) and r2["sigs"][-1] != r1["sigs"][-1], r2
    got = refused(oenv, first, TERMS, "this token was used already: it funded an earlier order at this address")
    assert r2["sigs"][-1] not in str(got), got
    n0 = net.txs
    assert go(oenv, second, TERMS, c.fund()) == {**r2, "sigs": r2["sigs"][-1:], "already": True} and net.txs == n0


def test_an_order_is_held_for_a_payee_with_no_wallet_then_settled_and_an_unproven_one_goes_back(oenv):
    c, net = oenv
    n, order = ordered(oenv, 30 * USDC)
    who = user()
    proof = order_pay_jwt(c, order, [(who, 10_000, None)])
    r = go(oenv, proof)
    until = c.now() + pay.HOLD
    assert r["ok"] and r["paid"] == [{"id": who, "payee_id": who, "amount": 30 * USDC, "to": None, "held_until": until}] and c.order(order).state == "held", r
    n0 = net.txs
    assert go(oenv, proof, None, c.fund()) == {**r, "sigs": r["sigs"][-1:], "already": True} and net.txs == n0
    assert refused(oenv, order_pay_jwt(c, order, [(user(), 10_000, Keypair().pubkey())]), None, "the order is already held for another GitHub user")
    cranker = c.fund()
    assert relay.settle_orders_held(net, cranker) == [] and relay.refund_orders_due(net, cranker, c.now()) == []
    wallet = Keypair().pubkey()
    assert go(oenv, bind_jwt(c, who, wallet))["ok"]
    assert len(relay.settle_orders_held(net, cranker)) == 1 and c.balance(pay.ata(wallet, c.usdc)) == 30 * USDC and c.order(order) is None
    # whoever settles takes the tip, in an account made on the way: TIP_FIRST, or the whole fee when that is less (2.2: 0.09 on 30.00)
    assert c.balance(pay.ata(cranker.pubkey(), c.usdc)) == P(pay.TIP_FIRST, 90_000)
    assert relay.settle_orders_held(net, cranker) == []
    # an order nobody proved goes back to its Balance with the fee its funder paid; a wallet's order to that wallet
    n, late = ordered(oenv, 10 * USDC, work=600)
    theirs = c.fund_wallet(amount=10 * USDC, work_s=600)
    bal0, w0 = c.balance(pay.baltok_pda(c.bal)), c.balance(c.funder_tok)
    assert [a for a, _o in relay.orders(net, 1)] == sorted([late, theirs], key=str) or len(relay.orders(net, 1)) >= 2
    c.warp(601)
    assert len(relay.refund_orders_due(net, cranker, c.now())) >= 2 and c.order(late) is None and c.order(theirs) is None
    assert c.balance(pay.baltok_pda(c.bal)) - bal0 == 10 * USDC + P(400_000, 50_000) and c.balance(c.funder_tok) - w0 == 10 * USDC + P(400_000, 50_000)
    assert relay.close_markers(net, cranker, c.now()) == []      # this relayer paid for no marker: nothing of its own to close


def _standing(c) -> Pubkey:
    return c.fund_wallet(amount=50 * USDC, options=pay.opts(flags=pay.F_STANDING, rate=10 * USDC))


def _standing_with_a_holdback(c) -> Pubkey:
    return c.fund_wallet(amount=50 * USDC, options=pay.opts(flags=pay.F_STANDING, rate=10 * USDC, holdback_bps=1000, warranty_days=5))


# what is wrong -> (the pay token for the order, what the relay says)
ORDER_PAY_REFUSALS = {
    "a fund.yml token": (lambda c, o: order_pay_jwt(c, o, [(77, 10_000, None)], file="fund.yml"), "not from a judge this order takes"),
    "a run in another repository": (lambda c, o: order_pay_jwt(c, o, [(77, 10_000, None)], repository_id=111), "not from a judge this order takes"),
    "prove.yml at another commit": (lambda c, o: order_pay_jwt(c, o, [(77, 10_000, None)], wf_sha="d" * 40), "the order pins another workflow repository or commit"),
    "a re-run": (lambda c, o: order_pay_jwt(c, o, [(77, 10_000, None)], run_attempt=2), "only a run's first attempt can pay an order"),
    "other terms": (lambda c, o: order_pay_jwt(c, o, [(77, 10_000, None)], terms=_OTHER), "the order has other terms than the ones this token was made for"),
    "a proof made before the funding": (lambda c, o: order_pay_jwt(c, o, [(77, 10_000, None)], iat=c.now() - 1800, exp=c.now() - 1500), "this token is older than the order"),
    "an order that does not exist": (lambda c, o: order_pay_jwt(c, Keypair().pubkey(), [(77, 10_000, None)]), "no such order is in escrow"),
    "shares that do not add up": (lambda c, o: order_pay_jwt(c, o, [(77, 6000, None), (78, 3000, None)]), "malformed audience or claims"),
    "five payees": (lambda c, o: order_pay_jwt(c, o, [(70 + k, 2000, None) for k in range(5)]), "malformed audience or claims"),
    "a payee named twice": (lambda c, o: order_pay_jwt(c, o, [(77, 5000, None), (77, 5000, None)]), "malformed audience or claims"),
    "a split with a payee nobody can pay yet": (lambda c, o: order_pay_jwt(c, o, [(user(), 5000, Keypair().pubkey()), (user(), 5000, None)]), "a split is paid whole or not at all"),
    "the escrow's own account as an address": (lambda c, o: order_pay_jwt(c, o, [(77, 10_000, pay.auth_pda())]), "is the escrow's own account"),
    "a standing order's payee with no wallet": (lambda c, o: order_pay_jwt(c, _standing(c), [(77, 10_000, None)], terms=__import__("_order").TERMS), "a standing order, and one with a holdback, is never held"),
    "a self-hosted runner": (lambda c, o: order_pay_jwt(c, o, [(77, 10_000, None)], runner_environment="self-hosted"), "not from a GitHub-hosted runner"),
    # the words of error 103, as the client has them
    "an order that is both standing and has a holdback": (lambda c, o: order_pay_jwt(c, _standing_with_a_holdback(c), [(77, 10_000, Keypair().pubkey())],
                                                                                    terms=__import__("_order").TERMS),
                                                          "this order is both standing and has a holdback, and such an order is never paid: its money goes back to "
                                                          "its funder at the deadline; fund a new one that is standing or has a holdback, not both"),
}


@pytest.mark.parametrize("what", list(ORDER_PAY_REFUSALS))
def test_an_orders_proof_costs_nothing_with(oenv, what):
    c, _net = oenv
    if not hasattr(c, "an_order"):
        c.an_order = ordered(oenv)[1]
    make, want = ORDER_PAY_REFUSALS[what]
    before = c.data(c.an_order)
    assert refused(oenv, make(c, c.an_order), None, want)["kind"] == "pay"
    assert c.data(c.an_order) == before


def test_an_orders_fund_token_is_refused_before_any_fee_and_the_faucet_funds_one(oenv, monkeypatch):
    c, net = oenv
    n = issue()
    private = pay.opts(flags=pay.F_PRIVATE, judge_repo_id=5, salted=True)
    for jwt, terms, want in (
            (order_fund_jwt(c, n, 4 * USDC), TERMS, "an order is from 5.00 to 100,000.00; this token asks for 4.00"),
            (order_fund_jwt(c, n, options=private), TERMS, "malformed audience or claims"),          # a private order's audience names issue 0
            (order_fund_jwt(c, 0, options=private), TERMS, "not the scope and the terms hash GitHub signed for"),
            (order_fund_jwt(c, n, options=pay.opts(flags=pay.F_PRIVATE, salted=True)), TERMS, "a private order names its scope and a judge repository"),
            (order_fund_jwt(c, n, options=pay.opts(judge_repo_id=5, salted=True)), TERMS, "the order's options are outside what is allowed"),
            (order_fund_jwt(c, n, options=pay.opts(arbiter_id=MAINT)), TERMS, "he cannot be the commenter who funds the order"),
            (order_fund_jwt(c, n, options=pay.opts(arbiter_id=OWNER)), TERMS, "nor the owner whose balance pays"),
            (order_fund_jwt(c, n, options=pay.opts(holdback_bps=6000, warranty_days=10)), TERMS, "the order's options are outside what is allowed"),
            (order_fund_jwt(c, n, options=pay.opts(flags=pay.F_STANDING)), TERMS, "the order's options are outside what is allowed"),
            (order_fund_jwt(c, n), _OTHER, "not the terms GitHub signed for"),
            (order_fund_jwt(c, n), None, "the order's terms did not come with its token"),
            (order_fund_jwt(c, n, actor_id=1234567), TERMS, "this commenter may not spend that balance"),
            (order_fund_jwt(c, n, run_attempt=2), TERMS, "only a run's first attempt can fund"),
            (order_fund_jwt(c, n, file="prove.yml"), TERMS, "a fund token must come from fund.yml"),
            (token(c, f"knos3:fund:{n}:20000000:0:{TH.hex()}:1209600:{c.bal}:0", file="fund.yml", event_name="issue_comment", actor_id=MAINT), TERMS, "malformed audience or claims")):
        assert refused(oenv, jwt, terms, want)["kind"] == "fund"
    # a Balance that holds the amount and not the fee on top of it
    w, wtok = c.wallet(c.usdc, 100 * USDC)
    org = user()
    assert c.send([pay.open_balance_ix(w.pubkey(), org, c.usdc)], w), c.err
    small = pay.balance_pda(org, w.pubkey(), c.usdc)
    from _order import transfer as move
    move(c, wtok, pay.baltok_pda(small), 20 * USDC, w)
    mine = dict(actor_id=org, repository_owner_id=org, repository_id=user())
    assert refused(oenv, order_fund_jwt(c, n, 20 * USDC, small, **mine), TERMS, f"the balance holds 20.00, less than this order and its fee ({P('20.50', '20.06')})")
    # the fee is the live build's, to the unit: one unit short of it is refused before any transaction, and with that unit the
    # program takes exactly what the relay counted (0.50 on 20.00 under 2.1, 0.06 under 2.2) and leaves the Balance empty
    move(c, wtok, pay.baltok_pda(small), P(500_000, 60_000) - 1, w)
    assert refused(oenv, order_fund_jwt(c, n, 20 * USDC, small, **mine), TERMS, "less than this order and its fee")
    move(c, wtok, pay.baltok_pda(small), 1, w)
    r = go(oenv, order_fund_jwt(c, n, 20 * USDC, small, **mine), TERMS)
    assert r["ok"] and r["fee"] == P(500_000, 60_000) and c.balance(pay.baltok_pda(small)) == 0, r
    assert c.held(Pubkey.from_string(r["order"])) == P(20_500_000, 20_060_000)
    # a second order on the issue from the same Balance takes another number, and each fund token works once
    n, first = ordered(oenv)
    assert refused(oenv, order_fund_jwt(c, n), TERMS, f"this issue already has order number 0 from this balance (order {first})")
    r = go(oenv, order_fund_jwt(c, n, seq=1), TERMS)
    assert r["ok"] and r["order"] == str(pay.order_pda(pay.scope_of(REPO, n), c.bal, 1)) != str(first), r
    # with no Balance, on devnet: the faucet mints the amount and the fee, and the order is test money
    org, repo, n = user(), user(), issue()
    jwt = order_fund_jwt(c, n, 20 * USDC, pay.faucet_balance_pda(org), repository_owner_id=org, repository_id=repo)
    net.spent()
    r = go(oenv, jwt, TERMS)
    assert r["ok"] and r["faucet"] and r["fee"] == P(500_000, 60_000) and (net.txs, net.waits) == (2, 2) and c.held(Pubkey.from_string(r["order"])) == P(20_500_000, 20_060_000), r
    # the deployed 2.0 escrow knows no order: its relay says so, and spends nothing
    monkeypatch.setattr(relay, "_VERSION", {("litesvm", pay.PAY_ID): 0})
    for jwt in (order_fund_jwt(c, issue()), order_pay_jwt(c, first, [(77, 10_000, None)])):
        assert refused(oenv, jwt, TERMS, "the escrow on this cluster is version 2.0, which takes no such token yet")
    assert relay.refund_orders_due(net, c.payer, c.now()) == [] and relay.settle_orders_held(net, c.payer) == []


# -- who may judge an order, and what an order can promise (2.1) -----------------------------------------------------------
def by_hand(who: int, **over) -> dict:
    """The claims of the pinned attest.yml started by hand by `who` in a repository of his own."""
    return {"file": "attest.yml", "event_name": "workflow_dispatch", "actor_id": who, "repository_owner_id": who, "repository_id": 40_000_000 + who % 1_000_000, **over}


def row(who: int, amount: int, to) -> dict:
    return {"id": who, "payee_id": who, "amount": amount, "to": str(to) if to else None, "held_until": None}


def test_a_neutral_run_the_judge_repository_and_the_arbiter_each_pay_an_order(oenv):
    c, net = oenv
    seller, wallet = user(), Keypair().pubkey()
    # b. the seller starts attest.yml by hand in a repository of his own: it pays an order funded NEUTRAL, and no other
    n, order = ordered(oenv, 20 * USDC, options=pay.opts(flags=pay.F_NEUTRAL))
    net.spent()
    r = go(oenv, order_pay_jwt(c, order, [(seller, 10_000, wallet)], **by_hand(seller)))
    assert r["ok"] and r["paid"] == [row(seller, 20 * USDC, wallet)] and c.order(order) is None and (net.txs, net.waits) == (2, 2), r
    _n, plain = ordered(oenv)
    assert refused(oenv, order_pay_jwt(c, plain, [(seller, 10_000, wallet)], **by_hand(seller)), None, "not from a judge this order takes")
    _n, neutral = ordered(oenv, options=pay.opts(flags=pay.F_NEUTRAL))
    for over in (dict(event_name="push"), dict(repository_owner_id=user()), dict(file="prove.yml"), dict(run_attempt=2)):
        assert refused(oenv, order_pay_jwt(c, neutral, [(seller, 10_000, wallet)], **by_hand(seller, **over)), None, None)["kind"] == "pay"
    # c. the repository the order named as its judge: its prove.yml or attest.yml, on any event
    judge_repo = user()
    _n, judged = ordered(oenv, options=pay.opts(judge_repo_id=judge_repo))
    assert refused(oenv, order_pay_jwt(c, judged, [(seller, 10_000, wallet)], file="attest.yml", repository_id=judge_repo + 1), None, "or a run in the order's judge repository")
    r = go(oenv, order_pay_jwt(c, judged, [(seller, 10_000, wallet)], file="attest.yml", repository_id=judge_repo, event_name="push"))
    assert r["ok"] and c.order(judged) is None and c.balance(pay.ata(wallet, c.usdc)) == 40 * USDC, r
    # d. the arbiter the order named rules: who is paid and in what shares, with no pull request. Nobody else's run rules
    arbiter, buyer = user(), Keypair().pubkey()
    n, disputed = ordered(oenv, 40 * USDC, options=pay.opts(arbiter_id=arbiter))
    ruled = [(seller, 7000, wallet), (MAINT, 3000, buyer)]
    assert relay.kind_of(pay.rule_audience(disputed, ruled)) == "rule"
    assert refused(oenv, token(c, pay.rule_audience(disputed, ruled), **by_hand(seller)), None, "a ruling is the arbiter's alone")["kind"] == "rule"
    assert refused(oenv, token(c, pay.rule_audience(disputed, ruled), **by_hand(arbiter, event_name="push")), None, "a ruling is the arbiter's alone")
    assert refused(oenv, token(c, pay.rule_audience(disputed, [(arbiter, 10_000, wallet)]), **by_hand(arbiter)), None, "a ruling cannot pay the arbiter himself")
    assert refused(oenv, token(c, pay.rule_audience(plain, ruled), **by_hand(arbiter)), None, "this order named none")
    ruling = token(c, pay.rule_audience(disputed, ruled), **by_hand(arbiter))
    r = go(oenv, ruling)
    assert r == {"ok": True, "kind": "rule", "sigs": r["sigs"], "order": str(disputed), "repo_id": REPO, "issue": n, "mint": str(c.usdc),
                 "paid": [row(seller, 28 * USDC, wallet), row(MAINT, 12 * USDC, buyer)]}, r
    assert c.order(disputed) is None and c.balance(pay.ata(buyer, c.usdc)) == 12 * USDC
    again = go(oenv, ruling, None, c.fund())                    # by another relayer: the escrow's own log says who was paid
    assert again["ok"] and again["already"] and again["paid"] == r["paid"], again


GHE = "https://ghe.acme.example/_services/token"        # a company's own GitHub Enterprise Server: no public runner reaches it
_SECRET = pay.terms_json({"accept": "", "checks": [{"app": 15368, "name": "sealed"}], "deny": [], "mode": "merge", "paths": ["vault/**"], "reserve": 0, "v": 1})


def private_fund_jwt(c: Chain, scope: bytes, judge_repo: int, amount: int = 40 * USDC, seq: int = 0, options: bytes | None = None, n: int = 0, **over) -> str:
    """What fund.yml asks GitHub to sign in a private order's judge repository: issue 0, and sha256(scope || terms hash) for terms."""
    c.warp(1)
    options = options or pay.opts(pay.F_PRIVATE, judge_repo_id=judge_repo, salted=True)
    aud = pay.order_fund_audience(n, amount, pay.MERGE, pay.private_fund_terms(scope, pay.terms_hash(_SECRET)), c.bal, 14 * 86_400, seq, options)
    return token(c, aud, **{"file": "fund.yml", "event_name": "issue_comment", "actor_id": MAINT, "repository_id": judge_repo, **over})


def test_a_comment_in_its_judge_repository_funds_a_private_order_and_its_wallets_own_key_pays_it(oenv):
    """What the relay used to drop. A PRIVATE order is funded by a comment (FundOrderBalance with the scope and the
    terms hash for data), and a token under a key that is not GitHub's is carried where a program takes it: verified
    for anyone to read, and, under a key a wallet registered itself, paying a private order of that wallet's Balance."""
    from knos.proof import ghrelay
    c, net = oenv
    judge_repo, secret_repo, secret_issue, th = user(), 777_123_456, 48_611_907, pay.terms_hash(_SECRET)
    scope = pay.scope_of(secret_repo, secret_issue, bytes(range(32)))
    beside = (scope + th).hex().encode()                    # the `knos-terms:` line of the funding comment
    assert relay.private_terms(beside) == relay.private_terms(scope + th) == scope + th and relay.private_terms(TERMS) is None
    # -- every refusal the escrow would give is given first, for nothing
    other = (pay.scope_of(secret_repo, secret_issue, bytes(32)) + th).hex().encode()
    for jwt, terms, want in (
            (private_fund_jwt(c, scope, judge_repo), None, "the order's scope and terms hash did not come with its token"),
            (private_fund_jwt(c, scope, judge_repo), other, "not the scope and the terms hash GitHub signed for"),
            (private_fund_jwt(c, scope, judge_repo), _SECRET, "not the scope and the terms hash GitHub signed for"),
            (private_fund_jwt(c, scope, judge_repo, repository_id=REPO), beside, "funded by a comment in the repository it names as its judge"),
            (private_fund_jwt(c, scope, judge_repo, n=7), beside, "malformed audience or claims"),
            (private_fund_jwt(c, scope, judge_repo, actor_id=1234567), beside, "this commenter may not spend that balance"),
            (private_fund_jwt(c, scope, judge_repo, file="prove.yml"), beside, "a fund token must come from fund.yml")):
        assert refused(oenv, jwt, terms, want)["kind"] == "fund"
    # -- the comment as a workflow posts it, as the worker reads it
    jwt = private_fund_jwt(c, scope, judge_repo)
    [found] = ghrelay.tokens([{"body": ghrelay.token_comment("fund", jwt, beside), "issue_url": "https://api.github.com/repos/acme/judge/issues/3"}])
    assert (found[0], found[2], found.terms) == ("fund", jwt, beside) and ghrelay.misposted("fund", jwt, beside) is None
    for wrong in (None, other, _SECRET, TERMS):
        assert "its `knos-terms:` line is missing, or is not the terms the token names" in ghrelay.misposted("fund", jwt, wrong)
    assert ghrelay.misposted("fund", order_fund_jwt(c, issue()), TERMS) is None and ghrelay.misposted("fund", order_fund_jwt(c, issue()), beside)
    # -- funded: two transactions, and nothing of the repository, the issue or the terms is on chain or in the verdict
    net.spent()
    r = ghrelay.relay_one(net, c.payer, "fund", jwt, terms=found.terms, submit=lambda led, payer, t: relay.submit(led, payer, t, found.terms, JWKS, now=c.now()))
    order = pay.order_pda(scope, c.bal, 0)
    assert r["ok"] and (r["order"], r["private"], r["issue"], r["repo_id"], r["amount"], r["fee"]) == (str(order), True, 0, judge_repo, 40 * USDC, P(USDC, 120_000)), r
    assert (net.txs, net.waits) == (2, 2)
    o = c.order(order)
    assert (o.state, o.from_balance, o.repo_id, o.issue, o.flags, o.judge_repo_id, o.scope, o.terms) == ("open", True, 0, 0, pay.F_PRIVATE, judge_repo, scope, th)
    assert "private work order" in r["note"] and f"judge repository (id {judge_repo})" in r["note"]
    assert not any(secret in r["note"] + json.dumps({k: v for k, v in r.items() if k != "note"}) for secret in (str(secret_repo), str(secret_issue), "vault"))
    again = go(oenv, jwt, beside, c.fund())                 # another relayer, the same comment: done, and no fee
    assert again["ok"] and again["already"] and again["order"] == str(order)
    # the 64 bytes themselves are taken as well (a workflow that relays its own token hands them over as they are)
    r2 = go(oenv, private_fund_jwt(c, scope, judge_repo, seq=1), scope + th)
    assert r2["ok"] and r2["order"] == str(pay.order_pda(scope, c.bal, 1)), r2
    second = Pubkey.from_string(r2["order"])
    # -- paid by a run in its judge repository, as any order with one is
    seller, wallet = user(), Keypair().pubkey()
    r = go(oenv, order_pay_jwt(c, order, [(seller, 10_000, wallet)], terms=_SECRET, file="attest.yml", repository_id=judge_repo))
    assert r["ok"] and r["paid"] == [row(seller, 40 * USDC, wallet)] and c.order(order) is None, r
    # -- a key that is not GitHub's. The wallet that opened the Balance registers its own server's key (and never sends its parameters)
    company = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    n = modulus(company)
    assert c.send([oidc.register_private_key_ix(c.owner.pubkey(), GHE, n)], c.owner), c.err
    mine = oidc.key_pda(GHE, n, registrant=c.owner.pubkey())
    assert [(a, k.private, k.registrant) for a, k, _n in relay.other_keys(net, GHE)] == [(mine, True, c.owner.pubkey())]
    ghe = lambda aud, key=company, **over: token(c, aud, key=key, **{"iss": GHE, "repository_id": judge_repo, **over})  # noqa: E731
    payees = [(seller, 10_000, wallet)]
    proof = lambda o, **over: ghe(pay.order_pay_audience(o, "a" * 40, th, pay.MERGE, 7, payees), **over)  # noqa: E731
    # what it cannot do, each said before a fee: pay as no judge of the order would, rule, fund, pay a public order of the
    # same Balance or anyone's order from a wallet; and a key some other wallet registered pays nothing of the company's
    _n, public = ordered(oenv, options=pay.opts(judge_repo_id=judge_repo))
    of_wallet = c.fund_wallet(options=pay.opts(judge_repo_id=judge_repo))
    thief_wallet, thief = c.fund(), rsa.generate_private_key(public_exponent=65537, key_size=2048)
    assert c.send([oidc.register_private_key_ix(thief_wallet.pubkey(), GHE, modulus(thief))], thief_wallet), c.err
    assert c.send([oidc.key_params_ix(thief_wallet.pubkey(), GHE, modulus(thief), registrant=thief_wallet.pubkey())], thief_wallet), c.err
    only = "pays only a private order funded from that wallet's own balance"
    for jwt, terms, want, kind in (
            (proof(second, repository_id=REPO), None, "not from a judge this order takes", "pay"),
            (proof(second, runner_environment="self-hosted"), None, "not from a GitHub-hosted runner", "pay"),
            (ghe(pay.order_pay_audience(public, "a" * 40, TH, pay.MERGE, 7, payees)), None, only, "pay"),
            (ghe(pay.order_pay_audience(of_wallet, "a" * 40, TH, pay.MERGE, 7, payees)), None, only, "pay"),
            (proof(second, key=thief), None, only, "pay"),
            (ghe(pay.rule_audience(second, payees), **by_hand(seller)), None, "the escrow takes GitHub's tokens only", "rule"),
            (private_fund_jwt(c, scope, judge_repo, seq=2, key=company, iss=GHE), beside, "the escrow takes GitHub's tokens only", "fund"),
            (proof(second, iss="https://ci.nobody.example"), None, "the verifier holds no key of its issuer that signed it", "pay"),
            (proof(second, key=_STRANGER), None, "the verifier holds no key of its issuer that signed it", "pay")):
        assert refused(oenv, jwt, terms, want)["kind"] == kind
    assert c.order(second).state == "open"
    # what it can: the company's own run pays the company's private order. The key's parameters go out on the way
    net.spent()
    r = go(oenv, proof(second))
    assert r["ok"] and r["paid"] == [row(seller, 40 * USDC, wallet)] and c.order(second) is None and c.balance(pay.ata(wallet, c.usdc)) == 80 * USDC, r
    assert oidc.read_key(c.data(mine)).state == 1 and net.txs == 3
    # -- and any token the verifier holds a key for is verified for another program to read: under the private key, and
    # under a registered issuer's (GitHub's signature named it, the guardian approved it, its day of waiting passed)
    me = c.fund()
    v = relay.verify_only(net, me, ghe("https://vault.acme.example"), JWKS, now=c.now())
    assert v["ok"] and oidc.token_issuer(c.data(Pubkey.from_string(v["account"]))) == (oidc.issuer_hash(GHE), c.owner.pubkey()), v
    ci, url = rsa.generate_private_key(public_exponent=65537, key_size=2048), "https://oidc.ci.example.dev"
    att = c.attest(url, modulus(ci))
    assert c.send([oidc.register_issuer_key_ix(c.payer.pubkey(), url, modulus(ci), att, c.key_of(att))]), c.err
    assert c.send([oidc.approve_ix(GUARDIAN.pubkey(), url, modulus(ci))], signers=[GUARDIAN]), c.err
    early = token(c, "https://vault.acme.example", key=ci, iss=url)
    n0 = net.txs
    assert "is new" in relay.verify_only(net, me, early, JWKS, now=c.now())["why"] and net.txs == n0       # its day of waiting: said, not paid for
    c.warp(oidc.KEY_DELAY)
    v = relay.verify_only(net, me, token(c, "https://vault.acme.example", key=ci, iss=url), JWKS, now=c.now())
    assert v["ok"] and oidc.read_token(c.data(Pubkey.from_string(v["account"]))).issuer == oidc.OTHER, v
    assert oidc.token_issuer(c.data(Pubkey.from_string(v["account"]))) == (oidc.issuer_hash(url), None)
    # the escrow takes nothing a registered issuer signed, and the relay says so for nothing
    _n, third = ordered(oenv, options=pay.opts(judge_repo_id=judge_repo))
    theirs = token(c, pay.order_pay_audience(third, "a" * 40, TH, pay.MERGE, 7, payees), key=ci, iss=url, repository_id=judge_repo)
    assert "a token of another issuer is verified for other programs to read" in refused(oenv, theirs, None, "the escrow takes GitHub's tokens only")["why"]


# -- a command (Reserve, Cancel) and a revert: the relay refuses what the escrow refuses, and carries what it takes ------------------
E_ACCOUNTS, E_STATE, E_CLAIMS, E_WORKFLOW, E_AUD = 80, 83, 85, 86, 87     # knos_pay's codes (programs-v2/knos_pay/src/lib.rs)
JUDGE_REPO, ARBITER = 31_313_131, 7_700_077
COMMENT = {"file": "fund.yml", "event_name": "issue_comment"}              # the order's COMMAND job answering a comment
NO_COMMAND, NO_JUDGE, ALONE = "not a command this order takes", "not from a judge this order takes", "a person reserves an order for himself"
BAD = "malformed audience or claims"
# what an order is funded with, by name: `judged` names a judge repository and an arbiter, `all` is NEUTRAL as well
ORDERS = {"plain": {}, "neutral": {"flags": pay.F_NEUTRAL}, "judged": {"judge_repo_id": JUDGE_REPO, "arbiter_id": ARBITER},
          "all": {"flags": pay.F_NEUTRAL, "judge_repo_id": JUDGE_REPO, "arbiter_id": ARBITER}}


def escrow_says(oenv, jwt: str, ix_of) -> int | None:
    """The escrow's own answer to a token, with no relay in between: the verifier takes the token as it stands and
    `ix_of(token account)` is sent. None when the escrow did what the token asks, else the escrow's error code."""
    from _order import code
    c, _net = oenv
    tok = c.verify(jwt, oidc.GITHUB, c.github)
    assert tok is not None, c.err
    return None if c.send([ix_of(tok)]) else code(c)


def reserve_with(c, order: Pubkey):
    return lambda tok: pay.reserve_ix(c.payer.pubkey(), tok, c.key, order)


def take_jwt(c: Chain, order: Pubkey, taker: int, days: int = 5, **over) -> str:
    return token(c, pay.take_audience(order, taker, days), **over)


# what -> (the order, the take token for `who`, None when the escrow reserves on it, else (its code, what the relay says first))
TAKES = {
    "the order's fund.yml answering the taker's comment": ("plain", lambda c, o, who: take_jwt(c, o, who, actor_id=who, **COMMENT), None),
    "the order's prove.yml on the taker's pull request": ("plain", lambda c, o, who: take_jwt(c, o, who, actor_id=who), None),
    "the most days the order allows": ("plain", lambda c, o, who: take_jwt(c, o, who, 7, actor_id=who, **COMMENT), None),
    "attest.yml by hand in the taker's own repository, for a NEUTRAL order": ("neutral", lambda c, o, who: take_jwt(c, o, who, **by_hand(who)), None),
    "the order's fund.yml for a NEUTRAL order": ("all", lambda c, o, who: take_jwt(c, o, who, actor_id=who, **COMMENT), None),
    "the arbiter of a NEUTRAL order, by hand, for himself as anyone": ("all", lambda c, o, who: take_jwt(c, o, ARBITER, **by_hand(ARBITER)), None),
    "a comment that names another taker": ("plain", lambda c, o, who: take_jwt(c, o, who, actor_id=user(), **COMMENT), (E_CLAIMS, ALONE)),
    "a pull request that names another taker": ("plain", lambda c, o, who: take_jwt(c, o, who, actor_id=user()), (E_CLAIMS, ALONE)),
    "a neutral run that names another taker": ("neutral", lambda c, o, who: take_jwt(c, o, who, **by_hand(user())), (E_CLAIMS, ALONE)),
    "a neutral run for an order that is not NEUTRAL": ("plain", lambda c, o, who: take_jwt(c, o, who, **by_hand(who)), (E_CLAIMS, NO_COMMAND)),
    "a neutral run started by a push": ("neutral", lambda c, o, who: take_jwt(c, o, who, **by_hand(who, event_name="push")), (E_CLAIMS, NO_COMMAND)),
    "a neutral run in a repository its starter does not own": ("neutral", lambda c, o, who: take_jwt(c, o, who, **by_hand(who, repository_owner_id=user())),
                                                               (E_CLAIMS, NO_COMMAND)),
    "prove.yml by hand in the taker's own repository": ("neutral", lambda c, o, who: take_jwt(c, o, who, **by_hand(who, file="prove.yml")), (E_WORKFLOW, NO_COMMAND)),
    "fund.yml by hand in the taker's own repository": ("neutral", lambda c, o, who: take_jwt(c, o, who, **by_hand(who, file="fund.yml")), (E_WORKFLOW, NO_COMMAND)),
    "attest.yml in the order's own repository, not NEUTRAL": ("plain", lambda c, o, who: take_jwt(c, o, who, actor_id=who, file="attest.yml"), (E_WORKFLOW, NO_COMMAND)),
    "another file of the pinned workflows": ("plain", lambda c, o, who: take_jwt(c, o, who, actor_id=who, file="claim.yml"), (E_WORKFLOW, NO_COMMAND)),
    "the command job of another repository": ("plain", lambda c, o, who: take_jwt(c, o, who, actor_id=who, repository_id=111, **COMMENT), (E_CLAIMS, NO_COMMAND)),
    "the judge repository's fund.yml": ("judged", lambda c, o, who: take_jwt(c, o, who, actor_id=who, repository_id=JUDGE_REPO, **COMMENT), (E_CLAIMS, NO_COMMAND)),
    "the judge repository's prove.yml": ("judged", lambda c, o, who: take_jwt(c, o, who, actor_id=who, repository_id=JUDGE_REPO), (E_CLAIMS, NO_COMMAND)),
    "the judge repository's attest.yml": ("judged", lambda c, o, who: take_jwt(c, o, who, actor_id=who, repository_id=JUDGE_REPO, file="attest.yml"),
                                          (E_CLAIMS, NO_COMMAND)),
    "the arbiter by hand, for an order that is not NEUTRAL": ("judged", lambda c, o, who: take_jwt(c, o, ARBITER, **by_hand(ARBITER)), (E_CLAIMS, NO_COMMAND)),
    "a re-run": ("plain", lambda c, o, who: take_jwt(c, o, who, actor_id=who, run_attempt=2, **COMMENT), (E_CLAIMS, "only a run's first attempt can reserve an order")),
    "the workflows at another commit": ("plain", lambda c, o, who: take_jwt(c, o, who, actor_id=who, wf_sha="d" * 40, **COMMENT),
                                        (E_WORKFLOW, "the order pins another workflow repository or commit")),
    "another repository's workflows": ("plain", lambda c, o, who: take_jwt(c, o, who, actor_id=who, wf_repo="someone/Knos", **COMMENT),
                                       (E_WORKFLOW, "the order pins another workflow repository or commit")),
    "a self-hosted runner": ("plain", lambda c, o, who: take_jwt(c, o, who, actor_id=who, runner_environment="self-hosted", **COMMENT),
                             (E_CLAIMS, "not from a GitHub-hosted runner")),
    "more days than the order allows": ("plain", lambda c, o, who: take_jwt(c, o, who, 8, actor_id=who), (E_AUD, "this order is reserved for 1 to 7 days, and the token asks for 8")),
    "no days": ("plain", lambda c, o, who: take_jwt(c, o, who, 0, actor_id=who), (E_AUD, "this order is reserved for 1 to 7 days, and the token asks for 0")),
    "days with a leading zero": ("plain", lambda c, o, who: token(c, f"knos3:take:{o}:{who}:05", actor_id=who), (E_AUD, BAD)),
    "a taker with a leading zero": ("plain", lambda c, o, who: token(c, f"knos3:take:{o}:0{who}:5", actor_id=who), (E_AUD, BAD)),
    "a taker with a sign": ("plain", lambda c, o, who: token(c, f"knos3:take:{o}:+{who}:5", actor_id=who), (E_AUD, BAD)),
    "days with a space": ("plain", lambda c, o, who: token(c, f"knos3:take:{o}:{who}: 5", actor_id=who), (E_AUD, BAD)),
    "nobody for a taker": ("plain", lambda c, o, who: take_jwt(c, o, 0, actor_id=0, **COMMENT), (E_AUD, BAD)),
    "an order funded with no reservations": ("closed", lambda c, o, who: take_jwt(c, o, who, 1, actor_id=who, **COMMENT), (E_AUD, "this order takes no reservations")),
}


@pytest.mark.parametrize("what", list(TAKES))
def test_a_take_token_is_carried_exactly_when_the_escrow_reserves_on_it(oenv, what):
    c, net = oenv
    kind, make, verdict = TAKES[what]
    who = user()
    n, order = ordered(oenv, options=pay.opts(reserve_days=0 if kind == "closed" else 7, **ORDERS.get(kind, {})))
    jwt = make(c, order, who)
    if verdict is None:
        assert relay.precheck(net, c.payer, jwt, None, JWKS, now=c.now()) is None
        r = go(oenv, jwt)
        o = c.order(order)
        assert r["ok"] and (r["kind"], r["issue"], r["taker_id"], r["reserved_until"]) == ("take", n, o.reserved_by, o.reserved_until) and o.reserved_by in (who, ARBITER), r
        assert o.reserved_until == c.now() + r["days"] * 86_400
        return
    code, why = verdict
    assert refused(oenv, jwt, None, why)["kind"] == "take"
    assert escrow_says(oenv, jwt, reserve_with(c, order)) == code and c.order(order).reserved_by == 0


def cancel_jwt(c: Chain, order: Pubkey, **over) -> str:
    return token(c, pay.cancel_audience(order), **over)


NOT_HIS = "only the commenter who funded the order, or the owner of the balance it came from, cancels it"
NEUTRAL_CANCEL = "a neutral run cancels nothing"
# what -> (the order, the cancel token, None when the escrow cancels on it, else (its code, what the relay says first)). MAINT funded every one from OWNER's Balance
CANCELS = {
    "the order's fund.yml answering the funder's comment": ("plain", lambda c, o: cancel_jwt(c, o, actor_id=MAINT, **COMMENT), None),
    "the order's prove.yml run by the funder": ("plain", lambda c, o: cancel_jwt(c, o, actor_id=MAINT), None),
    "the order's fund.yml answering the Balance's owner": ("plain", lambda c, o: cancel_jwt(c, o, actor_id=OWNER, **COMMENT), None),
    "the order's prove.yml run by the Balance's owner": ("plain", lambda c, o: cancel_jwt(c, o, actor_id=OWNER), None),
    "the order's fund.yml for a NEUTRAL order": ("all", lambda c, o: cancel_jwt(c, o, actor_id=MAINT, **COMMENT), None),
    "a comment by someone else": ("plain", lambda c, o: cancel_jwt(c, o, actor_id=user(), **COMMENT), (E_CLAIMS, NOT_HIS)),
    "a pull request by someone else": ("plain", lambda c, o: cancel_jwt(c, o, actor_id=user()), (E_CLAIMS, NOT_HIS)),
    "a comment by the arbiter": ("judged", lambda c, o: cancel_jwt(c, o, actor_id=ARBITER, **COMMENT), (E_CLAIMS, NOT_HIS)),
    "a neutral run by the funder, for a NEUTRAL order": ("neutral", lambda c, o: cancel_jwt(c, o, **by_hand(MAINT)), (E_CLAIMS, NEUTRAL_CANCEL)),
    "a neutral run by the Balance's owner in the order's own repository": ("neutral", lambda c, o: cancel_jwt(c, o, **by_hand(OWNER, repository_id=REPO)),
                                                                           (E_CLAIMS, NEUTRAL_CANCEL)),
    "a neutral run by the funder, for an order that is not NEUTRAL": ("plain", lambda c, o: cancel_jwt(c, o, **by_hand(MAINT)), (E_CLAIMS, NO_COMMAND)),
    "attest.yml in the order's own repository, not NEUTRAL": ("plain", lambda c, o: cancel_jwt(c, o, actor_id=MAINT, file="attest.yml"), (E_WORKFLOW, NO_COMMAND)),
    "another file of the pinned workflows": ("plain", lambda c, o: cancel_jwt(c, o, actor_id=MAINT, file="claim.yml"), (E_WORKFLOW, NO_COMMAND)),
    "the command job of another repository": ("plain", lambda c, o: cancel_jwt(c, o, actor_id=MAINT, repository_id=111, **COMMENT), (E_CLAIMS, NO_COMMAND)),
    "the judge repository's fund.yml": ("judged", lambda c, o: cancel_jwt(c, o, actor_id=MAINT, repository_id=JUDGE_REPO, **COMMENT), (E_CLAIMS, NO_COMMAND)),
    "the judge repository's prove.yml": ("judged", lambda c, o: cancel_jwt(c, o, actor_id=MAINT, repository_id=JUDGE_REPO), (E_CLAIMS, NO_COMMAND)),
    "the arbiter by hand": ("judged", lambda c, o: cancel_jwt(c, o, **by_hand(ARBITER)), (E_CLAIMS, NO_COMMAND)),
    "a re-run": ("plain", lambda c, o: cancel_jwt(c, o, actor_id=MAINT, run_attempt=2, **COMMENT), (E_CLAIMS, "only a run's first attempt can cancel an order")),
    "the workflows at another commit": ("plain", lambda c, o: cancel_jwt(c, o, actor_id=MAINT, wf_sha="d" * 40, **COMMENT),
                                        (E_WORKFLOW, "the order pins another workflow repository or commit")),
    "a self-hosted runner": ("plain", lambda c, o: cancel_jwt(c, o, actor_id=MAINT, runner_environment="self-hosted", **COMMENT), (E_CLAIMS, "not from a GitHub-hosted runner")),
    "an audience that says more": ("plain", lambda c, o: token(c, f"knos3:cancel:{o}:1", actor_id=MAINT, **COMMENT), (E_AUD, BAD)),
    "an order a wallet funded": ("wallet", lambda c, o: cancel_jwt(c, o, actor_id=MAINT, **COMMENT), (E_ACCOUNTS, "only that wallet's own signature cancels it")),
}


@pytest.mark.parametrize("what", list(CANCELS))
def test_a_cancel_token_is_carried_exactly_when_the_escrow_cancels_on_it(oenv, what):
    c, net = oenv
    kind, make, verdict = CANCELS[what]
    n, order = (0, c.fund_wallet(amount=10 * USDC)) if kind == "wallet" else ordered(oenv, options=pay.opts(**ORDERS[kind]), work=30 * 86_400)
    jwt = make(c, order)
    if verdict is None:
        assert relay.precheck(net, c.payer, jwt, None, JWKS, now=c.now()) is None
        r = go(oenv, jwt)
        o = c.order(order)
        assert r["ok"] and (r["kind"], r["issue"], r["cancel_at"], r["deadline"]) == ("cancel", n, o.cancel_at, o.deadline) == ("cancel", n, c.now(), c.now() + pay.NOTICE), r
        return
    code, why = verdict
    assert refused(oenv, jwt, None, why)["kind"] == "cancel"
    assert escrow_says(oenv, jwt, lambda tok: pay.cancel_ix(c.payer.pubkey(), order, tok, c.key)) == code and c.order(order).cancel_at == 0


def revert_jwt(c: Chain, order: Pubkey, head: str = "a" * 40, **over) -> str:
    return token(c, pay.revert_audience(order, head), **over)


# what -> (the order, the revert token, None when the escrow sends the holdback back on it, else (its code, what the relay says first))
REVERTS = {
    "a. the order's prove.yml": ("plain", lambda c, o: revert_jwt(c, o), None),
    "a. the order's prove.yml, whoever else could judge": ("all", lambda c, o: revert_jwt(c, o, actor_id=user()), None),
    "b. attest.yml by hand in the runner's own repository, for a NEUTRAL order": ("neutral", lambda c, o: revert_jwt(c, o, **by_hand(user())), None),
    "c. the judge repository's prove.yml": ("judged", lambda c, o: revert_jwt(c, o, repository_id=JUDGE_REPO), None),
    "c. the judge repository's attest.yml, on any event": ("judged", lambda c, o: revert_jwt(c, o, file="attest.yml", repository_id=JUDGE_REPO, event_name="push"), None),
    "the arbiter of a NEUTRAL order, by hand, as anyone": ("all", lambda c, o: revert_jwt(c, o, **by_hand(ARBITER)), None),
    "the arbiter, for an order that is not NEUTRAL": ("judged", lambda c, o: revert_jwt(c, o, **by_hand(ARBITER)), (E_CLAIMS, NO_JUDGE)),
    "the order's fund.yml: a command's run is no judge": ("plain", lambda c, o: revert_jwt(c, o, **COMMENT), (E_WORKFLOW, NO_JUDGE)),
    "attest.yml in the order's own repository, not NEUTRAL": ("plain", lambda c, o: revert_jwt(c, o, file="attest.yml"), (E_WORKFLOW, NO_JUDGE)),
    "a neutral run for an order that is not NEUTRAL": ("plain", lambda c, o: revert_jwt(c, o, **by_hand(user())), (E_CLAIMS, NO_JUDGE)),
    "a neutral run started by a push": ("neutral", lambda c, o: revert_jwt(c, o, **by_hand(user(), event_name="push")), (E_CLAIMS, NO_JUDGE)),
    "a neutral run in a repository its starter does not own": ("neutral", lambda c, o: revert_jwt(c, o, **by_hand(user(), repository_owner_id=user())), (E_CLAIMS, NO_JUDGE)),
    "prove.yml by hand in the runner's own repository": ("neutral", lambda c, o: revert_jwt(c, o, **by_hand(user(), file="prove.yml")), (E_WORKFLOW, NO_JUDGE)),
    "prove.yml in another repository": ("plain", lambda c, o: revert_jwt(c, o, repository_id=111), (E_CLAIMS, NO_JUDGE)),
    "the judge repository's fund.yml": ("judged", lambda c, o: revert_jwt(c, o, repository_id=JUDGE_REPO, **COMMENT), (E_WORKFLOW, NO_JUDGE)),
    "a re-run": ("plain", lambda c, o: revert_jwt(c, o, run_attempt=2), (E_CLAIMS, "only a run's first attempt can end an order's warranty")),
    "the workflows at another commit": ("plain", lambda c, o: revert_jwt(c, o, wf_sha="d" * 40), (E_WORKFLOW, "the order pins another workflow repository or commit")),
    "a self-hosted runner": ("plain", lambda c, o: revert_jwt(c, o, runner_environment="self-hosted"), (E_CLAIMS, "not from a GitHub-hosted runner")),
    "a head that is no commit": ("plain", lambda c, o: revert_jwt(c, o, "xyz"), (E_AUD, BAD)),
    "a head in capitals": ("plain", lambda c, o: revert_jwt(c, o, "A" * 40), (E_AUD, BAD)),
}


@pytest.mark.parametrize("what", list(REVERTS))
def test_a_revert_token_is_carried_exactly_when_the_escrow_returns_the_holdback_on_it(oenv, what):
    c, net = oenv
    kind, make, verdict = REVERTS[what]
    n, order = ordered(oenv, 50 * USDC, options=pay.opts(holdback_bps=2000, warranty_days=2, **ORDERS[kind]))
    assert go(oenv, order_pay_jwt(c, order, [(user(), 10_000, Keypair().pubkey())]))["ok"] and c.order(order).state == "warranty"
    jwt = make(c, order)
    bal0 = c.balance(pay.baltok_pda(c.bal))
    if verdict is None:
        assert relay.precheck(net, c.payer, jwt, None, JWKS, now=c.now()) is None
        r = go(oenv, jwt)
        assert r["ok"] and (r["kind"], r["issue"], r["amount"]) == ("revert", n, P(10_250_000, 10_030_000)) and c.order(order) is None, r
        assert c.balance(pay.baltok_pda(c.bal)) - bal0 == P(10_250_000, 10_030_000)
        return
    code, why = verdict
    assert refused(oenv, jwt, None, why)["kind"] == "revert"
    o = c.order(order)
    ix_of = lambda tok: pay.revert_ix(c.payer.pubkey(), tok, c.key, order, o, pay.read_holdback(c.data(pay.hb_pda(order))))  # noqa: E731
    assert escrow_says(oenv, jwt, ix_of) == code and c.order(order).state == "warranty" and c.balance(pay.baltok_pda(c.bal)) == bal0
    assert go(oenv, revert_jwt(c, order))["ok"] and c.order(order) is None        # and the order's own judge still reverts it


def test_a_private_order_has_no_command_job_and_its_judge_repository_reverts_it(oenv):
    """A PRIVATE order's own repository is not on chain (repository 0), so no run takes or cancels it, in its judge
    repository or anywhere; its judge repository, which pays it, is also the one that says its change was reverted."""
    c, net = oenv
    judge_repo, who, th = user(), user(), pay.terms_hash(_SECRET)
    scope = pay.scope_of(777_123_456, issue(), bytes(range(32)))
    options = pay.opts(pay.F_PRIVATE, judge_repo_id=judge_repo, salted=True, reserve_days=7, holdback_bps=2000, warranty_days=2)
    r = go(oenv, private_fund_jwt(c, scope, judge_repo, options=options), scope + th)
    assert r["ok"] and r["private"], r
    order = Pubkey.from_string(r["order"])
    for run in (lambda a: dict(COMMENT, repository_id=judge_repo, actor_id=a), lambda a: dict(repository_id=judge_repo, actor_id=a),
                lambda a: dict(COMMENT, repository_id=0, actor_id=a), by_hand):
        take, cancel = take_jwt(c, order, who, **run(who)), cancel_jwt(c, order, **run(MAINT))
        assert refused(oenv, take, None, NO_COMMAND)["kind"] == "take" and escrow_says(oenv, take, reserve_with(c, order)) == E_CLAIMS
        assert refused(oenv, cancel, None, NO_COMMAND)["kind"] == "cancel"
        assert escrow_says(oenv, cancel, lambda tok: pay.cancel_ix(c.payer.pubkey(), order, tok, c.key)) == E_CLAIMS
    assert (c.order(order).reserved_by, c.order(order).cancel_at) == (0, 0)
    assert go(oenv, order_pay_jwt(c, order, [(who, 10_000, Keypair().pubkey())], terms=_SECRET, file="attest.yml", repository_id=judge_repo))["ok"]
    assert refused(oenv, revert_jwt(c, order, repository_id=REPO), None, NO_JUDGE)["kind"] == "revert"
    r = go(oenv, revert_jwt(c, order, file="attest.yml", repository_id=judge_repo))
    assert r["ok"] and r["amount"] == P(8_200_000, 8_024_000) and c.order(order) is None, r


def test_an_order_is_reserved_then_cancelled_and_its_taker_gets_the_kill_fee(oenv):
    c, net = oenv
    taker, wallet = user(), Keypair().pubkey()
    n, order = ordered(oenv, 40 * USDC, options=pay.opts(reserve_days=7, kill_bps=1000), work=30 * 86_400)
    take = token(c, pay.take_audience(order, taker, 5), actor_id=taker)                       # a person reserves for himself
    net.spent()
    r = go(oenv, take)
    assert r == {"ok": True, "kind": "take", "sigs": r["sigs"], "order": str(order), "repo_id": REPO, "issue": n, "taker_id": taker, "days": 5,
                 "reserved_until": c.now() + 5 * 86_400}, r
    assert (net.txs, net.waits) == (2, 2) and c.order(order).reserved_by == taker
    assert go(oenv, take, None, c.fund()) == {**r, "sigs": r["sigs"][-1:], "already": True}
    other = user()
    assert refused(oenv, token(c, pay.take_audience(order, other, 5), actor_id=other), None, f"the order is reserved for GitHub user id {taker}")["kind"] == "take"
    for aud, want in ((pay.take_audience(Keypair().pubkey(), taker, 5), "no such order is in escrow"), (f"knos3:take:{order}:{taker}", "malformed audience or claims")):
        assert refused(oenv, token(c, aud, actor_id=taker), None, want)["kind"] == "take"
    # the commenter who funded it gives notice: seven days, or the order's own deadline if that is sooner
    cancel = token(c, pay.cancel_audience(order), actor_id=MAINT, **COMMENT)
    r = go(oenv, cancel)
    assert r == {"ok": True, "kind": "cancel", "sigs": r["sigs"], "order": str(order), "repo_id": REPO, "issue": n, "cancel_at": c.now(),
                 "deadline": c.now() + pay.NOTICE}, r
    assert go(oenv, cancel, None, c.fund()) == {**r, "sigs": r["sigs"][-1:], "already": True}
    c.warp(pay.TOKEN_AHEAD + 60)
    assert refused(oenv, token(c, pay.cancel_audience(order), actor_id=MAINT), None, "the order was cancelled already")
    late = token(c, pay.take_audience(order, other, 5), actor_id=other)
    assert refused(oenv, late, None, "a cancelled order takes no new reservation")["kind"] == "take" and escrow_says(oenv, late, reserve_with(c, order)) == E_STATE
    # past the notice the money goes back; the taker, who has bound a wallet, is sent the kill fee first (10% of 40)
    assert go(oenv, bind_jwt(c, taker, wallet))["ok"]
    cranker, bal0 = c.fund(), c.balance(pay.baltok_pda(c.bal))
    c.warp(pay.NOTICE + 1)
    assert relay.refund_orders_due(net, cranker, c.now()) and c.order(order) is None
    assert c.balance(pay.ata(wallet, c.usdc)) == 4 * USDC and c.balance(pay.baltok_pda(c.bal)) - bal0 >= 36 * USDC + order_fee(LIVE.v, 40 * USDC)


def test_a_holdback_waits_out_its_warranty_and_goes_to_the_payee_or_back_on_a_revert(oenv):
    c, net = oenv
    seller, wallet = user(), Keypair().pubkey()
    options = pay.opts(holdback_bps=2000, warranty_days=2)
    _n, kept = ordered(oenv, 50 * USDC, options=options)
    n2, undone = ordered(oenv, 50 * USDC, options=options)
    assert refused(oenv, order_pay_jwt(c, kept, [(user(), 10_000, None)]), None, "is never held")
    proof = order_pay_jwt(c, kept, [(seller, 10_000, wallet)])
    net.spent()
    r = go(oenv, proof)
    until = c.now() + 2 * 86_400
    assert r["ok"] and r["paid"] == [row(seller, 40 * USDC, wallet)] and (r["held_back"], r["warranty_until"]) == (10 * USDC, until), r
    assert (net.txs, net.waits) == (2, 2) and c.order(kept).state == "warranty" and c.held(kept) == 10 * USDC + P(250_000, 30_000)
    again = go(oenv, proof, None, c.fund())
    assert again["ok"] and again["already"] and again["paid"] == r["paid"], again
    assert refused(oenv, order_pay_jwt(c, kept, [(seller, 10_000, wallet)], pr=9), None, "what it holds back waits for its warranty")
    early = token(c, pay.revert_audience(undone, "a" * 40))                      # signed before the payment it would undo
    c.warp(5)
    assert go(oenv, order_pay_jwt(c, undone, [(seller, 10_000, wallet)], pr=8))["ok"]
    assert refused(oenv, early, None, "older than the payment")["kind"] == "revert"
    cranker = c.fund()
    assert relay.release_orders_due(net, cranker, c.now()) == []                # inside the warranty nothing is released
    # the change is reverted inside the warranty: the order's own repository says so, and everything it holds goes back
    c.warp(86_400)
    for aud, over, want in ((pay.revert_audience(undone, "a" * 40), by_hand(seller), "not from a judge this order takes"),
                            (pay.revert_audience(undone, "xyz"), {}, "malformed audience or claims"),
                            (pay.revert_audience(ordered(oenv)[1], "a" * 40), {}, "the order holds nothing back")):
        assert refused(oenv, token(c, aud, **over), None, want)["kind"] == "revert"
    bal0 = c.balance(pay.baltok_pda(c.bal))
    revert = token(c, pay.revert_audience(undone, "a" * 40))
    r = go(oenv, revert)
    assert r == {"ok": True, "kind": "revert", "sigs": r["sigs"], "order": str(undone), "head": "a" * 40, "repo_id": REPO, "issue": n2, "mint": str(c.usdc),
                 "amount": P(10_250_000, 10_030_000)}, r
    assert c.order(undone) is None and c.balance(pay.baltok_pda(c.bal)) - bal0 == P(10_250_000, 10_030_000)      # the holdback and the fee on it
    again = go(oenv, revert, None, c.fund())
    assert again["ok"] and again["already"] and again["amount"] == P(10_250_000, 10_030_000), again
    # the other order's warranty runs out with no revert: anyone releases the holdback to the wallet recorded at payment
    c.warp(86_400 + 1)
    assert refused(oenv, token(c, pay.revert_audience(kept, "a" * 40)), None, "the warranty ended")
    assert len(relay.release_orders_due(net, cranker, c.now())) == 1 and c.order(kept) is None
    assert c.balance(pay.ata(wallet, c.usdc)) == 40 * USDC + 40 * USDC + 10 * USDC
    # the releaser's tip is TIP, or all the fee the order still held when that is less (2.2: 0.03 of the 0.15 on 50.00 waited with the holdback)
    assert c.balance(pay.ata(cranker.pubkey(), c.usdc)) == P(pay.TIP, 30_000)
    assert relay.release_orders_due(net, cranker, c.now()) == []


def test_a_standing_order_pays_each_pull_request_once_and_the_markers_rent_comes_back(oenv):
    c, net = oenv
    n, order = ordered(oenv, 25 * USDC, options=pay.opts(flags=pay.F_STANDING, rate=10 * USDC))
    a, b, relayer = (user(), Keypair().pubkey()), (user(), Keypair().pubkey()), c.fund()
    first = order_pay_jwt(c, order, [(a[0], 10_000, a[1])], pr=11)
    r = go(oenv, first, None, relayer)
    assert r["ok"] and r["paid"] == [row(a[0], 10 * USDC, a[1])] and r["left"] == 15 * USDC and c.order(order).state == "open", r
    again = go(oenv, first, None, c.fund())
    assert again["ok"] and again["already"] and again["paid"] == r["paid"], again
    c.warp(pay.TOKEN_AHEAD + 60)        # (a token of the minutes just paid is taken for that payment's own)
    assert refused(oenv, order_pay_jwt(c, order, [(b[0], 10_000, b[1])], pr=11), None, "has paid pull request #11 already")
    r = go(oenv, order_pay_jwt(c, order, [(b[0], 10_000, b[1])], pr=12), None, relayer)
    assert r["ok"] and r["left"] == 5 * USDC and c.balance(pay.ata(b[1], c.usdc)) == 10 * USDC, r
    # less than one rate is left: the order's deadline is in the past, and the rest goes back at once
    assert refused(oenv, order_pay_jwt(c, order, [(a[0], 10_000, a[1])], pr=13), None, "the order's deadline has passed")
    marks = lambda who: net.program_accounts(pay.PAY_ID, P(pay.DONE_LEN_21, pay.DONE_LEN), {1: bytes(who.pubkey())})  # noqa: E731 - 65 bytes as 2.1 writes it, 73 as 2.2
    assert len(marks(relayer)) == 2 and relay.close_markers(net, relayer, c.now()) == []            # the order still stands: its markers stay
    assert relay.refund_orders_due(net, relayer, c.now()) and c.order(order) is None
    before = lamports(c, relayer)
    assert len(relay.close_markers(net, relayer, c.now())) == 1 and marks(relayer) == [] and lamports(c, relayer) > before     # both, in one transaction
    # a token's single-use marker (a fund token's, a 2.0 pay token's) is closed once no instruction takes that token any more
    used = lambda: net.program_accounts(pay.PAY_ID, pay.USED_LEN, {1: bytes(c.payer.pubkey())})  # noqa: E731
    ordered(oenv)
    fresh = sorted(str(a) for a, d in used() if pay.read_marker(d)[1] > c.now())
    relay.close_markers(net, c.payer, c.now())      # the markers of tokens long past go; one whose token could still be shown stays
    assert fresh and sorted(str(a) for a, _d in used()) == fresh
    c.warp(pay.USED_KEEP + 1)
    assert relay.close_markers(net, c.payer, c.now()) and used() == [] and relay.close_markers(net, c.payer, c.now()) == []


def test_an_organisations_member_binds_its_wallet_and_what_a_person_bound_stays_his(oenv):
    c, net = oenv
    org, member, wallet = user(), user(), Keypair().pubkey()

    def claim(to, **over) -> str:
        c.warp(1)
        return token(c, pay.org_bind_audience(to), **{"file": "claim.yml", "wf_repo": "drexthealpha/knos-oidc-rotate", "wf_sha": pay.IDS["claim_sha_org"],
                                                      "event_name": "workflow_dispatch", "actor_id": member, "repository_owner_id": org,
                                                      "repository": f"org{org}/knos-claim", "repository_id": 80_000_000 + org % 1_000_000, **over})
    assert relay.kind_of(pay.org_bind_audience(wallet)) == "bind"
    for over, want in ((dict(actor_id=org), "started by a member"), (dict(repository=f"org{org}/claims"), "started by a member"),
                       (dict(event_name="push"), "started by hand by a member"), (dict(wf_sha="d" * 40), "at its pinned commit"),
                       (dict(run_attempt=2), "not be a re-run")):
        assert refused(oenv, claim(wallet, **over), None, want)["kind"] == "bind"
    jwt = claim(wallet)
    net.spent()
    r = go(oenv, jwt)
    assert r == {"ok": True, "kind": "bind", "sigs": r["sigs"], "user_id": org, "wallet": str(wallet), "org": True, "by": member, "settled": []}, r
    assert (net.txs, net.waits) == (2, 2) and pay.read_bind(c.data(pay.bind_pda(org))).wallet == wallet
    n0 = net.txs
    again = go(oenv, jwt, None, c.fund())
    assert again["ok"] and again["already"] and net.txs == n0, again
    old = claim(Keypair().pubkey())
    assert go(oenv, claim(Keypair().pubkey()))["ok"]
    assert refused(oenv, old, None, "a newer claim has bound a wallet since this one")
    # a person bound his own wallet: someone he gave write access to his knos-claim does not rebind it
    person = user()
    assert go(oenv, bind_jwt(c, person, Keypair().pubkey()))["ok"]
    assert refused(oenv, claim(wallet, repository_owner_id=person, repository=f"user{person}/knos-claim"), None, "bound its wallet itself")


def test_a_key_of_any_issuer_is_registered_by_its_url_and_refreshed():
    """On a chain of its own. The rotate workflow, given an issuer's URL, attests a key it found in that issuer's key
    set; the token carries the hashes of the URL and of the key, and the URL comes beside it."""
    c = Chain()
    net = Net(c)
    url = "https://gitlab.example.com"
    n = modulus(_STRANGER)
    docs = {**JWKS, url: {"keys": [_jwk("their-1", n)]}}
    submit = lambda jwt, beside=url.encode(): relay.submit(net, c.payer, jwt, beside, docs, now=c.now())  # noqa: E731
    att = attestation(c, url, n)
    assert relay.kind_of(oidc.rotate_audience(url, n)) == "key"
    me = user()
    hand = dict(event_name="workflow_dispatch", actor_id=me, repository_owner_id=me, repository_id=user())
    n0 = net.txs
    for jwt, beside, want in ((att, None, "the issuer's URL did not come with its token"),
                              (att, b"https://evil.example.com", "is not the issuer this token names"),
                              (attestation(c, url, n, wf_sha="d" * 40), url.encode(), "only from the rotate workflow at its pinned commit"),
                              (attestation(c, url, n, **hand), url.encode(), "registered only on the attester's own run"),
                              (attestation(c, url, modulus(signing_key(4096))), url.encode(), "the issuer's key set has no key with that hash")):
        r = submit(jwt, beside)
        assert not r["ok"] and r["kind"] == "key" and want in r["why"] and net.txs == n0, r
    r = submit(att)
    key = oidc.key_pda(url, n)
    assert r == {"ok": True, "kind": "key", "sigs": r["sigs"], "key": str(key), "added": True, "refreshed": False, "issuer": url}, r
    k = oidc.read_key(c.data(key))
    assert (k.state, k.issuer, k.approved, k.issuer_hash) == (1, oidc.OTHER, False, oidc.issuer_hash(url)) and oidc.read_iss(c.data(oidc.iss_pda(url))) == url
    assert c.data(oidc.token_pda(c.payer.pubkey(), oidc.token_id(att))) is None                 # the attestation's account is closed behind it
    # the same key again changes nothing; two days on the attester's run refreshes it, and so does anyone's run by hand
    assert submit(attestation(c, url, n)) == {**r, "sigs": [], "added": False}
    for claims in ({}, hand):
        c.warp(2 * 86_400)
        r = submit(attestation(c, url, n, **claims))
        assert r["ok"] and r["refreshed"] and not r["added"] and oidc.read_key(c.data(key)).expires_at == c.now() + oidc.KEY_TTL, r


# -- the meter, and passkey wallets ---------------------------------------------------------------------------------------------
def test_an_evaluation_is_recorded_by_the_meter_once_and_what_it_would_refuse_costs_nothing():
    from _meter import BUYER, SELLER, Meter
    from knos.settle.v2 import meter
    c = Meter()
    net = Net(c)
    env = (c, net)
    mint = c.new_mint()
    _wallet, credits = c.open(mint, BUYER, 5 * USDC)
    c.set_used(BUYER, meter.FREE_PER_MONTH)                     # past the month's free evaluations: this one costs 0.05
    ev = lambda aud, **over: token(c, aud, **{"file": "attest.yml", "repository_owner_id": BUYER, **over})  # noqa: E731
    aud = c.aud("b" * 40, verdict=1, rate=2 * USDC)
    assert relay.kind_of(aud) == "eval" and relay.credits_for(net, BUYER) == [(credits, c.credits(credits), 5 * USDC)]
    jwt = ev(aud)
    net.spent()
    r = go(env, jwt)
    month = meter.yyyymm(c.now())
    assert r == {"ok": True, "kind": "eval", "sigs": r["sigs"], "buyer_id": BUYER, "seller_id": SELLER, "order": "a1" * 32, "artifact": "b" * 40, "milestone": 0,
                 "accepted": True, "rate": 2 * USDC, "fee": 50_000, "month": month}, r
    # two transactions; the relay made FEE_OWNER's token account on the way, and the fee went there from the credits
    assert (net.txs, net.waits) == (2, 2) and c.held(credits) == 5 * USDC - 50_000 and c.balance(pay.ata(meter.FEE_OWNER, mint)) == 50_000
    assert c.month() == meter.Statement(BUYER, SELLER, month, evaluations=1, accepted=1, rejected=0, value=2 * USDC, fees=50_000)
    # the same token, and another run's token for the same evaluation saying the opposite: counted already, the first verdict stands, no fee
    n0, sol = net.txs, lamports(c)
    for again in (jwt, ev(c.aud("b" * 40, verdict=0, rate=9 * USDC))):
        assert go(env, again) == {**r, "sigs": r["sigs"][-1:], "already": True}
    assert (net.txs, lamports(c)) == (n0, sol)
    for jwt, want in ((ev(c.aud("c" * 40), run_attempt=2), "only a run's first attempt is counted"),
                      (ev(c.aud("c" * 40), file="fund.yml"), "an evaluation is recorded from attest.yml or prove.yml"),
                      (ev(c.aud("c" * 40), repository_owner_id=999), "the run was not in a repository of the buyer its audience names"),
                      (ev(c.aud("c" * 40), wf_sha="d" * 40), "the buyer has no credits opened for these workflows at this commit"),
                      (ev(c.aud("c" * 40, buyer=31337), repository_owner_id=31337), "the buyer has no credits opened"),
                      (ev(c.aud("c" * 40), runner_environment="self-hosted"), "not from a GitHub-hosted runner"),
                      (ev("knosm:eval:1:2:zz:" + "c" * 40 + ":" + "00" * 32 + ":0:1:5", repository_owner_id=1), "malformed audience or claims")):
        assert refused(env, jwt, None, want)["kind"] == "eval"
    # credits that hold less than the fee are known from a read; a rejection is counted like an acceptance once they are there
    poor = user()
    _w, empty = c.open(mint, poor)
    c.set_used(poor, meter.FREE_PER_MONTH)
    short = ev(c.aud("d" * 40, verdict=0, buyer=poor), repository_owner_id=poor)
    assert refused(env, short, None, "the buyer's credits hold less than the fee of this evaluation")
    c.mint_to(mint, meter.crtok_pda(empty), 50_000)
    r = go(env, short)
    assert r["ok"] and r["accepted"] is False and r["fee"] == 50_000 and c.held(empty) == 0, r
    # knos_meter never calls the escrow: on a cluster whose escrow is still 2.0 (it refuses Version) an evaluation is
    # counted all the same, in legacy transactions, from the day the meter is deployed
    old = Old(net)
    assert relay.version(old, c.payer) == 0
    on_old = ev(c.aud("e" * 40, verdict=1, rate=3 * USDC))
    r = relay.submit(old, c.payer, on_old, None, JWKS, now=c.now())
    assert r["ok"] and r["kind"] == "eval" and r["accepted"] is True and r["rate"] == 3 * USDC and r["fee"] == 50_000, r
    assert c.month().evaluations == 2 and c.held(credits) == 5 * USDC - 2 * 50_000
    assert relay.submit(old, c.payer, on_old, None, JWKS, now=c.now())["already"]
    # a cluster without knos_meter: said from a read, before any fee
    class NoMeter(Old):
        def infos(self, addresses):
            return [None if a == meter.METER_ID else got for a, got in zip(addresses, net.infos(addresses))]
    n0, sol = net.txs, lamports(c)
    r = relay.submit(NoMeter(net), c.payer, ev(c.aud("f" * 40)), None, JWKS, now=c.now())
    assert r == {"ok": False, "kind": "eval", "why": f"knos_meter ({meter.METER_ID}) is not deployed on this cluster, so no evaluation can be counted here"}, r
    assert (net.txs, lamports(c)) == (n0, sol)
    # once the month is over and no token of it can come again, the relayer takes back the rent of the marks it paid for:
    # knos_meter's own instruction, sent whatever the escrow's version
    mine = meter.marks_of(net, c.payer.pubkey())
    assert len(mine) == 3 and relay.close_marks(net, c.payer, c.now()) == [] and relay.close_marks(old, c.payer, c.now()) == []
    c.warp(meter.close_after(c.now()) - c.now())
    before = lamports(c)
    assert len(relay.close_marks(old, c.payer, c.now())) == 1 and meter.marks_of(net, c.payer.pubkey()) == [] and lamports(c) > before


def test_a_passkey_withdrawal_request_is_simulated_then_sent_at_the_relays_cost():
    from test_passkey_chain import Passkey, client_data_json
    from knos.settle.v2 import passkey as pk
    c = Chain()
    c.svm.add_program_from_file(pk.PASSKEY_ID, str(FIX / "knos_passkey_v2_real.so"))
    net = Net(c)
    mint = c.new_mint()
    p = Passkey(11)                                             # a person paid at their passkey's address, who holds no SOL and never opened the wallet
    c.mint_to(mint, c.token_account(p.wallet, mint), 100 * USDC)
    owner = Keypair().pubkey()
    to = c.token_account(owner, mint)

    def ask(amount: int, nonce: int, signed: dict | None = None, by: Passkey | None = None) -> str:
        what = dict(wallet=p.wallet, mint=mint, to=to, amount=amount, nonce=nonce) | (signed or {})
        auth, cdj, sig = (by or p).get(pk.challenge(**what))
        return pk.request(p.key, mint, to, amount, nonce, auth, cdj, sig)
    first = ask(5 * USDC, 1)
    q = pk.read_request(first)
    assert (q.key, q.mint, q.to, q.amount, q.nonce, q.wallet) == (p.key, mint, to, 5 * USDC, 1, p.wallet) and pk.read_request(first.replace("+", "-").replace("/", "_")) == q
    net.spent()
    r = relay.withdraw(net, c.payer, first)
    assert r == {"ok": True, "kind": "withdraw", "sigs": r["sigs"], "wallet": str(p.wallet), "mint": str(mint), "to": str(to), "amount": 5 * USDC, "nonce": 1}, r
    # one transaction: Open (the wallet's account did not exist), the secp256r1 check, Withdraw
    assert (net.txs, net.waits) == (1, 1) and c.balance(to) == 5 * USDC and pk.read_wallet(c.data(p.wallet)).nonce == 1
    assert relay.withdraw(net, c.payer, ask(7 * USDC, 2))["ok"] and c.balance(to) == 12 * USDC      # the next one needs no Open
    # everything the chain would refuse is known beforehand, by reads or by simulating the very transaction: no fee
    n0, sol = net.txs, lamports(c)
    other = Passkey(12)
    for request, want in ((first, "the nonce is not the wallet's nonce plus one"),                                        # sent already
                          (ask(1000 * USDC, 3), "the wallet holds less of this mint than the request asks for"),
                          (ask(USDC, 3, signed=dict(amount=2 * USDC)), "the passkey signed for another withdrawal"),       # error 118, from the simulation
                          (ask(USDC, 3, by=other), "the passkey's signature does not verify"),
                          (pk.request(p.key, mint, Keypair().pubkey(), USDC, 3, b"a" * 37, client_data_json(bytes(32)), bytes([1]) * 64), "the destination is not a token account of this mint"),
                          (pk.request(p.key, Keypair().pubkey(), to, USDC, 3, b"a" * 37, client_data_json(bytes(32)), bytes([1]) * 64), "the mint this request names does not exist"),
                          ("bm90IGEgcmVxdWVzdA==", "not a withdrawal request"), ("%%%", "not a withdrawal request")):
        r = relay.withdraw(net, c.payer, request)
        assert not r["ok"] and r["kind"] == "withdraw" and want in r["why"], r
    assert (net.txs, lamports(c)) == (n0, sol)
    # a ledger that cannot simulate sends nothing
    from _pay2 import ChainLedger
    blind = ChainLedger(c)
    blind.simulate = None
    assert relay.withdraw(blind, c.payer, ask(USDC, 3))["why"] == "this relay's ledger cannot simulate, and a withdrawal is never sent unchecked"
    # a cluster without knos_passkey: said from a read, before any fee and before any simulation
    class NoPasskey(Old):
        def infos(self, addresses):
            return [None if a == pk.PASSKEY_ID else got for a, got in zip(addresses, net.infos(addresses))]
    bare = NoPasskey(net)
    r = relay.withdraw(bare, c.payer, ask(USDC, 3))
    assert r["why"] == f"knos_passkey ({pk.PASSKEY_ID}) is not deployed on this cluster, so no passkey wallet can withdraw here" and bare.asked == 0
    assert (net.txs, lamports(c)) == (n0, sol)
    # knos_passkey never calls the escrow: on a cluster whose escrow is still 2.0 (it refuses Version) the withdrawal is
    # simulated and sent the same way, the day the passkey program is deployed, not the day the escrow's upgrade executes
    old = Old(net)
    r = relay.withdraw(old, c.payer, ask(USDC, 3))
    assert r["ok"] and r["nonce"] == 3 and c.balance(to) == 13 * USDC and pk.read_wallet(c.data(p.wallet)).nonce == 3, r
    assert old.asked == 1 and relay.version(old, c.payer) == 0          # its one simulation was the withdrawal's own: the escrow's version is not asked
    assert relay.withdraw(net, c.payer, ask(USDC, 4))["ok"] and c.balance(to) == 14 * USDC


def test_program_ymls_gate_token_records_the_build_once_and_what_the_gate_would_refuse_costs_nothing(env):
    """The upgrade gate, end to end as the release uses it: program.yml's gate job has GitHub sign
    gate:<program>:<executable hash> and posts it as `knos-gate: <token>`; the worker finds that comment, and this
    relay has knos-oidc verify the token and upgrade_gate write its record, which `deploy_v2.sh --propose` waits for."""
    import hashlib

    import yaml

    from knos.proof import ghrelay
    from knos.settle.v2 import gate
    c, net = env
    c.svm.add_program_from_file(gate.GATE_ID, str(FIX / "upgrade_gate_v2_real.so"))
    elf = b"\x7fELF" + hashlib.sha256(b"the 2.1 build").digest() * 40
    h, commit = gate.executable_hash(elf + bytes(512)), "7" * 40        # trailing zeros do not count: a buffer and a file hash alike

    def jwt(program=pay.PAY_ID, executable=h, aud=None, **over) -> str:
        c.warp(1)
        claims = dict(file="program.yml", wf_repo="drexthealpha/Knos", wf_sha=commit, sha=commit, repository_id=gate.KNOS_REPO_ID,
                      repository="drexthealpha/Knos", ref="refs/heads/main", event_name="push", run_id=4242)
        return token(c, aud or gate.audience(program, executable), **{**claims, **over})
    # everything upgrade_gate asks is asked here first, with reads alone
    other = hashlib.sha256(b"x").digest()
    for bad, want in ((jwt(repository_id=gate.KNOS_REPO_ID + 1), "only on a run of Knos's own program.yml"), (jwt(file="ci.yml"), "Knos's own program.yml"),
                      (jwt(wf_repo="mallory/Knos"), "Knos's own program.yml"), (jwt(runner_environment="self-hosted"), "GitHub-hosted runner"),
                      (jwt(ref="refs/heads/feature"), "a commit of main or of a release tag"), (jwt(ref="refs/pull/7/merge"), "release tag"),
                      (jwt(wf_sha="8" * 40), "the workflow file of that same commit"), (jwt(sha="9" * 39 + "G"), "program.yml"),
                      (jwt(aud=f"gate:{pay.PAY_ID}"), "malformed audience or claims"), (jwt(aud=f"gate:{pay.PAY_ID}:{h.hex().upper()}"), "malformed"),
                      (jwt(aud=f"gate:knos_pay:{h.hex()}"), "malformed"), (jwt(aud=f"gate:{pay.PAY_ID}:{h.hex()}:x"), "malformed")):
        assert refused(env, bad, None, want)["kind"] == "gate"
    # the comment the workflow posts is one the worker reads, under the marker of its kind
    job = yaml.safe_load((ROOT / ".github" / "workflows" / "program.yml").read_text(encoding="utf-8"))["jobs"]["gate"]
    [fmt] = re.findall(r"printf '(knos-gate: %s[^']*)'", job["steps"][-1]["run"])
    good = jwt()
    body = fmt.replace("\\n", "\n").replace("%s", good)
    assert body.rstrip("\n") == ghrelay.token_comment("gate", good)
    [found] = ghrelay.tokens([{"body": body, "issue_url": "https://api.github.com/repos/drexthealpha/Knos/issues/9", "user": {"login": "github-actions[bot]"}}])
    assert tuple(found) == ("gate", 9, good, "github-actions[bot]") and ghrelay.misposted("gate", good) is None
    assert "carried under its own marker" in ghrelay.misposted("verify", good) and "its audience is a gate token's" in ghrelay.misposted("proof", good)
    net.spent()
    r = ghrelay.relay_one(net, c.payer, "gate", good, submit=lambda ledger, payer, t: relay.submit(ledger, payer, t, None, JWKS, now=c.now()))
    at = gate.record_pda(pay.PAY_ID, h)
    assert r == {"ok": True, "kind": "gate", "program": str(pay.PAY_ID), "hash": h.hex(), "record": str(at), "sigs": r["sigs"], "commit": commit,
                 "run_id": 4242, "note": r["note"]} and net.spent()[:2] == (2, 2)
    assert r["note"] == (f"Recorded at the upgrade gate: GitHub's runner built the executable {h.hex()} for program {pay.PAY_ID} from commit {commit} "
                         f"(run 4242). Record {at}.")
    rec = gate.read_record(c.data(at))
    assert (rec.program, rec.executable, rec.sha, rec.run_id) == (pay.PAY_ID, h, commit, 4242)
    assert max(net.units[-1:]) < relay._LAST_STEP[2048][0] + 75 * len(good) + relay._CU["gate"]         # what the plan allowed the last transaction
    # what `knos status` and the proposal read is this record: the buffer's build is vouched for
    assert gate.executable_hash(elf) == h and "ungated" not in r["note"]
    # carried again, or by a later run that built the same bytes (a release tag after main): done, and no fee
    for again in (good, jwt(ref="refs/tags/v0.3.13", sha="6" * 40, wf_sha="6" * 40, run_id=4243)):
        before, n0 = lamports(c), net.txs
        twice = go(env, again)
        assert twice["ok"] and twice["already"] and (twice["commit"], twice["run_id"]) == (commit, 4242) and (lamports(c), net.txs) == (before, n0)
    # the record is of one program: the same bytes for another program are another record
    assert go(env, jwt(program=oidc.OIDC_ID, ref="refs/tags/v0.3.13"))["record"] == str(gate.record_pda(oidc.OIDC_ID, h))
    assert c.data(gate.record_pda(pay.PAY_ID, other)) is None
    # a cluster without the gate: said before any fee
    class NoGate:
        def __getattr__(self, name):
            return getattr(net, name)

        def infos(self, addresses):
            return [None if a == gate.GATE_ID else got for a, got in zip(addresses, net.infos(addresses))]
    n0 = net.txs
    assert "is not deployed on this cluster" in relay.submit(NoGate(), c.payer, jwt(executable=other), None, JWKS, now=c.now())["why"] and net.txs == n0


def test_every_audience_goes_through_one_table():
    assert relay.KINDS["gate:"].name == "gate" and relay.KINDS["gate:"].since == 0 and not relay.KINDS["gate:"].github
    assert {prefix: (k.name, k.since) for prefix, k in relay.KINDS.items() if prefix != "gate:"} == {
        "knos2:fund:": ("fund", 0), "knos2:pay:": ("pay", 0), "knos2:bind:": ("bind", 0), "knos-oidc:key:": ("key", 0), "knos-oidc:ikey:": ("key", 1),
        "knos3:fund:": ("fund", 1), "knos3:pay:": ("pay", 1), "knos3:auto:": ("pay", 1), "knos3:rule:": ("rule", 1), "knos3:take:": ("take", 1), "knos3:cancel:": ("cancel", 1),
        "knos3:revert:": ("revert", 1), "knos3:bind:": ("bind", 1), "knosm:eval:": ("eval", 0),
        "knosm:batch:": ("batch", 0), "knosm:claim:": ("claim", 0)}     # the meter is a program of its own: no 2.1 escrow
    assert relay.kind_of("knos3:pay:x") == "pay" and relay.kind_of("knos3:take:x") == "take" and relay.kind_of("knos:fund:1") is None
    assert [prefix for prefix, k in relay.KINDS.items() if k.first] == ["knos-oidc:key:"]         # the first deployment is handed GitHub's and GitLab's keys, nothing else


# -- what a token costs: transactions, waits for confirmation, compute units -------------------------------------------------------
def cost(env, send) -> tuple[int, int, list[int], int, int]:
    """(transactions, waits, transactions per wait, most compute units in one transaction, compute units in all) of
    what `send` relays."""
    _c, net = env
    net.spent()
    net.units.clear()
    send()
    return net.txs, net.waits, list(net.shape), max(net.units), sum(net.units)


def test_transactions_waits_and_compute_units_of_every_path(monkeypatch):
    """A relay's time goes into waiting for confirmations, each after the one before. This relay sends a token's
    chunks side by side and puts the last verification step, the escrow's instruction and the Close into one
    transaction. Every path is counted here, so a change that costs a transaction or a wait fails; the compute units
    are LiteSVM's. Run with -s to see the table.
    The paths are relayed on a chain of their own from fixed inputs (the payer, the mint, the owner, the ids, the
    wallets and the added key), so they cost the same in every run: each address the programs derive costs 1,500
    compute units for every bump it tries, and with new keys, and ids that depend on which tests ran before on the
    same worker, the largest transaction of the faucet path ranged from about 1,084,000 to 1,104,600 from one run
    to the next."""
    env = _setup(Chain(), fixed=True)
    c, net = env
    monkeypatch.setitem(globals(), "_COUNT", [7_000, 6_000_000])     # issue() and user() from the same ids every run
    ok = lambda r: r["ok"] or pytest.fail(str(r))  # noqa: E731
    rows: dict[str, tuple] = {}
    org, repo, n_real, n_faucet, n_held = user(), user(), issue(), issue(), issue()
    payee, waiting, wallet = user(), user(), seeded(4).pubkey()
    rows["fund from a Balance"] = cost(env, lambda: ok(go(env, fund_jwt(c, n_real), TERMS)))
    rows["fund, the faucet opened on the way"] = cost(env, lambda: ok(go(env, faucet_jwt(c, n_faucet, org, repo), TERMS)))
    rows["pay to the address in the proof"] = cost(env, lambda: ok(go(env, pay_jwt(c, repo, n_faucet, payee, wallet))))
    rows["pay held (no wallet known)"] = cost(env, lambda: ok(go(env, pay_jwt(c, REPO, n_real, waiting))))
    rows["bind (nothing held)"] = cost(env, lambda: ok(go(env, bind_jwt(c, payee, wallet))))
    rows["bind, then settle the held job"] = cost(env, lambda: ok(go(env, bind_jwt(c, waiting, seeded(5).pubkey()))))
    funded(env, n_held)
    rows["pay to a bound wallet"] = cost(env, lambda: ok(go(env, pay_jwt(c, REPO, n_held, payee))))
    # a key GitHub has added, named by the rotate workflow: registered, and two days later refreshed
    new = SeedKey(2048, "the key GitHub added")
    jwks = {oidc.GITHUB: {"keys": [*JWKS[oidc.GITHUB]["keys"], _jwk("added", modulus(new))]}}
    key = lambda: relay.submit(net, c.payer, attestation(c, oidc.GITHUB, modulus(new)), None, jwks, now=c.now())  # noqa: E731
    rows["key registered"] = cost(env, lambda: ok(key()))
    c.warp(2 * 86_400)
    rows["key refreshed"] = cost(env, lambda: ok(key()))
    # what needs no token
    n_late, _job = funded(env, work=60)
    funded(env, n_held)
    assert go(env, pay_jwt(c, REPO, n_held, user()))["paid"][0]["to"] is None
    late = user()
    assert go(env, pay_jwt(c, REPO, funded(env)[0], late))["paid"][0]["to"] is None
    tok = c.verify(bind_jwt(c, late, seeded(6).pubkey()), oidc.GITHUB, c.github)
    assert c.send([pay.bind_ix(c.payer.pubkey(), tok, c.key, late)]), c.err
    c.warp(61)
    rows["refund of an unproven bounty"] = cost(env, lambda: relay.refund_due(net, c.payer, c.now()))
    rows["settle of a held bounty"] = cost(env, lambda: relay.settle_held(net, c.payer))
    other = seeded(7)
    c.svm.airdrop(other.pubkey(), 100 * 10 ** 9)
    rows["verify only (a 1,7xx-byte token)"] = cost(env, lambda: ok(relay.verify_only(net, other, token(c, "sts.amazonaws.com"), JWKS, now=c.now())))
    print()
    for path, (txs, waits, shape, most, total) in rows.items():
        print(f"{path:38} {txs} transactions  {waits} waits  per wait {shape!s:15}  compute units: {total:9,} in all, {most:9,} in the largest")
    two = (2, 2, [1, 1])        # Write + first Step, then last Step + the escrow's instructions + Close: v1 transactions
    assert {path: row[:3] for path, row in rows.items()} == {
        "fund from a Balance": two, "fund, the faucet opened on the way": two, "pay to the address in the proof": two, "pay held (no wallet known)": two,
        "bind (nothing held)": two, "bind, then settle the held job": two, "pay to a bound wallet": two, "key registered": two, "key refreshed": two,
        "refund of an unproven bounty": (1, 1, [1]), "settle of a held bounty": (1, 1, [1]), "verify only (a 1,7xx-byte token)": two}, rows
    # the last Step and the escrow together, with room to spare under the 1,400,000 a transaction may use
    assert all(row[3] < chain.MAX_COMPUTE_UNITS - 300_000 for row in rows.values()), rows


def test_without_v1_transactions_a_token_takes_four_legacy_ones_and_a_cluster_that_refuses_v1_is_asked_once(env, monkeypatch):
    """The path of 0.3.12, kept: for the 2.0 escrow (nothing new is sent to it), for a ledger that sends no v1
    transaction, and for a cluster whose validators or endpoint refuse one. That refusal is taken once: the token
    then goes the old way in the same call, and so does every token after it."""
    c, net = env
    ok = lambda r: r["ok"] or pytest.fail(str(r))  # noqa: E731
    org, repo, n, payee, wallet = user(), user(), issue(), user(), Keypair().pubkey()

    class Refuses(Flaky):
        refused = 0

        def send(self, ixs, payer, signers=None, v1=False):
            if v1:
                self.refused += 1
                raise chain.RpcError("failed to deserialize solana_transaction::versioned::VersionedTransaction: unsupported transaction version")
            return super().send(ixs, payer, signers)
    old = Refuses(net)
    old.takes_v1 = True
    net.spent()
    ok(relay.submit(old, c.payer, faucet_jwt(c, n, org, repo), TERMS, JWKS, now=c.now()))
    assert (old.refused, old.takes_v1, net.txs, net.v1s) == (1, False, 4, 0)
    net.spent()
    ok(relay.submit(old, c.payer, pay_jwt(c, repo, n, payee, wallet), None, JWKS, now=c.now()))
    assert (old.refused, net.txs, net.v1s) == (1, 4, 0) and c.balance(pay.ata(wallet, pay.faucet_mint())) == P(4_875_000, 4_950_000)
    assert chain.v1_refused(chain.RpcError("Transaction version (1) is not supported by the requesting client")) and not chain.v1_refused(chain.RpcError("custom program error: 0x54"))
    # a ledger that sends none, and the 2.0 escrow: four transactions and three waits each, as before
    monkeypatch.setattr(net, "takes_v1", False)
    rows = {"fund": cost(env, lambda: ok(go(env, fund_jwt(c, issue()), TERMS))),
            "pay": cost(env, lambda: ok(go(env, pay_jwt(c, REPO, funded(env)[0], user(), wallet)))),
            "bind": cost(env, lambda: ok(go(env, bind_jwt(c, payee, wallet)))),
            "verify only": cost(env, lambda: ok(relay.verify_only(net, c.fund(), token(c, "sts.amazonaws.com"), JWKS, now=c.now())))}
    assert {k: row[:3] for k, row in rows.items()} == {"fund": (4, 3, [2, 1, 1]), "pay": (8, 6, [2, 1, 1, 2, 1, 1]), "bind": (4, 3, [2, 1, 1]),
                                                       "verify only": (3, 3, [1, 1, 1])}, rows
    monkeypatch.setattr(net, "takes_v1", True)
    monkeypatch.setattr(relay, "_VERSION", {("litesvm", pay.PAY_ID): 0})
    assert cost(env, lambda: ok(go(env, bind_jwt(c, user(), wallet))))[:3] == (4, 3, [2, 1, 1]) and net.v1s == 0


def test_the_first_deployments_relay_takes_a_transaction_and_a_wait_for_every_step():
    """The same three tokens through knos.settle.relay on its own programs: every chunk, step, instruction and close
    in a transaction of its own, each waited for. What the second deployment's relay is measured against."""
    from _settle import Chain as Chain1
    from _settle import ChainLedger as Ledger1
    from _settle import github_claims as claims1
    c1 = Chain1()
    ledger1 = Ledger1(c1)
    assert c1.send([pay1.init_faucet_ix(c1.payer.pubkey())]), c1.err
    jwks1 = {oidc1.GITHUB: {"keys": [_jwk("k0", modulus(signing_key()))]}}
    payee, wallet = user(), Keypair().pubkey()

    def token1(aud: str, file: str, **over) -> str:
        claims = claims1(aud=aud, iat=c1.now(), nbf=c1.now() - 600, exp=c1.now() + 300, jti=f"f{ledger1.n}", repository_id=str(REPO),
                         repository_owner_id=str(OWNER), job_workflow_ref=f"{WF_REPO}/.github/workflows/{file}@refs/tags/v0.3.10", job_workflow_sha=WF_SHA)
        claims.update(over)
        return sign_jwt(signing_key(), claims, header={"typ": "JWT", "alg": "RS256", "kid": "k0"})
    assert relay1.submit(ledger1, c1.payer, token1(pay1.fund_audience(1, 5 * USDC), "fund.yml"), jwks1, now=c1.now())["ok"]    # registers the key on the way
    c1.warp(61)
    first = {}
    for kind, jwt in (("fund", token1(pay1.fund_audience(2, 5 * USDC), "fund.yml")), ("pay", token1(pay1.pay_audience(REPO, 2, payee, "a" * 40), "prove.yml")),
                      ("claim", token1(pay1.claim_audience(wallet), "claim.yml", event_name="workflow_dispatch", actor_id=str(payee), repository_owner_id=str(payee)))):
        n0 = ledger1.n
        assert relay1.submit(ledger1, c1.payer, jwt, jwks1, now=c1.now())["ok"]
        first[kind] = (ledger1.n - n0, len(jwt))
    print()
    for kind, (txs, size) in first.items():
        print(f"first deployment   {kind:5}  token {size} bytes  {txs} transactions  {txs} waits")
    assert {k: v[0] for k, v in first.items()} == {"fund": 7, "pay": 7, "claim": 6}


def test_how_long_a_token_each_write_carries(env, monkeypatch):
    """A v1 transaction carries a token up to about 3,700 bytes whole beside its first Step; a longer one has its head
    written first, in Writes side by side. In legacy transactions the head goes in Writes side by side and the tail
    beside the first Step: a token up to 1,756 bytes takes one Write before that Step, the longest (8,192 bytes) nine."""
    c, net = env
    me, tid = c.payer.pubkey(), bytes(32)
    from _settle import sized_jwt

    def rooms(v1: bool) -> tuple[int, int]:
        limit = relay.ROOM_V1 if v1 else relay.ROOM
        return (200 + limit - chain.tx_size([relay._write_ix(me, tid, 2000, 0, bytes(200))], me, v1),
                200 + limit - chain.tx_size([relay._write_ix(me, tid, 2000, 0, bytes(200)), oidc.step_ix(me, tid, c.key, 8)], me, v1))
    alone, beside = rooms(False)
    assert (alone, beside) == (914, 842)
    whole, with_step = rooms(True)
    print(f"\na v1 transaction carries {whole} bytes of a token alone, {with_step} beside the first Step")
    assert 3600 < with_step < whole < 4000      # (41 bytes more on a cluster, which needs no compute budget instruction)
    for v1, cases in ((True, ((with_step, [1, 1]), (with_step + 2, [1, 1, 1]), (oidc.MAX_JWT, [2, 1, 1]))),
                      (False, ((alone + beside, [1, 1, 1]), (alone + beside + 2, [2, 1, 1]), (oidc.MAX_JWT, [9, 1, 1])))):
        monkeypatch.setattr(net, "takes_v1", v1)
        for size, shape in cases:
            jwt = sized_jwt(signing_key(), github_claims(aud="x", iat=c.now(), exp=c.now() + 300, jti=f"size{size}{v1}", groups_direct=["g"]), size)
            net.spent()
            net.sizes.clear()
            assert relay.verify_only(net, c.fund(), jwt, JWKS, now=c.now())["ok"] and net.shape == shape, (len(jwt), net.shape)
            assert max(net.sizes) <= (relay.ROOM_V1 if v1 else relay.ROOM)


def test_the_harness_ledger_has_what_a_relay_and_a_settlement_use():
    """tests/_pay2.ChainLedger, the plain LiteSVM ledger other tests take: the relay runs on it, and a job's terms are
    read back from it as from a cluster."""
    from _pay2 import ChainLedger
    c = Chain()
    ledger = ChainLedger(c)
    assert c.send([pay.init_faucet_ix(c.payer.pubkey())]), c.err
    org, repo, payee, wallet = user(), user(), user(), Keypair().pubkey()
    r = relay.submit(ledger, c.payer, faucet_jwt(c, 7, org, repo), TERMS, JWKS, now=c.now())
    job = pay.job_pda(repo, 7, pay.faucet_balance_pda(org))
    assert r["ok"] and r["job"] == str(job) and ledger.n == 4, r
    assert ledger.log_of(job, "knos2:terms ") == "knos2:terms " + TERMS.decode() and ledger.log_of(job, "knos2:paid") is None
    assert ledger.log_of(job, "knos2:terms ", lambda line: False) is None and ledger.log_of(Keypair().pubkey(), "knos2:terms ") is None
    assert ledger.log_of(job, "knos2:terms ", by=pay.PAY_ID) == "knos2:terms " + TERMS.decode() and ledger.log_of(job, "knos2:terms ", by=pay.TOKEN) is None
    assert relay.submit(ledger, c.payer, pay_jwt(c, repo, 7, payee, wallet), None, JWKS)["ok"] and c.balance(pay.ata(wallet, pay.faucet_mint())) == P(4_875_000, 4_950_000)
    assert ledger.log_of(pay.rep_pda(payee), "knos2:paid ").startswith(f"knos2:paid repo={repo} issue=7 payee={payee} amount={P(4875000, 4950000)} fee={P(125000, 50000)} to={wallet}")
    assert ledger.infos([pay.faucet_mint(), Keypair().pubkey()]) == [(pay.TOKEN, c.data(pay.faucet_mint())), None]
    assert ledger.program_accounts(oidc.OIDC_ID, None, {50: bytes(c.payer.pubkey())}) == []      # the token accounts were closed behind the tokens


# -- knos.chain.Ledger, with a cluster's JSON-RPC faked where it is called ---------------------------------------------------
class Rpc:
    """What a cluster would answer knos.chain.call: transactions are kept, confirmed on the second time of asking,
    and refused (at preflight) or failed (on chain) when the test says so."""

    def __init__(self):
        self.calls: list[tuple[str, list]] = []
        self.sent: dict[str, object] = {}               # signature -> the transaction
        self.refuse: set[int] = set()                   # lamports of the transfers preflight refuses
        self.fail: set[int] = set()                     # and of those that fail on chain
        self.asked: list[list[str]] = []                # each getSignatureStatuses request
        self.rows: dict[str | None, list[dict]] = {}    # getSignaturesForAddress pages, by their `before`
        self.logs: dict[str, list[str]] = {}
        self.accounts: dict[str, tuple[str, bytes]] = {}

    def __call__(self, url, method, params, timeout=10.0):
        self.calls.append((method, params))
        return getattr(self, method)(*params)

    def count(self, method: str) -> int:
        return sum(1 for m, _p in self.calls if m == method)

    def getLatestBlockhash(self, opts):
        return {"value": {"blockhash": "4vJ9JU1bJJE96FWSJKvHsmmFADCg4gpZQff4P3bkLKi"}}

    def simulateTransaction(self, raw, opts):
        self.simulated = (base64.b64decode(raw), opts)
        return {"value": {"err": self.sim_err, "logs": ["Program log: knos2:version 1"]}}

    sim_err = None

    def sendTransaction(self, raw, opts):
        from solders.transaction import Transaction, VersionedTransaction
        tx = (VersionedTransaction if base64.b64decode(raw)[0] == 0x81 else Transaction).from_bytes(base64.b64decode(raw))
        lamports = int.from_bytes(bytes(tx.message.instructions[-1].data)[4:12], "little")
        if lamports in self.refuse:
            raise chain.RpcError("Transaction simulation failed: custom program error: 0x5b", {"logs": ["Program log: no"]})
        self.sent[str(tx.signatures[0])] = tx
        return str(tx.signatures[0])

    def getSignatureStatuses(self, sigs):
        self.asked.append(list(sigs))
        if len(self.asked) % 2:                         # not there yet, the first time
            return {"value": [None] * len(sigs)}
        lamports = lambda s: int.from_bytes(bytes(self.sent[s].message.instructions[-1].data)[4:12], "little")  # noqa: E731
        return {"value": [{"confirmationStatus": "confirmed", "err": {"InstructionError": [1, {"Custom": 91}]} if lamports(s) in self.fail else None}
                          for s in sigs]}

    def getSignaturesForAddress(self, address, opts):
        return self.rows.get(opts.get("before"), [])[:opts["limit"]]

    def getTransaction(self, sig, opts):
        return {"meta": {"logMessages": self.logs[sig]}} if sig in self.logs else None

    def getAccountInfo(self, address, opts):
        got = self.accounts.get(address)
        return {"value": {"owner": got[0], "data": [base64.b64encode(got[1]).decode(), "base64"]} if got else None}

    def getMultipleAccounts(self, addresses, opts):
        return {"value": [self.getAccountInfo(a, opts)["value"] for a in addresses]}

    def getProgramAccounts(self, program, opts):
        return [{"pubkey": str(pay.auth_pda()), "account": {"data": [base64.b64encode(b"job").decode(), "base64"]}}]


@pytest.fixture
def rpc(monkeypatch):
    fake = Rpc()
    monkeypatch.setattr(chain, "call", fake)
    monkeypatch.setattr(chain.time, "sleep", lambda s: None)
    return fake, chain.Ledger("https://rpc.example")


def _transfers(payer: Keypair, *lamports: int) -> list[list[Instruction]]:
    from solders.system_program import TransferParams, transfer
    return [[transfer(TransferParams(from_pubkey=payer.pubkey(), to_pubkey=pay.FEE_OWNER, lamports=n))] for n in lamports]


def test_send_all_signs_over_one_blockhash_sends_without_waiting_and_waits_for_all_at_once(rpc):
    fake, ledger = rpc
    payer = Keypair()
    sigs = ledger.send_all(_transfers(payer, 1, 2, 3), payer)
    assert [fake.count(m) for m in ("getLatestBlockhash", "sendTransaction")] == [1, 3]
    assert [int.from_bytes(bytes(fake.sent[s].message.instructions[-1].data)[4:12], "little") for s in sigs] == [1, 2, 3]       # in the order given
    assert fake.asked == [sigs, sigs]                           # every signature in one request, until all are confirmed
    for tx in fake.sent.values():                               # each is what `send` would have signed: a compute-unit limit first
        assert tx.message.instructions[0].program_id_index == tx.message.account_keys.index(chain.COMPUTE_BUDGET) and len(bytes(tx)) <= chain.MAX_TX_BYTES
        assert len(bytes(tx)) == chain.tx_size(_transfers(payer, 1)[0], payer.pubkey())
    # one transaction: `send`, as ever
    fake.calls.clear()
    assert len(ledger.send_all(_transfers(payer, 4), payer)) == 1 and fake.count("sendTransaction") == 1
    assert ledger.send_all([], payer) == []


def test_a_v1_transaction_holds_4096_bytes_and_carries_its_limits_in_the_message(rpc, monkeypatch):
    """SIMD-0385, as devnet runs it since Agave 4.2: first byte 0x81, no compute budget instruction (the limits are in
    the message; unset, a cluster loads nothing and refuses), the same signing and waiting as a legacy transaction."""
    fake, ledger = rpc
    monkeypatch.setattr(chain, "V1_BUDGET_IX", False)           # as a cluster takes it
    payer, other = Keypair(), Keypair()
    big = Instruction(pay.PAY_ID, bytes(3000), [AccountMeta(payer.pubkey(), True, True), AccountMeta(other.pubkey(), True, False)])
    assert chain.tx_size([big], payer.pubkey()) > chain.MAX_TX_BYTES and chain.tx_size([big], payer.pubkey(), v1=True) <= chain.MAX_V1_BYTES
    sig = ledger.send([big], payer, [other], v1=True)
    tx = fake.sent[sig]
    raw = bytes(tx)
    assert raw[0] == 0x81 and 3000 < len(raw) == chain.tx_size([big], payer.pubkey(), v1=True) and len(tx.signatures) == 2
    assert (tx.message.config.compute_unit_limit, tx.message.config.loaded_accounts_data_size_limit) == (chain.MAX_COMPUTE_UNITS, chain.V1_LOADED)
    assert [ix.program_id_index for ix in tx.message.instructions] == [tx.message.account_keys.index(pay.PAY_ID)]      # no compute budget instruction
    # a limit the caller asks for with a compute budget instruction becomes the message's
    from solders.compute_budget import set_compute_unit_limit
    m = chain.message_v1([set_compute_unit_limit(300_000), big], payer.pubkey())
    assert m.config.compute_unit_limit == 300_000 and len(m.instructions) == 1
    assert len(ledger.send_all([[big], [Instruction(pay.PAY_ID, b"x", [])]], payer, [other], v1=True)) == 2
    # asked, not sent: what the transaction would log, or the programs' own refusal; no signature is checked and no fee paid
    assert ledger.simulate([pay.version_ix()], payer) == ["Program log: knos2:version 1"]
    assert fake.simulated[1] == {"encoding": "base64", "sigVerify": False, "replaceRecentBlockhash": True, "commitment": "confirmed"} and fake.count("sendTransaction") == 3
    fake.sim_err = {"InstructionError": [1, "InvalidInstructionData"]}
    with pytest.raises(chain.RpcError, match="InvalidInstructionData"):
        ledger.simulate([pay.version_ix()], payer)
    monkey = {("https://rpc.example", pay.PAY_ID)}
    relay._VERSION.pop(("https://rpc.example", pay.PAY_ID), None)
    assert relay.version(ledger, payer) == 0 and set(relay._VERSION) >= monkey      # the deployed 2.0 escrow answers exactly this
    relay._VERSION.pop(("https://rpc.example", pay.PAY_ID), None)


def test_send_all_waits_for_the_rest_before_it_raises_what_one_of_them_met(rpc):
    fake, ledger = rpc
    payer = Keypair()
    fake.refuse = {2}                                           # preflight refuses the second: it never reaches the chain
    with pytest.raises(chain.RpcError, match="0x5b.*Program log: no"):
        ledger.send_all(_transfers(payer, 1, 2, 3), payer)
    assert len(fake.sent) == 2 and sorted(fake.asked[-1]) == sorted(fake.sent)      # the other two were waited for all the same
    fake.refuse, fake.fail = set(), {5}                         # one fails on chain
    with pytest.raises(chain.RpcError, match="transaction failed: .*'Custom': 91"):
        ledger.send_all(_transfers(payer, 4, 5, 6), payer)
    assert len(fake.sent) == 5


def test_a_ledger_reads_the_clock_accounts_and_logs_in_few_requests(rpc):
    fake, ledger = rpc
    fake.accounts[str(chain.CLOCK)] = ("Sysvar1111111111111111111111111111111111111", bytes(32) + (1_790_000_123).to_bytes(8, "little"))
    assert ledger.now() == 1_790_000_123 and fake.count("getAccountInfo") == 1      # the clock the programs see, in one read
    keys = [Keypair().pubkey() for _ in range(150)]
    fake.accounts[str(keys[149])] = (str(pay.PAY_ID), b"x")
    got = ledger.infos(keys)
    assert got[:149] == [None] * 149 and got[149] == (pay.PAY_ID, b"x") and fake.count("getMultipleAccounts") == 2
    assert ledger.accounts(keys[148:]) == [None, b"x"] and ledger.owner(keys[149]) == pay.PAY_ID and ledger.owner(keys[0]) is None
    assert ledger.program_accounts(pay.PAY_ID, 320, {8: b"\x01\x02"}) == [(pay.auth_pda(), b"job")]
    assert fake.calls[-1][1][1]["filters"] == [{"dataSize": 320}, {"memcmp": {"offset": 8, "bytes": "5T"}}]
    assert ledger.program_accounts(pay.PAY_ID, None, {}) and fake.calls[-1][1][1]["filters"] == []
    # a line a program logged, found by an address: its transactions newest first, the failed ones passed over, a
    # hundred rows a request, and the next request from the last row whether it failed or not
    job = Keypair().pubkey()
    fake.rows[None] = [{"signature": f"new{i}", "err": {"x": 1} if i % 2 else None} for i in range(100)]
    fake.rows["new99"] = [{"signature": "paid", "err": None}, {"signature": "failed funding", "err": {"x": 1}}, {"signature": "funding", "err": None}]
    fake.logs = {"funding": ["Program 5y7i invoke [1]", "Program log: knos2:funded repo=1 issue=2", 'Program log: knos2:terms {"v":1}', "Program 5y7i success"],
                 "failed funding": ['Program log: knos2:terms {"v":0}'], "paid": ["Program log: knos2:paid repo=1 issue=2"]}
    assert list(ledger.history(job))[-2:] == ["paid", "funding"] and len(list(ledger.history(job))) == 52
    assert ledger.log_of(job, "knos2:terms ") == 'knos2:terms {"v":1}' and ledger.log_of(job, "knos2:paid") == "knos2:paid repo=1 issue=2"
    assert ledger.log_of(job, "knos2:held") is None and ledger.log_of(job, "knos2:terms ", lambda line: "v\":2" in line) is None
    assert ledger.signatures(job, 5) == ["new0", "new2", "new4"] and ledger.last_signature(job) == "new0" and ledger.recent(job, 2) == [("new0", None)]
    # who logged a line is read from the runtime's own lines, which no program can write
    logs = [f"Program {pay.PAY_ID} invoke [1]", "Program log: knos2:funded repo=1", f"Program {pay.TOKEN} invoke [2]", "Program log: Instruction: Transfer",
            f"Program {pay.TOKEN} consumed 4645 of 100 compute units", f"Program {pay.TOKEN} success", "Program log: knos2:terms {}", f"Program {pay.PAY_ID} success",
            f"Program {pay.TOKEN_2022} invoke [1]", f"Program log: knos2:paid repo=1\nProgram {pay.PAY_ID} invoke [1]", "Program log: knos2:paid repo=2",
            f"Program {pay.TOKEN_2022} failed: custom program error: 0x1", "Program log: nobody is running"]
    assert chain.said(logs, pay.PAY_ID) == ["knos2:funded repo=1", "knos2:terms {}"] and chain.said(logs, pay.TOKEN) == ["Instruction: Transfer"]
    assert len(chain.said(logs)) == 6 and chain.said(logs, pay.TOKEN_2022)[1] == "knos2:paid repo=2"
    # a history longer than five hundred rows is not read to its end
    fake.rows = {None: [{"signature": "same", "err": None}] * 100, "same": [{"signature": "same", "err": None}] * 100}
    assert len(list(ledger.history(job))) == 500


def test_a_rate_limited_request_is_waited_out_and_asked_again(monkeypatch):
    import io
    import urllib.error
    waits, answers = [], [urllib.error.HTTPError("u", 429, "Too Many Requests", {"Retry-After": "7"}, None),
                          urllib.error.HTTPError("u", 429, "Too Many Requests", {}, None), io.BytesIO(b'{"result": 42}')]

    def urlopen(req, timeout=None):
        got = answers.pop(0)
        if isinstance(got, Exception):
            raise got
        return got
    monkeypatch.setattr(chain.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(chain.time, "sleep", waits.append)
    assert chain.call("https://rpc.example", "getSlot", []) == 42 and waits == [7.0, 2]       # the endpoint's own figure, else a doubling wait
    answers[:] = [io.BytesIO(b'{"error": {"message": "boom", "data": {"logs": ["a", "b"]}}}')]
    with pytest.raises(chain.RpcError, match="boom \\| a \\| b"):
        chain.call("https://rpc.example", "sendTransaction", [])
