"""A POSIX bash for the tests that run a shell script (scripts/build_site.sh, an adapter's step) as GitHub's Ubuntu
runner does. On Windows a bare `bash` is looked up in System32 first, and that is WSL's launcher, which starts a Linux
distribution (or fails, where none is installed) instead of running the script here. So there the one taken is Git
for Windows' own (GitHub's Windows runners have it under C:\\Program Files\\Git), and never one under the Windows folder
or a Store alias: <Git>\\usr\\bin\\bash.exe, not the <Git>\\bin\\bash.exe launcher, which puts Git's own programs (its
curl among them) before the PATH it is given, ahead of a test's stand-ins. Tests only."""
from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest


def _launcher(p: Path) -> bool:
    """WSL's bash.exe (System32) or a Store app alias (WindowsApps): not a bash that runs a script here."""
    low = str(p).lower()
    system = os.environ.get("SystemRoot", r"C:\Windows").lower().rstrip("\\") + "\\"
    return low.startswith(system) or "\\windowsapps\\" in low


def find() -> str | None:
    if os.name != "nt":
        return shutil.which("bash")
    roots = []
    git = shutil.which("git")
    if git:                     # <Git>\cmd\git.exe (or <Git>\bin\git.exe)
        roots.append(Path(git).resolve().parents[1])
    roots += [Path(base) / "Git" for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramW6432"), r"C:\Program Files") if base]
    candidates = [r / "usr" / "bin" / "bash.exe" for r in roots]
    if shutil.which("bash"):
        candidates.append(Path(shutil.which("bash")))
    return next((str(c) for c in candidates if c.is_file() and not _launcher(c)), None)


def bash() -> str:
    """The bash to run a script with; the test is skipped only where there is none (no Git for Windows)."""
    found = find()
    if not found:
        pytest.skip("no POSIX bash on this machine (on Windows: Git for Windows' bash)")
    return found


def environ(env: dict, first=()) -> dict:
    """`env` for a script run by bash(): PATH is the folders of `first` (a test's stand-ins), then, on Windows, the
    folder of that bash (cp, sed, grep, tr: what the runner has in /usr/bin), then the PATH of `env` or of this process."""
    parts = [str(p) for p in first] + ([str(Path(bash()).parent)] if os.name == "nt" else [])
    return {**env, "PATH": os.pathsep.join([*parts, env.get("PATH", os.environ.get("PATH", ""))])}


def path(p) -> str:
    """A path as a bash argument: with / on Windows too (bash reads \\ as an escape, and dirname splits only at /)."""
    return str(p).replace("\\", "/")
