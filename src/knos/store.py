"""Where Knos remembers: Sibyl's memory engine (sibyl-memory-client), and nothing else. There is no second store, no
cache and no fallback file; take Sibyl away and Knos remembers nothing (tests/test_sibyl_is_load_bearing.py).

Two stores, both Sibyl's:

    for a repo on this machine (the Stop hook)   one tenant per repo in Sibyl's own shared store
                                                 (`$SIBYL_MEMORY_DB`, else ~/.sibyl-memory/memory.db), behind Sibyl's
                                                 own cap gate. Knos does not patch or route around Sibyl's free-tier
                                                 cap; a Sibyl account on this machine (`sibyl init`) lifts it.
    for the judge in GitHub Actions              Sibyl's local store <dir>/sibyl.db, for the run. Between runs its
                                                 lessons travel as comments in the repository's `knos-memory` issue
                                                 (knos.proof.memory), and are loaded back into this store: no
                                                 secret, and nothing decides from the comments themselves.

Three of Sibyl's tiers carry weight (knos.proof.history): entities (WARM) hold the proof rules and lessons; the journal
(COLD, append-only) holds every verdict of the Stop hook, so a check refused in one session is owed in the next; one
state document (HOT) holds the running count of claims and refusals. Sibyl's FTS5 search finds a past refusal by its
words. Reference and archive are not used.

The judge's store also holds how each past order in a repository ended, by terms template and policy version (entities
of category `order`: knos.proof.history.order_outcome), so a funding reply can say which published template
(docs/TERMS.md) that history supports. No memory, no such line.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import time
from pathlib import Path


def shared_store() -> Path:
    override = os.environ.get("SIBYL_MEMORY_DB")
    p = Path(override).expanduser() if override else Path.home() / ".sibyl-memory" / "memory.db"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _root(repo: Path) -> Path:
    """The main checkout of `repo`: every worktree shares one `.git`, so they share one memory."""
    repo = Path(repo).resolve()
    try:
        got = subprocess.run(["git", "-C", str(repo), "rev-parse", "--git-common-dir"], capture_output=True, text=True,
                             timeout=10)
    except (OSError, subprocess.SubprocessError):
        return repo
    if got.returncode != 0:
        return repo
    common = Path(got.stdout.strip())
    if not common.is_absolute():
        common = repo / common
    try:
        main = common.resolve().parent
    except OSError:
        return repo
    return main if main.is_dir() else repo


def tenant(repo: Path) -> str:
    real = str(_root(repo).resolve()).lower()
    return f"knos-{Path(real).name}-{hashlib.sha256(real.encode()).hexdigest()[:10]}"


def account() -> dict[str, str]:
    """The Sibyl account on this machine, if its owner activated one: handed only to Sibyl's own cap gate."""
    path = Path(os.environ.get("SIBYL_CREDENTIALS") or Path.home() / ".sibyl-memory" / "credentials.json")
    try:
        got = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(got, dict) or not got.get("account_id") or not got.get("session_token"):
        return {}
    return {"account_id": str(got["account_id"]), "session_token": str(got["session_token"])}


def for_repo(repo: Path):
    """(MemoryClient, Storage) for this repo's tenant in Sibyl's shared store, under Sibyl's cap gate."""
    from sibyl_memory_client import CapGate, MemoryClient, Storage
    from sibyl_memory_client._capcheck import aggregate_db_size

    db = shared_store()
    storage = None
    for attempt in range(8):    # the first connection switches the store to WAL and needs it briefly to itself
        try:
            storage = Storage(str(db))
            break
        except sqlite3.OperationalError:
            if attempt == 7:
                raise
            time.sleep(0.05 * (attempt + 1))
    acct = account()
    gate = CapGate(account_id=acct.get("account_id"), session_token=acct.get("session_token"),
                   db_size_fn=lambda: aggregate_db_size(storage.db_path))
    return MemoryClient(storage, tenant_id=tenant(repo), cap_gate=gate), storage


def local(root: Path, tenant_id: str = "knos-judge"):
    """Sibyl's local store at <root>/sibyl.db."""
    from sibyl_memory_client import MemoryClient
    Path(root).mkdir(parents=True, exist_ok=True)
    return MemoryClient.local(str(Path(root) / "sibyl.db"), tenant_id=tenant_id)
