"""The playground in Knos's own issues (decided 14 Oct 2026),
and knos-labs as the tag `archive/labs` (section 3): every constant and page names drexthealpha/Knos, and the files a
stranger's issue and pull request need are in this tree, written by `python scripts/small_repos.py fold`."""
from __future__ import annotations
import pathlib as _pl

import pytest as _pt

if not (_pl.Path(__file__).resolve().parents[1] / "tasks").is_dir():
    _pt.skip("tasks/ left the public repository; this test runs where that folder is kept", allow_module_level=True)

import importlib.util
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
KNOS, OLD = "drexthealpha/Knos", "drexthealpha/knos-playground"


def _script(name: str):
    spec = importlib.util.spec_from_file_location(f"{name}_playground", ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod                  # a dataclass in the script looks its module up there
    spec.loader.exec_module(mod)
    return mod


def _const(path: str, name: str) -> str:
    m = re.search(rf'export const {name} = "([^"]+)";', (ROOT / path).read_text(encoding="utf-8"))
    assert m, (path, name)
    return m.group(1)


def test_the_playground_is_knos_and_the_old_home_is_no_longer_it():
    from knos import playground
    assert playground.REPO == KNOS and playground.OLD_REPO == OLD
    assert playground.is_playground(KNOS, playground.OWNER_ID, True)
    assert not playground.is_playground(OLD, playground.OWNER_ID, True)          # its runs install 0.3.28 from their own pinned workflows
    assert not playground.is_playground(KNOS, playground.OWNER_ID, False) and not playground.is_playground("someone/Knos", playground.OWNER_ID, True)
    said = playground.refuses(lambda path: [], KNOS, {"action": "created", "comment": {}, "issue": {"user": {"login": "x"}}}, 1, 0)
    assert f"https://github.com/{KNOS}/issues/new?template=fund-a-test-task.md" in said


def test_every_constant_and_page_names_knos():
    from knos import claim_guard, commands, controls, faucet
    where = f"https://github.com/{KNOS}/issues?q=is%3Aissue+is%3Aopen+label%3Afaucet"
    assert commands.FAUCET_WHERE == faucet.WHERE == where and where in commands.FAUCET_ELSEWHERE
    assert _const("web/install.js", "FAUCET_ISSUE") == _const("web/passkey_fund.js", "FAUCET_ISSUE") == where
    assert _const("web/playground.js", "REPO") == _const("web/buyer.js", "PLAYGROUND") == controls.SAMPLE_REPOSITORY == KNOS
    assert claim_guard.PLAYGROUND == f"https://github.com/{KNOS}"
    job = yaml.safe_load((ROOT / ".github" / "workflows" / "worker.yml").read_text(encoding="utf-8"))["jobs"]["faucet"]
    assert f"(vars.KNOS_FAUCET_REPO || '{KNOS}')" in job["if"]
    for script, name in (("pages_data", "PLAYGROUND"), ("exercise_public", "PLAYGROUND")):
        assert getattr(_script(script), name) == KNOS, script
    assert 'PLAYGROUND = "drexthealpha/Knos"' in (ROOT / "examples" / "witnessed" / "witness.py").read_text(encoding="utf-8")
    # nothing a user reads or runs still sends anyone to the old home, except the one constant that names it as the old home
    for path in [*sorted((ROOT / "web").glob("*.js")), *sorted((ROOT / "src" / "knos").rglob("*.py")), ROOT / "web" / "buyer_templates.json"]:
        text = path.read_text(encoding="utf-8")
        hits = [ln for ln in text.splitlines() if OLD in ln and not ln.startswith("OLD_REPO = ")]
        assert hits == [], (path, hits)


def test_this_tree_holds_the_playground_byte_for_byte_and_knos_keeps_its_own_files():
    r = _script("small_repos")
    want = r.playground_in_knos(r.board_of(ROOT))
    for rel, data in want.items():
        assert (ROOT / rel).read_bytes() == data, f"{rel}: python scripts/small_repos.py fold"
    from knos import playground
    have = {p.relative_to(ROOT).as_posix() for p in (ROOT / ".knos" / "acceptance").rglob("*") if p.is_file()}
    assert have == {k for k in want if k.startswith(".knos/acceptance/")} and len({k.split("/")[2] for k in have}) == playground.SLOTS
    assert ".github/ISSUE_TEMPLATE/fund-a-test-task.md" in want and playground.FUND in want[".github/ISSUE_TEMPLATE/fund-a-test-task.md"].decode("utf-8")
    assert playground.TASK in want and "check.py" in want
    old = r.files("knos-playground")
    for rel in r.IN_KNOS_SKIP:          # Knos holds its own: the callers are the examples (as the old home's are), the faucet is the worker's job
        assert rel not in want
    for rel in (".github/workflows/knos.yml", ".github/workflows/knos-check.yml"):
        assert (ROOT / rel).read_bytes() == old[rel]
    assert "  faucet:" in (ROOT / ".github" / "workflows" / "worker.yml").read_text(encoding="utf-8")


def test_fold_writes_the_playground_and_leaves_no_stale_check_behind(tmp_path):
    r = _script("small_repos")
    stale = tmp_path / ".knos" / "acceptance" / "7" / "old.json"
    stale.parent.mkdir(parents=True)
    stale.write_text("{}", encoding="utf-8")
    keep = tmp_path / ".knos" / "proof.toml"
    keep.write_text("x", encoding="utf-8")
    written = r.fold_playground(tmp_path)
    assert written == sorted(r.playground_in_knos())
    assert not stale.exists() and keep.read_text(encoding="utf-8") == "x"
    assert (tmp_path / ".knos" / "acceptance" / "7" / "cases.json").is_file() and (tmp_path / "words.py").is_file()


def test_the_labs_links_name_the_branch_of_knos():
    link = "https://github.com/drexthealpha/Knos/tree/archive/labs"
    for rel in ("CHANGELOG.md", "docs/reference/DISCLOSURE.md", "docs/reference/README.md", "src/knos/init.py"):
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert link in text and "https://github.com/drexthealpha/knos-labs" not in text, rel
