"""The Solana escrow program (`programs/knos_escrow`), from Python: instruction builders, addresses and the job layout.

Layouts are the program's own (programs/knos_escrow/src/lib.rs):

    config PDA ["config2"]: admin(32) mint(32) fee_token(32) fee_bps(u16) min_fee(u64) min_amount(u64)
                            max_amount(u64, 0 = no cap) paused(u8) bump(u8)
    vault authority PDA ["vault"]: owns the one vault token account per mint
    job PDA ["job", id(32)]: state(u8) buyer(32) worker(32) amount(u64) deadline(i64) review(i64) brief(32) result(32)
                             verifier(32, zero = none) proof(32) stake(u64)
                             (0.3.4 jobs: 217 bytes, no stake; jobs before 0.3.4: 153 bytes, no verifier/proof)

    1  Post          buyer(s,w) job(w) buyer_token(w) vault_token(w) config token system
                     data: id[32] amount u64 work i64 review i64 brief[32] verifier[32]
    2  Claim         worker(s) job(w) worker_token(w) vault_token(w) config token   (stakes stake_for(price); not the buyer)
    3  Deliver       worker(s) job(w) worker_token(w) vault_token(w) vault_auth token   data: result[32] (stake back)
    4  Accept        buyer(s) job(w) vault_token(w) vault_auth worker_token(w) fee_token(w) config token buyer(w)
    5  Release       anyone(s), same accounts as Accept, after the review window
    6  Reject        buyer(s,w) job(w) vault_token(w) vault_auth buyer_token(w) token  (inside the review window; not
                     on a job that names a verifier)
    7  Refund        same accounts as Reject       (open or claimed, past the work deadline; a claim's stake included)
    12 VerifyReject  verifier(s) job(w) vault_token(w) vault_auth buyer_token(w) token buyer(w)  data: proof_root[32]
    13 Settle        anyone(s) job(w) vault_token(w) vault_auth worker_token(w) fee_token(w) buyer_token(w) buyer(w)
                     config token   (the deadline crank: delivered -> worker paid; open/claimed -> buyer refunded)

Every settlement (4 5 6 7 11 12 13) closes the job account; its rent lamports go back to the buyer.
    8  Init2         admin(s,w) config(w) fee_token system legacy_config
                     data: fee_bps u16 min_fee u64 min_amount u64 max_amount u64 paused u8
    9  SetPause      admin(s) config(w)                                        data: paused u8 (new posts only)
    10 LowerCap      admin(s) config(w)                                        data: max_amount u64 (only downward)
    11 VerifyRelease verifier(s), same accounts as Accept                      data: result_hash[32] proof_root[32]

The fee on release is max(fee_bps of the price, min_fee); the minimum job is min_amount (1 USDC on devnet).

0.3.7 (programs/knos_escrow/src/bounty.rs):
    20 Faucet         wallet(s,w) faucet mint(w) wallet_token(w) drip(w) token system      data: amount u64
                      devnet builds only; <= the faucet's cap per call, one drip per wallet per hour (["drip", wallet])
    21 InitFaucetMint admin(s,w) config faucet(w) mint system                            data: cap u64
    22 AddMint        admin(s,w) config registry(w) mint vault_token system   registry PDA ["mint", mint]:
                      mint(32) vault(32) bump; the vault is owned by the PDA ["vault", mint]
    23 PostBounty     Post's accounts (plus the registry for a registered mint); the price may be 0
    Post/PostBounty with an 8th account (the registry) post a job in that mint: 257 bytes (the job + mint(32)).
    Every later builder takes `mint=` for such a job (it picks the ["vault", mint] authority).
"""

from __future__ import annotations

import os
import struct
from dataclasses import dataclass

from solders.instruction import AccountMeta, Instruction
from solders.pubkey import Pubkey

TOKEN = Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")
SYSTEM = Pubkey.from_string("11111111111111111111111111111111")
# The program deployed on devnet (overridable for a local validator or LiteSVM).
DEVNET_PROGRAM = os.environ.get("KNOS_ESCROW_PROGRAM", "GwmbMFvyHHwHug5em9dv26oXz2zTgXKGsNdrBxPayRPq")

STATES = {0: "none", 1: "open", 2: "claimed", 3: "delivered", 4: "released", 5: "refunded"}
JOB_LEN = 225
MINT_JOB_LEN = 257            # 0.3.7: a job in a registered mint (the job + mint)
V034_JOB_LEN = 217            # jobs posted by 0.3.4 (no stake): still parsed, still settle
LEGACY_JOB_LEN = 153          # jobs posted before 0.3.4 (no verifier, no proof): still parsed, still settle
JOB_LENS = (MINT_JOB_LEN, JOB_LEN, V034_JOB_LEN, LEGACY_JOB_LEN)
STAKE_BPS = 1_000             # the worker's claim stake: 10% of the price ...
MIN_STAKE_UNITS = 100_000     # ... at least 0.1 USDC


def stake_for(amount: int) -> int:
    """The program's claim stake: max(10% of the price, 0.1 USDC), in the job's mint."""
    return max(amount * STAKE_BPS // 10_000, MIN_STAKE_UNITS)
CONFIG_LEN = 124
FEE_BPS = 250                 # 2.5%, with a 0.05 USDC floor (MIN_FEE_UNITS)
MIN_FEE_UNITS = 50_000        # 0.05 USDC
MIN_JOB_UNITS = 1_000_000     # 1 USDC
NO_VERIFIER = Pubkey.default()


def program_id(pid: str | Pubkey | None = None) -> Pubkey:
    if isinstance(pid, Pubkey):
        return pid
    got = pid or DEVNET_PROGRAM or os.environ.get("KNOS_ESCROW_PROGRAM", "")
    if not got:
        raise LookupError("no escrow program id: set KNOS_ESCROW_PROGRAM or pass one")
    return Pubkey.from_string(got)


def config_pda(pid: Pubkey) -> Pubkey:
    return Pubkey.find_program_address([b"config2"], pid)[0]


def legacy_config_pda(pid: Pubkey) -> Pubkey:
    """The pre-0.3.4 config (["config"]): no longer read by the program; Init2 checks its admin."""
    return Pubkey.find_program_address([b"config"], pid)[0]


def vault_authority(pid: Pubkey, mint: Pubkey | None = None) -> Pubkey:
    """The vault authority: ["vault"] for the config mint, ["vault", mint] for a registered mint."""
    seeds = [b"vault"] if mint is None else [b"vault", bytes(mint)]
    return Pubkey.find_program_address(seeds, pid)[0]


def mint_registry(pid: Pubkey, mint: Pubkey) -> Pubkey:
    return Pubkey.find_program_address([b"mint", bytes(mint)], pid)[0]


def faucet_pda(pid: Pubkey) -> Pubkey:
    return Pubkey.find_program_address([b"faucet"], pid)[0]


def drip_pda(pid: Pubkey, wallet: Pubkey) -> Pubkey:
    return Pubkey.find_program_address([b"drip", bytes(wallet)], pid)[0]


def bounty_brief_json(repo: str, issue: int) -> str:
    """The brief of a bonded PR bounty (canonical JSON; its sha256 is the job's brief hash)."""
    import json
    return json.dumps({"kind": "github-bounty", "repo": repo, "issue": int(issue)}, sort_keys=True,
                      separators=(",", ":"))


def bounty_brief(repo: str, issue: int) -> bytes:
    import hashlib
    return hashlib.sha256(bounty_brief_json(repo, issue).encode()).digest()


def job_pda(pid: Pubkey, job_id: bytes) -> Pubkey:
    return Pubkey.find_program_address([b"job", job_id], pid)[0]


def fee_for(amount: int, fee_bps: int = FEE_BPS, min_fee: int = MIN_FEE_UNITS, min_amount: int = MIN_JOB_UNITS) -> int:
    """The program's fee rule: max(fee_bps of the price, min_fee); a (pre-0.3.4) job under the minimum pays the
    percentage alone. Never more than the price."""
    pct = amount * fee_bps // 10_000
    return min(amount, min_fee if amount >= min_amount and pct < min_fee else pct)


def _m(k: Pubkey, s: bool, w: bool) -> AccountMeta:
    return AccountMeta(k, is_signer=s, is_writable=w)


def init2(pid: Pubkey, admin: Pubkey, fee_token: Pubkey, fee_bps: int = FEE_BPS, min_fee: int = MIN_FEE_UNITS,
          min_amount: int = MIN_JOB_UNITS, max_amount: int = 0, paused: bool = False) -> Instruction:
    return Instruction(pid, bytes([8]) + struct.pack("<HQQQB", fee_bps, min_fee, min_amount, max_amount, int(paused)),
                       [_m(admin, True, True), _m(config_pda(pid), False, True), _m(fee_token, False, False),
                        _m(SYSTEM, False, False), _m(legacy_config_pda(pid), False, False)])


def init(pid: Pubkey, admin: Pubkey, fee_token: Pubkey, fee_bps: int = FEE_BPS, **limits) -> Instruction:
    """Initialise the escrow's config (Init2; the pre-0.3.4 Init is retired)."""
    return init2(pid, admin, fee_token, fee_bps, **limits)


def set_pause(pid: Pubkey, admin: Pubkey, paused: bool) -> Instruction:
    return Instruction(pid, bytes([9, int(paused)]), [_m(admin, True, False), _m(config_pda(pid), False, True)])


def lower_cap(pid: Pubkey, admin: Pubkey, max_amount: int) -> Instruction:
    return Instruction(pid, bytes([10]) + struct.pack("<Q", max_amount),
                       [_m(admin, True, False), _m(config_pda(pid), False, True)])


def lower_fee(pid: Pubkey, admin: Pubkey, fee_bps: int) -> Instruction:
    """LowerFee (14): the admin lowers fee_bps; the fee never goes up."""
    return Instruction(pid, bytes([14]) + struct.pack("<H", fee_bps),
                       [_m(admin, True, False), _m(config_pda(pid), False, True)])


def set_admin(pid: Pubkey, admin: Pubkey, new_admin: Pubkey) -> Instruction:
    """SetAdmin (27): the current admin hands the config to a new admin (e.g. a Squads v4 vault PDA)."""
    return Instruction(pid, bytes([27]) + bytes(new_admin), [_m(admin, True, False), _m(config_pda(pid), False, True)])


def set_fee_account(pid: Pubkey, admin: Pubkey, fee_token: Pubkey) -> Instruction:
    """SetFeeAccount (28): the admin points the fee at another token account of the config mint."""
    return Instruction(pid, bytes([28]), [_m(admin, True, False), _m(config_pda(pid), False, True),
                                          _m(fee_token, False, False)])


def post(pid: Pubkey, buyer: Pubkey, job_id: bytes, amount: int, work_s: int, review_s: int, brief_hash: bytes,
         buyer_token: Pubkey, vault_token: Pubkey, verifier: Pubkey | None = None, mint: Pubkey | None = None,
         _tag: int = 1) -> Instruction:
    """Post a job. `verifier` (default none) may later release the delivered job on proof (VerifyRelease).
    `mint` (default: the config mint) posts in a registered mint; `vault_token` is then that mint's vault."""
    if len(job_id) != 32 or len(brief_hash) != 32:
        raise ValueError("job id and brief hash are 32 bytes")
    data = bytes([_tag]) + job_id + struct.pack("<Qqq", amount, work_s, review_s) + brief_hash + \
        bytes(verifier or NO_VERIFIER)
    return Instruction(pid, data, [_m(buyer, True, True), _m(job_pda(pid, job_id), False, True),
                                   _m(buyer_token, False, True), _m(vault_token, False, True),
                                   _m(config_pda(pid), False, False), _m(TOKEN, False, False),
                                   _m(SYSTEM, False, False)]
                       + ([_m(mint_registry(pid, mint), False, False)] if mint is not None else []))


def post_bounty(pid: Pubkey, buyer: Pubkey, job_id: bytes, amount: int, work_s: int, review_s: int,
                brief_hash: bytes, buyer_token: Pubkey, vault_token: Pubkey, verifier: Pubkey | None = None,
                mint: Pubkey | None = None) -> Instruction:
    """PostBounty (23): a job whose brief is {kind: "github-bounty", repo, issue}; the price may be 0. The worker
    still stakes stake_for(price) at claim and gets it back on delivery."""
    return post(pid, buyer, job_id, amount, work_s, review_s, brief_hash, buyer_token, vault_token, verifier, mint,
                _tag=23)


def faucet(pid: Pubkey, wallet: Pubkey, mint: Pubkey, wallet_token: Pubkey, amount: int) -> Instruction:
    """Faucet (20, devnet builds only): test USDC to the signer's own token account."""
    return Instruction(pid, bytes([20]) + struct.pack("<Q", amount),
                       [_m(wallet, True, True), _m(faucet_pda(pid), False, False), _m(mint, False, True),
                        _m(wallet_token, False, True), _m(drip_pda(pid, wallet), False, True), _m(TOKEN, False, False),
                        _m(SYSTEM, False, False)])


def init_faucet_mint(pid: Pubkey, admin: Pubkey, mint: Pubkey, cap: int) -> Instruction:
    """InitFaucetMint (21, admin, devnet only): record the faucet's mint (whose mint authority is faucet_pda)."""
    return Instruction(pid, bytes([21]) + struct.pack("<Q", cap),
                       [_m(admin, True, True), _m(config_pda(pid), False, False), _m(faucet_pda(pid), False, True),
                        _m(mint, False, False), _m(SYSTEM, False, False)])


def add_mint(pid: Pubkey, admin: Pubkey, mint: Pubkey, vault_token: Pubkey) -> Instruction:
    """AddMint (22, admin): register `mint`; `vault_token` is a token account of it owned by vault_authority(pid, mint)."""
    return Instruction(pid, bytes([22]),
                       [_m(admin, True, True), _m(config_pda(pid), False, False), _m(mint_registry(pid, mint), False, True),
                        _m(mint, False, False), _m(vault_token, False, False), _m(SYSTEM, False, False)])


def claim(pid: Pubkey, worker: Pubkey, job_id: bytes, worker_token: Pubkey, vault_token: Pubkey) -> Instruction:
    """Claim an open job, staking stake_for(price) from `worker_token` into the vault. Never the job's buyer."""
    return Instruction(pid, bytes([2]), [_m(worker, True, False), _m(job_pda(pid, job_id), False, True),
                                         _m(worker_token, False, True), _m(vault_token, False, True),
                                         _m(config_pda(pid), False, False), _m(TOKEN, False, False)])


def deliver(pid: Pubkey, worker: Pubkey, job_id: bytes, result_hash: bytes, worker_token: Pubkey,
            vault_token: Pubkey, mint: Pubkey | None = None) -> Instruction:
    """Commit the result hash; the claim's stake goes back to `worker_token`."""
    if len(result_hash) != 32:
        raise ValueError("result hash is 32 bytes")
    return Instruction(pid, bytes([3]) + result_hash,
                       [_m(worker, True, False), _m(job_pda(pid, job_id), False, True), _m(worker_token, False, True),
                        _m(vault_token, False, True), _m(vault_authority(pid, mint), False, False), _m(TOKEN, False, False)])


def _payout(tag: int, data: bytes, pid: Pubkey, signer: Pubkey, job_id: bytes, vault_token: Pubkey,
            worker_token: Pubkey, fee_token: Pubkey, buyer: Pubkey, mint: Pubkey | None = None) -> Instruction:
    return Instruction(pid, bytes([tag]) + data,
                       [_m(signer, True, signer == buyer), _m(job_pda(pid, job_id), False, True),
                        _m(vault_token, False, True), _m(vault_authority(pid, mint), False, False),
                        _m(worker_token, False, True), _m(fee_token, False, True), _m(config_pda(pid), False, False),
                        _m(TOKEN, False, False), _m(buyer, signer == buyer, True)])


def settle(pid: Pubkey, signer: Pubkey, job_id: bytes, vault_token: Pubkey, worker_token: Pubkey, fee_token: Pubkey,
           release: bool = False, buyer: Pubkey | None = None, mint: Pubkey | None = None) -> Instruction:
    """Accept (the buyer) or, with release=True, release by anyone after the review window: worker paid, fee taken.
    The job closes; its rent goes to `buyer` (default: the signer, i.e. Accept)."""
    return _payout(5 if release else 4, b"", pid, signer, job_id, vault_token, worker_token, fee_token,
                   buyer or signer, mint)


def accept(pid, buyer, job_id, vault_token, worker_token, fee_token) -> Instruction:
    return settle(pid, buyer, job_id, vault_token, worker_token, fee_token)


def release(pid, anyone, job_id, vault_token, worker_token, fee_token, buyer: Pubkey) -> Instruction:
    return settle(pid, anyone, job_id, vault_token, worker_token, fee_token, release=True, buyer=buyer)


def verify_release(pid: Pubkey, verifier: Pubkey, job_id: bytes, result_hash: bytes, proof_root: bytes,
                   vault_token: Pubkey, worker_token: Pubkey, fee_token: Pubkey, buyer: Pubkey,
                   mint: Pubkey | None = None) -> Instruction:
    """Paid on proof: the job's verifier releases a delivered job whose committed result is `result_hash`, recording
    `proof_root`. The program refuses any other hash ("verifier releases unproven work"). The job closes (rent to
    `buyer`)."""
    if len(result_hash) != 32 or len(proof_root) != 32:
        raise ValueError("result hash and proof root are 32 bytes")
    return _payout(11, result_hash + proof_root, pid, verifier, job_id, vault_token, worker_token, fee_token, buyer,
                   mint)


def _refundish(tag: int, pid: Pubkey, buyer: Pubkey, job_id: bytes, vault_token: Pubkey,
               buyer_token: Pubkey, mint: Pubkey | None = None) -> Instruction:
    return Instruction(pid, bytes([tag]), [_m(buyer, True, True), _m(job_pda(pid, job_id), False, True),
                                           _m(vault_token, False, True), _m(vault_authority(pid, mint), False, False),
                                           _m(buyer_token, False, True), _m(TOKEN, False, False)])


def reject(pid, buyer, job_id, vault_token, buyer_token, mint: Pubkey | None = None) -> Instruction:
    """The buyer rejects delivered work inside the review window (never a job that names a verifier)."""
    return _refundish(6, pid, buyer, job_id, vault_token, buyer_token, mint)


def refund(pid, buyer, job_id, vault_token, buyer_token, mint: Pubkey | None = None) -> Instruction:
    return _refundish(7, pid, buyer, job_id, vault_token, buyer_token, mint)


def verify_reject(pid: Pubkey, verifier: Pubkey, job_id: bytes, proof_root: bytes, vault_token: Pubkey,
                  buyer_token: Pubkey, buyer: Pubkey, mint: Pubkey | None = None) -> Instruction:
    """The job's verifier fails the delivered work inside the review window: the buyer is refunded, the job closes."""
    if len(proof_root) != 32:
        raise ValueError("proof root is 32 bytes")
    return Instruction(pid, bytes([12]) + proof_root,
                       [_m(verifier, True, False), _m(job_pda(pid, job_id), False, True), _m(vault_token, False, True),
                        _m(vault_authority(pid, mint), False, False), _m(buyer_token, False, True), _m(TOKEN, False, False),
                        _m(buyer, False, True)])


def crank(pid: Pubkey, anyone: Pubkey, job_id: bytes, vault_token: Pubkey, worker_token: Pubkey, fee_token: Pubkey,
          buyer_token: Pubkey, buyer: Pubkey, mint: Pubkey | None = None) -> Instruction:
    """Settle (tag 13), the deadline crank, by anyone: delivered past the review deadline -> the worker is paid; open
    or claimed past the work deadline -> the buyer is refunded (with a timed-out claim's stake). The job closes.
    For an unclaimed job `worker_token` is unused: pass any token account (e.g. the buyer's)."""
    return Instruction(pid, bytes([13]),
                       [_m(anyone, True, anyone == buyer), _m(job_pda(pid, job_id), False, True),
                        _m(vault_token, False, True), _m(vault_authority(pid, mint), False, False),
                        _m(worker_token, False, True), _m(fee_token, False, True), _m(buyer_token, False, True),
                        _m(buyer, anyone == buyer, True), _m(config_pda(pid), False, False), _m(TOKEN, False, False)])


@dataclass(frozen=True)
class Job:
    address: Pubkey
    state: str
    buyer: Pubkey
    worker: Pubkey | None
    amount: int
    deadline: int
    review: int
    brief: bytes
    result: bytes | None
    verifier: Pubkey | None = None
    proof: bytes | None = None
    stake: int = 0                 # the claim's stake held in the vault (0 once delivered or settled)
    mint: Pubkey | None = None     # a registered mint's job (257 bytes); None = the config mint


def parse_job(address: Pubkey, raw: bytes) -> Job:
    if len(raw) not in JOB_LENS:
        raise ValueError("not a knos_escrow job account")
    state, = struct.unpack_from("<B", raw, 0)
    amount, deadline, review = struct.unpack_from("<Qqq", raw, 65)
    worker = Pubkey.from_bytes(raw[33:65])
    result = bytes(raw[121:153])
    verifier, proof, stake = None, None, 0
    if len(raw) >= V034_JOB_LEN:
        v = Pubkey.from_bytes(raw[153:185])
        verifier = None if v == NO_VERIFIER else v
        proof = None if raw[185:217] == bytes(32) else bytes(raw[185:217])
    mint = None
    if len(raw) >= JOB_LEN:
        stake, = struct.unpack_from("<Q", raw, 217)
    if len(raw) == MINT_JOB_LEN:
        mint = Pubkey.from_bytes(raw[225:257])
    elif len(raw) == JOB_LEN + 64 + 33 + 32:       # GH_MINT_JOB_LEN (a funded github job)
        mint = Pubkey.from_bytes(raw[JOB_LEN + 97:JOB_LEN + 129])
    return Job(address, STATES.get(state, "unknown"), Pubkey.from_bytes(raw[1:33]),
               None if worker == Pubkey.default() else worker, amount, deadline, review, bytes(raw[89:121]),
               None if result == bytes(32) else result, verifier, proof, stake, mint)


def parse_config(raw: bytes) -> dict:
    if len(raw) < CONFIG_LEN:
        raise ValueError("not a knos_escrow config2 account")
    fee_bps, min_fee, min_amount, max_amount, paused = struct.unpack_from("<HQQQB", raw, 96)
    return {"admin": Pubkey.from_bytes(raw[0:32]), "mint": Pubkey.from_bytes(raw[32:64]),
            "fee_token": Pubkey.from_bytes(raw[64:96]), "fee_bps": fee_bps, "min_fee": min_fee,
            "min_amount": min_amount, "max_amount": max_amount, "paused": bool(paused)}


# -- 0.3.7: GitHub Actions OIDC proof, verified on chain (programs/knos_escrow/src/github.rs) ---------------------------
#    15 RegisterKey  admin(s,w) config key(w) system   data: kid_len u8 kid n[256] r2[256] n0inv u32 (big-endian n, r2)
#    16 BufferWrite  prover(s,w) buffer(w) system      data: job_id[32] total_len u16 offset u16 chunk
#    17 VerifyStep1  prover(s) buffer(w) key           data: job_id[32]
#    18 VerifyStep2  prover(s,w) buffer(w) key job(w) vault_token(w) vault_auth worker_token(w) fee_token(w) buyer(w)
#                    config token                      data: job_id[32]
#    19 PostGithub   buyer(s,w) job(w) buyer_token(w) vault_token(w) config token system
#                    data: id[32] amount u64 work i64 review i64 brief[32] repo_hash[32] ref_hash[32]
GH_V037_JOB_LEN = JOB_LEN + 64  # a 0.3.7 github job: the job, sha256(repository), sha256(ref) (refund only now)
GH_JOB_LEN = JOB_LEN + 64 + 33  # 0.3.8: ... then checks_hash[32], stake_required u8
GH_MINT_JOB_LEN = GH_JOB_LEN + 32  # 0.3.9: a github job funded by FundWithToken: ... then the faucet mint[32]
JOB_LENS = JOB_LENS + (GH_JOB_LEN, GH_V037_JOB_LEN, GH_MINT_JOB_LEN)
GH_BUF_LEN = 291 + 2048
GH_MAX_JWT = 2048
GH_ISSUER = "https://token.actions.githubusercontent.com"
GH_WORKFLOW_PREFIX = "drexthealpha/Knos/.github/workflows/prove.yml@refs/tags/"
COMPUTE_BUDGET = Pubkey.from_string("ComputeBudget111111111111111111111111111111")


def gh_key_pda(pid: Pubkey, kid: str | bytes, issuer: int | None = None) -> Pubkey:
    """A registered signing key: ["ghkey", sha256(kid)] (a GitHub key, as registered before 0.3.9) or, scoped to a
    registered issuer, ["ghkey", sha256(kid), [issuer id]]."""
    import hashlib
    kid = kid.encode() if isinstance(kid, str) else kid
    seeds = [b"ghkey", hashlib.sha256(kid).digest()] + ([] if issuer is None else [bytes([issuer])])
    return Pubkey.find_program_address(seeds, pid)[0]


def gh_buffer_pda(pid: Pubkey, job_id: bytes, prover: Pubkey) -> Pubkey:
    return Pubkey.find_program_address([b"ghproof", job_id, bytes(prover)], pid)[0]


def gh_audience(job_id: bytes, head_sha: str = "0" * 40, checks_hash: bytes = bytes(32),
                payout: Pubkey | str = "11111111111111111111111111111111") -> str:
    """The proof audience: knos:<job hex>:<head sha>:<checks hash hex>:<payout base58>. The token's sha claim must be
    head_sha, checks_hash the job's (fixed at funding), and the payout is who gets paid."""
    return f"knos:{job_id.hex()}:{head_sha}:{checks_hash.hex()}:{payout}"


def parse_gh_audience(aud: str) -> tuple[bytes, str, bytes, str]:
    """(job id, head sha, checks hash, payout base58) from a 5-part proof audience; ValueError otherwise."""
    parts = aud.split(":")
    if len(parts) != 5 or parts[0] != "knos" or len(parts[1]) != 64 or len(parts[2]) != 40 or len(parts[3]) != 64:
        raise ValueError(f"not a knos proof audience: {aud!r}")
    return bytes.fromhex(parts[1]), parts[2], bytes.fromhex(parts[3]), parts[4]


def rsa_r2_n0inv(n: int) -> tuple[int, int]:
    """R^2 mod n (R = 2^2048) and -n^-1 mod 2^32: what RegisterKey takes (and checks)."""
    return pow(2, 4096, n), (-pow(n, -1, 2 ** 32)) % 2 ** 32


def compute_limit(units: int = 1_400_000) -> Instruction:
    return Instruction(COMPUTE_BUDGET, bytes([2]) + struct.pack("<I", units), [])


def register_key(pid: Pubkey, admin: Pubkey, kid: str | bytes, n: int, r2: int | None = None,
                 n0inv: int | None = None, issuer: int | None = None) -> Instruction:
    """RegisterKey (15, admin only): an RSA-2048 key GitHub signs OIDC tokens with, at ["ghkey", sha256(kid)].
    r2 and n0inv default to the right values; the program refuses wrong ones."""
    kid = kid.encode() if isinstance(kid, str) else kid
    if not 0 < len(kid) <= 64:
        raise ValueError("kid is 1..64 bytes")
    r2d, n0d = rsa_r2_n0inv(n)
    r2 = r2d if r2 is None else r2
    n0inv = n0d if n0inv is None else n0inv
    data = bytes([15, len(kid)]) + kid + n.to_bytes(256, "big") + r2.to_bytes(256, "big") + struct.pack("<I", n0inv)
    accts = [_m(admin, True, True), _m(config_pda(pid), False, False),
             _m(gh_key_pda(pid, kid, issuer), False, True), _m(SYSTEM, False, False)]
    if issuer is not None:      # 0.3.9: scoped to the registered issuer ["issuer", id]
        data += bytes([issuer])
        accts.append(_m(issuer_pda(pid, issuer), False, False))
    return Instruction(pid, data, accts)


# -- 0.3.9: the issuer registry, FundWithToken, the program version ---------------------------------------------------
#    25 RegisterIssuer admin(s,w) config issuer(w) system     data: id u8 claims_kind u8 url
#    26 FundWithToken  payer(s,w) buffer(w) key job(w) vault_token(w) faucet mint(w) registry config token system
#                      workflow(kind 1) fundrate(w)          data: job_id[32]
#    29 Version        (no accounts): logs "knos-escrow X.Y.Z"
CLAIMS_GITHUB, CLAIMS_GITLAB = 0, 1
ISSUER_GITHUB, ISSUER_GITLAB = 0, 1          # the ids Knos registers on devnet
GITLAB_ISSUER = "https://gitlab.com"
VERSION = "0.3.9"                              # the program version this client speaks


def issuer_pda(pid: Pubkey, issuer: int) -> Pubkey:
    return Pubkey.find_program_address([b"issuer", bytes([issuer])], pid)[0]


def register_issuer(pid: Pubkey, admin: Pubkey, issuer: int, url: str, claims_kind: int = CLAIMS_GITHUB) -> Instruction:
    """RegisterIssuer (25, admin): an OIDC issuer url (GitHub Actions: claims kind 0; GitLab CI: kind 1, where
    project_path stands for repository and ci_config_sha for job_workflow_sha)."""
    u = url.encode()
    if not 0 < len(u) <= 128:
        raise ValueError("issuer url is 1..128 bytes")
    return Instruction(pid, bytes([25, issuer, claims_kind]) + u,
                       [_m(admin, True, True), _m(config_pda(pid), False, False),
                        _m(issuer_pda(pid, issuer), False, True), _m(SYSTEM, False, False)])


def fund_job_id(repository: str, issue: int | str) -> bytes:
    """The job a fund.yml token funds: sha256("knos-fund" | repository | "#" | issue)."""
    import hashlib
    return hashlib.sha256(b"knos-fund" + repository.encode() + b"#" + str(issue).encode()).digest()


def fund_audience(issue: int, amount_units: int, checks_hash: bytes, stake_required: bool = False) -> str:
    return f"knos:fund:{issue}:{amount_units}:{checks_hash.hex()}:{int(stake_required)}"


def fundrate_pda(pid: Pubkey, repository: str) -> Pubkey:
    import hashlib
    return Pubkey.find_program_address([b"fundrate", hashlib.sha256(repository.encode()).digest()], pid)[0]


def fund_with_token(pid: Pubkey, payer: Pubkey, job_id: bytes, key: Pubkey, mint: Pubkey, vault_token: Pubkey,
                    workflow_sha: str, repository: str) -> Instruction:
    """FundWithToken (26, devnet): after BufferWrite + VerifyStep1 of a fund.yml token, create the github job it names
    and mint its amount of test USDC (the faucet mint) into that mint's vault."""
    return Instruction(pid, bytes([26]) + job_id,
                       [_m(payer, True, True), _m(gh_buffer_pda(pid, job_id, payer), False, True),
                        _m(key, False, False), _m(job_pda(pid, job_id), False, True), _m(vault_token, False, True),
                        _m(faucet_pda(pid), False, False), _m(mint, False, True),
                        _m(mint_registry(pid, mint), False, False), _m(config_pda(pid), False, False),
                        _m(TOKEN, False, False), _m(SYSTEM, False, False),
                        _m(workflow_pda(pid, workflow_sha, WF_FUND), False, False),
                        _m(fundrate_pda(pid, repository), False, True)])


def version_ix(pid: Pubkey) -> Instruction:
    return Instruction(pid, bytes([29]), [])


def program_version(raw: bytes) -> str | None:
    """The "knos-escrow X.Y.Z" version string inside a program binary (None: a build before 0.3.9)."""
    import re
    m = re.search(rb"knos-escrow (\d+\.\d+\.\d+)", raw)
    return m.group(1).decode() if m else None


def buffer_write(pid: Pubkey, prover: Pubkey, job_id: bytes, total_len: int, offset: int, chunk: bytes) -> Instruction:
    """BufferWrite (16): a chunk of the JWT into the proof buffer ["ghproof", job_id, prover] (created on first use)."""
    return Instruction(pid, bytes([16]) + job_id + struct.pack("<HH", total_len, offset) + chunk,
                       [_m(prover, True, True), _m(gh_buffer_pda(pid, job_id, prover), False, True),
                        _m(SYSTEM, False, False)])


def verify_step1(pid: Pubkey, prover: Pubkey, job_id: bytes, key: Pubkey) -> Instruction:
    """VerifyStep1 (17): s*R mod n, then 8 squarings, into the buffer. ~1.05M CU: send with compute_limit()."""
    return Instruction(pid, bytes([17]) + job_id, [_m(prover, True, False),
                                                   _m(gh_buffer_pda(pid, job_id, prover), False, True),
                                                   _m(key, False, False)])


WF_PROVE, WF_FUND = 0, 1      # workflow registry kinds: prove.yml, fund.yml


def workflow_pda(pid: Pubkey, sha: str, kind: int = WF_PROVE) -> Pubkey:
    """The registry entry ["workflow", kind, sha] that pins a workflow file by its 40-hex commit sha."""
    s = sha.encode()[:40].ljust(40, b"0")
    return Pubkey.find_program_address([b"workflow", bytes([kind]), s[:20], s[20:]], pid)[0]


def set_workflow(pid: Pubkey, admin: Pubkey, sha: str, add: bool = True, kind: int = WF_PROVE) -> Instruction:
    """SetWorkflow (24, admin): add or remove an allowed job_workflow_sha (kind 0 prove.yml, 1 fund.yml)."""
    if len(sha) != 40 or any(c not in "0123456789abcdef" for c in sha):
        raise ValueError("a 40-hex lowercase commit sha")
    return Instruction(pid, bytes([24, kind, int(add)]) + sha.encode(),
                       [_m(admin, True, True), _m(config_pda(pid), False, False),
                        _m(workflow_pda(pid, sha, kind), False, True), _m(SYSTEM, False, False)])


def jwt_claims(jwt: str) -> dict:
    """The (unverified) payload of a JWT: the program checks it; clients read it to pick accounts."""
    import base64
    import json
    p = jwt.strip().split(".")[1]
    return json.loads(base64.urlsafe_b64decode(p + "=" * (-len(p) % 4)))


def verify_step2(pid: Pubkey, prover: Pubkey, job_id: bytes, key: Pubkey, vault_token: Pubkey, worker_token: Pubkey,
                 fee_token: Pubkey, buyer: Pubkey, workflow_sha: str = "0" * 40, mint: Pubkey | None = None) -> Instruction:
    """VerifyStep2 (18): 8 squarings, * s, the PKCS#1 v1.5 check and the claims; on success the worker is paid and the
    job and the buffer close."""
    return Instruction(pid, bytes([18]) + job_id,
                       [_m(prover, True, True), _m(gh_buffer_pda(pid, job_id, prover), False, True),
                        _m(key, False, False), _m(job_pda(pid, job_id), False, True), _m(vault_token, False, True),
                        _m(vault_authority(pid, mint), False, False), _m(worker_token, False, True),
                        _m(fee_token, False, True), _m(buyer, False, True), _m(config_pda(pid), False, False),
                        _m(TOKEN, False, False), _m(workflow_pda(pid, workflow_sha), False, False)])


def post_github(pid: Pubkey, buyer: Pubkey, job_id: bytes, amount: int, work_s: int, review_s: int, brief_hash: bytes,
                repository: str, ref: str, buyer_token: Pubkey, vault_token: Pubkey, checks_hash: bytes = bytes(32),
                stake_required: bool = False) -> Instruction:
    """PostGithub (19): a job paid on a GitHub Actions proof for `repository` at `ref`. amount 0 = a bounty with no
    money (the claim stake only)."""
    import hashlib
    if len(job_id) != 32 or len(brief_hash) != 32:
        raise ValueError("job id and brief hash are 32 bytes")
    data = bytes([19]) + job_id + struct.pack("<Qqq", amount, work_s, review_s) + brief_hash + \
        hashlib.sha256(repository.encode()).digest() + hashlib.sha256(ref.encode()).digest() + checks_hash + \
        bytes([int(stake_required)])
    if len(checks_hash) != 32:
        raise ValueError("checks hash is 32 bytes")
    return Instruction(pid, data, [_m(buyer, True, True), _m(job_pda(pid, job_id), False, True),
                                   _m(buyer_token, False, True), _m(vault_token, False, True),
                                   _m(config_pda(pid), False, False), _m(TOKEN, False, False),
                                   _m(SYSTEM, False, False)])
