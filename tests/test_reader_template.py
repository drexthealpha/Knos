"""examples/reader_template: a separate program, built against the published interface crate only, releases once
when GitHub signed that one workflow of one repository asked this program for it (LiteSVM, beside knos_oidc built
from programs-v2/knos_oidc with the test keys in place of GitHub's: the verifier's code is the deployed one, the
trusted key is not). Each of the five mistakes the README lists is tried, and the line that prevents it refuses.

The binary is tests/fixtures/reader_template_v2_real.so: `cargo build-sbf` in examples/reader_template, unchanged."""
from __future__ import annotations

import hashlib
import re

import pytest

pytest.importorskip("solders.litesvm")

from solders.account import Account  # noqa: E402
from solders.instruction import AccountMeta, Instruction  # noqa: E402
from solders.keypair import Keypair  # noqa: E402
from solders.pubkey import Pubkey  # noqa: E402

from _pay2 import FIX, Chain, github_claims  # noqa: E402
from _settle import sign_jwt, signing_key  # noqa: E402

from knos.settle.v2 import oidc, pay  # noqa: E402

READER = Pubkey.from_bytes(hashlib.sha256(b"reader_template example program").digest())
REPO, WORKFLOW, SHA = 424242001, "octo/widgets/.github/workflows/release.yml@refs/heads/main", "5" * 40
NOT_OIDC, NOT_VERIFIED, STALE, KEY, KEY_REVOKED = 1, 2, 3, 68, 78          # knos-oidc-interface's Error
E_AUDIENCE, E_REPOSITORY, E_WORKFLOW, E_USED, E_ACCOUNTS = 101, 102, 103, 104, 105


class Reader(Chain):
    def __init__(self):
        super().__init__()
        self.svm.add_program_from_file(READER, str(FIX / "reader_template_v2_real.so"))

    def token(self, aud: str | None = None, **over) -> Pubkey:
        claims = {"repository_id": REPO, "sha": SHA, "job_workflow_ref": WORKFLOW, **over}
        return self.gh(aud or f"release:{READER}", **claims)

    def done(self, tok: Pubkey) -> Pubkey:
        t = oidc.read_token(self.data(tok))
        claims = hashlib.sha256(t.payload).digest() if t is not None and t.verified else bytes(32)
        return Pubkey.find_program_address([b"done", claims], READER)[0]

    def release(self, tok: Pubkey, key: Pubkey | None = None, done: Pubkey | None = None) -> bool:
        return self.send([Instruction(READER, b"", [
            AccountMeta(self.payer.pubkey(), True, True), AccountMeta(tok, False, False), AccountMeta(key or self.key, False, False),
            AccountMeta(done or self.done(tok), False, True), AccountMeta(pay.SYSTEM, False, False)])], tag="release")

    def code(self) -> int | None:
        m = re.search(r"Custom\((\d+)\)", self.err or "")
        return int(m.group(1)) if m else None

    def refuses(self, tok: Pubkey, **how) -> int | None:
        assert not self.release(tok, **how)
        return self.code()


def test_it_releases_once_for_its_own_workflow_and_refuses_the_five_mistakes():
    c = Reader()
    tok = c.token()
    assert c.release(tok), c.err
    d = c.data(c.done(tok))
    assert int.from_bytes(d[0:8], "little") == REPO and d[16:56].decode() == SHA
    cu = [int(m.group(1)) for m in (re.match(rf"Program {READER} consumed (\d+) of", line) for line in c.logs) if m]
    print("\nCU of a release:", cu[-1])
    assert cu[-1] < 100_000

    # mistake 4, reusing a result: the same verified token again
    assert c.refuses(tok) == E_USED
    assert c.refuses(tok, done=Keypair().pubkey()) == E_ACCOUNTS          # and no other record address will do

    # mistakes 1 and 5, the owner and the program id: the same bytes in an account that another program owns,
    # be it anyone's or the first deployment of knos-oidc
    real = c.svm.get_account(c.token())
    for owner in (READER, Pubkey.from_string("vpWym9azbPU5f2PH2a6n8c4RfmsyUeW2dMuWr1DSHcE")):
        fake = Keypair().pubkey()
        c.svm.set_account(fake, Account(lamports=real.lamports, data=bytes(real.data), owner=owner, executable=False))
        assert c.refuses(fake) == NOT_OIDC
    # a token that was written and never verified
    jwt = sign_jwt(signing_key(), github_claims(aud=f"release:{READER}", repository_id=REPO, sha=SHA, job_workflow_ref=WORKFLOW,
                                                exp=c.now() + 300, jti="never"))
    assert c.refuses(oidc.token_pda(c.payer.pubkey(), c.write(jwt))) == NOT_VERIFIED

    # mistake 3, a claim the verifier does not check: it verified each of these tokens, and none is for this release
    assert c.refuses(c.token(repository_id=REPO + 1)) == E_REPOSITORY
    assert c.refuses(c.token(job_workflow_ref=WORKFLOW.replace("release.yml", "other.yml"))) == E_WORKFLOW
    assert c.refuses(c.token(job_workflow_ref=WORKFLOW.replace("refs/heads/main", "refs/heads/x"))) == E_WORKFLOW
    assert c.refuses(c.token(aud=f"release:{pay.PAY_ID}")) == E_AUDIENCE     # asked for another program
    assert c.refuses(c.token(aud="knos:pay:1:2")) == E_AUDIENCE

    # mistake 2, freshness: another key account in place of the token's own, then an hour past the token's expiry
    late = c.token()
    assert c.refuses(late, key=tok) == KEY
    c.warp(300 + oidc.LATE)
    assert c.refuses(late) == STALE


def test_a_revoked_key_stops_its_tokens_at_once():
    c = Reader()
    tok = c.token()
    assert c.revoke(oidc.GITHUB, c.github), c.err
    assert c.refuses(tok) == KEY_REVOKED


def test_the_readme_names_the_line_that_prevents_each_of_the_five_mistakes_and_the_count_of_outside_readers_is_zero():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    here = root / "examples" / "reader_template"
    source, readme = (here / "src" / "lib.rs").read_text(encoding="utf-8"), (here / "README.md").read_text(encoding="utf-8")
    for n in range(1, 6):
        assert f"[M{n}]" in source and f"| M{n} |" in readme
    use = readme.split("## Use this template")[1].split("## Five mistakes")[0]
    assert len(use.strip().splitlines()) <= 30 and "cargo build-sbf" in use and "solana program deploy -u devnet" in use
    assert source.count("// CHANGE") == 2
    # a workspace of its own: nothing is taken from this repository by path, only the published crate by tag
    cargo = (here / "Cargo.toml").read_text(encoding="utf-8")
    assert "path =" not in cargo and "[workspace]" in cargo and 'knos-oidc-interface = "0.3.14"' in cargo     # the crate as published on crates.io
    compose = (root / "docs" / "COMPOSE.md").read_text(encoding="utf-8")
    assert "**Programs outside this repository that read `knos-oidc`: 0.**" in compose and "| none yet |" in compose
    assert "has not been deployed" in readme
