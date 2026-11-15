"""Secrets are private on a fresh index, without being asked.

A private path stays searchable by the person at the keyboard. Agents never
see it, and never see that it exists: no counts, no redactions, no "hidden"
notices. Absence is the only signal.
"""

from __future__ import annotations

import fnmatch
import re
import time
import json
from pathlib import Path
from typing import Any

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
    # Key material knos itself makes, or that a wallet leaves behind. These
    # are already in this repository's .gitignore; a path a project refuses
    # to commit is not one an agent should be handed either.
    "*.keystore",
    "keystore",
    ".knos-keys",
)

OWNER = "owner"
AGENT = "agent"



def _rules_file(repo: Path) -> Path:
    return paths.work_root(repo) / "private.json"


def added_patterns(repo: Path) -> list[str]:
    f = _rules_file(repo)
    if not f.exists():
        return []
    try:
        return list(json.loads(f.read_text(encoding="utf-8")))
    except (ValueError, OSError):
        return []


# One entry per repo: the patterns, and how the rules file looked when they
# were read. Reading a repo asks whether a path is private once per file in
# every commit — 93,703 times on the kernel — and each of those was opening
# the rules file, hashing the repo path and creating a directory to find it.
# That was 305 of the 317 seconds it took to read that repo.
_CACHE: dict[str, tuple[float, int, list[str]]] = {}


def _stamp(f: Path) -> tuple[float, int]:
    try:
        st = f.stat()
        return (st.st_mtime, st.st_size)
    except OSError:
        return (0.0, -1)


def patterns(repo: Path) -> list[str]:
    """Every pattern in force for this repo, defaults first.

    Cached against the rules file's mtime and size, so `knos private` takes
    effect on the very next call without anyone having to clear anything.
    """
    key = str(repo)
    f = _rules_file(repo)
    stamp = _stamp(f)
    hit = _CACHE.get(key)
    if hit is not None and (hit[0], hit[1]) == stamp:
        return hit[2]
    found = list(DEFAULT_PATTERNS) + added_patterns(repo)
    _CACHE[key] = (stamp[0], stamp[1], found)
    return found


def add(repo: Path, path: str) -> list[str]:
    """Mark one more path private. Returns the full added list."""
    current = added_patterns(repo)
    entry = _normalise(repo, path)
    if entry not in current:
        current.append(entry)
        _rules_file(repo).write_text(json.dumps(current, indent=2), encoding="utf-8")
        _MATCHERS.pop(str(repo), None)
        _CACHE.pop(str(repo), None)
        _CHECKED.pop(str(repo), None)
    return current


def _normalise(repo: Path, path: str) -> str:
    # The common case by a mile: a repo-relative path git already gave us in
    # posix form. Everything below builds Path objects, and on a large repo
    # that was hundreds of thousands of them.
    if "\\" not in path and ":" not in path and not path.startswith("/"):
        out = path
        while out.startswith("./"):
            out = out[2:]
        return out
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


# The patterns compiled into two regexes: one for the whole path, one for a
# single segment. Reading the kernel asks this about 93,703 paths, and doing
# it a pattern at a time meant ten million fnmatch calls. Compiled once per
# repo, it is one match per path against each.
_MATCHERS: dict[str, tuple[float, int, Any, Any]] = {}


# How often the rules file is checked for changes. Reading a repo asks about
# a private path once per file, and stat-ing the rules file each time was
# 93,805 syscalls and ten seconds on the kernel. A second is far below what
# anyone can notice and turns that into a handful of calls.
_RECHECK_SECONDS = 1.0
_CHECKED: dict[str, float] = {}


def _matchers(repo: Path) -> tuple[Any, Any]:
    key = str(repo)
    hit = _MATCHERS.get(key)
    if hit is not None:
        now = time.monotonic()
        if now - _CHECKED.get(key, 0.0) < _RECHECK_SECONDS:
            return hit[2], hit[3]
        _CHECKED[key] = now
        if (hit[0], hit[1]) == _stamp(_rules_file(repo)):
            return hit[2], hit[3]
    stamp = _stamp(_rules_file(repo))
    _CHECKED[key] = time.monotonic()

    whole: list[str] = []
    segment: list[str] = []
    for pattern in patterns(repo):
        pat = pattern.rstrip("/").lower()
        whole.append(fnmatch.translate(pat))
        # A directory rule covers everything beneath it.
        whole.append(fnmatch.translate(f"{pat}/*"))
        segment.append(fnmatch.translate(pat))
    made = (
        re.compile("|".join(whole)) if whole else None,
        re.compile("|".join(segment)) if segment else None,
    )
    _MATCHERS[key] = (stamp[0], stamp[1], made[0], made[1])
    return made


def is_private(repo: Path, path: str | Path) -> bool:
    """True if this path must never reach an agent.

    Case-insensitive everywhere: a secret in `.ENV` is a secret.
    """
    if not path:
        return False
    rel = _normalise(repo, str(path)).lower()
    whole, segment = _matchers(repo)
    if whole is not None and whole.match(rel):
        return True
    if segment is None:
        return False
    return any(
        segment.match(seg) for seg in rel.split("/") if seg and seg != "."
    )


def visible(
    repo: Path,
    records: list[dict],
    identity: str,
) -> list[dict]:
    """Drop what this identity may not see.

    The drop is total and silent: the caller is given no count and no
    placeholder, because either would confirm the content exists.
    """
    if identity == OWNER:
        return records
    # A path rule cannot see a secret that lives in words: a key pasted into a chat turns up in a session fact
    # or a commit message with no private path at all. Such a record is dropped for agents the same silent way.
    return [r for r in records if not is_private(repo, r.get("path") or "") and not _quotes_a_secret(r)]


_SECRET_TEXT: Any = None


def _quotes_a_secret(record: dict) -> bool:
    """Whether a record's own words carry a key, a token or a private key block."""
    global _SECRET_TEXT
    if _SECRET_TEXT is None:
        # well-known credential shapes; compiled once, no socket involved
        _SECRET_TEXT = re.compile("|".join(f"(?:{p})" for _, p in SECRET_PATTERNS))
    text = " ".join(str(record.get(k) or "") for k in ("text", "note", "evaluated"))
    return bool(text) and _SECRET_TEXT.search(text) is not None


SECRET_PATTERNS = (
    ('private-key', r'-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP |ENCRYPTED )?PRIVATE KEY-----'),
    ('aws-access-key', r'\b(?:AKIA|ASIA)[0-9A-Z]{16}\b'),
    ('github-token', r'\bgh[pousr]_[A-Za-z0-9]{36,}\b'),
    ('anthropic-key', r'\bsk-ant-api\d{2}-[A-Za-z0-9_\-]{20,}'),
    ('openai-key', r'\bsk-(?:proj-)?[A-Za-z0-9_\-]{32,}'),
    ('slack-token', r'\bxox[baprs]-[A-Za-z0-9-]{10,}'),
    ('stripe-live-key', r'\b(?:sk|rk)_live_[A-Za-z0-9]{20,}'),
    ('google-api-key', r'\bAIza[0-9A-Za-z_\-]{35}\b'),
)

