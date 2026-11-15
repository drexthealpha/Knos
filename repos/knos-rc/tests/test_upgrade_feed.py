"""scripts/upgrade_feed.py on fixture accounts: no network. The Squads accounts are built by the builders
tests/test_site_recorded.py holds the site's banner to; buffers, program data and upgrade_gate records are built here in
the layouts src/knos/settle/v2/gate.py and src/knos/mainnet_check.py read."""
from __future__ import annotations

import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from solders.pubkey import Pubkey

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import upgrade_feed as uf  # noqa: E402
from test_site_recorded import (BUFFER_OIDC, BUFFER_PAY, GOVERNANCE, IDS, NOW, OTHER_BUFFER, OTHER_PROGRAM, SQUADS,  # noqa: E402
                                config_transaction_account, proposal_account, vault_transaction_account)

from knos import mainnet_check as mc  # noqa: E402
from knos.settle.v2 import gate  # noqa: E402

ATOM = "{http://www.w3.org/2005/Atom}"
LOADER = str(mc.LOADER)
ELF_OLD, ELF_BAD, ELF_NEW, ELF_OIDC = (b"\x7fELF" + bytes([k]) * 60 for k in (1, 2, 3, 4))
COMMIT_BAD, COMMIT_NEW = "a" * 40, "b" * 40
BUFFER_BAD = IDS["fee_owner"]                                    # any other address: the withdrawn proposal's buffer


def buffer(elf: bytes) -> tuple[str, bytes]:
    return LOADER, (1).to_bytes(4, "little") + b"\x01" + bytes(32) + elf + bytes(40)       # trailing zeros, as a buffer has


def record(program: str, elf: bytes, commit: str, run: int) -> tuple[str, tuple[str, bytes]]:
    h = gate.executable_hash(elf)
    data = bytes([1, 255]) + bytes(6) + run.to_bytes(8, "little") + NOW.to_bytes(8, "little") + (9).to_bytes(8, "little") + bytes(Pubkey.from_string(program)) + h + commit.encode()
    assert len(data) == gate.RECORD_LEN
    return str(gate.record_pda(Pubkey.from_string(program), h)), (str(gate.GATE_ID), data)


def world(plan: list[tuple[int, str, int, int, bytes]], extra: dict, stale: int = 0) -> dict:
    """The accounts of a cluster: the real multisig of devnet with `transaction_index` len(plan), its proposals, and `extra`."""
    real = bytes.fromhex(GOVERNANCE["squads_accounts"]["upgrade"]["data"])
    ms_key, squads = Pubkey.from_string(IDS["upgrade_multisig"]), Pubkey.from_string(SQUADS)
    accounts = {IDS["upgrade_multisig"]: (SQUADS, real[:78] + max(i for i, *_ in plan).to_bytes(8, "little") + stale.to_bytes(8, "little") + real[94:]), **extra}
    for index, status, at, approved, tx in plan:
        accounts[str(mc.proposal_address(ms_key, index, squads))] = (SQUADS, proposal_account(index, status, at, approved))
        if tx is not None:
            accounts[str(mc.transaction_address(ms_key, index, squads))] = (SQUADS, tx)
    return accounts


PAY, OIDC = IDS["knos_pay"], IDS["knos_oidc"]
PROGRAM_NOW = {str(mc.programdata_address(PAY)): (LOADER, bytes(mc.PROGRAMDATA_HEADER) + ELF_OLD + bytes(16))}
RECORDS = dict([record(PAY, ELF_BAD, COMMIT_BAD, 71), record(PAY, ELF_NEW, COMMIT_NEW, 72)])


def first_world() -> dict:
    return world([
        (1, "Executed", NOW - 400 * 3600, 2, vault_transaction_account(PAY, BUFFER_OIDC)),        # ran long ago; its buffer is closed
        (2, "Cancelled", NOW - 30 * 3600, 2, vault_transaction_account(PAY, BUFFER_BAD)),         # withdrawn during its delay
        (3, "Approved", NOW - 5 * 3600, 2, vault_transaction_account(PAY, BUFFER_PAY)),           # the corrected build, in its delay
        (4, "Active", NOW - 3600, 1, vault_transaction_account(OIDC, OTHER_BUFFER)),              # one vote short; no gate record
        (5, "Draft", NOW - 100, 0, vault_transaction_account(OTHER_PROGRAM, BUFFER_PAY)),         # not a Knos program
        (6, "Approved", NOW - 50, 2, config_transaction_account()),                               # a change to the multisig itself
    ], {BUFFER_BAD: buffer(ELF_BAD), BUFFER_PAY: buffer(ELF_NEW), OTHER_BUFFER: buffer(ELF_OIDC), **PROGRAM_NOW, **RECORDS})


def read(accounts: dict, previous: list[dict] | None = None) -> dict[int, uf.Entry]:
    return {e.index: e for e in uf.entries(accounts.get, IDS, previous)[1]}


def test_one_entry_per_upgrade_of_a_knos_program_with_its_build_its_commit_its_time_and_its_status():
    got = read(first_world())
    assert sorted(got) == [1, 2, 3, 4]                                  # the other program's and the config change are not upgrades of Knos
    hash_of = lambda elf: gate.executable_hash(elf).hex()  # noqa: E731
    e = got[3]
    assert (e.program, e.program_address, e.buffer, e.status, e.squads_status) == ("knos_pay", PAY, BUFFER_PAY, "pending", "Approved")
    assert (e.build_hash, e.hash_from, e.source_commit, e.gate_run) == (hash_of(ELF_NEW), "buffer", COMMIT_NEW, 72)
    assert e.earliest_execution == NOW - 5 * 3600 + 172_800 and (e.approved, e.threshold) == (2, 2)
    assert (got[2].status, got[2].build_hash, got[2].source_commit) == ("replaced", hash_of(ELF_BAD), COMMIT_BAD)   # proposal 3 took its place
    assert (got[4].program, got[4].status, got[4].earliest_execution, got[4].source_commit) == ("knos_oidc", "pending", None, None)
    assert got[4].build_hash == hash_of(ELF_OIDC)                       # a hash, and no GitHub run that vouches for it
    assert (got[1].status, got[1].build_hash, got[1].hash_from) == ("executed", hash_of(ELF_OLD), "program")        # the newest that ran: what the program runs


def test_a_proposal_that_ran_keeps_the_hash_read_while_it_was_pending_and_a_withdrawn_one_with_no_successor_is_cancelled(tmp_path):
    uf.write(tmp_path, first_world().get, IDS, NOW, "devnet")
    before = json.loads((tmp_path / "upgrades.json").read_text())
    assert before["pending"] == 2 and (before["threshold"], before["members"], before["time_lock"]) == (2, 3, 172_800)
    ms_key, squads = Pubkey.from_string(IDS["upgrade_multisig"]), Pubkey.from_string(SQUADS)
    later = first_world()
    del later[BUFFER_PAY]                                               # the loader closes a buffer when its upgrade runs
    later[str(mc.proposal_address(ms_key, 3, squads))] = (SQUADS, proposal_account(3, "Executed", NOW + 44 * 3600, 2))
    later[str(mc.proposal_address(ms_key, 4, squads))] = (SQUADS, proposal_account(4, "Cancelled", NOW + 3600, 2))
    later[str(mc.programdata_address(PAY))] = (LOADER, bytes(mc.PROGRAMDATA_HEADER) + ELF_NEW)
    got = {e.index: e for e in uf.write(tmp_path, later.get, IDS, NOW + 45 * 3600, "devnet")}
    assert (got[3].status, got[3].hash_from, got[3].source_commit) == ("executed", "earlier feed", COMMIT_NEW)
    assert got[3].build_hash == gate.executable_hash(ELF_NEW).hex() and got[3].earliest_execution == NOW - 5 * 3600 + 172_800
    assert got[4].status == "cancelled" and got[2].status == "replaced"
    assert (got[1].build_hash, got[1].hash_from) == (gate.executable_hash(ELF_OLD).hex(), "earlier feed")      # read while it was the newest that ran
    assert json.loads((tmp_path / "upgrades.json").read_text())["pending"] == 0
    fresh = read(later)                                                 # the same chain with no earlier feed: what was never read is not guessed
    assert (fresh[3].build_hash, fresh[3].hash_from) == (gate.executable_hash(ELF_NEW).hex(), "program")
    assert (fresh[1].status, fresh[1].build_hash, fresh[1].source_commit) == ("executed", None, None)
    assert "can no longer be read" in uf.words(fresh[1])


def test_the_two_proposals_of_0_3_13_come_out_cancelled_once_withdrawn_and_replaced_once_this_build_is_proposed(tmp_path):
    """devnet as 0.3.13 left it (web/upgrades.json): proposal 1 upgrades knos_oidc, proposal 2 knos_pay, both approved at
    1791098249. 0.3.14 cancels both inside their 48 hours and proposes its own builds of four programs."""
    committed = {e["index"]: e for e in json.loads((ROOT / "web" / "upgrades.json").read_text(encoding="utf-8"))["entries"]}
    at, meter, passkey = 1_791_098_249, IDS["knos_meter"], IDS["knos_passkey"]
    b1, b2 = committed[1]["buffer"], committed[2]["buffer"]
    assert (committed[1]["program"], committed[2]["program"]) == ("knos_oidc", "knos_pay")       # true of the feed before and after it is written again
    old = {b1: buffer(ELF_OLD), b2: buffer(ELF_BAD), **dict([record(PAY, ELF_BAD, COMMIT_BAD, 71)])}
    first = [(1, "Approved", at, 2, vault_transaction_account(OIDC, b1)), (2, "Approved", at, 2, vault_transaction_account(PAY, b2))]
    uf.write(tmp_path, world(first, old).get, IDS, at + 3600, "devnet")
    before = json.loads((tmp_path / "upgrades.json").read_text())
    assert before["pending"] == 2 and [e["status"] for e in before["entries"]] == ["pending", "pending"]
    # withdrawn, and nothing proposed yet (deploy_v2.sh --propose --replace stopped after the cancellations): cancelled
    cancelled = [(1, "Cancelled", at + 7200, 2, first[0][4]), (2, "Cancelled", at + 7200, 2, first[1][4])]
    got = {e.index: e for e in uf.write(tmp_path, world(cancelled, old).get, IDS, at + 7300, "devnet")}
    assert (got[1].status, got[2].status, got[1].squads_status) == ("cancelled", "cancelled", "Cancelled")
    assert json.loads((tmp_path / "upgrades.json").read_text())["pending"] == 0
    assert "It was cancelled before it ran. The program is unchanged by it." in uf.words(got[2])
    # a cancelled proposal's buffer stays with the vault, so the withdrawn build and the commit it came from stay readable
    assert (got[2].build_hash, got[2].hash_from, got[2].source_commit) == (gate.executable_hash(ELF_BAD).hex(), "buffer", COMMIT_BAD)
    # this build proposed for all four: the two old ones are replaced, the four new ones pending
    new = {name: (str(Pubkey.from_string(IDS["guardian"]) if k == 0 else Pubkey.find_program_address([bytes([k])], Pubkey.from_string(SQUADS))[0]), b"\x7fELF" + bytes([40 + k]) * 50)
           for k, name in enumerate((OIDC, PAY, meter, passkey))}
    proposed = [(3 + k, "Approved", at + 7400 + k, 2, vault_transaction_account(program, where)) for k, (program, (where, _elf)) in enumerate(new.items())]
    accounts = world(cancelled + proposed, {**old, **{where: buffer(elf) for where, elf in new.values()}, **dict([record(PAY, new[PAY][1], COMMIT_NEW, 72)])})
    got = {e.index: e for e in uf.write(tmp_path, accounts.get, IDS, at + 7500, "devnet")}
    assert [(i, got[i].program, got[i].status) for i in sorted(got)] == [
        (1, "knos_oidc", "replaced"), (2, "knos_pay", "replaced"), (3, "knos_oidc", "pending"), (4, "knos_pay", "pending"), (5, "knos_meter", "pending"), (6, "knos_passkey", "pending")]
    assert "withdrawn before it ran, and a later proposal for the same program took its place" in uf.words(got[2])
    assert (got[4].build_hash, got[4].source_commit, got[4].earliest_execution) == (gate.executable_hash(new[PAY][1]).hex(), COMMIT_NEW, at + 7401 + 172_800)
    assert got[2].build_hash != got[4].build_hash and json.loads((tmp_path / "upgrades.json").read_text())["pending"] == 4
    feed = ET.fromstring((tmp_path / "upgrades.xml").read_text(encoding="utf-8"))
    titles = [e.find(ATOM + "title").text for e in feed.findall(ATOM + "entry")]
    assert titles[-2:] == ["knos_pay: upgrade proposal 2 is replaced", "knos_oidc: upgrade proposal 1 is replaced"]
    assert titles[0].startswith("knos_passkey: upgrade proposal 6 is pending, can run from ")
    # only knos_pay proposed again (knos_oidc ran this build already): the verifier's old proposal is cancelled, not replaced
    only_pay = world(cancelled + [proposed[1]], {**old, new[PAY][0]: buffer(new[PAY][1])})
    got = {e.index: e for e in uf.entries(only_pay.get, IDS)[1]}
    assert [(i, got[i].status) for i in sorted(got)] == [(1, "cancelled"), (2, "replaced"), (4, "pending")]
    # one withdrawn while it still collected approvals (rejected) reads the same way
    rejected = world([(1, "Rejected", at, 1, first[0][4]), (2, "Rejected", at, 1, first[1][4]), proposed[1]], {**old, new[PAY][0]: buffer(new[PAY][1])})
    got = {e.index: e for e in uf.entries(rejected.get, IDS)[1]}
    assert (got[1].status, got[2].status) == ("cancelled", "replaced")


def test_a_proposal_at_or_below_the_stale_index_is_void_and_never_pending():
    accounts = world([(1, "Approved", NOW, 2, vault_transaction_account(PAY, BUFFER_PAY))], {BUFFER_PAY: buffer(ELF_NEW)}, stale=1)
    assert read(accounts)[1].status == "cancelled"
    assert uf.status_of("Approved", False, False) == "pending" and uf.status_of("Rejected", False, True) == "replaced"


def test_the_feed_is_atom_with_one_entry_per_proposal_and_says_what_to_do_while_one_is_pending(tmp_path):
    uf.write(tmp_path, first_world().get, IDS, NOW, "devnet")
    feed = ET.fromstring((tmp_path / "upgrades.xml").read_text(encoding="utf-8"))
    assert feed.tag == ATOM + "feed" and feed.find(ATOM + "link[@rel='self']").get("href") == uf.FEED
    found = feed.findall(ATOM + "entry")
    ids = [e.find(ATOM + "id").text for e in found]
    assert len(found) == 4 and len(set(ids)) == 4 and all(i.startswith("tag:") for i in ids)
    newest = found[1]                                                   # proposal 3: entries are newest first, 4 then 3
    assert newest.find(ATOM + "title").text.startswith("knos_pay: upgrade proposal 3 is pending, can run from ")
    summary = newest.find(ATOM + "summary").text
    assert COMMIT_NEW in summary and gate.executable_hash(ELF_NEW).hex() in summary and "withdraw a Balance" in summary
    assert "no GitHub run vouches" in found[0].find(ATOM + "summary").text
    assert {c.get("term") for c in found[2].findall(ATOM + "category")} == {"replaced", "knos_pay"}
    assert all(e.find(ATOM + "updated").text.endswith("Z") for e in found)


def test_a_cluster_that_cannot_be_read_writes_nothing(tmp_path, monkeypatch):
    with pytest.raises(SystemExit, match="could not be read"):
        uf.entries({}.get, IDS)
    def down(*a, **k):
        raise OSError("no route")
    monkeypatch.setattr(uf.chain, "call", down)
    said: list[str] = []
    assert uf.main(["--rpc", "https://example.invalid", "--out", str(tmp_path)], said.append) == 2
    assert not list(tmp_path.iterdir()) and "Nothing was written" in said[0]


def test_the_committed_files_are_what_the_script_writes():
    doc = json.loads((ROOT / "web" / "upgrades.json").read_text(encoding="utf-8"))
    assert doc["multisig"] == IDS["upgrade_multisig"] and doc["feed"] == uf.FEED
    assert doc["pending"] == sum(e["status"] == "pending" for e in doc["entries"])
    assert all(e["status"] in ("pending", "executed", "cancelled", "replaced") and e["program"] in uf.PROGRAMS for e in doc["entries"])
    feed = ET.fromstring((ROOT / "web" / "upgrades.xml").read_text(encoding="utf-8"))
    assert len(feed.findall(ATOM + "entry")) == len(doc["entries"])
    assert "upgrades.xml" in (ROOT / "web" / "upgrade.js").read_text(encoding="utf-8")


def test_an_adopter_gets_the_full_feed_for_its_own_programs_and_its_own_gate(tmp_path):
    """`--ids FILE` and `--gate ADDRESS` (docs/reference/GATE.md): the programs the file names, held to the adopter's own gate."""
    their_gate = IDS["guardian"]                                        # any address that is not Knos's gate
    theirs = {"upgrade_multisig": IDS["upgrade_multisig"], "squads_program": SQUADS, "programs": {"their_program": OTHER_PROGRAM}, "upgrade_gate": their_gate}
    h = gate.executable_hash(ELF_NEW)
    at, (_owner, data) = record(OTHER_PROGRAM, ELF_NEW, COMMIT_NEW, 90)
    mine = str(gate.record_pda(Pubkey.from_string(OTHER_PROGRAM), h, Pubkey.from_string(their_gate)))
    assert mine != at
    got = {e.index: e for e in uf.entries({**first_world(), mine: (their_gate, data)}.get, theirs)[1]}
    assert sorted(got) == [5]                                           # the one proposal for their program: none of Knos's
    assert (got[5].program, got[5].program_address, got[5].build_hash, got[5].source_commit, got[5].gate_run) == ("their_program", OTHER_PROGRAM, h.hex(), COMMIT_NEW, 90)
    # a record at Knos's gate, or one owned by another program than their gate, vouches for nothing of theirs
    assert {e.index: e for e in uf.entries({**first_world(), at: (str(gate.GATE_ID), data)}.get, theirs)[1]}[5].source_commit is None
    assert {e.index: e for e in uf.entries({**first_world(), mine: (str(gate.GATE_ID), data)}.get, theirs)[1]}[5].source_commit is None
    # the command: a file without programs, Knos's own folder, or a gate without a file is refused in words, and nothing is written
    said: list[str] = []
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"upgrade_multisig": IDS["upgrade_multisig"]}), encoding="utf-8")
    good = tmp_path / "ids.json"
    good.write_text(json.dumps({k: v for k, v in theirs.items() if k != "upgrade_gate"}), encoding="utf-8")
    assert uf.main(["--ids", str(bad), "--out", str(tmp_path)], said.append) == 2 and "programs" in said[-1]
    assert uf.main(["--ids", str(good)], said.append) == 2 and "--out DIR" in said[-1]
    assert uf.main(["--gate", their_gate], said.append) == 2 and "--gate goes with --ids" in said[-1]
    assert not (tmp_path / "upgrades.json").exists()


def test_a_pending_approved_proposal_says_how_many_hours_are_left_to_leave(tmp_path):
    got = read(first_world())
    assert uf.hours_to_leave(got[3], NOW) == 43                         # approved 5 hours ago, 48 hours of delay
    assert uf.hours_to_leave(got[4], NOW) is None and uf.hours_to_leave(got[2], NOW) is None   # not approved; not pending
    assert "43 hours to leave" in uf.words(got[3], NOW) and "knos exit --before-upgrade" in uf.words(got[3], NOW)
    uf.write(tmp_path, first_world().get, IDS, NOW, "devnet")
    entries = {e["index"]: e for e in json.loads((tmp_path / "upgrades.json").read_text())["entries"]}
    assert entries[3]["hours_to_leave"] == 43 and entries[1]["hours_to_leave"] is None
    assert "(43 hours to leave at " in (tmp_path / "upgrades.xml").read_text()
