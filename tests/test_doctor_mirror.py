"""Tests for `knos doctor` mirror age and process status (drexthealpha/Knos#5)."""

from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path

from solders.keypair import Keypair

from knos import doctor
from knos.cli import main
from knos.team import config, live


def _setup_team(repo: Path) -> str:
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
    return str(cred)


def _write_mirror_db(cred: str, synced_at: float) -> None:
    d = config.root() / cred
    d.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(d / "mirror.db"))
    conn.execute("CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT)")
    conn.execute("INSERT OR REPLACE INTO meta VALUES ('synced_at', ?)", (str(synced_at),))
    conn.commit()
    conn.close()


def _set_mirror_running(cred: str, running: bool) -> None:
    d = config.root() / cred
    d.mkdir(parents=True, exist_ok=True)
    lock = d / "mirror.pid"
    if running:
        lock.write_text(str(os.getpid()))
    else:
        lock.unlink(missing_ok=True)


def test_doctor_fresh_mirror_and_running(repo, capsys, monkeypatch):
    """A fresh mirror (< 5s old) with knos mirror running passes doctor check."""
    cred = _setup_team(repo)
    monkeypatch.chdir(repo)

    _write_mirror_db(cred, time.time() - 1.2)
    _set_mirror_running(cred, True)

    from knos.team import service
    monkeypatch.setattr(service, "status", lambda tf: {
        "name": "core-team", "cluster": "devnet", "credential": cred,
        "max_signers": 16, "members": [],
    })

    rows = doctor.team(repo)
    mirror_rows = [r for r in rows if r[0] == "local mirror"]
    assert len(mirror_rows) == 1
    name, ok, detail = mirror_rows[0]
    assert ok is True
    assert "fresh" in detail
    assert "knos mirror is running" in detail
    assert "old" in detail

    rc = main(["doctor"])
    assert rc == 0
    got = capsys.readouterr()
    assert "local mirror:" in got.out
    assert "fresh" in got.out
    assert "knos mirror is running" in got.out


def test_doctor_stale_mirror_and_running(repo, capsys, monkeypatch):
    """A stale mirror (> 5s old) with knos mirror running flags warning in doctor check."""
    cred = _setup_team(repo)
    monkeypatch.chdir(repo)

    _write_mirror_db(cred, time.time() - 35.0)
    _set_mirror_running(cred, True)

    from knos.team import service
    monkeypatch.setattr(service, "status", lambda tf: {
        "name": "core-team", "cluster": "devnet", "credential": cred,
        "max_signers": 16, "members": [],
    })

    rows = doctor.team(repo)
    mirror_rows = [r for r in rows if r[0] == "local mirror"]
    assert len(mirror_rows) == 1
    name, ok, detail = mirror_rows[0]
    assert ok is False
    assert "stale" in detail
    assert "knos mirror is running" in detail

    rc = main(["doctor"])
    assert rc == 0
    got = capsys.readouterr()
    assert "local mirror:" in got.out
    assert "stale" in got.out
    assert "knos mirror is running" in got.out


def test_doctor_stale_mirror_not_running(repo, capsys, monkeypatch):
    """A stale mirror with knos mirror stopped reports stale and not running."""
    cred = _setup_team(repo)
    monkeypatch.chdir(repo)

    _write_mirror_db(cred, time.time() - 40.0)
    _set_mirror_running(cred, False)

    from knos.team import service
    monkeypatch.setattr(service, "status", lambda tf: {
        "name": "core-team", "cluster": "devnet", "credential": cred,
        "max_signers": 16, "members": [],
    })

    rows = doctor.team(repo)
    mirror_rows = [r for r in rows if r[0] == "local mirror"]
    assert len(mirror_rows) == 1
    name, ok, detail = mirror_rows[0]
    assert ok is False
    assert "stale" in detail
    assert "knos mirror is not running" in detail


def test_doctor_mirror_never_synced(repo, monkeypatch):
    """A repo with a team but no mirror db reports never synced."""
    cred = _setup_team(repo)
    monkeypatch.chdir(repo)

    _set_mirror_running(cred, False)

    from knos.team import service
    monkeypatch.setattr(service, "status", lambda tf: {
        "name": "core-team", "cluster": "devnet", "credential": cred,
        "max_signers": 16, "members": [],
    })

    rows = doctor.team(repo)
    mirror_rows = [r for r in rows if r[0] == "local mirror"]
    assert len(mirror_rows) == 1
    name, ok, detail = mirror_rows[0]
    assert ok is False
    assert "never synced" in detail
    assert "knos mirror is not running" in detail
