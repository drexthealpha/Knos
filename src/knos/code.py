"""Code structure. universal-ctags does the work; this only calls it.

There is no parsing here. No tree-sitter, no AST walk, no language table.
ctags reads 150-odd languages and writes one line per definition, so knos
runs it once when a person says `knos point`, keeps the file it produced,
and reads that file to answer.

What a structural question needs is a name, a file and a line. That is
exactly what a tags file holds, so there is no daemon to keep warm, no child
process per query, and nothing left running between commands.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

BINARY = "ctags"

# Languages whose "definitions" are data, not code. Left in, a single
# configuration file contributes tens of thousands of tags for every string
# and number in it, which is both useless and most of the indexing time.
DATA_LANGUAGES = (
    "JSON",
    "YAML",
    "Markdown",
    "HTML",
    "CSS",
    "SVG",
    "XML",
    "Iniconf",
    "Man",
    "Diff",
    "Txt2tags",
    "ReStructuredText",
    "Asciidoc",
    "Tex",
    "PropertyList",
    "RpmSpec",
)

# Directories that are never the repo's own code.
SKIP = (
    ".git",
    "node_modules",
    ".venv",
    "venv",
    "dist",
    "build",
    "vendor",
    "target",
    ".tox",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".next",
    "third_party",
)


class CodeUnavailable(RuntimeError):
    """ctags is not installed."""


@dataclass(frozen=True)
class Symbol:
    name: str
    kind: str
    path: str
    line: int = 0

    @property
    def short(self) -> str:
        return self.name.rsplit(".", 1)[-1] if self.name else ""

    @property
    def where(self) -> str:
        return f"{self.path}:{self.line}" if self.line else self.path


def binary() -> str:
    found = shutil.which(BINARY)
    if found:
        return found
    guesses = [
        Path.home() / ".ctags" / ("ctags.exe" if os.name == "nt" else "ctags"),
        Path("/usr/local/bin") / BINARY,
        Path("/usr/bin") / BINARY,
    ]
    for g in guesses:
        if g.exists():
            return str(g)
    raise CodeUnavailable(
        "ctags is not installed.\n" "Install it:  https://github.com/universal-ctags/ctags"
    )


def installed() -> bool:
    try:
        binary()
        return True
    except CodeUnavailable:
        return False


def tags_file(repo: Path) -> Path:
    from . import paths

    return paths.store_for(repo).parent / "tags"


def _tracked(repo: Path) -> list[str] | None:
    """The files git knows about, or None if this is not a repo.

    Handing ctags an explicit list rather than letting it walk the tree is
    worth twenty times the speed on a repo with a large `.git`: the walk
    stats every loose object, and the list does not. It also means the
    repo's own `.gitignore` decides what counts as its code, which is the
    answer the person who wrote it already gave.
    """
    try:
        done = subprocess.run(
            ["git", "-C", str(repo), "ls-files", "-z"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=180,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode != 0:
        return None
    return [str(repo / p) for p in done.stdout.split("\0") if p]


def index(repo: Path) -> dict[str, Any]:
    """Read a repo's structure. Run by `knos point`, never on a timer."""
    repo = Path(repo).resolve()
    out = tags_file(repo)
    # The classic sorted format, not JSON: readtags binary-searches a sorted
    # tags file, which is the difference between milliseconds and seconds on
    # a repo the size of a kernel.
    common = [
        binary(),
        "--fields=+n",
        "--sort=yes",
        f"--languages=-{','.join(DATA_LANGUAGES)}",
        "-f",
        str(out),
    ]

    started = time.perf_counter()
    files = _tracked(repo)
    try:
        if files:
            listing = out.with_suffix(".files")
            listing.write_text("\n".join(files), encoding="utf-8")
            subprocess.run(
                [*common, "-L", str(listing)], capture_output=True, text=True, timeout=3600
            )
            listing.unlink(missing_ok=True)
        else:
            # Not a git repo, so walk it, skipping what is never its code.
            subprocess.run(
                [*common, "-R", *(f"--exclude={d}" for d in SKIP), str(repo)],
                capture_output=True,
                text=True,
                timeout=3600,
            )
    except (OSError, subprocess.SubprocessError) as why:
        raise CodeUnavailable(str(why)) from why
    return {
        "nodes": _count(out),
        "seconds": round(time.perf_counter() - started, 1),
    }


def _count(tags: Path) -> int:
    if not tags.exists():
        return 0
    with tags.open(encoding="utf-8", errors="replace") as handle:
        return sum(1 for line in handle if not line.startswith("!_TAG_"))


def readtags() -> str | None:
    """ctags ships a query tool beside itself. Use it if it is there."""
    found = shutil.which("readtags")
    if found:
        return found
    beside = Path(binary()).with_name("readtags.exe" if os.name == "nt" else "readtags")
    return str(beside) if beside.exists() else None


def indexed(repo: Path) -> bool:
    return tags_file(repo).exists()


def search(repo: Path, query: str, limit: int = 20) -> tuple[list[Symbol], float]:
    """Find definitions whose name matches. Returns hits and the time taken."""
    repo = Path(repo).resolve()
    started = time.perf_counter()
    wanted = [w for w in re.split(r"[^A-Za-z0-9_]+", query.lower()) if len(w) > 2]
    tags = tags_file(repo)
    tool = readtags()
    if not wanted or not tags.exists() or tool is None:
        return [], 0.0

    found: list[Symbol] = []
    seen: set[tuple[str, int]] = set()
    for word in wanted[:4]:
        try:
            done = subprocess.run(
                # -e -n: extension fields plus the line number, which is the whole
                # point of the lookup.
                [tool, "-t", str(tags), "-i", "-p", "-e", "-n", "-", word],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
            )
        except (OSError, subprocess.SubprocessError):
            break
        for line in done.stdout.splitlines():
            symbol = _parse(line, repo)
            if symbol is None:
                continue
            key = (symbol.path, symbol.line)
            if key in seen:
                continue
            seen.add(key)
            found.append(symbol)
            if len(found) >= limit:
                return found, (time.perf_counter() - started) * 1000
    return found, (time.perf_counter() - started) * 1000


def _parse(line: str, repo: Path) -> Symbol | None:
    """One tags line: name, file, pattern, then extension fields."""
    parts = line.split("	")
    if len(parts) < 3:
        return None
    name, path = parts[0], parts[1]
    kind, number = "", 0
    for field in parts[2:]:
        if field.startswith("line:"):
            try:
                number = int(field[5:])
            except ValueError:
                number = 0
        elif field.startswith("kind:"):
            kind = field[5:]
        elif len(field) == 1 and field.isalpha():
            kind = field
    try:
        path = str(Path(path).resolve().relative_to(repo)).replace("\\", "/")
    except (ValueError, OSError):
        pass
    return Symbol(name=name, kind=kind, path=path, line=number)


def close() -> None:
    """Nothing is held open, so there is nothing to close."""
