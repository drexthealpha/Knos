"""Write tests/fixtures/governance_v2.json: what scripts/governance.mjs must agree with, produced by the Python client (the
authority, src/knos/settle/v2) and by knos.mainnet_check, so the Node script is tested offline against them.

    the addresses      the multisig and the vault each create key gives, derived here with solders and checked against
                       programs-v2/program_ids.json; governance.mjs derives them with the Squads SDK and must get the same
    the instructions   the guardian's Approve, Revoke and Pause as oidc.approve_ix / revoke_ix and pay.pause_ix build them
                       (program, data, accounts with their signer and writable flags), and the upgradeable loader's Upgrade
                       as the loader's source lays it out; governance.mjs puts these in a vault transaction
    two accounts       the Multisig accounts the Squads v4 program itself wrote when governance.mjs created the two multisigs
                       on a fork of mainnet-beta (the real program, 2 Oct 2026; three throwaway members), and what
                       knos.mainnet_check.read_multisig reads in them: the Squads SDK's own deserialiser must read the same
    loader accounts    a ProgramData account (with and without an upgrade authority) and a Buffer account as the upgradeable
                       loader lays them out, with what knos.mainnet_check.program_data reads in them and the executable hash
                       of their bytes: governance.mjs reads the same and hashes the same

The create keys' PUBLIC keys are in here: they give the pinned addresses and nothing else. Their secret files stay in the
key folder (never in this repository).

    python scripts/governance_fixture.py            # write the file
    python scripts/governance_fixture.py --check    # exit 1 if the file on disk is not what this writes
"""
import json
import sys
from pathlib import Path

from solders.instruction import AccountMeta, Instruction
from solders.pubkey import Pubkey

from knos import mainnet_check as mc
from knos.settle.v2 import oidc, pay

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "tests" / "fixtures" / "governance_v2.json"
IDS = json.loads((ROOT / "programs-v2" / "program_ids.json").read_text(encoding="utf-8"))
CREATE_KEYS = {"upgrade": "5fB4D2wEWok6LtNbR5hbSPGSHEkNbnaZ1tGv4spjaBHe", "guardian": "GPm6TNgv8oNpLwvyPY1PjjxwZj3d4b8uRgZJpF9QirMM"}
LOADER = mc.LOADER
SYSVAR_RENT = Pubkey.from_string("SysvarRent111111111111111111111111111111111")
SYSVAR_CLOCK = Pubkey.from_string("SysvarC1ock11111111111111111111111111111111")
N2048 = (1 << 2047) | 0x1234567      # an odd 2048-bit number: only its hash matters here
PAYER, BUFFER, SPILL = (Pubkey(bytes([i]) * 32) for i in (0x11, 0x22, 0x33))
# Multisig accounts as the Squads v4 program wrote them (an upgrade multisig and a guardian multisig, 2 of 3)
SQUADS_ACCOUNTS = {
    "upgrade": "e07479ba44a14fec45363021ca9e76d721dbbc5a0c458003c3f0b174c3502c0998ba83c7ab3082550000000000000000000000000000000000000000000000000000000000000000"
               "020000a302000000000000000000000000000000000000ff0300000071ee0ffe451242f7b060c3fe6b477a5536a212816489ef6fff3c27e0ef863740077fc0a9793211967d3e6e4b"
               "550a022da6d60f0d50dba401ba5cb1664c9b1edf8a07bdff32d7b0c8e1f2fde62ae5751e6873e6b98311ef451bd0f5ef4de25aeab0eb07"
               "0000000000000000000000000000000000000000000000000000000000000000",
    "guardian": "e07479ba44a14fece4b3f061d48154ae25250611a4b68e4d23a439fdbfa78b3f1bedac28fc2b84580000000000000000000000000000000000000000000000000000000000000000"
                "0200000000000000000000000000000000000000000000ff0300000071ee0ffe451242f7b060c3fe6b477a5536a212816489ef6fff3c27e0ef863740077fc0a9793211967d3e6e4b"
                "550a022da6d60f0d50dba401ba5cb1664c9b1edf8a07bdff32d7b0c8e1f2fde62ae5751e6873e6b98311ef451bd0f5ef4de25aeab0eb07"
                "0000000000000000000000000000000000000000000000000000000000000000",
}


def ix(i: Instruction) -> dict:
    return {"program": str(i.program_id), "data": bytes(i.data).hex(),
            "accounts": [{"pubkey": str(a.pubkey), "signer": a.is_signer, "writable": a.is_writable} for a in i.accounts]}


def upgrade_ix(program: Pubkey, buffer: Pubkey, authority: Pubkey, spill: Pubkey) -> Instruction:
    """The upgradeable loader's Upgrade, from the loader's source (solana-loader-v3-interface `upgrade`): variant 3, then
    the program data (w), the program (w), the buffer (w), the spill (w), the rent and clock sysvars, the authority (s)."""
    data = mc.programdata_address(program)
    return Instruction(LOADER, (3).to_bytes(4, "little"), [AccountMeta(data, False, True), AccountMeta(program, False, True), AccountMeta(buffer, False, True),
                                                           AccountMeta(spill, False, True), AccountMeta(SYSVAR_RENT, False, False),
                                                           AccountMeta(SYSVAR_CLOCK, False, False), AccountMeta(authority, True, False)])


def loader_accounts() -> dict:
    """ProgramData and Buffer accounts of the upgradeable loader (solana-loader-v3-interface `UpgradeableLoaderState`), the
    program bytes ending in the zero padding a write leaves, and what the Python reader and `solana-verify`'s hash say of them."""
    elf = b"\x7fELF" + b"a program of this repository" + bytes(range(1, 250)) + bytes(57)
    vault = Pubkey.from_string(IDS["upgrade_authority"])
    head = (3).to_bytes(4, "little") + (123_456).to_bytes(8, "little")
    out = {}
    for name, data, authority in (("programdata", head + b"\x01" + bytes(vault) + elf, str(vault)),
                                  ("programdata, no upgrade authority", head + b"\x00" + bytes(32) + elf, None),
                                  ("buffer", (1).to_bytes(4, "little") + b"\x01" + bytes(vault) + elf, str(vault))):
        out[name] = {"data": data.hex(), "authority": authority, "executable_hash": mc.elf_hash(elf), "program_bytes": len(elf)}
        if name.startswith("programdata"):
            deployed, who, got = mc.program_data(lambda _a, data=data: (str(LOADER), data), IDS["knos_pay"])
            assert deployed and who == authority and got == elf     # the Python reader agrees: this is what it must keep reading
            out[name]["slot"] = 123_456
    return out


def build() -> dict:
    squads, guardian = Pubkey.from_string(IDS["squads_program"]), Pubkey.from_string(IDS["guardian"])
    multisigs = {}
    for name, vault in (("upgrade", "upgrade_authority"), ("guardian", "guardian")):
        key = Pubkey.from_string(CREATE_KEYS[name])
        ms = mc.multisig_address(key, squads)
        multisigs[name] = {"create_key": str(key), "multisig": str(ms), "vault": str(mc.vault_address(ms, squads)),
                           "time_lock": 172_800 if name == "upgrade" else 0}
        assert multisigs[name]["multisig"] == IDS[f"{name}_multisig"] and multisigs[name]["vault"] == IDS[vault], \
            f"the {name} create key {key} does not give the pinned multisig and vault of programs-v2/program_ids.json"
    accounts = {}
    for name, hexed in SQUADS_ACCOUNTS.items():
        ms = mc.read_multisig(bytes.fromhex(hexed))
        accounts[name] = {"data": hexed, "create_key": str(ms.create_key), "threshold": ms.threshold, "time_lock": ms.time_lock,
                          "config_authority": None if ms.config_authority is None else str(ms.config_authority), "members": [str(m) for m in ms.members]}
    knos_pay = Pubkey.from_string(IDS["knos_pay"])
    return {
        "note": "Generated by scripts/governance_fixture.py from src/knos/settle/v2 and src/knos/mainnet_check.py. Do not edit.",
        "programs": {"knos_oidc": IDS["knos_oidc"], "knos_pay": IDS["knos_pay"], "squads": IDS["squads_program"], "loader": str(LOADER)},
        "guardian": IDS["guardian"],
        "multisigs": multisigs,
        "inputs": {"payer": str(PAYER), "buffer": str(BUFFER), "spill": str(SPILL), "key_hash": oidc.key_hash(N2048).hex()},
        "addresses": {"key(github)": str(oidc.key_pda(oidc.GITHUB, N2048)), "key(gitlab)": str(oidc.key_pda(oidc.GITLAB, N2048)),
                      "pause": str(pay.pause_pda()), "programdata(knos_pay)": str(mc.programdata_address(knos_pay))},
        "instructions": {
            "guardian approve github": ix(oidc.approve_ix(guardian, oidc.GITHUB, N2048)),
            "guardian revoke github": ix(oidc.revoke_ix(guardian, oidc.GITHUB, N2048)),
            "guardian approve gitlab": ix(oidc.approve_ix(guardian, oidc.GITLAB, N2048)),
            "guardian revoke gitlab": ix(oidc.revoke_ix(guardian, oidc.GITLAB, N2048)),
            "guardian pause 604800": ix(pay.pause_ix(guardian, PAYER, pay.PAUSE_MAX)),
            "guardian pause 600": ix(pay.pause_ix(guardian, PAYER, 600)),
            "guardian pause 0": ix(pay.pause_ix(guardian, PAYER, 0)),
            "upgrade knos_pay": ix(upgrade_ix(knos_pay, BUFFER, Pubkey.from_string(IDS["upgrade_authority"]), SPILL)),
        },
        "squads_accounts": accounts,
        "loader_accounts": loader_accounts(),
    }


def main(argv: list[str]) -> int:
    text = json.dumps(build(), indent=1) + "\n"
    if "--check" in argv:
        if not OUT.is_file() or OUT.read_text(encoding="utf-8") != text:
            print(f"{OUT.relative_to(ROOT)} is stale. Run: python scripts/governance_fixture.py", file=sys.stderr)
            return 1
        return 0
    OUT.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
