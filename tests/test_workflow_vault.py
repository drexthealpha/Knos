"""examples/workflow_vault: a vault with no private key (LiteSVM, beside the test build of the second knos-oidc, with
the test keys). It releases tokens only on a token GitHub signed for one workflow file at one commit of one
repository, with audience vault:<vault>:<to>:<amount>:<nonce>, and refuses everything else: another repository,
file or commit, a self-hosted runner, another vault's or destination's audience, a token used before, an account
knos-oidc does not own, and every token of a key the guardian revoked."""
from __future__ import annotations

import hashlib
import re

import pytest

pytest.importorskip("solders.litesvm")

from solders.account import Account  # noqa: E402
from solders.instruction import AccountMeta, Instruction  # noqa: E402
from solders.keypair import Keypair  # noqa: E402
from solders.pubkey import Pubkey  # noqa: E402

from _pay2 import FIX, Chain  # noqa: E402

from knos.settle.v2 import oidc, pay  # noqa: E402

VAULT = Pubkey.from_bytes(hashlib.sha256(b"workflow_vault example program").digest())
REPO, WF_REPO, FILE, SHA, USDC = 424242001, "octo/deploy", "pay.yml", "d" * 40, 1_000_000
WORKFLOW = f"{WF_REPO}/.github/workflows/{FILE}"


def vault_pda(mint: Pubkey, repo: int = REPO, workflow: str = WORKFLOW, sha: str = SHA) -> Pubkey:
    rule = hashlib.sha256(repo.to_bytes(8, "little") + hashlib.sha256(workflow.encode()).digest() + sha.encode() + bytes(mint)).digest()
    return Pubkey.find_program_address([b"vault", rule], VAULT)[0]


def open_ix(payer: Pubkey, mint: Pubkey, repo: int = REPO, workflow: str = WORKFLOW, sha: str = SHA) -> Instruction:
    return Instruction(VAULT, b"\x00" + repo.to_bytes(8, "little") + sha.encode() + workflow.encode(),
                       [AccountMeta(payer, True, True), AccountMeta(vault_pda(mint, repo, workflow, sha), False, True), AccountMeta(mint, False, False),
                        AccountMeta(pay.SYSTEM, False, False)])


class Vault(Chain):
    """A vault for octo/deploy's pay.yml at one commit, holding 100 USDC, and a wallet to pay."""
    def __init__(self):
        super().__init__()
        self.svm.add_program_from_file(VAULT, str(FIX / "workflow_vault_v2_real.so"))
        self.mint = self.new_mint()
        self.vault = vault_pda(self.mint)
        assert self.send([open_ix(self.payer.pubkey(), self.mint)]), self.err
        self.money = self.token_account(self.vault, self.mint)
        self.mint_to(self.mint, self.money, 100 * USDC)
        self.to = self.wallet(self.mint)[1]

    def token(self, amount: int, nonce: int, to: Pubkey | None = None, vault: Pubkey | None = None, **over) -> Pubkey:
        """What the vault's workflow asks GitHub to sign for one release."""
        self.warp(1)
        claims = {"file": FILE, "wf_repo": WF_REPO, "wf_sha": SHA, "repository_id": REPO, **over}
        return self.gh(f"vault:{vault or self.vault}:{to or self.to}:{amount}:{nonce}", **claims)

    def release(self, tok: Pubkey, to: Pubkey | None = None, key: Pubkey | None = None, vault: Pubkey | None = None, money: Pubkey | None = None) -> bool:
        return self.send([Instruction(VAULT, b"\x01", [
            AccountMeta(tok, False, False), AccountMeta(key or self.key, False, False), AccountMeta(vault or self.vault, False, True),
            AccountMeta(money or self.money, False, True), AccountMeta(self.mint, False, False), AccountMeta(to or self.to, False, True),
            AccountMeta(pay.TOKEN, False, False)])], tag="release")

    def code(self) -> int | None:
        m = re.search(r"Custom\((\d+)\)", self.err or "")
        return int(m.group(1)) if m else None

    def state(self) -> tuple[int, int]:
        d = self.data(self.vault)
        return int.from_bytes(d[16:24], "little"), int.from_bytes(d[128:136], "little")      # (last nonce, released in total)


def test_the_vault_pays_what_its_workflow_signed_for_once():
    c = Vault()
    tok = c.token(30 * USDC, 1)
    assert c.release(tok), c.err
    assert (c.balance(c.to), c.balance(c.money), c.state()) == (30 * USDC, 70 * USDC, (1, 30 * USDC))
    print("\nCU of a release:", sum(int(m.group(1)) for m in (re.match(rf"Program {VAULT} consumed (\d+) of", line) for line in c.logs) if m))
    # the same token again, and a new token with a nonce that is not greater: a token works once
    assert not c.release(tok) and c.code() == 3
    assert not c.release(c.token(USDC, 1)) and c.code() == 3
    # nonces only have to grow: a run that failed leaves a gap, and the older number never works afterwards
    assert c.release(c.token(5 * USDC, 7)), c.err
    assert not c.release(c.token(USDC, 6)) and c.code() == 3
    assert (c.balance(c.to), c.state()) == (35 * USDC, (7, 35 * USDC))
    # more than it holds: the token program refuses, and nothing is recorded
    assert not c.release(c.token(66 * USDC, 8))
    assert c.state() == (7, 35 * USDC)
    assert c.release(c.token(65 * USDC, 8)) and c.balance(c.money) == 0


def test_only_the_named_repository_workflow_and_commit_can_spend_it():
    c = Vault()
    n = iter(range(1, 100))
    for other in ({"repository_id": REPO + 1}, {"file": "other.yml"}, {"wf_repo": "octo/fork"}, {"wf_sha": "e" * 40},
                  {"runner_environment": "self-hosted"}):
        assert not c.release(c.token(USDC, next(n), **other)) and c.code() == 1, other
    # the audience must name this vault, the account that receives, and an amount
    elsewhere = c.wallet(c.mint)[1]
    assert not c.release(c.token(USDC, next(n)), to=elsewhere) and c.code() == 2          # a relayer cannot redirect it
    assert not c.release(c.token(USDC, next(n), vault=elsewhere)) and c.code() == 2
    assert not c.release(c.token(0, next(n))) and c.code() == 2
    for aud in (f"vault:{c.vault}:{c.to}:1", f"vault:{c.vault}:{c.to}:1:2:3", f"knos3:{c.vault}:{c.to}:1:2", f"vault:{c.vault}:{c.to}:01:2",
                f"vault:{c.vault}:{c.to}:1:-2"):
        tok = c.gh(aud, file=FILE, wf_repo=WF_REPO, wf_sha=SHA, repository_id=REPO)
        assert not c.release(tok) and c.code() == 2, aud
    # another vault (another rule: a different commit) has another address and its own money: this vault's is not its to spend
    other = vault_pda(c.mint, sha="e" * 40)
    assert other != c.vault and c.send([open_ix(c.payer.pubkey(), c.mint, sha="e" * 40)]), c.err
    tok = c.token(USDC, next(n), vault=other, wf_sha="e" * 40)
    assert not c.release(tok, vault=other)                                                # signed for, but `from` is not that vault's account
    assert not c.send([open_ix(c.payer.pubkey(), c.mint)])                                # a rule is set once
    # the same bytes in an account knos-oidc does not own; a token written but never verified
    good = c.token(USDC, next(n))
    real = c.svm.get_account(good)
    fake = Keypair().pubkey()
    c.svm.set_account(fake, Account(lamports=real.lamports, data=bytes(real.data), owner=VAULT, executable=False))
    assert not c.release(fake)
    from _pay2 import github_claims
    from _settle import sign_jwt, signing_key
    tid = c.write(sign_jwt(signing_key(), github_claims(aud=f"vault:{c.vault}:{c.to}:1:50", repository_id=REPO, exp=c.now() + 300, jti="nv")))
    assert not c.release(oidc.token_pda(c.payer.pubkey(), tid))
    assert c.balance(c.to) == 0 and c.state() == (0, 0)
    # a wrong key account; then the guardian revokes GitHub's key: the verified token in hand pays nothing, at once
    assert not c.release(good, key=c.vault) and c.code() == 68
    assert c.revoke(oidc.GITHUB, c.github), c.err
    assert not c.release(good) and c.code() == 78
    assert c.balance(c.money) == 100 * USDC
