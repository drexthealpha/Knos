"""Where knos keeps its data. Never inside the repo it reads."""

from __future__ import annotations

import hashlib
import os
import subprocess
from functools import lru_cache
from pathlib import Path


def remove_tree(path: Path | str, tries: int = 5) -> bool:
    """Delete a temporary folder knos made, on every OS. Windows refuses to delete read-only files (git's objects
    are read-only) and files another handle still has open (a SQLite store closing), so make files writable and
    retry briefly. Returns whether the folder is gone."""
    import shutil
    import stat
    import sys
    import time

    def writable(func, target, _exc):
        try:
            os.chmod(target, stat.S_IWRITE | stat.S_IREAD)
            func(target)
        except OSError:
            pass

    target = Path(path)
    for attempt in range(tries):
        if not target.exists():
            return True
        try:
            if sys.version_info >= (3, 12):
                shutil.rmtree(target, onexc=writable)
            else:
                shutil.rmtree(target, onerror=writable)
        except OSError:
            pass
        if not target.exists():
            return True
        time.sleep(0.2 * (attempt + 1))
    return not target.exists()


def home() -> Path:
    """The knos data directory. Override with KNOS_HOME."""
    override = os.environ.get("KNOS_HOME")
    root = Path(override) if override else Path.home() / ".knos"
    root.mkdir(parents=True, exist_ok=True)
    return root


def slug(repo: Path) -> str:
    """A stable short name for a repo path."""
    real = str(Path(repo).resolve()).lower()
    digest = hashlib.sha256(real.encode()).hexdigest()[:10]
    return f"{Path(real).name}-{digest}"


@lru_cache(maxsize=64)
def shared_root(repo: Path) -> Path:
    """The one directory every worktree of this repo agrees on.

    A worktree is a second working directory over the same repository, and
    people use them precisely so two agents cannot touch each other's files.
    That is isolation, and it is the right call — but it also gave each
    worktree its own memory, so a decision made in one was invisible in the
    next and a claim in one held nothing in the other.

    Git already knows they are the same repo: every worktree shares one
    `.git` directory, and `--git-common-dir` names it. Its parent is the main
    working tree, and that is what knos keys memory on. No config, no server,
    nothing for anyone to keep in sync.

    Cached, because this is a subprocess on a path taken by every command and
    every tool call.
    """
    repo = Path(repo).resolve()
    try:
        done = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--git-common-dir"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return repo
    if done.returncode != 0:
        return repo  # not a repo at all: it is its own root
    common = Path(done.stdout.strip())
    if not common.is_absolute():
        common = repo / common
    try:
        main = common.resolve().parent
    except OSError:
        return repo
    return main if main.is_dir() else repo


def worktrees(repo: Path) -> list[Path]:
    """Every working tree of this repo, main one first."""
    try:
        done = subprocess.run(
            ["git", "-C", str(repo), "worktree", "list", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if done.returncode != 0:
        return []
    return [
        Path(line[len("worktree ") :].strip())
        for line in done.stdout.splitlines()
        if line.startswith("worktree ")
    ]


SIBYL_STORE = "memory.db"


def shared_store() -> Path:
    """The one Sibyl store every repo's memory lives in, as a tenant of its own: `$SIBYL_MEMORY_DB`, or Sibyl's own
    default ~/.sibyl-memory/memory.db. That is where Sibyl's account-wide free-tier cap measures it; a store kept
    anywhere else would escape the cap, and knos does not route around Sibyl's cap."""
    override = os.environ.get("SIBYL_MEMORY_DB")
    p = Path(override).expanduser() if override else Path.home() / ".sibyl-memory" / SIBYL_STORE
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def store_for(repo: Path) -> Path:
    """The Sibyl store holding memory for one repo (the shared store; the repo is a tenant in it)."""
    return shared_store()


def tenant_for(repo: Path) -> str:
    """This repo's tenant in the shared store, worktrees included."""
    return "knos-" + slug(shared_root(repo))


def legacy_store_for(repo: Path) -> Path:
    """Where 0.1-0.2 kept one store per repo (outside Sibyl's cap). Migrated on first open."""
    return work_root(repo) / SIBYL_STORE


def born_for(repo: Path) -> Path:
    """Marks that this repo's memory was created here, so a vanished store is refused rather than replaced."""
    return work_root(repo) / "memory.born"


@lru_cache(maxsize=64)
def work_root(repo: Path) -> Path:
    """The directory holding one repo's store, made if it is not there.

    Cached: this was hashing the path and calling mkdir on every question
    about every file, which on a large repo was tens of thousands of writes
    to find a name that never changes.
    """
    d = home() / slug(shared_root(repo))
    d.mkdir(parents=True, exist_ok=True)
    return d


def work_dir(repo: Path) -> Path:
    """Where things belonging to one working tree go, not the repo.

    Memory is shared across worktrees on purpose. What the code looks like is
    not: two worktrees are usually two branches, and answering from the other
    one's structure would name a file and a line that is not there.
    """
    d = home() / slug(repo)
    d.mkdir(parents=True, exist_ok=True)
    return d


def repo_here(start: Path | None = None) -> Path | None:
    """The git repo the current directory is inside, if any."""
    here = Path(start) if start else Path.cwd()
    try:
        here = here.resolve()
    except OSError:
        return None
    for d in (here, *here.parents):
        if (d / ".git").exists():
            return d
    return None


def has_store(repo: Path) -> bool:
    """Whether knos has read this repo. Does not create anything."""
    d = home() / slug(shared_root(repo))
    return (d / "memory.born").exists() or (d / SIBYL_STORE).exists()

