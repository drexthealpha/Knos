"""Tests for `knos agent record --json` (drexthealpha/Knos#9)."""

from __future__ import annotations

import json
import secrets
import sqlite3
import time
from pathlib import Path

import pytest
from solders.keypair import Keypair
from solders.pubkey import Pubkey

from _devchain import URL, devchain, new_team
from knos.cli import main
from knos.team import config, live, records, schemas, units


def _setup_team_and_runtime(repo: Path, host: str = "claude") -> tuple[live.Runtime, Keypair, bytes]:
    owner = Keypair()
    cred = Keypair().pubkey()
    claim_s = Keypair().pubkey()
    renew_s = Keypair().pubkey()
    member_s = Keypair().pubkey()
    rec_s = Keypair().pubkey()
    salt = secrets.token_bytes(32)

    knos_dir = repo / ".knos"
    knos_dir.mkdir(parents=True, exist_ok=True)
    tf_data = {
        "cluster": "devnet",
        "credential": str(cred),
        "name": "core-team",
        "authority": str(owner.pubkey()),
        "schemas": {
            "claim": str(claim_s),
            "renew": str(renew_s),
            "member": str(member_s),
            "record": str(rec_s),
        },
        "repo_id": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
    }
    (knos_dir / "team.json").write_text(json.dumps(tf_data, indent=2), encoding="utf-8")

    config.write_member_key(owner)
    config.store_salt(cred, salt)

    rt = live.runtime(repo)
    assert rt is not None
    holder = rt.holder(host, "sess-1").hash(salt)
    return rt, owner, holder


def test_agent_record_json_no_holders(repo, capsys, monkeypatch):
    """When an agent has no events in the period, --json emits empty holders list."""
    _setup_team_and_runtime(repo, "claude")
    monkeypatch.chdir(repo)

    rc = main(["agent", "record", "claude", "--days", "3", "--json"])
    assert rc == 0
    got = capsys.readouterr()
    parsed = json.loads(got.out)
    assert parsed == {"host": "claude-code", "days": 3, "holders": []}


def test_agent_record_json_with_mocked_chain(repo, capsys, monkeypatch):
    """When an agent has past events and today's events, --json outputs machine-readable records."""
    rt, owner, holder = _setup_team_and_runtime(repo, "claude")
    monkeypatch.chdir(repo)

    today = records.period_start()
    yesterday = today - records.DAY

    conn = rt.db()
    conn.execute("INSERT INTO events VALUES (?,?,?)",
                 (yesterday + 100, "claim", json.dumps({"holder": holder.hex(), "claim": "a.py"})))
    conn.execute("INSERT INTO events VALUES (?,?,?)",
                 (yesterday + 200, "release", json.dumps({"holder": holder.hex(), "claim": "a.py"})))
    conn.execute("INSERT INTO events VALUES (?,?,?)",
                 (today + 50, "claim", json.dumps({"holder": holder.hex(), "claim": "b.py"})))
    conn.close()

    mock_rec = schemas.RecordData(
        holder=holder, period_start=yesterday, taken=1, finished=1,
        abandoned=0, collisions=0, spent_micro_usd=0, merkle_root=b"R" * 32,
    )

    def mock_verify(url, credential, period):
        return {
            "on_chain": True,
            "signer": str(owner.pubkey()),
            "counters_match": True,
            "root_matches": True,
            "record": mock_rec,
        }

    monkeypatch.setattr(records, "verify", mock_verify)

    rc = main(["agent", "record", "claude", "--days", "2", "--json"])
    assert rc == 0
    got = capsys.readouterr()
    parsed = json.loads(got.out)

    assert parsed["host"] == "claude-code"
    assert parsed["days"] == 2
    assert len(parsed["holders"]) == 1
    h_entry = parsed["holders"][0]
    assert h_entry["holder"] == holder.hex()
    recs = h_entry["records"]
    assert len(recs) == 2

    y_rec = [r for r in recs if r["period_start"] == yesterday][0]
    assert y_rec["taken"] == 1
    assert y_rec["finished"] == 1
    assert y_rec["on_chain"] is True
    assert y_rec["verified"] is True
    assert y_rec["record_on_chain"]["merkle_root"] == (b"R" * 32).hex()

    t_rec = [r for r in recs if r["period_start"] == today][0]
    assert t_rec["taken"] == 1
    assert t_rec["today"] is True
    assert t_rec["on_chain"] is False
    assert "written to chain tomorrow" in t_rec["status"]


@devchain
def test_agent_record_json_with_written_record_on_validator(repo, capsys, monkeypatch):
    """Acceptance test: a written record on the local validator is parsed and verified via --json."""
    team, _, (a,) = new_team(1)
    tf = config.TeamFile(
        "localnet", team.credential, "knos-t", a.pubkey(),
        {"claim": team.claim_schema, "renew": team.renew_schema, "record": sas.schema_pda(team.credential, schemas.RECORD[0])},
        team.repo_id, URL,
    )
    config.save(repo, tf)
    config.write_member_key(a)
    config.store_salt(team.credential, team.salt)
    monkeypatch.chdir(repo)

    rt = live.runtime(repo)
    assert rt is not None
    holder = rt.holder("codex", "sess-1").hash(team.salt)

    start = records.period_start() - records.DAY
    conn = rt.db()
    conn.execute("INSERT INTO events VALUES (?,?,?)",
                 (start + 10, "claim", json.dumps({"holder": holder.hex(), "claim": "file1.py"})))
    conn.execute("INSERT INTO events VALUES (?,?,?)",
                 (start + 20, "release", json.dumps({"holder": holder.hex(), "claim": "file1.py"})))
    conn.close()

    p = live.period_of(rt, holder, start)
    tx_sig = records.write(URL, team.credential, a, p)
    assert tx_sig is not None

    rc = main(["agent", "record", "codex", "--days", "2", "--json"])
    assert rc == 0
    got = capsys.readouterr()
    parsed = json.loads(got.out)
    assert parsed["host"] == "codex"
    assert len(parsed["holders"]) >= 1

    h_entry = [h for h in parsed["holders"] if h["holder"] == holder.hex()][0]
    rec = [r for r in h_entry["records"] if r["period_start"] == start][0]
    assert rec["on_chain"] is True
    assert rec["counters_match"] is True
    assert rec["root_matches"] is True
    assert rec["verified"] is True
    assert rec["signer"] == str(a.pubkey())
