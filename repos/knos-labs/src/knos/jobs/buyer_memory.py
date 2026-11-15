"""A buyer's memory across jobs: one Sibyl tenant per wallet, on the buyer's own machine.

What a buyer says once ("never use exclamation marks", "sign off with — Ada", "JSON keys in camelCase") is captured
as a `preference` entity and offered to the next worker. It leaves the machine only when the buyer consents for that
job (`knos jobs post --share-memory`): the preferences are written into that job's brief, which anyone who reads the
relay can see, and the CLI says so before posting. Nothing about the buyer is ever on chain.

Sibyl is the store when its client is installed; otherwise a JSON file (the null store) keeps the same behaviour, so
memory never becomes a hard dependency of hiring someone.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from pathlib import Path

from .. import paths

# Phrases that state a standing preference (as opposed to a one-off instruction).
_CUES = re.compile(r"\b(always|never|don't|do not|please use|i prefer|i'd prefer|i like|i want|i hate|i need|avoid|"
                   r"make sure|keep it|must|only|from now on|every time|whenever|sign (?:it )?off|camel ?case|"
                   r"snake_case|british|american spelling|no emojis?|no \w+(?: \w+)? (?:in|ever)|ever)\b", re.I)
_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")


def capture(text: str) -> list[str]:
    """The sentences of a brief or a rejection reason that state a standing preference."""
    out = []
    for s in _SPLIT.split(text or ""):
        s = s.strip()
        if 3 <= len(s) <= 240 and _CUES.search(s):
            out.append(s)
    return out


def tenant_for(wallet: str) -> str:
    return str(uuid.UUID(bytes=hashlib.sha256(b"knos.buyer." + wallet.encode()).digest()[:16]))


def _dir() -> Path:
    d = paths.home() / "jobs" / "memory"
    d.mkdir(parents=True, exist_ok=True)
    return d


class BuyerMemory:
    def __init__(self, wallet: str, root: Path | None = None, use_sibyl: bool = True):
        self.wallet = wallet
        self.root = Path(root) if root else _dir()
        self.client = None
        if use_sibyl:
            try:
                from sibyl_memory_client import MemoryClient, Storage
                self.client = MemoryClient(Storage(str(self.root / f"{tenant_for(wallet)}.db")),
                                           tenant_id=tenant_for(wallet))
            except Exception:  # noqa: BLE001 - no Sibyl, or a store we cannot open: the null store
                self.client = None
        self._file = self.root / f"{tenant_for(wallet)}.json"

    # -- the null store ------------------------------------------------------------------------------------------------
    def _load(self) -> list[str]:
        try:
            return json.loads(self._file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []

    def _save(self, prefs: list[str]) -> None:
        self._file.write_text(json.dumps(prefs, indent=1), encoding="utf-8")

    # -- the interface ---------------------------------------------------------------------------------------------------
    def remember(self, preference: str) -> bool:
        p = preference.strip()
        if not p or p in self.preferences():
            return False
        if self.client is not None:
            try:
                self.client.set_entity("preference", hashlib.sha256(p.encode()).hexdigest()[:16],
                                       {"text": p, "wallet": self.wallet}, status="active")
                return True
            except Exception:  # noqa: BLE001 - Sibyl refused (cap, tier): keep it in the null store instead
                pass
        self._save(self._load() + [p])
        return True

    def learn_from(self, text: str) -> list[str]:
        return [p for p in capture(text) if self.remember(p)]

    def preferences(self) -> list[str]:
        got: list[str] = []
        if self.client is not None:
            try:
                for e in self.client.list_entities("preference", status="active", limit=200):
                    body = e.get("body") or {}
                    if isinstance(body, str):
                        body = json.loads(body)
                    if body.get("text"):
                        got.append(body["text"])
            except Exception:  # noqa: BLE001
                pass
        return got + [p for p in self._load() if p not in got]

    def forget(self, preference: str) -> bool:
        before = self._load()
        self._save([p for p in before if p != preference])
        hit = len(before) != len(self._load())
        if self.client is not None:
            try:
                self.client.archive_entity("preference", hashlib.sha256(preference.encode()).hexdigest()[:16])
                hit = True
            except Exception:  # noqa: BLE001
                pass
        return hit
