"""Why people stay or leave, first-party only (Round 8, T8). Each page sends small events with a random visit id that
its browser makes and resets every day; nothing else identifies anyone: no cookie, no IP address and no account is
stored, and a browser that sends Do Not Track sends nothing at all (the page checks before it sends).

Events: view, press (and how long its answer took), result, proof (a proof ran to its end), backed (test money put
behind a claim), download, share, rage (three presses within a second on one spot), slow (a press with no visible answer
within 400 ms), error (an error shown), notwhat ("Not what I need", with an optional word), leave (the last screen and
the seconds on it). A visit says whether its browser came before (`back`), never who it is.

The funnel (visits, first press, first result, proof finished, backed, came back) and the screen people leave from most
are kept per day in memory and in a ledger file a scheduled job saves (visits.json on the gh-pages branch); /status
shows them, 0 until real visits exist."""
from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.request
from collections import Counter
from pathlib import Path

EVENTS = {"view", "press", "result", "proof", "backed", "download", "share", "rage", "slow", "error", "notwhat", "leave"}
LEDGER = Path(os.environ.get("KNOS_VISITS_LEDGER") or (Path(os.environ.get("TMPDIR") or "/tmp") / "knos-visits.json"))
SAVED = os.environ.get("KNOS_VISITS_SAVED", "https://raw.githubusercontent.com/drexthealpha/Knos/gh-pages/visits.json")
_lock = threading.Lock()
_days: dict = {}          # "YYYY-MM-DD" -> {"visits": set, "press": set, ...; "leave": Counter, "words": Counter, "slow": int, ...}
_seeded = [False]


def _today() -> str:
    return time.strftime("%Y-%m-%d", time.gmtime())


def _day(d: str) -> dict:
    return _days.setdefault(d, {k: set() for k in ("visits", "press", "result", "proof", "backed", "back")} | {"leave": Counter(), "counts": Counter(), "notwhat": Counter()})


def _seed() -> None:
    if _seeded[0] or os.environ.get("KNOS_VISITS_OFF"):
        return
    _seeded[0] = True
    try:
        with urllib.request.urlopen(urllib.request.Request(SAVED, headers={"User-Agent": "knos-visits"}), timeout=10) as r:
            saved = json.loads(r.read())
        with _lock:
            for d, s in (saved.get("days") or {}).items():
                if d not in _days:
                    _days[d] = {"saved": s}
    except Exception:  # noqa: BLE001 - none saved yet
        pass


def record(ev: dict) -> bool:
    """One event from a page; False when it is not one this module keeps."""
    vid, kind = str(ev.get("v") or ""), str(ev.get("e") or "")
    if not re.fullmatch(r"[0-9a-f]{16}", vid) or kind not in EVENTS:
        return False
    page = re.sub(r"[^a-z0-9/_-]", "", str(ev.get("p") or "")[:40].lower()) or "/"
    with _lock:
        d = _day(_today())
        d["visits"].add(vid)
        if ev.get("back"):
            d["back"].add(vid)
        d["counts"][kind] += 1
        if kind in ("press", "result", "proof", "backed"):
            d[kind].add(vid)
        if kind == "leave":
            d["leave"][page] += 1
        if kind == "notwhat" and ev.get("why"):
            d["notwhat"][re.sub(r"[^a-z ]", "", str(ev["why"]).lower())[:30]] += 1
    return True


def _plain(d: dict) -> dict:
    if "saved" in d:
        return d["saved"]
    return {"visits": len(d["visits"]), "first_press": len(d["press"]), "first_result": len(d["result"]), "proof_finished": len(d["proof"]),
            "backed": len(d["backed"]), "came_back": len(d["back"]), "events": dict(d["counts"]), "leave_from": dict(d["leave"].most_common(5)),
            "not_what": dict(d["notwhat"].most_common(5))}


def summary(days: int = 7) -> dict:
    """The funnel of the last `days` days and the screen people leave from most."""
    _seed()
    with _lock:
        out = {d: _plain(v) for d, v in sorted(_days.items())[-days:]}
    tot = Counter()
    leave = Counter()
    for v in out.values():
        for k in ("visits", "first_press", "first_result", "proof_finished", "backed", "came_back"):
            tot[k] += int(v.get(k) or 0)
        leave.update(v.get("leave_from") or {})
    return {"days": out, "funnel": {k: tot[k] for k in ("visits", "first_press", "first_result", "proof_finished", "backed", "came_back")},
            "leave_most": leave.most_common(1)[0][0] if leave else None, "read_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
