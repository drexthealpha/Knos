"""programs-hook/knos_hook in LiteSVM (Token-2022 is built in): a project-credit mint with the TransferHook extension
pointing at the hook; its rules name the project's vault owner; a transfer into the vault's account passes, a transfer
to anyone else fails the transaction. Needs the built program (cargo build-sbf): KNOS_HOOK_SO, else skipped."""
import os
import struct
from pathlib import Path

import pytest
from solders.instruction import AccountMeta, Instruction
from solders.keypair import Keypair
from solders.litesvm import LiteSVM
from solders.message import Message
from solders.pubkey import Pubkey
from solders.system_program import CreateAccountParams, create_account
from solders.transaction import Transaction

# the build deployed on devnet at AFQFtodihz5jAHpVBUk87AkH8FJsQdmHt8Z5NKLWRj1T on 24 Oct 2026 (cargo build-sbf --tools-version
# v1.57 in programs-hook/knos_hook; 79,592 bytes, sha256 97b8f270...ef08b): Execute, InitializeExtraAccountMetaList, MintCredits
SO = Path(os.environ.get("KNOS_HOOK_SO") or Path(__file__).resolve().parents[3] / "programs-hook" / "knos_hook" / "deployed" / "knos_hook_devnet.so")
pytestmark = pytest.mark.skipif(not SO.exists(), reason="the hook program is not built here (cargo build-sbf programs-hook/knos_hook)")

TOKEN22 = Pubkey.from_string("TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb")
ATA = Pubkey.from_string("ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL")
SYSTEM = Pubkey.from_string("11111111111111111111111111111111")
EXECUTE = bytes([105, 37, 101, 197, 75, 251, 102, 26])
INIT = bytes([43, 34, 13, 49, 167, 88, 235, 235])
MINT_CREDITS = bytes([187, 99, 204, 115, 30, 116, 73, 210])
MINT_LEN = 234          # base mint padded to 165, account type 1, TransferHook TLV 2 + 2 + 64


def send(svm, ixs, payer, signers=()):
    tx = Transaction([payer, *signers], Message.new_with_blockhash(ixs, payer.pubkey(), svm.latest_blockhash()), svm.latest_blockhash())
    return svm.send_transaction(tx)


def logs(r) -> list[str]:
    m = r.meta() if callable(getattr(r, "meta", None)) else getattr(r, "meta", r)
    got = getattr(m, "logs", getattr(r, "logs", []))
    return list(got() if callable(got) else got)


def ata(owner, mint):
    return Pubkey.find_program_address([bytes(owner), bytes(TOKEN22), bytes(mint)], ATA)[0]


@pytest.fixture
def chain():
    svm = LiteSVM()
    hook = Keypair().pubkey()
    svm.add_program(hook, SO.read_bytes())
    payer, mint, escrow, stranger = Keypair(), Keypair(), Keypair(), Keypair()
    svm.airdrop(payer.pubkey(), 10_000_000_000)
    rent = svm.minimum_balance_for_rent_exemption(MINT_LEN)
    ixs = [create_account(CreateAccountParams(from_pubkey=payer.pubkey(), to_pubkey=mint.pubkey(), lamports=rent, space=MINT_LEN, owner=TOKEN22)),
           # TransferHookExtension::Initialize (36, 0): authority, the hook program
           Instruction(TOKEN22, bytes([36, 0]) + bytes(payer.pubkey()) + bytes(hook), [AccountMeta(mint.pubkey(), False, True)]),
           # InitializeMint2 (20): 0 decimals, mint authority payer, no freeze authority
           Instruction(TOKEN22, bytes([20, 0]) + bytes(payer.pubkey()) + bytes([0]) + bytes(32), [AccountMeta(mint.pubkey(), False, True)])]
    assert not hasattr(send(svm, ixs, payer, [mint]), "err")
    validation = Pubkey.find_program_address([b"extra-account-metas", bytes(mint.pubkey())], hook)[0]
    rules = Pubkey.find_program_address([b"rules", bytes(mint.pubkey())], hook)[0]
    init = Instruction(hook, INIT + bytes(escrow.pubkey()), [AccountMeta(validation, False, True), AccountMeta(mint.pubkey(), False, False),
                       AccountMeta(payer.pubkey(), True, True), AccountMeta(SYSTEM, False, False), AccountMeta(rules, False, True)])
    assert not hasattr(send(svm, [init], payer), "err")
    accts = {}
    for who in (payer, escrow, stranger):
        a = ata(who.pubkey(), mint.pubkey())
        accts[who.pubkey()] = a
        ix = Instruction(ATA, bytes([1]), [AccountMeta(payer.pubkey(), True, True), AccountMeta(a, False, True), AccountMeta(who.pubkey(), False, False),
                                          AccountMeta(mint.pubkey(), False, False), AccountMeta(SYSTEM, False, False), AccountMeta(TOKEN22, False, False)])
        assert not hasattr(send(svm, [ix], payer), "err")
    mint_to = Instruction(TOKEN22, bytes([7]) + struct.pack("<Q", 100), [AccountMeta(mint.pubkey(), False, True),
                          AccountMeta(accts[payer.pubkey()], False, True), AccountMeta(payer.pubkey(), True, False)])
    assert not hasattr(send(svm, [mint_to], payer), "err")
    return svm, hook, payer, mint.pubkey(), escrow, stranger, accts, validation, rules


def transfer(c, to, amount=10):
    svm, hook, payer, mint, _, _, accts, validation, rules = c
    ix = Instruction(TOKEN22, bytes([12]) + struct.pack("<QB", amount, 0),
                     [AccountMeta(accts[payer.pubkey()], False, True), AccountMeta(mint, False, False), AccountMeta(accts[to], False, True),
                      AccountMeta(payer.pubkey(), True, False), AccountMeta(rules, False, False), AccountMeta(hook, False, False),
                      AccountMeta(validation, False, False)])
    svm.expire_blockhash()
    return send(svm, [ix], payer)


def test_credits_move_only_into_the_escrow_the_rules_name(chain):
    svm, hook, payer, mint, escrow, stranger, accts, validation, rules = chain
    ok = transfer(chain, escrow.pubkey())
    assert not hasattr(ok, "err"), ok
    assert any(str(hook) in line for line in logs(ok))                                          # Token-2022 called the hook
    assert int.from_bytes(bytes(svm.get_account(accts[escrow.pubkey()]).data)[64:72], "little") == 10
    refused = transfer(chain, stranger.pubkey())
    assert hasattr(refused, "err") and "custom program error: 0x1" in " ".join(logs(refused))  # Custom(1): not allowed
    v = bytes(svm.get_account(validation).data)
    assert v[:8] == EXECUTE and v[17:49] == bytes(rules)                                     # the Execute TLV lists the rules account


def test_only_the_mint_authority_sets_the_rules(chain):
    svm, hook, payer, mint, escrow, stranger, accts, validation, rules = chain
    svm.airdrop(stranger.pubkey(), 1_000_000_000)
    again = Instruction(hook, INIT + bytes(stranger.pubkey()), [AccountMeta(validation, False, True), AccountMeta(mint, False, False),
                        AccountMeta(stranger.pubkey(), True, True), AccountMeta(SYSTEM, False, False), AccountMeta(rules, False, True)])
    assert hasattr(send(svm, [again], stranger), "err")


def test_a_lock_becomes_project_credits_held_in_the_escrow_through_the_hook(monkeypatch, tmp_path):
    """knos_wanted.chainx.project_credits on the hook at its devnet address: the credits land in the vault's account."""
    from test_chainx import Ledger

    from knos_wanted import chainx, escrow, preorder
    led, payer, owner = Ledger(), Keypair(), Keypair()
    led.svm.add_program(Pubkey.from_string(chainx.HOOK), SO.read_bytes())
    led.svm.airdrop(payer.pubkey(), 10_000_000_000)
    monkeypatch.setattr(preorder, "relayer", lambda: payer)
    monkeypatch.setattr(escrow, "_state_dir", lambda: tmp_path)
    monkeypatch.setattr(escrow, "demo_key", lambda: owner)
    monkeypatch.setattr(escrow, "explorer", lambda sig: "x")
    got = chainx.project_credits("prj_" + "a" * 12, "ORDER1", 7, led=led)
    assert chainx.project_credits("prj_" + "a" * 12, "ORDER1", 7, led=led) == got                 # once per order
    vault = bytes(led.svm.get_account(Pubkey.from_string(got["escrow_account"])).data)
    assert vault[32:64] == bytes(owner.pubkey()) and int.from_bytes(vault[64:72], "little") == 7
    c = chainx.credits_of("prj_" + "a" * 12)
    assert c["hook"] == chainx.HOOK and c["escrow_owner"] == str(owner.pubkey())
    md = bytes(led.svm.get_account(Pubkey.from_string(c["mint"])).data)
    assert md[:4] == b"\x01\x00\x00\x00" and md[4:36] == bytes(chainx._mint_authority(c["mint"]))    # the hook alone mints
    assert bytes(led.svm.get_account(Pubkey.from_string(c["rules"])).data)[:33] == b"" + bytes(owner.pubkey())   # version 1 | owner


def _hand_to_hook(c):
    svm, hook, payer, mint, *_ = c
    pda = Pubkey.find_program_address([b"mint-authority", bytes(mint)], hook)[0]
    ix = Instruction(TOKEN22, bytes([6, 0, 1]) + bytes(pda), [AccountMeta(mint, False, True), AccountMeta(payer.pubkey(), True, False)])
    svm.expire_blockhash()
    assert not hasattr(send(svm, [ix], payer), "err")
    return pda


def _mint(c, pda, dest, signer, amount=5):
    svm, hook, payer, mint, _, _, accts, validation, rules = c
    ix = Instruction(hook, MINT_CREDITS + struct.pack("<Q", amount),
                     [AccountMeta(mint, False, True), AccountMeta(accts[dest], False, True), AccountMeta(rules, False, False),
                      AccountMeta(pda, False, False), AccountMeta(signer.pubkey(), True, False), AccountMeta(TOKEN22, False, False)])
    svm.expire_blockhash()
    svm.airdrop(signer.pubkey(), 1_000_000_000)
    return send(svm, [ix], signer)


def test_the_hook_alone_mints_credits_and_only_into_the_escrow(chain):
    svm, hook, payer, mint, escrow, stranger, accts, validation, rules = chain
    pda = _hand_to_hook(chain)
    ok = _mint(chain, pda, escrow.pubkey(), escrow)
    assert not hasattr(ok, "err"), ok
    assert int.from_bytes(bytes(svm.get_account(accts[escrow.pubkey()]).data)[64:72], "little") == 5
    elsewhere = _mint(chain, pda, stranger.pubkey(), escrow)                                     # into anyone else's account
    assert hasattr(elsewhere, "err") and "custom program error: 0x1" in " ".join(logs(elsewhere))
    not_owner = _mint(chain, pda, escrow.pubkey(), stranger)                                     # signed by someone else
    assert hasattr(not_owner, "err") and "custom program error: 0x5" in " ".join(logs(not_owner))
    by_key = Instruction(TOKEN22, bytes([7]) + struct.pack("<Q", 1), [AccountMeta(mint, False, True),
                         AccountMeta(accts[payer.pubkey()], False, True), AccountMeta(payer.pubkey(), True, False)])
    svm.expire_blockhash()
    assert hasattr(send(svm, [by_key], payer), "err")                                            # the key that made the mint cannot
