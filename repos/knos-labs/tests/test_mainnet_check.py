"""knos mainnet-check, offline: every gate driven by injected fetchers."""

from __future__ import annotations

from solders.pubkey import Pubkey

from knos import mainnet_check as mc

PID = Pubkey.from_string(mc.PROGRAM)
MS = Pubkey.new_unique()
VAULT = mc.vault_pda(MS)
MINT = Pubkey.new_unique()
FEE = Pubkey.new_unique()
ELF = b"\x7fELF" + b"code" * 50 + mc.SECURITY_TXT + b"name: knos" + b"\x00" * 64


OUTSIDE = Pubkey.new_unique()


def world(*, authority=VAULT, lock=86_400, members=None, admin=VAULT, fee_owner=VAULT, elf=ELF, verified=None, idl=True,
          audit=(True, "clean")):
    pd = Pubkey.find_program_address([bytes(PID)], mc.LOADER)[0]
    cfg = Pubkey.find_program_address([b"config2"], PID)[0]
    if members is None:
        members = [Pubkey.from_string(k) for k in sorted(mc.KNOS_KEYS)][:2] + [OUTSIDE]
    multisig = (b"\x00" * 8 + bytes(32) + bytes(32) + (2).to_bytes(2, "little") + lock.to_bytes(4, "little")
                + bytes(16) + b"\x00" + b"\xff" + len(members).to_bytes(4, "little")
                + b"".join(bytes(m) + b"\x07" for m in members) + bytes(8))
    accts = {
        str(pd): ("BPFLoaderUpgradeab1e11111111111111111111111",
                  (3).to_bytes(4, "little") + bytes(8) + b"\x01" + bytes(authority) + elf),
        str(MS): (str(mc.SQUADS), multisig),
        str(cfg): (mc.PROGRAM, bytes(admin) + bytes(MINT) + bytes(FEE) + bytes(40)),
        str(FEE): (str(mc.TOKEN), bytes(MINT) + bytes(fee_owner) + bytes(100)),
    }
    if idl:
        accts[str(mc.idl_addresses(PID)[0])] = (str(mc.METADATA), b"idl")
    v = {"is_verified": True, "executable_hash": mc.elf_hash(elf)} if verified is None else verified
    return mc.Fetch(account=accts.get, verify=lambda _p: v, audit=lambda: audit)


def results(fetch, env=None):
    return {name: ok for name, ok, _ in mc.run(fetch, multisig=str(MS), env=env or {})}


def test_all_gates_pass_and_exit_zero():
    got = results(world())
    assert all(got.values()), got
    assert "mainnet: locked (by design)" in got
    lines: list[str] = []
    assert mc.main(lines.append, fetch=world(), multisig=str(MS)) == 0
    assert lines[-1].startswith("10/10")


def test_each_gate_fails_on_its_own():
    other = Pubkey.new_unique()
    cases = {
        "upgrade authority is a Squads v4 vault (time lock > 0)": [world(authority=other), world(lock=0)],
        "an outside signer is a member": [world(members=[Pubkey.from_string(k) for k in mc.KNOS_KEYS])],
        "time lock >= 86,400 s": [world(lock=300)],
        "escrow admin is the vault": [world(admin=other)],
        "fee account owned by the vault": [world(fee_owner=other)],
        "solana-verify hash == on-chain hash": [world(verified={"is_verified": True, "executable_hash": "ab" * 32}),
                                                world(verified={})],
        "security.txt in the on-chain binary": [world(elf=b"\x7fELF" + b"x" * 99)],
        "IDL account on chain": [world(idl=False)],
        "cargo-audit clean": [world(audit=(False, "RUSTSEC-2099-0001"))],
    }
    for gate, worlds in cases.items():
        for w in worlds:
            got = results(w)
            assert got[gate] is False, gate
            assert sum(not ok for ok in got.values()) == 1 or gate in (
                "security.txt in the on-chain binary", "upgrade authority is a Squads v4 vault (time lock > 0)"), (gate, got)


def test_mainnet_unlocked_fails_and_main_exits_one():
    got = mc.run(world(), multisig=str(MS), env={"KNOS_ALLOW_MAINNET": "1"})
    assert [ok for name, ok, _ in got if name.startswith("mainnet")] == [False]


def test_no_multisig_fails_and_hash_ignores_padding():
    got = results(world())
    assert got
    assert {n: ok for n, ok, _ in mc.run(world(), multisig="", env={})}[
        "upgrade authority is a Squads v4 vault (time lock > 0)"] is False
    assert mc.elf_hash(b"ab\x00\x00") == mc.elf_hash(b"ab")
    lines: list[str] = []
    assert mc.main(lines.append, fetch=world(idl=False), multisig=str(MS)) == 1
    assert "mainnet stays locked" in lines[-1]


def test_todays_devnet_multisig_fails_independence():
    """All 3 members are Knos keys and the lock is 300 s: both new gates FAIL, so mainnet stays locked."""
    got = results(world(members=[Pubkey.from_string(k) for k in mc.KNOS_KEYS], lock=300))
    assert got["an outside signer is a member"] is False
    assert got["time lock >= 86,400 s"] is False
    assert mc.multisig_members(b"") == []
