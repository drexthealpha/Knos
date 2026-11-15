"""scripts/secret_scan.py on a fixture repository: a key committed and deleted later is found in the history by its
kind, never printed; a test's made-up key is told apart; a keypair of an address Knos operates with must be rotated; a
blob a person has reviewed passes. Everything runs on a git repository made in tmp_path; no network."""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "secret_scan.py"
spec = importlib.util.spec_from_file_location("secret_scan", SCRIPT)
assert spec and spec.loader
scan = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scan)

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="needs git")

# Made-up values, put together here so that this file holds none of them whole.
GH_TOKEN = "gh" + "p_" + "Q7x" * 12
AWS_ID = "AK" + "IA" + "Z9Y8X7W6V5U4T3S2"
ENV = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_AUTHOR_DATE": "2026-10-01T00:00:00Z",
       "GIT_COMMITTER_DATE": "2026-10-01T00:00:00Z"}


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@x", "-c", "commit.gpgsign=false", *args],
                          check=True, capture_output=True, encoding="utf-8", env=ENV).stdout


def keypair_bytes(seed: int) -> bytes:
    from solders.keypair import Keypair
    return bytes(Keypair.from_seed(bytes([seed]) * 32).to_bytes())


def address(seed: int) -> str:
    from solders.keypair import Keypair
    return str(Keypair.from_seed(bytes([seed]) * 32).pubkey())


def run(repo: Path, *args: str) -> tuple[int, str]:
    p = subprocess.run([sys.executable, str(SCRIPT), "--repo", str(repo), *args], capture_output=True, encoding="utf-8", env=ENV)
    return p.returncode, p.stdout + p.stderr


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "repo"
    r.mkdir()
    git(r, "init", "-q")
    (r / "README.md").write_text("a repository\n", encoding="utf-8")
    (r / "deploy.env").write_text(f"TOKEN={GH_TOKEN}\n", encoding="utf-8")
    git(r, "add", "-A")
    git(r, "commit", "-qm", "one")
    (r / "deploy.env").unlink()
    git(r, "add", "-A")
    git(r, "commit", "-qm", "two: the token is gone from the tree")
    return r


def test_a_key_deleted_from_the_tree_is_still_found_in_history_by_kind_without_its_value(repo: Path):
    code, out = run(repo)
    assert code == 0 and "nothing to rotate" in out                     # the tree is clean
    code, out = run(repo, "--history")
    assert code == 1 and "look: GitHub token in deploy.env" in out and GH_TOKEN not in out and GH_TOKEN[:12] not in out
    code, out = run(repo, "--history", "--json")
    doc = json.loads(out)
    assert code == 1 and doc["scope"] == "history" and doc["rotate"] == ["GitHub token"] and GH_TOKEN not in out
    assert doc["by_kind"] == [{"kind": "GitHub token", "verdict": "look", "blobs": 1}]
    hit = doc["hits"][0]
    assert set(hit) == {"kind", "path", "blob", "verdict"} and len(hit["blob"]) == 12


def test_a_made_up_key_in_a_test_is_a_test_key_and_passes(repo: Path):
    (repo / "tests").mkdir()
    (repo / "tests" / "test_redact.py").write_text(f'SAMPLE = "{AWS_ID}"\n', encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "three")
    out = scan.scan(scan.tree_blobs(repo), set())
    assert out["hits"] == [{"kind": "AWS access key id", "path": "tests/test_redact.py", "blob": "", "verdict": "test key"}] and out["rotate"] == []


def test_a_keypair_of_an_operated_address_must_be_rotated_wherever_it_sits(repo: Path):
    pytest.importorskip("solders")
    ids = repo / "src" / "knos" / "settle" / "v2"
    ids.mkdir(parents=True)
    (ids / "program_ids.json").write_text(json.dumps({"guardian": address(7)}), encoding="utf-8")
    (repo / "tests").mkdir()
    (repo / "tests" / "fixture-keypair.json").write_text(json.dumps(list(keypair_bytes(7))), encoding="utf-8")
    (repo / "tests" / "other-keypair.json").write_text(json.dumps(list(keypair_bytes(8))), encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "four")
    out = scan.scan(scan.tree_blobs(repo), scan.operational(repo))
    got = {h["path"]: h["verdict"] for h in out["hits"]}
    assert got == {"tests/fixture-keypair.json": "operational", "tests/other-keypair.json": "test key"}
    assert out["rotate"] == ["Solana keypair (64-byte array)"]
    code, text = run(repo)
    assert code == 1 and "operational: Solana keypair (64-byte array) in tests/fixture-keypair.json" in text
    assert str(list(keypair_bytes(7))[:8])[1:-1] not in text


def test_a_reviewed_blob_passes_and_a_changed_one_is_read_again(repo: Path, monkeypatch):
    blob = git(repo, "rev-list", "--all", "--objects").split()
    oid = next(b for i, b in enumerate(blob) if i + 1 < len(blob) and blob[i + 1] == "deploy.env")
    monkeypatch.setattr(scan, "REVIEWED", {oid: "a made-up token"})
    out = scan.scan(scan.history_blobs(repo), set())
    assert [h["verdict"] for h in out["hits"]] == ["reviewed"] and out["rotate"] == []
    git(repo, "checkout", "-q", "HEAD~1", "--", "deploy.env")
    (repo / "deploy.env").write_text(f"TOKEN={GH_TOKEN}\n# changed\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "five")
    out = scan.scan(scan.history_blobs(repo), set())
    assert sorted(h["verdict"] for h in out["hits"]) == ["look", "reviewed"]


def test_a_reviewed_key_whose_address_becomes_operated_must_be_rotated(repo: Path, monkeypatch):
    """The review of a spent key does not outlive its address becoming one Knos operates with."""
    pytest.importorskip("solders")
    (repo / "target").mkdir()
    (repo / "target" / "spent-keypair.json").write_text(json.dumps(list(keypair_bytes(9))), encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "a build output, read and passed")
    oid = git(repo, "rev-parse", "HEAD:target/spent-keypair.json").strip()
    monkeypatch.setattr(scan, "REVIEWED", {oid: "a spent build key"})
    key = lambda out: [h["verdict"] for h in out["hits"] if h["path"] == "target/spent-keypair.json"]  # noqa: E731
    out = scan.scan(scan.history_blobs(repo), scan.operational(repo))
    assert key(out) == ["reviewed"] and "Solana keypair (64-byte array)" not in out["rotate"]
    ids = repo / "src" / "knos" / "settle" / "v2"
    ids.mkdir(parents=True)
    (ids / "program_ids.json").write_text(json.dumps({"knos_pay": address(9)}), encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "its address becomes a program id")
    out = scan.scan(scan.history_blobs(repo), scan.operational(repo))
    assert key(out) == ["operational"] and "Solana keypair (64-byte array)" in out["rotate"]


def test_binary_blobs_are_skipped_and_counted(repo: Path):
    (repo / "blob.bin").write_bytes(b"\0" + GH_TOKEN.encode())
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "six")
    out = scan.scan(scan.tree_blobs(repo), set())
    assert out["skipped"] == 1 and out["hits"] == []


def test_a_directory_that_is_not_a_repository_exits_2(tmp_path: Path):
    alone = tmp_path / "alone"
    alone.mkdir()
    p = subprocess.run([sys.executable, str(SCRIPT), "--repo", str(alone), "--history"], capture_output=True, encoding="utf-8",
                       env={**ENV, "GIT_CEILING_DIRECTORIES": str(tmp_path)})
    code, out = p.returncode, p.stdout + p.stderr
    assert code == 2 and "git could not read" in out


def test_the_patterns_match_their_published_formats_and_not_a_signature_or_a_hash():
    kinds = {k for k, _ in scan.scan_bytes(f"{GH_TOKEN} {AWS_ID}".encode())}
    assert kinds == {"GitHub token", "AWS access key id"}
    sig = "5" * 88                                                      # a transaction signature's shape
    sha = "8b3c044024eac6e00cf10930c325465d5682c3fb7273fe2f0d59c6e01f99867c"
    assert list(scan.scan_bytes(f"{sig} {sha} FkwZdsYCmzicJMtHLTkPK76bYNVG4WNwkWJBiVWNtF3W".encode())) == []
