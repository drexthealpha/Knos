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
    assert pr.index("UNGATED: --ungated WAS PASSED. THIS IS FOR AN EMERGENCY ONLY") < pr.index("for name in $PROGRAMS") and "wait=0" in pr
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
        said = subprocess.run([bash, str(ROOT / "scripts" / "deploy_v2.sh"), "--help"], capture_output=True, text=True).stdout
        assert all(flag in said for flag in ("--new", "--rc ", "--rc-close", "--propose [--ungated]", "KNOS_GATE_TOKENS", "KNOS_RC_SO_DIR",
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
    # the reader deploy_v2.sh had before: the stand-in shows the race is real, not something this test made up
    early = afford("lamports() { sol \"$@\" --lamports | awk 'NF >= 2 { print $(NF - 1); exit }'; }")
    assert early.returncode != 0 and early.stdout == ""


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
    body = "\n".join(['set -euo pipefail', f'ROOT={repo}', 'PROGRAMS="knos_oidc knos_pay"', 'VERIFY_IMAGE=img',
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
