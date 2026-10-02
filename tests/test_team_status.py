"""Tests for `knos team status --json` (drexthealpha/Knos#4)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from solders.keypair import Keypair

from knos.cli import main
from knos.team import config


def _setup_team(repo: Path) -> dict:
    owner = Keypair().pubkey()
    cred = Keypair().pubkey()
    claim_s = Keypair().pubkey()
    renew_s = Keypair().pubkey()
    member_s = Keypair().pubkey()

    knos_dir = repo / ".knos"
    knos_dir.mkdir(parents=True, exist_ok=True)
    tf_data = {
        "cluster": "devnet",
        "credential": str(cred),
        "name": "core-team",
        "authority": str(owner),
        "schemas": {"claim": str(claim_s), "renew": str(renew_s), "member": str(member_s)},
        "repo_id": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
    }
    (knos_dir / "team.json").write_text(json.dumps(tf_data, indent=2), encoding="utf-8")

    sample_status = {
        "name": "core-team",
        "cluster": "devnet",
        "credential": str(cred),
        "rpc": "https://api.devnet.solana.com",
        "max_signers": 16,
        "members": [
            {"key": str(owner), "name": "alice", "owner": True},
            {"key": str(Keypair().pubkey()), "name": "bob", "owner": False},
        ],
        "live_claims": 2,
        "me": {
            "key": str(owner),
            "member": True,
            "sol": 0.045,
            "claims_headroom": 7,
        },
    }
    return sample_status


def test_team_status_json_parses(repo, capsys, monkeypatch):
    """`knos team status --json` emits parseable JSON matching service.status."""
    sample_status = _setup_team(repo)
    monkeypatch.chdir(repo)

    from knos.team import service
    monkeypatch.setattr(service, "status", lambda tf: sample_status)

    rc = main(["team", "status", "--json"])
    assert rc == 0
    got = capsys.readouterr()
    parsed = json.loads(got.out)
    assert parsed == sample_status
    assert parsed["name"] == "core-team"
    assert parsed["me"]["claims_headroom"] == 7
    assert len(parsed["members"]) == 2


def test_labs_team_status_json_parses(repo, capsys, monkeypatch):
    """`knos labs team status --json` works identically."""
    sample_status = _setup_team(repo)
    monkeypatch.chdir(repo)

    from knos.team import service
    monkeypatch.setattr(service, "status", lambda tf: sample_status)

    rc = main(["labs", "team", "status", "--json"])
    assert rc == 0
    got = capsys.readouterr()
    parsed = json.loads(got.out)
    assert parsed == sample_status


def test_team_status_human_output_differs_from_json(repo, capsys, monkeypatch):
    """Without `--json`, output is human-oriented terminal text."""
    sample_status = _setup_team(repo)
    monkeypatch.chdir(repo)

    from knos.team import service
    monkeypatch.setattr(service, "status", lambda tf: sample_status)

    rc = main(["team", "status"])
    assert rc == 0
    got = capsys.readouterr()
    assert "core-team on devnet" in got.out
    assert "members 2 of 16" in got.out
    assert "live claims 2" in got.out
    # Not JSON
    with pytest.raises(json.JSONDecodeError):
        json.loads(got.out)


def test_team_status_json_without_team(repo, capsys, monkeypatch):
    """Running `knos team status --json` without .knos/team.json exits 1."""
    monkeypatch.chdir(repo)
    rc = main(["team", "status", "--json"])
    assert rc == 1
    got = capsys.readouterr()
    assert "This repo has no team yet" in got.out + got.err
