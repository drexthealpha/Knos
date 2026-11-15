"""Test harness for knos-meter (programs-v2/knos_meter) inside LiteSVM, beside the second deployment's verifier: the
Chain of tests/_pay2.py (the verifier, the seed-derived signing key, SPL Token and Token-2022 mints, the clock) with
the meter's test build added. The build is tests/fixtures/knos_meter_test.so (`--features testkeys`: credits open in
any mint that passes the mint rules, and SetPlan also takes the test key below). Tests only."""
from __future__ import annotations

import re

from solders.account import Account
from solders.compute_budget import set_compute_unit_limit
from solders.keypair import Keypair
from solders.message import MessageV0
from solders.pubkey import Pubkey
from solders.transaction import VersionedTransaction

import _pay2
from _pay2 import FIX, WF_REPO, WF_SHA

from knos.settle.v2 import meter, oidc

# knos_meter 1.1, the batch mode: the client is knos.settle.v2.meter; these names are what the tests already import here
from knos.settle.v2.meter import (BATCH_ERRORS, E_BATCH, E_SEQ, LEDGER_LEN, MAX_BATCH, VERSION, BatchLedger, batch_audience, chain_hash,  # noqa: E402,F401
                                  claim_batch_ix, ledger_pda, merkle_root, read_ledger, record_batch_ix, version_ix)

PLAN_SETTER = Keypair.from_seed(bytes([7]) * 32)   # lib.rs TEST_FEE_OWNER: stands in for FEE_OWNER (a multisig vault) in a test build
BUYER, SELLER = 424242, 555000                     # GitHub owner ids: the buyer's organisation, the vendor
ORDER, POLICY = bytes([0xA1]) * 32, bytes([0xB2]) * 32
BUILD = "knos_meter_test.so"


class Ledger:
    """The part of knos.chain.Ledger a statement reads, over a Meter chain: history(address) gives the successful
    transactions that named an address, newest first, and logs(signature) what the programs logged in one."""
    def __init__(self, chain: "Meter"):
        self.chain = chain

    def history(self, address: Pubkey, most: int = 500):
        yield from self.chain.txs.get(address, [])[:most]

    def logs(self, signature: str) -> list[str]:
        return self.chain.tx_logs.get(signature, [])

    def account(self, address: Pubkey) -> bytes | None:
        return self.chain.data(address)

    def program_accounts(self, program: Pubkey, size: int | None = None, memcmp: dict[int, bytes] | None = None) -> list[tuple[Pubkey, bytes]]:
        """getProgramAccounts with its filters, over every address a transaction here has named."""
        out = []
        for address in self.chain.txs:
            a = self.chain.svm.get_account(address)
            if a is None or a.owner != program or (size is not None and len(a.data) != size):
                continue
            if all(bytes(a.data[off:off + len(raw)]) == raw for off, raw in (memcmp or {}).items()):
                out.append((address, bytes(a.data)))
        return out

    def now(self) -> int:
        return self.chain.now()


class Meter(_pay2.Chain):
    def __init__(self):
        assert (FIX / BUILD).is_file(), f"tests/fixtures/{BUILD} is missing: bash scripts/build_programs_v2.sh meter"
        self.txs: dict[Pubkey, list[str]] = {}        # address -> the transactions that named it and succeeded, newest first
        self.tx_logs: dict[str, list[str]] = {}
        super().__init__()
        assert meter.OIDC_ID == oidc.OIDC_ID          # the verifier whose token accounts the meter accepts
        self.svm.add_program_from_file(meter.METER_ID, str(FIX / BUILD))
        self.svm.airdrop(PLAN_SETTER.pubkey(), 10 ** 9)
        self.ledger = Ledger(self)

    def send(self, ixs, payer=None, signers=(), tag=None) -> bool:
        ixs = list(ixs)
        ok = super().send(ixs, payer, signers, tag)
        # what the meter's own instructions used, the programs they called included
        self.meter_cu = sum(int(m.group(1)) for m in (re.match(rf"Program {meter.METER_ID} consumed (\d+) of", line) for line in self.logs) if m)
        if ok:                                        # what getSignaturesForAddress and getTransaction would give a client
            sig = f"local{len(self.tx_logs)}"
            self.tx_logs[sig] = self.logs
            for key in {(payer or self.payer).pubkey(), *(a.pubkey for ix in ixs for a in ix.accounts)}:
                self.txs.setdefault(key, []).insert(0, sig)
        return ok

    @property
    def code(self) -> int | None:
        """The program's error number in the last failed transaction."""
        m = re.search(r"Custom\((\d+)\)", self.err or "")
        return int(m.group(1)) if m else None

    # -- credits -------------------------------------------------------------------------------------------------------
    def open(self, mint: Pubkey, owner_id: int = BUYER, amount: int = 0, authority: Keypair | None = None, wf_repo: str = WF_REPO,
             wf_sha: str = WF_SHA) -> tuple[Keypair, Pubkey]:
        """A wallet opens credits for `owner_id` and deposits `amount`. Returns (the wallet, the credits account)."""
        if authority is None:
            authority, _ = self.wallet(mint, amount)
        tp = self.token_program(mint)
        credits = meter.credits_pda(owner_id, authority.pubkey(), mint)
        assert self.send([meter.open_credits_ix(authority.pubkey(), owner_id, mint, wf_repo, wf_sha, tp)], authority), self.err
        if amount:
            decimals = self.svm.get_account(mint).data[44]
            assert self.send([meter.deposit_ix(meter.ata(authority.pubkey(), mint, tp), authority.pubkey(), credits, mint, amount, decimals, tp)],
                             authority), self.err
        return authority, credits

    def credits(self, credits: Pubkey) -> meter.Credits:
        return meter.read_credits(self.data(credits))

    def held(self, credits: Pubkey) -> int:
        return self.balance(meter.crtok_pda(credits))

    def fees(self, mint: Pubkey) -> int:
        """What FEE_OWNER's token account of the mint holds (created on first ask)."""
        return self.balance(self.token_account(meter.FEE_OWNER, mint))

    def set_used(self, owner_id: int, used: int, month: int | None = None) -> None:
        """Puts an owner's count of billable evaluations this month where the test needs it, by writing the Plan
        account as the program would have left it after that many: ten thousand verified tokens take too long."""
        addr = meter.plan_pda(owner_id)
        if self.data(addr) is None:
            bump = Pubkey.find_program_address([b"plan", owner_id.to_bytes(8, "little")], meter.METER_ID)[1]
            d = bytearray(meter.PLAN_LEN)
            d[0], d[1] = 1, bump
            d[8:16] = owner_id.to_bytes(8, "little")
        else:
            d = bytearray(self.data(addr))
        d[4:8] = (month or meter.yyyymm(self.now())).to_bytes(4, "little")
        d[32:40] = used.to_bytes(8, "little")
        self.svm.set_account(addr, Account(self.svm.minimum_balance_for_rent_exemption(meter.PLAN_LEN), bytes(d), meter.METER_ID))

    # -- evaluations -----------------------------------------------------------------------------------------------------
    def aud(self, artifact: str = "a" * 40, verdict: int = 1, rate: int = 2_000_000, buyer: int = BUYER, seller: int = SELLER, order: bytes = ORDER,
            policy: bytes = POLICY, milestone: int = 0) -> str:
        return meter.eval_audience(buyer, seller, order, artifact, policy, milestone, verdict, rate)

    def token(self, aud: str, file: str = "attest.yml", **over) -> Pubkey | None:
        """A verified token for this audience from a first run of the pinned workflow in a repository of the buyer."""
        claims = dict(repository_owner_id=int(aud.split(":")[2]), run_attempt=1)
        claims.update(over)
        return self.gh(aud, file=file, **claims)

    def record(self, credits: Pubkey, aud: str, token: Pubkey | None = None, relayer: Keypair | None = None, fee_token: Pubkey | None = None,
               **over) -> bool:
        """Relays one evaluation: a new verified token for `aud` (or `token`), then Record against `credits`."""
        token = token or self.token(aud, **over)
        assert token is not None, self.err
        r = relayer or self.payer
        return self.send([meter.record_ix(r.pubkey(), token, self.key_of(token), credits, self.credits(credits), aud, self.now(), fee_token)], r,
                         tag="record")

    # -- batches ---------------------------------------------------------------------------------------------------------
    def batch_aud(self, seq: int = 0, count: int = 5000, accepted: int = 4000, value: int = 8_000_000_000, root: bytes = bytes([0xAB]) * 32,
                  month: int | None = None, buyer: int = BUYER, seller: int = SELLER, kind: str = "batch") -> str:
        return batch_audience(buyer, seller, month or meter.yyyymm(self.now()), seq, count, accepted, value, root, kind)

    def batch(self, credits: Pubkey, aud: str, token: Pubkey | None = None, relayer: Keypair | None = None, **over) -> bool:
        """Relays one batch: a new verified token for `aud` from a run of the buyer (or `token`), then RecordBatch."""
        claims = dict(repository_owner_id=int(aud.split(":")[2]), run_attempt=1)
        claims.update(over)
        token = token or self.gh(aud, file=claims.pop("file", "attest.yml"), **claims)
        assert token is not None, self.err
        r = relayer or self.payer
        return self.send([record_batch_ix(r.pubkey(), token, self.key_of(token), credits, self.credits(credits), aud)], r, tag="batch")

    def claim(self, aud: str, token: Pubkey | None = None, relayer: Keypair | None = None, **over) -> bool:
        """Relays the seller's claim: a new verified token for `aud` from a run in a repository of the seller (or `token`)."""
        claims = dict(repository_owner_id=int(aud.split(":")[3]))
        claims.update(over)
        token = token or self.gh(aud, **claims)
        assert token is not None, self.err
        r = relayer or self.payer
        return self.send([claim_batch_ix(r.pubkey(), token, self.key_of(token), aud)], r, tag="claim")

    def book(self, claim: bool = False, buyer: int = BUYER, seller: int = SELLER, month: int | None = None) -> BatchLedger | None:
        return read_ledger(self.data(ledger_pda(buyer, seller, month or meter.yyyymm(self.now()), claim)))

    def close(self, marks, payer: Keypair, fee_payer: Keypair | None = None) -> bool:
        """CloseMark for each of `marks`, in one transaction that `payer` (the relayer the marks name) signs."""
        return self.send([meter.close_mark_ix(payer.pubkey(), m) for m in marks], fee_payer or payer, signers=[payer], tag="close")

    def close_size(self, marks, payer: Keypair) -> int:
        """The bytes of the transaction `close` would send (a cluster takes at most 1232; LiteSVM does not look)."""
        msg = MessageV0.try_compile(payer.pubkey(), [set_compute_unit_limit(1_400_000), *(meter.close_mark_ix(payer.pubkey(), m) for m in marks)], [],
                                    self.svm.latest_blockhash())
        return len(bytes(VersionedTransaction(msg, [payer])))

    def lamports(self, address: Pubkey) -> int:
        return self.svm.get_balance(address) or 0

    def month(self, buyer: int = BUYER, seller: int = SELLER, month: int | None = None) -> meter.Statement:
        month = month or meter.yyyymm(self.now())
        return meter.read_month(self.data(meter.month_pda(buyer, seller, month)), buyer, seller, month)
