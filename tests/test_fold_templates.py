"""One repository: the template repositories' files live in templates/<name>/, byte for byte
what scripts/small_repos.py writes from this tree's sources; nothing the site or the package hands out makes a
repository from a GitHub template any more; and the page that says what was folded names every repository it decided."""
from __future__ import annotations
import pathlib as _pl

import pytest as _pt

if not (_pl.Path(__file__).resolve().parents[1] / "tasks").is_dir():
    _pt.skip("tasks/ left the public repository; this test runs where that folder is kept", allow_module_level=True)

import importlib.util
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _script(name: str):
    spec = importlib.util.spec_from_file_location(f"{name}_fold", ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


r = _script("small_repos")


@pytest.mark.parametrize("name", r.FOLDED)
def test_each_folder_is_exactly_what_the_sources_write(name):
    folder = ROOT / "templates" / name
    want = r.files(name)
    have = {p.relative_to(folder).as_posix(): p.read_bytes() for p in folder.rglob("*") if p.is_file()}
    assert set(have) == set(want), f"templates/{name}: python scripts/small_repos.py fold"
    for rel, data in want.items():
        assert have[rel] == data, f"templates/{name}/{rel} is not what the sources write: python scripts/small_repos.py fold"
    assert "Use this template" not in have["README.md"].decode("utf-8") and f"templates/{name}/" in have["README.md"].decode("utf-8")


def test_fold_writes_the_four_folders_and_removes_what_is_not_theirs(tmp_path):
    (tmp_path / "knos-task" / "old").mkdir(parents=True)
    (tmp_path / "knos-task" / "old" / "stale.txt").write_text("left over", encoding="utf-8")
    assert r.fold(tmp_path) == list(r.FOLDED)
    for name in r.FOLDED:
        got = {p.relative_to(tmp_path / name).as_posix() for p in (tmp_path / name).rglob("*") if p.is_file()}
        assert got == set(r.files(name))
    assert "knos-playground" not in r.FOLDED and not (tmp_path / "knos-playground").exists()      # a live repository, not a copy


def test_nothing_handed_out_makes_a_repository_from_a_template():
    tracked = subprocess.run(["git", "ls-files", "web", "src/knos", "examples"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()
    for rel in tracked:
        if not rel.endswith((".js", ".html", ".py", ".md", ".yml")):
            continue
        text = (ROOT / rel).read_text(encoding="utf-8", errors="replace")
        assert "template_owner=" not in text and "template_name=" not in text, rel
        assert not re.search(r"repo\"?,? \"?create\"?.{0,80}--template", text), rel
    claim = (ROOT / "src" / "knos" / "claim.py").read_text(encoding="utf-8")
    assert '"repo", "create", repo, "--public", "--description", about' in claim and "TEMPLATE_REPO" not in claim
