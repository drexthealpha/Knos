"""One version everywhere a version lives.

    python scripts/bump_version.py 0.3.13        write it everywhere (safe to run again: a second run changes nothing)
    python scripts/bump_version.py --check       exit 1 unless every place names the version of pyproject.toml
    python scripts/bump_version.py --check 0.3.13    ... unless every place names exactly this version
    python scripts/bump_version.py --list        every place and what it names now

A place is a manifest (PLACES: the package, its lock, the registries' manifests, the plugin manifests, the JavaScript
client, the Rust crates and their lock files, the IDLs) or a PIN: a line somewhere in the tree that installs or names
one release (`knos==X`, `tag = "vX"`, `drexthealpha/Knos@vX`, `drexthealpha/Knos/.github/actions/knos-verify@vX`, `releases/download/vX/knos-settle-X.tgz`,
`git tag vX && git push origin vX`). Pins are found by pattern in every file git tracks, so a new document that
installs a release is covered the day it is written.

The lock is not a pin: requirements/sign.txt ends with `knos==X --hash=sha256:<the wheel>` once a release is locked,
and a wheel of another version has another hash, so a bump removes an earlier release's line instead of renaming it.

What it does not write: CHANGELOG.md (its top entry is written by hand; --check says when it is not this version),
programs/ (the first deployment, which never changes), a sentence that mentions an earlier release as history, and
the fixtures: after a version change the programs' bytes change, so run `bash scripts/build_programs_v2.sh all`
once before the release tree is frozen (the deployed bytes are the verified build's, never a fixture's).

A release that changes no program must not change a program's bytes either, and a crate's version is in its bytes
(the compiler mixes it into every symbol's hash: in 0.3.14 the example programs' binaries changed with no line of
their source changed). So the crates named in PROGRAMS_FROZEN stay at FROZEN_AT, with their entries in every lock
file and the IDLs that describe them, whatever version is written elsewhere: a bump writes FROZEN_AT there, and
--check fails when one of them names anything else. Empty PROGRAMS_FROZEN in the release that next changes a program.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
V = r"(\d+\.\d+\.\d+)"
OURS = ("knos", "knos-oidc-interface", "knos-pay-interface", "knos_oidc", "knos_pay", "knos_meter", "knos_passkey", "knos-handler-tests")
JSON_VERSION = r'"version": "' + V + '"'
# (files, pattern): every match's groups are the version. Each file must match at least once. A line ends in \n or in
# \r\n: a file written on Windows (by an editor, or Python's text mode) names its version as any other file does, and
# a bump still rewrites the version's bytes and nothing else.
PLACES: list[tuple[str, str]] = [
    ("pyproject.toml", r'(?m)\A(?:.*\n)*?\[project\]\r?\n(?:(?!\[).*\n)*?version = "' + V + '"'),
    ("uv.lock", r'\[\[package\]\]\r?\nname = "knos"\r?\nversion = "' + V + '"'),
    ("server.json", JSON_VERSION),                              # twice: the server, and the PyPI package it runs
    ("gemini-extension.json", JSON_VERSION),
    ("plugin/.claude-plugin/plugin.json", JSON_VERSION),
    ("plugin/.codex-plugin/plugin.json", JSON_VERSION),
    ("sdk/settle/package.json", r'\A\{\r?\n(?:  .*\n)*?  ' + JSON_VERSION),
    ("programs-v2/handlers/Cargo.toml", r'(?m)^\[package\]\r?\n(?:(?!\[).*\n)*?version = "' + V + '"'),    # the handler tests: in no program's build
]
# The programs, the two interface crates their builds read (knos_meter and the example programs depend on them by
# path), and the IDLs, which carry the version of the program they describe.
PROGRAM_PLACES: list[tuple[str, str]] = [
    ("idl/*.json", r'\A\{\r?\n(?:  .*\n)*?  ' + JSON_VERSION),
    ("crates/*/Cargo.toml", r'(?m)^\[package\]\r?\n(?:(?!\[).*\n)*?version = "' + V + '"'),
    ("programs-v2/knos_*/Cargo.toml", r'(?m)^\[package\]\r?\n(?:(?!\[).*\n)*?version = "' + V + '"'),
]
# 0.3.15 changes no program: upgrade proposals 3 to 6 name builds of these crates at 0.3.14, approved and waiting out
# their 48 hours. The committed builds (tests/fixtures/*.so) and whatever anyone builds from this tree to compare
# with the chain must stay byte-identical to them until they execute, and a version is in the bytes.
PROGRAMS_FROZEN: tuple[str, ...] = ("knos_oidc", "knos_pay", "knos_meter", "knos_passkey", "knos-oidc-interface", "knos-pay-interface")
FROZEN_AT = "0.3.14"
LOCKS = ("crates/*/Cargo.lock", "examples/*/Cargo.lock", "programs-v2/Cargo.lock", "programs-v2/knos_oidc/fuzz/Cargo.lock",
         "programs-v2/handlers/Cargo.lock")     # program.yml runs the handler tests with --locked: a lock one release behind fails the job



def _locked(names) -> str | None:
    """The pattern of these crates' entries in a lock file; None for no crate (an empty alternation matches every package)."""
    return r'name = "(?:' + "|".join(names) + r')"\r?\nversion = "' + V + '"' if names else None


LOCKED = _locked([n for n in OURS[1:] if n not in PROGRAMS_FROZEN])
LOCKED_FROZEN = _locked(PROGRAMS_FROZEN)
PINS = (r"\bknos==" + V, r'tag = "v' + V + '"', r"drexthealpha/Knos@v" + V, r"drexthealpha/Knos/\.github/actions/knos-verify@v" + V, r"releases/download/v" + V + r"/knos-settle-" + V + r"\.tgz",
        r"git tag v" + V + r" && git push origin v" + V)
PIN = re.compile("|".join(PINS))
# history, the first deployment, the patterns themselves, and the lock (its line names a wheel by hash: see unlock)
NOT_PINNED = ("CHANGELOG.md", "programs/", "scripts/bump_version.py", "requirements/sign.txt")
LOCK = re.compile(r"\r?\nknos==" + V + r" --hash=sha256:[0-9a-f]{64}\r?\n\Z")
CHANGELOG = re.compile(r"^## " + V + r"\b", re.M)


def tracked(root: Path) -> list[str]:
    """Every file git tracks or would add, by its path from the root (a plain folder: every file in it)."""
    done = subprocess.run(["git", "ls-files", "-co", "--exclude-standard", "-z"], cwd=root, capture_output=True, text=True)
    if done.returncode == 0 and done.stdout:
        return sorted(p for p in done.stdout.split("\0") if p and (root / p).is_file())
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file() and ".git" not in p.parts)


def _text(path: Path) -> str | None:
    try:
        data = path.read_bytes()
    except OSError:
        return None
    return None if b"\0" in data[:8192] else data.decode("utf-8", errors="surrogateescape")


def _spans(text: str, pattern: str | re.Pattern) -> list[tuple[int, int]]:
    return [m.span(k) for m in re.finditer(pattern, text) for k in range(1, (m.re.groups or 0) + 1) if m.group(k) is not None]


def _manifests(root: Path) -> tuple[dict[str, list[tuple[int, int]]], dict[str, list[tuple[int, int]]], list[str]]:
    """({file: spans that move with a release}, {file: spans held at FROZEN_AT}, the places that name no version though
    they must). A lock file can hold both kinds: the handler tests' lock names the programs and itself."""
    moving: dict[str, list[tuple[int, int]]] = {}
    frozen: dict[str, list[tuple[int, int]]] = {}
    missing = []
    held = frozen if PROGRAMS_FROZEN else moving
    plan = [*((f, p, None) for f, p in PLACES), *((f, None, p) for f, p in PROGRAM_PLACES)] if PROGRAMS_FROZEN else \
        [*((f, p, None) for f, p in (*PLACES, *PROGRAM_PLACES))]
    for files, moves, stays in [*plan, *((lock, LOCKED, LOCKED_FROZEN) for lock in LOCKS)]:
        paths = sorted(root.glob(files))
        if not paths:
            missing.append(f"{files}: no such file")
        for path in paths:
            text, rel = _text(path) or "", path.relative_to(root).as_posix()
            a = _spans(text, moves) if moves else []
            b = _spans(text, stays) if stays else []
            if not a and not b:
                missing.append(f"{rel}: carries no version")
            if a:
                moving.setdefault(rel, []).extend(a)
            if b:
                held.setdefault(rel, []).extend(b)
    return moving, frozen, missing


def found(root: Path = ROOT) -> tuple[dict[str, list[tuple[int, int]]], list[str]]:
    """({file: the spans of every version it names that a release moves}, the places that name none though they must)."""
    spans, _frozen, missing = _manifests(root)
    for rel in tracked(root):
        if rel.startswith(NOT_PINNED) or rel.endswith("package-lock.json"):
            continue
        text = _text(root / rel)
        if text is not None and (got := _spans(text, PIN)):
            spans.setdefault(rel, []).extend(got)
    return {rel: sorted(set(s)) for rel, s in spans.items()}, missing


def _lines(root: Path, spans: dict[str, list[tuple[int, int]]]) -> list[tuple[str, int, str]]:
    out = []
    for rel, at in sorted(spans.items()):
        text = _text(root / rel) or ""
        out += [(rel, text.count("\n", 0, a) + 1, text[a:b]) for a, b in sorted(set(at))]
    return out


def places(root: Path = ROOT) -> list[tuple[str, int, str]]:
    """(file, line, version) of every place a release moves, in the order of the files' names."""
    return _lines(root, found(root)[0])


def frozen_places(root: Path = ROOT) -> list[tuple[str, int, str]]:
    """(file, line, version) of every place held at FROZEN_AT: the frozen crates, their lock entries and the IDLs."""
    return _lines(root, _manifests(root)[1])


def project(root: Path = ROOT) -> str:
    m = re.search(PLACES[0][1], _text(root / "pyproject.toml") or "")
    if not m:
        raise SystemExit("pyproject.toml carries no version in its [project] table")
    return m.group(1)


def disagreements(version: str | None = None, root: Path = ROOT, changelog: bool = True) -> list[str]:
    """Every place that does not name `version` (default: pyproject.toml's), one line each."""
    want = version or project(root)
    said = [f"{rel}:{line}: {got}, not {want}" for rel, line, got in places(root) if got != want]
    said += [f"{rel}:{line}: {got}, not {FROZEN_AT} (a program crate, frozen: its builds must stay byte-identical until the proposed upgrades execute)"
             for rel, line, got in frozen_places(root) if got != FROZEN_AT]
    said += found(root)[1]
    if changelog:
        top = CHANGELOG.search(_text(root / "CHANGELOG.md") or "")
        if not top or top.group(1) != want:
            said.append(f"CHANGELOG.md: its top entry is {top.group(1) if top else 'missing'}, not {want} (written by hand)")
    return said


def unlock(version: str, root: Path = ROOT) -> bool:
    """requirements/sign.txt ends with the hash of one release's wheel once that release is locked. A wheel of another
    version has another hash, so the line of an earlier release is removed, never renamed: the next release locks its
    own wheel (docs/RELEASE.md). True when a line was removed."""
    path = root / "requirements" / "sign.txt"
    text = _text(path) or ""
    m = LOCK.search(text)
    if not m or m.group(1) == version:
        return False
    end = "\r\n" if text[m.start()] == "\r" else "\n"         # the line before keeps the end it had
    path.write_bytes((text[:m.start()] + end).encode("utf-8"))
    return True


def bump(version: str, root: Path = ROOT) -> list[str]:
    """Write `version` in every place. Returns the files that changed."""
    if not re.fullmatch(V, version):
        raise SystemExit(f"{version} is not a version: three numbers, as in 0.3.13")
    changed = ["requirements/sign.txt"] if unlock(version, root) else []
    _moving, frozen, _missing = _manifests(root)
    spans = {rel: [(a, b, version) for a, b in at] for rel, at in found(root)[0].items()}
    for rel, at in frozen.items():                        # held where they are: a crate an earlier run moved is put back
        spans.setdefault(rel, []).extend((a, b, FROZEN_AT) for a, b in at)
    for rel, at in sorted(spans.items()):
        text = new = _text(root / rel) or ""
        for a, b, v in sorted(set(at), reverse=True):     # from the end, so the earlier spans stay where they are
            new = new[:a] + v + new[b:]
        if new != text:
            (root / rel).write_bytes(new.encode("utf-8", errors="surrogateescape"))
            changed.append(rel)
    return sorted(changed)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="One version everywhere a version lives.")
    ap.add_argument("version", nargs="?", help="the version to write, or with --check the version every place must name")
    ap.add_argument("--check", action="store_true", help="change nothing; exit 1 unless every place agrees")
    ap.add_argument("--list", action="store_true", help="change nothing; print every place and what it names")
    a = ap.parse_args(argv)
    if a.list:
        for rel, line, got in places():
            print(f"{got}  {rel}:{line}")
        for rel, line, got in frozen_places():
            print(f"{got}  {rel}:{line}  (frozen at {FROZEN_AT})")
        return 0
    if a.check:
        said = disagreements(a.version)
        for line in said:
            print(line)
        print(f"{len(places())} places name {a.version or project()}" + (f"; {len(frozen_places())} of the program crates stay at {FROZEN_AT}." if PROGRAMS_FROZEN else ".") if not said else
              f"{len(said)} place(s) disagree. Write the version everywhere: python scripts/bump_version.py {a.version or project()}")
        return 1 if said else 0
    if not a.version:
        ap.error("name the version to write, or --check, or --list")
    changed = bump(a.version)
    print(f"Wrote {a.version} in {len(changed)} file(s)" + (": " + ", ".join(changed) if changed else " (every place named it already)") + ".")
    left = disagreements(a.version)
    for line in left:
        print(f"still to do: {line}")
    if PROGRAMS_FROZEN:
        print(f"The program crates stay at {FROZEN_AT} (PROGRAMS_FROZEN): no program is rebuilt, and the fixtures are not touched.")
    elif changed and any(rel.startswith("programs-v2/") for rel in changed):
        print("The program crates changed: run `bash scripts/build_programs_v2.sh all` once, so the fixtures are builds of this version.")
    return 1 if [line for line in left if not line.startswith("CHANGELOG.md")] else 0


if __name__ == "__main__":
    sys.exit(main())
