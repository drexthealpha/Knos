"""Test harness for the second deployment's escrow (programs-v2/knos_pay) inside LiteSVM, beside the second
deployment's verifier. The builds are tests/fixtures/knos_pay_v2_test.so and knos_oidc_v2_test.so (`--features
testkeys`: they trust the seed-derived test keys of tests/_settle.py, a test claim workflow pin, a test rotate
workflow pin and a test guardian). Tokens are verified with the second deployment's client, knos.settle.v2.oidc.
Tests only.

A verifier key stops verifying 30 days after it was registered or last refreshed, and the escrow then refuses the
tokens it verified. So a test that moves the clock further than that does it on a chain of its own and needs no token
afterwards, or refreshes the key (`refresh`). A test that revokes a key has a chain of its own too: that is for ever."""
from __future__ import annotations

import re
from pathlib import Path

from solders.compute_budget import set_compute_unit_limit
from solders.instruction import AccountMeta, Instruction
from solders.keypair import Keypair
from solders.litesvm import LiteSVM
from solders.message import MessageV0
from solders.pubkey import Pubkey
from solders.system_program import CreateAccountParams, create_account
from solders.transaction import VersionedTransaction

from _oidc2 import attest_claims
from _settle import NOW, modulus, sign_jwt, signing_key
from _settle import github_claims as _claims

from knos.chain import said
from knos.settle.v2 import oidc, pay

FIX = Path(__file__).parent / "fixtures"
GUARDIAN = Keypair.from_seed(bytes([7]) * 32)     # the test guardian of a testkeys build: the escrow's and the verifier's
USDC_KEY = Keypair.from_seed(bytes([8]) * 32)     # the mint a testkeys build counts as Circle's USDC in the record (TEST_USDC)
PLAN_SIGNER = Keypair.from_seed(bytes([6]) * 32)  # may sign SetPlan in a testkeys build, beside FEE_OWNER
WF_REPO, WF_SHA = "drexthealpha/Knos", "c" * 40   # the repository and commit whose fund.yml and prove.yml the tests' jobs pin
TEST_CLAIM_SHA = "2" * 40                         # the claim workflow commit a testkeys build accepts beside the real pin
_IDS = ("repository_id", "repository_owner_id", "actor_id", "run_number", "run_id", "run_attempt")


def github_claims(**over) -> dict:
    """The claims of a GitHub Actions token as GitHub writes them: ids are strings, times are numbers."""
    return _claims(**{k: str(v) if k in _IDS else v for k, v in over.items()})


def _opt(key: Pubkey | None) -> bytes:
    return b"\x01" + bytes(key) if key is not None else b"\x00"


def _key(key: Pubkey | None) -> bytes:
    return bytes(key) if key is not None else bytes(32)


class Chain:
    def __init__(self, pay_build: str = "knos_pay_v2_test.so", oidc_build: str = "knos_oidc_v2_test.so"):
        for build, crate in ((oidc_build, "knos_oidc"), (pay_build, "knos_pay")):
            assert (FIX / build).is_file(), f"tests/fixtures/{build} is missing: build it in programs-v2/{crate} with cargo build-sbf --features testkeys"
        assert oidc.OIDC_ID == pay.OIDC_ID          # the verifier whose token accounts the escrow accepts
        self.svm = LiteSVM()
        self.svm.add_program_from_file(oidc.OIDC_ID, str(FIX / oidc_build))
        self.svm.add_program_from_file(pay.PAY_ID, str(FIX / pay_build))
        c = self.svm.get_clock(); c.unix_timestamp = NOW; self.svm.set_clock(c)
        self.payer = self.fund()
        self.cu: dict[str, list[int]] = {}
        self.err = None
        self.logs: list[str] = []
        self._n = 0
        # GitHub's signing key (the 2048-bit seed key), and its account: every instruction that takes a token takes it
        self.github = modulus(signing_key())
        self.key = oidc.key_pda(oidc.GITHUB, self.github)
        assert self.register(oidc.GITHUB, self.github), self.err

    def fund(self, sol: int = 100) -> Keypair:
        k = Keypair(); self.svm.airdrop(k.pubkey(), sol * 10 ** 9); return k

    def warp(self, seconds: int) -> None:
        c = self.svm.get_clock(); c.unix_timestamp += seconds; self.svm.set_clock(c)

    def now(self) -> int:
        return int(self.svm.get_clock().unix_timestamp)

    def marked(self, ix):
        """An instruction of the escrow that takes a token, with that token's marker in its place when the
        builder was not given one: what a relay does with the JWT it holds, done here from the token account the
        instruction names. (A token account that holds no token gets some marker: the program refuses the token first.)"""
        # Pay (5) and FundOrderBalance (16) are always built with their marker
        at = pay.TOKEN_AT.get(ix.data[0]) if ix.program_id == pay.PAY_ID and ix.data and ix.data[0] not in (5, 16) else None
        if at is None or len(ix.accounts) <= at:
            return ix
        try:
            marker = pay.used_pda(self.data(ix.accounts[at].pubkey))
        except Exception:
            marker = pay.used_pda(bytes(32))
        return ix if any(a.pubkey == marker for a in ix.accounts) else pay.marked(ix, marker)

    def send(self, ixs, payer: Keypair | None = None, signers=(), tag: str | None = None, mark: bool = True) -> bool:
        payer = payer or self.payer
        ixs = [self.marked(ix) for ix in ixs] if mark else list(ixs)
        everyone = {bytes(k.pubkey()): k for k in [payer, *signers]}
        msg = MessageV0.try_compile(payer.pubkey(), [set_compute_unit_limit(1_400_000), *ixs], [], self.svm.latest_blockhash())
        tx = VersionedTransaction(msg, list(everyone.values()))
        self.size = len(bytes(tx))                # a cluster takes at most 1232 bytes
        r = self.svm.send_transaction(tx)
        self.svm.expire_blockhash()
        ok = "Failed" not in type(r).__name__
        meta = r if ok else r.meta()
        self.err = None if ok else str(r.err())
        self.logs = list(meta.logs())
        # what the escrow's own instructions used, the programs they called included (not the compute budget instruction)
        self.last_cu = sum(int(m.group(1)) for m in (re.match(rf"Program {pay.PAY_ID} consumed (\d+) of", line) for line in self.logs) if m)
        if ok and tag:
            self.cu.setdefault(tag, []).append(self.last_cu)
        return ok

    def said(self, prefix: str) -> list[str]:
        """The program's log lines of the last transaction that start with `prefix` (a `knos2:` line)."""
        return [line.split("Program log: ", 1)[1] for line in self.logs if line.startswith("Program log: " + prefix)]

    def data(self, address) -> bytes | None:
        a = self.svm.get_account(address)
        return bytes(a.data) if a is not None and a.lamports > 0 else None

    def lamports(self, address) -> int:
        return self.svm.get_balance(address) or 0

    # -- the verifier ------------------------------------------------------------------------------------------------
    def register(self, issuer: int, n: int, payer: Keypair | None = None) -> bool:
        """RegisterKey and KeyParams for one of the test build's two genesis keys: usable at once, for 30 days."""
        p = payer or self.payer
        return (self.send([oidc.register_key_ix(p.pubkey(), issuer, n)], p)
                and self.send([oidc.key_params_ix(p.pubkey(), issuer, n)], p))

    def revoke(self, issuer: int, n: int) -> bool:
        """The guardian ends a key, for ever."""
        return self.send([oidc.revoke_ix(GUARDIAN.pubkey(), issuer, n)], signers=[GUARDIAN])

    def attest(self, issuer: int, n: int, by=None) -> Pubkey | None:
        """A verified token in which GitHub names this key: a run of the pinned rotate workflow, issued now. Signed
        by the seed key, or by `by` (what `second_key` returned)."""
        now = self.now()
        self._n += 1
        claims = attest_claims(issuer, n, iat=now, nbf=now - 600, exp=now + 300, jti=f"a{self._n}")
        k = by or signing_key()
        return self.verify(sign_jwt(k, claims), oidc.GITHUB, modulus(k))

    def second_key(self):
        """Admits a second key of GitHub's the attested way: the first names it, the guardian approves it, and it
        verifies from a day after this call, for 30 days. An attestation counts only while the key that verified it
        is usable, so a key that has expired is refreshed by an attestation verified under one that has not."""
        from cryptography.hazmat.primitives.asymmetric import rsa
        k = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        n, p = modulus(k), self.payer.pubkey()
        tok = self.attest(oidc.GITHUB, n)
        assert tok is not None and self.send([oidc.register_key_ix(p, oidc.GITHUB, n, tok, self.key_of(tok))]), self.err
        assert self.send([oidc.key_params_ix(p, oidc.GITHUB, n)]) and self.send([oidc.approve_ix(GUARDIAN.pubkey(), oidc.GITHUB, n)], signers=[GUARDIAN]), self.err
        return k

    def refresh(self, issuer: int, n: int, attest: Pubkey) -> bool:
        """The key lives 30 days from now. `attest`: what `attest` returned, while GitHub's key could still verify it."""
        return self.send([oidc.refresh_ix(self.payer.pubkey(), issuer, n, attest, self.key_of(attest))])

    def key_of(self, token: Pubkey) -> Pubkey:
        """The key account a token account names: the one a relayer passes with it."""
        return oidc.read_token(self.data(token)).key

    def write(self, jwt: str, payer: Keypair | None = None) -> bytes:
        p = payer or self.payer
        tid = oidc.token_id(jwt)
        for ix in oidc.write_ixs(p.pubkey(), tid, jwt):
            assert self.send([ix], p), self.err
        return tid

    def verify(self, jwt: str, issuer: int, n: int, payer: Keypair | None = None) -> Pubkey | None:
        """Writes the token and runs every step. Returns the token account's address, or None if a step refused."""
        p = payer or self.payer
        tid = oidc.token_id(jwt)
        have = oidc.read_token(self.data(oidc.token_pda(p.pubkey(), tid)))
        if have is not None:                      # the same token again: reuse a verified account, restart any other
            if have.verified:
                return oidc.token_pda(p.pubkey(), tid)
            assert self.send([oidc.close_ix(p.pubkey(), tid)], p), self.err
        self.write(jwt, p)
        for sq in oidc.step_plan(n.bit_length()):
            if not self.send([oidc.step_ix(p.pubkey(), tid, oidc.key_pda(issuer, n), sq)], p):
                return None
        return oidc.token_pda(p.pubkey(), tid)

    def gh(self, aud: str, file: str = "prove.yml", wf_repo: str = WF_REPO, wf_sha: str = WF_SHA, payer: Keypair | None = None, **over) -> Pubkey | None:
        """A verified GitHub token account for this audience, from <wf_repo>/.github/workflows/<file> at wf_sha, issued now."""
        now = self.now()
        self._n += 1
        claims = dict(aud=aud, iat=now, nbf=now - 600, exp=now + 300, jti=f"t{self._n}",
                      job_workflow_ref=f"{wf_repo}/.github/workflows/{file}@refs/tags/v0.3.12", job_workflow_sha=wf_sha)
        claims.update(over)
        return self.verify(sign_jwt(signing_key(), github_claims(**claims)), oidc.GITHUB, self.github, payer)

    # -- SPL Token and Token-2022 ------------------------------------------------------------------------------------
    def new_mint(self, decimals: int = 6, keypair: Keypair | None = None) -> Pubkey:
        """An SPL Token mint; its mint authority is the chain's payer. With `keypair=USDC_KEY` it is the stand-in for
        Circle's USDC that a test build's record counts as real money; any other mint is counted as a test."""
        return self._mint(pay.TOKEN, 82, [], decimals, None, keypair)

    def new_mint22(self, *, decimals: int = 6, fee: tuple[int, int] | None = None, confidential: bool = False, permanent_delegate: Pubkey | None = None,
                   hook: tuple[Pubkey | None, Pubkey | None] | None = None, non_transferable: bool = False, default_state: int | None = None,
                   close_authority: bool = False, pausable: bool = False) -> Pubkey:
        """A Token-2022 mint with the extensions asked for. fee: (basis points, maximum fee); hook: (authority, program);
        default_state: 1 initialized, 2 frozen. Its mint, freeze, fee and hook authorities are the chain's payer."""
        me, mint22 = self.payer.pubkey(), lambda data: (lambda m: Instruction(pay.TOKEN_2022, data, [AccountMeta(m, False, True)]))  # noqa: E731
        ext: list[tuple[int, object]] = []      # (value length, instruction builder)
        if fee is not None:
            ext.append((108, mint22(bytes([26, 0]) + _opt(me) + _opt(me) + fee[0].to_bytes(2, "little") + fee[1].to_bytes(8, "little"))))
        if confidential:
            ext.append((65, mint22(bytes([27, 0]) + bytes(me) + b"\x01" + bytes(32))))
            if fee is not None:                 # Token-2022 requires the confidential fee config beside the two
                ext.append((129, mint22(bytes([37, 0]) + bytes(me) + bytes(Keypair().pubkey()))))
        if default_state is not None:
            ext.append((1, mint22(bytes([28, 0, default_state]))))
        if non_transferable:
            ext.append((0, mint22(bytes([32]))))
        if permanent_delegate is not None:
            ext.append((32, mint22(bytes([35]) + bytes(permanent_delegate))))
        if hook is not None:
            ext.append((64, mint22(bytes([36, 0]) + _key(hook[0]) + _key(hook[1]))))
        if close_authority:
            ext.append((32, mint22(bytes([25]) + _opt(me))))
        if pausable:
            ext.append((33, mint22(bytes([44, 0]) + bytes(me))))
        space = 166 + sum(4 + n for n, _ in ext) if ext else 82
        return self._mint(pay.TOKEN_2022, space + (2 if space == 355 else 0), [b for _, b in ext], decimals, me)

    def _mint(self, program: Pubkey, space: int, extensions, decimals: int, freeze: Pubkey | None, keypair: Keypair | None = None) -> Pubkey:
        m, me = keypair or Keypair(), self.payer.pubkey()
        ixs = [create_account(CreateAccountParams(from_pubkey=me, to_pubkey=m.pubkey(), lamports=self.svm.minimum_balance_for_rent_exemption(space),
                                                  space=space, owner=program)),
               *(build(m.pubkey()) for build in extensions),
               Instruction(program, bytes([20, decimals]) + bytes(me) + _opt(freeze), [AccountMeta(m.pubkey(), False, True)])]
        assert self.send(ixs, signers=[m]), self.err
        return m.pubkey()

    def set_fee22(self, mint: Pubkey, bps: int, maximum: int) -> None:
        """Schedules a new transfer fee on a Token-2022 mint (it takes effect two epochs later)."""
        ix = Instruction(pay.TOKEN_2022, bytes([26, 5]) + bps.to_bytes(2, "little") + maximum.to_bytes(8, "little"),
                         [AccountMeta(mint, False, True), AccountMeta(self.payer.pubkey(), True, False)])
        assert self.send([ix]), self.err

    def token_program(self, mint: Pubkey) -> Pubkey:
        return self.svm.get_account(mint).owner

    def token_account(self, owner: Pubkey, mint: Pubkey) -> Pubkey:
        """The owner's associated token account of the mint, created if needed."""
        tp = self.token_program(mint)
        assert self.send([pay.create_ata_ix(self.payer.pubkey(), owner, mint, tp)]), self.err
        return pay.ata(owner, mint, tp)

    def mint_to(self, mint: Pubkey, account: Pubkey, amount: int) -> None:
        ix = Instruction(self.token_program(mint), b"\x07" + amount.to_bytes(8, "little"),
                         [AccountMeta(mint, False, True), AccountMeta(account, False, True), AccountMeta(self.payer.pubkey(), True, False)])
        assert self.send([ix]), self.err

    def wallet(self, mint: Pubkey, amount: int = 0, sol: int = 10) -> tuple[Keypair, Pubkey]:
        """A new wallet with SOL and a token account of the mint holding `amount`."""
        k = self.fund(sol)
        t = self.token_account(k.pubkey(), mint)
        if amount:
            self.mint_to(mint, t, amount)
        return k, t

    def balance(self, account: Pubkey) -> int:
        d = self.data(account)
        return int.from_bytes(d[64:72], "little") if d and len(d) >= 165 else 0


class ChainLedger:
    """The Chain behind the interface a relay and a settlement use, as knos.chain.Ledger has it: send(ixs, payer,
    signers), send_all(groups, payer), simulate(ixs, payer), account(address), infos(addresses), now(), program_accounts(program, size,
    {offset: bytes}) and log_of(address, marker)."""
    def __init__(self, chain: Chain):
        self.chain = chain
        self.n = 0
        self.said: dict[Pubkey, list[list[str]]] = {}      # address -> the log of each transaction that named it, oldest first

    def send(self, ixs, payer, signers=None) -> str:
        ixs = list(ixs)
        if not self.chain.send(ixs, payer, signers or (), mark=False):        # a relay's own instructions, as it built them
            raise RuntimeError(self.chain.err)
        self.n += 1
        for key in {payer.pubkey(), *(ix.program_id for ix in ixs), *(a.pubkey for ix in ixs for a in ix.accounts)}:
            self.said.setdefault(key, []).append(self.chain.logs)
        return f"local{self.n}"

    def send_all(self, groups, payer, signers=None) -> list[str]:
        return [self.send(ixs, payer, signers) for ixs in groups]

    def simulate(self, ixs, payer, signers=None) -> list[str]:
        """As knos.chain.Ledger.simulate: the log the transaction would leave, with nothing sent."""
        everyone = {bytes(k.pubkey()): k for k in [payer, *(signers or [])]}
        msg = MessageV0.try_compile(payer.pubkey(), [set_compute_unit_limit(1_400_000), *ixs], [], self.chain.svm.latest_blockhash())
        r = self.chain.svm.simulate_transaction(VersionedTransaction(msg, list(everyone.values())))
        if "Failed" in type(r).__name__:
            raise RuntimeError(f"transaction failed: {r.err()}")
        return list(r.meta().logs())

    def account(self, address):
        return self.chain.data(address)

    def infos(self, addresses):
        got = [self.chain.svm.get_account(a) for a in addresses]
        return [(a.owner, bytes(a.data)) if a is not None and a.lamports > 0 else None for a in got]

    def now(self) -> int:
        return self.chain.now()

    def program_accounts(self, program, size: int | None = None, memcmp: dict[int, bytes] | None = None):
        out = []
        for addr, acc in self.chain.svm.get_program_accounts(program):
            d = bytes(acc.data)
            if acc.lamports > 0 and (size is None or len(d) == size) and all(d[o:o + len(b)] == b for o, b in (memcmp or {}).items()):
                out.append((addr, d))
        return out

    def log_of(self, address, marker: str, check=None, by=None) -> str | None:
        """As knos.chain.Ledger.log_of: the newest line a program (`by`, when given) logged that starts with `marker`,
        among the transactions that named `address`."""
        for logs in reversed(self.said.get(address, [])):
            for line in said(logs, by):
                if line.startswith(marker) and (check is None or check(line)):
                    return line
        return None
