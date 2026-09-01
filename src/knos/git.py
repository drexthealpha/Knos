"""Git history: free context every repo already has.

Commit messages, who changed what, when. Read by shelling out to git, once,
when a person asks. No library, no clone, no network.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path

# Field and record marks that cannot occur in commit prose. The body may
# contain newlines, so the file list is only ever what follows the last mark.
FIELD = "\x1e"
RECORD = "\x01"
FMT = RECORD + FIELD.join(["%H", "%an", "%aI", "%s", "%b"]) + FIELD


@dataclass(frozen=True)
class Commit:
    sha: str
    author: str
    when: str
    subject: str
    body: str = ""
    files: tuple[str, ...] = field(default_factory=tuple)

    @property
    def short(self) -> str:
        return self.sha[:8]

    @property
    def where(self) -> str:
        return f"commit {self.short} {self.when[:10]}"

    @property
    def text(self) -> str:
        return (self.subject + ("\n" + self.body if self.body.strip() else "")).strip()


def is_repo(repo: Path) -> bool:
    return (Path(repo) / ".git").exists()


def _run(repo: Path, args: list[str]) -> str:
    try:
        out = subprocess.run(
            ["git", *args],
            cwd=str(repo),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return out.stdout if out.returncode == 0 else ""


def read_commits(repo: Path, limit: int = 500) -> list[Commit]:
    """Commits newest first, each with the files it touched."""
    repo = Path(repo)
    if not is_repo(repo):
        return []
    raw = _run(repo, ["log", f"-n{limit}", f"--pretty=format:{FMT}", "--name-only"])
    commits: list[Commit] = []
    for chunk in raw.split(RECORD):
        if not chunk.strip():
            continue
        parts = chunk.split(FIELD)
        if len(parts) < 6:
            continue
        sha, author, when, subject, body = (p.strip() for p in parts[:5])
        files = [ln.strip() for ln in parts[5].splitlines() if ln.strip()]
        commits.append(
            Commit(
                sha=sha.strip(),
                author=author,
                when=when,
                subject=subject,
                body=body.strip(),
                files=tuple(dict.fromkeys(files)),
            )
        )
    return commits


def last_touched(repo: Path, needle: str, limit: int = 500) -> list[Commit]:
    """Commits that touched a path or mention a word, newest first."""
    needle = needle.lower()
    out = []
    for c in read_commits(repo, limit):
        if needle in c.text.lower() or any(needle in f.lower() for f in c.files):
            out.append(c)
    return out
