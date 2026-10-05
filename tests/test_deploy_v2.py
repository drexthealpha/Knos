"""scripts/deploy_v2.py, offline, against a fake ledger: the steps of scripts/deploy_v2.sh that are transactions of the two
programs each read the chain first and send only what is missing, so a run that failed half way is finished by running it
again, and a run on a finished deployment sends nothing."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
from solders.keypair import Keypair
from solders.pubkey import Pubkey

from knos import chain, mainnet_check as mc
from knos.settle.v2 import oidc, pay

ROOT = Path(__file__).resolve().parents[1]
NOW = 1_790_000_000
VAULT = oidc.IDS["upgrade_authority"]


def _script():
    spec = importlib.util.spec_from_file_location("deploy_v2_script", ROOT / "scripts" / "deploy_v2.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


d = _script()


class Ledger:
    """What the cluster does with the instructions deploy_v2.py sends, as far as the steps can see it."""

    def __init__(self, fail_on: int | None = None):
        self.accounts: dict[str, bytes] = {}
        self.sent: list[str] = []
        self.fail_on = fail_on          # the n-th send raises, as a dropped connection does

    def account(self, address) -> bytes | None:
        return self.accounts.get(str(address))

    def now(self) -> int:
        return NOW

    def send(self, ixs, payer) -> str:
        assert len(ixs) == 1
        ix = ixs[0]
        if self.fail_on is not None and len(self.sent) + 1 == self.fail_on:
            self.fail_on = None
            raise chain.RpcError("the connection dropped")
        if ix.program_id == pay.PAY_ID and ix.data == b"\x0a":
            self.accounts[str(ix.accounts[1].pubkey)] = b"mint"
            what = "InitFaucet"
        elif ix.program_id == oidc.OIDC_ID and ix.data[:1] == b"\x03":
            head = bytes([0, oidc.GITHUB, 64, 255]) + bytes(4) + NOW.to_bytes(8, "little") + (NOW + oidc.KEY_TTL).to_bytes(8, "little")
            self.accounts[str(ix.accounts[1].pubkey)] = head + bytes([oidc.GENESIS | oidc.APPROVED]) + bytes(15) + bytes(8 * 64)
            what = "RegisterKey"
        elif ix.program_id == oidc.OIDC_ID and ix.data[:1] == b"\x04":
            key = str(ix.accounts[1].pubkey)
            self.accounts[key] = b"\x01" + self.accounts[key][1:]
            what = "KeyParams"
        elif ix.program_id == pay.ATA_PROGRAM:
            self.accounts[str(ix.accounts[1].pubkey)] = b"token account"
            what = "CreateATA"
        else:
            raise AssertionError(f"an instruction this deployment does not send: {ix.program_id} {ix.data[:1].hex()}")
        self.sent.append(what)
        return f"sig{len(self.sent)}"

    def deploy(self, name: str, authority: str | None, elf: bytes = b"\x7fELFcode") -> None:
        head = (3).to_bytes(4, "little") + bytes(8) + (b"\x01" + bytes(Pubkey.from_string(authority)) if authority else bytes(33))
        self.accounts[str(mc.programdata_address(pay.IDS[name]))] = head + elf + bytes(40)


def run_all(ledger, payer=None) -> list[str]:
    payer = payer or Keypair()
    said: list[str] = []
    d.init_faucet(ledger, payer, said.append)
    d.register_keys(ledger, payer, d.genesis_keys(), said.append)
    d.fee_account(ledger, payer, said.append)
    return said


def test_the_four_genesis_keys_are_the_ones_the_verifier_takes_without_an_attestation():
    keys = d.genesis_keys()
    assert len(keys) == 4 and len({n for _, n in keys}) == 4
    pinned = {h for issuer, h in d.genesis(d.PINS.read_text(encoding="utf-8")) if issuer == oidc.GITHUB}
    assert {oidc.key_hash(n).hex() for _, n in keys} == pinned
    with pytest.raises(SystemExit, match="refused: github_jwks_2026-10-02.json has no key whose sha256 is"):
        d.genesis_keys(jwks={"keys": [k for k in json.loads(d.JWKS.read_text(encoding="utf-8"))["keys"]][:2]})


def test_every_step_sends_what_is_missing_and_a_second_run_sends_nothing():
    ledger = Ledger()
    said = run_all(ledger)
    assert ledger.sent == ["InitFaucet", *["RegisterKey", "KeyParams"] * 4, "CreateATA"]
    assert said[0] == "  InitFaucet: sig1" and said[-1].startswith("  the fee owner's token account: sig")
    assert sum("ready, verifies until 2026-10-21" in line for line in said) == 4
    again = run_all(ledger)
    assert len(ledger.sent) == 10, "nothing was sent the second time"
    assert [line for line in again if "exists already" in line] == ["  the faucet mint exists already", "  the fee owner's token account exists already"]


@pytest.mark.parametrize("fail_on", range(1, 11))
def test_a_run_that_failed_anywhere_is_finished_by_running_it_again_without_repeating_anything(fail_on):
    ledger = Ledger(fail_on=fail_on)
    with pytest.raises(chain.RpcError):
        run_all(ledger)
    run_all(ledger)
    assert sorted(ledger.sent) == sorted(["InitFaucet", *["RegisterKey", "KeyParams"] * 4, "CreateATA"]), (fail_on, ledger.sent)


def test_a_cluster_that_does_not_answer_in_time_is_asked_again_and_a_programs_refusal_is_not(monkeypatch):
    monkeypatch.setattr(d.time, "sleep", lambda seconds: None)
    said: list[str] = []
    seen: list[int] = []

    def slow():
        seen.append(1)
        if len(seen) < 3:
            raise TimeoutError("timed out")
        return "done"
    assert d.retrying(slow, say=said.append) == "done" and len(seen) == 3
    assert len(said) == 2 and "try 3 of 4" in said[-1] and "timed out" in said[0]
    seen.clear()

    def refused():
        seen.append(1)
        raise chain.RpcError("custom program error: 0x59", {"err": {}, "logs": ["Program x failed: custom program error: 0x59"]})
    with pytest.raises(chain.RpcError):
        d.retrying(refused, say=said.append)
    assert len(seen) == 1
    seen.clear()

    def down():
        seen.append(1)
        raise OSError("connection refused")
    with pytest.raises(OSError):
        d.retrying(down, say=said.append)
    assert len(seen) == 4, "four tries in all, then the last failure is raised"


def test_the_summary_is_complete_only_when_everything_is_on_chain_and_the_vault_holds_both_programs():
    keys = d.genesis_keys()
    ledger = Ledger()
    ok, line = d.summary(ledger, keys)
    assert not ok and "knos_oidc " + pay.IDS["knos_oidc"] + " is not deployed" in line and "0 of GitHub's 4 genesis keys verify" in line
    run_all(ledger)
    for name in ("knos_oidc", "knos_pay"):
        ledger.deploy(name, str(Keypair().pubkey()))
    ok, line = d.summary(ledger, keys)
    assert not ok and f"NOT the upgrade vault {VAULT}" in line and "4 of GitHub's 4 genesis keys verify" in line
    for name in ("knos_oidc", "knos_pay"):
        ledger.deploy(name, VAULT)
    ok, line = d.summary(ledger, keys)
    assert ok and line.count(f"its upgrade authority is the upgrade vault {VAULT}") == 2 and "(the first expires 2026-10-21" in line
    ledger.deploy("knos_pay", None)         # made immutable: no upgrade authority is not the vault, and the summary says so
    assert d.summary(ledger, keys)[0] is False


def test_the_program_state_is_the_executable_hash_and_the_authority_as_solana_verify_and_the_loader_say():
    ledger = Ledger()
    assert d.program_state(ledger, "knos_pay") is None
    ledger.deploy("knos_pay", VAULT, elf=b"\x7fELFa program")
    assert d.program_state(ledger, "knos_pay") == (mc.elf_hash(b"\x7fELFa program"), VAULT)
    ledger.deploy("knos_pay", None, elf=b"\x7fELFa program")
    assert d.program_state(ledger, "knos_pay") == (mc.elf_hash(b"\x7fELFa program"), None)


def test_every_address_of_the_deployment_is_listed_with_what_it_is():
    found = dict((address, what) for what, address in d.addresses(d.genesis_keys()))
    ids = oidc.IDS
    for name in ("knos_oidc", "knos_pay", "upgrade_multisig", "upgrade_authority", "guardian_multisig", "guardian", "fee_owner"):
        assert ids[name] in found, name
    assert found[ids["upgrade_authority"]].startswith("upgrade vault") and found[ids["guardian"]].startswith("guardian vault")
    assert found[str(pay.faucet_mint())].startswith("test-USDC mint") and found[str(mc.programdata_address(ids["knos_pay"]))].startswith("knos_pay program data")
    assert sum(what.startswith("GitHub key") for what in found.values()) == 4 and len(found) == len(d.addresses(d.genesis_keys()))


def test_the_transactions_are_listed_oldest_first_once_each_with_every_address_they_touched(monkeypatch):
    rows = {"A": [{"signature": "s2", "slot": 20, "blockTime": 1_790_000_020, "err": None}, {"signature": "s1", "slot": 10, "blockTime": 1_790_000_010, "err": None}],
            "B": [{"signature": "s2", "slot": 20, "blockTime": 1_790_000_020, "err": None}, {"signature": "s3", "slot": 30, "blockTime": None, "err": {"InstructionError": [0, "Custom"]}}],
            "C": []}

    def call(url, method, params, timeout=10.0):
        assert method == "getSignaturesForAddress" and url == "https://rpc.example"
        return rows[params[0]]
    monkeypatch.setattr(d.chain, "call", call)
    found = [("the first", "A"), ("the second", "B"), ("the third", "C")]
    devnet = d.transactions("https://rpc.example", found, "devnet")
    assert devnet == ["2026-09-21 14:13 UTC  s1  ok  touches the first  https://explorer.solana.com/tx/s1?cluster=devnet",
                      "2026-09-21 14:13 UTC  s2  ok  touches the first, the second  https://explorer.solana.com/tx/s2?cluster=devnet",
                      "slot 30  s3  FAILED  touches the second  https://explorer.solana.com/tx/s3?cluster=devnet"]
    assert [line.split("  ")[1] for line in d.transactions("https://rpc.example", found, "local")] == ["s1", "s2", "s3"]
    assert all("explorer" not in line for line in d.transactions("https://rpc.example", found, "local"))
    assert all("/tx/" in line and "cluster" not in line for line in d.transactions("https://rpc.example", found, "mainnet-beta"))
    monkeypatch.setitem(rows, "A", []), monkeypatch.setitem(rows, "B", [])
    assert d.transactions("https://rpc.example", found) == []


def test_hash_prints_the_executable_hash_of_a_file(tmp_path, capsys):
    so = tmp_path / "p.so"
    so.write_bytes(b"\x7fELF" + b"program" + bytes(100))
    assert d.main(["hash", str(so)]) == 0
    assert capsys.readouterr().out.strip() == mc.elf_hash(b"\x7fELFprogram")


def test_the_shell_script_has_seven_steps_no_idl_and_hands_over_last():
    text = (ROOT / "scripts" / "deploy_v2.sh").read_text(encoding="utf-8")
    steps = [line for line in text.splitlines() if line.startswith("step ")]
    assert [line.split()[1] for line in steps] == ["1", "2", "3", "4", "5", "6", "7"] and "handover" in steps[-1]
    assert "idl" not in text.lower() and "Program Metadata" not in text
    assert "--skip-new-upgrade-authority-signer-check" in text and "--max-sign-attempts 60" in text and '--buffer "$buffer"' in text
    assert "mainnet-beta" in text and "knos mainnet-check" in text     # the script refuses a mainnet endpoint and says where to go


# ---- 0.3.13: the new programs, a staging copy, and the upgrade's proposals -------------------------------------------

def _buffer(ledger: Ledger, address: Pubkey, elf: bytes, authority: str | None) -> None:
    head = (1).to_bytes(4, "little") + (b"\x01" + bytes(Pubkey.from_string(authority)) if authority else bytes(33))
    ledger.accounts[str(address)] = head + elf + bytes(64)


def test_a_program_is_named_by_its_pinned_name_or_its_address_and_the_gate_has_one_too():
    assert d.program_id("knos_meter") == pay.IDS["knos_meter"] and d.program_id("knos_passkey") == pay.IDS["knos_passkey"]
    assert d.program_id("upgrade_gate") == str(d.gate.GATE_ID) == "2DfVEuBMWvvh3kXZaQwk2SoszJsoV1PTiK1VGCkB55HW"
    other = str(Keypair().pubkey())
    assert d.program_id(other) == other
    for wrong in ("fee_owner", "rotate_sha", "knos_nothing", ""):          # a pinned value that is not a program is not one
        with pytest.raises(SystemExit, match="neither a program of this deployment"):
            d.program_id(wrong)
    ledger = Ledger()
    assert d.program_state(ledger, other) is None
    ledger.accounts[str(mc.programdata_address(other))] = (3).to_bytes(4, "little") + bytes(8) + bytes(33) + b"\x7fELFstaged" + bytes(9)
    assert d.program_state(ledger, other) == (mc.elf_hash(b"\x7fELFstaged"), None)


def test_a_buffer_is_read_with_its_build_and_its_authority_and_anything_else_is_not_a_buffer():
    ledger, at = Ledger(), Keypair().pubkey()
    assert d.buffer_state(ledger, str(at)) is None
    _buffer(ledger, at, b"\x7fELFnew build", VAULT)
    assert d.buffer_state(ledger, str(at)) == (mc.elf_hash(b"\x7fELFnew build"), VAULT)
    _buffer(ledger, at, b"\x7fELFnew build", None)
    assert d.buffer_state(ledger, str(at)) == (mc.elf_hash(b"\x7fELFnew build"), None)
    ledger.accounts[str(at)] = (3).to_bytes(4, "little") + bytes(60)       # program data is not a buffer
    assert d.buffer_state(ledger, str(at)) is None


def test_the_new_programs_are_complete_only_when_all_three_are_deployed_and_the_vault_holds_them():
    ledger = Ledger()
    ok, line = d.summary_new(ledger)
    assert not ok and line.count("is not deployed") == 3

    def put(name: str, authority: str | None) -> None:
        head = (3).to_bytes(4, "little") + bytes(8) + (b"\x01" + bytes(Pubkey.from_string(authority)) if authority else bytes(33))
        ledger.accounts[str(mc.programdata_address(d.program_id(name)))] = head + b"\x7fELF" + name.encode() + bytes(16)
    for name in d.NEW:
        put(name, str(Keypair().pubkey()))
    ok, line = d.summary_new(ledger)
    assert not ok and line.count(f"NOT the upgrade vault {VAULT}") == 3
    for name in d.NEW:
        put(name, VAULT)
    ok, line = d.summary_new(ledger)
    assert ok and line.count(f"its upgrade authority is the upgrade vault {VAULT}") == 3 and d.NEW == ("knos_meter", "knos_passkey", "upgrade_gate")


def test_the_gate_step_says_recorded_no_record_or_no_gate_and_never_calls_a_build_vouched_for_that_is_not():
    ledger, elf, said = Ledger(), b"\x7fELFa 2.1 build" + bytes(40), []
    assert d.gate_record(ledger, "knos_pay", elf, say=said.append) == 3 and "not deployed on this cluster" in said[-1]
    ledger.accounts[str(mc.programdata_address(str(d.gate.GATE_ID)))] = (3).to_bytes(4, "little") + bytes(8) + bytes(33) + b"\x7fELFgate" + bytes(8)
    assert d.gate_record(ledger, "knos_pay", elf, say=said.append) == 4 and "NO record that GitHub built" in said[-1]
    h = d.gate.executable_hash(elf)
    at = d.gate.record_pda(pay.PAY_ID, h)
    record = bytes([1]) + bytes(7) + (4242).to_bytes(8, "little") + NOW.to_bytes(8, "little") + (9).to_bytes(8, "little") + bytes(pay.PAY_ID) + h + b"c" * 40
    ledger.accounts[str(at)] = record
    assert d.gate_record(ledger, "knos_pay", elf, say=said.append) == 0
    assert said[-1] == f"  upgrade gate: GitHub's runner built {h.hex()} for knos_pay from commit {'c' * 40} (run 4242, record {at})"
    # the record of another build, or of another program, vouches for nothing
    assert d.gate_record(ledger, "knos_pay", elf + b"\x01", say=said.append) == 4 and d.gate_record(ledger, "knos_oidc", elf, say=said.append) == 4


def test_the_gate_step_waits_for_the_record_program_yml_and_a_relayer_write_and_gives_up_when_its_time_is_over():
    ledger, elf, said = Ledger(), b"\x7fELF the 2.1 build" + bytes(24), []
    h = d.gate.executable_hash(elf)
    at = str(d.gate.record_pda(pay.PAY_ID, h))
    record = bytes([1, 255]) + bytes(6) + (4242).to_bytes(8, "little") + bytes(16) + bytes(pay.PAY_ID) + h + b"c" * 40
    t, slept = [0.0], []

    def sleep(seconds: float) -> None:      # the relayer lands the record while the script sleeps for the third time
        slept.append(seconds)
        t[0] += seconds
        if len(slept) == 3:
            ledger.accounts[at] = record
    ask = lambda wait: d.gate_awaited(ledger, "knos_pay", elf, wait=wait, every=15, say=said.append, sleep=sleep, clock=lambda: t[0])  # noqa: E731
    # no gate on this cluster: nothing to wait for
    assert ask(600) == 3 and not slept and len(said) == 1 and "not deployed on this cluster" in said[0]
    ledger.accounts[str(mc.programdata_address(str(d.gate.GATE_ID)))] = (3).to_bytes(4, "little") + bytes(8) + bytes(33) + b"\x7fELFgate" + bytes(8)
    # asked with no wait (as --ungated does): one look, one line
    del said[:]
    assert ask(0) == 4 and not slept and len(said) == 1 and "NO record that GitHub built" in said[0]
    # waited for: said once that it waits and how the record comes, then what is so
    del said[:]
    assert ask(600) == 0 and slept == [15, 15, 15]
    assert len(said) == 2 and "Waiting up to 600 seconds" in said[0] and "program.yml" in said[0] and "a relayer carries" in said[0]
    assert said[1] == f"  upgrade gate: GitHub's runner built {h.hex()} for knos_pay from commit {'c' * 40} (run 4242, record {at})"
    # there already: no wait at all
    del said[:], slept[:]
    assert ask(600) == 0 and not slept and len(said) == 1
    # never comes: the time is used up, not more, and the answer is still no
    del said[:], slept[:]
    other = elf + b"\x01"
    assert d.gate_awaited(ledger, "knos_pay", other, wait=40, every=15, say=said.append, sleep=sleep, clock=lambda: t[0]) == 4
    assert slept == [15, 15, 10] and "NO record that GitHub built" in said[-1] and len(said) == 2
    # the command line takes the wait
    with pytest.raises(SystemExit):
        d.main(["--wait", "soon", "gate", "knos_pay", "x.so"])


def test_the_staging_ids_file_replaces_the_two_programs_says_what_it_is_and_the_clients_read_it(tmp_path):
    a, b = str(Keypair().pubkey()), str(Keypair().pubkey())
    ids = d.rc_ids(a, b)
    pinned = json.loads((ROOT / "programs-v2" / "program_ids.json").read_text(encoding="utf-8"))
    assert ids["knos_oidc"] == a and ids["knos_pay"] == b and "STAGING" in ids["staging"]
    assert {k: v for k, v in ids.items() if k not in ("knos_oidc", "knos_pay", "staging")} == {k: v for k, v in pinned.items() if k not in ("knos_oidc", "knos_pay")}
    for wrong in ((pinned["knos_oidc"], b), (a, pinned["knos_pay"]), (a, a)):
        with pytest.raises(SystemExit, match="a staging program must have an address of its own"):
            d.rc_ids(*wrong)
    out = tmp_path / "program_ids.json"
    assert d.main(["rc-ids", a, b, str(out)]) == 0 and json.loads(out.read_text(encoding="utf-8")) == ids
    # the Python client: the staging programs with the variable, the pinned ones without, and it says so once
    import subprocess
    import sys
    code = "from knos.settle.v2 import pay, oidc, meter; print(pay.PAY_ID, pay.OIDC_ID, oidc.OIDC_ID, meter.OIDC_ID, pay.FEE_OWNER)"
    env = {"PYTHONPATH": str(ROOT / "src"), "PATH": "/usr/bin:/bin"}
    got = subprocess.run([sys.executable, "-c", code], env={**env, "KNOS_PROGRAM_IDS": str(out)}, capture_output=True, text=True, check=True)
    assert got.stdout.split() == [b, a, a, a, pinned["fee_owner"]]
    assert got.stderr.count("KNOS_PROGRAM_IDS is set: using the STAGING programs") == 1 and "Unset it to use the real one" in got.stderr
    plain = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, check=True)
    assert plain.stdout.split() == [pinned["knos_pay"], pinned["knos_oidc"], pinned["knos_oidc"], pinned["knos_oidc"], pinned["fee_owner"]] and plain.stderr == ""


def test_a_staging_file_can_replace_program_addresses_and_nothing_else(tmp_path):
    from knos.settle import v2
    pinned = v2.load_ids({})
    assert pinned == json.loads((ROOT / "programs-v2" / "program_ids.json").read_text(encoding="utf-8"))
    f = tmp_path / "ids.json"

    def load(doc) -> dict:
        f.write_text(doc if isinstance(doc, str) else json.dumps(doc), encoding="utf-8")
        return v2.load_ids({"KNOS_PROGRAM_IDS": str(f)})
    other = str(Keypair().pubkey())
    assert load({"knos_pay": other}) == {**pinned, "knos_pay": other}
    assert load({**pinned, "knos_meter": other, "staging": "a note"}) == {**pinned, "knos_meter": other}       # the whole file, as --rc writes it
    for doc, why in (({"fee_owner": other}, "it changes fee_owner"), ({"guardian": other}, "it changes guardian"), ({"claim_sha": "0" * 40}, "it changes claim_sha"),
                     ({"upgrade_authority": other}, "it changes upgrade_authority"), ({"knos_pay": "not an address"}, "knos_pay is not an address"),
                     ({"knos_pay": 7}, "knos_pay is not an address"), ("[1]", "is not a JSON object"), ("{", "cannot be read as JSON")):
        with pytest.raises(RuntimeError, match=why):
            load(doc)
    with pytest.raises(RuntimeError, match="cannot be read as JSON"):
        v2.load_ids({"KNOS_PROGRAM_IDS": str(tmp_path / "none.json")})


def test_the_schedule_is_the_later_of_the_two_times_plus_ten_minutes_and_an_unapproved_proposal_schedules_nothing(tmp_path):
    def part(name: str, index: int, at: int | None) -> dict:
        return {"program": name, "address": pay.IDS[name], "buffer": str(Keypair().pubkey()), "hash": "ab" * 32, "index": index, "status": "Approved" if at else "Active",
                "approved_at": at, "executable_from": at + 172_800 if at else None}
    parts = [part("knos_pay", 4, NOW + 30), part("knos_oidc", 3, NOW)]
    plan = d.schedule(parts, "https://api.devnet.solana.com")
    assert plan["executable_from"] == NOW + 30 + 172_800 and plan["run_at"] == plan["executable_from"] + 600
    assert [p["hash"] for p in plan["proposals"]] == ["ab" * 32] * 2          # the build each was proposed with: the run executes no other
    assert plan["run_at_utc"] == d.when(plan["run_at"]) and [p["index"] for p in plan["proposals"]] == [3, 4] and plan["rpc"] == "https://api.devnet.solana.com"
    with pytest.raises(SystemExit, match=r"proposal 4 \(knos_pay\) is not approved yet, so its 48 hours have not started"):
        d.schedule([parts[1], part("knos_pay", 4, None)], "x")
    with pytest.raises(SystemExit, match="nothing to schedule"):
        d.schedule([], "x")
    files = []
    for p in parts:
        files.append(tmp_path / f"{p['program']}.json")
        files[-1].write_text(json.dumps(p), encoding="utf-8")
    out = tmp_path / "upgrade-schedule.json"
    assert d.main(["--rpc", "http://127.0.0.1:8899", "schedule", str(out), *map(str, files)]) == 0
    assert json.loads(out.read_text(encoding="utf-8")) == {**plan, "rpc": "http://127.0.0.1:8899"}


def test_the_shell_script_takes_one_new_mode_a_run_and_each_does_what_the_release_needs():
    import shutil
    import subprocess
    text = (ROOT / "scripts" / "deploy_v2.sh").read_text(encoding="utf-8")
    # --new: the three new programs at their pinned ids, the same resumable buffers, then the vault
    assert 'NEW_PROGRAMS="knos_meter knos_passkey upgrade_gate"' in text and 'deploy_one "$name" "$(py id "$name")" "$(new_key "$name")" "$KEYS/$name-buffer.json"' in text
    new = text[text.index("  --new)"):text.index("  --rc)")]
    assert new.index("build $NEW_PROGRAMS") < new.index("deploy_new") < new.index("handover $NEW_PROGRAMS") < new.index("py summary-new")
    # --rc: fresh keypairs in the key folder, the fee payer as authority, the ids file, and what the staged escrow trusts said aloud
    rc = text[text.index("rc_deploy() {"):text.index("rc_close() {")]
    assert 'solana-keygen new --no-bip39-passphrase --silent --outfile "$RC/$name-keypair.json"' in rc and 'py rc-ids' in rc and '"$RC/program_ids.json"' in rc
    assert "NOT by the staging verifier" in rc and "export KNOS_PROGRAM_IDS=$RC/program_ids.json" in rc
    close = text[text.index("rc_close() {"):text.index("# ---- --propose")]
    assert "sol program close" in close and '--recipient "$PAYER_ADDRESS"' in close and "is the keypair of a PINNED program" in close
    # --propose: buffer, gate, hand-over, proposal, schedule, in that order; no record means refusal unless --ungated, which is loud
    pr = text[text.index("propose() {"):text.index("# ---- run")]
    order = ["program write-buffer", 'py --wait "$wait" gate "$name"', "program set-buffer-authority", "governance upgrade propose", 'py schedule "$SCHEDULE"']
    assert [pr.index(x) for x in order] == sorted(pr.index(x) for x in order)
    assert "--propose --ungated" in pr and "UNGATED: NO RECORD AT THE UPGRADE GATE VOUCHES FOR THIS BUILD" in pr and 'flag="--ungated"' in pr
    # the record is waited for (program.yml's gate job and a relayer write it), so the release proposes WITHOUT --ungated;
    # the flag is the emergency's: it waits for nothing, says so before anything else, and is passed on only for a build with no record
    assert 'GATE_WAIT="${KNOS_GATE_WAIT:-1800}"' in text and 'wait="$GATE_WAIT"' in pr and pr.count('py --wait "$wait" gate') == 2
    assert pr.index("UNGATED: --ungated WAS PASSED. THIS IS FOR AN EMERGENCY ONLY") < pr.index("for name in $UPGRADES") and "wait=0" in pr
    # all four programs the vault holds, each gated by its own record, each with a buffer of its own for this build; older
    # proposals are dealt with before any buffer is written
    assert 'UPGRADES="knos_oidc knos_pay knos_meter knos_passkey"' in text and "for name in $PROGRAMS" not in pr and "build $UPGRADES" in text
    assert 'buffer="$KEYS/$name-upgrade-buffer-${want:0:16}.json"' in pr and "runs this build already" in pr
    assert pr.index("withdraw_older\n") < pr.index("for name in $UPGRADES") < pr.index('py kept "$name=$want"') < pr.index("program write-buffer")
    assert json.loads((ROOT / "programs-v2" / "program_ids.json").read_text(encoding="utf-8")).keys() >= set(d.UPGRADED) and " ".join(d.UPGRADED) in text
    # a build larger than the program's data account has room for: the account is extended first, after the gate has
    # vouched for the build and before its buffer is handed to the vault; a cluster that refuses stops the run in plain words
    grow = pr[pr.index('have="$(py room "$name")"'):pr.index('if [ "$held" != "$vault" ]')]
    assert pr.index('py --wait "$wait" gate "$name"') < pr.index('py extend "$name" $((size - have))') < pr.index("program set-buffer-authority")
    assert 'if [ "$size" -gt "$have" ]; then' in grow and "ExtendProgramChecked" in grow and "Nothing was proposed for $name" in grow
    gated = pr[pr.index('if [ "$rc" != 0 ]; then'):pr.index('if [ "$held" != "$vault" ]')]
    assert gated.index('if [ "$UNGATED" != 1 ]; then') < gated.index("after $wait seconds") < gated.index('flag="--ungated"')
    assert pr.count('flag="--ungated"') == 1 and "In an emergency only: --propose --ungated" in gated and "$flag |" in pr
    assert '--buffer "$buffer" --buffer-authority "$PAYER"' in pr and "--max-sign-attempts 60" in pr
    assert "KNOS_PROGRAM_IDS is set" in text            # the script never works on staging ids by accident
    # the bash on PATH: on Windows a bare "bash" is looked up in System32 first, which is WSL's launcher, not Git's bash
    if bash := shutil.which("bash"):
        assert subprocess.run([bash, "-n", str(ROOT / "scripts" / "deploy_v2.sh")]).returncode == 0
        two = subprocess.run([bash, str(ROOT / "scripts" / "deploy_v2.sh"), "--new", "--rc"], capture_output=True, text=True)
        assert two.returncode == 2 and "one of --new, --rc, --rc-close, --propose in a run" in two.stderr
        alone = subprocess.run([bash, str(ROOT / "scripts" / "deploy_v2.sh"), "--ungated"], capture_output=True, text=True)
        assert alone.returncode == 2 and "--ungated goes with --propose" in alone.stderr
        lone = subprocess.run([bash, str(ROOT / "scripts" / "deploy_v2.sh"), "--new", "--replace"], capture_output=True, text=True)
        assert lone.returncode == 2 and "--replace goes with --propose" in lone.stderr
        said = subprocess.run([bash, str(ROOT / "scripts" / "deploy_v2.sh"), "--help"], capture_output=True, text=True).stdout
        assert all(flag in said for flag in ("--new", "--rc ", "--rc-close", "--propose [--replace] [--ungated]", "KNOS_GATE_TOKENS", "KNOS_RC_SO_DIR",
                                             "KNOS_GATE_WAIT", "--ungated is for an emergency only"))


def test_lamports_reads_solanas_whole_answer_so_the_line_after_the_number_never_stops_the_script(tmp_path):
    """`solana rent N --lamports` prints its number, then an empty line. A reader that leaves after the number makes that
    second write fail (Broken pipe): solana exits 101, and with pipefail the cost check stopped deploy_v2.sh half way with
    no word of why (one call in ten on devnet). The stand-in waits between its two lines, so a reader that leaves early
    loses every time, and the script's own lamports() must not."""
    import os
    import re
    import shutil
    import subprocess
    bash = shutil.which("bash")
    if os.name == "nt" or not bash:
        pytest.skip("runs the script's functions with bash")
    text = (ROOT / "scripts" / "deploy_v2.sh").read_text(encoding="utf-8")
    funcs = [line for line in text.splitlines() if re.match(r"(sol|lamports)\(\) \{", line)]
    assert len(funcs) == 2 and "exit" not in funcs[1], funcs
    solana = tmp_path / "solana"
    solana.write_text('#!/bin/bash\ncase " $* " in\n  *" rent "*) echo "Rent-exempt minimum: 3678758200 lamports"; sleep 1; echo ;;\n'
                      '  *" balance "*) echo "14232197098 lamports" ;;\nesac\n', encoding="utf-8")
    solana.chmod(0o755)
    env = {"PATH": f"{tmp_path}:/usr/bin:/bin", "RPC": "http://127.0.0.1:1", "PAYER": "payer.json"}

    def afford(lamports_line: str) -> subprocess.CompletedProcess:
        # what afford() does with it: the two numbers in arithmetic, under the script's own shell options
        body = f'set -euo pipefail\n{funcs[0]}\n{lamports_line}\ncost=$(( $(lamports rent 724037) + 2 * $(lamports rent 724045) ))\necho "$cost $(lamports balance me)"\n'
        return subprocess.run([bash, "-c", body], env=env, capture_output=True, text=True, timeout=60)
    ok = afford(funcs[1])
    assert ok.returncode == 0 and ok.stdout.split() == [str(3678758200 * 3), "14232197098"], ok.stderr
    # A reader that leaves after the first line: the stand-in shows the race is real, not something this test made up.
    # `head -n 1` leaves there whatever awk is installed.
    early = afford("lamports() { sol \"$@\" --lamports | head -n 1 | awk 'NF >= 2 { print $(NF - 1) }'; }")
    assert early.returncode != 0 and early.stdout == ""
    # The reader deploy_v2.sh had before left through awk's `exit`. An awk that stops reading there (gawk) loses the same
    # way; one that reads its input to the end before it leaves (mawk, the awk of Debian and Ubuntu) happens to win. So it
    # stopped the script or not by which awk the machine had: either it fails with nothing printed, or it is right.
    old = afford("lamports() { sol \"$@\" --lamports | awk 'NF >= 2 { print $(NF - 1); exit }'; }")
    assert (old.returncode != 0 and old.stdout == "") or (old.returncode == 0 and old.stdout == ok.stdout), (old.returncode, old.stdout, old.stderr)


def _build_world(tmp_path):
    """deploy_v2.sh's sources_hash() and build() under the script's shell options, in a repository of a few files, with
    stand-ins for solana-verify and docker. The stand-in builds the crate whose manifest `find <mount>` lists first, as
    solana-verify does, into that crate's workspace, and then hashes what <workspace-path>/target/deploy holds."""
    import os
    import re
    import shutil
    import subprocess
    bash = shutil.which("bash")
    if os.name == "nt" or not bash:
        pytest.skip("runs the script's functions with bash")
    text = (ROOT / "scripts" / "deploy_v2.sh").read_text(encoding="utf-8")
    funcs = {"sha256": next(line for line in text.splitlines() if line.startswith("sha256() {")),
             "sources_hash": next(line for line in text.splitlines() if line.startswith("sources_hash() {")),
             "build": re.search(r"(?ms)^build\(\) \{.*?^\}$", text).group(0)}
    repo = tmp_path / "repo"
    for rel in ("programs-v2/Cargo.toml", "programs-v2/knos_oidc/Cargo.toml", "programs-v2/knos_pay/Cargo.toml",
                "programs/knos_oidc/Cargo.toml", "programs/knos_pay/Cargo.toml", "crates/knos-oidc-interface/src/lib.rs"):
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(rel, encoding="utf-8")
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    (bin_ / "docker").write_text("#!/bin/bash\nexit 0\n", encoding="utf-8")
    # FIRST=programs makes the stand-in list programs/ first, as find does on NTFS (WSL under /mnt/c, Git Bash)
    (bin_ / "solana-verify").write_text(
        '#!/bin/bash\necho "$*" >> "$LOG"\nmount="$2"; ws="$4"; lib="$6"\n'
        'crate="$mount/${FIRST:-programs-v2}/$lib"\nmkdir -p "$(dirname "$crate")/target/deploy"\n'
        'echo "built from $crate" > "$(dirname "$crate")/target/deploy/$lib.so"\n'
        '[ -f "$ws/target/deploy/$lib.so" ] || { echo "no $lib.so in $ws/target/deploy" >&2; exit 1; }\n', encoding="utf-8")
    for f in bin_.iterdir():
        f.chmod(0o755)
    log = tmp_path / "log"
    body = "\n".join(['set -euo pipefail', f'ROOT={repo}', 'PROGRAMS="knos_oidc knos_pay"', 'UPGRADES="knos_oidc knos_pay knos_meter knos_passkey"', 'VERIFY_IMAGE=img',
                      'die() { echo "stopped: $*" >&2; exit 1; }', 'need() { :; }', 'py() { sha256 "$2" | cut -c1-8; }',
                      funcs["sha256"], funcs["sources_hash"], funcs["build"], 'build $PROGRAMS'])

    def run(path: str = "/usr/bin:/bin", **env) -> subprocess.CompletedProcess:
        return subprocess.run([bash, "-c", body], capture_output=True, text=True, timeout=60,
                              env={"PATH": f"{bin_}:{path}", "LOG": str(log), **env})
    return repo, log, run


def test_the_verified_build_mounts_the_repository_names_programs_v2_and_rebuilds_when_its_sources_change(tmp_path):
    repo, log, run = _build_world(tmp_path)
    first = run()
    assert first.returncode == 0, first.stderr
    assert log.read_text().splitlines() == [f"build {repo} --workspace-path {repo}/programs-v2 --library-name {n} --base-image img"
                                            for n in ("knos_oidc", "knos_pay")]
    deploy = repo / "programs-v2" / "target" / "deploy"
    assert (deploy / "knos_pay.so").read_text().strip() == f"built from {repo}/programs-v2/knos_pay"
    assert (deploy / ".verified-build").read_text().splitlines()[0].endswith(" img")
    # unchanged sources, or a change under a target folder or in programs/ (which the build does not read): no rebuild
    (repo / "programs-v2" / "target" / "scratch.txt").write_text("x")
    (repo / "programs" / "knos_pay" / "Cargo.toml").write_text("changed")
    again = run()
    assert again.returncode == 0 and "unchanged since the last verified build" in again.stdout and len(log.read_text().splitlines()) == 2
    # the interface crate knos_meter reads is a source of the build: a change to it builds again
    (repo / "crates" / "knos-oidc-interface" / "src" / "lib.rs").write_text("changed")
    third = run()
    assert third.returncode == 0 and "unchanged" not in third.stdout and len(log.read_text().splitlines()) == 4


def test_a_verified_build_of_the_first_deployments_crate_of_the_same_name_is_refused_not_stamped(tmp_path):
    """The repository holds programs/knos_pay and programs-v2/knos_pay, and solana-verify builds the first manifest
    `find` lists. Where programs/ comes first, it builds the first deployment's crate elsewhere and hashes whatever
    programs-v2/target/deploy holds: a file build_programs_v2.sh left there (plain cargo build-sbf) must not be stamped
    as the verified build."""
    repo, log, run = _build_world(tmp_path)
    deploy = repo / "programs-v2" / "target" / "deploy"
    deploy.mkdir(parents=True)
    for n in ("knos_oidc", "knos_pay"):
        (deploy / f"{n}.so").write_text("cargo build-sbf, not reproducible")
    wrong = run(FIRST="programs")
    assert wrong.returncode != 0 and "Building manifest path" in wrong.stderr and "programs/knos_oidc" in wrong.stderr, wrong.stderr
    assert not (deploy / ".verified-build").exists() and not (deploy / "knos_oidc.so").exists()


def test_the_verified_build_and_its_stamp_need_no_sha256sum_where_the_system_has_only_shasum(tmp_path):
    """macOS has shasum and no sha256sum. With a PATH that has every command of /usr/bin and /bin but sha256sum, the
    build hashes its sources and stamps its files with shasum -a 256, and a stamp written where sha256sum is (Linux) is
    read there as the same build: the two write the same lines."""
    import shutil
    repo, log, run = _build_world(tmp_path)
    if not shutil.which("shasum", path="/usr/bin:/bin"):
        pytest.skip("needs shasum (perl's), which macOS and the Linux runners have")
    no_sha256sum = tmp_path / "no-sha256sum"
    no_sha256sum.mkdir()
    for d_ in ("/usr/bin", "/bin"):
        for f in Path(d_).iterdir():
            if f.name != "sha256sum" and not (no_sha256sum / f.name).exists():
                (no_sha256sum / f.name).symlink_to(f)
    assert shutil.which("sha256sum", path=str(no_sha256sum)) is None
    first = run()
    assert first.returncode == 0, first.stderr
    stamp = repo / "programs-v2" / "target" / "deploy" / ".verified-build"
    written = stamp.read_text()
    again = run(path=str(no_sha256sum))
    assert again.returncode == 0, again.stderr
    assert "unchanged since the last verified build" in again.stdout and len(log.read_text().splitlines()) == 2
    # a change of the sources builds again, and the stamp shasum writes is the one sha256sum wrote for the same files
    (repo / "crates" / "knos-oidc-interface" / "src" / "lib.rs").write_text("changed")
    third = run(path=str(no_sha256sum))
    assert third.returncode == 0 and "unchanged" not in third.stdout and len(log.read_text().splitlines()) == 4, third.stderr
    assert "sha256sum" not in third.stderr and stamp.read_text().splitlines()[1:] == written.splitlines()[1:]
    assert stamp.read_text().splitlines()[0] != written.splitlines()[0]
    fourth = run()
    assert fourth.returncode == 0 and "unchanged since the last verified build" in fourth.stdout, fourth.stderr


# ---- 0.3.14: a proposal that must not execute is withdrawn before its replacement is proposed ---------------------------

def _proposals(plan: list[tuple[int, str, str, bytes | None]]) -> dict:
    """The upgrade multisig with these proposals (index, Squads status, program name, the build in its buffer; None: the
    buffer is closed), in the account layouts scripts/upgrade_feed.py reads."""
    import sys
    sys.path.insert(0, str(ROOT / "tests"))
    import test_upgrade_feed as f
    accounts, rows = {}, []
    for index, status, name, elf in plan:
        buffer = str(Keypair().pubkey())
        if elf is not None:
            accounts[buffer] = f.buffer(elf)
        rows.append((index, status, f.NOW - 41 * 3600, 2 if status == "Approved" else 1, f.vault_transaction_account(pay.IDS[name], buffer)))
    return f.world(rows, accounts), f


def _entries(accounts: dict, f) -> list[dict]:
    return [vars(e) for e in f.uf.entries(accounts.get, f.IDS)[1]]


BAD_OIDC, BAD_PAY = b"\x7fELF oidc 0.3.13", b"\x7fELF pay 0.3.13, pays twice"
THIS = {name: mc.elf_hash(f"\x7fELF {name} 0.3.14".encode()) for name in ("knos_oidc", "knos_pay", "knos_meter", "knos_passkey")}


def test_an_older_proposal_that_can_still_run_stops_the_proposing_and_replace_lists_it_to_be_withdrawn_first():
    # devnet as 0.3.13 left it: proposals 1 and 2, approved, in their 48 hours
    accounts, f = _proposals([(1, "Approved", "knos_oidc", BAD_OIDC), (2, "Approved", "knos_pay", BAD_PAY)])
    entries = _entries(accounts, f)
    withdraw, refusal = d.replace_plan(entries, THIS, replace=False)
    assert withdraw == [] and refusal.startswith("refused: proposal 1 (knos_oidc, build " + mc.elf_hash(BAD_OIDC))
    assert f"proposal 2 (knos_pay, build {mc.elf_hash(BAD_PAY)}, approved: it can be executed from {d.when(f.NOW + 7 * 3600)})" in refusal
    assert "would deploy another build than this one. Nothing was proposed." in refusal
    assert refusal.endswith("pass --replace: bash scripts/deploy_v2.sh --propose --replace")
    withdraw, refusal = d.replace_plan(entries, THIS, replace=True)
    assert refusal is None and [(e["index"], e["program"], e["build_hash"], e["squads_status"]) for e in withdraw] == [
        (1, "knos_oidc", mc.elf_hash(BAD_OIDC), "Approved"), (2, "knos_pay", mc.elf_hash(BAD_PAY), "Approved")]
    # a program that runs this build already is not proposed, and an older proposal for it must still go: executed, it
    # would put the withdrawn build back. So every program is asked about, whatever is proposed this time
    assert [e["index"] for e in d.older(entries, {"knos_pay": THIS["knos_pay"]})] == [2]
    # once they are cancelled nothing stands in the way, with or without the flag
    accounts, f = _proposals([(1, "Cancelled", "knos_oidc", BAD_OIDC), (2, "Cancelled", "knos_pay", BAD_PAY)])
    assert d.replace_plan(_entries(accounts, f), THIS, False) == ([], None) == d.replace_plan(_entries(accounts, f), THIS, True)


def test_this_builds_own_proposal_is_kept_and_what_is_not_known_to_be_this_build_is_not():
    elf = {name: f"\x7fELF {name} 0.3.14".encode() for name in THIS}
    accounts, f = _proposals([
        (1, "Cancelled", "knos_oidc", BAD_OIDC), (2, "Cancelled", "knos_pay", BAD_PAY),
        (3, "Approved", "knos_oidc", elf["knos_oidc"]),        # a run of --propose that stopped after its first proposal: kept, and continued
        (4, "Active", "knos_pay", BAD_PAY),                    # one vote short, of the build that must not run: another vote would start its 48 hours
        (5, "Approved", "knos_meter", None),                   # its buffer is gone: nobody can say it is this build
        (6, "Executed", "knos_passkey", BAD_PAY),              # ran: nothing to withdraw
        (7, "Rejected", "knos_passkey", BAD_PAY)])
    entries = _entries(accounts, f)
    assert [(e["index"], e["squads_status"]) for e in d.older(entries, THIS)] == [(4, "Active"), (5, "Approved")]
    _none, refusal = d.replace_plan(entries, THIS, False)
    assert "proposal 4 (knos_pay, build " + mc.elf_hash(BAD_PAY) + ", active: it can still be approved)" in refusal
    assert "proposal 5 (knos_meter, build unknown: its buffer cannot be read, approved: it can be executed from" in refusal and "withdraw them" in refusal
    # this build's own proposal is found by its build, so a second run proposes with its buffer and never makes another
    own = next(e for e in entries if e["index"] == 3)
    assert d.kept(entries, "knos_oidc", THIS["knos_oidc"]) == own["buffer"] and d.kept(entries, "knos_pay", THIS["knos_pay"]) is None
    assert d.kept(entries, "knos_passkey", mc.elf_hash(BAD_PAY)) is None           # executed and rejected proposals carry nothing forward
    # at or below the multisig's stale index a proposal can never run: not in the way
    accounts[f.IDS["upgrade_multisig"]] = f.world([(7, "Rejected", 0, 0, None)], {}, stale=5)[f.IDS["upgrade_multisig"]]
    assert d.older(_entries(accounts, f), THIS) == []


def test_the_stale_step_prints_what_to_withdraw_or_refuses_with_exit_5(monkeypatch, capsys):
    accounts, f = _proposals([(1, "Approved", "knos_oidc", BAD_OIDC), (2, "Approved", "knos_pay", BAD_PAY)])
    monkeypatch.setattr(d.mc, "_rpc", lambda url: accounts.get)
    builds = [f"{name}={h}" for name, h in THIS.items()]
    assert d.main(["stale", *builds]) == 5
    said = capsys.readouterr()
    assert said.out == "" and "pass --replace" in said.err and "proposal 2 (knos_pay" in said.err
    assert d.main(["--replace", "stale", *builds]) == 0
    assert capsys.readouterr().out.splitlines() == [f"1 knos_oidc {mc.elf_hash(BAD_OIDC)} Approved", f"2 knos_pay {mc.elf_hash(BAD_PAY)} Approved"]
    assert d.main(["kept", f"knos_pay={mc.elf_hash(BAD_PAY)}"]) == 0 and capsys.readouterr().out.strip() == next(e["buffer"] for e in _entries(accounts, f) if e["index"] == 2)
    assert d.main(["kept", builds[1]]) == 0 and capsys.readouterr().out.strip() == ""
    with pytest.raises(SystemExit, match="stale takes NAME=HASH"):
        d.main(["stale", "upgrade_gate=" + "ab" * 32])
    with pytest.raises(SystemExit, match="stale takes NAME=HASH"):
        d.main(["stale"])


def _withdraw_world(tmp_path, stale_answers: list[tuple[int, str]]):
    """deploy_v2.sh's withdraw_older() under the script's shell options, with stand-ins for deploy_v2.py (its answers to
    `stale`, in turn) and governance.mjs: what the script does with what they say."""
    import os
    import re
    import shutil
    import subprocess
    bash = shutil.which("bash")
    if os.name == "nt" or not bash:
        pytest.skip("runs the script's function with bash")
    text = (ROOT / "scripts" / "deploy_v2.sh").read_text(encoding="utf-8")
    func = re.search(r"(?ms)^withdraw_older\(\) \{.*?^\}$", text).group(0)
    tmp_path = tmp_path / f"world-{len(list(tmp_path.iterdir()))}"
    keys, calls = tmp_path / "keys", tmp_path / "calls"
    keys.mkdir(parents=True)
    for n, (rc, out) in enumerate(stale_answers, 1):
        (tmp_path / f"stale-{n}").write_text(f"{rc}\n{out}", encoding="utf-8")
    body = "\n".join([
        "set -euo pipefail", f'KEYS={keys} SCHEDULE={keys}/upgrade-schedule.json RPC=http://127.0.0.1:9 SO_DIR=/so', 'UPGRADES="knos_oidc knos_pay knos_meter knos_passkey"',
        'die() { echo "stopped: $*" >&2; exit 1; }',
        f'py() {{ if [ "$1" = hash ]; then basename "$2" .so; return; fi; echo "py $*" >> {calls}; n=$(grep -c "stale" {calls}); '
        f'tail -n +2 {tmp_path}/stale-$n; [ "$(head -1 {tmp_path}/stale-$n)" = 0 ] || {{ echo "refused: pass --replace" >&2; return "$(head -1 {tmp_path}/stale-$n)"; }}; }}',
        f'governance() {{ echo "governance $*" >> {calls}; [ "$3" != "${{FAIL:-}}" ] || {{ echo "refused: not a member" >&2; return 1; }}; echo "on chain now: proposal $3 of the upgrade multisig is cancelled: it can never be executed."; }}',
        func, "withdraw_older", "echo PROPOSING"])

    def run(replace: bool, **env) -> subprocess.CompletedProcess:
        return subprocess.run([bash, "-c", f"REPLACE={int(replace)}\n{body}"], capture_output=True, text=True, timeout=60, env={"PATH": "/usr/bin:/bin", **env})
    return keys, calls, run


OLD = "1 knos_oidc a9dd1d07bad629cf1d43242ea927e811b43ae03122db814826fcaf5276847805 Approved\n2 knos_pay 69ec05b83e29b92fb255fd7f0cd52e128e04a4c9dbc5e16eecdc39caaafed9c9 Approved\n"


def test_replace_withdraws_each_older_proposal_says_which_and_proposes_only_once_the_chain_shows_them_gone(tmp_path):
    keys, calls, run = _withdraw_world(tmp_path, [(0, OLD), (0, "")])
    (keys / "upgrade-schedule.json").write_text("{}", encoding="utf-8")
    (keys / "upgrade-run.timer").write_text("systemd knos-upgrade\n", encoding="utf-8")
    done = run(True)
    assert done.returncode == 0, done.stderr
    said = calls.read_text(encoding="utf-8").splitlines()
    builds = "knos_oidc=knos_oidc knos_pay=knos_pay knos_meter=knos_meter knos_passkey=knos_passkey"      # every program's build is asked about
    assert said == [f"py --replace stale {builds}", "governance cancel upgrade 1", "governance cancel upgrade 2", f"py --replace stale {builds}"]
    out = done.stdout
    assert "REPLACING proposal 1: knos_oidc, build a9dd1d07bad629cf1d43242ea927e811b43ae03122db814826fcaf5276847805 (Approved)" in out
    assert "REPLACING proposal 2: knos_pay, build 69ec05b83e29b92fb255fd7f0cd52e128e04a4c9dbc5e16eecdc39caaafed9c9 (Approved)" in out
    assert out.index("REPLACING proposal 2") < out.index("proposal 2 of the upgrade multisig is cancelled") < out.index("PROPOSING")
    # the schedule of what was withdrawn is set aside, and a timer still arranged for it is named with the way to take it back
    assert not (keys / "upgrade-schedule.json").exists() and (keys / "upgrade-schedule.json.withdrawn").exists()
    assert "a timer for the withdrawn proposals is still arranged (systemd knos-upgrade)" in out and "bash scripts/schedule_upgrade.sh --cancel" in out


def test_without_replace_or_when_a_withdrawal_did_not_happen_nothing_is_proposed(tmp_path):
    keys, calls, run = _withdraw_world(tmp_path, [(5, "")])
    refused = run(False)
    assert refused.returncode == 1 and "PROPOSING" not in refused.stdout and "pass --replace" in refused.stderr
    assert [c for c in calls.read_text(encoding="utf-8").splitlines() if c.startswith("governance")] == []       # nothing was cancelled without the flag
    assert calls.read_text(encoding="utf-8").startswith("py stale ")
    # a member key that cannot cancel: the script stops at that proposal
    keys, calls, run = _withdraw_world(tmp_path, [(0, OLD), (0, "")])
    failed = run(True, FAIL="1")
    assert failed.returncode == 1 and "PROPOSING" not in failed.stdout and "proposal 1 (knos_oidc, build a9dd1d07" in failed.stderr and "was NOT withdrawn" in failed.stderr
    assert "it can still be executed. Nothing was proposed" in failed.stderr
    # the votes went out but the chain still shows one approved (one member key short of the threshold): not proposed
    keys, calls, run = _withdraw_world(tmp_path, [(0, OLD), (0, OLD.splitlines()[1] + "\n")])
    short = run(True)
    assert short.returncode == 1 and "PROPOSING" not in short.stdout
    assert "still not withdrawn: proposal 2 (knos_pay, build 69ec05b83e29b92fb255fd7f0cd52e128e04a4c9dbc5e16eecdc39caaafed9c9). Nothing was proposed" in short.stderr
    # nothing in the way: said, and on to the proposing; the cluster not answering stops it
    keys, calls, run = _withdraw_world(tmp_path, [(0, "")])
    clear = run(False)
    assert clear.returncode == 0 and "no older proposal that can still run" in clear.stdout and "PROPOSING" in clear.stdout
    keys, calls, run = _withdraw_world(tmp_path, [(1, "")])
    down = run(True)
    assert down.returncode == 1 and "could not be read" in down.stderr and "PROPOSING" not in down.stdout


def test_a_build_larger_than_the_programs_data_account_is_seen_and_the_extension_is_the_loaders_own_instruction():
    ledger = Ledger()
    where = mc.programdata_address(pay.IDS["knos_pay"])
    assert d.room(ledger, "knos_pay") is None                      # not deployed
    ledger.accounts[str(where)] = bytes(mc.PROGRAMDATA_HEADER) + bytes(383_744)     # devnet on 4 October 2026: twice the 2.0 build
    assert d.room(ledger, "knos_pay") == 383_744
    payer = Keypair()
    ix = d.extend_ix(pay.IDS["knos_pay"], payer.pubkey(), 19_928)
    assert str(ix.program_id) == d.LOADER and ix.data == bytes([6, 0, 0, 0]) + (19_928).to_bytes(4, "little")
    assert [(str(a.pubkey), a.is_signer, a.is_writable) for a in ix.accounts] == [
        (str(where), False, True), (pay.IDS["knos_pay"], False, True), ("11111111111111111111111111111111", False, False), (str(payer.pubkey()), True, True)]
    for bad in (0, -1, 2 ** 32):
        with pytest.raises(SystemExit, match="a program is extended by 1 to"):
            d.extend_ix(pay.IDS["knos_pay"], payer.pubkey(), bad)


# ---- --propose makes its plan first: a release proposes the programs it changes, and no other ---------------------------------

FOUR = ("knos_oidc", "knos_pay", "knos_meter", "knos_passkey")


def _plan_world(tmp_path, chain: dict[str, str], built: dict[str, str]):
    """deploy_v2.sh's plan() under the script's shell options. `chain`: the build each program runs (or "absent");
    `built`: the build of each file in the folder --propose was given. Everything that could send is a stand-in that
    writes its name to a file, so a test sees that the plan only reads."""
    import os
    import re
    import subprocess

    import _posix
    if os.name == "nt":
        pytest.skip("runs the script's function with bash, on paths as a POSIX system writes them")
    bash = _posix.bash()                                    # the one way a test finds a bash (tests/_posix.py)
    text = (ROOT / "scripts" / "deploy_v2.sh").read_text(encoding="utf-8")
    func = re.search(r"(?ms)^plan\(\) \{.*?^\}$", text).group(0)
    changes = re.search(r'(?m)^CHANGES="\$\{KNOS_CHANGES:-(.*)\}"$', text).group(1)
    world = tmp_path / f"plan-{len(list(tmp_path.iterdir()))}"
    world.mkdir()
    for name in FOUR:
        (world / f"chain-{name}").write_text(chain[name], encoding="utf-8")
        (world / f"built-{name}").write_text(built[name], encoding="utf-8")
    body = "\n".join([
        "set -euo pipefail", f"ROOT={ROOT} SO_DIR=/so", f'UPGRADES="{" ".join(FOUR)}"', f'CHANGES="${{KNOS_CHANGES:-{changes}}}"',
        'die() { echo "stopped: $*" >&2; exit 1; }', 'pinned() { echo "id-of-$1"; }',
        f'py() {{ [ "$1" = hash ] || {{ echo "py $*" >> {world}/sent; return 1; }}; cat {world}/built-$(basename "$2" .so); }}',
        f'program_state() {{ HAVE="$(cat {world}/chain-$1)"; AUTHORITY=vault; }}',
        f'governance() {{ echo "governance $*" >> {world}/sent; }}', f'sol() {{ echo "sol $*" >> {world}/sent; }}',
        func, "plan", 'echo "PLAN=[$PLAN]"'])

    def run(**env) -> subprocess.CompletedProcess:
        done = subprocess.run([bash, "-c", body], capture_output=True, text=True, encoding="utf-8", timeout=60, env={"PATH": "/usr/bin:/bin", **env})
        assert not (world / "sent").exists(), "the plan sent something: it only reads"
        return done
    return run, changes


def test_the_plan_of_this_release_is_knos_oidc_alone_and_a_rebuild_of_an_unchanged_program_is_never_proposed(tmp_path):
    """0.3.16 proposes ONE upgrade. After proposals 3 to 6 the chain runs the verified builds of the v0.3.14 tag; the
    release's build of knos_oidc differs from it and nothing else may. The plan is made before anything is withdrawn,
    written or proposed, so a file whose bytes moved without the release meaning it stops the run instead of becoming
    a proposal."""
    old = {name: f"{name}-at-0.3.14" for name in FOUR}
    run, changes = _plan_world(tmp_path, old, {**old, "knos_oidc": "knos_oidc-2.2"})
    assert changes == "knos_oidc"                                 # what this tree's script proposes when nothing overrides it
    done = run()
    assert done.returncode == 0, done.stderr
    assert done.stdout.splitlines() == ["  the plan: propose knos_oidc (this release changes: knos_oidc)", "PLAN=[knos_oidc]"]
    # the upgrade has executed (or the run is repeated after it): nothing is left to propose
    run, _ = _plan_world(tmp_path, {**old, "knos_oidc": "knos_oidc-2.2"}, {**old, "knos_oidc": "knos_oidc-2.2"})
    assert run().stdout.splitlines() == ["  the plan: propose nothing (this release changes: knos_oidc)", "PLAN=[]"]
    # a rebuild of knos_pay from the release's tree whose bytes are not the chain's: nothing is proposed, not even knos_oidc
    run, _ = _plan_world(tmp_path, old, {**old, "knos_oidc": "knos_oidc-2.2", "knos_pay": "knos_pay-rebuilt"})
    done = run()
    assert done.returncode == 1 and "PLAN=" not in done.stdout and "the plan:" not in done.stdout
    said = done.stderr
    assert said.startswith("stopped: knos_pay is not a program this release changes (it changes: knos_oidc)")
    assert "the build in /so (knos_pay-rebuilt) is not the one knos_pay id-of-knos_pay runs (knos_pay-at-0.3.14)" in said
    assert "Nothing was withdrawn, written or proposed" in said and "have not all executed: knos status" in said
    assert "The chain runs the verified build of the v0.3.14 tag" in said and 'KNOS_CHANGES="knos_oidc knos_pay"' in said
    # the same stop while the earlier proposals have not executed: every program still runs an older build
    before = {name: f"{name}-older" for name in FOUR}
    run, _ = _plan_world(tmp_path, before, {**old, "knos_oidc": "knos_oidc-2.2"})
    done = run()
    assert done.returncode == 1 and "stopped: knos_pay is not a program this release changes" in done.stderr
    # a release that does change a second program says so, and both are proposed in the order they execute
    run, _ = _plan_world(tmp_path, old, {**old, "knos_oidc": "knos_oidc-2.2", "knos_pay": "knos_pay-2.2"})
    done = run(KNOS_CHANGES="knos_pay knos_oidc")
    assert done.returncode == 0 and done.stdout.splitlines()[-1] == "PLAN=[knos_oidc knos_pay]"
    # a program that is not there cannot be upgraded
    run, _ = _plan_world(tmp_path, {**old, "knos_meter": "absent"}, {**old, "knos_oidc": "knos_oidc-2.2"})
    assert "knos_meter id-of-knos_meter is not deployed on this cluster" in run().stderr


def test_the_plan_comes_before_anything_is_withdrawn_and_the_three_unchanged_programs_are_held_where_the_chain_has_them():
    import re
    import shutil
    import subprocess
    text = (ROOT / "scripts" / "deploy_v2.sh").read_text(encoding="utf-8")
    pr = text[text.index("propose() {"):text.index("# ---- run")]
    assert pr.index("\n  plan\n") < pr.index("withdraw_older\n") < pr.index("for name in $UPGRADES") and "runs this build already" in pr
    assert text.index("\nplan() {") < text.index("\npropose() {") and "KNOS_CHANGES" in text[:text.index("set -euo pipefail")]
    # one source for the tag the unchanged programs' builds are of: scripts/bump_version.py
    bump = (ROOT / "scripts" / "bump_version.py").read_text(encoding="utf-8")
    held = re.search(r"(?m)^PROGRAMS_FROZEN: tuple\[str, \.\.\.\] = \((.*)\)$", bump).group(1)
    at = re.search(r'(?m)^FROZEN_AT = "([^"]+)"$', bump).group(1)
    assert """sed -n 's/^FROZEN_AT = "\\(.*\\)"$/\\1/p' "$ROOT/scripts/bump_version.py\"""" in text
    unchanged = [name for name in FOUR if name != "knos_oidc"]
    for name in unchanged:
        # held by bump_version, at that version: a bump cannot move its bytes with a version string
        assert f'"{name}"' in held and f'name = "{name}"\nversion = "{at}"' in (ROOT / "programs-v2" / name / "Cargo.toml").read_text(encoding="utf-8").replace("\r\n", "\n")
    # what the stop says about knos_pay is true of this tree: it is the one program that links knos_oidc
    links = [name for name in FOUR if re.search(r'(?m)^knos_oidc = \{ path = "\.\./knos_oidc"', (ROOT / "programs-v2" / name / "Cargo.toml").read_text(encoding="utf-8"))]
    assert links == ["knos_pay"] and "knos_pay links knos_oidc (programs-v2/knos_pay/Cargo.toml)" in text
    # and no line of the three, or of what only they are built from, moved since that tag (where git has it)
    git = shutil.which("git")
    if git and subprocess.run([git, "rev-parse", "-q", "--verify", f"v{at}^{{commit}}"], cwd=ROOT, capture_output=True).returncode == 0:
        own = [p for name in unchanged for p in (f"programs-v2/{name}/src", f"programs-v2/{name}/Cargo.toml")]
        shared = ["crates/knos-oidc-interface/src", "crates/knos-oidc-interface/Cargo.toml", "crates/knos-pay-interface/src", "crates/knos-pay-interface/Cargo.toml"]
        moved = subprocess.run([git, "diff", "--name-only", f"v{at}", "--", *own, *shared], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=True).stdout.split()
        assert moved == [], f"this release changes knos_oidc alone, and these moved since v{at}: {moved}"
