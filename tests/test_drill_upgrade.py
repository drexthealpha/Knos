"""scripts/drill_upgrade.sh, the step that proposes the no-op upgrade when the upgrade gate has no record of the bytes
the program runs: governance.mjs refuses first, the drill proposes with --ungated, and the row it logs says why the gate
has no record as the cluster shows it. Its own functions run here, with stand-ins for governance.mjs and the Solana
command line; nothing reaches a cluster."""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

import _posix

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "drill_upgrade.sh"
STANDINS = r'''
die() { echo "DIE: $*"; exit 3; }
asked=0
gov() {
  asked=$((asked + 1))
  if [ "$asked" = 1 ]; then echo "refused: the upgrade gate has no record that GitHub built abc for knos_pay. Nothing was sent." > "$OUT"; return 1; fi
  echo "on chain now: proposal 1 of the upgrade multisig is approved; it can be executed from 2026-10-06T04:57:25Z (in 48 hours)" > "$OUT"
}
sol() {
  [ "$1 $2" = "program show" ] || { echo "unexpected: sol $*" >&2; return 2; }
  if [ -n "$GATE_SLOT" ]; then echo "Last Deployed In Slot: $GATE_SLOT"; else echo "Error: Unable to find the account $3" >&2; return 1; fi
}
'''


def _functions(*names: str) -> str:
    text = SCRIPT.read_text(encoding="utf-8")
    out = []
    for name in names:
        found = re.search(rf"^{name}\(\) \{{\n.*?^\}}\n", text, re.M | re.S)
        assert found, f"scripts/drill_upgrade.sh has no function {name}"
        out.append(found.group(0))
    return "".join(out)


def _gate(tmp_path, slot: int, gate_slot: int | None) -> str:
    """What the drill logs about the gate when knos_pay was last deployed in `slot` and the gate program in `gate_slot`
    (None: it is not on the cluster)."""
    body = STANDINS + _functions("no_record", "propose") + 'propose\necho "INDEX=$INDEX FROM=$FROM"\necho "GATE=$GATE"\n'
    env = _posix.environ({**os.environ, "ROOT": _posix.path(ROOT), "NAME": "knos_pay", "BUFFER": "Buf", "OUT": _posix.path(tmp_path / "out"),
                          "PYTHON": _posix.path(sys.executable), "SLOT": str(slot), "GATE_SLOT": "" if gate_slot is None else str(gate_slot)})
    r = subprocess.run([_posix.bash(), "-c", body], env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and "DIE" not in r.stdout, (r.stdout, r.stderr)
    assert "INDEX=1 FROM=1791262645" in r.stdout, r.stdout
    return r.stdout.split("GATE=", 1)[1].strip()


def test_a_cluster_without_the_gate_program_is_said_to_have_none_not_that_the_bytes_predate_it(tmp_path):
    # rehearsed in 0.3.14 on a deploy_v2.sh --localnet validator with the verified builds: the row said the bytes were
    # "deployed before the gate existed", and the gate program was not on that cluster at all
    got = _gate(tmp_path, slot=50, gate_slot=None)
    assert got == ("governance.mjs refused it first because the upgrade gate program 2DfVEuBMWvvh3kXZaQwk2SoszJsoV1PTiK1VGCkB55HW is not on "
                   "this cluster, so it holds no record of these bytes, so it was proposed with --ungated"), got
    assert "before the gate" not in got


@pytest.mark.parametrize("slot, gate_slot, said", [
    (50, 100, "the upgrade gate holds no record of these bytes (knos_pay was last deployed in slot 50, before the gate, deployed in slot 100)"),
    (200, 100, "the upgrade gate holds no record of these bytes"),
])
def test_bytes_deployed_before_the_gate_are_said_to_be_only_when_the_slots_show_it(tmp_path, slot, gate_slot, said):
    assert _gate(tmp_path, slot, gate_slot) == f"governance.mjs refused it first because {said}, so it was proposed with --ungated"
