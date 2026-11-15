"""Squads v4 (Squads Labs' deployed program, fetched by scripts/squads_program.py and never committed) inside LiteSVM,
beside the test builds of knos_pay and knos-oidc: a controlled multisig, its vault, spending limits, and vault
transactions proposed, voted and executed, with the instructions written byte for byte from the program's IDL
(sdk/multisig/idl/squads_multisig_program.json of Squads-Protocol/v4). Tests only."""
from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path

from solders.account import Account
from solders.instruction import AccountMeta, Instruction
from solders.keypair import Keypair
from solders.pubkey import Pubkey

from _order import OrderChain

from knos.settle.v2 import pay

_spec = importlib.util.spec_from_file_location("squads_program", Path(__file__).resolve().parents[1] / "scripts" / "squads_program.py")
squads_program = importlib.util.module_from_spec(_spec)                     # type: ignore[arg-type]
_spec.loader.exec_module(squads_program)                                    # type: ignore[union-attr]

SQUADS = Pubkey.from_string(squads_program.PROGRAM)
SYSTEM = Pubkey.from_string("11111111111111111111111111111111")
INITIATE, VOTE, EXECUTE = 1, 2, 4
ONCE, DAY, WEEK, MONTH = 0, 1, 2, 3


def available() -> bool:
    return squads_program.ok(squads_program.default_path())


def _disc(kind: str, name: str) -> bytes:
    return hashlib.sha256(f"{kind}:{name}".encode()).digest()[:8]


def _u8(n: int) -> bytes:
    return n.to_bytes(1, "little")


def _u16(n: int) -> bytes:
    return n.to_bytes(2, "little")


def _u32(n: int) -> bytes:
    return n.to_bytes(4, "little")


def _u64(n: int) -> bytes:
    return n.to_bytes(8, "little")


def _vec(items: list[bytes]) -> bytes:
    return _u32(len(items)) + b"".join(items)


NONE = b"\x00"


def _pda(*seeds: bytes) -> Pubkey:
    return Pubkey.find_program_address([b"multisig", *seeds], SQUADS)[0]


def program_config() -> Pubkey:
    return _pda(b"program_config")


def multisig_pda(create_key: Pubkey) -> Pubkey:
    return _pda(b"multisig", bytes(create_key))


def vault_pda(ms: Pubkey, index: int = 0) -> Pubkey:
    return _pda(bytes(ms), b"vault", _u8(index))


def transaction_pda(ms: Pubkey, index: int) -> Pubkey:
    return _pda(bytes(ms), b"transaction", _u64(index))


def proposal_pda(ms: Pubkey, index: int) -> Pubkey:
    return _pda(bytes(ms), b"transaction", _u64(index), b"proposal")


def spending_limit_pda(ms: Pubkey, create_key: Pubkey) -> Pubkey:
    return _pda(bytes(ms), b"spending_limit", bytes(create_key))


def compile_message(vault: Pubkey, ixs: list[Instruction]) -> tuple[bytes, list[AccountMeta]]:
    """Squads' TransactionMessage for `ixs` with the vault as the paying signer, and the accounts VaultTransactionExecute
    then takes, in the message's order: signers that write, signers, writers, the rest."""
    flags: dict[bytes, list] = {bytes(vault): [vault, True, True]}
    for ix in ixs:
        for a in ix.accounts:
            f = flags.setdefault(bytes(a.pubkey), [a.pubkey, False, False])
            f[1] = f[1] or a.is_signer
            f[2] = f[2] or a.is_writable
        flags.setdefault(bytes(ix.program_id), [ix.program_id, False, False])
    keys = sorted(flags.values(), key=lambda f: (not f[1], not f[2]))
    keys = [flags[bytes(vault)]] + [k for k in keys if k[0] != vault]
    index = {bytes(k[0]): i for i, k in enumerate(keys)}
    signers = [k for k in keys if k[1]]
    body = (_u8(len(signers)) + _u8(sum(1 for k in signers if k[2])) + _u8(sum(1 for k in keys if not k[1] and k[2]))
            + _u8(len(keys)) + b"".join(bytes(k[0]) for k in keys) + _u8(len(ixs)))
    for ix in ixs:
        accs = [index[bytes(a.pubkey)] for a in ix.accounts]
        body += _u8(index[bytes(ix.program_id)]) + _u8(len(accs)) + bytes(accs) + _u16(len(bytes(ix.data))) + bytes(ix.data)
    body += _u8(0)                                      # no address lookup tables
    return body, [AccountMeta(k[0], False, k[2]) for k in keys]


class SquadsChain(OrderChain):
    """The work-order chain of tests/_order.py with Squads v4 beside it, and its program config (no creation fee)."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.svm.add_program_from_file(SQUADS, str(squads_program.default_path()))
        self.treasury = Keypair().pubkey()
        data = _disc("account", "ProgramConfig") + bytes(Keypair().pubkey()) + _u64(0) + bytes(self.treasury) + bytes(64)
        rent = self.svm.minimum_balance_for_rent_exemption(len(data))
        self.svm.set_account(program_config(), Account(rent, data, SQUADS, False, 0))
        self.messages: dict[tuple[bytes, int], list[AccountMeta]] = {}

    def squads_ok(self, ix: Instruction, *signers: Keypair) -> bool:
        return self.send([ix], self.payer, signers=list(signers), mark=False)

    def create(self, members: list[tuple[Keypair, int]], threshold: int, config_authority: Pubkey, time_lock: int = 0) -> Pubkey:
        create_key = Keypair()
        ms = multisig_pda(create_key.pubkey())
        args = (b"\x01" + bytes(config_authority) + _u16(threshold)
                + _vec([bytes(k.pubkey()) + _u8(mask) for k, mask in sorted(members, key=lambda m: bytes(m[0].pubkey()))])
                + _u32(time_lock) + NONE + NONE)
        ix = Instruction(SQUADS, _disc("global", "multisig_create_v2") + args, [
            AccountMeta(program_config(), False, False), AccountMeta(self.treasury, False, True), AccountMeta(ms, False, True),
            AccountMeta(create_key.pubkey(), True, False), AccountMeta(self.payer.pubkey(), True, True), AccountMeta(SYSTEM, False, False)])
        assert self.squads_ok(ix, create_key), self.err
        return ms

    def add_spending_limit(self, ms: Pubkey, authority: Keypair, mint: Pubkey, amount: int, period: int, members: list[Pubkey],
                           destinations: list[Pubkey], vault_index: int = 0) -> Pubkey | None:
        create_key = Keypair().pubkey()
        sl = spending_limit_pda(ms, create_key)
        args = (bytes(create_key) + _u8(vault_index) + bytes(mint) + _u64(amount) + _u8(period)
                + _vec([bytes(m) for m in members]) + _vec([bytes(d) for d in destinations]) + NONE)
        ix = Instruction(SQUADS, _disc("global", "multisig_add_spending_limit") + args, [
            AccountMeta(ms, False, False), AccountMeta(authority.pubkey(), True, False), AccountMeta(sl, False, True),
            AccountMeta(self.payer.pubkey(), True, True), AccountMeta(SYSTEM, False, False)])
        return sl if self.squads_ok(ix, authority) else None

    def use_spending_limit(self, ms: Pubkey, sl: Pubkey, member: Keypair, mint: Pubkey, destination: Pubkey, amount: int, vault_index: int = 0) -> bool:
        vault = vault_pda(ms, vault_index)
        ix = Instruction(SQUADS, _disc("global", "spending_limit_use") + _u64(amount) + _u8(6) + NONE, [
            AccountMeta(ms, False, False), AccountMeta(member.pubkey(), True, False), AccountMeta(sl, False, True), AccountMeta(vault, False, True),
            AccountMeta(destination, False, True), AccountMeta(SYSTEM, False, False), AccountMeta(mint, False, False),
            AccountMeta(pay.ata(vault, mint), False, True), AccountMeta(pay.ata(destination, mint), False, True), AccountMeta(pay.TOKEN, False, False)])
        return self.squads_ok(ix, member)

    def change_threshold(self, ms: Pubkey, signer: Keypair, threshold: int) -> bool:
        ix = Instruction(SQUADS, _disc("global", "multisig_change_threshold") + _u16(threshold) + NONE, [
            AccountMeta(ms, False, True), AccountMeta(signer.pubkey(), True, False), AccountMeta(self.payer.pubkey(), True, True),
            AccountMeta(SYSTEM, False, False)])
        return self.squads_ok(ix, signer)

    def config_change_threshold(self, ms: Pubkey, member: Keypair, threshold: int) -> bool:
        """A member proposes the change as a config transaction (what an autonomous multisig takes)."""
        index = self.next_index(ms)
        ix = Instruction(SQUADS, _disc("global", "config_transaction_create") + _vec([b"\x02" + _u16(threshold)]) + NONE, [
            AccountMeta(ms, False, True), AccountMeta(transaction_pda(ms, index), False, True), AccountMeta(member.pubkey(), True, False),
            AccountMeta(self.payer.pubkey(), True, True), AccountMeta(SYSTEM, False, False)])
        return self.squads_ok(ix, member)

    def next_index(self, ms: Pubkey) -> int:
        data = self.data(ms) or b""
        return int.from_bytes(data[8 + 32 + 32 + 2 + 4: 8 + 32 + 32 + 2 + 4 + 8], "little") + 1

    def threshold(self, ms: Pubkey) -> int:
        return int.from_bytes((self.data(ms) or b"")[8 + 64: 8 + 66], "little")

    def propose(self, ms: Pubkey, creator: Keypair, ixs: list[Instruction], vault_index: int = 0) -> int | None:
        """A vault transaction and its proposal, created by `creator`: the transaction's index, or None when refused."""
        index = self.next_index(ms)
        vault = vault_pda(ms, vault_index)
        message, accounts = compile_message(vault, ixs)
        create = Instruction(SQUADS, _disc("global", "vault_transaction_create") + _u8(vault_index) + _u8(0) + _u32(len(message)) + message + NONE, [
            AccountMeta(ms, False, True), AccountMeta(transaction_pda(ms, index), False, True), AccountMeta(creator.pubkey(), True, False),
            AccountMeta(self.payer.pubkey(), True, True), AccountMeta(SYSTEM, False, False)])
        proposal = Instruction(SQUADS, _disc("global", "proposal_create") + _u64(index) + b"\x00", [
            AccountMeta(ms, False, False), AccountMeta(proposal_pda(ms, index), False, True), AccountMeta(creator.pubkey(), True, False),
            AccountMeta(self.payer.pubkey(), True, True), AccountMeta(SYSTEM, False, False)])
        if not self.send([create, proposal], self.payer, signers=[creator], mark=False):
            return None
        self.messages[(bytes(ms), index)] = accounts
        return index

    def approve(self, ms: Pubkey, index: int, member: Keypair) -> bool:
        ix = Instruction(SQUADS, _disc("global", "proposal_approve") + NONE, [
            AccountMeta(ms, False, False), AccountMeta(member.pubkey(), True, True), AccountMeta(proposal_pda(ms, index), False, True)])
        return self.squads_ok(ix, member)

    def execute(self, ms: Pubkey, index: int, member: Keypair) -> bool:
        ix = Instruction(SQUADS, _disc("global", "vault_transaction_execute"), [
            AccountMeta(ms, False, False), AccountMeta(proposal_pda(ms, index), False, True), AccountMeta(transaction_pda(ms, index), False, False),
            AccountMeta(member.pubkey(), True, False), *self.messages[(bytes(ms), index)]])
        return self.squads_ok(ix, member)

    def said_error(self) -> str:
        """The Anchor error name of the last failed Squads instruction ("" when none is logged)."""
        for line in self.logs:
            if "Error Code: " in line:
                return line.split("Error Code: ", 1)[1].split(".", 1)[0]
        return ""
