"""What each part Knos depends on is doing now, read live (cached 60 s so a page view asks each part at most once a minute),
and what Knos does when that part is down. GET /api/status carries it as `deps`."""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.request

_lock = threading.Lock()
_cache: dict = {"at": 0.0, "deps": None}
TTL_S = 60
DOWN = {"open_signals": "a source that does not answer is left out of the card; with none, the check says it cannot decide",
        "solana_devnet": "nothing is held or paid; the brief and the check still work",
        "sibyl": "checks still run; the record line is written when the memory store is back",
        "rules_referee": "a lab's proof waits; nothing is released until the referee answers",
        "openalex": "a DOI is read from Crossref instead"}


def _get(url: str, data: bytes | None = None, timeout: float = 6) -> tuple[bool, str]:
    req = urllib.request.Request(url, data, {"User-Agent": "knos-status", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return 200 <= r.status < 300, f"HTTP {r.status}"
    except Exception as why:  # noqa: BLE001 - a part that does not answer is said as it is
        return False, type(why).__name__


def _read() -> dict:
    out = {}
    from . import open_signals
    out["open_signals"] = {"state": "asked with each check" if open_signals.online() else "not asked",
                           "said": "free, keyless public sources" if open_signals.online() else "the open sources are not asked on this server"}
    ok, said = _get("https://api.devnet.solana.com", json.dumps({"jsonrpc": "2.0", "id": 1, "method": "getSlot"}).encode())
    out["solana_devnet"] = {"state": "up" if ok else "down", "said": said}
    try:
        from knos.record import journal

        from . import company
        h = journal.head(company.root())               # the server's own copy of the record, said as that
        url = os.environ.get("KNOS_SIBYL_HEALTH_URL")    # Sibyl itself, asked only when its address is configured
        ok, said = _get(url) if url else (None, "")
        out["sibyl"] = {"state": ("up" if ok else "down") if url else "not asked",
                        "said": (f"{said}; " if url else "Sibyl's own address is not configured on this server; ")
                        + (f"the server's copy of the record is at line {h.get('seq')}" if h else "the server's copy of the record is empty")}
    except Exception as why:  # noqa: BLE001
        out["sibyl"] = {"state": "down", "said": type(why).__name__}
    try:
        from knos import referee_rules
        out["rules_referee"] = {"state": "up", "said": f"{referee_rules.MODEL}, the code on this server"}
    except Exception as why:  # noqa: BLE001
        out["rules_referee"] = {"state": "down", "said": type(why).__name__}
    ok, said = _get("https://api.openalex.org/works?per-page=1&select=id")
    out["openalex"] = {"state": "up" if ok else "down", "said": said}
    for k, v in out.items():
        v["when_down"] = DOWN[k]
    return out


def deps() -> dict:
    with _lock:
        if _cache["deps"] is not None and time.time() - _cache["at"] < TTL_S:
            return _cache["deps"]
    d = _read()
    with _lock:
        _cache.update({"at": time.time(), "deps": d})
    return d
