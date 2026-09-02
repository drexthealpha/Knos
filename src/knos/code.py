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

from . import builtin_reader

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

    return paths.work_dir(repo) / "tags"


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


# Seconds the automatic read gives this reader before dropping it. Most
# projects finish well inside it; the kernel takes two minutes and does not.
CODE_BUDGET = 3.0


def index(repo: Path, budget: float | None = None) -> dict[str, Any]:
    """Read a repo's structure. Run by `knos point`, never on a timer.

    `budget` caps how long the reader may take. The read that happens by
    itself gives it a few seconds, which is enough for most projects and
    not enough for the kernel; when it runs out the partial tags file is
    deleted, so a repo is either indexed or plainly not, never half. A
    person running `knos point` gives it no budget and waits.
    """
    repo = Path(repo).resolve()
    out = tags_file(repo)
    started = time.perf_counter()

    # Asking git for the file list costs seconds on a large repo, and on a
    # large repo the answer is always "too big to read in a few seconds".
    # The index file says how many entries there are without listing them.
    if budget is not None and _looks_huge(repo):
        return {"nodes": 0, "seconds": round(time.perf_counter() - started, 1), "ran_out": True}

    files = _tracked(repo)

    # Asked before naming the binary, because naming it is what raises when
    # it is not there — and a machine without ctags is the ordinary case
    # this branch exists for.
    if not installed():
        # No ctags on this machine. Rather than answer every structural
        # question with "install something", knos reads the tracked files
        # itself. Fewer languages and fewer kinds, but a file and a line.
        own = own_file(repo)
        if files is not None and _still_current(own, files):
            return {"nodes": _count_own(own), "seconds": 0.0, "reused": True, "own": True}
        found = builtin_reader.write_index(
            repo, files if files is not None else _walk(repo), own, budget
        )
        if found < 0:
            _discard(own)
            return {
                "nodes": 0,
                "seconds": round(time.perf_counter() - started, 1),
                "ran_out": True,
            }
        return {
            "nodes": found,
            "seconds": round(time.perf_counter() - started, 1),
            "own": True,
        }

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

    # The tags file survives `knos point` deleting the store, and reading a
    # repo that has not changed since it was written produces the same file
    # again. On a large repo that is the longest part of the command, spent
    # to learn nothing. Any tracked file touched since makes it stale, and
    # then it is rebuilt.
    if files and _still_current(out, files):
        return {"nodes": _count(out), "seconds": 0.0, "reused": True}

    # Burning the whole budget to find out a repo is too big is the same
    # wait, paid for nothing. A tree this size never finishes in seconds.
    TOO_BIG = 20_000
    if budget is not None and files is not None and len(files) > TOO_BIG:
        return {"nodes": 0, "seconds": round(time.perf_counter() - started, 1), "ran_out": True}

    limit = budget if budget is not None else 3600
    listing = out.with_suffix(".files")
    try:
        if files:
            listing.write_text("\n".join(files), encoding="utf-8")
            subprocess.run(
                [*common, "-L", str(listing)], capture_output=True, text=True, timeout=limit
            )
        else:
            # Not a git repo, so walk it, skipping what is never its code.
            subprocess.run(
                [*common, "-R", *(f"--exclude={d}" for d in SKIP), str(repo)],
                capture_output=True,
                text=True,
                timeout=limit,
            )
    except subprocess.TimeoutExpired:
        # Out of time. Leaving what it managed would answer some questions
        # and silently miss others, which is worse than answering none.
        _discard(out)
        if out.exists():
            # Windows would not let go of it. Say so beside it, so a partial
            # read is never mistaken for a whole one.
            try:
                out.with_suffix(".partial").write_text("", encoding="utf-8")
            except OSError:
                pass
        return {"nodes": 0, "seconds": round(time.perf_counter() - started, 1), "ran_out": True}
    except (OSError, subprocess.SubprocessError) as why:
        raise CodeUnavailable(str(why)) from why
    finally:
        _discard(listing)
    _discard(out.with_suffix(".partial"))
    return {
        "nodes": _count(out),
        "seconds": round(time.perf_counter() - started, 1),
    }


def own_file(repo: Path) -> Path:
    """Where the reader knos carries writes what it found."""
    from . import paths

    return paths.work_dir(repo) / "symbols"


def _count_own(f: Path) -> int:
    try:
        return sum(1 for line in f.read_text(encoding="utf-8").splitlines() if line)
    except OSError:
        return 0


def _walk(repo: Path) -> list[str]:
    """Every file in a folder that is not a git repo, skipping the obvious."""
    found: list[str] = []
    stack = [Path(repo)]
    while stack:
        d = stack.pop()
        try:
            for e in d.iterdir():
                if e.is_dir():
                    if e.name not in SKIP and not e.name.startswith("."):
                        stack.append(e)
                elif e.is_file():
                    found.append(str(e))
        except OSError:
            continue
    return found


# Git's index holds roughly 60-100 bytes per tracked file. Past this the
# repo has tens of thousands of files and no reader finishes in seconds, so
# there is nothing to learn from counting them exactly.
HUGE_INDEX_BYTES = 2_000_000


def _looks_huge(repo: Path) -> bool:
    """Whether this repo is too big for a few seconds of reading.

    One stat, against a `git ls-files` that took 2.26 seconds on the kernel
    to produce a list this then threw away.
    """
    try:
        common = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--git-dir"],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    if common.returncode != 0:
        return False
    index = Path(common.stdout.strip())
    if not index.is_absolute():
        index = repo / index
    try:
        return (index / "index").stat().st_size > HUGE_INDEX_BYTES
    except OSError:
        return False


def _still_current(tags: Path, files: list[str]) -> bool:
    """Whether every tracked file is older than the tags file.

    Stat is cheap and ctags is not, so this trades a walk of the file list
    against re-reading every file in the repo.
    """
    try:
        written = tags.stat().st_mtime
    except OSError:
        return False
    for path in files:
        try:
            if os.stat(path).st_mtime > written:
                return False
        except OSError:
            # A tracked file that is not on disk means the tree moved under
            # us. Rebuild rather than guess.
            return False
    return True


def _discard(f: Path) -> None:
    """Remove a working file, and never fail the call over it.

    Windows keeps a handle on a file a killed process was writing, so
    deleting it right after a timeout raises. The read already has its
    answer; a leftover temporary file is not worth losing it for.
    """
    try:
        f.unlink(missing_ok=True)
    except OSError:
        pass


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
    # Looking beside ctags means naming ctags, and naming it raises when it
    # is not installed — which is exactly when this is asked. There is no
    # readtags without ctags, so say so instead of throwing.
    try:
        where = binary()
    except CodeUnavailable:
        return None
    beside = Path(where).with_name("readtags.exe" if os.name == "nt" else "readtags")
    return str(beside) if beside.exists() else None


def indexed(repo: Path) -> bool:
    """Whether this repo's structure has been read, all of it.

    A reader that ran out of time leaves a marker beside the tags file when
    the file itself could not be removed. Half an index answers some
    questions and silently misses others, so half counts as none.
    """
    tags = tags_file(repo)
    if tags.exists() and not tags.with_suffix(".partial").exists():
        return True
    return own_file(repo).exists()


def search(repo: Path, query: str, limit: int = 20) -> tuple[list[Symbol], float]:
    """Find definitions whose name matches. Returns hits and the time taken."""
    repo = Path(repo).resolve()
    started = time.perf_counter()
    wanted = [w for w in re.split(r"[^A-Za-z0-9_]+", query.lower()) if len(w) > 2]
    tags = tags_file(repo)
    tool = readtags()
    if not wanted:
        return [], 0.0
    if not tags.exists() or tool is None:
        own = own_file(repo)
        if not own.exists():
            return [], 0.0
        found = [
            Symbol(
                name=name,
                kind=kind,
                path=rel,
                line=number,
            )
            for name, rel, number, kind in builtin_reader.search_index(
                own, wanted[:4], limit
            )
        ]
        return found, (time.perf_counter() - started) * 1000

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
