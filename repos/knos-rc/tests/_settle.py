"""Test harness for the settlement programs: knos-oidc and knos-pay (the test builds in tests/fixtures) inside
LiteSVM, the seed-derived test signing keys, and a token mint. Tests only."""
from __future__ import annotations

import base64
import json
from pathlib import Path

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from solders.compute_budget import set_compute_unit_limit
from solders.keypair import Keypair
from solders.litesvm import LiteSVM
from solders.message import MessageV0
from solders.transaction import VersionedTransaction

from solders.instruction import AccountMeta, Instruction
from solders.pubkey import Pubkey
from solders.system_program import CreateAccountParams, create_account

from knos.settle import oidc, pay

FIX = Path(__file__).parent / "fixtures"
NOW = 1_790_000_000  # the chain's clock at the start of a test


def b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


class SeedKey:
    """An RSA test key derived from a fixed seed (no key file is committed): `primes` primes of bits/primes bits each,
    found by Miller-Rabin over a seeded generator. The test build of knos-oidc trusts exactly these two moduli
    (pins.rs TEST_GENESIS). Signs PKCS#1 v1.5 SHA-256 in plain Python."""
    DIGEST_INFO = bytes.fromhex("3031300d060960864801650304020105000420")

    def __init__(self, bits: int, seed: str | None = None):
        import math
        import random
        rng = random.Random(seed or f"knos-oidc test key {bits}")
        count = 2 if bits == 2048 else 4
        size = bits // count

        def is_prime(n: int) -> bool:
            for p in (3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43, 47, 53, 59, 61, 67, 71, 73, 79, 83, 89, 97):
                if n % p == 0:
                    return n == p
            d, r = n - 1, 0
            while d % 2 == 0:
                d //= 2; r += 1
            for _ in range(24):
                x = pow(rng.randrange(2, n - 1), d, n)
                if x in (1, n - 1):
                    continue
                for _ in range(r - 1):
                    x = x * x % n
                    if x == n - 1:
                        break
                else:
                    return False
            return True

        primes: list[int] = []
        while len(primes) < count:
            c = rng.getrandbits(size) | (7 << (size - 3)) | 1     # top three bits set: the product keeps its top bit
            if c % 65537 != 1 and c not in primes and is_prime(c):
                primes.append(c)
        self.bits, self.n, self.primes = bits, math.prod(primes), tuple(primes)
        self.d = pow(65537, -1, math.lcm(*(p - 1 for p in primes)))
        # for `sign`: the exponent and the recombining factor of each prime (the Chinese remainder theorem)
        self._crt = tuple((p, self.d % (p - 1), self.n // p * pow(self.n // p, -1, p)) for p in primes)
        assert self.n.bit_length() == bits

    def public_key(self):
        from cryptography.hazmat.primitives.asymmetric import rsa
        return rsa.RSAPublicNumbers(65537, self.n).public_key()

    def sign(self, data: bytes) -> bytes:
        import hashlib
        k = self.bits // 8
        t = self.DIGEST_INFO + hashlib.sha256(data).digest()
        em = b"\x00\x01" + b"\xff" * (k - len(t) - 3) + b"\x00" + t
        # em ** d mod n, one prime at a time: the same number as pow(em, d, n), several times sooner, and every token
        # of the suite is signed here (the program, and a reference library in tests/test_oidc2_chain.py, verify them)
        m = int.from_bytes(em, "big")
        return (sum(pow(m % p, dp, p) * back for p, dp, back in self._crt) % self.n).to_bytes(k, "big")


_KEYS: dict[int, SeedKey] = {}


def signing_key(bits: int = 2048) -> SeedKey:
    if bits not in _KEYS:
        _KEYS[bits] = SeedKey(bits)
    return _KEYS[bits]


def modulus(key) -> int:
    return key.public_key().public_numbers().n


def sign_jwt(key, claims: dict, header: dict | None = None, raw_payload: bytes | None = None) -> str:
    head = b64(json.dumps(header or {"typ": "JWT", "alg": "RS256", "x5t": "abc", "kid": "k"}, separators=(",", ":")).encode())
    body = b64(raw_payload if raw_payload is not None else json.dumps(claims, separators=(",", ":")).encode())
    data = f"{head}.{body}".encode()
    sig = key.sign(data) if isinstance(key, SeedKey) else key.sign(data, padding.PKCS1v15(), hashes.SHA256())
    return f"{head}.{body}.{b64(sig)}"


def github_claims(**over) -> dict:
    """The claims of a GitHub Actions token, with real names and realistic lengths."""
    c = {"jti": "8b2c1f0e-6a4d-4c3b-9e2a-5d7f1c0b9a8e", "sub": "repo:octo/widgets:pull_request",
         "aud": "x", "ref": "refs/heads/main", "sha": "a" * 40, "repository": "octo/widgets", "repository_owner": "octo",
         "repository_owner_id": "424242", "run_id": "36905461215", "run_number": "17", "run_attempt": "1",
         "repository_visibility": "public", "repository_id": "987654321", "actor_id": "1234567", "actor": "mona",
         "workflow": "knos", "head_ref": "", "base_ref": "", "event_name": "pull_request_target", "ref_protected": "true",
         "ref_type": "branch", "workflow_ref": "octo/widgets/.github/workflows/knos.yml@refs/heads/main",
         "workflow_sha": "b" * 40, "job_workflow_ref": "drexthealpha/Knos/.github/workflows/prove.yml@refs/heads/main",
         "job_workflow_sha": "c" * 40, "runner_environment": "github-hosted", "check_run_id": "5550001",
         "iss": oidc.ISSUERS[oidc.GITHUB], "nbf": NOW - 600, "exp": NOW + 300, "iat": NOW}
    c.update(over)
    return c


def gitlab_claims(**over) -> dict:
    """The claims of a GitLab CI ID token, with the names GitLab documents. `groups_direct` (the user's groups,
    up to 200 of them) is what makes a real one long."""
    c = {"namespace_id": "72", "namespace_path": "my-group", "project_id": "20", "project_path": "my-group/my-project",
         "user_id": "1", "user_login": "sample-user", "user_email": "sample-user@example.com", "user_access_level": "owner",
         "user_identities": [{"provider": "github", "extern_uid": "2435223452345"}], "pipeline_id": "574",
         "pipeline_source": "push", "job_id": "302", "ref": "feature-branch-1", "ref_type": "branch",
         "ref_path": "refs/heads/feature-branch-1", "ref_protected": "false", "groups_direct": ["my-group/my-subgroup"],
         "environment": "test-environment2", "environment_protected": "false", "deployment_tier": "testing",
         "environment_action": "start", "runner_id": 1, "runner_environment": "gitlab-hosted", "sha": "d" * 40,
         "project_visibility": "public", "ci_config_ref_uri": "gitlab.com/my-group/my-project//.gitlab-ci.yml@refs/heads/main",
         "ci_config_sha": "e" * 40, "jti": "235b3a54-b797-45c7-ae9a-f72d7bc6ef5b", "iat": NOW, "nbf": NOW - 5, "exp": NOW + 300,
         "iss": oidc.ISSUERS[oidc.GITLAB], "sub": "project_path:my-group/my-project:ref_type:branch:ref:feature-branch-1",
         "aud": "x"}
    c.update(over)
    return c


def jwt_size(key, payload_bytes: int) -> int:
    """How long sign_jwt's token is for a payload of this many bytes, without signing (a 4096-bit signature is slow here)."""
    head = len(b64(json.dumps({"typ": "JWT", "alg": "RS256", "x5t": "abc", "kid": "k"}, separators=(",", ":")).encode()))
    return head + 1 + (payload_bytes * 4 + 2) // 3 + 1 + (modulus(key).bit_length() // 8 * 4 + 2) // 3


def sized_jwt(key, claims: dict, size: int, grow: str = "groups_direct") -> str:
    """`claims` signed as a token of `size` bytes, or one under (base64 skips every fourth length): the list claim
    `grow` gets more entries, as a GitLab user in more groups would have."""
    def length(c: dict) -> int:
        return jwt_size(key, len(json.dumps(c, separators=(",", ":"))))

    c = dict(claims, **{grow: list(claims[grow])})
    assert length(c) <= size, f"these claims are already {length(c)} bytes as a token"
    while length(dict(c, **{grow: c[grow] + [f"group-{len(c[grow]):03}/team"]})) <= size:
        c[grow].append(f"group-{len(c[grow]):03}/team")
    while length(dict(c, **{grow: c[grow][:-1] + [c[grow][-1] + "s"]})) <= size:
        c[grow][-1] += "s"
    jwt = sign_jwt(key, c)
    assert length(c) == len(jwt) and size - 1 <= len(jwt) <= size
    return jwt


class Chain:
    def __init__(self, pay_build: str = "knos_pay_test.so", oidc_build: str = "knos_oidc_test.so"):
        """The two programs in LiteSVM. A build is a file in tests/fixtures (the test builds, which trust the seed
        keys) or any path (scripts/replay_tokens.py loads the real builds, which trust only the issuers' keys)."""
        self.svm = LiteSVM()
        self.svm.add_program_from_file(oidc.OIDC_ID, str(FIX / oidc_build))
        self.svm.add_program_from_file(pay.PAY_ID, str(FIX / pay_build))
        c = self.svm.get_clock(); c.unix_timestamp = NOW; self.svm.set_clock(c)
        self.payer = self.fund()
        self.cu: dict[str, list[int]] = {}
        self.err = None

    def fund(self, sol: int = 100) -> Keypair:
        k = Keypair(); self.svm.airdrop(k.pubkey(), sol * 10 ** 9); return k

    def warp(self, seconds: int) -> None:
        c = self.svm.get_clock(); c.unix_timestamp += seconds; self.svm.set_clock(c)

    def now(self) -> int:
        return int(self.svm.get_clock().unix_timestamp)

    def send(self, ixs, payer: Keypair | None = None, signers=(), tag: str | None = None) -> bool:
        payer = payer or self.payer
        everyone = {bytes(k.pubkey()): k for k in [payer, *signers]}
        msg = MessageV0.try_compile(payer.pubkey(), [set_compute_unit_limit(1_400_000), *ixs], [], self.svm.latest_blockhash())
        r = self.svm.send_transaction(VersionedTransaction(msg, list(everyone.values())))
        self.svm.expire_blockhash()
        ok = "Failed" not in type(r).__name__
        self.err = None if ok else str(r.err() if callable(getattr(r, "err", None)) else r.err)
        if ok and tag:
            cu = r.compute_units_consumed
            self.cu.setdefault(tag, []).append(cu() if callable(cu) else cu)
        return ok

    def data(self, address) -> bytes | None:
        a = self.svm.get_account(address)
        return bytes(a.data) if a is not None and a.lamports > 0 else None

    # -- knos-oidc ----------------------------------------------------------------------------------------------
    def register(self, issuer: int, n: int, attest=None, payer: Keypair | None = None) -> bool:
        p = payer or self.payer
        return (self.send([oidc.register_key_ix(p.pubkey(), issuer, n, attest)], p)
                and self.send([oidc.key_params_ix(p.pubkey(), issuer, n)], p, tag=f"key_params_{n.bit_length()}"))

    def write(self, jwt: str, payer: Keypair | None = None) -> bytes:
        p = payer or self.payer
        tid = oidc.token_id(jwt)
        for ix in oidc.write_ixs(p.pubkey(), tid, jwt):
            assert self.send([ix], p), self.err
        return tid

    def verify(self, jwt: str, issuer: int, n: int, payer: Keypair | None = None, tag: str | None = None):
        """Writes the token and runs every step. Returns the token account's address, or None if a step refused."""
        p = payer or self.payer
        have = oidc.read_token(self.data(oidc.token_pda(p.pubkey(), oidc.token_id(jwt))))
        if have is not None:                      # the same token again: reuse a verified account, restart any other
            if have.verified:
                return oidc.token_pda(p.pubkey(), oidc.token_id(jwt))
            assert self.send([oidc.close_ix(p.pubkey(), oidc.token_id(jwt))], p), self.err
        tid = self.write(jwt, p)
        bits = n.bit_length()
        for i, sq in enumerate(oidc.step_plan(bits)):
            if not self.send([oidc.step_ix(p.pubkey(), tid, oidc.key_pda(issuer, n), sq)], p, tag=tag and f"{tag}_{bits}_step{i + 1}"):
                why = self.err
                self.send([oidc.close_ix(p.pubkey(), tid)], p)
                self.err = why
                return None
        return oidc.token_pda(p.pubkey(), tid)

    # -- SPL token ------------------------------------------------------------------------------------------------
    def new_mint(self, authority: Keypair | None = None) -> Pubkey:
        """A 6-decimal mint (a stand-in for Circle's USDC) whose mint authority is `authority` (default: the payer)."""
        a = authority or self.payer
        m = Keypair()
        ixs = [create_account(CreateAccountParams(from_pubkey=self.payer.pubkey(), to_pubkey=m.pubkey(),
                                                  lamports=self.svm.minimum_balance_for_rent_exemption(82), space=82, owner=pay.TOKEN)),
               Instruction(pay.TOKEN, bytes([20, 6]) + bytes(a.pubkey()) + b"\x00", [AccountMeta(m.pubkey(), False, True)])]
        assert self.send(ixs, signers=[m]), self.err
        return m.pubkey()

    def token_account(self, owner: Pubkey, mint: Pubkey) -> Pubkey:
        assert self.send([pay.create_ata_ix(self.payer.pubkey(), owner, mint)]), self.err
        return pay.ata(owner, mint)

    def mint_to(self, mint: Pubkey, account: Pubkey, amount: int, authority: Keypair | None = None) -> None:
        a = authority or self.payer
        ix = Instruction(pay.TOKEN, b"\x07" + amount.to_bytes(8, "little"),
                         [AccountMeta(mint, False, True), AccountMeta(account, False, True), AccountMeta(a.pubkey(), True, False)])
        assert self.send([ix], signers=[a]), self.err

    def balance(self, account: Pubkey) -> int:
        d = self.data(account)
        return int.from_bytes(d[64:72], "little") if d and len(d) == 165 else 0

    # -- GitHub tokens, signed by the committed test key and verified by knos-oidc ----------------------------------
    def gh(self, aud: str, file: str = "prove.yml", wf_repo: str = "drexthealpha/Knos", wf_sha: str = "c" * 40, key=None, **over) -> Pubkey | None:
        """A verified GitHub token account for this audience, from <wf_repo>/.github/workflows/<file> at wf_sha."""
        now = self.now()
        self._n = getattr(self, "_n", 0) + 1
        claims = github_claims(aud=aud, iat=now, nbf=now - 600, exp=now + 300, jti=f"t{self._n}",
                               job_workflow_ref=f"{wf_repo}/.github/workflows/{file}@refs/tags/v0.3.10", job_workflow_sha=wf_sha)
        claims.update(over)
        k = key or signing_key()
        return self.verify(sign_jwt(k, claims), oidc.GITHUB, modulus(k))


class ChainLedger:
    """The Chain behind the interface knos.settle.relay uses (send, account, program_accounts)."""
    def __init__(self, chain: Chain):
        self.chain = chain
        self.n = 0

    def send(self, ixs, payer, signers=None) -> str:
        if not self.chain.send(list(ixs), payer, signers or ()):
            raise RuntimeError(self.chain.err)
        self.n += 1
        return f"local{self.n}"

    def account(self, address):
        return self.chain.data(address)

    def now(self) -> int:
        return self.chain.now()

    def program_accounts(self, program, size: int, memcmp: dict[int, bytes]):
        out = []
        for addr, acc in self.chain.svm.get_program_accounts(program):
            d = bytes(acc.data)
            if acc.lamports > 0 and len(d) == size and all(d[o:o + len(b)] == b for o, b in memcmp.items()):
                out.append((addr, d))
        return out
