"""Secrets are private on a fresh index, without being asked.

A private path stays searchable by the person at the keyboard. Agents never
see it, and never see that it exists: no counts, no redactions, no "hidden"
notices. Absence is the only signal.
"""

from __future__ import annotations

import fnmatch
import json
from pathlib import Path

from . import paths

# Private without being asked. Matched against any path segment or the
# basename, so nesting does not defeat them.
DEFAULT_PATTERNS: tuple[str, ...] = (
    ".env",
    ".env.*",
    "*.pem",
    "*.key",
    "id_rsa",
    "id_rsa.*",
    "id_ed25519",
    "id_ed25519.*",
    ".ssh",
    ".aws",
    "*.p12",
    "*.pfx",
    "credentials",
    "secrets.*",
    ".netrc",
    ".npmrc",
    ".pypirc",
)

OWNER = "owner"
AGENT = "agent"

# An agent working for someone else. It sees only the paths that person was
# actually shared, which is the opposite default from your own agent: yours
# starts with everything except secrets, theirs starts with nothing.
GUEST = "guest"


def _rules_file(repo: Path) -> Path:
    return paths.store_for(repo).parent / "private.json"


def added_patterns(repo: Path) -> list[str]:
    f = _rules_file(repo)
    if not f.exists():
        return []
    try:
        return list(json.loads(f.read_text(encoding="utf-8")))
    except (ValueError, OSError):
        return []


def patterns(repo: Path) -> list[str]:
    return list(DEFAULT_PATTERNS) + added_patterns(repo)


def add(repo: Path, path: str) -> list[str]:
    """Mark one more path private. Returns the full added list."""
    current = added_patterns(repo)
    entry = _normalise(repo, path)
    if entry not in current:
        current.append(entry)
        _rules_file(repo).write_text(json.dumps(current, indent=2), encoding="utf-8")
    return current


def _normalise(repo: Path, path: str) -> str:
    p = Path(path)
    try:
        if p.is_absolute():
            return p.resolve().relative_to(Path(repo).resolve()).as_posix()
    except ValueError:
        return p.as_posix()
    out = p.as_posix()
    while out.startswith("./"):
        out = out[2:]
    return out


def is_private(repo: Path, path: str | Path) -> bool:
    """True if this path must never reach an agent."""
    if not path:
        return False
    rel = _normalise(repo, str(path))
    segments = [s for s in rel.split("/") if s and s != "."]
    for pattern in patterns(repo):
        pat = pattern.rstrip("/")
        if fnmatch.fnmatch(rel, pat) or fnmatch.fnmatch(rel, f"{pat}/*"):
            return True
        if any(fnmatch.fnmatch(seg, pat) for seg in segments):
            return True
        # A directory rule covers everything beneath it.
        if pat in segments:
            return True
    return False


def visible(
    repo: Path,
    records: list[dict],
    identity: str,
    allowed: list[str] | None = None,
) -> list[dict]:
    """Drop what this identity may not see.

    The drop is total and silent: the caller is given no count and no
    placeholder, because either would confirm the content exists.

    `allowed` is the list of folders a guest was shared. It is ignored for
    anyone else, and an empty list means a guest sees nothing at all.
    """
    if identity == OWNER:
        return records
    kept = [r for r in records if not is_private(repo, r.get("path") or "")]
    if identity != GUEST:
        return kept
    folders = [f.strip("./") for f in (allowed or [])]
    return [r for r in kept if _under_any(str(r.get("path") or ""), folders)]


def _under_any(path: str, folders: list[str]) -> bool:
    if not path or not folders:
        return False
    path = path.replace("\\", "/").strip("./")
    return any(path == f or path.startswith(f.rstrip("/") + "/") for f in folders)
