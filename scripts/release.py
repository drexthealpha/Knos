"""The parts of a release that have an order, each as one command that says what it did and can be run again.
docs/RELEASE.md is the plan; this is what it runs.

    python scripts/release.py wheel             build the wheel and the sdist ONCE, reproducibly, into dist/
    python scripts/release.py wheel --check     build them again and exit 1 unless the wheel is the locked one
    python scripts/release.py workflows DIR     write the pinned workflows into DIR (a checkout of knos-workflows), commit
                                                them there when they changed, and print the commit: what `stamp` takes
    python scripts/release.py verify [DIR]      everything the one commit must hold, checked: versions, the lock, the
                                                wheel built again, the pin (and DIR: the checkout whose HEAD is the pin)
    python scripts/release.py publish           upload THAT wheel (and the sdist) to PyPI: `uv publish`, token from the
                                                environment (UV_PUBLISH_TOKEN). Before the push
    python scripts/release.py pypi-check [--dist DIR] [--wait SECONDS]
                                                exit 1 unless PyPI serves the wheel with exactly the locked hash

Why the wheel can be built before the commit that pins the workflows exists: nothing in it names that commit
(scripts/pinned_workflows.py, in_the_wheel), so the same bytes come out before and after `stamp`. Why it is the same
on another machine: SOURCE_DATE_EPOCH is fixed here, and the build backend and everything it needs are installed by
hash from requirements/build.txt (`uv build --build-constraints ... --require-hashes`). The lock is the last line of
requirements/sign.txt: `knos==X.Y.Z --hash=sha256:<the wheel>`. A file on PyPI can never be replaced, so `publish`
refuses when PyPI already holds this version with another hash, and release.yml uploads nothing there: it only holds
what PyPI serves to the lock.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EPOCH = 1767225600                  # 2026-01-01T00:00:00Z: the time every file inside the wheel and the sdist carries
BUILD = "requirements/build.txt"    # the build backend and what it needs, by hash
PYPI = "https://pypi.org/pypi/knos/{version}/json"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(f"{name}.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def names(version: str) -> tuple[str, str]:
    return f"knos-{version}-py3-none-any.whl", f"knos-{version}.tar.gz"


def build(out: Path, root: Path = ROOT) -> tuple[Path, Path]:
    """The wheel and the sdist of the tree at `root`, built into `out`. The same tree gives the same bytes anywhere."""
    env = {**os.environ, "SOURCE_DATE_EPOCH": str(EPOCH)}
    done = subprocess.run(["uv", "build", "--wheel", "--sdist", "--no-config", "--out-dir", str(out), "--build-constraints", str(root / BUILD), "--require-hashes", str(root)],
                          env=env, capture_output=True, text=True)
    if done.returncode:
        raise SystemExit(f"the build failed:\n{(done.stdout + done.stderr).strip()}")
    version = _load("bump_version").project(root)
    wheel, sdist = (out / n for n in names(version))
    if not wheel.is_file() or not sdist.is_file():
        raise SystemExit(f"the build did not write {wheel.name} and {sdist.name}: {sorted(p.name for p in out.iterdir())}")
    return wheel, sdist


def lock_hash(root: Path = ROOT) -> tuple[str, str] | None:
    """(release, sha256 of its wheel) as the last line of requirements/sign.txt names them; None before the lock."""
    last = (root / "requirements" / "sign.txt").read_text(encoding="utf-8").rstrip("\n").rpartition("\n")[2]
    m = _load("pinned_workflows").KNOS_LINE.fullmatch(last)
    return (m.group("release"), m.group("hash")) if m else None


def wheel_cmd(check: bool) -> int:
    dist = ROOT / "dist"
    with tempfile.TemporaryDirectory() as tmp:
        wheel, sdist = build(Path(tmp))
        got, locked = sha256(wheel), lock_hash()
        if check:
            if locked is None:
                print(f"requirements/sign.txt holds no line for the knos wheel: the release was not locked. This build is {got}.")
                return 1
            if locked != (_load("bump_version").project(), got):
                print(f"NOT the locked wheel: this tree builds {wheel.name} with sha256 {got}, and requirements/sign.txt locks knos {locked[0]} with {locked[1]}. "
                      "The commit does not hold the sources of the wheel it names: nothing may be published from it.")
                return 1
        dist.mkdir(exist_ok=True)
        for built in (wheel, sdist):
            have = dist / built.name
            if have.is_file() and sha256(have) == sha256(built):
                print(f"dist/{built.name}: unchanged, sha256 {sha256(built)}")
            else:
                if have.is_file() and locked and built is wheel and sha256(have) == locked[1]:
                    print(f"NOT the locked wheel: dist/{built.name} is the locked one ({locked[1]}) and this tree now builds {got}. Something that is part of "
                          "the wheel changed after the lock: find it (git diff), or lock again BEFORE anything is published.")
                    return 1
                shutil.copyfile(built, have)
                print(f"dist/{built.name}: built, sha256 {sha256(built)}")
    if check:
        print(f"This tree builds the locked wheel: sha256 {got}.")
    elif locked is None or locked[1] != got:
        print(f"Next: python scripts/pinned_workflows.py lock dist/{names(_load('bump_version').project())[0]} --write")
    return 0


def git(*args: str, cwd: Path) -> str:
    done = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if done.returncode:
        raise SystemExit(f"git {' '.join(args)} failed in {cwd}: {done.stderr.strip()}")
    return done.stdout.strip()


def workflows_cmd(folder: Path) -> int:
    pub = _load("pinned_workflows")
    want = pub.published(pub._read(pub._own_lock()), None)
    if not (folder / ".git").exists():
        raise SystemExit(f"{folder} is not a git checkout: clone {pub.REPO} there first (git clone https://github.com/{pub.REPO} {folder})")
    for rel in sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file() and ".git" not in p.relative_to(folder).parts):
        if rel not in want:
            (folder / rel).unlink()                             # the repository holds the published set and nothing else
    for rel, data in want.items():
        (folder / rel).parent.mkdir(parents=True, exist_ok=True)
        (folder / rel).write_bytes(data)
    git("add", "-A", cwd=folder)
    if git("status", "--porcelain", cwd=folder):
        version = pub.release(pub.sources())
        git("commit", "-q", "-m", f"knos {version}: the workflows, with the lock of its wheel", cwd=folder)
        print(f"Committed the published set ({len(want)} files) in {folder}.")
    else:
        print(f"{folder} holds the published set already: nothing to commit.")
    sha, tree = git("rev-parse", "HEAD", cwd=folder), git("rev-parse", "HEAD^{tree}", cwd=folder)
    if tree != pub.tree_id(want):
        raise SystemExit(f"the commit {sha} in {folder} has the tree {tree}, and the published set is {pub.tree_id(want)}: something else is committed there")
    print(f"The commit everything names: {sha} (tree {tree}). It is not pushed: push it before the release's own push.")
    print(f"Next: python scripts/pinned_workflows.py stamp {sha}")
    return 0


def verify_cmd(folder: Path | None) -> int:
    pub, bump = _load("pinned_workflows"), _load("bump_version")
    said = [f"version: {line}" for line in bump.disagreements()]
    said += [f"workflows: {line}" for line in pub.inconsistencies()]
    locked = lock_hash()
    if locked is None:
        said.append("lock: requirements/sign.txt holds no line for the knos wheel")
    else:
        with tempfile.TemporaryDirectory() as tmp:
            got = sha256(build(Path(tmp))[0])
        if locked != (bump.project(), got):
            said.append(f"lock: this tree builds the wheel {got}, and requirements/sign.txt locks knos {locked[0]} with {locked[1]}")
        have = ROOT / "dist" / names(bump.project())[0]
        if not have.is_file() or sha256(have) != locked[1]:
            said.append(f"lock: dist/{have.name} is not the locked wheel (it is what `publish` uploads): python scripts/release.py wheel")
    if pub.pin() == pub.PLACEHOLDER:
        said.append(f"pin: the examples still say {pub.PLACEHOLDER}: python scripts/pinned_workflows.py stamp <the commit>")
    if folder is not None and locked is not None:
        want = pub.published(pub._read(pub._own_lock()), None)
        said += [f"{folder}: {line}" for line in pub.differences(folder, want)]
        head = git("rev-parse", "HEAD", cwd=folder)
        if head != pub.pin():
            said.append(f"pin: the examples name {pub.pin()}, and {folder} is at {head}")
        if git("rev-parse", "HEAD^{tree}", cwd=folder) != pub.tree_id(want) or git("status", "--porcelain", cwd=folder):
            said.append(f"{folder}: its commit is not exactly the published set")
    for line in said:
        print(line)
    print("Verified: one version, the wheel this tree builds is the locked one, and every file names the pin "
          f"{pub.pin()}" + (f", which is the commit of {folder}." if folder else ".") if not said else f"{len(said)} problem(s). Nothing may be committed or published yet.")
    return 1 if said else 0


def on_pypi(version: str, fetch=None) -> dict[str, str] | None:
    """{file name: sha256} of what PyPI serves for this version; None when it has no such version."""
    def get(url: str) -> bytes | None:
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"Accept": "application/json"}), timeout=30) as r:
                return r.read()
        except urllib.error.HTTPError as why:
            if why.code == 404:
                return None
            raise
    body = (fetch or get)(PYPI.format(version=version))
    return None if body is None else {u["filename"]: u["digests"]["sha256"] for u in json.loads(body)["urls"]}


def pypi_check(dist: Path | None = None, wait: int = 0, fetch=None, sleep=time.sleep, root: Path = ROOT) -> tuple[bool, str]:
    """(ok, what to say): PyPI serves the wheel of the locked release with exactly the locked hash. `dist`: a folder
    whose wheel must be that file too. `wait`: how long to keep asking while PyPI does not show the release yet."""
    locked = lock_hash(root)
    if locked is None:
        return False, "requirements/sign.txt holds no line for the knos wheel: this commit locks no release, so there is nothing PyPI could be held to."
    version, want = locked
    wheel = names(version)[0]
    deadline = time.monotonic() + wait
    while True:
        files = on_pypi(version, fetch)
        if files is not None and wheel in files or time.monotonic() >= deadline:
            break
        sleep(20)
    if files is None or wheel not in files:
        return False, (f"PyPI does not serve {wheel}. The release order uploads it BEFORE the push (python scripts/release.py publish, on the machine that "
                       f"built it). This workflow never uploads a wheel: one built here could differ from the locked one ({want}).")
    if files[wheel] != want:
        return False, (f"PyPI serves {wheel} with sha256 {files[wheel]}, and this commit locks {want}. They are DIFFERENT files: the signing jobs would refuse "
                       "to install what PyPI has. A file on PyPI cannot be replaced: release a new version, built and locked again.")
    if dist is not None:
        have = dist / wheel
        if not have.is_file() or sha256(have) != want:
            return False, f"{have} is not the locked wheel ({want}): the build job of this run did not build what PyPI serves."
    return True, f"PyPI serves {wheel} with the locked sha256 {want}."


def publish_cmd() -> int:
    locked = lock_hash()
    if locked is None:
        raise SystemExit("refused: requirements/sign.txt holds no line for the knos wheel. Lock the release first (docs/RELEASE.md).")
    version, want = locked
    wheel, sdist = (ROOT / "dist" / n for n in names(version))
    if not wheel.is_file() or sha256(wheel) != want:
        raise SystemExit(f"refused: dist/{wheel.name} is not the locked wheel ({want}). Nothing was uploaded.")
    if git("status", "--porcelain", cwd=ROOT):
        raise SystemExit("refused: the working tree is not committed. The wheel goes to PyPI after the one commit and before the push. Nothing was uploaded.")
    if git("show", "HEAD:requirements/sign.txt", cwd=ROOT) != (ROOT / "requirements" / "sign.txt").read_text(encoding="utf-8").strip():
        raise SystemExit("refused: the commit does not hold this lock. Nothing was uploaded.")
    files = on_pypi(version)
    if files and wheel.name in files:
        ok, said = pypi_check()
        print(said + (" Nothing to upload." if ok else ""))
        return 0 if ok else 1
    if not os.environ.get("UV_PUBLISH_TOKEN"):
        raise SystemExit("refused: UV_PUBLISH_TOKEN is not set. Export a PyPI token for the knos project (it is never printed). Nothing was uploaded.")
    upload = [str(wheel)] + ([str(sdist)] if sdist.is_file() else [])
    done = subprocess.run(["uv", "publish", "--check-url", "https://pypi.org/simple/", *upload])
    if done.returncode:
        print("uv publish failed (the lines above say why). Run this again: files PyPI already has are skipped.")
        return 1
    ok, said = pypi_check(wait=300)
    print(said + (" Next: git push, then the tag." if ok else ""))
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="The ordered parts of a release (docs/RELEASE.md).")
    sub = ap.add_subparsers(dest="command", required=True)
    sub.add_parser("wheel", help="build the wheel and the sdist reproducibly into dist/").add_argument("--check", action="store_true", help="exit 1 unless the wheel is the locked one")
    sub.add_parser("workflows", help="write and commit the pinned workflows in a checkout of knos-workflows").add_argument("dir")
    sub.add_parser("verify", help="check everything the one commit must hold").add_argument("dir", nargs="?")
    sub.add_parser("publish", help="upload the locked wheel to PyPI (UV_PUBLISH_TOKEN), before the push")
    check = sub.add_parser("pypi-check", help="exit 1 unless PyPI serves the wheel with exactly the locked hash")
    check.add_argument("--dist", help="a folder whose wheel must be that file too")
    check.add_argument("--wait", type=int, default=0, help="seconds to keep asking while PyPI does not show the release")
    a = ap.parse_args(argv)
    if a.command == "wheel":
        return wheel_cmd(a.check)
    if a.command == "workflows":
        return workflows_cmd(Path(a.dir))
    if a.command == "verify":
        return verify_cmd(Path(a.dir) if a.dir else None)
    if a.command == "publish":
        return publish_cmd()
    ok, said = pypi_check(Path(a.dist) if a.dist else None, a.wait)
    print(said if ok else f"::error title=PyPI::{said}" if os.environ.get("GITHUB_ACTIONS") else said)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
