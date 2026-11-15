"""Root money keys: encrypted at rest, unlocked only at an interactive terminal (5e)."""

from __future__ import annotations

import io
import json
import os
import stat
import sys
from pathlib import Path

import pytest

from knos import keystore


def test_seal_and_unseal_round_trip_with_strong_kdf(tmp_path):
    p = tmp_path / "k.keystore"
    keystore.save(p, b"secret-bytes", "correct horse battery staple", label="t")
    doc = json.loads(p.read_text())
    assert doc["kdf"]["n"] >= 2 ** 17 and doc["kdf"]["r"] == 8 and doc["kdf"]["p"] == 1
    assert doc["cipher"]["name"] == "aes-256-gcm"
    assert b"secret-bytes" not in p.read_bytes()
    assert keystore.load(p, "correct horse battery staple") == b"secret-bytes"
    with pytest.raises(keystore.KeystoreError):
        keystore.load(p, "wrong passphrase here")
    if os.name != "nt":
        assert stat.S_IMODE(p.stat().st_mode) == 0o600


def test_weak_passphrases_and_weakened_files_are_refused(tmp_path):
    with pytest.raises(keystore.KeystoreError):
        keystore.seal(b"x", "short")
    assert keystore.strong_enough("four small words here") and keystore.strong_enough("twelve chars")
    doc = keystore.seal(b"x", "a long enough passphrase")
    doc["kdf"]["n"] = 2 ** 10
    with pytest.raises(keystore.KeystoreError):
        keystore.unseal(doc, "a long enough passphrase")


@pytest.mark.parametrize("env", [{"CLAUDECODE": "1"}, {"CODEX_THREAD_ID": "x"}, {"CI": "true"}, {}])
def test_the_passphrase_is_refused_off_a_terminal_or_inside_an_agent(env, monkeypatch, tmp_path):
    for k in list(os.environ):
        if k in ("CLAUDECODE", "CI") or k.startswith("CODEX_"):
            monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))  # not a TTY
    with pytest.raises(keystore.NotATerminal) as got:
        keystore.ask(tmp_path / "x.keystore", "devnet")
    assert "run this in your own terminal" in str(got.value)


def test_the_test_escape_works_only_for_test_keystores_on_test_clusters(monkeypatch, tmp_path):
    pw = tmp_path / "pw.txt"
    pw.write_text("a long test passphrase\n")
    monkeypatch.setenv("KNOS_TEST_PASSPHRASE_FILE", str(pw))
    inside = Path.home() / ".knos-test-wallets" / "root.keystore"
    assert keystore.ask(inside, "devnet") == "a long test passphrase"
    assert keystore.ask(inside, "moderato") == "a long test passphrase"
    with pytest.raises(keystore.KeystoreError):
        keystore.ask(inside, "mainnet")
    with pytest.raises(keystore.KeystoreError):
        keystore.ask(tmp_path / "elsewhere.keystore", "devnet")
