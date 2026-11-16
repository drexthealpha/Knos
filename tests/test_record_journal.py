"""Knos Record's journal: append-only JSON Lines, hash-chained, each line held in the memory engine in its tier
(claims WARM, events COLD, papers REFERENCE), and nothing that may not be public goes in (src/knos/record/journal.py)."""

from __future__ import annotations

import contextlib
import json
import sqlite3

import pytest

from knos import record
from knos.record import journal

SPEC = "a" * 64


@pytest.fixture()
def rec(tmp_path):
    return tmp_path / "rec"


def test_lines_chain_and_land_in_their_memory_tiers(rec):
    c = record.claim("claim-1", {"title": "synthetic claim", "spec_hash": SPEC, "synthetic": True}, domain="ml", root=rec)
    v = record.append("verdict", {"spec_hash": SPEC, "passed": False, "cheat": "test_edited", "synthetic": True}, claim="claim-1", root=rec)
    p = record.paper("arxiv:2401.00001", {"title": "a paper", "sha256": "b" * 64}, root=rec)
    assert [e["seq"] for e in (c, v, p)] == [0, 1, 2]
    assert (c["tier"], v["tier"], p["tier"]) == ("WARM", "COLD", "REFERENCE")
    assert c["prev"] == journal.GENESIS and v["prev"] == c["hash"] and p["prev"] == v["hash"]
    assert all(e["hash"] == record.line_hash(e) for e in (c, v, p))
    lines = (rec / "journal.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(x) for x in lines] == [c, v, p] == record.entries(rec)
    st = record.sibyl(rec)
    assert record.claim_state("claim-1", store=st)["_hash"] == c["hash"]                    # WARM: the claim's state
    assert st.reference("record:paper:arxiv:2401.00001")["_hash"] == p["hash"]              # REFERENCE: the paper
    assert [e["hash"] for e in record.remembered(st)] == [c["hash"], v["hash"], p["hash"]]   # COLD: every line
    assert [e["kind"] for e in record.claim_events("claim-1", store=st)] == ["claim", "verdict"]
    with contextlib.closing(sqlite3.connect(rec / "sibyl.db")) as con:                       # in the memory engine's own tables
        assert con.execute("select count(*) from journal_events").fetchone()[0] == 3
        assert con.execute("select count(*) from entities where category = 'record_claim'").fetchone()[0] == 1


def test_a_new_claim_state_replaces_the_warm_entity_and_keeps_the_old_line(rec):
    first = record.claim("c", {"state": "open"}, root=rec)
    second = record.claim("c", {"state": "graduated"}, root=rec)
    assert record.claim_state("c", root=rec)["state"] == "graduated"
    assert record.claim_state("c", root=rec)["_hash"] == second["hash"]
    assert [e["payload"]["state"] for e in record.entries(rec)] == ["open", "graduated"] and first["seq"] == 0


@pytest.mark.parametrize("payload, why", [
    ({"token": "x"}, "named like a secret"),
    ({"private_key": "x"}, "named like a secret"),
    ({"note": "ghp_" + "A" * 36}, "GitHub token"),
    ({"note": "github_pat_" + "A" * 40}, "GitHub token"),
    ({"note": "-----BEGIN PRIVATE KEY-----"}, "PEM"),
    ({"note": "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJyZXBvIn0.c2lnbmF0dXJlc2ln"}, "JWT"),
    ({"by": "someone@example.com"}, "e-mail"),
    ({"log": "/home/alice/work/run.txt"}, "home path"),
    ({"key": list(range(64))}, "64 bytes"),
    ({"blob": "5" * 88}, "base58"),
    ({"blob": "ab" * 64}, "hex"),
    ({"x": float("nan")}, "finite"),
])
def test_nothing_secret_or_personal_goes_in_and_nothing_is_written(rec, payload, why):
    with pytest.raises(record.RecordError, match=why):
        record.append("verdict", payload, root=rec)
    assert not (rec / "journal.jsonl").exists()


def test_public_values_that_look_like_keys_are_taken_under_the_names_that_say_what_they_are(rec):
    sig = "5" * 88
    e = record.append("payout", {"tx": sig, "amount": 1_000_000, "spec_hash": SPEC, "commit": "c" * 40, "synthetic": True}, root=rec)
    assert e["payload"]["tx"] == sig


def test_kinds_ids_and_size_are_checked(rec):
    with pytest.raises(record.RecordError, match="not a record kind"):
        record.append("rumour", {}, root=rec)
    with pytest.raises(record.RecordError, match="names its claim"):
        record.append("claim", {}, root=rec)
    with pytest.raises(record.RecordError, match="claim id"):
        record.append("verdict", {}, claim="has space", root=rec)
    with pytest.raises(record.RecordError, match="at most"):
        record.append("verdict", {"x": "y" * (journal.MAX_PAYLOAD_BYTES + 1)}, root=rec)
    with pytest.raises(ValueError):                      # RecordError is a ValueError, for callers that catch that
        record.append("verdict", "not a dict", root=rec)
    assert record.entries(rec) == []


def test_without_the_memory_engine_there_is_no_record(rec, monkeypatch):
    import sys
    monkeypatch.setitem(sys.modules, "sibyl_memory_client", None)
    with pytest.raises(ImportError):
        record.append("verdict", {"passed": True}, root=rec)
    assert not (rec / "journal.jsonl").exists()              # the memory engine first, then the file: nothing half-written


def test_the_default_place_is_knos_home(knos_home, monkeypatch):
    assert record.default_root() == knos_home / "record"
    monkeypatch.setenv("KNOS_RECORD_DIR", str(knos_home / "elsewhere"))
    assert record.journal_path() == knos_home / "elsewhere" / "journal.jsonl"
