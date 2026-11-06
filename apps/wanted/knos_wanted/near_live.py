"""One live NEAR testnet job for any visitor of /near/: the hosted app posts a job from its own capped account
(live.knos-swarm-1105.testnet, test tokens only), both agents take it and submit with their function-call keys, and the
checker's own key (kid checker-live, set by 2 owners, removable by them) releases the bid to the agent that passed.

Caps: KNOS_NEAR_LIVE=on or nothing runs (the kill switch); one run at a time; KNOS_NEAR_LIVE_DAILY runs a UTC day
(default 20); a bid of 1000 test units; the account's token balance. Past a cap the page shows the last run, labelled
a replay. Keys: KNOS_NEAR_KEYS_FILE and KNOS_CHECKER_PEM_FILE, secret files on the host; none is ever sent or printed.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
import uuid
from pathlib import Path

ROOT = Path(os.environ.get("KNOS_NEAR_ROOT") or Path(__file__).resolve().parents[3])   # /app in the image
NEAR_WEB = ROOT / "near" / "web"
BID = 1000
_lock = threading.Lock()
_runs: dict[str, dict] = {}
_day = {"day": "", "n": 0}


def _jobs():
    if str(NEAR_WEB) not in sys.path:
        sys.path.insert(0, str(NEAR_WEB))
    import jobs_api   # near/web/jobs_api.py: the same code the maintainer's machine runs
    return jobs_api


def latest() -> dict:
    try:
        return json.loads((NEAR_WEB / "latest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def daily_cap() -> int:
    try:
        return max(0, int(os.environ.get("KNOS_NEAR_LIVE_DAILY") or 20))
    except ValueError:
        return 20


def status() -> dict:
    today = time.strftime("%Y-%m-%d", time.gmtime())
    used = _day["n"] if _day["day"] == today else 0
    on = os.environ.get("KNOS_NEAR_LIVE") == "on" and bool(os.environ.get("KNOS_NEAR_KEYS_FILE"))
    busy = any(r["state"] == "running" for r in _runs.values())
    return {"live": on, "used_today": used, "cap_today": daily_cap(), "busy": busy, "bid": BID, "network": "testnet",
            "account": os.environ.get("KNOS_NEAR_PAYER", ""), "money": "test tokens, not real money"}


def start() -> dict:
    """A run id to poll, or a replay of the last run with the reason no live run starts."""
    s = status()
    why = ("live runs are switched off" if not s["live"] else "a run is in progress; this one is a replay" if s["busy"]
           else f"today's {s['cap_today']} live runs are used; this one is a replay" if s["used_today"] >= s["cap_today"] else "")
    if not why:
        try:
            j = _jobs()
            if j.ft_balance(j.CONFIG["payer"]) < BID:
                why = "the live account's test tokens are spent; this one is a replay"
        except Exception as e:  # noqa: BLE001 - testnet unreachable: say so and replay
            why = f"testnet did not answer ({str(e)[:80]}); this one is a replay"
    if why:
        return {"replay": True, "why": why, "last": latest(), **s}
    with _lock:
        today = time.strftime("%Y-%m-%d", time.gmtime())
        if _day["day"] != today:
            _day.update(day=today, n=0)
        _day["n"] += 1
        rid = uuid.uuid4().hex[:12]
        _runs[rid] = {"state": "running", "step": "posting the job", "started": time.time()}
    threading.Thread(target=_run, args=(rid,), daemon=True).start()
    return {"replay": False, "run": rid, **status()}


def _run(rid: str) -> None:
    r = _runs[rid]
    try:
        j = _jobs()
        p = j.post({"bid": BID, "minutes": 10})
        r.update(step="agents take the job and submit; the checker runs the locked test", job_id=p.get("id"), post=p.get("url"))
        if not p.get("ok"):
            raise RuntimeError(p.get("said") or p.get("why") or "the job was not posted")
        out = j.run({"id": p["id"]})
        r.update(state="done" if out.get("ok") else "failed", step="paid" if out.get("ok") else "stopped", job=out.get("job"),
                 paid=out.get("paid"), check_to_paid_s=out.get("check_to_paid_s"), seconds=round(time.time() - r["started"], 1))
    except Exception as e:  # noqa: BLE001 - the page shows why the run stopped
        r.update(state="failed", step="stopped", why=str(e)[:300], seconds=round(time.time() - r["started"], 1))
    for k in [k for k, v in _runs.items() if time.time() - v["started"] > 3600]:
        _runs.pop(k, None)


def get(rid: str) -> dict | None:
    r = _runs.get(rid)
    return None if r is None else {k: v for k, v in r.items() if k != "started"} | {"seconds_so_far": round(time.time() - r["started"], 1)}
