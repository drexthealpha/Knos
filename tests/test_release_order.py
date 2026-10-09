"""The release order with one commit and one push (docs/RELEASE.md): the wheel is built once, before the commit of the
pinned workflows exists, the lock names it, the workflows are built with that lock, their commit is stamped into the
tree, and the wheel built again from the stamped tree is the same file. Run here on a copy of this tree, with the real
build."""
from __future__ import annotations

import hashlib
import importlib.util
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"{name}_for_order", ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _copy(tmp_path: Path) -> Path:
    """What the wheel, the lock, the pinned workflows and the stamp read, as a tree of its own."""
    root = tmp_path / "tree"
    for rel in ("pyproject.toml", "README.md", "README.pypi.md", "LICENSE", "src/knos", "terms", "requirements", "examples", ".github/workflows", "docs", "web/front.js",
                "sdk/settle/README.md", "scripts/front_workflow.py"):
        src, dst = ROOT / rel, root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__", "target", "node_modules", "*.so"))
        else:
            shutil.copyfile(src, dst)
    return root


@pytest.fixture()
def tree(tmp_path, monkeypatch):
    root = _copy(tmp_path)
    pub, rel = _load("pinned_workflows"), _load("release")
    monkeypatch.setattr(pub, "ROOT", root)
    return root, pub, rel


@pytest.mark.skipif(not shutil.which("uv"), reason="builds the wheel with uv, as a release does")
def test_the_wheel_built_before_the_stamp_is_the_wheel_built_after_it(tree, tmp_path):
    root, pub, rel = tree
    first = rel.build(tmp_path / "a", root)[0]
    locked = pub.lock(first)
    (root / "requirements" / "sign.txt").write_text(locked, encoding="utf-8")
    assert pub.locked().group("hash") == hashlib.sha256(first.read_bytes()).hexdigest() and rel.lock_hash(root) == (pub.release(pub.sources()), pub.locked().group("hash"))
    # the workflows with that lock; their commit, as a release makes it
    out = tmp_path / "knos-workflows"
    files = pub.published(locked)
    for name, data in files.items():
        (out / name).parent.mkdir(parents=True, exist_ok=True)
        (out / name).write_bytes(data)
    subprocess.run(["git", "init", "-q", str(out)], check=True)
    subprocess.run(["git", "-C", str(out), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(out), "-c", "user.name=t", "-c", "user.email=t@x", "commit", "-q", "-m", "the published set"], check=True)
    sha = subprocess.run(["git", "-C", str(out), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    held = subprocess.run(["git", "-C", str(out), "rev-parse", "HEAD^{tree}"], capture_output=True, text=True, check=True).stdout.strip()
    assert held == pub.tree_id(files)                            # the tree of that commit is computed from the sources alone
    # the stamp changes the files that name the commit, and none of them is in the wheel
    changed = pub.stamp(sha)
    assert changed and {"examples/knos-workflow.yml", ".github/workflows/knos.yml", "web/front.js"} <= set(changed)
    assert "README.md" not in changed and not [c for c in changed if c.startswith("src/")]
    assert pub.inconsistencies() == [] and pub.pin() == sha
    second = rel.build(tmp_path / "b", root)[0]
    assert second.read_bytes() == first.read_bytes(), "the stamp changed the wheel: the lock would name a wheel this commit does not build"
    # and the sdist, which holds README.md and src/knos too
    assert (tmp_path / "a" / second.name.replace("-py3-none-any.whl", ".tar.gz")).read_bytes() == \
           (tmp_path / "b" / second.name.replace("-py3-none-any.whl", ".tar.gz")).read_bytes()


@pytest.mark.skipif(not shutil.which("uv"), reason="builds the wheel with uv, as a release does")
def test_a_commit_named_inside_the_wheel_is_caught_before_it_can_break_the_lock(tree, tmp_path):
    root, pub, rel = tree
    assert pub.in_the_wheel() == []
    first = rel.build(tmp_path / "a", root)[0]
    readme = root / "README.pypi.md"
    readme.write_text(readme.read_text(encoding="utf-8") + f"\nCall {pub.REPO}/.github/workflows/fund.yml@{'c' * 40}\n", encoding="utf-8")
    said = pub.in_the_wheel()
    assert len(said) == 1 and said[0].startswith("README.pypi.md names a commit of drexthealpha/knos-workflows, and it is part of the wheel")
    assert said[0] in pub.inconsistencies()
    # why it matters: the description is inside the wheel, so the wheel is another file now
    assert rel.build(tmp_path / "b", root)[0].read_bytes() != first.read_bytes()
    src = root / "src" / "knos" / "pinned_note.py"
    src.write_text(f'PIN = "{pub.REPO}/{"d" * 40}/requirements/sign.txt"\n', encoding="utf-8")
    assert any(line.startswith("src/knos/pinned_note.py names a commit") for line in pub.in_the_wheel())


def test_the_lock_is_the_last_line_of_sign_txt_and_the_rest_is_the_third_party_list(tree, tmp_path, capsys):
    root, pub, _rel = tree
    # the tree as it is before its lock (the release commit holds one: it is taken back out of the copy)
    (root / "requirements" / "sign.txt").write_text(pub.third_party(), encoding="utf-8")
    before = (root / "requirements" / "sign.txt").read_text(encoding="utf-8")
    assert pub.locked() is None and pub.third_party() == before
    with pytest.raises(SystemExit, match="holds no line for the knos wheel yet"):
        pub.main(["build", str(tmp_path / "out")])
    wheel = tmp_path / f"knos-{pub.release(pub.sources())}-py3-none-any.whl"
    wheel.write_bytes(b"PK a wheel")
    assert pub.main(["lock", str(wheel), "--write"]) == 0
    line = f"knos=={pub.release(pub.sources())} --hash=sha256:{hashlib.sha256(b'PK a wheel').hexdigest()}"
    assert (root / "requirements" / "sign.txt").read_text(encoding="utf-8") == before + line + "\n"
    assert pub.locked().group(0) == line and pub.third_party() == before          # locking twice adds one line, not two
    assert pub.main(["lock", str(wheel), "--write"]) == 0 and (root / "requirements" / "sign.txt").read_text(encoding="utf-8") == before + line + "\n"
    # build and check take the tree's own lock when none is named
    capsys.readouterr()
    assert pub.main(["build", str(tmp_path / "out")]) == 0 and pub.main(["check", str(tmp_path / "out")]) == 0
    assert (tmp_path / "out" / "requirements" / "sign.txt").read_text(encoding="utf-8") == before + line + "\n"
    assert pub.main(["tree"]) == 0 and re.fullmatch(r"[0-9a-f]{40}", capsys.readouterr().out.strip().splitlines()[-1])
    # a lock for another release than the workflows install is said, and a version bump removes it instead of renaming it
    bump = _load("bump_version")
    (root / "requirements" / "sign.txt").write_text(before + "knos" + "==0.0.1 --hash=sha256:" + "e" * 64 + "\n", encoding="utf-8")
    assert any("locks the wheel of knos 0.0.1" in said for said in pub.inconsistencies())
    assert bump.unlock(pub.release(pub.sources()), root) and (root / "requirements" / "sign.txt").read_text(encoding="utf-8") == before
    assert not bump.unlock(pub.release(pub.sources()), root) and pub.locked() is None


def test_the_plan_names_every_step_in_the_order_the_tools_enforce():
    plan = (ROOT / "docs" / "RELEASE.md").read_text(encoding="utf-8")
    order = ["scripts/bump_version.py --check", "scripts/release.py wheel", "pinned_workflows.py lock", "scripts/release.py workflows", "pinned_workflows.py stamp",
             "scripts/release.py verify", "ship_check.py", "git commit", "scripts/release.py publish", "git push origin main", "git tag v"]
    at = [plan.index(step) for step in order]
    assert at == sorted(at), [step for step, a, b in zip(order, at, sorted(at)) if a != b]
    assert "ONE commit" in plan and "ONE push" in plan and "`release.yml` uploads nothing to PyPI" in plan
    for script in re.findall(r"scripts/([\w.]+\.(?:py|sh|mjs))", plan):
        assert (ROOT / "scripts" / script).is_file(), script
