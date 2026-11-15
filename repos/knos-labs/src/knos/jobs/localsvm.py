"""The escrow program in-process: LiteSVM (solders) with the real SPL Token program and `knos_escrow.so`.

Used by the test suite, the promise suite and `knos bench jobs`: every job path runs in the Solana runtime in
milliseconds, with no validator and no network. `expire_blockhash()` after each transaction instead of sleeping.
"""

from __future__ import annotations

import hashlib
import struct
from pathlib import Path

from solders.instruction import AccountMeta, Instruction
from solders.keypair import Keypair
from solders.message import MessageV0
from solders.pubkey import Pubkey
from solders.system_program import CreateAccountParams, create_account
from solders.transaction import VersionedTransaction

from . import sol

SO_CANDIDATES = [Path(__file__).resolve().parent / "knos_escrow.so"]   # built from programs/knos_escrow


def program_so() -> Path:
    for p in SO_CANDIDATES:
        if p.exists():
            return p
    raise FileNotFoundError("knos_escrow.so not found next to knos/jobs/localsvm.py (build programs/knos_escrow)")


class Escrow:
    """A fresh runtime with the escrow deployed, a USDC-like mint (6 decimals), the vault, and funded parties."""

    DEC = 6

    def __init__(self, fee_bps: int = 500, min_fee: int = sol.MIN_FEE_UNITS, min_amount: int = sol.MIN_JOB_UNITS,
                 max_amount: int = 0, paused: bool = False):
        from solders.litesvm import LiteSVM
        self.svm = LiteSVM()
        self.accounts: dict[bytes, Pubkey] = {}   # owner -> token account (what an ATA is on a real cluster)
        self.known_jobs: list[bytes] = []         # LiteSVM has no getProgramAccounts; the market records ids here
        self.pid = Keypair().pubkey()
        self.svm.add_program_from_file(self.pid, str(program_so()))
        self.admin = self.keypair()
        self.mint = Keypair()
        assert self.send([create_account(CreateAccountParams(
            from_pubkey=self.admin.pubkey(), to_pubkey=self.mint.pubkey(),
            lamports=self.svm.minimum_balance_for_rent_exemption(82), space=82, owner=sol.TOKEN)),
            self._tix([20, self.DEC] + list(bytes(self.admin.pubkey())) + [0], [(self.mint.pubkey(), False, True)])],
            self.admin, [self.admin, self.mint])
        self.vault = self.token_account(sol.vault_authority(self.pid))
        self.fee_token = self.token_account(self.admin.pubkey())
        self.accounts[bytes(self.admin.pubkey())] = self.fee_token
        assert self.send([sol.init2(self.pid, self.admin.pubkey(), self.fee_token, fee_bps, min_fee, min_amount,
                                    max_amount, paused)], self.admin, [self.admin])

    # -- runtime -----------------------------------------------------------------------------------------------------
    def keypair(self, lamports: int = 100_000_000_000) -> Keypair:
        k = Keypair()
        self.svm.airdrop(k.pubkey(), lamports)
        return k

    def send(self, ixs, payer: Keypair, signers) -> bool:
        msg = MessageV0.try_compile(payer.pubkey(), ixs, [], self.svm.latest_blockhash())
        r = self.svm.send_transaction(VersionedTransaction(msg, signers))
        self.svm.expire_blockhash()
        ok = type(r).__name__ == "TransactionMetadata"
        meta = r if ok else getattr(r, "meta", lambda: None)()
        self.last_cu = meta.compute_units_consumed() if meta is not None and callable(getattr(meta, "compute_units_consumed", None)) else getattr(meta, "compute_units_consumed", None)
        self.last_logs = list(meta.logs() if callable(getattr(meta, "logs", None)) else getattr(meta, "logs", []) or []) if meta is not None else []
        return ok

    # -- tokens --------------------------------------------------------------------------------------------------------
    def _tix(self, data, metas) -> Instruction:
        return Instruction(sol.TOKEN, bytes(data), [AccountMeta(k, is_signer=s, is_writable=w) for k, s, w in metas])

    def token_account(self, owner: Pubkey, mint: Pubkey | None = None) -> Pubkey:
        a = Keypair()
        m = mint or self.mint.pubkey()
        assert self.send([create_account(CreateAccountParams(
            from_pubkey=self.admin.pubkey(), to_pubkey=a.pubkey(),
            lamports=self.svm.minimum_balance_for_rent_exemption(165), space=165, owner=sol.TOKEN)),
            self._tix([18] + list(bytes(owner)), [(a.pubkey(), False, True), (m, False, False)])],
            self.admin, [self.admin, a])
        return a.pubkey()

    def mint_to(self, account: Pubkey, units: int) -> None:
        assert self.send([self._tix([7] + list(struct.pack("<Q", units)),
                                    [(self.mint.pubkey(), False, True), (account, False, True),
                                     (self.admin.pubkey(), True, False)])], self.admin, [self.admin])

    def balance(self, account: Pubkey) -> int:
        acc = self.svm.get_account(account)
        return struct.unpack("<Q", bytes(acc.data)[64:72])[0] if acc else 0

    def party(self, units: int = 0) -> tuple[Keypair, Pubkey]:
        k = self.keypair()
        t = self.token_account(k.pubkey())
        self.accounts[bytes(k.pubkey())] = t
        if units:
            self.mint_to(t, units)
        return k, t

    # -- jobs ----------------------------------------------------------------------------------------------------------
    def job(self, job_id: bytes) -> sol.Job | None:
        acc = self.svm.get_account(sol.job_pda(self.pid, job_id))
        if acc is None or len(bytes(acc.data)) not in sol.JOB_LENS:
            return None                       # never posted, or settled: a settlement closes the job account
        return sol.parse_job(sol.job_pda(self.pid, job_id), bytes(acc.data))

    STAKE_FLOAT = 10 ** 12   # what the in-process faucet gives each worker's stake account (test runtime only)

    def stake_account(self, owner: Pubkey) -> Pubkey:
        """The token account a worker stakes from and gets its stake back to. In this runtime it is a separate,
        faucet-funded account per worker, so a party's own account shows only what jobs paid it; on a cluster it is
        the worker's ATA (market.stake_account_for)."""
        got = self.stake_accounts.get(bytes(owner)) if hasattr(self, "stake_accounts") else None
        if got is None:
            if not hasattr(self, "stake_accounts"):
                self.stake_accounts = {}
            got = self.token_account(owner)
            self.mint_to(got, self.STAKE_FLOAT)
            self.stake_accounts[bytes(owner)] = got
        return got

    def lamports(self, address: Pubkey) -> int:
        acc = self.svm.get_account(address)
        return acc.lamports if acc else 0

    def _tok(self, owner: Pubkey) -> Pubkey:
        return self.accounts[bytes(owner)]

    def post(self, buyer: Keypair, buyer_token: Pubkey, job_id: bytes, amount: int, work: int = 600,
             review: int = 40, brief: bytes = b"", vault: Pubkey | None = None, verifier: Pubkey | None = None) -> bool:
        return self.send([sol.post(self.pid, buyer.pubkey(), job_id, amount, work, review,
                                   hashlib.sha256(b"brief" + brief + job_id).digest(), buyer_token,
                                   vault or self.vault, verifier)], buyer, [buyer])

    def claim(self, worker: Keypair, job_id: bytes, worker_token: Pubkey | None = None) -> bool:
        """Claim, staking from `worker_token` (default: the worker's faucet-funded stake account)."""
        wt = worker_token or self.stake_account(worker.pubkey())
        return self.send([sol.claim(self.pid, worker.pubkey(), job_id, wt, self.vault)], worker, [worker])

    @staticmethod
    def result_hash(job_id: bytes, result: bytes = b"result") -> bytes:
        return hashlib.sha256(result + job_id).digest()

    def deliver(self, worker: Keypair, job_id: bytes, result: bytes = b"result",
                worker_token: Pubkey | None = None) -> bool:
        wt = worker_token or self.stake_account(worker.pubkey())
        return self.send([sol.deliver(self.pid, worker.pubkey(), job_id, self.result_hash(job_id, result), wt,
                                      self.vault)], worker, [worker])

    def _buyer_of(self, job_id: bytes, buyer: Pubkey | None) -> Pubkey:
        if buyer is not None:
            return buyer
        j = self.job(job_id)
        return j.buyer if j else Pubkey.default()

    def accept(self, who: Keypair, job_id: bytes, worker_token: Pubkey, fee_token: Pubkey | None = None,
               release: bool = False, buyer: Pubkey | None = None) -> bool:
        b = self._buyer_of(job_id, buyer) if release else (buyer or who.pubkey())
        return self.send([sol.settle(self.pid, who.pubkey(), job_id, self.vault, worker_token,
                                     fee_token or self.fee_token, release, b)], who, [who])

    def verify_reject(self, verifier: Keypair, job_id: bytes, buyer_token: Pubkey, proof_root: bytes = bytes(32),
                      buyer: Pubkey | None = None) -> bool:
        return self.send([sol.verify_reject(self.pid, verifier.pubkey(), job_id, proof_root, self.vault, buyer_token,
                                            self._buyer_of(job_id, buyer))], verifier, [verifier])

    def settle(self, who: Keypair, job_id: bytes, worker_token: Pubkey | None = None,
               buyer_token: Pubkey | None = None, fee_token: Pubkey | None = None,
               buyer: Pubkey | None = None) -> bool:
        """The deadline crank (anyone). Token accounts default to the job's own parties'."""
        j = self.job(job_id)
        b = self._buyer_of(job_id, buyer)
        bt = buyer_token or self.accounts.get(bytes(b)) or self.fee_token
        wt = worker_token or (self.accounts.get(bytes(j.worker)) if j and j.worker else None) or bt
        return self.send([sol.crank(self.pid, who.pubkey(), job_id, self.vault, wt, fee_token or self.fee_token, bt,
                                    b)], who, [who])

    def verify_release(self, verifier: Keypair, job_id: bytes, worker_token: Pubkey, result_hash: bytes | None = None,
                       proof_root: bytes = b"" * 32, fee_token: Pubkey | None = None) -> bool:
        """Paid on proof. `result_hash` defaults to the hash `deliver()` commits for the default result."""
        return self.send([sol.verify_release(self.pid, verifier.pubkey(), job_id,
                                             result_hash or self.result_hash(job_id), proof_root, self.vault,
                                             worker_token, fee_token or self.fee_token,
                                             self._buyer_of(job_id, None))], verifier, [verifier])

    def set_pause(self, paused: bool, admin: Keypair | None = None) -> bool:
        a = admin or self.admin
        return self.send([sol.set_pause(self.pid, a.pubkey(), paused)], a, [a])

    def lower_cap(self, max_amount: int, admin: Keypair | None = None) -> bool:
        a = admin or self.admin
        return self.send([sol.lower_cap(self.pid, a.pubkey(), max_amount)], a, [a])

    def lower_fee(self, fee_bps: int, admin: Keypair | None = None) -> bool:
        a = admin or self.admin
        return self.send([sol.lower_fee(self.pid, a.pubkey(), fee_bps)], a, [a])

    def config(self) -> dict:
        return sol.parse_config(bytes(self.svm.get_account(sol.config_pda(self.pid)).data))

    def reject(self, who: Keypair, job_id: bytes, buyer_token: Pubkey) -> bool:
        return self.send([sol.reject(self.pid, who.pubkey(), job_id, self.vault, buyer_token)], who, [who])

    def refund(self, who: Keypair, job_id: bytes, buyer_token: Pubkey) -> bool:
        return self.send([sol.refund(self.pid, who.pubkey(), job_id, self.vault, buyer_token)], who, [who])
