"""The Squads accounts the site's upgrade banner (web/upgrade.js) is tested on: the upgrade multisig and its proposals, as the program lays them out.

The multisig account is the real one of devnet (tests/fixtures/governance_v2.json), with its transaction index set to 5: the real one has made no
proposal yet, and a banner has to be tested on some. The five proposals are built here with the layouts src/knos/mainnet_check.py reads (and
scripts/governance.mjs makes), at the addresses its `proposal_address` and `transaction_address` derive. What `pending_proposals` reads from
them is recorded beside them, and tests/web/site.mjs holds web/upgrade.js to the same answer. Written by `python tests/test_site_recorded.py`."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from solders.pubkey import Pubkey  # noqa: E402

from knos import mainnet_check as mc  # noqa: E402

RECORDED = ROOT / "tests" / "web" / "recorded" / "squads_upgrades.json"
IDS = json.loads((ROOT / "src" / "knos" / "settle" / "v2" / "program_ids.json").read_text(encoding="utf-8"))
GOVERNANCE = json.loads((ROOT / "tests" / "fixtures" / "governance_v2.json").read_text(encoding="utf-8"))
NOW = 1_790_000_000
SQUADS = IDS["squads_program"]
NOTE = ("The upgrade multisig's account is the real one of devnet (tests/fixtures/governance_v2.json) with transaction_index set to 5, because the real one has made no proposal; "
        "the five proposals and their transactions are built by tests/test_site_recorded.py in the layouts src/knos/mainnet_check.py reads, at the addresses it derives. `pending` is what "
        "mainnet_check.pending_proposals reads from them at `now`. tests/web/site.mjs holds web/upgrade.js to that answer. Written by `python tests/test_site_recorded.py`.")

# the buffers and the unrelated program of the proposals: addresses of the governance fixture, fixed
BUFFER_PAY = GOVERNANCE["inputs"]["buffer"]
BUFFER_OIDC = GOVERNANCE["inputs"]["spill"]
OTHER_PROGRAM, OTHER_BUFFER = GOVERNANCE["inputs"]["payer"], GOVERNANCE["addresses"]["key(github)"]


def member(i: int) -> bytes:
    return bytes([i]) * 32


def proposal_account(index: int, status: str, at: int, approved: int) -> bytes:
    """A Squads v4 Proposal of the upgrade multisig (as tests/test_mainnet_check.py builds one)."""
    tag = mc.STATUSES.index(status)
    out = mc.PROPOSAL + bytes(Pubkey.from_string(IDS["upgrade_multisig"])) + index.to_bytes(8, "little") + bytes([tag])
    out += at.to_bytes(8, "little", signed=True) if status != "Executing" else b""
    out += bytes([254]) + approved.to_bytes(4, "little") + b"".join(member(10 + k) for k in range(approved))
    return out + bytes(8)                                           # rejected and cancelled: none


def vault_transaction_account(program: str, buffer: str) -> bytes:
    """A Squads v4 VaultTransaction that carries the upgradeable loader's Upgrade (what `upgrade propose` creates)."""
    vault = Pubkey.from_string(IDS["upgrade_authority"])
    keys = [mc.programdata_address(program), Pubkey.from_string(program), Pubkey.from_string(buffer), Pubkey.from_string(IDS["fee_owner"]), Pubkey.from_string(GOVERNANCE["inputs"]["payer"]),
            Pubkey.from_string(IDS["guardian"]), vault, mc.LOADER]
    out = mc.VAULT_TX + bytes(32) + bytes(vault) + (6).to_bytes(8, "little") + bytes([255, 0, 254]) + (1).to_bytes(4, "little") + b"\x07"
    out += bytes([1, 1, 6]) + len(keys).to_bytes(4, "little") + b"".join(bytes(k) for k in keys)
    out += (1).to_bytes(4, "little") + bytes([7]) + (7).to_bytes(4, "little") + bytes(range(7)) + (4).to_bytes(4, "little") + (3).to_bytes(4, "little")
    return out + (0).to_bytes(4, "little")                           # no address table lookups


def config_transaction_account() -> bytes:
    return mc.CONFIG_TX + bytes(32) + bytes(8) + bytes(16)


def recorded() -> dict:
    squads, multisig_key = Pubkey.from_string(SQUADS), Pubkey.from_string(IDS["upgrade_multisig"])
    real = bytes.fromhex(GOVERNANCE["squads_accounts"]["upgrade"]["data"])
    multisig = real[:78] + (5).to_bytes(8, "little") + real[86:]                       # transaction_index 5; stale_transaction_index stays 0
    plan = [  # index, status, approved at, approvals, the transaction
        (5, "Draft", NOW - 100, 0, vault_transaction_account(OTHER_PROGRAM, OTHER_BUFFER), "an upgrade of a program that is not Knos's, drafted"),
        (4, "Approved", NOW - 5 * 3600, 2, vault_transaction_account(IDS["knos_pay"], BUFFER_PAY), "an upgrade of knos_pay, approved five hours before now"),
        (3, "Active", NOW - 2 * 3600, 1, vault_transaction_account(IDS["knos_oidc"], BUFFER_OIDC), "an upgrade of knos_oidc, one approval of two so far"),
        (2, "Executed", NOW - 90 * 3600, 2, vault_transaction_account(IDS["knos_pay"], BUFFER_PAY), "an upgrade of knos_pay that ran already: not pending"),
        (1, "Approved", NOW - 60 * 3600, 2, config_transaction_account(), "a change to the multisig itself, approved: pending, but not an upgrade of a program"),
    ]
    accounts = {IDS["upgrade_multisig"]: {"owner": SQUADS, "data": multisig.hex(), "what": "the upgrade multisig, with transaction_index 5"}}
    for index, status, at, approved, tx, what in plan:
        accounts[str(mc.proposal_address(multisig_key, index, squads))] = {"owner": SQUADS, "data": proposal_account(index, status, at, approved).hex(), "what": f"proposal {index}: {status}, {what}"}
        accounts[str(mc.transaction_address(multisig_key, index, squads))] = {"owner": SQUADS, "data": tx.hex(), "what": f"transaction {index}: {what}"}

    def account(address: str):
        got = accounts.get(address)
        return (got["owner"], bytes.fromhex(got["data"])) if got else None
    ms = mc.read_multisig(multisig)
    pending = [{"index": p.index, "status": p.status, "approved": p.approved, "threshold": p.threshold, "kind": p.kind, "program": p.program, "buffer": p.buffer, "executes_at": p.executes_at}
               for p in mc.pending_proposals(account, IDS["upgrade_multisig"], ms, SQUADS)]
    return {"note": NOTE, "now": NOW, "multisig": IDS["upgrade_multisig"], "time_lock": ms.time_lock, "threshold": ms.threshold, "accounts": accounts, "pending": pending}


def test_the_recorded_accounts_are_what_these_builders_write_and_the_reader_reads_five_proposals_as_four_pending():
    got = recorded()
    assert json.loads(RECORDED.read_text(encoding="utf-8")) == json.loads(json.dumps(got)), "regenerate: python tests/test_site_recorded.py"
    pending = {p["index"]: p for p in got["pending"]}
    assert sorted(pending) == [1, 3, 4, 5] and "2" not in pending                     # the executed one is not pending
    assert (pending[4]["status"], pending[4]["kind"], pending[4]["program"], pending[4]["buffer"], pending[4]["executes_at"]) == ("Approved", "upgrade", IDS["knos_pay"], BUFFER_PAY, NOW - 5 * 3600 + 172_800)
    assert (pending[3]["status"], pending[3]["approved"], pending[3]["threshold"], pending[3]["executes_at"]) == ("Active", 1, 2, None)
    assert pending[1]["kind"] == "config" and pending[5]["status"] == "Draft"


if __name__ == "__main__":
    RECORDED.write_text(json.dumps(recorded(), indent=1) + "\n", encoding="utf-8")
    print("wrote", RECORDED)
