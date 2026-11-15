"""The Tempo escrow contract (contracts/KnosEscrow.sol) under Foundry: the live Moderato run's attacks and edge paths,
the mainnet cap and pause, paid on proof, the minimum job and fee floor, and a 1,000-run conservation fuzz (10,000 under
FOUNDRY_PROFILE=nightly). Skipped when Foundry is not installed."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1] / "contracts"


def _forge() -> str | None:
    return shutil.which("forge") or next((str(p) for p in (Path.home() / ".foundry" / "bin" / "forge",
                                                             Path.home() / ".foundry" / "bin" / "forge.exe")
                                          if p.exists()), None)


FORGE = _forge()  # resolved at import: the suite's fixtures give each test a fake HOME


@pytest.mark.skipif(FORGE is None, reason="Foundry not installed")
def test_escrow_contract_under_foundry():
    env = {**os.environ, "FOUNDRY_DISABLE_NIGHTLY_WARNING": "1"}
    got = subprocess.run([FORGE, "test", "--root", str(ROOT)], capture_output=True, text=True, env=env, timeout=600)
    assert got.returncode == 0, got.stdout[-3000:] + got.stderr[-2000:]
    assert "13 passed; 0 failed" in got.stdout   # 0.3.6: + 6 ERC-8183 tests
