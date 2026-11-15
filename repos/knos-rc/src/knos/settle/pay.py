"""Client for knos-pay (programs/knos_pay): the escrow that pays a GitHub user only on a GitHub-signed token verified
on chain by knos-oidc. Pure instruction builders, audiences and account readers; no network.

A job is one issue of one repository: `job_pda(repository_id, issue)`. It pins the repository that holds the Knos
workflows (`wf_repo_hash("owner/name")`) and their commit sha. Money is credited to a GitHub user id (`due_pda`) and
leaves the vault only by `claim_ix`, on a token from a workflow_dispatch run in a repository that user owns.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

from solders.instruction import AccountMeta, Instruction
from solders.pubkey import Pubkey

from .oidc import IDS, SYSTEM

PAY_ID = Pubkey.from_string(IDS["knos_pay"])
TOKEN = Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")
ATA_PROGRAM = Pubkey.from_string("ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL")
FEE_OWNER = Pubkey.from_string("4G3cznCnwCUPBCZwzKiLupjdgB5pSoCcGWNGuFv4TYFo")   # Knos's Squads vault: receives fees, nothing else
USDC_DEVNET = Pubkey.from_string("4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU")  # Circle's devnet USDC

MERGE, TESTS = 0, 1
FEE_BPS, FEE_MIN, MIN_AMOUNT, MAX_AMOUNT, FAUCET_CAP = 250, 50_000, 1_000_000, 500_000_000, 100_000_000
NO_CHECKS = bytes(32)
STATES = {1: "open", 2: "proven"}
ERRORS = {80: "accounts", 81: "terms", 82: "job exists or is not this job", 83: "state or time", 84: "token not verified, not GitHub's, or expired",
          85: "token claims", 86: "workflow is not the job's pinned one", 87: "audience", 88: "payee or fee account",
          89: "devnet only", 90: "one funding per repository per minute", 91: "nothing due"}


def fee_of(amount: int) -> int:
    return min(max(amount * FEE_BPS // 10_000, FEE_MIN), amount)


def _u64(v: int) -> bytes:
    return v.to_bytes(8, "little")


def _pda(seeds: list[bytes], program: Pubkey) -> Pubkey:
    return Pubkey.find_program_address(seeds, program)[0]


def auth_pda(program: Pubkey = PAY_ID) -> Pubkey:
    return _pda([b"auth"], program)


def vault_pda(mint: Pubkey, program: Pubkey = PAY_ID) -> Pubkey:
    return _pda([b"vault", bytes(mint)], program)


def job_pda(repo_id: int, issue: int, funder: Pubkey | None = None, program: Pubkey = PAY_ID) -> Pubkey:
    """A job's address. `funder` is the wallet that funded it; None for the repository's own token-funded bounty.
    Anyone can add a bounty of their own to an issue: the same proof pays every job pinning the same workflow."""
    return _pda([b"job", _u64(repo_id), _u64(issue), bytes(funder) if funder is not None else bytes(32)], program)


def due_pda(user_id: int, mint: Pubkey, program: Pubkey = PAY_ID) -> Pubkey:
    return _pda([b"due", _u64(user_id), bytes(mint)], program)


def rep_pda(user_id: int, program: Pubkey = PAY_ID) -> Pubkey:
    return _pda([b"rep", _u64(user_id)], program)


def rate_pda(repo_id: int, program: Pubkey = PAY_ID) -> Pubkey:
    return _pda([b"rate", _u64(repo_id)], program)


def faucet_mint(program: Pubkey = PAY_ID) -> Pubkey:
    """The devnet test-USDC mint (6 decimals); its mint authority is the program."""
    return _pda([b"mint"], program)


def ata(owner: Pubkey, mint: Pubkey) -> Pubkey:
    return _pda([bytes(owner), bytes(TOKEN), bytes(mint)], ATA_PROGRAM)


def create_ata_ix(payer: Pubkey, owner: Pubkey, mint: Pubkey) -> Instruction:
    """Creates the owner's associated token account if it does not exist (idempotent)."""
    return Instruction(ATA_PROGRAM, b"\x01", [AccountMeta(payer, True, True), AccountMeta(ata(owner, mint), False, True), AccountMeta(owner, False, False),
                                              AccountMeta(mint, False, False), AccountMeta(SYSTEM, False, False), AccountMeta(TOKEN, False, False)])


def wf_repo_hash(repository: str) -> bytes:
    """sha256 of "owner/name": the repository whose prove.yml and fund.yml a job pins."""
    return hashlib.sha256(repository.encode()).digest()


# -- audiences: what the workflows ask GitHub to sign ------------------------------------------------------------------
def fund_audience(issue: int, amount: int, mode: int = MERGE, checks: bytes = NO_CHECKS, work_s: int = 14 * 86_400, review_s: int = 0) -> str:
    return f"knos:fund:{issue}:{amount}:{mode}:{checks.hex()}:{work_s}:{review_s}"


def pay_audience(repo_id: int, issue: int, author_id: int, head_sha: str, checks: bytes = NO_CHECKS, mode: int = MERGE) -> str:
    return f"knos:pay:{repo_id}:{issue}:{author_id}:{head_sha}:{checks.hex()}:{mode}"


def veto_audience(repo_id: int, issue: int) -> str:
    return f"knos:veto:{repo_id}:{issue}"


def claim_audience(address: Pubkey) -> str:
    return f"knos:claim:{address}"


# -- instructions ---------------------------------------------------------------------------------------------------
def fund_ix(funder: Pubkey, funder_token: Pubkey, mint: Pubkey, repo_id: int, issue: int, amount: int, wf_repo: str, wf_sha: str,
            mode: int = MERGE, checks: bytes = NO_CHECKS, work_s: int = 14 * 86_400, review_s: int = 0, program: Pubkey = PAY_ID) -> Instruction:
    data = (b"\x00" + _u64(repo_id) + _u64(issue) + _u64(amount) + work_s.to_bytes(8, "little", signed=True)
            + review_s.to_bytes(8, "little", signed=True) + bytes([mode]) + checks + wf_repo_hash(wf_repo) + wf_sha.encode())
    return Instruction(program, data, [AccountMeta(funder, True, True), AccountMeta(job_pda(repo_id, issue, funder, program), False, True),
                                       AccountMeta(funder_token, False, True), AccountMeta(vault_pda(mint, program), False, True),
                                       AccountMeta(mint, False, False), AccountMeta(auth_pda(program), False, False),
                                       AccountMeta(TOKEN, False, False), AccountMeta(SYSTEM, False, False)])


def fund_with_token_ix(payer: Pubkey, fund_token: Pubkey, repo_id: int, issue: int, program: Pubkey = PAY_ID) -> Instruction:
    mint = faucet_mint(program)
    return Instruction(program, b"\x01", [AccountMeta(payer, True, True), AccountMeta(fund_token, False, False),
                                          AccountMeta(job_pda(repo_id, issue, None, program), False, True), AccountMeta(vault_pda(mint, program), False, True),
                                          AccountMeta(mint, False, True), AccountMeta(auth_pda(program), False, False),
                                          AccountMeta(TOKEN, False, False), AccountMeta(SYSTEM, False, False),
                                          AccountMeta(rate_pda(repo_id, program), False, True)])


def _settle_accounts(job: Pubkey, author_id: int, mint: Pubkey, rent_to: Pubkey, program: Pubkey) -> list[AccountMeta]:
    return [AccountMeta(job, False, True), AccountMeta(due_pda(author_id, mint, program), False, True),
            AccountMeta(rep_pda(author_id, program), False, True), AccountMeta(vault_pda(mint, program), False, True),
            AccountMeta(ata(FEE_OWNER, mint), False, True), AccountMeta(auth_pda(program), False, False),
            AccountMeta(rent_to, False, True), AccountMeta(TOKEN, False, False), AccountMeta(SYSTEM, False, False)]


def pay_ix(relayer: Pubkey, pay_token: Pubkey, job: Pubkey, author_id: int, mint: Pubkey, rent_to: Pubkey, program: Pubkey = PAY_ID) -> Instruction:
    """`job` is job_pda(...); `rent_to` is the job's funder field (the wallet that paid the job's rent). The fee account (FEE_OWNER's ATA of
    the mint) must exist: put create_ata_ix(relayer, FEE_OWNER, mint) before this in the same transaction."""
    return Instruction(program, b"\x02", [AccountMeta(relayer, True, True), AccountMeta(pay_token, False, False),
                                          *_settle_accounts(job, author_id, mint, rent_to, program)])


def settle_ix(relayer: Pubkey, job: Pubkey, author_id: int, mint: Pubkey, rent_to: Pubkey, program: Pubkey = PAY_ID) -> Instruction:
    return Instruction(program, b"\x03", [AccountMeta(relayer, True, True), *_settle_accounts(job, author_id, mint, rent_to, program)])


def veto_ix(signer: Pubkey, job: Pubkey, veto_token: Pubkey | None = None, program: Pubkey = PAY_ID) -> Instruction:
    acc = [AccountMeta(signer, True, False), AccountMeta(job, False, True)]
    if veto_token is not None:
        acc.append(AccountMeta(veto_token, False, False))
    return Instruction(program, b"\x04", acc)


def refund_ix(relayer: Pubkey, job: Pubkey, mint: Pubkey, dest: Pubkey, rent_to: Pubkey, program: Pubkey = PAY_ID) -> Instruction:
    """`dest`: the funder's token account (wallet-funded) or due_pda(funder's GitHub id, mint) (token-funded)."""
    return Instruction(program, b"\x05", [AccountMeta(relayer, True, True), AccountMeta(job, False, True),
                                          AccountMeta(vault_pda(mint, program), False, True), AccountMeta(dest, False, True),
                                          AccountMeta(auth_pda(program), False, False), AccountMeta(rent_to, False, True),
                                          AccountMeta(TOKEN, False, False), AccountMeta(SYSTEM, False, False)])


def claim_ix(relayer: Pubkey, claim_token: Pubkey, user_id: int, mint: Pubkey, address: Pubkey, program: Pubkey = PAY_ID) -> Instruction:
    """Pays everything due to `user_id` in `mint` to `address`'s associated token account (create it first)."""
    return Instruction(program, b"\x06", [AccountMeta(relayer, True, True), AccountMeta(claim_token, False, False),
                                          AccountMeta(due_pda(user_id, mint, program), False, True), AccountMeta(vault_pda(mint, program), False, True),
                                          AccountMeta(ata(address, mint), False, True), AccountMeta(auth_pda(program), False, False),
                                          AccountMeta(TOKEN, False, False)])


def init_faucet_ix(payer: Pubkey, program: Pubkey = PAY_ID) -> Instruction:
    return Instruction(program, b"\x07", [AccountMeta(payer, True, True), AccountMeta(faucet_mint(program), False, True),
                                          AccountMeta(auth_pda(program), False, False), AccountMeta(TOKEN, False, False), AccountMeta(SYSTEM, False, False)])


# -- accounts -------------------------------------------------------------------------------------------------------
@dataclass
class Job:
    state: str
    mode: int
    token_funded: bool
    repo_id: int
    issue: int
    amount: int
    deadline: int
    review: int
    pay_after: int
    author_id: int
    funder_id: int
    not_before: int
    vetoes: int
    funder: Pubkey
    mint: Pubkey
    checks: bytes
    wf_repo_hash: bytes
    wf_sha: str


def read_job(data: bytes | None) -> Job | None:
    if not data or len(data) != 256:
        return None
    u = lambda o: int.from_bytes(data[o:o + 8], "little")            # noqa: E731
    i = lambda o: int.from_bytes(data[o:o + 8], "little", signed=True)  # noqa: E731
    return Job(state=STATES.get(data[0], "?"), mode=data[1], token_funded=data[2] == 1, repo_id=u(8), issue=u(16), amount=u(24),
               deadline=i(32), review=i(40), pay_after=i(48), author_id=u(56), funder_id=u(64), not_before=i(72),
               vetoes=int.from_bytes(data[80:84], "little"), funder=Pubkey.from_bytes(data[88:120]), mint=Pubkey.from_bytes(data[120:152]),
               checks=bytes(data[152:184]), wf_repo_hash=bytes(data[184:216]), wf_sha=bytes(data[216:256]).decode())


def read_due(data: bytes | None) -> int:
    """What is waiting for a GitHub user in one mint (0 when the account does not exist)."""
    return int.from_bytes(data[0:8], "little") if data and len(data) == 48 else 0


@dataclass
class Record:
    paid_jobs: int
    total_paid: int
    repositories: int


def read_rep(data: bytes | None) -> Record:
    if not data or len(data) != 32:
        return Record(0, 0, 0)
    return Record(int.from_bytes(data[0:4], "little"), int.from_bytes(data[8:16], "little"), int.from_bytes(data[16:20], "little"))
