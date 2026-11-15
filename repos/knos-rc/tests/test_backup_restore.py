"""Back up the record, lose it, restore it, get the same statements byte for byte (the pre-launch list, item 10).

The backup is `knos archive make` (src/knos/archive.py): one deterministic .zip of the log of events, the ledgers and
the statements, with its own verifier. The restore is unzipping it. Nothing here needs a network or a clock."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

import _es256
from knos import cli
from knos import events as E
from knos import statement as S
from test_archive import _evidence
from test_events import BUYER, SELLER, Key, _b64

HEAD = {"date": "2026-10-31", "invoice": "INV-7", "supplier": str(SELLER), "buyer": str(BUYER), "currency": "USD"}


@pytest.fixture(scope="module")
def given():
    """test_archive's small month: a log, a ledger, a statement for accounts payable, the issuer's keys."""
    x, y = _es256.mul(_es256.KEY_A, _es256.G)
    key = Key("knos archive test key")
    jwks = {"keys": [key.jwk("k1"), {"kty": "EC", "crv": "P-256", "alg": "ES256", "kid": "es1", "x": _b64(x.to_bytes(32, "big")),
                                    "y": _b64(y.to_bytes(32, "big"))}]}
    return _evidence(key, jwks), jwks


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def test_back_up_delete_restore_and_the_statements_are_byte_identical(tmp_path, given, capsys):
    ev, jwks = given
    live = tmp_path / "live"
    live.mkdir()
    (live / "events.jsonl").write_bytes(ev["events"])
    (live / "events.jsonl.jwks.json").write_text(json.dumps(jwks), encoding="utf-8")
    (live / "buyer.jsonl").write_bytes(ev["ledgers"]["buyer.jsonl"])
    (live / "ap-statement.json").write_bytes(ev["statements"]["ap-statement.json"])
    log, wrong = E.read(ev["events"].decode("utf-8"), jwks)
    assert not wrong
    month = sorted(log.by_month)[0]
    before = {p.name: _sha(p) for p in live.iterdir()}
    made_statement = S.canonical(S.make(ev["events"], HEAD))
    assert made_statement == ev["statements"]["ap-statement.json"]

    # 1. back up: the command an operator runs (documented in docs/reference/RETENTION.md)
    backup = tmp_path / "offsite" / "knos-2026-10.zip"
    backup.parent.mkdir()
    assert cli.main(["archive", "make", str(backup), "--events", str(live / "events.jsonl"), "--ledger", str(live / "buyer.jsonl"),
                     "--statement", str(live / "ap-statement.json"), "--keys-read", "2026-10-07", "--sealed", "2026-11-01"]) == 0
    assert "evidence files, root " in capsys.readouterr().out

    # 2. lose everything that was live
    for p in list(live.iterdir()):
        p.unlink()
    live.rmdir()
    assert not live.exists()

    # 3. restore: unzip, and the copy checks itself with no Knos
    restored = tmp_path / "restored"
    with zipfile.ZipFile(backup) as z:
        z.extractall(restored)
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    done = subprocess.run([sys.executable, "-I", "verify.py"], cwd=restored, capture_output=True, encoding="utf-8", env=env, timeout=120)
    assert done.returncode == 0 and "VERIFIED:" in done.stdout, done.stdout + done.stderr

    # 4. the same bytes: every file kept, and every statement made again from the restored log
    assert _sha(restored / "events" / "log.jsonl") == before["events.jsonl"]
    assert _sha(restored / "ledgers" / "buyer.jsonl") == before["buyer.jsonl"]
    assert _sha(restored / "statements" / "ap-statement.json") == before["ap-statement.json"]
    again = (restored / "events" / "log.jsonl").read_bytes()
    assert S.canonical(S.make(again, HEAD)) == made_statement
    relog, wrong = E.read(again.decode("utf-8"), jwks)
    assert not wrong and relog.head == log.head
    from knos.ledger import canon
    assert (restored / "statements" / f"events-{month}.json").read_bytes() == (canon(E.statement(relog, month)) + "\n").encode()

    # 5. a backup of the restored files is the same archive, byte for byte
    (tmp_path / "jwks.json").write_text(json.dumps(jwks), encoding="utf-8")
    again_zip = tmp_path / "again.zip"
    assert cli.main(["archive", "make", str(again_zip), "--events", str(restored / "events" / "log.jsonl"), "--ledger",
                     str(restored / "ledgers" / "buyer.jsonl"), "--statement", str(restored / "statements" / "ap-statement.json"),
                     "--keys", str(tmp_path / "jwks.json"), "--keys-read", "2026-10-07", "--sealed", "2026-11-01"]) == 0
    capsys.readouterr()
    assert again_zip.read_bytes() == backup.read_bytes()
