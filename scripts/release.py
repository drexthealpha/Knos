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
                                                exit 1 unless PyPI serves the wheel with exactly the locked hash, and
                                                its index (what an installer reads) lists that file
    python scripts/release.py registry-plan crates|npm NAME --tag vX.Y.Z
                                                release.yml's question before it publishes a crate or the npm package:
                                                is its version one this release may publish, and does the registry
                                                lack it? Exit 1 only for a version that is neither the tag's nor held
    python scripts/release.py registry-plan [--online]
                                                with no package named: everything this repository would publish to
                                                crates.io and npm, at which version, whether each packs here with
                                                no network, and whether its README survives leaving the repository
                                                (every link absolute). It publishes nothing. --online also asks each
                                                registry whether the name is free or which versions it has
    python scripts/release.py held NAME         the version scripts/bump_version.py holds a crate at; nothing when it
                                                moves with the release

Why the wheel can be built before the commit that pins the workflows exists: nothing in it names that commit
(scripts/pinned_workflows.py, in_the_wheel), so the same bytes come out before and after `stamp`. Why it is the same
on another machine: SOURCE_DATE_EPOCH is fixed here, and the build backend and everything it needs are installed by
hash from requirements/build.txt (`uv build --build-constraints ... --require-hashes`). The lock is the last line of
requirements/sign.txt: `knos==X.Y.Z --hash=sha256:<the wheel>`. A file on PyPI can never be replaced, so `publish`
refuses when PyPI already holds this version with another hash, and release.yml uploads nothing there: it only holds
what PyPI serves to the lock.

PyPI answers from two places. The JSON page of a version shows an upload at once; the index an installer resolves from
(https://pypi.org/simple/knos/) is cached and showed 0.3.15 a few minutes later, so the first runs after that push
found "no version of" the release they asked for. `publish` therefore says "git push" only once the index lists the locked wheel.

A package is published at ITS OWN version. The Python package and the JavaScript client move with every release. The
program crates and the two interface crates stay at FROZEN_AT while scripts/bump_version.py names them in
PROGRAMS_FROZEN (a version is in a build's bytes), so their version is not the tag's, on purpose. `registry-plan`
takes both as right, refuses anything else, and publishes only a version the registry does not have.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
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
SIMPLE = "https://pypi.org/simple/knos/"        # the index an installer resolves from (PEP 691: asked for as JSON)
REGISTRIES = {"crates": "crates.io", "npm": "npm"}


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


def _get(url: str, accept: str) -> bytes | None:
    """The body at `url`; None for 404. Any other failure is the caller's to report."""
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"Accept": accept, "User-Agent": "knos-release"}), timeout=30) as r:
            return r.read()
    except urllib.error.HTTPError as why:
        if why.code == 404:
            return None
        raise


def on_index(fetch=None) -> dict[str, str]:
    """{file name: sha256} of every file PyPI's index lists for knos: what `uv pip install` and pip resolve from."""
    body = (fetch or (lambda url: _get(url, "application/vnd.pypi.simple.v1+json")))(SIMPLE)
    return {} if body is None else {f["filename"]: f.get("hashes", {}).get("sha256", "") for f in json.loads(body)["files"]}


def index_check(wait: int = 0, fetch=None, sleep=time.sleep, root: Path = ROOT) -> tuple[bool, str]:
    """(ok, what to say): the index lists the locked wheel with the locked hash. It asks every 20 s for at most `wait`
    seconds and then gives up: the index is a cached page, and it has shown a release minutes after its upload."""
    locked = lock_hash(root)
    if locked is None:
        return False, "requirements/sign.txt holds no line for the knos wheel: there is no release to look for in PyPI's index."
    version, want = locked
    wheel = names(version)[0]
    asked = 0
    while True:
        files = on_index(fetch)
        if files.get(wheel) == want:
            return True, f"PyPI's index lists {wheel} with the locked sha256: an install of knos=={version} by hash finds it."
        if wheel in files:
            return False, f"PyPI's index lists {wheel} with sha256 {files[wheel]}, and this commit locks {want}. They are DIFFERENT files."
        if asked >= wait:
            return False, (f"PyPI's index ({SIMPLE}) does not list {wheel} after {asked} seconds, though the upload was taken. Do NOT push yet: every job that "
                           f"installs knos=={version} would fail with \"no version of knos=={version}\". Ask again: python scripts/release.py pypi-check --wait 600")
        sleep(20)
        asked += 20


# ---- crates.io and npm: a package is published at its own version ---------------------------------------------------------

def held(name: str) -> str | None:
    """The version scripts/bump_version.py holds this crate at (PROGRAMS_FROZEN, FROZEN_AT); None when it moves with a release."""
    bump = _load("bump_version")
    return bump.FROZEN_AT if name in bump.PROGRAMS_FROZEN else None


def own_version(registry: str, name: str, root: Path = ROOT) -> str:
    """The version the package's own manifest carries: what a publish from this commit would upload."""
    if registry == "crates":
        text = (root / "crates" / name / "Cargo.toml").read_text(encoding="utf-8")
        found = re.search(r'(?m)^\[package\]\r?\n(?:(?!\[).*\n)*?version = "([^"]+)"', text)
        if not found or f'name = "{name}"' not in text:
            raise SystemExit(f"crates/{name}/Cargo.toml does not name the crate {name} with a version")
        return found.group(1)
    manifest = json.loads((root / "sdk" / "settle" / "package.json").read_text(encoding="utf-8"))
    if manifest["name"] != name:
        raise SystemExit(f"sdk/settle/package.json is {manifest['name']}, not {name}")
    return manifest["version"]


def version_rule(name: str, version: str, tag: str, held_at: str | None) -> str | None:
    """None when this release may publish `name` at `version`: it is the tag's version, or the one the crate is held
    at. Otherwise what is wrong, in one sentence."""
    if f"v{version}" == tag:
        return None
    if held_at is not None and version == held_at:
        return None
    if held_at is not None:
        return (f"{name} is at {version}: neither the tag's version ({tag}) nor the {held_at} that scripts/bump_version.py holds it at "
                "(PROGRAMS_FROZEN, FROZEN_AT). Nothing is published.")
    return (f"{name} is at {version}, and the tag is {tag}. It is not held at an earlier version by scripts/bump_version.py (PROGRAMS_FROZEN), "
            "so its version must be the tag's. Nothing is published.")


def on_registry(registry: str, name: str, fetch=None) -> set[str] | None:
    """Every version of the package the registry has; None when the package is not there at all (its first version is
    published by hand)."""
    if registry == "crates":
        # crates.io's index: one JSON line per published version, in a folder made of the name's first letters
        folder = {1: "1", 2: "2", 3: f"3/{name[:1]}"}.get(len(name), f"{name[:2]}/{name[2:4]}")
        body = (fetch or (lambda url: _get(url, "text/plain")))(f"https://index.crates.io/{folder}/{name}")
        return None if body is None else {json.loads(line)["vers"] for line in body.decode("utf-8").splitlines() if line.strip()}
    body = (fetch or (lambda url: _get(url, "application/vnd.npm.install-v1+json")))(f"https://registry.npmjs.org/{name}")
    return None if body is None else set(json.loads(body).get("versions") or {})


def registry_plan(registry: str, name: str, tag: str, held_at: str | None, fetch=None, root: Path = ROOT) -> tuple[int, str, bool]:
    """(exit status, what to say, publish now?). Red only for a version this release may not publish, or a registry that
    did not answer. A package that is not on its registry yet, and a version it already has, are green and say so."""
    where = REGISTRIES[registry]
    version = own_version(registry, name, root)
    wrong = version_rule(name, version, tag, held_at)
    if wrong:
        return 1, f"::error title={where}::{wrong}", False
    why = "" if f"v{version}" == tag else f" (held at {version} by scripts/bump_version.py while the release is {tag}: it is published at its own version)"
    try:
        have = on_registry(registry, name, fetch)
    except (OSError, ValueError, KeyError) as failed:
        return 1, f"::error title={where}::The registry did not answer for {name} ({failed}): run this job again.", False
    if have is None:
        return 0, (f"::notice title={where}::Skipped: {name} is not on {where} yet. Its first version is published by hand (docs/RELEASE.md); "
                   f"after that this job publishes.{why}"), False
    if version in have:
        return 0, f"::notice title={where}::Skipped: {where} already has {name} {version}{why}. Nothing to publish.", False
    return 0, f"{where} has {name} without {version}{why}: publishing {name} {version}.", True


def registry_plan_cmd(registry: str, name: str, tag: str) -> int:
    code, said, publish = registry_plan(registry, name, tag, held(name))
    print(said)
    out = os.environ.get("GITHUB_OUTPUT")
    if out and code == 0:
        with open(out, "a", encoding="utf-8") as f:
            f.write(f"version={own_version(registry, name)}\n" + ("publish=true\n" if publish else ""))
    return code


# ---- everything that would be published, in one plan ------------------------------------------------------------------------
PACKAGES = (("crates", "knos-oidc-interface"), ("crates", "knos-pay-interface"), ("npm", "knos-settle"))
OWNERS = {"crates": "cargo owner --list {name}", "npm": "npm owner ls {name}"}
PUBLISH = {"crates": "cargo publish --manifest-path crates/{name}/Cargo.toml", "npm": "npm publish ./sdk/settle --access public"}


def package_dir(registry: str, name: str, root: Path = ROOT) -> Path:
    return root / "crates" / name if registry == "crates" else root / "sdk" / "settle"


def relative_links(text: str) -> list[str]:
    """The link and image targets of a Markdown page that only work inside the repository: a registry shows the page
    alone, so each must be a whole URL (or an anchor of the page itself)."""
    return [t for t in re.findall(r"\]\(([^)\s]+)", text) if not re.match(r"(https?://|mailto:|#)", t)]


def pack_check(registry: str, name: str, root: Path = ROOT, run=subprocess.run) -> tuple[bool, str]:
    """Does the package pack here with no network? crates: `cargo package --offline --no-verify` into a temporary
    target folder (`cargo publish --dry-run` asks the registry, so it is the release run's command and not this one's);
    npm: `npm pack --dry-run`. (it packs, what was said)."""
    where = package_dir(registry, name, root)
    with tempfile.TemporaryDirectory() as tmp:
        if registry == "crates":
            cmd = ["cargo", "package", "--offline", "--allow-dirty", "--no-verify", "--target-dir", tmp]
        else:
            cmd = ["npm", "pack", "--dry-run", "--json", "--offline"]
        try:
            r = run(cmd, cwd=where, capture_output=True, text=True, encoding="utf-8", timeout=150)
        except (OSError, subprocess.TimeoutExpired) as failed:
            return False, f"`{' '.join(cmd[:2])}` could not run here ({type(failed).__name__})"
    if r.returncode != 0:
        return False, f"`{' '.join(cmd[:4])}` failed: {(r.stderr or r.stdout).strip().splitlines()[-1:] or ['no output']}"
    if registry == "crates":
        found = re.search(r"Packaged (\d+) files", r.stderr + r.stdout)
        return True, f"packs offline ({found.group(1)} files)" if found else "packs offline"
    return True, f"packs offline ({len(json.loads(r.stdout)[0]['files'])} files)"


def registry_overview(online: bool = False, fetch=None, run=subprocess.run, root: Path = ROOT) -> tuple[int, list[str]]:
    """(exit status, lines): every package, where it would go, at which version, and whether it is ready. Red when one
    does not pack, has a README link that breaks outside the repository, or (online) a registry did not answer."""
    code, lines = 0, ["What a release would publish. Nothing is published by this command."]
    for registry, name in PACKAGES:
        where, version, at = REGISTRIES[registry], own_version(registry, name, root), held(name)
        lines.append(f"{name} {version} -> {where}" + (f" (held at {at} by scripts/bump_version.py: a version is in a build's bytes)" if at else " (moves with the release)"))
        ok, said = pack_check(registry, name, root, run)
        broken = relative_links((package_dir(registry, name, root) / "README.md").read_text(encoding="utf-8"))
        code |= 0 if ok and not broken else 1
        lines.append(f"  pack    {'ok' if ok else 'FAILED'}: {said}")
        lines.append("  README  ok: every link is absolute" if not broken else f"  README  FAILED: {len(broken)} links work only inside the repository: {', '.join(broken[:5])}")
        if online:
            try:
                have = on_registry(registry, name, fetch)
            except (OSError, ValueError, KeyError) as failed:
                code, have = 1, None
                lines.append(f"  name    FAILED: {where} did not answer ({failed})")
            else:
                lines.append(f"  name    free on {where}: the first version is published by hand" if have is None else
                             f"  name    on {where} with {', '.join(sorted(have))}: check that it is ours with `{OWNERS[registry].format(name=name)}`"
                             + ("" if version not in have else f"; {version} is already there, nothing to publish"))
        else:
            lines.append(f"  name    not asked here (no network). The release run: python scripts/release.py registry-plan --online; then `{OWNERS[registry].format(name=name)}`")
        lines.append(f"  publish `{PUBLISH[registry].format(name=name)}`" + (" (first `cargo publish --dry-run` with the same path)" if registry == "crates" else " (first `npm pack --dry-run ./sdk/settle`)"))
    lines.append("ready: every package packs and every README link is absolute." if code == 0 else "NOT ready: see FAILED above.")
    return code, lines


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
        return _pushable() if ok else 1
    if not os.environ.get("UV_PUBLISH_TOKEN"):
        raise SystemExit("refused: UV_PUBLISH_TOKEN is not set. Export a PyPI token for the knos project (it is never printed). Nothing was uploaded.")
    upload = [str(wheel)] + ([str(sdist)] if sdist.is_file() else [])
    done = subprocess.run(["uv", "publish", "--check-url", "https://pypi.org/simple/", *upload])
    if done.returncode:
        print("uv publish failed (the lines above say why). Run this again: files PyPI already has are skipped.")
        return 1
    ok, said = pypi_check(wait=300)
    print(said)
    return _pushable() if ok else 1


def _pushable() -> int:
    """The last word of `publish`: push only once the index an installer reads lists the wheel (at most 10 minutes)."""
    ok, said = index_check(wait=600)
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
    plan = sub.add_parser("registry-plan", help="may this release publish the package at its own version, and does the registry lack it")
    plan.add_argument("registry", nargs="?", choices=sorted(REGISTRIES), help="with a name and --tag: one package; with nothing: the whole plan")
    plan.add_argument("name", nargs="?")
    plan.add_argument("--tag", help="the release's tag, vX.Y.Z (with a registry and a name)")
    plan.add_argument("--online", action="store_true", help="the whole plan: also ask each registry whether the name is free")
    sub.add_parser("held", help="the version scripts/bump_version.py holds a crate at; nothing when it moves with the release").add_argument("name")
    a = ap.parse_args(argv)
    if a.command == "wheel":
        return wheel_cmd(a.check)
    if a.command == "workflows":
        return workflows_cmd(Path(a.dir))
    if a.command == "verify":
        return verify_cmd(Path(a.dir) if a.dir else None)
    if a.command == "publish":
        return publish_cmd()
    if a.command == "registry-plan":
        if a.registry is None:
            code, lines = registry_overview(a.online)
            print("\n".join(lines))
            return code
        if not a.name or not a.tag:
            ap.error("registry-plan takes a registry, a name and --tag, or nothing at all")
        return registry_plan_cmd(a.registry, a.name, a.tag)
    if a.command == "held":
        print(held(a.name) or "")
        return 0
    ok, said = pypi_check(Path(a.dist) if a.dist else None, a.wait)
    if ok:
        print(said)
        ok, said = index_check(wait=a.wait)
    print(said if ok else f"::error title=PyPI::{said}" if os.environ.get("GITHUB_ACTIONS") else said)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
