"""Test harness for the second deployment of knos-oidc (programs-v2/knos_oidc): its test build
(tests/fixtures/knos_oidc_v2_test.so) inside LiteSVM, with the seed-derived signing keys of tests/_settle.py, the
test guardian, attestations from the rotate workflow, and a clock that can be moved. Tests only.

The test build trusts what the real one trusts and, besides: the two seed keys as genesis keys, the rotate workflow at
commit "1" * 40, the harness's repository (owner 424242, repository 987654321) as an attester, and the guardian whose
seed is [7; 32] (pins.rs, the `testkeys` feature).
"""
from __future__ import annotations

from solders.compute_budget import set_compute_unit_limit
from solders.keypair import Keypair
from solders.litesvm import LiteSVM
from solders.message import MessageV0
from solders.pubkey import Pubkey
from solders.signature import Signature
from solders.transaction import VersionedTransaction

from _settle import FIX, NOW, github_claims, modulus, sign_jwt, signing_key

from knos.settle.v2 import oidc

GH, GL = oidc.GITHUB, oidc.GITLAB
ROTATE_REF = "drexthealpha/knos-oidc-rotate/.github/workflows/rotate.yml@refs/heads/main"
TEST_ROTATE_SHA = "1" * 40
GUARDIAN = Keypair.from_seed(bytes([7]) * 32)     # pins.rs TEST_GUARDIAN
HOP = oidc.KEY_TTL - 86_400                       # how far `travel` moves the clock between two refreshes


def attest_claims(issuer: int, n: int, **over) -> dict:
    """What GitHub signs for a scheduled run of the rotate workflow that found this key in the issuer's key set."""
    c = github_claims(aud=oidc.rotate_audience(issuer, n), job_workflow_ref=ROTATE_REF, job_workflow_sha=TEST_ROTATE_SHA,
                      event_name="schedule")
    c.update(over)
    return c


class Chain2:
    def __init__(self, oidc_build: str = "knos_oidc_v2_test.so", programs: dict[Pubkey, str] | None = None):
        """knos-oidc v2 in LiteSVM, and any other programs ({program id: file in tests/fixtures, or a path})."""
        self.svm = LiteSVM()
        self.svm.add_program_from_file(oidc.OIDC_ID, str(FIX / oidc_build))
        for program_id, build in (programs or {}).items():
            self.svm.add_program_from_file(program_id, str(FIX / build))
        c = self.svm.get_clock(); c.unix_timestamp = NOW; self.svm.set_clock(c)
        self.payer = self.fund()
        self.guardian = GUARDIAN
        self.svm.airdrop(GUARDIAN.pubkey(), 10 ** 9)
        self.cu: dict[str, list[int]] = {}
        self.err = None
        self.used = 0                                  # compute units of the last transaction, failed or not
        self.keys: set[tuple[int, int]] = set()        # (issuer, modulus) of every key registered here
        self._n = 0

    def fund(self, sol: int = 100) -> Keypair:
        k = Keypair(); self.svm.airdrop(k.pubkey(), sol * 10 ** 9); return k

    def warp(self, seconds: int) -> None:
        """Moves the clock, and nothing else: keys expire if this passes their expiry."""
        c = self.svm.get_clock(); c.unix_timestamp += seconds; self.svm.set_clock(c)

    def travel(self, seconds: int) -> None:
        """Moves the clock forward as a live cluster would see it: the rotate workflow keeps attesting, so every key
        registered here (and not revoked) is refreshed before each hop and at the end, and tokens still verify
        afterwards. Use `warp` to let keys expire."""
        while seconds > 0:
            self.refresh_all()
            hop = min(seconds, HOP)
            self.warp(hop)
            seconds -= hop
        self.refresh_all()

    def refresh_all(self) -> None:
        for issuer, n in sorted(self.keys, key=str):
            if not self.key(issuer, n).revoked:
                assert self.refresh(issuer, n), self.err

    def now(self) -> int:
        return int(self.svm.get_clock().unix_timestamp)

    def send(self, ixs, payer: Keypair | None = None, signers=(), tag: str | None = None) -> bool:
        payer = payer or self.payer
        everyone = {bytes(k.pubkey()): k for k in [payer, *signers]}
        msg = MessageV0.try_compile(payer.pubkey(), [set_compute_unit_limit(1_400_000), *ixs], [], self.svm.latest_blockhash())
        return self._sent(self.svm.send_transaction(VersionedTransaction(msg, list(everyone.values()))), tag)

    def send_unsigned(self, ixs, tag: str | None = None) -> bool:
        """Runs a transaction with signature checking off, so every account its instructions mark as a signer counts
        as one. This stands in for a multisig vault (the real guardian): it signs by a cross-program call from the
        multisig program, never with a key, and the program under test sees the same thing either way."""
        msg = MessageV0.try_compile(self.payer.pubkey(), [set_compute_unit_limit(1_400_000), *ixs], [], self.svm.latest_blockhash())
        self.svm.with_sigverify(False)
        try:
            r = self.svm.send_transaction(VersionedTransaction.populate(msg, [Signature.default()] * msg.header.num_required_signatures))
        finally:
            self.svm.with_sigverify(True)
        return self._sent(r, tag)

    def _sent(self, r, tag: str | None) -> bool:
        self.svm.expire_blockhash()
        ok = "Failed" not in type(r).__name__
        self.err = None if ok else str(r.err() if callable(getattr(r, "err", None)) else r.err)
        cu = (r if ok else r.meta()).compute_units_consumed
        self.used = cu() if callable(cu) else cu
        if ok and tag:
            self.cu.setdefault(tag, []).append(self.used)
        return ok

    def data(self, address) -> bytes | None:
        a = self.svm.get_account(address)
        return bytes(a.data) if a is not None and a.lamports > 0 else None

    # -- tokens -------------------------------------------------------------------------------------------------
    def write(self, jwt: str, payer: Keypair | None = None) -> bytes:
        p = payer or self.payer
        tid = oidc.token_id(jwt)
        for ix in oidc.write_ixs(p.pubkey(), tid, jwt):
            assert self.send([ix], p), self.err
        return tid

    def verify(self, jwt: str, issuer: int, n: int, payer: Keypair | None = None, tag: str | None = None, plan: list[int] | None = None,
               registrant: Pubkey | None = None):
        """Writes the token and runs every step. Returns the token account's address, or None if a step refused.
        `registrant`: the key is the private one that wallet registered for the issuer's URL."""
        p = payer or self.payer
        tid = oidc.token_id(jwt)
        have = oidc.read_token(self.data(oidc.token_pda(p.pubkey(), tid)))
        if have is not None:                      # the same token again: reuse a verified account, restart any other
            if have.verified:
                return oidc.token_pda(p.pubkey(), tid)
            assert self.send([oidc.close_ix(p.pubkey(), tid)], p), self.err
        self.write(jwt, p)
        bits = n.bit_length()
        for i, sq in enumerate(plan or oidc.step_plan(bits)):
            if not self.send([oidc.step_ix(p.pubkey(), tid, oidc.key_pda(issuer, n, registrant=registrant), sq)], p, tag=tag and f"{tag}_{bits}_step{i + 1}"):
                why = self.err
                self.send([oidc.close_ix(p.pubkey(), tid)], p)
                self.err = why
                return None
        return oidc.token_pda(p.pubkey(), tid)

    def gh(self, aud: str, key=None, **over) -> Pubkey | None:
        """A verified GitHub token account for this audience, signed by the seed key (or `key`), issued now."""
        now = self.now()
        self._n += 1
        claims = github_claims(aud=aud, iat=now, nbf=now - 600, exp=now + 300, jti=f"t{self._n}")
        claims.update(over)
        k = key or signing_key()
        return self.verify(sign_jwt(k, claims), GH, modulus(k))

    # -- keys ---------------------------------------------------------------------------------------------------
    def key(self, issuer: int, n: int) -> oidc.Key | None:
        return oidc.read_key(self.data(oidc.key_pda(issuer, n)))

    def attest(self, issuer: int, n: int, by=None, **over) -> Pubkey | None:
        """A verified token account in which GitHub names this key: the rotate workflow's run, issued now. Signed by
        the 2048-bit seed key, which is registered here first if the chain does not have it, or by `by` (another
        key of GitHub's that this chain already has)."""
        signer = modulus(by or signing_key())
        if self.key(GH, signer) is None:
            assert self.register(GH, signer), self.err
        now = self.now()
        self._n += 1
        claims = attest_claims(issuer, n, iat=now, nbf=now - 600, exp=now + 300, jti=f"a{self._n}")
        claims.update(over)
        return self.verify(sign_jwt(by or signing_key(), claims), GH, signer)

    def key_of(self, attest: Pubkey | None) -> Pubkey | None:
        """The key account an attestation is passed with: the one its token account names. For an account that is
        not a token (the tests pass some), the seed key's account, so that the attestation is what gets refused."""
        if attest is None:
            return None
        t = oidc.read_token(self.data(attest))
        return t.key if t is not None and t.verified else oidc.key_pda(GH, modulus(signing_key()))

    def register_ix(self, issuer: int | str, n: int, attest: Pubkey | None = None, payer: Keypair | None = None):
        """RegisterKey for GitHub (0) or GitLab (1); RegisterIssuerKey for an issuer named by its URL."""
        if isinstance(issuer, str):
            return oidc.register_issuer_key_ix((payer or self.payer).pubkey(), issuer, n, attest, self.key_of(attest))
        return oidc.register_key_ix((payer or self.payer).pubkey(), issuer, n, attest, self.key_of(attest))

    def refresh_ix(self, issuer: int, n: int, attest: Pubkey, payer: Keypair | None = None):
        return oidc.refresh_ix((payer or self.payer).pubkey(), issuer, n, attest, self.key_of(attest))

    def register(self, issuer: int, n: int, attest: Pubkey | None = None, payer: Keypair | None = None) -> bool:
        """RegisterKey, then KeyParams. A genesis key is usable after this; an attested one still waits (see admit)."""
        p = payer or self.payer
        ok = (self.send([self.register_ix(issuer, n, attest, p)], p)
              and self.send([oidc.key_params_ix(p.pubkey(), issuer, n)], p, tag=f"key_params_{n.bit_length()}"))
        if ok:
            self.keys.add((issuer, n))
        return ok

    def refresh(self, issuer: int, n: int, attest: Pubkey | None = None, payer: Keypair | None = None) -> bool:
        p = payer or self.payer
        attest = attest or self.attest(issuer, n)
        return attest is not None and self.send([self.refresh_ix(issuer, n, attest, p)], p, tag="refresh")

    def register_private(self, wallet: Keypair, url: str, n: int) -> bool:
        """RegisterPrivateKey by `wallet`, then KeyParams: usable when this returns True."""
        return (self.send([oidc.register_private_key_ix(wallet.pubkey(), url, n)], wallet)
                and self.send([oidc.key_params_ix(wallet.pubkey(), url, n, registrant=wallet.pubkey())], wallet))

    def approve(self, issuer: int, n: int, guardian: Keypair | None = None) -> bool:
        g = guardian or self.guardian
        return self.send([oidc.approve_ix(g.pubkey(), issuer, n)], signers=[g], tag="approve")

    def revoke(self, issuer: int, n: int, guardian: Keypair | None = None) -> bool:
        g = guardian or self.guardian
        return self.send([oidc.revoke_ix(g.pubkey(), issuer, n)], signers=[g], tag="revoke")

    def admit(self, issuer: int, n: int) -> bool:
        """The whole attested path for a key that is not a genesis key: GitHub's signature names it, it is registered,
        the guardian approves it, and its day of waiting passes. The key is usable when this returns True."""
        tok = self.attest(issuer, n)
        if tok is None or not self.register(issuer, n, tok) or not self.approve(issuer, n):
            return False
        self.travel(oidc.KEY_DELAY)
        return oidc.key_usable(self.key(issuer, n), self.now())[0]
