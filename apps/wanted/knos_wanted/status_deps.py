"""What each part Knos depends on is doing now, read live (cached 60 s so a page view asks each part at most once a minute),
and what Knos does when that part is down. GET /api/status carries it as `deps`; /start/ and /status/ show it."""
from __future__ import annotations

import json
import threading
import time
import urllib.request

_lock = threading.Lock()
_cache: dict = {"at": 0.0, "deps": None}
TTL_S = 60
DOWN = {"qloo": "the card shows the last recorded answer with its date, and a new check is queued until Qloo answers",
        "solana_devnet": "nothing is held or paid; the brief and the check still work",
        "sibyl": "checks still run; the record line is written when Sibyl is back",
        "iris_referee": "the rules referee on this server checks a lab's proof with the same code",
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
    try:
        from . import qloo_status
        q = qloo_status.doc()
        out["qloo"] = {"state": "limited" if q.get("limited") else "answering", "said": q.get("line") or "Qloo is answering."}
    except Exception as why:  # noqa: BLE001
        out["qloo"] = {"state": "unknown", "said": type(why).__name__}
    ok, said = _get("https://api.devnet.solana.com", json.dumps({"jsonrpc": "2.0", "id": 1, "method": "getSlot"}).encode())
    out["solana_devnet"] = {"state": "up" if ok else "down", "said": said}
    try:
        from knos.record import journal

        from . import company
        h = journal.head(company.root())
        out["sibyl"] = {"state": "up", "said": f"record line {h.get('seq')}" if h else "the record is empty here"}
    except Exception as why:  # noqa: BLE001
        out["sibyl"] = {"state": "down", "said": type(why).__name__}
    try:
        from knos import referee_rules
        out["iris_referee"] = {"state": "up", "said": f"{referee_rules.MODEL} on this server; IRIS runs it inside a lab's own walls"}
    except Exception as why:  # noqa: BLE001
        out["iris_referee"] = {"state": "down", "said": type(why).__name__}
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
