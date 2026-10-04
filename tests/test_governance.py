"""scripts/governance.mjs against the Python client, offline.

The Python client (src/knos/settle/v2) and knos.mainnet_check are the authority: scripts/governance_fixture.py writes what
the Node script must agree with (the pinned addresses, the bytes and accounts of the instructions the guardian's vault
signs, the Squads and loader accounts as the programs lay them out) to tests/fixtures/governance_v2.json, and
scripts/governance.test.mjs holds the script to it with no network and no key of ours.

These tests check that the fixture is current and run the Node tests. Without Node 20 or the packages
(`npm ci --prefix scripts`) the Node tests are skipped, and say so.
"""

from __future__ import annotations

import importlib.util
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from knos import mainnet_check as mc
from knos.settle.v2 import oidc, pay

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "governance_v2.json"


def _generator():
    spec = importlib.util.spec_from_file_location("governance_fixture", ROOT / "scripts" / "governance_fixture.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_fixture_is_what_the_generator_writes(capsys):
    assert _generator().main(["--check"]) == 0, capsys.readouterr().err


def test_the_fixture_says_what_programs_v2_pins():
    fx = json.loads(FIXTURE.read_text(encoding="utf-8"))
    pins = json.loads((ROOT / "programs-v2" / "program_ids.json").read_text(encoding="utf-8"))
    assert pins == oidc.IDS      # the client's copy is the repository's
    assert (fx["programs"]["knos_oidc"], fx["programs"]["knos_pay"], fx["programs"]["squads"]) == (pins["knos_oidc"], pins["knos_pay"], pins["squads_program"])
    assert fx["guardian"] == pins["guardian"] == str(oidc.GUARDIAN) == str(pay.GUARDIAN)
    assert {n: (m["multisig"], m["vault"], m["time_lock"]) for n, m in fx["multisigs"].items()} == {
        "upgrade": (pins["upgrade_multisig"], pins["upgrade_authority"], mc.TIME_LOCK),
        "guardian": (pins["guardian_multisig"], pins["guardian"], 0)}


def test_the_fixtures_instructions_are_the_documented_ones():
    """Approve is tag 6, Revoke tag 7 (knos_oidc), Pause tag 9 and a u32 (knos_pay), Upgrade variant 3 of the loader: the
    Node script's bytes are held to these. The guardian's instructions touch a key account, the pause account and the payer
    that funds the pause account's rent, and nothing else is writable in them: none moves money."""
    fx = json.loads(FIXTURE.read_text(encoding="utf-8"))
    ix = fx["instructions"]
    assert [ix[f"guardian {a} github"]["data"] for a in ("approve", "revoke")] == ["06", "07"]
    assert ix["guardian pause 600"]["data"] == "09" + (600).to_bytes(4, "little").hex()
    assert ix["guardian pause 604800"]["data"] == "09" + pay.PAUSE_MAX.to_bytes(4, "little").hex()
    assert ix["upgrade knos_pay"]["data"] == "03000000"
    allowed = {fx["addresses"]["key(github)"], fx["addresses"]["key(gitlab)"], fx["addresses"]["pause"], fx["inputs"]["payer"]}
    for name, one in ix.items():
        assert one["program"] == (str(mc.LOADER) if name.startswith("upgrade") else oidc.IDS["knos_pay" if "pause" in name else "knos_oidc"]), name
        if name.startswith("guardian"):
            signers = [a["pubkey"] for a in one["accounts"] if a["signer"]]
            assert signers[0] == str(oidc.GUARDIAN), name
            assert {a["pubkey"] for a in one["accounts"] if a["writable"]} <= allowed, name


def _node() -> str:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed: install Node 20 or later, then npm ci --prefix scripts")
    version = subprocess.run([node, "--version"], capture_output=True, text=True, timeout=30).stdout.strip()
    if not re.match(r"v(\d+)\.", version) or int(re.match(r"v(\d+)\.", version).group(1)) < 20:
        pytest.skip(f"node {version} is older than 20")
    if not (ROOT / "scripts" / "node_modules" / "@sqds" / "multisig").is_dir():
        pytest.skip("the packages are not installed: npm ci --prefix scripts")
    return node


def test_governance_mjs_agrees_with_the_python_client():
    node = _node()
    done = subprocess.run([node, "--test", "scripts/governance.test.mjs"], cwd=ROOT, capture_output=True, text=True, timeout=240)
    summary = "\n".join(line for line in done.stdout.splitlines() if line.startswith(("# tests", "# pass", "# fail")) or line.startswith("not ok"))
    assert done.returncode == 0, f"{summary}\n{done.stdout[-3000:]}\n{done.stderr[-1000:]}"
    assert re.search(r"^# pass (\d+)$", done.stdout, re.M) and int(re.search(r"^# pass (\d+)$", done.stdout, re.M).group(1)) >= 20


def test_upgrade_propose_refuses_a_buffer_whose_build_the_gate_has_not_recorded():
    """examples/upgrade_gate records ["build", program, executable hash] only on GitHub's signed word that this repository's
    program.yml built those bytes. `upgrade propose` reads that record before it proposes anything: without one it refuses,
    unless --ungated is passed. The record the Node script is held to is one the program itself wrote in LiteSVM
    (tests/fixtures/upgrade_gate.json), at the address the Python client derives."""
    import os
    import sys

    from knos.settle.v2 import gate
    pytest.importorskip("solders.litesvm")
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "upgrade_gate_fixture.py"), "--check"], capture_output=True, text=True, check=False,
                       env={**os.environ, "PYTHONPATH": str(ROOT / "src")})
    assert r.returncode == 0, r.stderr or r.stdout
    fx = json.loads((ROOT / "tests" / "fixtures" / "upgrade_gate.json").read_text(encoding="utf-8"))
    rec = gate.read_record(bytes.fromhex(fx["record_data"]))
    assert (str(rec.program), rec.executable.hex(), rec.sha) == (fx["program"], fx["executable_hash"], fx["commit"])
    assert str(gate.record_pda(rec.program, rec.executable)) == fx["record"] and fx["gate"] == str(gate.GATE_ID)
    assert gate.executable_hash(bytes.fromhex(fx["elf"]) + bytes(9)).hex() == fx["executable_hash"]
    mjs = (ROOT / "scripts" / "governance.mjs").read_text(encoding="utf-8")
    body = mjs[mjs.index("async function upgrade("):mjs.index("// ---- approve, cancel, execute")]
    assert 0 < body.index("say(gated(await conn.getAccountInfo(buildRecord(program, hash)") < body.index("await propose(")
    assert "o.ungated" in body and "--ungated" in mjs.split("import fs")[0]            # the flag is passed on, and the usage text names it
    node = _node()
    done = subprocess.run([node, "--test", "--test-name-pattern", "upgrade gate|upgrade propose refuses", "scripts/governance.test.mjs"], cwd=ROOT,
                          capture_output=True, text=True, timeout=240)
    assert done.returncode == 0 and re.search(r"^# pass 2$", done.stdout, re.M) and re.search(r"^# fail 0$", done.stdout, re.M), done.stdout[-3000:]
