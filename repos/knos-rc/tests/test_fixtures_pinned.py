"""Pinned fixtures: every data file listed in tests/fixtures/SHA256SUMS still has the hash recorded there.

A fixture that changes changes what the tests prove, so a change must show up in review as an edit to SHA256SUMS too.
That holds for the program binaries of the second deployment as well: tests/fixtures/knos_oidc_v2_*.so are what the
tests of programs-v2 run, and scripts/build_programs_v2.sh rewrites their lines when it rebuilds them.

Line endings of text files are normalised to LF before hashing (the repo checks text out as LF; this keeps a CRLF
checkout green). Regenerate a line with: tr -d '\\r' < PATH | sha256sum
A binary file (.gitattributes: *.so, *.bin, *.png) is hashed as it is, since a program can hold the bytes 0D 0A
anywhere: sha256sum PATH
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SUMS = ROOT / "tests" / "fixtures" / "SHA256SUMS"
BINARY = (".so", ".bin", ".png")      # what .gitattributes marks binary: git never rewrites their bytes


def _entries() -> list[tuple[str, str]]:
    out = []
    for line in SUMS.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("#"):
            digest, path = line.split(None, 1)
            out.append((digest, path.strip().lstrip("*")))
    return out


def test_sums_file_lists_fixtures():
    entries = _entries()
    assert entries, "tests/fixtures/SHA256SUMS lists no fixtures"
    assert all(len(d) == 64 and int(d, 16) >= 0 for d, _ in entries)
    assert len({p for _, p in entries}) == len(entries), "a fixture is listed twice"


@pytest.mark.parametrize("digest,path", _entries(), ids=[p for _, p in _entries()])
def test_fixture_hash_is_pinned(digest: str, path: str):
    f = ROOT / path
    assert f.is_file(), f"pinned fixture {path} is missing"
    data = f.read_bytes()
    got = hashlib.sha256(data if f.suffix in BINARY else data.replace(b"\r\n", b"\n")).hexdigest()
    assert got == digest, f"{path} changed: sha256 {got}, pinned {digest}. If intended, update tests/fixtures/SHA256SUMS"


def test_binary_fixtures_are_binary_to_git_and_the_second_deployments_builds_are_pinned():
    attrs = (ROOT / ".gitattributes").read_text(encoding="utf-8").splitlines()
    assert all(f"*{suffix} binary" in attrs for suffix in BINARY)
    pinned = {p for _, p in _entries()}
    built = {f"tests/fixtures/{f.name}" for f in (ROOT / "tests" / "fixtures").glob("*_v2_*.so")}
    assert built and built <= pinned, f"not pinned in tests/fixtures/SHA256SUMS: {sorted(built - pinned)}"
