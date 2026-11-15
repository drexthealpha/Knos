"""Agent budgets enforced by Solana's Token program: an SPL delegate on one vault per agent.

Each agent gets its own vault: a plain (non-associated) token account owned by the team's vault key, which is
encrypted at rest. The vault key approves the agent's key as delegate for at most N tokens (`ApproveChecked`). The
agent pays with `TransferChecked` signed by its own key as delegate; the Token program refuses anything beyond the
delegated amount, whatever the agent's software does. A token account holds one delegate, which is why each agent
has its own vault. `Revoke` ends it.

Instruction layouts are the SPL Token program's (github.com/solana-program/token, program/src/instruction.rs):
InitializeAccount3 = 18, ApproveChecked = 13, TransferChecked = 12, MintToChecked = 14, Revoke = 5,
InitializeMint2 = 20. SPL Token, the associated-token program and Memo are in every validator's genesis.
"""

from __future__ import annotations

import struct

from solders.instruction import AccountMeta, Instruction
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.system_program import CreateAccountParams, create_account

TOKEN_PROGRAM = Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")
ATA_PROGRAM = Pubkey.from_string("ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL")
MEMO_PROGRAM = Pubkey.from_string("MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr")
MINT_SIZE, ACCOUNT_SIZE = 82, 165
USDC = {"mainnet": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
        "devnet": "4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU"}


def _ix(accounts: list[tuple[Pubkey, bool, bool]], data: bytes, program: Pubkey = TOKEN_PROGRAM) -> Instruction:
    return Instruction(program, data, [AccountMeta(k, is_signer=s, is_writable=w) for k, s, w in accounts])


def initialize_mint2(mint: Pubkey, decimals: int, authority: Pubkey) -> Instruction:
    return _ix([(mint, False, True)], bytes([20, decimals]) + bytes(authority) + b"\x00")


def initialize_account3(account: Pubkey, mint: Pubkey, owner: Pubkey) -> Instruction:
    return _ix([(account, False, True), (mint, False, False)], bytes([18]) + bytes(owner))


def mint_to_checked(mint: Pubkey, dest: Pubkey, authority: Pubkey, amount: int, decimals: int) -> Instruction:
    return _ix([(mint, False, True), (dest, False, True), (authority, True, False)],
               bytes([14]) + struct.pack("<QB", amount, decimals))


def approve_checked(source: Pubkey, mint: Pubkey, delegate: Pubkey, owner: Pubkey, amount: int,
                    decimals: int) -> Instruction:
    return _ix([(source, False, True), (mint, False, False), (delegate, False, False), (owner, True, False)],
               bytes([13]) + struct.pack("<QB", amount, decimals))


def transfer_checked(source: Pubkey, mint: Pubkey, dest: Pubkey, authority: Pubkey, amount: int,
                     decimals: int) -> Instruction:
    return _ix([(source, False, True), (mint, False, False), (dest, False, True), (authority, True, False)],
               bytes([12]) + struct.pack("<QB", amount, decimals))


def revoke(source: Pubkey, owner: Pubkey) -> Instruction:
    return _ix([(source, False, True), (owner, True, False)], bytes([5]))


def memo(text: str, signer: Pubkey | None = None) -> Instruction:
    return _ix([(signer, True, False)] if signer else [], text.encode(), program=MEMO_PROGRAM)


def ata(owner: Pubkey, mint: Pubkey) -> Pubkey:
    return Pubkey.find_program_address([bytes(owner), bytes(TOKEN_PROGRAM), bytes(mint)], ATA_PROGRAM)[0]


def create_ata_idempotent(payer: Pubkey, owner: Pubkey, mint: Pubkey) -> Instruction:
    return _ix([(payer, True, True), (ata(owner, mint), False, True), (owner, False, False), (mint, False, False),
                (Pubkey.from_string("11111111111111111111111111111111"), False, False), (TOKEN_PROGRAM, False, False)],
               bytes([1]), program=ATA_PROGRAM)


def parse_token_account(raw: bytes) -> dict:
    """mint, owner, amount, delegate (or None), delegated_amount: the SPL token account layout."""
    if len(raw) < ACCOUNT_SIZE:
        raise ValueError("not a token account")
    mint, owner = Pubkey.from_bytes(raw[0:32]), Pubkey.from_bytes(raw[32:64])
    (amount,) = struct.unpack_from("<Q", raw, 64)
    (has_delegate,) = struct.unpack_from("<I", raw, 72)
    delegate = Pubkey.from_bytes(raw[76:108]) if has_delegate else None
    (delegated,) = struct.unpack_from("<Q", raw, 121)
    return {"mint": mint, "owner": owner, "amount": amount, "delegate": delegate, "delegated_amount": delegated}


def new_vault_ixs(url: str, payer: Pubkey, vault_owner: Pubkey, vault: Keypair, mint: Pubkey) -> list[Instruction]:
    """A fresh non-ATA token account owned by the vault key: one per agent, because each holds one delegate."""
    from knos.team import rpc
    lamports = rpc.call(url, "getMinimumBalanceForRentExemption", [ACCOUNT_SIZE])
    return [create_account(CreateAccountParams(from_pubkey=payer, to_pubkey=vault.pubkey(), lamports=lamports,
                                               space=ACCOUNT_SIZE, owner=TOKEN_PROGRAM)),
            initialize_account3(vault.pubkey(), mint, vault_owner)]


def status(url: str, vault: Pubkey) -> dict:
    from knos.team import rpc
    _, raw = rpc.account_data(url, vault)
    if raw is None:
        raise LookupError("vault not found")
    return parse_token_account(raw)
