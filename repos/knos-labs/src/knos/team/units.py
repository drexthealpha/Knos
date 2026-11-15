"""What a claim names on chain: a salted hash of a unit, never the unit itself.

A unit is one repo-relative path spelled the same on every OS: POSIX slashes, Unicode NFC, then casefolded. So
`Src\\A.py` on NTFS and `src/a.py` on ext4 are one unit (two real files that differ only in case then share a unit,
which only ever causes an extra conflict). A directory claim is written with a trailing `/`. Units beyond code carry a
scheme: `task:invoice-4411`, `market:ETH`, `wallet:<address>`.

    unit_hash = sha256(team_salt || repo_id || unit)
    ancestors = first 8 bytes of the salted hash of every ancestor directory prefix, root to parent

Two units overlap if they are equal, or if one's first 8 hash bytes appear in the other's ancestors. Truncation can
only make extra overlaps, which are safe.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata

_SCHEME = re.compile(r"^([A-Za-z][A-Za-z0-9+.-]+):(?![\\/])")

FILE = 0
DIR = 1

# Agent hosts, by a public one-byte code carried (masked with the team salt) in the last byte of the holder hash, so
# team members can say "alice/codex" while outsiders see only random bytes.
HOSTS = ["other", "claude-code", "codex", "cursor", "opencode", "copilot", "sdk", "cli", "gemini", "langgraph",
         "hermes", "eliza", "cloud"]


def unit(path: str, directory: bool = False) -> str:
    """The canonical unit for a repo-relative path (or a `scheme:` unit), as described above."""
    raw = str(path).strip()
    m = _SCHEME.match(raw)
    if m and m.group(1).lower() != "file":  # task:…, market:…, wallet:…
        return unicodedata.normalize("NFC", raw).casefold()
    p = (raw[m.end():] if m else raw).replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    p = p.lstrip("/")
    while "//" in p:
        p = p.replace("//", "/")
    if p.endswith("/**"):
        p, directory = p[:-2], True
    elif p.endswith("/"):
        directory = True
    p = p.rstrip("/")
    if not p:
        return ""
    return unicodedata.normalize("NFC", p + ("/" if directory else "")).casefold()


def _h(salt: bytes, repo_id: bytes, text: str) -> bytes:
    return hashlib.sha256(salt + repo_id + text.encode("utf-8")).digest()


def unit_hash(salt: bytes, repo_id: bytes, u: str) -> bytes:
    return _h(salt, repo_id, u)


def ancestors(salt: bytes, repo_id: bytes, u: str) -> bytes:
    """8 bytes per ancestor directory prefix (`a/`, `a/b/`, …), root to parent. Scheme units have none."""
    if _SCHEME.match(u):
        return b""
    parts = u.rstrip("/").split("/")[:-1]
    out, prefix = b"", ""
    for part in parts:
        prefix += part + "/"
        out += _h(salt, repo_id, prefix)[:8]
    return out


def ancestor_units(u: str) -> list[str]:
    """The directory units above `u`, root first: `a/`, `a/b/` for `a/b/c.py`. A claim on any of them covers `u`."""
    if _SCHEME.match(u):
        return []
    parts = u.rstrip("/").split("/")[:-1]
    out, prefix = [], ""
    for part in parts:
        prefix += part + "/"
        out.append(prefix)
    return out


def overlaps(a_hash: bytes, a_ancestors: bytes, b_hash: bytes, b_ancestors: bytes) -> bool:
    if a_hash == b_hash:
        return True
    a8, b8 = a_hash[:8], b_hash[:8]
    return any(b_ancestors[i:i + 8] == a8 for i in range(0, len(b_ancestors), 8)) or \
        any(a_ancestors[i:i + 8] == b8 for i in range(0, len(a_ancestors), 8))


def holder_hash(salt: bytes, signer: bytes, host: str, machine: str, session: str = "") -> bytes:
    """Who holds a claim: person (signer key), agent host, machine and session, salted. Two agents of one person are
    different holders. The last byte carries the host code, masked so only salt holders can read it."""
    body = hashlib.sha256(salt + b"knos.holder" + signer + host.encode() + b"\0" + machine.encode() + b"\0"
                          + session.encode()).digest()[:31]
    code = HOSTS.index(host) if host in HOSTS else 0
    return body + bytes([code ^ _mask(salt, body)])


def holder_host(salt: bytes, holder: bytes) -> str:
    if len(holder) != 32:
        return "other"
    code = holder[31] ^ _mask(salt, holder[:31])
    return HOSTS[code] if code < len(HOSTS) else "other"


def _mask(salt: bytes, body: bytes) -> int:
    return hashlib.sha256(salt + b"knos.host" + body).digest()[0]
