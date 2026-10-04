"""One version everywhere a version lives: scripts/bump_version.py finds every place (the manifests, the lock files, the
IDLs, and every line in the tree that installs or names one release), writes a version in all of them, and says which
disagree. A release changes them together or not at all."""
from __future__ import annotations

import importlib.util
import re
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _script():
    spec = importlib.util.spec_from_file_location("bump_version", ROOT / "scripts" / "bump_version.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


b = _script()
NEW = "9.10.11"                 # never written beside a pin's words in this file, which is itself read for pins


def test_every_place_names_the_version_of_the_package():
    version = b.project()
    assert re.fullmatch(r"\d+\.\d+\.\d+", version)
    # CHANGELOG.md's top entry is written by hand, with the release notes: the gate before the commit holds it to the version
    assert b.disagreements(changelog=False) == []
    named = {rel for rel, _line, _got in b.places()}
    # the places a release is installed from, each found (a pattern that stopped matching would otherwise pass in silence)
    assert named >= {"pyproject.toml", "uv.lock", "server.json", "gemini-extension.json", "plugin/.claude-plugin/plugin.json",
                     "plugin/.codex-plugin/plugin.json", "sdk/settle/package.json", "sdk/settle/README.md",
                     "crates/knos-oidc-interface/Cargo.toml", "crates/knos-pay-interface/Cargo.toml", "crates/knos-oidc-interface/Cargo.lock",
                     "programs-v2/Cargo.lock", "programs-v2/knos_oidc/fuzz/Cargo.lock", "programs-v2/handlers/Cargo.lock", "examples/upgrade_gate/Cargo.lock",
                     "idl/knos_pay_v2.json", "idl/knos_oidc_v2.json", "idl/knos_meter.json", "idl/knos_passkey.json",
                     ".github/workflows/prove.yml", ".github/workflows/check.yml", "docs/INSTALL.md"}
    assert {f"programs-v2/{crate}/Cargo.toml" for crate in ("knos_oidc", "knos_pay", "knos_meter", "knos_passkey")} <= named
    counts = {rel: sum(r == rel for r, _l, _g in b.places()) for rel in named}
    assert counts["server.json"] == 2 and counts["programs-v2/Cargo.lock"] >= 5      # the server and its package; six crates of ours
    # the first deployment is never a place, and neither is a third party's version that happens to sit in a lock file
    assert not [rel for rel in named if rel.startswith("programs/") or rel.endswith("package-lock.json")]


def _copy(tmp_path: Path) -> Path:
    """The files that are places, and nothing else, as a tree of their own."""
    for rel in {rel for rel, _l, _g in b.places()} | {"CHANGELOG.md"}:
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / rel, tmp_path / rel)
    b.bump(b.project(), tmp_path)             # the copy starts consistent, whatever this tree is in the middle of
    return tmp_path


def test_a_bump_writes_every_place_changes_nothing_else_and_a_second_run_changes_nothing(tmp_path):
    root, old = _copy(tmp_path), b.project()
    before = {rel: (root / rel).read_bytes() for rel, _l, _g in b.places(root)}
    start = len(b.places(root))
    changed = b.bump(NEW, root)
    assert sorted(changed) == sorted(before) and b.project(root) == NEW
    assert len(b.places(root)) == start and {got for _r, _l, got in b.places(root)} == {NEW}
    assert b.disagreements(NEW, root, changelog=False) == []
    assert [line for line in b.disagreements(NEW, root) if not line.startswith("CHANGELOG.md")] == []
    assert b.disagreements(NEW, root)[-1].startswith("CHANGELOG.md: its top entry is ")      # said, never written
    for rel, data in before.items():                         # only the version moved: every other byte is the same
        now = (root / rel).read_bytes()
        assert now != data and now.replace(NEW.encode(), old.encode()) == data, rel
    assert b.bump(NEW, root) == []                     # again: nothing to do
    with pytest.raises(SystemExit, match="is not a version"):
        b.bump("v9.10", root)


def test_one_stale_place_is_named_by_file_and_line_and_history_is_left_alone(tmp_path):
    root, old = _copy(tmp_path), b.project()
    (root / "notes.md").write_text(f"Before {old} the wheel was uploaded by hand.\nInstall: `pip install knos=" + f"={old}`\n", encoding="utf-8")
    assert ("notes.md", 2, old) in b.places(root) and ("notes.md", 1, old) not in b.places(root)
    idl = root / "idl" / "knos_meter.json"
    idl.write_text(idl.read_text(encoding="utf-8").replace(f'"version": "{old}"', '"version": "0.0.1"', 1), encoding="utf-8")
    assert b.disagreements(root=root, changelog=False) == [f"idl/knos_meter.json:2: 0.0.1, not {old}"]
    b.bump(NEW, root)
    assert (root / "notes.md").read_text(encoding="utf-8") == f"Before {old} the wheel was uploaded by hand.\nInstall: `pip install knos=" + f"={NEW}`\n"
    # a manifest that lost its version is said, not skipped
    (root / "gemini-extension.json").write_text("{}\n", encoding="utf-8")
    assert "gemini-extension.json: carries no version" in b.disagreements(NEW, root, changelog=False)


@pytest.mark.parametrize("eol", ["\n", "\r\n"])
def test_unlock_removes_an_earlier_releases_lock_line_and_keeps_the_files_line_ends(tmp_path, eol):
    sign = tmp_path / "requirements" / "sign.txt"
    sign.parent.mkdir()
    head = eol.join(["solders==0.29.0 \\", "    --hash=sha256:" + "0" * 64, "    # via -r requirements/sign.in", ""])

    def lock(v: str) -> bytes:              # split, so this file names no pin of its own
        return (head + "knos=" + f"={v} --hash=sha256:" + "a" * 64 + eol).encode()
    sign.write_bytes(lock("1.2.3"))
    assert b.unlock("1.2.4", tmp_path)
    assert sign.read_bytes() == head.encode()           # the solders lines, byte for byte, with the file's own line ends
    assert not b.unlock("1.2.4", tmp_path)               # nothing left to remove
    sign.write_bytes(lock("1.2.4"))
    assert not b.unlock("1.2.4", tmp_path) and sign.read_bytes() == lock("1.2.4")     # a release's own lock stays
