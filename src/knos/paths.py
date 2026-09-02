"""Where knos keeps its data. Never inside the repo it reads."""

from __future__ import annotations

import hashlib
import os
import subprocess
from functools import lru_cache
from pathlib import Path


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


def store_for(repo: Path) -> Path:
    """The sqlite file holding memory for one repo, worktrees included."""
    return work_root(repo) / "memory.db"


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


def pointer() -> Path:
    """File recording the repo most recently pointed at."""
    return home() / "pointed"


def remember_pointed(repo: Path) -> None:
    pointer().write_text(str(Path(repo).resolve()), encoding="utf-8")


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


def pointed_repo() -> Path | None:
    """The repo `knos point` was last run on, or None."""
    p = pointer()
    if not p.exists():
        return None
    raw = p.read_text(encoding="utf-8").strip()
    return Path(raw) if raw else None


def has_store(repo: Path) -> bool:
    """Whether knos has read this repo. Does not create anything."""
    return (home() / slug(shared_root(repo)) / "memory.db").exists()


def current_repo() -> Path | None:
    """The repo to answer from.

    The one you are standing in wins, if knos has read it. Two repos both
    pointed at used to mean the second one answered for both, which is how
    an agent open in one project quietly quotes another.
    """
    here = repo_here()
    if here is not None and has_store(here):
        return here
    return pointed_repo()
