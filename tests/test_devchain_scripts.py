"""Tests for devchain scripts consistency and documentation (drexthealpha/Knos#10)."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_devchain_ps1_parity_with_sh():
    """devchain.ps1 mirrors devchain.sh parameters, constants, and actions."""
    sh_file = ROOT / "scripts" / "devchain.sh"
    ps1_file = ROOT / "scripts" / "devchain.ps1"

    assert sh_file.exists(), "scripts/devchain.sh must exist"
    assert ps1_file.exists(), "scripts/devchain.ps1 must exist"

    sh_content = sh_file.read_text(encoding="utf-8")
    ps1_content = ps1_file.read_text(encoding="utf-8")

    sas_id = "22zoJMtdu4tQc2PzL74ZUT7FrwgB1Udec8DdW4yw4BdG"
    lighthouse_id = "L2TExMFKdjpN9kozasaurPirfHy9P8sbXoAN1qA3S95"

    assert sas_id in sh_content
    assert sas_id in ps1_content
    assert lighthouse_id in sh_content
    assert lighthouse_id in ps1_content

    for action in ("start", "stop", "status"):
        assert f'"{action}"' in ps1_content or f"'{action}'" in ps1_content or action in ps1_content

    assert "--limit-ledger-size" in ps1_content
    assert "10000" in ps1_content
    assert "--clone-upgradeable-program" in ps1_content
    assert "solana-test-validator" in ps1_content


def test_contributing_documents_devchain_ps1():
    """CONTRIBUTING.md documents devchain.ps1 for Windows."""
    contributing = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
    assert "scripts/devchain.ps1" in contributing
    assert "start" in contributing
