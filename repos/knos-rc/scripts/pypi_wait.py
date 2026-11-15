"""Wait until PyPI serves the exact knos file a hash-pinned requirements file names, then exit 0.

    python scripts/pypi_wait.py requirements/sign.txt [--package knos] [--most 600]

The worker's `claims` job installs knos from requirements/sign.txt (`knos==X --hash=sha256:H`), and a release commit
reaches the default branch before PyPI has the file it pins: an install started then fails. This asks PyPI's simple
index the way an installer does (the JSON form of PEP 691: `Accept: application/vnd.pypi.simple.v1+json`,
https://peps.python.org/pep-0691/) and waits, with a growing pause (5, 10, 20, 40, then 60 s), until a file of that
version with one of the pinned hashes is listed. After `--most` seconds it exits 1 and says what it last saw.
Standard library only: it runs before anything is installed.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.request
from pathlib import Path
from typing import Callable

INDEX = "https://pypi.org/simple/{}/"
ACCEPT = "application/vnd.pypi.simple.v1+json"
PAUSES = (5, 10, 20, 40)        # then 60 s each time
LAST = 60


def pinned(text: str, package: str) -> tuple[str, set[str]]:
    """(version, {sha256, ...}) of `package==version --hash=sha256:...` in a requirements file (continued lines too)."""
    joined = re.sub(r"\\\s*\n", " ", text)
    for line in joined.splitlines():
        found = re.match(rf"\s*{re.escape(package)}==([0-9][^\s;]*)(.*)", line, re.I)
        if found:
            hashes = set(re.findall(r"--hash=sha256:([0-9a-f]{64})", found.group(2)))
            if not hashes:
                raise SystemExit(f"{package}=={found.group(1)} has no --hash=sha256 in the requirements file")
            return found.group(1), hashes
    raise SystemExit(f"the requirements file pins no {package}==<version>")


def listed(doc: dict, package: str, version: str, hashes: set[str]) -> bool:
    """Whether the index lists a file of `version` with one of `hashes`."""
    stem = re.sub(r"[-_.]+", "_", package).lower()
    for f in doc.get("files") or []:
        name = str(f.get("filename") or "").lower()
        if (name.startswith(f"{stem}-{version}-") or name == f"{stem}-{version}.tar.gz") and (f.get("hashes") or {}).get("sha256") in hashes:
            return True
    return False


def fetch(package: str) -> dict:
    req = urllib.request.Request(INDEX.format(package), headers={"Accept": ACCEPT, "Cache-Control": "no-cache"})
    with urllib.request.urlopen(req, timeout=30) as r:      # noqa: S310 - a fixed https URL
        return json.loads(r.read().decode("utf-8"))


def tell(line: str) -> None:
    """One line of the log, written out at once: a job's output is a pipe, and a pipe holds what Python prints until
    the process ends (staging, 8 Oct: all twelve "waiting" lines of a ten-minute wait reached the log in its last
    second). A wait that says nothing while it waits looks like a hang."""
    print(line, flush=True)


def wait(package: str, version: str, hashes: set[str], most: float, get: Callable[[str], dict] | None = None,
         sleep: Callable[[float], None] | None = None, say: Callable[[str], None] | None = None) -> bool:
    """True once the file is listed; False after `most` seconds of pauses."""
    get, sleep, say = get or fetch, sleep or time.sleep, say or tell
    waited, n, seen = 0.0, 0, "nothing yet"
    while True:
        try:
            if listed(get(package), package, version, hashes):
                say(f"PyPI lists {package} {version} with the pinned hash (after {waited:.0f} s)")
                return True
            seen = f"no file of {package} {version} with the pinned hash"
        except (OSError, ValueError) as why:        # an index that does not answer yet is a reason to wait, not to stop
            seen = f"{type(why).__name__}: {why}"
        pause = PAUSES[n] if n < len(PAUSES) else LAST
        if waited + pause > most:
            say(f"PyPI did not list {package} {version} with the pinned hash within {most:.0f} s; last seen: {seen}")
            return False
        say(f"waiting {pause} s for {package} {version} on PyPI ({seen})")
        sleep(pause)
        waited, n = waited + pause, n + 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Wait until PyPI lists the file a hash-pinned requirements file names.")
    p.add_argument("requirements", type=Path)
    p.add_argument("--package", default="knos")
    p.add_argument("--most", type=float, default=600.0, help="seconds to wait at most (default 600)")
    a = p.parse_args(argv)
    version, hashes = pinned(a.requirements.read_text(encoding="utf-8"), a.package)
    return 0 if wait(a.package, version, hashes, a.most) else 1


if __name__ == "__main__":
    sys.exit(main())
