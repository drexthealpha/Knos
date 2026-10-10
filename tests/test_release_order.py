"""The release order with one commit and one push (docs/RELEASE.md): the wheel is built once, before the commit of the
pinned workflows exists, the lock names it, the workflows are built with that lock, their commit is stamped into the
tree, and the wheel built again from the stamped tree is the same file. Run here on a copy of this tree, with the real
build."""
from __future__ import annotations

import hashlib
import importlib.util
import json
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


def _pypi(tmp_path: Path, wheel: str, data: bytes, at: str = "2026-10-11T09:14:07.512345Z", sha: str | None = None) -> Path:
    """PyPI's JSON page of a release, as `cutoff` reads it: the wheel (and an sdist taken a moment later), each with its
    sha256 and the time PyPI took it."""
    page = {"urls": [{"filename": wheel, "digests": {"sha256": sha or hashlib.sha256(data).hexdigest()}, "upload_time_iso_8601": at},
                     {"filename": wheel.replace("-py3-none-any.whl", ".tar.gz"), "digests": {"sha256": "0" * 64}, "upload_time_iso_8601": "2026-10-11T09:14:09.000001Z"}]}
    path = tmp_path / "pypi.json"
    path.write_text(json.dumps(page), encoding="utf-8")
    return path


def _before_its_cutoff(root: Path, pub) -> None:
    """The copy as the release's tree is before `cutoff` runs: its cutoff's note names the release before this one. On
    the release's own commit, after `cutoff`, the note names this release; these tests replay the order from the start."""
    this = pub.release(pub.sources())
    major, minor, patch = (int(x) for x in this.split("."))
    before = f"{major}.{minor}.{patch - 1}" if patch else f"{major}.{minor - 1}.99" if minor else "0.0.1"
    for name in pub.WORKFLOWS:
        path = root / ".github" / "workflows" / name
        text = path.read_text(encoding="utf-8")
        path.write_text(text.replace(f"# knos {this} reached PyPI at ", f"# knos {before} reached PyPI at "), encoding="utf-8", newline="\n")
    assert pub.cutoff_pending(pub.sources()), "the copy is not before its cutoff"


@pytest.fixture()
def tree(tmp_path, monkeypatch):
    root = _copy(tmp_path)
    pub, rel = _load("pinned_workflows"), _load("release")
    monkeypatch.setattr(pub, "ROOT", root)
    _before_its_cutoff(root, pub)
    return root, pub, rel


def test_the_copy_is_put_back_before_its_cutoff_when_the_tree_has_its_own(tmp_path, monkeypatch):
    # the release's commit carries the cutoff `cutoff` wrote for it; the order above is replayed from before that step
    root = _copy(tmp_path)
    pub = _load("pinned_workflows")
    monkeypatch.setattr(pub, "ROOT", root)
    this = pub.release(pub.sources())
    for name in pub.WORKFLOWS:
        path = root / ".github" / "workflows" / name
        path.write_text(pub.CUTOFF.sub(lambda m: f'{m.group("lead")}"2026-10-10T09:46:00Z"   # knos {this} reached PyPI at 2026-10-10T09:35:20Z',
                                       path.read_text(encoding="utf-8")), encoding="utf-8", newline="\n")
    assert pub.cutoff_pending(pub.sources()) is None
    _before_its_cutoff(root, pub)
    assert "Upload the wheel first" in pub.cutoff_pending(pub.sources())


@pytest.mark.skipif(not shutil.which("uv"), reason="builds the wheel with uv, as a release does")
def test_the_wheel_built_before_the_stamp_is_the_wheel_built_after_it(tree, tmp_path):
    root, pub, rel = tree
    first = rel.build(tmp_path / "a", root)[0]
    locked = pub.lock(first)
    (root / "requirements" / "sign.txt").write_text(locked, encoding="utf-8")
    assert pub.locked().group("hash") == hashlib.sha256(first.read_bytes()).hexdigest() and rel.lock_hash(root) == (pub.release(pub.sources()), pub.locked().group("hash"))
    # the wheel goes to PyPI, and the cutoff is written from the time PyPI took it: before that nothing is published
    with pytest.raises(SystemExit, match="Upload the wheel first"):
        pub.published(locked)
    assert pub.main(["cutoff", "--pypi", str(_pypi(tmp_path, first.name, first.read_bytes()))]) == 0
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
    # build and check take the tree's own lock when none is named, once the cutoff lets that release through
    with pytest.raises(SystemExit, match="Upload the wheel first"):
        pub.main(["build", str(tmp_path / "out")])
    assert pub.main(["cutoff", "--pypi", str(_pypi(tmp_path, wheel.name, b"PK a wheel"))]) == 0
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
    # PyPI before the workflows: their cutoff is written from the time PyPI took the wheel (pinned_workflows.py cutoff)
    order = ["scripts/bump_version.py --check", "scripts/release.py wheel", "pinned_workflows.py lock", "scripts/release.py publish", "pinned_workflows.py cutoff",
             "scripts/release.py workflows", "pinned_workflows.py stamp", "scripts/small_repos.py build", "scripts/release.py verify", "ship_check.py", "git commit",
             "git push origin main", "git tag v"]
    at = [plan.index(step) for step in order]
    assert at == sorted(at), [step for step, a, b in zip(order, at, sorted(at)) if a != b]
    assert "ONE commit" in plan and "ONE push" in plan and "`release.yml` uploads nothing to PyPI" in plan
    for script in re.findall(r"scripts/([\w.]+\.(?:py|sh|mjs))", plan):
        assert (ROOT / "scripts" / script).is_file(), script


# ---- the cutoff of the jobs that sign nothing: written from the time PyPI took the wheel -------------------------------

def _set(pub, texts: dict[str, str], value: str, note: str, release: str | None = None) -> dict[str, str]:
    """The workflows with every UV_EXCLUDE_NEWER line set to `value` and `note` (and installing `release`)."""
    out = {name: pub.CUTOFF.sub(lambda m: f'{m.group("lead")}"{value}"{note}', text) for name, text in texts.items()}
    return out if release is None else {name: re.sub(r'"knos==\d+\.\d+\.\d+"', f'"knos=={release}"', text) for name, text in out.items()}


def test_no_cutoff_in_this_tree_is_earlier_than_the_release_it_names():
    """0.3.25 published workflows whose cutoff was midnight of the day its wheel reached PyPI, three hours later: uv
    could not see knos 0.3.25, and every job that installs it from PyPI failed. The test meant to catch it read the
    newest DATED heading of CHANGELOG.md, which was 0.3.11's. Here the cutoff carries a note: the release it was written
    for, and the time PyPI took that wheel. The cutoff comes after that time, and the release is the one the workflows
    install, or (before its upload) an earlier one, with which a locked tree publishes nothing."""
    pub = _load("pinned_workflows")
    texts = pub.sources()
    assert pub.cutoff_wrong(texts) == []
    value, named, at = pub.cutoff(texts)
    assert pub._time(value) > pub._time(at) and pub._time(value) == pub.cutoff_after(pub._time(at))
    assert len(re.findall(r'(?m)^ +UV_EXCLUDE_NEWER: "', "".join(texts.values()))) == len(pub.CUTOFF.findall("".join(texts.values()))) >= 4
    installs = pub.release(texts)
    assert pub._numbers(named) <= pub._numbers(installs)
    if pub.locked():          # the release's own commit: the cutoff lets the locked release through
        assert named == installs == pub.locked().group("release") and pub.cutoff_pending(texts) is None
    elif named != installs:   # a tree between releases: it says what comes first
        assert "Upload the wheel first" in pub.cutoff_pending(texts)


def test_a_cutoff_set_by_hand_is_refused_wherever_the_workflows_are_checked_or_published(monkeypatch):
    pub = _load("pinned_workflows")
    real = pub.sources()
    spec = "git+https://github.com/drexthealpha/Knos@" + "a" * 40
    cases = {
        # the 0.3.25 pin as it was: midnight, no note
        "has no note": _set(pub, real, "2026-10-10T00:00:00Z", "", "0.3.25"),
        # the same with a note: the cutoff is before the upload it names
        "is not after 2026-10-10T03:00:43Z": _set(pub, real, "2026-10-10T00:00:00Z", "   # knos 0.3.25 reached PyPI at 2026-10-10T03:00:43Z", "0.3.25"),
        "is not 2026-10-10T03:11:00Z": _set(pub, real, "2026-10-12T00:00:00Z", "   # knos 0.3.25 reached PyPI at 2026-10-10T03:00:43Z", "0.3.25"),
        "is not a time": _set(pub, real, "10 Oct 2026", "   # knos 0.3.25 reached PyPI at 2026-10-10T03:00:43Z", "0.3.25"),
        "an older release": _set(pub, real, "2026-10-10T03:11:00Z", "   # knos 0.3.25 reached PyPI at 2026-10-10T03:00:43Z", "0.3.24"),
        "must say the same thing": {**real, "check.yml": _set(pub, {"c": real["check.yml"]}, "2026-10-10T03:12:00Z", "   # knos 0.3.25 reached PyPI at 2026-10-10T03:01:43Z")["c"]},
    }
    for why, texts in cases.items():
        assert [line for line in pub.cutoff_wrong(texts) if why in line], why
        monkeypatch.setattr(pub, "sources", lambda texts=texts: texts)
        assert [line for line in pub.inconsistencies() if why in line], why
        with pytest.raises(SystemExit, match=re.escape(why)):
            pub.published(spec=spec)                        # not even a rehearsal is written with it
    # and the cutoff `cutoff` writes for that upload is right
    monkeypatch.setattr(pub, "sources", lambda: _set(pub, real, "2026-10-10T03:11:00Z", "   # knos 0.3.25 reached PyPI at 2026-10-10T03:00:43Z", "0.3.25"))
    assert pub.cutoff_wrong(pub.sources()) == [] and pub.cutoff_pending(pub.sources()) is None


def test_the_cutoff_is_ten_minutes_after_the_upload_rounded_up_to_a_minute():
    pub = _load("pinned_workflows")
    for at, want in (("2026-10-10T03:00:43Z", "2026-10-10T03:11:00Z"), ("2026-10-10T03:00:00Z", "2026-10-10T03:10:00Z"),
                     ("2026-10-10T23:59:01Z", "2026-10-11T00:10:00Z")):
        assert pub._say(pub.cutoff_after(pub._time(at))) == want
        assert pub.cutoff_after(pub._time(at)) > pub._time(at)


def test_the_release_writes_the_cutoff_only_from_pypis_answer_for_the_locked_wheel(tree, tmp_path, capsys):
    root, pub, _rel = tree
    (root / "requirements" / "sign.txt").write_text(pub.third_party(), encoding="utf-8")     # the tree before its lock
    version = pub.release(pub.sources())
    wheel = tmp_path / f"knos-{version}-py3-none-any.whl"
    wheel.write_bytes(b"PK the wheel")
    before = {name: (root / ".github" / "workflows" / name).read_text(encoding="utf-8") for name in pub.WORKFLOWS}
    with pytest.raises(SystemExit, match="holds no line for the knos wheel yet"):
        pub.main(["cutoff", "--pypi", str(_pypi(tmp_path, wheel.name, b"PK the wheel"))])
    assert pub.main(["lock", str(wheel), "--write"]) == 0
    # locked, not on PyPI: nothing is published, and check says what comes first
    if pub.cutoff(pub.sources())[1] != version:
        assert [line for line in pub.inconsistencies() if "Upload the wheel first" in line]
        with pytest.raises(SystemExit, match="Upload the wheel first"):
            pub.main(["build", str(tmp_path / "out")])
    # PyPI has no such wheel, or another file under its name: nothing is written
    with pytest.raises(SystemExit, match="does not serve"):
        pub.main(["cutoff", "--pypi", str(_pypi(tmp_path, f"knos-{version}-py3-none-any.whl".replace(version, "0.0.1"), b"PK the wheel"))])
    with pytest.raises(SystemExit, match="different files"):
        pub.main(["cutoff", "--pypi", str(_pypi(tmp_path, wheel.name, b"PK the wheel", sha="e" * 64))])
    with pytest.raises(SystemExit, match="cannot read PyPI's page"):
        pub.main(["cutoff", "--pypi", str(tmp_path / "missing.json")])
    assert {name: (root / ".github" / "workflows" / name).read_text(encoding="utf-8") for name in pub.WORKFLOWS} == before
    # the locked wheel on PyPI at 09:14:07.5: the note says 09:14:08 and the cutoff is 09:25
    capsys.readouterr()
    assert pub.main(["cutoff", "--pypi", str(_pypi(tmp_path, wheel.name, b"PK the wheel"))]) == 0
    line = f'"2026-10-11T09:25:00Z"   # knos {version} reached PyPI at 2026-10-11T09:14:08Z'
    assert f"UV_EXCLUDE_NEWER: {line}, written into prove.yml, check.yml, attest.yml." in capsys.readouterr().out
    after = {name: (root / ".github" / "workflows" / name).read_text(encoding="utf-8") for name in pub.WORKFLOWS}
    assert after["fund.yml"] == before["fund.yml"]                       # fund.yml installs by hash only: no cutoff there
    for name in ("prove.yml", "check.yml", "attest.yml"):
        old, new = before[name].splitlines(), after[name].splitlines()
        changed = [b for a, b in zip(old, new) if a != b]
        assert len(old) == len(new) and changed and all(b.strip() == f"UV_EXCLUDE_NEWER: {line}" for b in changed), name
    assert pub.cutoff_wrong(pub.sources()) == [] and pub.cutoff_pending(pub.sources()) is None and pub.inconsistencies() == []
    # written again from the same answer: the same bytes
    assert pub.main(["cutoff", "--pypi", str(_pypi(tmp_path, wheel.name, b"PK the wheel"))]) == 0 and "as the workflows say already" in capsys.readouterr().out
    # the published set carries it
    assert pub.main(["build", str(tmp_path / "out")]) == 0
    assert f"UV_EXCLUDE_NEWER: {line}" in (tmp_path / "out" / ".github" / "workflows" / "check.yml").read_text(encoding="utf-8")
