"""The naive check, kept beside the real one to show what it lets through: it runs inside the pull request's tree
(in-process), runs analysis.py once on the data in that tree and compares the number with RESULT.json. A script that
prints the claimed number passes it. Nobody should fund on this bundle; bundle 1 is the one that is paid."""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SEED = 20261005


def test_the_script_prints_the_claimed_estimate():
    claim = json.loads((ROOT / "RESULT.json").read_text(encoding="utf-8"))
    got = subprocess.run([sys.executable, "analysis.py", str(SEED)], input=(ROOT / "data" / "trial.csv").read_bytes(),
                         capture_output=True, cwd=ROOT, timeout=60, check=True)
    assert claim["seed"] == SEED and abs(float(got.stdout.decode().strip()) - claim["estimate"]) <= 1e-6
