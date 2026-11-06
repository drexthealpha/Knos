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
    ready = bool(_ready.get("job"))
    if on and not ready and not _preparing.locked() and used < daily_cap():   # keep one job ready for the next click
        threading.Thread(target=prepare, daemon=True).start()
    return {"live": on, "used_today": used, "cap_today": daily_cap(), "busy": busy, "ready": ready, "bid": BID, "network": "testnet",
            "account": os.environ.get("KNOS_NEAR_PAYER", ""), "money": "test tokens, not real money"}


def start() -> dict:
    """A run id to poll, or a replay of the last run with the reason no live run starts."""
    s = status()
    why = ("live runs are switched off" if not s["live"] else "a run is in progress; this one is a replay" if s["busy"]
           else f"today's {s['cap_today']} live runs are used; this one is a replay" if s["used_today"] >= s["cap_today"] else "")
    if not why and not _ready.get("job"):   # a ready job is funded already: no balance to ask for
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
        ready = _ready.pop("job", None) if _ready.get("job") and time.time() - _ready["job"]["at"] < READY_FOR else None
    if ready:   # a job both agents have already tried: the visitor's click sends only the payment
        out = _release(ready)
        threading.Thread(target=prepare, daemon=True).start()
        return {"replay": False, **out, **status()}
    with _lock:
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


READY_FOR = 3 * 3600      # a ready job is posted with a 4 h deadline and offered for 3 h of it
_ready: dict = {}
_preparing = threading.Lock()


def prepare() -> None:
    """Post a job and have both agents take it and submit, and run the locked test on each output, but pay nobody yet:
    the job then waits, ready, for a visitor's click (start). One at a time."""
    if not _preparing.acquire(blocking=False):
        return
    try:
        if _ready.get("job") or not status()["live"]:
            return
        j = _jobs()
        p = j.post({"bid": BID, "minutes": 240})
        if not p.get("ok"):
            return
        ra = j.run_agent("a", j.pass_agent.SOLUTION, p["id"])
        rb = j.run_agent("b", j.fail_agent.SOLUTION, p["id"])
        c = j.checker.check(p["id"], release=False)
        win = next((x for x in c["attempts"] if x.get("passed")), None)
        if not win:
            return
        _ready["job"] = {"id": p["id"], "at": time.time(), "criteria_hash": c["criteria_hash"], "payee": win["agent"],
                         "output_sha256": win["output_sha256"],
                         "attempts": [{"agent": x["agent"], "passed": x["passed"], "reason": x.get("reason", "")} for x in c["attempts"]],
                         "txs": {"post": p.get("tx"), "take_a": ra["take"]["tx"], "submit_a": ra["submit"]["tx"],
                                 "take_b": rb["take"]["tx"], "submit_b": rb["submit"]["tx"]}}
        if os.environ.get("KNOS_NEAR_KEYS_FILE"):
            import common   # near/agents/common.py, on the path once jobs_api is loaded
            common.prefetch(j.CONFIG["relayer"])   # the click then only signs and sends the payment
    except Exception:  # noqa: BLE001 - no ready job: the next click runs the whole job instead
        pass
    finally:
        _preparing.release()


def _release(ready: dict) -> dict:
    j, t0 = _jobs(), time.time()
    try:
        r = j.checker.release_one(ready["id"], ready["payee"], ready["output_sha256"], ready["criteria_hash"])
    except RuntimeError as e:   # a nonce fetched earlier went stale: fetch afresh and send once more
        if "nonce" not in str(e).lower():
            raise
        r = j.checker.release_one(ready["id"], ready["payee"], ready["output_sha256"], ready["criteria_hash"])
    agents = [x["agent"] for x in ready["attempts"]]
    paid = {a: (BID if a == ready["payee"] and r.get("ok") else 0) for a in agents}
    job = {"id": ready["id"], "bid": BID, "txs": {**ready["txs"], **({"release": r["tx"]} if r.get("ok") else {})},
           "paid": paid, "check_to_paid_s": round(time.time() - t0, 1), "attempts": ready["attempts"], "ok": bool(r.get("ok"))}
    return {"state": "done" if r.get("ok") else "failed", "step": "paid" if r.get("ok") else "stopped", "job": job, "paid": paid,
            "seconds": round(time.time() - t0, 1), "why": "" if r.get("ok") else r.get("said", ""), "release_url": r.get("url")}


def get(rid: str) -> dict | None:
    r = _runs.get(rid)
    return None if r is None else {k: v for k, v in r.items() if k != "started"} | {"seconds_so_far": round(time.time() - r["started"], 1)}
