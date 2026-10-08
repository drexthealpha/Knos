"""`python scripts/provenance.py verify-proposal N`: one upgrade proposal's bytes held to upgrade_gate's record of the
verified build, to the feed, and to a build of the reader's own. On the fixture accounts of tests/test_upgrade_feed.py:
no network."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import provenance as pv  # noqa: E402
from test_upgrade_feed import COMMIT_NEW, ELF_NEW, ELF_OIDC, IDS, first_world  # noqa: E402

from knos.settle.v2 import gate  # noqa: E402

NEW = gate.executable_hash(ELF_NEW).hex()


def run(monkeypatch, *argv: str, feed: dict | None = None) -> tuple[int, list[str]]:
    monkeypatch.setattr(pv, "load", lambda root=pv.ROOT: {"ids": IDS, "upgrades": feed or {}})
    said: list[str] = []
    return pv.verify_main(list(argv), said.append, first_world().get), said


def test_a_proposal_whose_bytes_the_verified_build_recorded_is_verified_and_says_how_to_rebuild_it(monkeypatch):
    code, said = run(monkeypatch, "3")
    assert code == 0 and said[-1] == "proposal 3: VERIFIED"
    assert f"the bytes, read from the buffer: {NEW}" in said
    assert f"upgrade_gate: GitHub's runner built exactly these bytes from commit {COMMIT_NEW} in run 72 of drexthealpha/Knos's program.yml" in said
    assert any(f"git checkout {COMMIT_NEW}" in line for line in said) and any("--library-name knos_pay --base-image" in line for line in said)


def test_your_own_build_decides_and_trailing_zeros_do_not_count(monkeypatch, tmp_path):
    same, other = tmp_path / "same.so", tmp_path / "other.so"
    same.write_bytes(ELF_NEW + bytes(4096))                            # a build file is padded; its hash is not
    other.write_bytes(ELF_OIDC)
    code, said = run(monkeypatch, "3", "--so", str(same))
    assert code == 0 and said[-1] == "proposal 3: VERIFIED against your own build" and f"your build: {NEW}: the SAME bytes" in said
    code, said = run(monkeypatch, "3", "--so", str(other))
    assert code == 1 and said[-1] == "proposal 3: NOT VERIFIED" and any("DIFFERENT bytes: do not vote" in line for line in said)
    assert run(monkeypatch, "3", "--hash", "xyz")[0] == 2


def test_no_gate_record_a_feed_that_disagrees_or_not_an_upgrade_of_knos_is_not_verified(monkeypatch):
    code, said = run(monkeypatch, "4")                                 # knos_oidc, a buffer no verified-build run recorded
    assert code == 1 and any("NO record of a verified-build run" in line for line in said) and said[-1] == "proposal 4: NOT VERIFIED"
    code, said = run(monkeypatch, "3", feed={"entries": [{"index": 3, "build_hash": "0" * 64}]})
    assert code == 1 and f"web/upgrades.json printed ANOTHER hash: {'0' * 64}" in said
    code, said = run(monkeypatch, "5")
    assert code == 1 and said[0].startswith("proposal 5 (Draft): not an upgrade of a Knos program")
    code, said = run(monkeypatch, "99")
    assert code == 1 and "no such proposal" in said[0]


def test_the_script_takes_verify_proposal_as_its_first_word():
    said: list[str] = []
    assert pv.main(["verify-proposal", "3", "--hash", "not-hex"], said.append) == 2 and said[0].startswith("stopped: --hash takes")
