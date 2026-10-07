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
                     "programs-v2/handlers/Cargo.toml", "programs-v2/handlers/Cargo.lock",
                     ".github/workflows/prove.yml", ".github/workflows/check.yml", "docs/INSTALL.md",
                     # what this release added: the outside reproduction's install, and the action a repository calls by tag
                     "examples/knos-reproduce.yml", ".github/workflows/knos-reproduce.yml", ".github/actions/knos-verify/action.yml",
                     "integrations/workflows/knos-verify.yml"}
    # the crates a program is built from, their lock entries and the IDLs: places too, moved by a bump or held (next test)
    programs = {"crates/knos-oidc-interface/Cargo.toml", "crates/knos-pay-interface/Cargo.toml", "crates/knos-oidc-interface/Cargo.lock",
                "programs-v2/Cargo.lock", "programs-v2/knos_oidc/fuzz/Cargo.lock", "programs-v2/handlers/Cargo.lock", "examples/upgrade_gate/Cargo.lock",
                "idl/knos_pay_v2.json", "idl/knos_oidc_v2.json", "idl/knos_meter.json", "idl/knos_passkey.json",
                *(f"programs-v2/{crate}/Cargo.toml" for crate in ("knos_oidc", "knos_pay", "knos_meter", "knos_passkey"))}
    held = b.frozen_places()
    places = b.places()                                                               # read once: every call reads every place again
    assert programs <= {rel for rel, _l, _g in (*held, *places)}                      # held or moved: scripts/bump_version.py says which
    assert sum(r == "server.json" for r, _l, _g in places) == 2                      # the server and its package
    assert sum(r == "programs-v2/Cargo.lock" for r, _l, _g in (*held, *places)) >= 5  # five crates of ours
    # the first deployment is never a place, and neither is a third party's version that happens to sit in a lock file
    assert not [rel for rel in named if rel.startswith("programs/") or rel.endswith("package-lock.json")]


def test_a_release_that_changes_no_program_leaves_every_program_crate_where_its_builds_are():
    """A crate's version is in its build's bytes. While PROGRAMS_FROZEN names crates, they, their lock entries and the
    IDLs stay at FROZEN_AT whatever the package's version is, so the committed builds are still builds of this tree."""
    if not b.PROGRAMS_FROZEN:
        assert b.frozen_places() == [] and b.LOCKED_FROZEN is None
        return
    # which crates are frozen is scripts/bump_version.py's to say (PROGRAMS_FROZEN): nothing here lists them, so a crate
    # that leaves the set (a program this release changes) is held to the package's version instead, with no edit here
    crates = set(b.OURS[1:]) - {"knos-handler-tests"}
    assert set(b.PROGRAMS_FROZEN) <= crates and re.fullmatch(r"\d+\.\d+\.\d+", b.FROZEN_AT)
    held = b.frozen_places()
    assert held and {got for _r, _l, got in held} == {b.FROZEN_AT}
    assert not {(rel, line) for rel, line, _g in held} & {(rel, line) for rel, line, _g in b.places()}       # a place is one or the other
    # each crate's own manifest says its version: FROZEN_AT when frozen, the package's otherwise
    for crate in sorted(crates):
        folder = "programs-v2" if (ROOT / "programs-v2" / crate).is_dir() else "crates"
        manifest = (ROOT / folder / crate / "Cargo.toml").read_text(encoding="utf-8")
        want = b.FROZEN_AT if crate in b.PROGRAMS_FROZEN else b.project()
        assert f'name = "{crate}"\nversion = "{want}"' in manifest.replace("\r\n", "\n"), crate
    for lock in (path for pattern in b.LOCKS for path in ROOT.glob(pattern)):
        for name, version in re.findall(r'name = "([^"]+)"\r?\nversion = "([^"]+)"', lock.read_text(encoding="utf-8")):
            if name in b.OURS[1:]:
                assert version == (b.FROZEN_AT if name in b.PROGRAMS_FROZEN else b.project()), (lock.name, name)
    # the handler tests are in no program's build: their own version moves with the release
    assert ("programs-v2/handlers/Cargo.toml", b.project()) in {(rel, got) for rel, _l, got in b.places()}


def test_the_example_that_builds_against_a_tag_keeps_a_tag_that_exists():
    """examples/reader_template takes the interface crate from GitHub by tag, and its lock holds that tag's commit. A
    release's own tag exists only after the push, so no bump moves this one: it is the tag the frozen crate was made at."""
    here = ROOT / "examples" / "reader_template"
    [tag] = re.findall(r'git = "https://github.com/drexthealpha/Knos", tag = "v(\d+\.\d+\.\d+)"', (here / "Cargo.toml").read_text(encoding="utf-8"))
    assert tag == b.FROZEN_AT and f"Knos?tag=v{tag}#" in (here / "Cargo.lock").read_text(encoding="utf-8")
    assert not [rel for rel in b.found()[0] if rel.startswith("examples/reader_template/")]


def test_a_bump_holds_the_frozen_crates_puts_back_one_that_was_moved_and_check_names_it(tmp_path):
    if not b.PROGRAMS_FROZEN:
        pytest.skip("no program crate is frozen in this release")
    root = _copy(tmp_path)
    held = b.frozen_places(root)
    whole = [rel for rel in {rel for rel, _l, _g in held} if rel not in {rel for rel, _l, _g in b.places(root)}]
    before = {rel: (root / rel).read_bytes() for rel in whole}
    b.bump(NEW, root)
    assert b.frozen_places(root) == held                                             # every frozen place, as it was
    assert before and {rel: (root / rel).read_bytes() for rel in before} == before   # and not one byte of a file that holds only such places
    assert b.disagreements(NEW, root, changelog=False) == []
    crate = sorted(b.PROGRAMS_FROZEN)[0]                                              # any frozen crate: the script names them
    rel = f"{'programs-v2' if (root / 'programs-v2' / crate).is_dir() else 'crates'}/{crate}/Cargo.toml"
    moved = root / rel
    assert f'version = "{b.FROZEN_AT}"'.encode() in moved.read_bytes()
    moved.write_bytes(moved.read_bytes().replace(f'version = "{b.FROZEN_AT}"'.encode(), f'version = "{NEW}"'.encode(), 1))
    [said] = b.disagreements(NEW, root, changelog=False)
    assert re.fullmatch(rf"{re.escape(rel)}:\d+: {re.escape(NEW)}, not {re.escape(b.FROZEN_AT)} \(a program crate, frozen.*", said), said
    assert b.bump(NEW, root) == [rel] and {rel: (root / rel).read_bytes() for rel in before} == before


def _copy(tmp_path: Path) -> Path:
    """The files that are places, and nothing else, as a tree of their own."""
    for rel in {rel for rel, _l, _g in (*b.places(), *b.frozen_places())} | {"CHANGELOG.md"}:
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / rel, tmp_path / rel)
    b.bump(b.project(), tmp_path)             # the copy starts consistent, whatever this tree is in the middle of
    return tmp_path


def test_a_bump_writes_every_place_changes_nothing_else_and_a_second_run_changes_nothing(tmp_path):
    root, old = _copy(tmp_path), b.project()
    before = {rel: (root / rel).read_bytes() for rel, _l, _g in b.places(root)}
    start = len(b.places(root))
    changed = b.bump(NEW, root)
    assert sorted(changed) == sorted(before) and b.project(root) == NEW     # every place that moves (a file of frozen places only is not one)
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
    sdk = root / "sdk" / "settle" / "package.json"
    sdk.write_text(sdk.read_text(encoding="utf-8").replace(f'"version": "{old}"', '"version": "0.0.1"', 1), encoding="utf-8")
    assert b.disagreements(root=root, changelog=False) == [f"sdk/settle/package.json:3: 0.0.1, not {old}"]
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


def test_a_bump_adds_the_tags_key_to_the_action_pins_and_never_renames_an_earlier_tags_commit(tmp_path):
    """A commit cannot name itself: the release's tag gets a key whose value is the placeholder, and the earlier
    tag keeps the commit it names (the supplier workflow runs the action at it)."""
    import json
    root, old = _copy(tmp_path), b.project()
    (root / "scripts").mkdir(exist_ok=True)
    pins = {"note": "n", "pins": {"actions/checkout@v7": "3" * 40, "drexthealpha/Knos@" + "v0.0.1": "f" * 40, "x/y@v1": "1" * 40}}
    (root / b.SELF_PINS).write_text(json.dumps(pins, indent=1) + "\n", encoding="utf-8")
    assert f"{b.SELF_PINS}: no key drexthealpha/Knos@v{old} " in "\n".join(b.disagreements(root=root, changelog=False))
    assert b.SELF_PINS in b.bump(NEW, root)
    got = json.loads((root / b.SELF_PINS).read_text(encoding="utf-8"))["pins"]
    assert got == {**pins["pins"], f"drexthealpha/Knos@v{NEW}": b.SELF_PIN} and list(got)[2] == f"drexthealpha/Knos@v{NEW}"
    assert b.bump(NEW, root) == [] and b.disagreements(NEW, root, changelog=False) == []
    # this tree: the release's key is there, and the action the supplier workflow runs is an earlier tag's commit
    here = json.loads((ROOT / b.SELF_PINS).read_text(encoding="utf-8"))["pins"]
    assert here[f"drexthealpha/Knos@v{old}"] == b.SELF_PIN or re.fullmatch(r"[0-9a-f]{40}", here[f"drexthealpha/Knos@v{old}"])
    used = re.search(r"uses: drexthealpha/Knos@([0-9a-f]{40})", (ROOT / ".github" / "workflows" / "supplier.yml").read_text(encoding="utf-8")).group(1)
    assert used in here.values()
