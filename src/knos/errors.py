"""How knos fails.

Every message says what happened in a sentence a person would say, and ends
with the command that fixes it. No stack traces, no exception names, no
"failed to", no paths into knos's own insides.

A private path never appears here. Not as a skip, not as a count, not as a
reason a number is lower than expected: a message that says a secret was
skipped has leaked the secret's existence, which is the one thing 1.6
promises will not happen.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Problem:
    """Something that went wrong, and the command that fixes it."""

    said: str
    fix: str

    def __str__(self) -> str:
        return f"{self.said}\n{self.fix}"


def nothing_indexed() -> Problem:
    return Problem(
        "This folder is not a git repo, so knos does not know what to read.",
        "Go to your project and ask again, or name it:  knos point ~/work/repo",
    )


def no_such_folder(path: str) -> Problem:
    return Problem(f"No such folder: {path}", "Read a folder you have:  knos point .")


def nothing_found(repo: Path) -> Problem:
    return Problem("Nothing about that yet.", f"Read more first:  knos point {repo}")


def memory_full(repo: Path, kept: int = 0) -> Problem:
    """The store hit its 5 MB ceiling part-way through reading.

    Sessions and commits are read newest first, so what is in the store is
    the recent end of both. Nothing already written is lost or overwritten;
    the read simply stops.
    """
    what = f"Kept the newest {kept} things and stopped there." if kept else "Kept the newest and stopped there."
    return Problem(
        f"This repo's memory is full at 5 MB. {what} Older sessions and"
        " commits were not read. What is stored is still whole - nothing was"
        " evicted or truncated.",
        f"Read one folder instead of all of it:  knos point {Path(repo)}/src",
    )


def busy(repo: Path) -> Problem:
    return Problem(
        f"knos is already reading {Path(repo).name} somewhere else.",
        "Wait for that to finish, then try again.",
    )


def not_a_repo(path: str) -> Problem:
    return Problem(
        f"{path} has no git history, so knos read the code and sessions only.",
        "Read a folder with history:  knos point <a git repo>",
    )


def install_ctags() -> str:
    """The one line that installs a code reader, for this machine.

    One command, for the platform the person is actually on. Offering all
    three and letting them work out which is theirs is how a one-line fix
    becomes a five-minute detour.
    """
    import sys

    if sys.platform.startswith("win"):
        return "winget install UniversalCtags.Ctags"
    if sys.platform == "darwin":
        return "brew install universal-ctags"
    return "sudo apt install universal-ctags"


def code_engine_missing() -> Problem:
    return Problem(
        "No code reader here, so knos answered from sessions and commits only.",
        f"For answers that name a file and line:  {install_ctags()}",
    )


def structure_unread(repo: Path) -> Problem:
    """The code reader is the slow one, so it waits to be asked for.

    Reading a repo happens by itself on the first question. Running the code
    reader there too would have meant two minutes of silence on a big repo,
    so it is the one source a person asks for. Saying nothing about it would
    be the same silent hole in a different place.
    """
    return Problem(
        "Answered from sessions, commits and your rules. The code structure"
        " is the one part knos has not read.",
        f"For answers that name a file and line:  knos point {Path(repo)}",
    )


# ---- things knos steps over rather than stopping for -------------------


@dataclass(frozen=True)
class Skipped:
    """A file knos could not read. Named, counted, and carried on from."""

    path: str
    because: str


def unreadable(path: str, because: str = "it could not be read") -> Skipped:
    return Skipped(path=path, because=because)


def report_skipped(skipped: list[Skipped]) -> str:
    """One line per file, then nothing more. knos kept going regardless."""
    if not skipped:
        return ""
    lines = [f"  {s.path} was skipped, {s.because}." for s in skipped[:5]]
    if len(skipped) > 5:
        lines.append(f"  and {len(skipped) - 5} more.")
    lines.append("  Everything else was read.")
    return "\n".join(lines)


def stale(path: str) -> str:
    """A file that was read and has since gone.

    Said out loud rather than quietly dropped, because an answer that cites
    a file nobody can open is worse than one that admits the file moved.
    """
    return f"{path} is gone since knos read it"
